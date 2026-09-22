# Reconcile the theater Ugoos

The Reconciler shadows the shell on three Resource Types on the theater Ugoos:
the eight Smart Playlists under `special://profile/playlists/video`, the four
Arctic Fuse Shortcut Nodes under `script.skinvariables`, and the Kodi settings
inside seven Settings Documents — `guisettings.xml`, the Home
Assistant weather add-on's `settings.xml`, the NextPVR client's
`instance-settings-1.xml`, TMDb Helper's `settings.xml`, Arctic Fuse 3's
`settings.xml`, Arctic Fuse's view types, and the CEC adapter's
`peripheral_data` document. Both engines
still write them, holding the same values. Everything else on the Device is
the shell provisioner's, and its declaration remains the Recovery Baseline
([ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md)).

A Smart Playlist and a Shortcut Node are documents the Reconciler renders
whole. A Settings
Document is not: it holds many State Addresses, almost all of them Unmanaged
State. The Reconciler changes only the State Addresses the resolved
configuration declares and preserves every other setting's identity and
value.

## Configuration

| File | Holds |
| --- | --- |
| `config/shared/ugoos-am6b-plus/coreelec-21.3/profile.yaml` | The Profile: SSH transport, the declared Smart Playlists, the declared Shortcut Nodes, and the declared Settings Documents |
| `config/rooms/theater/room.yaml` | The Room Overlay: the room, the Device hostname, the Profile it uses, and the room-scoped Settings Documents |
| `.env` | The values Desired State names but may not carry, shared with the shell |

