# Changelog

## py36-compat

- Added a Python 3.6.6 compatibility branch for Linux/RHEL7.9 source development.
- Added a runtime compatibility layer, pinned offline dependencies, and a branch-specific test runner.
- Removed standalone packaging helpers from this branch; source service and CLI remain supported.

## Next

- Added structured parsing for model definitions, ports, source provenance, and compound device relationships.
- Added source-priority resolution, rule overrides, missing-value states, and explicit confirmation before inferred checks can be exported.
- Added topology-aware candidates for isolation structures, substrate connections, parasitic paths, and non-MOS device families.
- Added local and read-only SSH input, background parsing progress, coverage summaries, and Spectre quick checks.
- Added `soa-project/v1` validation and `soa-adapter/v1` configuration for private process-specific naming and evidence.
- Added synthetic fixtures and tests for duplicate handling, rule identity, topology, model-internal SOA clues, and export behavior.
- Added reproducible source validation helpers that exclude private and ignored artifacts.

## Earlier

- Established the local browser and Python service workflow for importing, editing, and exporting SOA checks.
- Added Spectre `sub`/`subs` parsing, rule grouping, min/max merging, source evidence, and user-authored rules.
- Added JSON project export/import and a configurable inference strategy for missing evidence.
