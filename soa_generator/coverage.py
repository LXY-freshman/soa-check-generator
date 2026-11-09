"""Coverage summaries for an imported PDK parse session."""

from __future__ import annotations

from collections import Counter
from typing import Iterable


def pdk_coverage(
    devices: Iterable[dict[str, object]],
    rules: Iterable[dict[str, object]],
    sources: Iterable[dict[str, object]] = (),
) -> dict[str, object]:
    device_list = list(devices)
    rule_list = list(rules)
    source_list = list(sources)
    family_counts = Counter(str(device.get("family", "unknown")) for device in device_list)
    scope_counts = Counter(str(device.get("scope", "unknown")) for device in device_list)
    route_counts = Counter(str(rule.get("route", "unknown")) for rule in rule_list)
    status_counts = Counter(str(rule.get("status", rule.get("confidence", "unknown"))) for rule in rule_list)
    source_kind_counts = Counter(str(source.get("kind", "unknown")) for source in source_list)
    matrix_status_counts: Counter[str] = Counter()
    device_reports: list[dict[str, object]] = []
    for device in device_list:
        matrix = [item for item in (device.get("check_matrix") or []) if isinstance(item, dict)]
        matrix_status_counts.update(str(item.get("status", "unknown")) for item in matrix)
        applicable = [item for item in matrix if item.get("applicable")]
        complete = [item for item in applicable if item.get("maximum") not in (None, "") or item.get("minimum") not in (None, "")]
        missing = [item for item in applicable if item.get("status") == "missing"]
        inferred = [item for item in applicable if item.get("status") == "inferred"]
        conflicts = [item for item in applicable if item.get("status") == "conflict" or item.get("conflict")]
        device_reports.append({
            "name": device.get("name", ""),
            "family": device.get("family", "unknown"),
            "scope": device.get("scope", "unknown"),
            "profile_stage": device.get("profile_stage", "skeleton"),
            "profile_completeness": device.get("profile_completeness", 0),
            "ports": list(device.get("ports") or []),
            "port_roles": dict(device.get("port_roles") or {}),
            "applicable_checks": len(applicable),
            "complete_checks": len(complete),
            "missing_checks": [item.get("limit_kind") for item in missing],
            "inferred_checks": [item.get("limit_kind") for item in inferred],
            "conflict_checks": [item.get("limit_kind") for item in conflicts],
        })
    return {
        "schema": "soa-coverage/v1",
        "summary": {
            "devices": len(device_list),
            "rules": len(rule_list),
            "sources": len(source_list),
            "families": dict(family_counts),
            "scopes": dict(scope_counts),
            "rule_routes": dict(route_counts),
            "rule_statuses": dict(status_counts),
            "matrix_statuses": dict(matrix_status_counts),
            "devices_with_missing_checks": sum(bool(item["missing_checks"]) for item in device_reports),
            "devices_with_conflicts": sum(bool(item["conflict_checks"]) for item in device_reports),
        },
        "sources": {"kinds": dict(source_kind_counts)},
        "devices": device_reports,
    }
