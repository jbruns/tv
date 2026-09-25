# CoreELEC Device Configuration

This context describes the desired configuration of the repository's CoreELEC/Kodi device fleet and the process of reconciling devices with that configuration.

## Language

A term is the Reconciler's unless a `_Realised by_` line names another engine.

**Device**:
A CoreELEC/Kodi installation managed by this repository.
_Avoid_: Target, host, node

**Manageable Device**:
A Device that has completed unavoidable local bootstrap and is network-reachable over SSH.
_Avoid_: First-boot Device, prepared host

**First Contact**:
The one Run that reaches a Manageable Device using the credentials its first-boot wizard left, establishes the administrator key, and proves key-only access. A Device needs it once.
_Avoid_: Bootstrap, onboarding, enrolment

**Profile**:
A versioned declaration of desired state for a class of Devices sharing relevant platform and deployment characteristics.
_Avoid_: Baseline, manifest

**Room Overlay**:
The small set of Desired State values that tailor a Profile to the room a Device is installed in. An overlay value either overrides the Profile's value for a State Address or adds one the Profile does not declare; room values are evaluated last and win.
_Avoid_: Device profile, local override

**Desired State**:
The state a Profile declares that a Device must have.
_Avoid_: Target values, expected configuration

**Named Value**:
A Desired State value that Desired State names rather than holds, resolved from the shared `.env` file on every read. It reaches the Device and nothing else: no committed file carries it, and no Run prints it.
_Avoid_: Secret, credential, variable

**Profile Constant**:
A value a Profile states once and more than one State Address takes, so the Device cannot hold two records of one fact that disagree.
_Avoid_: Named Value, variable, default

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

**Cleared Address**:
A State Address that exists and from which the Device resolves no value.
_Avoid_: Empty setting, null value
_Realised by_: Settings Document. Declared `unset`, applied as an empty node.

**Unmanaged State**:
Device state that no Resource in the resolved Profile owns and that reconciliation therefore preserves or ignores.
_Avoid_: Drift, absent state

**Contested Address**:
A State Address another engine rewrites on its own schedule, so no Resource can hold a value there. Contested Addresses are left as Unmanaged State. A Run may fire a Rebuild Trigger there.
_Avoid_: Volatile setting, drift, race

**Rebuild Trigger**:
A write that makes another engine regenerate an artifact it compiles, and that the engine undoes by regenerating. A Run fires one without owning the address it writes.
_Avoid_: Cache bust, force rebuild, arm

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

**Artifact**:
Versioned content referenced by a Profile and installed or used while reconciling a Resource.
_Avoid_: Download, payload

**Artifact Lock**:
The record of which Artifact version a Profile installs, and of the exact bytes that version is: enough for anyone, or anything, to fetch it again and know it is unchanged.
_Avoid_: Pin list, manifest, catalogue

**Artifact Patch**:
A targeted correction a Profile applies to an Artifact it does not publish, carrying its own assertion of the Artifact version it was written against.
_Avoid_: Fix, override, transform

**Release Channel**:
A publisher's list of the add-on versions it offers for one Kodi version, and where an add-on's Stable Releases are found.
_Avoid_: Index, feed, repository

**Stable Release**:
An add-on version its Release Channel offers that is not marked as a prerelease.
_Avoid_: Latest version, newest release

**Update Proposal**:
A reviewed request to move an add-on's Artifact Lock pin to a newer Stable Release, carrying a verdict on each Artifact Patch it touches. It is never accepted by the thing that raised it.
_Avoid_: Bump, upgrade PR, auto-update

**Carried Patch**:
An Artifact Patch that still applies to the proposed version unchanged.
_Avoid_: Rebased patch

**Obsolete Patch**:
An Artifact Patch whose corrected text the proposed version already contains. That is evidence upstream fixed the fault, not proof, so a reviewer confirms it before the patch is dropped.
_Avoid_: Upstreamed patch, redundant patch

**Stale Patch**:
An Artifact Patch that neither applies to the proposed version nor is already contained in it, so it must be rewritten before the Update Proposal can be accepted.
_Avoid_: Broken patch, conflicting patch

**Smart Playlist**:
A Kodi-defined saved query whose typed rules, ordering, and result limit select media for playback or navigation.
_Avoid_: Widget, static playlist

**Shortcut Node**:
An entry in a skin's menu or widget list naming what to open: a Smart Playlist, a window, or a built-in command. Shortcut Nodes nest.
_Avoid_: Widget, menu item, tile

**Display**:
The screen in a Device's room that the Device's video reaches.
_Avoid_: TV, Sony, screen

**Kodi Lifecycle**:
Starting and stopping Kodi on a running Device so that Kodi runs while its Display is on and is stopped once the Display has been off for a while. It is a runtime behaviour, not Desired State, and the Reconciler plays no part in it.
_Avoid_: Desired Kodi state, reconciliation, power management
_Realised by_: Home Assistant.

**Keep-Running Hold**:
An operator's standing instruction that Kodi keep running on a Device whatever its Display does, until the operator lifts it.
_Avoid_: Override, keep-alive, maintenance mode

**Viewing**:
The condition in which a Device's Display is on and selected to that Device's input. A Display that is on but showing another input or its own apps is not Viewing.
_Avoid_: Display on, watching, active

**Idle Power-Off**:
Turning a Display off after its Device has been idle for the room's idle timeout while Viewing.
_Avoid_: Sleep timer, auto-off, standby

**Wife Acceptance Factor**:
The project's quality bar: the Device just works, the configuration stays easy to maintain, and any Device is easy to snap to its Desired State.
_Avoid_: Reliability, production readiness
