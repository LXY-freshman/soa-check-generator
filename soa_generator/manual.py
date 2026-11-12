"""Conservative extraction of explicit device limits from process documents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .classify import terminal_pair
from .models import Device, Rule, SourceEvidence


_KIND_RE = re.compile(
    r"\b(?P<kind>V(?:ds|gs|gd|gb|bs|bd|ce|cb|be)|isolation[_ -]?bv|reverse[_ -]?voltage|forward[_ -]?voltage|current[_ -]?density)\b",
    re.I,
)
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


def _header_kind(cell: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", " ", cell.lower()).strip()
    direct = re.search(r"\bv(ds|gs|gd|gb|bs|bd|ce|cb|be)\b", normalized)
    if direct:
        return _kind(direct.group(0))
    if "current" in normalized and "density" in normalized:
        return "current_density"
    if "dsb" in normalized:
        return "Vds"
    if "isolation" in normalized or ("nbl" in normalized and "psub" in normalized):
        return "isolation_bv"
    if "gate" in normalized and any(token in normalized for token in ("body", "source", "rating", "bv", "limit")):
        return "Vgs"
    if "drain" in normalized and "body" in normalized:
        return "Vbd"
    if "drain" in normalized and any(token in normalized for token in ("source", "ds", "bv", "limit")):
        return "Vds"
    return None


def _split_cells(line: str) -> list[str]:
    if "|" in line:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]
    if "\t" in line:
        return [cell.strip() for cell in line.split("\t")]
    return [cell.strip() for cell in re.split(r"\s{2,}", line.strip()) if cell.strip()]


def _table_header(line: str) -> tuple[int, list[tuple[int, str]]] | None:
    cells = _split_cells(line)
    if len(cells) < 2:
        return None
    columns = [(index, kind) for index, cell in enumerate(cells) if (kind := _header_kind(cell))]
    if not columns:
        return None
    device_index = next(
        (index for index, cell in enumerate(cells) if re.search(r"device|cell|model|器件", cell, re.I)),
        0,
    )
    return device_index, columns


def _table_values(cells: list[str], device_index: int, columns: list[tuple[int, str]]) -> list[tuple[str, str, str | None]]:
    result: list[tuple[str, str, str | None]] = []
    for index, kind in columns:
        actual_index = index
        if len(cells) == len(columns):
            actual_index -= 1 if device_index == 0 else 0
        if actual_index < 0 or actual_index >= len(cells):
            continue
        value = _value_after(cells[actual_index])
        if value:
            result.append((kind, value[0], value[1]))
    return result


def _make_rule(
    device_name: str,
    device: Device | None,
    kind: str,
    maximum: str | None,
    minimum: str | None,
    source_path: str,
    page_number: int,
    line_number: int,
    note: str,
) -> Rule:
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
        source=SourceEvidence(path=source_path, line=line_number, page=page_number, mechanism="manual_table", note=note),
        notes=["手册文本明确给出限值；请确认适用温度、测试条件和器件变体。"],
        status="source",
        route="document",
    )
    rule.original = rule.to_dict()
    return rule


def _line_candidate(line: str, device_name: str, device: Device | None) -> tuple[str, str, str | None, str | None] | None:
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
        return None
    if re.search(r"\b(?:curve|typical|around|range|typical value|曲线|典型|范围)\b", line, re.I) and not re.search(r"\b(?:max|maximum|limit|rating|上限|限值)\b", line, re.I):
        return None
    device_match = re.search(re.escape(device_name), line, re.I)
    anchor = kind_match.end() if kind_match else device_match.end() if device_match else 0
    value = _value_after(line[anchor:])
    if value is None and kind_match:
        value = _value_after(line[:kind_match.start()])
    if value is None:
        return None
    maximum, _unit = value
    minimum = None
    before = line[max(0, anchor - 24):anchor].lower()
    after = line[anchor:].lower()
    if re.search(r"\bmin(?:imum)?\b|lower|下限", before + after):
        minimum, maximum = maximum, None
    return kind, maximum, minimum, "从手册文本提取的明确限值；未将曲线或典型值转换为单一阈值。"


def parse_manual_rules(text: str, source_path: str, devices: Iterable[Device] = ()) -> list[Rule]:
    """Extract explicit line and table limits while preserving provenance.

    Supported tables use pipe, tab, or multi-space columns. Curve, typical,
    and range statements are retained as evidence only and never converted
    into a scalar SOA limit.
    """
    known = {device.name: device for device in devices}
    rules: list[Rule] = []
    seen: set[tuple[str, str, str | None, str | None, int, int]] = set()
    for page_number, page_text in enumerate(text.split("\f"), 1):
        table: tuple[int, list[tuple[int, str]]] | None = None
        pending_device = ""
        for line_number, raw in enumerate(page_text.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith(("#", "//", "*")):
                if not line:
                    pending_device = ""
                continue
            header = _table_header(line)
            if header:
                table = header
                continue
            device_name, device = _device_for_line(line, known)
            if not device_name and pending_device:
                device_name = pending_device
                device = known.get(device_name)
            if device_name and line.strip() == device_name:
                pending_device = device_name
            elif device_name:
                pending_device = device_name
            if device_name:
                candidate = _line_candidate(line, device_name, device)
                if candidate:
                    kind, maximum, minimum, note = candidate
                    key = (device_name, kind, maximum, minimum, page_number, line_number)
                    if key not in seen:
                        seen.add(key)
                        rules.append(_make_rule(device_name, device, kind, maximum, minimum, source_path, page_number, line_number, note))
            if table and device_name:
                cells = _split_cells(line)
                for kind, maximum, _unit in _table_values(cells, table[0], table[1]):
                    key = (device_name, kind, maximum, None, page_number, line_number)
                    if key in seen:
                        continue
                    seen.add(key)
                    rules.append(_make_rule(device_name, device, kind, maximum, None, source_path, page_number, line_number, "从手册表格行提取的明确限值；列名提供检查类别。"))
            elif table and pending_device:
                cells = _split_cells(line)
                for kind, maximum, _unit in _table_values(cells, table[0], table[1]):
                    key = (pending_device, kind, maximum, None, page_number, line_number)
                    if key in seen:
                        continue
                    seen.add(key)
                    rules.append(_make_rule(pending_device, known.get(pending_device), kind, maximum, None, source_path, page_number, line_number, "从手册表格续行提取的明确限值；列名提供检查类别。"))
    return rules
