# Managed audio output on the Ugoos AM6B+

This is the reference for the three Kodi audio output settings the
provisioner brings under management: the output device, the passthrough
device, and the decoded-audio channel layout. It exists so that drift in any
of the three is **reported**, not silently absorbed. Two of the three are
`core` state, treated as a shared per-model baseline across every AM6B+ unit;
the third is `room` state, because it depends on the room's AVR. See the
[room desired-state reference](room-desired-state.md) for the other room
settings and how they are requested.

## What is managed

| Kodi setting | Component | Configuration key | File |
| --- | --- | --- | --- |
| `audiooutput.audiodevice` | `core` | `AUDIO_DEVICE` | `config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf` |
| `audiooutput.passthroughdevice` | `core` | `AUDIO_PASSTHROUGH_DEVICE` | `config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf` |
| `audiooutput.channels` | `room` | `ROOM_AUDIO_CHANNELS` | `config/rooms/<room>/room.conf` |

## Why configuration states intent, not the concrete value

Configuration never holds the literal Kodi values for these three settings.
It holds a symbolic intent (`hdmi-multichannel`, `hdmi`, `7.1`), and a
pre-transaction probe resolves that intent against whatever the running Kodi
actually offers, on every run.

The concrete values are not stable facts safe to hard-code:

- `audiooutput.audiodevice` and `audiooutput.passthroughdevice` are ALSA
  device strings that embed the kernel sound-card name, e.g.
  `ALSA:surround71:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND`. `AMLAUGESOUND` is
  a driver detail, not a hardware fact worth pinning in configuration that
  ships to every room.
- `audiooutput.channels` is resolved fresh every run too, but not because its
  value moves. Kodi registers no options-filler for it: its options are a
  static table in Kodi's own `system/settings/settings.xml`, where `10` is
  `AE_CH_LAYOUT_7_1`, so matching the label `7.1` against that table always
  yields `10` on this Kodi. The shell resolves it only because it shares the
  probe with the two device strings above. The display resolution index,
  which was observed moving from `41` to `40` on unchanged hardware, is a
  different case: Kodi recomputes that ordinal from the live display mode at
  every startup
  ([ADR 0019](../../adr/0019-the-profiles-scope-resolves-what-the-shell-probed.md)).

## The intent vocabulary

`AUDIO_DEVICE` and `AUDIO_PASSTHROUGH_DEVICE` share one vocabulary of output
intents, validated in `lib/coreelec-config.sh`. The probe maps each intent to
the ALSA selector token it must match in the option Kodi reports:

| Intent | ALSA selector token |
| --- | --- |
| `analog` | `@` |
| `sysdefault` | `sysdefault` |
| `hdmi-multichannel` | `surround71` |
| `spdif` | `iec958` |
| `hdmi` | `hdmi` |

`ROOM_AUDIO_CHANNELS` uses a separate vocabulary of speaker-layout labels,
also validated in `lib/coreelec-config.sh`, matched directly against the
option labels `audiooutput.channels` reports:

| Layout |
| --- |
| `2.0` |
| `2.1` |
| `3.0` |
| `3.1` |
| `4.0` |
| `4.1` |
| `5.0` |
| `5.1` |
| `7.0` |
| `7.1` |

The theater's current values: `AUDIO_DEVICE=hdmi-multichannel`,
`AUDIO_PASSTHROUGH_DEVICE=hdmi`, `ROOM_AUDIO_CHANNELS=7.1`.

## Why a missing output is a failure, not a fallback

The probe fails closed. If the requested intent is not among the options the
running Kodi offers for that setting, the run aborts and the failure message
names every option Kodi actually reports for that setting, so the operator
can see the real option list rather than guess at it.

The value of managing these settings at all is detecting drift. A scheme that
silently substituted a different, "close enough" output when the requested
one disappeared would be indistinguishable from not noticing the problem —
which is exactly the failure this feature exists to prevent. So there is no
fallback path: an unresolvable intent is always a hard stop.

The probe runs immediately after the administrator key is installed and
before the pre-provisioning backup is created — before the transaction opens.
A probe failure therefore aborts with nothing on the device to undo, the same
timing the room display probe uses.

## Which settings are baseline and which are room state

`AUDIO_DEVICE` and `AUDIO_PASSTHROUGH_DEVICE` are `core` (shared baseline)
state: the output intent they resolve is a per-model baseline, treated as
shared across every AM6B+ unit regardless of which room it sits in. It does
not depend on the room's AVR, unlike the speaker layout below, which is why
it is `core` rather than `room` scope.

`ROOM_AUDIO_CHANNELS` is `room` state: the correct speaker layout depends on
the connected AVR, which differs by room. It is a **required** key in every
`room.conf` — a room file that omits it fails to parse, because a silent
default for this setting is exactly the unverifiable state room management
exists to eliminate.

`audiooutput.channels` governs only audio Kodi decodes itself (PCM). It has
no effect on bitstreamed passthrough formats (AC-3, E-AC-3, DTS, TrueHD,
DTS-HD, and anything Atmos rides inside), which are controlled by the
`ROOM_AUDIO_*` passthrough flags documented in the room desired-state
reference and are unaffected by the channel layout.

On the theater device before this feature, `audiooutput.channels` had been
left at Kodi's own default of `1` (2.0 stereo) while `audiooutput.audiodevice`
was already set to the `surround71` (7.1) ALSA device. Decoded, non-bitstreamed
audio was therefore being downmixed to stereo even though the output path was
wired for 7.1. Bringing `audiooutput.channels` under management as `7.1`
corrects that mismatch.

## Troubleshooting

Verification reports one status per managed setting: `audio.device.status`,
`audio.passthroughdevice.status`, and `room.audio.channels.status`. Each is
one of:

| Status | Meaning | Operator action |
| --- | --- | --- |
| `ok` | The resolved value was written and Kodi reports it back unchanged. | None. |
| `mismatch` | Kodi reports a value different from what was resolved and written. | Investigate; something changed the setting after the transaction wrote it. |
| `unobservable` | A verification failure (it increments the failure count, same as `mismatch`), emitted in either of two cases: (1) Kodi's report never included this setting at all, so `observed` is empty; or (2) the setting's intent was configured but no concrete value was resolved for this run, so `expected` shows the configured intent as written (e.g. `hdmi-multichannel` or `7.1`) rather than the resolved concrete value — `observed` may still show a real value read from the device in this case. If the owning component was not requested at all, no keys are emitted for the setting and `unobservable` never appears; absence of the key is a different condition from a status of `unobservable`. | Check whether `expected` is a concrete resolved value or a configured intent: if it is an intent, resolve the missing concrete value for that intent (case 2). If `expected` is already resolved and `observed` is empty, investigate why Kodi's JSON-RPC report omitted the setting (case 1). |

If the probe itself fails before the transaction opens, the failure message
names the setting and lists every output (or channel layout) Kodi actually
offers for it, so the fix is to reconcile the requested intent with that
list — never to silently accept whatever Kodi offered instead.
