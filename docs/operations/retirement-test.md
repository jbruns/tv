# The retirement test

The Reconciler has shadowed `provision-coreelec.sh` one cohort of State
Addresses at a time, and the ownership ledger now records every address the
shell writes as accepted or deliberately retired. That is a claim about a
document, not about a Device. The retirement test is the experiment that
settles it: take a factory-fresh CoreELEC installation, converge it with the
Reconciler and nothing else, and name every way the result differs from the
appliance that is in service today.

It is the precondition for
[retiring the shell by attrition](../adr/0010-retire-the-shell-by-attrition.md).
Until it has run, the shell remains the
[Recovery Baseline](../../CONTEXT.md) and nothing is removed from it.

## What the test produces

The verdict is **a list of named gaps**, not a pass or a fail. Three
conditions have to hold, and the third is the one with content:

1. `apply` converges a factory-fresh Device with no manual step beyond the
   wizard below and `bootstrap`.
2. A second `plan` reports no Changes.
3. Every line in the survey diff classifies as one of four things:
   - a **per-Device fact** — `services.deviceuuid`, `host_mac`, a host key,
     a thumbnail cache;
   - **operator-owned** — `GUIDE-003` through `GUIDE-006`, the Plex and Emby
     account ladders that are expected to stay manual;
   - **deliberately retired** — an address ADR 0012 or
     [ADR 0019](../adr/0019-the-profiles-scope-resolves-what-the-shell-probed.md)
     records the Reconciler will never own;
   - a **genuine Profile gap** — something the appliance needs that nothing
     declares.

An empty diff is not the target and is not reachable: `services.deviceuuid`
alone guarantees one line. The gap list is the output, and each gap becomes a
slice.

## Rules

**The shell does not run.** Not once, not to check something, not to repair a
gap. A shell run silently fixes whatever the Profile missed and destroys the
only evidence the test exists to gather.

**No hand-fixing.** If `apply` fails partway, stop, record where and why, fix
it as an ordinary slice, re-image the card, and start over. Repairing the
Device by hand and carrying on makes every later finding unattributable.
Re-imaging costs one card write and a 410 MB artifact fetch; that is cheap
enough that no shortcut earns its place.

**The known-good card is the fallback.** The live installation is on microSD.
Removing the test card and putting the known-good one back restores the
theatre in one power cycle, at any point in the procedure.

## Before the test

### The baseline survey

Survey the known-good Device and keep the output. This is the thing the fresh
Device is compared against, and it can only be taken while the known-good card
is in the Device — that is, before the swap.

```console
uv run coreelec-reconciler survey --room theater > baseline.txt
```

The raw output **is not committed.** It carries `services.deviceuuid`, the
NextPVR `host_mac`, and whatever else the Device holds. Only the triaged
findings go in the repository.

Note what the report is and is not. Inside each declared Settings Document it
skips a setting Kodi marked `default="true"` — but that marker only exists in
documents `CSettingsManager` writes. Kodi's skin settings come from
`CSkinInfo::SettingsToXML`, which writes `id` and `type` and nothing else, and
peripheral data such as `cec_*.xml` is outside that writer too. Every setting
in those documents is reported whether or not anyone touched it. That is why
the test is a **diff of two surveys** rather than a reading of one.

### Set the override aside

Confirm `input_boolean.ugoos_theater_keep_kodi_running` is **off** before the
swap, and that the Sony is off. The survey refuses to run while Kodi is up,
and while either the Sony or the override is on, Home Assistant restarts a
hand-stopped Kodi within about thirty seconds.

## The procedure

### 1. Image and swap the card

Write a plain CoreELEC 21.3 image to a spare microSD, power the Device down,
remove the known-good card, and insert the spare. The known-good card is now
the recovery path; label it.

### 2. The minimal wizard

The wizard gets **three answers and no more**:

- Hostname `ugoos-theater`.
- Wired Ethernet, DHCP.
- SSH enabled, with a password.

Nothing else. No region, no language, no timezone, no update policy, no
Bluetooth pairing, no Samba. The
[device guide's wizard baseline](../devices/ugoos-am6b-plus/coreelec-21.3.md)
is the steady-state instruction for a human building a Device; here it would
hide exactly what the test is looking for. Anything the appliance needs and
the Profile does not carry has to surface as a gap, and an answer given in the
wizard cannot.

The Device keeps its DHCP reservation across the swap — same hardware, same
MAC, same lease, same name.

### 3. Clear the stale host keys

Same address and same name, different host key. An ordinary Run is
`StrictHostKeyChecking=yes` and will refuse; `bootstrap` uses `accept-new`,
which adds an unknown key but does not override a changed one. So both need
the old entries gone first:

```console
ssh-keygen -R ugoos-theater
ssh-keygen -R ugoos-theater.lan.wavebe.am
ssh-keygen -R 172.16.5.41
```

Do this again, in the other direction, when the known-good card goes back in.

### 4. First Contact

`bootstrap` prompts for the Device's root password on the terminal by design —
there is no stored password and no `.env` key for one
([ADR 0016](../adr/0016-the-reconciler-owns-first-contact.md)). A human runs
it.

```console
uv run coreelec-reconciler bootstrap --room theater
```

### 5. Take the override

`apply` will carry Kodi setting Changes, so it will stop Kodi. Home Assistant
must be told to keep out of the way first — the recipe is in
[Hardware acceptance](reconcile-theater.md#hardware-acceptance).

```console
ha services/input_boolean/turn_on -d "{\"entity_id\": \"$keep\"}"
ha states/$keep                     # expect "state": "on"
```

### 6. Plan, apply, plan

```console
uv run coreelec-reconciler plan  --room theater
uv run coreelec-reconciler apply --room theater
uv run coreelec-reconciler plan  --room theater
```

Keep all three transcripts. The first `plan` is the Reconciler's own account
of what a factory-fresh Device lacks, which is worth reading on its own. The
`apply` fetches the whole Artifact Lock, roughly 410 MB. The second `plan`
must report no Changes — that is condition 2.

### 7. Hand the override back and stop Kodi

The survey needs the opposite of what `apply` needed: Kodi down, and Home
Assistant content to leave it down.

```console
ha services/input_boolean/turn_off -d "{\"entity_id\": \"$keep\"}"
ha states/$keep                     # expect "state": "off"
```

With the override off and the Sony off, Home Assistant stops Kodi itself
within a minute or so and keeps it stopped. Confirm before surveying:

```console
ssh root@ugoos-theater systemctl is-active kodi   # expect inactive
```

### 8. Survey the fresh Device

```console
uv run coreelec-reconciler survey --room theater > fresh.txt
diff baseline.txt fresh.txt
```

### 9. Triage

Classify every line of the diff into the four categories above. Lines present
in the baseline and absent from the fresh Device are the interesting
direction: something the appliance in service holds that a Reconciler-only
build does not produce.

### 10. Restore

Power down, swap the known-good card back, clear the host keys again, and
confirm the theatre works. Turn the override off if it was left on.

## Recording the result

The outcome is one dated document in `docs/research/`: the three conditions
and whether each held, the triaged diff, and the gap list. Raw survey output
stays out of the repository. Each gap then becomes an issue, and the shell's
attrition begins in the forced order the
[write-set permission freeze](shell-write-set-permissions.md) requires — the
address leaves `provision-coreelec.sh` and its write set first, and only then
does the ledger row flip.
