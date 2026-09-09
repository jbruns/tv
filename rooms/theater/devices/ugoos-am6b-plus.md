# Theater: Ugoos AM6B+

Install using the [shared CoreELEC 21.3 guide](../../../docs/devices/ugoos-am6b-plus/coreelec-21.3.md). Apply the following room-specific choices alongside that procedure.

## Connections and identity

- HDMI output connects directly to **Sony HDMI IN 4**; video does not pass through the receiver or extender.
- Use wired Ethernet and the supplied power adapter.
- Proposed hostname: `ugoos-theater`. Confirm and record the actual hostname, wired MAC, and DHCP reservation in the [room record](../README.md#installation-record).
- Onboard through [pfSense Plus 26.07](../../../docs/network/pfsense-plus-26.07-onboarding.md), leaving CoreELEC on DHCP. Add the guide's device network record here once this unit's MAC and mapping are known.
- Network: LAN, `172.16.0.0/16` and `2001:db8:1::/64`; individual addresses remain to be recorded.
- Remote model and use of Bluetooth remain to be confirmed. Use the shared guide's matching `remote.conf` or UR-01 Bluetooth steps where applicable.

## Video

Set Dolby Vision mode to **TV-led / display-led** after applying the [Sony settings](sony-xr-65a90j.md). Add all available 2160p modes reported by the Sony to Kodi's resolution whitelist; do not add unreported modes.

Keep custom EDID overrides and Dolby Vision colorimetry startup scripts unset. They are unnecessary for the baseline with the Ugoos directly connected to a correctly configured A90J.

## Audio during the ARC-only interim

While the original AVPro T/R pair remains installed, do not treat a failed TrueHD/Atmos test as a CoreELEC defect. ARC is the limiting link.

After the T2/R2 extender is installed and the television reports an active eARC audio system, configure Kodi for HDMI passthrough and enable the codecs supported by the Denon, including Dolby Digital, Dolby Digital Plus, DTS, Dolby TrueHD, DTS-HD, and Atmos carried within the source bitstream. Keep `Sync playback to display` off because it conflicts with passthrough.

## Arctic Fuse live acceptance — 2026-09-08

- **Hostname**: CoreELEC-theater
- **Platform**: Amlogic-ng.arm-21.3-Omega (Kodi 21.3, JSON-RPC 13.5.0)
- **Provisioner HEAD**: 844d4fe (`fix: persist Arctic Fuse shortcut settings`)

### Deployments

| Run | Report | State | Verification |
|-----|--------|-------|--------------|
| 1st | `coreelec-theater-20260909T044223Z.txt` | committed | pass — all `arctic_fuse.*` and `metadata.*` statuses ok |
| 2nd | `coreelec-theater-20260909T045435Z.txt` | committed | pass — all statuses ok (idempotence) |

### Playlist validation (JSON-RPC Files.GetDirectory)

| Playlist | Type | Items | Status |
|----------|------|-------|--------|
| InProgressMovies90Days | movies | 2 | OK |
| InProgressShows90Days | tvshows | 14 | OK |
| RecentlyAiredEpisodes30Days | episodes | 0 | **DEFECT** — Kodi 21.3 SQL syntax error on `inthelast`/`before`+`tomorrow` rules |
| RecentlyReleasedMovies90Days | movies | 0 | **DEFECT** — same SQL generation bug |
| NewShows | tvshows | 50 | OK |
| NewMovies | movies | 50 | OK |

**Date-relative XSP defect**: Library contains 79 qualifying episodes (30-day) and 3 qualifying movies (90-day), but Kodi 21.3's `CSmartPlaylistDirectory` generates invalid SQL: `WHERE (()) AND (())`. Both JSON-RPC and internal `CGUIMediaWindow::GetDirectory` fail. Home widget tabs 503/504 hidden due to 0 items. Requires provisioner XSP rule fix.

### Pending corrected acceptance expectations

The next acceptance run after the provisioner XSP fix must demonstrate:

- `RecentlyAiredEpisodes30Days`: loads successfully and returns current candidates
- `RecentlyReleasedMoviesCurrentYear`: loads successfully and returns current-year candidates
- `RecentlyReleasedMovies90Days`: absent

### Application launch results

- **Plex (script.plexmod)**: PM4K started, loaded user-select screen (no PLEX_TOKEN configured). Not an empty hub — expected sign-in flow without credentials.
- **YouTube (plugin.video.youtube)**: Opened in Videos window (id=10025) with full 20-item root menu including Sign In, Subscriptions, Trending, Search, etc.

### Screenshots

| Artifact | Description |
|----------|-------------|
| `screenshot-home.png` | Home screen with movie metadata, widget tabs (In-Progress Movies, In-Progress Shows, New Shows, New Movies), Play/More Information buttons |
| `screenshot-power.png` | Options overlay with Settings tile, Weather, and five Power items |
| `screenshot-home-evidence.png` | Home confirming 4 visible tabs (503/504 hidden due to XSP defect) |
| `screenshot-hub-home-v2.png` | Home/Videos hub |
| `screenshot-hub-plex-v2.png` | Plex hub (11101) |
| `screenshot-hub-youtube-v2.png` | YouTube hub (11102) |
| `screenshot-hub-nextaired-v2.png` | Next Aired hub (11106) |
| `screenshot-hub-pvr-v2.png` | PVR hub (11107) |
| `screenshot-hub-addons-v2.png` | Addons hub (11108) |

### Hub navigation

All 6 HomeSwitcher hubs verified via Right-navigation: Home (10000) → Plex (11101) → YouTube (11102) → Next Aired (11106) → PVR (11107) → Addons (11108). `Skin.String()` toggle mechanism works correctly with `type="string"` settings.

### Idempotence and hashes

8 of 9 managed files byte-identical across deployments. The sole difference is `skin.arctic.fuse.3/settings.xml`, which Kodi modifies at runtime (non-managed settings). All 14 managed skin settings remained correct (`type="string"`, expected values) with no case-insensitive duplicate IDs (224 total settings).

### Power menu — five items, correct order, no execution

1. Power off system — `Powerdown()`
2. Custom shutdown timer — `AlarmClock(shutdowntimer,Shutdown())`
3. Suspend — `Suspend()`
4. Reboot — `Reset()`
5. Restart Kodi — `RestartApp()`

No Hibernate, Quit, Log off, or Exit entries. The Power menu was opened and closed via `Input.Back` — **no Power action was executed** at any point during acceptance.

### PVR

589 TV channels present; PVR hub toggle (`HomeSwitcher.1107.Toggle`) enabled.

## Validation and follow-on setup

For Home Assistant wake control from IoT, follow the [shared WoL procedure](../../../docs/network/wake-on-lan.md) using destination `172.16.99.99` and this unit's real wired MAC. Record the tested power state and UDP port here; wake support has not yet been validated for this unit.

Complete both the shared guide's validation checklist and the [theater checklist](../README.md#room-validation) before eMMC migration. After a backup, follow the [remaining room-specific service work](../../../docs/runbook.md#7-remaining-room-specific-service-work); the shared add-ons are already installed and configured by [`provision-coreelec.sh`](../../../docs/runbook.md#3-provision-the-shared-coreelec-baseline). Home Assistant power behavior and additional applications remain follow-on work.
