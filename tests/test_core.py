import tempfile
import unittest
from pathlib import Path

from soa_generator.classify import classify_device
from soa_generator.adapters import apply_adapter_config
from soa_generator.export import ExportSet, model_soa_export_metadata, project_json, render_spectre, select_rules
from soa_generator.models import Device
from soa_generator.parsers import detect_model_soa, parse_device_list, parse_model_definitions, parse_spectre_asserts
from soa_generator.schema import validate_adapter_config, validate_project_payload
from soa_generator.service import _spectre_diagnostics, parse_sources, parse_text
from soa_generator.validation import lint_rules


class ParserTests(unittest.TestCase):
    def test_spectre_sub_and_subs_rules_keep_section_and_fields(self) -> None:
        text = """simulator lang=spectre
section soa_hv
check1_n18 assert sub=n18_ckt expr=\"v(d,s)>=4&&v(g,s)<0.5\" message=\"Vds limit\" level=warning duration=t_trans_hv
chk_nch assert subs=nch_svt_1p8v expr=\"V(d,s)\" max=1.98 min=-1.98
endsection soa_hv
"""
        rules = parse_spectre_asserts(text, "soa_spe.mdl")
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0].section, "soa_hv")
        self.assertEqual(rules[0].target_kind, "sub")
        self.assertEqual(rules[0].limit_kind, "Vds")
        self.assertEqual(rules[1].target_kind, "subs")
        self.assertEqual(rules[1].maximum, "1.98")

    def test_matching_expression_min_and_max_are_one_rule(self) -> None:
        text = '''a assert sub=n50_ckt expr="v(d,b)" min=-5 message="Vbd" level=warning duration=t_trans_hv
b assert sub=n50_ckt expr="v(d,b)" max=5 message="Vbd" level=warning duration=t_trans_hv
'''
        rules = parse_spectre_asserts(text)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].minimum, "-5")
        self.assertEqual(rules[0].maximum, "5")

    def test_device_list_headers_and_variant_metadata(self) -> None:
        text = """****** LV/MV MOS *******
n50_ckt
****** Resistor ********
rhrp_lc10k_3t_ckt
****** ESD PNP ********
esd6_pnp_nbl
"""
        devices = parse_device_list(text, "devices.devicelist")
        self.assertEqual([device.name for device in devices], ["n50_ckt", "rhrp_lc10k_3t_ckt", "esd6_pnp_nbl"])
        self.assertEqual(devices[0].family, "mos")
        self.assertEqual(devices[0].family_voltage, 5.0)
        self.assertEqual(devices[1].family, "resistor")
        self.assertEqual(devices[2].family, "bjt")
        self.assertEqual(devices[2].scope, "esd_protection")

    def test_voltage_name_conventions(self) -> None:
        self.assertEqual(classify_device("n18_ckt").family_voltage, 1.8)
        self.assertEqual(classify_device("n50_ckt").family_voltage, 5.0)
        self.assertEqual(classify_device("nld12_iso_ckt").family_voltage, 12.0)
        self.assertEqual(classify_device("nch_svt_1p8v").family_voltage, 1.8)
        iso = classify_device("n50_hvbn_30v_ckt")
        self.assertEqual(iso.family_voltage, 5.0)
        self.assertEqual(iso.isolation_voltage, 30.0)
        self.assertEqual(iso.isolation_confidence, "inferred")
        self.assertEqual(classify_device("rnwaa5v_ckt").family_voltage, 5.0)
        self.assertEqual(classify_device("pnp18").family_voltage, 1.8)

    def test_combined_export_selects_devices_and_renders_section(self) -> None:
        rules = parse_spectre_asserts('check assert sub=n50_ckt expr="V(d,s)" max=5')
        export_set = ExportSet(device_names=["n50_ckt"], formats=["spectre"])
        selected = select_rules(rules, export_set)
        rendered = render_spectre(selected)
        self.assertEqual(len(selected), 1)
        self.assertIn("section soa_generated", rendered)
        self.assertIn("sub=n50_ckt", rendered)

    def test_lint_reports_missing_check(self) -> None:
        rules = parse_spectre_asserts("bad assert sub=n50_ckt message=\"x\"")
        issues = lint_rules(rules, {"n50_ckt"})
        self.assertTrue(any(issue.code == "missing_check" for issue in issues))

    def test_model_source_produces_device_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.mdl"
            path.write_text("subckt n50_hvbn_30v_ckt d g s b nbl psub\n", encoding="utf-8")
            payload = parse_sources([{
                "kind": "local",
                "path": str(path),
                "candidate_kind": "model_spectre",
            }])
            self.assertEqual(payload["summary"]["files"], 1)
            self.assertEqual(payload["devices"][0]["isolation_voltage"], 30.0)

    def test_model_ports_and_isolation_candidate(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "model_ports.scs"
        text = fixture.read_text(encoding="utf-8")
        definitions = parse_model_definitions(text)
        self.assertEqual(definitions[0][0], "n50_hvbn_30v_ckt")
        self.assertEqual(definitions[0][1][-2:], ["nbl", "psub"])
        payload = parse_text(text, str(fixture))
        by_name = {device["name"]: device for device in payload["devices"]}
        self.assertEqual(by_name["n50_hvbn_30v_ckt"]["port_confidence"], "confirmed")
        self.assertIn("nbl", by_name["n50_hvbn_30v_ckt"]["topology"])
        self.assertEqual(by_name["pch3d3_nbl_7v_7t_mac"]["family_voltage"], 3.3)
        self.assertEqual(by_name["pch3d3_nbl_7v_7t_mac"]["isolation_voltage"], 7.0)
        self.assertEqual(
            next(rule for rule in payload["rules"] if rule["target"] == "n50_hvbn_30v_ckt")["terminal_pair"],
            ["nbl", "psub"],
        )
        self.assertFalse(any(rule["target"] == "n50_hvbn_30v_ckt" and rule["confidence"] == "inferred" for rule in payload["rules"]))
        pch_candidates = [rule for rule in payload["rules"] if rule["target"] == "pch3d3_nbl_7v_7t_mac"]
        self.assertTrue(any(rule["limit_kind"] == "isolation_bv" and not rule["enabled"] for rule in pch_candidates))
        self.assertEqual(pch_candidates[0]["terminal_pair"], ["nbl", "psub"])

    def test_model_soa_detection_does_not_treat_every_bsource_as_soa(self) -> None:
        ordinary = "subckt demo d g s b\ncgb (g b) bsource q=1\n"
        self.assertFalse(detect_model_soa(ordinary)["enabled"])
        internal = "subckt demo d g s b\nparameters soa_ar=1e-4 soa_vdd=1\ngsoa (d s) bsource i=soa_ar\n"
        result = detect_model_soa(internal)
        self.assertTrue(result["enabled"])
        self.assertEqual(result["mechanism"], "gsoa_bsource")

    def test_non_mos_candidates_are_disabled_and_category_specific(self) -> None:
        text = """simulator lang=spectre
inline subckt rhrp_hv_3t_ckt (in out sx)
inline subckt rhrp_3k_mac (in out sx)
inline subckt rnpo_3t_ckt (in out sx)
inline subckt ndio18 (p n)
inline subckt pvar18_ckt (p n)
inline subckt mim_ckt (top bot)
"""
        payload = parse_text(text, "passive_models.scs")
        candidates = [rule for rule in payload["rules"] if rule["confidence"] == "inferred"]
        by_name = {rule["target"]: rule for rule in candidates}
        self.assertEqual(by_name["rhrp_hv_3t_ckt"]["maximum"], "120")
        self.assertEqual(by_name["rhrp_3k_mac"]["maximum"], "30")
        self.assertEqual(by_name["rnpo_3t_ckt"]["maximum"], "30")
        self.assertEqual(by_name["ndio18"]["maximum"], "1.98")
        self.assertEqual(by_name["ndio18"]["minimum"], "-1.98")
        self.assertEqual(by_name["pvar18_ckt"]["limit_kind"], "terminal_voltage")
        self.assertTrue(all(not rule["enabled"] for rule in candidates))
        self.assertNotIn("mim_ckt", by_name)

    def test_non_mos_source_rule_wins_over_candidate(self) -> None:
        text = """simulator lang=spectre
inline subckt ndio18 (p n)
source_diode assert sub=ndio18 expr="V(p,n)" max=2
"""
        payload = parse_text(text, "diode.scs")
        rules = [rule for rule in payload["rules"] if rule["target"] == "ndio18"]
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["confidence"], "confirmed")
        self.assertEqual(rules[0]["maximum"], "2")

    def test_spectre_diagnostics_are_compact_and_readable(self) -> None:
        output = """Error found by spectre during circuit read-in.
ERROR (SFE-874): \"/tmp/main.scs\" 4: syntax error.
Warning from spectre during initial setup.
WARNING (SPECTRE-17607): Assert `check' is ignored.
"""
        issues = _spectre_diagnostics(output, 2)
        self.assertEqual(issues[0]["severity"], "error")
        self.assertIn("spectre_sfe-874", issues[0]["code"])
        self.assertTrue(any(item["severity"] == "warning" for item in issues))

    def test_adapter_config_overrides_device_metadata(self) -> None:
        device = Device(name="custom12_iso_ckt", family="unknown")
        config = {
            "schema": "soa-adapter/v1",
            "id": "demo",
            "version": "1",
            "device_rules": [{
                "pattern": "^custom12_",
                "family": "ldmos",
                "scope": "active",
                "family_voltage": 12,
                "topology": ["iso"],
            }],
        }
        apply_adapter_config([device], [], config)
        self.assertEqual(device.family, "ldmos")
        self.assertEqual(device.family_voltage, 12.0)
        self.assertIn("iso", device.topology)
        self.assertEqual(validate_adapter_config(config), [])

    def test_project_schema_keeps_devices_and_adapter(self) -> None:
        rules = parse_spectre_asserts('check assert sub=n50_ckt expr="V(d,s)" max=5')
        adapter = {"schema": "soa-adapter/v1", "id": "demo", "version": "1", "device_rules": []}
        project = project_json(
            process_path="/pdk",
            process_version="v1",
            rules=rules,
            export_set=ExportSet(formats=["json"]),
            devices=[{"name": "n50_ckt", "family": "mos"}],
            sources=[{"path": "/pdk/soa.mdl", "kind": "spectre_soa"}],
            adapter=adapter,
        )
        payload = __import__("json").loads(project)
        self.assertEqual(validate_project_payload(payload), [])
        self.assertEqual(payload["devices"][0]["name"], "n50_ckt")
        self.assertEqual(payload["adapter_config"]["id"], "demo")

    def test_model_soa_export_modes_are_explicit(self) -> None:
        rules = parse_spectre_asserts('check assert sub=n50_ckt expr="V(d,s)" max=5')
        sources = [{
            "path": "/pdk/models/hvmos.mdl",
            "kind": "model_spectre",
            "model_internal_soa": True,
            "model_soa_mechanism": "gsoa_bsource",
            "model_soa_line": 42,
        }]
        native = render_spectre(rules, model_sources=sources, model_soa_mode="native")
        self.assertIn('include "/pdk/models/hvmos.mdl"', native)
        annotated = render_spectre(rules, model_sources=sources, model_soa_mode="annotate")
        self.assertNotIn('include "/pdk/models/hvmos.mdl"', annotated)
        self.assertIn("只记录模型内 SOA 来源", annotated)
        metadata = model_soa_export_metadata(sources, "approximate")
        self.assertEqual(metadata["sources"][0]["mechanism"], "gsoa_bsource")
        self.assertIn("不能复现模型内 gsoa/soa_* 曲线", metadata["warnings"][0])
        dual = render_spectre(rules, model_sources=sources, model_soa_mode="dual")
        self.assertIn('include "/pdk/models/hvmos.mdl"', dual)
        self.assertIn("可能产生重复告警", dual)
        project = project_json(
            process_path="/pdk",
            process_version=None,
            rules=rules,
            export_set=ExportSet(formats=["json"]),
            model_sources=sources,
            model_soa_mode="native",
        )
        self.assertIn('"model_soa"', project)


if __name__ == "__main__":
    unittest.main()
