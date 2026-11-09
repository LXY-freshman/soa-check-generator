"""Explicit isolation terminal relations shared by rules and the check matrix."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Device


ISOLATION_PORTS = frozenset({"iso", "isub", "nbl", "pepi", "hvnwell", "hvbn", "dpw", "ddnw"})


@dataclass(frozen=True)
class IsolationConnection:
    left: str
    right: str
    side: str
    description: str


def isolation_connections(device: Device) -> list[IsolationConnection]:
    """Expand supported relations using actual port spelling and direction.

    A substrate port alone does not prove isolation. No absent terminals or
    voltage ratings are inferred here, and each relation remains independent.
    """
    ports = {port.lower(): port for port in device.ports}
    templates = [
        (("iso", "isub", "nbl", "hvbn", "hvnwell", "ddnw"), ("b", "bs", "body"), "inner", "隔离环对内体端耐压"),
        (("iso", "isub", "nbl", "hvbn", "hvnwell", "ddnw"), ("psub", "sub"), "outer", "隔离环对外大衬底耐压"),
        (("dpw",), ("b", "bs", "sub"), "inner", "深 P 井到体端检查，结构待确认"),
        (("nbl",), ("pepi",), "epitaxy", "NBL 到 P 外延层耐压"),
        (("nbl",), ("d",), "drain", "NBL 到漏极耐压"),
        (("pepi",), ("psub",), "substrate", "P 外延层到大衬底检查，结构待确认"),
    ]
    connections: list[IsolationConnection] = []
    seen: set[tuple[str, str]] = set()
    for left_names, right_names, side, description in templates:
        for left_name in left_names:
            for right_name in right_names:
                if left_name not in ports or right_name not in ports:
                    continue
                pair = ports[left_name], ports[right_name]
                if pair in seen:
                    continue
                seen.add(pair)
                connections.append(IsolationConnection(*pair, side, description))
    # External substrate checks precede internal checks consistently across
    # imports, while preserving the original spellings in every expression.
    connections.sort(key=lambda item: 0 if item.side == "outer" else 1)
    return connections
