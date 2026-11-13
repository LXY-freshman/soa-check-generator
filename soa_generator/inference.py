from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .models import Confidence, Device, Rule, SourceEvidence
from .classify import classify_limit
from .resolution import expression_measurement_key


DEFAULT_UNIT_WIDTH_CURRENT = "10uA/um"


@dataclass
class InferenceResult:
    value: str
    confidence: Confidence
    reason: str
    margin: float | None = None


def apply_margin(nominal: float, margin: float = 0.10, polarity: int = 1) -> InferenceResult:
    value = polarity * nominal * (1.0 + margin)
    return InferenceResult(
        value=f"{value:g}",
        confidence="inferred",
        reason=f"nominal value {nominal:g} with configured margin {margin:.1%}",
        margin=margin,
    )


def infer_terminal_limit(device: Device, terminal: str, margin: float = 0.10) -> InferenceResult | None:
    if device.family_voltage is None:
        return None
    # This is deliberately a candidate only. Existing source rules and manual
    # tables must override it before export.
    return apply_margin(device.family_voltage, margin=margin)


def mark_inferred(rule: Rule, reason: str) -> Rule:
    rule.confidence = "inferred"
    rule.notes.append(reason)
    return rule


def _port_pair(device: Device) -> tuple[str, str] | None:
    if len(device.ports) < 2:
        return None
    return device.ports[0], device.ports[1]


def _bjt_pair(device: Device) -> tuple[str, str] | None:
    ports = {port.lower(): port for port in device.ports}
    collector = ports.get("c") or ports.get("collector")
    emitter = ports.get("e") or ports.get("eb") or ports.get("emitter")
    if collector and emitter:
        return collector, emitter
    return _port_pair(device)


def _named_resistor_limit(device: Device, three_terminal: bool) -> tuple[float | None, str]:
    value = device.name.lower()
    if "high" in value and three_terminal:
        return 120.0, "适配器或手册提供的高压三端电阻 Vop 指导值；这不是原生 SOA 曲线。"
    if three_terminal:
        return 30.0, "适配器或手册提供的普通三端电阻对衬底偏压指导值；这不是原生 SOA 曲线。"
    if device.family_voltage is not None:
        return device.family_voltage * 1.10, "器件命名或工艺族电压乘以 10% 经验裕量。"
    return None, "缺少电阻工作电压或手册上限，不能安全生成数值候选。"


def _numeric_parameter(device: Device, names: tuple[str, ...]) -> tuple[float, str] | None:
    for name in names:
        raw = device.model_parameters.get(name)
        if raw is None:
            continue
        value = raw.strip().strip("()")
        if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value):
            return float(value), name
    return None


def _raw_parameter(device: Device, names: tuple[str, ...]) -> tuple[str, str] | None:
    for name in names:
        raw = device.model_parameters.get(name)
        if raw is not None and str(raw).strip():
            return str(raw).strip(), name
    return None


def _unit_width_expression(device: Device, current_port: str) -> tuple[str, str]:
    """Build a transparent Id/Weff expression from model-visible geometry.

    Spectre model wrappers often keep ``w`` symbolic and add ``nf``/``m`` on
    the primitive instance. Keep those expressions intact so users can review
    the normalization instead of receiving a guessed numeric area.
    """
    for item in device.geometry_candidates:
        width = item.get("w")
        if width in (None, ""):
            continue
        nf = item.get("nf") or "1"
        multiplier = item.get("m") or "1"
        width_expr = f"({width})*({nf})*({multiplier})"
        return f"abs(I({current_port}))/({width_expr})", f"Weff=({width_expr})"
    return f"abs(I({current_port}))/Weff", "缺少模型实例 w/nf/m，Weff 需用户或适配器补充"


