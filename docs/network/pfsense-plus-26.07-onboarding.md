# Network onboarding: pfSense Plus 26.07

**Applies to:** network-connected devices in theater, living, guest, and master.  
**Edge routing standard:** pfSense Plus 26.07.  
**Documentation reviewed:** 2026-09-05; the live firewall has not been inspected or changed.

Use DHCP on room devices and assign a fixed IPv4 address centrally with a pfSense DHCP static mapping. This is our default for devices used by Home Assistant, including playback devices and network-controlled receivers or displays. Reserve the Home Assistant host's address too if it uses DHCP. Devices intentionally kept offline, such as the theater Sony during the pilot, do not need onboarding until network control is selected.

Complete this procedure before configuring an integration with the device's address. For the Ugoos lifecycle, finish reservation and DNS before restricted lifecycle gateway deployment. Return to the [shared setup runbook](../runbook.md) afterward.

## Shared network record

The following networks and device placement were supplied by the owner. Room names describe physical locations; they do not imply separate VLANs.

| Network | IPv4 subnet | IPv6 prefix | Role |
|---|---|---|---|
| LAN | `172.16.0.0/16` | `2001:db8:1::/64` | Streaming devices in all rooms |
| IoT | `192.168.10.0/24` | `2001:db8:10::/64` | Home Assistant |

The existing cross-network Wake-on-LAN destination is **`172.16.99.99`**, backed by a static ARP entry on the LAN side of pfSense. Set this address aside exclusively for that purpose: exclude it from dynamic pools, device mappings, and manual host assignments. See the [shared Wake-on-LAN guide](wake-on-lan.md) for the IoT-to-LAN path and validation.

| Field | Recorded value |
|---|---|
| Router software target | pfSense Plus 26.07 |
| Installed version / firewall name | Pending confirmation |
| DHCP backend | Pending confirmation: Kea or ISC |
| Client interface / VLAN | LAN for streaming devices; IoT for Home Assistant. VLAN IDs and physical interfaces pending. |
| Gateway addresses | Pending for LAN and IoT; do not infer from the subnet prefixes. |
| Dynamic DHCP pool(s), including additional pools | Pending |
| Address range set aside for static mappings | Pending; inside the subnet, outside every dynamic pool |
| Local DNS service / server address / domain | Pending |
| Home Assistant host address | Pending; connected to IoT (`192.168.10.0/24`). |
| Wake-on-LAN destination | `172.16.99.99`; existing LAN static ARP entry, persistence and exact configuration to be recorded. |
| Firewall backup location | Pending; store outside this repository |

