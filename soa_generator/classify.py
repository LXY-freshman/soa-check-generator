from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Union
import re

from .models import Device, Rule


_VOLTAGE_AFTER_FAMILY = re.compile(r"^(?:nld|pld|nde|pde|nmos|pmos|n|p)(\d+)", re.I)
_ISO_VOLTAGE = re.compile(r"(?:iso|isoring|isowell|hvbn|hvnwell|dpw|ddnw)[_-]?(\d+)(?:v)?", re.I)
_NBL_ISO_VOLTAGE = re.compile(r"(?:nbl|hvnwell|dpw)[_-](\d+)v(?:_|$)", re.I)
_DESCRIPTOR_VOLTAGE = re.compile(r"^[np](?:ch|mos)(\d+)d(\d+)", re.I)
_TEXT_VOLTAGE = re.compile(r"(?:^|_)(\d+)p(\d+)v(?:_|$)", re.I)
_NAMED_VOLTAGE = re.compile(r"(\d+(?:\.\d+)?)v(?:_|$)", re.I)
_VOLTAGE_PAIR = re.compile(r"\bv\s*\(\s*([^,\s()]+)\s*,\s*([^,\s()]+)\s*\)", re.I)


def classify_family(name: str, category: str = "") -> str:
    value = f"{name} {category}".lower()
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
    if "demo_mos" in value or "demo_pmos" in value:
        return "mos"
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
    if classify_family(name, category) in {"resistor", "diode", "bjt", "varactor", "capacitor"}:
        return "passive"
    return "active"


def topology_tokens(name: str) -> List[str]:
    value = name.lower()
    known = ("ful_iso", "iso", "isowell", "hvbn", "hvnwell", "dpw", "ddnw", "cmt", "hs", "ls", "lvt", "ulvt", "udvt", "dvt", "dep", "gg")
    return [token for token in known if token in value]


def topology_from_ports(ports: List[str]) -> List[str]:
    """Return topology markers that are explicit in a model terminal list."""
    normalized = {port.strip().lower() for port in ports if port.strip()}
    markers: List[str] = []
    for port, marker in (
        ("iso", "iso"),
        ("isub", "isub"),
        ("nbl", "nbl"),
        ("pepi", "pepi"),
        ("hvnwell", "hvnwell"),
        ("hvbn", "hvbn"),
        ("isowell", "isowell"),
        ("dpw", "dpw"),
        ("ddnw", "ddnw"),
        ("dnw", "dnw"),
        ("dnwell", "dnwell"),
    ):
        if port in normalized and marker not in markers:
            markers.append(marker)
    return markers


def apply_port_metadata(device: Device, ports: List[str]) -> Device:
    """Attach model-derived terminals and topology markers to a device."""
    cleaned: List[str] = []
    for port in ports:
        value = port.strip().strip("(),")
        if value and value not in cleaned:
            cleaned.append(value)
    device.ports = cleaned
    role_names = {
        "d": "drain", "drain": "drain",
        "g": "gate", "gate": "gate",
        "s": "source", "source": "source",
        "bs": "body_source", "b": "body", "body": "body",
        "psub": "bulk_substrate", "sub": "bulk_substrate",
        "nbl": "isolation_nbl", "pepi": "isolation_epitaxy",
        "iso": "isolation_ring", "isub": "isolation_substrate",
        "hvnwell": "isolation_well", "hvbn": "isolation_well", "isowell": "isolation_well",
        "dpw": "isolation_well", "ddnw": "isolation_well",
        "dnw": "isolation_well", "dnwell": "isolation_well",
        "pwell": "body", "pw": "body",
        "p": "anode", "pos": "anode", "n": "cathode", "neg": "cathode",
        "c": "collector", "e": "emitter",
    }
    device.port_roles = {
        port: role_names[port.lower()]
        for port in cleaned
        if port.lower() in role_names
    }
    if cleaned:
        device.port_confidence = "confirmed"
    for marker in topology_from_ports(cleaned):
        if marker not in device.topology:
            device.topology.append(marker)
    return device


