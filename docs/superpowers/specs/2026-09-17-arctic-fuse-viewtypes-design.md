# Arctic Fuse Season and Episode View Types Design

## Status

Approved for implementation planning. Every path, identifier, value, and
behavioral claim below was established on the live `ugoos-theater` device
during the spike recorded in issue #27, or read back from that device while
writing this design. Nothing here is inferred from documentation.

## Context

Issue #4 assumed that provisioning season and episode view types would require
"controlled view-state database mutation". It does not. Kodi's
`userdata/Database/ViewModes6.db` on `ugoos-theater` contains zero rows: Kodi
is not persisting these views at all. Arctic Fuse routes them through
`script.skinvariables` instead.

The state lives in two places, and only one of them is authored:

| Role | Path |
| --- | --- |
| Source | `.kodi/userdata/addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json` |
| Effective | `.kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml` |

The JSON holds two scopes, `library` and `plugins`, each mapping 37 content
types to a view id. `script.skinvariables` compiles it into the XML, and the
skin reads only the XML.

The device's managed intent is two values in the `library` scope:

| Content | Managed | Meaning | Skin default |
| --- | --- | --- | --- |
| `seasons` | `509` | List Flixart | `521` (Combined Landscape) |
| `episodes` | `549` | List Flixart 2 | `501` (Row Landscape) |

The names come from the skin's own `shortcuts/skinviewtypes.json` viewtype map
and `language/resource.language.en_gb/strings.po` (`31480`, `31040`, `31003`,
`31112`). The `plugins` scope on the device is untouched skin default.

### Why this cannot be a plain file deployment

Four findings from the spike constrain the design.

**Writing the JSON alone changes nothing.** `viewtypes.py` gates regeneration:

```python
if not makexml and self.xmlfile_exists(skinfolder):
    return
```

`makexml` comes from `force`, or from a hash taken over the *skin's* rules file
(`special://skin/shortcuts/skinviewtypes.json`) — never over the addon_data
JSON we write. Changing `library.episodes` from `549` to `502` and rebuilding
without `force` left the compiled XML's md5 unchanged at
`381c1f29cf61143f49926ee6425e18d4`.

**There is exactly one deterministic trigger**, and it requires a running Kodi:

```
kodi-send --action='RunScript(script.skinvariables,action=buildviews,force=True,no_reload=True)'
```

`kodi-send` is present at `/usr/bin/kodi-send` on CoreELEC.

**JSON-RPC cannot be substituted.** `script.skinvariables` declares both
`xbmc.python.script` and `xbmc.python.pluginsource`, so
`Addons.ExecuteAddon` runs `plugin.py`, silently ignores `action=buildviews`,
and still returns `"OK"`.

**A Kodi restart does not regenerate a missing compiled XML.** The file was
deleted, Kodi restarted, the skin fully loaded, and the file was still absent
two minutes later.

That last finding exposes a latent defect that exists today, independent of
this issue: the compiled XML lives *inside* the skin add-on directory, which
provisioning replaces wholesale on every skin artifact deploy. Nothing
restores or rebuilds it, so season and episode views silently revert to skin
defaults after any skin redeploy or version bump.

## Goals

- Provision `library.seasons` and `library.episodes` idempotently.
- Make the compiled XML converge on every skin-effective run, closing the
  silent-revert defect.
- Verify semantically, against meaning rather than bytes.
- Leave every other content type, and the entire `plugins` scope, untouched.
- Keep the deployment transaction recoverable, including on rollback.

## Non-goals

- Managing any content type other than `seasons` and `episodes`.
- Managing the `plugins` scope.
- Reimplementing the add-on's compiler to generate the XML ourselves. The
  output is deterministic, but reproducing it would couple provisioning to the
  add-on's internals across versions.
- Applying new views to the *running* Kodi session. The rebuild runs with
  `no_reload=True`; see "Reload behavior".

## Design

### The source is merged, not replaced

The transform reads the existing JSON, sets `library.seasons` and
`library.episodes`, and writes it back atomically. The other 72 values are
preserved exactly as found.

A whole-file managed artifact was rejected. `make_xmlfile` rewrites the JSON
on every rebuild, merging in skin defaults, so a fully-specified managed copy
would drift the moment Arctic Fuse adds a content type — verification would
then fail on a difference provisioning neither caused nor cares about.

If the file is absent, empty, or unparseable, the transform writes a minimal
document containing only the two managed keys. `make_defaultjson(overwrite=True)`
fills in the remaining defaults on the next rebuild, and our values win that
merge. This is the documented behavior of the add-on, confirmed during the
spike.

