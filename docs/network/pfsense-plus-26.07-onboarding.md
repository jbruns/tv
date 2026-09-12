# Network onboarding: pfSense Plus 26.07

**Applies to:** network-managed devices in theater, living, guest, and master.
**Edge routing standard:** pfSense Plus 26.07.

Use wired Ethernet, DHCP, DHCP reservations, and local DNS for every managed
device. Ugoos playback devices use **LAN**. Home Assistant, network-controlled
Sony displays, and network-controlled Denon receivers use **IoT**. Complete
this procedure before configuring an address-based integration. For the Ugoos
lifecycle, finish reservation and DNS before deploying the restricted SSH
gateway. Return to the [shared setup runbook](../runbook.md) afterward.

## Shared network placement

| Network | IPv4 subnet | IPv6 prefix | Role |
|---|---|---|---|
| LAN | `172.16.0.0/16` | `2001:db8:1::/64` | Streaming devices, including Ugoos playback units |
| IoT | `192.168.10.0/24` | `2001:db8:10::/64` | Home Assistant, Sony displays, Denon receivers, and other network-controlled room devices |

Set aside **`172.16.99.99`** exclusively for the shared static-ARP
Wake-on-LAN design. Do not use it for a host reservation, dynamic pool, or
manual host assignment. See the [shared Wake-on-LAN guide](wake-on-lan.md) for
that optional path.

