from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

from .models import ExportSet, Rule
from .schema import PROJECT_SCHEMA, adapter_metadata, validate_adapter_config, validate_project_payload


MODEL_SOA_MODES = {"native", "annotate", "approximate", "dual"}


def model_soa_sources(
    sources: Iterable[dict[str, object]] | None,
) -> list[dict[str, object]]:
    """Keep only safe, model-internal SOA records for export metadata."""
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for source in sources or []:
        if not source or not (source.get("model_internal_soa") or source.get("mechanism")):
            continue
        path = str(source.get("path", "")).strip()
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(
            {
                "path": path,
                "kind": str(source.get("kind", "model_spectre")),
                "model_internal_soa": True,
                "mechanism": source.get("model_soa_mechanism"),
                "line": source.get("model_soa_line"),
                "note": source.get("model_soa_note", ""),
            }
        )
    return result


def model_soa_export_metadata(
    sources: Iterable[dict[str, object]] | None,
    mode: str = "native",
) -> dict[str, object]:
    if mode not in MODEL_SOA_MODES:
        raise ValueError("模型内 SOA 导出模式必须是 native、annotate、approximate 或 dual。")
    records = model_soa_sources(sources)
    warnings: list[str] = []
    if records and mode == "annotate":
        warnings.append("本次输出只记录模型内 SOA 来源，没有复制模型内部行为。")
    if records and mode == "approximate":
        warnings.append("近似输出只使用已启用的外部规则，不能复现模型内 gsoa/soa_* 曲线。")
    if records and mode == "dual":
        warnings.append("双输出同时保留模型内 SOA 和外部 assert，可能产生重复告警，请按器件和规则检查。")
    return {"mode": mode, "sources": records, "warnings": warnings}


def select_rules(rules: Iterable[Rule], export_set: ExportSet) -> list[Rule]:
    rules = list(rules)
    selected = set(export_set.rule_ids)
    if selected:
        return [rule for rule in rules if rule.rule_id in selected and rule.effective("enabled") and rule.effective("status") not in {"missing", "not_applicable"}]
    if export_set.device_names:
        devices = set(export_set.device_names)
        return [rule for rule in rules if rule.target in devices and rule.effective("enabled") and rule.effective("status") not in {"missing", "not_applicable"}]
    return [rule for rule in rules if rule.effective("enabled") and rule.effective("status") not in {"missing", "not_applicable"}]


def render_spectre(
    rules: Iterable[Rule],
    section: str = "soa_generated",
    *,
    model_sources: Iterable[dict[str, object]] | None = None,
    model_soa_mode: str = "annotate",
) -> str:
    metadata = model_soa_export_metadata(model_sources, model_soa_mode)
    lines = [
        "simulator lang=spectre insensitive=yes",
    ]
    records = metadata["sources"]
    if records:
        lines.extend(["", "// SOA generator: model-internal SOA provenance"])
        for record in records:
            path = str(record["path"]).replace("\\", "\\\\").replace('"', '\\"')
            mechanism = record.get("mechanism") or "unknown"
            line = record.get("line")
            location = f" line {line}" if line else ""
            lines.append(f"// mode={metadata['mode']} mechanism={mechanism}{location}: {path}")
            if metadata["mode"] in {"native", "dual"}:
                lines.append(f'include "{path}"')
        for warning in metadata["warnings"]:
            lines.append(f"// WARNING: {warning}")
    lines.extend(["", f"section {section}"])
    for rule in rules:
        if not rule.effective("enabled") or rule.effective("status") in {"missing", "not_applicable"}:
            continue
        parts = [str(rule.effective("name")), "assert"]
        target_key = "subs" if rule.effective("target_kind") == "subs" else "sub"
        parts.append(f"{target_key}={rule.effective('target')}")
        expr = rule.effective("expr")
        maximum = rule.effective("maximum")
        minimum = rule.effective("minimum")
        message = rule.effective("message")
        level = rule.effective("level")
        duration = rule.effective("duration")
        if expr:
            parts.append(f'expr="{expr}"')
        if maximum is not None and maximum != "":
            parts.append(f"max={maximum}")
        if minimum is not None and minimum != "":
            parts.append(f"min={minimum}")
        if message:
            parts.append(f'message="{message}"')
        if level:
            parts.append(f"level={level}")
        if duration:
            parts.append(f"duration={duration}")
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
    model_sources: Iterable[dict[str, object]] | None = None,
    model_soa_mode: str = "native",
    devices: Iterable[dict[str, object]] | None = None,
    sources: Iterable[dict[str, object]] | None = None,
    adapter: dict[str, object] | None = None,
    source_priority: Iterable[str] | None = None,
) -> str:
    if adapter is not None:
        adapter_issues = validate_adapter_config(adapter)
        if adapter_issues:
            raise ValueError("适配器配置无效：" + "；".join(item["message"] for item in adapter_issues))
    payload: dict[str, object] = {
        "schema": PROJECT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generator": {"name": "soa-generator", "version": "0.1"},
        "process": {"path": process_path, "version": process_version, "adapter": adapter_metadata(adapter)},
        "adapter_config": adapter,
        "source_priority": list(source_priority or []),
        "export_set": export_set.to_dict(),
        "devices": list(devices or []),
        "sources": list(sources or []),
        "rules": [rule.to_dict() for rule in rules],
        "model_soa": model_soa_export_metadata(model_sources, model_soa_mode),
    }
    if extra:
        payload.update(extra)
    issues = validate_project_payload(payload)
    if issues:
        raise ValueError("项目 JSON 不符合 schema：" + "；".join(item["message"] for item in issues))
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
