# Component-scoped CoreELEC provisioning design

## Context

`provision-coreelec.sh` currently treats every Kodi deployment as a full
shared-baseline transaction. Even `--addon ID` rewrites shared Kodi, service,
CEC, and Arctic Fuse state and verifies all of those surfaces before commit.

That behavior is safe for initial provisioning but unsafe for narrow
maintenance. A CEC-only change was applied and verified correctly, then rolled
back because Arctic Fuse recreated unrelated runtime defaults while the
transaction was verifying the full skin baseline. Waiting for skin convergence
did not solve the ownership problem: unrelated skin state should not decide the
fate of a CEC-only transaction.

The provisioner needs explicit component ownership so narrow maintenance can
retain the existing backup, rollback, reporting, and verification guarantees
without mutating or judging unrelated state.

## Goals

- Add explicit, composable provisioning components.
- Preserve the current full-baseline behavior when no component is selected.
- Preserve the current behavior of legacy `--addon ID` invocations.
- Resolve component dependencies deterministically and report the expanded
  plan.
- Mutate, back up, verify, and report only the effective component scope.
- Keep one transaction engine rather than creating domain-specific scripts.
- Provide a component boundary for future room-specific Kodi desired state.

## Non-goals

- Populate the future `room` component in this change.
- Change the locked add-on set or add-on dependency resolution.
- Weaken full-baseline Arctic Fuse verification.
- Copy Kodi or add-on database rows.
- Coordinate Home Assistant maintenance mode automatically.
- Change Sony or Denon configuration.

## CLI contract

Add a repeatable option:

```text
--component NAME
```

Initial component names:

| Component | Owned state |
|---|---|
| `core` | Regional and timezone state, Kodi web access, update policy, and shared Kodi defaults |
| `cec` | Kodi CEC peripheral power-isolation settings |
| `addons` | Locked add-on artifacts selected by the manifest and optional `--addon` filters |
| `services` | TMDb Helper, Weather, NextPVR, and PM4K-owned settings |
| `skin` | Arctic Fuse settings, widget JSON, playlists, and active-skin state |
| `room` | Reserved for reviewed room-specific playback and library state |
| `baseline` | Alias for every implemented component except reserved `room` |

No `--component` option preserves the current full-baseline behavior.

Existing `--addon ID` behavior remains unchanged when no component is
explicitly selected: it applies the full shared settings baseline and filters
only the artifact deployment set.

With explicit components, each `--addon ID` implicitly requests `addons`.
Unknown component names, an empty effective plan, and contradictory options
fail before any device contact. `--no-kodi` is incompatible with Kodi-owned
components.

## Component graph

Dependencies are expanded automatically:

```text
services -> addons
skin     -> addons, core
room     -> core
```

`core`, `cec`, and `addons` have no component dependencies.

Dependency expansion must be deterministic, cycle-checked, and visible in the
report. It does not resolve dependencies between individual Kodi add-ons; the
existing artifact-lock rules remain authoritative.

## Transaction flow

1. Parse and validate requested components before network access.
2. Expand dependencies into a stable effective component order.
3. Render a scoped settings payload containing explicit component flags.
4. Select add-on artifacts only when `addons` is effective.
5. Build a mutation plan from effective component ownership.
6. Back up each path the plan may mutate.
7. Stop Kodi once for the combined plan.
8. Apply only effective component transformations and artifact replacements.
9. Restart Kodi.
10. Collect device observations.
11. Compare only platform/transaction invariants and effective component
    expectations.
12. Retry complete verification samples for up to 60 seconds when selected
    runtime state can converge asynchronously.
13. Commit only after one complete passing sample; otherwise roll back.

An empty add-on artifact manifest is valid when no effective component owns
artifacts.

## Component ownership

### Core

The `core` transformer owns:

- locale, timezone, and keyboard settings;
- timezone cache and `/etc/localtime`;
- Kodi web server credentials and transport settings;
- shared update policy;
- shared non-room Kodi defaults.

### CEC

The `cec` transformer owns exactly one detected CEC peripheral file and these
settings:

```text
activate_source=0
wake_devices=231
standby_devices=231
standby_tv_on_pc_standby=0
standby_pc_on_tv_standby=36028
```

CEC remains enabled for navigation. Kodi startup and shutdown must not power
the television on or off, and television standby must not stop the always-awake
CoreELEC host.

A `--component cec` run must not mutate or verify `guisettings.xml`, service
settings, Arctic Fuse state, playlists, widget nodes, or add-on directories.

### Add-ons

The `addons` component owns only staged locked artifacts and their installed
add-on directories. `--addon ID` filters the selected artifact set exactly as
it does today.

