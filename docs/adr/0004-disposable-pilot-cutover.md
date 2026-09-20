---
status: superseded by ADR-0010
---

# Cut over through a disposable pilot and retire shell promptly

The single pilot Device will be treated as disposable acceptance infrastructure rather than requiring a complex shell/Python coexistence layer. Every currently managed State Address will be classified as migrated, retired, or a Guided Action, and migrated state must pass fresh convergence, representative drift repair, and second-Run no-op through Python. After the complete inventory passes, active shell provisioning commands, tests, and documentation will be removed promptly; git history, not a fallback engine, preserves the old implementation.
