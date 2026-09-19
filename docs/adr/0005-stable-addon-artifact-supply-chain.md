---
status: accepted
---

# Use a stable-first reviewed add-on Artifact supply chain

Add-on Artifacts will default to stable upstream releases and GitHub Actions may only propose evidence-rich pull requests for review; it will never auto-merge or deploy them. A prerelease requires an explicit per-Artifact rationale, pinned digest, additional acceptance evidence, and an expiry or review trigger, while patched Artifacts must be reproducibly built and record upstream, patch-set, and final provenance digests so Devices install a prebuilt final Artifact rather than applying runtime transforms.

The accepted issue #47 refinement is recorded in
[`2026-09-18-addon-update-patch-supply-chain.md`](../research/2026-09-18-addon-update-patch-supply-chain.md).
It preserves this stable-first decision while making expiry mandatory,
separating origin from distribution, defining repository-owned mirroring,
and fixing proposal, dependency, attestation, and workflow contracts.
