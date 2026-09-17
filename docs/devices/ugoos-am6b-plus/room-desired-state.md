# Room desired state on the Ugoos AM6B+

This is the reference for the `room` provisioning component: the display and
audio state that lives in `guisettings.xml` and depends on which room the
device is physically installed in. It governs what `config/rooms/<room>/room.conf`
means and what an operator should expect from a `--component room` run. The
evidence and design rationale behind this contract are recorded in the
[room-specific desired state design](../../superpowers/specs/2026-09-17-room-desired-state-design.md).

## What `room` manages, and what it deliberately does not

`room` owns exactly eleven Kodi settings: the desktop resolution, the display
mode whitelist, both Dolby Vision settings, the six audio passthrough flags,
and the decoded-audio channel layout. It writes only `guisettings.xml`, and
only the room-scoped identifiers below.

It does not manage:

- **`advancedsettings.xml`.** The 4K remux buffering work tracked as #9 owns
  that file exclusively; `room` never touches it.
- **The ALSA audio device strings** (`audiooutput.audiodevice` and
  `audiooutput.passthroughdevice`). These are treated as a per-model
  baseline shared across every AM6B+ unit, not room state. They are managed
  by the `core` component instead; see [managed audio output](audio-output.md)
  for how they are resolved.
- Anything about the Sony or the Denon. `room` configures the CoreELEC
  playback host only.
- Hostname, DHCP reservation, DNS, or CEC policy. Those belong to the network
  onboarding guide, the first-boot wizard, and the already-implemented `cec`
  component, respectively.

`room` is opt-in. It is never expanded from `baseline`, and it is never
applied implicitly by a bare `--target` run. It must be requested explicitly
with `--component room --room NAME`. Requesting `--component room` without
`--room` fails before the device is contacted; supplying `--room` without also
requesting the `room` component fails the same way, rather than being silently
ignored, so an operator is never told a run succeeded when it did nothing.
`room` also declares a dependency on `core`, so `--component room` always
brings `core` along as an added dependency: the whitelist Kodi writes only
takes effect once `core`'s `videoplayer.adjustrefreshrate=2` is in place, and
applying room state without it would write settings that are inert.

## The configuration surface

A new file per room, selected by `--room NAME`:

```text
config/rooms/<room>/room.conf
```

It uses the same strict, line-by-line, allowlist-dispatched grammar as
`config/shared/.../provision.conf`, with its own separate key allowlist — a
`provision.conf` key in a room file, or a room key in `provision.conf`, is
rejected by name. No secret may appear in either file. `NAME` is validated more
strictly than the general identifier rule used elsewhere in this repository:
it may contain only letters, digits, underscore, and hyphen, may not start
with a hyphen, and may not be empty, `.`, or `..`, because it becomes a single
path segment under `config/rooms/`.

Every key below is **required**. A room file missing any one of them is
rejected outright; there is no default for a display or audio setting,
because a silent default is exactly the unverifiable state this component
exists to eliminate.

| Key | Kodi setting | Accepted values | Meaning |
| --- | --- | --- | --- |
| `ROOM_DISPLAY_RESOLUTION` | `videoscreen.resolution` | a resolution label such as `3840x2160p` | The GUI desktop resolution, stated as the label the display reports, not Kodi's internal index. |
| `ROOM_DISPLAY_WHITELIST` | `videoscreen.whitelist` | a comma-separated list of Kodi display mode strings | Every mode the display is allowed to switch to for content playback. |
| `ROOM_DOLBY_VISION` | `coreelec.amlogic.disabledolbyvision` | `0` or `1` | Whether Dolby Vision is enabled, stated positively. `1` means Dolby Vision **on**. |
| `ROOM_DOLBY_VISION_MODE` | `coreelec.amlogic.dolbyvisionled` | `tv-led` or `player-led` | Which device negotiates the Dolby Vision mode with the display. |
| `ROOM_AUDIO_PASSTHROUGH` | `audiooutput.passthrough` | `0` or `1` | Master switch for HDMI audio passthrough. |
| `ROOM_AUDIO_AC3` | `audiooutput.ac3passthrough` | `0` or `1` | Dolby Digital (AC-3) passthrough. |
| `ROOM_AUDIO_EAC3` | `audiooutput.eac3passthrough` | `0` or `1` | Dolby Digital Plus (E-AC-3) passthrough. |
| `ROOM_AUDIO_DTS` | `audiooutput.dtspassthrough` | `0` or `1` | DTS passthrough. |
| `ROOM_AUDIO_TRUEHD` | `audiooutput.truehdpassthrough` | `0` or `1` | Dolby TrueHD passthrough. |
| `ROOM_AUDIO_DTSHD` | `audiooutput.dtshdpassthrough` | `0` or `1` | DTS-HD passthrough. |
| `ROOM_AUDIO_CHANNELS` | `audiooutput.channels` | a layout label, e.g. `7.1` | The decoded (non-bitstreamed) audio channel layout, stated as a label rather than Kodi's internal enum ordinal. See [managed audio output](audio-output.md) for how the label is resolved and why it does not affect passthrough. |

**There is no Atmos setting.** Kodi exposes five audio passthrough flags, and
none of them is Atmos. Atmos rides inside TrueHD (Blu-ray) and E-AC-3
(streaming), so it is enabled by `ROOM_AUDIO_TRUEHD` and `ROOM_AUDIO_EAC3`. An
operator looking for a `ROOM_AUDIO_ATMOS` key will not find one; there is
nothing to add.

