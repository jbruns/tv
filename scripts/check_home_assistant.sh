#!/bin/bash
# Runs Home Assistant's check_config against the repository's blueprints and
# packages, laid out as they are deployed under /config. Needs uv.
#
# check_config only logs an automation it cannot build from its blueprint, and
# still exits 0, so any logged error fails the check too.

set -euo pipefail

HOMEASSISTANT_VERSION="2026.9.3"

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config="$(mktemp -d)"
trap 'rm -rf "${config}"' EXIT

cp -R "${repo}/home-assistant/blueprints" "${config}/blueprints"
cp -R "${repo}/home-assistant/packages" "${config}/packages"
cat > "${config}/configuration.yaml" <<'YAML'
homeassistant:
  packages: !include_dir_named packages
YAML

uvx --python 3.14 --from "homeassistant==${HOMEASSISTANT_VERSION}" \
  hass --script check_config --config "${config}" --fail-on-warnings \
  2>&1 | tee "${config}/check.log"

if grep -Eq '^(ERROR|CRITICAL)' "${config}/check.log"; then
  printf 'check_config logged errors\n' >&2
  exit 1
fi
