from __future__ import annotations

import re

from .models import Device, Rule


_VOLTAGE_AFTER_FAMILY = re.compile(r"^(?:nld|pld|nde|pde|nmos|pmos|n|p)(\d+)", re.I)
_ISO_VOLTAGE = re.compile(r"(?:iso|isoring|hvbn|hvnwell|dpw|ddnw)[_-]?(\d+)(?:v)?", re.I)
_NBL_ISO_VOLTAGE = re.compile(r"(?:nbl|hvnwell|dpw)[_-](\d+)v(?:_|$)", re.I)
_DESCRIPTOR_VOLTAGE = re.compile(r"^[np](?:ch|mos)(\d+)d(\d+)", re.I)
_TEXT_VOLTAGE = re.compile(r"(?:^|_)(\d+)p(\d+)v(?:_|$)", re.I)


def classify_family(name: str) -> str:
    value = name.lower()
    if any(token in value for token in ("cap", "mim", "mom")):
        return "capacitor"
    if any(token in value for token in ("var", "varactor")):
        return "varactor"
    if any(token in value for token in ("dio", "zener", "sbd")):
        return "diode"
    if any(token in value for token in ("pnp", "npn", "bjt", "bipolar")):
        return "bjt"
    if value.startswith(("r", "res")) or "resistor" in value:
        return "resistor"
    if any(token in value for token in ("esd", "scr", "efuse", "eprom", "eeprom")):
        return "esd_protection"
    if any(token in value for token in ("ldm", "nld", "pld")):
        return "ldmos"
    if any(token in value for token in ("dem", "nde", "pde")):
        return "demos"
    if any(token in value for token in ("mos", "nch", "pch", "nmos", "pmos")) or re.match(r"^[np](?:nt|lvt|ulvt|udvt|dvt)?\d", value):
        return "mos"
    return "unknown"


def classify_scope(name: str, category: str = "") -> str:
    value = f"{name} {category}".lower()
    if any(token in value for token in ("pocket", "iso_ring", "sealring", "parasitic", "hidden")):
        return "infrastructure"
    if any(token in value for token in ("esd", "scr", "efuse", "eprom", "eeprom")):
        return "esd_protection"
    if classify_family(name) in {"resistor", "diode", "bjt", "varactor", "capacitor"}:
        return "passive"
    return "active"


def topology_tokens(name: str) -> list[str]:
    value = name.lower()
    known = ("ful_iso", "iso", "hvbn", "hvnwell", "dpw", "ddnw", "cmt", "hs", "ls", "lvt", "ulvt", "udvt", "dvt", "dep", "gg")
    return [token for token in known if token in value]


def topology_from_ports(ports: list[str]) -> list[str]:
    """Return topology markers that are explicit in a model terminal list."""
    normalized = {port.strip().lower() for port in ports if port.strip()}
    markers: list[str] = []
    for port, marker in (
        ("iso", "iso"),
        ("isub", "isub"),
        ("nbl", "nbl"),
        ("psub", "psub"),
        ("pepi", "pepi"),
        ("hvnwell", "hvnwell"),
        ("hvbn", "hvbn"),
        ("dpw", "dpw"),
        ("ddnw", "ddnw"),
    ):
        if port in normalized and marker not in markers:
            markers.append(marker)
    return markers


def apply_port_metadata(device: Device, ports: list[str]) -> Device:
    """Attach model-derived terminals and topology markers to a device."""
    cleaned: list[str] = []
    for port in ports:
        value = port.strip().strip("(),")
        if value and value not in cleaned:
            cleaned.append(value)
    device.ports = cleaned
    if cleaned:
        device.port_confidence = "confirmed"
    for marker in topology_from_ports(cleaned):
        if marker not in device.topology:
            device.topology.append(marker)
    # A model with explicit isolation terminals has a useful candidate even
    # when the PDK does not publish a numeric isolation rating. Keep the
    # candidate visibly inferred; it must not silently replace a source rule.
    if device.isolation_voltage is None and device.family_voltage is not None:
        if any(marker in device.topology for marker in ("iso", "isub", "nbl", "psub", "pepi", "hvnwell", "hvbn", "dpw", "ddnw")):
            device.isolation_voltage = round(device.family_voltage * 1.10, 6)
            device.isolation_confidence = "inferred"
    return device


def family_voltage(name: str) -> float | None:
    value = name.lower()
    descriptor_match = _DESCRIPTOR_VOLTAGE.match(value)
    if descriptor_match:
        return float(f"{descriptor_match.group(1)}.{descriptor_match.group(2)}")
    text_match = _TEXT_VOLTAGE.search(value)
    if text_match:
        return float(f"{text_match.group(1)}.{text_match.group(2)}")
    match = _VOLTAGE_AFTER_FAMILY.match(value)
    if not match:
        return None
    number = int(match.group(1))
    # SMIC-style LV/MV MOS names use 18/50/60 for 1.8/5/6 V.
    if re.match(r"^(?:n|p)(?:nt|lvt|ulvt|udvt|dvt)?\d", value) and not value.startswith(("nld", "pld", "nde", "pde")):
        return {18: 1.8, 50: 5.0, 60: 6.0}.get(number, float(number))
    return float(number)


def isolation_voltage(name: str) -> float | None:
    value = name.lower()
    match = _ISO_VOLTAGE.search(value) or _NBL_ISO_VOLTAGE.search(value)
    return float(match.group(1)) if match else None


def classify_device(name: str, category: str = "") -> Device:
    family = classify_family(name)
    iso = isolation_voltage(name)
    return Device(
        name=name,
        category=category or family,
        scope=classify_scope(name, category),
        family=family,
        topology=topology_tokens(name),
        family_voltage=family_voltage(name),
        isolation_voltage=iso,
        isolation_confidence="inferred" if iso is not None else "missing",
    )


def classify_limit(expr: str, message: str | None = None) -> str:
    text = f"{expr} {message or ''}".lower()
    for key, aliases in {
        "isolation_bv": ("v(iso", "v(isub", "v(nbl", "v(pepi", "v(b,sub)", "v(iso,sub)", "isolation"),
        "Vds": ("vds", "v(d,s)", "v(d,bs)"),
        "Vgs": ("vgs", "v(g,s)", "v(g,bs)"),
        "Vbs": ("vbs", "v(s,b)", "v(bs", "v(b,s)"),
        "Vgb": ("vgb", "v(g,b)"),
        "Vbd": ("vbd", "v(d,b)"),
        "temperature": ("temp",),
        "current_density": ("current density", "j_density", "i(") ,
    }.items():
        if any(alias in text for alias in aliases):
            return key
    return "other"


def apply_device_metadata(rule: Rule) -> Rule:
    rule.device_family = classify_family(rule.target)
    rule.limit_kind = classify_limit(rule.expr, rule.message)
    return rule
