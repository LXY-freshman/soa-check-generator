"""Conservative extraction of explicit device limits from process documents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .classify import terminal_pair
from .models import Device, Rule, SourceEvidence


_KIND_RE = re.compile(r"\b(?P<kind>V(?:ds|gs|gd|gb|bs|bd|ce|cb|be)|isolation[_ -]?bv|reverse[_ -]?voltage|forward[_ -]?voltage|current[_ -]?density)\b", re.I)
_NUMBER_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_VALUE_RE = re.compile(rf"(?P<value>{_NUMBER_RE})\s*(?P<unit>V|mV|uA\s*/\s*um|mA\s*/\s*um)?\b", re.I)
_DEVICE_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*(?:_ckt|_mac|_t|_iso|_ls|_hs)?\b")


def _kind(value: str) -> str:
    normalized = value.lower().replace("-", "_").replace(" ", "_")
    return {
        "vds": "Vds",
        "vgs": "Vgs",
        "vgd": "Vgd",
        "vgb": "Vgb",
        "vbs": "Vbs",
        "vbd": "Vbd",
        "vce": "Vce",
        "vcb": "Vcb",
        "vbe": "Vbe",
        "isolation_bv": "isolation_bv",
        "reverse_voltage": "reverse_voltage",
        "forward_voltage": "forward_voltage",
        "current_density": "current_density",
    }.get(normalized, value)


def _number(value: str, unit: str | None) -> str:
    if not unit or unit.lower() == "v":
        return value
    normalized = unit.replace(" ", "").lower()
    if normalized == "mv":
        return f"{float(value) / 1000:g}"
    return f"{value}{unit.replace(' ', '')}"


def _device_for_line(line: str, devices: dict[str, Device]) -> tuple[str, Device | None]:
    for name in sorted(devices, key=len, reverse=True):
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", line, re.I):
            return name, devices[name]
    for match in _DEVICE_TOKEN_RE.finditer(line):
        token = match.group(0)
        lower = token.lower()
        if any(lower.startswith(prefix) for prefix in ("n", "p", "r", "d", "q", "m", "c", "esd")) and (
            "_" in token or re.search(r"\d", token)
        ):
            return token, None
    return "", None


def _pair_for_kind(device: Device | None, kind: str) -> list[str]:
    roles = device.port_roles if device else {}
    ports = {port.lower(): port for port in (device.ports if device else [])}

    def find(*role_names: str) -> str | None:
        for port, role in roles.items():
            if role in role_names:
                return port
        for name in role_names:
            if name in ports:
                return ports[name]
        return None

    source = find("source", "body_source") or "s"
    body = find("body") or "b"
    drain = find("drain") or "d"
    gate = find("gate") or "g"
    if kind == "Vds":
        return [drain, source]
    if kind == "Vgs":
        return [gate, source]
    if kind == "Vgd":
        return [gate, drain]
    if kind == "Vgb":
        return [gate, body]
    if kind == "Vbs":
        return [body, source]
    if kind == "Vbd":
        return [drain, body]
    if kind == "Vce":
        return [find("collector") or "c", find("emitter") or "e"]
    if kind == "Vcb":
        return [find("collector") or "c", find("body") or "b"]
    if kind == "Vbe":
        return [find("body") or "b", find("emitter") or "e"]
    if kind == "isolation_bv":
        nbl = find("isolation_nbl", "isolation_ring", "isolation_well") or "nbl"
        substrate = find("bulk_substrate") or "psub"
        return [nbl, substrate]
    if kind == "current_density":
        return [drain]
    return terminal_pair(f"v({drain},{source})")


def _value_after(fragment: str) -> tuple[str, str | None] | None:
    match = _VALUE_RE.search(fragment)
    if not match:
        return None
    return _number(match.group("value"), match.group("unit")), match.group("unit")


def parse_manual_rules(
    text: str,
    source_path: str,
    devices: Iterable[Device] = (),
) -> list[Rule]:
    """Extract only explicit, line-local manual limits.

    Curves, typical values, and family ranges are intentionally ignored. A
    user can add those as an adapter rule after reviewing the source.
    """
    known = {device.name: device for device in devices}
    rules: list[Rule] = []
    for page_number, page_text in enumerate(text.split("\f"), 1):
        for line_number, raw in enumerate(page_text.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith(("#", "//", "*")):
                continue
            device_name, device = _device_for_line(line, known)
            if not device_name:
                continue
            kind_match = _KIND_RE.search(line)
            kind = _kind(kind_match.group("kind")) if kind_match else ""
            if not kind:
                lowered = line.lower()
                if re.search(r"gate(?:[- ]to[- ](?:body|source))?.{0,40}\b(?:rating|limit|耐压)", lowered):
                    kind = "Vgs"
                elif "current density" in lowered or "current_density" in lowered:
                    kind = "current_density"
                elif re.search(r"nbl.{0,20}psub|psub.{0,20}nbl|isolation", lowered):
                    kind = "isolation_bv"
            if not kind:
                continue
            if re.search(r"\b(?:curve|typical|around|range|typical value|曲线|典型|范围)\b", line, re.I) and not re.search(r"\b(?:max|maximum|limit|rating|上限|限值)\b", line, re.I):
                continue
            device_match = re.search(re.escape(device_name), line, re.I)
            anchor = kind_match.end() if kind_match else device_match.end() if device_match else 0
            value = _value_after(line[anchor:])
            if value is None and kind_match:
                value = _value_after(line[:kind_match.start()])
            if value is None:
                continue
            maximum, _unit = value
            minimum = None
            before = line[max(0, anchor - 24):anchor].lower()
            after = line[anchor:].lower()
            if re.search(r"\bmin(?:imum)?\b|lower|下限", before + after):
                minimum, maximum = maximum, None
            pair = _pair_for_kind(device, kind)
            expr = f"I({pair[0]})" if kind == "current_density" else f"v({pair[0]},{pair[1]})"
            rule = Rule(
            rule_id=f"document:{Path(source_path).name}:{page_number}:{line_number}:{device_name}:{kind}",
            name=f"documented_{device_name}_{kind}_{line_number}",
            target=device_name,
            target_kind="sub",
            expr=expr,
            maximum=maximum,
            minimum=minimum,
            message=f"Documented {kind} limit for {device_name}",
            level="warning",
            duration="t_trans_hv",
            section="soa_generated",
            line=line_number,
            limit_kind=kind,
            terminal_pair=pair,
            device_family=device.family if device else "unknown",
            confidence="documented",
            enabled=True,
            source=SourceEvidence(path=source_path, line=line_number, page=page_number, mechanism="manual_table", note="从手册文本提取的明确限值；未将曲线或典型值转换为单一阈值。"),
            notes=["手册文本明确给出限值；请确认适用温度、测试条件和器件变体。"],
            status="source",
            route="document",
        )
            rule.original = rule.to_dict()
            rules.append(rule)
    return rules
