---
status: accepted
---

# The Profile's scope resolves what the shell probed

Four State Addresses were deferred as Intents: `audiooutput.audiodevice`,
`audiooutput.passthroughdevice`, `audiooutput.channels`, and
`videoscreen.resolution`. The shell resolves all four by starting a probe
against a **running** Kodi over JSON-RPC, reading the options Kodi offers for
each setting, and matching a stable label to whatever opaque value that
Device happens to expose
([`provision-coreelec.sh:3768`](https://github.com/jbruns/tv/blob/d604fe6e2d0e7eb910d7f82fcd3e355ce361dded/provision-coreelec.sh#L3768),
[`:3928-3945`](https://github.com/jbruns/tv/blob/d604fe6e2d0e7eb910d7f82fcd3e355ce361dded/provision-coreelec.sh#L3928-L3945)).

The Reconciler will not do this. It never probes a running Kodi. Three of the
four values are declared as literals, because the Profile's directory already
names the hardware model and the Kodi version
(`config/shared/ugoos-am6b-plus/coreelec-21.3/`) and that scope is what the
probe was recomputing at runtime. The fourth is retired, because Kodi ignores
it.

This matters beyond convenience. A probe needs Kodi running, and
[ADR 0013](0013-a-settings-document-always-takes-the-kodi-stop.md) requires
Kodi stopped to write a settings document. Keeping the probe would have forced
a Run to start Kodi, read, stop, write, and start again — and on a
factory-fresh Device the probe's own channel is not configured yet, so the
first Run could not use it at all. The genericity that cost was buying is
genericity the Profile's path already provides.

## `audiooutput.channels` is a fixed table, not a capability

Kodi registers options-fillers for `audiodevices`,
`audiodevicespassthrough`, `aequalitylevels` and `audiostreamsilence`
(`ActiveAESettings.cpp:59-62`, Omega). It registers none for
`audiooutput.channels`. That setting's options are a static list written into
Kodi's own `system/settings/settings.xml`, where `10` is
`AE_CH_LAYOUT_7_1` and has been for every option in the table from `1` to
`10`.

So the shell's `resolve_channels` matches the label `7.1` against a constant
table to obtain a constant. The Device holds `10`, and the room asks for
`7.1`. It is declared as `10`.

The claim that this ordinal is unstable across runs — recorded in the Room
Overlay's comments and in the reconcile runbook — is wrong, and those
statements are corrected. Only the resolution ordinal moves.

## The ALSA strings belong to the platform the Profile names

`audiooutput.audiodevice` and `audiooutput.passthroughdevice` hold strings
that embed the kernel's card name:

```
ALSA:surround71:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND
ALSA:hdmi:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND
```

`AMLAUGESOUND` is a property of the Amlogic sound driver on this board, which
is exactly what `ugoos-am6b-plus/coreelec-21.3` names. It is not a per-Device
discovery, and it is readable **without Kodi**: `/proc/asound/cards` on the
Device reports `0 [AMLAUGESOUND ]: AML-AUGESOUND - AML-AUGESOUND`.

The Reconciler reads that file before writing either address and fails the Run
if the pinned card is absent. Re-reading `guisettings.xml` afterwards only
proves the Reconciler wrote what it meant to; it cannot show that Kodi will
accept the string. The failure this catches is Kodi silently falling back to a
different output, which presents as "no audio" and is expensive to trace back
to a card name.

## `videoscreen.resolution` is bookkeeping Kodi recomputes

The ordinal is a user-interface control, not the stored truth. Both
`CDisplaySettings::GetCurrentResolution` and
`CDisplaySettings::GetDisplayResolution` return
`GetResolutionFromString(videoscreen.screenmode)` (`DisplaySettings.cpp`,
Omega). The ordinal only reaches `screenmode` through `OnSettingChanging`
(`DisplaySettings.cpp:256-277`), which fires when the setting is changed
**through Kodi**. Editing the file while Kodi is stopped never triggers it.

The Device proves it. `videoscreen.resolution` reads `40` while
`videoscreen.screenmode` still reads `DESKTOP`; had the shell's write been
taken as a change, `screenmode` would hold a mode string instead. The shell
never writes `screenmode`. And Kodi's log shows it deriving the value for
itself at startup:

```
Found (1920x1080@60.000000) at 40, setting to RES_DESKTOP at 16
```

`ROOM-001` is therefore retired. Writing a value Kodi recomputes is not
ownership. Mode switching during playback is governed by
`videoscreen.whitelist`, which `ROOM-002` already owns.

If pinning the GUI mode ever becomes a real need, the address is
`videoscreen.screenmode` and it is a literal mode string. Nothing needs that
today.

## Nothing provisions the display mode, and nothing should

The output mode is not configuration. `/flash/config.ini` mentions `hdmimode`
only inside a comment, `service.coreelec.settings` has no `addon_data`
directory at all, and `hpd_state` reads `1` against a live Sony EDID. CoreELEC
re-reads EDID and selects the best mode on every boot, which is why
`/sys/class/display/mode` reads `2160p60hz` with nothing on disk saying so.

A factory-fresh Device that comes up at 1080p60 has not been misconfigured; it
read no usable EDID at that moment, because the display was off, on another
input, or behind a device not yet passing through. It corrects itself on the
next boot with the display live. Note also that the Kodi GUI always renders at
1920x1080 and is scaled to the output on this platform, so "set the user
interface to 4K" is not an operation that exists here.

Because the mode is self-correcting there is no address to manage, but a bad
EDID handshake is silent. The provisioning runbook therefore carries a
precondition and a check rather than a setting.

## What this gives up

The shell's display probe also asserted that the display currently offers
every mode pinned in `videoscreen.whitelist`. That check is not reimplemented.
A whitelisted mode the display cannot do is simply never selected by Kodi, and
`ROOM-002` has been accepted and running without the check already.

## Consequences

`Intent` leaves `CONTEXT.md`. With the probe gone nothing resolves an Intent,
and the work the term described is done by the Profile's scope — which
`Profile Constant` already covers. A glossary term with no referent invites
someone to build the machinery again.

Branching a Profile for a future CoreELEC or Kodi release stays a
configuration change: the new Profile directory names the new version, and any
value that moved with it is edited in that directory. No code knows which
version it is talking to.
