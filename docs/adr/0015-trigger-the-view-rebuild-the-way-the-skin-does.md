---
status: accepted
---

# Trigger the view rebuild the way the skin does

`script.skinvariables` compiles `skin.arctic.fuse.3-viewtypes.json` into an XML
include the skin reads, `1080i/script-skinviewtypes-includes.xml`. Setting
`SKIN-015` and `SKIN-016` — the season and episode view types — means changing
the source and then getting that compile to happen.

The shell gets it to happen by talking to Kodi. It polls a JSON-RPC endpoint
until Kodi answers, reads `services.esenabled` to confirm the EventServer is
on, sends `RunScript(script.skinvariables,action=buildviews,force=True,no_reload=True)`
through `kodi-send`, and then watches the compiled file's digest until two
consecutive samples agree (provision-coreelec.sh:3954-4075). About a hundred
lines, an authenticated HTTP channel, a UDP datagram, and a settle loop whose
own comment concedes that it "does not adjudicate the outcome".

**The Reconciler does none of that. It writes the skin's own trigger stub over
the compiled include and restarts Kodi, which it was going to do anyway.**

## The skin says so

`skin.arctic.fuse.3/1080i/Includes_Fallbacks.xml:3-5` defines
`Action_BuildViews` as an empty include carrying only a description:

> Is set in script-skinviewtypes-includes.xml to rebuild viewtypes on update
> and then not again because it will then overwrite the file. Includes file set
> to not track in github so that it always is blank with just the include to
> trigger refresh.

`Home.xml:4` and `Includes_Actions.xml:83` reference `Action_BuildViews` on
load. Whichever definition wins decides whether a rebuild happens: the empty
fallback, or an `onload` in the compiled include. A stub in that file therefore
*is* the trigger, and the compiled output overwriting it *is* the disarm. The
file on the theater Ugoos carries zero `Action_BuildViews` references, which is
why nothing rebuilds on restart today.

The re-arm is deliberate rather than incidental. `ViewTypes.update_xml`
(`viewtypes.py:493-530`) proceeds when the source hash has changed, when
`force` is set, or when `xmlfile_exists` is false — and `xmlfile_exists`
(`:482-490`) is false whenever the file's hash differs from the checksum stored
at the last build. Overwriting with the stub changes that hash, so the rebuild
runs even when the source is untouched.

## Why the stub is authored rather than restored

The skin ships the file deliberately untracked, so there is no pristine copy to
put back. The Reconciler writes a minimal include defining `Action_BuildViews`
with the `RunScript(script.skinvariables,action=buildviews)` onload. This is
the one place in the slice where the Reconciler authors skin internals instead
of shadowing the shell, and it is pinned by a test.

Emptying the file instead would not work: the reference would resolve to the
empty fallback and no rebuild would fire.

## Knowing it happened

`start_service` returns when systemd has started Kodi, not when the skin has
loaded, so the Run waits. It polls the compiled include until the content
differs from the stub and parses as well-formed XML.

The shell's digest-repeat exists because `kodi-send` left it blind to the
starting content. Having written the stub, the Reconciler knows exactly what it
is waiting to stop seeing, so "changed from what we wrote" is an edge rather
than a guess. The parse is what catches the partial write the shell's own
comment warns about — reading mid-write returns an empty file — which a
digest-repeat catches only by timing luck.

A durable signal exists but is not readable during the Run. `write_skinfile`
(`script.module.jurialmunkey`, `futils.py:118-129`) sets two Skin Strings after
writing: `script-skinviewtypes-hash`, the source hash, and
`script-skinviewtypes-checksum`, the md5 of the file it wrote. On the theater
Ugoos the stored checksum equals the compiled include's md5 exactly. Both are
Skin Strings, so they reach `addon_data/skin.arctic.fuse.3/settings.xml` only
when Kodi exits. They are Contested Addresses and the Reconciler declares
neither.

## What this costs and what it buys

The cost is that the rebuild is coupled to a Kodi restart. The Reconciler
already takes that Effect once per Run for Settings Documents
([ADR 0013](0013-a-settings-document-always-takes-the-kodi-stop.md)), so the
slice adds none.

What it buys is that no Run needs Kodi's ear. `services.esenabled` gating the
buildviews probe was half the reason `CORE-020`–`CORE-027` were deferred; that
half is now gone. The remaining half stands, and the cohort stays deferred:
those eight addresses configure the channel the add-on artifact slice will
depend on, and that slice should settle them.

## The alternative that was rejected

Shadowing the shell exactly — JSON-RPC readiness poll, `esenabled` check,
`kodi-send`, digest settle — would have made the Kodi conversation the next
slice, as originally sequenced. It was rejected for being a mechanism built
ahead of anything needing it. `kodi-send` speaks to the EventServer over UDP
and is fire-and-forget: its exit status reports that a datagram left the box,
never that Kodi acted on it. A file write and a restart are both synchronous
and both already in the Run.
