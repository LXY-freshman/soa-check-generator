from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .classify import apply_device_metadata, apply_port_metadata, classify_device, isolation_voltage
from .models import Device, Rule, SourceEvidence


_ASSERT_RE = re.compile(r"^(?P<name>\S+)\s+assert\s+(?P<body>.*)$", re.I)
_FIELD_RE = re.compile(r"(?P<key>sub|subs|expr|message|level|duration|max|min)\s*=\s*(?P<value>\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[^\s]+)", re.I)
_SECTION_RE = re.compile(r"^section\s+(?P<section>\S+)", re.I)
_SUBCKT_RE = re.compile(
    r"^\s*(?:(?:inline)\s+)?subckt\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<ports>.*)$",
    re.I,
)
_MODEL_RE = re.compile(r"^\s*model\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)", re.I)
_MODEL_SOA_PARAMETER_RE = re.compile(r"\bsoa_(?:ar|br|cr|dr|a|b|c|d|vdd|vgg|rt1|rt2)\b", re.I)
_MODEL_PARAMETER_RE = re.compile(
    r"\b(?P<key>bv_max|vbreakdown|breakdown|fv_max|ibv|bv|vb|jmax|current_density|rsh)\s*=\s*"
    r"(?P<value>'[^']*'|\"[^\"]*\"|[^\s]+)",
    re.I,
)
_MODEL_LIMIT_RE = re.compile(
    r"^\s*(?P<primitive>[A-Za-z_][A-Za-z0-9_]*)\s*\(\s*"
    r"(?P<left>[^,\s()]+)\s+(?P<right>[^,\s()]+)\s*\)[^\n]*?"
    r"\b(?P<key>bv_max|vbreakdown|breakdown|fv_max|bv|vb)\s*=\s*"
    r"(?P<value>'[^']*'|\"[^\"]*\"|[^\s]+)",
    re.I,
)
_INSTANCE_RE = re.compile(
    r"^\s*(?P<instance>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s+(?P<master>[A-Za-z_][A-Za-z0-9_]*)",
    re.I,
)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _targets(value: str) -> list[str]:
    value = _unquote(value).strip("[]")
    return [item.strip(" '\"") for item in value.split(",") if item.strip(" '\"")]


def parse_spectre_asserts(text: str, source_path: str = "<memory>") -> list[Rule]:
    rules: list[Rule] = []
    section: str | None = None
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        section_match = _SECTION_RE.match(line)
        if section_match:
            section = section_match.group("section")
        if not line or line.startswith(("//", "*", "$") ):
            continue
        match = _ASSERT_RE.match(line)
        if not match:
            continue
        fields = {item.group("key").lower(): _unquote(item.group("value")) for item in _FIELD_RE.finditer(match.group("body"))}
        target_key = "subs" if "subs" in fields else "sub" if "sub" in fields else "unknown"
        targets = _targets(fields.get(target_key, "")) or [""]
        for target_index, target in enumerate(targets):
            rule = Rule(
                rule_id=f"{Path(source_path).name}:{line_number}:{match.group('name')}:{target_index}",
                name=match.group("name"),
                target=target,
                target_kind=target_key,  # type: ignore[arg-type]
                expr=fields.get("expr", ""),
                maximum=fields.get("max"),
                minimum=fields.get("min"),
                message=fields.get("message"),
                level=fields.get("level"),
                duration=fields.get("duration"),
                section=section,
                line=line_number,
                source=SourceEvidence(
                    path=source_path,
                    line=line_number,
                    mechanism="spectre_assert",
                ),
            )
            rule.original = rule.to_dict()
            rules.append(apply_device_metadata(rule))
    # A single Spectre check can be written as two source lines, one with min
    # and one with max. Keep one editable rule when every other condition is
    # identical, so the export restores a single bounded assertion.
    merged: list[Rule] = []
    by_signature: dict[tuple[str, str, str, str | None, str | None, str | None, str | None], Rule] = {}
    for rule in rules:
        signature = (rule.target, rule.target_kind, rule.expr, rule.message, rule.level, rule.duration, rule.section)
        current = by_signature.get(signature)
        can_merge = current is not None and (
            (current.maximum is None and rule.maximum is not None)
            or (current.minimum is None and rule.minimum is not None)
        )
        if can_merge:
            if current.maximum is None:
                current.maximum = rule.maximum
            if current.minimum is None:
                current.minimum = rule.minimum
            current.notes.append(f"合并来源：{rule.name}（第 {rule.line} 行）")
            continue
        by_signature[signature] = rule
        merged.append(rule)
    return merged


def _clean_ports(value: str) -> list[str]:
    value = value.split("//", 1)[0].strip().strip("()")
    return [item for item in re.split(r"[\s,]+", value) if item]


