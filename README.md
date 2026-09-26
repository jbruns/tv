# Home media systems

Use this README as the stable repository index. Shared procedures belong under
[`docs/`](docs/); room documents under `rooms/<room>/` record only installed
hardware, room-specific connections, network placement, and Home Assistant
integrations.

## Shared guides

- [Shared room setup runbook](docs/runbook.md)
- [Provision a Device](docs/operations/provision-a-device.md)
- [Profile reference](docs/reference/profile.md)
- [Python development](docs/development.md)
- [Network onboarding guide](docs/network/pfsense-plus-26.07-onboarding.md)
- [Kodi Lifecycle guide](docs/home-assistant/ugoos-kodi-lifecycle.md)
- [Remote guide](docs/home-assistant/remote.md)
- [Theater overview](rooms/theater/README.md)

## Room index

| Room | Status | Guide | Installed hardware record |
|---|---|---|---|
| Theater | Configured | [Theater overview](rooms/theater/README.md) | Ugoos AM6B+, Sony XR-65A90J, Denon AVR-X4700H, OREI EARC-EX165-K |
| Living | Awaiting hardware record | [Living overview](rooms/living/README.md) | None recorded |
| Guest | Awaiting hardware record | [Guest overview](rooms/guest/README.md) | None recorded |
| Master | Awaiting hardware record | [Master overview](rooms/master/README.md) | None recorded |

## LAN and IoT placement

- Streaming devices such as Ugoos stay on LAN.
- Home Assistant, network-controlled displays, and receivers stay on IoT.
- Only the documented cross-network rules needed for Home Assistant to reach
  Ugoos lifecycle SSH and Kodi endpoints should cross that boundary.

## Repository layout

```text
README.md                     Stable repository index
AGENTS.md                     Working rules for agents and contributors
CONTEXT.md                    Domain glossary
.env.example                  Named Value template; copy to .env locally
pyproject.toml                Reconciler package and tooling configuration
.python-version               Pinned Python version
uv.lock                       Frozen Python dependency lock
skills-lock.json              Pinned agent skills, restored into .agents/
.github/                      CI workflows
.githooks/                    Local pre-commit checks; enable with core.hooksPath
docs/
  adr/                        Architecture decision records
  agents/                     Agent working procedures
  home-assistant/             Shared Home Assistant, lifecycle and Remote guides
  network/                    Shared network onboarding and control rules
  operations/                 Provisioning a Device
  reference/                  Profile reference
  research/                   Retained historical records
  runbook.md                  Shared room setup workflow
  development.md              Python development
src/coreelec_reconciler/      The Reconciler
config/shared/                Profiles
config/rooms/                 Room Overlays
scripts/                      Repository Markdown and Home Assistant checks
tests/unit/                   Reconciler boundary tests
rooms/
  theater/                    Installed Theater inventory and device guides
  living/                     Living room template and device-guide index
  guest/                      Guest room template and device-guide index
  master/                     Master room template and device-guide index
home-assistant/               Deployed Home Assistant assets
```

The Reconciler provisions every Device from its Profile and Room Overlay. See
[Provision a Device](docs/operations/provision-a-device.md) to run it and the
[Profile reference](docs/reference/profile.md) to change what it declares.
