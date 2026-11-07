from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .models import Rule


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    rule_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def lint_rules(rules: Iterable[Rule], known_devices: set[str] | None = None) -> list[Issue]:
    result: list[Issue] = []
    seen: set[str] = set()
    valid_levels = {"none", "notice", "warning", "error", "fatal", None}
    for rule in rules:
        if rule.rule_id in seen:
            result.append(Issue("error", "duplicate_rule_id", f"重复规则 ID：{rule.rule_id}", rule.rule_id))
        seen.add(rule.rule_id)
        if not rule.target:
            result.append(Issue("error", "missing_target", "规则缺少 sub/subs 目标", rule.rule_id))
        if not rule.expr and rule.maximum is None and rule.minimum is None:
            result.append(Issue("error", "missing_check", "规则没有 expr、max 或 min", rule.rule_id))
        if rule.level not in valid_levels:
            result.append(Issue("error", "invalid_level", f"未知 level：{rule.level}", rule.rule_id))
        if known_devices is not None and rule.target not in known_devices:
            result.append(Issue("warning", "unknown_target", f"目标器件未在导入列表中：{rule.target}", rule.rule_id))
        if rule.confidence in {"inferred", "conflict", "missing"}:
            result.append(Issue("warning", "uncertain_source", f"规则可信度为 {rule.confidence}", rule.rule_id))
    return result
