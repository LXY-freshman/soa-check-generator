from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import discover_local, summarize_candidates
from .export import project_json, render_spectre, select_rules
from .models import ExportSet
from .parsers import detect_model_soa
from .schema import validate_adapter_config
from .service import _rule_from_dict, parse_source


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def command_scan(args: argparse.Namespace) -> int:
    candidates = discover_local(args.path)
    payload = {
        "path": args.path,
        "summary": summarize_candidates(candidates),
        "candidates": [item.to_dict() for item in candidates],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_parse(args: argparse.Namespace) -> int:
    print(json.dumps(parse_source({"kind": "local", "path": args.path}), ensure_ascii=False, indent=2))
    return 0


def command_export(args: argparse.Namespace) -> int:
    adapter = None
    if args.adapter_config:
        adapter = json.loads(_read(args.adapter_config))
        issues = validate_adapter_config(adapter)
        if issues:
            raise SystemExit("适配器配置无效：" + "；".join(item["message"] for item in issues))
    export_set = ExportSet(name=args.name, formats=args.formats)
    parsed = parse_source({"kind":"local", "path":args.path}, adapter_config=adapter)
    rules = [_rule_from_dict(item) for item in parsed["rules"]]
    selected = select_rules(rules, export_set)
    model_sources = []
    for source_path in args.model_source:
        detection = detect_model_soa(_read(source_path))
        if detection["enabled"]:
            model_sources.append({
                "path": source_path,
                "kind": "model_spectre",
                "model_internal_soa": True,
                "model_soa_mechanism": detection["mechanism"],
                "model_soa_line": detection["line"],
                "model_soa_note": detection["note"],
            })
    if "spectre" in args.formats:
        Path(args.output).write_text(
            render_spectre(selected, model_sources=model_sources, model_soa_mode=args.model_soa_mode),
            encoding="utf-8",
        )
    if "json" in args.formats:
        json_path = str(Path(args.output).with_suffix(".json"))
        Path(json_path).write_text(
            project_json(
                process_path=args.path,
                process_version=None,
                rules=selected,
                export_set=export_set,
                model_sources=model_sources,
                model_soa_mode=args.model_soa_mode,
                adapter=adapter,
                devices=parsed["devices"],
            ),
            encoding="utf-8",
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="soa-generator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan")
    scan.add_argument("path")
    scan.set_defaults(func=command_scan)

    parse = subparsers.add_parser("parse")
    parse.add_argument("path")
    parse.set_defaults(func=command_parse)

    export = subparsers.add_parser("export")
    export.add_argument("path")
    export.add_argument("output")
    export.add_argument("--name", default="default")
    export.add_argument("--formats", nargs="+", choices=("spectre", "json"), default=["spectre", "json"])
    export.add_argument("--model-source", action="append", default=[], help="模型内 SOA 文件，可重复传入")
    export.add_argument("--model-soa-mode", choices=("native", "annotate", "approximate", "dual"), default="native")
    export.add_argument("--adapter-config", help="soa-adapter/v1 JSON 配置")
    export.set_defaults(func=command_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
