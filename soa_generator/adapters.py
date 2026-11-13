from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Union
import re
from typing import Any, Iterable

from .classify import terminal_pair
from .models import Device, Rule, SourceEvidence
from .schema import validate_adapter_config


def apply_adapter_config(
    devices: Iterable[Device],
    rules: Iterable[Rule],
    config: Optional[Dict[str, Any]],
) -> None:
    """Apply declarative process-specific metadata without changing core parsers."""
    if not config:
        return
    issues = validate_adapter_config(config)
    if issues:
        raise ValueError("适配器配置无效：" + "；".join(item["message"] for item in issues))
    device_rules = config.get("device_rules", [])
    for device in devices:
        for item in device_rules:
            pattern = str(item.get("pattern", ""))
            if not pattern or not re.search(pattern, device.name, re.I):
                continue
            if item.get("category"):
                device.category = str(item["category"])
            if item.get("family"):
                device.family = str(item["family"])
            if item.get("scope"):
                device.scope = str(item["scope"])
            if item.get("isolation_type"):
                device.isolation_type = str(item["isolation_type"])
            device.port_roles.update(item.get("port_roles", {}))
            for edge in item.get("isolation_junctions", []):
                if edge not in device.isolation_junctions:
                    device.isolation_junctions.append(dict(edge))
            if item.get("family_voltage") is not None:
                device.family_voltage = float(item["family_voltage"])
            if item.get("gate_voltage") is not None:
                device.gate_voltage = float(item["gate_voltage"])
                device.gate_voltage_confidence = str(item.get("gate_voltage_confidence", "documented"))
            if item.get("isolation_voltage") is not None:
                device.isolation_voltage = float(item["isolation_voltage"])
                device.isolation_confidence = str(item.get("isolation_confidence", "documented"))
            for token in item.get("topology", []):
                if token not in device.topology:
                    device.topology.append(str(token))
        if device.gate_voltage is None and device.family_voltage is not None:
            device.gate_voltage = min(device.family_voltage, 5.0) if device.family in {"ldmos", "demos"} else device.family_voltage
            device.gate_voltage_confidence = "inferred"
        for index, item in enumerate(config.get("check_rules", [])):
            pattern = str(item.get("pattern", ""))
            if not pattern or not re.search(pattern, device.name, re.I):
                continue
            limit_kind = str(item.get("limit_kind", "other"))
            expr = str(item.get("expr", "")).strip()
            if not expr:
                continue
            rule_id = f"adapter:{config.get('id', 'unknown')}:{device.name}:{index}"
            if any(rule.rule_id == rule_id for rule in rules):
                continue
            source_path = str(item.get("source_path") or f"adapter://{config.get('id', 'unknown')}@{config.get('version', 'unknown')}")
            note = str(item.get("note", "工艺适配器提供的文档限值"))
            rule = Rule(
                rule_id=rule_id,
                name=str(item.get("name") or f"documented_{device.name}_{limit_kind}_{index}"),
                target=device.name,
                target_kind=str(item.get("target_kind", "sub")),  # type: ignore[arg-type]
                expr=expr,
                maximum=str(item["maximum"]) if item.get("maximum") is not None else None,
                minimum=str(item["minimum"]) if item.get("minimum") is not None else None,
                message=str(item.get("message") or f"Documented {limit_kind} limit for {device.name}"),
                level=str(item.get("level", "warning")),
                duration=str(item["duration"]) if item.get("duration") is not None else None,
                section=str(item.get("section", "soa_generated")),
                line=int(item["line"]) if item.get("line") is not None else None,
                limit_kind=limit_kind,
                measurement=str(item.get("measurement", "unknown")),
                measurement_unit=str(item.get("measurement_unit", "")),
                terminal_pair=[str(value) for value in item.get("terminal_pair", [])] or terminal_pair(expr),
                device_family=device.family,
                confidence="documented",
                enabled=bool(item.get("enabled", True)),
                source=SourceEvidence(path=source_path, page=int(item["page"]) if item.get("page") is not None else None, mechanism="manual_table", note=note),
                notes=[note, "来自适配器文档证据；原始 PDK 保持只读。"],
                status="source",
                route="adapter",
            )
            rule.original = rule.to_dict()
            rules.append(rule)
    family_by_name = {device.name: device.family for device in devices}
    for rule in rules:
        if rule.target in family_by_name:
            rule.device_family = family_by_name[rule.target]
