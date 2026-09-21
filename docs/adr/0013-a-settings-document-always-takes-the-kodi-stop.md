---
status: accepted
---

# A Settings Document always takes the Kodi stop

The Reconciler manages `guisettings.xml` by stopping `kodi.service`, re-reading
the document, merging, and writing once, because Kodi holds the document in
memory and rewrites it from memory as it exits. Extending that Resource Type to
the other Settings Documents — add-on `settings.xml` in both of Kodi's dialects,
and the CEC file under `peripheral_data/` — raised the question of whether each
document should declare whether it needs the stop.

It should not. **The Kodi stop is a property of the Settings Document Resource
Type, taken for every document it manages, and it is never declared in a
Profile.**

This is worth recording because the repository contains evidence that the stop
is unnecessary for some documents. A restart trial on the theater Ugoos found
that `skin.arctic.fuse.3/settings.xml` was rewritten across a Kodi restart while
`plugin.video.themoviedb.helper/settings.xml` and `script.plexmod/settings.xml`
were untouched, and the onboarding contract draws the rule accordingly: only
add-on settings "that Kodi has loaded" are Kodi-owned. A future reader will find
that trial and reasonably ask why we stop Kodi for a file Kodi demonstrably left
alone.

The answer is that *loaded* is a runtime property, not a property of the
document. TMDb Helper's file survived that restart because the add-on happened
not to be loaded at that moment; enabling it, opening it once, or a later Kodi
version instantiating it earlier all change the answer without changing anything
a Profile could see. Declaring "this document does not need the stop" would
therefore encode a snapshot of runtime state into configuration, and the failure
it produces is the worst one available here: the write lands, Kodi overwrites it
from memory on exit, and Verification reports Convergence because it ran before
the exit. Nothing in a later Run would distinguish that from success.

Kodi's own code makes the cost of the conservative choice small. `CPeripheral`'s
destructor calls `PersistSettings(true)`, which rebuilds the entire `<settings>`
document from the in-memory map and overwrites the file — so the CEC document
has exactly the `guisettings.xml` hazard, a fact this repository had not
previously established. Add-on settings persist through `CAddon::SaveSettings`
on the same pattern. The documents that are genuinely safe with Kodi running are
the ones that are not Settings Documents at all: Smart Playlists, which Kodi
reads on demand, and the Skin Variables JSON, which Kodi core never parses.
Those are separate Resource Types and are unaffected by this decision.

The stop is taken once per Run around the whole apply, as
[ADR 0009](0009-fail-forward-and-exclusive-execution-ownership.md) requires, so
managing twenty documents costs the same restart as managing one. There is no
per-document saving to be had by declaring the exception, only a way to get it
wrong.

## Considered and rejected

**Declaring the Effect per document.** A Profile that states each document's
Effects reads as a complete description of what a Run will do. It also lets
someone omit the stop, and an omitted stop fails silently. The Resource Type
knows the answer; the Profile author does not need to.

**Reading the add-on's definition file to decide.** An add-on's valid setting
ids are enumerable on the Device at `<addon>/resources/settings.xml`, and
instance settings at `resources/instance-settings.xml`. That tells us what a
document may contain, not whether Kodi has it open, so it does not answer this
question. It was also rejected as a way to enforce the `create` rule of
[ADR 0012](0012-shadow-the-shell-and-retire-it-wholesale.md): `guisettings.xml`
is core and has no definition file, so the check would cover some documents and
not others while appearing to cover all, and the behavioural rule — no declared
address may plan as `create` on a provisioned Device — already catches the typo
it would catch, on the first Run, for nothing.
