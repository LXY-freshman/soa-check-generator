# SOA Check Generator Project Plan

## Current scope

Build a local browser tool that lets a user select readable model and documentation files, discover device and SOA sources, review provenance, edit derived checks, and export Spectre or JSON output.

## Boundaries

- User-provided process inputs remain read-only and never enter this repository.
- Only directly readable files and directories selected by the user are processed; archives and unextracted packages are out of scope.
- Adapters carry process-specific naming and evidence outside the core code.
- Inferred checks remain disabled until a user confirms them.
- Generated projects preserve source paths, mechanisms, and confidence without storing passwords or private keys.
- Quick checks inspect syntax, sections, parameters, and target references; they do not run a complete circuit simulation.

## Implemented

- Local and read-only SSH discovery with candidate selection and duplicate handling.
- Spectre assertion parsing, model-internal SOA detection, device-list parsing, model limits, and subcircuit dependencies.
- Device families, port roles, topology markers, compound devices, and physical check matrix candidates.
- Source provenance, priority resolution, conflicts, rule overrides, and user-confirmed values.
- Spectre, browser text, and `soa-project/v1` JSON export/import.
- `soa-adapter/v1` configuration for naming, family metadata, topology, port roles, and documented checks.
- Background parsing, coverage summaries, source review, and local/remote Spectre quick checks.
- Synthetic fixtures, unit tests, and reproducible source packaging helpers.

## Planned

- CDF/OA terminal order and parameter-table parsing.
- More complete applicability metadata for physical matrix entries.
- Browser automation coverage for compound-device export flows.
- Optional visualization of conditional SOA regions after the text and provenance workflows are stable.
