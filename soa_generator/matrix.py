from __future__ import annotations

from typing import Iterable

from .models import Device, Rule
from .resolution import ResolvedRule, normalize_source_priority, physical_rule_key, resolve_rule_group, resolve_rule_groups, scalar_bounds_in_direction, scalar_rule_key, source_route


_ISOLATION_PORTS = {"iso", "isub", "nbl", "pepi", "hvnwell", "hvbn", "dpw", "ddnw"}


def _port(device: Device, *names: str) -> str | None:
    ports = {port.lower(): port for port in device.ports}
    for name in names:
        if name.lower() in ports:
            return ports[name.lower()]
    return None


def _pair_item(
    device: Device,
    kind: str,
    left_names: tuple[str, ...],
    right_names: tuple[str, ...],
    reason: str,
) -> dict[str, object]:
    left = _port(device, *left_names)
    right = _port(device, *right_names)
    fallback_left = left_names[0]
    fallback_right = right_names[0]
    known_ports = bool(device.ports)
    applicable = bool(left and right) if known_ports else True
    return {
        "limit_kind": kind,
        "pair": [left or fallback_left, right or fallback_right],
        "applicable": applicable,
        "reason": reason if applicable else f"模型端口明确缺少 {fallback_left}/{fallback_right}",
        "status": "not_applicable" if not applicable else "missing",
    }


def _metric_item(device: Device, kind: str, port_names: tuple[str, ...], reason: str) -> dict[str, object]:
    port = _port(device, *port_names)
    applicable = bool(port) if device.ports else True
    return {
        "limit_kind": kind,
        "pair": [port or port_names[0]],
        "applicable": applicable,
        "reason": reason if applicable else f"模型端口明确缺少 {port_names[0]}",
        "status": "not_applicable" if not applicable else "missing",
    }


def _isolation_definitions(device: Device) -> list[dict[str, object]]:
    has_isolation = bool(set(device.topology) & _ISOLATION_PORTS) or bool(set(port.lower() for port in device.ports) & _ISOLATION_PORTS)
    pairs = [
        (("iso",), ("b", "bs", "sub"), "隔离环到体/衬底"),
        (("iso",), ("sub", "psub"), "隔离环到衬底"),
        (("isub",), ("b", "bs", "sub"), "隔离衬底到体端"),
        (("nbl",), ("psub",), "NBL 到 P 衬底"),
        (("nbl",), ("pepi",), "NBL 到 P 外延层"),
        (("nbl",), ("b", "bs"), "NBL 到器件体端"),
        (("nbl",), ("d",), "NBL 到漏极"),
        (("pepi",), ("psub",), "P 外延层到 P 衬底"),
        (("hvnwell", "hvbn", "dpw", "ddnw"), ("b", "bs", "sub"), "高压井到器件体端"),
    ]
    result = []
    for left_names, right_names, reason in pairs:
        left = _port(device, *left_names)
        right = _port(device, *right_names)
        if left and right:
            result.append(_pair_item(device, "isolation_bv", left_names, right_names, reason))
    if not result:
        result.append({
            "limit_kind": "isolation_bv",
            "pair": ["iso/nbl/pepi", "b/bs/psub"],
            "applicable": has_isolation,
            "reason": "隔离拓扑已识别，但模型端口尚未补齐" if has_isolation else "器件没有隔离环、NBL 或外延端口",
            "status": "missing" if has_isolation else "not_applicable",
        })
    return result


def _mos_definitions(device: Device) -> list[dict[str, object]]:
    drain = ("d", "drain")
    source = ("bs", "s", "source") if device.family in {"ldmos", "demos"} else ("s", "source")
    body = ("b", "body", "bs")
    items = [
        _pair_item(device, "Vds", drain, source, "漏源/漏体主耐压"),
        _pair_item(device, "Vgs", ("g", "gate"), source, "栅源/栅体氧化层耐压"),
        _pair_item(device, "Vgd", ("g", "gate"), drain, "栅漏耐压"),
    ]
    body_port = _port(device, *body)
    source_port = _port(device, *source)
    if body_port and source_port and body_port.lower() != source_port.lower():
        items.extend([
            _pair_item(device, "Vbs", body, source, "体源结耐压"),
            _pair_item(device, "Vbd", drain, body, "漏体结耐压"),
            _pair_item(device, "Vgb", ("g", "gate"), body, "栅体耐压"),
            _pair_item(device, "body_diode_forward", source, body, "源体寄生二极管正向导通"),
            _pair_item(device, "body_diode_forward", drain, body, "漏体寄生二极管正向导通"),
        ])
    elif device.family in {"ldmos", "demos"}:
        items.append(_pair_item(device, "body_diode_forward", drain, source, "LDMOS/DEMOS 体二极管正向导通"))
    items.append(_metric_item(device, "current_density", drain, "沟道/漂移区电流密度"))
    return items + _isolation_definitions(device)


