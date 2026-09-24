---
status: accepted
---

# The Kodi Lifecycle is event-driven Home Assistant blueprints

The first Kodi Lifecycle was a 932-line Home Assistant package for one
Device. It hardcoded the theater's entity IDs, polled Kodi every 30 seconds
to push it toward a computed "desired" state, and carried an observation
epoch, six error helpers, post-command status verification, and a JSON-RPC
idle probe. Almost all of that machinery came from review rounds, not from
failures seen on the hardware. It never checked the Display's input, so Idle
Power-Off could turn the Sony off while it was showing its own apps.

The Kodi Lifecycle is instead written once as Home Assistant blueprints and
instantiated per Device. It acts only on transitions:
- The Display turning on starts Kodi and selects the Device's input.
- The Display being off for the stop delay (default 10 minutes) stops Kodi.
- On Home Assistant start, it acts once on the Display's current state,
  restarting the stop delay rather than stopping Kodi immediately.

Only `off` counts as off; an `unavailable` or `unknown` Display does nothing.
Crash recovery belongs to systemd (`kodi.service` has `Restart=always`), not
to Home Assistant. Idle Power-Off fires only while Viewing, and uses the Kodi
media player's `idle` state rather than a JSON-RPC input-idle probe. The
Keep-Running Hold is the only per-Device helper. An AVR gets no automation
while it follows the Display over CEC.

Every mechanism beyond this must name the hardware scenario that failed
without it ([ADR 0007](0007-trusted-home-appliance-bar.md)).

## Considered Options

- **Keep the poll.** Rejected. The poll is what undoes a hand-stopped Kodi,
  which is why provisioning needed the Keep-Running Hold. It also drives most
  of the reachability and verification machinery. Without it, a Kodi stopped
  by hand or by the Reconciler stays stopped until the next Display
  transition.
- **A custom integration in Python.** Rejected as more code to own than
  blueprints, which are Home Assistant's built-in way to reuse logic across
  entities.
- **Remote reboot as recovery.** Rejected. No failure has been seen that a
  Kodi restart does not fix. The restricted gateway stays at `start`, `stop`,
  `status`, and an operator-invoked Restart Kodi action is stop then start.
