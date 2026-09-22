---
status: accepted
---

# Enable add-ons in Kodi's database while Kodi is stopped

Installing an add-on is not finished when its directory is in place.
`CAddonDatabase::SyncInstalled` (Omega, `AddonDatabase.cpp:417-425`) inserts a
newly-discovered add-on with `int enable = 0` unless it is a system or optional
manifest add-on, so a dropped-in directory arrives **disabled**. The
`installed` table is the whole truth: `GetDisabled` selects `WHERE enabled=0`,
and `EnableAddon` is `UPDATE installed SET enabled=1, disabledReason=0`.

Crucially, `SyncInstalled` only inserts rows for ids that are on disk and *not
already in the table*.

So the Reconciler writes the row itself, with `enabled=1`, while Kodi is
stopped — which the Run already is, because add-on directories cannot be
replaced under a running Kodi. Kodi then starts, finds nothing to add, and the
add-on is enabled.

## Why not JSON-RPC

The shell calls `Addons.SetAddonEnabled` against a running Kodi, wrapped in a
convergence loop of repeated rounds. That loop exists because Kodi reports
success even when its dependency walk did not take, and leaves a dependent
disabled when its dependency was not enabled at the moment the request was
served. With Kodi stopped, every row is set in one transaction and the ordering
problem does not exist.

JSON-RPC also cannot run at the right moment. Installing requires Kodi **down**;
enabling over JSON-RPC requires it **up**. Taking that route means a second stop
and start for every Run that installs anything.

And it creates a circular dependency. JSON-RPC needs the Kodi web server, which
is `CORE-020`–`CORE-027` — the cohort
[ADR 0012](0012-shadow-the-shell-and-retire-it-wholesale.md) deferred precisely
because we had not decided whether the Reconciler depends on that channel.
Using it would mean configuring the channel from a Run that needs it. This ADR
is that decision: the Reconciler does not speak JSON-RPC, so those eight
addresses are no longer deferred. They still have to be configured, because
Home Assistant's lifecycle package waits on that endpoint, but no Run needs
them.

## The cost, and what limits it

`Addons33.db` is Kodi's private schema, not a public interface. This is the
largest departure from an upstream mechanism we have made, and it is worth
naming as such.

Two things bound it. The schema version is **in the filename**, so a Kodi
release that changes the schema renames the file rather than silently changing
what it means — and the address is declared in the Profile, not in code, so a
Profile branched for a future Kodi is a configuration change. And the
statements are exactly the ones Kodi issues itself: insert only `(addonID,
enabled, installDate)`, update only `SET enabled=1, disabledReason=0`. Every
other column takes its declared default, so a future schema that adds a
defaulted column still works. Writing a full row would be the version-bound
choice.

This is not the [ADR 0013](0013-a-settings-document-always-takes-the-kodi-stop.md)
hazard in reverse. `installed` is written immediately on change rather than
held in memory and flushed at exit, so a stopped Kodi has nothing to lose.

## One Resource, not two

An add-on's Desired State is "installed at this version **and** enabled". The
two facts are never independently desirable — there is no add-on we want
present but disabled, or enabled but absent — so they are one declaration that
cannot disagree with itself. Appearing in the Artifact Lock *is* the statement
that the add-on should be enabled, which keeps the Lock a pure lock.
