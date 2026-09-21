# Reconcile the theater Ugoos

The Reconciler shadows the shell on two Resource Types on the theater Ugoos:
the Smart Playlist `NewShows.xsp`, and the Kodi settings inside three Settings
Documents — `guisettings.xml`, the Home Assistant weather add-on's
`settings.xml`, and the NextPVR client's `instance-settings-1.xml`. Both
engines still write them, holding the same values. Everything else on the
Device is the shell provisioner's, and its declaration remains the Recovery
Baseline
([ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md)).

A Smart Playlist is a document the Reconciler renders whole. A Settings
Document is not: it holds many State Addresses, almost all of them Unmanaged
State. The Reconciler changes only the State Addresses the resolved
configuration declares and preserves every other setting's identity and
value.

## Configuration

| File | Holds |
| --- | --- |
| `config/shared/ugoos-am6b-plus/coreelec-21.3/profile.yaml` | The Profile: SSH transport, the declared Smart Playlists, and the declared Settings Documents |
| `config/rooms/theater/room.yaml` | The Room Overlay: the room, the Device hostname, the Profile it uses, and the room-scoped Settings Documents |

Both files are strict: an unknown or missing key is rejected naming the key,
before any Device contact. The shell's `provision.conf` and `room.conf` beside
them are untouched and still read only by the shell.

The Device is identified by its hostname and nothing more. Every Run asks the
Device what it calls itself and refuses to continue unless the answer matches
the Room Overlay exactly, case aside, so a Run aimed at the wrong Device fails
while planning, before any mutation. Write the hostname the way the Device
reports it: CoreELEC answers with the short name, not a fully-qualified one.

## Running

```console
uv sync --frozen

# Report the Changes; mutates nothing.
uv run coreelec-reconciler plan --room theater

# Converge.
uv run coreelec-reconciler apply --room theater
```

Transport is the system `ssh` client with the existing administrator key
(`~/.ssh/coreelec_admin_ed25519` by default; change it in the Profile).

`plan` mutates nothing, including the Kodi service. It reports one Change per
Resource: a unified diff for a Smart Playlist, and for a Kodi setting a single
line naming the Settings Document, the State Address, the Observation, and the
desired value, so a Run that applies a dozen settings leaves a dozen readable
lines.

```
update /storage/.kodi/userdata/guisettings.xml#videolibrary.flattentvshows: 0 -> 1
```

## Declaring a Settings Document

A Settings Document is an entry in `settings_documents`, naming its path on
the Device, the dialect it is serialised in, and the State Addresses the
Reconciler owns inside it.

```yaml
settings_documents:
  - document: /storage/.kodi/userdata/guisettings.xml
    dialect: guisettings
    settings:
      - setting: videolibrary.flattentvshows
        value: "1"
```

### Dialects

Kodi does not serialise every Settings Document the same way, and the dialect
is **declared, never sniffed**. Sniffing a truncated or half-written document
would read it as a plausible other shape, report every declared address as
unset, plan each as a `create`, and write nodes Kodi never reads — and
Verification would then pass. A declared dialect that does not match the
document on the Device is an error naming the document, raised before Kodi is
stopped.

| Dialect | Shape | Used by |
| --- | --- | --- |
| `guisettings` | `<settings version="2"><setting id="x">y</setting></settings>` | `guisettings.xml` |
| `addon_v2` | the same, for an add-on | an add-on whose settings definition declares a version, such as `pvr.nextpvr` |
| `addon_v1` | `<setting id="x" value="y" />` | an add-on whose settings definition carries **no** version attribute, such as `weather.ha` |

`guisettings` and `addon_v2` are the same shape on the wire. They are named
apart because they are different documents, and what a future Kodi does to
one it need not do to the other.

Which dialect an add-on uses is a property of its settings definition, not of
its data. `weather.ha`'s definition has no version attribute, so Kodi loads
and writes it in the flat form
(`provision-coreelec.sh`, `set_addon_setting`).

### Declaring a setting

Add an entry to a document's `settings`. No code changes; two Device checks
do.

Declare the value `provision-coreelec.sh` already writes, exactly as it writes
it — `true` and `1` are different values to Kodi. The two declarations then
agree, the Recovery Baseline and Desired State do not diverge, and a shell run
stays a no-op. Values the shell resolves from `provision.conf` are declared as
the resolved literal.

The Profile declares twenty-four settings this way and the Reconciler holds no
list of its own, so the twenty-fifth is an entry here and no code change. Two
checks belong to declaring one: the Device must not plan it as a `create`, and
the shell must still agree after it lands. Both are acceptance scenarios 7 and
8 below.

Kodi resolves a setting ID without regard to case and reads only the direct
`<setting>` children of the document root. The Reconciler resolves a declared
setting to that one node: a differently cased node, or a copy nested under
`<category>`, is the same setting and does not survive beside it. This is what
the shell provisioner does, so the two agree on what "set" means.

