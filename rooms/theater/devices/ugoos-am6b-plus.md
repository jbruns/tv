# Theater: Ugoos AM6B+

Apply these room-specific values with the shared Ugoos procedures.

## Theater-specific values

- **Hostname:** `ugoos-theater`
- **Network:** connect the wired NIC to **LAN**, leave IP configuration on **DHCP**, and create a pfSense DHCP reservation plus local DNS record.
- **HDMI:** connect the HDMI output directly to **Sony HDMI IN 4**.
- **Power:** use the supplied power adapter.
- **Dolby Vision:** set Dolby Vision mode to **TV-led / display-led**.
- **Kodi resolution whitelist:** enable all 2160p modes actually reported by the Sony.
- **Startup overrides:** leave custom EDID and Dolby Vision colorimetry startup overrides unset.
- **Audio:** enable HDMI passthrough for Dolby Digital, Dolby Digital Plus, DTS, Dolby TrueHD, DTS-HD, and Dolby Atmos, and keep `Sync playback to display: Off`.
- **Kodi entity:** `media_player.kodi_theater`
- **Lifecycle SSH alias:** `ugoos-theater-lifecycle`

## Shared guides

- [Shared installation guide](../../../docs/devices/ugoos-am6b-plus/coreelec-21.3.md)
- [Shared provisioning operations](../../../docs/operations/provision-ugoos.md)
- [Shared lifecycle guide](../../../docs/home-assistant/ugoos-kodi-lifecycle.md)
