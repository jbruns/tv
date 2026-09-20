---
status: accepted
---

# Run CI on Linux only, write portable code, and test at the boundary

CI runs on Linux alone. The controller is also run from macOS, so macOS is
covered by a local pre-commit hook running formatting, linting, strict typing,
and the tests rather than by a hosted runner. This is only safe paired with a
second rule: no platform-specific code. Where behaviour genuinely differs, the
option that works everywhere is chosen and the weaker guarantee accepted — the
Reconciler's local state is disposable, so a portable `fsync` beats a macOS
branch. The CI matrix is not pinned by any test, so changing platforms is a
one-file edit rather than a reopened decision. This amends ADR 0006, which
named Linux and macOS as supported peers exercised by CI.

Tests may not import from the package except through its public entry point.
They drive the published interface and assert observable outcomes, because
tests that reach inside modules both inflate the test tree and weld the
implementation in place — 20,627 lines of tests asserting on internal
machinery are what made the M3 implementation impractical to simplify. Under
this rule any internal module can be deleted without touching a test, and a
module justifiable only by tests that reach inside it should not exist. The
bespoke test-budget runner and its evidence records are removed; tests are kept
fast by attention rather than by apparatus. Strict mypy and Ruff are retained.
