---
status: superseded by ADR-0025
---

# The Remote drives the room through its Display

A room's Remote sends every key on its TV page to the Display: the Display's
`remote` entity for navigation, playback and volume, and its `media_player`
for power and the app list. The Display carries keys to the Device over CEC,
the same path its own handset uses, and carries volume to the AVR. The Remote
never addresses Kodi or the AVR directly.

That makes the same keys work in the Display's own apps as well as in Kodi,
and the TV page needs two entities instead of five. Power on and off only
switch the Display, and the Kodi Lifecycle
([ADR 0020](0020-kodi-lifecycle-is-event-driven-home-assistant-blueprints.md))
starts and stops Kodi as usual. So the Remote adds no scripts or automations,
and the reusable part is a per-room dashboard file plus an on-remote
checklist, not a blueprint.

## Considered Options

- **Kodi scripts.** Rejected. RosCard's card can bind a key only to a
  `media_player`, `remote`, `select` or `script`, and `media_player` has no
  d-pad action. So navigating Kodi directly would need about ten
  `kodi.call_method` scripts per room, and they would do nothing while a
  Display app is showing. Revisit only if CEC pass-through proves laggy or
  drops keys on the hardware.
- **The remote's IR blaster.** Rejected until something in a room needs IR.
  It needs the Astrion integration, which nothing else does yet.
- **A remote-driven power-on sequence.** Rejected. It would duplicate what the
  Kodi Lifecycle already does on the Display's transition.
