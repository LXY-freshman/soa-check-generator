# SOA Check Generator source package

This archive contains the public source tree and, when a build artifact is supplied separately, an optional Linux package. The source tree contains no proprietary process data.

## Source layout

```text
SOA_Check_Generator/
├── README.md
├── source/                   public source, tests, and generic documentation
└── linux-package/            optional independently built Linux package
```

## Run the source tree

Python 3.10 or newer is required:

```bash
cd source
python3 -m soa_generator.service --port 8765
```

Then open `http://127.0.0.1:8765/`. Local and read-only SSH inputs are supplied by the user at runtime.

## Build a Linux package

On a Linux build host with Python 3 and network access for build dependencies:

```bash
cd source
./build_linux.sh
```

The output is written under `source/dist/` and is ignored by Git. Review the archive contents before sharing it.

## Input boundary

Do not place process model files, manuals, credentials, private keys, screenshots, logs, or private adapter files in the source archive. Use synthetic reproductions in public issues and tests.
