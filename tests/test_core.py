import tempfile
import unittest
from pathlib import Path

from soa_generator.classify import apply_port_metadata, classify_device
from soa_generator.adapters import apply_adapter_config
from soa_generator.coverage import pdk_coverage
from soa_generator.export import ExportSet, model_soa_export_metadata, project_json, render_spectre, select_rules
from soa_generator.models import Device, Rule, SourceEvidence
from soa_generator.manual import parse_manual_rules
from soa_generator.parsers import detect_model_soa, parse_device_list, parse_model_definitions, parse_model_limits, parse_model_parameters, parse_spectre_asserts, parse_subckt_dependencies, topology_rule_candidates
from soa_generator.resolution import resolve_rule_groups
from soa_generator.schema import validate_adapter_config, validate_project_payload
from soa_generator.service import _spectre_diagnostics, parse_sources, parse_text, parse_texts
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
        parsed = parse_text(text, "soa.scs", source_priority=["spectre_soa", "model_spectre", "inference"])
        self.assertEqual(parsed["source_priority"][:2], ["user_confirmed", "spectre_soa"])

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

    def test_ldmos_keeps_drain_and_gate_voltage_separate(self) -> None:
        device = classify_device("nld12_iso_ckt")
        self.assertEqual(device.family_voltage, 12.0)
        self.assertEqual(device.gate_voltage, 5.0)
        self.assertEqual(device.gate_voltage_confidence, "inferred")
        payload = parse_text("subckt nld12_iso_ckt (d g bs nbl psub)\nends nld12_iso_ckt\n", "nld12.scs")
        parsed = payload["devices"][0]
        matrix = {(item["limit_kind"], tuple(item["terminal_pair"])): item for item in parsed["check_matrix"]}
        self.assertEqual(matrix[("Vds", ("d", "bs"))]["status"], "inferred")
        self.assertEqual(matrix[("Vgs", ("g", "bs"))]["status"], "inferred")
        values = {rule["limit_kind"]: rule["maximum"] for rule in payload["rules"] if rule["target"] == "nld12_iso_ckt"}
        self.assertEqual(values["Vds"], "13.2")
        self.assertEqual(values["Vgs"], "5.5")
        isolation_pairs = {
            tuple(rule["terminal_pair"])
            for rule in payload["rules"]
            if rule["target"] == "nld12_iso_ckt" and rule["limit_kind"] == "isolation_bv"
        }
        self.assertTrue({("nbl", "psub"), ("nbl", "bs"), ("nbl", "d")} <= isolation_pairs)

    def test_generic_iso_name_does_not_infer_isolation_rating_from_family_voltage(self) -> None:
        payload = parse_text("subckt n18_iso_ckt (d g s b nbl psub)\nends n18_iso_ckt\n", "generic_iso.scs")
        device = payload["devices"][0]
        self.assertIsNone(device["isolation_voltage"])
        isolation = [rule for rule in payload["rules"] if rule["limit_kind"] == "isolation_bv"]
        self.assertTrue(isolation)
        self.assertTrue(all(rule["maximum"] is None for rule in isolation))
        self.assertTrue(all(rule["status"] == "missing" and not rule["enabled"] for rule in isolation))

    def test_isolation_ring_checks_inner_body_and_outer_psub(self) -> None:
        device = classify_device("n50_iso_30v_ckt")
        apply_port_metadata(device, ["d", "g", "s", "b", "iso", "psub"])
        rules = topology_rule_candidates([device], [])
        pairs = {tuple(rule.terminal_pair): rule for rule in rules}
        self.assertIn(("iso", "b"), pairs)
        self.assertIn(("iso", "psub"), pairs)
        self.assertEqual(pairs[("iso", "b")].maximum, "30")
        self.assertEqual(pairs[("iso", "psub")].maximum, "30")

    def test_physical_matrix_covers_non_mos_terminal_checks(self) -> None:
        text = """inline subckt dio5 (p n)\ninline subckt npn5 (c b e)\ninline subckt rpoly (n1 n2 sub)\ninline subckt mim_5v (top bot)\n"""
        payload = parse_text(text, "non_mos_matrix.scs")
        devices = {device["name"]: device for device in payload["devices"]}
        diode_kinds = {item["limit_kind"] for item in devices["dio5"]["check_matrix"]}
        self.assertIn("reverse_voltage", diode_kinds)
        self.assertIn("forward_voltage", diode_kinds)
        bjt_kinds = {item["limit_kind"] for item in devices["npn5"]["check_matrix"]}
        self.assertEqual(bjt_kinds, {"Vce", "Vcb", "Vbe"})
        resistor = {(item["limit_kind"], tuple(item["terminal_pair"])): item for item in devices["rpoly"]["check_matrix"]}
        self.assertTrue(resistor[("resistor_substrate_voltage", ("n1", "sub"))]["applicable"])
        self.assertIn("current_density", {item["limit_kind"] for item in devices["rpoly"]["check_matrix"]})
        self.assertEqual(devices["mim_5v"]["check_matrix"][0]["limit_kind"], "terminal_voltage")

    def test_combined_export_selects_devices_and_renders_section(self) -> None:
        rules = parse_spectre_asserts('check assert sub=n50_ckt expr="V(d,s)" max=5')
        export_set = ExportSet(device_names=["n50_ckt"], formats=["spectre"])
        selected = select_rules(rules, export_set)
        rendered = render_spectre(selected)
        self.assertEqual(len(selected), 1)
        self.assertIn("section soa_generated", rendered)
        self.assertIn("sub=n50_ckt", rendered)

    def test_rule_override_is_used_for_export_and_lint(self) -> None:
        rules = parse_spectre_asserts('check assert sub=n50_ckt expr="V(d,s)" max=5 level=warning')
        rules[0].override = {"name": "check_user", "maximum": "4", "level": "error"}
        rendered = render_spectre(rules)
        self.assertIn("check_user assert", rendered)
        self.assertIn("max=4", rendered)
        self.assertIn("level=error", rendered)
        self.assertFalse(any(issue.code == "invalid_level" for issue in lint_rules(rules, {"n50_ckt"})))

    def test_source_priority_resolves_one_physical_check(self) -> None:
        native = Rule(
            rule_id="native",
            name="native_vds",
            target="n50_ckt",
            expr="v(d,s)",
            maximum="5",
            limit_kind="Vds",
            terminal_pair=["d", "s"],
            source=SourceEvidence(path="soa.mdl", mechanism="spectre_assert"),
        )
        model = Rule(
            rule_id="model",
            name="model_vds",
            target="n50_ckt",
            expr="v(d,s)",
            maximum="5.5",
            limit_kind="Vds",
            terminal_pair=["d", "s"],
            source=SourceEvidence(path="model.scs", mechanism="model_internal"),
        )
        resolved = resolve_rule_groups([native, model], ["model_spectre", "spectre_soa"])
        item = next(iter(resolved.values()))
        self.assertEqual(item.chosen.rule_id, "model")
        self.assertEqual(item.route, "model_spectre")
        self.assertEqual(item.status, "conflict")
        self.assertTrue(item.conflict)

    def test_curve_source_does_not_conflict_with_scalar_absolute_candidate(self) -> None:
        curve = Rule(
            rule_id="curve",
            name="nld12_vds_curve",
            target="nld12_iso_ckt",
            expr="v(d,bs)>=23.9&&v(g,bs)<1",
            limit_kind="Vds",
            terminal_pair=["d", "bs"],
            source=SourceEvidence(path="soa_spe.mdl", mechanism="spectre_assert"),
        )
        scalar = Rule(
            rule_id="scalar",
            name="nld12_vds_absolute",
            target="nld12_iso_ckt",
            expr="v(d,bs)",
            maximum="13.2",
            minimum="-13.2",
            limit_kind="Vds",
            terminal_pair=["d", "bs"],
            confidence="inferred",
            status="inferred",
            route="inference",
            source=SourceEvidence(path="model.scs", mechanism="inference"),
        )
        item = next(iter(resolve_rule_groups([curve, scalar]).values()))
        self.assertEqual(item.chosen.rule_id, "curve")
        self.assertFalse(item.conflict)

    def test_confirmed_rule_resolves_source_conflict(self) -> None:
        source = Rule(
            rule_id="source",
            name="source_vds",
            target="n50_ckt",
            expr="v(d,s)",
            maximum="5",
            limit_kind="Vds",
            terminal_pair=["d", "s"],
            source=SourceEvidence(path="soa.mdl", mechanism="spectre_assert"),
        )
        confirmed = Rule(
            rule_id="confirmed",
            name="confirmed_vds",
            target="n50_ckt",
            expr="v(d,s)",
            maximum="5.5",
            limit_kind="Vds",
            terminal_pair=["d", "s"],
            status="confirmed",
            route="user",
            source=SourceEvidence(path="用户确认", mechanism="unknown"),
        )
        item = next(iter(resolve_rule_groups([source, confirmed]).values()))
        self.assertEqual(item.chosen.rule_id, "confirmed")
        self.assertEqual(item.status, "confirmed")
        self.assertEqual(item.route, "user_confirmed")
        self.assertTrue(item.conflict)

    def test_export_deduplicates_resolved_candidates(self) -> None:
        native = Rule(
            rule_id="native",
            name="native_vds",
            target="n50_ckt",
            expr="v(d,s)",
            maximum="5",
            limit_kind="Vds",
            terminal_pair=["d", "s"],
            source=SourceEvidence(path="soa.mdl", mechanism="spectre_assert"),
        )
        model = Rule(
            rule_id="model",
            name="model_vds",
            target="n50_ckt",
            expr="v(d,s)",
            maximum="5.5",
            limit_kind="Vds",
            terminal_pair=["d", "s"],
            source=SourceEvidence(path="model.scs", mechanism="model_internal"),
        )
        selected = select_rules([native, model], ExportSet(formats=["spectre"]), ["model_spectre", "spectre_soa"])
        self.assertEqual([rule.rule_id for rule in selected], ["model"])

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

    def test_model_source_is_preserved_when_merged_with_device_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            device_path = Path(directory) / "devices.devicelist"
            model_path = Path(directory) / "models.scs"
            device_path.write_text("****** MOS ******\nn50_ckt\n", encoding="utf-8")
            model_path.write_text("subckt n50_ckt (d g s b)\nends n50_ckt\n", encoding="utf-8")
            payload = parse_sources([
                {"kind": "local", "path": str(device_path), "candidate_kind": "device_list"},
                {"kind": "local", "path": str(model_path), "candidate_kind": "model_spectre"},
            ])
        device = next(item for item in payload["devices"] if item["name"] == "n50_ckt")
        self.assertEqual(device["ports"], ["d", "g", "s", "b"])
        self.assertEqual(device["model_sources"][0]["kind"], "model_spectre")
        self.assertEqual(payload["coverage"]["summary"]["model_backed_devices"], 1)
        self.assertEqual(payload["coverage"]["summary"]["device_list_only_devices"], 0)

    def test_browser_batch_parser_reports_file_progress(self) -> None:
        updates = []
        result = parse_texts([
            {"path": "one.scs", "kind": "model_spectre", "text": "subckt n18_ckt (d g s b)\n"},
            {"path": "two.scs", "kind": "model_spectre", "text": "subckt n50_ckt (d g s b)\n"},
        ], progress=updates.append)
        self.assertEqual(result["summary"]["files"], 2)
        completed = [item["completed"] for item in updates if item["stage"] == "file_complete"]
        self.assertEqual(completed, [1, 2])
        self.assertEqual(updates[-1]["stage"], "building_matrix")

    def test_multiple_model_sources_complete_iso_mos_profiles_without_fake_ratings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device_path = root / "devices.devicelist"
            soa_path = root / "soa_spe.mdl"
            model_path = root / "mis_spe.mdl"
            device_path.write_text("****** MOS ******\nn18_iso_ckt\nn50_iso_ckt\n", encoding="utf-8")
            soa_path.write_text(
                'v18 assert sub=n18_iso_ckt expr="v(g,s)" max=1.98 min=-1.98\n'
                'v50 assert sub=n50_iso_ckt expr="v(g,s)" max=5.5 min=-5.5\n',
                encoding="utf-8",
            )
            model_path.write_text(
                "inline subckt n18_iso_ckt (d g s b nbl psub)\n"
                "inline subckt n50_iso_ckt (d g s b nbl psub)\n",
                encoding="utf-8",
            )
            payload = parse_sources([
                {"kind": "local", "path": str(device_path), "candidate_kind": "device_list"},
                {"kind": "local", "path": str(soa_path), "candidate_kind": "spectre_soa"},
                {"kind": "local", "path": str(model_path), "candidate_kind": "model_spectre"},
            ])
        profiles = {device["name"]: device for device in payload["devices"]}
        for name in ("n18_iso_ckt", "n50_iso_ckt"):
            profile = profiles[name]
            self.assertEqual(profile["ports"], ["d", "g", "s", "b", "nbl", "psub"])
            self.assertEqual(profile["model_sources"][0]["path"], str(model_path))
            self.assertIsNone(profile["isolation_voltage"])
            self.assertTrue(all(item["maximum"] is None for item in profile["check_matrix"] if item["limit_kind"] == "isolation_bv"))
        self.assertEqual(payload["coverage"]["summary"]["model_backed_devices"], 2)
        self.assertEqual(payload["coverage"]["summary"]["device_list_only_devices"], 0)

    def test_manual_text_extracts_explicit_limits_but_skips_curves(self) -> None:
        device = classify_device("nld12_iso_ckt")
        apply_port_metadata(device, ["d", "g", "bs", "nbl", "psub"])
        text = """nld12_iso_ckt Vgs max 5.5 V\n+nld12_iso_ckt Vds SOA curve around 23.9-28.8 V\n+nld12_iso_ckt gate rating 5 V\n+\f\nnld12_iso_ckt Vgd maximum 5.5 V\n+"""
        rules = parse_manual_rules(text, "manual.pdf", [device])
        self.assertEqual(len(rules), 3)
        self.assertEqual(rules[0].maximum, "5.5")
        self.assertEqual(rules[0].terminal_pair, ["g", "bs"])
        self.assertEqual(rules[0].source.page, 1)
        self.assertEqual(rules[1].maximum, "5")
        self.assertEqual(rules[2].source.page, 2)
        self.assertFalse(any(rule.limit_kind == "Vds" for rule in rules))

    def test_manual_text_source_enters_profile_matrix(self) -> None:
        payload = parse_text(
            "subckt nld12_iso_ckt (d g bs nbl psub)\nends nld12_iso_ckt\n"
            "nld12_iso_ckt Vgs max 5.5 V\n",
            "manual.txt",
        )
        matrix = next(item for item in payload["devices"][0]["check_matrix"] if item["limit_kind"] == "Vgs")
        self.assertEqual(matrix["route"], "document")
        self.assertEqual(matrix["maximum"], "5.5")

    def test_manual_table_extracts_columns_and_continuation_rows(self) -> None:
        device = classify_device("nld12_iso_ckt")
        apply_port_metadata(device, ["d", "g", "bs", "nbl", "psub"])
        text = """Device | Gate BV | DSB BV | NBL-PSUB BV
nld12_iso_ckt | 5.5 V | 13.2 V | 30 V
nld12_ls_ckt
5.5 V | 13.2 V | 30 V
"""
        rules = parse_manual_rules(text, "table.txt", [device, classify_device("nld12_ls_ckt")])
        by_key = {(rule.target, rule.limit_kind): rule for rule in rules}
        self.assertEqual(by_key[("nld12_iso_ckt", "Vgs")].maximum, "5.5")
        self.assertEqual(by_key[("nld12_iso_ckt", "Vds")].maximum, "13.2")
        self.assertEqual(by_key[("nld12_iso_ckt", "isolation_bv")].maximum, "30")
        self.assertEqual(by_key[("nld12_ls_ckt", "Vgs")].maximum, "5.5")

    def test_pdk_coverage_reports_missing_and_conflict_checks(self) -> None:
        coverage = pdk_coverage([
            {"name": "n50", "family": "mos", "scope": "active", "check_matrix": [
                {"limit_kind": "Vds", "applicable": True, "status": "missing"},
                {"limit_kind": "Vgs", "applicable": True, "status": "conflict", "conflict": True},
            ]},
        ], [{"route": "spectre_soa", "status": "source"}], [{"kind": "spectre_soa"}])
        self.assertEqual(coverage["schema"], "soa-coverage/v1")
        self.assertEqual(coverage["summary"]["devices_with_missing_checks"], 1)
        self.assertEqual(coverage["summary"]["devices_with_conflicts"], 1)

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
        self.assertEqual(by_name["n50_hvbn_30v_ckt"]["port_roles"]["psub"], "bulk_substrate")
        self.assertEqual(by_name["n50_hvbn_30v_ckt"]["port_roles"]["nbl"], "isolation_nbl")
        self.assertEqual(by_name["pch3d3_nbl_7v_7t_mac"]["family_voltage"], 3.3)
        self.assertEqual(by_name["pch3d3_nbl_7v_7t_mac"]["isolation_voltage"], 7.0)
        self.assertEqual(
            next(rule for rule in payload["rules"] if rule["target"] == "n50_hvbn_30v_ckt")["terminal_pair"],
            ["nbl", "psub"],
        )
        self.assertFalse(any(rule["target"] == "n50_hvbn_30v_ckt" and rule["limit_kind"] == "isolation_bv" and rule["terminal_pair"] == ["nbl", "psub"] and rule["confidence"] == "inferred" for rule in payload["rules"]))
        self.assertTrue(any(rule["target"] == "n50_hvbn_30v_ckt" and rule["limit_kind"] == "isolation_bv" and rule["terminal_pair"] == ["nbl", "b"] and rule["confidence"] == "inferred" for rule in payload["rules"]))
        pch_candidates = [rule for rule in payload["rules"] if rule["target"] == "pch3d3_nbl_7v_7t_mac"]
        self.assertTrue(any(rule["limit_kind"] == "isolation_bv" and not rule["enabled"] for rule in pch_candidates))
        self.assertEqual(pch_candidates[0]["terminal_pair"], ["nbl", "psub"])

    def test_model_parameters_bind_to_devices_and_candidates(self) -> None:
        text = """simulator lang=spectre
model ndio18 diode
+ bv=11.5 ibv=625
subckt ndio18 (p n)
ends ndio18
subckt pvar3d3_mac (n1 n2)
cgg (n1 n2) capacitor c=1e-15 bv_max=5.5
ends pvar3d3_mac
"""
        parameters = parse_model_parameters(text)
        self.assertEqual(parameters["ndio18"]["bv"], "11.5")
        self.assertEqual(parameters["ndio18"]["ibv"], "625")
        self.assertEqual(parameters["pvar3d3_mac"]["bv_max"], "5.5")
        payload = parse_text(text, "model_parameters.scs")
        devices = {device["name"]: device for device in payload["devices"]}
        self.assertEqual(devices["ndio18"]["model_parameters"]["bv"], "11.5")
        diode_rule = next(rule for rule in payload["rules"] if rule["target"] == "ndio18")
        self.assertEqual(diode_rule["maximum"], "11.5")
        self.assertEqual(diode_rule["minimum"], "-11.5")
        var_rule = next(rule for rule in payload["rules"] if rule["target"] == "pvar3d3_mac")
        self.assertEqual(var_rule["maximum"], "5.5")

    def test_model_forward_voltage_and_current_density_candidates(self) -> None:
        text = """simulator lang=spectre
model dio5 diode
+ bv=5.5 fv_max=1.2
subckt dio5 (p n)
ends dio5
model n50_ckt nmos
+ jmax=0.25
subckt n50_ckt (d g s b)
ends n50_ckt
"""
        payload = parse_text(text, "model_forward_current.scs")
        diode_rules = [rule for rule in payload["rules"] if rule["target"] == "dio5"]
        self.assertTrue(any(rule["limit_kind"] == "forward_voltage" and rule["maximum"] == "1.2" for rule in diode_rules))
        mos_rules = [rule for rule in payload["rules"] if rule["target"] == "n50_ckt"]
        current = next(rule for rule in mos_rules if rule["limit_kind"] == "current_density")
        self.assertEqual(current["maximum"], "0.25")
        self.assertEqual(current["minimum"], "-0.25")

    def test_diode_forward_candidate_survives_source_reverse_rule(self) -> None:
        text = """simulator lang=spectre
model dio5 diode
+ bv=5.5 fv_max=1.2
subckt dio5 (p n)
source_reverse assert sub=dio5 expr=\"V(p,n)\" max=5.5
ends dio5
"""
        payload = parse_text(text, "diode_source_and_model.scs")
        diode_rules = [rule for rule in payload["rules"] if rule["target"] == "dio5"]
        self.assertTrue(any(rule["limit_kind"] == "reverse_voltage" and rule["confidence"] == "confirmed" for rule in diode_rules))
        self.assertTrue(any(rule["limit_kind"] == "forward_voltage" and rule["maximum"] == "1.2" for rule in diode_rules))

    def test_spectre_model_limits_generate_terminal_candidates(self) -> None:
        text = """simulator lang=spectre
subckt n50_ckt (d g s b)
cgd (g d) capacitor c=1e-15 bv_max=5.5
cgs (g s) capacitor c=1e-15 bv_max=5.5
ends n50_ckt
"""
        limits = parse_model_limits(text)
        self.assertEqual(limits["n50_ckt"][0]["left"], "g")
        self.assertEqual(limits["n50_ckt"][0]["value"], "5.5")
        payload = parse_text(text, "mos_model.scs")
        rules = [rule for rule in payload["rules"] if rule["target"] == "n50_ckt"]
        self.assertTrue(any(rule["limit_kind"] == "Vgs" and rule["maximum"] == "5.5" for rule in rules))
        self.assertTrue(any(rule["limit_kind"] == "Vgd" or rule["limit_kind"] == "terminal_voltage" for rule in rules))
        self.assertTrue(all(not rule["enabled"] for rule in rules))

    def test_subckt_dependencies_keep_parent_and_child_targets(self) -> None:
        text = """simulator lang=spectre
subckt child (d g s b)
ends child
subckt parent (d g s b)
xcore (d g s b) child
ends parent
"""
        self.assertEqual(parse_subckt_dependencies(text), {"parent": ["child"]})
        payload = parse_text(text, "hierarchy.scs")
        parent = next(device for device in payload["devices"] if device["name"] == "parent")
        self.assertEqual(parent["associated_devices"], ["child"])

    def test_device_profile_contains_physical_check_matrix(self) -> None:
        text = "subckt n50_ckt (d g s b)\nends n50_ckt\n"
        payload = parse_text(text, "profile.scs")
        device = payload["devices"][0]
        self.assertEqual(device["profile_stage"], "enriched")
        matrix = {item["limit_kind"]: item for item in device["check_matrix"]}
        self.assertEqual(matrix["Vds"]["terminal_pair"], ["d", "s"])
        self.assertEqual(matrix["isolation_bv"]["status"], "not_applicable")
        self.assertTrue(device["profile_completeness"] < 100)

    def test_psub_alone_does_not_create_isolation_check(self) -> None:
        payload = parse_text("subckt n50_ckt (d g s b psub)\nends n50_ckt\n", "ordinary_mos_psub.scs")
        matrix = [item for item in payload["devices"][0]["check_matrix"] if item["limit_kind"] == "isolation_bv"]
        self.assertEqual(len(matrix), 1)
        self.assertFalse(matrix[0]["applicable"])
        self.assertEqual(matrix[0]["status"], "not_applicable")
        self.assertIsNone(payload["devices"][0]["isolation_voltage"])

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
        self.assertEqual(by_name["mim_ckt"]["status"], "missing")
        self.assertIsNone(by_name["mim_ckt"]["maximum"])

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

    def test_adapter_documented_check_rule_binds_to_device_profile(self) -> None:
        config = {
            "schema": "soa-adapter/v1",
            "id": "documented-demo",
            "version": "1",
            "device_rules": [{"pattern": "^custom12_", "family": "ldmos", "family_voltage": 12}],
            "check_rules": [{
                "pattern": "^custom12_",
                "limit_kind": "Vgs",
                "expr": "v(g,bs)",
                "maximum": "5.5",
                "minimum": "-5.5",
                "source_path": "manual.pdf",
                "page": 42,
                "note": "gate absolute limit",
            }],
        }
        payload = parse_text(
            "subckt custom12_iso_ckt (d g bs nbl psub)\nends custom12_iso_ckt\n",
            "custom12.scs",
            adapter_config=config,
        )
        rule = next(rule for rule in payload["rules"] if rule["rule_id"].startswith("adapter:"))
        self.assertEqual(rule["confidence"], "documented")
        self.assertEqual(rule["route"], "adapter")
        self.assertEqual(rule["source"]["page"], 42)
        matrix = next(item for item in payload["devices"][0]["check_matrix"] if item["limit_kind"] == "Vgs")
        self.assertEqual(matrix["route"], "adapter")
        self.assertEqual(matrix["maximum"], "5.5")

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
