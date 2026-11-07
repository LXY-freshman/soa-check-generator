from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

from .models import ExportSet, Rule


def select_rules(rules: Iterable[Rule], export_set: ExportSet) -> list[Rule]:
    rules = list(rules)
    selected = set(export_set.rule_ids)
    if selected:
        return [rule for rule in rules if rule.rule_id in selected and rule.enabled]
    if export_set.device_names:
        devices = set(export_set.device_names)
        return [rule for rule in rules if rule.target in devices and rule.enabled]
    return [rule for rule in rules if rule.enabled]


def render_spectre(rules: Iterable[Rule], section: str = "soa_generated") -> str:
    lines = [
        "simulator lang=spectre insensitive=yes",
        "",
        f"section {section}",
    ]
    for rule in rules:
        if not rule.enabled:
            continue
        parts = [rule.name, "assert"]
        target_key = "subs" if rule.target_kind == "subs" else "sub"
        parts.append(f"{target_key}={rule.target}")
        if rule.expr:
            parts.append(f'expr="{rule.expr}"')
        if rule.maximum is not None:
            parts.append(f"max={rule.maximum}")
        if rule.minimum is not None:
            parts.append(f"min={rule.minimum}")
        if rule.message:
            parts.append(f'message="{rule.message}"')
        if rule.level:
            parts.append(f"level={rule.level}")
        if rule.duration:
            parts.append(f"duration={rule.duration}")
        lines.append(" ".join(parts))
    lines.extend([f"endsection {section}", ""])
    return "\n".join(lines)


def project_json(
    *,
    process_path: str,
    process_version: str | None,
    rules: Iterable[Rule],
    export_set: ExportSet,
    extra: dict[str, object] | None = None,
) -> str:
    payload: dict[str, object] = {
        "schema": "soa-project/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "process": {"path": process_path, "version": process_version},
        "export_set": export_set.to_dict(),
        "rules": [rule.to_dict() for rule in rules],
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
