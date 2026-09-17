# Theater: Ugoos AM6B+

Apply these room-specific values with the shared Ugoos procedures.

## Theater-specific values

- **Hostname:** `ugoos-theater`; Home Assistant reaches it from IoT as `ugoos-theater.lan.wavebe.am`.
- **Network:** connect the wired NIC to **LAN**, leave IP configuration on **DHCP**, and create a pfSense DHCP reservation plus local DNS record.
- **HDMI:** connect the HDMI output directly to **Sony HDMI IN 4**.
- **Display and audio desired state:** the Dolby Vision mode, the Kodi
  resolution whitelist, and the audio passthrough flags are managed by the
  `room` provisioning component, not recorded here. The authoritative values
  live in
  [`config/rooms/theater/room.conf`](../../../config/rooms/theater/room.conf);
  what each key means is in the
  [room desired-state reference](../../../docs/devices/ugoos-am6b-plus/room-desired-state.md).
  The audio path is still: Sony HDMI 4 eARC, through the OREI link, to the
  Denon.
- **CEC:** retain navigation, but do not let Kodi startup or shutdown power the
  Sony on or off; Home Assistant and user actions own television power.
- **Kodi entity:** `media_player.theater_kodi_theater`
- **Lifecycle SSH alias:** `ugoos-theater-lifecycle`

## Scoped CEC maintenance

Once Home Assistant lifecycle control is active, enable
`input_boolean.ugoos_theater_keep_kodi_running` and confirm Kodi is running
before maintenance. Apply only the Ugoos CEC policy with:

```bash
./provision-coreelec.sh \
  --target ugoos-theater \
  --component cec \
  --yes
```

Keep the override enabled until the corrected Home Assistant package is
installed and its live recovery checks complete. The repository state alone
does not prove that either the CEC policy or package is live. The scoped run
uses the shared transaction and rollback workflow and must report only CEC
verdicts; it must not judge Arctic Fuse or other unselected state.

This rollout does not change Sony or Denon configuration. Weather, buffering,
and add-on sequencing remain separate work. Display and audio desired state
is applied by the `room` component, run separately from the CEC-only rollout
above.

## Shared guides

- [Shared installation guide](../../../docs/devices/ugoos-am6b-plus/coreelec-21.3.md), including shared power, startup-override, and playback-sync defaults
- [Shared provisioning operations](../../../docs/operations/provision-ugoos.md)
- [Room desired-state reference](../../../docs/devices/ugoos-am6b-plus/room-desired-state.md)
- [Shared lifecycle guide](../../../docs/home-assistant/ugoos-kodi-lifecycle.md)
