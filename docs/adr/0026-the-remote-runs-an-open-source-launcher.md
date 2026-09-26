---
status: accepted
---

# The Remote runs an open-source launcher

The Remote's stock Astrion Launcher is closed source. Every limit we hit on it
had to be reverse-engineered: its RosCard cards need undocumented fields, a
held key repeats at a fixed two presses a second after a 510 ms delay
(measured), and nothing shows the AVR's volume once volume no longer passes
through the Display. None of this can be configured.

**The Remote runs [Astrion Custom
Dashboard](https://github.com/dckiller51/astrion-custom-dashboard) (GPL-3.0)
from its beta channel, installed alongside the stock launcher and set as the
home app.** Each room's hardware keys are bound in
`remotes/<room>/dashboard.json`, which is kept in git and uploaded to the
Remote. The launcher holds a persistent websocket to Home Assistant, sends
Android's own key repeat, and pops up a volume bar for the entity a volume key
targets. The beta channel is used because the volume bar is not in a stable
release yet.

This amends [ADR 0025](0025-the-remote-sends-keys-to-whatever-the-display-is-showing.md):
volume keys call the AVR's `media_player.volume_up` and `volume_down`
directly, not the key router, so the volume bar reads the AVR's level. Volume
moves in the AVR's own 0.5 dB step. Everything else in ADR 0025 holds: power
goes to the Display, and every other key goes to the key router.

Going back is `adb uninstall com.custom.astrion.debug`, which returns the
Remote to the stock launcher. Its RosCard dashboard is removed from this
repository and would have to be restored from history.

## Considered Options

- **Keep the stock launcher.** Rejected. Repeat timing and volume feedback
  cannot be changed, and every fault needs reverse-engineering.
- **vvaters/astrion-ha-dashboard.** Rejected. It needs the stock app running
  to arm the IR blaster, throttles held keys to about five a second, has no
  volume display, and has one contributor.
- **Patching the launcher's key repeat.** Not needed. Android's own repeat,
  with the AVR's 0.5 dB step, was accepted on the hardware. If it ever needs
  tuning, the change is offered upstream first, against its issue #30.
