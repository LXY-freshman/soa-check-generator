from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Union
import os
from ._compat import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class CandidateFile:
    path: str
    kind: str
    size: int

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _kind(path: str) -> Optional[str]:
    name = os.path.basename(path).lower()
    if name.endswith(".devicelist") or name == "device_list":
        return "device_list"
    if name.endswith(".scs") and ("soa" in name or "esoa" in name):
        return "spectre_soa"
    if name.endswith(".mdl") and "soa" in name:
        return "hspice_soa" if any(part in path.lower().split(os.sep) for part in ("hspice", "hsp")) else "spectre_soa"
    if name.endswith(".biaschk") or name.endswith(".lis") and "soa" in name:
        return "hspice_soa"
    if name.endswith(".mdl") or name.endswith(".scs") or name.endswith(".ckt") or name.endswith(".lib"):
        return "model_spectre" if name.endswith((".scs", ".mdl")) else "model_spice"
    if name.endswith((".va", ".vams")):
        return "verilog_a"
    if name.endswith(".cat") or name.endswith(".cat%"):
        return "catalog"
    if name.endswith(".pdf") or name.endswith(".txt") or "readme" in name:
        return "document"
    return None


def discover_local(root: str, max_files: int = 100_000, max_depth: int = 8) -> List[CandidateFile]:
    result: List[CandidateFile] = []
    root_depth = os.path.abspath(root).count(os.sep)
    for current, dirs, files in os.walk(root):
        depth = os.path.abspath(current).count(os.sep) - root_depth
        dirs[:] = [
            name
            for name in dirs
            if name not in {".git", "__pycache__", "stream", "Calibre", "CCI_QRC", "layout", "symbol", "thumbnail"}
            and depth < max_depth
        ]
        for name in files:
            path = os.path.join(current, name)
            kind = _kind(path)
            if kind is None:
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            result.append(CandidateFile(path=path, kind=kind, size=size))
            if len(result) >= max_files:
                return result
    return result


def summarize_candidates(candidates: Iterable[CandidateFile]) -> Dict[str, int]:
    summary: Dict[str, int] = {}
    for item in candidates:
        summary[item.kind] = summary.get(item.kind, 0) + 1
    return summary