A State Address is the document plus the setting, so the same setting ID in
two documents is two addresses and not a collision.

### What is not declared

Four addresses in these documents are credentials and stay the shell's until
the `.env` slice: `weather.ha`'s `ha_key`, `pvr.nextpvr`'s `pin`, and TMDb
Helper's `mdblist_apikey` and `omdb_apikey`. Two more go with them —
`weather.ha`'s `ha_server` and `pvr.nextpvr`'s `host` — because both resolve
from `HOME_ASSISTANT_URL` and `NEXTPVR_HOST`, which the shell holds in the
shared `.env` file and refuses to read from `provision.conf`. Declaring them
in a committed Profile would move that boundary, which is the `.env` slice's
decision to make, not this one's.

The surrounding values are independently meaningful, so the cohort is split
deliberately rather than held whole — the mistake
[ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md) records
for `CORE-020`..`CORE-027` was declaring a cohort *around* a credential while
leaving the credential behind, not splitting one at all.

## Declaring a room-scoped Kodi setting

A setting that describes the room's hardware rather than the class of Device
belongs in the Room Overlay's `settings_documents`, which uses the Profile's
schema exactly: a room names the document and its dialect too. The Room
Overlay declares nine settings in `guisettings.xml`: the Sony's EDID mode
whitelist, the two Dolby Vision settings, and the six passthrough flags for
the Sony eARC to OREI to Denon chain.

```yaml
settings_documents:
  - document: /storage/.kodi/userdata/guisettings.xml
    dialect: guisettings
    settings:
      - setting: audiooutput.truehdpassthrough
        value: "true"
```

The block is required. A room that adds nothing says so with an empty list;
omitting the key is rejected naming it, like every other strict-schema miss.

The Reconciler merges the two sides per document path. A document declared on
both sides contributes the settings of both, and the two sides must agree on
its dialect, because they describe one file. A room may add an address the
Profile does not declare; an address declared on both sides is an error naming
the document and the address, raised before any Device contact. The language
says a Room Overlay wins on collision, and that is what a second room will
need, but nothing needs it yet, so it is not built — merging per document is
what keeps each side's contribution separable so the winning rule can be added
later without reshaping anything.

### Transforms

Two of the nine are not written as declared, because what a human states and
what Kodi stores are different things:

| Transform | Declared | Written |
| --- | --- | --- |
| `invert` | `true` | `false` |
| `dolby_vision_mode` | `tv-led` | `0` |
| `dolby_vision_mode` | `player-led` | `1` |

```yaml
  - setting: coreelec.amlogic.disabledolbyvision
    value: "true"
    transform: invert
```

Dolby Vision is on in this room, and Kodi's address states it negatively, so
declaring `false` there would read as a lie about the room. The declaration
states the room's fact and the transform carries it to the Device. Each
transform's domain is closed: a value it cannot read is rejected naming both
the value and the transform, because passing it through would write something
Kodi ignores and then verify as converged.

`plan` names the value that will reach the Device, and the declaration it came
from, so the Room Overlay still reads as the source:

```
update /storage/.kodi/userdata/guisettings.xml#coreelec.amlogic.dolbyvisionled: 1 -> 0 (dolby_vision_mode of tv-led)
```

`videoscreen.resolution` and `audiooutput.channels` are room-scoped too and
are deliberately *not* declared. Both are opaque Kodi enum ordinals the shell
resolves by probing a running Kodi, and the resolved index is not stable
across runs against unchanged hardware, so an address declared as a literal
would report a Change on every Run and fail its own Verification. They wait
for Intent resolution.

## The Kodi restart Effect

Kodi rewrites a Settings Document from memory when it exits, so a write made
while Kodi is running is silently lost at the next shutdown. Restarting Kodi
is therefore an Effect these Changes require, not a courtesy.

The stop belongs to the Settings Document Resource Type and is never declared
per document ([ADR 0013](../adr/0013-a-settings-document-always-takes-the-kodi-stop.md)).
Whether Kodi has a particular add-on loaded is runtime state, not something a
Profile can see, so a document that declared it did not need the stop would
fail the one way nothing catches: the write lands, Kodi overwrites it on exit,
and Verification reports Convergence because it ran first.

The Run takes that Effect **once**, however many documents it writes. It stops
`kodi.service` if any planned Change requires it, **re-reads each document
after the stop** rather than trusting the Plan, writes each document once, and
starts Kodi again — including when a Change failed partway, because a Run must
never leave the television dead. The Run then reports what was and was not
applied:

```
stopping kodi.service
applied 1 of 2 changes
not applied /storage/.kodi/userdata/guisettings.xml#videolibrary.flattentvshows
starting kodi.service
```

