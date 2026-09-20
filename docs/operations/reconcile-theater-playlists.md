# Reconcile theater Smart Playlists

The Reconciler owns `NewShows.xsp` on the theater Ugoos. This is the first
slice of the walking skeleton
([ADR 0008](../adr/0008-restart-from-a-walking-skeleton.md)) and the only
Resource it manages today. Everything else on the Device is still the shell
provisioner's, and its declaration remains the Recovery Baseline
([ADR 0010](../adr/0010-retire-the-shell-by-attrition.md)).

## Configuration

| File | Holds |
| --- | --- |
| `config/shared/ugoos-am6b-plus/coreelec-21.3/profile.yaml` | The Profile: SSH transport and the declared Smart Playlists |
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
(`~/.ssh/coreelec_admin_ed25519` by default; change it in the Profile). Kodi
does not need to be stopped: a Smart Playlist is read when it is opened.

## Hardware acceptance

A Reconciler change is accepted on the real Device, not in CI. Kodi on the
theater Ugoos is under the Home Assistant lifecycle package, which stops Kodi
whenever the Sony is off, so acceptance runs bracketed by the operational
override. Take control, test, hand control back:

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
5. **Usable** — Kodi still starts and the playlist still opens:

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

`NewShows.xsp` has exactly one writer. `inventory/ownership-ledger.json`
records `SKIN-025` as Python-owned, and `provision-coreelec.sh` no longer
writes it, verifies it, or backs it up — see
[the handoff](shell-write-set-permissions.md).

This matters because the shell is run ad hoc. Were both engines still writing
the address, any `--component skin` run would silently revert whatever the
Reconciler had converged, and nothing would report it.

The practical consequence is that a shell baseline no longer leaves this
playlist behind. The home and TV menus still link to it, so after a recovery
run the "New Shows" entry is empty until `apply` runs. That is the intended
shape of [retiring the shell by attrition](../adr/0010-retire-the-shell-by-attrition.md):
the Recovery Baseline lags Desired State by exactly the addresses handed over.

The Observation is the file's content only. Mode is not observed: the
Reconciler writes `0644`, and on a single-user appliance where Kodi runs as
root, observing a mode portably costs more than the difference is worth.
