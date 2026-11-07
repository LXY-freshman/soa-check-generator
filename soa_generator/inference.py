from __future__ import annotations

from dataclasses import dataclass

from .models import Confidence, Device, Rule


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