def family_voltage(name: str) -> Optional[float]:
    value = name.lower()
    synthetic_levels = (
        ("demo_mos_low", 1.8),
        ("demo_mos_mid", 5.0),
        ("demo_ldmos_high", 12.0),
        ("demo_pmos_mid", 3.3),
        ("demo_var_3p3v", 3.3),
        ("demo_var_low", 1.8),
        ("demo_diode_low", 1.8),
        ("demo_resistor_5v", 5.0),
        ("demo_pnp_low", 1.8),
    )
    for marker, voltage in synthetic_levels:
        if marker in value:
            return voltage
    for pattern in (
        r"^[np]var(\d+)",
        r"^(?:pnp|npn)(\d+)",
        r"^[np]dio(\d+)",
        r"^n(\d+)npb",
        r"^sdmte(\d+)",
        r"^mom(\d+)",
        r"^esd(\d+)",
    ):
        match = re.match(pattern, value)
        if match:
            number = int(match.group(1))
            if pattern in {r"^[np]var(\d+)", r"^(?:pnp|npn)(\d+)", r"^[np]dio(\d+)", r"^n(\d+)npb"}:
                return {18: 1.8, 50: 5.0, 60: 6.0}.get(number, float(number))
            return float(number)
    descriptor_match = _DESCRIPTOR_VOLTAGE.match(value)
    if descriptor_match:
        return float(f"{descriptor_match.group(1)}.{descriptor_match.group(2)}")
    text_match = _TEXT_VOLTAGE.search(value)
    if text_match:
        return float(f"{text_match.group(1)}.{text_match.group(2)}")
    match = _VOLTAGE_AFTER_FAMILY.match(value)
    if match:
        number = int(match.group(1))
        # Some legacy model naming conventions encode nominal voltage as 18/50/60.
        if re.match(r"^(?:n|p)(?:nt|lvt|ulvt|udvt|dvt)?\d", value) and not value.startswith(("nld", "pld", "nde", "pde")):
            return {18: 1.8, 50: 5.0, 60: 6.0}.get(number, float(number))
        return float(number)
    named = _NAMED_VOLTAGE.search(value)
    return float(named.group(1)) if named else None


def isolation_voltage(name: str) -> Optional[float]:
    value = name.lower()
    match = _ISO_VOLTAGE.search(value) or _NBL_ISO_VOLTAGE.search(value)
    return float(match.group(1)) if match else None


def classify_device(name: str, category: str = "") -> Device:
    family = classify_family(name, category)
    iso = isolation_voltage(name)
    nominal_voltage = family_voltage(name)
    gate_voltage = None
    gate_confidence = "missing"
    if nominal_voltage is not None and family in {"ldmos", "demos"}:
        gate_voltage = min(nominal_voltage, 5.0)
        gate_confidence = "inferred"
    elif nominal_voltage is not None and family == "mos":
        gate_voltage = nominal_voltage
        gate_confidence = "inferred"
    return Device(
        name=name,
        category=category or family,
        scope=classify_scope(name, category),
        family=family,
        topology=topology_tokens(name),
        family_voltage=nominal_voltage,
        gate_voltage=gate_voltage,
        gate_voltage_confidence=gate_confidence,
        isolation_voltage=iso,
        isolation_confidence="inferred" if iso is not None else "missing",
    )


def classify_limit(expr: str, message: Optional[str] = None) -> str:
    text = f"{expr} {message or ''}".lower()
    match = _VOLTAGE_PAIR.search(expr or "")
    if match:
        pair = frozenset((match.group(1).lower(), match.group(2).lower()))
        if pair & {"iso", "isub", "isowell", "nbl", "pepi", "hvnwell", "hvbn", "dpw", "ddnw", "dnw", "dnwell", "pwell", "pw"}:
            return "isolation_bv"
        voltage_kinds = {
            frozenset(("d", "s")): "Vds", frozenset(("d", "bs")): "Vds",
            frozenset(("g", "s")): "Vgs", frozenset(("g", "bs")): "Vgs",
            frozenset(("g", "d")): "Vgd", frozenset(("g", "b")): "Vgb",
            frozenset(("b", "s")): "Vbs", frozenset(("d", "b")): "Vbd",
        }
        if pair in voltage_kinds:
            return voltage_kinds[pair]
    for key, aliases in {
        "isolation_bv": ("v(iso", "v(isub", "v(nbl", "v(pepi", "v(b,sub)", "v(iso,sub)", "isolation"),
        "reverse_voltage": ("v(p,n)", "v(pos,neg)", "v(anode,cathode)", "reverse_voltage"),
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


def terminal_pair(expr: str) -> List[str]:
    """Extract the first explicit voltage terminal pair from a Spectre expr."""
    match = _VOLTAGE_PAIR.search(expr or "")
    return [match.group(1), match.group(2)] if match else []


def apply_device_metadata(rule: Rule) -> Rule:
    rule.device_family = classify_family(rule.target)
    rule.limit_kind = classify_limit(rule.expr, rule.message)
    rule.terminal_pair = terminal_pair(rule.expr)
    return rule
