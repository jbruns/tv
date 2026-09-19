# Device authority, preparation, and recovery inspection

M3.2 provides the offline authority and preparation boundary for managed
files. It does not authorize Device access or managed-state mutation.
`SKIN-025` remains shell-owned until the M4 handoff.

## Authority scopes

Three independent mechanisms are intentionally not interchangeable:

- the local Device lease excludes concurrent mutating Runs on one controller;
- the Run revision lease serializes one immutable evidence chain;
- the durable remote ownership marker excludes other controllers.

An execution Run persists its random ownership token locally before remote
acquisition. Only the token digest enters canonical evidence or the remote
marker. The active Device index is added before acquisition and may
over-report after a crash; it must never under-report. A verified full
workspace scan is the only way to rebuild it.

Remote authority is granted only by atomic exclusive creation followed by
marker and parent durability, reread, and digest verification. Existing,
foreign, malformed, symlinked, nonregular, quarantined, or unknown remote
state blocks acquisition. Marker updates compare the full identity, token
digest, generation, phase, and marker digest. Release and quarantine are
separate operations.

Elapsed time, a missing process, a PID, a hostname, or a heartbeat never
authorizes takeover. M3 has no takeover or quarantine-clearing operation.

## Safe managed paths

The Resource retains its logical State Address, for example:

```text
special://profile/playlists/video/NewShows.xsp
```

Resolution requires an observed typed Kodi Profile-root capability. The
suffix is joined using case-sensitive POSIX rules and must remain strictly
beneath the normalized absolute root. Unknown schemes, missing capability,
empty components, `.` or `..`, non-absolute roots, and root escape are
rejected before observation.

The normalized Device path may appear in Resource evidence. Controller-local
paths and Run Infrastructure temporary names may not.

## Observation and preparation

Observation uses fresh `lstat`-style metadata and a bounded complete read.
Absence is distinct from an unknown result. Symlinks, directories,
nonregular entries, unreadable content, oversized content, incomplete reads,
and transport failures are unsafe or unverifiable and block preparation.

Preparation performs no managed-address mutation. It:

1. freshly captures complete presence, kind, bytes, size, digest, and mode;
2. durably publishes and rereads a content-addressed rollback attachment;
3. records every normalized state reachable at later primitive boundaries;
4. builds a complete binding-specific preparation manifest; and
5. freshly rechecks the original precondition.

Attachment, codec, binding, or digest corruption prevents rollback authority.
A stale final recheck requires replanning and performs no mutation.

## Inspection and allowed actions

Inspection is read-only. It reads the remote marker, validates local chains,
attachments, codecs, preparation, binding, helper state, and fresh Resource
state, then rereads the marker. A generation or digest change makes the
snapshot unstable.

Allowed actions are computed as a pure total function of that snapshot:

- `inspect` requires enough opaque identity to avoid probing an arbitrary
  Device;
- `resume_verification` performs observation and Verification only, never
  forward mutation;
- `rollback` requires complete valid preparation, original approval, matching
  binding, no live helper, and a fresh state equal to the before-state, known
  post-image, or an enumerated Run-produced intermediate;
- `finalize normal` preserves known terminal truth and cannot claim
  Convergence;
- `finalize abandon` requires separate approval and a non-empty reason, and
  converts ownership into durable blocking quarantine.

Corrupt evidence permits only inspection and, when ownership can be safely
identified, approved abandonment. Transport failure is `unknown`, not
`absent`. Recovery does not retry an operation, finish a pending forward
primitive, start an unperformed Change, rerun an Effect, or infer safety from
age.

Public facts contain opaque Run/workspace IDs, logical or approved normalized
managed paths, typed states, and digests. They never contain ownership tokens,
secret values, controller-local paths, transport exception text, or temporary
remote names.