def parse_model_definitions(text: str) -> list[tuple[str, list[str], int]]:
    """Parse one-line Spectre subckt/inline-subckt/model declarations.

    PDK model files use both ``subckt name (d g s b)`` and
    ``inline subckt name (d g s b nbl psub)``. A model declaration has no
    terminals, but is returned so callers can associate it with a file.
    """
    definitions: list[tuple[str, list[str], int]] = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("//", "*", "$")):
            continue
        subckt = _SUBCKT_RE.match(raw)
        if subckt:
            definitions.append((subckt.group("name"), _clean_ports(subckt.group("ports")), line_number))
            continue
        model = _MODEL_RE.match(raw)
        if model:
            definitions.append((model.group("name"), [], line_number))
    return definitions


def parse_model_parameters(text: str) -> dict[str, dict[str, str]]:
    """Extract safety-related model parameters grouped by subckt/model name."""
    parameters: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("//", "*", "$")):
            continue
        subckt = _SUBCKT_RE.match(raw)
        if subckt:
            current = subckt.group("name")
            parameters.setdefault(current, {})
        else:
            model = _MODEL_RE.match(raw)
            if model:
                current = model.group("name")
                parameters.setdefault(current, {})
            elif re.match(r"^\s*(?:ends|\.ends|end\s+subckt)\b", raw, re.I):
                current = None
        if current is None:
            continue
        for match in _MODEL_PARAMETER_RE.finditer(raw):
            value = match.group("value").strip("'\"")
            parameters[current][match.group("key").lower()] = value
    return {name: values for name, values in parameters.items() if values}


def parse_model_limits(text: str) -> dict[str, list[dict[str, str]]]:
    """Extract terminal-pair safety parameters from primitive model lines."""
    limits: dict[str, list[dict[str, str]]] = {}
    current: str | None = None
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("//", "*", "$")):
            continue
        subckt = _SUBCKT_RE.match(raw)
        if subckt:
            current = subckt.group("name")
            limits.setdefault(current, [])
        else:
            model = _MODEL_RE.match(raw)
            if model:
                current = model.group("name")
                limits.setdefault(current, [])
            elif re.match(r"^\s*(?:ends|\.ends|end\s+subckt)\b", raw, re.I):
                current = None
        if current is None:
            continue
        match = _MODEL_LIMIT_RE.match(raw)
        if not match:
            continue
        limits[current].append({
            "primitive": match.group("primitive"),
            "left": match.group("left"),
            "right": match.group("right"),
            "key": match.group("key").lower(),
            "value": match.group("value").strip("'\""),
            "line": str(line_number),
        })
    return {name: values for name, values in limits.items() if values}


def parse_subckt_dependencies(text: str) -> dict[str, list[str]]:
    """Find subckt masters instantiated inside other subckts."""
    definitions = {name for name, _ports, _line in parse_model_definitions(text)}
    dependencies: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("//", "*", "$")):
            continue
        subckt = _SUBCKT_RE.match(raw)
        if subckt:
            current = subckt.group("name")
            dependencies.setdefault(current, [])
            continue
        if re.match(r"^\s*(?:ends|\.ends|end\s+subckt)\b", raw, re.I):
            current = None
            continue
        if current is None:
            continue
        instance = _INSTANCE_RE.match(raw)
        if not instance:
            continue
        master = instance.group("master")
        if master in definitions and master != current and master not in dependencies[current]:
            dependencies[current].append(master)
    return {name: values for name, values in dependencies.items() if values}


def detect_model_soa(text: str) -> dict[str, object]:
    """Detect model-internal SOA without treating every bsource as SOA."""
    gsoa_match = re.search(r"(?im)^\s*gsoa\b", text)
    parameter_match = _MODEL_SOA_PARAMETER_RE.search(text)
    if gsoa_match:
        return {
            "enabled": True,
            "mechanism": "gsoa_bsource",
            "line": text[: gsoa_match.start()].count("\n") + 1,
            "note": "检测到 gsoa 行；SOA 由模型内部行为源实现。",
        }
    if parameter_match:
        return {
            "enabled": True,
            "mechanism": "soa_parameters",
            "line": text[: parameter_match.start()].count("\n") + 1,
            "note": "检测到 soa_* 模型参数；需要保留模型原生实现，不能按 assert 重写。",
        }
    return {"enabled": False, "mechanism": None, "line": None, "note": ""}


def _isolation_pairs(device: Device) -> list[tuple[str, str]]:
    ports = {port.lower(): port for port in device.ports}
    pairs: list[tuple[str, str]] = []
    for left_names, right_names in [
        (("iso",), ("b", "bs", "sub")),
        (("isub",), ("b", "bs", "sub")),
        (("nbl",), ("psub", "pepi", "b", "bs", "d")),
        (("pepi",), ("psub",)),
        (("hvnwell", "hvbn", "dpw", "ddnw"), ("b", "bs", "sub")),
    ]:
        left_values = [ports[name] for name in left_names if name in ports]
        right_values = [ports[name] for name in right_names if name in ports]
        for left in left_values:
            for right in right_values:
                if (left, right) not in pairs:
                    pairs.append((left, right))
    return pairs


