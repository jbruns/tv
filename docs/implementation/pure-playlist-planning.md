# Pure Kodi Smart Playlist planning

Issue #58 implements the nonmutating planning boundary for
`skin.playlist.new-shows`.

## Inputs and public paths

The existing `Reconciler.execute(command)` boundary accepts `ValidateCommand`
and `PlanCommand`. The CLI accepts:

```text
validate --device-id DEVICE --observations FILE
plan DEVICE --observations FILE
plan DEVICE --observations FILE --document run
```

`plan` writes the canonical Plan by default; `--document run` selects its
canonical nonmutating planning Run Report. Either JSON document receives
exactly one framing newline. Canonical bytes used for digests contain no
newline.

The supplied JSON document is versioned as
`CoreElecSuppliedPlanningInput` schema version 1. It contains fixed UUIDv7/time
values, safe Device binding evidence, and one bounded typed
`KodiSmartPlaylistObservation`. Regular-file content is base64 input capped at
65,536 bytes. It is parsed for planning but never copied to Plan/Run output.
Unknown or duplicate fields, invalid modes, non-UUIDv7 IDs, non-UTC times,
invalid digests, invalid base64, and oversized content fail closed.

## Semantic behavior

The XML parser compares a strict canonical model: media type, display name,
match mode, limit, ordered rules, and order field/direction. Whitespace, XML
declaration style, UTF-8 BOM, CRLF, and attribute order do not cause drift.
Unknown elements or attributes, namespaces, duplicate singleton fields,
malformed rules/XML, unsupported encoding declarations, and undecodable bytes
are repairable malformed-current divergence for a safe regular file.

| Observation and Desired State | Plan |
| --- | --- |
| absent, desired present | actionable `smart_playlist.create` |
| semantic equivalent, mode `0644` | `noop` |
| semantic drift | actionable `smart_playlist.update` |
| mode-only drift | actionable `smart_playlist.update` |
| malformed safe regular content | actionable `smart_playlist.update` |
| present, desired absent | actionable `smart_playlist.remove` |
| absent, desired absent | `noop` |
| unsafe non-regular state | `blocked` |

Formatting-only inputs normalize to byte-identical Plan/Run documents when all
event inputs are identical. Changes carry stable reason codes, normalized
before/desired digests, an exact evidence-digest precondition,
`content_mutation` (and `removal` when applicable), verified rollback
capability, and no Effects. Observe-only drift remains visible but cannot
produce a Change.

## Canonical documents

Plans and planning Run Reports are frozen values backed by canonical UTF-8 JSON
bytes. Objects use lexicographically sorted keys and no insignificant
whitespace. Canonical bytes have no trailing newline; CLI JSON adds exactly one
LF.

Plan `full_digest` omits only itself. The semantic projection omits exactly
`plan_id`, `created_at`, `expires_at`, `producer.version`, `full_digest`, and
`semantic_digest`. Run `current_digest` omits only itself, and revision 2 links
to the digest of the nonpersisted revision-1 `planning` value. Strict decoders
reject noncanonical bytes, duplicate/unknown fields, unsupported kinds or
versions, malformed digests, and digest tampering.

No Plan or Run contains supplied XML, credentials, transport exception text,
controller-local paths, staging names, or secret values.

### Plan schema version 2 dependency amendment

Plan schema version 2 supports a complete selected Resource set rather than
the original single-Resource slice. Every Resource carries a closed
`requires` array containing sorted, unique Resource IDs. The Resources and
their evidence records are ordered by a stable topological sort: all currently
ready Resources are ordered by Resource ID before the next dependency layer.
The decoder rejects missing or unknown fields, unregistered Resource Types,
duplicate Resource/evidence/Change IDs, self/dangling/duplicate dependencies,
cycles, unstable ordering, and any Resource/Change/evidence binding mismatch.

Dependencies, every Resource, every evidence record, and every Change are
covered by both the full and semantic Plan digests. A decoded
`CanonicalPlan.resource_dependencies` therefore reconstructs the exact
`requires` graph from saved canonical Plan bytes without consulting mutable
authored or resolved configuration. The reporting-side
`check_plan_invariants()` oracle independently checks canonical bytes, digests,
graph ordering, and cross-record references rather than calling the production
Plan validator.

Schema version 1 remains accepted only for its original single Resource and
single evidence shape, with an implicit empty dependency set. Its existing
canonical golden bytes and digests are unchanged. The multi-Resource golden is
explicitly schema version 2.

## Exclusions

This slice does not implement SSH/SFTP, live Device observation, durable Run
workspaces, apply, Verification, rollback, recovery, Effect execution,
authored `RemoteFile`, or hard-coded Desired State. Desired State comes only
from the resolved authored configuration delivered by issue #57.