A Run whose Plan holds only Smart Playlist Changes does not touch the service
at all: a Smart Playlist is read when it is opened.

### The Home Assistant precondition

Because applying a Kodi setting stops Kodi, **every `apply` that may carry a
Kodi setting Change needs the lifecycle override on**, not just hardware
acceptance. The lifecycle package stops Kodi whenever the Sony is off, and
will otherwise fight the Run: turn on
`input_boolean.ugoos_theater_keep_kodi_running` first and turn it off after.
The commands are in [Hardware acceptance](#hardware-acceptance) below.

Run `plan` first if you are unsure whether a Run will restart Kodi. `plan`
never touches the service.

## Hardware acceptance

A Reconciler change is accepted on the real Device, not in CI. Kodi on the
theater Ugoos is under the Home Assistant lifecycle package, which stops Kodi
whenever the Sony is off, so acceptance runs — and any `apply` carrying a Kodi
setting Change — bracketed by the operational override. Take control, test,
hand control back:

```console
set -a && . ./.env && set +a
ha() { curl -sS --max-time 15 -H "Authorization: Bearer $HOME_ASSISTANT_TOKEN" \
  -H 'Content-Type: application/json' "$HOME_ASSISTANT_URL/api/$1" "${@:2}"; }
keep=input_boolean.ugoos_theater_keep_kodi_running

# 1. Take control: keep Kodi running regardless of the Sony.
ha services/input_boolean/turn_on -d "{\"entity_id\": \"$keep\"}"
ha states/$keep                     # expect "state": "on"

# 2. Confirm Kodi is actually up before touching anything.
ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater systemctl is-active kodi

# 3. Run the acceptance scenarios (below).

# 4. Hand control back to Home Assistant.
ha services/input_boolean/turn_off -d "{\"entity_id\": \"$keep\"}"
ha states/$keep                     # expect "state": "off"
```

The override is persistent: nothing turns it off on its own, so leaving it on
silently disables the Sony-off and idle power-off behaviour until someone
notices. Turning it off is part of the run, not an afterthought — if a
scenario fails, turn it off before investigating.

The scenarios are:

1. **Fresh convergence** — remove the file on the Device, `apply`, the file is
   present and correct.
2. **No-op** — `apply` again, no Changes, the file is unchanged.
3. **Drift repair** — edit the file on the Device, `apply`, it converges.
4. **Interruption** — kill a Run mid-`apply` at several points, confirm the
   file is always either the old or the new document and never truncated, then
   `apply` again and reach Convergence. This is the property that replaces
   rollback and is the one that matters most.
5. **The Kodi settings land** — set `videolibrary.flattentvshows` to the
   wrong value in the Kodi UI (Settings > Media > Videos > Flatten TV show
   seasons), `apply`, and confirm three things: the plan named the State
   Address and both values, Kodi came back up, and the UI shows the declared
   value after the restart. Then confirm unrelated settings are untouched by
   diffing `guisettings.xml` before and after the Run, and that the skin still
   loads.
6. **Both add-on dialects land** — this is the first Run through them, so it
   has to prove them. Stop Kodi, put a wrong value into each document in its
   own dialect, start Kodi so the wrong values are loaded into memory, then
   `apply` and confirm both correct — and survive a restart, which is the half
   that catches a write Kodi discards on exit.

   ```console
   ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }
   weather=/storage/.kodi/userdata/addon_data/weather.ha/settings.xml
   nextpvr=/storage/.kodi/userdata/addon_data/pvr.nextpvr/instance-settings-1.xml

   ug systemctl stop kodi
   # addon_v1: the value is an attribute.
   ug "sed -i 's/id=\"ha_sun_entity_id\" value=\"[^\"]*\"/id=\"ha_sun_entity_id\" value=\"sun.wrong\"/' $weather"
   # addon_v2: the value is element text.
   ug "sed -i 's|<setting id=\"hostprotocol\">[^<]*</setting>|<setting id=\"hostprotocol\">http</setting>|' $nextpvr"
   ug systemctl start kodi

   uv run coreelec-reconciler apply --room theater
   ug systemctl restart kodi
   uv run coreelec-reconciler plan --room theater
   ```

   Expect the `apply` to name both documents and both values, and the `plan`
   after the restart to report `no changes`. A `plan` that reports the drift
   again is Kodi having overwritten the write from memory.
7. **No declared setting is a `create`** — the shell writes every declared
   setting, so on a provisioned Device none may plan as a `create`. A `create`
   is a misread or typo'd setting id, or a document read in the wrong dialect:
   it writes a node Kodi ignores and then verifies as converged, so nothing
   else catches it
   ([ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md)).

   ```console
   uv run coreelec-reconciler plan --room theater | grep '^create '
   ```

   Expect no output. Run this whenever the Profile or the Room Overlay
   declares a new setting or a new Settings Document.
8. **The shell and the Reconciler agree** — the value-parity invariant. One
   mismatched literal (`true` against `1`) gives two engines that revert each
   other forever, and it is the check that proves a transform produces what
   the shell produces rather than something merely plausible. After `apply`,
   run the shell and re-plan:

   ```console
   ./provision-coreelec.sh --target ugoos-theater --component baseline
   uv run coreelec-reconciler plan --room theater
   ```

   Expect `plan: no changes`. The room component is the narrower form of the
   same check, and it is the one that exercises the transforms:

   ```console
   ./provision-coreelec.sh --target ugoos-theater --component room --room theater
   uv run coreelec-reconciler plan --room theater
   ```

   The `services` component is the one that covers the two add-on documents:

   ```console
   ./provision-coreelec.sh --target ugoos-theater --component services
   uv run coreelec-reconciler plan --room theater
   ```

9. **Usable** — Kodi still starts, the playlist still opens, the weather
   widget still renders on the home screen, and NextPVR still lists channels:

   ```console
   curl -sS --max-time 15 --user "$KODI_USER:$KODI_WEB_PASSWORD" \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"Files.GetDirectory","params":
          {"directory":"special://profile/playlists/video/NewShows.xsp",
           "media":"video","limits":{"end":5}}}' \
     http://ugoos-theater:8080/jsonrpc

   curl -sS --max-time 15 --user "$KODI_USER:$KODI_WEB_PASSWORD" \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"PVR.GetChannels","params":
          {"channelgroupid":1,"limits":{"end":5}}}' \
     http://ugoos-theater:8080/jsonrpc
   ```

   A `result` with `files` (or an empty list when nothing is unwatched) means
   Kodi parsed the Smart Playlist. An `error` means it did not.

See [the lifecycle guide](../home-assistant/ugoos-kodi-lifecycle.md) for what
the override changes and for the rest of the lifecycle contract.

## Failure semantics

There is no rollback. A Run that fails partway stops, reports what it did, and
exits non-zero; running `apply` again is how the Device reaches Convergence
([ADR 0009](../adr/0009-fail-forward-and-exclusive-execution-ownership.md)).

Each file is written by staging it beside its destination as
`.<name>.tmp` and renaming it into place, so a Run killed mid-write leaves the
previous file intact rather than truncated. The staged name is fixed, so an
interrupted Run leaves one stale staged file that the next Run overwrites.

If the Reconciler cannot converge the Device at all, the recovery path is the
shell full baseline in [the provisioning guide](provision-ugoos.md), followed
by `apply` again.

## Ownership

`inventory/ownership-ledger.json` records `SKIN-025`
(`special://profile/playlists/video/NewShows.xsp`), the twenty
`guisettings.xml` addresses the Profile declares — `CORE-001`-`CORE-005`,
`CORE-008`-`CORE-019`, `SKIN-001`, `SKIN-002` and `SVC-001` — the nine the
Room Overlay declares (`ROOM-002`-`ROOM-010`), and the six add-on addresses
the Profile declares (`SVC-004`, `SVC-005`, `SVC-007`-`SVC-009` and
`SVC-011`) as shell-owned
with
`reconciler_status: accepted`, and the shell still writes them during a `core`,
`skin`, `services`, `room` or `baseline` run. That is the shadowing model:
transferring a row freezes
those shell runs
([the write-set permission freeze](shell-write-set-permissions.md)), which
would remove the Recovery Baseline this slice depends on, so ownership moves
only when the shell is deleted wholesale
([ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md)).

`SVC-002`, `SVC-003`, `SVC-006`, `SVC-010`, `SVC-012` and `SVC-013` stay
`none`: four are credentials and two are the endpoints those credentials
authenticate to, all six held in `.env`. They go together in the secrets
slice.

The two declarations agree — the Reconciler renders the same Smart Playlist
document the shell does, declares the same Kodi setting values, and its two
transforms produce exactly what the shell's inversion and mapping produce — so
a Device restored from the shell baseline converges with no Change. The
Observation is the file's content, or the setting's value, and nothing else.

The shell writes the Smart Playlist `0600` and the Reconciler writes it
`0644`, so a file the shell last wrote keeps `0600`; on a single-user
appliance where Kodi runs as root that difference is inert, and observing a
mode portably costs more than the difference is worth. Every Settings Document
is written `0600` by both.

Applying a Kodi setting reserialises the Settings Document the way the shell
provisioner does — four-space indentation, one declaration, trailing newline,
and the declared dialect's own node shape. Every setting's ID and value
survives; incidental whitespace from whoever
wrote the document last does not. Kodi reformats the document on its own terms
at the next shutdown anyway, so preserving its byte layout would buy nothing
and cost a source-offset-preserving XML writer.