def topology_rule_candidates(
    devices: Iterable[Device],
    existing_rules: Iterable[Rule],
    source_path: str = "<inferred>",
) -> list[Rule]:
    """Create disabled isolation checks from model ports and explicit ratings."""
    existing = {(rule.target, rule.expr.replace(" ", "").lower(), rule.limit_kind) for rule in existing_rules}
    candidates: list[Rule] = []
    for device in devices:
        pairs = _isolation_pairs(device)
        if not pairs or not device.ports:
            continue
        for left, right in pairs:
            expr = f"v({left},{right})"
            key = (device.name, expr, "isolation_bv")
            if key in existing:
                continue
            named_voltage = isolation_voltage(device.name) is not None
            value = device.isolation_voltage if named_voltage else None
            reason = (
                f"端口 {left}/{right} 来自模型定义；隔离等级来自器件命名中的明确电压线索，仍需手册或原生 SOA 确认。"
                if named_voltage
                else f"端口 {left}/{right} 来自模型定义；器件名称没有隔离电压等级，保留空值等待手册或用户填写。"
            )
            rule = Rule(
                rule_id=f"inferred:isolation:{device.name}:{left}:{right}",
                name=f"candidate_{device.name}_{left}_{right}_isolation_bv",
                target=device.name,
                target_kind="sub",
                expr=expr,
                maximum=f"{value:g}" if value is not None else None,
                message=f"SOA Warning - {device.name} isolation voltage candidate exceeded",
                level="warning",
                duration="t_trans_hv",
                section="soa_generated",
                limit_kind="isolation_bv",
                terminal_pair=[left, right],
                device_family=device.family,
                confidence="inferred" if value is not None else "missing",
                enabled=False,
                source=SourceEvidence(
                    path=source_path,
                    mechanism="inference",
                    note=reason,
                ),
                notes=[reason, "候选规则默认关闭，请结合工艺手册或原生 SOA 文件确认后再启用。"],
                status="inferred" if value is not None else "missing",
                route="topology" if value is not None else "missing",
            )
            rule.original = rule.to_dict()
            candidates.append(rule)
    return candidates


def parse_device_list(text: str, source_path: str = "<memory>") -> list[Device]:
    devices: list[Device] = []
    category = "unknown"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("******"):
            value = line.strip("* ")
            if value:
                category = value
            continue
        if line.startswith(("*", "/", "#")) or " " in line or "\t" in line:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_]+", line):
            continue
        device = classify_device(line, category)
        device.source = SourceEvidence(path=source_path, mechanism="manual_table")
        devices.append(device)
    return devices


def merge_devices(devices: Iterable[Device], rules: Iterable[Rule]) -> list[Device]:
    by_name: dict[str, Device] = {}
    for incoming in devices:
        current = by_name.get(incoming.name)
        if current is None:
            by_name[incoming.name] = incoming
            continue
        if current.category in {"unknown", "model"} and incoming.category not in {"unknown", "model"}:
            current.category = incoming.category
        if current.family == "unknown" and incoming.family != "unknown":
            current.family = incoming.family
        if current.scope == "active" and incoming.scope != "active":
            current.scope = incoming.scope
        current.topology = list(dict.fromkeys([*current.topology, *incoming.topology]))
        current.ports = list(dict.fromkeys([*current.ports, *incoming.ports]))
        current.port_roles.update(incoming.port_roles)
        if incoming.port_confidence == "confirmed":
            current.port_confidence = "confirmed"
        current.model_parameters.update(incoming.model_parameters)
        current.model_limits.extend(item for item in incoming.model_limits if item not in current.model_limits)
        current.model_sources.extend(item for item in incoming.model_sources if item not in current.model_sources)
        current.associated_devices = list(dict.fromkeys([*current.associated_devices, *incoming.associated_devices]))
        if incoming.parameter_confidence == "confirmed":
            current.parameter_confidence = "confirmed"
        if current.family_voltage is None:
            current.family_voltage = incoming.family_voltage
        if current.gate_voltage is None:
            current.gate_voltage = incoming.gate_voltage
            current.gate_voltage_confidence = incoming.gate_voltage_confidence
        if current.isolation_voltage is None:
            current.isolation_voltage = incoming.isolation_voltage
            current.isolation_confidence = incoming.isolation_confidence
        elif incoming.isolation_voltage is not None and current.isolation_voltage != incoming.isolation_voltage:
            current.isolation_confidence = "conflict"
        if current.source is None:
            current.source = incoming.source
        current.aliases = list(dict.fromkeys([*current.aliases, *incoming.aliases]))
    for rule in rules:
        if rule.target not in by_name:
            by_name[rule.target] = classify_device(rule.target)
        device = by_name[rule.target]
        if rule.confidence == "inferred" and device.soa_status == "unknown":
            device.soa_status = "candidate_rule"
        else:
            device.soa_status = "source_rule"
    return sorted(by_name.values(), key=lambda item: item.name.lower())
