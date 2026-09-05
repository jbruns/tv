# Reusable code

Reserved for deployment and maintenance code shared across rooms. No scripts are implemented yet.

Use device/platform directories as code is added, for example `code/ugoos-am6b-plus/` for tools used by multiple Ugoos units. Keep room names, network addresses, and other per-device values in [configuration](../config/README.md), supplied as inputs rather than hard-coded in scripts.

Future deployment tools should select targets explicitly, support reviewing intended changes, and document prerequisites, invocation, backup, and recovery behavior. Keep firmware flashing and eMMC migration separate from routine configuration deployment.

Manual setup remains documented in the [shared runbook](../docs/runbook.md).
