# Ugoos AM6B+ Network Keep-Alive and Kodi Lifecycle Design

## Purpose

Keep every managed Ugoos AM6B+ running CoreELEC 21.3 reachable on the
network regardless of the power state of its attached Sony display, AVR, or
other HDMI equipment. Stop Kodi while the display is off by default, start
Kodi when the display becomes active, and power off an idle display after a
configurable inactivity timeout without suspending or shutting down
CoreELEC.

This design replaces HDMI-CEC-driven host power management with a
Home Assistant-controlled Kodi lifecycle. CoreELEC and wired Ethernet remain
fully awake. Host reachability and Kodi availability are separate states.

## Context and Decision

Kodi 21 defaults **When the TV is switched off** to **Suspend**. Kodi handles
a TV-originated CEC standby event by applying that setting, which explains
the observed AM6B+ loss of network connectivity shortly after the Sony turns
off.

CoreELEC runs Kodi as `kodi.service`, independently from networking and
`sshd.service`. Stopping Kodi with systemd leaves CoreELEC, wired Ethernet,
and SSH available. Conversely, suspend and power-off wake depend on
device-specific Amlogic bootloader and wake support that has not been
validated on these AM6B+ devices.

The system will therefore:

- set Kodi's CEC TV-off action to **Ignore**;
- keep CoreELEC and wired Ethernet awake continuously;
- enable stopping Kodi while the display is off on every managed Ugoos by
  default;
- let an individual device explicitly opt out of stopping Kodi;
- use the paired Sony Bravia entity in Home Assistant as the display power
  authority;
- use Kodi's own input-idle condition as the source of inactivity evidence;
- use Home Assistant as the only policy and cross-device action owner; and
- keep suspend, shutdown, CEC wake, and Wake-on-LAN outside normal operation.

## Scope

### Included

- Shared Kodi CEC safety configuration.
- A restricted SSH command gateway for Kodi start, stop, and status.
- Transactional deployment and verification of that gateway.
- Versioned Home Assistant packages for manual deployment.
- Sony-off-driven Kodi lifecycle control.
- Kodi-idle-driven Sony power-off.
- Per-device policy configuration and a persistent operational override.
- Monitoring, failure reporting, reconciliation, tests, and rollout
  documentation.

### Excluded

- Suspending or shutting down CoreELEC during normal operation.
- Wake-on-LAN as a production availability mechanism.
- A Bluetooth remote lifecycle monitor.
- Generic support for non-Sony displays.
- Automatic deployment into the Home Assistant host.
- Automatic pfSense configuration.
- Rebooting or power-cycling a Ugoos as failure remediation.

## System Ownership

### CoreELEC

CoreELEC owns the actual Kodi process state through `kodi.service`. It exposes
only three lifecycle operations to Home Assistant through a forced-command
SSH key. CoreELEC never interprets Sony state and never suspends itself in
response to this feature.

### Kodi

Kodi owns its input-idle measurement. Home Assistant queries Kodi's supported
`XBMC.GetInfoBooleans` JSON-RPC method with
`System.IdleTime(<configured-seconds>)`.

Kodi does not own the idle action. Its native shutdown timer is not used:
Kodi's `Quit` action exits the application, but CoreELEC configures
`kodi.service` with `Restart=always`, so systemd would start Kodi again.

### Home Assistant

Home Assistant is the sole desired-state and cross-device action owner. It:

- observes the paired Sony Bravia and Kodi entities;
- obtains Kodi input-idle evidence;
- powers off an idle Sony;
- computes whether Kodi should be running;
- issues restricted, idempotent lifecycle commands; and
- reports health and failures.

Home Assistant does not suspend, shut down, reboot, or power-cycle CoreELEC.

## Configuration Model

### Shared defaults

| Setting | Default |
|---|---|
| Kodi CEC action when TV switches off | Ignore |
| Stop Kodi while display is off | Enabled |
| Confirmed Sony-off interval | 60 seconds |
| Idle-driven Sony power-off | Enabled |
| Kodi idle timeout | 30 minutes |
| Kodi idle probe cadence | 15 seconds |
| Sony power-off confirmation timeout | 30 seconds |
| Restricted SSH command timeout | 15 seconds |
| Kodi JSON-RPC readiness timeout after start | 90 seconds |
| Keep Kodi running | Off |

