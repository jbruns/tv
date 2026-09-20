# Agent skills

The skills this repository uses come from
[`mattpocock/skills`](https://github.com/mattpocock/skills) (MIT). They are
**pinned, not vendored**: `skills-lock.json` records the exact upstream commit,
and the tree under `.agents/skills/` is restored from it and gitignored.

## Restore them

```console
npx skills@latest experimental_install
```

This reads `skills-lock.json`, checks out the pinned ref, and writes
`.agents/skills/`. Restored content is byte-identical to the pin.

## Move the pin

Skills iterate upstream. To take a newer version, install from a ref URL and
commit the resulting `skills-lock.json`:

```console
npx skills@latest add https://github.com/mattpocock/skills/tree/<ref> \
  -s '*' -a github-copilot -y --copy
```

`<ref>` may be a tag, branch, or commit SHA.

Two things to know before you do:

- **The `owner/repo@ref` shorthand does not pin.** `skills add
  mattpocock/skills@v1.2.3` silently resolves against the default branch and
  installs whatever is at HEAD. Only the full `tree/<ref>` URL is honored.
  Check `ref` is present on every entry in the lockfile afterwards.
- **The newest release is not the newest content.** Several skills we use are
  unreleased and exist only on the default branch, so tags can be older than
  what is already installed.

## Why pinned rather than vendored

The upstream installer copies editable files into the repository by design, so
the obvious move is to commit them. We don't, because the lockfile pin gives
the same reproducibility without carrying several thousand lines of somebody
else's Markdown in this repository's history and diffs.

The tree is therefore third-party content we do not own. Edit a skill in place
and the next restore silently discards it. Repository-specific agent guidance
belongs here in `docs/agents/`, or in `AGENTS.md`.

`scripts/check_markdown.py` skips `.agents/` for the same reason: those
relative links resolve against the upstream repository, not this one.

## Caveats

`experimental_install` is marked experimental upstream and may change. If it
breaks, the fallback is the `add` command above with the ref from
`skills-lock.json`.
