---
status: accepted
---

# The Remote sends keys to whatever the Display is showing

[ADR 0024](0024-the-remote-drives-the-room-through-its-display.md) sent every
Remote key to the Display, which passed navigation to Kodi over CEC and volume
to the AVR. On the theater's hardware that worked, but it lagged, and held
keys repeated slowly, which hurt most for volume.

Timed from Home Assistant, a key sent through the Sony's `remote.send_command`
took 250–280 ms per press once several were sent, before its CEC hop to the
Device. The same key sent to Kodi with `kodi.call_method` took 5–10 ms.
Nothing can remove the Remote's own Wi-Fi hop to Home Assistant, but the rest
of the route is ours to choose.

**Each room has one key-router select. Power still goes to the Display's
`media_player`. Every other key on the TV card is bound to the select, with
the key's name as the option:**
- Volume goes straight to the AVR, 2 dB per press, and Mute toggles the AVR's
  mute. Holding a key still sends one call per repeat, so each call moves
  further.
- While Viewing, every other key goes to Kodi as a JSON-RPC `Input` call.
- Otherwise, when the Display shows its own apps or another input, keys go to
  the Display as its own remote codes, as before.

A key that arrives while the previous one is still running is dropped, not
queued, so a held key never runs on after it is released. For a moment after
the Display changes input, a key may reach the wrong device. That is accepted
([ADR 0007](0007-trusted-home-appliance-bar.md)).

ADR 0024 still holds otherwise: power switches only the Display, the Kodi
Lifecycle starts and stops Kodi, and the router is the only Remote logic in
Home Assistant.

## Considered Options

- **Bluetooth from the Remote to the Device.** Rejected. Sanytron states that
  the Astrion HA100's MTK6580 platform cannot act as a Bluetooth keyboard or
  remote. Revisit if hardware that can (Sanytron's planned HA200) replaces it.
- **The Remote's IR blaster.** Rejected. A key still travels from the Remote
  to Home Assistant and back to the Remote before the IR is sent, and nothing
  shows a held key sends true IR repeats. It saves nothing over the network,
  and it needs the Astrion integration. The theater's AVR is out of IR reach
  anyway.
- **One Kodi script per key.** Rejected. The card can bind a key to a
  `select` and pass the key's value as the option, so one select per room
  replaces about ten scripts, and it can fall back to the Display.
