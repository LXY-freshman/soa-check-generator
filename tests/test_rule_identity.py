import json
from pathlib import Path
import unittest
from unittest.mock import patch

from soa_generator.classify import apply_port_metadata, classify_device
from soa_generator.export import project_json, render_spectre, select_rules
from soa_generator.matrix import build_check_matrix
from soa_generator.models import ExportSet
from soa_generator.parsers import parse_spectre_asserts, topology_rule_candidates
from soa_generator.resolution import canonical_scalar_bounds, resolve_rule_groups, scalar_rule_key
from soa_generator.service import _rule_from_dict, parse_text, parse_texts, quick_check, resolve_project_rules


class RuleIdentityTests(unittest.TestCase):
    def test_native_vsb_prevents_duplicate_vbs_inference_in_all_batch_paths(self):
        fixture = Path(__file__).parent / "fixtures" / "directional_checks.scs"
        text = fixture.read_text()
        for payload in (
            parse_text(text, str(fixture)),
            parse_texts([{"path": str(fixture), "kind": "model_spectre", "text": text}]),
        ):
            rules = [item for item in payload["rules"] if item["limit_kind"] == "Vbs"]
            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0]["expr"], "V(s,b)")
            self.assertEqual(rules[0]["source"]["mechanism"], "spectre_assert")
            matrix = next(item for item in payload["devices"][0]["check_matrix"] if item["limit_kind"] == "Vbs")
            self.assertFalse(matrix["conflict"])
            self.assertEqual((matrix["maximum"], matrix["minimum"]), ("1.98", "-1.98"))

    def test_numeric_formatting_and_reversed_symmetric_voltage_are_equivalent(self):
        rules = parse_spectre_asserts(
            'a assert sub=demo expr="V(s,b)" max=1.980 min=-1.980\n'
            'b assert sub=demo expr="v(b,s)" max=1.98 min=-1.98\n'
        )
        group = next(iter(resolve_rule_groups(rules).values()))
        self.assertEqual(len(group.candidates), 2)
        self.assertFalse(group.conflict)
        self.assertEqual(len(select_rules(rules, ExportSet())), 1)
        # Source evidence and the original orientation remain reviewable.
        self.assertEqual(rules[0].expr, "V(s,b)")
        self.assertEqual(rules[0].maximum, "1.980")

    def test_asymmetric_bounds_swap_and_negate_in_matrix(self):
        rules = parse_spectre_asserts(
            'a assert sub=demo_mos_low_demo expr="v(s,b)" max=1.2 min=-3\n'
            'b assert sub=demo_mos_low_demo expr="v(b,s)" max=3 min=-1.2\n'
        )
        self.assertEqual(canonical_scalar_bounds(rules[0]), ("3", "-1.2"))
        self.assertFalse(next(iter(resolve_rule_groups(rules).values())).conflict)
        device = classify_device("demo_mos_low_demo")
        apply_port_metadata(device, ["d", "g", "s", "b"])
        matrix = next(item for item in build_check_matrix(device, rules) if item["limit_kind"] == "Vbs")
        self.assertEqual(matrix["terminal_pair"], ["b", "s"])
        self.assertEqual((matrix["maximum"], matrix["minimum"]), ("3", "-1.2"))
        self.assertEqual(matrix["source_candidates"][0]["maximum"], "1.2")

    def test_different_asymmetric_voltage_limits_remain_a_conflict(self):
        rules = parse_spectre_asserts(
            'a assert sub=demo expr="v(s,b)" max=1 min=-3\n'
            'b assert sub=demo expr="v(b,s)" max=3 min=-2\n'
        )
        self.assertTrue(next(iter(resolve_rule_groups(rules).values())).conflict)

    def test_symbolic_and_one_sided_bounds_are_safe(self):
        rules = parse_spectre_asserts(
            'a assert sub=demo expr="v(s,b)" max=body_limit\n'
            'b assert sub=demo expr="v(b,s)" min=-(body_limit)\n'
        )
        self.assertEqual(canonical_scalar_bounds(rules[0]), (None, "-(body_limit)"))
        self.assertFalse(next(iter(resolve_rule_groups(rules).values())).conflict)
        self.assertEqual(len(select_rules(rules, ExportSet())), 1)

    def test_opposite_one_sided_limits_are_complementary(self):
        rules = parse_spectre_asserts(
            'a assert sub=demo expr="v(s,b)" max=1.98\n'
            'b assert sub=demo expr="v(b,s)" max=1.98\n'
        )
        self.assertEqual(len(select_rules(rules, ExportSet())), 2)
        self.assertFalse(any(group.conflict for group in resolve_rule_groups(rules).values()))

    def test_quick_check_deduplicates_reverse_voltage_without_running_spectre(self):
        rules = parse_spectre_asserts(
            'a assert sub=demo expr="v(s,b)" min=-1.98 max=1.98\n'
            'b assert sub=demo expr="v(b,s)" min=-1.98 max=1.98\n'
            'curve assert sub=demo expr="v(s,b)>2 && v(g,s)>1"\n'
        )
        with patch("soa_generator.service._run_local_spectre_check", return_value=(0, "")) as runner:
            quick_check(rules, ["demo"], {"kind": "local"})
        generated = runner.call_args.args[0]
        self.assertEqual(generated.count(" assert "), 2)
        self.assertIn('expr="v(s,b)>2 && v(g,s)>1"', generated)

    def test_resolve_preview_returns_only_scalar_alternatives_as_conflicts(self):
        rules = parse_spectre_asserts(
            'a assert sub=demo_mos_low_demo expr="v(s,b)" max=1 min=-3\n'
            'b assert sub=demo_mos_low_demo expr="v(b,s)" max=3 min=-2\n'
            'c assert sub=demo_mos_low_demo expr="v(s,b)>4 && v(g,s)>1"\n'
        )
        device = classify_device("demo_mos_low_demo")
        apply_port_metadata(device, ["d", "g", "s", "b"])
        result = resolve_project_rules({"rules": [rule.to_dict() for rule in rules], "devices": [device.to_dict()]})
        self.assertEqual(len(result["selected_rule_ids"]), 2)
        matrix = next(item for item in result["profiles"][0]["check_matrix"] if item["limit_kind"] == "Vbs")
        conflicts = [group for group in matrix["resolution_groups"] if group["conflict"]]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["candidate_rule_ids"], [rules[0].rule_id, rules[1].rule_id])
        self.assertNotIn(rules[2].rule_id, conflicts[0]["candidate_rule_ids"])

    def test_different_target_scopes_and_duration_are_not_deduplicated(self):
        rules = parse_spectre_asserts(
            'a assert sub=demo expr="v(s,b)" max=2 duration=slow\n'
            'b assert sub=demo expr="v(s,b)" max=2 duration=fast\n'
            'c assert subs=demo expr="v(s,b)" max=2 duration=fast\n'
        )
        self.assertEqual(len(select_rules(rules, ExportSet())), 3)

    def test_all_curve_segments_and_scalar_check_export_and_round_trip(self):
        fixture = Path(__file__).parent / "fixtures" / "directional_checks.scs"
        rules = parse_spectre_asserts(fixture.read_text(), str(fixture))
        export_set = ExportSet()
        selected = select_rules(rules, export_set)
        self.assertEqual(len(selected), 4)
        rendered = render_spectre(selected)
        for rule in rules:
            self.assertIn(rule.expr, rendered)
        project = json.loads(project_json(process_path="/demo", process_version="v1", rules=rules, export_set=export_set))
        restored = [_rule_from_dict(item) for item in project["rules"]]
        self.assertEqual(render_spectre(select_rules(restored, export_set)), rendered)
        with patch("soa_generator.service._run_local_spectre_check", return_value=(0, "")) as runner:
            result = quick_check(selected, ["demo_mos_low_demo"], {"kind": "local"})
            self.assertTrue(result["ok"])
            self.assertEqual(runner.call_args.args[0], rendered)

    def test_editing_expression_uses_effective_terminals_not_stale_pair(self):
        rules = parse_spectre_asserts('a assert sub=demo expr="v(s,b)" max=1 min=-3')
        rule = rules[0]
        rule.override = {"expr": "v(g,d)", "maximum": "5.5", "minimum": "-5.5"}
        self.assertEqual(scalar_rule_key(rule)[2], ("d", "g"))
        self.assertEqual(rule.terminal_pair, ["s", "b"])
        self.assertEqual(rule.original["expr"], "v(s,b)")

    def test_reversed_isolation_and_other_voltage_pairs_preserve_direction(self):
        device = classify_device("demo_mos_mid_iso_30v_ckt")
        apply_port_metadata(device, ["d", "g", "s", "b", "iso", "psub"])
        rules = parse_spectre_asserts('a assert sub=demo_mos_mid_iso_30v_ckt expr="v(psub,iso)" min=-30')
        self.assertEqual(rules[0].limit_kind, "isolation_bv")
        candidates = topology_rule_candidates([device], rules)
        self.assertFalse(any(item.terminal_pair == ["iso", "psub"] for item in candidates))
        matrix = next(item for item in build_check_matrix(device, rules) if item["terminal_pair"] == ["iso", "psub"])
        self.assertEqual((matrix["maximum"], matrix["minimum"]), ("30", None))

    def test_conditions_with_same_first_voltage_are_not_alternative_sources(self):
        rules = parse_spectre_asserts(
            'a assert sub=demo expr="v(d,s) * v(g,s)" max=10\n'
            'b assert sub=demo expr="v(d,s) * v(g,s) + 1" max=20\n'
        )
        self.assertEqual(len(resolve_rule_groups(rules)), 2)
        self.assertEqual(len(select_rules(rules, ExportSet())), 2)


if __name__ == "__main__":
    unittest.main()
