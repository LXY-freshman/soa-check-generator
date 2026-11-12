"""Resolve competing SOA rule candidates into one explainable result.

The parser intentionally keeps every source rule as evidence.  This module
chooses a candidate only at the matrix/export boundary, so source evidence
and user overrides remain immutable and inspectable.
"""

from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Union


from ._compat import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Iterable

from .models import Rule


DEFAULT_SOURCE_PRIORITY = [
    "user_confirmed",
    "user_defined",
    "spectre_soa",
    "document",
    "adapter",
    "model_spectre",
    "device_list",
    "inference",
]


def normalize_source_priority(priority: Optional[Iterable[str]]) -> List[str]:
    """Return a stable priority list while keeping user confirmation fixed first."""
    requested = [str(item).strip() for item in (priority or []) if str(item).strip()]
    result: List[str] = []
    for item in ["user_confirmed", *requested, *DEFAULT_SOURCE_PRIORITY]:
        if item not in result:
            result.append(item)
    return result


def _pair_from_expr(expr: str) -> Optional[Tuple[str, str]]:
    match = re.search(r"\bv\s*\(\s*([^,\s()]+)\s*,\s*([^,\s()]+)\s*\)", expr or "", re.I)
    if not match:
        return None
    return match.group(1).lower(), match.group(2).lower()


def is_scalar_voltage_expr(expr: str) -> bool:
    """Whether an expression is exactly one voltage pair, without SOA conditions."""
    return bool(re.fullmatch(r"\s*v\s*\(\s*[^,\s()]+\s*,\s*[^,\s()]+\s*\)\s*", expr or "", re.I))


def expression_measurement_key(target: str, expr: str) -> Tuple[str, Tuple[str, ...]]:
    """Find existing measurements before generating a fallback candidate.

    Conditional expressions intentionally never match a bare voltage pair.
    """
    pair = _pair_from_expr(expr) if is_scalar_voltage_expr(expr) else None
    identity = ("voltage", *sorted(pair)) if pair else ("expression", expr.strip())
    return target.lower(), identity


def canonical_limit_kind(kind: str) -> str:
    return {
        "vsb": "Vbs", "vbs": "Vbs", "vdb": "Vbd", "vbd": "Vbd",
        "vds": "Vds", "vsd": "Vds", "vgs": "Vgs", "vsg": "Vgs",
        "vgd": "Vgd", "vdg": "Vgd", "vgb": "Vgb", "vbg": "Vgb",
        "vce": "Vce", "vec": "Vce", "vcb": "Vcb", "vbc": "Vcb",
        "vbe": "Vbe", "veb": "Vbe",
    }.get(kind.lower(), kind)


def _canonical_pair(kind: str, pair: Tuple[str, ...]) -> Tuple[Tuple[str, ...], bool]:
    if len(pair) != 2:
        return pair, False
    preferred = {
        "Vds": [("d", "s"), ("d", "bs")],
        "Vgs": [("g", "s"), ("g", "bs")],
        "Vgd": [("g", "d")], "Vgb": [("g", "b")],
        "Vbs": [("b", "s")], "Vbd": [("d", "b")],
        "Vce": [("c", "e")], "Vcb": [("c", "b")], "Vbe": [("b", "e")],
    }.get(canonical_limit_kind(kind), [])
    canonical = next((item for item in preferred if set(item) == set(pair)), tuple(sorted(pair)))
    return canonical, canonical != pair


def scalar_rule_key(rule: Rule) -> Optional[Tuple[str, str, Tuple[str, ...]]]:
    expr = str(rule.effective("expr") or "")
    if not is_scalar_voltage_expr(expr):
        return None
    # Use the edited expression, not a possibly stale terminal_pair cache.
    pair = _pair_from_expr(expr) or ()
    canonical, _reversed = _canonical_pair(str(rule.limit_kind or "other"), pair)
    return (
        str(rule.effective("target") or rule.target).lower(),
        canonical_limit_kind(str(rule.limit_kind or "other")),
        canonical,
    )


def _bound(value: object, negate: bool = False) -> Optional[str]:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    try:
        number = Decimal(raw)
        if number.is_finite():
            number = -number if negate else number
            if number == 0:
                return "0"
            normalized = number.normalize()
            return format(normalized, "f") if abs(normalized.adjusted()) <= 100 else str(normalized)
    except InvalidOperation:
        pass
    if not negate:
        return raw
    if re.fullmatch(r"-\([A-Za-z_][A-Za-z0-9_]*\)", raw):
        return raw[2:-1]
    if re.fullmatch(r"-[A-Za-z_][A-Za-z0-9_]*", raw):
        return raw[1:]
    return f"-({raw})"


