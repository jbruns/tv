# Canonical Plan and Run Report schema contract

Date: 2026-09-18

Ticket: [Prototype canonical Plan and Run report schemas](https://github.com/jbruns/tv/issues/39)

Interactive evidence: [Throwaway Plan/Run state-model prototype](../../prototypes/coreelec-reconciler-plan-run-schema-prototype.html)

Status: **Accepted contract-level decision**

## 0.1 Issue 81 Plan dependency amendment (2026-09-19)

Plan schema version 2 closes the restart-reconstruction gap for selected
Resource dependencies. Each Plan Resource has a required `requires` array of
sorted, unique Resource IDs. All referenced Resources must be present in the
same Plan. Self-dependencies, duplicate edges, dangling references, cycles,
duplicate Resource/evidence/Change IDs, and mismatched cross-references are
invalid.

Resources use a deterministic stable topological order. At each dependency
layer, ready Resources are ordered by Resource ID. Evidence follows the same
Resource order, and Changes remain nested under their owning Resource. The
complete graph, all Resources, evidence, and Changes participate in both full
and semantic digests. Consequently execution and recovery can reconstruct the
approved dependency and reverse-dependency order solely from saved canonical
Plan bytes.

Version 2 normalized evidence is dispatched through the registered Resource
Type's closed codec. Its normalized summary and state digest must exactly
match each referencing Change's before-state. Resource management, desired
relation, blockers, and Change presence must form an accepted assessment
combination; for example, an observe-only divergence has its dedicated
blocker and no Change, while an enforcing divergence has one Change and no
blocker.

Schema version 1 remains valid only for the original single-Resource shape and
has an implicit empty `requires` set, preserving its accepted canonical bytes
and digests.

## 0. Issue 43 recovery refinement (2026-09-18)

[Issue 43](2026-09-18-run-workspace-recovery-effect-contracts.md) keeps the
closed canonical status set and refines `failed_partial`: it means any fully
observed, known, non-converged final state, including zero mutation with known
unchanged state after an execution blocker. It is not limited to a mixed
state. Unknown or unsafe state remains `failed_recovery_required`.

Recovery action codes remain `inspect`, `resume_verification`, `rollback`, and
`finalize`. `finalize` now has a required closed mode, `normal` or `abandon`.
Abandonment requires a separate explicit approval and reason and results in
`failed_recovery_required`; it cannot reuse ordinary finalization authority.

## 1. Decision

The Reconciler has two separate canonical JSON document kinds:

- an immutable `CoreElecReconcilerPlan`, which authorizes potential work; and
- a revisioned `CoreElecReconcilerRunReport`, which records the actual
  observe/plan/apply/verify lifecycle and evidence.

A Run is the full invocation or attempt. Its first report revision begins in
`planning`, before a Plan exists. Every planning invocation emits a revisioned
Run Report. A blocked or no-op Plan terminates that Run as `blocked` or `noop`;
there is no execution phase.

The Plan records its originating planning Run ID. Applying a saved actionable
Plan in a later invocation creates a fresh execution Run ID that references
the exact Plan and its originating planning Run. Recovery creates later
revisions with the same Run ID.

This record resolves machine data contracts and semantics. Exact Pydantic
types and module names, workspace paths and lock mechanics, retry execution,
and report storage are later implementation decisions, principally
[issue #43](https://github.com/jbruns/tv/issues/43).

## 2. Authority and presentation boundary

Canonical JSON is the sole automation contract. Automation may depend only on
schema-defined fields, codes, ordering, references, and digests.

The following are derived presentation and are never authoritative:

- prose summaries and remediation wording;
- colors, icons, tables, headings, and display order;
- localized messages;
- rendered commands or transport exception text;
- a generic success boolean.

Presentation can change without changing the underlying contract. A consumer
must determine executability from disposition, blockers, expiry, approvals,
and typed states—not prose or severity.

## 3. Canonical JSON and compatibility

| Concern | Contract |
|---|---|
| Encoding | UTF-8 |
| Objects | Keys sorted lexicographically |
| Whitespace | No insignificant whitespace |
| Arrays | Schema-defined deterministic order; dependency order then stable ID where applicable |
| Numbers | Integers or exact decimal strings; binary floating point is forbidden |
| Time | RFC 3339 UTC with `Z` |
| IDs | Fresh UUIDv7 Plan and Run IDs |
| Digests | SHA-256 over canonical bytes, written as `sha256:<64 lowercase hex>` |
| Fields | Duplicate and unknown fields are rejected |
| Codes | Closed required-code vocabularies; unknown required codes are rejected |
| Nulls | Each field explicitly defines required, nullable, or omitted; null and omission are never inferred equivalent |
| Extensions | Only named, versioned extension containers declared by the schema |

One repository-owned serializer will eventually own byte production. It must
have byte-for-byte fixtures. Producers must not independently approximate
canonicalization.

Each document separates:

```json
{
  "kind": "CoreElecReconcilerPlan",
  "producer": {
    "name": "coreelec-reconciler",
    "version": "0.1.0"
  },
  "schema_version": 1
}
```

`schema_version` governs compatibility. Producer version is evidence, not a
compatibility signal.

A consumer rejects:

- unsupported schema versions;
- digest mismatch;
- invalid references or duplicate IDs;
- unknown fields outside declared extension containers;
- unknown required enum or code values;
- nondeterministic or noncanonical input when canonical bytes are required.

## 4. Identity and digests

Plan and Run IDs are fresh UUIDv7 values, never content-derived identities.
Stable Resource IDs and State Addresses persist across Plans. Change, Effect,
attempt, and evidence IDs are local to their owning document or Run. Tools
compare Changes across Plans by Resource ID plus operation code and logical
operation key, not by local Change ID.

### 4.1 Plan digests

Every Plan carries:

- `full_digest`: SHA-256 of the complete canonical Plan including ID, event
  times, target binding, evidence, and all semantics, excluding only the
  `full_digest` field itself;
- `semantic_digest`: SHA-256 of a schema-defined semantic projection.

The semantic projection excludes only this enumerated event metadata:

- `plan_id`;
- `created_at`;
- `expires_at`;
- `producer.version`;
- `full_digest`;
- `semantic_digest`.

It includes target binding, Desired State, normalized evidence, Changes,
blockers, warnings/advisories, impacts, approval requirements, continuation
policy, Effects, dependencies, and Guards. Changing any included value changes
the semantic digest.

The Plan also records separate SHA-256 digests for:

- authored configuration;
- resolved Profile;
- Artifact catalog/resolution;
- controller capability set;
- observation snapshot;
- aggregate semantic input.

These bindings are not interchangeable.

### 4.2 Run Report revisions

All snapshots of one Run share `run_id`. Revisions:

- start at `1`;
- increase monotonically;
- include `previous_revision_digest` (`null` only for revision 1);
- include `current_digest`, computed over the revision with that field omitted;
- form a digest chain;
- become immutable when terminal.

## 5. Plan contract

### 5.1 Disposition and completeness

| Disposition | Meaning | Executable |
|---|---|---|
| `noop` | Every safely closed selected Resource is satisfied or not applicable | No |
| `actionable` | At least one executable Change and no blocker | Yes, while valid and approved |
| `blocked` | At least one typed blocker | No |

A Plan has one complete entry for every safely closed selected Resource,
including converged, not-applicable, observe-only, absent, and blocked
Resources. It is not merely a Change list.

Any known Resource, Guard, dependency, ownership, evidence, or capability
blocker makes the entire Plan `blocked` and prevents execution. Blocked and
no-op Plans retain full evidence. A blocked Plan may retain calculable
candidate Changes, but each is explicitly non-executable.

Only actionable Plans have:

- `valid_from`;
- mandatory `expires_at`;
- `approval_requirements`.

An expired Plan cannot start execution. Any Device identity mismatch requires
re-planning.

### 5.2 Exact Device binding

The target binding includes:

- logical Device ID;
- endpoint host and port;
- pinned SSH host-key fingerprint;
- freshly observed platform identity fingerprint.

### 5.3 Evidence

All normalized evidence uses one envelope:

| Field | Meaning |
|---|---|
| `evidence_id` | Local stable evidence ID |
| `subject` | Typed subject kind and ID |
| `state_addresses` | Sorted unique State Addresses |
| `observed_at` | RFC 3339 UTC observation time |
| `observer` | Stable observer code and version |
| `payload_kind` / `payload_schema_version` | Closed typed payload contract |
| `payload` | Safe normalized payload sufficient for review/recheck |
| `raw_attachment_digest` | Optional content-addressed raw attachment |

Raw attachments are optional unless the normalized payload cannot be
interpreted without one. If a required attachment is missing, execution is
invalid. Canonical evidence never contains secrets.

Desired-state relation codes are:

- `satisfied`;
- `divergent`;
- `not_applicable`;
- `unverifiable`.

Physical present/absent is a payload or domain fact, not a desired-state
outcome. `unverifiable` always has a typed blocker or failure.

### 5.4 Resources and Changes

A Resource entry has zero or more typed Changes. A Change includes:

- a Plan-local stable ID unique within the Plan;
- Resource ID and Resource Type;
- operation code and logical operation key;
- sorted unique affected State Addresses;
- safe before and desired summaries;
- complete normalized state digests and evidence references;
- closed impact codes;
- typed preconditions;
- declared Effects;
- rollback capability.

It never includes commands, secrets, rendered shell, or transport
representation.

Preconditions are typed evidence facts or digests and are rechecked
immediately before mutation. Mismatch means stale Plan: no mutation occurs.

### 5.5 Effects and barriers

Resource Types declare Effects. The pure planner orders and coalesces Effect
groups and barriers before approval. Runtime never invents a stronger Effect.
An Effect is skipped only if no successful contributing Change needs it.

Contributing Changes receive fresh Verification before their coalesced Effect.
The Effect runs once. Every affected Resource is then freshly re-observed
before crossing the barrier or claiming final convergence.

### 5.6 Impact and approval

The closed ordered v1 impact codes are:

1. `content_mutation`
2. `removal`
3. `kodi_restart`
4. `service_reload`
5. `device_reboot`

Impact is separate from Resource Type and Effect. Adding an impact code
requires a schema version change.

An actionable Plan requires base scope `apply` plus one scope for every
elevated impact present:

- `impact.removal`;
- `impact.kodi_restart`;
- `impact.service_reload`;
- `impact.device_reboot`.

Approval grants are not Plan mutations. They are input to Run execution and
are copied into the Report with actor, mechanism, time, exact Plan ID, exact
full digest, and scope. Interactive and noninteractive grants use the same
canonical shape.

The Plan fixes one continuation policy before approval:

- `continue_safe_independent` (default);
- `fail_fast`.

Warnings and advisories are typed nonblocking records. Severity and prose
never determine executability.

## 6. Full actionable Plan example

This is a complete canonical-shape example. Digest values are illustrative.
The independent Resource is deliberately non-disruptive; the Effect-producing
Resource demonstrates coalescing.

```json
{
  "approval_requirements": [
    {
      "scope": "apply"
    },
    {
      "scope": "impact.kodi_restart"
    }
  ],
  "blockers": [],
  "continuation_policy": "continue_safe_independent",
  "created_at": "2026-09-18T23:20:00Z",
  "device": {
    "endpoint": {
      "host": "coreelec-living-room.example.test",
      "port": 22
    },
    "logical_id": "living-room.ugoos-am6b-plus",
    "observed_platform_identity_fingerprint": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "ssh_host_key_fingerprint": "SHA256:examplePinnedHostKey"
  },
  "disposition": "actionable",
  "evidence": [
    {
      "evidence_id": "evidence.playlist.before",
      "observed_at": "2026-09-18T23:18:00Z",
      "observer": {
        "code": "kodi-smart-playlist-observer",
        "version": 1
      },
      "payload": {
        "limit": 25,
        "presence": "present"
      },
      "payload_kind": "KodiSmartPlaylistObservation",
      "payload_schema_version": 1,
      "raw_attachment_digest": null,
      "state_addresses": [
        "special://profile/playlists/video/NewShows.xsp"
      ],
      "subject": {
        "id": "skin.playlist.new-shows",
        "kind": "resource"
      }
    },
    {
      "evidence_id": "evidence.ssh-banner.before",
      "observed_at": "2026-09-18T23:18:01Z",
      "observer": {
        "code": "managed-file-observer",
        "version": 1
      },
      "payload": {
        "presence": "present"
      },
      "payload_kind": "ManagedFileObservation",
      "payload_schema_version": 1,
      "raw_attachment_digest": null,
      "state_addresses": [
        "file:///storage/.config/ssh/banner"
      ],
      "subject": {
        "id": "ssh.banner",
        "kind": "resource"
      }
    },
    {
      "evidence_id": "evidence.kodi-language.before",
      "observed_at": "2026-09-18T23:18:02Z",
      "observer": {
        "code": "kodi-gui-settings-observer",
        "version": 1
      },
      "payload": {
        "language": "resource.language.en_us",
        "timezone_country": "USA"
      },
      "payload_kind": "KodiGuiSettingsObservation",
      "payload_schema_version": 1,
      "raw_attachment_digest": null,
      "state_addresses": [
        "kodi://settings/locale.language",
        "kodi://settings/locale.timezonecountry"
      ],
      "subject": {
        "id": "kodi.gui.language",
        "kind": "resource"
      }
    }
  ],
  "effects": [
    {
      "affected_resource_ids": [
        "kodi.gui.language"
      ],
      "barrier_id": "barrier.kodi-restart.01",
      "contributing_change_ids": [
        "change.kodi.gui.language.locale",
        "change.kodi.gui.language.timezone"
      ],
      "effect_id": "effect.kodi-restart.01",
      "effect_type": "KodiRestart",
      "impact_code": "kodi_restart",
      "operation_code": "kodi.restart"
    }
  ],
  "expires_at": "2026-09-19T23:20:00Z",
  "full_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "input_digests": {
    "aggregate_semantic": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "artifact_resolution": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "authored_configuration": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "controller_capabilities": "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    "observation_snapshot": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
    "resolved_profile": "sha256:2222222222222222222222222222222222222222222222222222222222222222"
  },
  "kind": "CoreElecReconcilerPlan",
  "originating_run_id": "019950f8-4c00-7000-8000-000000000201",
  "plan_id": "019950f8-4c00-7000-8000-000000000101",
  "producer": {
    "name": "coreelec-reconciler",
    "version": "0.1.0"
  },
  "resources": [
    {
      "blockers": [],
      "changes": [
        {
          "affected_state_addresses": [
            "special://profile/playlists/video/NewShows.xsp"
          ],
          "before": {
            "evidence_refs": [
              "evidence.playlist.before"
            ],
            "normalized_state_digest": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
            "summary": {
              "limit": 25,
              "presence": "present"
            }
          },
          "change_id": "change.skin.playlist.new-shows.update",
          "desired": {
            "normalized_state_digest": "sha256:4444444444444444444444444444444444444444444444444444444444444444",
            "summary": {
              "limit": 50,
              "presence": "present"
            }
          },
          "effects": [],
          "impact_codes": [
            "content_mutation"
          ],
          "operation_code": "smart_playlist.update",
          "operation_key": "special://profile/playlists/video/NewShows.xsp",
          "preconditions": [
            {
              "evidence_ref": "evidence.playlist.before",
              "expected_digest": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
              "kind": "normalized_state_digest_matches"
            }
          ],
          "resource_id": "skin.playlist.new-shows",
          "resource_type": "KodiSmartPlaylist",
          "rollback": {
            "capability": "verified_supported",
            "required_before_evidence_ref": "evidence.playlist.before"
          }
        }
      ],
      "desired_relation": "divergent",
      "evidence_refs": [
        "evidence.playlist.before"
      ],
      "management": "enforce",
      "resource_id": "skin.playlist.new-shows",
      "resource_type": "KodiSmartPlaylist",
      "state_addresses": [
        "special://profile/playlists/video/NewShows.xsp"
      ]
    },
    {
      "blockers": [],
      "changes": [
        {
          "affected_state_addresses": [
            "file:///storage/.config/ssh/banner"
          ],
          "before": {
            "evidence_refs": [
              "evidence.ssh-banner.before"
            ],
            "normalized_state_digest": "sha256:5555555555555555555555555555555555555555555555555555555555555555",
            "summary": {
              "presence": "present"
            }
          },
          "change_id": "change.ssh.banner.update",
          "desired": {
            "normalized_state_digest": "sha256:6666666666666666666666666666666666666666666666666666666666666666",
            "summary": {
              "presence": "present"
            }
          },
          "effects": [],
          "impact_codes": [
            "content_mutation"
          ],
          "operation_code": "managed_file.update",
          "operation_key": "file:///storage/.config/ssh/banner",
          "preconditions": [
            {
              "evidence_ref": "evidence.ssh-banner.before",
              "expected_digest": "sha256:5555555555555555555555555555555555555555555555555555555555555555",
              "kind": "normalized_state_digest_matches"
            }
          ],
          "resource_id": "ssh.banner",
          "resource_type": "ManagedFile",
          "rollback": {
            "capability": "verified_supported",
            "required_before_evidence_ref": "evidence.ssh-banner.before"
          }
        }
      ],
      "desired_relation": "divergent",
      "evidence_refs": [
        "evidence.ssh-banner.before"
      ],
      "management": "enforce",
      "resource_id": "ssh.banner",
      "resource_type": "ManagedFile",
      "state_addresses": [
        "file:///storage/.config/ssh/banner"
      ]
    },
    {
      "blockers": [],
      "changes": [
        {
          "affected_state_addresses": [
            "kodi://settings/locale.language"
          ],
          "before": {
            "evidence_refs": [
              "evidence.kodi-language.before"
            ],
            "normalized_state_digest": "sha256:7777777777777777777777777777777777777777777777777777777777777777",
            "summary": {
              "language": "resource.language.en_us"
            }
          },
          "change_id": "change.kodi.gui.language.locale",
          "desired": {
            "normalized_state_digest": "sha256:8888888888888888888888888888888888888888888888888888888888888888",
            "summary": {
              "language": "resource.language.en_gb"
            }
          },
          "effects": [
            "effect.kodi-restart.01"
          ],
          "impact_codes": [
            "content_mutation",
            "kodi_restart"
          ],
          "operation_code": "kodi_setting.update",
          "operation_key": "locale.language",
          "preconditions": [
            {
              "evidence_ref": "evidence.kodi-language.before",
              "expected_digest": "sha256:7777777777777777777777777777777777777777777777777777777777777777",
              "kind": "normalized_state_digest_matches"
            }
          ],
          "resource_id": "kodi.gui.language",
          "resource_type": "KodiGuiSettings",
          "rollback": {
            "capability": "verified_supported",
            "required_before_evidence_ref": "evidence.kodi-language.before"
          }
        },
        {
          "affected_state_addresses": [
            "kodi://settings/locale.timezonecountry"
          ],
          "before": {
            "evidence_refs": [
              "evidence.kodi-language.before"
            ],
            "normalized_state_digest": "sha256:9999999999999999999999999999999999999999999999999999999999999999",
            "summary": {
              "timezone_country": "USA"
            }
          },
          "change_id": "change.kodi.gui.language.timezone",
          "desired": {
            "normalized_state_digest": "sha256:abababababababababababababababababababababababababababababababab",
            "summary": {
              "timezone_country": "Britain (UK)"
            }
          },
          "effects": [
            "effect.kodi-restart.01"
          ],
          "impact_codes": [
            "content_mutation",
            "kodi_restart"
          ],
          "operation_code": "kodi_setting.update",
          "operation_key": "locale.timezonecountry",
          "preconditions": [
            {
              "evidence_ref": "evidence.kodi-language.before",
              "expected_digest": "sha256:7777777777777777777777777777777777777777777777777777777777777777",
              "kind": "normalized_state_digest_matches"
            }
          ],
          "resource_id": "kodi.gui.language",
          "resource_type": "KodiGuiSettings",
          "rollback": {
            "capability": "verified_supported",
            "required_before_evidence_ref": "evidence.kodi-language.before"
          }
        }
      ],
      "desired_relation": "divergent",
      "evidence_refs": [
        "evidence.kodi-language.before"
      ],
      "management": "enforce",
      "resource_id": "kodi.gui.language",
      "resource_type": "KodiGuiSettings",
      "state_addresses": [
        "kodi://settings/locale.language",
        "kodi://settings/locale.timezonecountry"
      ]
    }
  ],
  "schema_version": 1,
  "semantic_digest": "sha256:cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd",
  "valid_from": "2026-09-18T23:20:00Z",
  "warnings": []
}
```

Normalized evidence referenced above:

```json
{
  "evidence_id": "evidence.playlist.before",
  "observed_at": "2026-09-18T23:18:00Z",
  "observer": {
    "code": "kodi-smart-playlist-observer",
    "version": 1
  },
  "payload": {
    "display_name": "New Shows",
    "limit": 25,
    "media_type": "tvshows",
    "presence": "present"
  },
  "payload_kind": "KodiSmartPlaylistObservation",
  "payload_schema_version": 1,
  "raw_attachment_digest": null,
  "state_addresses": [
    "special://profile/playlists/video/NewShows.xsp"
  ],
  "subject": {
    "id": "skin.playlist.new-shows",
    "kind": "resource"
  }
}
```

## 7. No-op full Plan and Run

The following complete compact Plan demonstrates that a no-op retains selected
Resource evidence but has no execution validity or approvals.

```json
{
  "approval_requirements": [],
  "blockers": [],
  "continuation_policy": "continue_safe_independent",
  "created_at": "2026-09-18T23:20:00Z",
  "device": {
    "endpoint": {
      "host": "coreelec-living-room.example.test",
      "port": 22
    },
    "logical_id": "living-room.ugoos-am6b-plus",
    "observed_platform_identity_fingerprint": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "ssh_host_key_fingerprint": "SHA256:examplePinnedHostKey"
  },
  "disposition": "noop",
  "evidence": [
    {
      "evidence_id": "evidence.playlist.noop",
      "observed_at": "2026-09-18T23:18:00Z",
      "observer": {
        "code": "kodi-smart-playlist-observer",
        "version": 1
      },
      "payload": {
        "limit": 50,
        "presence": "present"
      },
      "payload_kind": "KodiSmartPlaylistObservation",
      "payload_schema_version": 1,
      "raw_attachment_digest": null,
      "state_addresses": [
        "special://profile/playlists/video/NewShows.xsp"
      ],
      "subject": {
        "id": "skin.playlist.new-shows",
        "kind": "resource"
      }
    },
    {
      "evidence_id": "evidence.ssh-banner.noop",
      "observed_at": "2026-09-18T23:18:01Z",
      "observer": {
        "code": "managed-file-observer",
        "version": 1
      },
      "payload": {
        "presence": "present"
      },
      "payload_kind": "ManagedFileObservation",
      "payload_schema_version": 1,
      "raw_attachment_digest": null,
      "state_addresses": [
        "file:///storage/.config/ssh/banner"
      ],
      "subject": {
        "id": "ssh.banner",
        "kind": "resource"
      }
    }
  ],
  "effects": [],
  "full_digest": "sha256:1010101010101010101010101010101010101010101010101010101010101010",
  "input_digests": {
    "aggregate_semantic": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
    "artifact_resolution": "sha256:1212121212121212121212121212121212121212121212121212121212121212",
    "authored_configuration": "sha256:1313131313131313131313131313131313131313131313131313131313131313",
    "controller_capabilities": "sha256:1414141414141414141414141414141414141414141414141414141414141414",
    "observation_snapshot": "sha256:1515151515151515151515151515151515151515151515151515151515151515",
    "resolved_profile": "sha256:1616161616161616161616161616161616161616161616161616161616161616"
  },
  "kind": "CoreElecReconcilerPlan",
  "originating_run_id": "019950f8-4c00-7000-8000-000000000301",
  "plan_id": "019950f8-4c00-7000-8000-000000000302",
  "producer": {
    "name": "coreelec-reconciler",
    "version": "0.1.0"
  },
  "resources": [
    {
      "blockers": [],
      "changes": [],
      "desired_relation": "satisfied",
      "evidence_refs": [
        "evidence.playlist.noop"
      ],
      "management": "enforce",
      "resource_id": "skin.playlist.new-shows",
      "resource_type": "KodiSmartPlaylist",
      "state_addresses": [
        "special://profile/playlists/video/NewShows.xsp"
      ]
    },
    {
      "blockers": [],
      "changes": [],
      "desired_relation": "satisfied",
      "evidence_refs": [
        "evidence.ssh-banner.noop"
      ],
      "management": "observe_only",
      "resource_id": "ssh.banner",
      "resource_type": "ManagedFile",
      "state_addresses": [
        "file:///storage/.config/ssh/banner"
      ]
    }
  ],
  "schema_version": 1,
  "semantic_digest": "sha256:1717171717171717171717171717171717171717171717171717171717171717",
  "warnings": []
}
```

Its planning invocation produces this terminal Report; no execution phase
exists:

```json
{
  "approvals": [],
  "current_digest": "sha256:1818181818181818181818181818181818181818181818181818181818181818",
  "device_id": "living-room.ugoos-am6b-plus",
  "ended_at": "2026-09-18T23:20:01Z",
  "failures": [],
  "kind": "CoreElecReconcilerRunReport",
  "lifecycle_history": [
    "planning",
    "noop"
  ],
  "originating_planning_run_id": "019950f8-4c00-7000-8000-000000000301",
  "plan_reference": {
    "originating_planning_run_id": "019950f8-4c00-7000-8000-000000000301",
    "plan_full_digest": "sha256:1010101010101010101010101010101010101010101010101010101010101010",
    "plan_id": "019950f8-4c00-7000-8000-000000000302"
  },
  "previous_revision_digest": "sha256:1919191919191919191919191919191919191919191919191919191919191919",
  "producer": {
    "name": "coreelec-reconciler",
    "version": "0.1.0"
  },
  "resource_results": [
    {
      "desired_disposition": "present",
      "final_convergence": "converged",
      "latest_observed_relation": "satisfied",
      "mutation_outcome": "not_required",
      "post_effect_verification": "not_applicable",
      "resource_id": "skin.playlist.new-shows",
      "rollback_outcome": "not_attempted",
      "verification_outcome": "fresh_match"
    },
    {
      "desired_disposition": "observe_only",
      "final_convergence": "converged",
      "latest_observed_relation": "satisfied",
      "mutation_outcome": "not_required",
      "post_effect_verification": "not_applicable",
      "resource_id": "ssh.banner",
      "rollback_outcome": "not_attempted",
      "verification_outcome": "fresh_match"
    }
  ],
  "revision": 2,
  "run_id": "019950f8-4c00-7000-8000-000000000301",
  "schema_version": 1,
  "started_at": "2026-09-18T23:10:00Z",
  "status": "noop"
}
```

## 8. Blocked Plan example (excerpt)

This valid JSON is explicitly an excerpt. The candidate Change remains visible
for review but cannot execute.

```json
{
  "excerpt": true,
  "plan": {
    "approval_requirements": [],
    "blockers": [
      {
        "code": "resource.unsafe-symlink",
        "evidence_refs": [
          "evidence.playlist.symlink"
        ],
        "subject": {
          "id": "skin.playlist.new-shows",
          "kind": "resource"
        }
      }
    ],
    "disposition": "blocked",
    "originating_run_id": "019950f8-4c00-7000-8000-000000000401",
    "resources": [
      {
        "changes": [
          {
            "change_id": "change.skin.playlist.new-shows.candidate",
            "executable": false,
            "operation_code": "smart_playlist.update"
          }
        ],
        "desired_relation": "unverifiable",
        "resource_id": "skin.playlist.new-shows"
      }
    ]
  },
  "run_terminal": {
    "lifecycle_history": [
      "planning",
      "blocked"
    ],
    "run_id": "019950f8-4c00-7000-8000-000000000401",
    "status": "blocked"
  }
}
```

## 9. Run Report contract

### 9.1 Status model

| Status | Terminal | Meaning |
|---|---:|---|
| `planning` | No | Observing and producing a Plan |
| `blocked` | Yes | Planning found a blocker; no execution |
| `noop` | Yes | Planning found no executable Change; no execution |
| `awaiting_approval` | No | Actionable Plan exists; grants incomplete |
| `ready` | No | Exact Plan is valid and fully approved |
| `executing` | No | Applying, verifying, running Effects, or recovery |
| `interrupted` | No | Durable recovery point; invocation incomplete |
| `converged` | Yes | Every convergence condition is freshly proven |
| `failed_rolled_back` | Yes | Failed path restored, Desired State not achieved |
| `failed_partial` | Yes | Final state is fully observed, known, and non-converged; includes mixed state and zero-mutation known unchanged |
| `failed_recovery_required` | Yes | Managed final state or ownership safety is unknown/unsafe, or Run was abandoned |

`converged` requires every selected applicable Resource, including
observe-only Resources, to have fresh final Verification after all relevant
Effects; all Guards must be satisfied and no failure or recovery may remain
unresolved.

### 9.2 Per-Resource truth

The Report keeps these dimensions separate:

- desired disposition;
- latest observed relation;
- mutation outcome;
- Verification outcome;
- rollback outcome;
- post-Effect Verification;
- final convergence.

Command success never implies Verification or rollback success.

### 9.3 Attempts and failures

Mutation, Verification, Effect, and rollback attempts are append-only and
ordered. Every attempt has a stable attempt ID, operation code, timestamps,
typed outcome, evidence references, and optional typed failure. Summary fields
point to the decisive attempt ID.

Every failure has:

| Field | Values/meaning |
|---|---|
| `code` | Stable typed failure code |
| `phase` | Planning, precondition, mutation, Verification, Effect, rollback, or recovery |
| `subject` | Typed subject kind and ID |
| `inherent_stop_scope` | `resource`, `barrier`, or `run` |
| `effective_stop_scope` | Scope after Plan policy |
| `retry_classification` | `never`, `replan`, `same_run`, or `operator_action` |
| `safe_message` | Secret-free display input |
| `evidence_refs` | Normalized evidence supporting the failure |

Stack traces and transport exception text are diagnostic
attachments/presentation, not canonical failure messages.

### 9.4 Continuation and barriers

`fail_fast` promotes every failure to effective `run` scope and marks
remaining work `skipped_run_stopped`.

Under `continue_safe_independent`:

- transitive dependents become `skipped_dependency`;
- work behind a failed barrier does not cross that barrier;
- unrelated pending, non-disruptive work may continue only after the failed
  Resource reaches a known final state;
- known means verified rollback, verified unchanged, or a fully observed known
  partial state;
- unknown or unsafe final state escalates to effective `run` scope.

### 9.5 Resource phases and rollback

Each enforcing Resource has explicit phases:

1. immediate precondition recheck;
2. mutation;
3. fresh Verification;
4. optional rollback;
5. rollback Verification.

Unchanged and observe-only Resources still receive fresh Verification without
mutation.

Automatic rollback is permitted only when:

- the exact Change declares rollback capability;
- sufficient before evidence exists and is still applicable;
- the base apply approval grants rollback permission.

Unsafe, stale, or unsupported rollback produces recovery-required truth.
Verified rollback preserves the original failure.

### 9.6 Recovery pointer

`interrupted` is durable and nonterminal. The Report exposes:

- an opaque workspace ID, never a path;
- computed allowed action codes;
- a typed reason for each allowed or disallowed action.

Action codes are:

- `inspect`;
- `resume_verification`;
- `rollback`;
- `finalize`.

`finalize` carries mode `normal` or `abandon`. `abandon` additionally requires
a distinct approval and reason bound to the Run/workspace/Device. A later
revision resumes or finalizes the same Run. `finalize` never asserts
convergence; fully known non-converged state becomes `failed_partial`, while
unresolved, unsafe, abandoned, or unknown state becomes
`failed_recovery_required`. Paths, lock layout, retention, and action
mechanics are specified by issue #43.

## 10. Full converged terminal Report

This complete Report corresponds to the actionable Plan example. All
contributing Changes verify, the coalesced Effect runs once, and the affected
Resource receives post-Effect Verification.

```json
{
  "approvals": [
    {
      "actor": "actor.local-admin",
      "granted_at": "2026-09-18T23:29:00Z",
      "mechanism": "interactive_cli",
      "plan_full_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "plan_id": "019950f8-4c00-7000-8000-000000000101",
      "scope": "apply"
    },
    {
      "actor": "actor.local-admin",
      "granted_at": "2026-09-18T23:29:01Z",
      "mechanism": "interactive_cli",
      "plan_full_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "plan_id": "019950f8-4c00-7000-8000-000000000101",
      "scope": "impact.kodi_restart"
    }
  ],
  "attempts": [
    {
      "attempt_id": "attempt.playlist.mutation.01",
      "ended_at": "2026-09-18T23:35:02Z",
      "evidence_refs": [
        "evidence.playlist.before"
      ],
      "operation_code": "smart_playlist.update",
      "outcome": "completed",
      "phase": "mutation",
      "started_at": "2026-09-18T23:35:00Z",
      "subject": {
        "id": "skin.playlist.new-shows",
        "kind": "resource"
      }
    },
    {
      "attempt_id": "attempt.playlist.verify.01",
      "ended_at": "2026-09-18T23:35:05Z",
      "evidence_refs": [
        "evidence.playlist.final"
      ],
      "operation_code": "smart_playlist.verify",
      "outcome": "matched",
      "phase": "verification",
      "started_at": "2026-09-18T23:35:03Z",
      "subject": {
        "id": "skin.playlist.new-shows",
        "kind": "resource"
      }
    },
    {
      "attempt_id": "attempt.ssh-banner.verify.01",
      "ended_at": "2026-09-18T23:35:08Z",
      "evidence_refs": [
        "evidence.ssh-banner.final"
      ],
      "operation_code": "managed_file.verify",
      "outcome": "matched",
      "phase": "verification",
      "started_at": "2026-09-18T23:35:06Z",
      "subject": {
        "id": "ssh.banner",
        "kind": "resource"
      }
    },
    {
      "attempt_id": "attempt.kodi-language.mutation.01",
      "ended_at": "2026-09-18T23:36:02Z",
      "evidence_refs": [
        "evidence.kodi-language.before"
      ],
      "operation_code": "kodi_setting.update_group",
      "outcome": "completed",
      "phase": "mutation",
      "started_at": "2026-09-18T23:36:00Z",
      "subject": {
        "id": "kodi.gui.language",
        "kind": "resource"
      }
    },
    {
      "attempt_id": "attempt.kodi-language.verify-before-effect.01",
      "ended_at": "2026-09-18T23:36:05Z",
      "evidence_refs": [
        "evidence.kodi-language.pre-effect"
      ],
      "operation_code": "kodi_setting.verify",
      "outcome": "matched",
      "phase": "verification",
      "started_at": "2026-09-18T23:36:03Z",
      "subject": {
        "id": "kodi.gui.language",
        "kind": "resource"
      }
    },
    {
      "attempt_id": "attempt.kodi-restart.01",
      "ended_at": "2026-09-18T23:37:15Z",
      "evidence_refs": [
        "evidence.kodi.ready"
      ],
      "operation_code": "kodi.restart",
      "outcome": "completed",
      "phase": "effect",
      "started_at": "2026-09-18T23:37:00Z",
      "subject": {
        "id": "effect.kodi-restart.01",
        "kind": "effect"
      }
    },
    {
      "attempt_id": "attempt.kodi-language.post-effect-verify.01",
      "ended_at": "2026-09-18T23:37:18Z",
      "evidence_refs": [
        "evidence.kodi-language.final"
      ],
      "operation_code": "kodi_setting.verify",
      "outcome": "matched",
      "phase": "post_effect_verification",
      "started_at": "2026-09-18T23:37:16Z",
      "subject": {
        "id": "kodi.gui.language",
        "kind": "resource"
      }
    }
  ],
  "current_digest": "sha256:2020202020202020202020202020202020202020202020202020202020202020",
  "device_id": "living-room.ugoos-am6b-plus",
  "ended_at": "2026-09-18T23:37:19Z",
  "failures": [],
  "kind": "CoreElecReconcilerRunReport",
  "lifecycle_history": [
    "planning",
    "awaiting_approval",
    "ready",
    "executing",
    "converged"
  ],
  "originating_planning_run_id": "019950f8-4c00-7000-8000-000000000201",
  "plan_reference": {
    "originating_planning_run_id": "019950f8-4c00-7000-8000-000000000201",
    "plan_full_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "plan_id": "019950f8-4c00-7000-8000-000000000101"
  },
  "previous_revision_digest": "sha256:2121212121212121212121212121212121212121212121212121212121212121",
  "producer": {
    "name": "coreelec-reconciler",
    "version": "0.1.0"
  },
  "recovery": {
    "allowed_actions": [],
    "workspace_id": "workspace:019950f8-4c00-7000-8000-000000000201"
  },
  "resource_results": [
    {
      "decisive_attempt_id": "attempt.playlist.verify.01",
      "desired_disposition": "present",
      "final_convergence": "converged",
      "latest_observed_relation": "satisfied",
      "mutation_outcome": "completed",
      "post_effect_verification": "not_applicable",
      "resource_id": "skin.playlist.new-shows",
      "rollback_outcome": "not_attempted",
      "verification_outcome": "matched"
    },
    {
      "decisive_attempt_id": "attempt.ssh-banner.verify.01",
      "desired_disposition": "observe_only",
      "final_convergence": "converged",
      "latest_observed_relation": "satisfied",
      "mutation_outcome": "not_required",
      "post_effect_verification": "not_applicable",
      "resource_id": "ssh.banner",
      "rollback_outcome": "not_attempted",
      "verification_outcome": "matched"
    },
    {
      "decisive_attempt_id": "attempt.kodi-language.post-effect-verify.01",
      "desired_disposition": "present",
      "final_convergence": "converged",
      "latest_observed_relation": "satisfied",
      "mutation_outcome": "completed",
      "post_effect_verification": "matched",
      "resource_id": "kodi.gui.language",
      "rollback_outcome": "not_attempted",
      "verification_outcome": "matched"
    }
  ],
  "revision": 5,
  "run_id": "019950f8-4c00-7000-8000-000000000201",
  "schema_version": 1,
  "started_at": "2026-09-18T23:10:00Z",
  "status": "converged"
}
```

## 11. Failure and recovery examples

Each block below is a clearly marked valid-JSON excerpt.

### 11.1 Safe-independent partial continuation

```json
{
  "excerpt": true,
  "failures": [
    {
      "code": "mutation.rejected-before-write",
      "effective_stop_scope": "resource",
      "evidence_refs": [
        "evidence.playlist.verified-unchanged"
      ],
      "inherent_stop_scope": "resource",
      "phase": "mutation",
      "retry_classification": "same_run",
      "safe_message": "Mutation did not occur; the original state is freshly verified.",
      "subject": {
        "id": "skin.playlist.new-shows",
        "kind": "resource"
      }
    }
  ],
  "resource_results": [
    {
      "final_convergence": "failed_known",
      "resource_id": "skin.playlist.new-shows"
    },
    {
      "final_convergence": "skipped_dependency",
      "resource_id": "skin.playlist.widget-cache"
    },
    {
      "final_convergence": "converged",
      "resource_id": "ssh.banner"
    }
  ],
  "status": "failed_partial"
}
```

With the same inherent failure and Plan policy `fail_fast`,
`effective_stop_scope` is `run` and both remaining Resources become
`skipped_run_stopped`.

### 11.2 Stale precondition

```json
{
  "excerpt": true,
  "attempt": {
    "attempt_id": "attempt.playlist.precondition.01",
    "ended_at": "2026-09-18T23:35:01Z",
    "evidence_refs": [
      "evidence.playlist.recheck"
    ],
    "operation_code": "smart_playlist.update",
    "outcome": "stale_no_mutation",
    "phase": "precondition_recheck",
    "started_at": "2026-09-18T23:35:00Z"
  },
  "failure": {
    "code": "precondition.normalized-state-digest-mismatch",
    "effective_stop_scope": "resource",
    "evidence_refs": [
      "evidence.playlist.recheck"
    ],
    "inherent_stop_scope": "resource",
    "phase": "precondition_recheck",
    "retry_classification": "replan",
    "safe_message": "Observed state changed after planning; no mutation occurred.",
    "subject": {
      "id": "skin.playlist.new-shows",
      "kind": "resource"
    }
  }
}
```

### 11.3 Verification failure and verified rollback

```json
{
  "excerpt": true,
  "failures": [
    {
      "code": "verification.desired-state-mismatch",
      "effective_stop_scope": "resource",
      "evidence_refs": [
        "evidence.playlist.verify-failed"
      ],
      "inherent_stop_scope": "resource",
      "phase": "verification",
      "retry_classification": "operator_action",
      "safe_message": "Fresh Verification did not establish Desired State.",
      "subject": {
        "id": "skin.playlist.new-shows",
        "kind": "resource"
      }
    }
  ],
  "resource_result": {
    "final_convergence": "rolled_back_verified",
    "mutation_outcome": "completed",
    "resource_id": "skin.playlist.new-shows",
    "rollback_outcome": "restored_and_verified",
    "verification_outcome": "mismatch"
  },
  "status": "failed_rolled_back"
}
```

### 11.4 Effect and post-Effect failure

```json
{
  "effect_failure_excerpt": {
    "failure": {
      "code": "effect.kodi-restart.failed",
      "effective_stop_scope": "barrier",
      "evidence_refs": [
        "evidence.kodi.restart-failure"
      ],
      "inherent_stop_scope": "barrier",
      "phase": "effect",
      "retry_classification": "operator_action",
      "safe_message": "Kodi restart did not reach the declared ready state.",
      "subject": {
        "id": "effect.kodi-restart.01",
        "kind": "effect"
      }
    },
    "resource_result": {
      "final_convergence": "failed_known",
      "post_effect_verification": "not_reached",
      "resource_id": "kodi.gui.language"
    }
  },
  "excerpt": true,
  "post_effect_failure_excerpt": {
    "failure": {
      "code": "verification.post-effect-mismatch",
      "effective_stop_scope": "barrier",
      "evidence_refs": [
        "evidence.kodi-language.post-effect"
      ],
      "inherent_stop_scope": "barrier",
      "phase": "post_effect_verification",
      "retry_classification": "operator_action",
      "safe_message": "Post-Effect state is known but does not satisfy Desired State.",
      "subject": {
        "id": "kodi.gui.language",
        "kind": "resource"
      }
    },
    "resource_result": {
      "final_convergence": "failed_known",
      "post_effect_verification": "mismatch",
      "resource_id": "kodi.gui.language"
    }
  }
}
```

### 11.5 Interrupted revision and recovery pointer

```json
{
  "current_digest": "sha256:2323232323232323232323232323232323232323232323232323232323232323",
  "excerpt": true,
  "previous_revision_digest": "sha256:2424242424242424242424242424242424242424242424242424242424242424",
  "recovery": {
    "actions": [
      {
        "allowed": true,
        "code": "inspect",
        "reason_code": "recovery.workspace-present"
      },
      {
        "allowed": true,
        "code": "resume_verification",
        "reason_code": "recovery.mutation-complete-verification-pending"
      },
      {
        "allowed": true,
        "code": "rollback",
        "reason_code": "recovery.rollback-capable-before-evidence-present"
      },
      {
        "allowed": true,
        "code": "finalize",
        "mode": "normal",
        "reason_code": "recovery.explicit-failure-finalization-available",
        "requirements": {
          "approval": false,
          "reason": false
        }
      }
    ],
    "workspace_id": "workspace:019950f8-4c00-7000-8000-000000000501"
  },
  "revision": 4,
  "run_id": "019950f8-4c00-7000-8000-000000000501",
  "status": "interrupted"
}
```

A resume revision keeps Run ID
`019950f8-4c00-7000-8000-000000000501`, increments `revision`, and points
`previous_revision_digest` at the interrupted revision. A finalization without
fresh convergence evidence ends as `failed_partial` or
`failed_recovery_required`, never `converged`.

### 11.6 Applying a saved Plan

```json
{
  "excerpt": true,
  "originating_planning_run_id": "019950f8-4c00-7000-8000-000000000201",
  "plan_reference": {
    "originating_planning_run_id": "019950f8-4c00-7000-8000-000000000201",
    "plan_full_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "plan_id": "019950f8-4c00-7000-8000-000000000101"
  },
  "revision": 1,
  "run_id": "019950f8-4c00-7000-8000-000000000601",
  "status": "awaiting_approval"
}
```

The execution Run ID differs from the Plan's originating planning Run ID.

## 12. Secret and attachment boundary

Boundary types reject secret-bearing canonical data before serialization.
There is no best-effort post-redaction pass.

Canonical documents contain only normalized safe evidence and safe
content-addressed attachment digests. Raw sensitive diagnostics live under a
separate access and retention policy and are never required to interpret the
contract. A contract that requires sensitive raw data for interpretation is
invalid.

## 13. Deferred implementation decisions

This decision intentionally does not choose:

- exact Pydantic class names or Python file/module names;
- workspace directory names, paths, locks, cleanup, or retention;
- report persistence backend or indexing;
- concrete retry scheduler/executor behavior;
- transport diagnostic storage;
- the internal serializer implementation beyond its required canonical
  behavior.

Those choices must implement this contract rather than redefine it.

## 14. Corrected contradictions

The final decision corrects two earlier prototype candidates:

1. A Run does **not** begin only when execution begins. It exists before the
   Plan and covers the full invocation. Blocked and no-op Plans therefore have
   terminal Run Reports.
2. A Resource failure does **not** invariably stop the whole Run. The immutable
   Plan selects `continue_safe_independent` or `fail_fast`. Safe continuation
   is allowed only after the failed Resource reaches a known final state;
   unknown or unsafe state always escalates to Run stop.
