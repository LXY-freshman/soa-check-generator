from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import discover_local, summarize_candidates
from .export import project_json, render_spectre, select_rules
from .models import ExportSet
from .parsers import merge_devices, parse_device_list, parse_spectre_asserts


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
    rules = parse_spectre_asserts(_read(args.path), source_path=args.path)
    devices = merge_devices([], rules)
    print(json.dumps({"devices": [item.to_dict() for item in devices], "rules": [item.to_dict() for item in rules]}, ensure_ascii=False, indent=2))
    return 0


def command_export(args: argparse.Namespace) -> int:
    rules = parse_spectre_asserts(_read(args.path), source_path=args.path)
    export_set = ExportSet(name=args.name, formats=args.formats)
    selected = select_rules(rules, export_set)
    if "spectre" in args.formats:
        Path(args.output).write_text(render_spectre(selected), encoding="utf-8")
    if "json" in args.formats:
        json_path = str(Path(args.output).with_suffix(".json"))
        Path(json_path).write_text(project_json(process_path=args.path, process_version=None, rules=selected, export_set=export_set), encoding="utf-8")
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
    export.set_defaults(func=command_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
