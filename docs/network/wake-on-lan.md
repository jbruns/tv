# Wake-on-LAN from Home Assistant on IoT to LAN

Use this alongside [device network onboarding](pfsense-plus-26.07-onboarding.md)
only for optional wake workflows. Wake-on-LAN is outside the always-awake
Ugoos/CoreELEC lifecycle: the lifecycle package does not send WoL and does not
depend on it.

## Shared design

| Item | Value | Purpose |
|---|---|---|
| Home Assistant network | `192.168.10.0/24`; `2001:db8:10::/64` | Source network (IoT) |
| Streaming device network | `172.16.0.0/16`; `2001:db8:1::/64` | Target network (LAN) |
| Shared IPv4 wake destination | `172.16.99.99` | Destination passed to the Home Assistant WoL action |
| LAN static ARP mapping | `172.16.99.99` → `ff:ff:ff:ff:ff:ff` | Ethernet broadcast delivery |
| Target MAC in magic packet | Each device real wired MAC | Selects the device to wake |
| Device DHCP address | Each device reserved LAN address | Control and availability checks after wake |

`172.16.99.99` is a host-form address inside the LAN `/16`; the subnet IPv4
broadcast address remains `172.16.255.255`. The design uses a static ARP
mapping so traffic addressed to `.99.99` is emitted as an Ethernet broadcast.

```text
Home Assistant on IoT
    -> IPv4 UDP to 172.16.99.99, carrying the target device MAC
    -> pfSense IoT ingress rule permits the wake traffic
    -> LAN static ARP entry delivers an Ethernet broadcast
    -> matching LAN device wakes
    -> Home Assistant reconnects to that device reserved address
```

Keep `172.16.99.99` out of dynamic pools and ordinary device assignments. The
broadcast MAC belongs only to this shared mechanism; device reservations and
magic-packet targets use real device MACs.

This wake path is IPv4-only. The IPv6 prefixes above remain relevant for normal
dual-stack connectivity but do not change the ARP-based wake mechanism.

## Preserve and verify the pfSense path

1. Inspect **Diagnostics > ARP Table** for `172.16.99.99` on the LAN
   interface. Confirm the MAC and permanent status, and confirm the entry is
   restored after a firewall restart.
   [Netgate ARP table guide](https://docs.netgate.com/pfsense/en/latest/monitoring/status/arp.html)
2. Verify that neither DHCP pools nor another host can claim `172.16.99.99`.
3. Inspect the rule permitting **IPv4 UDP** from the **actual Home Assistant
   host address** on IoT to **`172.16.99.99/32`** on the selected destination
   port. The example below uses UDP **9**.
   [Netgate firewall rule methodology](https://docs.netgate.com/pfsense/en/latest/firewall/rule-methodology.html)
4. Preserve this shared entry when adding ordinary DHCP mappings. It is not a
   reason to enable interface-wide static ARP restrictions or add a
   broadcast-MAC mapping for every device.

Normal Kodi, display, and receiver control still use the devices' own reserved
addresses and their own firewall rules. Sending a wake packet does not confirm
those control paths.

## Home Assistant action

If the action is not already available, enable the Wake on LAN integration; the
action-only YAML setup adds `wake_on_lan:` to `configuration.yaml`. Use this
action in the chosen wake automation, replacing the MAC placeholder and
confirming the port against the installed firewall rule:

```yaml
action: wake_on_lan.send_magic_packet
data:
  mac: "REPLACE_WITH_DEVICE_WIRED_MAC"
  broadcast_address: "172.16.99.99"
  broadcast_port: 9
```

Home Assistant supports an explicit destination and port. This is an action
example, not a complete automation or deployed configuration.
[Home Assistant Wake on LAN](https://www.home-assistant.io/integrations/wake_on_lan/)

Reuse the destination across LAN devices and vary only the target MAC. If a
WoL switch uses a `host` field for availability, supply the device reserved IP
or verified hostname, not `172.16.99.99`.

## Troubleshooting

First confirm that the target device supports WoL from the selected power state
and keeps its wired interface powered. Then trigger the Home Assistant action
and verify the device wakes and becomes reachable at its reserved address.

If wake fails, use **Diagnostics > Packet Capture** to inspect the UDP flow
first on IoT, then on LAN. On LAN, verify destination IP `172.16.99.99`, the
Ethernet broadcast destination, and the intended device MAC in the magic-packet
payload. Capture link-layer headers when checking the Ethernet address.
[Netgate packet capture guide](https://docs.netgate.com/pfsense/en/latest/diagnostics/packetcapture/webgui.html)

No packet at IoT ingress points to the sender or its route. A packet arriving
on IoT but absent on LAN points to firewall, routing, or ARP configuration. A
correct LAN broadcast without a wake points to device capability, power state,
or link behavior. A device that wakes but stays unavailable needs normal
address, service, or control-path troubleshooting.