Because the add-on rewrites the file, the bytes we wrote are not the bytes on
disk afterward. Verification therefore compares parsed content, never bytes.

### The effective state is rebuilt by a new stage

A new remote stage, `buildviews`, runs on the host between deployment and
verification:

1. The deploy transaction runs unchanged: stop Kodi, write files including the
   viewtypes JSON, start Kodi.
2. **New.** The host runs the `buildviews` stage over SSH. The stage polls the
   device's own localhost JSON-RPC endpoint until Kodi answers
   (`COREELEC_BUILDVIEWS_ATTEMPTS`, default 24, at
   `COREELEC_BUILDVIEWS_RETRY_DELAY`, default 5 seconds — the same shape as
   `COREELEC_VERIFICATION_ATTEMPTS`), then invokes `kodi-send` with
   `action=buildviews`, `force=True`, `no_reload=True`.
3. Verification runs, using its existing 13-attempt retry loop.

The stage is emitted through the same `--emit-remote-script` mechanism as
`verify-probe`, `display-probe`, and `audio-probe`, and is independently
testable the same way.

Three alternatives were considered and rejected:

- **Rebuilding inside the remote deploy transaction.** It would put an
  unbounded wait for Kodi readiness inside the critical section, while the
  transaction's emergency-restart trap is armed. The deploy script is
  deliberately a pure POSIX-sh file transaction.
- **Rebuilding from the verification probe.** The probe must remain an
  observer. A probe that mutates cannot be trusted to report, and self-healing
  would mask drift rather than surface it.
- **Rebuilding only when the source changed.** It would duplicate the
  detection logic verification already performs, and would skip the rebuild in
  exactly the case that matters most — a skin artifact redeploy that destroyed
  the compiled XML while leaving the JSON untouched.

The rebuild is therefore **unconditional on every skin-effective run**. The
spike proved the output byte-deterministic: restoring the original JSON and
forcing a rebuild reproduced the compiled XML exactly, 8245 bytes, same md5,
with `script-skinviewtypes-checksum` returning to its original value.

### The stage cannot prove success, and does not try

`kodi-send` speaks to Kodi's EventServer over UDP. It is fire-and-forget: its
exit code reports that a datagram was sent, never that Kodi acted on it. Two
consequences shape the design.

**EventServer is a dependency, and an unmanaged one.** On `ugoos-theater` the
`services.es*` settings all carry `default="true"`, meaning no value has been
set and Kodi's built-in default applies. That default is enabled, so the
trigger works today — but the device depends on a default nothing verifies,
the same failure shape the room design flagged for the Dolby Vision settings.
If EventServer were disabled, `kodi-send` would succeed and nothing would
happen.

The stage therefore reads `services.esenabled` over JSON-RPC before sending
and fails with a named error if it is false, converting a silent no-op into a
loud failure. Managing the setting is deliberately out of scope here: it
belongs to a service-level component, not to view types.

**Verification is the authority, not the stage.** The stage makes the attempt
and waits for the result to settle; it does not adjudicate. A `kodi-send` that
quietly did nothing leaves the compiled XML either missing or holding its
previous content, and both cases fail the semantic checks below, retry, and
ultimately roll back. This keeps the stage simple and puts the judgement in
the one place that reads the actual state.

### Settling

The rebuild is not atomic. Reading the compiled file mid-rebuild returned an
empty file (`d41d8cd98f00b204e9800998ecf8427e`). The stage therefore does not
return until the file is non-empty and its size and mtime are stable across
two consecutive samples, bounded by `COREELEC_BUILDVIEWS_SETTLE_ATTEMPTS`
(default 12, at one second). Verification's retry loop
remains the backstop: a partial read observes `0` and is retried rather than
failing the run outright.

### Reload behavior

The rebuild uses `no_reload=True`, suppressing the `ReloadSkin()` the script
would otherwise fire.

The alternative was rejected on evidence. A skin load causes Kodi to rewrite
`addon_data/skin.arctic.fuse.3/settings.xml` — the behavior established in
issue #30 — and the rebuild itself is non-atomic. Firing `ReloadSkin()`
immediately before verification would inject exactly that churn into the
window where verification reads those files.

The consequence is that new views take effect at the next skin load rather
than instantly. Since the deployment already restarts Kodi before the rebuild,
a device provisioned from cold is correct on its next start. This is
documented for operators rather than worked around.

### Verification

Two observations, produced by the existing verification probe under the `skin`
component and folded into `arctic_fuse.status`:

