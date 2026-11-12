from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Union
from typing import Iterable

from .models import Device, Rule
from .topology import ISOLATION_PORTS, isolation_connections
from .resolution import ResolvedRule, normalize_source_priority, physical_rule_key, resolve_rule_group, resolve_rule_groups, scalar_bounds_in_direction, scalar_rule_key, source_route


def _port(device: Device, *names: str) -> Optional[str]:
    ports = {port.lower(): port for port in device.ports}
    for name in names:
        if name.lower() in ports:
            return ports[name.lower()]
    return None


def _pair_item(
    device: Device,
    kind: str,
    left_names: Tuple[str, ...],
    right_names: Tuple[str, ...],
    reason: str,
) -> Dict[str, object]:
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


def _metric_item(device: Device, kind: str, port_names: Tuple[str, ...], reason: str) -> Dict[str, object]:
    port = _port(device, *port_names)
    applicable = bool(port) if device.ports else True
    return {
        "limit_kind": kind,
        "pair": [port or port_names[0]],
        "applicable": applicable,
        "reason": reason if applicable else f"模型端口明确缺少 {port_names[0]}",
        "status": "not_applicable" if not applicable else "missing",
    }


def _isolation_definitions(device: Device) -> List[Dict[str, object]]:
    has_isolation = bool(set(token.lower() for token in device.topology) & ISOLATION_PORTS) or bool(set(port.lower() for port in device.ports) & ISOLATION_PORTS)
    result = [
        {"limit_kind": connection.limit_kind, "pair": [connection.left, connection.right],
         "applicable": True, "status": "missing", "reason": connection.description,
         "isolation_side": connection.side, "structure_confirmed": connection.verified}
        for connection in isolation_connections(device)
    ]
    if result and device.isolation_type != "dielectric" and not any(item["isolation_side"] == "outer" for item in result):
        result.append({"limit_kind": "isolation_bv", "pair": ["隔离层", "PSUB/大衬底（节点待确认）"],
                       "isolation_side": "outer", "applicable": True, "status": "missing",
                       "reason": "外侧大衬底节点未确认或未暴露；保留覆盖缺口，不导出虚构 PSUB 表达式。"})
    if not result:
        result.append({
            "limit_kind": "isolation_bv",
            "pair": ["iso/nbl/pepi", "b/bs/psub"],
            "reason": "介质隔离：不套用 PN 结耐压/正向导通规则，需独立介质规格" if device.isolation_type == "dielectric" else "隔离拓扑已识别，但模型端口尚未补齐" if has_isolation else "器件没有隔离环、NBL 或外延端口",
            "status": "missing" if has_isolation and device.isolation_type != "dielectric" else "not_applicable",
            "applicable": has_isolation and device.isolation_type != "dielectric",
        })
    return result


def _mos_definitions(device: Device) -> List[Dict[str, object]]:
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
    return items


def _passive_definitions(device: Device) -> List[Dict[str, object]]:
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


def _definitions(device: Device) -> List[Dict[str, object]]:
    if device.family in {"mos", "ldmos", "demos"}:
        return _mos_definitions(device) + _isolation_definitions(device)
    items = _passive_definitions(device)
    if device.isolation_junctions or set(device.topology) & ISOLATION_PORTS or any(port.lower() in ISOLATION_PORTS for port in device.ports):
        items.extend(_isolation_definitions(device))
    return items


def _matches_for_definition(
    device: Device,
    definition: Dict[str, object],
    indexed: Dict[Tuple[str, Tuple[str, ...]], List[Rule]],
    rules: List[Rule],
) -> List[Rule]:
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
    unique: List[Rule] = []
    seen: Set[str] = set()
    for rule in matches:
        if rule.rule_id in seen:
            continue
        seen.add(rule.rule_id)
        unique.append(rule)
    return unique


def build_check_matrix(
    device: Device,
    rules: Iterable[Rule] = (),
    source_priority: Optional[List[str]] = None,
) -> List[Dict[str, object]]:
    priority = normalize_source_priority(source_priority)
    rule_list = list(rules)
    indexed: Dict[Tuple[str, Tuple[str, ...]], List[Rule]] = {}
    for rule in rule_list:
        target, kind, pair = physical_rule_key(rule)
        if target != device.name.lower():
            continue
        indexed.setdefault((kind, pair), []).append(rule)
    matrix: List[Dict[str, object]] = []
    definitions = _definitions(device)
    for rule in rule_list:
        if rule.target != device.name or rule.limit_kind != "isolation_constraint":
            continue
        pair = list(rule.terminal_pair)
        if not any(item["limit_kind"] == "isolation_constraint" and item["pair"] == pair for item in definitions):
            definitions.append({"limit_kind": "isolation_constraint", "pair": pair, "applicable": True,
                                "status": "missing", "reason": "工艺资料指定的同电位或复合寄生路径约束"})
    for index, definition in enumerate(definitions):
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
            "isolation_side": str(definition.get("isolation_side", "")),
            "structure_confirmed": bool(definition.get("structure_confirmed", False)),
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


def refresh_profiles(devices: Iterable[Device], rules: Iterable[Rule], source_priority: Optional[List[str]] = None) -> None:
    rules_by_target: Dict[str, List[Rule]] = {}
    for rule in rules:
        rules_by_target.setdefault(rule.target, []).append(rule)
    for device in devices:
        device.check_matrix = build_check_matrix(device, rules_by_target.get(device.name, []), source_priority)
        applicable = [item for item in device.check_matrix if item["applicable"]]
        complete = [item for item in applicable if item["status"] in {"source", "confirmed"} and (item["maximum"] is not None or item["minimum"] is not None)]
        device.profile_completeness = round((len(complete) / len(applicable)) * 100, 1) if applicable else 100.0
        device.profile_stage = "ready" if device.ports and device.profile_completeness == 100.0 else "enriched" if device.ports else "skeleton"
