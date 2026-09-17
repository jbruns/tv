# Room-Specific Desired State Design

## Status

Approved for implementation planning. Every setting identifier, value form, and
capability claim below was captured read-only from the live `ugoos-theater`
device on 2026-09-16. The raw capture is retained outside the repository as
session evidence (`ws7-evidence/settings-expert.json`,
`ws7-evidence/guisettings-video-audio.xml`).

## Context

`provision-coreelec.sh` already recognizes a `room` component
(`coreelec_component_known`, `:3432`), declares its dependency on `core`
(`:3448`), and lists it in the canonical component order (`:3527`) — but
`coreelec_component_implemented` (`:3437`) deliberately rejects it, and the
usage text calls the name "reserved". The reservation exists because the room's
desired state had never been written down as a contract: it lives only as prose
in `rooms/theater/devices/ugoos-am6b-plus.md`, where an operator applies it by
hand through the Kodi UI.

That prose state is unverifiable. Nothing detects when a hand-applied value
drifts, and nothing detects when a CoreELEC upgrade changes a default the room
silently depends on. The live capture shows both failure modes are real and one
is already active:

- `videoscreen.resolution`, `videoscreen.whitelist`, and five
  `audiooutput.*` flags carry no `default="true"` attribute — they were set by
  hand and are unmanaged.
- `coreelec.amlogic.dolbyvisionled` (`0` = TV-Led) and
  `coreelec.amlogic.disabledolbyvision` (`false`) *do* carry
  `default="true"`. The theater's two documented Dolby Vision requirements are
  satisfied only because CoreELEC's current defaults happen to agree with them.
  A release that changes either default would break the room with nothing
  reporting it.

This design defines a small, fail-closed `room` contract covering display and
audio desired state, and the verification that proves it.

## Goals

- Define a strict, declarative room configuration surface, separate from the
  shared baseline that `config/README.md` forbids room values from entering.
- Implement the reserved `room` component end to end: mutation, backup,
  verification, and reporting, all scoped to room settings only.
- Pin the Dolby Vision settings that currently match by accident, so agreement
  becomes an assertion rather than a coincidence.
- Express the display-dependent whitelist as a literal value, and assert before
  the device is modified that the display still reports every pinned mode, so
  EDID drift aborts cleanly instead of producing a confusing mismatch.
- Prove byte isolation between `room` and every other component by test.

## Non-goals

