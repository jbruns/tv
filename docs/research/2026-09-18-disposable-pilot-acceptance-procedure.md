# Disposable pilot acceptance procedure

Date: 2026-09-18  
Issue: [#44, Define the disposable-pilot acceptance procedure](https://github.com/jbruns/tv/issues/44)  
Status: **Accepted contract-level decision**

## 1. Decision

The first live `KodiSmartPlaylist` acceptance run uses the enrolled
`ugoos-theater` Device and the actual
`special://profile/playlists/video/NewShows.xsp` State Address. The procedure
proves fresh convergence, semantic no-op, representative drift repair,
approved removal and recreation, Kodi usability without an Effect, and
evidence integrity. Recovery evidence is a separate supplemental bundle and
cannot be stitched into the mandatory core acceptance bundle.

This is acceptance infrastructure, not permission to treat the Device
carelessly. The operator must regard the Device as temporarily disposable for
the selected Resource while preserving unrelated room, Kodi, Home Assistant,
and Run Infrastructure state. This procedure is not a general production
runbook and does not authorize fleet deployment.

> **Non-production warning:** this is a controlled acceptance exercise on a
> deliberately selected disposable pilot. Do not apply it to an ordinary
> production Device, broaden its reset scope, or treat a passing first-Resource
> result as fleet-cutover approval.

A full CoreELEC factory reset is **not** required before every first-Resource
attempt. Here, fresh convergence means convergence of the selected Resource
from a deliberately established absent or divergent state on a verified
Manageable Device. Milestone evidence must include one first-use Run in which
the Reconciler infrastructure root is genuinely absent before production code
creates and durably verifies it. That proof may occur on the first
implementation pilot without reimaging the Device. If the root already exists,
validate it; never delete existing Run Infrastructure to manufacture
freshness.

Issue #44 derives the scoped reset from the Manageable Device/resource scope
and the accepted architecture's disposable-pilot framing. It does not
attribute leaf-reset mechanics to ADR 0004, whose source file is not present
on this branch and must be integrated from the main architecture/ADR branch by
#45. A full reimage remains available only when the Device is no longer
Manageable or a reviewed future full-fleet pilot explicitly requires it. A
changed host key after reimage requires a reviewed inventory identity
transition; it is never automatically repinned. Reimage also does not
necessarily create a new logical Device ID because that identity may represent
the continuing physical installation.

## 2. Sources and decision boundary

This decision synthesizes the three preceding analyses: contract coverage and
acceptance completeness, Device/actor/lifecycle operations, and destructive
test/evidence safety. Their common result is a scoped real-address pilot with
exclusive actor epochs, independent evidence, and no live ambiguity or unsafe
node injection.

This procedure operationalizes, and does not weaken:

- the inventory and migration boundary in
  [Current managed-state inventory](2026-09-18-current-managed-state-inventory.md)
  and
  [Managed-state classification](2026-09-18-managed-state-classification.md);
- the exact authored `NewShows.xsp` Intent in
  [Authored configuration schema](2026-09-18-authored-configuration-schema.md);
- Plan, Run, identity, report, and evidence truth in
  [Canonical Plan and Run Report schema](2026-09-18-canonical-plan-run-report-schema.md);
- safe path resolution, XML semantics, mode, atomic replacement, verification,
  and no-Effect behavior in
  [Core module and Resource Type contracts](2026-09-18-core-module-resource-type-contracts.md);
- the live acceptance gates in
  [First managed-file test contract](2026-09-18-first-managed-file-test-contract.md);
- leases, markers, preparation, interruption, rollback, quarantine, Effects,
  and cleanup truth in
  [Run workspace, recovery, and Effect contracts](2026-09-18-run-workspace-recovery-effect-contracts.md);
- the accepted architecture/ADR decision recorded in the issue map that makes
  the pilot Device disposable acceptance infrastructure and requires fresh
  convergence, representative drift repair, and a second-Run no-op before
  shell retirement; #45 must integrate the branch-local source documents;
- the current
  [Ugoos provisioning operations](../operations/provision-ugoos.md),
  [theater Device record](../../rooms/theater/devices/ugoos-am6b-plus.md), and
  [Home Assistant Kodi lifecycle contract](../home-assistant/ugoos-kodi-lifecycle.md).

Issue ownership remains:

| Issue | Owns |
|---|---|
| #42 | Test seams, independent oracles, adapter contracts, live gates, and evidence validity |
| #43 | Run workspaces, leases, markers, recovery, Effects, interruption semantics, retention, and cleanup |
| #44 | This reset boundary, actor handoff, operator sequence, live drift fixtures, Kodi usability test, bundle rules, and pass/fail decision |
| #45 | Integrated implementation plan and milestone sequencing after #44 is independently accepted |

#44 does not redesign the Resource contract, relax #42, replace #43 recovery
rules, or authorize implementation. It supplies the implementation-ready
human-plus-automation procedure that #45 must schedule and that the eventual
live pilot must execute.

## 3. Roles and authority

### 3.1 Automated harness

The acceptance harness:

- creates the local evidence bundle before first Device contact;
- records source, wheel, tool, contract, and Device bindings;
- performs readiness and safety guards;
- acquires the accepted local and remote ownership authorities;
- invokes the production Reconciler through its public interface;
- performs only the declared fixture mutations between terminal Runs;
- captures canonical Plans, every Run revision, attachments, traces,
  preparations, Verifications, marker generations, cleanup receipts, and
  independent observations;
- stops immediately on any failed, blocked, quarantined, abandoned, ambiguous,
  or unexpected result;
- seals the attempt, exits, and then invokes the repository's independent
  offline bundle-verifier tool as a separate process.

Automation may not answer operator attestations, approve an unexpected identity
change, clear recovery state, retry a Device operation, or infer that a Kodi
restart was harmless.

### 3.2 Operator

The operator:

- confirms the physical installation and logical Device identity;
- confirms the screen and HDMI path belong to the intended theater pilot;
- controls the Home Assistant keep-running override;
- confirms Kodi is running and records its PID/start identity;
- declares and signs the shell-to-Python handoff;
- remains at the display for Kodi UI checks;
- decides whether to abort when automation reports a guard failure;
- attests that Python ownership is sealed after the bundle is sealed.

The operator does not manually edit the playlist during a scenario. All
planned drift is a serialized, logged harness fixture phase.

### 3.3 Actor ownership epochs

There are three explicit phases:

1. **Shell preparation epoch.** Before handoff, shell tooling or a human may
   inspect, prepare, or reset the exact playlist leaf under this procedure.
2. **Python acceptance epoch.** From signed handoff until the evidence bundle
   is sealed, Python is the sole ordinary actor for the Resource. Shell
   provisioning whose effective scope includes `skin`, manual playlist edits,
   Home Assistant provisioning, and every other undeclared actor are frozen.
3. **Sealed pilot epoch.** After the first successful Python pilot handoff,
   shell provisioning whose computed effective scope includes `skin` remains
   frozen on this Device until the shell writer and verifier for this State
   Address are retired at cutover. There is no shell skin-ownership handback.
   The Device remains dedicated acceptance infrastructure. Other shell
   operations are permitted only when their recorded computed effective scope
   provably excludes `skin` and `NewShows.xsp`.

Never run shell and Python concurrently. Any later Python attempt requires a
new freeze recheck and handoff event. Do not run `provision-coreelec.sh` with
an effective `skin` scope after the first successful handoff: `skin` expands
to `core` and `addons`, stops/restarts Kodi, and writes more than this
Resource.

This freeze is required because the accepted Python Desired State owns mode
`0644`, while legacy `write_xml_atomic(path, tree, mode=0o600)` writes
`NewShows.xsp` as `0600` and legacy semantic verification does not verify its
mode. Semantic/content equality therefore does **not** make resuming shell
skin ownership safe. Home Assistant status traffic may continue and lifecycle policy may
resume only after the core evidence is sealed, but shell skin ownership does
not resume.

## 4. Fixed identities and accepted Desired State

| Field | Accepted value |
|---|---|
| Logical Device | `ugoos-theater` |
| Resource ID | `skin.playlist.new-shows` |
| Resource Type | `KodiSmartPlaylist` |
| State Address | `special://profile/playlists/video/NewShows.xsp` |
| Presence | present, except in the explicit removal scenario |
| Media type | `tvshows` |
| Name | `New Shows` |
| Match | `all` |
| Limit | `50` |
| Rule | `playcount is 0` |
| Order | `dateadded descending` |
| File type | regular file, no symlink traversal |
| Mode | `0644` |
| Owner/group | observed, not managed by this Resource |
| Effect | none |

The resolved physical path is evidence, not authored Desired State. It must be
derived afresh from Kodi's verified `special://profile` root and safely joined
beneath that root. The harness must never accept a caller-supplied physical
playlist path as authority.

## 5. Attempt and evidence-bundle invariants

An **attempt** begins when its empty evidence bundle is created and ends only
when that bundle is sealed as `passed`, `failed`, or `aborted`. One failed or
aborted case invalidates the entire attempt. Cases from different attempts
must never be stitched together. There is no automatic retry or rerun.

Before first Device contact, create an append-only local bundle outside the
source tree and bind it to:

- a unique attempt ID;
- the source commit and source-tree digest;
- the installed wheel digest;
- the exact contract version;
- the intended Device and Resource;
- a monotonic scenario sequence;
- the bundle format and verifier version.

The exact present and absent Desired State documents, their named Profile IDs,
and the inventory selection that chooses them must already be committed in the
same clean acceptance commit. Each scenario records the selected Profile and
Intent IDs plus their independently computed digests. Working-tree edits,
generated out-of-tree Intent, or changing a Profile between Runs invalidate
the attempt.

The harness may append new immutable objects and atomically advance an
append-only journal. It may not overwrite previously recorded evidence.
Sealing writes a final manifest whose digest covers every retained object.
After sealing, verification is read-only.

### 5.1 Required manifest tree

The implementation must produce this logical tree. Names in angle brackets are
typed identifiers, not instructions to expose private filesystem paths.

```text
pilot-acceptance-<attempt-id>/
├── manifest.json
├── manifest.sha256
├── README.txt
├── source/
│   ├── binding.json
│   ├── git-status.txt
│   ├── source-tree.sha256
│   ├── wheel-metadata.json
│   ├── wheel.sha256
│   └── authored-inputs.json
├── environment/
│   ├── controller.json
│   ├── tools.json
│   ├── device-binding.json
│   ├── platform.json
│   ├── home-assistant.json
│   ├── kodi-process.json
│   ├── storage-stat-capabilities.json
│   └── command-log.jsonl
├── preflight/
│   ├── readiness.json
│   ├── infrastructure-root.json
│   ├── active-state-scan.json
│   ├── adapter-contract-binding.json
│   ├── protocol-negotiation.json
│   ├── safe-probe-root.json
│   ├── sibling-snapshot.before.json
│   └── sibling-snapshot.after.json
├── transitions/
│   └── <seq>-<scenario>/
│       ├── reset-dry-run.json
│       ├── reset-apply.json
│       ├── handoff.json
│       └── freeze-recheck.json
├── offline-contracts/
│   ├── linux.json
│   ├── macos.json
│   ├── production-adapter.json
│   ├── ambiguity-cases.json
│   └── junit/
│       └── <suite>.xml
├── live-device/
│   └── junit/
│       └── <suite>.xml
├── scenarios/
│   ├── 01-absent-create/
│   ├── 02-formatting-noop/
│   ├── 03-semantic-drift/
│   ├── 04-mode-drift/
│   ├── 05-malformed-xml/
│   ├── 06-explicit-removal/
│   ├── 07-recreate-and-kodi/
│   └── 08-immediate-noop/
├── independent/
│   ├── observations.jsonl
│   ├── xml-oracle.jsonl
│   ├── stat-oracle.jsonl
│   ├── directory-oracle.jsonl
│   ├── digest-checks.jsonl
│   └── report-invariants.jsonl
├── operator/
│   ├── target-attestation.json
│   ├── freeze-attestation.json
│   ├── kodi-ui-attestations.jsonl
│   └── ownership-seal-attestation.json
├── final/
│   ├── canonical-state.json
│   ├── active-state-scan.json
│   ├── run-leftovers.json
│   ├── lifecycle-reconciliation.json
│   ├── ownership-seal.json
│   ├── shell-skin-freeze.json
│   └── verdict.json
└── verifier/
    ├── source-binding.json
    ├── invocation.json
    ├── results.json
    └── results.sha256
```

Each scenario directory contains, when applicable:

```text
<scenario>/
├── selection.json
├── fixture-intent.json
├── fixture-result.json
├── plan.json
├── plan.sha256
├── commands.jsonl
├── revisions/
│   ├── <revision>.json
│   └── <revision>.sha256
├── attachments/
│   ├── manifest.json
│   └── <content-addressed-object>
├── marker-generations.jsonl
├── preparation-manifest.json
├── mutation-intents.jsonl
├── primitive-traces.jsonl
├── verifications.jsonl
├── cleanup-receipts.jsonl
├── before/
│   ├── state.json
│   ├── stat.json
│   ├── directory.json
│   └── kodi.json
└── after/
    ├── state.json
    ├── stat.json
    ├── directory.json
    └── kodi.json
```

An absent optional artifact is represented in the manifest as
`not_applicable` with a reason; files are not silently omitted.

### 5.2 Required evidence content

Record:

- source commit, clean committed status, source-tree digest, wheel filename,
  wheel digest, package version, and installed distribution metadata;
- committed present/absent Profile and inventory-selection paths, selected
  Profile/Intent IDs, and independent input digests for every scenario;
- Linux and macOS offline results and production-adapter contract results for
  the same commit and wheel;
- Python, uv, package, Paramiko, SSH client/server, CoreELEC, Kodi, Home
  Assistant package, harness, verifier, and independent-oracle versions;
- command arguments and environment variable **names only**;
- logical and physical Device identity, endpoint, independently pinned host
  key, platform/model/release, boot identity, profile-root identity, and time
  observations;
- initial and final Home Assistant override; all allowed Home Assistant status
  traffic; lifecycle state; and Kodi PID/process start identity;
- every Plan, Run revision, attachment digest, marker generation,
  preparation manifest, intent, primitive trace, Verification, rollback
  result, recovery action, cleanup receipt, and terminal report;
- independent content bytes digest, semantic tuple, entry type, mode,
  ownership, supported stat tuple, and fixed parent-directory listing before
  and after every fixture, mutation, and no-op;
- every sequenced reset, handoff, and freeze recheck, proving each fixture
  mutation interval is bracketed by valid handoff/freeze events;
- structured operator attestations and final Python ownership seal.

Do not record secrets, environment values, private keys, raw local private
paths, unrelated media names, broad directory trees, Kodi library contents, or
screenshots by default. Redact controller usernames and workspace locations
where they are not part of a public contract. The operator UI attestation is
the default because a screenshot can leak media and household information.

### 5.3 Independent offline bundle verifier

A separately invoked repository script/tool runs only after the acceptance
harness exits. Its source commit and source digest are recorded. It may share
only schema definitions and cryptographic primitives with production code; it
must not share Resource assessment, scenario verdict, or pass/fail logic.

The verifier must:

1. reject an unsealed, modified, duplicate-path, path-traversing, or
   schema-incompatible bundle;
2. recompute the manifest, file, source-tree, wheel, Plan, revision,
   attachment, and report digests;
3. verify attempt ID, source, wheel, contract, Device, Resource, and scenario
   bindings throughout;
4. replay the independent report-invariant checker;
5. independently recompute machine-verifiable pass/fail verdicts;
6. prove scenario order, terminality, cleanup, no retry, no stitching, and
   that every fixture mutation interval is bracketed by the corresponding
   sequenced handoff and freeze-recheck events;
7. identify every operator-only assertion and refuse to manufacture it from
   machine evidence;
8. emit one deterministic result and digest without Device access.

The verifier must not import or call `KodiSmartPlaylist.assess`, its renderer,
the production scenario verdict, or the production report verdict function.

## 6. Preconditions

All conditions are mandatory before the handoff.

### 6.1 Source and package

- The checkout is on the reviewed acceptance commit.
- `git status --porcelain=v1` is empty.
- The commit is reachable from the expected branch.
- The wheel was built from that exact clean tree.
- The installed wheel digest and metadata match the recorded wheel.
- The committed inventory selection and named present/absent Profiles exist in
  that tree; their selected Intent IDs and digests are recorded before contact.
- Required pure, offline, Linux, macOS, shared adapter, and production-adapter
  contract tests pass for the same commit.
- Ambiguous-outcome adapter cases pass even though live ambiguity injection is
  excluded.

### 6.2 Device identity and manageability

- The operator identifies the physical theater installation and confirms
  `ugoos-theater` is the intended disposable pilot.
- Inventory logical ID, endpoint, and independently authenticated pinned host
  key match.
- Freshly observed platform, model, release, boot identity, and profile-root
  identity match the Plan binding.
- Reconciler administrator SSH is functional without weakening host-key
  checking.
- The Device is Manageable: reachable, authenticated, correctly identified,
  safely observable, and able to satisfy required durability and atomicity
  capabilities.
- A host-key mismatch is an abort, not an invitation to edit `known_hosts`.

### 6.3 Home Assistant and Kodi

- `input_boolean.ugoos_theater_keep_kodi_running` is `on`.
- Kodi lifecycle state is `running`.
- Kodi JSON-RPC is available.
- Kodi PID and a stable process-start identity are recorded.
- Before reset, the harness invokes this exact JSON-RPC request shape:

  ```json
  {
    "jsonrpc": "2.0",
    "id": "pilot-new-shows",
    "method": "Files.GetDirectory",
    "params": {
      "directory": "special://profile/playlists/video/NewShows.xsp",
      "media": "video",
      "properties": ["playcount"]
    }
  }
  ```

  The response must contain at least one item whose `playcount` is `0`;
  otherwise abort because later no-Effect evidence would be nondiscriminating.
- Record only the response shape, item count, and safe item identifiers needed
  to prove that match; do not retain unrelated library metadata.
- The initial keep-running override value is recorded so it can be restored
  after the final evidence seal.
- Home Assistant provisioning/reload/restart is frozen for the acceptance
  window.

Kodi PID and start identity must remain unchanged throughout the core
acceptance window. Home Assistant status traffic is allowed and recorded, but
any lifecycle `start` or `stop`, shell provisioning, or PID/start-identity
change invalidates the core bundle. Keep the override on until after final
evidence is sealed.

### 6.4 No unresolved work

- No legacy shell transaction is pending, cleanup-pending, or
  incomplete-rollback.
- The last shell transaction ID, terminal state, and completion time are
  recorded.
- No local Reconciler lease, local active index entry, nonterminal Run,
  unexplained workspace, quarantine, or recovery-required state exists for
  the Device.
- No remote Reconciler marker, unexplained marker generation, helper, staged
  content, or Run-owned residue exists.
- Existing valid recovery state blocks the pilot. Never delete or abandon it
  to make preflight pass.

## 7. Readiness and path-safety guard

The readiness guard runs before fixture reset and again before each Run:

1. authenticate the pinned host key and re-observe Device/platform/boot
   identity;
2. query Kodi for the current `special://profile` translation;
3. require one absolute, normalized profile root of the expected filesystem;
4. resolve only `playlists/video/NewShows.xsp` beneath that root;
5. walk each existing path component without following symlinks;
6. reject root escape, `..`, alternate separators, symlink components,
   non-directory parents, nonregular leaf, unreadable leaf, or ambiguous
   lookup;
7. bind parent and leaf observations to stable identities used for stale
   rechecks;
8. consume source-matched production-adapter contract evidence and perform
   nonmutating protocol capability negotiation;
9. independently confirm the resolved leaf corresponds to the literal logical
   address.

The guard must not create the playlist or silently repair unsafe parents.

Any live write capability probe is a distinct preflight operation, not a probe
before each Run. It uses a separately declared safe probe root, records its
binding, and fully removes and verifies that root before the baseline snapshot.
It must not create or delete `/storage/.coreelec-reconciler/`; production code
alone proves genuine first use.

Before any no-op case, record `/storage` filesystem timestamp granularity and
the stat fields the server/protocol exposes. The supported tuple is fixed for
the attempt. Unsupported fields are declared before scenarios and never
silently omitted later.

### 7.1 Run Infrastructure root

The fixed remote root is `/storage/.coreelec-reconciler/`.

- If genuinely absent and no prior evidence says it existed, record
  `first_use=true`. Production Reconciler code must exclusively create it,
  set and verify its required type/mode, sync it durably, then freshly observe
  it before any Resource mutation.
- If present, record `first_use=false` and validate its type, ownership policy,
  mode, layout, durability capability, and absence of unexplained state.
- If malformed, unsafe, unreadable, or inconsistent with evidence, abort.
- Never remove the root, marker, workspace, quarantine, or retained recovery
  state to obtain a first-use result.

The milestone cannot pass until one retained bundle contains genuine
first-use infrastructure creation. A repeat fixture can pass its own Resource
cases but cannot substitute for that milestone proof.

## 8. Scoped reset helper

The reset helper is a future implementation artifact with its final spelling
defined by implementation documentation. It is not a broad cleanup command.
It operates on the resolved exact leaf only and has mandatory dry-run and
apply modes.

### 8.1 Safety contract

The helper:

- accepts typed Device, Resource, attempt, expected identity, and mode
  arguments;
- resolves the logical address through the same safe profile-root boundary;
- never accepts a wildcard, directory target, recursive flag, or arbitrary
  physical path;
- uses no-follow lookup and rejects a symlink or nonregular leaf;
- reads and records the complete shell-produced prestate bytes, SHA-256,
  semantics, entry type, and stat tuple before removal;
- snapshots the immediate parent directory without exposing unrelated names
  beyond the allowlisted structural evidence;
- proves no shell or Reconciler transaction is pending;
- removes only the exact playlist leaf to establish absence;
- durably syncs the parent and freshly verifies absence;
- proves siblings are byte/stat unchanged and no transient entry remains;
- cannot address `/storage/.coreelec-reconciler/`, any local workspace, or
  any path outside the resolved playlist leaf;
- aborts without mutation if any assertion fails.

Dry-run is mandatory immediately before apply, and apply consumes the digest of
that dry-run result. A changed identity or state invalidates it. After reset
proves filesystem absence, repeat the exact preflight `Files.GetDirectory`
call. It must fail or return unavailable for the playlist. If Kodi continues
to serve the playlist through cache, abort because the later no-Effect result
would be nondiscriminating.

### 8.2 Conceptual invocation

Final CLI spellings come from implementation documentation. The following
shows required inputs and sequence, not a promised interface:

```bash
set -eu

: "${PILOT_ATTEMPT_ID:?}"
: "${PILOT_DEVICE_ID:?}"
: "${PILOT_ENDPOINT:?}"
: "${PILOT_HOST_KEY_SHA256:?}"
: "${PILOT_RESOURCE_ID:?}"
: "${PILOT_EVIDENCE_DIR:?}"

RESET_HELPER="./implementation-defined-reset-helper"

"$RESET_HELPER" dry-run \
  --attempt-id "$PILOT_ATTEMPT_ID" \
  --device "$PILOT_DEVICE_ID" \
  --endpoint "$PILOT_ENDPOINT" \
  --host-key-sha256 "$PILOT_HOST_KEY_SHA256" \
  --resource "$PILOT_RESOURCE_ID" \
  --evidence "$PILOT_EVIDENCE_DIR"

"$RESET_HELPER" apply \
  --from-dry-run "$PILOT_EVIDENCE_DIR/transitions/01-absent-create/reset-dry-run.json" \
  --evidence "$PILOT_EVIDENCE_DIR"
```

No command in this procedure prints secret values.

## 9. Handoff and freeze

After reset and immediately before Python ownership, the operator and harness
produce a signed, typed handoff event:

```json
{
  "schema": "coreelec-reconciler-pilot-handoff-1",
  "attempt_id": "0199-example-attempt",
  "device_id": "ugoos-theater",
  "resource_id": "skin.playlist.new-shows",
  "logical_address": "special://profile/playlists/video/NewShows.xsp",
  "from_actor": "shell-operations",
  "to_actor": "python-reconciler",
  "effective_at": "2026-09-19T02:00:00Z",
  "last_shell_transaction": {
    "id": "recorded-terminal-transaction-id",
    "completed_at": "2026-09-19T01:55:00Z",
    "terminal_state": "committed"
  },
  "frozen_actors": [
    "provision-coreelec.sh with effective skin scope",
    "manual playlist edits",
    "Home Assistant provisioning",
    "other playlist writers"
  ],
  "operator_attestation_id": "operator-attestation-id",
  "signature": {
    "type": "implementation-defined-reviewed-signature",
    "value": "detached-signature-reference"
  }
}
```

The signature mechanism must be typed and verifiable but must not place a
private key or secret in the bundle. The harness rechecks freeze evidence
before every Run and after every declared fixture mutation. Each reset,
handoff, and recheck is appended under
`transitions/<seq>-<scenario>/`; no occurrence overwrites another.

## 10. Independent state oracle

The independent oracle is separate code with separate fixture logic. It:

- safely reads the actual resolved leaf without following links;
- records bytes and SHA-256;
- parses XML with a separate parser/configuration from the Resource Type;
- derives the exact tuple:
  `(presence, media_type, name, match, limit, rules, order, mode)`;
- distinguishes absent, malformed regular XML, unsafe, and unreadable;
- records `(dev,inode,mtime_ns,ctime_ns,size,mode,uid,gid)` where supported;
- records a bounded immediate-parent entry snapshot sufficient to detect
  transient or new entries without listing unrelated media;
- validates reports and digests independently.

It must not reuse the production Resource Type's assess, normalize, compare,
render, Verification verdict, or report verdict functions.

## 11. Fixed live scenario sequence

Scenarios run in this order. A scenario starts only after the previous Run is
terminal, its evidence is appended, its cleanup is verified, and its scenario
record is sealed. Fixture mutation is a distinct phase between Runs.

Every status and primitive trace below is normative. Any deviation fails the
core bundle; it may not be rationalized from implementation details.
Immediately before and after every fixture mutation, production mutation, and
no-op, record the same fixed bounded parent-directory listing. Any transient
sibling, leaked stage/backup/helper entry, or unexplained listing difference
fails the bundle.

### 11.1 Absent to create: fresh convergence

Precondition: the leaf is freshly verified absent.

Required proof:

- the Plan is actionable and the Run status is exactly `converged`;
- an actionable `create` mutation intent exists;
- the ordered mutation trace is `stage-write`, `atomic-replace`, plus `chmod`
  only when the create primitive cannot set mode `0644` atomically;
- exactly one applied Resource Change names
  `special://profile/playlists/video/NewShows.xsp`;
- there is no remove, rollback, or Effect trace;
- there is no Effect intent, Effect trace, Kodi restart, or unrelated Change;
- fresh Verification occurs after mutation;
- the independent oracle observes a regular file, exact semantics, and mode
  `0644`;
- the parent directory contains no Run transient;
- the Run is terminal and cleanup is verified;
- Kodi PID/start identity is unchanged.

This case exercises create. If this is the genuine first-use infrastructure
attempt, it also proves exclusive durable creation of
`/storage/.coreelec-reconciler/`.

### 11.2 Semantic-equivalent formatting variant to no-op

As a declared fixture phase, replace the leaf atomically with valid XML that
has different harmless formatting but the exact accepted semantic tuple and
mode `0644`. Record before/fixture/after observations and re-establish
handoff.

The following Run must:

- produce Plan status and Run status exactly `noop`;
- emit zero mutation intents, primitive mutation traces, Changes, Effects, and
  preparation manifest;
- leave bytes, SHA-256, and the full stat tuple identical to the fixture;
- create no transient/new parent-directory entries;
- advance only expected ownership/report marker generations;
- keep Kodi PID stable and the playlist usable.

This proves semantic comparison rather than byte normalization.

### 11.3 Valid semantic drift to atomic update

As a declared fixture phase, atomically install valid playlist XML differing
only by `limit=49`, with mode `0644`.

The Run status must be exactly `converged`. It emits one `update` with ordered
`stage-write`, `atomic-replace`, and `chmod` only if needed; uses the accepted
same-directory stale-safe atomic replacement path; freshly verifies exact
desired semantics and mode `0644`; preserves unrelated siblings; and emits no
rollback or Effect.

### 11.4 Mode-only drift

As a declared fixture phase, change only the regular leaf mode from `0644` to
`0600`; prove bytes and semantics did not change.

The Run status must be exactly `converged` with a `chmod`-only trace. Content
bytes, digest, inode, and size remain unchanged; there is no stage-write,
replace, remove, rollback, or Effect. This is intentionally the legacy-shell
conflict case: legacy shell writes this XML through a `0600` default and does
not verify mode, so shell skin scope remains frozen after Python handoff.

### 11.5 Malformed regular XML

As a declared fixture phase, atomically install a small malformed regular XML
fixture at mode `0644`. Do not use a symlink, directory, device node, or
unreadable file.

The Run status must be exactly `converged`. It classifies repairable
malformed-content drift and emits ordered `stage-write`, `atomic-replace`, plus
`chmod` only if needed. It freshly verifies exact semantics/mode, preserves
siblings, and emits no remove, rollback, or Effect.

### 11.6 Explicit desired absent

Use the committed named absent Profile/Intent. The Plan must show an explicit
approved `remove`, never hide deletion in update or cleanup.

The Run status must be exactly `converged` with a remove-only primitive trace.
It removes only the exact regular leaf, durably verifies fresh absence,
preserves siblings, emits no write/chmod/rollback/Effect, and keeps Kodi PID
stable. The exact `Files.GetDirectory` call must now fail or return unavailable;
continued cached success aborts the bundle as nondiscriminating.

### 11.7 Desired present: recreate and Kodi usability

Select the committed named present Profile/Intent. The Run status is exactly
`converged` and repeats the create trace from 11.1.

Then, without restarting Kodi:

1. invoke exactly `Files.GetDirectory` for
   `special://profile/playlists/video/NewShows.xsp`, media `video`, with the
   same reviewed video properties as preflight;
2. require at least one returned item matching `playcount=0`, recording only
   response shape, count, and safe identifiers;
3. prove Kodi PID/start identity is unchanged and no restart occurred;
4. the operator freshly navigates to the actual playlist, opens it, and
   observes at least one item—not merely its home-screen label;
5. record structured `pass`, `fail`, `error`, or `empty` without a screenshot.

If restart/PID change occurs, or only a restart makes the query/UI work, fail
and open the narrow Effect decision.

### 11.8 Immediate second-Run no-op

Without any intervening fixture, actor, or Desired State change, immediately
run the same present reconciliation again.

Plan and Run status must be exactly `noop`; there are zero mutation intents,
preparations, primitive traces, Changes, Effects, or cleanup mutations. It must
satisfy every no-op and stat/list invariant in section 12 and repeat the exact
JSON-RPC plus operator usability evidence with the same Kodi process.

### 11.9 Excluded live injections

Do not inject live:

- symlink or nonregular leaf hazards;
- unreadable or unsafe parent hazards;
- acknowledgement loss or other ambiguous mutation outcomes;
- malformed or unexplained Run Infrastructure;
- third-party mutation during rollback;
- concurrent controllers.

These remain mandatory offline/shared-production-adapter contracts. Excluding
them from this live Device protects unrelated state and does not relax their
acceptance status.

### 11.10 Supplemental recovery-evidence bundle

Only after the core acceptance bundle has passed and been sealed may a new,
separate supplemental bundle exercise deterministic pre-mutation
interruption/recovery. It never becomes a core scenario and cannot alter,
stitch, or retroactively strengthen/weaken the core verdict.

Run it only when the production test hook proves all of the following before
the Run begins:

- interruption occurs after durable preparation but before mutation intent;
- computed allowed actions are limited to normal finalize and/or
  known-unchanged terminal `failed_partial`;
- abandon and quarantine are impossible outcomes for the exercised state;
- no mutation intent or Device mutation can have occurred.

If the hook could quarantine, dead-end, or require abandonment, do not run it
live. Stop the supplemental bundle on any unexpected status and never continue
within it after a failed/interrupted Run. Failure of this bundle does not alter
the already sealed core bundle. Until a safe live hook exists, the architecture
recovery gate remains primarily #42 offline and production-adapter evidence.

## 12. Exact no-op proof

A no-op passes only if:

- independent before and after bytes are identical;
- SHA-256 is identical;
- inode, bytes, mode, size, mtime, and ctime are identical wherever the
  predeclared server capability exposes them; other supported tuple fields
  such as device, uid, and gid are also identical;
- the semantic tuple and mode remain exact;
- Plan and Run contain zero mutation intents, Resource Changes, primitive
  mutation traces, Effects, and preparation manifest;
- marker-generation changes are limited to the expected ownership/report
  lifecycle and contain no unexplained generation;
- bounded parent-directory listings are identical and contain no temporary,
  staged, backup, helper, or new entry;
- Kodi PID/start identity is stable;
- JSON-RPC usability and operator UI usability pass.

`/storage` timestamp granularity and supported stat fields are recorded before
the no-op cases. An unsupported field must be declared then; it cannot
disappear opportunistically from after-state evidence.

## 13. Fixture mutation protocol

All drift injection is a harness-owned, serialized phase between Runs:

1. prove the previous Run terminal and cleanup-complete;
2. append a typed fixture intent naming the exact permitted leaf,
   transformation, committed Profile/Intent selection, and digest;
3. temporarily suspend the Python sole-actor claim for only that fixture;
4. recheck Device/path identity and stale preconditions;
5. apply the exact no-follow, same-directory fixture mutation;
6. sync and independently observe the result;
7. prove sibling and Run Infrastructure invariants;
8. append a typed fixture result;
9. immediately append a new sequenced Python handoff and freeze recheck under
   `transitions/<seq>-<scenario>/`;
10. begin the next Run.

No interactive editor, unlogged `ssh`, wildcard, recursive operation, or
manual content change is permitted.

## 14. Kodi no-Effect decision

The live test must discriminate observability using one exact JSON-RPC method:

- before reset, `Files.GetDirectory` for the actual playlist URI, media
  `video`, and reviewed video properties returns at least one item matching
  `playcount=0`;
- after reset/absence, that same call fails or reports the URI unavailable;
  continued cached success aborts as nondiscriminating;
- after creation, with unchanged Kodi PID/start identity and no restart, the
  same call again returns at least one matching item;
- a human freshly navigates to and opens the actual playlist and observes at
  least one item; merely seeing a home label is insufficient;
- after recreate and immediate no-op, the same machine and human checks pass.

Legacy shell behavior is evidence only. Its grouped `skin` transaction stops
and restarts Kodi, but that does not establish an automatic Effect policy.
Issue #40's no-Effect default controls.

If Kodi cannot use the playlist without restart, or if any restart occurs, the
attempt fails. Do not restart Kodi to rescue the attempt. Open the narrow
Effect decision, implement and test that decision, and execute a wholly new
attempt.

Example operator attestation:

```json
{
  "schema": "coreelec-reconciler-kodi-ui-attestation-1",
  "attempt_id": "0199-example-attempt",
  "scenario_id": "07-recreate-and-kodi",
  "device_id": "ugoos-theater",
  "display_path_confirmed": true,
  "actual_playlist_navigated": true,
  "playlist_opened": true,
  "item_observed": true,
  "unexpected_restart_seen": false,
  "result": "pass",
  "operator": "recorded-operator-id",
  "observed_at": "2026-09-19T02:30:00Z",
  "signature": "detached-signature-reference"
}
```

## 15. Pass, fail, and abort

### 15.1 Pass

An attempt passes only when:

- every mandatory precondition and scenario passes in order;
- the same attempt/source/wheel/Device/contract bindings hold throughout;
- every Run is terminal and cleanup-complete;
- no quarantine, abandonment, active marker, nonterminal Run, or run-owned
  leftover remains;
- canonical present state and Kodi usability are restored;
- Python ownership is sealed and the persistent shell-skin freeze is recorded;
- the sealed bundle passes the independent offline verifier;
- the bundle includes genuine first-use infrastructure proof, or is explicitly
  classified as a repeat fixture that does not satisfy that milestone gate.

### 15.2 Fail

Failure includes:

- a wrong verdict, Change, trace, Effect, rewrite, mode, semantic tuple, or
  cleanup result;
- Kodi restart or inability to use the playlist without restart;
- operator attestation failure;
- unexpected external mutation;
- report/digest/invariant mismatch;
- any quarantined or abandoned Run;
- any recovery outcome other than the exact computed safe outcome.

Automation stops at the first failure. It may perform read-only
inspect/report, then only the computed recovery action allowed by #43. It may
not retry the failed Device operation or continue to later scenarios.

### 15.3 Abort

Abort before mutation for identity, host-key, manageability, lifecycle,
pending transaction, active ownership, unsafe path, unsafe infrastructure,
stale binding, evidence, or operator-readiness failures.

After mutation begins, report truthful failure/recovery state rather than
relabelling it a harmless abort.

Quarantine or abandon always means the attempt failed and future mutation is
blocked until a separately reviewed clearance/reset procedure exists. This
procedure does not define a quarantine-clear operation.

## 16. Recovery response

On interruption or failure:

1. freeze all writers;
2. do not retry;
3. preserve the local workspace and remote evidence;
4. invoke public read-only inspection;
5. independently observe Device, marker generation, leaf, Kodi process, and
   parent directory;
6. record the computed allowed actions;
7. execute only an allowed, preapproved recovery action;
8. verify its outcome and terminal truth;
9. attempt cleanup only after terminal truth is durable;
10. seal the full attempt `failed` or `aborted`.

Recovery never resumes forward mutation. Rollback is allowed only when current
state exactly matches the before-state or an enumerated Run-produced state and
all bindings remain valid. Third-party drift, unreadability, or ambiguity
blocks rollback. Cleanup failure cannot rewrite terminal truth.

## 17. Cleanup and ownership seal

Successful scenario cleanup is not the final ownership seal. At the end:

1. verify the last Run is terminal and its scenario evidence sealed;
2. independently verify canonical present semantics and mode `0644`;
3. prove no active local index/lease, remote marker, quarantine, nonterminal
   Run, exact Run-owned temporary, staged file, helper, backup, or leftover;
4. while the override remains on, inspect the pending Home Assistant lifecycle
   reconciliation and prove restoring the initial value will not issue a
   `start`/`stop` or stop Kodi;
5. write and sign the Python ownership seal and persistent shell-skin freeze;
6. retain all core evidence and seal the bundle;
7. exit the harness and separately invoke the repository bundle verifier;
8. only after the seal succeeds, restore the recorded keep-running value;
9. allow ordinary lifecycle reconciliation/status traffic and confirm health;
10. retain the post-seal operational restoration record separately; it cannot
    modify the sealed core verdict.

The seal does not hand skin ownership back to shell. Shell provisioning whose
effective scope includes `skin` stays frozen until its writer and verifier for
this State Address are retired at cutover. Other shell operations require a
recorded effective-scope proof excluding `skin` and `NewShows.xsp`.

## 18. Operator checklist

### Before Device contact

- [ ] Confirm branch, clean commit, source digest, wheel digest, and versions.
- [ ] Confirm named committed present/absent Profiles and inventory selection;
      record selected Profile/Intent IDs and digests.
- [ ] Confirm Linux/macOS offline and production-adapter contracts match that
      source and wheel.
- [ ] Create the empty evidence bundle and record its attempt ID.
- [ ] Confirm no command or evidence collector will store secrets or unrelated
      media data.

### Physical and lifecycle readiness

- [ ] Stand at the intended theater display and confirm the physical Device.
- [ ] Confirm logical ID `ugoos-theater`, endpoint, pinned host key, platform,
      release, and boot identity.
- [ ] Record the initial Home Assistant keep-running override.
- [ ] Turn `input_boolean.ugoos_theater_keep_kodi_running` on.
- [ ] Confirm lifecycle `running`, Kodi JSON-RPC available, and record PID/start
      identity.
- [ ] Run the exact pre-reset `Files.GetDirectory` query and prove at least one
      `playcount=0` item without retaining unrelated metadata.
- [ ] Freeze Home Assistant provisioning and all other playlist actors.

### Transaction and path readiness

- [ ] Confirm the last shell transaction ID/time is terminal.
- [ ] Confirm no pending shell transaction.
- [ ] Confirm no active/recovery/quarantine Reconciler state locally or
      remotely.
- [ ] Resolve the actual `special://profile` root and exact playlist leaf.
- [ ] Pass no-follow/type/read/root-containment checks.
- [ ] Record `/storage` timestamp granularity and supported stat fields.
- [ ] Bind source-matched adapter contracts; negotiate protocol capabilities
      nonmutatingly; if a write probe is required, use and fully clean only the
      declared safe probe root before baseline.
- [ ] Validate or genuinely first-create Run Infrastructure; never delete it.
- [ ] Pass durability and atomic capability guards.

### Reset and handoff

- [ ] Run reset-helper dry-run.
- [ ] Review exact leaf, prestate digest/stat, sibling invariants, and no-touch
      exclusions.
- [ ] Apply reset and verify fresh absence.
- [ ] Repeat exact JSON-RPC and prove unavailable; abort on cached success.
- [ ] Append sequenced handoff and freeze evidence.

### Core scenarios

- [ ] Absent → create/fresh convergence.
- [ ] Confirm first creation is usable without Kodi restart.
- [ ] Equivalent formatting → semantic no-op with unchanged bytes/stat.
- [ ] `limit=49` → atomic update to desired semantics.
- [ ] Mode `0600` → repair to `0644`.
- [ ] Malformed regular XML → repair.
- [ ] Desired absent → approved removal and fresh absence.
- [ ] Desired present → recreate and repeat Kodi usability.
- [ ] Immediate second Run → no-op/no rewrite.

### Finalization

- [ ] Verify canonical present state and no leftovers.
- [ ] While override remains on, prove restoring its initial value will not
      issue lifecycle `start`/`stop` or stop Kodi.
- [ ] Seal bundle, exit harness, and separately pass offline verification.
- [ ] Seal Python ownership and preserve shell `skin` freeze until cutover.
- [ ] After seal, restore the initial Home Assistant override.
- [ ] Observe lifecycle reconciliation and health.

### Supplemental recovery evidence

- [ ] Only after core seal, start a separate supplemental bundle if the safe
      pre-mutation hook proves the section 11.10 allowed-action constraints.
- [ ] Never stitch supplemental evidence into the core verdict.

## 19. Conceptual command sequence

Final CLI spellings, flags, exit codes, and artifact names come from reviewed
implementation documentation. These placeholders describe ordering and
required bindings only.

```bash
set -eu

: "${PILOT_ATTEMPT_ID:?}"
: "${PILOT_DEVICE_ID:=ugoos-theater}"
: "${PILOT_ENDPOINT:?}"
: "${PILOT_HOST_KEY_SHA256:?}"
: "${PILOT_RESOURCE_ID:=skin.playlist.new-shows}"
: "${PILOT_EVIDENCE_DIR:?}"

HARNESS="./implementation-defined-pilot-harness"
VERIFIER="./repository-independent-bundle-verifier"

"$HARNESS" initialize \
  --attempt-id "$PILOT_ATTEMPT_ID" \
  --device "$PILOT_DEVICE_ID" \
  --resource "$PILOT_RESOURCE_ID" \
  --evidence "$PILOT_EVIDENCE_DIR"

"$HARNESS" preflight \
  --endpoint "$PILOT_ENDPOINT" \
  --host-key-sha256 "$PILOT_HOST_KEY_SHA256" \
  --record-stat-capabilities \
  --profile present.acceptance \
  --profile absent.acceptance

"$HARNESS" kodi-check --phase before-reset \
  --method Files.GetDirectory \
  --directory special://profile/playlists/video/NewShows.xsp \
  --media video

"$HARNESS" reset --scenario absent-create --dry-run
"$HARNESS" reset --scenario absent-create --apply-reviewed-dry-run
"$HARNESS" kodi-check --phase after-reset --expect unavailable
"$HARNESS" handoff --scenario absent-create \
  --from shell-operations --to python-reconciler
"$HARNESS" freeze-recheck --scenario absent-create

"$HARNESS" run-scenario absent-create --profile present.acceptance
"$HARNESS" inject-fixture equivalent-formatting
"$HARNESS" handoff --scenario formatting-noop --from fixture --to python-reconciler
"$HARNESS" freeze-recheck --scenario formatting-noop
"$HARNESS" run-scenario formatting-noop --profile present.acceptance
"$HARNESS" inject-fixture semantic-limit-49
"$HARNESS" handoff --scenario semantic-drift --from fixture --to python-reconciler
"$HARNESS" freeze-recheck --scenario semantic-drift
"$HARNESS" run-scenario semantic-drift --profile present.acceptance
"$HARNESS" inject-fixture mode-0600
"$HARNESS" handoff --scenario mode-drift --from fixture --to python-reconciler
"$HARNESS" freeze-recheck --scenario mode-drift
"$HARNESS" run-scenario mode-drift --profile present.acceptance
"$HARNESS" inject-fixture malformed-regular-xml
"$HARNESS" handoff --scenario malformed-xml --from fixture --to python-reconciler
"$HARNESS" freeze-recheck --scenario malformed-xml
"$HARNESS" run-scenario malformed-xml --profile present.acceptance
"$HARNESS" freeze-recheck --scenario explicit-removal
"$HARNESS" run-scenario explicit-removal --profile absent.acceptance \
  --approval reviewed-removal-approval
"$HARNESS" freeze-recheck --scenario recreate-and-kodi
"$HARNESS" run-scenario recreate-and-kodi --profile present.acceptance
"$HARNESS" kodi-check --phase after-recreate \
  --method Files.GetDirectory \
  --directory special://profile/playlists/video/NewShows.xsp \
  --media video
"$HARNESS" freeze-recheck --scenario immediate-noop
"$HARNESS" run-scenario immediate-noop --profile present.acceptance

"$HARNESS" seal-core --preserve-shell-skin-freeze
"$VERIFIER" verify --offline --bundle "$PILOT_EVIDENCE_DIR"

# Optional only after the core bundle is sealed and independently verified.
SUPPLEMENTAL_EVIDENCE_DIR="${PILOT_EVIDENCE_DIR}.supplemental-recovery"
"$HARNESS" initialize-supplemental \
  --evidence "$SUPPLEMENTAL_EVIDENCE_DIR" \
  --require-safe-pre-mutation-hook
"$HARNESS" run-supplemental pre-mutation-recovery
"$HARNESS" seal-supplemental
"$VERIFIER" verify --offline --bundle "$SUPPLEMENTAL_EVIDENCE_DIR"
```

The operator performs the display attestations when prompted. The harness
must not automate or default those answers. The supplemental commands are
omitted entirely unless the hook proves section 11.10 safe before mutation.

## 20. Milestone acceptance implications

The first managed-file milestone is accepted only when one execution of this
accepted procedure produces an unstitched, sealed bundle that proves:

- same-commit Linux/macOS offline and production-adapter contracts;
- exact Device and path binding;
- one genuine first-use Run Infrastructure creation;
- fresh absent-to-present convergence;
- semantic formatting no-op;
- semantic, mode, and malformed-content repair;
- approved absence and recreation;
- actual Kodi usability without restart or Effect;
- immediate second-Run no rewrite;
- exact cleanup, canonical final state at `0644`, lifecycle restoration,
  sealed Python ownership, and persistent shell-skin freeze;
- independent offline bundle verification.

A repeat fixture without first-use infrastructure proof is useful regression
evidence but cannot satisfy the milestone by itself. Live ambiguity injection
is excluded; the mandatory shared production-adapter contracts carry that
proof. A deterministic pre-mutation interruption belongs
only to a separate post-core supplemental bundle through the safe tested hook.
Its failure cannot alter the sealed core result; without such a hook, #42
offline/adapter evidence remains the primary architecture recovery gate.

Failure does not imply a factory reset. Reimage only under the triggers in
section 1. Otherwise, preserve evidence, execute computed recovery, restore
manageability, correct the implementation or narrow Effect decision, and begin
a wholly new attempt with a new evidence bundle and handoff.

## 21. Autonomous safety conclusion

The procedure is accepted with these fixed conclusions:

- scoped Resource reset is safer and more probative than repeated full-device
  reimaging;
- the actual production address is necessary to test Kodi observability;
- explicit ownership phases prevent shell/Python races; because shell writes
  this XML as `0600` while Python requires `0644`, semantic equality does not
  permit shell skin ownership to resume;
- Home Assistant enrollment remains active, with the keep-running override
  controlling lifecycle interference;
- live ambiguity and unsafe-node injection add Device risk without adding
  evidence beyond mandatory adapter contracts, so they are excluded;
- structured human UI attestation is sufficient and avoids media/privacy
  leakage;
- no-retry, no-stitching, append-only evidence and independent re-verification
  make a failed case visible rather than repairable by presentation;
- legacy shell restart behavior is not policy. The pilot decides empirically
  whether issue #40's no-Effect default holds.

The final accepted outcome leaves the playlist canonical at mode `0644`,
seals Python ownership, and keeps this Device dedicated as pilot acceptance
infrastructure with shell `skin` scope frozen until cutover.