Stopping Kodi while the display is off is enabled for every managed Ugoos.
An individual device must explicitly set its stop policy to disabled to opt
out. The default is not limited to newly provisioned devices.

### Per-device values

Each Home Assistant package defines:

- Sony Bravia media-player entity ID;
- Kodi media-player entity ID;
- Ugoos hostname or reserved IPv4 address;
- Home Assistant SSH identity reference;
- explicit stop-policy opt-out, when required;
- idle timeout override, when required; and
- namespaced helper, sensor, script, and automation identifiers.

The first concrete package targets the theater Sony/Ugoos pair. Additional
managed Ugoos devices use the same package contract with their own values.

## State Model

### Inputs

Each device pair has two policy inputs:

1. `stop_when_display_off`, a static per-device setting that defaults to
   enabled.
2. **Keep Kodi running**, a persistent per-device Home Assistant helper that
   defaults to off.

The helper is an operational override. Its value survives Home Assistant
restart until an operator changes it.

### Desired Kodi state

Conditions are evaluated in this precedence order:

| Priority | Condition | Desired Kodi state |
|---|---|---|
| 1 | Stop policy disabled | Running |
| 2 | Keep Kodi running enabled | Running |
| 3 | Sony is `off` continuously for 60 seconds | Stopped |
| 4 | Sony is any definite non-off state | Running |
| 5 | Sony is `unknown` or `unavailable` | Running |

Any definite non-off Sony state, including on, idle, playing, or paused,
requires Kodi to run. Kodi starts without an additional debounce.

A pending 60-second stop interval is canceled immediately if:

- the Sony leaves `off`;
- the stop policy becomes disabled; or
- **Keep Kodi running** becomes enabled.

Display-off wins over Kodi playback state unless **Keep Kodi running** is
enabled or the stop policy is disabled. There is no playback drain, prompt,
or delayed stop.

### Idempotent operations

Home Assistant issues state-setting commands, never a toggle:

- `start` means `systemctl start kodi.service` when Kodi is not active;
- `stop` means `systemctl stop kodi.service` when Kodi is active; and
- `status` reports the current lifecycle state.

Repeated events that request the current state have no effect.

### Restart reconciliation

A Ugoos reboot starts Kodi normally. Home Assistant may stop it only after a
new, continuous 60-second observation of a definitely off Sony. It does not
trust an off interval from before either system restarted.

When Home Assistant starts or reloads the package:

- a definite non-off, `unknown`, or `unavailable` Sony state requests Kodi
  start; and
- a definitely off Sony begins a new 60-second stop interval.

This deliberately fails awake. Missing state cannot strand Kodi in an
intentionally stopped state.

## Idle Policy

### Idle definition

The device pair is idle only when both conditions hold for the configured
timeout:

1. The Home Assistant Kodi entity has continuously remained `idle`, meaning
   there is no active player.
2. Kodi reports `System.IdleTime(<timeout-seconds>) = true`, meaning there has
   been no Kodi input during the same threshold.

Both conditions are necessary. The Kodi entity alone would classify active
menu navigation as idle. Kodi's input timer alone can continue while media is
playing.

Playing and paused media inhibit idle power-off. This matches Kodi's native
power-saving behavior. The timeout begins again after Kodi returns to
`idle`.

### Idle evidence transport

While Kodi is reachable, Home Assistant calls:

```text
XBMC.GetInfoBooleans
  booleans:
    - System.IdleTime(<configured-seconds>)
```

The Home Assistant Kodi integration emits a `kodi_call_method_result` event
containing the structured result. The package consumes only events matching:

- the configured Kodi entity;
- `XBMC.GetInfoBooleans`; and
- the exact idle condition generated for that device.

The package polls every 15 seconds by default. Idle evidence expires after
two missed polling intervals. An unavailable Kodi instance, failed call, or
stale result cannot prove idle.

