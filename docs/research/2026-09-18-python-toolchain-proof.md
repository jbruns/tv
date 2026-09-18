# Python 3.14 toolchain proof

## Result

All evidence gates in [issue 48](https://github.com/jbruns/tv/issues/48)
passed on the throwaway `wayfinder/prove-python-toolchain` branch. Every Python
source file and test added by this branch is evidence-only. This work does not
integrate the existing shell implementation, define production schemas, or
begin the Reconciler implementation.

The proof ran with uv 0.12.3 and CPython 3.14.2 on macOS arm64 on 2026-09-18.
The package has the static version `0.0.0`; no VCS-derived or publication
versioning behavior is implied.

## Selected direct bounds

These ranges accept compatible maintenance releases while deliberately
preventing an unreviewed next major (or, for fast-moving tooling, next minor)
series. `uv.lock` records the exact selected versions and hashes.

| Role | Metadata range | Locked/tested version |
| --- | --- | --- |
| Build backend | `uv_build>=0.12.17,<0.13` | 0.12.17 |
| YAML boundary | `PyYAML>=6.0.3,<7` | 6.0.3 |
| Validation boundary | `pydantic>=2.13.5,<3` | 2.13.5 |
| SSH/SFTP boundary | `paramiko>=5.0.0,<6` | 5.0.0 |
| Tests | `pytest>=9.1.1,<10` | 9.1.1 |
| Type checking | `mypy>=2.3.1,<3` | 2.3.1 |
| Lint and format | `ruff>=0.16.8,<0.17` | 0.16.8 |
| Paramiko typing | `types-paramiko>=5.0.0.20260724,<5.1` | 5.0.0.20260724 |
| PyYAML typing | `types-PyYAML>=6.0.12.20260906,<6.1` | 6.0.12.20260906 |

The two stub packages are development-only and are required for strict mypy
coverage of the selected infrastructure boundaries. `uv_build` is bounded to
the tested 0.12 minor series. Runtime and development resolution is exact in
the committed lock.

## Reproducible environments and lock failure

Two absent environment directories were independently created from the lock:

```console
UV_PROJECT_ENVIRONMENT=.proof-env-one uv sync --locked
UV_PROJECT_ENVIRONMENT=.proof-env-one uv pip freeze | sort
UV_PROJECT_ENVIRONMENT=.proof-env-two uv sync --frozen
UV_PROJECT_ENVIRONMENT=.proof-env-two uv pip freeze | sort
diff -u .proof-env-one.freeze .proof-env-two.freeze
```

Both installed the same 27-package environment. Clean sync elapsed times were
0.18 seconds (`--locked`) and 0.17 seconds (`--frozen`).

To prove freshness enforcement, the PyYAML upper bound was changed in a
temporary working copy of `pyproject.toml`, then:

```console
uv lock --check
```

failed with exit 1 and “the lockfile ... needs to be updated.” The original
`pyproject.toml` was restored, the temporary backup was removed, and
`uv lock --check` then passed.

## Strict configuration boundary

`config.py` uses a repository-owned `yaml.SafeLoader` subclass that rejects
duplicate mapping keys. It consumes exactly one document and requires a
mapping root. Pydantic is confined to this input boundary with strict,
frozen models and `extra="forbid"`; validated values are converted to frozen
standard-library dataclasses before entering the domain.

Tests prove rejection of:

- duplicate keys;
- multiple YAML documents;
- unsupported YAML tags;
- non-mapping roots;
- unknown fields;
- scalar coercion;
- missing Resource references;
- dependency cycles;
- unsupported schema versions.

Every rejection is asserted to occur before a sentinel transport factory is
invoked.

## Standard-library core and output separation

`reporting.py` owns canonical JSON settings: sorted keys, compact separators,
UTF-8 Unicode without ASCII escaping, a single trailing newline, and
`allow_nan=False`. A golden test compares exact bytes and tests NaN and both
infinities.

A standard-library AST test parses `domain.py` and `planning.py` and rejects
imports of PyYAML, Pydantic, Paramiko, CLI/config/transport infrastructure, and
filesystem/network/subprocess adapters.

Typed milestone and heartbeat events are presented independently from result
serialization:

```console
uv run coreelec-reconciler --output human
uv run coreelec-reconciler --output json
uv run coreelec-reconciler --output json --quiet
```

Human mode produced a result on stdout and two progress lines on stderr. JSON
mode stdout was exactly:

```json
{"schema_version":1,"status":"proof_complete"}
```

Progress remained on stderr; quiet JSON mode emitted no stderr.

## Tests and timings

Pytest has no third-party plugins in the dependency graph.

```console
uv run ruff format --check src tests/proof
uv run ruff check src tests/proof
uv run mypy
UV_NO_CACHE=1 uv run --isolated pytest -q \
  tests/proof/test_architecture.py tests/proof/test_config.py \
  tests/proof/test_reporting.py
UV_NO_CACHE=1 uv run --isolated pytest -q tests/proof -m 'not device'
```

- Ruff format/check: passed.
- Strict mypy: passed for 13 source/test files.
- Cold focused pure tests: 17 passed; 2.02 seconds wall time.
- Cold complete non-Device proof suite: 20 passed, 1 Device test deselected;
  2.65 seconds wall time.

These are below the 10-second pure-suite and 60-second offline-suite budgets.

## Build and clean installation

```console
uv build --no-sources
uv venv --python 3.14 .proof-wheel-env
uv pip install --python .proof-wheel-env/bin/python dist/*.whl
cd .proof-smoke-cwd
../.proof-wheel-env/bin/python -c \
  'import coreelec_reconciler; print(coreelec_reconciler.__version__)'
../.proof-wheel-env/bin/coreelec-reconciler --help
```

`uv_build` created
`coreelec_reconciler-0.0.0.tar.gz` and
`coreelec_reconciler-0.0.0-py3-none-any.whl` in 0.36 seconds. The wheel
contained only the eight `coreelec_reconciler` Python modules and dist-info
metadata. Automated archive inspection found no Profile, catalog, or template
paths in either artifact. A clean wheel environment installed the runtime
closure, imported the src-layout package away from the repository root,
reported version `0.0.0`, and ran `coreelec-reconciler --help`.

## Dependency, license, and platform inventory

The inventory below comes from the exact lock plus the bounded build backend.
Availability means the release publishes either a universal wheel or a
CPython 3.14 wheel suitable for that platform. It is an installability
assessment from PyPI release files, not a claim that this macOS run executed
Linux binaries.

| Scope | Package | Version | License metadata | Linux x86_64 | macOS arm64 |
| --- | --- | --- | --- | --- | --- |
| build | uv_build | 0.12.17 | MIT OR Apache-2.0 | yes | yes |
| runtime | PyYAML | 6.0.3 | MIT | yes | yes |
| runtime | pydantic | 2.13.5 | MIT | yes | yes |
| runtime | paramiko | 5.0.0 | LGPL-2.1 | yes | yes |
| development | pytest | 9.1.1 | MIT | yes | yes |
| development | mypy | 2.3.1 | MIT | yes | yes |
| development | Ruff | 0.16.8 | MIT | yes | yes |
| development | types-PyYAML | 6.0.12.20260906 | Apache-2.0 | yes | yes |
| development | types-paramiko | 5.0.0.20260724 | Apache-2.0 | yes | yes |
| transitive | annotated-types | 0.8.0 | MIT | yes | yes |
| transitive | ast-serialize | 0.11.2 | MIT | yes | yes |
| transitive | bcrypt | 5.0.0 | Apache-2.0 | yes | yes |
| transitive | cffi | 2.1.1 | MIT-0 | yes | yes |
| transitive | cryptography | 50.0.1 | Apache-2.0 OR BSD-3-Clause | yes | yes |
| transitive | iniconfig | 2.3.0 | MIT | yes | yes |
| transitive | invoke | 3.0.3 | BSD-2-Clause | yes | yes |
| transitive | librt | 0.15.0 | MIT | yes | yes |
| transitive | mypy-extensions | 1.1.0 | MIT | yes | yes |
| transitive | packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | yes | yes |
| transitive | pathspec | 1.1.1 | MPL-2.0 | yes | yes |
| transitive | pluggy | 1.6.0 | MIT | yes | yes |
| transitive | pycparser | 3.0 | BSD-3-Clause | yes | yes |
| transitive | pydantic-core | 2.46.5 | MIT | yes | yes |
| transitive | Pygments | 2.21.0 | BSD-2-Clause | yes | yes |
| transitive | PyNaCl | 1.6.2 | Apache-2.0 | yes | yes |
| transitive | typing-extensions | 4.16.0 | PSF-2.0 | yes | yes |
| transitive | typing-inspection | 0.4.4 | MIT | yes | yes |

The lock also contains the Windows-only pytest dependency `colorama==0.4.6`;
it is not installed on either supported peer. This proof makes no native
Windows support claim.

## Disposable Device Paramiko smoke

The opt-in test used the repository/controller Device endpoint, dedicated
identity, and existing known-hosts configuration. `SSHClient` loaded that
known-hosts file and used `RejectPolicy`; no accept-new or `AutoAddPolicy`
behavior exists in the proof.

Without displaying connection details or sensitive material, the test proved:

- authenticated command execution;
- upload/download byte equality;
- `lstat` and `stat` metadata;
- a uniquely named Run-scoped directory under the Device cache;
- same-directory rename;
- channel timeout handling;
- an intentionally ambiguous outcome caused solely by closing the proof's own
  SSH channel after a harmless Run-scoped rename, followed by re-observation
  that established the actual state;
- explicit command-channel, timeout-channel, ambiguous-channel, SFTP, and SSH
  client closure.

Command:

```console
COREELEC_PROOF_DEVICE=1 uv run pytest -q \
  tests/proof/test_device_paramiko.py
```

Result: 1 passed in 0.95 seconds (1.21 seconds wall time). The test removed
only the exact files it created, removed its exact Run-scoped directory using
SFTP operations without wildcards or recursive deletion, and verified that
the directory no longer existed. It did not restart Kodi, sshd, a service, or
the Device; it did not touch a managed production State Address; and it never
invoked `paste`.

## Limitations

- Runtime behavior is a boundary proof, not a production Reconciler.
- Linux x86_64 was assessed from upstream wheel metadata and upstream Python
  3.14 CI evidence; this execution host was macOS arm64.
- The live smoke covered one disposable CoreELEC Device and did not exercise
  Kodi JSON-RPC.
- Native Windows is unsupported until separately evidenced.
- Static version `0.0.0` is appropriate only for this throwaway proof.

## Sources

- [Selected ADR 0006](https://github.com/jbruns/tv/blob/research/python-314-foundation/docs/adr/0006-python-foundation-toolchain.md)
- [Foundation research](https://github.com/jbruns/tv/blob/research/python-314-foundation/docs/research/2026-09-18-python-314-foundation.md)
- [uv lock and sync documentation](https://docs.astral.sh/uv/concepts/projects/sync/)
- [uv build backend](https://docs.astral.sh/uv/concepts/build-backend/)
- [Python 3.14 JSON encoder](https://docs.python.org/3.14/library/json.html)
- [PyYAML documentation](https://pyyaml.org/wiki/PyYAMLDocumentation)
- [Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/)
- [Paramiko SSHClient](https://docs.paramiko.org/en/stable/api/client.html)
- [Paramiko SFTPClient](https://docs.paramiko.org/en/stable/api/sftp.html)
- PyPI release JSON/pages for every package and version in the inventory