def _candidate(
    device: Device,
    *,
    name: str,
    expr: str,
    limit_kind: str,
    maximum: str | None,
    minimum: str | None = None,
    reason: str,
    source_path: str,
    terminal_pair: list[str],
    status: str = "inferred",
    route: str = "inference",
    mechanism: str | None = None,
    measurement: str = "unknown",
) -> Rule:
    value_note = reason
    pair_id = ":".join(terminal_pair) or "unknown"
    rule = Rule(
        rule_id=f"inferred:{limit_kind}:{device.name}:{pair_id}",
        name=name,
        target=device.name,
        target_kind="sub",
        expr=expr,
        maximum=maximum,
        minimum=minimum,
        message=f"SOA Warning - {device.name} {limit_kind} candidate exceeded",
        level="warning",
        duration="t_trans_hv",
        section="soa_generated",
        limit_kind=limit_kind,
        measurement=measurement,
        terminal_pair=terminal_pair,
        device_family=device.family,
        confidence="inferred",
        enabled=False,
        source=SourceEvidence(
            path=source_path,
            mechanism=mechanism or ("manual_table" if "手册" in reason else "inference"),
            note=value_note,
        ),
        notes=[value_note, "非原生 SOA 候选，默认关闭；请用工艺手册、模型参数或实测数据确认后再启用。"],
        status=status,
        route=route,
    )
    rule.original = rule.to_dict()
    return rule


def non_mos_rule_candidates(
    devices: Iterable[Device],
    existing_rules: Iterable[Rule],
    source_path: str = "<inferred>",
    margin: float = 0.10,
) -> list[Rule]:
    """Build disabled candidates for passive/protection families.

    These are deliberately conservative. A candidate is emitted only when a
    model terminal pair and a numeric process/name clue are available.
    """
    existing = {
        expression_measurement_key(str(rule.effective("target")), str(rule.effective("expr") or ""))
        for rule in existing_rules
    }
    existing_kinds = {
        (*expression_measurement_key(str(rule.effective("target")), str(rule.effective("expr") or "")), rule.limit_kind)
        for rule in existing_rules
    }
    candidates: list[Rule] = []
    for device in devices:
        family = device.family
        if family not in {"resistor", "diode", "varactor", "capacitor", "bjt", "esd_protection"}:
            continue
        pair = _bjt_pair(device) if family == "bjt" else _port_pair(device)
        if not pair:
            continue
        left, right = pair
        three_terminal_resistor = family == "resistor" and len(device.ports) >= 3 and (
            "3t" in device.name.lower()
            or device.ports[2].lower() in {"sx", "sub", "psub", "bulk", "b"}
        )
        expr = f"v({left},{right})"
        existing_expr = expression_measurement_key(device.name, expr) in existing
        if existing_expr and family != "diode":
            continue
        value: float | None
        reason: str
        limit_kind: str
        minimum: str | None = None
        candidate_status = "inferred"
        if family == "resistor":
            value, reason = _named_resistor_limit(device, three_terminal_resistor)
            limit_kind = "resistor_substrate_voltage" if three_terminal_resistor else "resistor_terminal_voltage"
            if value is None:
                candidate_status = "missing"
        else:
            model_names = ("bv", "vb", "vbreakdown", "breakdown") if family in {"diode", "bjt", "esd_protection"} else ("bv_max", "vbreakdown", "breakdown")
            model_value = _numeric_parameter(device, model_names)
            if model_value:
                value, parameter_name = model_value
                reason = f"模型参数 {parameter_name}={value:g} 提供端子耐压线索；仍需确认它是否对应当前器件端口。"
                limit_kind = "reverse_voltage" if family == "diode" else "Vce" if family == "bjt" else "terminal_voltage"
            elif device.family_voltage is not None:
                value = device.family_voltage * (1.0 + margin)
                reason = f"{family} 缺少模型耐压参数，按器件族电压 {device.family_voltage:g} V 加 {margin:.0%} 经验裕量。"
                limit_kind = "reverse_voltage" if family == "diode" else "terminal_voltage"
            else:
                value = None
                reason = f"{family} 没有模型耐压或器件族电压，保留空白端子检查等待用户填写。"
                limit_kind = "reverse_voltage" if family == "diode" else "terminal_voltage"
                candidate_status = "missing"
            if value is not None:
                minimum = f"{-value:g}"
            if family == "diode":
                forward_value = _numeric_parameter(device, ("fv_max",))
                forward_key = (*expression_measurement_key(device.name, expr), "forward_voltage")
                if forward_value and forward_key not in existing_kinds:
                    forward, parameter_name = forward_value
                    candidates.append(
                        _candidate(
                            device,
                            name=f"candidate_{device.name}_forward_voltage_{left}_{right}",
                            expr=expr,
                            limit_kind="forward_voltage",
                            maximum=f"{forward:g}",
                            reason=f"模型参数 {parameter_name}={forward:g} 提供二极管正向压降线索；仍需确认测试条件。",
                            source_path=device.source.path if device.source else source_path,
                            terminal_pair=[left, right],
                        )
                    )
            if existing_expr:
                continue
        source = device.source.path if device.source else source_path
        pairs = [(left, right)]
        if family == "resistor" and limit_kind == "resistor_substrate_voltage" and len(device.ports) >= 3:
            substrate = device.ports[2]
            pairs = [(device.ports[0], substrate), (device.ports[1], substrate)]
        for pair_left, pair_right in pairs:
            pair_expr = f"v({pair_left},{pair_right})"
            if expression_measurement_key(device.name, pair_expr) in existing:
                continue
            candidates.append(
                _candidate(
                    device,
                    name=f"candidate_{device.name}_{limit_kind}_{pair_left}_{pair_right}",
                    expr=pair_expr,
                    limit_kind=limit_kind,
                    maximum=f"{value:g}" if value is not None else None,
                    minimum=minimum,
                    reason=reason,
                    source_path=source,
                    terminal_pair=[pair_left, pair_right],
                    status=candidate_status,
                    route="inference" if candidate_status == "inferred" else "missing",
                )
            )
    return candidates


