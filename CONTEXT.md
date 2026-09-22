# CoreELEC Device Configuration

This context describes the desired configuration of the repository's CoreELEC/Kodi device fleet and the process of reconciling devices with that configuration.

## Language

A term is the Reconciler's unless a `_Realised by_` line names another engine.
A term realised by the Recovery Baseline describes what the shell provisioner
does and is not a Reconciler capability.

**Device**:
A CoreELEC/Kodi installation managed by this repository.
_Avoid_: Target, host, node

**Manageable Device**:
A Device that has completed unavoidable local bootstrap and is network-reachable with administrator SSH access.
_Avoid_: First-boot Device, prepared host

**Profile**:
A versioned declaration of desired state for a class of Devices sharing relevant platform and deployment characteristics.
_Avoid_: Baseline, manifest

**Room Overlay**:
The small set of Desired State values that tailor a Profile to the room a Device is installed in. An overlay value either overrides the Profile's value for a State Address or adds one the Profile does not declare; room values are evaluated last and win.
_Avoid_: Device profile, local override

**Desired State**:
The state a Profile declares that a Device must have.
_Avoid_: Target values, expected configuration

**Recovery Baseline**:
The shell-declared configuration that restores a Device to a working state, deliberately allowed to lag current Desired State.
_Avoid_: Desired State, fallback profile

**Intent**:
A stable, device-independent expression of Desired State that may be resolved to a device-specific representation using observed capabilities.
_Avoid_: Raw setting value

**Named Value**:
A Desired State value that Desired State names rather than holds, resolved from the shared `.env` file on every read. It reaches the Device and nothing else: no committed file carries it, and no Run prints it.
_Avoid_: Secret, credential, variable

**Resource**:
An independently observable and reconcilable unit of managed Device state.
_Avoid_: Component, task, step

**Resource Type**:
A category of Resources that share observation, planning, application, and verification semantics.
_Avoid_: Action type, handler

**State Address**:
The unique location or identity of a piece of Device state owned by one Resource.
_Avoid_: Key, path

**Settings Document**:
A Device document that holds many State Addresses, each owned independently, rather than one a Resource owns whole.
_Avoid_: Config file, settings file

**Managed State**:
Device state whose State Address is owned by a Resource in the resolved Profile.
_Avoid_: Known state

**Managed Absence**:
A State Address whose Desired State is that it does not exist.
_Avoid_: Deletion, cleanup
_Realised by_: Recovery Baseline. The Reconciler declares no Managed Absence.

**Cleared Address**:
A State Address that exists and from which the Device resolves no value.
_Avoid_: Managed Absence, empty setting, null value
_Realised by_: Settings Document. Declared `unset`, applied as an empty node.

**Unmanaged State**:
Device state that no Resource in the resolved Profile owns and that reconciliation therefore preserves or ignores.
_Avoid_: Drift, absent state

**Contested Address**:
A State Address another engine rewrites on its own schedule, so no Resource can hold a value there. Contested Addresses are left as Unmanaged State.
_Avoid_: Volatile setting, drift, race

**Observation**:
The measured state of a Resource on a Device at a point in time.
_Avoid_: Current state, probe result

**Guard**:
An observed prerequisite that must hold before the Reconciler may safely mutate a Device.
_Avoid_: Resource, warning

**Change**:
A difference between a Resource's Observation and its desired state that can be applied to the Device.
_Avoid_: Drift item, mutation

**Effect**:
A disruptive consequence required by one or more Changes, such as restarting Kodi, reloading a service, or rebooting a Device.
_Avoid_: Change, cleanup step

**Plan**:
The ordered set of Changes required to reconcile selected Resources on a Device.
_Avoid_: Effective component plan, action list

**Run**:
One attempt to observe, plan, apply, or verify selected Resources for one Device.
_Avoid_: Transaction, deployment

**Verification**:
An independent comparison of a Resource's new Observation with its Desired State after Changes have been applied.
_Avoid_: Command success, post-check

**Convergence**:
The condition in which Verification finds that a Resource's Observation matches its Desired State.
_Avoid_: Successful command, completed deployment

**Fail Forward**:
The failure semantic in which an interrupted Run stops and reports what changed, and a repeated Run is the means of reaching Convergence.
_Avoid_: Rollback, retry

**Guided Action**:
An operator-assisted operation that cannot be expressed as verifiable Desired State, such as interactive account linking.
_Avoid_: Resource, manual Resource

**Reconciler**:
The system that observes Resources, plans Changes, applies them, and independently verifies the resulting state.
_Avoid_: Provisioner, desired configuration management engine

**Component**:
A user-facing group used to select related Resources for a Run; it is not a unit of reconciliation.
_Avoid_: Resource
_Realised by_: Recovery Baseline. The Reconciler has no Component selector.

**Artifact**:
Versioned content referenced by a Profile and installed or used while reconciling a Resource.
_Avoid_: Download, payload

**Smart Playlist**:
A Kodi-defined saved query whose typed rules, ordering, and result limit select media for playback or navigation.
_Avoid_: Widget, static playlist

**Shortcut Node**:
An entry in a skin's menu or widget list naming what to open: a Smart Playlist, a window, or a built-in command. Shortcut Nodes nest.
_Avoid_: Widget, menu item, tile

**Pilot Phase**:
The period in which exactly one disposable Device is managed, ending when a factory-fresh Device can be provisioned from a Profile alone.
_Avoid_: Beta, rollout

**Wife Acceptance Factor**:
The project's quality bar: the Device just works, the configuration stays easy to maintain, and any Device is easy to snap to its Desired State.
_Avoid_: Reliability, production readiness
