# CoreELEC Device Configuration

This context describes the desired configuration of the repository's CoreELEC/Kodi device fleet and the process of reconciling devices with that configuration.

## Language

**Device**:
A CoreELEC/Kodi installation managed by this repository.
_Avoid_: Target, host, node

**Manageable Device**:
A Device that has completed unavoidable local bootstrap and is network-reachable with administrator SSH access.
_Avoid_: First-boot Device, prepared host

**Profile**:
A versioned declaration of desired state for a class of Devices sharing relevant platform and deployment characteristics.
_Avoid_: Baseline, manifest

**Desired State**:
The state a Profile declares that a Device must have.
_Avoid_: Target values, expected configuration

**Intent**:
A stable, device-independent expression of Desired State that may be resolved to a device-specific representation using observed capabilities.
_Avoid_: Raw setting value

**Resource**:
An independently observable and reconcilable unit of managed Device state.
_Avoid_: Component, task, step

**Resource Type**:
A category of Resources that share observation, planning, application, and verification semantics.
_Avoid_: Action type, handler

**State Address**:
The unique location or identity of a piece of Device state owned by one Resource.
_Avoid_: Key, path

**Managed State**:
Device state whose State Address is owned by a Resource in the resolved Profile.
_Avoid_: Known state

**Unmanaged State**:
Device state that no Resource in the resolved Profile owns and that reconciliation therefore preserves or ignores.
_Avoid_: Drift, absent state

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

**Run Infrastructure**:
Operational state used to coordinate, audit, recover, or finalize a Run without representing Device Desired State.
_Avoid_: Resource, managed Device state

**Verification**:
An independent comparison of a Resource's new Observation with its Desired State after Changes have been applied.
_Avoid_: Command success, post-check

**Health Check**:
An observation of whether a configured Resource or its external dependency is currently usable, without determining whether Device state has converged.
_Avoid_: Verification, drift check

**Convergence**:
The condition in which Verification finds that a Resource's Observation matches its Desired State.
_Avoid_: Successful command, completed deployment

**Guided Action**:
An operator-assisted operation that cannot be expressed as verifiable Desired State, such as interactive account linking.
_Avoid_: Resource, manual Resource

**Reconciler**:
The system that observes Resources, plans Changes, applies them, and independently verifies the resulting state.
_Avoid_: Provisioner, desired configuration management engine

**Component**:
A user-facing group used to select related Resources for a Run; it is not a unit of reconciliation.
_Avoid_: Resource

**Artifact**:
Versioned content referenced by a Profile and installed or used while reconciling a Resource.
_Avoid_: Download, payload

**Smart Playlist**:
A Kodi-defined saved query whose typed rules, ordering, and result limit select media for playback or navigation.
_Avoid_: Widget, static playlist
