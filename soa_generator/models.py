from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Confidence = Literal["confirmed", "documented", "inferred", "missing", "conflict"]
Mechanism = Literal[
    "spectre_assert",
    "hspice_biaschk",
    "model_internal",
    "manual_table",
    "unknown",
]


@dataclass
class SourceEvidence:
    path: str
    line: int | None = None
    page: int | None = None
    mechanism: Mechanism = "unknown"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Device:
    name: str
    category: str = "unknown"
    scope: str = "active"
    family: str = "unknown"
    topology: list[str] = field(default_factory=list)
    family_voltage: float | None = None
    isolation_voltage: float | None = None
    isolation_confidence: str = "missing"
    ports: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    source: SourceEvidence | None = None
    soa_status: str = "unknown"
    associated_devices: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Rule:
    rule_id: str
    name: str
    target: str
    target_kind: Literal["sub", "subs", "unknown"] = "unknown"
    expr: str = ""
    maximum: str | None = None
    minimum: str | None = None
    message: str | None = None
    level: str | None = None
    duration: str | None = None
    section: str | None = None
    line: int | None = None
    limit_kind: str = "other"
    device_family: str = "unknown"
    confidence: Confidence = "confirmed"
    enabled: bool = True
    source: SourceEvidence | None = None
    original: dict[str, Any] | None = None
    override: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def effective(self, key: str) -> Any:
        if key in self.override:
            return self.override[key]
        return getattr(self, key)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.source:
            value["source"] = self.source.to_dict()
        return value


@dataclass
class ExportSet:
    name: str = "default"
    device_names: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    include_dependencies: bool = True
    formats: list[str] = field(default_factory=lambda: ["spectre", "json"])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