def scalar_bounds_in_direction(rule: Rule, pair: Iterable[str]) -> Tuple[Optional[str], Optional[str]]:
    """Express bounds relative to the specified terminals without editing evidence."""
    actual = _pair_from_expr(str(rule.effective("expr") or ""))
    direction = tuple(port.lower() for port in pair)
    maximum, minimum = rule.effective("maximum"), rule.effective("minimum")
    if actual and len(direction) == 2 and actual == direction[::-1] and actual != direction:
        return _bound(minimum, True), _bound(maximum, True)
    return _bound(maximum), _bound(minimum)


def canonical_scalar_bounds(rule: Rule) -> Tuple[Optional[str], Optional[str]]:
    key = scalar_rule_key(rule)
    return scalar_bounds_in_direction(rule, key[2] if key else ())


def physical_rule_key(rule: Rule) -> Tuple[str, str, Tuple[str, ...]]:
    """Identify a terminal check for the matrix, including conditional evidence."""
    expr = str(rule.effective("expr") or "")
    kind = canonical_limit_kind(str(rule.limit_kind or "other"))
    pair = _pair_from_expr(expr) or tuple(str(port).lower() for port in rule.terminal_pair)
    canonical, _reversed = _canonical_pair(kind, pair)
    return str(rule.effective("target") or "").lower(), kind, canonical


def _context(rule: Rule) -> Tuple[str, ...]:
    # Different scopes, sections and timing/report settings must not suppress
    # each other in an exported assertion set.
    return tuple(str(rule.effective(key) or "") for key in ("target_kind", "section", "duration", "level"))


def rule_match_key(rule: Rule) -> Tuple[str, str, Tuple[str, ...]]:
    """Identify one physical check independently of its source and rule name."""
    scalar_key = scalar_rule_key(rule)
    if scalar_key is not None:
        target, kind, pair = scalar_key
        maximum, minimum = canonical_scalar_bounds(rule)
        # A lower-only and an upper-only assertion are complementary; both
        # must survive source selection when a PDK writes them separately.
        shape = ("max" if maximum is not None else "", "min" if minimum is not None else "")
        return target, kind, ("voltage", *pair, *shape, "context", *_context(rule))
    return (
        str(rule.effective("target") or rule.target).lower(),
        canonical_limit_kind(str(rule.limit_kind or "other")),
        ("expression", str(rule.effective("expr") or "").strip(), "context", *_context(rule)),
    )


def source_route(rule: Rule) -> str:
    """Map a rule's evidence and lifecycle to a user-facing priority route."""
    status = str(rule.effective("status") or rule.status)
    if status == "confirmed":
        return "user_confirmed"
    if rule.route == "user":
        return "user_defined"
    if rule.route == "adapter":
        return "adapter"
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

    key: Tuple[str, str, Tuple[str, ...]]
    chosen: Optional[Rule]
    candidates: Tuple[Rule, ...]
    route: str = "inference"
    status: str = "missing"
    conflict: bool = False

    @property
    def complete(self) -> bool:
        return self.chosen is not None and _complete(self.chosen)

    def to_dict(self) -> Dict[str, object]:
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
    source_priority: Optional[Iterable[str]] = None,
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
    comparable: Dict[Tuple[str, str, Tuple[str, ...]], Set[Tuple[Optional[str], Optional[str]]]] = {}
    for candidate in ordered:
        if not _complete(candidate):
            continue
        bounds = canonical_scalar_bounds(candidate) if scalar_rule_key(candidate) else (
            _bound(candidate.effective("maximum")), _bound(candidate.effective("minimum"))
        )
        comparable.setdefault(rule_match_key(candidate), set()).add(bounds)
    conflict = any(len(bounds) > 1 for bounds in comparable.values())
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
    source_priority: Optional[Iterable[str]] = None,
) -> Dict[Tuple[str, str, Tuple[str, ...]], ResolvedRule]:
    groups: Dict[Tuple[str, str, Tuple[str, ...]], List[Rule]] = {}
    for rule in rules:
        groups.setdefault(rule_match_key(rule), []).append(rule)
    return {
        key: resolve_rule_group(group, source_priority)
        for key, group in groups.items()
    }

