# SOA Check Generator

SOA Check Generator is a local browser tool for importing user-selected semiconductor model files, reviewing safe-operating-area (SOA) evidence, editing derived checks, and exporting Spectre or JSON results.

The public repository contains only source code, synthetic fixtures, and generic adapter examples. No process kit, model library, design manual, credentials, screenshots, or private paths are bundled.

## Run locally

Python 3.6.6 or newer is required on this compatibility branch.

Install `dataclasses` from `requirements-py36.txt` before running Python 3.6.6. Install the optional `pypdf` entry when PDF extraction is needed, then run `./run_py36_tests.sh` before starting development. The branch targets Linux/RHEL7.9 and preserves the same parser, service, CLI, export, and validation workflows as the modern main line.

```bash
python3.6 -m soa_generator.service --port 8765
```

Open `http://127.0.0.1:8765/`. The service reads only paths and files that the user selects. It can work with local paths and read-only SSH sources. Archives and unextracted process packages are outside the supported input boundary.

PDF extraction is optional; install the pinned `pypdf` entry from `requirements-py36.txt` when it is needed.

## Command line

```bash
python3.6 -m soa_generator.cli scan /path/to/models
python3.6 -m soa_generator.cli parse /path/to/soa-source.scs
python3.6 -m soa_generator.cli export /path/to/soa-source.scs /tmp/soa-generated.scs --formats spectre json
python3.6 -m soa_generator.cli export /path/to/soa-source.scs /tmp/soa-generated.scs \
  --adapter-config adapters/example.json
```

The importer understands Spectre `assert` sources, model-internal SOA clues, device and subcircuit definitions, structured port topology, and selected manual evidence. Inferred values remain disabled until a user confirms them. Source evidence is preserved in derived project JSON and the original input is never modified.

## Adapters

An adapter is a `soa-adapter/v1` JSON file that maps a user's naming conventions to generic device families, port roles, topology markers, and documented checks. The repository includes only a synthetic example. Replace its patterns and evidence paths with values from your own private process environment; do not commit those source files or credentials.

## Offline dependencies

The parser, rule matrix, CLI, and local service use the standard library plus the `dataclasses` backport on Python 3.6. In an offline environment, provide the wheels listed in `requirements-py36.txt` and install them with `pip --no-index --find-links /path/to/wheels -r requirements-py36.txt`.

## Tests

```bash
./run_py36_tests.sh
node -e "const fs=require('fs');const s=fs.readFileSync('web/index.html','utf8').match(/<script>([\\s\\S]*)<\\/script>/)[1];new Function(s);console.log('web script syntax ok')"
```

## Privacy boundary

Keep process inputs, model files, manuals, SSH credentials, private keys, local screenshots, logs, and generated archives outside Git. Use a private adapter file for process-specific naming and limits. Public issues and pull requests should contain synthetic reproductions rather than proprietary model content.