**`arctic_fuse.viewtypes_source_configured`** — the JSON parses, and
`library.seasons == "509"` and `library.episodes == "549"`.

**`arctic_fuse.viewtypes_compiled_configured`** — the compiled XML parses and,
for each managed content type, *exactly one* `<expression name="Exp_View_*">`
body contains the library-scope clause:

```
Container.Content(<type>) + [String.IsEmpty(Container.PluginName)]
```

and that expression is the expected id. Read back from the device, this
discriminates exactly:

```text
seasons  -> library-scope owners: ['Exp_View_509']
episodes -> library-scope owners: ['Exp_View_549']
```

The clause is precise in two ways that matter. `[String.IsEmpty(...)]` alone
selects the `library` scope; the `plugins` scope compiles to
`[!String.IsEmpty(...)]`, and a view serving both compiles to the disjunction
`[[String.IsEmpty(...)] | [!String.IsEmpty(...)]]`. And
`Container.Content(seasons)` with its closing parenthesis does not collide with
`episode-groups-seasons`, which shares the `Container.Content(seasons)` token
but is discriminated by its `episode_group_seasons` guard — confirmed by
`Exp_View_521` carrying that token without matching the clause.

If Arctic Fuse ever changes this expression grammar, the check fails loudly
rather than passing silently. That is the correct failure direction for a
verification predicate: a missing view is a defect, and a check that cannot
prove the view is present must not claim it is.

A missing, empty, or partially-written compiled file observes `0`.

Report keys follow the existing convention: `arctic_fuse.viewtypes_source.*`
and `arctic_fuse.viewtypes_compiled.*`, each with `expected`, `observed`, and
`status`.

### Backup and rollback

The JSON lives under `addon_data/script.skinvariables`, already a registered
managed directory, so the existing backup of scoped settings paths covers it.

The compiled XML is additionally backed up into the transaction and restored
on rollback. This deviates from the spike's recommendation to treat it purely
as derived state and rebuild rather than restore, for a reason the spike did
not consider: on rollback the JSON reverts to its previous values, and a
compiled XML left at the new values would leave the device internally
inconsistent until some later run happened to rebuild it. It is a single 8 KB
file, and restoring it makes rollback exact without making rollback depend on
a live Kodi — which rollback must never do, since it has to work when Kodi is
the thing that is broken.

## Testing

**Settings transform** (`tests/test-coreelec-settings.sh`)

- The two managed keys are written into the `library` scope.
- All other `library` content types are preserved byte-for-byte.
- The entire `plugins` scope is preserved, including `seasons` and `episodes`.
- An absent source produces a minimal document with only the two keys.
- An empty or malformed source is replaced rather than crashing the transform.
- A second run over a transformed tree changes nothing.

**Verification probe** (`tests/test-coreelec-report.sh`)

- A correct fixture observes `1` for both new observations.
- A drifted `library.seasons` fails `viewtypes_source` and `arctic_fuse`.
- A compiled XML whose `episodes` clause names a different view fails
  `viewtypes_compiled`.
- A missing compiled file observes `0`.
- An empty compiled file — the mid-rebuild case — observes `0` rather than
  raising.
- A compiled XML where two expressions claim the same content type in the
  library scope observes `0`.
- The passing-device fixture gains both keys, as every new observation must.

**Stage and scope** (`tests/test-coreelec-artifacts.sh`,
`tests/test-coreelec-config.sh`)

- `--emit-remote-script buildviews` emits the stage.
- The stage is rejected by name when unknown, matching sibling stages.
- A run whose components exclude `skin` never rebuilds and never reports the
  new keys, gated on `coreelec_component_effective skin`.
- The stage fails with a named error when `services.esenabled` is false.

## Live verification

On `ugoos-theater`, with `keep_kodi_running` on for the duration:

1. Run `--component skin` and confirm the run converges with
   `verification_failures=0` and both new keys `ok`.
2. Drift `library.episodes` on the device, re-run, and confirm convergence
   returns it — the same convergence proof used for the shared library
   preferences in #25.
3. Delete the compiled XML, re-run, and confirm the stage rebuilds it. This is
   the direct test of the silent-revert defect.
4. Restart Kodi and confirm the views survive.

`keep_kodi_running` is returned to off afterward.

## Documentation

`config/README.md` gains the two managed values and the statement that the
compiled XML is derived state rebuilt on every skin-effective run.

`docs/operations/provision-ugoos.md` gains an operator-facing section covering
the two views by name, the fact that they apply at the next skin load rather
than instantly, and the defect this closes: before this change, any skin
redeploy silently reverted them.
