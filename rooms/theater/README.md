# Theater

## Installed devices

| Device | Role | Guide |
|---|---|---|
| Ugoos AM6B+ | CoreELEC 21.3 Omega playback host | [Ugoos](devices/ugoos-am6b-plus.md) |
| Sony XR-65A90J | Display and Home Assistant-controlled power state | [Sony](devices/sony-xr-65a90j.md) |
| Denon AVR-X4700H | Audio system and Home Assistant-monitored receiver state | [Denon](devices/denon-avr-x4700h.md) |
| OREI EARC-EX165-K | eARC/ARC and CEC bridge between the Sony and Denon | [OREI](devices/orei-earc-ex165-k.md) |

## Signal topology

```text
Ugoos AM6B+ HDMI OUT
    -> Sony HDMI IN 4

Sony HDMI IN 3 (eARC)
    -> OREI EARC-EX165-K TV-side unit
    -> CAT6/7
    -> OREI EARC-EX165-K AVR-side unit
    -> Denon MONITOR 1 HDMI OUT (eARC)
```

## Network topology

```text
LAN: Ugoos AM6B+
IoT: Sony XR-65A90J, Denon AVR-X4700H, Home Assistant
```

## Setup order

1. Wire the installed topology and configure device and network prerequisites
   using the [Sony](devices/sony-xr-65a90j.md),
   [OREI](devices/orei-earc-ex165-k.md), [Denon](devices/denon-avr-x4700h.md),
   and [shared network](../../docs/network/pfsense-plus-26.07-onboarding.md)
   guides.
2. Provision the Ugoos shared baseline, add-ons, and restricted lifecycle
   gateway with the
   [shared Ugoos operations guide](../../docs/operations/provision-ugoos.md).
3. Configure the native Sony BRAVIA, Kodi, and Denon Home Assistant
   integrations and their documented stable entity IDs.
4. Install the Theater Home Assistant package by following the
   [shared lifecycle guide](../../docs/home-assistant/ugoos-kodi-lifecycle.md).
5. Apply the room playback settings in the [Ugoos](devices/ugoos-am6b-plus.md),
   [Sony](devices/sony-xr-65a90j.md), and
   [Denon](devices/denon-avr-x4700h.md) guides, then verify playback, device
   control, network reachability, and automations.
