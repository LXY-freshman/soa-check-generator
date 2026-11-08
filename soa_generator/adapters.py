from __future__ import annotations

import re
from typing import Any, Iterable

from .models import Device, Rule
from .schema import validate_adapter_config


def apply_adapter_config(
    devices: Iterable[Device],
    rules: Iterable[Rule],
    config: dict[str, Any] | None,
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
    family_by_name = {device.name: device.family for device in devices}
    for rule in rules:
        if rule.target in family_by_name:
            rule.device_family = family_by_name[rule.target]
