from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .classify import apply_device_metadata, classify_device
from .models import Device, Rule, SourceEvidence


_ASSERT_RE = re.compile(r"^(?P<name>\S+)\s+assert\s+(?P<body>.*)$", re.I)
_FIELD_RE = re.compile(r"(?P<key>sub|subs|expr|message|level|duration|max|min)\s*=\s*(?P<value>\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[^\s]+)", re.I)
_SECTION_RE = re.compile(r"^section\s+(?P<section>\S+)", re.I)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _targets(value: str) -> list[str]:
    value = _unquote(value).strip("[]")
    return [item.strip(" '\"") for item in value.split(",") if item.strip(" '\"")]


def parse_spectre_asserts(text: str, source_path: str = "<memory>") -> list[Rule]:
    rules: list[Rule] = []
    section: str | None = None
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        section_match = _SECTION_RE.match(line)
        if section_match:
            section = section_match.group("section")
        if not line or line.startswith(("//", "*", "$") ):
            continue
        match = _ASSERT_RE.match(line)
        if not match:
            continue
        fields = {item.group("key").lower(): _unquote(item.group("value")) for item in _FIELD_RE.finditer(match.group("body"))}
        target_key = "subs" if "subs" in fields else "sub" if "sub" in fields else "unknown"
        targets = _targets(fields.get(target_key, "")) or [""]
        for target_index, target in enumerate(targets):
            rule = Rule(
                rule_id=f"{Path(source_path).name}:{line_number}:{match.group('name')}:{target_index}",
                name=match.group("name"),
                target=target,
                target_kind=target_key,  # type: ignore[arg-type]
                expr=fields.get("expr", ""),
                maximum=fields.get("max"),
                minimum=fields.get("min"),
                message=fields.get("message"),
                level=fields.get("level"),
                duration=fields.get("duration"),
                section=section,
                line=line_number,
                source=SourceEvidence(
                    path=source_path,
                    line=line_number,
                    mechanism="spectre_assert",
                ),
            )
            rule.original = rule.to_dict()
            rules.append(apply_device_metadata(rule))
    # A single Spectre check can be written as two source lines, one with min
    # and one with max. Keep one editable rule when every other condition is
    # identical, so the export restores a single bounded assertion.
    merged: list[Rule] = []
    by_signature: dict[tuple[str, str, str, str | None, str | None, str | None, str | None], Rule] = {}
    for rule in rules:
        signature = (rule.target, rule.target_kind, rule.expr, rule.message, rule.level, rule.duration, rule.section)
        current = by_signature.get(signature)
        can_merge = current is not None and (
            (current.maximum is None and rule.maximum is not None)
            or (current.minimum is None and rule.minimum is not None)
        )
        if can_merge:
            if current.maximum is None:
                current.maximum = rule.maximum
            if current.minimum is None:
                current.minimum = rule.minimum
            current.notes.append(f"合并来源：{rule.name}（第 {rule.line} 行）")
            continue
        by_signature[signature] = rule
        merged.append(rule)
    return merged


def parse_device_list(text: str, source_path: str = "<memory>") -> list[Device]:
    devices: list[Device] = []
    category = "unknown"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("******"):
            value = line.strip("* ")
            if value:
                category = value
            continue
        if line.startswith(("*", "/", "#")) or " " in line or "\t" in line:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_]+", line):
            continue
        device = classify_device(line, category)
        device.source = SourceEvidence(path=source_path, mechanism="manual_table")
        devices.append(device)
    return devices


def merge_devices(devices: Iterable[Device], rules: Iterable[Rule]) -> list[Device]:
    by_name = {device.name: device for device in devices}
    for rule in rules:
        if rule.target not in by_name:
            by_name[rule.target] = classify_device(rule.target)
        device = by_name[rule.target]
        device.soa_status = "source_rule"
    return sorted(by_name.values(), key=lambda item: item.name.lower())
