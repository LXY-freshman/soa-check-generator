# Set Python 3.6.6 as the public runtime floor

**Status**: superseded by ADR 0009

## Context

The customer deployment target is Red Hat Enterprise Linux 7.9 with CPython 3.6.6. The customer needs to run and modify the parser, rule matrix, local service, and CLI in that environment. A newer Python installation is difficult, and a frozen executable would allow execution but would not provide a practical source-level development workflow. The public repository must therefore match the customer development baseline rather than leave the customer on a long-lived private compatibility fork.

## Decision

The public main line will support CPython 3.6.6 as its runtime floor and will target Linux first. Core parsing, rule resolution, matrix generation, project validation, the local browser service, CLI paths, and tests are part of the compatibility contract. PDF extraction and Spectre quick checks remain supported capabilities, but they are optional integrations whose external tools and compatible dependencies are supplied by the deployment environment.

The codebase will use one cross-version implementation rather than separate 3.6 and modern branches. Compatibility work includes replacing syntax that cannot be parsed by Python 3.6, providing small compatibility boundaries for runtime APIs, and pinning optional dependencies to versions that can be installed offline. A Python 3.6.6 validation job is a release gate; newer Python versions are secondary checks.

The project will not require a standalone executable for the customer workflow. Build and packaging helpers may remain as convenience tools, but source installation and source-level debugging are the supported path.

## Consequences

- Customer changes to parsers and rule logic can be tested in the same runtime that runs the service.
- The public project must avoid newer language syntax and standard-library APIs, even when those APIs would simplify the implementation.
- Compatibility dependencies and their transitive wheels need a documented offline delivery process.
- Optional integrations must fail clearly when their dependency or external executable is absent; core parsing must remain usable.
- A future move to a maintained Python release is a deliberate migration project, not an implicit change to the current baseline.

## Rejected alternatives

- Requiring a parallel Python installation: rejected because it is difficult in the customer environment.
- Maintaining a private Python 3.6 fork: rejected because fixes and security reviews would diverge from the public line.
- Shipping only a frozen executable: rejected because it does not support customer source-level development.

This decision was superseded when the project adopted a modern-Python public main line and a separately maintained compatibility branch. See ADR 0009.
