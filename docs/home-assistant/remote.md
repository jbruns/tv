# Remote in Home Assistant

This guide installs and operates a room's Remote, a Sanytron Astrion HA100.
It runs [Astrion Custom
Dashboard](https://github.com/dckiller51/astrion-custom-dashboard) in place of
the stock launcher
([ADR 0026](../adr/0026-the-remote-runs-an-open-source-launcher.md)). The
room's `dashboard.json` binds each hardware key to a Home Assistant action:

- Power toggles the Display, and the
  [Kodi Lifecycle](ugoos-kodi-lifecycle.md) starts and stops Kodi as usual.
- Volume goes straight to the AVR, in its own 0.5 dB step. The Remote pops up
  a volume bar showing the AVR's level.
- Every other key goes to the room's key router
  ([ADR 0025](../adr/0025-the-remote-sends-keys-to-whatever-the-display-is-showing.md)).
  Mute toggles the AVR's mute. While Viewing, other keys go to Kodi as its own
  remote's buttons, so each Kodi screen gives them their usual meaning.
  Otherwise they go to the Display as its own remote codes.

| File in this repository | Deployed to |
|---|---|
| `home-assistant/packages/remote_theater.yaml` | `/config/packages/remote_theater.yaml` |
| `remotes/theater/dashboard.json` | Uploaded to the Remote |

The package holds two template selects and one automation:

- `select.theater_remote_keys` is the key router. It holds the Kodi button and
  Sony code for each key.
- `select.theater_sony_apps` is the Remote's app list. The Sony's
  `source_list` holds only its inputs, so selecting an option launches that
  app with `media_player.play_media`. To offer another app, add its title
  exactly as Media -> Theater TV -> Applications shows it.
- The mute resync. The Sony mutes the Denon as it turns off, and the Denon
  unmutes itself at power-on without telling Home Assistant. Five seconds
  after the Denon comes on, the automation mutes and unmutes it so that Home
  Assistant sees its real state.

`dashboard.json` holds the Remote's two pages and its key bindings. The TV
page shows Kodi, the AVR and the app list. Swiping left opens the room page:
the room's lights, with brightness, and the thermostat's setpoint and mode.
The hardware keys do the same thing on both pages. The Home
Assistant URL and token are entered on the Remote itself and are never in
this file.

## 1. Prerequisites

- The room's Display, AVR and Kodi integrations are configured. For the
  theater, they provide `media_player.sony_theater`, `remote.sony_theater`,
  `media_player.denon_theater` and `media_player.ugoos_theater`. The Sony
  has **Remote start** on, as in the
  [Sony guide](../../rooms/theater/devices/sony-xr-65a90j.md).
- `adb` and `gh` on the operator's machine, and a USB data cable for the
  Remote.
- The Remote has a fixed address on the network, for example from a DHCP
  reservation. This guide calls it `<remote>`.

## 2. Create the Remotes user

The Remote logs in as its own non-admin user, not as an operator.

1. Settings -> People -> Users -> Add user. Name it `Remotes`, turn on
   **Can only log in from the local network**, and leave **Administrator** off.
2. Log in as `Remotes`. Under Profile -> Security, create a long-lived access
   token named after the Remote, for example `astrion-theater`.
3. If the Remote used another token before, revoke it from its owner's
   Profile -> Security.

## 3. Install the launcher

1. On the Remote, turn on Developer options (Settings -> About, tap the build
   number seven times), then turn on **USB debugging**. Connect it by USB and
   accept the debugging prompt. `adb devices` lists it as `HA100`.
2. Download the beta and install it. It installs alongside the stock launcher
   as `com.custom.astrion.debug`:

   ```sh
   gh release download dev-latest --repo dckiller51/astrion-custom-dashboard \
     --pattern app-debug.apk --dir /tmp/astrion
   adb install /tmp/astrion/app-debug.apk
   ```

3. Grant its permissions and make it the home app:

   ```sh
   app=com.custom.astrion.debug
   adb shell pm grant "$app" android.permission.READ_EXTERNAL_STORAGE
   adb shell pm grant "$app" android.permission.WRITE_EXTERNAL_STORAGE
   adb shell appops set "$app" WRITE_SETTINGS allow
   adb shell cmd package set-home-activity "$app/com.custom.astrion.MainActivity"
   adb reboot
   ```

4. If the Remote shows a home-app chooser after the reboot, choose **Astrion
   Custom** and **Always**.

Later updates need no ADB: `http://<remote>:8080` offers the beta update.
To return to the stock launcher, run `adb uninstall com.custom.astrion.debug`.

## 4. Connect it to Home Assistant

1. Open `http://<remote>:8080` from a browser on the same network.
2. Enter the Home Assistant URL and the `Remotes` token. Leave **Webhook id**
   blank: it only reports the Remote's page changes to Home Assistant, and
   nothing uses them.
3. Save. The launcher restarts and connects.

## 5. Deploy

1. Run `scripts/check_home_assistant.sh`.
2. Copy the package to the path in the table above. The first time, run
   `ha core check` and restart Home Assistant Core. After that, reload
   Developer Tools -> YAML -> Template entities and Automations instead.
   Packages must be enabled, as in the
   [Kodi Lifecycle guide](ugoos-kodi-lifecycle.md).
3. Upload the room's `dashboard.json`. The Remote reloads it at once:

   ```sh
   curl -F file=@remotes/theater/dashboard.json http://<remote>:8080/dashboard.json
   ```

## 6. Check it on the hardware

The first time a Remote is set up in a room, check each row with Kodi showing
on the Display, then again in a Sony app. Where a key doesn't work, fix its
Kodi button or Sony code in the key router. To list the Sony's code names,
call `remote.send_command` on `remote.sony_theater` with the command `Test`.
The integration then logs every code name the Sony supports.

| Check | Expected |
|---|---|
| Power with the Display off | The Sony comes on, and the Kodi Lifecycle starts Kodi on HDMI 4 |
| Power with the Display on | The Sony turns off. Kodi stops after the stop delay |
| D-pad, OK, Back, Home, Menu in Kodi's menus | Kodi moves, selects, goes back, goes home and opens the context menu |
| Hold a d-pad key | It repeats quickly, and stops when released |
| Page Up, Page Down in a list | Kodi pages up and down |
| Play/Pause, Stop, Rewind, Fast Forward | Kodi plays and pauses, stops, rewinds and fast-forwards |
| Left, Right, Up, Down during playback | Kodi steps back and forward, and by a chapter or a big step |
| OK, Menu during playback | Kodi opens its on-screen display |
| Keys in a Sony app | The Sony app responds |
| Volume up and down | The Denon moves 0.5 dB per press, and the Remote shows its level |
| Hold volume | It repeats quickly |
| Mute, pressed twice, after a power cycle | The Denon mutes, then unmutes |
| App list | Launches YouTube on the Sony |
| Tap a light, drag its slider | The light toggles, and its brightness follows the slider |
| Thermostat steppers, mode chips, power | The setpoint moves 1 °F per press, and the mode and off follow the chips and power |
| Volume and d-pad on the room page | They still drive the AVR and the Display |

After any touch on the screen, the first d-pad, OK or Page key is lost.
Android 8.1 consumes it to leave touch mode before the launcher sees it. Every
later press works, and the other keys are unaffected.

To see which key the Remote sent, read its key log while pressing keys:

```sh
adb logcat -v time -s AstrionKeys:I
```

ADB can also reach the Remote over Wi-Fi, so it can go back in its case: with
the Remote on USB, run `adb tcpip 5555`, then `adb connect <remote>:5555`.
This lasts until the Remote reboots.

## 7. Add a room

1. Copy `home-assistant/packages/remote_theater.yaml` to
   `remote_<room>.yaml`, and `remotes/theater/` to `remotes/<room>/`.
2. In the package, rename both selects and the automation, and change their
   unique IDs. In the key router, set the Display, its `remote`, its input for
   Viewing, the AVR and the Kodi media player. In the app list, set the
   Display. In the mute resync, set the AVR, or drop it if the room's AVR
   does not have the problem.
3. In the room's `dashboard.json`, replace the Display, the AVR, the Kodi
   media player, the key router and the app list. On the room page, rename
   the page and set the room's lights and thermostat.
4. Follow sections 3 to 6 for the new Remote.
