from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import shlex
import shutil
import stat
import subprocess
import tempfile
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .discovery import CandidateFile, discover_local, summarize_candidates
from .adapters import apply_adapter_config
from .classify import apply_port_metadata, classify_device
from .export import model_soa_export_metadata, project_json, render_spectre, select_rules
from .inference import model_rule_candidates, non_mos_rule_candidates
from .models import ExportSet, Rule, SourceEvidence
from .parsers import (
    merge_devices,
    parse_device_list,
    parse_model_definitions,
    parse_model_parameters,
    parse_model_limits,
    parse_subckt_dependencies,
    parse_spectre_asserts,
    detect_model_soa,
    topology_rule_candidates,
)
from .validation import lint_rules
from .schema import adapter_metadata, project_schema_document, validate_adapter_config, validate_project_payload


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"


def _spectre_diagnostics(output: str, exit_code: int) -> list[dict[str, object]]:
    """Convert Spectre's human log into compact UI issues."""
    issues: list[dict[str, object]] = []
    lines = output.splitlines()
    seen: set[tuple[str, str]] = set()
    for raw in lines:
        line = raw.strip()
        upper = line.upper()
        if "ERROR (" in upper or "FATAL (" in upper:
            severity = "error"
        elif "WARNING (" in upper:
            severity = "warning"
        else:
            continue
        message = line
        code_match = re.search(r"\(([A-Z][A-Z0-9-]+)\)", line) or re.search(r"\b([A-Z][A-Z0-9-]+)\b", line)
        code = f"spectre_{code_match.group(1).lower()}" if code_match else "spectre_diagnostic"
        key = (severity, message)
        if key in seen:
            continue
        seen.add(key)
        issues.append({
            "severity": severity,
            "code": code,
            "message": message[:600],
        })
    if exit_code != 0 and not any(item["severity"] == "error" for item in issues):
        issues.insert(0, {
            "severity": "error",
            "code": "spectre_exit",
            "message": f"Spectre 退出码为 {exit_code}，请查看后续诊断信息。",
        })
    return issues


def _quick_check_main(library_name: str, section: str = "soa_generated") -> str:
    return "\n".join([
        "simulator lang=spectre",
        f'include "{library_name}" section={section}',
        "",
    ])


