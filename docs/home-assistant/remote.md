# Remote in Home Assistant

This guide installs and operates a room's Remote, a Sanytron Astrion. It runs
the stock Astrion Launcher and shows a Home Assistant dashboard built from RosCard
cards. Every key on its TV page goes to the room's Display, which passes
navigation to the Device over CEC and volume to the AVR
([ADR 0024](../adr/0024-the-remote-drives-the-room-through-its-display.md)).
The Remote adds no automations or scripts. Power on and off switch only the
Display, and the [Kodi Lifecycle](ugoos-kodi-lifecycle.md) starts and stops
Kodi as usual.

Each room has its own dashboard:

| File in this repository | Deployed to |
|---|---|
| `home-assistant/packages/remote_theater.yaml` | `/config/packages/remote_theater.yaml` |
| `home-assistant/dashboards/remote_theater.yaml` | `/config/dashboards/remote_theater.yaml` |

The package registers the YAML-mode dashboard `remote-theater`, which is
hidden from the sidebar, and `select.theater_sony_apps`, the Remote's app list.
The Sony's `source_list` holds only its inputs, so selecting an option launches
that app with `media_player.play_media`. To offer another app, add its title
exactly as Media -> Theater TV -> Applications shows it. The dashboard file
holds the pages.

The Remote does not open one chosen dashboard. It reads every RosCard card on
every dashboard its user can see, and shows only those. Standard Lovelace cards
never reach it. A view or dashboard named `default` or `home` clashes with the
Remote's launcher, so don't use those names.

## 1. Prerequisites

- The room's Display integration is configured. For the theater, the Sony
  BRAVIA integration provides `media_player.sony_theater` and
  `remote.sony_theater`. The Sony has **Remote start** on and **BRAVIA Sync
  control** on, as in the [Sony guide](../../rooms/theater/devices/sony-xr-65a90j.md).
- RosCard is installed through HACS as a **Lovelace** repository. Settings ->
  Dashboards -> Resources lists its `RosCard.js`.
- The Astrion integration is **not** needed. It adds the Remote's IR blaster,
  and nothing uses IR yet.

RosCard's README names its cards `custom:ros-*`, but the cards it actually
installs are `custom:aiks-*`, for example `custom:aiks-tv-card`. Copy card
types from these dashboard files, not from the README.

A card must carry every field RosCard's editor saves, including a `uuid`. The
Remote shows "View is empty" for a card written without them. Give each new
card its own fixed `uuid`, for example from `python3 -c 'import uuid;
print(uuid.uuid4())'`, and never reuse one.

## 2. Create the Remotes user

The Remote logs in as its own non-admin user, not as an operator.

1. Settings -> People -> Users -> Add user. Name it `Remotes`, turn on
   **Can only log in from the local network**, and leave **Administrator** off.
2. Log in as `Remotes`. Under Profile -> Security, create a long-lived access
   token named after the Remote, for example `astrion-theater`.
3. Still as `Remotes`, go to Profile -> General. Set the default dashboard to
   the room's Remote dashboard, for example Theater Remote. Choose **Change
   order and hide items** for the sidebar, and hide every item.
4. Pair the Remote with that token by following Sanytron's
   [pairing guide](https://hub.sanytron.com/support/astrion/pair-home-assistant).
5. If the Remote was paired with another user's token before, revoke that
   token from its owner's Profile -> Security.

Revoking a token disconnects that Remote only. Because a Remote shows every
RosCard card its user can see, one shared user works for only one room. How a
second room's Remote is kept to its own cards is decided when that Remote is
added.

## 3. Deploy the dashboard

1. Run `scripts/check_home_assistant.sh`.
2. Copy both files in the table above to the paths shown.
3. Run `ha core check`, then restart Home Assistant Core. Packages must be
   enabled, as in the [Kodi Lifecycle guide](ugoos-kodi-lifecycle.md). If
   `configuration.yaml` already declares `lovelace: dashboards:`, move those
   dashboards into a package too. Home Assistant will not merge two
   `dashboards` mappings.
4. A later change to the dashboard file alone needs no restart: refresh the
   Remote instead. A change to the package's app list needs Developer Tools ->
   YAML -> Template entities to be reloaded.

## 4. Set up the Remote

These settings live on the Remote, not in this repository. Set them on every
new or reset Remote:

1. On the Remote, go to Settings -> TV Card -> shortcut configuration and
   turn **Global Buttons** off. The TV page's key map then applies while it is
   showing.
2. Pull down from the top of the home screen and tap Refresh. The Remote
   caches what it reads, so it needs this after every dashboard change. RosCard issue
   [#31](https://github.com/yyqclhy/RosCard/issues/31) reports that the
   refresh sometimes loads an empty view. If it does, refresh again.

## 5. Check it on the hardware

The first time a Remote is set up in a room, check each row with Kodi showing
on the Display and record what happened. Where a key doesn't work, change its
`value` in the dashboard file to another of the Display's own code names. To
list them, call `remote.send_command` on `remote.sony_theater` with the
command `Test`. The integration then logs every code name the Sony supports.

| Check | Expected |
|---|---|
| Power with the Display off | The Sony comes on, and the Kodi Lifecycle starts Kodi on HDMI 4 |
| Power with the Display on | The Sony turns off. Kodi stops after the stop delay |
| D-pad, OK, Back | Kodi moves, selects and goes back, with no noticeable lag or dropped presses |
| Hold a d-pad key | Record whether it repeats |
| Home, Menu | Record what Kodi or the Sony does |
| Play, Pause | Kodi plays and pauses. In a Sony app, that app does |
| Volume up and down, Mute | The Denon's volume changes |
| Hold volume | Record whether it repeats |
| App list | Launches YouTube on the Sony |

## 6. Add a room

1. Copy `remote_theater.yaml` in both `packages/` and `dashboards/` to
   `remote_<room>.yaml`.
2. In the package, rename the dashboard to `remote-<room>`, and change its
   title and filename. Rename the app-list select, and change its unique ID and
   Display.
3. In the dashboard, replace the Display's `media_player` and `remote` entity
   IDs and the app-list `source`, set `tv_name`, and give the card a new
   `uuid`.
4. Decide how the new Remote sees only its own room's cards (see section 2),
   then follow sections 2 to 5 for it.