- `advancedsettings.xml`. The 4K remux buffering work (#9) owns that file
  exclusively. This design touches only `guisettings.xml`, so the coordination
  flag raised on both issues is resolved: the two workstreams write disjoint
  files and need no byte-isolation negotiation.
- Shared Kodi library behavior, season/episode views, and Arctic Fuse hub
  navigation. Those are #4.
- `audiooutput.audiodevice` and `audiooutput.passthroughdevice`. Both are
  hand-set and unmanaged, but their values (`AML-AUGESOUND`) are AM6B+ hardware
  facts identical in every room, so they are not room state. Tracked as a
  follow-up.
- Hostname, DHCP reservation, and DNS. Those are pfSense and first-boot wizard
  concerns, outside provisioning.
- CEC policy, which is already its own implemented component.
- Sony and Denon configuration. `room` configures the CoreELEC playback host
  only.

## Evidence

Captured from `ugoos-theater` on 2026-09-16, read-only, with the Sony powered
on and selected to HDMI IN 4.

### The whitelist is a scalar on disk

This was the design's principal risk. Kodi's JSON-RPC types
`videoscreen.whitelist` as `list`, which would have implied a repeating XML
element that the existing transformer cannot express. On disk it is a single
comma-separated string:

```xml
<setting id="videoscreen.whitelist">0409602160024.00000pstd,0409602160023.97602pstd,...</setting>
```

`set_kodi_setting` (`provision-coreelec.sh:502`) writes scalar element text and
therefore handles it unchanged. No transformer extension is required.

### Reported modes

The device reports ten 2160p modes, and the live whitelist contains exactly
those ten — confirming the documented intent, "enable all 2160p modes actually
reported by the Sony", is currently satisfied:

| Mode string | Label |
|---|---|
| `0409602160024.00000pstd` | 4096x2160p 24.00Hz |
| `0409602160023.97602pstd` | 4096x2160p 23.98Hz |
| `0384002160060.00000pstd` | 3840x2160p 60.00Hz |
| `0384002160059.94006pstd` | 3840x2160p 59.94Hz |
| `0384002160050.00000pstd` | 3840x2160p 50.00Hz |
| `0384002160030.00000pstd` | 3840x2160p 30.00Hz |
| `0384002160029.97003pstd` | 3840x2160p 29.97Hz |
| `0384002160025.00000pstd` | 3840x2160p 25.00Hz |
| `0384002160024.00000pstd` | 3840x2160p 24.00Hz |
| `0384002160023.97602pstd` | 3840x2160p 23.98Hz |

`/sys/class/amhdmitx/amhdmitx0/disp_cap` agrees and marks `2160p60hz*` active.
`dv_cap` confirms the Sony advertises Dolby Vision (`VSVDB Version: V2`,
`DV_RGB_444_8BIT`, `LL_YCbCr_422_12BIT`).

### There is no Atmos setting

The theater doc lists six codecs including "Dolby Atmos", but Kodi exposes five
passthrough flags and none of them is Atmos. Atmos is carried inside TrueHD
(Blu-ray) and E-AC-3 (streaming), so it is enabled by
`audiooutput.truehdpassthrough` and `audiooutput.eac3passthrough`. The contract
document must state this, so that no future change adds a phantom
`ROOM_AUDIO_ATMOS` key that could never be verified.

### Dolby Vision mode semantics

`coreelec.amlogic.dolbyvisionled` is an integer with exactly two options:
`0` = TV-Led, `1` = Player-Led. The theater requires TV-Led.

`videoplayer.allowedhdrformats` and `videoplayer.convertdovi` exist on disk but
do not appear in the device's expert-level setting list, indicating they are
not applicable on this AMLogic platform, where Dolby Vision is handled by the
`coreelec.amlogic.*` layer. They are therefore out of scope.

## The room contract

### Configuration surface

A new file per room, selected by an explicit flag:

```text
config/rooms/<room>/room.conf
```

It is parsed by the same strict, line-by-line, allowlist-dispatched grammar as
`provision.conf`: never `eval`, never `source`, never indirect expansion, so
shell metacharacters in a value stay inert data. It has its own key allowlist;
a `provision.conf` key appearing in `room.conf` is rejected naming the key, and
the reverse holds too. No secret may appear in either.

The room is selected with `--room NAME`. `NAME` is used as a single path
segment, so it is validated more strictly than the repository's general
identifier rule: `validate_identifier` permits `.`, which would accept `..` and
allow directory traversal. Room names must additionally be rejected when they
are `.` or `..`, or when they contain `/`. This is called out because the
existing validator looks sufficient at a glance and is not.

Selection is fail-closed in both directions:

- `--component room` without `--room` is an error. There is no default room
  and no inference from the target hostname: `ugoos-theater` resolving to
  `theater` is a naming coincidence, and a wrong guess writes one room's
  display settings onto another room's device.
- `--room` without the room component in effective scope is also an error,
  rather than being silently ignored, so an operator who expected room state to
  be applied is never told the run succeeded when it did nothing.

### Keys

| Key | Kodi setting | Value form | Theater value |
|---|---|---|---|
| `ROOM_DISPLAY_RESOLUTION` | `videoscreen.resolution` | resolution label | `3840x2160p` |
| `ROOM_DISPLAY_WHITELIST` | `videoscreen.whitelist` | comma-separated mode strings | the ten modes above |
| `ROOM_DOLBY_VISION` | `coreelec.amlogic.disabledolbyvision` | `0`/`1` | `1` |
| `ROOM_DOLBY_VISION_MODE` | `coreelec.amlogic.dolbyvisionled` | `tv-led`/`player-led` | `tv-led` |
| `ROOM_AUDIO_PASSTHROUGH` | `audiooutput.passthrough` | `0`/`1` | `1` |
| `ROOM_AUDIO_AC3` | `audiooutput.ac3passthrough` | `0`/`1` | `1` |
| `ROOM_AUDIO_EAC3` | `audiooutput.eac3passthrough` | `0`/`1` | `1` |
| `ROOM_AUDIO_DTS` | `audiooutput.dtspassthrough` | `0`/`1` | `1` |
| `ROOM_AUDIO_TRUEHD` | `audiooutput.truehdpassthrough` | `0`/`1` | `1` |
| `ROOM_AUDIO_DTSHD` | `audiooutput.dtshdpassthrough` | `0`/`1` | `1` |

Every key is required. A room file missing a key is rejected rather than
defaulted, because a silent default for a display or audio setting is exactly
the unverifiable state this component exists to eliminate.

`ROOM_DOLBY_VISION` is inverted on write: `ROOM_DOLBY_VISION=1` writes
`coreelec.amlogic.disabledolbyvision=false`. The configuration key states the
desired outcome positively; the Kodi setting happens to be expressed as a
negative.

### Two value forms that are deliberately not the raw Kodi value

**Resolution is a label, not an index.** On the live device
`videoscreen.resolution` is `41`. That integer is a Kodi-internal enum whose
meaning is derived from the device's own reported mode table — the same run
reports `3840x2160p` as `41` and `4096x2160p` as `38`, and nothing guarantees
those indices are stable across Kodi releases or displays. Pinning `41` in
configuration would therefore pin a number that can silently come to mean a
different resolution. The configuration holds the label, and the device
resolves label to index in the pre-transaction probe described below. A label
with no matching reported option aborts the run, rather than being guessed.

`videoscreen.screenmode` is not an escape from this. It holds a mode string in
the whitelist's vocabulary and would be offline-writable, but on this platform
it is `DESKTOP` and defers to `videoscreen.resolution`, so it cannot express
the desired resolution on its own.

**Dolby Vision mode is a name, not `0`/`1`.** Same reasoning at smaller scale,
plus readability: `ROOM_DOLBY_VISION_MODE=tv-led` states the intent that
`0` obscures.

Resolution labels as reported by the device carry a trailing space
(`'3840x2160p '`, `'4096x2160p '`). Label matching must normalize surrounding
whitespace on both sides rather than comparing raw strings; the configuration
value is written without the trailing space.

## Pre-transaction display probe

Mutation writes `guisettings.xml` with Kodi stopped, and the existing verify
probe runs only after the transaction restarts it. There is therefore no point
in the current flow at which the device can resolve a resolution label into
Kodi's index before that index must be written. `room` adds one probe that runs
**before the transaction stops Kodi**, while JSON-RPC is still answering.

The probe issues a single `Settings.GetSettings` call and does two things:

1. Resolves `ROOM_DISPLAY_RESOLUTION` against the reported
   `videoscreen.resolution` options, yielding the index to write. An
   unmatched label aborts the run.
2. Asserts every mode in `ROOM_DISPLAY_WHITELIST` appears in the reported
   `videoscreen.whitelist` options. Any missing mode aborts the run, naming
   the modes.

Both are aborts in the preflight sense: they happen before the backup is taken
and before anything on the device is modified, in the same spirit as
`coreelec_validate_addon_selection` (`:3853`), which refuses an unknown
`--addon` before the run has changed the device at all.

This placement is deliberate and is better than asserting display support after
mutation. A run against a powered-off display fails before touching the device,
with a message naming the modes the display is not reporting, instead of
applying state and then reporting a failure the operator must interpret.

The probe reuses the existing verify-request and remote-probe transport rather
than introducing a second way to talk to Kodi. It runs only when `room` is in
effective scope.

The resolved index travels to the transformer in the settings payload as
`ROOM_DISPLAY_RESOLUTION_INDEX`. The transformer never resolves labels itself;
it writes the index it was given, so it remains a pure offline file
transformation that the existing `--transform-fixture` tests can drive.

## Mutation and transaction

Room adds `ROOM_SETTING_IDS` and an `apply_room` branch to the existing
transformer, reusing `set_kodi_setting` and `write_xml_atomic` unchanged.

`room` defines no new restart contract. `guisettings.xml` is Class K under the
file-ownership classification established by the add-on onboarding and restart
contract: Kodi rewrites it from memory at both shutdown and startup, so it may
only be written while Kodi is stopped. The existing deployment transaction
already stops Kodi before applying settings (`:1509`) and performs one
unconditional stop/start per transaction. `room` inherits that behavior and
adds nothing to it.

The declared `room` → `core` dependency (`:3448`) is semantically correct and
retained: the whitelist only takes effect when core's
`videoplayer.adjustrefreshrate=2` is in place, so applying room state without
core would produce settings that are written but inert.

### Byte isolation

`room`'s setting identifiers are disjoint from every other component's:

- `CORE_SETTING_IDS` — `locale.*`; core additionally writes
  `videoplayer.adjustrefreshrate` and `videoplayer.usedisplayasclock`, which
  are `videoplayer.*`, not `videoscreen.*` or `audiooutput.*`
- `SKIN_SETTING_IDS` — `lookandfeel.skin`
- `SERVICE_SETTING_IDS` — `weather.addon`

Disjointness is asserted by test rather than left to review, because the sets
live in different parts of a 5,400-line script and a future overlap would
manifest as two components silently overwriting each other inside one
transaction.

`guisettings.xml` is already listed in the backup path set (`:1068`), so the
existing transaction provides room's rollback material with no change. The
backup is credential-bearing and is already handled as such (`:1137`, `:1169`).

## Verification and reporting

### Setting comparison

`ROOM_SETTING_IDS` is added to the verify probe's per-component selection
(`:2815-2819`), and each setting is compared expected-against-observed in the
established `coreelec_report_comparison` style under an
`if coreelec_component_effective room` guard, emitting `room.*` keys.

### Whitelist support assertion

The pre-transaction probe already refuses to run when the display does not
report a pinned mode, so the common case never reaches verification. The report
still carries the verdict, because the display can change between the probe and
the post-transaction verification, and because the report is the artifact an
operator reads afterwards. The probe therefore also reads `definition.options`
for `videoscreen.whitelist` from the `Settings.GetSettings` response it already
fetches, and checks that every pinned mode appears in the reported set.

`room.display.whitelist.status` takes one of four values:

| Value | Meaning |
|---|---|
| `ok` | desired value written, and every pinned mode is reported by the display |
| `mismatch` | the written value differs from the desired value |
| `unsupported` | the written value is correct, but the display no longer reports some pinned mode |
| `unobservable` | the reported option list could not be read at all |

`unsupported` names the offending modes in
`room.display.whitelist.unsupported`. Only `ok` passes; `unobservable` is a
failure, because unproven is not proven.

`room.display.resolution.status` uses the same vocabulary, where `unsupported`
means the configured label matches no reported option.

### The powered-off display case

A run performed with the Sony powered off, or switched to another input, cannot
prove the display delivers the pinned modes: EDID falls back to a degraded mode
list that omits the 2160p modes. The pre-transaction probe catches this and
aborts before the backup is taken, naming the missing modes, so the device is
left untouched and the operator is told exactly what to fix.

If a display is powered off *after* that probe and before verification, the
post-transaction report records `unsupported` instead. The desired state is
still correctly written — writing XML does not depend on the display — and a
later verification with the display on will pass.

The operations runbook must state that room runs are performed with the display
powered on and on the correct input. The operations runbook must state that room runs are verified with
the display powered on and on the correct input.

## Plumbing

Every site below currently enumerates exactly five implemented components as a
fail-closed gate. Each must learn about `room`; missing any one of them would
let a room run report success without applying or proving anything.

| Site | Change |
|---|---|
| `coreelec_component_implemented` `:3437` | accept `room` |
| usage text `:80`, `:158` | document `--room`; drop "reserved and rejected" and the "does not configure audio codecs or the display mode whitelist" disclaimer |
| deployment plan validator `:1392-1457` | `seen_room`, repeat detection, missing-component check, dependency check |
| payload component list `:1719` | room key |
| `canonical_components` `:2802` | add `room` |
| transformer `:654-700` | `apply_room` branch and `ROOM_SETTING_IDS` |
| report scope `:4409-4470` | `room.*` block and scope flags |
| backup scope `:4906` | room in the component scope string |
| CLI parser `:3684` | `--room NAME` |
| preflight `:3853` region | pre-transaction display probe, gated on room in effective scope |

Line numbers are from the tree at the time of writing and are navigational
hints only; implementation locates each site by content.

## Testing

| Suite | Coverage |
|---|---|
| `test-coreelec-config.sh` | `ROOM_*` grammar: every key required, value-form validation, rejection of secrets and of `provision.conf` keys, `--room` name validation including `.`, `..`, and `/` |
| `test-coreelec-settings.sh` | transform fixture writes exactly the room settings and no others; `ROOM_SETTING_IDS` disjoint from core/skin/service; the transformer writes the supplied `ROOM_DISPLAY_RESOLUTION_INDEX` without resolving labels itself |
| `test-coreelec-report.sh` | all four `room.display.whitelist.status` values; `unsupported` names the missing modes; room verdicts absent when room is not in effective scope; the pre-transaction probe resolves a label to an index, aborts on an unmatched label, and aborts naming the modes a degraded display fails to report |
| `test-coreelec-artifacts.sh` | deployment plan accepts room, rejects a repeated room key, rejects a missing one |

Fail-closed selection is tested at both gates: `--component room` without
`--room`, and `--room` without the room component.

## Documentation

- New `docs/devices/ugoos-am6b-plus/room-desired-state.md`: the key reference,
  the value forms and why they are not raw Kodi values, the pre-transaction
  probe and what aborts a run, the four whitelist verdicts, the Atmos note, and
  the powered-off-display case.
- `rooms/theater/devices/ugoos-am6b-plus.md`: stop listing display and audio
  values as prose; point at `config/rooms/theater/room.conf` as the source of
  truth and at the contract doc for meaning. Hostname, network, and CEC prose
  stays, since none of it is room component state.
- `docs/operations/provision-ugoos.md`: how to run a room-scoped
  provision, and the requirement that the display be powered on and on the
  correct input for verification to pass.
- `config/README.md`: describe the room configuration surface and its boundary
  with the shared baseline, which currently only says room values must stay
  out.

## Follow-ups

- `audiooutput.audiodevice` and `audiooutput.passthroughdevice` are hand-set
  and unmanaged by any component. They are AM6B+ hardware facts rather than
  room state, so they belong to a shared component, not this one.