Both configuration files are strict: an unknown or missing key is rejected
naming the key, before any Device contact. The shell's `provision.conf` and
`room.conf` beside them are untouched and still read only by the shell. `.env`
is the shell's too, and the Reconciler reads the same file; see
[naming a value the Profile may not hold](#naming-a-value-the-profile-may-not-hold).

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
(`~/.ssh/coreelec_admin_ed25519` by default; change it in the Profile). The
shared `.env` is read from the repository root; `--env-file PATH` names
another, and a Run that names no value in it never opens it at all.

`plan` mutates nothing, including the Kodi service. It reports one Change per
Resource: a unified diff for a document rendered whole — a Smart Playlist or a
Shortcut Node — and for a Kodi setting a single
line naming the Settings Document, the State Address, the Observation, and the
desired value, so a Run that applies a dozen settings leaves a dozen readable
lines.

```
update /storage/.kodi/userdata/guisettings.xml#videolibrary.flattentvshows: 0 -> 1
```

## Declaring a Smart Playlist

A Smart Playlist is an entry in `smart_playlists.playlists`, naming its file
inside the declared directory, the document Kodi reads, and its rules. Adding
one is an entry in the Profile and no code change.

```yaml
smart_playlists:
  directory: /storage/.kodi/userdata/playlists/video
  playlists:
    - file: NewShows.xsp
      name: New Shows
      type: tvshows
      match: all
      limit: 50
      order:
        field: dateadded
        direction: descending
      rules:
        - field: playcount
          operator: is
          value: "0"
```

A rule whose operator carries the whole test — `inprogress` with `true`, for
instance — declares `value: ""`, and the rendered document then holds no
`<value>` element, which is what Kodi writes and what the shell renders.

### Rules the calendar moves

A rule that selects on the current year cannot state a literal. The shell
renders `RecentlyReleasedMoviesCurrentAndPreviousYear.xsp` from today's date,
so a literal year in the Profile would be right until 1 January and then
disagree with the shell for the rest of the year, each engine reverting the
other. Kodi's `year` field is numeric and has no relative operator, so the
bound is declared as an offset from a named base and resolved on every read.

```yaml
rules:
  - field: year
    operator: greaterthan
    value: -2
    relative_to: current_year
```

`current_year` is the only base, and an unknown one is rejected naming it,
before any Device contact. `value` is then a whole-number offset, not a
string; anything else is rejected the same way.

### The two playlists that are absent

`RecentlyReleasedMovies90Days.xsp` and `RecentlyReleasedMoviesCurrentYear.xsp`
are **not** declared. A newer playlist superseded both, so the shell deletes
them, but a factory-fresh Device never had either file. Declaring either would
ask for a Managed Absence the Reconciler does not have and does not yet need;
they are deleted by hand, once, when the shell is deleted
([ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md#the-two-retired-addresses)).

## Declaring a Shortcut Node

A Shortcut Node is one of Arctic Fuse's widget rows, or its power menu. Each
is a JSON document the Reconciler renders whole, declared by name in
`shortcut_nodes`.

```yaml
shortcut_nodes:
  - document: /storage/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/skinvariables-shortcut-homewidgets.json
    shortcuts:
      - guid: coreelec-home-new-shows
        playlist: NewShows.xsp
        target: videos
      - guid: coreelec-power-poweroff
        path: Powerdown()
        label: "$LOCALIZE[13016]"
        icon: special://skin/extras/icons/power.png
```

A shortcut states **exactly one** of `playlist` and `path`. Stating both, or
neither, is an error naming the shortcut, before any Device contact.

- `playlist` names a Smart Playlist the Profile already declares, and supplies
  both the shortcut's path and its label. Naming one the Profile does not
  declare is an error naming the shortcut and the playlist. That is what makes
  a shortcut pointing at a retired playlist *unrepresentable* rather than
  merely detectable — nothing structural stopped it when
  `RecentlyReleasedMovies90Days.xsp` was superseded. An explicit `label`
  beside a `playlist` is an error, because the playlist already carries one.
- `path` carries a Kodi builtin, or a playlist some other add-on supplies, and
  then states its own `label`.

`icon` and `target` default to the empty string, which is what the add-on's
own default item holds. `submenu` and `widgets` hold shortcuts of exactly this
kind — the type is recursive because upstream's is — and are written only when
they hold something: the add-on creates either key lazily, so absent and empty
are one thing to it.

Every `guid` is declared, none is generated, and none is empty. The add-on
invents `guid-{random}` for an item carrying none, which would differ on every
Run and plan a Change forever. The existing ids do not derive cleanly from
anything, so they are stated as the Recovery Baseline writes them. A guid
repeated anywhere in one node file — including inside a `submenu` or
`widgets` — is an error, because the add-on finds an item by walking the whole
tree for its guid.

**The directory is never enumerated.** The Device holds six node files and
four of them are ours; `skinvariables-shortcut-homesubmenu.json` and
`-searchwidgets.json` are the skin's own, carrying generated guids. Owning the
directory would delete two working files on the first Run.

Applying a Shortcut Node restarts Kodi. The skin reads a node file when it
loads, and its own shortcut editor holds the list it read, so a file written
under a running Kodi is neither live nor safe from being written back.

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
| `json` | `{"library": {"seasons": "509"}}`, addressed by dotted path | an add-on that keeps settings as JSON, such as `script.skinvariables` |

`guisettings` and `addon_v2` are the same shape on the wire. They are named
apart because they are different documents, and what a future Kodi does to
one it need not do to the other.

`json` is the one dialect that also picks the *parser*. A document declared
`json` that does not parse as JSON, or whose top level is not an object, is an
error naming the document — never an empty parse that would plan every
declared address as a `create`. An address is a dotted path into the object,
and it names a string: a path landing on a nested object, a list or a number
is refused naming the address, because overwriting it would discard whatever
the add-on put there. An address the document does not hold reads as unset,
the same as everywhere else. Clearing one removes the key, JSON having no
empty node and `null` being a value rather than the lack of one — and when the
branch it sits under is absent, nothing is written, since building the branch
to remove nothing from it would add keys the document did not have.

Which dialect an add-on uses is a property of its settings definition, not of
its data. `weather.ha`'s definition has no version attribute, so Kodi loads
and writes it in the flat form
(`provision-coreelec.sh`, `set_addon_setting`).

### Declaring a setting

Add an entry to a document's `settings`. A setting states **exactly one** of
`value`, `from_env` and `unset`; stating two, or none, is an error naming the
setting, raised before the Device is contacted. No code changes; two Device
checks do.

Declare the value `provision-coreelec.sh` already writes, exactly as it writes
it — `true` and `1` are different values to Kodi. The two declarations then
agree, the Recovery Baseline and Desired State do not diverge, and a shell run
stays a no-op. Values the shell resolves from `provision.conf` are declared as
the resolved literal.

The Profile declares eighty-one settings this way and the Reconciler holds no
list of its own, so the eighty-second is an entry here and no code change.
Two checks belong to declaring one: the Device must not plan it as a `create`,
and the shell must still agree after it lands. Both are acceptance scenarios 7
and 8 below.

Kodi resolves a setting ID without regard to case and reads only the direct
`<setting>` children of the document root. The Reconciler resolves a declared
setting to that one node: a differently cased node, or a copy nested under
`<category>`, is the same setting and does not survive beside it. This is what
the shell provisioner does, so the two agree on what "set" means.

A State Address is the document plus the setting, so the same setting ID in
two documents is two addresses and not a collision.

### Naming a document the Profile cannot know

Kodi names a peripheral's settings document after the hardware's own
identity, so the CEC document on the theater Ugoos is `cec_CEC_Adapter.xml`:
a `cec_` bus prefix Kodi controls, and an adapter name the adapter reports. A
Profile can state the pattern but not the path.

A Settings Document therefore states **exactly one** of `document` and
`document_glob`. Stating both, or neither, is an error naming the document,
raised before the Device is contacted.

```yaml
- document_glob: /storage/.kodi/userdata/peripheral_data/cec_*.xml
  dialect: addon_v1
```

The shape is declared, never sniffed. A `*` inside a `document` is a
character in a filename and never a wildcard, because a path that quietly
became a pattern would resolve to a file nobody declared.

A pattern is resolved once per Run, before any Change is planned and so
before anything is written. The Reconciler asks the Device for the names the
directory holds and matches them in Python; no glob is ever handed to the
remote `sh`, where an unmatched pattern expands to itself and arrives as a
path that merely does not exist.

**Exactly one match.** Zero is as much an error as several, and both name the
pattern and everything it found. Two CEC documents mean a television or an
HDMI path changed and the old one was left behind, so writing either is a
coin toss — and the symptom, a television that stops answering its own
remote, is diagnosed nowhere near a Run. A Device Kodi has never run on has
no peripheral document at all and fails here too; that is a bootstrap
condition and not a CEC quirk.

Everything after resolution is ordinary: `plan` and `apply` name the document
they resolved to, never the pattern.

### Clearing an address

Some addresses must hold no value rather than a value. Arctic Fuse's home
screen is half of this: the hubs the appliance does not use own their fields,
and a stale path or target from an earlier profile still aims a tile
somewhere. Such an address is a [Cleared Address](../../CONTEXT.md), and it
states `unset`:

```yaml
- setting: optionstiles.03.path
  unset: true
```

It cannot be spelled as an empty value, and the reason is the trap this
mechanism exists to avoid. Kodi cannot store an empty string — an empty node
reads back as no value at all:

```text
written:              <setting id="a" />
observed after write: (unset)
Kodi-materialised:    (unset)
absent:               (unset)
```

A Profile declaring `value: ""` would compare `""` against an Observation of
nothing, plan a Change on every Run, and fail its own Verification forever.
`value: null` is rejected for a different reason: YAML reads a truncated
`value:` line as null too, so accepting it would make a typo silently mean
"clear this".

`unset` converges when the Device resolves no value. All three states above
are that one Observation, so:

- An address the shell has **already cleared** plans no Change, and nothing is
  written or created for it. Most of the declared clears are in this state.
- Kodi **re-materialises** a referenced skin string as an empty node at
  startup, often with a lowercased id. That node resolves no value either, so
  it does not re-plan as a Change after a restart.

Applying a clear **writes an empty node** rather than removing one. The shell
removes it and will keep doing so as the Recovery Baseline; the Device
resolves no value either way, so the two engines do not revert each other over
the difference.

The Reconciler writes no `type` attribute. `set_skin_setting` writes one, but
Kodi's own serialiser writes only `id`, plus `default` when a value is at its
default. `type` is the shell's invention; a node that already carries one
keeps it through a rewrite, which is enough.

**A Cleared Address is not a Managed Absence.** Nothing is deleted: the hub
stays gone because it resolves nothing.

**Drift injection is the only net.** The `create`-catches-a-typo check
(scenario 7) cannot reach a Cleared Address, because a typo'd id resolves no
value, matches `unset`, and reports converged forever. Declaring one therefore
carries an obligation at acceptance, scenario 11 below
([ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md),
"Rule 2 does not reach a Cleared Address").

An address the skin writes for itself is **not** declared, cleared or
otherwise. `HomeSwitcher.1104.Name`, `.Mode` and `.Icon` are the case:
Arctic Fuse rewrites them on every skin load, so declaring them cleared would
give two engines that revert each other at every Kodi restart. They are inert
while `HomeSwitcher.1104.Toggle` is empty, which is the field that decides
whether the hub renders, so the six behaviourally active fields are declared
and those three stay Unmanaged State. `provision-coreelec.sh`'s own verifier
draws the same line.

### Naming a value the Profile may not hold

Six State Addresses hold values a committed file may not carry: `weather.ha`'s
`ha_server` and `ha_key`, `pvr.nextpvr`'s `host` and `pin`, and TMDb Helper's
`mdblist_apikey` and `omdb_apikey`. They live in the shared `.env` file, which
the shell entry points read and `provision.conf` refuses to hold
([the shared secret boundary](../../config/README.md#shared-secret-boundary)).

Desired State **names** such a value rather than holding it. `from_env` is the
`.env` key:

```yaml
- setting: ha_server
  from_env: HOME_ASSISTANT_URL
```

Four of the six are credentials. The other two are the endpoints those
credentials authenticate to, and they are named too, because the boundary is
the file rather than a judgement about each key
([ADR 0014](../adr/0014-desired-state-names-a-value-it-may-not-hold.md)).

A named key that `.env` does not hold — or holds empty, which is what
`.env.example` ships — is an error naming the key, raised while the
configuration is read and before the Device is contacted:

```console
$ uv run coreelec-reconciler plan --room theater
error: …/profile.yaml names NEXTPVR_PIN, which .env does not hold
```

`.env` is bash to the shell, which sources it. The Reconciler reads it with a
strict `KEY=value` grammar instead: blank lines and `#` comments are skipped,
a value is bare, `'single-quoted'`, or `"double-quoted"`, and anything else —
an expansion, a command substitution, a duplicate key, an `export` prefix — is
rejected naming the file and the line. A misread credential would be written
to the Device and then verified against itself as converged, so a line the
grammar cannot read is never guessed at.

**A named value is never printed.** `plan` and `apply` report the address and
the key it is named by, and neither the desired value nor the Observation —
what the Device holds for `ha_key` is the token, so reporting drift the
ordinary way would print the credential while reporting it wrong:

```
update /storage/.kodi/userdata/addon_data/weather.ha/settings.xml#ha_key: named by HOME_ASSISTANT_TOKEN
```

A named value takes no transform. Nothing needs one, and a transform that
cannot read its input reports the value it could not read.

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

A transform stands between what a human declares and what Kodi stores, for a
setting where the two are different things. Two of the room's nine use one,
and so does the CEC power policy in the Profile:

| Transform | Declared | Written |
| --- | --- | --- |
| `invert` | `true` | `false` |
| `dolby_vision_mode` | `tv-led` | `0` |
| `dolby_vision_mode` | `player-led` | `1` |
| `cec_tv_off_action` | `ignore` | `36028` |

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

`cec_tv_off_action` is the same idea with a domain of exactly one. `36028` is
Kodi's localisation ID for the CEC "Ignore" action, and the shell reads it
from a variable and then rejects every value but that one — a knob with a
domain of one. Declaring `ignore` makes the shell's check the schema and
stops `36028` being a meaningless integer in a config file. It is a constant
and not a secret, so it stays here rather than in `.env`
([ADR 0014](../adr/0014-desired-state-names-a-value-it-may-not-hold.md)).

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

## The view rebuild Effect

`script.skinvariables` compiles its view types document into an XML include
inside the skin, `1080i/script-skinviewtypes-includes.xml`. Changing the
source leaves that artifact stale, and nothing else rebuilds it — a plain Kodi
restart provably does not.

A document that has such an artifact names it:

```yaml
  - document: /storage/.kodi/userdata/addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json
    dialect: json
    compiles_to: /storage/.kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml
```

When a Change touches that document, and only then, the Run writes the skin's
own trigger stub over the compiled include while Kodi is stopped, and the
restart it was taking anyway fires the rebuild
([ADR 0015](../adr/0015-trigger-the-view-rebuild-the-way-the-skin-does.md)).
There is no JSON-RPC, no `kodi-send` and no EventServer.

```
arming /storage/.kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml
stopping kodi.service
applied 2 changes
starting kodi.service
waiting for /storage/.kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml
rebuilt /storage/.kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml
verification: converged
```

The stub is **authored**, not restored: the skin ships that file untracked, so
no pristine copy exists. `Includes_Fallbacks.xml` defines `Action_BuildViews`
as an empty include and the compiled file overrides it; the stub is that
override, and the compile disarms it by replacing the file. Emptying the file
instead would resolve to the empty fallback and rebuild nothing.

Starting `kodi.service` returns when systemd started Kodi, not when the skin
loaded, so the Run waits. It reads the compiled include until the content both
differs from the stub it wrote and parses as well-formed XML. Having written
the stub, the Run knows exactly what it is waiting to stop seeing; the parse
is what catches a read taken mid-write, which returns a partial or empty file.
A Run that waits four minutes without seeing a rebuild fails naming the
artifact.

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

1. **Fresh convergence** — remove `NewShows.xsp` on the Device, `apply`, the
   file is present and correct.
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
   that catches a write Kodi discards on exit. TMDb Helper's document is
   `addon_v2` as well, and every address in it is a named value, so drifting
   its `omdb_apikey` proves the named path end to end: the wrong value is
   replaced by one no committed file holds.

   ```console
   ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }
   weather=/storage/.kodi/userdata/addon_data/weather.ha/settings.xml
   nextpvr=/storage/.kodi/userdata/addon_data/pvr.nextpvr/instance-settings-1.xml
   tmdb=/storage/.kodi/userdata/addon_data/plugin.video.themoviedb.helper/settings.xml

   ug systemctl stop kodi
   # addon_v1: the value is an attribute.
   ug "sed -i 's/id=\"ha_sun_entity_id\" value=\"[^\"]*\"/id=\"ha_sun_entity_id\" value=\"sun.wrong\"/' $weather"
   # addon_v2: the value is element text.
   ug "sed -i 's|<setting id=\"hostprotocol\">[^<]*</setting>|<setting id=\"hostprotocol\">http</setting>|' $nextpvr"
   # A named value: the Reconciler restores it from .env, never from here.
   ug "sed -i 's|<setting id=\"omdb_apikey\">[^<]*</setting>|<setting id=\"omdb_apikey\">wrong</setting>|' $tmdb"
   ug systemctl start kodi

   uv run coreelec-reconciler apply --room theater
   ug systemctl restart kodi
   uv run coreelec-reconciler plan --room theater
   ```

   Expect the `apply` to name all three documents, the two held values, and
   `omdb_apikey` as `named by OMDB_API_KEY` with no value either side of it,
   and the `plan` after the restart to report `no changes`. A `plan` that
   reports the drift again is Kodi having overwritten the write from memory.
7. **No declared setting, playlist or Shortcut Node is a `create`** — the
   shell writes every one of them, so on a provisioned Device
   none may plan as a `create`. A `create` is a misread or typo'd setting id,
   a document read in the wrong dialect, or a playlist or node file named
   wrongly: it
   writes a document Kodi ignores and then verifies as converged, so nothing
   else catches it
   ([ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md)).

   ```console
   uv run coreelec-reconciler plan --room theater | grep '^create '
   ```

   Expect no output. Run this whenever the Profile or the Room Overlay
   declares a new setting, a new Settings Document, or a new playlist.
8. **The shell and the Reconciler agree** — the value-parity invariant. One
   mismatched literal (`true` against `1`) gives two engines that revert each
   other forever, and it is the check that proves a transform produces what
   the shell produces rather than something merely plausible. For the Smart
   Playlists it is the whole risk: the Reconciler renders each document whole,
   so a single differing attribute is a file the two engines rewrite past each
   other on every Run. After `apply`, run the shell and re-plan:

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

   The `skin` component is the one that covers the playlists and the
   Arctic Fuse document:

   ```console
   ./provision-coreelec.sh --target ugoos-theater --component skin
   uv run coreelec-reconciler plan --room theater
   ```

   The `cec` component is the one that covers the CEC power policy, and it is
   the one that proves `cec_tv_off_action` produces what the shell produces:

   ```console
   ./provision-coreelec.sh --target ugoos-theater --component cec
   uv run coreelec-reconciler plan --room theater
   ```

9. **Usable** — Kodi still starts, every playlist still opens, the weather
   widget still renders on the home screen, NextPVR still lists channels, and
   TMDb Helper still returns ratings. The last four are what the six named
   values buy: each one is a live endpoint or the credential that reaches it,
   so a value written wrongly shows up as a widget that does not render rather
   than as a failed Run. Ask Kodi for each playlist in turn:

   ```console
   for xsp in InProgressMovies90Days InProgressShows90Days \
              RecentlyAiredEpisodes30Days \
              RecentlyReleasedMoviesCurrentAndPreviousYear \
              TraktPopularTVShows TraktWeekendBoxOffice NewShows NewMovies; do
     echo "== $xsp"
     curl -sS --max-time 15 --user "$KODI_USER:$KODI_WEB_PASSWORD" \
       -H 'Content-Type: application/json' \
       -d '{"jsonrpc":"2.0","id":1,"method":"Files.GetDirectory","params":
            {"directory":"special://profile/playlists/video/'"$xsp"'.xsp",
             "media":"video","limits":{"end":5}}}' \
       http://ugoos-theater:8080/jsonrpc
   done

   curl -sS --max-time 15 --user "$KODI_USER:$KODI_WEB_PASSWORD" \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"PVR.GetChannels","params":
          {"channelgroupid":1,"limits":{"end":5}}}' \
     http://ugoos-theater:8080/jsonrpc
   ```

   A `result` with `files` (or an empty list when nothing is unwatched) means
   Kodi parsed the Smart Playlist. An `error` means it did not.
10. **No named value is anywhere it should not be** — the whole point of
    naming. Capture a Run's output and search it for each of the six values,
    and search what the Reconciler commits:

    ```console
    set -a && . ./.env && set +a
    uv run coreelec-reconciler plan --room theater > /tmp/run.log 2>&1
    for value in "$HOME_ASSISTANT_URL" "$HOME_ASSISTANT_TOKEN" \
                 "$NEXTPVR_HOST" "$NEXTPVR_PIN" \
                 "$MDBLIST_API_KEY" "$OMDB_API_KEY"; do
      grep -qF -- "$value" /tmp/run.log && echo "LEAKED in output"
      git -C . grep -qF -- "$value" && echo "LEAKED in the tree"
    done
    rm -f /tmp/run.log
    ```

    Expect no output at all. Run it again after an `apply`, which prints more.
11. **Every Cleared Address is the id the skin actually reads** — and this is
    the only thing that proves it. Scenario 7 catches a typo because a wrong
    id has no node and plans a `create`. A Cleared Address inverts that: a
    typo'd id resolves no value, matches `unset`, and reports converged
    forever. So **set every declared `unset` address to a junk value and watch
    `apply` clear them all**. Run it whenever a slice declares a new one.

    Kodi must be stopped for the injection and started again before the Run,
    so the junk reaches memory — otherwise Kodi rewrites the document from
    memory on the next exit and the Run proves nothing.

    ```console
    ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }
    skin=/storage/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml

    # Every id declared `unset` in the Profile, read from the Profile itself
    # so the list cannot drift away from what is declared.
    cleared=$(uv run python -c '
    import sys, yaml
    for d in yaml.safe_load(open(sys.argv[1]))["settings_documents"]:
        if "skin.arctic.fuse.3" not in d["document"]:
            continue
        for s in d["settings"]:
            if s.get("unset"):
                print(s["setting"])
    ' config/shared/ugoos-am6b-plus/coreelec-21.3/profile.yaml)

    ug systemctl stop kodi
    ug "cp $skin ${skin}.before"
    for id in $cleared; do
      ug "python3 - <<PY
    import xml.etree.ElementTree as ET
    t = ET.parse('$skin'); r = t.getroot()
    n = next((x for x in r if (x.get('id') or '').casefold() == '$id'.casefold()), None)
    if n is None:
        n = ET.SubElement(r, 'setting'); n.set('id', '$id')
    n.text = 'junk-$id'
    t.write('$skin')
    PY"
    done
    ug systemctl start kodi && sleep 20

    uv run coreelec-reconciler plan  --room theater
    uv run coreelec-reconciler apply --room theater
    ug systemctl restart kodi && sleep 20
    uv run coreelec-reconciler plan  --room theater
    ```

    Expect the `plan` to name **every** declared `unset` address as
    `junk-… -> (cleared)` with none missing, the `apply` to converge, and the
    `plan` after the restart to report `no changes`. An address that does not
    appear in the first `plan` is an id nothing wrote to, which means the
    injection missed it; an address that reappears in the last `plan` is one
    Kodi or the skin writes for itself and must not be declared at all.

    Then confirm the skin agrees: the home screen shows the TV Shows, Movies,
    Plex, PVR and Add-ons hubs, the 1104 hub is still absent, the weather tile
    renders, and the NowPlaying, Settings and SystemInfo tiles are present. A
    junk value the Reconciler cleared but the skin never read would pass every
    command above and show up only here.
12. **The CEC power policy lands, and the glob refuses a second document** —
    the two halves of the first Run that resolves a document by pattern. A
    glob matching one file is indistinguishable from a literal path, so a
    successful Run alone proves nothing about the capability, and the second
    half is not optional.

    Kodi must be stopped for the injection and started again before the Run,
    so the wrong values reach `m_settings`; `CPeripheral::PersistSettings`
    rebuilds this document from memory when Kodi exits, which is also why the
    final `plan` comes after a full stop and start and not straight after
    `apply` ([ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md)).

    ```console
    ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }
    dir=/storage/.kodi/userdata/peripheral_data
    cec=$(ug "ls $dir/cec_*.xml")   # expect exactly one path

    ug systemctl stop kodi
    ug "sed -i 's/id=\"activate_source\" value=\"[^\"]*\"/id=\"activate_source\" value=\"1\"/;
                s/id=\"standby_pc_on_tv_standby\" value=\"[^\"]*\"/id=\"standby_pc_on_tv_standby\" value=\"13011\"/' $cec"
    ug systemctl start kodi && sleep 20

    uv run coreelec-reconciler apply --room theater
    ug systemctl restart kodi && sleep 20
    uv run coreelec-reconciler plan --room theater
    ```

    Expect the `apply` to name the **resolved** path and not the pattern, and
    `standby_pc_on_tv_standby` as `13011 -> 36028 (cec_tv_off_action of
    ignore)`. Expect the final `plan` to report `no changes`; drift reported
    again is Kodi having rebuilt the document from memory over the write.

    Then prove the refusal, and put the Device back:

    ```console
    ug "cp $cec $dir/cec_Decoy.xml"
    uv run coreelec-reconciler plan --room theater   # expect exit 1
    ug "rm $dir/cec_Decoy.xml"
    uv run coreelec-reconciler plan --room theater   # expect no changes
    ```

    Expect the refusing `plan` to name the pattern and **both** matches, to
    mention no Change at all, and to leave the Kodi service alone: resolution
    happens before anything is planned, so a second document stops the whole
    Run and not just this cohort.

    Finally, confirm the policy on the hardware, which is the only thing that
    proves the five values mean what they say. **Someone has to be in the
    room with the remote for this.** Turn the Sony off and confirm the Ugoos
    keeps running and Kodi is still up; turn it back on and confirm the Sony's
    remote still drives Kodi, which is the CEC navigation the policy keeps.

    ```console
    ug systemctl is-active kodi     # with the Sony off: expect "active"
    ```

13. **The Shortcut Nodes and the view types land, and the views rebuild** —
    three things at once, because the rebuild is what makes the view types
    visible and a Run carrying either takes the same Kodi stop.

    Stop Kodi, corrupt one shortcut's `path` and one view type, start Kodi,
    and watch `apply` correct both and rebuild.

    ```console
    ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }
    nodes=/storage/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3
    views=/storage/.kodi/userdata/addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json
    include=/storage/.kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml

    ug "md5sum $nodes/skinvariables-shortcut-homesubmenu.json \
                $nodes/skinvariables-shortcut-searchwidgets.json"

    ug systemctl stop kodi
    ug "sed -i 's|special://profile/playlists/video/NewShows.xsp|special://profile/playlists/video/Wrong.xsp|' \
        $nodes/skinvariables-shortcut-homewidgets.json"
    ug "sed -i 's/\"seasons\": \"509\"/\"seasons\": \"55\"/' $views"
    ug systemctl start kodi && sleep 20

    uv run coreelec-reconciler apply --room theater
    ```

    Expect the `apply` to name both documents, to print `arming`, `waiting
    for` and `rebuilt` for the compiled include, and to end `verification:
    converged`. Then confirm the three things a Run cannot confirm for itself:

    ```console
    # The skin's own two node files are untouched: the directory is never
    # enumerated. Expect the same digests as before the Run.
    ug "md5sum $nodes/skinvariables-shortcut-homesubmenu.json \
                $nodes/skinvariables-shortcut-searchwidgets.json"

    # The rebuild disarmed itself by overwriting the stub.
    ug "grep -c Action_BuildViews $include"     # expect 0
    ```

    Finally, **someone has to look at the screen**: open a TV show and confirm
    the season and episode views render the way they are meant to. That is the
    whole point of `509` and `549`, and nothing on the command line shows it.

    Then the parity half, which covers all six addresses at once:

    ```console
    ./provision-coreelec.sh --target ugoos-theater --component skin
    uv run coreelec-reconciler plan --room theater
    ```

    Expect `plan: no changes`, and expect scenario 7 to stay clean — the shell
    writes all six, so none may plan as a `create`.

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

`inventory/ownership-ledger.json` records the eight declared Smart Playlists
(`SKIN-019`-`SKIN-026`), the twenty
`guisettings.xml` addresses the Profile declares — `CORE-001`-`CORE-005`,
`CORE-008`-`CORE-019`, `SKIN-001`, `SKIN-002` and `SVC-001` — the nine the
Room Overlay declares (`ROOM-002`-`ROOM-010`), the twelve add-on addresses
the Profile declares (`SVC-002`-`SVC-013`), the Arctic Fuse home screen
(`SKIN-003`-`SKIN-010`), the four Shortcut Nodes (`SKIN-011`-`SKIN-014`), the
two view types (`SKIN-015`, `SKIN-016`), the view rebuild (`EFFECT-004`), and
the CEC power policy (`CEC-001`-`CEC-005`) as
shell-owned
with
`reconciler_status: accepted`, and the shell still writes them during a `core`,
`cec`, `skin`, `services`, `room` or `baseline` run. `SKIN-027` and `SKIN-028`,
the
two superseded playlists, stay `retired` and are not declared anywhere. That
is the shadowing model:
transferring a row freezes
those shell runs
([the write-set permission freeze](shell-write-set-permissions.md)), which
would remove the Recovery Baseline this slice depends on, so ownership moves
only when the shell is deleted wholesale
([ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md)).

`SKIN-003`-`SKIN-010` are forty-four addresses in one document, twenty-eight
valued and sixteen cleared. The shell writes forty-seven: the three it clears
and the Reconciler does not declare are `HomeSwitcher.1104.Name`, `.Mode` and
`.Icon`, which Arctic Fuse rewrites for itself. The shell removes them and the
skin puts two of them straight back, which is why its own verifier does not
check them; the Reconciler is silent about them for the same reason, and they
stay Unmanaged State.

`SVC-002`, `SVC-003`, `SVC-006`, `SVC-010`, `SVC-012` and `SVC-013` are the
six named values. Both engines read them from the same `.env`, so the two
declarations agree there for the same reason they agree everywhere else: there
is one source.

`CEC-001`-`CEC-005` are the only addresses in a document neither engine names
literally. The shell finds it with `*CEC*.xml` and the Profile declares
`cec_*.xml`; both resolve the same file on this Device, so value parity is
unaffected, and the narrower pattern is the deliberate departure ADR 0012
records.

The two declarations agree — the Reconciler renders the same Smart Playlist
document the shell does, declares the same Kodi setting values, and its three
transforms produce exactly what the shell's inversion, mapping and CEC check
produce — so
a Device restored from the shell baseline converges with no Change. The
Observation is the file's content, or the setting's value, and nothing else.

The shell writes the Smart Playlist `0600` and the Reconciler writes it
`0644`, so a file the shell last wrote keeps `0600`; on a single-user
appliance where Kodi runs as root that difference is inert, and observing a
mode portably costs more than the difference is worth. Every Settings Document
and every Shortcut Node is written `0600` by both.

Applying a Kodi setting reserialises the Settings Document the way the shell
provisioner does — four-space indentation, one declaration, trailing newline,
and the declared dialect's own node shape. Every setting's ID and value
survives; incidental whitespace from whoever
wrote the document last does not. Kodi reformats the document on its own terms
at the next shutdown anyway, so preserving its byte layout would buy nothing
and cost a source-offset-preserving XML writer.
