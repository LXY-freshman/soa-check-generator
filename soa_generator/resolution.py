"""Resolve competing SOA rule candidates into one explainable result.

The parser intentionally keeps every source rule as evidence.  This module
chooses a candidate only at the matrix/export boundary, so source evidence
and user overrides remain immutable and inspectable.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .models import Rule


DEFAULT_SOURCE_PRIORITY = [
    "user_confirmed",
    "user_defined",
    "spectre_soa",
    "document",
    "model_spectre",
    "device_list",
    "adapter",
    "inference",
]


def normalize_source_priority(priority: Iterable[str] | None) -> list[str]:
    """Return a stable priority list while keeping user confirmation fixed first."""
    requested = [str(item).strip() for item in (priority or []) if str(item).strip()]
    result: list[str] = []
    for item in ["user_confirmed", *requested, *DEFAULT_SOURCE_PRIORITY]:
        if item not in result:
            result.append(item)
    return result


def _pair_from_expr(expr: str) -> tuple[str, str] | None:
    match = re.search(r"\bv\s*\(\s*([^,\s()]+)\s*,\s*([^,\s()]+)\s*\)", expr or "", re.I)
    if not match:
        return None
    return match.group(1).lower(), match.group(2).lower()


def rule_match_key(rule: Rule) -> tuple[str, str, tuple[str, ...]]:
    """Identify one physical check independently of its source and rule name."""
    pair = tuple(item.lower() for item in rule.terminal_pair)
    if not pair:
        parsed = _pair_from_expr(str(rule.effective("expr") or ""))
        pair = parsed if parsed else (re.sub(r"\s+", "", str(rule.effective("expr") or "")).lower(),)
    return (
        str(rule.effective("target") or rule.target).lower(),
        str(rule.limit_kind or "other"),
        pair,
    )


def source_route(rule: Rule) -> str:
    """Map a rule's evidence and lifecycle to a user-facing priority route."""
    status = str(rule.effective("status") or rule.status)
    if status == "confirmed":
        return "user_confirmed"
    if rule.route == "user":
        return "user_defined"
    mechanism = rule.source.mechanism if rule.source else "unknown"
    if mechanism == "spectre_assert":
        return "spectre_soa"
    if mechanism == "manual_table":
        return "document"
    if mechanism == "model_internal":
        return "model_spectre"
    if mechanism == "inference" or status in {"inferred", "missing"}:
        return "inference"
    if rule.route in {"model", "model_spectre"}:
        return "model_spectre"
    if rule.route in {"adapter", "device_list"}:
        return rule.route
    if rule.confidence == "documented":
        return "document"
    return "device_list" if rule.source and rule.source.mechanism == "manual_table" else "inference"


def _status(rule: Rule) -> str:
    return str(rule.effective("status") or rule.status or rule.confidence or "source")


def _complete(rule: Rule) -> bool:
    return bool(
        rule.effective("expr")
        and (
            rule.effective("maximum") not in (None, "")
            or rule.effective("minimum") not in (None, "")
        )
    )


@dataclass(frozen=True)
class ResolvedRule:
    """One selected candidate plus the evidence needed to explain it."""

    key: tuple[str, str, tuple[str, ...]]
    chosen: Rule | None
    candidates: tuple[Rule, ...]
    route: str = "inference"
    status: str = "missing"
    conflict: bool = False

    @property
    def complete(self) -> bool:
        return self.chosen is not None and _complete(self.chosen)

    def to_dict(self) -> dict[str, object]:
        chosen = self.chosen
        return {
            "key": [self.key[0], self.key[1], list(self.key[2])],
            "rule_id": chosen.rule_id if chosen else None,
            "route": self.route,
            "status": self.status,
            "conflict": self.conflict,
            "maximum": chosen.effective("maximum") if chosen else None,
            "minimum": chosen.effective("minimum") if chosen else None,
            "candidate_rule_ids": [rule.rule_id for rule in self.candidates],
        }


def resolve_rule_group(
    rules: Iterable[Rule],
    source_priority: Iterable[str] | None = None,
) -> ResolvedRule:
    candidates = tuple(rules)
    if not candidates:
        return ResolvedRule(("", "other", ()), None, ())
    priority = normalize_source_priority(source_priority)
    rank = {name: index for index, name in enumerate(priority)}
    indexed = list(enumerate(candidates))
    indexed.sort(
        key=lambda item: (
            rank.get(source_route(item[1]), len(priority)),
            0 if _complete(item[1]) else 1,
            item[0],
        )
    )
    ordered = tuple(rule for _index, rule in indexed)
    chosen = ordered[0]
    bounds = {
        (chosen_rule.effective("maximum"), chosen_rule.effective("minimum"))
        for chosen_rule in ordered
    }
    conflict = len(bounds) > 1
    route = source_route(chosen)
    selected_status = _status(chosen)
    # A confirmed user value resolves a disagreement, while preserving the
    # conflict flag so the UI can explain what it overrode.
    status = selected_status
    if conflict and route != "user_confirmed":
        status = "conflict"
    elif route == "user_confirmed":
        status = "confirmed"
    return ResolvedRule(rule_match_key(chosen), chosen, ordered, route, status, conflict)


def resolve_rule_groups(
    rules: Iterable[Rule],
    source_priority: Iterable[str] | None = None,
) -> dict[tuple[str, str, tuple[str, ...]], ResolvedRule]:
    groups: dict[tuple[str, str, tuple[str, ...]], list[Rule]] = {}
    for rule in rules:
        groups.setdefault(rule_match_key(rule), []).append(rule)
    return {
        key: resolve_rule_group(group, source_priority)
        for key, group in groups.items()
    }