def _run_local_spectre_check(library_text: str, *, spectre_path: str | None = None) -> tuple[int, str]:
    executable = spectre_path or os.environ.get("SPECTRE_BIN") or shutil.which("spectre")
    if not executable:
        raise RuntimeError("本机找不到 spectre；请设置 SPECTRE_BIN，或改用 SSH 快速检查。")
    with tempfile.TemporaryDirectory(prefix="soa-spectre-check-") as temp_dir:
        root = Path(temp_dir)
        library = root / "soa_generated.scs"
        main = root / "main.scs"
        log = root / "run.log"
        raw = root / "raw"
        library.write_text(library_text, encoding="utf-8")
        main.write_text(_quick_check_main(str(library)), encoding="utf-8")
        result = subprocess.run(
            [executable, "+log", str(log), "-raw", str(raw), str(main)],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        output = "\n".join(value for value in (result.stdout, result.stderr, log.read_text(encoding="utf-8", errors="replace") if log.exists() else "") if value)
        return result.returncode, output


def _run_remote_spectre_check(source: dict[str, Any], library_text: str) -> tuple[int, str]:
    temp_name = f"/tmp/soa-spectre-check-{os.getpid()}"
    library_encoded = base64.b64encode(library_text.encode("utf-8")).decode("ascii")
    main_text = _quick_check_main(f"{temp_name}/soa_generated.scs")
    main_encoded = base64.b64encode(main_text.encode("utf-8")).decode("ascii")
    command = "; ".join([
        f"rm -rf {shlex.quote(temp_name)}",
        f"mkdir -p {shlex.quote(temp_name)}",
        f"printf %s {shlex.quote(library_encoded)} | base64 -d > {shlex.quote(temp_name + '/soa_generated.scs')}",
        f"printf %s {shlex.quote(main_encoded)} | base64 -d > {shlex.quote(temp_name + '/main.scs')}",
        f"spectre +log {shlex.quote(temp_name + '/run.log')} -raw {shlex.quote(temp_name + '/raw')} {shlex.quote(temp_name + '/main.scs')} >/dev/null 2>&1",
        "status=$?",
        f"cat {shlex.quote(temp_name + '/run.log')} 2>/dev/null",
        f"printf '\\n__SOA_SPECTRE_STATUS__=%s\\n' \"$status\"",
        f"rm -rf {shlex.quote(temp_name)}",
        "exit 0",
    ])
    result = _ssh_run(source, command)
    match = re.search(r"__SOA_SPECTRE_STATUS__=(\d+)", result.stdout)
    if not match:
        raise RuntimeError("远程 Spectre 没有返回可识别的退出状态。")
    output = re.sub(r"\n__SOA_SPECTRE_STATUS__=\d+\s*$", "", result.stdout)
    return int(match.group(1)), output


def quick_check(
    rules: list[Rule],
    devices: list[str],
    runner: dict[str, Any],
    *,
    model_sources: list[dict[str, Any]] | None = None,
    model_soa_mode: str = "annotate",
) -> dict[str, Any]:
    static = lint_rules(rules, known_devices=set(devices) or None)
    spectre_text = render_spectre(
        rules,
        model_sources=model_sources or [],
        model_soa_mode=model_soa_mode,
    )
    kind = str(runner.get("kind", "local"))
    if kind == "ssh":
        exit_code, output = _run_remote_spectre_check(runner, spectre_text)
        runner_label = "SSH 远程 Spectre"
    else:
        exit_code, output = _run_local_spectre_check(spectre_text, spectre_path=runner.get("spectre_path"))
        runner_label = "本机 Spectre"
    runtime = _spectre_diagnostics(output, exit_code)
    issues = [item.to_dict() for item in static] + runtime
    return {
        "ok": not any(item.get("severity") == "error" for item in issues),
        "runner": runner_label,
        "exit_code": exit_code,
        "issues": issues,
        "output_tail": output[-6000:],
    }


def _read_local(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _ssh_run(source: dict[str, Any], remote_command: str) -> subprocess.CompletedProcess[str]:
    host = str(source["host"]).strip()
    user = str(source.get("user", "")).strip()
    port = str(source.get("port", "")).strip()
    password = str(source.get("password", ""))
    if not host:
        raise ValueError("SSH 主机地址不能为空")
    target = f"{user}@{host}" if user else host
    command = ["ssh", "-o", "ConnectTimeout=12", "-o", "StrictHostKeyChecking=accept-new"]
    if password:
        command.extend(["-o", "BatchMode=no", "-o", "PreferredAuthentications=password,keyboard-interactive"])
    else:
        command.extend(["-o", "BatchMode=yes"])
    if port:
        command.extend(["-p", port])
    command.extend([target, remote_command])
    try:
        if not password:
            return subprocess.run(command, check=True, capture_output=True, text=True)
        # OpenSSH asks SSH_ASKPASS for a password without putting it in argv.
        with tempfile.TemporaryDirectory(prefix="soa-ssh-") as temp_dir:
            askpass = Path(temp_dir) / "askpass"
            askpass.write_text("#!/bin/sh\nprintf '%s\\n' \"$SOA_SSH_PASSWORD\"\n", encoding="utf-8")
            askpass.chmod(stat.S_IRWXU)
            env = os.environ.copy()
            env.update({"SSH_ASKPASS": str(askpass), "SSH_ASKPASS_REQUIRE": "force", "DISPLAY": "soa-generator", "SOA_SSH_PASSWORD": password})
            return subprocess.run(["setsid", "-w", *command], check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
    except FileNotFoundError as exc:
        raise RuntimeError("本机找不到 ssh 命令，请先安装 OpenSSH 客户端。") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        lower = detail.lower()
        if "could not resolve hostname" in lower or "name or service not known" in lower:
            message = "无法解析 SSH 主机地址，请检查主机名或 IP。"
        elif "timed out" in lower or "operation timed out" in lower:
            message = "SSH 连接超时，请检查地址、端口和网络。"
        elif "connection refused" in lower:
            message = "SSH 连接被拒绝，请检查端口和远程 SSH 服务。"
        elif "permission denied" in lower or "authentication" in lower or "auth fail" in lower:
            message = "SSH 认证失败，请检查用户名、密码或系统 SSH 认证配置。"
        elif "no such file or directory" in lower or "cannot access" in lower:
            message = "远程路径不存在或当前账号没有读取权限。"
        else:
            compact = " ".join(detail.split())
            message = f"SSH 操作失败：{compact[:240]}" if compact else "SSH 操作失败，请检查连接参数。"
        raise RuntimeError(message) from exc


def _read_ssh(source: dict[str, Any], path: str) -> str:
    command = f"cat -- {shlex.quote(path)}"
    return _ssh_run(source, command).stdout


def read_source(source: dict[str, Any]) -> str:
    if source.get("kind", "local") == "ssh":
        return _read_ssh(source, str(source["path"]))
    return _read_local(str(source["path"]))


def _candidate_from_dict(value: dict[str, Any]) -> CandidateFile:
    return CandidateFile(path=str(value["path"]), kind=str(value["kind"]), size=int(value.get("size", 0)))


def _ssh_candidates(source: dict[str, Any], root: str) -> list[CandidateFile]:
    pattern = "-iname '*.devicelist' -o -name device_list -o -iname '*soa*.mdl' -o -iname '*eSOA*.scs' -o -iname '*.Cat' -o -iname '*.Cat%'"
    command = f"find {shlex.quote(root)} -type f \\( {pattern} \\) -printf '%s\\t%p\\n' | head -1000"
    result = _ssh_run(source, command)
    candidates: list[CandidateFile] = []
    for line in result.stdout.splitlines():
        try:
            size, path = line.split("\t", 1)
        except ValueError:
            continue
        lower = path.lower()
        if "devicelist" in lower or lower.endswith("device_list"):
            kind = "device_list"
        elif "soa" in lower or "esoa" in lower:
            kind = "hspice_soa" if "/hspice/" in lower or "/hsp/" in lower else "spectre_soa"
        elif lower.endswith((".mdl", ".scs")):
            kind = "model_spectre"
        elif lower.endswith((".ckt", ".lib")):
            kind = "model_spice"
        elif lower.endswith((".pdf", ".txt")) or "readme" in lower:
            kind = "document"
        else:
            kind = "catalog"
        candidates.append(CandidateFile(path=path, kind=kind, size=int(size)))
    return candidates


def discover(source: dict[str, Any]) -> list[CandidateFile]:
    if source.get("kind", "local") == "ssh":
        return _ssh_candidates(source, str(source["path"]))
    path = Path(str(source["path"]))
    if path.is_file():
        kind = "spectre_soa" if "soa" in path.name.lower() else "device_list"
        return [CandidateFile(path=str(path), kind=kind, size=path.stat().st_size)]
    return discover_local(str(path))


def parse_source(source: dict[str, Any], adapter_config: dict[str, Any] | None = None) -> dict[str, Any]:
    text = read_source(source)
    path = str(source["path"])
    lower = path.lower()
    if "devicelist" in lower or lower.endswith("device_list"):
        devices = parse_device_list(text, path)
        rules: list[Rule] = []
    else:
        rules = parse_spectre_asserts(text, path)
        devices = []
    definitions = parse_model_definitions(text)
    model_parameters = parse_model_parameters(text)
    model_limits = parse_model_limits(text)
    dependencies = parse_subckt_dependencies(text)
    for name, ports, line in definitions:
        device = classify_device(name, "model")
        apply_port_metadata(device, ports)
        device.model_parameters = model_parameters.get(name, {})
        device.model_limits = model_limits.get(name, [])
        device.associated_devices = dependencies.get(name, [])
        if device.model_parameters:
            device.parameter_confidence = "confirmed"
        device.source = SourceEvidence(path=path, line=line, mechanism="unknown", note="模型定义")
        devices.append(device)
    devices = merge_devices(devices, rules)
    apply_adapter_config(devices, rules, adapter_config)
    candidates = topology_rule_candidates(devices, rules, path)
    rules.extend(candidates)
    rules.extend(model_rule_candidates(devices, rules, path))
    rules.extend(non_mos_rule_candidates(devices, rules, path))
    devices = merge_devices(devices, rules)
    safe_source = {key: value for key, value in source.items() if key != "password"}
    return {
        "source": safe_source,
        "adapter": adapter_metadata(adapter_config),
        "devices": [item.to_dict() for item in devices],
        "rules": [item.to_dict() for item in rules],
        "summary": {"files": 1, "devices": len(devices), "rules": len(rules)},
    }


def parse_text(text: str, path: str, adapter_config: dict[str, Any] | None = None) -> dict[str, Any]:
    lower = path.lower()
    if "devicelist" in lower or lower.endswith("device_list"):
        devices = parse_device_list(text, path)
        rules: list[Rule] = []
    else:
        rules = parse_spectre_asserts(text, path)
        devices = []
    source_rule_count = len(rules)
    model_parameters = parse_model_parameters(text)
    model_limits = parse_model_limits(text)
    dependencies = parse_subckt_dependencies(text)
    for name, ports, line in parse_model_definitions(text):
        device = classify_device(name, "model")
        apply_port_metadata(device, ports)
        device.model_parameters = model_parameters.get(name, {})
        device.model_limits = model_limits.get(name, [])
        device.associated_devices = dependencies.get(name, [])
        if device.model_parameters:
            device.parameter_confidence = "confirmed"
        device.source = SourceEvidence(path=path, line=line, mechanism="unknown", note="模型定义")
        devices.append(device)
    devices = merge_devices(devices, rules)
    apply_adapter_config(devices, rules, adapter_config)
    rules.extend(topology_rule_candidates(devices, rules, path))
    rules.extend(model_rule_candidates(devices, rules, path))
    rules.extend(non_mos_rule_candidates(devices, rules, path))
    devices = merge_devices(devices, rules)
    model_soa = detect_model_soa(text)
    return {
        "source": {"kind": "browser_file", "path": path},
        "adapter": adapter_metadata(adapter_config),
        "devices": [item.to_dict() for item in devices],
        "rules": [item.to_dict() for item in rules],
        "file_results": [{
            "path": path,
            "kind": "device_list" if "devicelist" in lower or lower.endswith("device_list") else "model_spectre",
            "role": "规则源" if source_rule_count else "器件资料",
            "status": "已识别模型内 SOA" if model_soa["enabled"] and not source_rule_count else "已提取规则" if source_rule_count else "已识别器件/端口" if devices else "已读取，等待专用抽取器",
            "rule_count": source_rule_count,
            "device_count": len(devices),
            "model_internal_soa": model_soa["enabled"],
            "model_soa_mechanism": model_soa["mechanism"],
            "model_soa_line": model_soa["line"],
            "model_soa_note": model_soa["note"],
        }],
        "summary": {"files": 1, "devices": len(devices), "rules": len(rules)},
    }


def parse_sources(sources: list[dict[str, Any]], adapter_config: dict[str, Any] | None = None) -> dict[str, Any]:
    devices = []
    rules: list[Rule] = []
    seen_paths: set[str] = set()
    seen_rules: set[tuple[str, str, str, str | None, str | None]] = set()
    file_results: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for source in sources:
        path = str(source.get("path", ""))
        if path in seen_paths:
            continue
        seen_paths.add(path)
        text = read_source(source)
        lower = path.lower()
        kind = str(source.get("candidate_kind", ""))
        is_device_list = kind == "device_list" or "devicelist" in lower or lower.endswith("device_list")
        parsed_devices = parse_device_list(text, path) if is_device_list else []
        parsed_rules = [] if is_device_list else parse_spectre_asserts(text, path)
        devices.extend(parsed_devices)
        for rule in parsed_rules:
            key = (rule.target, rule.name, rule.expr, rule.maximum, rule.minimum)
            if key not in seen_rules:
                seen_rules.add(key)
                rules.append(rule)
        definitions = parse_model_definitions(text)
        model_parameters = parse_model_parameters(text)
        model_limits = parse_model_limits(text)
        dependencies = parse_subckt_dependencies(text)
        definition_map: dict[str, tuple[list[str], int]] = {}
        for name, ports, line in definitions:
            previous = definition_map.get(name)
            if previous is None or (not previous[0] and ports):
                definition_map[name] = (ports, line)
        model_names = sorted(definition_map)
        model_soa = detect_model_soa(text)
        has_model_soa = bool(model_soa["enabled"])
        source_devices: list[Any] = []
        for name in model_names:
            ports, line = definition_map[name]
            device = classify_device(name, "model")
            apply_port_metadata(device, ports)
            device.model_parameters = model_parameters.get(name, {})
            device.model_limits = model_limits.get(name, [])
            device.associated_devices = dependencies.get(name, [])
            if device.model_parameters:
                device.parameter_confidence = "confirmed"
            apply_adapter_config([device], rules, adapter_config)
            device.source = SourceEvidence(
                path=path,
                line=line,
                mechanism="model_internal" if has_model_soa else "unknown",
                note="模型定义" + (f"；{model_soa['note']}" if has_model_soa else ""),
            )
            source_devices.append(device)
            devices.append(device)
        candidates = topology_rule_candidates(source_devices, [*rules, *parsed_rules], path)
        for rule in candidates:
            key = (rule.target, rule.name, rule.expr, rule.maximum, rule.minimum)
            if key not in seen_rules:
                seen_rules.add(key)
                rules.append(rule)
        role = "规则源" if parsed_rules else "器件资料" if parsed_devices or model_names else "文档/证据"
        status = "已提取规则" if parsed_rules else "已识别模型内 SOA" if has_model_soa else "已识别器件/端口" if parsed_devices or model_names else "已读取，等待专用抽取器"
        file_result = {"path": path, "kind": kind or "unknown", "role": role, "status": status, "rule_count": len(parsed_rules), "device_count": len(parsed_devices), "model_count": len(model_names), "port_device_count": sum(bool(ports) for ports, _line in definition_map.values()), "topology_rule_count": len(candidates), "model_names": model_names[:100], "model_internal_soa": has_model_soa, "model_soa_mechanism": model_soa["mechanism"], "model_soa_line": model_soa["line"], "model_soa_note": model_soa["note"]}
        file_results.append(file_result)
        evidence.append(file_result)
    devices = merge_devices(devices, rules)
    apply_adapter_config(devices, rules, adapter_config)
    topology = topology_rule_candidates(devices, rules)
    for rule in topology:
        key = (rule.target, rule.name, rule.expr, rule.maximum, rule.minimum)
        if key not in seen_rules:
            seen_rules.add(key)
            rules.append(rule)
    model_rules = model_rule_candidates(devices, rules)
    rules.extend(model_rules)
    non_mos = non_mos_rule_candidates(devices, rules)
    rules.extend(non_mos)
    devices = merge_devices(devices, rules)
    for device in devices:
        related = [item for item in evidence if device.name in item.get("model_names", [])]
        if device.source:
            related.append({"path": device.source.path, "role": "器件资料", "status": "已识别器件"})
        rule_sources: dict[str, bool] = {}
        for rule in rules:
            if rule.target == device.name and rule.source:
                rule_sources[rule.source.path] = rule_sources.get(rule.source.path, False) or rule.confidence == "inferred"
        related.extend(
            {
                "path": path,
                "role": "推断候选" if inferred else "规则源",
                "status": "待确认后启用" if inferred else "已提取 SOA 规则",
            }
            for path, inferred in sorted(rule_sources.items())
        )
        device.evidence = related
    safe_sources = [{key: value for key, value in source.items() if key != "password"} for source in sources]
    return {
        "sources": safe_sources,
        "adapter": adapter_metadata(adapter_config),
        "devices": [item.to_dict() for item in devices],
        "rules": [item.to_dict() for item in rules],
        "file_results": file_results,
        "evidence": evidence,
        "summary": {"files": len(seen_paths), "devices": len(devices), "rules": len(rules), "inferred_rules": len(non_mos) + len(model_rules), "evidence": len(evidence)},
    }


def _rule_from_dict(value: dict[str, Any]) -> Rule:
    value = dict(value)
    source = value.get("source")
    if isinstance(source, dict):
        source_fields = {key: source.get(key) for key in SourceEvidence.__dataclass_fields__ if key in source}
        value["source"] = SourceEvidence(**source_fields)
    else:
        value["source"] = None
    value["original"] = value.get("original")
    value["override"] = dict(value.get("override") or {})
    value["notes"] = list(value.get("notes") or [])
    return Rule(**{key: value[key] for key in Rule.__dataclass_fields__ if key in value})


class Handler(BaseHTTPRequestHandler):
    server_version = "SOAGenerator/0.1"

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json({"ok": True, "service": self.server_version})
            return
        if path == "/api/schema":
            self._send_json(project_schema_document())
            return
        file_path = WEB_ROOT / ("index.html" if path in {"", "/"} else path.lstrip("/"))
        if not file_path.is_file() or WEB_ROOT not in file_path.parents:
            self.send_error(404)
            return
        content = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(file_path))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/discover":
                candidates = discover(body["source"])
                self._send_json({"summary": summarize_candidates(candidates), "candidates": [item.to_dict() for item in candidates]})
                return
            if path == "/api/parse":
                self._send_json(parse_source(body["source"], body.get("adapter_config")))
                return
            if path == "/api/parse_text":
                self._send_json(parse_text(str(body.get("text", "")), str(body.get("path", "browser-file")), body.get("adapter_config")))
                return
            if path == "/api/parse_sources":
                self._send_json(parse_sources(body.get("sources", []), body.get("adapter_config")))
                return
            if path == "/api/parse_texts":
                devices = []
                rules: list[Rule] = []
                seen_rules: set[tuple[str, str, str, str | None, str | None]] = set()
                file_results: list[dict[str, Any]] = []
                for item in body.get("files", []):
                    path_value = str(item.get("path", "browser-file"))
                    text_value = str(item.get("text", ""))
                    is_device_list = item.get("kind") == "device_list" or path_value.lower().endswith((".devicelist", "device_list"))
                    file_devices = parse_device_list(text_value, path_value) if is_device_list else []
                    file_rules = [] if is_device_list else parse_spectre_asserts(text_value, path_value)
                    devices.extend(file_devices)
                    for rule in file_rules:
                        key = (rule.target, rule.name, rule.expr, rule.maximum, rule.minimum)
                        if key not in seen_rules:
                            seen_rules.add(key)
                            rules.append(rule)
                    model_soa = detect_model_soa(text_value)
                    file_results.append({
                        "path": path_value,
                        "kind": item.get("kind", "unknown"),
                        "role": "规则源" if item.get("kind") in {"spectre_soa", "hspice_soa"} else "器件资料",
                        "status": "已识别模型内 SOA" if model_soa["enabled"] and not file_rules else "已提取规则" if file_rules else "已识别器件" if file_devices else "已读取，等待专用抽取器",
                        "rule_count": len(file_rules),
                        "device_count": len(file_devices),
                        "model_internal_soa": model_soa["enabled"],
                        "model_soa_mechanism": model_soa["mechanism"],
                        "model_soa_line": model_soa["line"],
                        "model_soa_note": model_soa["note"],
                    })
                    model_parameters = parse_model_parameters(text_value)
                    model_limits = parse_model_limits(text_value)
                    dependencies = parse_subckt_dependencies(text_value)
                    model_devices: list[Any] = []
                    for name, ports, line in parse_model_definitions(text_value):
                        device = classify_device(name, "model")
                        apply_port_metadata(device, ports)
                        device.model_parameters = model_parameters.get(name, {})
                        device.model_limits = model_limits.get(name, [])
                        device.associated_devices = dependencies.get(name, [])
                        if device.model_parameters:
                            device.parameter_confidence = "confirmed"
                        apply_adapter_config([device], rules, body.get("adapter_config"))
                        device.source = SourceEvidence(
                            path=path_value,
                            line=line,
                            mechanism="model_internal" if model_soa["enabled"] else "unknown",
                            note="模型定义" + (f"；{model_soa['note']}" if model_soa["enabled"] else ""),
                        )
                        model_devices.append(device)
                        devices.append(device)
                    file_results[-1].update(
                        model_count=len(model_devices),
                        port_device_count=sum(bool(device.ports) for device in model_devices),
                        model_names=[device.name for device in model_devices[:100]],
                    )
                    for rule in topology_rule_candidates(model_devices, rules, path_value):
                        key = (rule.target, rule.name, rule.expr, rule.maximum, rule.minimum)
                        if key not in seen_rules:
                            seen_rules.add(key)
                            rules.append(rule)
                devices = merge_devices(devices, rules)
                apply_adapter_config(devices, rules, body.get("adapter_config"))
                topology = topology_rule_candidates(devices, rules)
                for rule in topology:
                    key = (rule.target, rule.name, rule.expr, rule.maximum, rule.minimum)
                    if key not in seen_rules:
                        seen_rules.add(key)
                        rules.append(rule)
                model_rules = model_rule_candidates(devices, rules)
                rules.extend(model_rules)
                non_mos = non_mos_rule_candidates(devices, rules)
                rules.extend(non_mos)
                devices = merge_devices(devices, rules)
                self._send_json({"adapter": adapter_metadata(body.get("adapter_config")), "devices": [item.to_dict() for item in devices], "rules": [item.to_dict() for item in rules], "file_results": file_results, "summary": {"files": len(body.get("files", [])), "devices": len(devices), "rules": len(rules), "inferred_rules": len(non_mos) + len(model_rules)}})
                return
            if path == "/api/export":
                rules = [_rule_from_dict(value) for value in body.get("rules", [])]
                export_data = body.get("export_set", {})
                export_set = ExportSet(
                    name=export_data.get("name", "default"),
                    device_names=export_data.get("device_names", []),
                    rule_ids=export_data.get("rule_ids", []),
                    include_dependencies=export_data.get("include_dependencies", True),
                    formats=export_data.get("formats", ["spectre", "json"]),
                )
                selected = select_rules(rules, export_set)
                model_sources = body.get("model_sources", [])
                model_soa_mode = str(body.get("model_soa_mode", "native"))
                model_metadata = model_soa_export_metadata(model_sources, model_soa_mode)
                self._send_json({
                    "count": len(selected),
                    "spectre": render_spectre(
                        selected,
                        model_sources=model_sources,
                        model_soa_mode=model_soa_mode,
                    ) if "spectre" in export_set.formats else None,
                    "json": project_json(
                        process_path=str(body.get("process_path", "")),
                        process_version=body.get("process_version"),
                        rules=selected,
                        export_set=export_set,
                        model_sources=model_sources,
                        model_soa_mode=model_soa_mode,
                        devices=body.get("devices", []),
                        sources=body.get("sources", []),
                        adapter=body.get("adapter_config"),
                    ) if "json" in export_set.formats else None,
                    "model_soa": model_metadata,
                })
                return
            if path == "/api/validate":
                rules = [_rule_from_dict(value) for value in body.get("rules", [])]
                known = set(body.get("devices", [])) or None
                issues = lint_rules(rules, known_devices=known)
                self._send_json({"ok": not any(item.severity == "error" for item in issues), "issues": [item.to_dict() for item in issues]})
                return
            if path == "/api/quick_check":
                rules = [_rule_from_dict(value) for value in body.get("rules", [])]
                result = quick_check(
                    rules,
                    [str(value) for value in body.get("devices", [])],
                    body.get("runner", {}),
                    model_sources=body.get("model_sources", []),
                    model_soa_mode=str(body.get("model_soa_mode", "annotate")),
                )
                self._send_json(result)
                return
            if path == "/api/schema":
                self._send_json(project_schema_document())
                return
            if path == "/api/validate_project":
                issues = validate_project_payload(body.get("project"))
                self._send_json({"ok": not issues, "issues": issues})
                return
            if path == "/api/validate_adapter":
                issues = validate_adapter_config(body.get("adapter_config"))
                self._send_json({"ok": not issues, "issues": issues})
                return
            self.send_error(404)
        except Exception as exc:  # service boundary: return readable UI error
            self._send_json({"error": str(exc)}, status=400)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"SOA generator: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
