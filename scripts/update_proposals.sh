#!/bin/bash
# Opens, refreshes and closes the Update Proposal pull requests (ADR 0022).
#
# `coreelec-reconciler propose-updates` writes the proposals as files and talks
# to no GitHub; this is the half that does. Each proposal lives on
# update/<profile>/<id>, rebuilt from main and force-pushed every run, so
# nobody resolves a conflict in a bot branch by hand. Nothing here merges.
#
# Needs gh and jq, and GH_TOKEN set to a token that can push and open pull
# requests. A pull request opened with the workflow's own token triggers no
# other workflow, and `ci` and `artifact-patches` must run on these.

set -euo pipefail

BASE="main"
# Marks a pull request this script closed because its proposal no longer
# exists, so it is not mistaken for one a human declined.
SUPERSEDED="update-superseded"

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo}"
out="$(mktemp -d)/proposals"

git fetch -q origin "+refs/heads/${BASE}:refs/remotes/origin/${BASE}" \
  "+refs/heads/update/*:refs/remotes/origin/update/*"

# A version whose proposal a human closed unmerged is not proposed again. A
# newer version is proposed as usual; the GitHub history is the record.
declined=()
while IFS= read -r key; do
  declined+=(--declined "${key}")
done < <(gh pr list --state closed --limit 1000 \
  --json headRefName,body,mergedAt,labels \
  --jq ".[]
    | select(.headRefName | startswith(\"update/\"))
    | select(.mergedAt == null)
    | select([.labels[].name] | index(\"${SUPERSEDED}\") | not)
    | .body
    | capture(\"<!-- update-proposal: (?<key>[^ ]+) -->\").key")

# A channel that cannot be reached is skipped and fails the run, after every
# other proposal has been opened.
status=0
uv run coreelec-reconciler propose-updates --out "${out}" ${declined[@]+"${declined[@]}"} \
  || status=$?

proposed=()
while IFS= read -r -d '' meta; do
  proposal="$(dirname "${meta}")"
  branch="$(jq -r .branch "${meta}")"
  title="$(jq -r .title "${meta}")"
  draft="$(jq -r .draft "${meta}")"
  proposed+=("${branch}")

  git checkout -q -B "${branch}" "origin/${BASE}"
  cp -R "${proposal}/files/." config/
  while IFS= read -r path; do
    if [ -n "${path}" ]; then
      git rm -q "config/${path}"
    fi
  done < "${proposal}/deleted"
  git add -A config
  git commit -q -m "${title}" -m "Proposed by the Update Proposals workflow (ADR 0022)."

  # Pushing the same tree onto the same main again would rerun every check
  # for nothing.
  if git rev-parse -q --verify "origin/${branch}" > /dev/null \
    && [ "$(git rev-parse "origin/${branch}^")" = "$(git rev-parse "origin/${BASE}")" ] \
    && git diff --quiet "origin/${branch}" HEAD; then
    printf 'unchanged %s\n' "${branch}"
  else
    git push -q --force origin "HEAD:refs/heads/${branch}"
    printf 'pushed %s\n' "${branch}"
  fi

  number="$(gh pr list --head "${branch}" --state open --json number \
    --jq '.[0].number // empty')"
  if [ -z "${number}" ]; then
    flags=()
    if [ "${draft}" = "true" ]; then
      flags+=(--draft)
    fi
    gh pr create --base "${BASE}" --head "${branch}" --title "${title}" \
      --body-file "${proposal}/body.md" ${flags[@]+"${flags[@]}"}
  else
    gh pr edit "${number}" --title "${title}" --body-file "${proposal}/body.md"
    held="$(gh pr view "${number}" --json isDraft --jq .isDraft)"
    if [ "${draft}" = "true" ] && [ "${held}" = "false" ]; then
      gh pr ready "${number}" --undo
    elif [ "${draft}" = "false" ] && [ "${held}" = "true" ]; then
      gh pr ready "${number}"
    fi
  fi
done < <(find "${out}" -name proposal.json -print0 | sort -z)
git checkout -q "origin/${BASE}"

# A proposal that no longer exists closes its pull request. Only a run that
# reached every channel knows that, because a skipped channel proposes
# nothing for the records it serves.
if [ "${status}" -eq 0 ]; then
  gh label create "${SUPERSEDED}" --force --color ededed \
    --description "Closed by the Update Proposals workflow" > /dev/null
  while read -r number branch; do
    keep=false
    for held in ${proposed[@]+"${proposed[@]}"}; do
      if [ "${held}" = "${branch}" ]; then
        keep=true
      fi
    done
    if [ "${keep}" = "false" ]; then
      gh pr edit "${number}" --add-label "${SUPERSEDED}"
      gh pr close "${number}" --delete-branch \
        --comment "This Update Proposal no longer exists on ${BASE}, so it is closed."
    fi
  done < <(gh pr list --state open --limit 1000 --json number,headRefName \
    --jq '.[] | select(.headRefName | startswith("update/"))
      | "\(.number) \(.headRefName)"')
fi

exit "${status}"