### `ROOM_DOLBY_VISION` is inverted on write

This is the single most error-prone thing in this contract: the configuration
key states the desired outcome positively, but Kodi's own setting is a
negative. `ROOM_DOLBY_VISION=1` (Dolby Vision **enabled**) writes
`coreelec.amlogic.disabledolbyvision=false`. `ROOM_DOLBY_VISION=0` (Dolby
Vision **disabled**) writes `coreelec.amlogic.disabledolbyvision=true`. Read
`ROOM_DOLBY_VISION` as "is Dolby Vision on", never as "is Dolby Vision
disabled".

### The display mode string format

Each entry in `ROOM_DISPLAY_WHITELIST` is a Kodi display mode string in a
fixed, undelimited layout: five digits of width, five digits of height, three
digits of integer refresh rate, a literal `.`, five decimal digits, a scan
letter (`p` or `i`), then the literal `std`.

```text
0384002160060.00000pstd
│└──┘│└──┘│└┘ │└──┘│└─┘
│3840 2160 060 00000 p  std
width height refresh decimals scan  suffix
```

That example is `3840x2160`, `60` Hz integer part, `.00000` fractional part,
progressive scan: `3840x2160p 60.00Hz`. Get the exact strings for a display
from a live capture of the device's own reported `videoscreen.whitelist`
options — do not hand-type them from a spec sheet, because Kodi's EDID-derived
values (for example `59.94006` for `59.94Hz`) do not round the way a display's
marketing numbers do.

## Resolution is a label, not Kodi's index

`videoscreen.resolution` is a Kodi-internal integer enum whose meaning is
derived from the device's own reported mode table. The same physical mode can
be index `41` on one Kodi release or display and something else after a
CoreELEC upgrade or a display swap, so pinning a raw index in configuration
would pin a number that can silently come to mean a different resolution.
`ROOM_DISPLAY_RESOLUTION` therefore holds the label (`3840x2160p`), and the
device resolves that label to the index that matters for this run in a
pre-transaction probe, described next.

This is not a theoretical concern. During the first two provisioning runs
against the theater, minutes apart on one unchanged CoreELEC release and one
unchanged display, `3840x2160p` resolved to index `41` and then to index `40`.
A configuration pinning the raw index would have been wrong by the second run.
Resolving the label on every run is what makes the setting stable.

## The pre-transaction display probe

Immediately after the administrator key is installed, and immediately before
the pre-provisioning backup is created — while Kodi is still running and still
answering JSON-RPC — the provisioner issues one `Settings.GetSettings` call
against the running Kodi and:

1. Resolves `ROOM_DISPLAY_RESOLUTION` against the resolution options Kodi
   currently reports, yielding the index that will actually be written. A
   label the display does not currently offer aborts the run.
2. Asserts that every mode in `ROOM_DISPLAY_WHITELIST` still appears among the
   whitelist options Kodi currently reports. Any missing mode aborts the run,
   naming the modes.

**This is the operating requirement an operator must know before starting a
room run: the display must be powered on and switched to this device's HDMI
input.** If it is not, the probe fails and the run aborts with nothing changed
on the device except the (idempotent, independently reversible) administrator
key — no backup taken, no settings written, nothing to roll back. This is
deliberately better than discovering the same problem after mutation: a run
against a powered-off or wrong-input display fails before touching the device,
naming the modes the display is not currently reporting.

## The four report statuses

Verification emits `room.display.whitelist.status`, `room.display.resolution.status`,
`room.dolbyvision.status`, one status per audio codec
(`room.audio.{passthrough,ac3,eac3,dts,truehd,dtshd}.status`), and
`room.audio.channels.status`. Each takes one of four values, and **only `ok`
passes** — every other value counts as a verification failure and blocks the
transaction from being committed.

| Status | Meaning | Operator action |
| --- | --- | --- |
| `ok` | The desired value was written and Kodi reports it back unchanged. | None. |
| `mismatch` | Kodi reports a value that differs from what was written. | Investigate; something (another process, a manual UI edit) changed the setting after the transaction wrote it. |
| `unsupported` | Applies only to `room.display.whitelist`: Kodi answered, but reported an empty whitelist. | Confirm the display is still powered on and on the correct input, and re-run. |
| `unobservable` | Kodi never answered for that setting at all, or (for `room.display.resolution` specifically) no resolution index was ever resolved for this run. | Confirm Kodi is reachable over JSON-RPC on the device and re-run. |

`room.display.resolution` is reported `unobservable` whenever
`ROOM_DISPLAY_RESOLUTION_INDEX` was never resolved for that run, because
verification cannot re-probe the already-running Kodi to invent a value to
compare against after the fact; comparing an observed numeric index to the
configured label would either always fail or require guessing the mapping a
second time, so the honest report is `unobservable` rather than a
guessed-at pass or fail.

## Requesting the component

```bash
./provision-coreelec.sh --target ugoos-theater --component room --room theater
```

Because `room` depends on `core`, the effective component plan for this
invocation is `core,room`, not `room` alone; inspect it without contacting the
device with:

```bash
./provision-coreelec.sh --component room --room theater --print-component-plan
```
