from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Union
from typing import Any


PROJECT_SCHEMA = "soa-project/v1"
ADAPTER_SCHEMA = "soa-adapter/v1"


def project_schema_document() -> Dict[str, Any]:
    """Return the intentionally small, dependency-free project contract."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PROJECT_SCHEMA,
        "type": "object",
        "required": ["schema", "created_at", "process", "export_set", "rules"],
        "properties": {
            "schema": {"const": PROJECT_SCHEMA},
            "created_at": {"type": "string"},
            "generator": {"type": "object"},
            "process": {"type": "object", "required": ["path", "version"]},
            "adapter_config": {"type": ["object", "null"]},
            "source_priority": {"type": "array"},
            "export_set": {"type": "object"},
            "devices": {"type": "array"},
            "sources": {"type": "array"},
            "rules": {"type": "array"},
            "model_soa": {"type": "object"},
        },
    }


def validate_project_payload(payload: Any) -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []
    if not isinstance(payload, dict):
        return [{"code": "project_not_object", "message": "项目文件顶层必须是 JSON 对象。"}]
    if payload.get("schema") != PROJECT_SCHEMA:
        issues.append({"code": "project_schema", "message": f"项目 schema 必须是 {PROJECT_SCHEMA}。"})
    process = payload.get("process")
    if not isinstance(process, dict):
        issues.append({"code": "project_process", "message": "项目缺少 process 对象。"})
    else:
        if "path" not in process:
            issues.append({"code": "process_path", "message": "process.path 不能为空。"})
        if "version" not in process:
            issues.append({"code": "process_version", "message": "process.version 字段缺失。"})
    export_set = payload.get("export_set")
    if not isinstance(export_set, dict):
        issues.append({"code": "project_export_set", "message": "项目缺少 export_set 对象。"})
    rules = payload.get("rules")
    if not isinstance(rules, list):
        issues.append({"code": "project_rules", "message": "rules 必须是数组。"})
    else:
        seen: Set[str] = set()
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                issues.append({"code": "rule_object", "message": f"rules[{index}] 必须是对象。"})
                continue
            rule_id = str(rule.get("rule_id", ""))
            if not rule_id:
                issues.append({"code": "rule_id", "message": f"rules[{index}] 缺少 rule_id。"})
            elif rule_id in seen:
                issues.append({"code": "duplicate_rule_id", "message": f"重复规则 ID：{rule_id}"})
            seen.add(rule_id)
            if not rule.get("target"):
                issues.append({"code": "rule_target", "message": f"rules[{index}] 缺少 target。"})
    for key in ("devices", "sources"):
        if key in payload and not isinstance(payload[key], list):
            issues.append({"code": f"project_{key}", "message": f"{key} 必须是数组。"})
    model_soa = payload.get("model_soa")
    if model_soa is not None and not isinstance(model_soa, dict):
        issues.append({"code": "model_soa", "message": "model_soa 必须是对象。"})
    if payload.get("adapter_config") is not None:
        issues.extend(validate_adapter_config(payload.get("adapter_config")))
    return issues


def validate_adapter_config(config: Any) -> List[Dict[str, str]]:
    if not isinstance(config, dict):
        return [{"code": "adapter_not_object", "message": "适配器配置顶层必须是 JSON 对象。"}]
    issues: List[Dict[str, str]] = []
    if config.get("schema") != ADAPTER_SCHEMA:
        issues.append({"code": "adapter_schema", "message": f"适配器 schema 必须是 {ADAPTER_SCHEMA}。"})
    if not config.get("id"):
        issues.append({"code": "adapter_id", "message": "适配器缺少 id。"})
    if not config.get("version"):
        issues.append({"code": "adapter_version", "message": "适配器缺少 version。"})
    rules = config.get("device_rules", [])
    if not isinstance(rules, list):
        issues.append({"code": "adapter_device_rules", "message": "device_rules 必须是数组。"})
    else:
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict) or not rule.get("pattern"):
                issues.append({"code": "adapter_rule", "message": f"device_rules[{index}] 必须包含 pattern。"})
            if not isinstance(rule, dict):
                continue
            isolation_type = rule.get("isolation_type", "unknown")
            if not isinstance(isolation_type, str) or isolation_type not in {"unknown", "junction", "dielectric"}:
                issues.append({"code": "isolation_type", "message": f"device_rules[{index}].isolation_type 必须是 unknown、junction 或 dielectric。"})
            roles = rule.get("port_roles", {})
            if not isinstance(roles, dict) or any(not isinstance(value, str) for value in roles.values()):
                issues.append({"code": "port_roles", "message": f"device_rules[{index}].port_roles 必须为端口到角色的对象。"})
            edges = rule.get("isolation_junctions", [])
            if not isinstance(edges, list) or any(not isinstance(edge, dict) or not isinstance(edge.get("p_port"), str) or not edge.get("p_port") or not isinstance(edge.get("n_port"), str) or not edge.get("n_port") or edge.get("p_port") == edge.get("n_port") for edge in edges):
                issues.append({"code": "isolation_junctions", "message": f"device_rules[{index}].isolation_junctions 必须是含不同 p_port/n_port 的 PN 结数组。"})
            elif any(edge.get("source") is not None and not isinstance(edge["source"], dict) for edge in edges):
                issues.append({"code": "isolation_source", "message": f"device_rules[{index}] 的隔离结 source 必须是来源对象。"})
    check_rules = config.get("check_rules", [])
    if not isinstance(check_rules, list):
        issues.append({"code": "adapter_check_rules", "message": "check_rules 必须是数组。"})
    else:
        for index, rule in enumerate(check_rules):
            if not isinstance(rule, dict) or not rule.get("pattern") or not rule.get("expr"):
                issues.append({"code": "adapter_check_rule", "message": f"check_rules[{index}] 必须包含 pattern 和 expr。"})
            if isinstance(rule, dict) and rule.get("page") is not None:
                try:
                    if int(rule["page"]) < 1:
                        raise ValueError
                except (TypeError, ValueError):
                    issues.append({"code": "adapter_check_page", "message": f"check_rules[{index}].page 必须是正整数。"})
    return issues


def adapter_metadata(config: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    if not config:
        return None
    return {"id": str(config.get("id", "")), "version": str(config.get("version", ""))}
