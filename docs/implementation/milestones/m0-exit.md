# M0 exit: authoritative planning baseline

Date: 2026-09-18

Status: Accepted candidate for merge through issue
[#51](https://github.com/jbruns/tv/issues/51) and PR **PENDING**. The pull
request must be merged with a merge commit. This record does not authorize
deployment or Device access.

## Bound merged inputs

M0 is based on merged `main`, not a planning branch or the stale root
worktree.

| Input | Commit | Tree | Evidence |
| --- | --- | --- | --- |
| Accepted untracked Reconciler foundation | PR [#60](https://github.com/jbruns/tv/pull/60) merge `d36f46f1138d8903d7391baa4675c75727f90fc1` | `666e390ec9e6e11c15d0f9ae9b17375f0554b6e4` | Issue [#49](https://github.com/jbruns/tv/issues/49), source hashes below |
| Accepted decision and research integration | PR [#61](https://github.com/jbruns/tv/pull/61) merge `3a7147a96ba1e13a0725c7f8b36c9f6a45e9111a` | `c118dd6593670f10c02aa0e4d76f95d69e5f8833` | Issue [#50](https://github.com/jbruns/tv/issues/50), PR #61 provenance table |
| M0 deletion, link repair, validator, and exit evidence | **PENDING** | **PENDING** | Issue #51 and its merge-commit-only PR |

The six preservation hashes recorded by PR #60 still match the files in the
PR #61 merged tree:

| Path | SHA-256 |
| --- | --- |
| `CONTEXT.md` | `beb73e7aa1b73a607c176e5cab29f736b065545727fcd1ed95baa980c95eb7f4` |
| `docs/architecture/coreelec-reconciler.md` | `b558c9516ce217452e763a63101c62b66f3e9f5bfe656f8bedc7e2414c2698a2` |
| `docs/adr/0001-controller-only-on-demand-reconciler.md` | `9e82dd741958303bcc993db13890473230da0a9fc142a40903831e5acde82ff4` |
| `docs/adr/0002-declarative-domain-resources.md` | `f77c0ba7d81d24baa3006aa6faa8af3c88ddb5c2dd4f60eafedb8df8bbfb6a0a` |
| `docs/adr/0003-exclusive-resource-ownership-and-verified-rollback.md` | `71fec4a3c99cc657ee377b9f48625eea89524df1ef6d9d79253fec278d00a3e9` |
| `docs/adr/0004-disposable-pilot-cutover.md` | `263bbf2f6d9b3f71ac023ddb8f4147f8b702fa644638745e01ca4a634b37449e` |

PR #61 preserves the accepted Wayfinder history from `41117ba25412f836241ce776e82f2819b47d4f39`
through `5e61a0a5218945c2458aeaba2b7e134fb021d4f1`, integrates ADR 0006 from
`4d6f6225d90211d1adadddd7200b237643573374`, and integrates only the
toolchain proof record from `42d8eeb73e5e3a935f74575ab0c8e0c400375a78`.

## Preservation and link audit

Section 6 of the
[managed-state inventory](../../research/2026-09-18-current-managed-state-inventory.md#6-documentation-evidence-extraction-before-superseded-artifact-deletion)
is the unique-fact checklist. Each superseded artifact was audited before
deletion:

| Removed artifact family | Retained operational facts | Accepted destination |
| --- | --- | --- |
| Arctic Fuse 3 provisioning design and plan | Hub/widget/playlist semantics, Kodi 21 playlist-year limitation, unrelated-setting preservation, ordered JSON/removal rules | Executable transformer and verifier; [`docs/operations/provision-ugoos.md`](../../operations/provision-ugoos.md); inventory State Addresses |
| Component-scoped provisioning design and plan | Component graph, CEC ownership, scoped backup/Verification, one restart transaction, component/add-on selection distinction | [`docs/operations/provision-ugoos.md`](../../operations/provision-ugoos.md); [`docs/home-assistant/ugoos-kodi-lifecycle.md`](../../home-assistant/ugoos-kodi-lifecycle.md) |
| Add-on onboarding/restart design and plan | Two status axes, Emby and PM4K ladders, restart checkpoint, TMDb Helper boundary | [`docs/devices/ugoos-am6b-plus/addon-onboarding-contract.md`](../../devices/ugoos-am6b-plus/addon-onboarding-contract.md) |
| Arctic Fuse viewtypes design and plan | Source ownership/rebuild, deterministic trigger, restart limitation, separate source/compiled Observation, ownership predicate | [`docs/operations/provision-ugoos.md`](../../operations/provision-ugoos.md); inventory rows `SKIN-015`–`SKIN-018` |
| Audio device management plan | Stable audio Intent, Device-enumeration resolution, fail-closed matching, channel/passthrough distinction | [`docs/devices/ugoos-am6b-plus/audio-output.md`](../../devices/ugoos-am6b-plus/audio-output.md) |
| Room Desired State design and plan | Whitelist representation, ten 2160p modes, no Atmos key, Dolby Vision enum, unstable ordinals, powered-display preflight | [`docs/devices/ugoos-am6b-plus/room-desired-state.md`](../../devices/ugoos-am6b-plus/room-desired-state.md); [`config/rooms/theater/room.conf`](../../../config/rooms/theater/room.conf) |

One operational fact was moved during deletion: the report-1 to report-2
status migration table moved from the superseded add-on design to the
[durable add-on contract](../../devices/ugoos-am6b-plus/addon-onboarding-contract.md#migration-from-coreelec-addon-configuration-report-1).
All other retained facts were already present in the accepted destinations
listed above; plan-only task steps, temporary evidence paths, commit commands,
live report names, and dated acceptance results remain available only in git
history.

Repaired links:

| Former source | Repair |
| --- | --- |
| `docs/devices/ugoos-am6b-plus/room-desired-state.md` | Replaced the deleted design link with the accepted inventory preservation index |
| `docs/devices/ugoos-am6b-plus/addon-onboarding-contract.md` | Replaced the deleted design link with the accepted inventory preservation index |
| `docs/operations/provision-ugoos.md` | Retargeted the report migration-table link to the durable add-on contract |
| `docs/research/2026-09-18-addon-supply-chain-primary-sources.md` | Corrected a pre-existing stale inventory heading fragment found by the new validator |

Removed paths: all six superseded plans and all five superseded
specifications. The containing superseded documentation tree is absent.
`docs/decisions/repository-documentation-architecture.md` now names the
surviving record classes: accepted ADRs, accepted research, durable operational
documents, and git history.

## Validator contract and results

`scripts/check_markdown.py` uses only the Python standard library. It:

- checks repository-local inline and reference-style links;
- verifies Markdown heading and explicit-anchor fragments;
- reports duplicate explicit HTML or attribute anchors;
- reports missing linked repository paths;
- rejects paths that resolve outside the repository;
- ignores fenced examples; and
- skips external URLs without requesting or reading them.

Focused fixture checks covered a valid local anchor, an ignored external URL,
a duplicate explicit anchor, a missing repository path, a missing Markdown
anchor, and a path escaping the repository.

Exact final results on macOS arm64 with Python 3.14.2:

| Command | Result |
| --- | --- |
| `python3 scripts/check_markdown.py` | Passed: `Markdown validation passed for 47 file(s).` |
| focused dependency-free validator fixture command | `focused validator tests: 5 behaviors passed` |
| `git diff --check` | Passed with no output |
| `git grep 'docs/superpowers/' -- ':!docs/implementation/milestones/m0-exit.md'` | Passed: no matches (expected exit 1) |
| `for test_script in tests/test-*.sh; do ...; bash "$test_script"; done` (excluding `tests/test-helper.sh`) | Passed: 8 scripts in 395 seconds |

## Scope and ownership

No inventory ID or Device State Address changes ownership in M0. Shell remains
the Device mutation actor. There was no Device access, deployment, dependency
manifest change, production package/runtime work, or later milestone exit.

The merged input and this candidate contain no production `src/`,
`pyproject.toml`, `uv.lock`, `.python-version`, or `tests/proof/` path.

Known failures or merge-blocking residual concerns: **none**, provided the PR
is merged with a merge commit and the final PR head retains the evidence
commit and passing checks recorded above.
