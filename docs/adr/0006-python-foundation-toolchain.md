---
status: accepted
---

# Use an evidence-gated Python foundation toolchain

The Reconciler will be a PEP 621 `src/` package named `coreelec-reconciler`, imported as `coreelec_reconciler`, built with a bounded `uv_build` version, and operated from a reviewed checkout using `uv` and a committed `uv.lock`. It requires Python 3.14 or newer, while official controller support is limited to Python and operating-system versions exercised by CI; Linux and macOS are supported peers, and native Windows requires separate evidence. Initial runtime dependencies are PyYAML, Pydantic, and Paramiko behind strict input and synchronous transport adapters. Pure domain and planning code uses standard-library models and cannot import those infrastructure libraries.

The initial contributor toolchain is pytest, strict mypy, and Ruff for linting, import sorting, and formatting. The CLI uses argparse, canonical JSON uses the standard library, diagnostics use standard-library logging, and typed progress events provide chatty human output without contaminating machine-readable stdout. Profiles, Artifact catalogs, and Desired State templates remain repository data outside the wheel. Exact dependency bounds are accepted only after a dedicated proof task demonstrates reproducible locked installs, strict validation, architectural import enforcement, canonical serialization, clean wheel contents, test budgets, dependency licensing, and required Paramiko behavior; failure reopens this decision instead of permitting a workaround.
