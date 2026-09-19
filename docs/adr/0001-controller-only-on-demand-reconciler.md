---
status: accepted
---

# Use a controller-only, on-demand Reconciler

The Reconciler will be a Python 3.14 CLI over a reusable application library, invoked on demand from the administrator machine. CoreELEC remains a constrained managed Device reached through SSH/SFTP and Kodi JSON-RPC; temporary audited helpers are allowed, but no persistent agent or continuous reconciliation service will be installed. This keeps runtime and dependency complexity off the Device while preserving a future seam for external scheduling.
