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
(`special://profile/playlists/video/NewShows.xsp`) as shell-owned, and the
shell still writes it during a `skin` or `baseline` run. That is deliberate
for now: transferring the row freezes those shell runs
([the write-set permission freeze](shell-write-set-permissions.md)), which
would remove the Recovery Baseline this slice depends on.

The two declarations agree byte for byte — the Reconciler renders the same
document the shell does — so a Device restored from the shell baseline
converges with no Change. The Observation is the file's content only. The
shell writes the file `0600` and the Reconciler writes it `0644`, so a file
the shell last wrote keeps `0600`; on a single-user appliance where Kodi runs
as root that difference is inert, and observing a mode portably costs more
than the difference is worth.
