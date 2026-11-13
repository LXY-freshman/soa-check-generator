# SOA Check Generator

SOA Check Generator is a local browser tool for importing user-selected semiconductor model files, reviewing safe-operating-area (SOA) evidence, editing derived checks, and exporting Spectre or JSON results.

The public repository contains only source code, synthetic fixtures, and generic adapter examples. No process kit, model library, design manual, credentials, screenshots, or private paths are bundled.

## Run locally

Python 3.10 or newer is required.

This main line targets modern Python. The customer-compatible Python 3.6.6 implementation is maintained separately on the public `py36-compat` branch and has its own dependency and validation instructions.

```bash
python3 -m soa_generator.service --port 8765
```

Open `http://127.0.0.1:8765/`. The service reads only paths and files that the user selects. It can work with local paths and read-only SSH sources. Archives and unextracted process packages are outside the supported input boundary.

For a convenience launcher:

- Windows: run `start_soa_generator.bat`.
- Linux/macOS: run `./start_soa_generator.sh`.

The launcher starts the local service and may open a browser. PDF extraction is optional and requires `pypdf`.

## Command line

```bash
python3 -m soa_generator.cli scan /path/to/models
python3 -m soa_generator.cli parse /path/to/soa-source.scs
python3 -m soa_generator.cli export /path/to/soa-source.scs /tmp/soa-generated.scs --formats spectre json
python3 -m soa_generator.cli export /path/to/soa-source.scs /tmp/soa-generated.scs \
  --adapter-config adapters/example.json
```

The importer understands Spectre `assert` sources, model-internal SOA clues, device and subcircuit definitions, structured port topology, and selected manual evidence. Inferred values remain disabled until a user confirms them. Source evidence is preserved in derived project JSON and the original input is never modified.

## Adapters

An adapter is a `soa-adapter/v1` JSON file that maps a user's naming conventions to generic device families, port roles, topology markers, and documented checks. The repository includes only a synthetic example. Replace its patterns and evidence paths with values from your own private process environment; do not commit those source files or credentials.

## Source packages

The build and packaging scripts are included for reproducibility. They operate on the public source tree and do not include ignored build output, screenshots, private research notes, or process data. Generated archives under `dist/` are intentionally ignored by Git.

## Tests

```bash
python3 -m compileall -q soa_generator tests
python3 -m unittest discover -s tests -v
node -e "const fs=require('fs');const s=fs.readFileSync('web/index.html','utf8').match(/<script>([\\s\\S]*)<\\/script>/)[1];new Function(s);console.log('web script syntax ok')"
```

## Privacy boundary

Keep process inputs, model files, manuals, SSH credentials, private keys, local screenshots, logs, and generated archives outside Git. Use a private adapter file for process-specific naming and limits. Public issues and pull requests should contain synthetic reproductions rather than proprietary model content.
