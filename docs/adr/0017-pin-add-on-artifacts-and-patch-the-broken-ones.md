---
status: accepted
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

## The Artifact Lock is its own file

The Lock lives beside `profile.yaml` in the same Profile directory rather than
inside it. Requirement 3 decides this: a bot rewriting the file humans edit for
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

## What an add-on's Observation is

`/storage/.kodi/addons/<id>/addon.xml` declares the installed version, and it
matches the pin exactly — `0.0.6.6`, `1.16.0+matrix.1`, `21.3.2.1`. So
observing an add-on is reading one small file. Hashing the installed tree
cannot work: the installed tree is the *expanded* archive, so its hash is never
the Artifact's, and three of our add-ons are deliberately patched afterwards. A
Reconciler-written receipt on the Device was rejected because it can disagree
with reality, while `addon.xml` is what Kodi itself believes.

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
