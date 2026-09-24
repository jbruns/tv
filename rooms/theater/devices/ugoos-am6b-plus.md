# Theater: Ugoos AM6B+

Provision this Device with [Provision a Device](../../../docs/operations/provision-a-device.md)
and `--room theater`.

## Theater-specific values

- **Hostname:** `ugoos-theater`; Home Assistant reaches it from IoT as `ugoos-theater.lan.wavebe.am`.
- **Network:** connect the wired NIC to **LAN**, leave IP configuration on **DHCP**, and create a pfSense DHCP reservation plus local DNS record.
- **HDMI:** connect the HDMI output directly to **Sony HDMI IN 4**.
- **Display and audio Desired State:** the Dolby Vision mode, the Kodi
  resolution whitelist, and the audio passthrough flags are declared in the
  theater Room Overlay,
  [`config/rooms/theater/room.yaml`](../../../config/rooms/theater/room.yaml),
  not recorded here. The audio path is Sony HDMI 4 eARC, through the OREI
  link, to the Denon.
- **CEC:** retain navigation, but do not let Kodi startup or shutdown power the
  Sony on or off; Home Assistant and user actions own television power.
- **Kodi entity:** `media_player.theater_kodi_theater`
- **Lifecycle SSH alias:** `ugoos-theater-lifecycle`

## Shared guides

- [Provision a Device](../../../docs/operations/provision-a-device.md)
- [Profile reference](../../../docs/reference/profile.md)
- [Shared lifecycle guide](../../../docs/home-assistant/ugoos-kodi-lifecycle.md)
