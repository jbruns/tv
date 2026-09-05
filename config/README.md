# Deployable configuration

Reserved for reusable configuration and explicit room/device overrides. No deployable configuration or deployment tooling is implemented yet; the layout below is a convention for future files.

```text
config/
  shared/
    ugoos-am6b-plus/
      coreelec-21.3/            Settings/templates reusable across matching units
  rooms/
    theater/<device-id>/       Theater-specific values
    living/<device-id>/        Living-room-specific values
    guest/<device-id>/         Guest-room-specific values
    master/<device-id>/        Master-room-specific values
```

Use a distinct device ID for each unit so a room can contain multiple devices. Keep hostname, address/reservation, remote model, and room video/audio choices with the target device. Keep shared defaults independent of any room. Version-specific assets should remain tied to the matching platform; CoreELEC 21.3 `-ng` and CoreELEC 22 `-no` are separate installations.

The shared edge routing target is **pfSense Plus 26.07**. Follow the [network onboarding guide](../docs/network/pfsense-plus-26.07-onboarding.md) for DHCP static mappings and device records. Future network inventory should retain each device's active MAC, pfSense interface/subnet, reserved IPv4, and hostname; keep devices on DHCP. No mapping deployment or pfSense configuration import is implemented. Keep full firewall configuration backups outside the repository.

Keep the [shared WoL destination](../docs/network/wake-on-lan.md), `172.16.99.99`, separate from per-device DHCP addresses. Future wake configuration can share that destination while supplying each unit's real wired MAC. Preserve the existing LAN static ARP entry and record the verified UDP port before deployment.

When [deployment code](../code/README.md) is added, document its configuration format, destination paths on the device, and how shared defaults and device overrides are combined before deploying. This directory currently defines no automatic merging or deployment behavior.

Keep passwords, private keys, downloaded firmware/module binaries, and full device backups outside the repository. Record download sources in the [shared device guide](../docs/devices/ugoos-am6b-plus/coreelec-21.3.md); record backup locations and installed values in the appropriate [room guide](../README.md).
