# Theater: Denon AVR-X4700H

Use the [theater signal topology](../README.md#signal-topology). The Denon is the theater audio system.

## Physical connections

- Connect **Denon MONITOR 1 HDMI OUT (eARC)** to the [OREI EARC-EX165-K AVR-side unit](orei-earc-ex165-k.md).
- The OREI link carries Sony return audio over CAT6/7 from **Sony HDMI IN 3 (eARC)**.
- Ugoos video stays on the direct **Sony HDMI IN 4** path.

## Network and Home Assistant

- Connect the Denon wired NIC to **IoT** and leave IP configuration on **DHCP**.
- Create a pfSense reservation and local DNS record for the receiver.
- Enable **HDMI Control**.
- Enable **ARC/eARC** for the **MONITOR 1** television path.
- Set **Network Control** to **Always On** so Home Assistant can monitor and control the receiver in standby.
- In Home Assistant, add **Denon AVR Network Receivers** under **Settings > Devices & services** using discovery or the reserved address.
- Receiver state and control are independent of the Ugoos lifecycle package.

## Source

- [Home Assistant Denon AVR Network Receivers integration](https://www.home-assistant.io/integrations/denonavr/)
