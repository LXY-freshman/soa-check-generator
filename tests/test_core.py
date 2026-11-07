import tempfile
import unittest
from pathlib import Path

from soa_generator.classify import classify_device
from soa_generator.export import ExportSet, render_spectre, select_rules
from soa_generator.parsers import parse_device_list, parse_model_definitions, parse_spectre_asserts
from soa_generator.service import parse_sources, parse_text
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
"""
        devices = parse_device_list(text, "devices.devicelist")
        self.assertEqual([device.name for device in devices], ["n50_ckt", "rhrp_lc10k_3t_ckt"])
        self.assertEqual(devices[0].family, "mos")
        self.assertEqual(devices[0].family_voltage, 5.0)
        self.assertEqual(devices[1].family, "resistor")

    def test_voltage_name_conventions(self) -> None:
        self.assertEqual(classify_device("n18_ckt").family_voltage, 1.8)
        self.assertEqual(classify_device("n50_ckt").family_voltage, 5.0)
        self.assertEqual(classify_device("nld12_iso_ckt").family_voltage, 12.0)
        self.assertEqual(classify_device("nch_svt_1p8v").family_voltage, 1.8)
        iso = classify_device("n50_hvbn_30v_ckt")
        self.assertEqual(iso.isolation_voltage, 30.0)
        self.assertEqual(iso.isolation_confidence, "inferred")

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


if __name__ == "__main__":
    unittest.main()
