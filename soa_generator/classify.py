from __future__ import annotations

import re

from .models import Device, Rule


_VOLTAGE_AFTER_FAMILY = re.compile(r"^(?:nld|pld|nde|pde|nmos|pmos|n|p)(\d+)", re.I)
_ISO_VOLTAGE = re.compile(r"(?:iso|isoring|hvbn|hvnwell|dpw|ddnw)[_-]?(\d+)(?:v)?", re.I)
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


def family_voltage(name: str) -> float | None:
    value = name.lower()
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
    match = _ISO_VOLTAGE.search(name.lower())
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