def _model_limit_kind(left: str, right: str) -> str:
    kind = classify_limit(f"v({left},{right})")
    if kind != "other":
        return kind
    pair = {left.lower(), right.lower()}
    if pair == {"d", "s"}:
        return "Vds"
    if pair == {"g", "s"}:
        return "Vgs"
    if pair == {"g", "b"} or pair == {"g", "bs"}:
        return "Vgb"
    if pair == {"d", "b"} or pair == {"d", "bs"}:
        return "Vbd"
    if pair == {"s", "b"} or pair == {"s", "bs"}:
        return "Vbs"
    if pair in ({"c", "e"}, {"collector", "emitter"}):
        return "Vce"
    if pair in ({"c", "b"}, {"collector", "base"}):
        return "Vcb"
    if pair in ({"b", "e"}, {"base", "emitter"}):
        return "Vbe"
    if pair in ({"p", "n"}, {"pos", "neg"}, {"anode", "cathode"}):
        return "reverse_voltage"
    return "terminal_voltage"


def _numeric_value(raw: str) -> float | None:
    value = raw.strip().strip("()")
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value):
        return float(value)
    return None


def model_rule_candidates(
    devices: Iterable[Device],
    existing_rules: Iterable[Rule],
    source_path: str = "<inferred>",
    margin: float = 0.10,
) -> list[Rule]:
    """Turn Spectre model safety parameters and MOS voltage names into candidates."""
    existing = {
        (expression_measurement_key(str(rule.effective("target")), str(rule.effective("expr") or "")), rule.limit_kind)
        for rule in existing_rules
    }
    candidates: list[Rule] = []
    for device in devices:
        source = device.source.path if device.source else source_path
        for item in device.model_limits:
            value = _numeric_value(item.get("value", ""))
            left, right = item.get("left", ""), item.get("right", "")
            if value is None or not left or not right:
                continue
            expr = f"v({left},{right})"
            kind = _model_limit_kind(left, right)
            if (expression_measurement_key(device.name, expr), kind) in existing:
                continue
            key = item.get("key", "model_limit")
            reason = f"Spectre 模型参数 {key}={value:g} 来自 {item.get('primitive', 'primitive')} 的端口 {left}/{right}；候选仍需确认是否为最终 SOA 上限。"
            candidates.append(
                _candidate(
                    device,
                    name=f"candidate_{device.name}_{key}_{left}_{right}",
                    expr=expr,
                    limit_kind=kind,
                    maximum=f"{value:g}",
                    minimum=f"{-value:g}",
                    reason=reason,
                    source_path=source,
                    terminal_pair=[left, right],
                )
            )
            existing.add((expression_measurement_key(device.name, expr), kind))
        if device.family in {"mos", "ldmos", "demos", "resistor"}:
            ports = {port.lower(): port for port in device.ports}
            current_port = ports.get("d") or ports.get("n1") or (device.ports[0] if device.ports else None)
            model_value = _raw_parameter(device, ("jmax", "current_density"))
            if current_port and (device.family in {"mos", "ldmos", "demos"} or model_value) and not any(
                rule.target.lower() == device.name.lower() and rule.limit_kind == "current_density"
                for rule in existing_rules
            ):
                expr, geometry_note = _unit_width_expression(device, current_port)
                if model_value:
                    value, parameter_name = model_value
                    reason = (
                        f"模型参数 {parameter_name}={value} 被解释为单位栅宽电流候选；"
                        f"{geometry_note}；仍需确认 PDK 单位和温度条件。"
                    )
                    maximum = value
                    route = "model_spectre"
                    mechanism = "model_internal"
                    candidate_source = source
                else:
                    reason = (
                        f"用户参考单位栅宽电流 {DEFAULT_UNIT_WIDTH_CURRENT}；{geometry_note}；"
                        "不是工艺文档已确认值，需确认适用器件、温度和持续时间。"
                    )
                    maximum = DEFAULT_UNIT_WIDTH_CURRENT
                    route = "inference"
                    mechanism = "inference"
                    candidate_source = "用户参考"
                status = "inferred" if device.geometry_candidates else "missing"
                candidates.append(
                    _candidate(
                        device,
                        name=f"candidate_{device.name}_current_density_{current_port}",
                        expr=expr,
                        limit_kind="current_density",
                        maximum=maximum,
                        reason=reason,
                        source_path=candidate_source,
                        terminal_pair=[current_port],
                        status=status,
                        route=route,
                        mechanism=mechanism,
                        measurement="unit_width_current",
                    )
                )
        if device.family not in {"mos", "ldmos", "demos"}:
            continue
        ports = {port.lower(): port for port in device.ports}
        source_port = ports.get("s") or ports.get("bs")
        body_port = ports.get("b") or ports.get("body")
        separate_body = bool(body_port and (not source_port or body_port.lower() != source_port.lower()))
        fallback_pairs = []
        if ports.get("d") and source_port:
            fallback_pairs.append((ports["d"], source_port, "Vds"))
        if ports.get("g") and source_port:
            fallback_pairs.append((ports["g"], source_port, "Vgs"))
        if separate_body and source_port:
            fallback_pairs.append((body_port, source_port, "Vbs"))
        if ports.get("g") and ports.get("d"):
            fallback_pairs.append((ports["g"], ports["d"], "Vgd"))
        if ports.get("d") and separate_body:
            fallback_pairs.append((ports["d"], body_port, "Vbd"))
        if ports.get("g") and separate_body:
            fallback_pairs.append((ports["g"], body_port, "Vgb"))
        for left, right, limit_kind in fallback_pairs:
            expr = f"v({left},{right})"
            nominal = device.gate_voltage if limit_kind in {"Vgs", "Vgd", "Vgb"} else device.family_voltage
            value = nominal * (1.0 + margin) if nominal is not None else None
            if (expression_measurement_key(device.name, expr), limit_kind) in existing:
                continue
            if value is None:
                reason = f"Spectre 模型未提供 {limit_kind} 数值上限，保留空白检查等待用户填写。"
                status = "missing"
                route = "missing"
            else:
                voltage_label = "栅极名义电压" if limit_kind in {"Vgs", "Vgd", "Vgb"} else "器件族电压"
                reason = f"Spectre 模型未提供 {limit_kind} 数值上限，按{voltage_label} {nominal:g} V 加 {margin:.0%} 裕量生成候选；这不是 SOA 曲线。"
                status = "inferred"
                route = "inference"
            candidates.append(
                _candidate(
                    device,
                    name=f"candidate_{device.name}_{limit_kind}_family_voltage",
                    expr=expr,
                    limit_kind=limit_kind,
                    maximum=f"{value:g}" if value is not None else None,
                    minimum=f"{-value:g}" if value is not None else None,
                    reason=reason,
                    source_path=source,
                    terminal_pair=[left, right],
                    status=status,
                    route=route,
                )
            )
            existing.add((expression_measurement_key(device.name, expr), limit_kind))
    return candidates
