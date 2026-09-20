# Working in this repository

## The bar

Read [ADR 0007](docs/adr/0007-trusted-home-appliance-bar.md) before writing
code. This project manages home streaming appliances on a trusted home
network. It is not an audit-grade, enterprise, or adversarially-hardened
system, and must not be built as one.

Three rules follow from it:

- **Weigh every edge case.** Before writing a mechanism that exists only to
  handle a failure, name the failure, how likely it is, and what recovery
  costs without it. Unlikely or cheaply-recoverable failures do not justify
  significant machinery. Disaster recovery is reprovisioning from scratch.
- **No mechanism before a slice needs it.** Do not write design documents
  that specify machinery in advance, and do not build infrastructure for a
  failure that has not happened. Work is delivered as vertical slices that
  each work end-to-end on real hardware.
- **Test at the boundary.** Tests may not import from the package except
  through its public entry point. See
  [ADR 0011](docs/adr/0011-linux-only-ci-and-boundary-tests.md).

Milestones M0 through M3 ignored these rules and produced 29,582 lines of
Python that never contacted a device, against 11,390 lines of working shell.
[ADR 0008](docs/adr/0008-restart-from-a-walking-skeleton.md) records what went
wrong. The original architecture document is retained in `docs/research/` as a
historical record; do not build from it.

## Domain language

`CONTEXT.md` is the glossary. Use its terms, prefer them over the listed
alternatives, and keep implementation detail out of it.

## Agent skills

### Issue tracker

Issues are tracked in this repository's GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the canonical `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix` labels. See `docs/agents/triage-labels.md`.

### Domain docs

Domain documentation uses a single-context layout. See `docs/agents/domain.md`.
