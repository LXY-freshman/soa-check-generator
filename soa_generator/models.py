from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Union
from ._compat import asdict, dataclass, field


Confidence = str
Mechanism = str


@dataclass
class SourceEvidence:
    path: str
    line: Optional[int] = None
    page: Optional[int] = None
    mechanism: Mechanism = "unknown"
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Device:
    name: str
    category: str = "unknown"
    scope: str = "active"
    family: str = "unknown"
    topology: List[str] = field(default_factory=list)
    family_voltage: Optional[float] = None
    gate_voltage: Optional[float] = None
    gate_voltage_confidence: str = "missing"
    isolation_voltage: Optional[float] = None
    isolation_confidence: str = "missing"
    isolation_type: str = "unknown"
    ports: List[str] = field(default_factory=list)
    port_roles: Dict[str, str] = field(default_factory=dict)
    port_confidence: str = "missing"
    model_parameters: Dict[str, str] = field(default_factory=dict)
    model_limits: List[Dict[str, str]] = field(default_factory=list)
    parameter_confidence: str = "missing"
    aliases: List[str] = field(default_factory=list)
    model_sources: List[Dict[str, Any]] = field(default_factory=list)
    isolation_junctions: List[Dict[str, Any]] = field(default_factory=list)
    source: Optional[SourceEvidence] = None
    soa_status: str = "unknown"
    associated_devices: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    profile_stage: str = "skeleton"
    profile_completeness: float = 0.0
    check_matrix: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Rule:
    rule_id: str
    name: str
    target: str
    target_kind: str = "unknown"
    expr: str = ""
    maximum: Optional[str] = None
    minimum: Optional[str] = None
    message: Optional[str] = None
    level: Optional[str] = None
    duration: Optional[str] = None
    section: Optional[str] = None
    line: Optional[int] = None
    limit_kind: str = "other"
    terminal_pair: List[str] = field(default_factory=list)
    device_family: str = "unknown"
    confidence: Confidence = "confirmed"
    enabled: bool = True
    source: Optional[SourceEvidence] = None
    original: Optional[Dict[str, Any]] = None
    override: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    status: str = "source"
    route: str = "native"

    def effective(self, key: str) -> Any:
        if key in self.override:
            return self.override[key]
        return getattr(self, key)

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        if self.source:
            value["source"] = self.source.to_dict()
        return value


@dataclass
class ExportSet:
    name: str = "default"
    device_names: List[str] = field(default_factory=list)
    rule_ids: List[str] = field(default_factory=list)
    include_dependencies: bool = True
    formats: List[str] = field(default_factory=lambda: ["spectre", "json"])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
