# Reconcile the theater Ugoos

The Reconciler owns two Resource Types on the theater Ugoos: the Smart
Playlist `NewShows.xsp`, and the Kodi settings the Profile declares inside
`guisettings.xml`. Everything else on the Device is still the shell
provisioner's, and its declaration remains the Recovery Baseline
([ADR 0010](../adr/0010-retire-the-shell-by-attrition.md)).

A Smart Playlist is a document the Reconciler renders whole.
`guisettings.xml` is not: it is a shared document holding hundreds of
settings, almost all of them Unmanaged State. The Reconciler changes only the
State Addresses the Profile declares and preserves every other setting's
identity and value.

## Configuration

| File | Holds |
| --- | --- |
| `config/shared/ugoos-am6b-plus/coreelec-21.3/profile.yaml` | The Profile: SSH transport, the declared Smart Playlists, and the declared Kodi settings |
| `config/rooms/theater/room.yaml` | The Room Overlay: the room, the Device hostname, and the Profile it uses |

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
line naming the State Address, the Observation, and the desired value, so a
Run that applies a dozen settings leaves a dozen readable lines.

```
update /storage/.kodi/userdata/guisettings.xml#videolibrary.flattentvshows: 0 -> 1
```

## Declaring a Kodi setting

Add an entry to `kodi_settings.settings` in the Profile; nothing else changes.

```yaml
kodi_settings:
  document: /storage/.kodi/userdata/guisettings.xml
  settings:
    - setting: videolibrary.flattentvshows
      value: "1"
```

Declare the value `provision-coreelec.sh` already writes. The two declarations
then agree, the Recovery Baseline and Desired State do not diverge, and a
shell run stays a no-op.

Kodi resolves a setting ID without regard to case and reads only the direct
`<setting>` children of the document root. The Reconciler resolves a declared
setting to that one node: a differently cased node, or a copy nested under
`<category>`, is the same setting and does not survive beside it. This is what
the shell provisioner does, so the two agree on what "set" means.

## The Kodi restart Effect

Kodi rewrites `guisettings.xml` from memory when it exits, so a write made
while Kodi is running is silently lost at the next shutdown. Restarting Kodi
is therefore an Effect these Changes require, not a courtesy.

The Run takes that Effect **once**. It stops `kodi.service` if any planned
Change requires it, applies every Change, and starts Kodi again — including
when a Change failed partway, because a Run must never leave the television
dead. The Run then reports what was and was not applied:

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
5. **The Kodi setting lands** — set `videolibrary.flattentvshows` to the
   wrong value in the Kodi UI (Settings > Media > Videos > Flatten TV show
   seasons), `apply`, and confirm three things: the plan named the State
   Address and both values, Kodi came back up, and the UI shows the declared
   value after the restart. Then confirm unrelated settings are untouched by
   diffing `guisettings.xml` before and after the Run.
6. **Usable** — Kodi still starts and the playlist still opens:

   ```console
   curl -sS --max-time 15 --user "$KODI_USER:$KODI_WEB_PASSWORD" \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"Files.GetDirectory","params":
          {"directory":"special://profile/playlists/video/NewShows.xsp",
           "media":"video","limits":{"end":5}}}' \
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

`inventory/ownership-ledger.json` still records `SKIN-025`
(`special://profile/playlists/video/NewShows.xsp`) and `CORE-013`
(`videolibrary.flattentvshows`) as shell-owned, and the shell still writes
them during a `skin` or `baseline` run. That is deliberate for now: transferring a row freezes those
shell runs
([the write-set permission freeze](shell-write-set-permissions.md)), which
would remove the Recovery Baseline this slice depends on.

The two declarations agree — the Reconciler renders the same Smart Playlist
document the shell does, and declares the same Kodi setting values — so a
Device restored from the shell baseline converges with no Change. The
Observation is the file's content, or the setting's value, and nothing else.

The shell writes the Smart Playlist `0600` and the Reconciler writes it
`0644`, so a file the shell last wrote keeps `0600`; on a single-user
appliance where Kodi runs as root that difference is inert, and observing a
mode portably costs more than the difference is worth. `guisettings.xml` is
written `0600` by both.

Applying a Kodi setting reserialises `guisettings.xml` the way the shell
provisioner does — four-space indentation, one declaration, trailing newline.
Every setting's ID and value survives; incidental whitespace from whoever
wrote the document last does not. Kodi reformats the document on its own terms
at the next shutdown anyway, so preserving its byte layout would buy nothing
and cost a source-offset-preserving XML writer.
