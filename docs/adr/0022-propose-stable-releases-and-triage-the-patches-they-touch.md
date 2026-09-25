---
status: accepted
amends: ADR-0017
---

# Propose Stable Releases as reviewed pull requests, and triage the patches they touch

[ADR 0017](0017-pin-add-on-artifacts-and-patch-the-broken-ones.md) required an
Action that proposes add-on updates and never applies them, and left it
unbuilt. This ADR records its shape, and reverses one thing ADR 0017 said.

## A dependency bump is a decision too

ADR 0017 said bumping a `dependency` is "a consequence of a decision, never a
decision". That no longer holds. Many of these add-ons talk to external
services, some through reverse-engineered APIs: TMDb, Plex, Emby, Widevine
through `script.module.inputstreamhelper`, and TLS through
`script.module.certifi`. When those services change, the fix is a newer
release, and it is as likely to land in a dependency as in the add-on someone
chose. Staying compliant with those services is reason enough to take any
Stable Release.

So every record whose Release Channel offers a newer Stable Release gets an
Update Proposal, whatever its `role`. `role` still matters: it decides how a
bump is grouped and described, and what is removed along with a `chosen`
add-on. It no longer decides whether a bump is proposed.

## The Lock names each record's Release Channel

One add-on id is published in more than one place, at different versions.
Kodi's own Omega index carries `plugin.video.themoviedb.helper` 5.4.16 while
jurialmunkey's carries 6.17.4, and `script.skinvariables` is 2.1.33 in one and
2.2.4 in the other. "The newest version anywhere" is therefore the wrong
question. The right one is "the newest version in the channel this pin came
from".

Deriving the channel from the pinned URL was rejected. It fails on day one for
`script.plexmod`, which is pinned to a commit rather than the index directory;
for `weather.ha`, which only has GitHub tags; and for `repository.emby.kodi`,
which appears in no index. So the Lock gains a `channels:` map naming each
Release Channel once. Each one is either a Kodi repository `addons.xml` for
this Kodi version or a GitHub repository's tags. Each record gains a
`channel:` field naming one entry in the map. These are the provenance fields
ADR 0017 said would arrive with the proposer.

A version in a channel is a Stable Release unless its version string carries
`alpha`, `beta`, `rc` or `~`. The channel is already scoped to this Kodi
version, and the filter is cheap insurance on top. CoreELEC's channel is
scoped to the CoreELEC release, so add-ons whose version follows CoreELEC
(`pvr.nextpvr` and the two inputstreams) need no exclusion.

A proposed pin's URL follows Kodi's own convention,
`<datadir>/<id>/<id>-<version>.zip`, or the tag archive for a GitHub channel.
The SHA-256 fixes the bytes, so resolving URLs to immutable commits is not
worth doing. If a superseded zip disappears, the recovery is the next
proposal.

## One proposal per add-on, rebuilt from `main` every run

An Update Proposal moves one record, together with any dependency bumps its
new `<requires>` floors force. It lives on `update/<profile>/<id>`, and every
run rebuilds that branch from `main`. A dependency gets a proposal of its own
only if no other proposal in the same run already moves it. Merging one
proposal therefore makes the next run rebase or close the ones it overlapped,
and nobody resolves a conflict in a bot branch by hand.

A requirement new to the Lock is added with `role: dependency` if exactly one
known channel satisfies it; otherwise the proposal opens as a draft saying
why. A requirement that disappears is reported in the proposal and nothing is
removed.

If a repository add-on's new `addon.xml` moves the directory it publishes for
this Kodi version, the proposal says so and a human edits the `channels:` map.
The Action never edits the map.

## Patches are triaged, not rewritten

For each Artifact Patch a bumped add-on carries, the Action reaches one of
three verdicts:

- **Carried Patch**: it still applies. Its version header is rewritten and
  `record-patches` regenerates the post-patch hashes.
- **Obsolete Patch**: it reverse-applies, so the new version already contains
  the corrected text. The proposal deletes it. That is evidence upstream fixed
  the fault, not proof, so the reviewer confirms it.
- **Stale Patch**: neither of the above. The proposal opens as a draft with
  the reject hunks and the upstream diff of each touched file, and a human
  rewrites the patch.

Fuzzy application was rejected because it can land a correction in the wrong
place, and a result that compiles is not proof it is right. Handing Stale
Patches to a coding agent was deferred: this fleet carries five patches, and
the mechanism can wait until drafts turn out to be common.

## What a proposal carries, and who accepts it

The proposal body lists:

- the old and new version
- the upstream `<news>`
- the record's `notes`, quoted, so a warning such as Arctic Fuse's about the
  Shortcut Nodes written against it is read at the moment it matters
- any change to `<requires>`
- each patch verdict, with the upstream diff of every file a patch touches
- a checkbox confirming a Device running this Profile was reconciled from the
  branch

It carries no full source diff.

Proposals are opened with a fine-grained personal access token scoped to this
repository, because pull requests opened with the workflow's own token trigger
no other workflows, and `ci` and `artifact-patches` must run on them. Nothing
auto-merges. Closing a proposal unmerged stops that exact version being
proposed again, and a newer version is proposed as usual. The GitHub history
is the record; the Lock carries no hold field.

The Action runs weekly and on demand. It processes every Artifact Lock under
`config/`, and nothing coordinates across Profiles until a second Profile
exists. If a channel cannot be reached, the run skips it, still produces the
other proposals, and fails at the end, so the next week's run is the recovery.

The logic is a Reconciler subcommand rather than a script. The Lock parser and
the fetch, digest, expand and patch pipeline already live in the package, and
[ADR 0011](0011-linux-only-ci-and-boundary-tests.md)'s boundary tests then
cover it.
