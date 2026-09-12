# Repository Documentation Architecture

## Status

Approved.

## Purpose

The repository documentation describes the installed home media systems and
the supported procedures for configuring them. It must represent current
operational truth rather than preserve deployment history, acceptance logs, or
temporary implementation notes.

The Theater is the first fully documented room and defines the documentation
shape that Living, Guest, and Master will follow.

## Documentation Layers

Documentation is organized into four layers:

1. The repository `README.md` is the stable entry point and room index.
2. `docs/decisions/` records durable system decisions and their constraints.
3. Shared device, network, Home Assistant, and operations guides under `docs/`
   describe reusable procedures.
4. `rooms/<room>/` records only installed equipment, physical connections,
   room-specific device settings, network placement, and required Home
   Assistant integrations.

Executable configuration remains authoritative for automated behavior:

- provisioning scripts and their `--help` output define supported operations;
- `config/` defines the shared provisioned CoreELEC baseline;
- `home-assistant/` defines deployed Home Assistant entities and lifecycle
  behavior.

Documentation links to these sources instead of restating their implementation
details.

## Historical Material

The existing `docs/superpowers/` plans and design specs are implementation
artifacts, not operator documentation. They will be removed.

Remaining documentation will not contain:

- rollout-stage terminology;
- "as of" dates or dated verification status;
- live acceptance results, report filenames, commit hashes, or screenshots;
- pending-result tables or descriptions of superseded equipment;
- speculative settings for rooms that are not configured.

Durable validation procedures may remain in shared operational guides when
they are necessary to confirm a successful installation. Room documents will
not serve as acceptance journals.

## CoreELEC Documentation

The Ugoos AM6B+ documentation has three distinct responsibilities:

1. A single CoreELEC 21.3 decision record defines the current system
   specification: selected hardware and CoreELEC platform, Dolby Vision
   dependency, always-awake network model, provisioned baseline, manual
   room-specific boundary, and migration constraints.
2. The shared device guide explains media preparation, first boot, and other
   installation steps that cannot be performed by the provisioning scripts.
3. A concise operations guide explains how to provision a new Ugoos device:
   prepare the operator environment, reserve the device address, run local
   checks, deploy the shared baseline, run post-deployment workflows, deploy
   lifecycle control, install the Home Assistant package, and inspect the
   resulting state.

The operations and device guides link to the decision record for rationale.
They do not duplicate it. Settings enforced by provisioning are summarized by
outcome and linked to executable configuration rather than documented as
manual steps.

Each room-specific Ugoos guide contains only values that cannot be shared:
hostname, network placement, HDMI connection, display-specific Dolby Vision
mode and resolution whitelist, audio-path choices, and any manual service
identity required for that room.

## Theater Documentation

The Theater room record represents the installed system:

- Ugoos AM6B+ on wired LAN, connected directly to Sony HDMI input 4;
- Sony XR-65A90J on wired IoT, configured for the required HDMI, audio,
  BRAVIA Sync, and IP Control behavior;
- Denon AVR-X4700H on wired IoT, configured for eARC and network control;
- OREI EARC-EX165-K carrying eARC/ARC and CEC between the Sony and Denon over
  CAT6/7.

The Sony guide documents Pre-Shared Key authentication under IP Control and
the Bravia Home Assistant integration. Its entity ID must match the entity
used by the Theater Ugoos lifecycle package.

The Denon guide documents the required receiver network-control setting and
the Denon Home Assistant integration used to manage and monitor receiver
state. Documentation will not claim that the Ugoos lifecycle package controls
the Denon unless the package does so.

The obsolete AVPro device guide and all rollout-stage terminology for
ARC-to-eARC replacement will be removed.

## Unconfigured Rooms

Living, Guest, and Master retain concise templates modeled on Theater. Each
template provides headings for:

- installed inventory;
- physical signal connections;
- device-specific settings;
- network placement;
- Home Assistant integrations.

Templates contain no guessed devices, addresses, settings, or validation
results.

## Network and Home Assistant Boundaries

Shared network documentation distinguishes:

- streaming devices such as Ugoos on LAN;
- Home Assistant, network-controlled displays, and receivers on IoT;
- narrow cross-network rules required for Home Assistant to reach Ugoos
  lifecycle SSH and Kodi endpoints.

The Home Assistant lifecycle guide documents the entities, SSH alias,
package installation, and operator recovery actions implemented by the
repository. It does not carry room acceptance evidence.

Sony and Denon native integrations are documented as follow-on room setup.
The Theater lifecycle package uses the Sony and Kodi entity IDs that appear in
its YAML. The Denon integration is independently required for receiver state
and control.

## Validation

The documentation change is complete when:

1. every Markdown link resolves after file additions, replacements, and
   deletions;
2. remaining operator documentation contains no rollout-stage terminology,
   dated-status, stale AVPro, acceptance-result, or superseded-equipment
   prose;
3. documented Ugoos commands and options match the script interfaces;
4. documented configuration inputs match the shipped configuration contract;
5. documented Home Assistant entities and lifecycle behavior match the
   Theater package;
6. the existing targeted Home Assistant package and CoreELEC
   configuration/settings tests pass;
7. the final diff confirms that room documents contain only connections,
   settings, network placement, and Home Assistant follow-on work.

No runtime behavior or Home Assistant template will change as part of this
documentation task unless a direct contract mismatch makes the current
documentation impossible to state truthfully. Such a mismatch requires a
separate decision before changing automation.
