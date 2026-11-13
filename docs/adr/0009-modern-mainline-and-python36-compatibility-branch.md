# Keep a modern main line and a Python 3.6.6 compatibility branch

**Status**: accepted

## Context

The customer deployment target is Red Hat Enterprise Linux 7.9 with CPython 3.6.6, while the current project uses modern Python syntax and standard-library APIs. Making the public main line support 3.6.6 would require a broad compatibility rewrite and would constrain future development. The customer still needs source-level customization, so a frozen executable is insufficient.

## Decision

Keep the current modern-Python line as the public main line. It continues to document and test its existing modern runtime target.

Maintain a public `py36-compat` branch for the customer environment. The branch targets Linux/RHEL7.9 and CPython 3.6.6, and preserves the complete current product surface: browser service, CLI, parsing, rule matrix, project validation, export, optional PDF extraction, and Spectre quick checks. The branch receives necessary fixes through deliberate manual backports after a stable main-line change; it does not automatically track every main-line commit.

Use separate compatibility tags such as `compat-3.6.6-*`; main-line and compatibility versions are not interchangeable. The branch must carry its own dependency pins, offline installation notes, and Python 3.6.6 validation command. Future modern-runtime upgrades happen on the main line first and are evaluated for backportability afterward.

## Consequences

- Main-line development can use current language features and maintained libraries.
- The customer receives a source-level development path that matches its installed runtime.
- Every backportable fix has an explicit review and validation step; fixes that rely on modern APIs may remain main-line-only.
- Documentation must state which branch and runtime a command targets.
- The compatibility branch has ongoing maintenance cost and should be versioned and tested independently.

## Rejected alternatives

- Making Python 3.6.6 the permanent main-line floor: rejected because it constrains all future development.
- Shipping only a frozen executable: rejected because the customer must modify and debug source code.
- Keeping the compatibility branch private: rejected because public visibility improves review, reproducibility, and customer-led fixes.