### Idle action

When idle is proven, Home Assistant requests `media_player.turn_off` for the
paired Sony once per idle episode. It does not stop Kodi directly.

After the Sony reports `off`, the ordinary 60-second display-off path stops
Kodi. This keeps one Kodi state machine and gives every stop the same
confirmation behavior.

The **Keep Kodi running** helper and the static stop-policy opt-out do not
suppress idle-driven Sony power-off. They suppress only the later Kodi stop.

If Sony power-off fails or the Sony does not become off within the bounded
confirmation period, Home Assistant reports the failure and leaves Kodi
running. It does not retry indefinitely.

## CoreELEC Restricted SSH Gateway

### Separate controller identity

The Home Assistant controller key is separate from the administrator key
used by provisioning. The private key:

- is generated and stored outside this repository;
- is installed on Home Assistant by an operator;
- is never copied to the Ugoos;
- is never placed in environment reports, logs, or command lines; and
- grants no general-purpose shell access.

### Target-side wrapper

The lifecycle workflow installs a root-owned executable at:

```text
/storage/.config/kodi-lifecycle
```

The wrapper reads the forced SSH original command and accepts exactly one of:

| Command | Result |
|---|---|
| `start` | Start `kodi.service` if it is not active |
| `stop` | Stop `kodi.service` if it is active |
| `status` | Print one machine-readable lifecycle state |

The status output is exactly one of:

- `running`
- `stopped`
- `failed`

The wrapper maps only systemd `active` to `running`, `inactive` to `stopped`,
and `failed` to `failed`. Transitional, missing, or unrecognized systemd
states produce no lifecycle state on stdout, print a diagnostic to stderr,
and exit nonzero.

Unsupported, empty, compound, or extra-argument commands print a diagnostic
to stderr and exit nonzero. The wrapper invokes fixed `systemctl` arguments.
It does not use `eval`, caller-supplied unit names, or success-shaped
fallbacks.

### Authorized key restrictions

The Home Assistant public key receives a uniquely marked
`authorized_keys` entry with a forced command and OpenSSH restrictions
equivalent to:

```text
restrict,command="/storage/.config/kodi-lifecycle" <public-key>
```

The deployment workflow verifies that the installed OpenSSH supports
`restrict`. If it does not, the workflow uses explicit restrictions that
disable:

- agent forwarding;
- port forwarding;
- X11 forwarding;
- PTY allocation; and
- user RC execution.

The key cannot obtain an interactive shell or transfer files.

### Network policy

pfSense permits TCP/22 from the actual Home Assistant host address on IoT
only to the reserved addresses of managed Ugoos devices. This rule is
separate from administrator SSH access and from the directed-broadcast WoL
path.

## Deployment Architecture

### Shared provisioning

The shared CoreELEC provisioner sets and verifies the Kodi CEC peripheral
setting **When the TV is switched off** to **Ignore**. Kodi is stopped while
its peripheral XML is edited so Kodi cannot overwrite the change on exit.
The setting participates in the existing backup, rollback, audit, and
idempotency guarantees.

Sony **Device auto power off** remains disabled. Home Assistant, not Sony CEC
power propagation, owns the lifecycle policy.

### Lifecycle deployment command

A focused repository command and library configure one CoreELEC target. They
remain separate from add-on provisioning and post-deployment add-on
workflows.

The command:

1. validates the Home Assistant public key locally;
2. checks target platform and CoreELEC release compatibility;
3. backs up every target file it may replace;
4. stages the wrapper and authorized-key candidate with restrictive modes;
5. atomically installs both;
6. verifies `status`, idempotent `start`, and idempotent `stop` through the
   restricted key;
7. returns Kodi to the state observed before verification;
8. commits the transaction only after successful verification; and
9. rolls back all changed files on failure.

Rerunning replaces only the uniquely marked lifecycle key entry and does not
modify administrator or unrelated authorized keys.

### Home Assistant packages

The repository contains versioned Home Assistant package templates and
per-device examples for manual deployment. A package contains:

- the persistent **Keep Kodi running** helper;
- idle evidence and freshness state;
- host, lifecycle, desired-state, and error sensors;
- restricted SSH start, stop, and status commands;
- the serialized Kodi state reconciler;
- the Kodi idle probe;
- the Sony idle-power automation; and
- persistent failure notifications.

Home Assistant installation remains an operator action. The repository
documents file placement, private-key installation, package inclusion,
configuration validation, reload/restart, and acceptance tests.

## Home Assistant Control Flow

### Idle probe

- Poll only while Kodi is reachable.
- Use a bounded 15-second default cadence.
- Ignore unrelated or mismatched `kodi_call_method_result` events.
- Invalidate evidence after two missed intervals.
- Do not preserve a stale `true` across Kodi or Home Assistant restart.

### Sony idle-power automation

- Require continuous Kodi `idle` state and fresh positive input-idle
  evidence for the configured timeout.
- Issue Sony power-off once per idle episode.
- Wait up to 30 seconds for Sony-off confirmation.
- On failure, notify and leave Kodi running.

### Kodi desired-state reconciler

- Serialize operations per device.
- Query `status` before changing state.
- Run only the required explicit `start` or `stop`.
- Query `status` afterward.
- For start, require both lifecycle `running` and Kodi JSON-RPC availability
  within 90 seconds.
- For stop, require lifecycle `stopped`; the Kodi entity becoming
  unavailable is expected.

Each restricted SSH invocation has a 15-second deadline. The reconciler does
not loop or retry indefinitely. A later relevant state change or operator
retry initiates a new bounded reconciliation.

### Health and observability

Each package exposes:

- Ugoos host reachability;
- actual Kodi lifecycle state;
- desired Kodi state;
- Kodi JSON-RPC availability;
- idle evidence and freshness;
- last successful lifecycle command;
- last successful reconciliation time; and
- last lifecycle or idle-power error.

Home Assistant creates a persistent notification for:

- restricted SSH authentication or command failure;
- malformed or unexpected lifecycle status;
- `kodi.service` entering `failed`;
- Kodi start or JSON-RPC readiness timeout;
- Sony power-off failure;
- stale/malformed idle probe results; or
- package/entity configuration mismatch.

An error clears only after a later verified successful operation of the same
class. Automatic remediation never reboots, suspends, power-cycles, or sends
WoL to the Ugoos.

## Error Handling and Safety

- Unknown and unavailable Sony state require Kodi to run.
- Missing or stale Kodi idle evidence never powers off the Sony.
- Failure to power off the Sony leaves Kodi running.
- Failure to stop Kodi leaves the host running and raises an alert.
- Failure to start Kodi leaves CoreELEC reachable for SSH diagnosis and
  raises an alert.
- Concurrent events are serialized per device and resolve through desired
  state, not event order.
- Every command is idempotent and verified.
- Credentials and private keys are never committed or included in audit
  output.
- CEC never initiates CoreELEC suspend or shutdown.
- WoL remains an independently tested emergency experiment, not a dependency
  or automatic fallback.

## Repository Changes

Implementation will:

- extend `provision-coreelec.sh` and its focused helpers/tests for the shared
  CEC Ignore setting;
- add a focused lifecycle deployment command, library, and shell tests;
- add versioned Home Assistant package templates and a theater package;
- add lifecycle deployment and Home Assistant operations documentation;
- update the shared Ugoos guide, Sony guide, theater record, network/firewall
  guide, runbook, and configuration documentation; and
- revise baseline acceptance wording so suspend/WoL is optional experimental
  testing rather than a requirement for the always-awake design.

No general-purpose Home Assistant deployment framework, MQTT agent, HTTP
daemon, Bluetooth monitor, or pfSense configurator will be introduced.

## Validation

### Local automated tests

Use the repository's existing shell test style and tools. Tests cover:

- shared and per-device default/override parsing;
- CEC peripheral XML update, verification, idempotency, and rollback;
- Home Assistant public-key validation;
- exact forced-command authorization output;
- rejection of empty, unknown, compound, and extra-argument commands;
- wrapper start, stop, and status behavior with stubbed `systemctl`;
- lifecycle status normalization to `running`, `stopped`, or `failed`;
- backup, atomic install, rerun, marked-key replacement, and rollback;
- preservation of unrelated authorized keys;
- restoration of Kodi's pre-verification state;
- redaction of private/key material from logs and reports;
- Home Assistant package fixtures for precedence, idle evidence freshness,
  event matching, serialization, and error paths; and
- shell syntax checks.

Use an existing Home Assistant configuration validator only if one is
already available in the repository or deployment environment. Do not add a
new validation tool solely for this feature.

### Device and Home Assistant acceptance

The theater pilot must demonstrate:

1. Turning the Sony off no longer removes Ugoos ping or SSH reachability.
2. The Ugoos remains network-reachable through repeated off/on cycles and a
   continuous 24-hour Sony-off interval.
3. Sony off stops Kodi only after a fresh 60-second off interval.
4. Sony definite non-off starts Kodi and restores JSON-RPC and the UI.
5. Sony `unknown` or `unavailable` starts or preserves Kodi.
6. Thirty minutes of genuine Kodi inactivity powers off the Sony and then
   stops Kodi through the normal 60-second path.
7. Active menu input resets the input-idle condition.
8. Playing and paused media inhibit idle power-off.
9. **Keep Kodi running** allows idle-driven Sony power-off but leaves Kodi
   running.
10. A per-device stop-policy opt-out leaves Kodi running while preserving
    idle-driven Sony power-off.
11. Home Assistant restart, Ugoos reboot, restricted-command failure, and
    network partition follow the fail-awake and notification rules.
12. Repeated idle, off, on, and restart cycles do not create Sony/Kodi CEC
    power loops.
13. The restricted SSH key cannot execute a shell, transfer files, allocate a
    PTY, forward connections, or control any non-Kodi service.

### Rollout

Deploy first to the theater Sony/Ugoos pair. Observe it for at least 24 hours
and complete repeated manual off/on, natural idle, override, restart, and
failure-injection cycles.

After the theater acceptance record passes, apply the enabled-by-default
stop policy to every other managed Ugoos. Each device retains an explicit
per-device opt-out.

## Primary References

- Kodi Omega CEC peripheral settings:
  <https://github.com/xbmc/xbmc/blob/Omega/system/peripherals.xml>
- Kodi Omega CEC standby implementation:
  <https://github.com/xbmc/xbmc/blob/Omega/xbmc/peripherals/devices/PeripheralCecAdapter.cpp>
- Kodi Omega power-management settings:
  <https://github.com/xbmc/xbmc/blob/Omega/system/settings/settings.xml>
- Kodi Omega idle implementation:
  <https://github.com/xbmc/xbmc/blob/Omega/xbmc/application/ApplicationPowerHandling.cpp>
- Kodi Omega JSON-RPC methods:
  <https://github.com/xbmc/xbmc/blob/Omega/xbmc/interfaces/json-rpc/schema/methods.json>
- CoreELEC 21 Kodi systemd unit:
  <https://github.com/CoreELEC/CoreELEC/blob/coreelec-21/packages/mediacenter/kodi/system.d/kodi.service>
- CoreELEC 21 SSH systemd unit:
  <https://github.com/CoreELEC/CoreELEC/blob/coreelec-21/packages/network/openssh/system.d/sshd.service>
- CoreELEC 21 Ethernet wake rule:
  <https://github.com/CoreELEC/CoreELEC/blob/coreelec-21/packages/network/ethtool/udev.d/99-wakeup-eth.rules>
- Home Assistant Kodi integration:
  <https://www.home-assistant.io/integrations/kodi/>
- Home Assistant Sony Bravia integration:
  <https://www.home-assistant.io/integrations/braviatv/>
- AM6B+ CEC power-state report:
  <https://discourse.coreelec.org/t/am6b-cec-tv-off-action-not-respected/53780>
- AM6B+ BL301 injection report:
  <https://discourse.coreelec.org/t/guide-s922x-j-ugoos-am6b-coreelec-ng-installation-and-faqs/51231/588>
