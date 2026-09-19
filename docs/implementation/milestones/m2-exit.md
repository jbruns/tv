# M2 exit: authored configuration contribution

Date: 2026-09-19

Status: **Issue #57 contribution only. M2 is not exited by this record.**

## Scope

Issue #57 implements the restricted authored YAML boundary, strict Pydantic
input validation, fixed platform to room to Device composition, frozen domain
values, selector/dependency resolution, opaque secret references, minimal
Artifact and `KodiSmartPlaylist` forms, stable diagnostics, and canonical
round trips.

It does not implement SSH/SFTP, RuntimeValues resolution, Device observation or
mutation, add-on automation, plugins, Plan/Run behavior owned by issue #58, or
live acceptance.

## Accepted-schema differences

None for the implemented `skin.playlist.new-shows` slice. Artifact support is
intentionally limited to the empty catalog and stable direct-origin GitHub
release-asset form; prerelease, patched, repacked, build, attestation, and
download behavior remain unimplemented rather than being approximated.

## Evidence

Local evidence was produced on macOS arm64 with Python 3.14.2, uv 0.12.3,
Ruff 0.16.8, mypy 2.3.1, and pytest 9.1.1.

| Exact command | Result | Elapsed |
| --- | --- | ---: |
| `uv run pytest -q tests/unit/config` | 23 passed | 0.28 s |
| `uv run ruff check .` and the documented `ruff format --check` paths | Passed; 50 files formatted | 0.04 s |
| `uv run mypy` | No issues in 50 source files | 0.10 s |
| Pure/unit/architecture budget command from `docs/development.md` | 81 passed; 2.171 s measured selection, below 10 s | 2.22 s |
| Complete-offline budget command from `docs/development.md` | 14 passed; 3.014 s aggregate, below 60 s | 0.89 s |
| `uv run pytest -q` | 95 passed | 2.87 s |
| `uv build` | Source distribution and wheel built | 0.37 s |
| Documented wheel inspection and installed-wheel smoke | Passed; 47 wheel entries; version/help passed | 0.03 s inspection |
| `python3 scripts/check_markdown.py` | 55 Markdown files passed | 0.20 s |
| `uv run python scripts/check_inventory_milestones.py` | Passed | 0.04 s |
| `python3 scripts/check_shell_permissions.py --audit` | Passed | 0.15 s |
| `git diff --check origin/main...HEAD` | Passed | not timed |

Fixture SHA-256 digests:

| Fixture | SHA-256 |
| --- | --- |
| `tests/fixtures/repository/artifacts/catalog.yaml` | `6fb54bd9af401c37a6561c0f0fd50016afe1f60f963c8b133e1cfc4879ccc41b` |
| `tests/fixtures/repository/inventory/living-room.yaml` | `dc7254c419dad27b485c5eb49839b443ef004c036aa0758f449e011f9bd5d6e4` |
| `tests/fixtures/repository/profiles/device/living-room-ugoos.yaml` | `fa7e88dbd4d9b9b6fb89d614185da3a815e43b274c92a25e3bb2ae5db7004414` |
| `tests/fixtures/repository/profiles/platform/coreelec-21-amlogic-ng.yaml` | `80844bea73be67b1aaee46db2c6611681878a08c700885538e6c6e0f39648185` |
| `tests/fixtures/repository/profiles/room/living-room.yaml` | `69f5a358afc38a0284ea1ab45e789461d561b44f54974f90e1e6e536fcc2faff` |
| `tests/fixtures/repository/secret-providers/controller-environment.yaml` | `d0e1c065c89bb1f45f3d7a123b5dac0e3912dfea2ce380a54b72ec79cdcf84c8` |

The canonical resolved configuration is 1,818 bytes with SHA-256
`004d7e8c39e512fae99572a8e912d6eecd6b3fe0f9088584acae41f61da2208b`.
The built wheel SHA-256 is
`2ab42f827087adb9697bd4945c119f50b18af6138c971fdd72b1f2bbeff0006a`;
the source distribution SHA-256 is
`f140e212bb7c064fe959b0bc1550d70be1b6a098f1e89ecd326affe2f054b24f`.

The mandatory two-axis code review found configuration-boundary ownership and
three fail-closed gaps. The implementation was revised to add the immutable
Resource Type registry and type-owned codecs/address resolution, isolate
composition, validate every layer before merge, reject unapproved playlist
values, reject incomplete nested Intent with diagnostics, validate unknown
types in unselected Profiles, and reject unsupported Artifact dependency
constraints.

Hosted Linux/macOS and shell-transition evidence is linked from the pull
request. No Device was accessed and no deployment occurred.
