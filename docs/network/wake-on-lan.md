# Wake-on-LAN from Home Assistant on IoT to LAN

Use this alongside [device network onboarding](pfsense-plus-26.07-onboarding.md). The owner reports an existing pfSense static ARP entry for **`172.16.99.99`** to deliver wake traffic from Home Assistant's IoT network to streaming devices on LAN. This document records that design; live configuration and device wake behavior have not been inspected.

## Networks and address roles

| Item | Value | Purpose |
|---|---|---|
| Home Assistant network | `192.168.10.0/24`; `2001:db8:10::/64` | Source network (IoT); exact host address pending |
| Streaming device network | `172.16.0.0/16`; `2001:db8:1::/64` | Target network (LAN) |
| Shared IPv4 wake destination | `172.16.99.99` | Destination passed to Home Assistant's WoL action |
| Expected LAN ARP mapping | `172.16.99.99` → `ff:ff:ff:ff:ff:ff` | Ethernet broadcast delivery; confirm against the existing entry |
| Target MAC in magic packet | Each device's real wired MAC | Selects the device to wake |
| Device DHCP address | Each device's own reserved LAN address | Normal control and availability checks after wake |

`172.16.99.99` is a host-form address inside the LAN `/16`; the subnet's IPv4 broadcast address is `172.16.255.255`. The reported design uses a static ARP mapping to send traffic addressed to `.99.99` as an Ethernet broadcast. The broadcast MAC above is the expected mapping for that mechanism, pending inspection of the installed entry.

```text
Home Assistant on IoT
    -> IPv4 UDP to 172.16.99.99, carrying the target device's MAC
    -> pfSense IoT ingress rule permits the wake traffic
    -> LAN static ARP entry delivers an Ethernet broadcast
    -> matching LAN device wakes
    -> Home Assistant reconnects to that device's reserved address
```

Keep `172.16.99.99` out of dynamic pools and ordinary device assignments. The `ff:ff:ff:ff:ff:ff` MAC belongs only to the shared broadcast mechanism; device reservations and magic-packet targets use real device MACs. A stable reservation supports reconnection and monitoring after wake; the magic packet identifies the sleeping device by MAC.

This wake path uses IPv4. The recorded IPv6 prefixes apply to normal dual-stack connectivity; they do not change this ARP-based delivery mechanism.

## Preserve and verify the pfSense path

1. Inspect **Diagnostics > ARP Table** for `172.16.99.99` on the LAN interface. Confirm its MAC and permanent status. Record how the existing entry is created and restored at startup; a runtime-only entry is insufficient after a firewall restart. Netgate documents the interface, MAC, and permanence fields in the [ARP table guide](https://docs.netgate.com/pfsense/en/latest/monitoring/status/arp.html).
2. Verify that neither DHCP pools nor another host can claim `172.16.99.99`.
3. Inspect the rule permitting **IPv4 UDP** from the **actual Home Assistant host address** on IoT to **`172.16.99.99/32`**, with the configured destination port. The example below uses UDP **9**; the existing port and rule still need confirmation. pfSense interface rules normally evaluate incoming traffic, so this flow enters on IoT. [Netgate firewall rule methodology](https://docs.netgate.com/pfsense/en/latest/firewall/rule-methodology.html)
4. Preserve this shared entry when adding ordinary DHCP mappings. It is not a reason to enable interface-wide static ARP restrictions or add a broadcast-MAC mapping for every device.

Normal Kodi/receiver control and callbacks use separate rules to the devices' own addresses. Success sending a wake packet does not establish that those services are reachable.

## Home Assistant action

If the action is not already available, enable the Wake on LAN integration; the action-only YAML setup adds `wake_on_lan:` to `configuration.yaml`. Use this action in the chosen wake automation, replacing the MAC placeholder and confirming the port against the existing firewall rule:

```yaml
action: wake_on_lan.send_magic_packet
data:
  mac: "REPLACE_WITH_DEVICE_WIRED_MAC"
  broadcast_address: "172.16.99.99"
  broadcast_port: 9
```

Home Assistant supports an explicit destination and port. This is an action example, not a complete automation or deployed configuration. [Home Assistant Wake on LAN](https://www.home-assistant.io/integrations/wake_on_lan/)

Reuse the destination across LAN devices and vary the target MAC. If using a WoL switch's `host` field for availability, supply the device's reserved IP or verified hostname, not `172.16.99.99`. Confirm recovery through the actual media/control integration as well.

## Validation

- [ ] The device supports WoL from the selected power state, and its wired interface remains powered and connected. Test suspend and shutdown separately if both are intended; neither is assumed for an untested Ugoos installation.
- [ ] Trigger the wake action from Home Assistant on IoT while the target sleeps. Confirm it wakes, then responds through its integration at its reserved LAN address.
- [ ] Repeat after the target has remained asleep long enough for ordinary dynamic ARP state to expire. Success must not depend on a recently awake device's ARP entry.
- [ ] During the next planned firewall restart, verify the shared static ARP entry returns and repeat the wake test.
- [ ] Record the device MAC, destination, actual UDP port, tested power state, outcome, and date in the room's device guide.

If wake fails, use **Diagnostics > Packet Capture** to inspect the UDP flow first on IoT, then on LAN. On LAN, verify destination IP `172.16.99.99`, the expected Ethernet broadcast destination, and the intended device MAC in the magic-packet payload. Capture link-layer headers when checking the Ethernet address. [Netgate packet capture guide](https://docs.netgate.com/pfsense/en/latest/diagnostics/packetcapture/webgui.html)

No packet at IoT ingress points to the sender or its route. A packet arriving on IoT but absent on LAN points to firewall/routing/ARP configuration. A correct LAN broadcast without a wake points to device capability, power state, or link behavior. A device that wakes but stays unavailable needs normal address, service, or control-path troubleshooting.
