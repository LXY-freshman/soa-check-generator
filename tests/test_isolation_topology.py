import json
from pathlib import Path
import unittest
from unittest.mock import patch

from soa_generator.classify import apply_port_metadata, classify_device
from soa_generator.export import project_json, render_spectre, select_rules
from soa_generator.models import ExportSet
from soa_generator.parsers import parse_spectre_asserts, topology_rule_candidates
from soa_generator.service import _rule_from_dict, parse_source, parse_sources, parse_text, parse_texts, quick_check, resolve_project_rules


FIXTURE = Path(__file__).parent / "fixtures" / "isowell_ports.scs"


class IsolationTopologyTests(unittest.TestCase):
    def test_isowell_external_candidate_and_matrix_exist_in_all_parse_paths(self):
        text = FIXTURE.read_text()
        source = {"kind": "local", "path": str(FIXTURE), "candidate_kind": "model_spectre"}
        for payload in (
            parse_source(source), parse_sources([source]),
            parse_text(text, str(FIXTURE)),
            parse_texts([{"path": str(FIXTURE), "text": text, "kind": "model_spectre"}]),
        ):
            with self.subTest(summary=payload["summary"]):
                device = next(item for item in payload["devices"] if item["name"] == "demo_mos_mid_isowell_30v_demo")
                matrix = {tuple(item["terminal_pair"]): item for item in device["check_matrix"] if item["limit_kind"] == "isolation_bv"}
                self.assertEqual(matrix[("ISOWELL", "PSUB")]["isolation_side"], "outer")
                self.assertEqual(matrix[("ISOWELL", "B")]["isolation_side"], "inner")
                # Native internal 12 V is not copied to the external check.
                self.assertEqual(matrix[("ISOWELL", "B")]["maximum"], "12")
                self.assertEqual(matrix[("ISOWELL", "PSUB")]["maximum"], "30")
                outer = [rule for rule in payload["rules"] if rule["terminal_pair"] == ["ISOWELL", "PSUB"]]
                self.assertEqual(len(outer), 1)
                self.assertFalse(outer[0]["enabled"])
                self.assertEqual(outer[0]["status"], "inferred")
                self.assertEqual(outer[0]["source"]["path"], str(FIXTURE))
                self.assertIn("对外大衬底", outer[0]["source"]["note"])

    def test_unknown_isowell_rating_stays_blank_with_internal_and_external_checks(self):
        payload = parse_text(FIXTURE.read_text(), str(FIXTURE))
        device = next(item for item in payload["devices"] if item["name"] == "demo_mos_mid_isowell_demo")
        checks = {tuple(item["terminal_pair"]): item for item in device["check_matrix"] if item["limit_kind"] == "isolation_bv"}
        for pair in (("isowell", "psub"), ("isowell", "b")):
            self.assertTrue(checks[pair]["applicable"])
            self.assertEqual(checks[pair]["status"], "missing")
            self.assertIsNone(checks[pair]["maximum"])
        self.assertIsNone(device["isolation_voltage"])

    def test_named_isolation_ports_share_internal_external_generation(self):
        for ring in ("iso", "isub", "nbl", "ISOWELL", "hvnwell", "ddnw"):
            with self.subTest(ring=ring):
                payload = parse_text(f"subckt demo_mos_mid_demo (d g s b {ring} psub)\nends demo_mos_mid_demo\n", "demo.scs")
                candidates = {tuple(item["terminal_pair"]) for item in payload["rules"] if item["limit_kind"] == "isolation_bv"}
                matrix = {tuple(item["terminal_pair"]) for item in payload["devices"][0]["check_matrix"] if item["limit_kind"] == "isolation_bv"}
                self.assertIn((ring, "b"), candidates)
                self.assertIn((ring, "psub"), candidates)
                self.assertEqual(candidates, matrix)

    def test_all_explicit_isolation_terminals_are_kept(self):
        payload = parse_text("subckt demo_mos_mid_demo (d g s b isowell nbl psub sub)\nends demo_mos_mid_demo\n", "demo.scs")
        pairs = {tuple(item["terminal_pair"]) for item in payload["devices"][0]["check_matrix"] if item["isolation_side"] == "outer"}
        self.assertEqual(pairs, {("isowell", "psub"), ("isowell", "sub"), ("nbl", "psub"), ("nbl", "sub")})

    def test_reverse_native_psub_check_is_not_duplicated_or_reassigned_to_body(self):
        device = classify_device("demo_mos_mid_isowell_30v_demo")
        apply_port_metadata(device, ["d", "g", "s", "b", "ISOWELL", "PSUB"])
        native = parse_spectre_asserts('native_outer assert sub=demo_mos_mid_isowell_30v_demo expr="V(PSUB,ISOWELL)" min=-28 level=warning')
        generated = topology_rule_candidates([device], native)
        self.assertFalse(any(rule.terminal_pair == ["ISOWELL", "PSUB"] for rule in generated))
        result = resolve_project_rules({"rules": [rule.to_dict() for rule in [*native, *generated]], "devices": [device.to_dict()]})
        outer = next(item for item in result["profiles"][0]["check_matrix"] if item["isolation_side"] == "outer")
        self.assertEqual(outer["maximum"], "28")
        self.assertEqual(outer["route"], "spectre_soa")
        self.assertEqual(outer["rule_ids"], [native[0].rule_id])

    def test_absent_outer_terminal_never_creates_a_psub_expression(self):
        payload = parse_text("subckt demo_mos_mid_isowell_30v_demo (d g s b ISOWELL)\nends demo_mos_mid_isowell_30v_demo\n", "demo.scs")
        self.assertFalse(any("psub" in item["expr"].lower() for item in payload["rules"]))

    def test_psub_without_isolation_terminal_does_not_create_isolation_checks(self):
        payload = parse_text("subckt demo_mos_mid_demo (d g s b psub)\nends demo_mos_mid_demo\n", "demo.scs")
        self.assertFalse(any(rule["limit_kind"] == "isolation_bv" for rule in payload["rules"]))

    def test_user_can_fill_external_check_round_trip_and_export_it(self):
        payload = parse_text(FIXTURE.read_text(), str(FIXTURE))
        rules = [_rule_from_dict(item) for item in payload["rules"]]
        rule = next(item for item in rules if item.target == "demo_mos_mid_isowell_demo" and item.terminal_pair == ["isowell", "psub"])
        self.assertNotIn(rule, select_rules(rules, ExportSet()))
        rule.override = {"maximum": "24", "enabled": True, "status": "confirmed"}
        self.assertIsNone(rule.maximum)
        self.assertIsNone(rule.original["maximum"])
        generated = render_spectre(select_rules(rules, ExportSet()))
        self.assertIn('expr="v(isowell,psub)" max=24', generated)
        data = json.loads(project_json(process_path="/demo", process_version="1", rules=rules, export_set=ExportSet(), devices=payload["devices"]))
        restored = [_rule_from_dict(item) for item in data["rules"]]
        self.assertEqual(render_spectre(select_rules(restored, ExportSet())), generated)
        with patch("soa_generator.service._run_local_spectre_check", return_value=(0, "")) as runner:
            quick_check(restored, [item["name"] for item in payload["devices"]], {"kind": "local"})
            self.assertEqual(runner.call_args.args[0], generated)


if __name__ == "__main__":
    unittest.main()
