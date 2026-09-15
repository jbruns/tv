# Theater: Ugoos AM6B+

Apply these room-specific values with the shared Ugoos procedures.

## Theater-specific values

- **Hostname:** `ugoos-theater`; Home Assistant reaches it from IoT as `ugoos-theater.lan.wavebe.am`.
- **Network:** connect the wired NIC to **LAN**, leave IP configuration on **DHCP**, and create a pfSense DHCP reservation plus local DNS record.
- **HDMI:** connect the HDMI output directly to **Sony HDMI IN 4**.
- **Dolby Vision:** set Dolby Vision mode to **TV-led / display-led**.
- **Kodi resolution whitelist:** enable all 2160p modes actually reported by the Sony.
- **Audio path:** pass audio from Sony HDMI 4 through eARC and the OREI link to the Denon; enable HDMI passthrough for Dolby Digital, Dolby Digital Plus, DTS, Dolby TrueHD, DTS-HD, and Dolby Atmos.
- **CEC:** retain navigation, but do not let Kodi startup or shutdown power the
  Sony on or off; Home Assistant and user actions own television power.
- **Kodi entity:** `media_player.theater_kodi_theater`
- **Lifecycle SSH alias:** `ugoos-theater-lifecycle`

## Shared guides

- [Shared installation guide](../../../docs/devices/ugoos-am6b-plus/coreelec-21.3.md), including shared power, startup-override, and playback-sync defaults
- [Shared provisioning operations](../../../docs/operations/provision-ugoos.md)
- [Shared lifecycle guide](../../../docs/home-assistant/ugoos-kodi-lifecycle.md)
