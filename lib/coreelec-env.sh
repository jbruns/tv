#!/bin/bash

coreelec_env_secret_names() {
  cat <<'SECRETS'
KODI_WEB_PASSWORD
OMDB_API_KEY
MDBLIST_API_KEY
YOUTUBE_API_KEY
YOUTUBE_CLIENT_ID
YOUTUBE_CLIENT_SECRET
HOME_ASSISTANT_TOKEN
NEXTPVR_PIN
PLEX_TOKEN
EMBY_PASSWORD
SECRETS
}

# Sources the shared operator environment in isolation, then imports only the
# documented secrets so shell code cannot replace parsed CLI/config state.
coreelec_env_load() {
  local env_file="$1" assignments marker name
  if [[ ! -r "${env_file}" ]]; then
    printf 'ERROR: Shared environment file is not readable: %s\n' "${env_file}" >&2
    printf 'Copy .env.example to .env and configure the required values.\n' >&2
    return 1
  fi

  assignments="$(
    while IFS= read -r name; do
      unset "${name}"
    done <<EOF
$(coreelec_env_secret_names)
EOF
    # shellcheck disable=SC1090
    source "${env_file}" >/dev/null || exit $?
    printf '__COREELEC_ENV_READY__\n'
    while IFS= read -r name; do
      printf 'export %s=%q\n' "${name}" "${!name:-}"
    done <<EOF
$(coreelec_env_secret_names)
EOF
  )" || return $?

  marker="${assignments%%$'\n'*}"
  if [[ "${marker}" != "__COREELEC_ENV_READY__" ]]; then
    printf 'ERROR: Shared environment file did not finish loading: %s\n' "${env_file}" >&2
    return 1
  fi
  assignments="${assignments#*$'\n'}"
  eval "${assignments}"
}
