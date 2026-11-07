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
        if family == "resistor":
            value, reason = _named_resistor_limit(device, three_terminal_resistor)
            limit_kind = "resistor_substrate_voltage" if three_terminal_resistor else "resistor_terminal_voltage"
        elif device.family_voltage is not None:
            value = device.family_voltage * (1.0 + margin)
            reason = f"{family} 缺少原生 SOA，按器件族电压 {device.family_voltage:g} V 加 {margin:.0%} 经验裕量。"
            limit_kind = "reverse_voltage" if family == "diode" else "terminal_voltage"
            minimum = f"{-value:g}"
        else:
            continue
        if value is None:
            continue
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
                    maximum=f"{value:g}",
                    minimum=minimum,
                    reason=reason,
                    source_path=source,
                    terminal_pair=[pair_left, pair_right],
                )
            )
    return candidates
