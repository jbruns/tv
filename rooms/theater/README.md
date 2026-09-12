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

1. Follow the [shared Ugoos operations guide](../../docs/operations/provision-ugoos.md), then apply the [Theater Ugoos values](devices/ugoos-am6b-plus.md).
2. Wire and configure the [Sony XR-65A90J](devices/sony-xr-65a90j.md).
3. Install the [OREI EARC-EX165-K](devices/orei-earc-ex165-k.md).
4. Connect and configure the [Denon AVR-X4700H](devices/denon-avr-x4700h.md).
