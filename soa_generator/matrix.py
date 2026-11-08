from __future__ import annotations

from typing import Iterable

from .models import Device, Rule
from .resolution import DEFAULT_SOURCE_PRIORITY, ResolvedRule, normalize_source_priority, resolve_rule_group, rule_match_key, source_route


def _definitions(device: Device) -> list[dict[str, object]]:
    ports = {port.lower(): port for port in device.ports}
    family = device.family
    items: list[dict[str, object]] = []
    if family in {"mos", "ldmos", "demos"}:
        pairs = [("Vds", "d", "s"), ("Vgs", "g", "s"), ("Vbs", "b", "s"),
                 ("Vgd", "g", "d"), ("Vbd", "d", "b"), ("Vgb", "g", "b")]
        for kind, left, right in pairs:
            if left in ports and right in ports:
                items.append({"limit_kind": kind, "pair": [ports[left], ports[right]], "applicable": True, "reason": "模型端口已识别"})
            elif device.ports:
                items.append({"limit_kind": kind, "pair": [left, right], "applicable": False, "reason": f"缺少端口 {left}/{right}", "status": "not_applicable"})
            else:
                items.append({"limit_kind": kind, "pair": [left, right], "applicable": True, "reason": "器件档案尚未补齐模型端口"})
        isolation_tokens = {"iso", "isub", "nbl", "psub", "pepi", "hvnwell", "hvbn", "dpw", "ddnw"}
        has_isolation = bool(set(device.topology) & isolation_tokens) or bool(isolation_tokens & set(ports))
        isolation_pairs = [("isolation_bv", "iso", "b"), ("isolation_bv", "iso", "sub"),
                           ("isolation_bv", "isub", "b"), ("isolation_bv", "nbl", "psub"),
                           ("isolation_bv", "pepi", "psub")]
        for kind, left, right in isolation_pairs:
            if left in ports and right in ports:
                items.append({"limit_kind": kind, "pair": [ports[left], ports[right]], "applicable": True, "reason": "隔离/寄生端口已识别"})
        if not any(item["limit_kind"] == "isolation_bv" for item in items):
            items.append({"limit_kind": "isolation_bv", "pair": ["iso/nbl/pepi", "b/sub/psub"], "applicable": has_isolation, "reason": "未识别隔离端口" if not has_isolation else "隔离端口尚未补齐", "status": "not_applicable" if not has_isolation else "missing"})
    elif family == "diode":
        pair = [ports.get("pos") or ports.get("p") or "pos", ports.get("neg") or ports.get("n") or "neg"]
        items.append({"limit_kind": "reverse_voltage", "pair": pair, "applicable": True, "reason": "二极管反向耐压" if device.ports else "二极管端口待确认"})
    elif family == "resistor":
        if len(device.ports) >= 2:
            items.append({"limit_kind": "resistor_terminal_voltage", "pair": device.ports[:2], "applicable": True, "reason": "电阻端子电压"})
        if len(device.ports) >= 3:
            items.append({"limit_kind": "resistor_substrate_voltage", "pair": [device.ports[0], device.ports[2]], "applicable": True, "reason": "三端电阻对衬底"})
    elif family in {"bjt", "esd_protection"}:
        items.append({"limit_kind": "terminal_voltage", "pair": [ports.get("c", "c"), ports.get("e", "e")], "applicable": True, "reason": "BJT 集电极-发射极" if family == "bjt" else "保护器件主端子"})
    elif family in {"varactor", "capacitor"}:
        items.append({"limit_kind": "terminal_voltage", "pair": device.ports[:2] if len(device.ports) >= 2 else ["top", "bottom"], "applicable": True, "reason": "无源器件端子耐压"})
    return items


def build_check_matrix(
    device: Device,
    rules: Iterable[Rule] = (),
    source_priority: list[str] | None = None,
) -> list[dict[str, object]]:
    priority = normalize_source_priority(source_priority)
    indexed: dict[tuple[str, tuple[str, ...]], list[Rule]] = {}
    for rule in rules:
        target, kind, pair = rule_match_key(rule)
        if target != device.name.lower():
            continue
        key = (kind, pair)
        indexed.setdefault(key, []).append(rule)
    matrix: list[dict[str, object]] = []
    for index, definition in enumerate(_definitions(device)):
        kind = str(definition["limit_kind"])
        raw_pair = definition["pair"]
        pair = tuple(item.lower() for item in raw_pair) if isinstance(raw_pair, list) and len(raw_pair) == 2 else ()
        matches = indexed.get((kind, pair), [])
        if not matches and kind == "terminal_voltage":
            matches = [rule for rule in rules if rule.target == device.name and rule.limit_kind == kind]
        resolved: ResolvedRule = resolve_rule_group(matches, priority)
        chosen = resolved.chosen
        status = str(definition.get("status", "missing" if definition.get("applicable", True) else "not_applicable"))
        if chosen:
            status = resolved.status
        item: dict[str, object] = {
            "matrix_id": f"{device.name}:{kind}:{index}",
            "name": kind,
            "limit_kind": kind,
            "terminal_pair": list(raw_pair) if isinstance(raw_pair, list) else [],
            "applicable": bool(definition.get("applicable", True)),
            "status": status,
            "reason": str(definition.get("reason", "")),
            "route": resolved.route if chosen else "inference",
            "source": chosen.source.to_dict() if chosen and chosen.source else None,
            "source_candidates": [
                {
                    "rule_id": rule.rule_id,
                    "route": source_route(rule),
                    "status": rule.effective("status"),
                    "confidence": rule.confidence,
                    "enabled": rule.effective("enabled"),
                    "maximum": rule.effective("maximum"),
                    "minimum": rule.effective("minimum"),
                    "source": rule.source.to_dict() if rule.source else None,
                }
                for rule in resolved.candidates
            ],
            "maximum": chosen.effective("maximum") if chosen else None,
            "minimum": chosen.effective("minimum") if chosen else None,
            "rule_ids": [rule.rule_id for rule in resolved.candidates],
            "conflict": resolved.conflict,
        }
        matrix.append(item)
    return matrix


def refresh_profiles(devices: Iterable[Device], rules: Iterable[Rule], source_priority: list[str] | None = None) -> None:
    rules_by_target: dict[str, list[Rule]] = {}
    for rule in rules:
        rules_by_target.setdefault(rule.target, []).append(rule)
    for device in devices:
        device.check_matrix = build_check_matrix(device, rules_by_target.get(device.name, []), source_priority)
        applicable = [item for item in device.check_matrix if item["applicable"]]
        complete = [item for item in applicable if item["status"] in {"source", "confirmed"} and (item["maximum"] is not None or item["minimum"] is not None)]
        device.profile_completeness = round((len(complete) / len(applicable)) * 100, 1) if applicable else 100.0
        device.profile_stage = "ready" if device.ports and device.profile_completeness == 100.0 else "enriched" if device.ports else "skeleton"
