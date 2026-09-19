---
status: accepted
---

# Declare domain Resources instead of imperative actions

Profiles will declare Desired State as domain Resources and Artifact references, never generic SSH commands, JSON-RPC calls, XML edits, or an imperative action DSL. Built-in Resource Types own observation, normalization, planning, application, verification, rollback, and Effect semantics through typed transport interfaces. This keeps configuration reviewable as Intent and prevents the current implementation complexity from moving out of shell and into YAML.
