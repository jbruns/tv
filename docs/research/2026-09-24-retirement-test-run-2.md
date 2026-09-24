# Retirement test, run 2 — 2026-09-24

The [retirement test](../operations/retirement-test.md) run a second time,
after [#151](https://github.com/jbruns/tv/issues/151) (skin settings written
typed) closed the gap that stopped run 1. The raw surveys, plans and apply
transcript stay off the repository.

## Run 1, in one paragraph

Run 1 (2026-09-23) stopped at step 6. The first `plan` reported 132 Changes and
`apply` wrote them all, then failed its own Verification on 22 Arctic Fuse
`HomeSwitcher.*` addresses. The Reconciler wrote skin setting nodes without
`type`, and Kodi's skin loader drops those silently, so the skin started from
its own defaults. #151 added the `skin` dialect.

## Setup

- Spare card re-imaged with plain CoreELEC 21.3; wizard given hostname,
  wired DHCP and SSH with a password, nothing else.
- Host keys cleared and re-learned for the fresh card.
- `bootstrap` run by the maintainer; the administrator key then worked and
  the Device held only Estuary, `peripheral.joystick` and
  `service.coreelec.settings` in `addon_data`.

**Steps 5 and 7 did not apply.** The Home Assistant theater lifecycle package
was no longer loaded: every `ugoos_theater_*` entity, the
`keep_kodi_running` override included, had been `unavailable` since
2026-09-24 05:16, and no replacement automation was running
([ADR 0020](../adr/0020-kodi-lifecycle-is-event-driven-home-assistant-blueprints.md),
#153, #155). Nothing started or stopped Kodi but `apply` and the operator.
Kodi was stopped by hand with `systemctl stop kodi` for the survey. The
procedure still names the override and will need updating once the blueprint
lands.

## The three conditions

**1. `apply` converges with no manual step — held.** The first `plan` reported
132 Changes, the same count as run 1. `apply` wrote all 132, shipped the
Artifact Lock, started Kodi, rebuilt the view include, and reported
`verification: converged` in one Run.

**2. A second `plan` reports no Changes — held.** Taken 90 s after `apply`,
with Kodi running.

#151's own acceptance also held. Emby's first-start `DB reset required, Kodi
restart` fired at 12:50:49, as in run 1, and Kodi exited cleanly at 12:53:03,
rewriting the skin document from memory. The file then held 119
`type="string"` nodes, with `HomeSwitcher.1101.Name = TV Shows` and the
`Toggle` values declared. A third `plan`, taken with Kodi stopped, reported no
Changes.

systemd restarted Kodi at 12:53:05, and the operator's `stop` landed on that
fresh process. It hit the 30 s stop timeout and was SIGKILLed, so `kodi.service`
reads `failed` rather than `inactive`. A Kodi a few seconds into startup had
written nothing, and the third `plan` was read after the kill. This is
harmless and needs no mechanism.

**3. Every survey diff line classifies — held**, with the gaps below. The
baseline is the in-service Device's survey of 2026-09-23 (356 findings); the
fresh Device reported 323. The diff has 37 baseline-only lines and 4
fresh-only lines. Three addresses change value and so appear on both sides,
`services.deviceuuid` and two skin hashes, which leaves 38 addresses: 7
per-Device facts, 3 retired, 26 equal to unset, and 2 gaps.

## Triaged diff

### Per-Device facts (7)

| Address | Baseline | Fresh |
|---|---|---|
| `guisettings.xml#services.deviceuuid` | its UUID | a different UUID |
| skin `script-skinvariables-generator-hash` | a hash | `""` |
| skin `script-skinviewtypes-hash` | a hash | `""` |
| skin `script-skinviewtypes-checksum` | a hash | absent |
| `/storage/.cache/fontconfig` | present | absent |
| `/storage/.cache/fstrim.run` | present | absent |
| `addon_data/plugin.video.themoviedb.helper/nodes` | present | absent |

The empty skinvariables hashes are derived cache keys. `script.skinvariables`
was killed at both Kodi exits (`script didn't stop in 5 seconds`) before it
stored them. The generated include it keys was written anyway:
`script-skinvariables-generator-includes-.xml` is 90 KB, and the view include
is the real 8245-byte file. An empty hash only makes the skin regenerate on a
later load.

### Deliberately retired (3)

- `/storage/.cache/coreelec-provision`: the shell's payload and transaction
  cache. It goes with the shell ([ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md)).
- `/storage/.cache/kodi-lifecycle`: transaction state of
  `lib/coreelec-lifecycle.sh`, which ADR 0020 replaces.
- `guisettings.xml#pictures.displayresolution = 41`: Kodi Omega never uses it.
  The setting is `<visible>false</visible> <!-- not properly respected -->`
  (`system/settings/settings.xml:1584-1592`), and `GUIWindowSlideShow.cpp:1004-1010`
  reads it and then discards it behind a dead `if (false …)` branch
  ("FIXME: Use GUI resolution for now"). Its value is an index into the
  EDID-dependent resolution table (`SettingOptionsResolutionsFiller`), the
  same kind of value [ADR 0019](../adr/0019-the-profiles-scope-resolves-what-the-shell-probed.md)
  declined to own for `videoscreen.resolution`. Declaring it would own a
  value Kodi ignores.

### Equal to unset or default (26)

These are Arctic Fuse skin settings the in-service Device holds as `""` or
`false`, and the fresh Device does not hold at all. An empty string is an
unset `Skin.String`, and `false` is an unset toggle, so the skin behaves the
same either way:

- `HomeSwitcher.110{1,2}.Spotlight.{Limit,SortMethod,SortOrder}` (6)
- `hub.1108.disable{game,music,picture,program,video}` (5)
- `search.disable{combined,discover}`, `contextmenu.disable{artwork,optionstray}`,
  `widgets.{disablenoresultsitem,enableshowmore}` (6)
- `homeswitcher.1105.toggle`, `homeswitcher.onup`, `home.label`,
  `osd_timeout`, `SkinHelper.AutoCloseVideoOSD`, `TMDbHelper.Date.Format`,
  `skinvariables.skinuser.icon`, `tmdbhelper.enabletranslationproperties` (8)
- `OptionsTiles.03.Onclick = ActivateWindow(junk-optionstiles.03.target,…)`:
  the skin's placeholder for an unconfigured tile, which opens nothing (1)

### Operator-owned

None. The `GUIDE-003` to `GUIDE-006` Plex and Emby ladders do not appear in the
survey, which reports only declared documents and undeclared paths.

### Genuine Profile gaps (2)

Neither address is written by the shell or declared by the Profile. Both
diverge from the appliance in service, and both reproduce: run 1 showed the
same two lines.

| Address | In service | Fresh |
|---|---|---|
| `guisettings.xml#videoscreen.screenmode` | `DESKTOP` (default) | `0384002160060.00000pstd` |
| `guisettings.xml#services.wsdiscovery` | `false` | default (`true`) |

- **`videoscreen.screenmode`.** A fresh Device pins the GUI to 2160p60 instead
  of following the desktop mode that CoreELEC selects from EDID. The two agree
  today, because CoreELEC also chose `2160p60hz`. They diverge whenever the
  Device boots without a usable EDID. ADR 0019 named this address as the one
  to declare "if pinning the GUI mode ever becomes a real need"; the need is
  parity with the Device in service. The mode is display-specific, so the
  declaration belongs in the theater Room Overlay.
- **`services.wsdiscovery`.** WS-Discovery lets Kodi find SMB shares
  (`settings.xml:2474-2478`, level 2, default `true`). The in-service Device
  has it off and nothing records who turned it off. The Device class is the
  same in every room, so the declaration belongs in the Profile.

Both are one slice: [#156](https://github.com/jbruns/tv/issues/156).

## Verdict

The Reconciler alone produces the appliance, except for two guisettings
literals. Once #156 lands and the shell's attrition begins, the order is the
one the [write-set permission freeze](../operations/shell-write-set-permissions.md)
requires. Neither gap is in the shell's write set, so neither blocks it.
