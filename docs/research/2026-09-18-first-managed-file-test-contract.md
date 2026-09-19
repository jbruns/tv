# First managed-file vertical-slice test contract

Date: 2026-09-18

Ticket: [Define the first vertical-slice test contract](https://github.com/jbruns/tv/issues/42)

Status: **Draft autonomous decision for independent review**

## 1. Decision

The first production slice is accepted only when tests prove the behavior of
`skin.playlist.new-shows` through the same application seam used by callers:

```text
Reconciler.execute(command) -> command-specific typed outcome
```

The primary tests assert:

- the typed outcome;
- final fake Device state through an independent inspection interface;
- canonical Plan and Run document bytes, revisions, and evidence;
- computed allowed recovery actions;
- presentation diagnostics, where relevant.

They never assert internal calls, call order, Paramiko method order, temporary
names, private helpers, or implementation-specific workspace paths.

The architecture is not proven by pure tests or a happy-path fake alone. It is
proven only after the complete reviewed behavior/fault matrix passes on Linux
x86_64 and macOS arm64 offline CI, the production adapter contracts pass, and
fresh acceptance evidence from the disposable pilot Device is attached to the
exact source digest or commit being accepted.

This contract applies the TDD discipline in the repository skill: one failing
behavior through an accepted seam, the minimum implementation to pass, then
the next vertical tracer bullet. It forbids a horizontal “write the whole test
suite, then implement it” phase.

## 2. Settled test seams

### 2.1 Primary behavior seam

Use `Reconciler.execute` for application behavior:

- `validate`;
- `observe`;
- `plan`;
- `apply`;
- `reconcile`;
- `verify`;
- minimal `recover`;
- `report`.

`inventory` and `action` are members of the closed command union but return
typed `not_implemented` outcomes in this slice. `provision` is tested only as
CLI sugar that constructs `ReconcileCommand`.

Assertions at this seam may inspect only public outcomes, canonical documents,
RunStore revisions through its public load/inspection behavior, evidence,
allowed recovery actions, and fake Device state through the independent
inspector described below.

### 2.2 Focused pure seams

Focused tests directly exercise:

- restricted YAML parsing, authored validation, and fixed composition;
- playlist Intent parsing, semantic XML parsing/rendering, codecs, resolution,
  and assessment;
- the pure planner;
- canonical Plan/Run mapping and serialization;
- the independent Run Report invariant validator.

These tests use hand-authored expected literals. They do not recreate the
implementation algorithm to calculate expected values.

### 2.3 Adapter seams

Reusable behavioral contract cases run against both fakes and production
adapters where the environment permits:

- Device session capability negotiation;
- SSH command outcomes;
- SFTP metadata, read/write, and atomic replace-over-existing semantics;
- RunStore lease/revision/attachment behavior;
- Resource descriptor persisted codecs.

Live Device acceptance is separately marked. A production filesystem
RunStore contract may use a pytest-provided test directory; it must not depend
on repository-relative current working directory.

### 2.4 Installed CLI boundary

CLI integration tests invoke the installed `coreelec-reconciler` executable as
a subprocess from an unrelated working directory. In-process parser tests are
useful but do not satisfy the installed boundary.

## 3. Required test-driven refinement of issue 41

Test design exposed three corrections to the accepted module sketches. The
companion issue-41 contract receives a narrow dated erratum:

1. mutation and SSH outcomes are closed unions that distinguish
   `completed`/`applied`, `definitely_not_applied`, and `ambiguous`;
2. managed-file apply and restore return typed mutation outcomes, never
   `None`, while execution always re-observes;
3. SFTP must provide safe atomic replacement over an existing destination,
   using OpenSSH `posix-rename@openssh.com`/Paramiko `posix_rename` when
   supported, and must block before mutation when it cannot;
4. remove-then-rename is forbidden;
5. prepared and rollback payloads remain closed, safe, and versioned.

These refinements do not change the selected seams, ownership, or lifecycle.

## 4. Settled semantic and evidence policies

### 4.1 Playlist equivalence

Verification uses strict **semantic** equivalence from issue 40. Formatting,
indentation, XML declaration style, and attribute order do not cause drift
when parsing yields the identical canonical playlist model. Such a file is
satisfied and is not rewritten.

When mutation is required, the rendered XML is deterministic. Unknown
elements or attributes, duplicate singleton elements, duplicate or malformed
rules, an unsupported namespace, a wrong encoding declaration, or any
different canonical field is not semantically equivalent.

### 4.2 Canonical bytes and CLI newline

The bytes digested for canonical Plan and Run documents are UTF-8 canonical
JSON with **no trailing newline**. CLI JSON stdout writes those bytes followed
by exactly one `LF`. The newline is presentation framing and is not included
in any document digest.

This intentionally refines the proof helper, which combined canonical bytes
and its terminal newline. Production has separate
`canonical_document_bytes(value)` and CLI framing behavior.

### 4.3 Live evidence

Live Device evidence is mandatory before declaring the managed-file
architecture or milestone proven. It is:

- excluded from default CI;
- not required on each intermediate red/green commit;
- unquarantined when run for acceptance;
- fresh for the exact source commit or source-tree digest accepted;
- retained with tool versions, canonical document digests, JUnit output, and
  pre/post Device evidence.

The live State Address is exactly:

```text
special://profile/playlists/video/NewShows.xsp
```

Issue 40 assigns that address and sole Python ownership during acceptance.
The Device must be disposable; no production Device may be used. Issue 44
defines the exact shell preparation/reset and operator procedure.

### 4.4 CI and acceptance gates

There are currently no CI workflow files. The first implementation milestone
must add Python 3.14 jobs for:

- Linux x86_64;
- macOS arm64.

Both run the offline suites, architecture checks, installed-wheel CLI tests,
and budgets. Live Device acceptance is a separate retained-evidence job or
operator-triggered run.

No automatic retry, flaky rerun, quarantine, `xfail`, or ignored failure can
satisfy acceptance. There is no line-coverage percentage gate. The reviewed
behavior and fault matrix is the coverage gate.

### 4.5 Progress delivery failure

`ProgressSink` delivery failure is typed, visible, and non-controlling:

- it cannot cancel, retry, reorder, or alter Device mutation scheduling;
- it cannot change canonical Plan or Run semantics or their digests;
- the application outcome records a presentation diagnostic outside the
  canonical Plan/Run documents;
- the CLI attempts a minimal safe stderr fallback diagnostic;
- failure is never silent.

The diagnostic code spelling is not yet accepted. Tests use a closed,
versioned presentation-diagnostic code and label the initial spelling
illustrative until its owning schema is implemented.

## 5. Exact planned tests and fixtures

This refines, rather than replaces, the tree accepted in issue 41. Matrix files
group closely related cases to avoid one file per trivial assertion.

```text
tests/
├── architecture/
│   ├── test_import_direction.py
│   ├── test_bootstrap.py
│   ├── test_no_network.py
│   └── test_wheel_contents.py
├── unit/
│   ├── application/
│   │   ├── test_execute_validate.py
│   │   ├── test_execute_workflows.py
│   │   ├── test_execute_fault_matrix.py
│   │   ├── test_progress_diagnostics.py
│   │   └── test_unsupported_commands.py
│   ├── config/
│   │   ├── test_parse_matrix.py
│   │   └── test_composition_matrix.py
│   ├── resource_types/kodi_smart_playlist/
│   │   ├── test_intent.py
│   │   ├── test_xml_matrix.py
│   │   ├── test_codecs.py
│   │   ├── test_resolve_assess.py
│   │   └── test_lifecycle_matrix.py
│   ├── capabilities/
│   │   └── test_managed_file_matrix.py
│   ├── planning/
│   │   └── test_planner_matrix.py
│   ├── execution/
│   │   ├── test_execution_matrix.py
│   │   └── test_recovery_surface.py
│   └── reporting/
│       ├── test_canonical_plan.py
│       ├── test_canonical_run.py
│       ├── test_digest_oracle.py
│       └── test_run_invariants.py
├── contract/
│   ├── test_device_session_contract.py
│   ├── test_ssh_contract.py
│   ├── test_sftp_contract.py
│   ├── test_paramiko_device_session.py
│   ├── test_filesystem_run_store.py
│   └── test_resource_descriptor_codecs.py
├── integration/
│   ├── test_cli_installed.py
│   └── test_playlist_vertical_slice.py
├── device/
│   └── test_playlist_pilot.py
├── fakes/
│   ├── device_session.py
│   ├── device_inspector.py
│   ├── run_store.py
│   ├── runtime_values.py
│   ├── progress.py
│   └── faults.py
└── fixtures/
    ├── repository/
    │   ├── inventory/
    │   ├── profiles/{platform,room,device}/
    │   ├── artifacts/
    │   └── secret-providers/
    ├── playlists/
    │   ├── accepted-new-shows.xsp
    │   ├── desired-new-shows.xsp
    │   ├── equivalent-formatting.xsp
    │   ├── equivalent-attribute-order.xsp
    │   ├── divergent-limit.xsp
    │   ├── divergent-rule.xsp
    │   ├── malformed.xsp
    │   ├── duplicate-singleton.xsp
    │   ├── duplicate-rule.xsp
    │   ├── namespace.xsp
    │   ├── utf8-bom.xsp
    │   ├── utf8-crlf.xsp
    │   └── non-utf8-declaration.xsp
    ├── canonical/
    │   ├── plan-actionable.json
    │   ├── plan-noop.json
    │   ├── run-converged-r1.json
    │   ├── run-converged-terminal.json
    │   └── run-interrupted.json
    └── corrupted/
        ├── converged-without-verification.json
        ├── converged-without-post-effect-verification.json
        ├── rolled-back-without-rollback-verification.json
        └── broken-revision-chain.json
```

`accepted-new-shows.xsp` may be a captured real sample only after confirming it
contains no private hostnames, paths, credentials, usernames, tokens, or other
fleet-sensitive content. Otherwise it is replaced by an equivalent sanitized
fixture. `desired-new-shows.xsp` is hand-authored from the issue-40 Intent, not
generated by production code.

## 6. Authored YAML and composition matrix

Every row asserts the typed validation result, complete stable diagnostic
envelope, and that neither a Device session nor transport adapter is created.
Code spellings already accepted elsewhere are used exactly; new spellings are
marked illustrative and must become a closed versioned vocabulary.

| Case | Required result |
|---|---|
| valid inventory plus platform Profile | accepted frozen domain values |
| platform → room → Device scalar override | Device value wins; provenance names each source |
| schema-approved nested mapping merge | only declared mapping fields merge |
| list override | later list replaces; never positional merge |
| omission | unmanaged; never implicit absence |
| explicit `desired: absent` | retained as owned typed Resource |
| `observe-only` | valid and non-mutating |
| type changes across layers | rejected |
| duplicate Resource/document/logical IDs | rejected |
| duplicate mapping key | rejected |
| multiple YAML documents | rejected |
| alias, anchor, merge key, custom tag | rejected |
| non-string mapping key | rejected |
| unknown kind/field/Resource Type | rejected |
| non-integer or unsupported schema version | rejected |
| scalar coercion (`"50"` for integer, etc.) | rejected |
| timestamp-looking untyped scalar | remains string |
| malformed syntax in one file | other parseable documents still report independent diagnostics |
| missing Profile/Resource/secret/Artifact reference | rejected |
| Resource or Artifact dependency cycle | rejected |
| duplicate State Address ownership | rejected in all desired/management combinations |
| false `when` | not applicable and no ownership claim |
| unknown `when` fact/capability | explicit failure, not false |
| selector expansion | dependency and shared-document closure included |
| secret literal | rejected |
| missing/expired prerelease exception | rejected |
| digest/provenance mismatch | rejected |

Composition expected values are literal resolved structures with literal
origin maps. Tests must not invoke the production merge routine to construct
expected data.

## 7. Playlist fixtures and independent oracles

The canonical semantic model for the first Intent is the literal:

```text
media_type = tvshows
display_name = New Shows
match = all
limit = 50
rules = [(playcount, is, 0)]
order = (dateadded, descending)
mode = 0644
```

Required cases:

| Input/state | Assessment |
|---|---|
| absent regular path, desired present | one create Change |
| exact deterministic desired bytes, mode `0644` | satisfied |
| different whitespace/indentation | satisfied, no rewrite |
| different XML attribute order | satisfied, no rewrite |
| UTF-8 BOM or CRLF but identical parsed semantics | satisfied, no rewrite |
| limit/rule/order/name/media-type drift | one structured update Change |
| correct semantics, wrong mode | one update Change for mode drift |
| malformed regular XML | repairable divergence |
| unknown child/attribute or unsupported namespace | divergent or unverifiable according to the closed parser rule; never silently ignored |
| duplicate singleton (`name`, `match`, `limit`, `order`) | malformed divergence |
| duplicate identical rule | semantically different; divergence |
| wrong/unsupported encoding declaration or undecodable bytes | typed unverifiable/repairable result according to safe-read policy |
| symlink, directory, device node, socket, unreadable, oversized | blocker |
| desired absent and path absent | satisfied |
| desired absent and safe regular file present | one remove Change |

The XML oracle parses fixtures with an independent test-only parser or checked
literal tuples. It does not call production canonicalization when deciding the
expected semantic tuple.

## 8. Workflow contract through `Reconciler.execute`

### 8.1 Workflow matrix

| Command | Required first-slice behavior |
|---|---|
| `validate` | complete pre-transport validation; typed diagnostics |
| `observe` | fresh normalized evidence and revisioned Run; no mutation |
| `plan` | complete immutable blocked/no-op/actionable Plan plus planning Run |
| `apply` | exact saved Plan binding/approval validation, prepare, apply, verify, rollback route, revisions |
| `reconcile` | plan then, only when actionable and approved, execute through the same machinery |
| `verify` | fresh observe + same assess; never trusts prior receipt |
| `recover` | expose and execute only minimal allowed `inspect`, `resume_verification`, `rollback`, `finalize` surface |
| `report` | load and return/render the requested canonical revision |
| `inventory` | typed `not_implemented` |
| `action` | typed `not_implemented` |
| CLI `provision` | aliases `reconcile`; no second implementation |

### 8.2 Normal behavior matrix

For each applicable workflow, cover:

- absent → create → fresh Verification → converged;
- divergent semantics → update → fresh Verification → converged;
- mode-only drift → update → fresh Verification → converged;
- semantically equivalent bytes → no-op and byte preservation;
- present → explicit absence → fresh absence Verification;
- second reconcile after convergence → no Change;
- observe-only satisfied and divergent states with no mutation;
- blocked unsafe states;
- saved Plan exact binding and expiry checks;
- dependency skip and safe-independent continuation using synthetic
  planner/execution inputs where the single Resource cannot express a graph.

`apply` and `reconcile` assertions include every durable report revision and
its chain, not merely the terminal status.

### 8.3 Outcome truth

A completed or applied receipt means only that the adapter observed completion.
`definitely_not_applied` means the adapter can prove no server-side mutation.
`ambiguous` means client acknowledgement cannot determine server state.

All three routes are followed by fresh observation when state may have changed.
No receipt, exception class, connection close, or missing response establishes
Convergence.

## 9. Stateful fake Device

The fake models a case-sensitive POSIX-like subtree rooted at an artificial
Device storage root:

- directory, regular file, symlink, and non-regular entries;
- byte content, mode bits, readability, size, and existence;
- parent directory policy;
- same-directory staging;
- rollback attachments/markers;
- OpenSSH atomic replace extension availability;
- logical Device ID, endpoint, pinned host-key identity, and platform identity;
- server-side mutation separately from client acknowledgement.

It implements POSIX replacement semantics: safe atomic replacement over an
existing regular destination succeeds as one namespace operation when the
extension is available. A missing extension produces capability unavailable
before any staging/mutation that could affect the managed address. There is no
remove-plus-rename fallback.

The fake exposes a separate read-only `DeviceInspector` created independently
from the session/capability objects. Assertions use:

- exact entry kind/content/mode;
- exact subtree snapshot;
- absence of unexpected staging, backup, helper, or marker entries.

The inspector exposes no call history. Fake call logs, invocation counts, and
method order are forbidden as behavior assertions.

## 10. Named Device fault/interleaving matrix

Fault point names are test vocabulary, not persisted public codes unless later
adopted by a versioned schema.

| Fault point | Injection | Expected safe behavior |
|---|---|---|
| `after_plan_observation_before_prepare` | third party changes content/mode | prepare re-observation finds `precondition.normalized-state-digest-mismatch`; no mutation |
| `after_rollback_capture_before_prepare_recheck` | third party changes state | stale; staged material cleaned/retained only per #43, managed address unchanged by Reconciler |
| `after_prepare_recheck_before_atomic_replace` | third party changes destination | atomic operation must use a final compare/guard capability or block as stale; it must not overwrite unobserved state |
| `replace_signal_lost_server_applied` | server atomically replaces, client receives transport loss | receipt is `ambiguous`; re-observe may prove Desired State, then report truthfully |
| `replace_signal_lost_server_not_applied` | identical client transport loss, server leaves original | same `ambiguous` client signal; re-observe proves unchanged/divergent and follows failure/rollback policy |
| `mode_signal_lost_server_applied` | chmod applies, acknowledgement lost | ambiguous then re-observe complete content/mode |
| `write_stage_fails` | stage write rejected | definitely not applied; managed address unchanged |
| `atomic_replace_unsupported` | extension absent | capability blocker before mutation |
| `disconnect_during_observe` | read incomplete | unverifiable; no mutation |
| `disconnect_after_replace_before_verify` | new session required | persist interruption/recovery truth; never infer success |
| `verification_reads_third_party_drift` | drift after successful replace | Verification mismatch; tested rollback route |
| `rollback_signal_lost_applied` | restoration applied, acknowledgement lost | ambiguous; fresh rollback Verification decides truth |
| `rollback_signal_lost_not_applied` | identical signal, no restoration | ambiguous; fresh evidence leads to recovery required |
| `cleanup_fails_after_convergence` | managed state converged, staging remains | canonical convergence truth retained, cleanup/recovery diagnostic explicit per #43 |

The two replace ambiguity cases deliberately have identical client-visible
signals and differ only in the independent server state. A test that branches
on exception text rather than observation fails this contract.

The last stale window requires the production mutation primitive to prevent an
unguarded overwrite after the last recheck. The exact compare/guard mechanism
is an issue-43 implementation decision, but issue 42 requires a failing test
for the interleaving and forbids accepting a check-then-unconditional-replace
race.

## 11. RunStore, interruption, and recovery surface

The fake RunStore models:

- exclusive lease ownership and lease loss;
- opaque workspaces;
- attachment digest/content integrity;
- revision starts at 1;
- compare-and-append conflicts;
- monotonic revision and previous-digest linkage;
- append failure before and after durable commit acknowledgement;
- load corruption;
- finalize failure;
- interruption at every durable lifecycle boundary.

Required interruption points are:

1. planning revision before Plan;
2. Plan stored;
3. execution Run created;
4. rollback/prepared payload durable;
5. mutation outcome durable or ambiguous;
6. Verification pending;
7. rollback pending;
8. rollback Verification pending;
9. terminal revision appended but finalization acknowledgement missing.

Tests assert only the allowed action set and truthful report state. Exact
workspace layout, stale-lock algorithm, marker format, cleanup/retention,
retry scheduler, and recovery algorithms belong to issue 43.

No first-slice test expects retry sleeps. If issue 43 introduces scheduled
retry, it must introduce an injected delay capability; tests may not patch or
sleep real time.

## 12. RuntimeValues and ProgressSink

`FakeRuntimeValues` is a queue, not an implicit auto-clock:

- tests enqueue exact UTC instants and UUIDv7 values;
- consumption from an empty queue fails the test;
- unconsumed values fail the test when the scenario closes;
- timezone and locale never affect produced values.

`RecordingProgressSink` records closed typed events for presentation tests but
is not used to prove execution behavior. A failing sink can fail on selected
emissions. Paired scenarios with a working and failing sink must produce:

- identical Device mutation schedule and final Device state;
- byte-identical canonical Plan/Run documents and digests;
- the same application status;
- an additional typed presentation diagnostic only in the failing case;
- safe CLI stderr fallback without secret/raw exception content.

## 13. Shared adapter contracts

### 13.1 Device/session and SSH

Shared fake/production cases:

- reject unknown or changed host key;
- refuse undeclared capability requirements;
- close command channels, SFTP, and SSH client;
- preserve stdout/stderr bytes without decoding;
- distinguish completed, definitely-not-applied, and ambiguous command
  outcomes;
- timeouts and disconnects carry safe typed data;
- no credential value crosses into canonical documents or progress.

Live-only exceptions are authentication against the disposable Device and real
server negotiation. Unit tests do not inspect Paramiko internals.

### 13.2 SFTP atomic overwrite

Shared cases:

- `lstat` does not follow symlinks;
- regular-file read limit;
- staged write with required mode;
- metadata/mode read and `chmod` behavior needed by managed-file;
- atomic replace when destination is absent;
- atomic replace over an existing regular destination;
- source disappearance and destination replacement semantics;
- extension/capability absence blocks before managed-address mutation;
- no remove-plus-rename sequence exists;
- ambiguous acknowledgement is representable.

The production Paramiko adapter must use
`SFTPClient.posix_rename`, backed by
`posix-rename@openssh.com`, for replace-over-existing. Ordinary SFTP `rename`
does not satisfy this contract. The live contract confirms the disposable
Device server supports the extension. If unsupported, the first slice is
blocked rather than weakened.

### 13.3 Filesystem RunStore

Shared fake/production cases:

- one lease owner;
- stale/foreign lease rejection without unsafe takeover;
- opaque workspace ID;
- attachment bytes round-trip and digest mismatch rejection;
- compare-and-append conflict;
- durable revision chain;
- finalize idempotence only where issue 43 explicitly permits it;
- restrictive permissions for sensitive workspace material;
- paths never appear in public outcomes.

Filesystem-specific durability, fsync, atomic file replacement, and stale lock
details remain issue 43 decisions but must receive production contract cases.

## 14. Independent Run Report invariant checker

A test-only checker is written from the accepted schema rules without importing
production report validation or status-computation code. It proves at minimum:

- `converged` requires fresh final Verification for every selected applicable
  Resource;
- any Resource affected by an Effect requires matching post-Effect
  Verification after that Effect;
- `restored_and_verified` and `rolled_back_verified` require a rollback
  attempt plus later rollback Verification evidence;
- mutation completion alone cannot imply convergence;
- ambiguous mutation cannot be terminally classified without later
  observation;
- terminal revisions are immutable;
- revision numbers and previous digests form one chain;
- evidence references resolve and subject/state-address bindings agree;
- an unknown final state cannot coexist with safe-independent continuation or
  a converged/known-partial status.

Every positive golden is checked. Corrupted fixtures each violate one rule and
must be rejected. Production and test invariant implementations must not share
helper functions.

## 15. Canonical JSON, digests, and revision chains

Golden JSON bytes are hand-authored and independently reviewed. Required cases:

- lexicographic object keys;
- schema-defined array order;
- UTF-8 non-ASCII without ASCII escaping;
- no insignificant whitespace;
- no trailing newline in canonical document bytes;
- exactly one CLI framing newline;
- non-finite numbers rejected;
- duplicate/unknown fields rejected on decode;
- required, nullable, and omitted fields remain distinct;
- timezone/locale do not change bytes;
- dictionary insertion order does not change bytes;
- `PYTHONHASHSEED` variation does not change bytes;
- Plan full digest omits only `full_digest`;
- semantic projection omits exactly the six fields accepted in issue 39;
- changing every included semantic field changes the semantic digest;
- changing each excluded event-metadata field leaves semantic digest stable;
- Run revision digest omits only `current_digest`;
- independent recomputation verifies the complete revision chain.

The digest oracle uses `hashlib.sha256` directly over checked literal bytes and
a test-owned semantic projection enumerator. It must not call the production
serializer, digest helper, or projection function to compute expectations.

## 16. Installed CLI contract

The wheel is built and installed into an isolated environment. Tests invoke
the executable from an unrelated directory with controlled environment,
locale, timezone, `PYTHONHASHSEED`, `TERM`, `NO_COLOR`, and TTY/non-TTY
conditions.

### 16.1 Streams

- JSON stdout is canonical document bytes plus exactly one `LF`.
- stdout contains no progress, warnings, logs, tracebacks, prompts, terminal
  escapes, or bootstrap noise.
- progress and human diagnostics use stderr.
- `--quiet` suppresses ordinary progress, not required safety or presentation
  fallback diagnostics.
- logging configuration cannot contaminate stdout.
- non-ASCII output is valid UTF-8.
- color is disabled for non-TTY or `NO_COLOR`; `TERM=dumb` is safe.
- broken-pipe handling exits without a traceback or secret leakage.

### 16.2 Exit codes

The first CLI schema fixes this table:

| Code | Meaning |
|---:|---|
| `0` | command completed successfully, including valid/no-op/converged/report |
| `2` | CLI usage or authored validation failure |
| `3` | typed blocked, unsupported, not-implemented, or capability-unavailable outcome; no mutation |
| `4` | execution failed with a fully known final state |
| `5` | interrupted or recovery-required/unknown final state |
| `70` | safely captured internal defect |

Tests map typed outcomes, not message text, to these values.

### 16.3 Contamination sentinel

Inputs contain unique sentinel credentials, tokens, private local paths,
remote paths outside the normalized State Address, transport exception text,
and attachment payload fragments. None may appear in:

- Plans or Run Reports;
- progress events or presentation diagnostics;
- stdout or stderr;
- filenames exposed by outcomes;
- JUnit or retained acceptance summaries.

The expected logical secret provider/key and normalized public State Address
may appear where the accepted schemas permit them.

## 17. Architecture, packaging, and offline enforcement

AST tests enforce the complete issue-41 import table plus:

- one production `bootstrap` definition/composition root;
- the installed CLI imports and uses that bootstrap path;
- tests may replace ports only through the accepted constructor/composition
  seam, not a test-only application path;
- no `socket`, `urllib`, HTTP client, Paramiko, or subprocess import appears
  outside approved adapter/CLI modules;
- no dynamic Resource plugin discovery, `pickle`, or persisted class name;
- no real `time.sleep` in first-slice source or offline tests.

Offline tests install a socket-creation guard early enough to fail any
accidental network attempt. Subprocess use is limited to installed CLI,
packaging, and explicit architecture probes; application behavior tests stay
in-process.

Wheel inspection proves:

- only package code and required metadata are present;
- no `inventory/`, `profiles/`, `artifacts/`, `secret-providers/`,
  `templates/`, `tests/`, fixture, Device, or fleet configuration data;
- the console script resolves to the tested bootstrap/application path;
- import and `--help` work away from the checkout.

## 18. Timing budgets

Timing measures only the test process after a frozen dependency sync. It does
not set `UV_NO_CACHE=1`, create environments, resolve dependencies, or build
the wheel inside the measured interval.

Each Linux and macOS CI job:

1. installs/synchronizes with `uv sync --frozen`;
2. starts a stdlib timing wrapper immediately before pytest;
3. runs pure/unit/architecture tests with a hard 10-second job-step timeout;
4. runs the complete offline suite with a hard 60-second job-step timeout;
5. records monotonic elapsed seconds in the job summary/artifact.

The wrapper uses `time.monotonic_ns()` and propagates pytest's exit status.
The CI runner or standard `timeout` facility enforces the hard ceiling; the
recorded value makes regressions visible. No sleeps, external network, or live
Device work occurs in either measured suite.

“Cold enough” means a fresh CI job/process after dependency sync, with no
pytest daemon or persistent test worker. It does not mean deliberately
discarding uv/download caches and measuring environment setup.

## 19. TDD tracer-bullet implementation order

Every step begins with one failing test through the named accepted seam:

1. installed `validate` rejects one invalid Profile before transport;
2. pure valid Profile composition resolves the literal playlist Intent;
3. pure XML parse/render and semantic no-op;
4. `execute(PlanCommand)` on absent state emits an actionable canonical Plan;
5. Plan digest/newline golden;
6. `execute(ReconcileCommand)` creates the file and freshly verifies it;
7. second reconcile is no-op and preserves bytes;
8. semantic formatting variant is no-op;
9. mode and semantic drift repair;
10. stale-before-mutation rejection;
11. atomic replace capability refusal;
12. identical ambiguous signals with applied/not-applied server states;
13. Verification failure and verified rollback;
14. rollback ambiguity and recovery-required truth;
15. interruption/recover/report surface;
16. progress sink failure invariance and CLI fallback;
17. production adapter shared contracts;
18. Linux/macOS packaging, architecture, and budget gates;
19. live disposable-Device acceptance.

Do not prebuild later workflow machinery merely to satisfy imagined tests.
Refactoring occurs after a green slice and independent review, not inside the
red/green step.

## 20. Live disposable-Device acceptance

Marker: `device`; excluded from default test selection; no retry/rerun plugin.

Preconditions:

- exact Device logical identity, endpoint, host key, and platform identity
  guard match;
- operator confirms the target is the disposable pilot;
- issue-44 reset/preparation completed;
- shell may prepare/reset before handoff, then Python is the sole actor for
  `NewShows.xsp`;
- source commit/tree digest and clean/declared dirty state are captured;
- adapter contract has already proven safe atomic overwrite support.

Required live cases:

1. capture safe pre-state evidence, including independent content semantics,
   mode, entry kind, and Device identity;
2. fresh convergence at the actual playlist address;
3. independently parse the resulting playlist and prove exact semantics and
   mode `0644`;
4. prove Kodi can use/display the playlist and that no Effect is required;
5. introduce the representative drift selected by issue 44 and repair it;
6. if issue 44 determines it is operationally safe, induce one ambiguous
   acknowledgement and prove re-observation; otherwise the shared production
   adapter contract evidence covers ambiguity without weakening any other
   live gate;
7. run again and prove a no-op with no rewrite;
8. restore/reset the Device according to issue 44;
9. capture final subtree leak check and post-state evidence.

The retained evidence bundle contains:

- source commit and optional source-tree digest;
- clean/dirty metadata;
- Python, uv, package, Paramiko, SSH server, Device/CoreELEC, and Kodi versions;
- JUnit XML;
- command lines and environment variable **names**, never values;
- canonical Plan and every Run revision;
- independently recomputed document and revision digests;
- safe pre/post semantic and mode evidence;
- Kodi usability result;
- drift and ambiguity scenario identifiers;
- final cleanup/reset result.

Evidence is stale if it was produced by another commit/source digest, by a
quarantined or retried run, with a different playlist contract, or without the
identity guard.

## 21. Issue boundaries

| Issue | Owns | Explicitly does not own |
|---|---|---|
| #42, this contract | seams, exact behavior/fault/CLI/serialization/adapter/live matrices, fakes, independent oracles, CI platforms, budgets, evidence gates | workspace layout and operational pilot procedure |
| #43, Run workspace/recovery/Effects | exact local/remote workspace paths, leases/markers, durability, stale ownership, attachment retention, interruption algorithms, retry classification/scheduling, recovery action algorithms, Effect barriers | weakening #42 observation, ambiguity, invariant, or acceptance gates |
| #44, disposable pilot | reset boundary, operator commands, drift injection, cleanup/restoration, Kodi usability procedure, whether live ambiguity injection is safe | replacing production adapter ambiguity coverage or changing the managed address |

If #43 introduces retry delays it must add an injected delay capability and
new deterministic tests. If #44 deems live ambiguity injection unsafe, the
production adapter contract remains mandatory and all other live gates remain
unchanged.

## 22. Architecture-proven checklist

The managed-file architecture is proven only when all are true:

- [ ] every required first-slice workflow has a typed outcome test through
      `Reconciler.execute`;
- [ ] inventory/action typed `not_implemented` and provision alias are tested;
- [ ] authored validation/composition matrix passes before transport;
- [ ] playlist semantic, codec, resolution, assessment, and malformed-input
      matrix passes with independent literals;
- [ ] stateful fake Device and independent inspector prove final state and no
      subtree leaks;
- [ ] stale and identical-signal ambiguity cases pass;
- [ ] SFTP safe atomic overwrite-over-existing capability passes in fake and
      Paramiko contracts, with no fallback;
- [ ] fresh Verification and rollback Verification invariants pass, including
      corrupted negative documents;
- [ ] fake and filesystem RunStore revision/lease/attachment contracts pass;
- [ ] canonical byte goldens, independent digests, semantic projection, and
      revision-chain recomputation pass;
- [ ] progress failure leaves canonical semantics and mutation behavior
      unchanged and is never silent;
- [ ] installed CLI stream, exit, environment, broken-pipe, and secret
      contamination cases pass;
- [ ] AST/bootstrap/no-network/wheel-content tests pass on the actual installed
      path;
- [ ] Linux x86_64 and macOS arm64 Python 3.14 offline CI pass under 10/60
      second budgets;
- [ ] no retry, quarantine, rerun, or coverage percentage substitutes for the
      matrix;
- [ ] fresh unquarantined disposable-Device evidence matches the exact accepted
      source digest/commit;
- [ ] live convergence, independent semantics/mode, Kodi usability, drift
      repair, second-Run no-op, and reset/restoration pass.

Passing only the offline suite means the implementation is ready for pilot
acceptance. It does not mean the architecture or milestone is proven.

## 23. Consequences

- Tests remain coupled to public behavior and stable data contracts rather
  than orchestration choreography.
- Ambiguous transport outcomes become representable and cannot be mistaken for
  failure-before-write or success.
- Safe atomic overwrite is an explicit Device capability instead of an
  assumption hidden behind ordinary SFTP rename.
- Independent state, report, XML, and digest oracles make tautological tests
  harder to write.
- The test matrix, not line coverage, defines acceptance.
- Offline feedback remains fast on both supported controller platforms while
  live evidence remains a mandatory milestone gate.
- Issues 43 and 44 retain their operational choices without being able to
  weaken the safety and truthfulness established here.