### Services

The `services` component owns settings under:

- `plugin.video.themoviedb.helper`;
- `weather.ha`;
- `pvr.nextpvr`;
- `script.plexmod`.

It depends on `addons` so a fresh target can receive the corresponding locked
code before settings are verified.

### Skin

The `skin` component owns:

- active Arctic Fuse skin selection;
- Arctic Fuse settings XML;
- Skin Variables widget JSON;
- managed video playlists;
- skin-specific shared Kodi defaults.

It depends on `addons` and `core`. Full semantic skin verification remains
strict. Runtime-created inert defaults may be accepted only when they cannot
enable or redirect a managed surface.

### Room

`room` is reserved but initially has no mutations. A request for an
unimplemented component fails rather than succeeding as a no-op. A later
approved design will assign theater playback, whitelist, audio, library, hub,
and view-state ownership.

## Verification and reports

Every report adds strict key-value fields:

```text
components.requested=<ordered comma-separated names>
components.effective=<ordered comma-separated names>
components.dependencies_added=<ordered comma-separated names or none>
```

Each effective component emits a component verdict. Unselected component
verdicts are omitted rather than reported as successful or unchanged.

Platform identity, transaction identity, rollback capability, and observation
format remain mandatory for every transaction.

For `--component cec`, verification requires all five CEC values and does not
read or judge Arctic Fuse. For a default full-baseline run, all current strict
checks remain mandatory.

No report may contain secrets, controller key material, dynamic CEC adapter
filenames, or managed file contents.

## Failure behavior

Fail before mutation on:

- unknown or unimplemented components;
- dependency cycles;
- an empty effective plan;
- incompatible CLI options;
- an unlocked requested add-on;
- malformed scoped payloads;
- missing component-required source files.

Roll back after mutation on:

- any selected component mismatch;
- an unanswered selected-component probe;
- incomplete selected-component application;
- persistent non-convergence at the verification deadline.

Never fall back silently to `baseline`.

## Testing

### CLI and graph

- Default invocation expands to the existing full baseline.
- Repeated components are deduplicated in stable order.
- `baseline` expands correctly.
- Dependencies expand and are reported.
- Unknown, unimplemented, cyclic, empty, and conflicting plans fail before
  device contact.
- Legacy `--addon` behavior remains unchanged.
- Explicit `--component cec --addon script.plexmod` expands to `cec,addons`.

### Transformation isolation

- `cec` changes only the CEC peripheral file.
- Unselected `guisettings.xml`, service settings, Arctic Fuse XML/JSON,
  playlists, and add-on directories remain byte-identical.
- Combined components apply each owned mutation once.
- A second scoped transform is byte-identical.

### Transaction and rollback

- A non-add-on component accepts an empty artifact manifest.
- Scoped backup contains every selected mutable path.
- Scoped rollback restores the CEC file exactly.
- Unselected paths are not rollback prerequisites.

### Verification

- CEC-only verification ignores deliberately broken Arctic Fuse observations.
- Full-baseline verification still rejects those observations.
- Every incorrect or missing CEC value fails.
- A transient selected-component mismatch can converge before commit.
- A persistent selected-component mismatch rolls back.

### Reports and secrecy

- Requested, effective, and dependency-added fields are deterministic.
- Only selected component verdicts appear.
- Existing redaction and strict key-value tests continue to pass.

### Regression

Run the existing config, settings, artifacts, report, add-on workflow,
lifecycle, and Home Assistant package suites.

## Live rollout

1. Keep `input_boolean.ugoos_theater_keep_kodi_running` enabled during
   maintenance.
2. Run:

   ```bash
   ./provision-coreelec.sh --target ugoos-theater --component cec --yes
   ```

3. Require `deployment_state=committed`, `verification_result=pass`, and all
   five CEC comparisons `ok`.
4. Install the corrected Home Assistant lifecycle package, run
   `ha core check`, and restart Home Assistant Core.
5. Disable the maintenance override.
6. Power the Sony off manually and confirm Kodi stops after 60 seconds and
   remains stopped across later status polls.
7. Start Kodi while the Sony remains off and confirm the television does not
   wake.
8. Reboot Ugoos while the Sony remains off and confirm CoreELEC, network, and
   Home Assistant recover without waking the television.
9. Turn the Sony on manually and confirm Kodi reconciliation and CEC
   navigation still work.

## Follow-up boundaries

The following remain separate subprojects:

- add-on onboarding and restart sequencing;
- room-specific Kodi desired state;
- Home Assistant Weather startup resilience;
- 4K remux buffering analysis and tuning.
