# Reconcile the theater Ugoos

The Reconciler shadows the shell on six Resource Types on the theater Ugoos:
the eight Smart Playlists under `special://profile/playlists/video`, the four
Arctic Fuse Shortcut Nodes under `script.skinvariables`,
`/storage/.ssh/authorized_keys`, the Kodi lifecycle gateway
`/storage/.config/kodi-lifecycle`, forty Kodi add-ons, and the Kodi settings
inside nine Settings Documents — `guisettings.xml`, the Home
Assistant weather add-on's `settings.xml`, the NextPVR client's
`instance-settings-1.xml`, TMDb Helper's `settings.xml`, Arctic Fuse 3's
`settings.xml`, Arctic Fuse's view types, the CEC adapter's
`peripheral_data` document, the CoreELEC timezone cache, and CoreELEC's
`sshd.conf`. Both engines
still write them, holding the same values. Everything else on the Device is
the shell provisioner's, and its declaration remains the Recovery Baseline
([ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md)).

A Smart Playlist, a Shortcut Node, `authorized_keys` and a document shipped as
a file are documents the Reconciler renders whole. An add-on is a tree the Reconciler replaces whole,
from bytes it pinned. A Settings
Document is not: it holds many State Addresses, almost all of them Unmanaged
State. The Reconciler changes only the State Addresses the resolved
configuration declares and preserves every other setting's identity and
value.

## Configuration

| File | Holds |
| --- | --- |
| `config/shared/ugoos-am6b-plus/coreelec-21.3/profile.yaml` | The Profile: the platform identity, the Profile Constants, the addresses, SSH transport, and who may log in |
| `config/shared/ugoos-am6b-plus/coreelec-21.3/playlists.yaml` | The Profile's declared Smart Playlists |
| `config/shared/ugoos-am6b-plus/coreelec-21.3/shortcuts.yaml` | The Profile's declared Shortcut Nodes |
| `config/shared/ugoos-am6b-plus/coreelec-21.3/documents.yaml` | The Profile's declared documents shipped as files |
| `config/shared/ugoos-am6b-plus/coreelec-21.3/settings.yaml` | The Profile's declared Settings Documents |
| `config/shared/ugoos-am6b-plus/coreelec-21.3/documents/` | The sources of the documents shipped as files, one file per document |
| `config/shared/ugoos-am6b-plus/coreelec-21.3/addons.yaml` | The Artifact Lock: one record per declared add-on — its version, its URL, and the SHA-256 of the bytes that URL must return |
| `config/rooms/theater/room.yaml` | The Room Overlay: the room, the Device hostname, the Profile it uses, and the room-scoped Settings Documents |
| `.env` | The values Desired State names but may not carry, shared with the shell |

