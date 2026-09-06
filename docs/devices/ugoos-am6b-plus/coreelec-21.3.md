# Ugoos AM6B+ / CoreELEC 21.3 shared setup

**Applies to:** Ugoos AM6B+ units in any room using CoreELEC 21.3 Omega, Amlogic-ng.  
**Verification date recorded in the original pilot guide:** 2026-09-05.

Follow the [shared room runbook](../../runbook.md) and the selected [room guide](../../../README.md). This document covers image preparation, removable-media boot, initial configuration, validation, and optional eMMC migration. Display ports, audio routing, Dolby Vision mode, and room control choices belong in the room's device documents.

## Platform decision

The stable pilot will use CoreELEC 21.3 `Amlogic-ng`. Development of `-ng` has ceased, but it remains the stable CoreELEC/Kodi 21 option required for mature Profile 7 FEL support. CoreELEC 22 `Amlogic-no` now has FEL support in beta, but it uses a different kernel and Dolby module and should be evaluated later on separate removable media.

> **Do not perform an in-place `-ng` to `-no` upgrade.** When CoreELEC 22 is ready, create a fresh `-no` installation on a second microSD card, validate it, and only then migrate it to eMMC.

## Hardware required for installation

- Ugoos AM6B+ and its supplied power adapter.
- 32–64 GB, Class 10/UHS-I or better microSD card.
- microSD reader.
- Short certified Premium High Speed or Ultra High Speed HDMI cable.
- Wired Ethernet connection to the Ugoos LAN.
- Paper clip or similar non-damaging tool for the recessed recovery button.
- Optional USB keyboard for initial setup.

Do not power the Ugoos from a television USB port. Use its supplied adapter and leave ventilation space when mounting it behind the television.

## Files to download

### 1. CoreELEC image

Download exactly:

[`CoreELEC-Amlogic-ng.arm-21.3-Omega-Generic.img.gz`](https://github.com/CoreELEC/CoreELEC/releases/download/21.3-Omega/CoreELEC-Amlogic-ng.arm-21.3-Omega-Generic.img.gz)

Expected SHA-256:

```text
9edf06e752ed285e11a565584a2369a39b734df56bd0852ce37eee3d9ea9d16b
```

Do not substitute any of the following:

- `Amlogic-ne`
- `aarch64`
- a `.tar` upgrade package
- CoreELEC 22/Piers beta or nightly
- a CPM community build
- an old Ugoos dual-boot CoreELEC firmware image

### 2. Dolby Vision module for CoreELEC 21.3-ng

Download the [`dovi.ko` linked by the CoreELEC AM6B+ guide](https://dumps.tadiphone.dev/dumps/stream/dv8555-altice/-/raw/franklin-user-12-STTC.220815.001-20230722-release-keys/odm/lib/modules/dovi.ko).

CoreELEC cannot bundle this proprietary module. It is required for Dolby Vision on this installation and runs as kernel-level code. Obtain it only from the link maintained in the CoreELEC guide.

This file is for the 4.9-kernel `-ng` build. Do not use a module whose original filename begins with `5.15_2.6`; that module belongs to CoreELEC 22 `-no`.

### 3. Image-writing software

Download [balenaEtcher](https://etcher.balena.io/). Rufus or USBImager can also be used, but this procedure assumes Etcher.

### 4. Remote configuration, if needed

Download the configuration matching the model printed on the remote:

- [Ugoos UR-01 `remote.conf`](https://raw.githubusercontent.com/CoreELEC/remotes/master/AmRemote/Ugoos%20UR-01/remote.conf)
- [Ugoos UR-02 `remote.conf`](https://raw.githubusercontent.com/CoreELEC/remotes/master/AmRemote/Ugoos%20UR-02/remote.conf)

Download only the matching file and save it as `remote.conf`. This can be omitted if initial setup will use a USB keyboard or HDMI-CEC exclusively.

### 5. Device tree

Do not download the device tree separately. The required file is included in the CoreELEC image:

```text
device_trees/g12b_s922x_ugoos_am6b.dtb
```

## Verify the CoreELEC download

Linux:

```bash
sha256sum CoreELEC-Amlogic-ng.arm-21.3-Omega-Generic.img.gz
```

macOS:

```bash
shasum -a 256 CoreELEC-Amlogic-ng.arm-21.3-Omega-Generic.img.gz
```

Windows PowerShell:

```powershell
Get-FileHash .\CoreELEC-Amlogic-ng.arm-21.3-Omega-Generic.img.gz -Algorithm SHA256
```

Do not continue unless the result matches the expected SHA-256 above.

## Prepare the microSD card

1. Insert the microSD card into the computer.
2. Open Etcher.
3. Select the downloaded `.img.gz` file directly; do not decompress it.
4. Select the microSD card carefully. Etcher will erase the selected device.
5. Flash the image and allow Etcher to complete its validation.
6. Remove and reinsert the card if the `COREELEC` partition does not mount automatically.
7. If Windows asks to format another partition, cancel. The second partition uses a Linux filesystem.
8. Open the `device_trees` directory on the `COREELEC` partition.
9. Copy `g12b_s922x_ugoos_am6b.dtb` to the root of the `COREELEC` partition. Copy it; do not move the original.
10. Rename the root copy to `dtb.img`.
11. Copy the downloaded `dovi.ko` to the root.
12. If using the Ugoos remote, copy the selected configuration to the root as `remote.conf`.
13. Safely eject the card.

The relevant files at the root should be:

```text
COREELEC/
|-- dtb.img
|-- dovi.ko
|-- remote.conf        # optional
|-- kernel.img
|-- SYSTEM
`-- device_trees/
```

## Connect the room equipment

Before booting, connect the Ugoos using the room's documented HDMI topology, supplied power adapter, and wired Ethernet. Configure the display and audio equipment using the room's device guides.

For the theater pilot, follow the [room topology](../../../rooms/theater/README.md#hdmi-topology) and [Sony preparation steps](../../../rooms/theater/devices/sony-xr-65a90j.md).

## First CoreELEC boot

1. Disconnect DC power from the Ugoos.
2. Insert the prepared microSD card.
3. Press and hold the recessed recovery/reset button on the underside.
4. While continuing to hold it, reconnect DC power.
5. Release the button when the CoreELEC logo appears.
6. Allow the first boot to resize the storage partition and reboot. Do not interrupt it.

The recovery-button procedure normally activates multiboot only once. With the card inserted, subsequent starts should enter CoreELEC. Removing the card preserves access to the stock Android installation.

## CoreELEC initial wizard

Use the following baseline:

- Hostname: a unique name recorded in the room guide, such as `ugoos-theater`; do not reuse a hostname across devices.
- Network: wired Ethernet on LAN (`172.16.0.0/16`) using DHCP.
- Wi-Fi: disable after wired networking is verified.
- SSH: enable and set a unique password.
- Samba: enable temporarily only if it will be used for setup and file transfer.
- Region, language, and time zone: set as appropriate.
- Automatic CoreELEC updates: set to **Manual**.

Follow the [pfSense Plus 26.07 network onboarding guide](../../network/pfsense-plus-26.07-onboarding.md) to create a DHCP static mapping using the Ugoos wired interface's real MAC address. Keep CoreELEC on DHCP, choose an address outside the dynamic pools, renew the lease, and verify the assigned address before configuring Home Assistant. Do not use `ff:ff:ff:ff:ff:ff`; that is the Ethernet broadcast address and is not a valid host reservation.

Keep `172.16.99.99` reserved for the shared [IoT-to-LAN Wake-on-LAN path](../../network/wake-on-lan.md). Each Ugoos has its own DHCP address and real wired MAC; validate its supported wake states before adding wake automation.

If using the UR-01 over Bluetooth:

1. Open `Settings -> CoreELEC -> Bluetooth`.
2. Hold Volume Up and Volume Down together until the remote enters pairing mode.
3. Select the displayed UR-01 and pair it.

## Provision the shared CoreELEC baseline

With wired networking and SSH enabled, and **before** the room-specific Dolby Vision/audio choices below, run the shared provisioner from a Mac:

```bash
./provision-coreelec.sh --target <hostname-or-IP>
```

This installs the pinned add-on set (Emby for Kodi Next Gen, PM4K, official Kodi YouTube, Arctic Fuse 3, NextPVR, Home Assistant Weather, TMDb Helper, and their dependencies), sets the skin active, applies the Pacific/English-US regional baseline, and writes a redacted audit report. It also applies `Adjust display refresh rate: On start/stop` and `Sync playback to display: Off` below — the only baseline table row it does not set is Dolby Vision mode, which stays room-specific. See the [shared runbook's provisioning step](../../runbook.md#3-provision-the-shared-coreelec-baseline) for validation-only commands, the interactive password/passphrase prompts, backup/rollback locations, manual Emby/YouTube authorization, and restoration after a failed run, and [`config/README.md`](../../../config/README.md) for every configuration key and secret.

## Baseline Kodi/CoreELEC settings

Before testing media, change the settings level to `Expert` and confirm:

| Setting | Value |
|---|---|
| Adjust display refresh rate | **On start/stop** (applied by the provisioning step above) |
| Sync playback to display | **Off** (applied by the provisioning step above) |
| Dolby Vision mode | Use the room's display-specific choice when Dolby Vision is supported. Not set by provisioning. |

For a 2160p display, add all available 2160p modes reported by that display to Kodi's resolution whitelist. This prevents Kodi's legacy handling from forcing 25 fps and 30 fps material to 50/60 fps. Do not add modes the display does not report.

Leave custom EDID overrides and Dolby Vision colorimetry startup scripts unset during the baseline. Document any subsequently required override in the room's Ugoos guide.

Configure HDMI passthrough and supported codecs according to the complete room audio path. Keep `Sync playback to display` off because it conflicts with passthrough. The theater's ARC-only interim and final eARC settings are documented in its [Ugoos guide](../../../rooms/theater/devices/ugoos-am6b-plus.md).

## Validation before eMMC installation

Keep CoreELEC on the microSD card until all applicable shared and room-specific checks pass:

- [ ] CoreELEC reports version 21.3 Omega and the `Amlogic-ng` platform.
- [ ] Cold boot and reboot are reliable.
- [ ] Suspend and wake work repeatedly.
- [ ] The wired interface receives the intended DHCP reservation.
- [ ] The selected remote/control method works as intended.
- [ ] For an HDR-capable display, a known HDR10 title triggers its HDR picture mode.
- [ ] For a compatible Dolby Vision path, the CoreELEC Dolby Vision controls appear.
- [ ] For a compatible Dolby Vision path, a known Profile 5 title triggers Dolby Vision.
- [ ] For a compatible Dolby Vision path, a known Profile 7 FEL title plays without purple/green video.
- [ ] Supported SDR, HDR10, and Dolby Vision modes switch cleanly in both directions.
- [ ] The room's audio and other device-specific validation checks pass.

Mark unsupported formats as not applicable with the room's documented reason; record temporary limitations as blocked tests to repeat after the hardware change.

Purple/green Dolby Vision output usually indicates a missing or incorrect `dovi.ko`, or that the connected display path is not reporting TV-led Dolby Vision support.

## Optional eMMC migration

Do not migrate until the removable-media build passes the baseline validation.

1. Create a CoreELEC backup and copy it to another system.
2. SSH to the Ugoos as `root`.
3. Run:

   ```bash
   ceemmc -x
   ```

4. Select the dual-boot installation and the current removable installation as the source. Read the displayed choices instead of relying on a remembered menu number.
5. Allow the operation to complete and shut down.
6. Remove the microSD card and boot CoreELEC from eMMC.
7. In CoreELEC hardware settings, select the available `HS200/HS400` eMMC speed mode.
8. Preserve the proven 21.3 microSD card as recovery media.

Installing to eMMC alters the internal partition layout. The external-media pilot is reversible simply by removing the card; eMMC migration is not equivalently risk-free.

## Stop point

After validation and a backup, continue with the [remaining room-specific service work](../../runbook.md#7-remaining-room-specific-service-work) — the shared add-ons were already installed and configured by the [provisioning step](#provision-the-shared-coreelec-baseline) above.

## Sources

- [CoreELEC 21.3 Omega release](https://github.com/CoreELEC/CoreELEC/releases/tag/21.3-Omega)
- [CoreELEC AM6B+ `-ng` installation and Dolby Vision guide](https://discourse.coreelec.org/t/guide-s922x-j-ugoos-am6b-coreelec-ng-installation-and-faqs/51231)
- [CoreELEC for Ugoos](https://wiki.coreelec.org/coreelec%3Augoos)
- [CoreELEC remote configurations](https://github.com/CoreELEC/remotes)
