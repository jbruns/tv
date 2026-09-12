# Reusable code

Executable Ugoos automation entry points live at the repository root, and
reusable shell libraries live under [`../lib/`](../lib/).

## Entry points

- [`../provision-coreelec.sh`](../provision-coreelec.sh) — transactional
  shared CoreELEC baseline deployment. See
  [docs/operations/provision-ugoos.md](../docs/operations/provision-ugoos.md)
  and [config/README.md](../config/README.md).
- [`../configure-coreelec-addons.sh`](../configure-coreelec-addons.sh) —
  post-deployment add-on validation plus guarded interactive workflows. See
  [docs/operations/provision-ugoos.md](../docs/operations/provision-ugoos.md)
  and [config/README.md](../config/README.md).
- [`../configure-kodi-lifecycle.sh`](../configure-kodi-lifecycle.sh) —
  restricted Kodi lifecycle SSH gateway deployment. See
  [docs/home-assistant/ugoos-kodi-lifecycle.md](../docs/home-assistant/ugoos-kodi-lifecycle.md).

## Libraries

The `lib/` directory contains the reusable shell modules sourced by those
entry points for configuration parsing, environment loading, SSH transport,
artifact verification, add-on workflows, and lifecycle deployment.
