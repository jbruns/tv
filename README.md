# Home media systems

Use this README as the stable repository index. Shared procedures belong under
[`docs/`](docs/); room documents under `rooms/<room>/` record only installed
hardware, room-specific connections, network placement, and Home Assistant
integrations.

## Shared guides

- [Shared room setup runbook](docs/runbook.md)
- [CoreELEC system decision](docs/decisions/ugoos-coreelec-21.3-system.md)
- [Shared Ugoos setup guide](docs/devices/ugoos-am6b-plus/coreelec-21.3.md)
- [Ugoos provisioning operations guide](docs/operations/provision-ugoos.md)
- [Network onboarding guide](docs/network/pfsense-plus-26.07-onboarding.md)
- [Ugoos Kodi lifecycle guide](docs/home-assistant/ugoos-kodi-lifecycle.md)
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
.env.example                 Shared secret template; copy to .env locally
provision-coreelec.sh        Shared CoreELEC baseline deployment
configure-coreelec-addons.sh Shared add-on validation and workflows
configure-kodi-lifecycle.sh  Shared lifecycle gateway deployment
docs/
  decisions/                  Durable system decisions
  devices/                    Shared device setup guides
  home-assistant/             Shared Home Assistant and lifecycle guides
  network/                    Shared network onboarding and control rules
  operations/                 Shared provisioning procedures
  runbook.md                  Shared room setup workflow
rooms/
  theater/                    Installed Theater inventory and device guides
  living/                     Living room template and device-guide index
  guest/                      Guest room template and device-guide index
  master/                     Master room template and device-guide index
code/                         Reusable automation documentation
config/                       Shared non-secret provisioning contract
home-assistant/               Deployed Home Assistant assets
lib/                          Reusable shell libraries
tests/                        Existing validation coverage
```
