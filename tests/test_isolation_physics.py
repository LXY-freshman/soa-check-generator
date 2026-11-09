import json
from pathlib import Path
import unittest
import tempfile

from soa_generator.export import project_json, select_rules, render_spectre
from soa_generator.models import ExportSet
from soa_generator.parsers import parse_isolation_junctions
from soa_generator.schema import validate_adapter_config, validate_project_payload
from soa_generator.service import _rule_from_dict, parse_source, parse_sources, parse_text, parse_texts
from soa_generator.cli import main as cli_main


FIXTURE = Path(__file__).parent / "fixtures" / "isolation_junctions.scs"


class IsolationPhysicsTests(unittest.TestCase):
    def test_explicit_wrapper_maps_p_n_and_preserves_provenance(self):
        edges = parse_isolation_junctions(FIXTURE.read_text(), str(FIXTURE))
        outer = next(item for item in edges["nch_demo_iso"] if item["p_port"] == "sub")
        self.assertEqual(outer["n_port"], "iso")
        self.assertEqual(outer["source"]["path"], str(FIXTURE))
        self.assertGreater(outer["source"]["line"], 1)

    def test_pn_directions_generated_on_all_parse_paths(self):
        text = FIXTURE.read_text()
        source = {"kind": "local", "path": str(FIXTURE), "candidate_kind": "model_spectre"}
        for payload in (parse_source(source), parse_sources([source]), parse_text(text, str(FIXTURE)),
                        parse_texts([{"path": str(FIXTURE), "text": text, "kind": "model_spectre"}])):
            with self.subTest(summary=payload["summary"]):
                rules = [item for item in payload["rules"] if item["target"] == "nch_demo_iso" and item["limit_kind"].startswith("isolation")]
                checks = {(item["limit_kind"], tuple(item["terminal_pair"])) for item in rules}
                self.assertEqual(checks, {("isolation_bv", ("iso", "sub")), ("isolation_forward_voltage", ("sub", "iso")),
                                          ("isolation_bv", ("iso", "b")), ("isolation_forward_voltage", ("b", "iso"))})
                self.assertTrue(all(not item["enabled"] and item["maximum"] is None for item in rules))

    def test_nested_pmos_has_three_actual_junctions_not_fake_body_nbl(self):
        payload = parse_text(FIXTURE.read_text(), str(FIXTURE))
        for name, middle, ring, sub in (("pch_demo_layers", "isub", "iso", "sub"), ("pch_demo_nbl", "pepi", "nbl", "psub")):
            device = next(item for item in payload["devices"] if item["name"] == name)
            reverse = {tuple(item["terminal_pair"]) for item in device["check_matrix"] if item["limit_kind"] == "isolation_bv"}
            self.assertEqual(reverse, {("b", middle), (ring, middle), (ring, sub)})
            self.assertNotIn((ring, "b"), reverse)
            self.assertNotIn((middle, sub), reverse)
            self.assertTrue(all(item["structure_confirmed"] for item in device["check_matrix"] if item["limit_kind"].startswith("isolation")))

    def test_isolation_is_not_mos_only(self):
        payload = parse_text(FIXTURE.read_text(), str(FIXTURE))
        for name in ("var_demo_iso", "r_demo_iso", "dio_demo_iso", "npn_demo_iso", "cap_demo_iso"):
            device = next(item for item in payload["devices"] if item["name"] == name)
            kinds = {item["limit_kind"] for item in device["check_matrix"]}
            self.assertIn("isolation_bv", kinds, name)
            self.assertIn("isolation_forward_voltage", kinds, name)

    def test_no_common_forward_value_or_copy_of_outer_rating_to_inner(self):
        text = FIXTURE.read_text().replace("nch_demo_iso", "n50_iso_30v_demo")
        payload = parse_text(text, "ratings.scs")
        isolation = [item for item in payload["rules"] if item["target"] == "n50_iso_30v_demo" and item["limit_kind"].startswith("isolation")]
        for item in isolation:
            expected = "30" if item["terminal_pair"] == ["iso", "sub"] and item["limit_kind"] == "isolation_bv" else None
            self.assertEqual(item["maximum"], expected)

    def test_native_forward_reverse_are_distinct_and_values_remain_independent(self):
        text = FIXTURE.read_text() + '\nouter assert sub=nch_demo_iso expr="v(iso,sub)" max=55\ninner assert sub=nch_demo_iso expr="v(iso,b)" max=12\nfwd assert sub=nch_demo_iso expr="v(sub,iso)" max=0.6\n'
        payload = parse_text(text, "native.scs")
        device = next(item for item in payload["devices"] if item["name"] == "nch_demo_iso")
        matrix = {(item["limit_kind"], tuple(item["terminal_pair"])):item for item in device["check_matrix"]}
        self.assertEqual(matrix[("isolation_bv", ("iso", "sub"))]["maximum"], "55")
        self.assertEqual(matrix[("isolation_bv", ("iso", "b"))]["maximum"], "12")
        self.assertEqual(matrix[("isolation_forward_voltage", ("sub", "iso"))]["maximum"], "0.6")
        rules = [_rule_from_dict(item) for item in payload["rules"]]
        rendered = render_spectre(select_rules(rules, ExportSet()))
        self.assertIn('expr="v(sub,iso)" max=0.6', rendered)
        saved = json.loads(project_json(process_path="/demo", process_version="1", rules=rules, export_set=ExportSet(), devices=payload["devices"]))
        self.assertFalse(validate_project_payload(saved))
        self.assertEqual(saved["devices"], payload["devices"])

    def test_same_type_epi_substrate_and_arbitrary_drain_not_invented(self):
        payload = parse_text('subckt pch_demo (d g s b pepi nbl psub)\nends pch_demo\n', 'unknown.scs')
        pairs = {tuple(item["terminal_pair"]) for item in payload["rules"] if item["limit_kind"] == "isolation_bv"}
        self.assertEqual(pairs, {("nbl", "psub"), ("nbl", "pepi")})
        self.assertFalse(any(item["limit_kind"] == "isolation_forward_voltage" for item in payload["rules"]))

    def test_adapter_maps_custom_ports_and_can_exclude_dielectric_pn_checks(self):
        config = {"schema":"soa-adapter/v1", "id":"isolated-demo", "version":"1", "device_rules":[{
            "pattern":"^custom_", "isolation_type":"junction",
            "port_roles":{"well_pin":"isolation_well", "substrate_pin":"bulk_substrate"},
            "isolation_junctions":[{"p_port":"substrate_pin", "n_port":"well_pin", "source":{"path":"manual.pdf", "page":12}}]}]}
        self.assertFalse(validate_adapter_config(config))
        text = 'subckt custom_device (a b well_pin substrate_pin)\nends custom_device\n'
        payload = parse_text(text, 'custom.scs', adapter_config=config)
        self.assertEqual(len([rule for rule in payload["rules"] if rule["limit_kind"].startswith("isolation")]), 2)
        config['device_rules'][0]['isolation_type'] = 'dielectric'
        payload = parse_text(text, 'custom.scs', adapter_config=config)
        self.assertFalse(any(rule["limit_kind"].startswith("isolation") for rule in payload["rules"]))
        self.assertFalse(any(item["applicable"] for item in payload["devices"][0]['check_matrix'] if item['limit_kind']=='isolation_bv'))

    def test_documented_same_potential_constraint_is_visible_and_exportable(self):
        config = {"schema":"soa-adapter/v1", "id":"pmos-variant", "version":"1", "check_rules":[{
            "pattern":"^pch_demo$", "limit_kind":"isolation_constraint", "expr":"v(b,hvbn)",
            "maximum":"0", "minimum":"0", "source_path":"manual.pdf", "page":52}]}
        payload = parse_text('subckt pch_demo (d g s b hvbn psub)\nends pch_demo\n','pmos.scs',adapter_config=config)
        matrix = next(item for item in payload['devices'][0]['check_matrix'] if item['limit_kind']=='isolation_constraint')
        self.assertEqual(matrix['source']['page'],52)
        self.assertEqual(matrix['maximum'],'0')
        self.assertIn('expr="v(b,hvbn)" max=0 min=0',render_spectre(select_rules([_rule_from_dict(item) for item in payload['rules']],ExportSet())))

    def test_bad_adapter_connections_rejected(self):
        config = {"schema":"soa-adapter/v1", "id":"bad", "version":"1", "device_rules":[{
            "pattern":".*", "isolation_type":"invalid", "isolation_junctions":[{"p_port":"x", "n_port":"x"}]}]}
        codes={item['code'] for item in validate_adapter_config(config)}
        self.assertTrue({'isolation_type','isolation_junctions'} <= codes)

    def test_unexposed_substrate_is_a_coverage_gap_not_an_exportable_node(self):
        text = 'model j diode\nsubckt n50_iso_demo (d g s b nbl)\nd1 (b nbl) j\nends n50_iso_demo\n'
        payload = parse_text(text, 'hidden_substrate.scs')
        device = next(item for item in payload['devices'] if item['name']=='n50_iso_demo')
        gaps = [item for item in device['check_matrix'] if item['isolation_side']=='outer']
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]['status'], 'missing')
        self.assertFalse(gaps[0]['rule_ids'])
        self.assertFalse(any('psub' in rule['expr'].lower() for rule in payload['rules']))

    def test_selected_cross_file_diode_definition_resolves_without_stale_fallbacks(self):
        model = 'subckt pch_demo (d g s b pepi nbl psub)\nd1 (pepi b) separate_diode\nd2 (pepi nbl) separate_diode\nd3 (psub nbl) separate_diode\nends pch_demo\n'
        files = [{"path":"mis.scs", "kind":"model_spectre", "text":model},
                 {"path":"diode.scs", "kind":"model_spectre", "text":"model separate_diode diode bv=80\n"}]
        for sequence in (files, files[::-1]):
            payload = parse_texts(sequence)
            rules = [item for item in payload['rules'] if item['target']=='pch_demo' and item['limit_kind'].startswith('isolation')]
            self.assertEqual(len(rules),6)
            self.assertFalse(any(set(item['terminal_pair'])=={'b','nbl'} for item in rules))
            self.assertTrue(all(item['source']['path']=='mis.scs' for item in rules))

    def test_cli_adapter_isolation_checks_and_json_profiles(self):
        config = {"schema":"soa-adapter/v1", "id":"cli-demo", "version":"1", "device_rules":[{
            "pattern":"^nch_demo_iso$", "isolation_type":"junction",
            "isolation_junctions":[{"p_port":"sub","n_port":"iso"}]}],"check_rules":[{
            "pattern":"^nch_demo_iso$", "expr":"v(sub,iso)", "limit_kind":"isolation_forward_voltage",
            "maximum":"0.5", "source_path":"manual.pdf", "page":8}]}
        with tempfile.TemporaryDirectory() as directory:
            adapter = Path(directory)/'adapter.json'
            output = Path(directory)/'checks.scs'
            adapter.write_text(json.dumps(config))
            self.assertEqual(cli_main(['export',str(FIXTURE),str(output),'--adapter-config',str(adapter)]),0)
            self.assertIn('expr="v(sub,iso)" max=0.5',output.read_text())
            project=json.loads(output.with_suffix('.json').read_text())
            self.assertFalse(validate_project_payload(project))
            self.assertEqual(project['adapter_config']['id'],'cli-demo')
            self.assertTrue(next(item['isolation_junctions'] for item in project['devices'] if item['name']=='nch_demo_iso'))


if __name__ == '__main__':
    unittest.main()
