# SOA Generator Agent Guide

## Start Here

Read `docs/PROJECT_PLAN.md` before changing scope. Read `docs/DEVELOPMENT.md` before committing. For adapter work, read `adapters/README.md`; for project-file changes, use `soa-project/v1` and validate with `/api/validate_project`.

## Boundaries

- Keep original PDK files read-only. Store only脱敏 fixtures and metadata in Git.
- Process only user-selected readable files/directories. Archives and unextracted PDK packages are explicitly out of scope; do not unpack or scan them automatically.
- Treat PDK SOA files as evidence. Preserve source paths, mechanisms, and confidence on derived rules.
- Keep inferred rules disabled until a user confirms them.
- Do not store SSH passwords, private keys, or raw credentials in project JSON, tests, or documentation.
- Add new process naming and voltage behavior in a `soa-adapter/v1` JSON file when the core rules are unchanged.

## Change Loop

1. Locate the parser, model, service endpoint, and UI path affected by the change.
2. Add a small脱敏 fixture for a new file format or process convention.
3. Run `python3 -m compileall -q soa_generator tests`.
4. Run `python3 -m unittest discover -s tests -v`.
5. Run the Web script syntax check from `docs/DEVELOPMENT.md`.
6. Run `git diff --check`, inspect `git status`, and commit one coherent change.

## Completion

A parser change is complete when its fixture, provenance behavior, duplicate handling, export behavior, and UI-facing JSON are tested. A schema or adapter change is complete when its validation endpoint, import/export round trip, and CLI/API path are tested.

Rule edits use `Rule.override`; source evidence remains immutable provenance. Test export and quick-check paths after changing rule editing behavior.