All three configuration files are strict: an unknown or missing key is
rejected naming the key, before any Device contact. The shell's `provision.conf` and
`room.conf` beside them are untouched and still read only by the shell. `.env`
is the shell's too, and the Reconciler reads the same file; see
[naming a value the Profile may not hold](#naming-a-value-the-profile-may-not-hold).

The Device is identified by its hostname and nothing more. Every Run asks the
Device what it calls itself and refuses to continue unless the answer matches
the Room Overlay exactly, case aside, so a Run aimed at the wrong Device fails
while planning, before any mutation. Write the hostname the way the Device
reports it: CoreELEC answers with the short name, not a fully-qualified one.

## The platform Guard

A hostname says which Device answered. It does not say what that Device *is*,
so a second Guard runs beside it, before anything is planned.

The Profile declares what a Device in it is claimed to be, and nothing about
how to check it:

```yaml
platform:
  id: coreelec
  version: "21.3"
  device: Amlogic-ng
  release_contains: Amlogic-ng.arm-21.3-Omega
```

Which file holds which key is the Reconciler's business. A Profile that named
paths and grep patterns would be the only block declaring mechanism, and the
only one naming a path outside a Resource. The block is required; a Profile
missing it is an error before any Device contact.

`/etc/os-release` is a defined `KEY=value` document, so the Reconciler
**parses it and asserts on keys**: `ID`, `VERSION_ID` and `COREELEC_DEVICE`,
with surrounding quotes stripped. The shell instead concatenates
`/etc/os-release` and `/etc/release` and greps the blob case-insensitively for
`coreelec` — which passes on a Device whose `ID` is something else entirely,
because `coreelec` is also in `HOME_URL` and `BUG_REPORT_URL`. `/etc/release`
is genuinely one line of free text (`Amlogic-ng.arm-21.3-Omega`), so
`release_contains` stays a substring match.

A refusal names the key, what the Profile declares and what the Device holds:

```console
$ uv run coreelec-reconciler plan --room theater
error: /etc/os-release on ugoos-theater holds VERSION_ID=22.0 and the Profile
declares 21.3: refusing to reconcile it
```

The sound card is part of the platform too:

```yaml
  sound_card: AMLAUGESOUND
```

The Profile's audio device strings embed it as `CARD=AMLAUGESOUND`, and Kodi
given a card the Device does not have falls back to another output without
complaint — which presents as "no audio", a long way from a card name.
Re-reading `guisettings.xml` after a write proves only that the Reconciler
wrote what it meant to, so the Guard reads `/proc/asound/cards` instead, which
needs no running Kodi, and refuses unless the declared id is one of the
bracketed card ids listed there:

```console
error: /proc/asound/cards on ugoos-theater lists AMLAUGESOUND and the Profile
declares AMLMESONAUDIO: refusing to reconcile it
```

Nothing here is derived from the Profile's directory name.
`ugoos-am6b-plus/coreelec-21.3` is for humans; the Device's own model string
is `UGOOS AM6`, with no "plus" in it. The device-tree model is not checked at
all: `PLAT-002` is retired, and
[ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md) records
why.

## Profile Constants

A fact more than one State Address records is stated once:

```yaml
constants:
  timezone: America/Los_Angeles
```

and an address takes it with `from_profile`, which is a fourth arm beside
`value`, `from_env` and `unset`:

```yaml
  - setting: locale.timezone
    from_profile: timezone
```

The timezone is the case that forced it. Kodi's `locale.timezone` and the
operating system's `/storage/.cache/timezone` are two records of one fact, and
two declarations are two things free to diverge — with a symptom that is
quiet, Kodi showing one zone and the shell another.

The block is required; a Profile with nothing to share states an empty
mapping. A `from_profile` naming a constant the Profile does not declare is an
error naming both, raised before the Device is contacted.

This is **not** interpolation inside `value`, and `value` is never scanned for
one. Kodi values routinely carry `$LOCALIZE[...]` and `$INFO[...]`, so sigils
in a value are normal here and scanning a literal would change the meaning of
one that legitimately holds `${`.

A Profile Constant is also not a Named Value. A Named Value comes from `.env`,
reaches no committed file and is never printed
([ADR 0014](../adr/0014-desired-state-names-a-value-it-may-not-hold.md)); a
Profile Constant is committed, reviewable and printed by a Run like any other
value. `from_profile` and `from_env` stay distinct keys for exactly that
reason.

## Device addresses

A few State Addresses are not declared as Resources but are still paths the
Reconciler must know: the CoreELEC timezone cache, `sshd.conf`, the add-on
directory, Kodi's add-on database, and Kodi's list of the add-ons it ships
with. The Profile names them:

```yaml
addresses:
  timezone_cache: /storage/.cache/timezone
  sshd_conf: /storage/.cache/services/sshd.conf
  addons: /storage/.kodi/addons
  addon_database: /storage/.kodi/userdata/Database/Addons33.db
  addon_manifest: /usr/share/kodi/system/addon-manifest.xml
```

The key is a role the Reconciler knows; the value is where that role lives on
this platform. Which Effect a role takes stays in code — a Settings Document
at `timezone_cache` always takes the timezone Effect, and one at `sshd_conf`
always restarts the transport — because that is mechanism, not declaration
([ADR 0013](../adr/0013-a-settings-document-always-takes-the-kodi-stop.md)).
What changes across CoreELEC releases is the path, and the path is the part
the Profile holds.

`addon_manifest` is Kodi's own list of the add-ons it installs with itself.
They live under the same address as every other add-on and nobody pinned
them, so without this file a Run would report seven perfectly ordinary
metadata scrapers as strays; see
[add-ons nobody declared](#add-ons-nobody-declared).

`addon_database` is the case that forced the block. Kodi versions its add-on
database by schema (`Addons33.db` on Kodi 21, a different number on the next
major release), so a Reconciler with the name compiled in silently stops
matching on an upgrade. The Profile states it, and the platform Guard already
refuses a Device whose version the Profile does not claim.

The block is required and every key in it is required. A missing or unknown
key is an error naming the key, before any Device contact.

## Running

```console
uv sync --frozen

# Meet a Device that has no administrator key yet. Once per Device.
uv run coreelec-reconciler bootstrap --room theater

# Report the Changes; mutates nothing.
uv run coreelec-reconciler plan --room theater

# Converge.
uv run coreelec-reconciler apply --room theater

# Report what the Device holds that the Profile does not; needs Kodi stopped.
uv run coreelec-reconciler survey --room theater
```

Transport is the system `ssh` client with the existing administrator key
(`~/.ssh/coreelec_admin_ed25519` by default; change it in the Profile). An
ordinary Run is key-only and `StrictHostKeyChecking=yes`: a changed host key
means the Device was reimaged or something is wrong, and refusing is the
right answer. The shared `.env` is read from the repository root;
`--env-file PATH` names
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

## First Contact

CoreELEC's first-boot wizard offers to enable SSH, and its final step offers
to change the root password — an offer that is easy to accept as-is. A
freshly imaged Device therefore sits on the home network with SSH open on a
default password, and closing that window is the first thing anyone would
want to do. The Reconciler does it
([ADR 0016](../adr/0016-the-reconciler-owns-first-contact.md)).

`bootstrap` is a separate entry point, not a fallback on the ordinary Run. It
does three things and no others:

1. Connects with `PubkeyAuthentication=no` and
   `StrictHostKeyChecking=accept-new`. The system `ssh` client prompts for
   the Device's root password on the terminal — there is no `sshpass`, no
   stored password, and no `.env` key for one. Trust on first use is correct
   for the connection that *is* first use, and it belongs to this entry point
   alone.
2. Appends the administrator public key to `/storage/.ssh/authorized_keys`,
   matching on the key material so a second attempt adds nothing.
3. Proves key-only authentication in a **new** connection, by asking the
   Device its name — which is also the Guard every ordinary Run runs first,
   so First Contact reports success on one Device only.

```console
$ uv run coreelec-reconciler bootstrap --room theater
first contact ugoos-theater (room theater, profile ugoos-am6b-plus/coreelec-21.3)
installing coreelec-admin@jbmbp in /storage/.ssh/authorized_keys; ssh will ask for the Device's root password
root@ugoos-theater's password:
installed the administrator key
ugoos-theater answers to a key-only connection: run apply to converge it
```

Nothing else happens here. Hardening the daemon, declaring who else may log
in, and everything the Profile says are the ordinary Run's.

It is a separate entry point rather than a fallback because in steady state
password authentication is disabled, so a Run that fell back would turn every
genuine key failure — a moved key file, a wrong identity path — into three
password prompts against a daemon that refuses all of them, and a confusing
timeout in place of a clear error.

## Declaring who may log in

`/storage/.ssh/authorized_keys` is declared **whole**: the document is the
complete set of entries, and a key nobody declares is removed. That is what
lets a revoked key actually be revoked — the shell appends each entry if
absent, so its file can only ever grow.

```yaml
authorized_keys:
  document: /storage/.ssh/authorized_keys
  entries:
    - comment: homeassistant-ugoos-kodi-lifecycle
      from_env: COREELEC_LIFECYCLE_PUBLIC_KEY
      forced_command: /storage/.config/kodi-lifecycle
```

The **administrator entry is not declared and cannot be**. It is derived from
the public half of the identity the Run is already authenticating with,
because a Profile that can name an administrator key is a Profile that can
name the wrong one and lock the Reconciler out of its own Device. Its `.pub`
file must be beside the identity; a Run that cannot read it fails naming the
file, before any Device contact.

Every entry a Profile *does* declare carries a `forced_command`, which is the
only program that key may ever run. There is no arm for declaring a second
unrestricted key: that arm would be the one that quietly grants a Device to
anybody a Profile names. The entry is written in the `restrict` form alone —
`restrict` already implies no agent forwarding, no port forwarding, no pty,
no user rc and no X11 forwarding on OpenSSH 7.2 and later, and the Device
runs 9.9. `lib/coreelec-lifecycle.sh` also renders a spelled-out fallback for
older releases, which guards a failure that cannot occur on any Device this
Profile describes.

The public key is named in `.env` rather than held. It is not a secret, so
this widens `.env` slightly beyond
[ADR 0014](../adr/0014-desired-state-names-a-value-it-may-not-hold.md)'s
framing: the file holds per-deployment values, and secrecy is a property of
some of them rather than the reason it exists.

A Change here is reported by the entries the document gains and loses. A key
blob is sixty-eight characters of base64 that nobody reads, and printing a
diff of them would bury the one fact that matters:

```
update /storage/.ssh/authorized_keys
observed entries: coreelec-admin@jbmbp, homeassistant-ugoos-kodi-lifecycle, somebody-else
desired entries: coreelec-admin@jbmbp, homeassistant-ugoos-kodi-lifecycle
```

`LIFE-001`, the forced-command wrapper the entry names, is still the shell's.
Between First Contact and the lifecycle installer that key can authenticate
and run nothing, which is safer than a key that can run anything.

## Closing the password window, and the sshd restart Effect

`/storage/.cache/services/sshd.conf` is CoreELEC's own document, and its two
keys are CoreELEC's own. `service.coreelec.settings` writes exactly this pair
from its "Disable SSH password" toggle:

```yaml
  - document: /storage/.cache/services/sshd.conf
    dialect: shell_vars
    mode: "0644"
    settings:
      - setting: SSH_ARGS
        value: "-o 'PasswordAuthentication no'"
      - setting: SSHD_DISABLE_PW_AUTH
        value: "true"
```

The mode is what CoreELEC gives it: `oe.py`'s `set_service` writes the file
with a plain `open` and no `chmod`, which is why `avahi.conf`, `crond.conf`,
`samba.conf` and `bluez.conf` are all `0644`. The shell's `0600` is the
departure, and the file holds no secret.

A Device whose wizard left the password enabled holds these same two keys
with `SSH_ARGS=""` and `SSHD_DISABLE_PW_AUTH="false"`, so hardening plans as
two Changes and never as a `create`.

Applying either restarts `sshd.service`, and **that restart drops the
connection issuing it**. This is unavoidable rather than chosen:
`ExecStart=/usr/sbin/sshd -D $SSH_ARGS` reads the option from the
environment at start; `ExecReload`'s SIGHUP makes the daemon re-exec from its
original argv, so a reload would not pick the new option up; and the daemon
is not socket-activated, so the Run's session is a child in the unit's
cgroup.

So this Effect is not the stop-and-start every other one is — a stop would
take the connection with it and leave nothing able to start it again. The
unit is restarted *after* the writes, its exit status is not read because a
restart that worked kills the connection before `systemctl` can report
anything, and what the Run reads is the connection after it:

```
restarting sshd.service
sshd.service is active and /storage/.ssh/authorized_keys is not empty
verification: converged
```

`authorized_keys` is checked with it because an empty one is the other way
the Device becomes unreachable, and after this restart there is no password
left to fall back on.

**If the Device does not answer, the Run fails hard and names the local
console.** There is no revert: a revert would have to travel over the
connection that just died. The Run is not reordered to leave Kodi playing in
that case either. A Device that cannot be reached after its own `sshd`
restarted is evidence of something wrong with the Device, the storage media,
or the way it was imaged, and that diagnosis is forced rather than softened.

```console
$ uv run coreelec-reconciler apply --room theater
error: ugoos-theater did not answer within 20s of sshd.service restarting.
Use the local console to inspect /storage/.cache/services/sshd.conf
```

The Reconciler writes `SSH_ARGS` byte for byte as CoreELEC does — the quotes
are load-bearing, because `sshd` is started as `/usr/sbin/sshd -D $SSH_ARGS`
and the option and its argument have to arrive as two words rather than
three. `SSHD_DISABLE_PW_AUTH` is written bare, like every other `shell_vars`
value; the settings add-on strips quotes when it reads it back, so `true` and
`"true"` are the same answer to it.

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
([ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md#the-retired-addresses)).

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

## Declaring a document shipped as a file

A document the Reconciler owns every byte of, whose content is not generated
from structured Desired State, is shipped as a file beside the Profile and
declared in `documents`:

```yaml
documents:
  - document: /storage/.config/kodi-lifecycle
    source: documents/kodi-lifecycle
    mode: "0700"
```

`source` is relative to the Profile directory and must stay inside it, like
`patches/<id>/`, so a Profile is copyable as a unit. A missing or unreadable
source is an error naming it when the Profile is read, before any Device
contact. `mode` is required and must be an octal mode: some of these are
programs the Device runs, and a mode nobody wrote down is how one stops being
executable. A path declared twice is an error.

The Observation is the file's content, the same as a Smart Playlist's. A
drifted file plans as an `update` with a unified diff and is replaced whole.
Nothing the Reconciler knows of reads one of these while it runs, so applying
one takes no Effect.

The only one today is the Kodi lifecycle gateway, the forced command of Home
Assistant's `authorized_keys` entry. It accepts `start`, `stop` and `status`
in `SSH_ORIGINAL_COMMAND` and nothing else, and hardcodes
`/usr/bin/systemctl` and `kodi.service`. Its source is byte for byte what
`coreelec_lifecycle_render_wrapper /usr/bin/systemctl` in
`lib/coreelec-lifecycle.sh` renders, and a boundary test re-renders it to
prove so. Kodi never reads it, so the shell's capture and restore of the Kodi
state around its install (`LIFE-003`) has nothing to shadow.

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
| `shell_vars` | `TIMEZONE=America/Los_Angeles`, addressed by key | a document the operating system reads, such as `/storage/.cache/timezone` |

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

`shell_vars` is the one dialect that is not Kodi's. It is here because the
document has exactly the property the name Settings Document describes — many
addresses in one file, owned one at a time — and because `sshd.conf` is next
and is the same shape with two keys. The read is the strict `KEY=value`
grammar `.env` uses, so a line is data and never shell syntax, and a document
outside it is an error naming the document. The rewrite is line by line:
every undeclared key keeps its line, its order and whatever comment sits
beside it. Clearing an address removes the line, because `KEY=` is the empty
string to a shell that sources the file rather than the absence of a value.

A `shell_vars` document also states its `mode`, because it is not the `0600`
every Kodi document is written with:

```yaml
  - document: /storage/.cache/timezone
    dialect: shell_vars
    mode: "0644"
```

Which dialect an add-on uses is a property of its settings definition, not of
its data. `weather.ha`'s definition has no version attribute, so Kodi loads
and writes it in the flat form
(`provision-coreelec.sh`, `set_addon_setting`).

### Declaring a setting

Add an entry to a document's `settings`. A setting states **exactly one** of
`value`, `from_env`, `from_profile` and `unset`; stating two, or none, is an
error naming the setting, raised before the Device is contacted. No code changes; two Device
checks do.

Declare the value `provision-coreelec.sh` already writes, exactly as it writes
it — `true` and `1` are different values to Kodi. The two declarations then
agree, the Recovery Baseline and Desired State do not diverge, and a shell run
stays a no-op. Values the shell resolves from `provision.conf` are declared as
the resolved literal. The one exception is declared out loud; see
[declaring a Divergent Address](#declaring-a-divergent-address).

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

### Declaring a Divergent Address

A Divergent Address is a State Address where the Profile deliberately holds a
value the Recovery Baseline **cannot produce**. The two disagree by intent
rather than by mistake, and the disagreement is written down per address:

```yaml
      - setting: general.addonupdates
        value: "2"
        divergent: >-
          the shell writes 0 or 1 from ADDON_UPDATE_MODE and cannot emit 2,
          so a shell run after an apply leaves this address changed on purpose
```

`divergent` carries the reason and nothing else. An empty reason is an error
naming the setting, and the key belongs to a setting rather than to a
document: a document-level flag would excuse every address inside it, which is
the blanket escape hatch
[ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md) refuses.

The reason this is a declaration and not a code path is acceptance scenario 8:
run the shell after an `apply`, re-plan, and expect no changes. That check
exists because one mismatched literal — `true` against `1` — gives two engines
that revert each other forever and nothing else would catch it. A Divergent
Address is the one Change scenario 8 is allowed to come back with, and the
Plan says so where it is read:

```
update /storage/.kodi/userdata/guisettings.xml#general.addonupdates: 1 -> 2
divergent: the shell writes 0 or 1 from ADDON_UPDATE_MODE and cannot emit 2, ...
```

The line is printed with the Change it explains and never on its own, so a
converged address is silent. Recovery is unaffected: the order is shell
baseline, then reconcile, so the Reconciler lands its value after the shell
laid down the older one, and the Baseline is run once rather than on a
schedule ([ADR 0010](../adr/0010-retire-the-shell-by-attrition.md)).

`general.addonupdates` was the first, in about eighty addresses, and
`services.esenabled` is the second: the shell turns the EventServer on for its
`kodi-send` view rebuild, which
[ADR 0015](../adr/0015-trigger-the-view-rebuild-the-way-the-skin-does.md)
replaced with the skin's own trigger. Home Assistant speaks JSON-RPC, and
`services.esallinterfaces` is `false`, so nothing off the Device could ever
reach it. The rest of this section is about the first.

For `general.addonupdates`, Kodi's `2` is `AUTO_UPDATES_NEVER`, the only mode that stops
`CRepositoryUpdater` rescheduling its timer; `1` is `AUTO_UPDATES_NOTIFY`,
which still polls all three repositories even though
`general.addonnotifications` is `false` and nobody ever sees the answer. The
Artifact Lock is the supply chain now, so that poll has no consumer. The
honest cost is that "an update is available" leaves the UI, which makes the
update proposer in requirement 3 of
[ADR 0017](../adr/0017-pin-add-on-artifacts-and-patch-the-broken-ones.md)
load-bearing rather than a nicety.

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
(scenario 8) cannot reach a Cleared Address, because a typo'd id resolves no
value, matches `unset`, and reports converged forever. Declaring one therefore
carries an obligation at acceptance, scenario 12 below
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
error: …/settings.yaml names NEXTPVR_PIN, which .env does not hold
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
Overlay declares ten settings in `guisettings.xml`: the Sony's EDID mode
whitelist, the two Dolby Vision settings, the six passthrough flags for
the Sony eARC to OREI to Denon chain, and the decoded channel layout.

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
setting where the two are different things. Two of the room's ten use one,
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

`audiooutput.channels` is the room's tenth address, declared as `10`. That
looks like an ordinal, and it is one, but from a fixed table in Kodi's own
`settings.xml` where `10` is `AE_CH_LAYOUT_7_1`; nothing on the Device
assigns it, so it is as stable as the Kodi version the Profile names.

`videoscreen.resolution` is room-scoped too and is deliberately *not*
declared, now or later. Kodi recomputes that ordinal from the live display
mode at every startup; the stored truth is `videoscreen.screenmode`, which the
shell never writes. Writing the ordinal is not ownership, so `ROOM-001` is
retired
([ADR 0019](../adr/0019-the-profiles-scope-resolves-what-the-shell-probed.md)).

## Declaring an add-on

Forty-three add-ons — every one this fleet installs — are the Reconciler's. They are declared in the Artifact Lock
beside the Profile, never in the Profile itself:

```yaml
addons:
  - id: script.module.six
    version: "1.16.0+matrix.1"
    url: https://mirrors.kodi.tv/addons/omega/script.module.six/script.module.six-1.16.0+matrix.1.zip
    sha256: "4197f7773f75ab9f16b3c920195acbb8b8b151b4b3c8c3e14fc4876e764e3860"
    role: dependency
    notes: ~
```

A record names the bytes, not a place to look for bytes. The Reconciler
fetches the URL and hashes what came back; anything but `sha256` fails the Run
without touching the Device, because a mirror that changed under a stable URL
is exactly the case a pin exists to catch
([ADR 0017](../adr/0017-pin-add-on-artifacts-and-patch-the-broken-ones.md)).

Appearing in the Lock is one statement: **installed at this version and
enabled**. There is no add-on this fleet wants present but disabled, so the
two are not separately declarable and cannot disagree with each other
([ADR 0018](../adr/0018-enable-add-ons-in-kodis-database-while-kodi-is-stopped.md)).

`role` and `notes` answer two different questions and nothing but a human
reads either. `role` is why the add-on is here at all — `chosen` is a decision
someone made, `dependency` is a consequence of one, and `repository` is the
kind whose enablement could invite Kodi to go and fetch something. `notes` is
why *this version* and not the newest; a record with nothing to explain states
`~`, which most of them do.

Two add-ons the shell never pinned are inside the Lock:
`plugin.program.autocompletion` and
`script.module.autocompletion` were installed by hand from the official Kodi
repository and recorded in nothing but a comment. They are Profile intent, so
they are declared like anything else someone chose.

The archive's top-level directory is not required to be the add-on id, and for
three of these pins it is not — `plugin.service.emby-next-gen` is rooted at
`plugin.video.emby-plugin.service.emby-next-gen_11.1.27`,
`resource.font.robotocjksc` at `resource.font.robotcjksc`, an upstream typo,
and `weather.ha` at `kodi_weather_ha-0.0.6.6`, because the pin is a GitHub tag
archive. The identity comes from `addon.xml`, which all three declare
correctly, and the tree is installed under the id the Lock pins. Artifact
Patches are applied relative to that root, so a patch does not care which
directory the archive happened to use.

The Lock is a separate file from the Profile because a version bump is
eventually a bot's edit, and a bot editing the file humans edit for settings
turns every bump into a conflict with unrelated work.

### Correcting an add-on upstream has broken

Three add-ons cannot be correct as published, and four one-line fixes stand
between this fleet and add-ons that crash. Each fix is a unified diff in
`patches/<addon-id>/` beside the Lock, and the record lists the ones it
applies:

```yaml
  - id: weather.ha
    version: "0.0.6.6"
    url: https://codeload.github.com/Eugeniusz-Gienek/kodi_weather_ha/zip/refs/tags/0.0.6.6
    sha256: "2978014d258c01e3b5ce73d2a8a73bb3e7d29e64b4d36ae35a355d5665760ae5"
    role: chosen
    notes: >-
      ...
    patches:
      - 0001-settings-int-is-number-on-kodi-21.patch
      - 0002-continue-when-the-request-raises.patch
    patched_files:
      lib/homeassistant/_adapter.py: "0f1ffeb4..."
      resources/settings.xml: "c2ab0d8d..."
```

Each patch opens with a header comment naming the add-on and the version it
was written against. `patch` skips leading text, so that assertion costs the
diff nothing, and it is checked against the Lock **before anything is
fetched**: a version bump that outruns its patches fails at once rather than
after an 8 MB download, which is the safeguard that makes carrying patches
acceptable at all.

Patches are applied on the controller, between expanding the Artifact and
packing the tree the Device receives, by shelling out to `patch` — CoreELEC
has `unzip` and `python3` but no `patch`, and reimplementing diff application
on the Device to avoid a dependency we already take for `ssh` and `curl` is
reimplementing a very old tool. The Device receives finished bytes.

A diff's context lines *are* the assertion the shell hand-wrote as expected
line tuples, so a patch that does not apply cleanly fails the Run with the
Device untouched. The shell's second tuple, occurrence counts and
already-patched branch do not survive: they guard re-patching a tree that is
already installed, and this tree was expanded from bytes a SHA-256 pins.

What does survive is the syntax check. A clean application proves the context
matched; it does not prove the result parses, and four of the five patched
files are Python that Kodi imports at boot. Every patched `.py` file is
compiled on the controller, so a broken patch fails the Run instead of the
add-on.

### Recording what a patch produces

Correcting a patch does not move the add-on's version. The Device still
reports `6.17.1`, so a Plan reading only the version would see no difference
and the correction would never ship — and iterating on patches is the whole
reason for carrying them.

So a patched add-on is observed by its version **and** by the hashes of the
files its patches touch. The file list comes from the diffs' own `+++`
headers, so nothing declares it twice, and `patched_files` must name exactly
those files or the Lock is refused.

Those hashes are recorded rather than recomputed, which is what keeps `plan`
offline and instant — the alternative puts a download and a patch run in the
path that executes even when nothing changed. `record-patches` generates
them, by running the real pipeline and no imitation of it:

```console
uv run coreelec-reconciler record-patches --room theater
```

It fetches each patched Artifact, proves its digest, expands it, applies the
patches, hashes what came out, and writes the values back into the Lock —
rewriting nothing else in the file, so every comment beside a pin survives. It
contacts no Device, and needs no transport identity to run: it reads the Lock,
the patches beside it, and the upstream Artifacts. A record whose hash is `~`
is one nobody has recorded, and a Run refuses it rather than guessing: an
unrecorded hash cannot tell a patched Device from an unpatched one.

Regeneration lives on the Reconciler rather than in `scripts/` because it *is*
the artifact pipeline. A tool beside it would duplicate the pipeline or reach
past the package boundary
([ADR 0011](../adr/0011-linux-only-ci-and-boundary-tests.md)), and it is what
the update proposer will call when it bumps a version.

CI regenerates and compares, in a job that runs only when the Lock or
`patches/` changed — exactly when the answer could have moved. It is not in
the main suite, because that makes an unrelated one-line change fail when a
mirror is down, and not scheduled-only either, because a wrong hash would then
merge and surface as a failed Run on the appliance.

Encoding patch identity in the version instead — shipping `6.17.1+tv.1` — was
rejected. `skin.arctic.fuse.3` declares a dependency floor of `6.14.3` on
`plugin.video.themoviedb.helper`, so that rewrites the identity another add-on
compares against.

### What a Run observes

The Observation is `/storage/.kodi/addons/<id>/addon.xml`, parsed as XML and
read for the `version` attribute — what Kodi itself believes is installed.
Nothing hashes the tree, and the Reconciler writes no receipt of its own: a
receipt would be a second record of the same fact, free to disagree with the
one Kodi reads. The enabled half is the `installed` row in the add-on
database. For a patched add-on it is those two and the files the diffs
touch, read back and compared against the hashes the Lock records. They are
read only when the declared version already matches: an add-on being replaced
whole is replaced whole.

A Plan names both:

```
create /storage/.kodi/addons/script.module.six
version: (absent) -> 1.16.0+matrix.1
enabled: (no row) -> 1
```

An add-on already at its pin but disabled plans as an `update` that ships
nothing — the tree is already right, so re-downloading it would be work
nobody asked for:

```
update /storage/.kodi/addons/script.module.six
version: 1.16.0+matrix.1 -> 1.16.0+matrix.1
enabled: 0 -> 1
```

An add-on at its pin whose patched files are not the bytes the Lock records
plans as an `update` that ships the whole tree, and names the file:

```
update /storage/.kodi/addons/weather.ha
version: 0.0.6.6 -> 0.0.6.6
patched file: resources/settings.xml is not the bytes the Artifact Lock records
```

### What an Apply does

Everything that can fail on the controller fails first. The Run downloads the
archive, verifies the digest, rejects any ZIP entry that is absolute or walks
out of the archive, cross-checks the `addon.xml` inside against the pinned id
and version, and builds a `ustar` tar — all before Kodi is stopped.
Downloading under a stopped Kodi would hold the television down for the length
of the transfer, and an Artifact that fails its pin would hold it down for
nothing:

```
fetching script.module.six 1.16.0+matrix.1
stopping kodi.service
shipping script.module.six 1.16.0+matrix.1
starting kodi.service
```

The tree is streamed over the existing ssh transport, expanded into a staging
directory beside the destination, and moved into place only once it is whole.
A Run killed mid-transfer leaves the old add-on intact and a staging directory
behind; the next Run replaces it. That is the interruption property, not
rollback — there is no copy of the previous tree, and reprovisioning is the
disaster recovery story
([ADR 0009](../adr/0009-fail-forward-and-exclusive-execution-ownership.md)).

The row is then written directly into Kodi's add-on database with Kodi still
stopped, with exactly the statement Kodi itself issues: update `enabled` and
`disabledReason` if a row exists, insert `(addonID, enabled, installDate)` if
one does not. Kodi writes `installed` immediately on change rather than
flushing it from memory at exit, so a stopped Kodi has nothing to lose. There
is no JSON-RPC path that installs a local add-on and enables it, which is why
the database is the interface
([ADR 0018](../adr/0018-enable-add-ons-in-kodis-database-while-kodi-is-stopped.md)).

The add-on database is named by the Profile, not compiled in; see
[Device addresses](#device-addresses).

Install order does not matter. Kodi is stopped and enablement is a database
write, so nothing sequences a dependency ahead of its dependant. Only add-ons
whose declared version differs are fetched at all, so a converged Device ships
nothing; a fresh one fetches the whole Lock, about 410 MB, and ships it inside
the stop window. That is the one Run where the television is not yet in
service, and `/storage` has 26.8 GB free against it.

### Add-ons nobody declared

Every directory under the add-on address is in the Artifact Lock, is in
Kodi's `addon-manifest.xml`, or is not an add-on. Whatever is left is
reported on every Run, `plan` and `apply` alike:

```
undeclared add-on: /storage/.kodi/addons/plugin.video.themoviedb.helper
```

An add-on is a directory holding an `addon.xml`. Kodi's `packages` and `temp`
scratch directories fall out of that by observation rather than by name, which
is the point: naming them would re-introduce the hand-maintained list the Lock
replaced, and would still miss the next scratch directory Kodi invents. A
`.<id>.staging` directory a killed Run left behind is skipped too.

**A stray does not fail the Run.** An add-on appearing from nowhere is worth
knowing about, but nothing has yet decided what a Run should *do* about one,
and refusing to work for a reason nobody chose is worse than the stray
([ADR 0007](../adr/0007-trusted-home-appliance-bar.md)). The report is made
once, from the planning the Run opens with, so `apply` does not say it twice
when it re-plans to verify.

A missing or unparseable `addon_manifest` *does* fail the Run, naming the
address. That is not a stray: without it every add-on Kodi ships with reads as
one, and a report that cries wolf seven times is a report nobody reads.

On the theater Ugoos today the report names nothing. Every add-on on the
Device is in the Lock or in Kodi's own manifest
([ADR 0017](../adr/0017-pin-add-on-artifacts-and-patch-the-broken-ones.md)).

This replaces the shell's `coreelec_report_addon_inventory`, which printed a
count and tolerated nine ids through `ADDON_UNMANAGED_ALLOWED`. Seven of those
nine are in Kodi's manifest and are now accounted for by the manifest; the
other two are in the Lock. The variable stays in `provision.conf` until the
shell retires it by attrition, in the forced order the
[write-set permission freeze](shell-write-set-permissions.md) requires
([ADR 0010](../adr/0010-retire-the-shell-by-attrition.md)).

## Surveying Unmanaged State

`survey` answers one question: how does this Device differ from the Profile?
It mutates nothing, and it is for two jobs — surveying a known-good Device
and a factory-fresh one after `apply` and diffing the two, and reading back
what to put in the Profile after configuring something by hand.

```console
ssh root@ugoos-theater systemctl is-active kodi   # expect inactive
uv run coreelec-reconciler survey --room theater
```

It **refuses while `kodi.service` is active.** Kodi rewrites a Settings
Document from memory when it exits
([ADR 0013](../adr/0013-a-settings-document-always-takes-the-kodi-stop.md)),
so a document read under it may not be what the Device goes on to hold.

Stopping Kodi by hand is not enough on the theater Ugoos: while the Sony is on,
or the [operational override](#hardware-acceptance) is on, Home Assistant's
lifecycle poll starts Kodi again within thirty seconds. Turn the Sony off and
leave the override off, and Home Assistant stops Kodi itself a minute later and
keeps it stopped. Nothing in the survey needs the television.

The report is one sorted block, so two surveys diff with no ordering noise:

```
declared setting differs: /storage/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml#Hub_TVShows: Profile says X, Device holds Y
undeclared add-on: /storage/.kodi/addons/script.example
undeclared directory: /storage/.kodi/userdata/Thumbnails
undeclared document: /storage/.kodi/userdata/sources.xml
undeclared setting: /storage/.kodi/userdata/guisettings.xml#audiooutput.volumesteps = 90
```

Where it looks is derived from what the Profile declares, never listed. The
directory holding each declared document — a Settings Document, a document
shipped as a file, a Smart Playlist, a Shortcut Node, `authorized_keys` — is
walked one level deep. An undeclared directory is named and not descended
into; a directory holding a declared document further down is not named at
all. Add-ons are reported exactly as a Run reports them
([above](#add-ons-nobody-declared)).

Inside each declared Settings Document it reports every setting the Profile
does not declare, with its value, **except one Kodi marked `default="true"`**.
Kodi writes that attribute on every setting it holds at its default, so
`guisettings.xml`'s several hundred defaults cost no lines. The `json` and
`shell_vars` dialects carry no such marker, so every undeclared key in them is
reported. A declared setting the Device holds differently is reported with
both sides; one the Profile names from `.env` is reported by its key alone.

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

## The timezone Effect

Writing `/storage/.cache/timezone` changes nothing on its own.
`/etc/localtime` is a symlink to `/var/run/localtime`, and `tz-data.service`
is the oneshot that relinks it:

```
[Service]
Type=oneshot
EnvironmentFile=-/storage/.cache/timezone
ExecStart=/bin/ln -sf /usr/share/zoneinfo/${TIMEZONE} /var/run/localtime
```

The Profile does not name that unit — the Reconciler knows which service
reads the document, exactly as it knows that a Kodi document takes the Kodi
stop:

```yaml
  - document: /storage/.cache/timezone
    dialect: shell_vars
    mode: "0644"
    settings:
      - setting: TIMEZONE
        from_profile: timezone
```

The Effect is taken **only when that document actually changes**, through the
same machinery as the Kodi stop: the unit is stopped before the writes and
started after them, once per Run however many addresses moved. Because it is
a oneshot, `start` returns after `ExecStart` — there is nothing to poll and no
partial state.

The Run then reads `/var/run/localtime` and fails unless it names the declared
zone. That is the opposite end of the spectrum from the view rebuild: one
synchronous call with an unambiguous answer.

```
stopping tz-data.service
applied 1 change
starting tz-data.service
/var/run/localtime names America/Los_Angeles
verification: converged
```

No document declares its Effect, Kodi's or otherwise
([ADR 0013](../adr/0013-a-settings-document-always-takes-the-kodi-stop.md)). A
document that could state its unit could omit it, and an omitted unit is the
one mistake nothing catches: the write lands, the document converges, the Run
reports `verification: converged`, and the Device keeps yesterday's zone.

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
7. **The add-on lands, both halves** — this is the first Run through the
   Artifact Type, so it has to prove the whole vertical. Delete the tree and
   forget the row, start Kodi so it settles with the add-on genuinely gone,
   then `apply`:

   ```console
   ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }
   db=/storage/.kodi/userdata/Database/Addons33.db

   ug systemctl stop kodi
   ug rm -rf /storage/.kodi/addons/script.module.six
   ug "sqlite3 $db \"DELETE FROM installed WHERE addonID='script.module.six'\""
   ug systemctl start kodi

   uv run coreelec-reconciler apply --room theater
   uv run coreelec-reconciler plan --room theater
   ```

   Expect the `apply` to name `(absent) -> 1.16.0+matrix.1` and
   `(no row) -> 1`, to fetch before it stops Kodi, and the `plan` after it to
   report the add-on converged. Then confirm the three things the Run claims:

   ```console
   ug cat /storage/.kodi/addons/script.module.six/addon.xml | head -3
   ug "sqlite3 $db \"SELECT addonID, enabled, disabledReason FROM installed
       WHERE addonID='script.module.six'\""
   ug systemctl restart kodi
   ```

   Expect `version="1.16.0+matrix.1"` in the manifest, `1|0` for the row, and
   Kodi to come back up with the add-on enabled in Settings > Add-ons > My
   add-ons. A restart is the half that catches a database write Kodi discards.

   Then prove the disabled-only path separately: disable the add-on in the
   Kodi UI, `apply`, and confirm the Run planned an `update` with no
   `fetching` or `shipping` line — the tree was already at its pin.

   Finally, prove the pin refuses. Edit `addons.yaml` to a `sha256` that is
   one character different, delete the tree, and `apply`: the Run must fail
   naming both digests, before it stops Kodi, and the television must still be
   up. Restore the digest afterwards.

   **Then the four add-ons whose capabilities differ.** The Lock holds forty
   records and re-shipping all of them proves nothing `script.module.six` did
   not, at about 410 MB. Four differ from it in a specific way, so those four
   are the drift:

   | add-on | what it is the only case of |
   | --- | --- |
   | `skin.arctic.fuse.3` | 69 MB installed, and the active skin. Replacing its directory destroys the compiled view include |
   | `repository.jurialmunkey` | a repository add-on — the one kind whose enablement could invite Kodi to go and fetch something |
   | `plugin.service.emby-next-gen` | the archive's top-level directory is not the add-on id |
   | `resource.images.studios.white` | inert bulk, nothing but files |

   ```console
   ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }
   db=/storage/.kodi/userdata/Database/Addons33.db
   four="skin.arctic.fuse.3 repository.jurialmunkey \
     plugin.service.emby-next-gen resource.images.studios.white"

   ug systemctl stop kodi
   for id in $four; do
     ug rm -rf "/storage/.kodi/addons/$id"
     ug "sqlite3 $db \"DELETE FROM installed WHERE addonID='$id'\""
   done
   ug systemctl start kodi

   uv run coreelec-reconciler apply --room theater
   uv run coreelec-reconciler plan --room theater
   ```

   Expect four `create` lines, four `fetching` lines before a single
   `stopping kodi.service`, and the `plan` after it to report no changes.
   Expect nothing else: deleting the active skin's directory does not make
   Kodi rewrite `lookandfeel.skin`, so no Settings Document Change appears
   alongside the four.
   Then confirm what each one was chosen to prove:

   ```console
   # The id, not the archive's directory.
   ug ls -d /storage/.kodi/addons/plugin.service.emby-next-gen
   ug ls /storage/.kodi/addons/ | grep -c emby-plugin    # expect 0

   # The skin came back and rebuilt its own view include.
   views=/storage/.kodi/addons/skin.arctic.fuse.3/1080i
   ug wc -c "$views/script-skinviewtypes-includes.xml"
   ```

   The view include is the one to watch. Arctic Fuse ships it as a 190-byte
   stub whose `onload` makes the skin regenerate the real file; replacing the
   directory puts the stub back, and the skin rewrites it on the next skin
   load. Expect it to be the stub immediately after the Run and several
   kilobytes once Kodi has loaded the skin. Add-ons apply before the view
   rebuild is armed, so this self-heals — this Run is what proves it.

   Finally, check the television: the skin loads, the home screen is intact,
   and Settings > Add-ons > My add-ons shows all four enabled.

   **And the two with no Recovery Baseline.**
   `plugin.program.autocompletion` and `script.module.autocompletion` are the
   only add-ons the shell does not pin, so nothing else on this Device can
   repair them. Delete both and confirm the Reconciler is what brings them
   back:

   ```console
   ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }
   db=/storage/.kodi/userdata/Database/Addons33.db

   ug systemctl stop kodi
   ug "rm -rf /storage/.kodi/addons/plugin.program.autocompletion \
     /storage/.kodi/addons/script.module.autocompletion"
   ug "sqlite3 $db \"DELETE FROM installed WHERE addonID LIKE '%autocompletion'\""
   ug systemctl start kodi

   uv run coreelec-reconciler apply --room theater
   ```

   Their `installed` row loses its `origin` in the process: Kodi recorded
   `repository.xbmc.org` because someone installed them from there, and a
   re-installed row carries the empty `origin` every other pinned add-on on
   this Device already has. That is the intended outcome — the version is the
   Lock's now, not the repository's — and it makes them indistinguishable
   from the thirty-eight the shell installs the same way.
8. **No declared setting, playlist, Shortcut Node or add-on is a `create`**
   — the shell writes every one of them, so on a provisioned Device
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
9. **The shell and the Reconciler agree** — the value-parity invariant. One
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

   Expect exactly two Changes, and expect each to explain itself:

   ```
   update /storage/.kodi/userdata/guisettings.xml#general.addonupdates: 1 -> 2
   divergent: the shell writes 0 or 1 from ADDON_UPDATE_MODE and cannot emit 2, ...
   update /storage/.kodi/userdata/guisettings.xml#services.esenabled: true -> false
   divergent: the shell writes true for the kodi-send view rebuild ADR 0015 retired, ...
   ```

   Those are the two Divergent Addresses, and they are the only Changes a
   parity plan may come back with. A Change *without* a `divergent:` line under it is the
   fault this scenario exists to catch; re-`apply` afterwards to put the
   declared value back. Every other component below must still report
   `plan: no changes`, because none of them writes `guisettings.xml`'s
   `services.*` addresses or `general.addonupdates`.

   The room component is the narrower form of the
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

   The `addons` component is the one that covers the Artifact Lock, and it
   is the one that proves the two engines install the same version from the
   same bytes rather than reverting each other on every Run. Thirty-eight of
   the forty records are pins the shell holds too, so a single transcription
   error shows up here as a Run that never converges:

   ```console
   ./provision-coreelec.sh --target ugoos-theater --component addons
   uv run coreelec-reconciler plan --room theater
   ```

   **Let Kodi settle before reading a parity plan.** Every shell component
   restarts Kodi, and a `plan` run in the seconds after that restart reads a
   `guisettings.xml` Kodi has truncated and not yet rewritten — it reports
   most of the declared addresses as `(unset)`, which is not drift. Wait for
   `systemctl is-active kodi` and re-plan before believing a parity failure.

10. **Usable** — Kodi still starts, every playlist still opens, the weather
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
11. **No named value is anywhere it should not be** — the whole point of
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
12. **Every Cleared Address is the id the skin actually reads** — and this is
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
    ' config/shared/ugoos-am6b-plus/coreelec-21.3/settings.yaml)

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
13. **The CEC power policy lands, and the glob refuses a second document** —
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

14. **The Shortcut Nodes and the view types land, and the views rebuild** —
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

    Expect `plan: no changes`, and expect scenario 8 to stay clean — the shell
    writes all six, so none may plan as a `create`.
15. **The timezone lands in both places, and `/etc/localtime` follows** — the
    first Run through the `shell_vars` dialect, the `from_profile` arm and the
    `tz-data.service` Effect, so it has to prove all three. Drift both records
    of the zone in different directions: if the two addresses did not resolve
    from one constant, only one of them would come back.

    Kodi must be stopped for the injection and started again before the Run,
    so the wrong `locale.timezone` reaches memory.

    ```console
    ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }
    cache=/storage/.cache/timezone
    gui=/storage/.kodi/userdata/guisettings.xml

    ug systemctl stop kodi
    ug "printf 'TIMEZONE=Europe/Berlin\n' > $cache"
    ug "sed -i 's|<setting id=\"locale.timezone\"[^>]*>[^<]*</setting>|<setting id=\"locale.timezone\">Asia/Tokyo</setting>|' $gui"
    # Confirm the injection actually took before trusting the Run.
    ug "grep -o '<setting id=\"locale.timezone\"[^>]*>[^<]*' $gui; cat $cache"
    ug systemctl start kodi && sleep 20

    uv run coreelec-reconciler apply --room theater
    ```

    The `[^>]*` matters and the confirmation is not ceremony. Kodi writes
    `default="true"` on any setting still holding Kodi's own default, and
    `America/Los_Angeles` **is** Kodi's default here, so the address on a
    converged Device reads
    `<setting id="locale.timezone" default="true">America/Los_Angeles</setting>`.
    A pattern that assumed a bare `>` matches nothing, `sed` exits `0`, and
    the scenario quietly becomes a one-address test that still passes — the
    cache drifts, the Run repairs it, and the half this scenario exists to
    prove never runs. No other scenario has this problem: the add-on
    addresses in scenario 6 are declared to values Kodi has no default for,
    so they carry no attribute.

    Expect the `apply` to name **both** addresses, to stop and start
    `tz-data.service`, to print `/var/run/localtime names America/Los_Angeles`,
    and to end `verification: converged`. Then confirm the three things a Run
    cannot confirm for itself:

    ```console
    ug "cat $cache; ls -l $cache"        # TIMEZONE=…, mode -rw-r--r--
    ug "readlink -f /etc/localtime"      # /usr/share/zoneinfo/America/Los_Angeles
    ug date                              # reports the declared zone
    ```

    The mode matters: the shell writes this file `0644` and a Kodi document
    `0600`, so a `shell_vars` document that ignored its declared mode would
    show up here and nowhere else.

    Then the parity half:

    ```console
    ./provision-coreelec.sh --target ugoos-theater --component core
    uv run coreelec-reconciler plan --room theater
    ```

    The `core` component writes `general.addonupdates`, so expect exactly the
    one Divergent Address Change described in scenario 9 and nothing else,
    and scenario 8 to stay clean. `apply` again to put the declared value
    back.
16. **The platform Guard refuses a Device that is not what the Profile
    claims** — a Guard that has never refused anything is a Guard nobody has
    tested. Declare a version the Device does not hold and watch the Run stop
    before it writes:

    ```console
    profile=config/shared/ugoos-am6b-plus/coreelec-21.3/profile.yaml
    ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }

    ug "md5sum /storage/.kodi/userdata/guisettings.xml"
    sed -i.bak 's/^  version: "21.3"/  version: "22.0"/' $profile
    uv run coreelec-reconciler apply --room theater   # expect exit 1
    mv $profile.bak $profile
    ug "md5sum /storage/.kodi/userdata/guisettings.xml"
    ```

    Expect the refusal to name `/etc/os-release`, `VERSION_ID`, both values,
    and no Change at all — the Guard runs before anything is planned. Expect
    the two digests to match and `systemctl status kodi` to show no restart:
    an `apply` that refuses here must not have touched the service.

    Repeat with a sound card the Device does not have:

    ```console
    sed -i.bak 's/^  sound_card: AMLAUGESOUND/  sound_card: AMLMESONAUDIO/' $profile
    uv run coreelec-reconciler apply --room theater   # expect exit 1
    mv $profile.bak $profile
    ug "md5sum /storage/.kodi/userdata/guisettings.xml"
    ```

    Expect the refusal to name `/proc/asound/cards`, `AMLAUGESOUND` and
    `AMLMESONAUDIO`, the digest to match again, and Kodi not to have
    restarted.

    Then confirm what the Device actually says, which is what the Profile has
    to keep agreeing with:

    ```console
    ug "cat /etc/os-release; cat /etc/release; cat /proc/asound/cards"
    ```

17. **Who may log in converges, and the password window closes** — this is
    the first Run that restarts the daemon carrying its own connection, so it
    has to prove the reconnect. Inject both drifts at once: a stray key in
    `authorized_keys`, and the pair a wizard-enabled Device presents.

    ```console
    ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }
    keys=/storage/.ssh/authorized_keys
    conf=/storage/.cache/services/sshd.conf

    ug "ssh-keygen -q -t ed25519 -N '' -C stray-key -f /tmp/stray"
    ug "cat /tmp/stray.pub >> $keys"
    ug "printf 'SSH_ARGS=\"\"\nSSHD_DISABLE_PW_AUTH=\"false\"\n' > $conf"
    ug "systemctl restart sshd.service" ; sleep 3

    uv run coreelec-reconciler plan --room theater
    uv run coreelec-reconciler apply --room theater

    ug "cut -d' ' -f1,3- $keys; cat $conf; ls -l $conf"
    ```

    Expect the plan to name three Changes — the document, and both keys of
    `sshd.conf` as `update`, never `create` — and to report the entries
    rather than any key blob. Expect the apply to print `restarting
    sshd.service`, then `sshd.service is active and …/authorized_keys is not
    empty`, then `verification: converged`. Expect the stray key to be gone,
    the lifecycle entry to survive untouched, and the file to be `0600`.

    Then prove the window is actually shut, from a connection that offers no
    key at all:

    ```console
    ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password \
        -o NumberOfPasswordPrompts=1 root@ugoos-theater true
    ```

    Expect `Permission denied (publickey)` — the daemon refusing to even
    offer password authentication — and `ug true` to still work.

18. **First Contact reaches a Device with no administrator key** — the
    precondition for the retirement test, and the one scenario that needs the
    Device's root password. Remove the administrator entry, confirm the
    Device is unreachable, and meet it again.

    **Do this with the local console to hand.** It is the one scenario that
    deliberately removes the Reconciler's own way in, and it needs password
    authentication enabled to get back — so run it before scenario 17, or
    re-enable the password from the console first.

    ```console
    ug "cp $keys $keys.acceptance-backup"
    ug "grep kodi-lifecycle $keys > $keys.new && mv $keys.new $keys"
    ug "chmod 600 $keys"
    ssh -o BatchMode=yes -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater true

    uv run coreelec-reconciler bootstrap --room theater
    uv run coreelec-reconciler plan --room theater
    ```

    Expect the fourth command to fail with `Permission denied`, `bootstrap`
    to prompt for the password once and then report that the Device answers
    to a key-only connection, and the `plan` after it — which is key-only and
    strict — to succeed. Expect `bootstrap` to have appended the
    administrator entry and left the lifecycle entry exactly where it was.

19. **Kodi stops polling, and the poll actually stops** — the address is
    only half the claim. Drift it, converge it, and then read Kodi's own log
    for the repository check that must not happen.

    Kodi must be stopped for the injection and started again before the Run,
    so the wrong value reaches memory.

    ```console
    ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }
    gui=/storage/.kodi/userdata/guisettings.xml
    log=/storage/.kodi/temp/kodi.log

    ug systemctl stop kodi
    ug "sed -i 's|<setting id=\"general.addonupdates\"[^>]*>[^<]*</setting>|<setting id=\"general.addonupdates\">1</setting>|' $gui"
    ug "grep -o '<setting id=\"general.addonupdates\"[^>]*>[^<]*' $gui"
    ug systemctl start kodi && sleep 20

    uv run coreelec-reconciler apply --room theater
    ug systemctl restart kodi && sleep 60
    uv run coreelec-reconciler plan --room theater
    ```

    The `[^>]*` matters for the same reason it does in scenario 15: Kodi
    writes `default="true"` on a setting still holding its own default.

    Expect the `apply` to name the address as `1 -> 2`, to print the
    `divergent:` line under it, and to converge; expect the final `plan` to
    report no changes, which is the half that catches a write Kodi discards
    on exit. Then read the log across a full minute of uptime:

    ```console
    ug "grep -ci 'CRepositoryUpdater\|checking repositories for updates' $log"
    ```

    Expect `0`. A non-zero count is the timer still running, which is the
    whole thing this address is for.

20. **Every add-on on the Device is accounted for** — the inventory half.
    Read the report, then derive the same answer independently and compare:

    ```console
    ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }

    uv run coreelec-reconciler plan --room theater | grep '^undeclared add-on: '

    ug "cd /storage/.kodi/addons && for e in *; do
          [ -f \"\$e\"/addon.xml ] && echo \"\$e\"; done" | sort > /tmp/held
    ug "sed -n 's#.*<addon[^>]*>\(.*\)</addon>.*#\1#p' \
        /usr/share/kodi/system/addon-manifest.xml" | sort > /tmp/kodis
    uv run python -c '
    import yaml
    for r in yaml.safe_load(open("config/shared/ugoos-am6b-plus/coreelec-21.3/addons.yaml"))["addons"]:
        print(r["id"])' | sort > /tmp/locked
    comm -23 /tmp/held <(sort -u /tmp/kodis /tmp/locked)
    rm -f /tmp/held /tmp/kodis /tmp/locked
    ```

    Expect both to be empty, now that the three patched add-ons are in the
    Lock
    ([ADR 0017](../adr/0017-pin-add-on-artifacts-and-patch-the-broken-ones.md)).
    Anything either one names is a genuine stray and is worth finding out
    about, and the two must agree: the report naming something the derivation
    does not, or the reverse, is the accounting being broken rather than the
    Device being dirty. The injected stray below is what proves an empty
    report is still a report.

    Then prove a stray is actually seen, and that it does not stop a Run:

    ```console
    ug "mkdir -p /storage/.kodi/addons/plugin.video.nobody.declared && \
        printf '<addon id=\"plugin.video.nobody.declared\" version=\"1.0.0\"/>' \
        > /storage/.kodi/addons/plugin.video.nobody.declared/addon.xml"

    uv run coreelec-reconciler plan --room theater    # expect exit 0
    ug rm -rf /storage/.kodi/addons/plugin.video.nobody.declared
    ```

    Expect a fourth `undeclared add-on:` line naming it, exit `0`, and no
    Change alongside it. Expect `packages` and `temp` never to appear: they
    hold no `addon.xml`, which is the whole rule.

21. **A patched add-on is not identified by its version** — the drift only
    the recorded file hashes can catch. Install the **unpatched** add-on at
    the pinned version, which is what upstream ships and what an operator
    installing from the repository would get:

    ```console
    ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }
    tmdb=/storage/.kodi/addons/plugin.video.themoviedb.helper
    service=$tmdb/resources/tmdbhelper/lib/monitor/service.py

    ug "sed -i '/\.daemon = True/d' $service"
    ug "grep -c 'daemon = True' $service"        # expect 0
    ug "sed -n 's/.*version=\"\([^\"]*\)\".*/\1/p' $tmdb/addon.xml | head -1"

    uv run coreelec-reconciler plan --room theater
    ```

    Expect the version to read `6.17.1`, matching the pin exactly, and the
    plan to name the add-on anyway with a `patched file:` line for
    `resources/tmdbhelper/lib/monitor/service.py`. That is the case where the
    old Observation returns "converged" and the new one must not. Deleting the
    add-on instead would pass even if patching were skipped entirely, which is
    why the drift is injected inside a file rather than by removing the tree.

    Then converge it and confirm the bytes on the Device are the patched ones,
    not merely present:

    ```console
    uv run coreelec-reconciler apply --room theater
    ug "grep -c 'daemon = True' $service"        # expect 2
    ug "grep -c 'if windowutils.HOME:' /storage/.kodi/addons/script.plexmod/lib/monitor.py"
    ug "grep -c 'type=\"number\"' /storage/.kodi/addons/weather.ha/resources/settings.xml"

    uv run coreelec-reconciler plan --room theater    # expect no changes
    ```

    Expect `1` from each of the other two, and the final `plan` to report no
    changes — the same hashes the Lock records, read back off the Device.

22. **Home Assistant can reach the Device** — over JSON-RPC for state and
    over SSH for lifecycle. Drift the web server and delete the gateway, with
    Kodi stopped so the wrong values reach memory:

    ```console
    ug() { ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater "$@"; }
    gui=/storage/.kodi/userdata/guisettings.xml

    ug systemctl stop kodi
    ug "sed -i -e 's|<setting id=\"services.webserverport\"[^>]*>[^<]*</setting>|<setting id=\"services.webserverport\">8081</setting>|' \
               -e 's|<setting id=\"services.esenabled\"[^>]*>[^<]*</setting>|<setting id=\"services.esenabled\">true</setting>|' $gui"
    ug rm /storage/.config/kodi-lifecycle
    ug systemctl start kodi && sleep 25

    uv run coreelec-reconciler apply --room theater
    ```

    Expect `create /storage/.config/kodi-lifecycle` with the whole gateway as
    a diff, `8081 -> 8080`, and `true -> false` with its `divergent:` line.
    Then prove the gateway *runs*, not merely that forty lines landed, by
    executing it the way `sshd` does. Home Assistant's private key is Home
    Assistant's, so the administrator connection stands in for it:

    ```console
    ug 'SSH_ORIGINAL_COMMAND=status /storage/.config/kodi-lifecycle; echo rc=$?'
    ug 'SSH_ORIGINAL_COMMAND=reboot /storage/.config/kodi-lifecycle; echo rc=$?'
    ```

    Expect `running` and `rc=0`, then `Allowed commands: start, stop, status`
    and `rc=2`. Finally, prove JSON-RPC answers with the declared credentials
    and refuses without them, and re-plan:

    ```console
    set -a && . ./.env && set +a
    rpc='{"jsonrpc":"2.0","id":1,"method":"JSONRPC.Ping"}'
    curl -sS -u "homeassistant:$KODI_WEB_PASSWORD" -H 'Content-Type: application/json' \
      -d "$rpc" http://ugoos-theater.lan.wavebe.am:8080/jsonrpc
    curl -s -o /dev/null -w '%{http_code}\n' -H 'Content-Type: application/json' \
      -d "$rpc" http://ugoos-theater.lan.wavebe.am:8080/jsonrpc
    uv run coreelec-reconciler plan --room theater
    ```

    Expect `"result":"pong"`, then `401`, then `plan: no changes`.

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
(`SKIN-019`-`SKIN-026`), the thirty
`guisettings.xml` addresses the Profile declares — `CORE-001`-`CORE-005`,
`CORE-008`-`CORE-029`, `SKIN-001`, `SKIN-002` and `SVC-001` — the ten the
Room Overlay declares (`ROOM-002`-`ROOM-011`), the twelve add-on addresses
the Profile declares (`SVC-002`-`SVC-013`), the Arctic Fuse home screen
(`SKIN-003`-`SKIN-010`), the four Shortcut Nodes (`SKIN-011`-`SKIN-014`), the
two view types (`SKIN-015`, `SKIN-016`), the view rebuild (`EFFECT-004`), the
CEC power policy (`CEC-001`-`CEC-005`), the platform Guard (`PLAT-001`), the
timezone cache (`CORE-006`), the `tz-data.service` restart (`EFFECT-002`),
the two `authorized_keys` entries (`SSH-002`, `LIFE-002`), the Kodi
lifecycle gateway (`LIFE-001`), the `sshd.conf`
pair (`SSH-003`), the host key policy (`SSH-004`), the `sshd.service`
restart (`EFFECT-003`) and all forty-one add-on artifacts
(`ART-001`-`ART-041`)
as
shell-owned
with
`reconciler_status: accepted`, and the shell still writes them during a `core`,
`cec`, `skin`, `services`, `addons`, `room` or `baseline` run. `ADDON-001` is
one row covering the enabled flag of all forty-one add-ons, and it is
`accepted` too: the Reconciler now declares every one of them, which is the
one thing that row was waiting for.

The Artifact Lock also declares two add-ons that have **no ledger row at
all**: `plugin.program.autocompletion` and `script.module.autocompletion`. The
ledger is the inventory of what the shell *does*, and the shell never wrote
either — it only tolerated them through `ADDON_UNMANAGED_ALLOWED`, which is
what `ADDON-003` records. They are the first Reconciler-owned addresses with
no shell write set, and the schema takes that shape unchanged: nothing
requires a row per Reconciler-owned address, and `--audit` stays valid because
every check it makes is scoped to rows whose owner is `shell`.

`SKIN-027` and `SKIN-028`,
the
two superseded playlists, stay `retired` and are not declared anywhere, and
so does `PLAT-002`, the device-tree model check the Reconciler will never
make, and so do `PLAT-004`, `PLAT-005` and `LIFE-003`, the lifecycle deploy's
second platform guard, its pre-7.2 OpenSSH fallback and its Kodi stop
([ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md)), and
so does `ROOM-001`, the display resolution ordinal Kodi recomputes at every
startup
([ADR 0019](../adr/0019-the-profiles-scope-resolves-what-the-shell-probed.md)). That
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
declarations agree there for the same reason they agree everywhere else:
there is one source. `LIFE-002` names a seventh,
`COREELEC_LIFECYCLE_PUBLIC_KEY`, which only the Reconciler reads: the shell
takes the same key as a file path on `configure-kodi-lifecycle.sh`'s command
line. Keeping both pointed at one key is the operator's until the shell
retires. `CORE-025`, the web server password, names an eighth,
`KODI_WEB_PASSWORD`, which both engines read from `.env`.

`SSH-001`, the controller-local private key, stays with the operator. It is
the one thing the Reconciler cannot declare, and the administrator entry in
`authorized_keys` is derived from its public half rather than declared, so a
Profile cannot name the wrong administrator.

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
and every Shortcut Node is written `0600` by both, and so is
`authorized_keys`, which `sshd` insists on. `sshd.conf` goes the other way:
the Reconciler writes it `0644`, which is what CoreELEC's own writer gives
it, and the shell's `0600` is the departure.

Applying a Kodi setting reserialises the Settings Document the way the shell
provisioner does — four-space indentation, one declaration, trailing newline,
and the declared dialect's own node shape. Every setting's ID and value
survives; incidental whitespace from whoever
wrote the document last does not. Kodi reformats the document on its own terms
at the next shutdown anyway, so preserving its byte layout would buy nothing
and cost a source-offset-preserving XML writer.
