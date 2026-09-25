---
status: accepted, amended by ADR-0022
supersedes: ADR-0005
---

# Pin add-on Artifacts, and patch the ones upstream has broken

[ADR 0005](0005-stable-addon-artifact-supply-chain.md) specified a supply chain
with repository-owned mirroring, mandatory expiry, attestation, deterministic
rebuilds, and a 467-line contract for source adapters and proposal identity.
None of it was built. What exists and works is 197 lines
(`lib/coreelec-artifacts.sh`) plus 41 pinned records in `provision.conf`. ADR
0005 also required that "Devices install a prebuilt final Artifact rather than
applying runtime transforms", and the Recovery Baseline violates that four
times over: it patches `weather.ha` twice, `script.plexmod` once, and
`plugin.video.themoviedb.helper` once.

An accepted decision that the working system contradicts is worse than no
decision, because a reader cannot tell which parts still bind. This ADR
replaces it with what we actually need.

## Three requirements

1. **Pin known-good versions, and the bytes of those versions.** A Profile
   states which version of each add-on it installs and the SHA-256 of the
   archive that version is, so a fetch that returns different bytes fails
   rather than installs.
2. **Correct add-ons upstream has broken.** Four one-line fixes stand between
   this fleet and add-ons that crash. Waiting for upstream is not a plan, and
   running a fork to deliver a missing `continue` is not proportionate.
3. **Propose updates automatically, and never apply them automatically.** An
   Action should watch the sources and open a pull request when a new stable
   version appears. It must never merge or deploy one.

Requirement 3 is not built. It is recorded here because it is the reason for a
decision taken now: the Artifact Lock is structured data rather than
`|`-delimited records annotated with prose comments, because something other
than a human has to read and rewrite it. The *provenance* fields an update
proposer needs — which channel to watch, how to recognise a stable release —
arrive with the proposer that reads them, not before. Today's deviation
rationales become a `notes` field on the record so they stay attached to the
pin a reviewer is being asked to move.

### `role` separates a decision from a consequence

`notes` answers "why this version and not the newest". A second field, `role`,
answers "why is this add-on here at all", with three values: `chosen`,
`dependency`, `repository`.

The two questions looked like one until the Lock was widened past a single
record. The forty entries split twenty-six `dependency`, eleven `chosen` and
three `repository`, and thirty-four of them have no version deviation to
explain, so their `notes` is `~` and without `role` the record would say
nothing at all about why it exists.

The distinction is not bookkeeping. Bumping a `chosen` add-on is a decision
someone makes; bumping a `dependency` is a consequence of one. Removing a
`chosen` add-on should remove the dependencies nothing else needs. An update
proposer that cannot tell the two apart proposes the wrong bumps, and
requirement 3 is the reason the field is worth its keep.

`role` is an intent, not a graph. Which add-on requires which is already
derivable from `<requires>` in `addon.xml`, which the Reconciler parses. That
a human *wanted* an add-on is derivable from nothing.

## The Lock's boundary is derived, not listed

Every directory under the add-on address is in the Lock, is in Kodi's own
`addon-manifest.xml`, or is not an add-on at all. There is no fourth category,
and on a provisioned Device today there are no exceptions.

The shell maintained a hand-written allowlist of add-ons it tolerated but did
not pin. That list conflated two unrelated things. Seven of its nine entries
are in Kodi's manifest, so Kodi stamps them with its own system origin,
enables them itself, and versions them with Kodi — they are not a gap in our
supply chain, they *are* Kodi, and pinning them would mean overwriting files
Kodi considers part of itself on every upgrade. The other two were genuine
operator installs from the official repository, unrecorded anywhere but a
comment, and they belong in the Lock like anything else we chose.

Deriving the boundary from the manifest is what keeps it honest. A
hand-written list is a statement about the past that nothing updates; the
manifest is on the Device and answers for the Kodi that is actually installed.
An add-on is a directory containing `addon.xml`, which excludes Kodi's scratch
directories by observation rather than by naming them.

What falls outside all three is reported, not failed. An add-on appearing from
nowhere is interesting and we want to know, but we do not yet know what a Run
should *do* about one, and guessing would make the Reconciler refuse to work
for a reason nobody chose.

## The Artifact Lock is its own file

The Lock lives beside the Profile's other files in the same directory rather
than inside any of them. Requirement 3 decides this: a bot rewriting the file humans edit for
settings turns every routine version bump into a conflict with unrelated work,
and a reviewer reads "one version and one hash moved" very differently from a
settings change. Splitting manifest from lock is what every language ecosystem
does, for this reason.

## Artifact Patches are unified diffs, applied on the controller

Each patch is a diff file. The shell hand-codes each one instead: exact
expected line tuples, a second tuple describing the already-patched form,
occurrence counts, then an insertion. A diff's context lines *are* that
assertion, and "is it already applied?" is a reverse dry-run rather than a
second hand-written tuple, so roughly 230 lines of bespoke matching become four
small reviewable files. A diff is also the form these fixes would take if they
were ever sent upstream, which is where they belong.

