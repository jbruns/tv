# Provision a Device

Use this runbook when bringing up a new Device or restoring one by re-imaging
its card. It assumes a Ugoos AM6B+ running CoreELEC 21.3 / Kodi Omega and a
Room Overlay already present in `config/rooms/<room>/room.yaml`.

## Prerequisites

On the controller:

- `uv` is installed.
- This repository is checked out.
- `.env` has been copied from `.env.example`, every key filled in, and made
  private. `COREELEC_LIFECYCLE_PUBLIC_KEY` is Home Assistant's controller key;
  the [lifecycle guide](../home-assistant/ugoos-kodi-lifecycle.md) creates it.

  ```console
  cp .env.example .env
  chmod 600 .env
  ```

- The administrator SSH key named by the Profile exists. The current Profile
  uses `~/.ssh/coreelec_admin_ed25519`, and its `.pub` file must sit beside it.
- Home Assistant has the Device's Keep-Running Hold available. Before any
  `apply` that may restart Kodi, turn the Hold on so Kodi Lifecycle does not
  stop Kodi mid-Run. Turn it off afterwards; it is persistent.

Run the commands below from the repository root.

## 1. Image the card

1. Write the CoreELEC 21.3 Omega `Amlogic-ng.arm` generic image to a microSD
   card. Start with microSD; do not move to eMMC until the Device works.
2. Put the Ugoos AM6B+ device tree at the card root as `dtb.img`.
3. If the room needs Dolby Vision, put the CoreELEC 21.3 `-ng` `dovi.ko` at
   the card root. Profile 7 FEL Dolby Vision depends on the matching image and
   module.
4. Boot the Device from the card and let CoreELEC finish its first resize and
   reboot.

## 2. Complete the first-boot wizard

Give the wizard only the answers needed to make a Manageable Device:

- Hostname: the Room Overlay hostname, for example `ugoos-theater`.
- Network: wired Ethernet with DHCP.
- SSH: enabled, with a temporary root password.

Skip the rest. The Reconciler carries Desired State after First Contact.

## 3. Clear old host keys after a re-image

A re-imaged card has a new host key at the same hostname. Remove stale entries
from the controller before First Contact:

```console
ssh-keygen -R <hostname>
ssh-keygen -R <hostname.example.lan>
ssh-keygen -R <ip-address>
```

Use only names or addresses that actually resolve to the Device.

## 4. Make First Contact

`bootstrap` is First Contact. It connects with the wizard password, installs
the administrator key, then proves key-only access in a new connection.

```console
uv run coreelec-reconciler bootstrap --room <room>
```

SSH prompts for the Device's root password. There is no stored password and no
`.env` key for one.

## 5. Plan, apply, plan

Turn on the Device's Keep-Running Hold before `apply` if the first `plan` shows
Kodi setting Changes.

```console
uv run coreelec-reconciler plan --room <room>
uv run coreelec-reconciler apply --room <room>
uv run coreelec-reconciler plan --room <room>
```

The final `plan` should report no Changes. Turn the Keep-Running Hold off when
the Run is complete, even if the Run failed.

## 6. Complete Guided Actions

After `apply` converges, complete these operator steps in order. No reboot is
needed.

1. Sync the Emby library and let Kodi finish the first library update.
2. Sign in to PM4K (`script.plexmod`) with the room's Plex account.

These are Guided Actions: they require interactive account or library state and
are not verifiable Desired State.

## 7. Survey Unmanaged State when needed

`survey` reports Device state the Profile does not declare. Use it after hand
configuration to learn what should be declared, or to compare two Devices.

Kodi must be stopped and kept stopped while surveying:

```console
ssh -i ~/.ssh/coreelec_admin_ed25519 root@<hostname> systemctl stop kodi
uv run coreelec-reconciler survey --room <room>
```

Keep the Display off while surveying, so Kodi Lifecycle does not start Kodi
again.

## Recovery

There is no rollback. The Reconciler fails forward: if a Run is interrupted or
reports a non-converged Device, fix the cause and run `apply` again.

Disaster recovery is to re-image the card and run this procedure again.

## Add a Device in another room

Add a Room Overlay at `config/rooms/<room>/room.yaml`. It names the room, the
Device hostname, the shared Profile, and any room-scoped Desired State such as
Display and audio settings.
