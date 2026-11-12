"""Explicit isolation terminal relations shared by rules and the check matrix."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .models import Device, Rule


ISOLATION_PORTS = frozenset({"iso", "isub", "isowell", "nbl", "pepi", "hvnwell", "hvbn", "dpw", "ddnw", "dnw", "dnwell", "pwell", "pw"})


@dataclass(frozen=True)
class IsolationConnection:
    left: str
    right: str
    side: str
    description: str
    limit_kind: str = "isolation_bv"
    source: dict[str, object] | None = None
    verified: bool = False


def isolation_connections(device: Device) -> list[IsolationConnection]:
    """Expand supported relations using actual port spelling and direction.

    A substrate port alone does not prove isolation. No absent terminals or
    voltage ratings are inferred here, and each relation remains independent.
    """
    ports = {port.lower(): port for port in device.ports}
    if device.isolation_type == "dielectric":
        return []
    explicit: list[IsolationConnection] = []
    for edge in device.isolation_junctions:
        p = ports.get(str(edge.get("p_port", "")).lower())
        n = ports.get(str(edge.get("n_port", "")).lower())
        if not p or not n or p == n:
            continue
        side = "outer" if p.lower() in {"sub", "psub"} or device.port_roles.get(p) == "bulk_substrate" else "inner"
        label = "对外大衬底" if side == "outer" else "对内隔离结"
        source = edge.get("source")
        explicit.extend([
            IsolationConnection(n, p, side, f"隔离环{label}反向耐压", source=source, verified=True),
            IsolationConnection(p, n, side, f"隔离环{label}正向导通/注入", "isolation_forward_voltage", source, True),
        ])
    if explicit:
        return list({(item.left, item.right, item.limit_kind): item for item in explicit}.values())

    # Without a diode graph these are structural candidates only: the
    # existence of a port does not establish a PN junction or its polarity.
    ring_ports = [port for port in device.ports if port.lower() in {"iso", "isowell", "nbl", "hvbn", "hvnwell", "ddnw", "dnw", "dnwell"}
                  or device.port_roles.get(port) in {"isolation_ring", "isolation_nbl", "isolation_well"}]
    if not ring_ports and "isub" in ports:
        ring_ports = [ports["isub"]]
    outer_ports = [port for port in device.ports if port.lower() in {"psub", "sub"}
                   or device.port_roles.get(port) == "bulk_substrate"]
    fallback = [IsolationConnection(ring, substrate, "outer", "隔离环对外大衬底耐压（结构待确认）")
                for ring in ring_ports for substrate in outer_ports if ring != substrate]
    inner_ports = [ports[name] for name in ("pepi", "isub", "pwell", "pw") if name in ports]
    inner_ports = [port for port in inner_ports if port not in ring_ports]
    if not inner_ports and device.family in {"mos", "ldmos", "demos"}:
        inner_ports = [ports[name] for name in ("b", "bs", "body") if name in ports]
        # PMOS body is N-type: never invent an NBL/Nwell junction from names.
        if device.name.lower().startswith(("p", "pmos")):
            inner_ports = []
    fallback.extend(IsolationConnection(ring, inner, "inner", "隔离环对内体端耐压（结构待确认）")
                    for ring in ring_ports for inner in inner_ports if ring != inner)
    return list({(item.left, item.right, item.limit_kind): item for item in fallback}.values())


def bind_isolation_rule_metadata(device: Device, rules: list[Rule]) -> None:
    """Use explicit junction polarity to distinguish native forward limits."""
    for rule in rules:
        if rule.target != device.name or rule.limit_kind not in {"isolation_bv", "other"}:
            continue
        expr = str(rule.effective("expr") or "")
        pair = re.fullmatch(r"\s*v\s*\(\s*([^,\s()]+)\s*,\s*([^,\s()]+)\s*\)\s*", expr, re.I)
        if pair is None:
            continue
        actual = pair.group(1).lower(), pair.group(2).lower()
        for edge in device.isolation_junctions:
            forward = str(edge["p_port"]).lower(), str(edge["n_port"]).lower()
            try:
                upper, lower = rule.effective("maximum"), rule.effective("minimum")
                positive_upper = upper not in (None, "") and (bool(re.search(r"forward|vf", str(upper), re.I)) or float(upper) >= 0) and lower in (None, "")
                negative_lower = lower not in (None, "") and float(lower) <= 0 and upper in (None, "")
            except (ValueError, TypeError):
                continue
            if (actual == forward and positive_upper) or (actual == forward[::-1] and negative_lower):
                rule.limit_kind = "isolation_forward_voltage"
                break