Patches are applied to the expanded Artifact **on the controller**, and the
Device receives the finished tree. CoreELEC has `unzip` and `python3` but no
`patch`, so the alternative is reimplementing diff application on the Device.
Applying on the controller also reaches what ADR 0005 actually wanted — a
Device that installs final bytes — without a fork or a build pipeline. And it
makes Observation fall out for free: the desired content of a patched file is
computable locally, so those files are read back and compared, with no separate
declaration of how to observe a patch.

Each patch keeps the version assertion the shell makes. A version bump fails
loudly and forces the patch to be re-reviewed, which is the safeguard that
makes carrying patches acceptable at all.

### How a patch is written and applied

Patches live in `patches/<addon-id>/` beside the Lock, and the Lock record
lists them. Each file opens with a header comment naming the add-on and the
version it was written against; `patch` ignores leading text, and we check the
assertion against the Lock *before* anything is fetched, so a bump that
outruns its patches fails at once rather than after an 8 MB download.

Keeping the diff in its own file rather than a YAML block scalar is what lets
`patch` read it and a reviewer see it as a diff, in a format that is already
whitespace-significant for a different reason.

Application shells out to `patch` on the controller. We already shell out to
`ssh` and `curl`, so an external binary is not a new category, and writing a
diff applier to avoid a dependency we would not be taking anyway is
reimplementing a very old tool.

The shell's idempotence machinery does not survive. Its second tuple, its
occurrence counts and its already-patched branch exist because it re-patches
a tree that is already installed. We patch a freshly expanded archive whose
bytes are fixed by SHA-256, so "already patched?" describes an input that
cannot occur.

What does survive is the syntax check. A clean application proves the context
matched; it does not prove the result parses, and most patched files are
Python that Kodi imports at boot. Compiling the patched source turns a silent
add-on failure on the appliance into a failed Run on the controller.

## What an add-on's Observation is

`/storage/.kodi/addons/<id>/addon.xml` declares the installed version, and it
matches the pin exactly — `0.0.6.6`, `1.16.0+matrix.1`, `21.3.2.1`. So
observing an add-on is reading one small file. Hashing the installed tree
cannot work: the installed tree is the *expanded* archive, so its hash is never
the Artifact's, and three of our add-ons are deliberately patched afterwards. A
Reconciler-written receipt on the Device was rejected because it can disagree
with reality, while `addon.xml` is what Kodi itself believes.

### A patched add-on is not identified by its version

For the three patched add-ons, the version is not enough. Correcting a patch
does not move the add-on's version, so the Device still reports `6.17.1`, the
Plan sees no difference, and the corrected patch never ships. Since iterating
on patches is the whole point of carrying them, this is the ordinary case
rather than the exotic one.

So a patched add-on is observed by its version *and* by the hashes of the
files its patches touch — the list comes from the diffs' `+++` headers, so
nothing is declared twice. The Lock records the expected post-patch hash of
each touched file, and a command on the Reconciler regenerates them by running
the real pipeline: fetch, prove the digest, expand, patch.

Recording the result rather than recomputing it keeps `plan` offline and
instant. The alternative is downloading and patching those add-ons on every
Run, which puts a network round-trip in the path that runs even when nothing
changes. It also makes a patch reviewable as "this produces exactly these
bytes" instead of "trust the diff", which is the same argument that pinned the
upstream bytes in the first place. The cost is generated data a human must not
hand-edit, so a CI job filtered to the Lock and `patches/` regenerates and
compares it — running exactly when the answer could have changed, rather than
making every unrelated pull request depend on six upstream hosts.

Encoding patch identity in the version instead — shipping `6.17.1+tv.1` — was
rejected. Kodi parses the idiom, `1.16.0+matrix.1` proves that, but
`skin.arctic.fuse.3` declares a dependency floor of `6.14.3` on
`plugin.video.themoviedb.helper`, so this would rewrite the identity another
add-on compares against to buy something the file hashes give without touching
upstream's metadata.

Because the Plan ships only add-ons whose declared version differs, the
expensive work is bounded by the diff and is empty on a converged Device. The
Run selection mechanism we expected to need here is therefore not built: a
fresh Device needs all of them regardless, so selection would not help the one
case that is genuinely slow.

A replaced directory is not kept. The Artifact is pinned by URL and SHA-256, so
a rollback copy stores on the Device something the Lock can reproduce at any
time. An interrupted Run is repeated, per
[ADR 0009](0009-fail-forward-and-exclusive-execution-ownership.md).

The research document
[`2026-09-18-addon-update-patch-supply-chain.md`](../research/2026-09-18-addon-update-patch-supply-chain.md)
stays in `docs/research/` as a historical record, like the original
architecture document. Do not build from it.
