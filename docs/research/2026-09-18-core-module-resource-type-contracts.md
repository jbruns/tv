# Core module and Resource Type contracts

Date: 2026-09-18

Ticket: [Prototype the core module and Resource Type contracts](https://github.com/jbruns/tv/issues/41)

Interactive evidence:
[Throwaway module-contract prototype](../../prototypes/coreelec-reconciler-module-contracts-prototype.html)

Status: **Accepted contract-level implementation decision**

## 0. Test-driven refinement and erratum (2026-09-18)

[Issue 42](https://github.com/jbruns/tv/issues/42) test design found that the
original compact mutation sketches could not represent transport ambiguity and
that ordinary SFTP rename does not portably guarantee atomic replacement over
an existing destination. This narrow erratum corrects those sketches without
changing the accepted module boundaries, lifecycle, or ownership.

- Remote mutation outcomes are a closed union of `applied`,
  `definitely_not_applied`, and `ambiguous`. SSH command outcomes make the same
  distinction between completed execution, definite non-execution, and
  ambiguous transport loss.
- The domain defines `MutationDisposition`, `MutationReceipt`, and the ordered
  `MutationTrace` once. Every state-changing SFTP primitive used by this slice
  returns a receipt: stage write, `chmod`, atomic replace, remove, and every
  rollback restoration operation. A lost acknowledgement is a successful
  transport-call result whose receipt is `ambiguous`; `Failure` means the
  adapter can prove the mutation was not applied or could not begin.
- `ManagedFiles.apply` and `ManagedFiles.restore` return ordered composite
  traces, never `None`. A trace can truthfully record a partial sequence such
  as replace `applied` followed by `chmod` `ambiguous`. Execution always
  re-observes the complete owned state and never infers Device state or
  Convergence from receipts.
- `lstat` and reads return typed Result values. An incomplete read or transport
  loss during a read is a typed unverifiable failure, not mutation ambiguity.
- The SFTP port exposes atomic replace-over-existing as an explicit capability.
  The Paramiko adapter implements it with `SFTPClient.posix_rename`
  (`posix-rename@openssh.com`). Lack of that capability blocks before mutation.
  Remove-then-rename is not an allowed fallback.
- `posix_rename` is unconditional. The immediate stale recheck narrows but
  cannot eliminate the final race. Fresh post-replace Verification detects
  third-party drift in that window and routes to rollback/recovery; it is never
  reported converged. The operating assumption is one Python actor, while
  unexpected third-party drift remains safely detectable rather than silently
  accepted.
- Resolution of `special://profile/...` requires an observed typed Kodi profile
  root capability. Pure Resource resolution maps the accepted VFS scheme to a
  normalized absolute `ManagedPath`, rejects unknown schemes, missing
  capability, and root escape, and retains both logical State Address and safe
  Device path in normalized evidence. The logical State Address remains the
  ownership identity.
- The SFTP port also exposes the metadata and mode operations actually needed
  by managed-file behavior. Fakes implement matching case-sensitive POSIX
  semantics.
- Prepared and rollback payloads remain closed, safe, versioned persisted data
  under the codec rules already accepted below.

### Issue 43 Run ownership and recovery refinement (2026-09-18)

[Issue 43](2026-09-18-run-workspace-recovery-effect-contracts.md) distinguishes
the controller-local Device lease from the per-workspace revision lease and
adds a derived fail-closed Device-active Run index plus persistent remote Device
ownership. `RunStore.acquire` in section 8.10 is therefore superseded by
separate Device-lease, Run-creation/lease, verified chain/attachment reads,
active lookup/rebuild, typed compare-and-append index intent, and explicit
finalize/seal operations in the issue-43 sketches. Planning-only Runs do not
enter the active index. Its cache may over-report but must never under-report;
corruption blocks until a verified workspace scan rebuilds it.

`RuntimeValues` securely generates the full remote ownership token. `RunStore`
persists it locally mode `0600` and records its digest in initial revision 1
before `RemoteRunOwnership.acquire_exclusive` receives the full credential.
The remote marker and ownership handle retain only the digest. Remote marker
creation/update uses a typed repository-owned durability capability that
atomically writes, syncs the marker and relevant parents, rereads, and verifies
the digest. Unsupported durability blocks; generic SFTP is not claimed to
provide `fsync`.

Recovery also no longer means continuing the generic lifecycle at the next
step. `resume_verification` may fresh-observe, assess, resolve ambiguity,
finish pending Verification/post-Effect observation, and route to an already
approved conditional rollback. It never completes an interrupted forward
primitive, begins an unperformed Change, or reruns an interrupted Effect.
Forward work requires a new Plan and execution Run.

The controller-side content-addressed attachment is authoritative rollback
data. Device-side stage/backup objects are transient aids. Every
state-changing primitive receives a durable intent revision before execution
and an ordered trace/ambiguity revision afterwards; intent without outcome is
ambiguous. These refinements preserve the single `Reconciler.execute`
interface, deep execution module, strict codecs, and fresh-observe
Verification rules.

`RunStore` additionally owns a private `LocalDurability` seam with production
OS and scripted fault adapters for write/full-sync/rename/directory-sync/ack
points. This seam is not application API and tests assert public RunStore
behavior rather than private paths.

## 1. Question

What production module structure and typed interfaces give callers and tests
the greatest leverage while keeping configuration, planning, Resource
semantics, Device I/O, safe mutation, execution, reporting, and recovery local?

This record also fixes the first-slice boundary for
`skin.playlist.new-shows`, the selected `KodiSmartPlaylist` Resource from
[issue 40](https://github.com/jbruns/tv/issues/40).

## 2. Decision

The supported external application interface is one synchronous typed method:

```text
Reconciler.execute(command) -> command-specific typed outcome
```

The command union is closed over `validate`, `inventory`, `observe`, `plan`,
`apply`, `reconcile`, `verify`, `recover`, `report`, and `action`. Python
overloads preserve command-specific return types. `provision` is CLI sugar
that constructs a `ReconcileCommand`; it is not a command variant or a second
implementation. Unsupported closed commands return explicit typed
`not_implemented` or `capability_unavailable` outcomes. They never return a
success-shaped placeholder.

The CLI does only:

```text
parse arguments -> construct typed command -> execute -> render
```

`bootstrap` is the one explicit production composition root. There is no
dependency-injection framework. Application internals are not a supported
public toolkit.

Resource Types are strongly typed and stateless. Each implementation owns:

1. pure `resolve`;
2. I/O-performing `observe`;
3. pure `assess`;
4. `prepare`, including rollback persistence and an immediate stale recheck;
5. `apply` of an opaque prepared change;
6. optional `rollback`.

Verification and rollback Verification always perform a fresh `observe`
followed by the same pure `assess`. A mutation result records only what the
mutation adapter knows; it cannot claim Convergence.

Heterogeneous Resource Types cross the engine only through a private,
repository-owned erased adapter built from an immutable descriptor. The
registry is explicit, closed, and immutable. There are no plugins, entry
points, imports by class name, or dynamic registration.

Each Resource Type owns strict, versioned codecs for safe persisted
`Intent`, `Observation`, `Change`, prepared-change, and rollback payloads.
Persistence never uses pickle, importable class names, or unversioned
dictionaries.

The confirmed real seams are:

- `DeviceSessionFactory` and least-authority Device sessions;
- synchronous SSH and SFTP ports for the first slice;
- `RunStore`;
- `RuntimeValues`;
- `ProgressSink`;
- Effect handler descriptors and handlers when the first Effect is consumed.

Configuration composition, planning, canonical JSON, XML, the Resource
registry, managed-file mechanics, and Effect coalescing are ordinary modules,
not Protocols.

This is a **plan contract, not production implementation**. Exact minor
filenames may vary only when the dependency direction, ownership, public
interface, persistence contracts, and first-slice boundaries below are
preserved. The tree in section 5 is the exact planned tree expected by build
tickets.

## 3. Context

This decision is constrained by the accepted architecture and prior records:

- controller-only, on-demand Python 3.14;
- domain Resources rather than imperative action recipes;
- exclusive State Address ownership and verified Resource-scoped rollback;
- restricted versioned authored YAML, with Pydantic ending at the input
  boundary;
- immutable, evidence-complete Plans and revisioned Run Reports;
- synchronous first implementation;
- Paramiko behind repository-owned ports;
- canonical JSON separate from human presentation and progress;
- repository Profiles, inventory, catalogs, and templates outside the wheel;
- `KodiSmartPlaylist` at
  `special://profile/playlists/video/NewShows.xsp` as the first slice.

The foundational proof demonstrated Python 3.14, strict mypy, Ruff, pytest,
Pydantic boundary conversion, deterministic JSON, AST import rejection,
wheel isolation, and Paramiko SSH/SFTP behavior. The production design keeps
those proven constraints while replacing proof-only module shapes.

The architecture file is not tracked on this branch. It was intentionally not
recreated from main-worktree-only material. When the accepted architecture is
integrated onto a common branch, its “Application Structure” section must be
surgically updated to the direction in sections 5 and 6, including the single
`execute` interface, pure assessment/fresh Verification rule, and deep
managed-file capability.

## 4. Interface designs compared

| Design | Depth and leverage | Locality | Seam placement | Testing surface | Rejection or selection |
| --- | --- | --- | --- | --- | --- |
| Ten public workflow methods | Moderate. Names are discoverable, but callers learn nearly every CLI verb as a separate method. | Workflow dispatch and common Run ownership tend to be duplicated. | Public seam follows presentation vocabulary instead of one application operation. | Tests multiply across public methods and can bypass shared invariants. | Rejected: a shallow public toolkit, especially for not-yet-implemented workflows. |
| Four public methods: `plan`, `apply`, `verify`, `recover` | High for the pilot subset, but incomplete for the approved workflow vocabulary. | Core orchestration remains local. | Public seam arbitrarily elevates four workflows while other commands need another route. | Good vertical tests, but creates two application conventions as more commands arrive. | Rejected after prototype: smaller than ten methods but still needless surface and not the final command set. |
| One broad untyped `execute` | Numerically deepest, but callers lose command-specific return knowledge. | Excellent orchestration locality. | Correct external seam, weak type-level expression. | A broad `Outcome` forces narrowing everywhere and permits mismatched assumptions. | Rejected in this form; retained and strengthened with overloads and closed unions. |
| Externally exposed generic Resource lifecycle | Low. Callers must know phase order, stale checks, rollback, Verification, Effects, and revisions. | Lifecycle knowledge leaks into CLI, tests, and integrations. | Resource internals become a supported external seam. | Phase-level mocks test orchestration details rather than application behavior. | Rejected: deletion merely redistributes complexity to callers. |
| Ports-first orchestration with a universal `Device` or Protocol per helper | Medium. Real variability is replaceable, but construction and authority become broad. | Adapter behavior is local; orchestration becomes fragmented. | Too many hypothetical seams; universal Device overgrants capabilities. | Mock-heavy tests can assert call choreography rather than outcomes. | Rejected as the governing design; retain only proven seams and stateful fakes. |
| **Selected: overloaded `Reconciler.execute` plus private typed erasure and real seams** | **Very high. One operation owns full workflows; overloads preserve precise outcomes.** | **Configuration, planning, lifecycle, mutation safety, and reporting remain in their owning modules.** | **One external application seam; internal Resource seam; ports only where production and fake behavior genuinely vary.** | **Primary vertical tests call `execute`; focused pure and adapter contract tests remain available.** | **Selected. It combines a deep external module with strong Resource typing and least-authority infrastructure.** |

The selected design passes the deletion test: removing `Reconciler` would
spread Run creation, command dispatch, validation ordering, session
acquisition, planning, approvals, execution, recovery, and report revisions
across the CLI and tests. Removing the public Resource lifecycle instead
removes interface burden without losing required behavior.

## 5. Exact planned production and data tree

```text
src/coreelec_reconciler/
├── __init__.py
├── application/
│   ├── __init__.py
│   ├── commands.py
│   ├── outcomes.py
│   └── reconciler.py
├── domain/
│   ├── __init__.py
│   ├── identifiers.py
│   ├── capabilities.py
│   ├── diagnostics.py
│   ├── failures.py
│   ├── evidence.py
│   ├── resources.py
│   ├── changes.py
│   ├── effects.py
│   ├── plans.py
│   └── runs.py
├── config/
│   ├── __init__.py
│   ├── yaml_loader.py
│   ├── input_models.py
│   ├── parse.py
│   ├── composition.py
│   └── load.py
├── resource_types/
│   ├── __init__.py
│   ├── contracts.py
│   ├── codecs.py
│   ├── descriptor.py
│   ├── _erased.py
│   ├── registry.py
│   ├── builtins.py
│   └── kodi_smart_playlist/
│       ├── __init__.py
│       ├── intent.py
│       ├── models.py
│       ├── xml.py
│       ├── codecs.py
│       └── resource_type.py
├── capabilities/
│   ├── __init__.py
│   └── managed_file.py
├── planning/
│   ├── __init__.py
│   ├── input.py
│   ├── graph.py
│   ├── effects.py
│   └── planner.py
├── execution/
│   ├── __init__.py
│   ├── input.py
│   ├── execute.py
│   └── recovery.py
├── ports/
│   ├── __init__.py
│   ├── device_session.py
│   ├── ssh.py
│   ├── sftp.py
│   ├── run_store.py
│   ├── runtime_values.py
│   ├── progress.py
│   └── effects.py
├── adapters/
│   ├── __init__.py
│   ├── paramiko_device_session.py
│   ├── filesystem_run_store.py
│   ├── system_runtime_values.py
│   ├── console_progress.py
│   └── effects.py
├── reporting/
│   ├── __init__.py
│   ├── canonical_json.py
│   ├── plan_document.py
│   ├── run_document.py
│   └── human.py
├── bootstrap.py
└── cli/
    ├── __init__.py
    ├── parser.py
    └── main.py
```

The exact first-slice production files are:

```text
src/coreelec_reconciler/application/{commands,outcomes,reconciler}.py
src/coreelec_reconciler/domain/{identifiers,capabilities,diagnostics,failures,evidence,resources,changes,effects,plans,runs}.py
src/coreelec_reconciler/config/{yaml_loader,input_models,parse,composition,load}.py
src/coreelec_reconciler/resource_types/{contracts,codecs,descriptor,_erased,registry,builtins}.py
src/coreelec_reconciler/resource_types/kodi_smart_playlist/{intent,models,xml,codecs,resource_type}.py
src/coreelec_reconciler/capabilities/managed_file.py
src/coreelec_reconciler/planning/{input,graph,effects,planner}.py
src/coreelec_reconciler/execution/{input,execute,recovery}.py
src/coreelec_reconciler/ports/{device_session,ssh,sftp,run_store,runtime_values,progress,effects}.py
src/coreelec_reconciler/adapters/{paramiko_device_session,filesystem_run_store,system_runtime_values,console_progress}.py
src/coreelec_reconciler/reporting/{canonical_json,plan_document,run_document,human}.py
src/coreelec_reconciler/{bootstrap.py}
src/coreelec_reconciler/cli/{parser,main}.py
```

`adapters/effects.py` is added only with the first consumed Effect. Kodi
JSON-RPC, secrets, and Artifact ports/adapters are not first-slice files.

Repository data stays outside the wheel:

```text
inventory/
profiles/
├── platform/
├── room/
└── device/
artifacts/
secret-providers/
templates/
tests/fixtures/repository/
```

The package may contain schema-owned constants and deterministic XML logic,
but no fleet Desired State, Profile, Device inventory, Artifact selection, or
managed template payload.

## 6. Exact planned test tree

```text
tests/
├── architecture/
│   ├── test_import_direction.py
│   └── test_wheel_contents.py
├── unit/
│   ├── application/
│   │   ├── test_execute_validate.py
│   │   ├── test_execute_plan.py
│   │   ├── test_execute_apply.py
│   │   ├── test_execute_reconcile.py
│   │   ├── test_execute_verify.py
│   │   ├── test_execute_recover.py
│   │   ├── test_execute_report.py
│   │   └── test_unsupported_commands.py
│   ├── config/
│   │   ├── test_parse.py
│   │   └── test_composition.py
│   ├── resource_types/kodi_smart_playlist/
│   │   ├── test_intent.py
│   │   ├── test_xml.py
│   │   ├── test_codecs.py
│   │   ├── test_resolve.py
│   │   ├── test_assess.py
│   │   └── test_lifecycle.py
│   ├── capabilities/test_managed_file.py
│   ├── planning/test_planner.py
│   ├── execution/
│   │   ├── test_execute_change.py
│   │   └── test_recovery.py
│   └── reporting/
│       ├── test_canonical_plan.py
│       └── test_canonical_run.py
├── contract/
│   ├── test_paramiko_device_session.py
│   ├── test_filesystem_run_store.py
│   └── test_resource_descriptor_codecs.py
├── integration/
│   ├── test_cli_validate.py
│   └── test_playlist_vertical_slice.py
├── device/
│   └── test_playlist_pilot.py
├── fakes/
│   ├── device_session.py
│   ├── run_store.py
│   ├── runtime_values.py
│   └── progress.py
└── fixtures/repository/
    ├── inventory/
    ├── profiles/
    ├── artifacts/
    ├── secret-providers/
    └── expected/
```

Issue 42 decides the exact acceptance cases, markers, and timing budgets.
Issue 43 decides exact workspace paths, leases, markers, retry categories,
recovery actions, cleanup, and Effect-barrier mechanics. Those issues may
refine tests without changing the seams or ownership fixed here.

## 7. Dependency direction and AST contract

```text
cli ────────────────> application, reporting
bootstrap ──────────> application, adapters, reporting, resource_types
application ────────> config, planning, execution, reporting, domain, ports
config ─────────────> domain, resource_types descriptor/registry
planning ───────────> domain, resource_types private runtime
execution ──────────> domain, planning, capabilities, resource_types private runtime, ports
resource_types ─────> domain, capabilities, ports
capabilities ───────> domain, ports
reporting ──────────> domain
adapters ───────────> domain, ports
ports ──────────────> domain
domain ─────────────> Python standard library only
```

Allowed edges:

- `cli` may import command types, the `Reconciler` interface, and renderers.
- `bootstrap` may import concrete adapters and the closed built-in registry.
- `application` may coordinate ordinary modules and real ports.
- `config` may select a descriptor and call its strict Intent parser, but may
  not invoke lifecycle operations.
- `planning` and `execution` may use the private erased runtime.
- a Resource Type may depend only on domain values, lifecycle contexts,
  capability modules, and capability-specific ports exposed in those contexts.
- adapters implement ports and may use infrastructure libraries.

Forbidden edges suitable for AST rejection:

| Importer | Forbidden imports |
| --- | --- |
| `domain` | every project package except `domain`; PyYAML, Pydantic, Paramiko, argparse, pathlib I/O, subprocess, socket |
| `planning` | `config`, `execution`, `adapters`, `cli`, Paramiko, Pydantic, PyYAML |
| `resource_types` | `adapters`, `cli`, `reporting`, `bootstrap`, Paramiko, Pydantic, PyYAML |
| `capabilities` | `adapters`, `cli`, `reporting`, `bootstrap`, Paramiko |
| `ports` | `adapters`, `application`, `bootstrap`, `cli`, Paramiko |
| `reporting` | `config`, `planning`, `execution`, `resource_types`, `capabilities`, `adapters`, `cli` |
| `adapters` | `application`, `bootstrap`, `cli`, `planning`, `execution` |
| `cli` | `adapters`, `config`, `planning`, `execution`, `capabilities`, `resource_types`, Paramiko |

Additionally, AST tests reject:

- direct `paramiko` imports outside `adapters/paramiko_device_session.py`;
- direct Pydantic or PyYAML imports outside `config/`;
- a Resource Type importing another concrete Resource Type;
- dynamic import functions in `resource_types/registry.py` or `builtins.py`;
- plugin discovery through entry points;
- `pickle`;
- persisted Python module/class names;
- a second production composition root.

## 8. Typed Python 3.14 interface sketches

The following are contract sketches, not production source. Blocks marked
“standalone sketch” are syntactically parseable Python 3.14. Referenced domain
types are abbreviated where their full canonical Plan/Run fields are already
fixed by the Plan/Run schema record.

### 8.1 Commands, outcomes, and overloaded `execute`

```python
# standalone sketch
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, final, overload


@dataclass(frozen=True, slots=True)
class DeviceId:
    value: str


@dataclass(frozen=True, slots=True)
class PlanId:
    value: str


@dataclass(frozen=True, slots=True)
class RunId:
    value: str


@dataclass(frozen=True, slots=True)
class ValidateCommand:
    repository_root: str


@dataclass(frozen=True, slots=True)
class InventoryCommand:
    repository_root: str


@dataclass(frozen=True, slots=True)
class ObserveCommand:
    repository_root: str
    device_id: DeviceId


@dataclass(frozen=True, slots=True)
class PlanCommand:
    repository_root: str
    device_id: DeviceId


@dataclass(frozen=True, slots=True)
class ApplyCommand:
    repository_root: str
    plan_id: PlanId
    approval_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconcileCommand:
    repository_root: str
    device_id: DeviceId
    approval_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VerifyCommand:
    repository_root: str
    device_id: DeviceId


@dataclass(frozen=True, slots=True)
class RecoverCommand:
    repository_root: str
    run_id: RunId
    action: str


@dataclass(frozen=True, slots=True)
class ReportCommand:
    repository_root: str
    run_id: RunId


@dataclass(frozen=True, slots=True)
class ActionCommand:
    repository_root: str
    action_code: str


type Command = (
    ValidateCommand
    | InventoryCommand
    | ObserveCommand
    | PlanCommand
    | ApplyCommand
    | ReconcileCommand
    | VerifyCommand
    | RecoverCommand
    | ReportCommand
    | ActionCommand
)


class UnsupportedReason(StrEnum):
    NOT_IMPLEMENTED = "not_implemented"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"


@dataclass(frozen=True, slots=True)
class UnsupportedOutcome:
    command: str
    reason: UnsupportedReason
    diagnostic_code: str


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    valid: bool
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InventoryOutcome:
    device_ids: tuple[DeviceId, ...]


@dataclass(frozen=True, slots=True)
class ObservationOutcome:
    run_id: RunId
    report_revision: int


@dataclass(frozen=True, slots=True)
class PlanOutcome:
    run_id: RunId
    plan_id: PlanId | None
    disposition: str


@dataclass(frozen=True, slots=True)
class ApplyOutcome:
    run_id: RunId
    status: str


@dataclass(frozen=True, slots=True)
class ReconcileOutcome:
    planning_run_id: RunId
    execution_run_id: RunId | None
    status: str


@dataclass(frozen=True, slots=True)
class VerifyOutcome:
    run_id: RunId
    status: str


@dataclass(frozen=True, slots=True)
class RecoverOutcome:
    run_id: RunId
    status: str


@dataclass(frozen=True, slots=True)
class ReportOutcome:
    run_id: RunId
    revision: int


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    action_code: str
    status: str


type ValidateResult = ValidationOutcome | UnsupportedOutcome
type InventoryResult = InventoryOutcome | UnsupportedOutcome
type ObserveResult = ObservationOutcome | UnsupportedOutcome
type PlanResult = PlanOutcome | UnsupportedOutcome
type ApplyResult = ApplyOutcome | UnsupportedOutcome
type ReconcileResult = ReconcileOutcome | UnsupportedOutcome
type VerifyResult = VerifyOutcome | UnsupportedOutcome
type RecoverResult = RecoverOutcome | UnsupportedOutcome
type ReportResult = ReportOutcome | UnsupportedOutcome
type ActionResult = ActionOutcome | UnsupportedOutcome
type Outcome = (
    ValidateResult
    | InventoryResult
    | ObserveResult
    | PlanResult
    | ApplyResult
    | ReconcileResult
    | VerifyResult
    | RecoverResult
    | ReportResult
    | ActionResult
)


class Reconciler(Protocol):
    @overload
    def execute(self, command: ValidateCommand) -> ValidateResult: ...
    @overload
    def execute(self, command: InventoryCommand) -> InventoryResult: ...
    @overload
    def execute(self, command: ObserveCommand) -> ObserveResult: ...
    @overload
    def execute(self, command: PlanCommand) -> PlanResult: ...
    @overload
    def execute(self, command: ApplyCommand) -> ApplyResult: ...
    @overload
    def execute(self, command: ReconcileCommand) -> ReconcileResult: ...
    @overload
    def execute(self, command: VerifyCommand) -> VerifyResult: ...
    @overload
    def execute(self, command: RecoverCommand) -> RecoverResult: ...
    @overload
    def execute(self, command: ReportCommand) -> ReportResult: ...
    @overload
    def execute(self, command: ActionCommand) -> ActionResult: ...
    def execute(self, command: Command) -> Outcome: ...


@final
class ApplicationReconciler:
    def execute(self, command: Command) -> Outcome:
        match command:
            case ValidateCommand():
                return ValidationOutcome(valid=True, diagnostics=())
            case _:
                return UnsupportedOutcome(
                    command=type(command).__name__,
                    reason=UnsupportedReason.NOT_IMPLEMENTED,
                    diagnostic_code="application.command-not-implemented",
                )
```

The production dispatcher exhaustively matches every closed command. The
minimal body above demonstrates the fallback shape only; it is not permission
to leave reachable first-slice commands unsupported.

### 8.2 Bootstrap and CLI composition

```python
# standalone sketch
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Command(Protocol):
    pass


class Outcome(Protocol):
    pass


class Reconciler(Protocol):
    def execute(self, command: Command) -> Outcome: ...


@dataclass(frozen=True, slots=True)
class BootstrapSettings:
    repository_root: str


def bootstrap(settings: BootstrapSettings) -> Reconciler:
    runtime = SystemRuntimeValues()
    run_store = FilesystemRunStore(runtime)
    sessions = ParamikoDeviceSessionFactory()
    progress = ConsoleProgressSink()
    registry = built_in_resource_registry()
    return ApplicationReconciler(
        runtime=runtime,
        run_store=run_store,
        sessions=sessions,
        progress=progress,
        registry=registry,
        repository_root=settings.repository_root,
    )


def main(argv: tuple[str, ...]) -> int:
    parsed = parse_args(argv)
    command = command_from_args(parsed)
    reconciler = bootstrap(BootstrapSettings(parsed.repository_root))
    outcome = reconciler.execute(command)
    render(outcome, parsed.output)
    return exit_code(outcome)
```

This fragment is intentionally non-standalone with respect to concrete
constructors. Its point is the composition shape: one explicit factory, no
container, and no lifecycle decisions in the CLI.

### 8.3 Frozen domain results and failures

```python
# standalone sketch
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar


T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True, slots=True)
class Ok(Generic[T]):
    value: T


@dataclass(frozen=True, slots=True)
class Err(Generic[E]):
    error: E


type Result[T, E] = Ok[T] | Err[E]


@dataclass(frozen=True, slots=True)
class LogicalStateAddress:
    value: str


@dataclass(frozen=True, slots=True)
class ManagedPath:
    value: str


@dataclass(frozen=True, slots=True)
class KodiProfileRootCapability:
    root: ManagedPath


@dataclass(frozen=True, slots=True)
class ResolvedManagedAddress:
    logical_address: LogicalStateAddress
    device_path: ManagedPath


class FailureKind(StrEnum):
    INVALID_INPUT = "invalid_input"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    UNSAFE_STATE = "unsafe_state"
    STALE_PRECONDITION = "stale_precondition"
    TRANSPORT = "transport"
    MUTATION = "mutation"
    VERIFICATION = "verification"
    ROLLBACK = "rollback"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True, slots=True)
class ExpectedFailure:
    kind: FailureKind
    code: str
    subject_id: str
    safe_message: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class DefectRecord:
    defect_id: str
    safe_type: str
    safe_message: str


class MutationDisposition(StrEnum):
    APPLIED = "applied"
    DEFINITELY_NOT_APPLIED = "definitely_not_applied"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class MutationReceipt:
    operation: str
    disposition: MutationDisposition
    evidence_digest: str | None


type MutationTrace = tuple[MutationReceipt, ...]
```

Domain values are frozen standard-library values. Expected operational
failures are data. Programming and invariant defects remain exceptions until
the application seam catches them, records a safe `DefectRecord`, finalizes
the Run truthfully where possible, and avoids leaking secrets or raw transport
details.

### 8.4 Resource Type, codecs, descriptor, erasure, and registry

```python
# standalone sketch
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar


IntentT = TypeVar("IntentT", covariant=True)
DecodedT = TypeVar("DecodedT")


class InputParser(Protocol[IntentT]):
    def parse(self, value: object) -> IntentT: ...


class PayloadCodec(Protocol[DecodedT]):
    @property
    def kind(self) -> str: ...

    @property
    def schema_version(self) -> int: ...

    def encode(self, value: DecodedT) -> Mapping[str, object]: ...

    def decode(self, payload: Mapping[str, object]) -> DecodedT: ...


@dataclass(frozen=True, slots=True)
class CapabilityRequirements:
    resolve: frozenset[str]
    observe: frozenset[str]
    prepare: frozenset[str]
    apply: frozenset[str]
    rollback: frozenset[str]


@dataclass(frozen=True, slots=True)
class ResourceTypeCode:
    value: str


class ErasedResourceRuntime(Protocol):
    @property
    def type_code(self) -> ResourceTypeCode: ...


@dataclass(frozen=True, slots=True)
class ResourceDescriptor(Generic[IntentT]):
    type_code: ResourceTypeCode
    authored_schema_versions: frozenset[int]
    persisted_schema_versions: frozenset[int]
    intent_parser: InputParser[IntentT]
    intent_codec: PayloadCodec[IntentT]
    requirements: CapabilityRequirements
    runtime: ErasedResourceRuntime


@dataclass(frozen=True, slots=True)
class ResourceRegistry:
    descriptors: Mapping[ResourceTypeCode, ResourceDescriptor[object]]

    def descriptor(self, type_code: ResourceTypeCode) -> ResourceDescriptor[object]:
        return self.descriptors[type_code]
```

The production registry wraps its mapping in `MappingProxyType` and validates
unique type codes, codec kinds, and supported versions during bootstrap.
`built_in_resource_registry()` constructs the complete tuple of descriptors;
there is no mutation method.

The public descriptor uses no cast. Python cannot express heterogeneous
higher-kinded storage while retaining every concrete generic parameter. The
only localized `typing.cast` is permitted inside
`resource_types/_erased.py`, immediately after the descriptor has validated
the type code, payload kind, schema version, and concrete decoded payload
type. That module is private, has exhaustive mismatch tests, and never exposes
the cast value. No caller, Resource Type, codec, registry consumer, or public
sketch uses `Any` or an unchecked cast.

```python
# standalone sketch
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from coreelec_reconciler.domain.changes import MutationTrace


IntentT = TypeVar("IntentT")
ResolvedT = TypeVar("ResolvedT")
ObservationT = TypeVar("ObservationT")
ChangeT = TypeVar("ChangeT")
PreparedT = TypeVar("PreparedT")
RollbackT = TypeVar("RollbackT")


class Result[T, E](Protocol):
    pass


class Failure(Protocol):
    pass


class CapabilitySnapshot(Protocol):
    pass


class ObservationContext(Protocol):
    pass


class PrepareContext(Protocol):
    pass


class ApplyContext(Protocol):
    pass


@dataclass(frozen=True, slots=True)
class Assessment(Generic[ChangeT]):
    relation: str
    changes: tuple[ChangeT, ...]
    blocker_codes: tuple[str, ...]
    impact_codes: tuple[str, ...]
    effect_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedChange(Generic[PreparedT, RollbackT]):
    payload: PreparedT
    rollback: RollbackT
    precondition_digest: str


class ResourceType[
    IntentT,
    ResolvedT,
    ObservationT,
    ChangeT,
    PreparedT,
    RollbackT,
](Protocol):
    def resolve(
        self,
        intent: IntentT,
        capabilities: CapabilitySnapshot,
    ) -> Result[ResolvedT, Failure]: ...

    def observe(
        self,
        resolved: ResolvedT,
        context: ObservationContext,
    ) -> Result[ObservationT, Failure]: ...

    def assess(
        self,
        resolved: ResolvedT,
        observation: ObservationT,
    ) -> Assessment[ChangeT]: ...

    def prepare(
        self,
        resolved: ResolvedT,
        change: ChangeT,
        before: ObservationT,
        context: PrepareContext,
    ) -> Result[PreparedChange[PreparedT, RollbackT], Failure]: ...

    def apply(
        self,
        prepared: PreparedT,
        context: ApplyContext,
    ) -> Result[MutationTrace, Failure]: ...

    def rollback(
        self,
        rollback: RollbackT,
        context: ApplyContext,
    ) -> Result[MutationTrace, Failure]: ...
```

`rollback` is optional at the descriptor level: a non-rollback Resource Type
publishes no rollback codec or operation. It does not implement a method that
raises “unsupported.”

### 8.5 Lifecycle contexts and safe payloads

```python
# standalone sketch
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ManagedFileReader(Protocol):
    def observe(self, request: object) -> object: ...


class ManagedFileMutator(Protocol):
    def prepare(self, request: object) -> object: ...
    def apply(self, prepared: object) -> object: ...
    def restore(self, rollback: object) -> object: ...


class Workspace(Protocol):
    def put_attachment(self, kind: str, payload: bytes) -> str: ...


@dataclass(frozen=True, slots=True)
class ObservationContext:
    managed_files: ManagedFileReader


@dataclass(frozen=True, slots=True)
class PrepareContext:
    managed_files: ManagedFileMutator
    workspace: Workspace


@dataclass(frozen=True, slots=True)
class ApplyContext:
    managed_files: ManagedFileMutator
```

Actual contexts use concrete capability request/result types rather than
`object`; this compact standalone sketch shows authority. Observation cannot
mutate. Preparation can persist rollback material and stage data. Apply can
only apply the already prepared opaque operation. No context carries
credentials, Paramiko objects, a universal Device, reporting, or configuration
loaders.

Every persisted envelope contains:

```text
resource_type
payload_kind
payload_schema_version
payload
```

The owning codec rejects unknown fields, wrong type code, wrong payload kind,
unsupported version, invalid scalar type, missing field, unsafe content, or
semantic mismatch. Prepared and rollback payloads contain only safe normalized
data or opaque RunStore attachment references. Secret values, live handles,
exceptions, Python class names, and transport clients are forbidden.

### 8.6 Planning input and planner

```python
# standalone sketch
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ResourceAssessment:
    resource_id: str
    relation: str
    change_codes: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    impact_codes: tuple[str, ...]
    effect_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanningInput:
    planning_run_id: str
    device_binding_digest: str
    authored_configuration_digest: str
    resolved_profile_digest: str
    artifact_resolution_digest: str
    capability_snapshot_digest: str
    observation_snapshot_digest: str
    selected_resource_ids: tuple[str, ...]
    dependency_edges: tuple[tuple[str, str], ...]
    assessments: tuple[ResourceAssessment, ...]
    continuation_policy: str


@dataclass(frozen=True, slots=True)
class Plan:
    plan_id: str
    disposition: str
    resource_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanningDiagnostic:
    code: str
    subject_id: str


@dataclass(frozen=True, slots=True)
class PlanningResult:
    plan: Plan
    diagnostics: tuple[PlanningDiagnostic, ...]


class Planner(Protocol):
    def plan(self, value: PlanningInput) -> PlanningResult: ...
```

The production planner is an ordinary pure function, not a Protocol. It
accepts a complete `PlanningInput` and returns an immutable Plan plus
diagnostics. The Protocol above expresses the function shape only. Planning
does not load configuration, observe a Device, acquire a session, read the
clock, allocate IDs, append reports, or render JSON. The application prepares
all event values before calling it.

Assessment is the sole owner of Resource convergence relation, typed Changes,
blockers, impact, and Effect declaration. Resolution cannot pre-decide drift.
Observation cannot produce a Change. Transport receipts cannot produce
Convergence.

### 8.7 Execution input and outcome

```python
# standalone sketch
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionInput:
    run_id: str
    plan_id: str
    plan_full_digest: str
    approval_scopes: tuple[str, ...]
    expected_report_revision: int
    selected_change_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResourceExecutionOutcome:
    resource_id: str
    mutation_status: str
    verification_relation: str
    rollback_status: str | None
    final_state: str


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    run_id: str
    status: str
    report_revision: int
    resources: tuple[ResourceExecutionOutcome, ...]
```

Execution is one deep operation. It owns exact Plan/approval validation,
session acquisition, capability narrowing, prepare/apply ordering, fresh
Verification, rollback, rollback Verification, Effect dispatch, safe
continuation, and report revision appends. It does not own Resource-specific
comparison or transport implementation.

### 8.8 Device sessions and SSH/SFTP ports

```python
# standalone sketch
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from coreelec_reconciler.domain.changes import MutationReceipt


@dataclass(frozen=True, slots=True)
class DeviceConnection:
    host: str
    port: int
    username: str
    host_key_reference: str
    credential_reference: str


@dataclass(frozen=True, slots=True)
class SessionRequirements:
    capability_codes: frozenset[str]


@dataclass(frozen=True, slots=True)
class SshCompleted:
    exit_status: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True, slots=True)
class SshDefinitelyNotApplied:
    failure_code: str


@dataclass(frozen=True, slots=True)
class SshAmbiguous:
    failure_code: str


type SshOutcome = SshCompleted | SshDefinitelyNotApplied | SshAmbiguous


class SshPort(Protocol):
    def run(self, argv: tuple[str, ...], stdin: bytes | None = None) -> SshOutcome: ...


@dataclass(frozen=True, slots=True)
class SftpAttributes:
    mode: int
    size: int
    modified_ns: int


class ReadFailure(Protocol):
    pass


class MutationFailure(Protocol):
    pass


class Result[T, E](Protocol):
    pass


class SftpPort(Protocol):
    def lstat(self, path: str) -> Result[SftpAttributes, ReadFailure]: ...
    def read(self, path: str, limit: int) -> Result[bytes, ReadFailure]: ...
    def write(
        self, path: str, content: bytes
    ) -> Result[MutationReceipt, MutationFailure]: ...
    def chmod(
        self, path: str, mode: int
    ) -> Result[MutationReceipt, MutationFailure]: ...
    def supports_atomic_replace(self) -> bool: ...
    def atomic_replace(
        self, source: str, destination: str
    ) -> Result[MutationReceipt, MutationFailure]: ...
    def remove(self, path: str) -> Result[MutationReceipt, MutationFailure]: ...


class DeviceSession(Protocol):
    def ssh(self) -> SshPort: ...
    def sftp(self) -> SftpPort: ...
    def close(self) -> None: ...


class DeviceSessionFactory(Protocol):
    def open(
        self,
        connection: DeviceConnection,
        requirements: SessionRequirements,
    ) -> DeviceSession: ...
```

The concrete session refuses a requirement set it cannot satisfy and exposes
only the capability modules requested by the selected descriptors. The
production implementation may represent this with phase-specific session
views rather than accessors, but Resource Types never receive credentials,
the connection record, raw Paramiko clients, or a universal `Device`.

Kodi JSON-RPC becomes a separate port only when a consumed Resource Type or
Effect handler requires it. It is not part of the first slice.

### 8.9 Deep managed-file capability

```python
# standalone sketch
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from coreelec_reconciler.domain.changes import MutationTrace
from coreelec_reconciler.domain.failures import Failure, Result
from coreelec_reconciler.domain.identifiers import (
    ManagedPath,
    ResolvedManagedAddress,
)


class FileKind(StrEnum):
    ABSENT = "absent"
    REGULAR = "regular"


@dataclass(frozen=True, slots=True)
class ManagedFileObservation:
    address: ResolvedManagedAddress
    kind: FileKind
    mode: int | None
    size: int
    content_digest: str | None
    content: bytes | None


@dataclass(frozen=True, slots=True)
class ManagedFileChange:
    path: ManagedPath
    expected_digest: str | None
    desired_content: bytes | None
    desired_mode: int | None


@dataclass(frozen=True, slots=True)
class PreparedManagedFileChange:
    token: str


@dataclass(frozen=True, slots=True)
class ManagedFileRollback:
    token: str


class ManagedFiles(Protocol):
    def observe(self, path: ManagedPath, read_limit: int) -> ManagedFileObservation: ...
    def prepare(
        self,
        change: ManagedFileChange,
    ) -> tuple[PreparedManagedFileChange, ManagedFileRollback]: ...
    def apply(
        self, prepared: PreparedManagedFileChange
    ) -> Result[MutationTrace, Failure]: ...
    def restore(
        self, rollback: ManagedFileRollback
    ) -> Result[MutationTrace, Failure]: ...
```

`capabilities/managed_file.py` is a deep internal module over SSH/SFTP. It
owns parent policy, `lstat`, symlink and non-regular-file
rejection, read limits, mode handling, staging, rollback attachment
persistence, immediate stale recheck, same-directory atomic namespace
replace-over-existing through the required OpenSSH extension,
atomic removal where supported, cleanup, and exact content/mode restoration.
It never implements replacement as remove followed by rename. Mutation
traces preserve every per-step ambiguity, and execution always re-observes the
complete owned state afterward.

`KodiSmartPlaylist.resolve` owns pure VFS resolution. It accepts only the
`special://profile/` scheme, combines its normalized relative suffix with the
observed `KodiProfileRootCapability`, and rejects an unknown scheme, a missing
capability, a non-absolute root, or any normalized escape from that root. The
resolved Resource and normalized Plan/evidence retain both
`special://profile/playlists/video/NewShows.xsp` and the safe absolute Device
path. Ownership and duplicate detection continue to use only the logical State
Address. Controller-local paths, credentials, and staging/backup/helper names
never enter those values.

`KodiSmartPlaylist` owns playlist identity, deterministic XML, XML parsing,
semantic comparison, and typed playlist Changes. It calls managed-file
operations but does not reimplement file safety. There is deliberately no
authored generic `RemoteFile` Resource Type.

### 8.10 RunStore

```python
# standalone sketch
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class WorkspaceId:
    value: str


@dataclass(frozen=True, slots=True)
class DeviceLease:
    token: str


@dataclass(frozen=True, slots=True)
class RevisionLease:
    run_id: str
    workspace_id: WorkspaceId
    token: str


class RunStatus(StrEnum):
    PLANNING = "planning"
    BLOCKED = "blocked"
    NOOP = "noop"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    EXECUTING = "executing"
    INTERRUPTED = "interrupted"
    CONVERGED = "converged"
    FAILED_ROLLED_BACK = "failed_rolled_back"
    FAILED_PARTIAL = "failed_partial"
    FAILED_RECOVERY_REQUIRED = "failed_recovery_required"


class DeviceIndexIntent(StrEnum):
    ADD_OR_RETAIN_ACTIVE = "add_or_retain_active"
    REMOVE_AFTER_RELEASE_OR_QUARANTINE = "remove_after_release_or_quarantine"
    NO_CHANGE = "no_change"


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    digest: str
    kind: str
    codec: str


@dataclass(frozen=True, slots=True)
class StoredRevision:
    revision: int
    digest: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class VerifiedRunChain:
    revisions: tuple[StoredRevision, ...]
    head: StoredRevision
    terminal: bool


@dataclass(frozen=True, slots=True)
class AppendIntent:
    next_status: RunStatus
    terminal: bool
    device_index: DeviceIndexIntent


class RunStore(Protocol):
    def acquire_device(self, device_id: str) -> DeviceLease: ...
    def find_active_by_device(self, device_id: str) -> tuple[str, ...]: ...
    def rebuild_active_device_index(self) -> tuple[str, ...]: ...
    def create_execution_run(
        self,
        device_lease: DeviceLease,
        run_id: str,
        device_id: str,
        ownership_token: bytes,
        ownership_token_digest: str,
        initial_payload: bytes,
    ) -> RevisionLease: ...
    def acquire_run(self, run_id: str) -> RevisionLease: ...
    def load_chain(self, run_id: str) -> VerifiedRunChain: ...
    def compare_and_append(
        self,
        lease: RevisionLease,
        expected_revision: int,
        expected_digest: str,
        payload: bytes,
        intent: AppendIntent,
    ) -> StoredRevision: ...
    def attach(
        self,
        lease: RevisionLease,
        kind: str,
        codec: str,
        payload: bytes,
    ) -> AttachmentRef: ...
    def read_attachment(
        self,
        lease: RevisionLease,
        reference: AttachmentRef,
    ) -> bytes: ...
    def finalize_and_seal(
        self,
        lease: RevisionLease,
        terminal_revision: int,
        ownership_released_or_quarantined: bool,
    ) -> StoredRevision: ...
```

```python
# standalone sketch
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class RemoteMarkerPhase(StrEnum):
    ACQUIRED = "acquired"
    PREPARING = "preparing"
    PREPARED = "prepared"
    MUTATING = "mutating"
    VERIFYING = "verifying"
    EFFECT = "effect"
    ROLLING_BACK = "rolling_back"
    TERMINAL_RELEASE_PENDING = "terminal_release_pending"
    QUARANTINE_PENDING = "quarantine_pending"


@dataclass(frozen=True, slots=True)
class RemoteOwnership:
    token_digest: str
    generation: int
    phase: RemoteMarkerPhase
    marker_digest: str


class RemoteRunOwnership(Protocol):
    def acquire_exclusive(
        self,
        identity_digest: str,
        ownership_token: bytes,
    ) -> RemoteOwnership: ...
    def inspect(self, device_id: str) -> RemoteOwnership | None: ...
    def compare_and_update(
        self,
        ownership: RemoteOwnership,
        ownership_token: bytes,
        next_phase: RemoteMarkerPhase,
    ) -> RemoteOwnership: ...
    def verify_checkpoint(
        self,
        ownership: RemoteOwnership,
        expected_phase: RemoteMarkerPhase,
    ) -> RemoteOwnership: ...
    def release(
        self,
        ownership: RemoteOwnership,
        ownership_token: bytes,
        terminal_receipt_digest: str,
    ) -> None: ...
    def quarantine(
        self,
        ownership: RemoteOwnership,
        ownership_token: bytes,
        incident_receipt_digest: str,
    ) -> None: ...


class LocalDurability(Protocol):
    def write_private(self, object_id: str, payload: bytes) -> None: ...
    def full_sync_file(self, object_id: str) -> None: ...
    def atomic_replace(self, source_id: str, destination_id: str) -> None: ...
    def sync_directory(self, directory_id: str) -> None: ...
    def acknowledge(self, operation_id: str) -> None: ...
```

Controller-local workspace paths never cross this seam. Exact lock files,
directory layout, retention, remote markers, and recovery algorithms are
specified by issue 43. Canonical payload bytes remain opaque to `RunStore`;
typed status/terminal/index intent is explicit instead of decoded from those
bytes. `load_chain` verifies the complete chain, attachment reads verify
digest/kind/codec, active lookup can rebuild from all workspaces, and
finalize/seal remains explicit. Canonical Resource evidence may publish the
logical State Address and safe normalized managed Device path, but never
credentials or temporary staging/backup/helper names.

The filesystem implementation privately depends on `LocalDurability`, with a
production OS adapter and a scripted fault adapter for secure write, file
full-sync, atomic rename, directory sync, and acknowledgement injection.

### 8.11 Runtime values and progress

```python
# standalone sketch
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class RuntimeValues(Protocol):
    def now(self) -> datetime: ...
    def new_uuid7(self) -> UUID: ...
    def new_ownership_token(self) -> bytes: ...


class ProgressKind(StrEnum):
    PHASE_STARTED = "phase_started"
    RESOURCE_STARTED = "resource_started"
    RESOURCE_COMPLETED = "resource_completed"
    HEARTBEAT = "heartbeat"


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    kind: ProgressKind
    run_id: str
    phase: str
    resource_id: str | None


class ProgressSink(Protocol):
    def emit(self, event: ProgressEvent) -> None: ...
```

Progress is closed, typed, safe, and non-controlling. A sink cannot approve,
cancel, retry, reorder, or alter a Run. Failure to render progress cannot
change the canonical outcome. The canonical Run Report is authoritative.

### 8.12 Effect handler descriptor and registry

```python
# standalone sketch
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EffectCode:
    value: str


@dataclass(frozen=True, slots=True)
class EffectRequest:
    code: EffectCode
    contributing_change_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EffectResult:
    code: EffectCode
    completed: bool
    failure_code: str | None


class EffectHandler(Protocol):
    def execute(self, request: EffectRequest) -> EffectResult: ...


@dataclass(frozen=True, slots=True)
class EffectHandlerDescriptor:
    code: EffectCode
    required_capabilities: frozenset[str]
    handler: EffectHandler


@dataclass(frozen=True, slots=True)
class EffectRegistry:
    handlers: Mapping[EffectCode, EffectHandlerDescriptor]
```

The planner is an ordinary module that coalesces Resource-declared Effects.
Execution dispatches them through the closed handler registry. Resource Types
never execute Effects. The registry and handlers are implemented only when a
first Effect is consumed. `KodiSmartPlaylist` declares no Effect unless pilot
evidence requires one.

## 9. `skin.playlist.new-shows` exact trace

1. `Reconciler.execute(PlanCommand(...))` allocates a planning Run ID through
   `RuntimeValues` and appends Run Report revision 1 in `planning` before a
   Plan exists.
2. `config.load` reads the repository documents. The restricted YAML loader
   parses the common Resource envelope: ID, type, management, desired state,
   selectors, dependencies, and raw `intent`.
3. The closed registry selects the immutable `KodiSmartPlaylist` descriptor.
   Its strict Pydantic input model rejects unknown/coerced fields and converts
   accepted input to frozen stdlib `KodiSmartPlaylistIntent`. Pydantic objects
   do not cross the boundary.
4. Fixed platform → room → Device composition produces the resolved authored
   Resource with provenance and validates exclusive ownership/dependencies.
5. The application gathers descriptor-declared resolution capabilities into
   an immutable observed `CapabilitySnapshot`.
6. `KodiSmartPlaylist.resolve` is pure over Intent plus that snapshot. It
   derives playlist identity, deterministic desired XML, mode `0644`, the
   logical State Address
   `special://profile/playlists/video/NewShows.xsp`, and its normalized
   absolute Device `ManagedPath` beneath the observed Kodi profile root.
   Missing capability, unknown VFS scheme, or root escape fails resolution.
7. The application opens a least-authority observation session containing
   only the managed-file read capability required by the descriptor.
8. `KodiSmartPlaylist.observe` asks managed-file to inspect/read the address.
   Managed-file consumes the already normalized `ManagedPath` and owns
   `lstat`, regular-file enforcement, size limit, content read, mode, and
   digest. The Resource Type parses XML into a typed playlist Observation. A
   symlink, non-regular file, unsafe path, or unreadable/oversized content
   becomes a typed blocker/failure.
9. `KodiSmartPlaylist.assess` is pure. It is the only operation that decides
   `satisfied`, `divergent`, `not_applicable`, or `unverifiable`; creates the
   typed create/update/remove Change; emits blockers and
   `content_mutation` impact; and declares Effects. For the pilot it declares
   no Effect.
10. The application creates a complete `PlanningInput`. The pure planner
    orders the Resource, creates the evidence-complete Plan, computes
    disposition and approvals, and returns diagnostics. Reporting serializes
    canonical Plan bytes. The application compare-and-appends the planning
    Run revision that references the Plan.
11. An actionable Plan is approved exactly by Plan ID, full digest, and
    required scopes. `Reconciler.execute(ApplyCommand(...))` creates a fresh
    execution Run referencing the exact Plan and originating planning Run.
12. Execution validates Plan digest, expiry, Device binding, graph, selection,
    and approval. It acquires the RunStore lease and opaque workspace.
13. Execution opens a new least-authority Device session from the selected
    descriptors' prepare/apply requirements. Resource Types receive only the
    managed-file capability, not credentials or the session factory.
14. `KodiSmartPlaylist.prepare` asks managed-file to persist the exact
    pre-image/mode or absence marker as a RunStore attachment, stage the
    desired bytes, and immediately re-observe the precondition. A mismatch
    returns typed stale failure with no mutation. Success returns an opaque
    prepared playlist change plus rollback payload.
15. Execution appends the durable prepared revision before mutation.
16. `KodiSmartPlaylist.apply` delegates the opaque prepared file change.
    Managed-file performs same-directory atomic replacement/removal and mode
    enforcement. It returns an ordered per-step `MutationTrace`; for example,
    replace may be `applied` while the following `chmod` is `ambiguous`.
    Transport/acknowledgement loss is an `Ok` ambiguous receipt, while
    `Failure` proves the affected primitive was not applied or could not
    begin. The trace does not say converged.
17. Execution append-revises the mutation result, then performs Verification:
    a fresh managed-file observation, playlist XML parse, and the same pure
    assessment of complete owned state. Only `satisfied` establishes
    Convergence. Because `posix_rename` is unconditional, this Verification
    also detects a third-party interleaving after the final stale recheck and
    routes it to rollback/recovery rather than silently accepting it.
18. With successful Verification, execution records no Effect, appends the
    authoritative terminal report revision, finalizes the lease/workspace
    according to issue 43 policy, and returns `ApplyOutcome`.
19. If Verification is divergent/unverifiable and rollback is safe, execution
    invokes the descriptor rollback operation using persisted material.
    Managed-file restores exact prior content/absence and mode, returning an
    ordered trace for every restoration primitive.
20. Rollback success is not final truth. Execution performs a fresh rollback
    Observation and assesses it against the persisted before-state contract.
    The report preserves the original failure plus
    `restored_and_verified`, or records `failed_recovery_required`.
21. If interruption occurs after a durable phase, the latest revision is
    `interrupted` with an opaque workspace ID and computed recovery actions.
    `Reconciler.execute(RecoverCommand(...))` loads the Run, compare-acquires
    its lease, fresh-observes state, and routes to inspect, resume
    Verification, rollback, or finalize as issue 43 specifies. It never infers
    success from a missing process or mutation receipt.
22. `Reconciler.execute(ReportCommand(...))` loads the canonical revision and
    renders it. Progress events emitted during all phases are informative
    only; they never replace report evidence.

## 10. Ownership matrix

| Behavior | Owning module | Input → output | Why it belongs there |
| --- | --- | --- | --- |
| YAML safety | `config/yaml_loader.py` | bytes → restricted YAML values/diagnostics | One infrastructure boundary owns YAML hazards. |
| Common Resource envelope | `config/input_models.py`, `parse.py` | YAML value → validated envelope | Common authored rules are independent of a concrete Resource Type. |
| Intent parsing | Resource descriptor and type input model | raw `intent` → frozen stdlib Intent | The type owns its authored vocabulary and version. |
| Fixed composition | `config/composition.py` | authored documents → resolved authored Resources | Layering and provenance are repository-wide rules. |
| Registry selection | `resource_types/registry.py` | type code → immutable descriptor | Closed built-ins need one explicit lookup. |
| Capability observation | application plus session/capability modules | selected requirements → snapshot | Resolution receives observed facts without performing I/O itself. |
| VFS/profile path resolution | `kodi_smart_playlist/resource_type.py` | logical State Address + observed profile root → normalized absolute `ManagedPath` | The Resource owns its accepted VFS scheme and keeps logical ownership distinct from Device representation. |
| Playlist resolution | `kodi_smart_playlist/resource_type.py` | Intent + snapshot → resolved playlist | Domain identity and representation are type-specific. |
| XML | `kodi_smart_playlist/xml.py` | playlist model ↔ deterministic XML | XML is playlist representation, not transport or planning. |
| Safe file observation | `capabilities/managed_file.py` | managed path → safe file facts/content | File hazards and limits are reusable deep mechanics. |
| Playlist observation | `kodi_smart_playlist/resource_type.py` | safe file facts → typed Observation | Only the Resource Type knows playlist semantics. |
| Convergence/Change/blocker/impact/Effect decision | Resource Type `assess` | resolved + Observation → Assessment | One pure owner prevents contradictory decisions. |
| Complete Plan | `planning/planner.py` | complete PlanningInput → Plan + diagnostics | Cross-Resource graph and approvals are planning concerns. |
| Effect coalescing | `planning/effects.py` | declared Effects → groups/barriers | Resources declare; planner schedules. |
| Run ownership | `application/reconciler.py` | command → Run/Plan/typed outcome | The full invocation belongs at the application seam. |
| Prepare/apply/verify/rollback sequencing | `execution/execute.py` | ExecutionInput → ExecutionOutcome | One deep operation owns safety ordering and report revisions. |
| Staging/stale check/exact restoration | `capabilities/managed_file.py` | typed file change → opaque prepared/rollback values | These mechanics must not be reimplemented by Resources. |
| SSH/SFTP mechanics | Paramiko adapter | port calls → transport facts/results | Infrastructure dependency remains replaceable and testable. |
| Least-authority session | session factory/adapter | connection + requirements → session view | Prevents credentials and unused authority reaching Resources. |
| Workspace/lease/revisions | RunStore adapter | opaque IDs/bytes → stored revisions | Filesystem layout and concurrency remain hidden. |
| Time and IDs | RuntimeValues adapter | request → event value | Deterministic stateful fakes replace global clock/UUID patching. |
| Progress | ProgressSink adapter | typed event → presentation side effect | Non-authoritative output can vary without changing results. |
| Canonical documents | `reporting/` | domain Plan/Run → canonical bytes | One serializer protects the automation contract. |
| CLI | `cli/` | argv → command; outcome → exit/render choice | CLI must not own application behavior. |
| Wiring | `bootstrap.py` | settings → Reconciler | One visible composition root is sufficient. |

## 11. Expected failures versus defects

| Situation | Classification | Representation and handling |
| --- | --- | --- |
| Invalid YAML/schema/unknown Resource Type | Expected failure | Typed diagnostics; no Device session constructed. |
| Unsupported authored/persisted payload version | Expected failure | Typed version failure; never best-effort decode. |
| Missing declared capability | Expected failure | `capability_unavailable`; Plan blocked or command unsupported. |
| Unsafe path, symlink, non-regular file, read limit | Expected failure | Managed-file typed unsafe-state result. |
| Malformed regular playlist XML | Expected drift or blocker according to type rule | Typed Observation; assessment decides repairability. |
| Stale precondition | Expected failure | No mutation; typed stale result and Run revision. |
| SSH/SFTP timeout or disconnect | Expected failure | Typed transport result, ambiguity preserved for re-observation/recovery. |
| Mutation adapter returns `Failure` | Expected failure | Adapter proves that primitive was not applied or could not begin; never converged. |
| Mutation acknowledgement is lost | Expected successful transport-call result | `Ok` receipt with `ambiguous`; retain the ordered trace and re-observe complete owned state. |
| Read is incomplete or transport is lost | Expected failure | Typed unverifiable read result; never mutation ambiguity. |
| Fresh Verification mismatch | Expected failure | Rollback route when supported, otherwise truthful failure. |
| Rollback or rollback Verification failure | Expected failure | `failed_recovery_required`; preserve original failure. |
| Unsupported closed command in first slice | Expected outcome | Explicit `not_implemented` or `capability_unavailable`. |
| Impossible enum/state-machine branch | Programming/invariant defect | Raise exception; application seam records a safe defect and truthful Run status. |
| Codec emits data it cannot decode | Programming defect | Exception, contract test failure, safe application capture. |
| Descriptor type/payload mismatch after validation | Programming defect | Private erasure invariant exception; never silently coerce. |
| Duplicate built-in type code | Bootstrap defect | Fail startup before accepting a command. |
| Unexpected exception containing sensitive transport data | Programming/infrastructure defect | Sanitize at application seam; raw exception is not canonical output. |

## 12. Real seams, ordinary modules, and deferred seams

| Category | Modules | Decision |
| --- | --- | --- |
| Real seam now | `DeviceSessionFactory`/session, SSH, SFTP | Production Paramiko and stateful fake implementations are both required. |
| Real seam now | `RunStore` | Filesystem persistence and in-memory/stateful fake differ materially. |
| Real seam now | `RuntimeValues` | System time/UUID and deterministic tests vary. |
| Real seam now | `ProgressSink` | Console/quiet/recording behavior varies without controlling execution. |
| Internal typed seam | Resource Type generic contract/private erasure | Multiple built-in Resource Types will vary, but this is not public application surface. |
| Ordinary module | config composition and validation flow | One repository-owned implementation; pure focused tests suffice. |
| Ordinary module | planner, graph, Effect coalescing | Pure deterministic functions; no adapter variation needed. |
| Ordinary module | canonical JSON and report mapping | One authoritative implementation protected by golden fixtures. |
| Ordinary module | playlist XML | One domain representation implementation. |
| Ordinary deep module | managed-file capability | Internal reuse with one implementation over provided SSH/SFTP ports. |
| Ordinary module | closed registry construction | No plugin or runtime mutation requirement. |
| Deferred real seam | Effect handlers | Add closed handler registry when a first Effect is consumed. |
| Deferred possible seam | Kodi JSON-RPC | Add only with a consuming Resource Type/Effect. |
| Deferred possible seam | secrets | First slice validates references but does not resolve unused secrets. |
| Deferred possible seam | Artifact download/build | Add with the first consuming Artifact Resource flow. |

## 13. First-slice implementation boundary

The first production slice implements only reachable:

- `validate`;
- `observe`;
- `plan`;
- `apply`;
- `reconcile`;
- `verify`;
- minimal `recover`;
- `report`.

It implements only:

- `KodiSmartPlaylist` for `skin.playlist.new-shows`;
- managed-file observation/preparation/mutation/restoration;
- SSH/SFTP through a least-authority Device session;
- RunStore lease/workspace/revisions/attachments;
- RuntimeValues;
- ProgressSink/events;
- canonical Plan/Run and human reporting;
- production adapters and stateful fakes for those seams.

It does not implement inventory UX, Guided Action execution, Kodi JSON-RPC,
add-ons, secret resolution, Artifact download/build, or Effects. `inventory`
and `action` remain closed commands with explicit typed unsupported outcomes.
No future command returns an empty-success substitute.

Stateful fakes model behavior, not call lists:

- fake Device sessions retain files, modes, symlinks, staged content,
  disconnect points, and capability grants;
- fake RunStore retains lease ownership, workspace attachments, revision
  digests, compare-and-append conflicts, interruption points, and finalization;
- fake RuntimeValues consumes explicit finite clock and UUIDv7 queues;
  exhaustion or leftover values fail the test;
- fake ProgressSink records typed events but cannot influence execution.

The first slice has no sleeping or retry scheduler. Issue 43 adds an injected
delay capability only if its accepted recovery policy requires one.

The primary vertical-slice tests construct the application with those fakes
and call `Reconciler.execute`. They assert returned outcomes, Device state,
canonical revisions, rollback material, and final truth. Focused pure tests
cover parsing, XML, codecs, resolution, assessment, planning, and report
serialization. Adapter contract tests run the same behavioral cases against
fake and production adapter implementations where safe. Live Device tests are
opt-in.

## 14. Rejected alternatives

### Ten public workflow methods

Rejected because the external interface would mirror the CLI, enlarge the
supported toolkit, duplicate common dispatch semantics, and encourage direct
workflow coupling.

### Four public workflow methods

Rejected despite the original prototype recommendation. It privileges
`plan/apply/verify/recover`, omits other approved workflows, and forces a
second convention later. Overloaded `execute` keeps equal or better typing
with one operation.

### Externally exposed generic Resource lifecycle

Rejected because callers would own ordering, preconditions, Verification,
rollback, Effects, and report revision rules.

### Universal Device object

Rejected because it exposes credentials and unrelated transport authority,
makes capability requirements implicit, and permits Resource Types to connect.

### Generic authored RemoteFile Resource

Rejected because it moves paths/content mechanics into configuration and
erases domain ownership. Managed-file is an internal deep module;
`KodiSmartPlaylist` remains the authored Resource Type.

### Protocol per module

Rejected for config composition, planning, canonical JSON, XML, registry, and
Effect coalescing. They have one implementation and pure tests; hypothetical
seams add indirection without replaceability.

### Dynamic plugins

Rejected because the repository owns the fleet and compatibility surface.
Explicit built-ins make schemas, capabilities, codecs, and upgrades reviewable.

### Async-first

Rejected because first-slice mutation is serialized, Paramiko is synchronous,
and concurrency is not yet an evidence-backed need. Async can be reconsidered
behind unchanged application semantics.

### Pydantic domain

Rejected because Pydantic is an input adapter dependency. Frozen stdlib domain
values keep pure modules independent and make persistence explicit through
type-owned codecs.

### CLI orchestration

Rejected because it would make CLI and application tests reconstruct workflow
ordering. CLI is parse, construct, execute, render only.

### Direct Paramiko use

Rejected outside the adapter. Resource Types and capabilities depend on
repository-owned SSH/SFTP ports.

### Separate Resource `verify` method

Rejected because it can diverge from assessment semantics. Verification is
fresh `observe` plus the same `assess`; rollback Verification follows the same
rule against the restoration contract.

### Mutation claiming Convergence

Rejected because a successful rename or command receipt proves only mutation
mechanics. Convergence requires independent fresh evidence.

## 15. Consequences

- The application interface remains small while supporting all approved
  workflows with precise Python typing.
- The first slice is testable through the same seam external callers use.
- Resource implementations remain strongly typed without making heterogeneous
  payload mechanics public.
- Persistence is safer and evolvable because every payload is closed and
  versioned.
- Least-authority sessions make capability requirements reviewable and prevent
  accidental transport reach.
- Managed-file safety is implemented once without creating a generic authored
  file Resource.
- Execution and application are deliberately deep modules; tests should not
  reach through them merely to assert call order.
- More concrete workspace and recovery detail is intentionally left to
  issue 43, while exact acceptance cases and budgets remain for issue 42.

## 16. Validation expectations

Build tickets must preserve:

1. exhaustive command/outcome typing and overloaded `execute`;
2. one bootstrap composition root;
3. frozen stdlib domain values;
4. Pydantic/PyYAML confinement to config input;
5. pure resolution, assessment, and planning;
6. fresh-observe Verification and rollback Verification;
7. opaque prepared changes and mutation receipts without Convergence claims;
8. private validated Resource Type erasure;
9. strict versioned codecs;
10. explicit immutable registry;
11. least-authority sessions and declared phase capabilities;
12. deep managed-file ownership;
13. opaque RunStore paths and compare-and-append revisions;
14. non-controlling typed progress;
15. explicit typed unsupported outcomes;
16. AST-enforced forbidden imports;
17. repository data excluded from the wheel.