For new DHCP service, prefer Kea: Netgate identifies ISC as deprecated. Check
the active backend under **System > Advanced > Networking > Server Backend**;
do not change an existing backend as a routine device-onboarding step. The
steps below use pfSense webConfigurator menu names.
[Netgate DHCP overview](https://docs.netgate.com/pfsense/en/latest/services/dhcp/index.html)

## Required cross-network flows

Home Assistant on IoT and Ugoos playback devices on LAN need only narrow,
documented access:

| Source | Destination | Purpose |
|---|---|---|
| Actual Home Assistant host on IoT | Managed Ugoos reserved LAN address or DNS name on TCP/22 | Restricted lifecycle SSH endpoint used by `ugoos-theater-lifecycle` |
| Actual Home Assistant host on IoT | Managed Ugoos Kodi endpoint using only the configured direct integration traffic plus any separately approved discovery or callback handling | Kodi integration state and control |

Do not add broad inter-VLAN access, a general IoT-to-LAN SSH rule, or WAN port
forwards as an onboarding shortcut. If Home Assistant discovery is required
across networks, document only the exact forwarding or protocol support that is
enabled. Address reservations alone do not establish firewall access.

## 1. Choose the device identity and address

Use a unique hostname such as `ugoos-theater`, `ugoos-living`,
`ugoos-guest`, or `ugoos-master`. Add a suffix if a room has multiple units.

Choose an unused IPv4 address inside the correct interface subnet and outside
**all** dynamic pools. Check existing mappings, leases, and documented manual
assignments; a failed ping alone does not prove an address is unused. Exclude
the gateway, virtual IPs, network address, and broadcast address.

- Streaming devices use **LAN** `172.16.0.0/16` with mask `255.255.0.0`.
- Home Assistant, Sony displays, and Denon receivers use **IoT**
  `192.168.10.0/24` with mask `255.255.255.0`.
- `172.16.255.255` is the LAN broadcast address.
- `172.16.99.99` is reserved for the optional static-ARP WoL destination.

pfSense calls these entries static mappings. They do not prevent another device
from manually using the same address. Keep mappings outside dynamic pools.
[Netgate mapping and pool guidance](https://docs.netgate.com/pfsense/en/latest/services/dhcp/mappings-in-pools.html)

## 2. Connect and identify the actual interface

1. Connect the device to its managed **wired Ethernet** network.
2. Leave the device IPv4 configuration on **Automatic / DHCP**.
3. Read the active wired MAC from the device and match it against
   **Status > DHCP Leases** in pfSense.
4. Record the MAC actually used on that wired connection. Do not reuse another
   device MAC and do not use `ff:ff:ff:ff:ff:ff`, the broadcast address.

If the network admits only known clients, obtain the wired MAC locally and
create the mapping before connecting the device.
[Netgate DHCP lease status](https://docs.netgate.com/pfsense/en/latest/monitoring/status/dhcp-ipv4.html)

## 3. Create the static mapping

Open **Services > DHCP Server**, select the correct interface, and choose
**Add Static Mapping**. Alternatively, use the add-mapping action on the
matching lease.

| Field | Value |
|---|---|
| MAC Address | Active wired interface MAC |
| IP Address | Chosen unused address outside the dynamic pools |
| Hostname | Unique device name |
| Description | Room, device model, and interface |
| Client Identifier | Leave blank for the normal MAC-based setup |
| Gateway / DNS overrides | Inherit the interface settings unless the device has a documented exception |
| ARP Table Static Entry | Leave unchecked for ordinary device mappings; preserve the separate `172.16.99.99` wake entry |

Save, then apply pending changes if prompted. A MAC-only entry does not pin an
address. Device DHCP mappings and the shared wake static ARP entry serve
separate purposes.
[Netgate DHCPv4 configuration](https://docs.netgate.com/pfsense/en/latest/services/dhcp/ipv4.html)

## 4. Renew the device lease

Saving a mapping does not immediately replace an address already in use by the
client. Renew DHCP from the device network controls, or reconnect/reboot the
device when idle. Expect existing SSH or control sessions to drop if the
address changes.

Confirm the assigned IPv4 address on the device itself and compare it with the
mapping. If the client keeps the previous address, check the interface, MAC,
pool boundaries, and DHCP logs before retrying. Do not clear the entire lease
database to fix one client.

For a Ugoos that boots both CoreELEC and Android, verify the intended network
identity in each OS if both will be used.

## 5. Verify local DNS

A reservation stabilizes the IPv4 endpoint; local DNS gives it a readable
name. Use the site DNS service that Home Assistant will query.

If using **Kea with the pfSense DNS Resolver (Unbound)**, enable
**DNS Registration** under **Services > DHCP Server > Settings** and check the
selected interface override. For fixed devices, enable **Early DNS
Registration** on the intended interface if names should register at service
startup before clients request leases.
[Netgate Kea DNS registration](https://docs.netgate.com/pfsense/en/latest/services/dhcp/kea-settings.html)

If using **ISC with Unbound**, use **Services > DNS Resolver > General
Settings > Register DHCP static mappings in the DNS Resolver**. With another
local DNS service, create or verify the equivalent host record there.
[Netgate DNS Resolver settings](https://docs.netgate.com/pfsense/en/latest/services/dns/resolver-config.html)

From a client using the same resolver path as Home Assistant, query the device
by name and verify it returns the reserved address. If an integration will use
the reserved IPv4 address directly, record that choice.

## 6. Verify firewall and Home Assistant reachability

Use the reserved IPv4 address when an integration requires an IP; use the
verified DNS name when the integration supports hostnames.

Test the actual integration from Home Assistant, including a state update and a
harmless control action. Ping is only a diagnostic aid. For Kodi, enable its
web interface before using discovery or **Settings > Devices & services > Add
Integration > Kodi**.
[Home Assistant Kodi integration](https://www.home-assistant.io/integrations/kodi/)

For the Ugoos Kodi lifecycle, add a dedicated pfSense IoT ingress rule that
permits only the actual Home Assistant host address to each managed Ugoos
reserved LAN address on TCP/22. This SSH rule is separate from administrator
SSH and from the `172.16.99.99` Wake-on-LAN destination.

For the Kodi integration, permit only the configured direct endpoint traffic
and any separately approved discovery or callback handling that the
installation uses. Home Assistant Zeroconf discovery uses mDNS and depends on
its selected network interfaces; test discovery separately from direct address
access. The shared WoL path does not forward mDNS.
[Home Assistant Zeroconf documentation](https://www.home-assistant.io/integrations/zeroconf/)

## Replacement, moves, and recovery

When replacing a unit, disconnect the old device before transferring its
address to the replacement wired MAC. Renew the replacement lease and repeat
DNS and Home Assistant checks; a reused IP does not transfer device
credentials, host keys, or integration identity automatically.

A move to another subnet requires a mapping valid on that subnet and updates to
room documentation, DNS, firewall rules, and integration endpoints. If a new
mapping fails, restore the prior mapping or remove the new entry, return the
client to DHCP, renew, and locate its current lease before reconnecting.

pfSense is the live configuration. Record the chosen hostname, MAC, reserved
address, DNS name, and required firewall flows in the relevant room device
documentation, and back up the updated firewall configuration outside this
repository.