For new DHCP service, prefer Kea: Netgate identifies ISC as deprecated. Check the active backend under **System > Advanced > Networking > Server Backend**; do not change an existing backend as a routine device-onboarding step. The steps below use the pfSense webConfigurator menu names. [Netgate DHCP overview](https://docs.netgate.com/pfsense/en/latest/services/dhcp/index.html)

## 1. Choose the device identity and address

Use a unique hostname such as `ugoos-theater`, `ugoos-living`, `ugoos-guest`, or `ugoos-master`. Add a suffix if a room has multiple units. These are naming examples, not installed device records.

Choose an unused IPv4 address inside the correct interface's subnet and outside **all** its dynamic pools. Check existing mappings, leases, and documented manual assignments; a failed ping alone does not establish that an address is unused. Exclude the gateway, virtual IPs, network address, and broadcast address.

Streaming devices receive addresses in **`172.16.0.0/16`** with mask **`255.255.0.0`**. Home Assistant is on **`192.168.10.0/24`** with mask **`255.255.255.0`**. The LAN broadcast address is `172.16.255.255`; `172.16.99.99` is the dedicated static-ARP wake destination. Neither is available for a device reservation. Record the actual DHCP pools before choosing host addresses; no per-device addresses have been allocated here.

pfSense calls these entries static mappings. They do not prevent another device from manually using the same address. Netgate documents why mappings must stay outside dynamic pools, including the risk of another client receiving an in-pool address while the intended device is offline. [Netgate mapping and pool guidance](https://docs.netgate.com/pfsense/en/latest/services/dhcp/mappings-in-pools.html)

## 2. Connect and identify the actual interface

1. Select the intended Ethernet port/network or Wi-Fi SSID. Prefer wired Ethernet for Ugoos units.
2. Leave the device's IPv4 configuration on **Automatic / DHCP**.
3. Read the active interface's MAC from the device and match it against **Status > DHCP Leases** in pfSense. The lease page shows the address, MAC, and hostname and offers an action to add a static mapping. [Netgate DHCP lease status](https://docs.netgate.com/pfsense/en/latest/monitoring/status/dhcp-ipv4.html)
4. Record the MAC actually used on that network. Ethernet and Wi-Fi have different identities; use a stable Wi-Fi MAC setting for the home SSID if the device supports privacy rotation. Do not copy another unit's MAC or use `ff:ff:ff:ff:ff:ff`, the broadcast address.

If the network admits only known clients, obtain the MAC locally and create the mapping before connecting. If both interfaces are deliberately active, give each its own record and address; choose which endpoint Home Assistant will use.

## 3. Create the static mapping

Open **Services > DHCP Server**, select the correct interface, and choose **Add Static Mapping**. Alternatively, use the add-mapping action on the matching lease.

| Field | Value |
|---|---|
| MAC Address | Active interface's verified MAC |
| IP Address | Chosen unused address outside the dynamic pools; do not leave blank |
| Hostname | Unique device name |
| Description | Room, device model, and interface |
| Client Identifier | Leave blank for the normal MAC-based setup |
| Gateway / DNS overrides | Inherit the interface settings unless the device has a documented exception |
| ARP Table Static Entry | Leave unchecked for ordinary device mappings; preserve the separate `172.16.99.99` wake entry. |

Save, then apply pending changes if prompted. A MAC-only entry does not pin an address. Device DHCP mappings and the shared wake static ARP entry serve separate purposes. [Netgate DHCPv4 configuration](https://docs.netgate.com/pfsense/en/latest/services/dhcp/ipv4.html)

## 4. Renew the device's lease

Saving a mapping does not immediately replace an address already in use by the client. Renew DHCP using the device's network controls, or reconnect/reboot the device when idle. Expect an existing SSH or control connection to drop if the address changes.

Confirm the assigned IPv4 address on the device itself and compare it with the mapping. If it still has the previous address, check the interface, MAC, pool boundaries, and DHCP logs before retrying renewal. Do not clear the entire lease database to fix one client.

For an Ugoos that boots both CoreELEC and Android, verify the intended network identity in each OS if both will be used. Record any difference before relying on one mapping for both installations.

## 5. Verify local DNS

A reservation stabilizes the IPv4 endpoint; local DNS gives it a readable name. Use the site's recorded domain and DNS service.

If using **Kea with the pfSense DNS Resolver (Unbound)**, enable **DNS Registration** under **Services > DHCP Server > Settings** and check the selected interface's override. For these fixed devices, enable **Early DNS Registration** on the intended interface if names should be registered at service startup before clients request leases. Kea supports both settings and uses the configured DHCP domain. [Netgate Kea DNS registration](https://docs.netgate.com/pfsense/en/latest/services/dhcp/kea-settings.html)

If using **ISC with Unbound**, use **Services > DNS Resolver > General Settings > Register DHCP static mappings in the DNS Resolver**. With another local DNS service, create or verify the equivalent host record there. [Netgate DNS Resolver settings](https://docs.netgate.com/pfsense/en/latest/services/dns/resolver-config.html)

From a client using the same DNS service as Home Assistant, resolve the device's fully qualified name and check that it returns the reserved IPv4 address. Repeat from the Home Assistant environment where tooling permits. A name resolving correctly on a laptop does not prove the Home Assistant host uses the same resolver.

## 6. Validate Home Assistant reachability

Use the reserved IPv4 address when an integration requires an IP; use the verified DNS name when the integration supports hostnames. Record the endpoint actually configured. This guide stabilizes IPv4 only: an integration using IPv6 needs its own address/DNS validation.

Test the actual integration from Home Assistant, including a state update and a harmless control action. Ping is only a diagnostic aid. For Kodi, enable its web interface when proceeding to integration setup, then use discovery or **Settings > Devices & services > Add Integration > Kodi**. [Home Assistant Kodi integration](https://www.home-assistant.io/integrations/kodi/)

Home Assistant on IoT and streaming devices on LAN occupy different subnets. Record and permit the specific integration traffic required between them, including any device-to-Home-Assistant callbacks. Address reservations alone do not establish firewall access or discovery across networks. Home Assistant's Zeroconf discovery uses mDNS and depends on its selected network interfaces; test discovery separately from direct address access. The existing WoL path does not forward mDNS. [Home Assistant Zeroconf documentation](https://www.home-assistant.io/integrations/zeroconf/)

For the Ugoos Kodi lifecycle, add a dedicated pfSense IoT ingress rule permitting only the actual Home Assistant host address to each managed Ugoos reserved LAN address on TCP/22. Enable logging during pilot validation so failed connection attempts and unexpected sources are visible, then decide whether to keep logging according to the site's normal firewall-noise policy. This SSH rule is separate from administrator SSH and from the `172.16.99.99` Wake-on-LAN destination.

Do not add broad inter-VLAN access or WAN port forwards as an onboarding shortcut, and prohibit a broad IoT-to-LAN SSH rule. Record any needed discovery forwarding and protocol/port rules in the room device guide once the integration and network design are known.

## 7. Record and accept the installation

Copy this record into the relevant `rooms/<room>/devices/<device>.md`. Keep the shared network plan above current; do not invent addresses for rooms awaiting installation.

| Device network field | Value to record |
|---|---|
| Room / device ID / model | Actual device |
| Hostname / FQDN | Configured names |
| Connection / switch port or SSID | Active interface and attachment |
| MAC / reserved IPv4 | Observed MAC and assigned address |
| pfSense interface / VLAN / subnet | Actual client network |
| Home Assistant integration / endpoint | Configured integration and IP or name; pending if deferred |
| Required traffic / discovery handling | Rules and behavior verified for this integration; for Ugoos lifecycle, HA-host-only TCP/22 to the reserved Ugoos address with pilot logging |
| Wake-on-LAN | Device's real wired MAC, shared destination `172.16.99.99`, actual UDP port, tested power state |
| Validation date / backup location | Results and external backup location |

- [ ] The device uses DHCP and receives the recorded address after renewal and reboot.
- [ ] Its name resolves to that address through the DNS service Home Assistant uses, if DNS is part of the setup.
- [ ] Home Assistant can read state and issue the selected control action after the device restarts.
- [ ] For managed Ugoos lifecycle devices, pfSense logs show only the actual Home Assistant host using TCP/22 to the reserved Ugoos address; no broad IoT-to-LAN SSH rule exists.
- [ ] Optional suspend/wake reconnects successfully only where explicitly supported and selected.
- [ ] For WoL-capable devices, the [IoT-to-LAN wake tests](wake-on-lan.md#optional-experimental-validation) pass and Home Assistant reconnects at the reserved device address.
- [ ] Any deferred integration or wake tests are recorded as pending, with a reason.
- [ ] The room record matches pfSense, and the updated firewall configuration is backed up outside the repository.

Complete network-address checks during initial installation. If Home Assistant setup is deferred until after the playback baseline, keep its checks pending and return here during service setup.

## Replacement, moves, and recovery

When replacing a unit, disconnect the old device before transferring its address to the replacement's verified MAC. Renew the replacement's lease and repeat DNS and Home Assistant checks; a reused IP does not transfer device credentials or integration identity automatically.

A move to another subnet requires a mapping valid on that subnet and updates to the room record, DNS, firewall references, and integration endpoint. If a new mapping fails, restore the prior mapping or remove the new entry, return the client to DHCP, renew, and locate its current lease before reconnecting.

Future deployment inventory belongs in the [configuration layout](../../config/README.md). Until tooling exists, pfSense is the live configuration and room device records document the intended assignments; Markdown changes do not deploy mappings.
