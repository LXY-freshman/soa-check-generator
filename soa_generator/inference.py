from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .models import Confidence, Device, Rule, SourceEvidence


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
    if "hv" in value and three_terminal:
        return 120.0, "工艺手册中的 HV 三端电阻 Vop 指导值约 120 V；这不是原生 SOA 曲线。"
    if three_terminal:
        return 30.0, "工艺手册中的非 HV 三端电阻对衬底偏压指导值约 30 V；这不是原生 SOA 曲线。"
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
) -> Rule:
    value_note = reason
    rule = Rule(
        rule_id=f"inferred:{limit_kind}:{device.name}:{terminal_pair[0]}:{terminal_pair[1]}",
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
        terminal_pair=terminal_pair,
        device_family=device.family,
        confidence="inferred",
        enabled=False,
        source=SourceEvidence(
            path=source_path,
            mechanism="manual_table" if "手册" in reason else "inference",
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
        (rule.target, re.sub(r"\s+", "", rule.expr).lower())
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
        if (device.name, expr.replace(" ", "").lower()) in existing:
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
                limit_kind = "reverse_voltage" if family == "diode" else "terminal_voltage"
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
        source = device.source.path if device.source else source_path
        pairs = [(left, right)]
        if family == "resistor" and limit_kind == "resistor_substrate_voltage" and len(device.ports) >= 3:
            substrate = device.ports[2]
            pairs = [(device.ports[0], substrate), (device.ports[1], substrate)]
        for pair_left, pair_right in pairs:
            pair_expr = f"v({pair_left},{pair_right})"
            if (device.name, pair_expr.replace(" ", "").lower()) in existing:
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
    existing = {(rule.target, re.sub(r"\s+", "", rule.expr).lower()) for rule in existing_rules}
    candidates: list[Rule] = []
    for device in devices:
        source = device.source.path if device.source else source_path
        for item in device.model_limits:
            value = _numeric_value(item.get("value", ""))
            left, right = item.get("left", ""), item.get("right", "")
            if value is None or not left or not right:
                continue
            expr = f"v({left},{right})"
            if (device.name, expr.replace(" ", "").lower()) in existing:
                continue
            key = item.get("key", "model_limit")
            reason = f"Spectre 模型参数 {key}={value:g} 来自 {item.get('primitive', 'primitive')} 的端口 {left}/{right}；候选仍需确认是否为最终 SOA 上限。"
            candidates.append(
                _candidate(
                    device,
                    name=f"candidate_{device.name}_{key}_{left}_{right}",
                    expr=expr,
                    limit_kind=_model_limit_kind(left, right),
                    maximum=f"{value:g}",
                    minimum=f"{-value:g}",
                    reason=reason,
                    source_path=source,
                    terminal_pair=[left, right],
                )
            )
            existing.add((device.name, expr.replace(" ", "").lower()))
        if device.family not in {"mos", "ldmos", "demos"}:
            continue
        ports = {port.lower(): port for port in device.ports}
        fallback_pairs = []
        if ports.get("d") and ports.get("s"):
            fallback_pairs.append((ports["d"], ports["s"], "Vds"))
        if ports.get("g") and ports.get("s"):
            fallback_pairs.append((ports["g"], ports["s"], "Vgs"))
        if ports.get("b") and ports.get("s"):
            fallback_pairs.append((ports["b"], ports["s"], "Vbs"))
        if ports.get("g") and ports.get("d"):
            fallback_pairs.append((ports["g"], ports["d"], "Vgd"))
        if ports.get("d") and ports.get("b"):
            fallback_pairs.append((ports["d"], ports["b"], "Vbd"))
        if ports.get("g") and ports.get("b"):
            fallback_pairs.append((ports["g"], ports["b"], "Vgb"))
        value = device.family_voltage * (1.0 + margin) if device.family_voltage is not None else None
        for left, right, limit_kind in fallback_pairs:
            expr = f"v({left},{right})"
            if (device.name, expr.replace(" ", "").lower()) in existing:
                continue
            if value is None:
                reason = f"Spectre 模型未提供 {limit_kind} 数值上限，保留空白检查等待用户填写。"
                status = "missing"
                route = "missing"
            else:
                reason = f"Spectre 模型未提供 {limit_kind} 数值上限，按器件族电压 {device.family_voltage:g} V 加 {margin:.0%} 裕量生成候选；这不是 SOA 曲线。"
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
            existing.add((device.name, expr.replace(" ", "").lower()))
    return candidates