def _passive_definitions(device: Device) -> list[dict[str, object]]:
    ports = device.ports
    if device.family == "diode":
        return [
            _pair_item(device, "reverse_voltage", ("p", "pos", "anode"), ("n", "neg", "cathode"), "二极管反向耐压"),
            _pair_item(device, "forward_voltage", ("p", "pos", "anode"), ("n", "neg", "cathode"), "二极管正向导通压降"),
        ]
    if device.family == "resistor":
        first = (ports[0],) if ports else ("n1",)
        second = (ports[1],) if len(ports) > 1 else ("n2",)
        substrate = (ports[2],) if len(ports) > 2 else ("sub",)
        return [
            _pair_item(device, "resistor_terminal_voltage", first, second, "电阻两端工作电压"),
            _pair_item(device, "resistor_substrate_voltage", first, substrate, "电阻端子到衬底耐压"),
            _metric_item(device, "current_density", first, "电阻电流密度/功率限制"),
        ]
    if device.family == "bjt":
        return [
            _pair_item(device, "Vce", ("c", "collector"), ("e", "emitter"), "集电极-发射极耐压"),
            _pair_item(device, "Vcb", ("c", "collector"), ("b", "base"), "集电极-基极耐压"),
            _pair_item(device, "Vbe", ("b", "base"), ("e", "emitter"), "基极-发射极耐压"),
        ]
    if device.family in {"varactor", "capacitor"}:
        first = (ports[0],) if ports else ("top",)
        second = (ports[1],) if len(ports) > 1 else ("bottom",)
        items = [_pair_item(device, "terminal_voltage", first, second, "无源器件端子耐压")]
        if len(ports) >= 3:
            items.append(_pair_item(device, "substrate_voltage", first, (ports[2],), "无源器件端子到衬底耐压"))
        return items
    if device.family == "esd_protection":
        first = (ports[0],) if ports else ("anode",)
        second = (ports[1],) if len(ports) > 1 else ("cathode",)
        return [_pair_item(device, "terminal_voltage", first, second, "保护器件主端子耐压")]
    if len(ports) >= 2 or not ports:
        first = (ports[0],) if ports else ("p1",)
        second = (ports[1],) if len(ports) > 1 else ("p2",)
        return [_pair_item(device, "terminal_voltage", first, second, "未知器件主端子耐压，等待器件族确认")]
    return []


def _definitions(device: Device) -> list[dict[str, object]]:
    if device.family in {"mos", "ldmos", "demos"}:
        return _mos_definitions(device)
    return _passive_definitions(device)


def _matches_for_definition(
    device: Device,
    definition: dict[str, object],
    indexed: dict[tuple[str, tuple[str, ...]], list[Rule]],
    rules: list[Rule],
) -> list[Rule]:
    kind = str(definition["limit_kind"])
    raw_pair = definition["pair"]
    pair = tuple(item.lower() for item in raw_pair) if isinstance(raw_pair, list) else ()
    matches = list(indexed.get((kind, pair), []))
    if len(pair) == 2:
        matches.extend(indexed.get((kind, (pair[1], pair[0])), []))
    if not matches and kind in {"current_density", "temperature", "power_density"}:
        matches = [rule for rule in rules if rule.target.lower() == device.name.lower() and rule.limit_kind == kind]
    if not matches and kind in {"terminal_voltage", "forward_voltage", "reverse_voltage"}:
        matches = [rule for rule in rules if rule.target.lower() == device.name.lower() and rule.limit_kind == kind]
    unique: list[Rule] = []
    seen: set[str] = set()
    for rule in matches:
        if rule.rule_id in seen:
            continue
        seen.add(rule.rule_id)
        unique.append(rule)
    return unique


def build_check_matrix(
    device: Device,
    rules: Iterable[Rule] = (),
    source_priority: list[str] | None = None,
) -> list[dict[str, object]]:
    priority = normalize_source_priority(source_priority)
    rule_list = list(rules)
    indexed: dict[tuple[str, tuple[str, ...]], list[Rule]] = {}
    for rule in rule_list:
        target, kind, pair = physical_rule_key(rule)
        if target != device.name.lower():
            continue
        indexed.setdefault((kind, pair), []).append(rule)
    matrix: list[dict[str, object]] = []
    for index, definition in enumerate(_definitions(device)):
        kind = str(definition["limit_kind"])
        raw_pair = definition["pair"]
        matches = _matches_for_definition(device, definition, indexed, rule_list)
        resolved: ResolvedRule = resolve_rule_group(matches, priority)
        chosen = resolved.chosen
        status = str(definition.get("status", "missing" if definition.get("applicable", True) else "not_applicable"))
        if chosen:
            status = resolved.status
        maximum, minimum = scalar_bounds_in_direction(chosen, raw_pair) if chosen and scalar_rule_key(chosen) else (
            chosen.effective("maximum") if chosen else None,
            chosen.effective("minimum") if chosen else None,
        )
        matrix.append({
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
                    "expr": rule.effective("expr"),
                    "source": rule.source.to_dict() if rule.source else None,
                }
                for rule in resolved.candidates
            ],
            "maximum": maximum,
            "minimum": minimum,
            "rule_ids": [rule.rule_id for rule in resolved.candidates],
            "resolution_groups": [group.to_dict() for group in resolve_rule_groups(matches, priority).values()],
            "conflict": resolved.conflict,
        })
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
