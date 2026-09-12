# Home media systems

Start with the [shared room setup runbook](docs/runbook.md), follow the shared guide for each device, then apply the selected room's wiring, settings, and validation requirements.

All rooms use **pfSense Plus 26.07** for edge routing. Follow the [shared network onboarding guide](docs/network/pfsense-plus-26.07-onboarding.md) to assign stable DHCP addresses, DNS names, and the narrow Home Assistant control rules.

Streaming devices are on LAN; Home Assistant is on IoT. The [Ugoos Kodi lifecycle guide](docs/home-assistant/ugoos-kodi-lifecycle.md) documents the always-awake CoreELEC/SSH path and Home Assistant/Sony orchestration. The [Wake-on-LAN guide](docs/network/wake-on-lan.md) records the separate experimental cross-network wake path through `172.16.99.99`; WoL is not lifecycle acceptance.

| Room | Guide | Equipment recorded |
|---|---|---|
| Theater | [Room overview](rooms/theater/README.md) | Ugoos AM6B+, Sony XR-65A90J, Denon AVR-X4700H, AVPro extender |
| Living | [Room overview](rooms/living/README.md) | To be documented |
| Guest | [Room overview](rooms/guest/README.md) | To be documented |
| Master | [Room overview](rooms/master/README.md) | To be documented |

```text
.env.example                   Shared Ugoos secret template; copy to .env
docs/                          Shared procedures for all rooms
  runbook.md                   Overall setup and validation order
  home-assistant/              Ugoos Kodi lifecycle deployment and operations
  network/                     Shared pfSense onboarding and address plan
  devices/ugoos-am6b-plus/      Reusable Ugoos/CoreELEC installation guide
rooms/
  theater/
    README.md                  Inventory, topology, and room validation
    devices/                   Instructions specific to each installed device
  living/devices/              Reserved for living-room device guides
  guest/devices/               Reserved for guest-room device guides
  master/devices/              Reserved for master-room device guides
code/                          Reusable deployment and maintenance code
config/                        Shared configuration and future room overrides
```

Shared instructions belong in `docs/`; room device documents link to them and record only room-specific choices. Reusable code and configuration have separate homes so multiple Ugoos units can use the same assets. See the [code conventions](code/README.md) and [configuration conventions](config/README.md).

Before running a Ugoos provisioning or configuration script, copy
`.env.example` to the gitignored `.env` and set the required secrets.

The original Ugoos/Sony pilot guide has been split across these documents. Its recorded verification date was **2026-09-05**; this reorganization does not establish new hardware test results. The existing pilot is assigned to `theater` based on the workspace context. Other rooms remain unconfigured in this documentation.

Shared Ugoos rollout order: CoreELEC wizard -> DHCP reservation and DNS -> shared baseline provisioning (CEC Ignore) -> restricted lifecycle gateway deployment -> Sony and Kodi Home Assistant integrations -> theater HA package -> playback configuration -> lifecycle/idle acceptance.
