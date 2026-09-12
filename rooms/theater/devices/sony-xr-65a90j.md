# Theater: Sony XR-65A90J

Use the [theater signal topology](../README.md#signal-topology). These settings apply to this television and room wiring.

## Physical connections

1. Connect the Ugoos HDMI output directly to **Sony HDMI IN 4**.
2. Connect **Sony HDMI IN 3 (eARC)** to the [OREI EARC-EX165-K TV-side unit](orei-earc-ex165-k.md).
3. Connect the Sony wired NIC to **IoT**.

## Network and Home Assistant

- Leave the Sony IP configuration on **DHCP**.
- Create a pfSense reservation and local DNS record for the wired IoT connection.
- Open:

  ```text
  Settings
  -> Network
  -> Home Network Setup
  -> IP Control
  ```

- Set authentication to the PSK-capable mode and configure a unique pre-shared key stored outside the repository.
- Set **Remote start: On** so Home Assistant can control the television from standby.
- In Home Assistant, add the **Sony Bravia TV** integration under **Settings > Devices & services** using the reserved address and PSK.
- Rename the integration entity to `media_player.sony_xr_65a90j` so the lifecycle package contract is satisfied.

## HDMI signal formats

On the Sony, open:

```text
Quick Settings
-> Settings
-> Channels & Inputs
-> External inputs
-> HDMI signal format
```

Set:

| Input | Setting | Reason |
|---|---|---|
| HDMI 4 | **Enhanced format (Dolby Vision)** | Ugoos input; enables the required Dolby Vision signaling and 18 Gbit/s formats. |
| HDMI 3 | **No video-format requirement** | The OREI connection carries return audio and CEC only; receiver video is not forwarded through this path. |

Do not select `Enhanced format (VRR)` for the Ugoos input. VRR provides no benefit for Kodi movie playback and may make Dolby Vision unavailable on this television generation.

If a format change produces a blank screen, temporarily return that input to `Standard format`, confirm the cable and input, and then re-enable `Enhanced format (Dolby Vision)`.

## Audio output and eARC

Open:

```text
Quick Settings
-> Settings
-> Display & Sound
-> Audio output
```

Apply these settings:

| Sony setting | Required value | Purpose |
|---|---|---|
| Speakers | **Audio system** | Routes television and HDMI-source audio to the Denon. |
| Audio system prioritization | **On** | Selects the HDMI audio system when available. |
| TV center speaker mode | **Off** | The Sony is not being used as the Denon's center channel. |
| A/V sync | **Auto** | Provides the initial lip-sync baseline; tune only if testing shows a repeatable error. |
| eARC mode | **Auto** | Enables high-bitrate return audio when an eARC endpoint is detected. |
| Digital audio out | **Auto 1** | Passes compressed formats without converting them to PCM. |
| Dolby Digital Plus output | **Dolby Digital Plus** | Preserves DD+ and streaming Atmos instead of converting to legacy Dolby Digital. |
| Pass through mode | **Auto** | Passes supported source bitstreams to the Denon without television decoding. |
| Sound mode sync | **Off** | Recommended to prevent the television from changing the Denon's listening mode; not required for eARC transport. |

Do not set `Digital audio out` to `PCM`; doing so would prevent bitstream transport of TrueHD/Atmos. `Digital audio out volume` applies to PCM and is not material to this bitstream configuration.

## BRAVIA Sync / HDMI-CEC

Open:

```text
Quick Settings
-> Settings
-> Channels & Inputs
-> External inputs
-> BRAVIA Sync settings
```

Use this configuration:

| Setting | Value | Reason |
|---|---|---|
| BRAVIA Sync control | **On** | Enables HDMI-CEC discovery, Sony-remote navigation, and audio-system coordination. |
| Device auto power off | **Off** | Keeps Home Assistant, not the television, in charge of display idle power-off and Kodi lifecycle. |
| TV auto power on | **Off** | Prevents Kodi, HDMI input, or CEC activity from unexpectedly turning on the television during lifecycle automation. |

Keep **Device auto power off** and **TV auto power on** disabled for the Ugoos lifecycle. Home Assistant owns display idle power-off and Kodi start/stop; BRAVIA Sync remains enabled only for discovery, Sony-remote navigation, and audio coordination.

## Picture settings

No global picture-mode reset is required. Sony picture controls are stored by input and signal type. Preserve any existing calibration.

When Dolby Vision is first detected, select `Dolby Vision Dark` or `Dolby Vision Bright` according to viewing conditions. This is a picture preference, not a compatibility requirement. Do not change HDR tone-mapping, motion, color-temperature, or panel-brightness settings merely to complete the CoreELEC installation.

## Sources

- [Sony XR-65A90J specifications](https://www.sony.com/electronics/support/televisions-projectors-oled-tvs-android-/xr-65a90j/specifications)
- [Sony HDMI input capabilities and signal-format settings](https://www.sony.com/electronics/support/articles/00194995)
- [Sony A90J Help Guide: HDMI input picture settings](https://helpguide.sony.net/tv/iusltn1/v1/en-003/04-09_02.html)
- [Sony A90J Help Guide: audio output, eARC, and pass-through](https://helpguide.sony.net/tv/iusltn1/v1/en-003/01-03-09_02.html)
- [Sony BRAVIA Sync overview](https://www.sony.com/electronics/support/articles/00161073)
- [Home Assistant Sony Bravia TV integration](https://www.home-assistant.io/integrations/braviatv/)
