# Room-Specific Desired State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the reserved `room` provisioning component so theater display and audio desired state is declared in configuration, applied transactionally, and verified.

**Architecture:** A new per-room configuration file (`config/rooms/<room>/room.conf`) is parsed by a second strict allowlist in `lib/coreelec-config.sh` and selected with `--room NAME`. A pre-transaction probe asks the running Kodi to resolve a resolution label into its index and to confirm the display still reports every pinned whitelist mode, aborting before the device is touched if either fails. The existing settings transformer gains an `apply_room` branch writing nine `guisettings.xml` settings, and the existing verify probe and report gain a `room.*` block.

**Tech Stack:** Bash 3.2, POSIX `sh` for remote programs, Python 3 (device stdlib only) for XML transformation and JSON-RPC parsing, Kodi JSON-RPC over localhost HTTP.

**Spec:** `docs/superpowers/specs/2026-09-17-room-desired-state-design.md`

## Global Constraints

- **Bash 3.2 target.** No associative arrays (`declare -A`), no `local -n`, no `${var,,}`, no `mapfile`, no `declare -g`.
- **Remote programs are POSIX `sh`**, not bash. The device is BusyBox: no `grep --include`, no `base64` binary, no `sqlite3` CLI. Python 3 with the standard library is present.
- **No `eval`, `source`, or indirect expansion** in any configuration parsing path. Every key goes through an explicit `case` allowlist.
- **Remote script emitters never interpolate caller data** other than the storage root. Non-secret parameters travel on stdin; secrets travel on stdin only, never in argv.
- **Tests must be appended to the trailing backslash-continued `run_all_tests` list** at the end of each test file, or they silently never run.
- **Test files set `IFS=$'\n\t'` globally.** A bare `read` will not split on spaces — use a command-prefix `IFS=' ' read -r a b`.
- **Never claim a suite passes without running it.** Single suite: `bash tests/<file>.sh`. All suites: `ls tests/*.sh | grep -v test-helper | while read f; do bash "$f"; done` (~7 minutes).
- The live device is `ugoos-theater.lan.wavebe.am` (the short name does not resolve). **No task in this plan contacts it.** All verification is against fixtures.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `lib/coreelec-config.sh` | Room config grammar, validators, room-name validation | 1 |
| `config/rooms/theater/room.conf` | Theater desired state (data) | 1 |
| `provision-coreelec.sh` | Component gating, `--room`, plan/payload plumbing, transformer, probe, report | 2-6 |
| `tests/test-coreelec-config.sh` | Room grammar and component-selection gating | 1, 2 |
| `tests/test-coreelec-artifacts.sh` | Deployment plan validation | 3 |
| `tests/test-coreelec-settings.sh` | Transformer behavior and byte isolation | 4 |
| `tests/test-coreelec-report.sh` | Pre-transaction probe and report verdicts | 5, 6 |
| `docs/devices/ugoos-am6b-plus/room-desired-state.md` | The room contract reference | 7 |
| `rooms/theater/devices/ugoos-am6b-plus.md` | Theater room guide, de-duplicated | 7 |
| `docs/operations/provision-ugoos.md` | Operator runbook | 7 |
| `config/README.md` | Configuration surface boundary | 7 |

---

### Task 1: Room configuration surface

**Files:**
- Modify: `lib/coreelec-config.sh` (append after `coreelec_config_validate_id_list`, and after `coreelec_config_validate`)
- Create: `config/rooms/theater/room.conf`
- Test: `tests/test-coreelec-config.sh`

**Interfaces:**
- Consumes: `die`, `coreelec_config_validate_bool`, `coreelec_config_validate_enum` (all already in `lib/coreelec-config.sh`)
- Produces:
  - `coreelec_validate_room_name NAME` — dies unless `NAME` is a safe single path segment
  - `coreelec_room_config_defaults` — clears every `ROOM_*` global
  - `coreelec_room_config_load FILE` — strict parser for `room.conf`
  - `coreelec_room_config_validate` — dies unless every room key is set
  - Globals: `ROOM_NAME`, `ROOM_CONFIG_FILE`, `ROOM_DISPLAY_RESOLUTION`, `ROOM_DISPLAY_WHITELIST`, `ROOM_DOLBY_VISION`, `ROOM_DOLBY_VISION_MODE`, `ROOM_AUDIO_PASSTHROUGH`, `ROOM_AUDIO_AC3`, `ROOM_AUDIO_EAC3`, `ROOM_AUDIO_DTS`, `ROOM_AUDIO_TRUEHD`, `ROOM_AUDIO_DTSHD`, `ROOM_DISPLAY_RESOLUTION_INDEX`

- [ ] **Step 1: Write the failing tests**

Append these functions to `tests/test-coreelec-config.sh`, before the `run_all_tests` call at the end of the file:

```bash
test_room_config_parses_every_key() {
  local dir file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/room.conf"
  cat > "${file}" <<'CONF'
# theater
ROOM_DISPLAY_RESOLUTION=3840x2160p
ROOM_DISPLAY_WHITELIST=0409602160024.00000pstd,0384002160060.00000pstd
ROOM_DOLBY_VISION=1
ROOM_DOLBY_VISION_MODE=tv-led
ROOM_AUDIO_PASSTHROUGH=1
ROOM_AUDIO_AC3=1
ROOM_AUDIO_EAC3=1
ROOM_AUDIO_DTS=1
ROOM_AUDIO_TRUEHD=1
ROOM_AUDIO_DTSHD=0
CONF
  coreelec_room_config_defaults
  coreelec_room_config_load "${file}"
  coreelec_room_config_validate
  assert_eq "3840x2160p" "${ROOM_DISPLAY_RESOLUTION}" "resolution label"
  assert_eq "0409602160024.00000pstd,0384002160060.00000pstd" \
    "${ROOM_DISPLAY_WHITELIST}" "whitelist"
  assert_eq "tv-led" "${ROOM_DOLBY_VISION_MODE}" "dolby vision mode"
  assert_eq "0" "${ROOM_AUDIO_DTSHD}" "dts-hd passthrough"
}

test_room_config_missing_key_is_rejected() {
  local dir file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/room.conf"
  cat > "${file}" <<'CONF'
ROOM_DISPLAY_RESOLUTION=3840x2160p
CONF
  coreelec_room_config_defaults
  coreelec_room_config_load "${file}"
  set +e
  output="$(coreelec_room_config_validate 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an incomplete room file must be rejected"
  assert_contains "${output}" "ROOM_DISPLAY_WHITELIST"
}

test_room_config_rejects_provision_keys_and_secrets() {
  local dir file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/room.conf"
  printf 'KODI_PORT=8181\n' > "${file}"
  coreelec_room_config_defaults
  set +e
  output="$(coreelec_room_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a provision.conf key must not be accepted in room.conf"
  assert_contains "${output}" "unknown room configuration key: KODI_PORT"

  printf 'KODI_WEB_PASSWORD=hunter2\n' > "${file}"
  coreelec_room_config_defaults
  set +e
  output="$(coreelec_room_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a secret must not be accepted in room.conf"
  assert_contains "${output}" "is a secret"
  assert_not_contains "${output}" "hunter2"
}

test_room_config_rejects_room_keys_in_provision_conf() {
  local dir file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"
  printf 'ROOM_DISPLAY_RESOLUTION=3840x2160p\n' > "${file}"
  coreelec_config_defaults
  set +e
  output="$(coreelec_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a room key must not be accepted in provision.conf"
  assert_contains "${output}" "unknown configuration key: ROOM_DISPLAY_RESOLUTION"
}

test_room_config_rejects_malformed_values() {
  local dir file rc output entry
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/room.conf"
  for entry in \
    'ROOM_DISPLAY_RESOLUTION=3840*2160p' \
    'ROOM_DISPLAY_WHITELIST=not-a-mode' \
    'ROOM_DISPLAY_WHITELIST=0384002160060.00000pstd,' \
    'ROOM_DOLBY_VISION_MODE=player' \
    'ROOM_AUDIO_DTS=yes'; do
    printf '%s\n' "${entry}" > "${file}"
    coreelec_room_config_defaults
    set +e
    output="$(coreelec_room_config_load "${file}" 2>&1)"
    rc=$?
    set -e
    assert_failure "${rc}" "malformed entry must be rejected: ${entry}"
    assert_contains "${output}" "${entry%%=*}"
  done
}

test_room_name_rejects_path_traversal() {
  local name rc output
  for name in '.' '..' 'a/b' '' '-theater'; do
    set +e
    output="$(coreelec_validate_room_name "${name}" 2>&1)"
    rc=$?
    set -e
    assert_failure "${rc}" "room name must be rejected: '${name}'"
  done
  set +e
  coreelec_validate_room_name theater >/dev/null 2>&1
  rc=$?
  set -e
  assert_success "${rc}" "a plain room name is accepted"
}

test_shipped_theater_room_config_is_complete() {
  coreelec_room_config_defaults
  coreelec_room_config_load "${SCRIPT_DIR}/../config/rooms/theater/room.conf"
  coreelec_room_config_validate
  assert_eq "3840x2160p" "${ROOM_DISPLAY_RESOLUTION}" "theater resolution"
  assert_eq "tv-led" "${ROOM_DOLBY_VISION_MODE}" "theater dolby vision mode"
  assert_eq "1" "${ROOM_AUDIO_TRUEHD}" "theater truehd passthrough"
  assert_contains "${ROOM_DISPLAY_WHITELIST}" "0384002160060.00000pstd"
}
```

Register them by appending to the trailing backslash-continued list at the end of the file, after `test_production_config_takes_binary_addons_from_the_installed_branch`. Add a backslash to that line first:

```bash
  test_production_config_takes_binary_addons_from_the_installed_branch \
  test_room_config_parses_every_key \
  test_room_config_missing_key_is_rejected \
  test_room_config_rejects_provision_keys_and_secrets \
  test_room_config_rejects_room_keys_in_provision_conf \
  test_room_config_rejects_malformed_values \
  test_room_name_rejects_path_traversal \
  test_shipped_theater_room_config_is_complete
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-config.sh`
Expected: FAIL with `coreelec_room_config_defaults: command not found`.

- [ ] **Step 3: Add the validators and room-name check**

In `lib/coreelec-config.sh`, immediately after `coreelec_config_validate_id_list`, add:

```bash
# A Kodi resolution label such as "3840x2160p". Kodi reports these with a
# trailing space; the configuration value never carries one.
coreelec_config_validate_resolution_label() {
  local label="$1" value="$2"
  case "${value}" in
    ""|*[!0-9xpi]*|*x*x*) die "${label} must be a resolution label such as 3840x2160p: ${value}" ;;
  esac
  case "${value}" in
    [0-9]*x[0-9]*[pi]) ;;
    *) die "${label} must be a resolution label such as 3840x2160p: ${value}" ;;
  esac
}

# A comma-separated list of Kodi display mode strings. Each is exactly five
# width digits, five height digits, three refresh digits, a dot, five decimal
# digits, a scan letter, and the stereo suffix: 0384002160060.00000pstd.
coreelec_config_validate_mode_list() {
  local label="$1" value="$2" token remainder="$2"
  [[ -n "${value}" ]] || die "${label} must not be empty"
  while [[ -n "${remainder}" ]]; do
    token="${remainder%%,*}"
    case "${token}" in
      [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].[0-9][0-9][0-9][0-9][0-9][pi]std) ;;
      *) die "${label} must be a comma-separated list of Kodi display modes; rejected: ${token}" ;;
    esac
    case "${remainder}" in
      *,*) remainder="${remainder#*,}" ;;
      *) remainder="" ;;
    esac
  done
  case "${value}" in
    *,,*|,*|*,) die "${label} must not contain an empty display mode: ${value}" ;;
  esac
}

# A room name is used as a single path segment under config/rooms, so it is
# validated more strictly than validate_identifier, which permits "." and
# would therefore accept "..".
coreelec_validate_room_name() {
  local value="$1"
  case "${value}" in
    ""|.|..) die "Room name must not be empty, '.', or '..'" ;;
    -*) die "Room name must not start with a hyphen: ${value}" ;;
    *[!A-Za-z0-9_-]*) die "Room name may contain only letters, digits, underscore, and hyphen: ${value}" ;;
  esac
}
```

- [ ] **Step 4: Add the room parser**

Append to `lib/coreelec-config.sh`, after `coreelec_config_validate`:

```bash
# --- Room configuration ----------------------------------------------------
#
# A second strict allowlist, deliberately separate from coreelec_config_assign
# so the two key sets cannot leak into each other: a provision.conf key in a
# room file, or a room key in provision.conf, is an unknown key to the other
# parser and is rejected naming the key.

coreelec_room_config_defaults() {
  ROOM_NAME=""
  ROOM_CONFIG_FILE=""
  ROOM_DISPLAY_RESOLUTION=""
  ROOM_DISPLAY_WHITELIST=""
  ROOM_DOLBY_VISION=""
  ROOM_DOLBY_VISION_MODE=""
  ROOM_AUDIO_PASSTHROUGH=""
  ROOM_AUDIO_AC3=""
  ROOM_AUDIO_EAC3=""
  ROOM_AUDIO_DTS=""
  ROOM_AUDIO_TRUEHD=""
  ROOM_AUDIO_DTSHD=""
  # Resolved by the pre-transaction display probe, never by configuration.
  ROOM_DISPLAY_RESOLUTION_INDEX=""
  COREELEC_ROOM_CONFIG_SEEN_KEYS=$'\n'
}

coreelec_room_config_assign() {
  local source="$1" line_number="$2" key="$3" value="$4"
  local location="${source}:${line_number}"

  case "${key}" in
    KODI_WEB_PASSWORD|OMDB_API_KEY|MDBLIST_API_KEY|HOME_ASSISTANT_URL|HOME_ASSISTANT_TOKEN|NEXTPVR_HOST|NEXTPVR_PIN|TMDB_API_KEY)
      die "${location}: ${key} is a secret and must be supplied only as an environment variable"
      ;;
  esac

  case "${COREELEC_ROOM_CONFIG_SEEN_KEYS}" in
    *$'\n'"${key}"$'\n'*) die "${location}: duplicate room configuration key: ${key}" ;;
  esac
  COREELEC_ROOM_CONFIG_SEEN_KEYS="${COREELEC_ROOM_CONFIG_SEEN_KEYS}${key}"$'\n'

  case "${key}" in
    ROOM_DISPLAY_RESOLUTION)
      coreelec_config_validate_resolution_label "ROOM_DISPLAY_RESOLUTION" "${value}"
      ROOM_DISPLAY_RESOLUTION="${value}"
      ;;
    ROOM_DISPLAY_WHITELIST)
      coreelec_config_validate_mode_list "ROOM_DISPLAY_WHITELIST" "${value}"
      ROOM_DISPLAY_WHITELIST="${value}"
      ;;
    ROOM_DOLBY_VISION)
      coreelec_config_validate_bool "ROOM_DOLBY_VISION" "${value}"
      ROOM_DOLBY_VISION="${value}"
      ;;
    ROOM_DOLBY_VISION_MODE)
      coreelec_config_validate_enum "ROOM_DOLBY_VISION_MODE" "${value}" "tv-led" "player-led"
      ROOM_DOLBY_VISION_MODE="${value}"
      ;;
    ROOM_AUDIO_PASSTHROUGH)
      coreelec_config_validate_bool "ROOM_AUDIO_PASSTHROUGH" "${value}"
      ROOM_AUDIO_PASSTHROUGH="${value}"
      ;;
    ROOM_AUDIO_AC3)
      coreelec_config_validate_bool "ROOM_AUDIO_AC3" "${value}"
      ROOM_AUDIO_AC3="${value}"
      ;;
    ROOM_AUDIO_EAC3)
      coreelec_config_validate_bool "ROOM_AUDIO_EAC3" "${value}"
      ROOM_AUDIO_EAC3="${value}"
      ;;
    ROOM_AUDIO_DTS)
      coreelec_config_validate_bool "ROOM_AUDIO_DTS" "${value}"
      ROOM_AUDIO_DTS="${value}"
      ;;
    ROOM_AUDIO_TRUEHD)
      coreelec_config_validate_bool "ROOM_AUDIO_TRUEHD" "${value}"
      ROOM_AUDIO_TRUEHD="${value}"
      ;;
    ROOM_AUDIO_DTSHD)
      coreelec_config_validate_bool "ROOM_AUDIO_DTSHD" "${value}"
      ROOM_AUDIO_DTSHD="${value}"
      ;;
    *)
      die "${location}: unknown room configuration key: ${key}"
      ;;
  esac
}

coreelec_room_config_load() {
  local file="$1" line line_number=0 key value trimmed
  [[ -r "${file}" ]] || die "Room configuration file is not readable: ${file}"
  ROOM_CONFIG_FILE="${file}"
  COREELEC_ROOM_CONFIG_SEEN_KEYS=$'\n'
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line_number=$((line_number + 1))
    trimmed="${line#"${line%%[![:space:]]*}"}"
    case "${trimmed}" in
      ''|'#'*) continue ;;
      *=*) key="${line%%=*}"; value="${line#*=}" ;;
      *) die "${file}:${line_number}: expected KEY=value" ;;
    esac
    coreelec_room_config_assign "${file}" "${line_number}" "${key}" "${value}"
  done < "${file}"
}

# Every room key is required. A silent default for a display or audio setting
# is exactly the unverifiable state this component exists to eliminate.
coreelec_room_config_validate() {
  local key
  for key in ROOM_DISPLAY_RESOLUTION ROOM_DISPLAY_WHITELIST ROOM_DOLBY_VISION \
    ROOM_DOLBY_VISION_MODE ROOM_AUDIO_PASSTHROUGH ROOM_AUDIO_AC3 \
    ROOM_AUDIO_EAC3 ROOM_AUDIO_DTS ROOM_AUDIO_TRUEHD ROOM_AUDIO_DTSHD; do
    case "${COREELEC_ROOM_CONFIG_SEEN_KEYS}" in
      *$'\n'"${key}"$'\n'*) ;;
      *) die "${ROOM_CONFIG_FILE:-room configuration}: missing required room configuration key: ${key}" ;;
    esac
  done
  return 0
}
```

- [ ] **Step 5: Ship the theater room configuration**

Create `config/rooms/theater/room.conf`:

```text
# Theater room desired state for the CoreELEC playback host.
#
# Applied by: ./provision-coreelec.sh --target ugoos-theater --component room --room theater
#
# Every key is required. See
# docs/devices/ugoos-am6b-plus/room-desired-state.md for the meaning of each
# value and for why the resolution is a label rather than Kodi's index.
#
# These values were captured from the live device on 2026-09-16 with the Sony
# XR-65A90J powered on and selected to HDMI IN 4.

# GUI desktop resolution, as a label. The device resolves it to Kodi's
# internal index during the pre-transaction display probe.
ROOM_DISPLAY_RESOLUTION=3840x2160p

# Every 2160p mode the Sony reports over EDID.
ROOM_DISPLAY_WHITELIST=0409602160024.00000pstd,0409602160023.97602pstd,0384002160060.00000pstd,0384002160059.94006pstd,0384002160050.00000pstd,0384002160030.00000pstd,0384002160029.97003pstd,0384002160025.00000pstd,0384002160024.00000pstd,0384002160023.97602pstd

# Dolby Vision, display-led. Both settings currently agree with CoreELEC's
# defaults; pinning them turns that coincidence into an assertion.
ROOM_DOLBY_VISION=1
ROOM_DOLBY_VISION_MODE=tv-led

# Audio passes through the Sony eARC and the OREI link to the Denon.
# There is no Atmos key: Atmos rides on TrueHD and E-AC-3.
ROOM_AUDIO_PASSTHROUGH=1
ROOM_AUDIO_AC3=1
ROOM_AUDIO_EAC3=1
ROOM_AUDIO_DTS=1
ROOM_AUDIO_TRUEHD=1
ROOM_AUDIO_DTSHD=1
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-config.sh`
Expected: PASS, with the seven new tests reported.

- [ ] **Step 7: Commit**

```bash
git add lib/coreelec-config.sh config/rooms/theater/room.conf tests/test-coreelec-config.sh
git commit -m "feat: add the room configuration surface

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Component gating and the `--room` flag

**Files:**
- Modify: `provision-coreelec.sh` (usage text, `coreelec_component_implemented`, CLI parser, post-parse selection)
- Test: `tests/test-coreelec-config.sh`

**Interfaces:**
- Consumes: `coreelec_validate_room_name`, `coreelec_room_config_load`, `coreelec_room_config_validate` (Task 1)
- Produces: `--room NAME` accepted; `room` accepted by `--component`; `coreelec_select_room` resolving and loading the room file; globals `ROOM_NAME`, `ROOM_CONFIG_FILE` populated for later tasks

**Gating rules (fail closed in both directions):**
1. `--component room` without `--room NAME` is an error.
2. `--room NAME` when `room` is not in the effective component plan is an error.
3. `room` is never pulled in by `baseline`; it is opt-in only. `coreelec_expand_component`'s baseline list stays `core cec addons services skin`.

- [ ] **Step 1: Write the failing tests**

In `tests/test-coreelec-config.sh`, **replace** `test_unimplemented_room_component_is_rejected` (currently at line 314) with:

```bash
test_room_component_requires_a_room_name() {
  local output rc
  set +e
  output="$(bash "${PROVISIONER}" --component room --print-component-plan 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "--component room must require --room"
  assert_contains "${output}" "--component room requires --room NAME"
}

test_room_name_without_the_room_component_is_rejected() {
  local output rc
  set +e
  output="$(bash "${PROVISIONER}" --room theater --component cec \
    --print-component-plan 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "--room must require the room component"
  assert_contains "${output}" "--room requires the room component"
}

test_room_component_plan_includes_its_dependency() {
  local output
  output="$(bash "${PROVISIONER}" --component room --room theater \
    --print-component-plan 2>&1)"
  assert_contains "${output}" "room"
  assert_contains "${output}" "core"
  assert_not_contains "${output}" "Component is not implemented"
}

test_baseline_plan_excludes_the_room_component() {
  local output
  output="$(bash "${PROVISIONER}" --print-component-plan 2>&1)"
  assert_contains "${output}" "skin"
  assert_not_contains "${output}" "room"
}

test_unknown_room_is_rejected_by_name() {
  local output rc
  set +e
  output="$(bash "${PROVISIONER}" --component room --room kitchen \
    --print-component-plan 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an unknown room must be rejected"
  assert_contains "${output}" "kitchen"
}

test_room_flag_rejects_path_traversal() {
  local output rc name
  for name in '..' '../../etc' 'theater/../..'; do
    set +e
    output="$(bash "${PROVISIONER}" --component room --room "${name}" \
      --print-component-plan 2>&1)"
    rc=$?
    set -e
    assert_failure "${rc}" "--room must reject: ${name}"
    assert_contains "${output}" "Room name"
  done
}
```

Update the registration list: replace `test_unimplemented_room_component_is_rejected \` (line 811) with the six new names, each backslash-continued.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-config.sh`
Expected: FAIL — `--component room` still dies with `Component is not implemented: room`, and `--room` is an unknown option.

- [ ] **Step 3: Accept the component**

In `provision-coreelec.sh`, change `coreelec_component_implemented`:

```bash
coreelec_component_implemented() {
  case "$1" in
    baseline|core|cec|addons|services|skin|room) return 0 ;;
    *) return 1 ;;
  esac
}
```

Leave `coreelec_component_known` and `coreelec_component_dependencies` unchanged — `room` is already listed in both, and `room` already declares `core`.

- [ ] **Step 4: Add the CLI flag**

Declare the globals next to the other CLI state (near `CLI_COMPONENTS`):

```bash
ROOM_NAME=""
ROOM_CONFIG_FILE=""
```

Add the parser case immediately after the `--component` case:

```bash
    --room)
      (( $# >= 2 )) || die "--room requires a value"
      coreelec_validate_room_name "$2"
      ROOM_NAME="$2"
      shift 2
      ;;
```

- [ ] **Step 5: Gate and load after the plan is prepared**

Add the loader beside the other component helpers:

```bash
# Resolves --room against config/rooms and loads it. Called after the
# component plan is prepared so both failure directions can be checked, and
# before --print-component-plan exits so a plan printed for the room component
# has already proven its configuration parses.
coreelec_select_room() {
  local file

  if coreelec_component_effective room; then
    [[ -n "${ROOM_NAME}" ]] \
      || die "--component room requires --room NAME"
  elif [[ -n "${ROOM_NAME}" ]]; then
    die "--room requires the room component; add --component room"
  else
    return 0
  fi

  file="${SCRIPT_DIR}/config/rooms/${ROOM_NAME}/room.conf"
  [[ -r "${file}" ]] \
    || die "No room configuration for ${ROOM_NAME}: ${file} is not readable"
  coreelec_room_config_defaults
  coreelec_room_config_load "${file}"
  coreelec_room_config_validate
}
```

Call it in the main flow immediately after `coreelec_prepare_component_plan` and **before** the `--print-component-plan` early exit:

```bash
coreelec_prepare_component_plan
coreelec_select_room
if [[ "${PRINT_COMPONENT_PLAN}" == "1" ]]; then
```

`coreelec_room_config_defaults` is called inside `coreelec_select_room` rather than at startup so that `ROOM_*` is empty on every non-room run — later tasks test emptiness to mean "room is not in scope".

- [ ] **Step 6: Update the usage text**

Replace the `--component` description and add `--room` after it:

```text
  --component NAME          Apply only this component and its dependencies;
                             repeatable. Implemented components are baseline,
                             core, cec, addons, services, skin, and room.
                             baseline does not include room: room is opt-in
                             and requires --room. Dependencies are expanded
                             and reported.
  --room NAME               Room whose desired display and audio state applies,
                             read from config/rooms/NAME/room.conf. Required
                             with --component room and rejected without it.
                             The display must be powered on and selected to
                             this device for the run to proceed.
```

Delete the trailing disclaimer paragraph's first sentence and keep the Emby one:

```text
This script cannot perform Emby server sign-in -- that add-on is always left
for the operator to finish by hand.
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-config.sh`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-config.sh
git commit -m "feat: accept the room component and --room

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Deployment plan and payload plumbing

**Files:**
- Modify: `provision-coreelec.sh` (`valid_component_name`, the remote deployment plan validator, `COMPONENT_PAYLOAD_KEYS`, the `COMPONENTS` tuple, `coreelec_settings_payload`, `coreelec_remote_backup_script`, `scoped_settings_paths`)
- Test: `tests/test-coreelec-artifacts.sh`

**Interfaces:**
- Consumes: `ROOM_*` globals (Tasks 1-2), `coreelec_component_effective`
- Produces: `room` accepted end to end by the remote deployment-plan validator and the payload parser; `guisettings.xml` backed up when room is in scope

This task carries `room` through the untrusted-input boundary. The device revalidates everything it is sent, so `room` must be added to **both** sides: the local emitters and the remote validators.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test-coreelec-artifacts.sh`:

```bash
test_deployment_plan_accepts_the_room_component() {
  local dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_component_plan "${dir}/plan.tsv" core=1 cec=0 addons=0 services=0 \
    skin=0 room=1
  output="$(run_deploy_plan_validator "${dir}/plan.tsv" partial 2>&1)"
  assert_success "$?" "a plan selecting room must validate"
}

test_deployment_plan_rejects_a_repeated_room_component() {
  local dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_component_plan "${dir}/plan.tsv" core=1 cec=0 addons=0 services=0 \
    skin=0 room=1
  printf 'component\troom\t1\n' >> "${dir}/plan.tsv"
  set +e
  output="$(run_deploy_plan_validator "${dir}/plan.tsv" partial 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a repeated room component must be rejected"
  assert_contains "${output}" "deployment plan repeats component room"
}

test_deployment_plan_rejects_a_missing_room_component() {
  local dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_component_plan "${dir}/plan.tsv" core=1 cec=0 addons=0 services=0 skin=0
  set +e
  output="$(run_deploy_plan_validator "${dir}/plan.tsv" partial 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a plan omitting room must be rejected"
  assert_contains "${output}" "deployment plan is missing component room"
}

test_deployment_plan_rejects_room_without_core() {
  local dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_component_plan "${dir}/plan.tsv" core=0 cec=0 addons=0 services=0 \
    skin=0 room=1
  set +e
  output="$(run_deploy_plan_validator "${dir}/plan.tsv" partial 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "room without core must be rejected"
  assert_contains "${output}" "selects room without required component core"
}

test_room_scope_backs_up_guisettings() {
  local output
  output="$(bash "${PROVISIONER}" --emit-remote-script backup core,room 2>&1)"
  assert_contains "${output}" 'apply_room="1"'
  assert_contains "${output}" '.kodi/userdata/guisettings.xml'
}

test_backup_scope_rejects_an_unknown_component() {
  local output rc
  set +e
  output="$(bash "${PROVISIONER}" --emit-remote-script backup core,kitchen 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an unknown backup scope component must be rejected"
  assert_contains "${output}" "Unsupported component in remote backup scope: kitchen"
}
```

`write_component_plan` and `run_deploy_plan_validator` are the existing helpers in this file; if the existing helper takes a fixed component list, extend it to accept `room=N` in the same `name=value` form rather than adding a parallel helper. Register all six tests in the trailing `run_all_tests` list.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-artifacts.sh`
Expected: FAIL with `unsupported component in deployment plan: room`.

- [ ] **Step 3: Accept `room` in the remote validator**

```bash
valid_component_name() {
  case "$1" in
    core|cec|addons|services|skin|room) return 0 ;;
    *) return 1 ;;
  esac
}
```

In the deployment plan validator, add the initializers beside the others:

```bash
  apply_room=""
  seen_room=0
```

Add the `case` arm after `skin)`:

```bash
          room)
            [ "${seen_room}" -eq 0 ] || fail "deployment plan repeats component room"
            seen_room=1
            apply_room="${plan_field2}"
            ;;
```

Add the completeness check and the dependency check after the `skin` ones:

```bash
  [ "${seen_room}" -eq 1 ] || fail "deployment plan is missing component room"
```

Extend the "selects no component" arithmetic to include `apply_room`:

```bash
  [ "$((apply_core + apply_cec + apply_addons + apply_services + apply_skin + apply_room))" -gt 0 ] \
    || fail "deployment plan selects no component"
```

And after the skin dependency check:

```bash
  if [ "${apply_room}" = "1" ] && [ "${apply_core}" != "1" ]; then
    fail "deployment plan selects room without required component core"
  fi
```

- [ ] **Step 4: Carry `room` through the payload**

In the transformer's preamble:

```python
COMPONENT_PAYLOAD_KEYS = (
    "APPLY_COMPONENT_CORE",
    "APPLY_COMPONENT_CEC",
    "APPLY_COMPONENT_ADDONS",
    "APPLY_COMPONENT_SERVICES",
    "APPLY_COMPONENT_SKIN",
    "APPLY_COMPONENT_ROOM",
)
```

In the remote component-plan program:

```python
COMPONENTS = (
    ("APPLY_COMPONENT_CORE", "core"),
    ("APPLY_COMPONENT_CEC", "cec"),
    ("APPLY_COMPONENT_ADDONS", "addons"),
    ("APPLY_COMPONENT_SERVICES", "services"),
    ("APPLY_COMPONENT_SKIN", "skin"),
    ("APPLY_COMPONENT_ROOM", "room"),
)
```

In `coreelec_settings_payload`, after the `APPLY_COMPONENT_SKIN` entry:

```bash
  coreelec_settings_payload_entry APPLY_COMPONENT_ROOM \
    "$(coreelec_component_effective room && printf 1 || printf 0)"
```

And, still in `coreelec_settings_payload`, emit the room values only when room is in scope — an out-of-scope run must not carry room data at all:

```bash
  if coreelec_component_effective room; then
    coreelec_settings_payload_entry ROOM_NAME "${ROOM_NAME}"
    coreelec_settings_payload_entry ROOM_DISPLAY_RESOLUTION_INDEX \
      "${ROOM_DISPLAY_RESOLUTION_INDEX}"
    coreelec_settings_payload_entry ROOM_DISPLAY_WHITELIST "${ROOM_DISPLAY_WHITELIST}"
    coreelec_settings_payload_entry ROOM_DOLBY_VISION "${ROOM_DOLBY_VISION}"
    coreelec_settings_payload_entry ROOM_DOLBY_VISION_MODE "${ROOM_DOLBY_VISION_MODE}"
    coreelec_settings_payload_entry ROOM_AUDIO_PASSTHROUGH "${ROOM_AUDIO_PASSTHROUGH}"
    coreelec_settings_payload_entry ROOM_AUDIO_AC3 "${ROOM_AUDIO_AC3}"
    coreelec_settings_payload_entry ROOM_AUDIO_EAC3 "${ROOM_AUDIO_EAC3}"
    coreelec_settings_payload_entry ROOM_AUDIO_DTS "${ROOM_AUDIO_DTS}"
    coreelec_settings_payload_entry ROOM_AUDIO_TRUEHD "${ROOM_AUDIO_TRUEHD}"
    coreelec_settings_payload_entry ROOM_AUDIO_DTSHD "${ROOM_AUDIO_DTSHD}"
  fi
```

`ROOM_DISPLAY_RESOLUTION_INDEX` is populated by Task 5's probe. Until Task 5 lands it is empty, and Task 4's transformer treats an empty index as "leave `videoscreen.resolution` alone" — so the intermediate state after this task is safe rather than half-configured.

- [ ] **Step 5: Extend the backup scope**

In `coreelec_remote_backup_script`, add `apply_room=0` to the local declaration, add `room) apply_room=1 ;;` to the scope `case`, and add `apply_room="${apply_room}"` to the emitted `REMOTE_BACKUP_HEADER`. Leave the `baseline` expansion as `core,cec,addons,services,skin` — baseline does not include room.

In `scoped_settings_paths`, add `apply_room` to the guisettings condition:

```sh
scoped_settings_paths() {
  if [ "${apply_core}" = "1" ] || [ "${apply_services}" = "1" ] \
      || [ "${apply_skin}" = "1" ] || [ "${apply_room}" = "1" ]; then
    printf '%s\n' '.kodi/userdata/guisettings.xml'
  fi
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-artifacts.sh`
Expected: PASS.

Then run the settings suite, which will now fail on the newly required payload key:

Run: `bash tests/test-coreelec-settings.sh`
Expected: FAIL with `deployment scope rejected` / a missing `APPLY_COMPONENT_ROOM`.

- [ ] **Step 7: Fix the settings test helper**

In `tests/test-coreelec-settings.sh`, `write_scoped_base_payload` takes a file path followed by one flag per component, and every existing caller passes the five current components. Add `room` as the **last** parameter with a default so no existing caller changes:

```bash
write_scoped_base_payload() {
  local file="$1" core="$2" cec="$3" addons="$4" services="$5" skin="$6"
  local room="${7:-0}"
  ...
  APPLY_COMPONENT_ROOM=${room}
```

Read the helper before editing to confirm the current parameter order and positional numbering, and keep it; `room` goes last so `${N:-0}` defaults it for every existing call site at once.

Run: `bash tests/test-coreelec-settings.sh`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-artifacts.sh tests/test-coreelec-settings.sh
git commit -m "feat: carry the room component through the deployment plan and payload

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: The transformer

**Files:**
- Modify: `provision-coreelec.sh` (the embedded settings transformer's `main()`)
- Test: `tests/test-coreelec-settings.sh`

**Interfaces:**
- Consumes: payload keys from Task 3, `set_kodi_setting`, `load_kodi_settings`, `write_xml_atomic` (all existing)
- Produces: nine or ten `guisettings.xml` settings written when `apply_room` is set

**The settings written:**

| Kodi setting | Source | Transform |
|---|---|---|
| `videoscreen.resolution` | `ROOM_DISPLAY_RESOLUTION_INDEX` | written verbatim; **skipped when empty** |
| `videoscreen.whitelist` | `ROOM_DISPLAY_WHITELIST` | verbatim (a comma-separated scalar on disk) |
| `coreelec.amlogic.disabledolbyvision` | `ROOM_DOLBY_VISION` | **inverted**: `1` → `false`, `0` → `true` |
| `coreelec.amlogic.dolbyvisionled` | `ROOM_DOLBY_VISION_MODE` | `tv-led` → `0`, `player-led` → `1` |
| `audiooutput.passthrough` | `ROOM_AUDIO_PASSTHROUGH` | `1` → `true`, `0` → `false` |
| `audiooutput.ac3passthrough` | `ROOM_AUDIO_AC3` | boolean |
| `audiooutput.eac3passthrough` | `ROOM_AUDIO_EAC3` | boolean |
| `audiooutput.dtspassthrough` | `ROOM_AUDIO_DTS` | boolean |
| `audiooutput.truehdpassthrough` | `ROOM_AUDIO_TRUEHD` | boolean |
| `audiooutput.dtshdpassthrough` | `ROOM_AUDIO_DTSHD` | boolean |

The inversion on `disabledolbyvision` is the single most error-prone line in this component: the configuration key is stated positively and Kodi's setting is stated negatively. It gets its own test.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test-coreelec-settings.sh`:

```bash
test_room_transform_writes_display_and_audio_settings() {
  local dir payload
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  payload="${dir}/payload.env"
  write_scoped_base_payload "${payload}" 0 0 0 0 0 1
  cat >> "${payload}" <<'EOF'
ROOM_NAME=theater
ROOM_DISPLAY_RESOLUTION_INDEX=41
ROOM_DISPLAY_WHITELIST=0409602160024.00000pstd,0384002160060.00000pstd
ROOM_DOLBY_VISION=1
ROOM_DOLBY_VISION_MODE=tv-led
ROOM_AUDIO_PASSTHROUGH=1
ROOM_AUDIO_AC3=1
ROOM_AUDIO_EAC3=1
ROOM_AUDIO_DTS=1
ROOM_AUDIO_TRUEHD=1
ROOM_AUDIO_DTSHD=0
EOF
  run_transform "${dir}" "${payload}"
  local gui="${dir}/root/.kodi/userdata/guisettings.xml"
  assert_setting_equals "${gui}" "videoscreen.resolution" "41"
  assert_setting_equals "${gui}" "videoscreen.whitelist" \
    "0409602160024.00000pstd,0384002160060.00000pstd"
  assert_setting_equals "${gui}" "audiooutput.passthrough" "true"
  assert_setting_equals "${gui}" "audiooutput.truehdpassthrough" "true"
  assert_setting_equals "${gui}" "audiooutput.dtshdpassthrough" "false"
  assert_setting_equals "${gui}" "coreelec.amlogic.dolbyvisionled" "0"
}

test_room_transform_inverts_dolby_vision() {
  local dir payload gui
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  payload="${dir}/payload.env"
  write_scoped_base_payload "${payload}" 0 0 0 0 0 1
  write_room_payload_values "${payload}" DV=1 MODE=player-led
  run_transform "${dir}" "${payload}"
  gui="${dir}/root/.kodi/userdata/guisettings.xml"
  assert_setting_equals "${gui}" "coreelec.amlogic.disabledolbyvision" "false"
  assert_setting_equals "${gui}" "coreelec.amlogic.dolbyvisionled" "1"

  rm -rf -- "${dir}/root"
  write_scoped_base_payload "${payload}" 0 0 0 0 0 1
  write_room_payload_values "${payload}" DV=0 MODE=tv-led
  run_transform "${dir}" "${payload}"
  assert_setting_equals "${gui}" "coreelec.amlogic.disabledolbyvision" "true"
}

test_room_transform_skips_resolution_without_a_resolved_index() {
  local dir payload gui
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  payload="${dir}/payload.env"
  write_scoped_base_payload "${payload}" 0 0 0 0 0 1
  write_room_payload_values "${payload}" INDEX=
  run_transform "${dir}" "${payload}"
  gui="${dir}/root/.kodi/userdata/guisettings.xml"
  assert_setting_absent "${gui}" "videoscreen.resolution"
  assert_setting_equals "${gui}" "audiooutput.passthrough" "true"
}

test_room_transform_touches_no_other_component_setting() {
  local dir payload gui setting
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  payload="${dir}/payload.env"
  write_scoped_base_payload "${payload}" 0 0 0 0 0 1
  write_room_payload_values "${payload}"
  run_transform "${dir}" "${payload}"
  gui="${dir}/root/.kodi/userdata/guisettings.xml"
  for setting in locale.language locale.country locale.timezone \
    videoplayer.adjustrefreshrate videoplayer.usedisplayasclock \
    lookandfeel.skin weather.addon services.webserver; do
    assert_setting_absent "${gui}" "${setting}"
  done
}

test_core_and_skin_transform_touch_no_room_setting() {
  local dir payload gui setting
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  payload="${dir}/payload.env"
  write_scoped_base_payload "${payload}" 1 0 1 1 1 0
  run_transform "${dir}" "${payload}"
  gui="${dir}/root/.kodi/userdata/guisettings.xml"
  for setting in videoscreen.resolution videoscreen.whitelist \
    audiooutput.passthrough audiooutput.ac3passthrough \
    audiooutput.eac3passthrough audiooutput.dtspassthrough \
    audiooutput.truehdpassthrough audiooutput.dtshdpassthrough \
    coreelec.amlogic.disabledolbyvision coreelec.amlogic.dolbyvisionled; do
    assert_setting_absent "${gui}" "${setting}"
  done
}

test_room_transform_preserves_unmanaged_settings() {
  local dir payload gui
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  payload="${dir}/payload.env"
  mkdir -p "${dir}/root/.kodi/userdata"
  gui="${dir}/root/.kodi/userdata/guisettings.xml"
  cat > "${gui}" <<'XML'
<settings version="2">
    <setting id="audiooutput.audiodevice">ALSA:@</setting>
    <setting id="audiooutput.passthrough" default="true">false</setting>
</settings>
XML
  write_scoped_base_payload "${payload}" 0 0 0 0 0 1
  write_room_payload_values "${payload}"
  run_transform "${dir}" "${payload}"
  assert_setting_equals "${gui}" "audiooutput.audiodevice" "ALSA:@"
  assert_setting_equals "${gui}" "audiooutput.passthrough" "true"
}
```

Add the helper alongside the other payload helpers in this file. It writes the ten room keys, letting named overrides replace individual values, so each test states only what it is testing:

```bash
write_room_payload_values() {
  local file="$1"; shift
  local index=41 dv=1 mode=tv-led pass=1 ac3=1 eac3=1 dts=1 truehd=1 dtshd=1
  local entry
  for entry in "$@"; do
    case "${entry}" in
      INDEX=*) index="${entry#INDEX=}" ;;
      DV=*) dv="${entry#DV=}" ;;
      MODE=*) mode="${entry#MODE=}" ;;
      *) printf 'unknown room payload override: %s\n' "${entry}" >&2; return 1 ;;
    esac
  done
  cat >> "${file}" <<EOF
ROOM_NAME=theater
ROOM_DISPLAY_RESOLUTION_INDEX=${index}
ROOM_DISPLAY_WHITELIST=0409602160024.00000pstd,0384002160060.00000pstd
ROOM_DOLBY_VISION=${dv}
ROOM_DOLBY_VISION_MODE=${mode}
ROOM_AUDIO_PASSTHROUGH=${pass}
ROOM_AUDIO_AC3=${ac3}
ROOM_AUDIO_EAC3=${eac3}
ROOM_AUDIO_DTS=${dts}
ROOM_AUDIO_TRUEHD=${truehd}
ROOM_AUDIO_DTSHD=${dtshd}
EOF
}
```

If `assert_setting_absent` does not already exist in this file, add it next to `assert_setting_equals`, asserting that no `<setting id="...">` element with that ID is present.

Register all six tests in the trailing `run_all_tests` list.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-settings.sh`
Expected: FAIL — `guisettings.xml` is not written at all for a room-only payload.

- [ ] **Step 3: Implement the transformer branch**

In the transformer's `main()`, after `apply_skin`:

```python
    apply_room = config("APPLY_COMPONENT_ROOM") == "1"
```

Add `apply_room` to the `userdata` managed-directory condition:

```python
    if apply_core or apply_skin or apply_room:
        register_managed_directory(userdata)
```

After the `apply_skin` block that updates `kodi_values`:

```python
    if apply_room:
        def room_bool(key):
            return "true" if config(key) == "1" else "false"

        kodi_values.update({
            "videoscreen.whitelist": config("ROOM_DISPLAY_WHITELIST"),
            # The configuration states Dolby Vision positively; Kodi's setting
            # states it negatively. This is the one inverted write in the
            # component.
            "coreelec.amlogic.disabledolbyvision":
                "false" if config("ROOM_DOLBY_VISION") == "1" else "true",
            "coreelec.amlogic.dolbyvisionled":
                "1" if config("ROOM_DOLBY_VISION_MODE") == "player-led" else "0",
            "audiooutput.passthrough": room_bool("ROOM_AUDIO_PASSTHROUGH"),
            "audiooutput.ac3passthrough": room_bool("ROOM_AUDIO_AC3"),
            "audiooutput.eac3passthrough": room_bool("ROOM_AUDIO_EAC3"),
            "audiooutput.dtspassthrough": room_bool("ROOM_AUDIO_DTS"),
            "audiooutput.truehdpassthrough": room_bool("ROOM_AUDIO_TRUEHD"),
            "audiooutput.dtshdpassthrough": room_bool("ROOM_AUDIO_DTSHD"),
        })
        # The index is resolved by the pre-transaction display probe against
        # the running Kodi, because Kodi's resolution enumeration is internal
        # and unstable across releases and displays. With no resolved index
        # the desktop resolution is left exactly as it was rather than pinned
        # to a number that may mean something else.
        resolution_index = config("ROOM_DISPLAY_RESOLUTION_INDEX")
        if resolution_index:
            kodi_values["videoscreen.resolution"] = resolution_index
```

Extend the guisettings write condition:

```python
    if apply_core or apply_skin or apply_room \
            or (apply_services and weather_configured):
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-settings.sh`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-settings.sh
git commit -m "feat: write room display and audio settings in the transformer

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: The pre-transaction display probe

**Files:**
- Modify: `provision-coreelec.sh` (new emitter, `coreelec_emit_remote_script`, usage text, main flow)
- Test: `tests/test-coreelec-report.sh`

**Interfaces:**
- Consumes: `ROOM_DISPLAY_RESOLUTION`, `ROOM_DISPLAY_WHITELIST`, `KODI_USER`, `KODI_WEB_PASSWORD`, `KODI_PORT`, `ssh_keyed`
- Produces:
  - `coreelec_remote_display_probe_script ROOT` — emits the POSIX `sh` probe
  - `--emit-remote-script display-probe` — test entry point
  - `coreelec_resolve_room_display` — runs the probe and sets `ROOM_DISPLAY_RESOLUTION_INDEX`

**Why this exists.** The transformer writes `guisettings.xml` with Kodi stopped, so there is no moment inside the transaction when the device can resolve a resolution *label* into Kodi's internal index. The probe runs while Kodi is still up and **before the transaction begins** — see the placement note below. A display that is off, on the wrong input, or no longer reporting a pinned mode aborts the run cleanly with nothing to roll back.

**Transport rules (non-negotiable):**
- The probe reads user, password, port, resolution label, and whitelist from **stdin**, one `KEY=value` per line. No value is interpolated into the emitted program.
- Because stdin carries the parameters, the program cannot also be piped to `sh -s`. It therefore travels the way the payload and stage programs already do: inside a single-quoted remote `sh -c '...'` argument, guarded by the same `[[ "${script}" != *"'"* ]]` assertion those call sites use. **The emitted program must contain no single quote anywhere** — use double-quoted `trap`, and unquoted here-document delimiters (the JSON and Python bodies contain no `$`, backtick, or backslash that would expand).
- The curl configuration file carrying the password is written into a `mktemp -d` guarded by a trap, so the probe leaves nothing behind even on failure.
- The RPC is one `Settings.GetSettings` filtered to `{"section": "system", "category": "display"}`, which Phase A proved contains both `videoscreen.resolution` and `videoscreen.whitelist` and is far smaller than the unfiltered call.
- Kodi reports resolution labels with a **trailing space** (`'3840x2160p '`). Both sides are compared with whitespace stripped.

**Placement — a deliberate, documented deviation from the spec.** The spec places the probe before `install_public_key_if_needed`. That cannot work as written: before the key is installed the only transport is `ssh_password`, which would prompt the operator for the root password a second time, and `remote_identity` may already have used the key. The probe is therefore placed **immediately after `install_public_key_if_needed` and immediately before `create_remote_backup`**. Installing the administrator public key is idempotent and independently reversible; `create_remote_backup` is the first real state change and the first thing a rollback would have to undo. The spec's actual guarantee — that a dark or wrongly-switched display aborts the run before the transaction begins — is preserved exactly. Record this in a comment at the call site.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test-coreelec-report.sh`:

```bash
test_display_probe_resolves_a_label_to_an_index() {
  local dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_display_probe_stub "${dir}" \
    '3840x2160p ' 41 \
    '0409602160024.00000pstd' '0384002160060.00000pstd'
  output="$(run_display_probe "${dir}" \
    '3840x2160p' \
    '0409602160024.00000pstd,0384002160060.00000pstd')"
  assert_contains "${output}" "resolution_index=41"
}

test_display_probe_rejects_an_unreported_resolution() {
  local dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_display_probe_stub "${dir}" '1920x1080p ' 16 '0192001080060.00000pstd'
  set +e
  output="$(run_display_probe "${dir}" '3840x2160p' '0192001080060.00000pstd' 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an unreported resolution must abort the probe"
  assert_contains "${output}" "3840x2160p"
}

test_display_probe_rejects_an_unreported_whitelist_mode() {
  local dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_display_probe_stub "${dir}" '3840x2160p ' 41 '0384002160060.00000pstd'
  set +e
  output="$(run_display_probe "${dir}" '3840x2160p' \
    '0384002160060.00000pstd,0409602160024.00000pstd' 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a mode the display no longer reports must abort"
  assert_contains "${output}" "0409602160024.00000pstd"
}

test_display_probe_reports_an_unreachable_kodi_clearly() {
  local dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_failing_curl_stub "${dir}"
  set +e
  output="$(run_display_probe "${dir}" '3840x2160p' '0384002160060.00000pstd' 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an unreachable Kodi must abort the probe"
  assert_contains "${output}" "display probe could not reach Kodi"
}

test_display_probe_program_contains_no_single_quote() {
  local output
  output="$(bash "${PROVISIONER}" --emit-remote-script display-probe 2>&1)"
  assert_not_contains "${output}" "'"
}

test_display_probe_program_carries_no_parameters() {
  local output
  output="$(bash "${PROVISIONER}" --emit-remote-script display-probe 2>&1)"
  assert_not_contains "${output}" "3840x2160p"
  assert_not_contains "${output}" "0384002160060.00000pstd"
  assert_contains "${output}" "mktemp -d"
  assert_contains "${output}" "trap"
}

test_display_probe_leaves_no_files_behind() {
  local dir before after
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_display_probe_stub "${dir}" '3840x2160p ' 41 '0384002160060.00000pstd'
  mkdir -p "${dir}/tmp"
  before="$(find "${dir}/tmp" -type f | wc -l | tr -d ' ')"
  run_display_probe "${dir}" '3840x2160p' '0384002160060.00000pstd' >/dev/null
  after="$(find "${dir}/tmp" -type f | wc -l | tr -d ' ')"
  assert_eq "${before}" "${after}" "the probe must remove its temporary files"
}
```

Add the helpers next to the existing stub helpers in this file, following their structure:

- `write_display_probe_stub DIR LABEL INDEX MODE...` — writes an executable `curl` onto a stub `PATH` that ignores its arguments and prints a `Settings.GetSettings` response whose `videoscreen.resolution` setting offers exactly one option with that label and value, and whose `videoscreen.whitelist` setting offers one option per given mode.
- `write_failing_curl_stub DIR` — writes a `curl` that exits non-zero.
- `run_display_probe DIR LABEL WHITELIST` — emits the probe with `--emit-remote-script display-probe`, then runs `PATH="${dir}/bin:${PATH}" TMPDIR="${dir}/tmp" sh -c "${script}"` with the five `KEY=value` parameter lines on stdin.

**Before writing the stub, read the captured Phase A fixture** at `~/.copilot/session-state/49eccbeb-6590-417e-a0a3-f1aed9db1212/files/ws7-evidence/settings-expert.json` and shape the stub's response after the real `videoscreen.resolution` and `videoscreen.whitelist` entries — in particular confirm which field carries the mode string. The stub and the parser must both agree with the real device, not merely with each other.

Register all seven tests in the trailing `run_all_tests` list.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-report.sh`
Expected: FAIL — `--emit-remote-script display-probe` is rejected.

- [ ] **Step 3: Implement the emitter**

Add beside the other remote-script emitters:

```bash
# Resolves a room's desired resolution label into Kodi's internal index and
# asserts the display still reports every pinned whitelist mode. Runs while
# Kodi is up and before the backup exists, because the transformer writes
# guisettings.xml with Kodi stopped and can no longer ask.
#
# stdin carries the parameters, so this program cannot be streamed to `sh -s`
# like most of the others; it travels inside a single-quoted remote `sh -c`
# argument and therefore must never contain a single quote of its own. That is
# why the trap is double-quoted and the here-document delimiters are unquoted:
# neither body contains a dollar sign, backtick, or backslash to expand.
coreelec_remote_display_probe_script() {
  local root="${1:-/storage}"
  cat <<REMOTE_DISPLAY_PROBE
set -eu
umask 077
storage_root="${root}"
REMOTE_DISPLAY_PROBE
  cat <<'REMOTE_DISPLAY_PROBE_BODY'
probe_user=""
probe_password=""
probe_port="8080"
probe_resolution=""
probe_whitelist=""
while IFS= read -r probe_line; do
  case "${probe_line}" in
    KODI_WEB_USER=*) probe_user="${probe_line#KODI_WEB_USER=}" ;;
    KODI_WEB_PASSWORD=*) probe_password="${probe_line#KODI_WEB_PASSWORD=}" ;;
    KODI_PORT=*) probe_port="${probe_line#KODI_PORT=}" ;;
    ROOM_DISPLAY_RESOLUTION=*) probe_resolution="${probe_line#ROOM_DISPLAY_RESOLUTION=}" ;;
    ROOM_DISPLAY_WHITELIST=*) probe_whitelist="${probe_line#ROOM_DISPLAY_WHITELIST=}" ;;
    "") ;;
    *) printf "display probe rejected an unknown parameter\n" >&2; exit 1 ;;
  esac
done

[ -n "${probe_user}" ] || { printf "display probe requires a Kodi user\n" >&2; exit 1; }
[ -n "${probe_resolution}" ] || { printf "display probe requires a resolution label\n" >&2; exit 1; }
[ -n "${probe_whitelist}" ] || { printf "display probe requires a whitelist\n" >&2; exit 1; }

probe_dir="$(mktemp -d)"
trap "rm -rf -- ${probe_dir}" EXIT INT TERM

# The password reaches curl only through a mode-600 configuration file in a
# directory the trap removes: it never appears in argv or in the process list.
printf "user = \"%s:%s\"\n" "${probe_user}" "${probe_password}" \
  > "${probe_dir}/curlrc"
cat > "${probe_dir}/request.json" <<PROBE_REQUEST
{"jsonrpc":"2.0","id":1,"method":"Settings.GetSettings","params":{"level":"expert","filter":{"section":"system","category":"display"}}}
PROBE_REQUEST

if ! curl --silent --show-error --fail --max-time 20 \
  --config "${probe_dir}/curlrc" \
  --header "Content-Type: application/json" \
  --data "@${probe_dir}/request.json" \
  "http://127.0.0.1:${probe_port}/jsonrpc" > "${probe_dir}/response.json"; then
  printf "display probe could not reach Kodi on port %s\n" "${probe_port}" >&2
  exit 1
fi

printf "%s\n%s\n" "${probe_resolution}" "${probe_whitelist}" \
  > "${probe_dir}/expected"

python3 - "${probe_dir}/response.json" "${probe_dir}/expected" <<PROBE_PARSE
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    try:
        document = json.load(handle)
    except ValueError:
        raise SystemExit("display probe could not parse Kodi response")

with open(sys.argv[2], "r", encoding="utf-8") as handle:
    wanted_label = handle.readline().strip()
    wanted_modes = [item for item in handle.readline().strip().split(",") if item]

settings = document.get("result", {}).get("settings")
if not isinstance(settings, list):
    raise SystemExit("display probe did not receive a settings list")

by_id = {}
for setting in settings:
    if isinstance(setting, dict) and "id" in setting:
        by_id[setting["id"]] = setting


def options(setting_id):
    setting = by_id.get(setting_id)
    if setting is None:
        raise SystemExit(
            "display probe: Kodi did not report %s; is the display powered on "
            "and selected to this device?" % setting_id)
    found = []
    for option in setting.get("options", []):
        if isinstance(option, dict) and "label" in option:
            found.append((str(option["label"]).strip(), option.get("value")))
    return found


resolution_options = options("videoscreen.resolution")
matches = [value for label, value in resolution_options if label == wanted_label]
if not matches:
    raise SystemExit(
        "display probe: the display does not offer resolution %s; it offers: %s"
        % (wanted_label, ", ".join(sorted(
            label for label, _ in resolution_options)) or "nothing"))
if len(matches) > 1:
    raise SystemExit(
        "display probe: resolution %s is ambiguous; Kodi reports it %d times"
        % (wanted_label, len(matches)))

reported_modes = set(label for label, _ in options("videoscreen.whitelist"))
missing = [mode for mode in wanted_modes if mode not in reported_modes]
if missing:
    raise SystemExit(
        "display probe: the display no longer reports pinned display "
        "mode(s): %s" % ", ".join(missing))

print("resolution_index=%s" % matches[0])
PROBE_PARSE
REMOTE_DISPLAY_PROBE_BODY
}
```

Two details to confirm while implementing, because both are easy to get wrong and both are covered by the tests above:
- `trap "rm -rf -- ${probe_dir}" EXIT` expands `probe_dir` at trap-set time, which is correct here (the value is a `mktemp -d` path with no spaces) and is the only form available without single quotes. If `mktemp -d` could return a path containing a space, `TMPDIR` is at fault, not the probe; the test that asserts no leftover files covers the ordinary case.
- The unquoted `<<PROBE_PARSE` delimiter means the shell expands `$` inside the Python body. The body above deliberately contains none — verify with a grep after writing it, and if a `$` becomes necessary, escape it as `\$`.

- [ ] **Step 4: Expose the test entry point**

In `coreelec_emit_remote_script`, add the dispatch arm and extend the error message:

```bash
    display-probe) coreelec_remote_display_probe_script "${root}" ;;
```

```bash
      die "--emit-remote-script expects backup, payload, stage, deploy, rollback, finalize, verify, verify-probe, display-probe, or authorized-key, not: ${name}"
```

- [ ] **Step 5: Wire it into the main flow**

Add the caller beside the other remote helpers:

```bash
# Runs after the administrator key is installed (which is idempotent and
# independently reversible) and before create_remote_backup, which is the
# first real state change. A display that is off, on another input, or no
# longer reporting a pinned mode aborts the run here, with nothing to undo.
coreelec_resolve_room_display() {
  local script output line
  coreelec_component_effective room || return 0

  script="$(coreelec_remote_display_probe_script)"
  [[ "${script}" != *"'"* ]] \
    || die "Internal error: the remote display probe script must not contain a single quote"

  info "Resolving the ${ROOM_NAME} display mode against the running Kodi" >&2
  output="$(
    {
      printf 'KODI_WEB_USER=%s\n' "${KODI_USER}"
      printf 'KODI_WEB_PASSWORD=%s\n' "${KODI_WEB_PASSWORD}"
      printf 'KODI_PORT=%s\n' "${KODI_PORT}"
      printf 'ROOM_DISPLAY_RESOLUTION=%s\n' "${ROOM_DISPLAY_RESOLUTION}"
      printf 'ROOM_DISPLAY_WHITELIST=%s\n' "${ROOM_DISPLAY_WHITELIST}"
    } | ssh_keyed "sh -c '${script}'"
  )" || die "The display probe failed. The display must be powered on and selected to this device for the room component to apply. Nothing on the device has been changed apart from the administrator key."

  while IFS= read -r line; do
    case "${line}" in
      resolution_index=*) ROOM_DISPLAY_RESOLUTION_INDEX="${line#resolution_index=}" ;;
    esac
  done <<< "${output}"

  case "${ROOM_DISPLAY_RESOLUTION_INDEX}" in
    ""|*[!0-9]*)
      die "The display probe did not return a usable resolution index for ${ROOM_DISPLAY_RESOLUTION}"
      ;;
  esac
  info "Resolved ${ROOM_DISPLAY_RESOLUTION} to Kodi resolution index ${ROOM_DISPLAY_RESOLUTION_INDEX}" >&2
}
```

Call it in the main flow between the key install and the backup:

```bash
install_public_key_if_needed

coreelec_resolve_room_display

REMOTE_BACKUP_PATH="$(create_remote_backup)"
```

`ROOM_DISPLAY_RESOLUTION_INDEX` is read by `coreelec_settings_payload` (Task 3), which runs later in `apply_kodi_baseline`, so the ordering is already correct.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-report.sh`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-report.sh
git commit -m "feat: resolve the room display mode before the transaction begins

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Verification and reporting

**Files:**
- Modify: `provision-coreelec.sh` (verify probe `ROOM_SETTING_IDS` and `canonical_components`, `coreelec_verify_request`, `verify_remote_baseline`, `coreelec_report_render`)
- Test: `tests/test-coreelec-report.sh`

**Interfaces:**
- Consumes: the verify probe's `setting_value`, `coreelec_report_comparison`, `coreelec_observation_value`
- Produces: report keys `room.display.resolution.status`, `room.display.whitelist.status`, `room.audio.<codec>.status`, `room.dolbyvision.status`

**Status vocabulary** — only `ok` passes:

| Status | Meaning |
|---|---|
| `ok` | The device reports exactly the configured value |
| `mismatch` | The device reports a different value |
| `unsupported` | The display no longer reports a pinned mode |
| `unobservable` | Kodi did not report the setting at all |

**The normalization trap:** the verify probe's `setting_value` **joins list values with a space**, so the observed whitelist arrives space-separated while the configured value is comma-separated. The comparison must normalize both to the same separator before comparing, and the test must prove it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test-coreelec-report.sh`:

```bash
test_room_report_normalizes_the_whitelist_separator() {
  local dir report
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_room_observations "${dir}/observations.env" \
    whitelist='0409602160024.00000pstd 0384002160060.00000pstd'
  report="$(run_room_verification "${dir}" \
    '0409602160024.00000pstd,0384002160060.00000pstd')"
  assert_contains "${report}" "room.display.whitelist.status=ok"
}

test_room_report_flags_a_whitelist_mismatch() {
  local dir report
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_room_observations "${dir}/observations.env" \
    whitelist='0384002160060.00000pstd'
  report="$(run_room_verification "${dir}" \
    '0409602160024.00000pstd,0384002160060.00000pstd')"
  assert_contains "${report}" "room.display.whitelist.status=mismatch"
  assert_contains "${report}" "verification_result=fail"
}

test_room_report_flags_an_unobservable_setting() {
  local dir report
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_room_observations "${dir}/observations.env" omit=videoscreen.whitelist
  report="$(run_room_verification "${dir}" '0384002160060.00000pstd')"
  assert_contains "${report}" "room.display.whitelist.status=unobservable"
  assert_contains "${report}" "verification_result=fail"
}

test_room_report_reports_dolby_vision_positively() {
  local dir report
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_room_observations "${dir}/observations.env" disabledolbyvision=false
  report="$(run_room_verification "${dir}" '0384002160060.00000pstd')"
  assert_contains "${report}" "room.dolbyvision.status=ok"
  assert_not_contains "${report}" "room.dolbyvision.disabled"
}

test_room_report_flags_each_audio_codec_independently() {
  local dir report
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_room_observations "${dir}/observations.env" truehdpassthrough=false
  report="$(run_room_verification "${dir}" '0384002160060.00000pstd')"
  assert_contains "${report}" "room.audio.truehd.status=mismatch"
  assert_contains "${report}" "room.audio.dts.status=ok"
  assert_contains "${report}" "room.audio.eac3.status=ok"
}

test_report_omits_room_keys_when_room_is_out_of_scope() {
  local dir report
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  report="$(run_baseline_verification "${dir}")"
  assert_not_contains "${report}" "room."
}

test_verify_probe_requests_room_settings_only_when_selected() {
  local output
  output="$(run_verify_probe_with_components "core,room")"
  assert_contains "${output}" "videoscreen.whitelist"
  output="$(run_verify_probe_with_components "core,skin")"
  assert_not_contains "${output}" "videoscreen.whitelist"
}
```

Add `write_room_observations` and `run_room_verification` beside the existing observation helpers, following their structure. `write_room_observations` writes a complete, all-matching room observation set and lets `key=value` overrides replace one value or `omit=<setting id>` drop one entirely.

Register all seven tests in the trailing `run_all_tests` list.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-report.sh`
Expected: FAIL — no `room.*` keys are produced.

- [ ] **Step 3: Extend the verify probe**

In the probe's preamble, beside `SKIN_SETTING_IDS`:

```python
ROOM_SETTING_IDS = [
    "videoscreen.resolution",
    "videoscreen.whitelist",
    "coreelec.amlogic.disabledolbyvision",
    "coreelec.amlogic.dolbyvisionled",
    "audiooutput.passthrough",
    "audiooutput.ac3passthrough",
    "audiooutput.eac3passthrough",
    "audiooutput.dtspassthrough",
    "audiooutput.truehdpassthrough",
    "audiooutput.dtshdpassthrough",
]
SETTING_IDS = (CORE_SETTING_IDS + SKIN_SETTING_IDS + SERVICE_SETTING_IDS
               + ROOM_SETTING_IDS)
```

Extend the scope list and the selection:

```python
    canonical_components = ["core", "cec", "addons", "services", "skin", "room"]
```

```python
    if selected("room"):
        setting_ids.extend(ROOM_SETTING_IDS)
```

- [ ] **Step 4: Send the expected values**

In `coreelec_verify_request`, after the `addons` block:

```bash
  if coreelec_component_effective room; then
    coreelec_settings_payload_entry ROOM_NAME "${ROOM_NAME}"
    coreelec_settings_payload_entry ROOM_DISPLAY_RESOLUTION "${ROOM_DISPLAY_RESOLUTION}"
    coreelec_settings_payload_entry ROOM_DISPLAY_WHITELIST "${ROOM_DISPLAY_WHITELIST}"
  fi
```

The audio and Dolby Vision expectations are already in the `ROOM_*` globals on the local side, so `verify_remote_baseline` compares against them directly and they do not need to cross to the device.

- [ ] **Step 5: Compare and report**

In `verify_remote_baseline`, add a block guarded by `coreelec_component_effective room`. Compare each observed value against the configured one, emitting one `room.*.status` key per setting using the four-value vocabulary. The whitelist comparison normalizes first:

```bash
    # The verify probe joins list values with a space; the configuration
    # states the whitelist comma-separated. Normalize both to commas before
    # comparing so a separator difference is never reported as a mismatch.
    coreelec_normalize_mode_list() {
      printf '%s' "$1" | tr ' ' ',' | tr -s ','
    }
```

Order within the whitelist is significant to Kodi's mode selection and is therefore compared as-is, not sorted.

Emit `unobservable` when `coreelec_observation_value` finds no entry for a setting ID, and `mismatch` when the values differ. `unsupported` is reserved for the case where the observed whitelist is missing a configured mode *and* the device reported the setting — distinguishing "Kodi wrote something else" from "the display stopped offering it".

In `coreelec_report_render`, add the room scope flag beside the existing component flags so a room-scoped run is identifiable in the report header, and ensure no `room.*` key is rendered when room is out of scope.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-report.sh`
Expected: PASS.

- [ ] **Step 7: Run every suite**

Run:
```bash
ls tests/*.sh | grep -v test-helper | while read f; do echo "== $f"; bash "$f" || echo "FAILED: $f"; done
```
Expected: every suite passes (~7 minutes). Fix anything that regressed before committing.

- [ ] **Step 8: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-report.sh
git commit -m "feat: verify and report the room desired state

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Documentation

**Files:**
- Create: `docs/devices/ugoos-am6b-plus/room-desired-state.md`
- Modify: `rooms/theater/devices/ugoos-am6b-plus.md`, `docs/operations/provision-ugoos.md`, `config/README.md`

No code changes and no tests. Every statement must match what Tasks 1-6 actually implemented — read the code, do not restate this plan.

- [ ] **Step 1: Write the room contract reference**

Create `docs/devices/ugoos-am6b-plus/room-desired-state.md` covering:
- What the `room` component manages and what it deliberately does not (`advancedsettings.xml` belongs to the playback-tuning work in #9; the ALSA device strings are unmanaged and tracked in #17).
- Every configuration key: meaning, accepted values, and the exact Kodi setting it writes — including that `ROOM_DOLBY_VISION` is stated positively and inverted onto `coreelec.amlogic.disabledolbyvision`.
- The display mode string format (five width digits, five height digits, three refresh digits, a dot, five decimals, scan letter, `std`) with a worked example.
- Why the resolution is a label rather than Kodi's index, and what the pre-transaction probe does.
- **The operating requirement: the display must be powered on and selected to this device.** State the failure mode plainly — the run aborts before touching the device.
- The four report statuses and what an operator should do about each.

- [ ] **Step 2: Reduce the theater device guide to a pointer**

In `rooms/theater/devices/ugoos-am6b-plus.md`, replace the prose listing of display and audio values with a pointer to `config/rooms/theater/room.conf` as the authority, and to the reference above for what the keys mean. Keep anything the room component does not manage (physical wiring, HDMI input assignments, the OREI link) exactly as it is. Delete no content that is still the only record of something.

- [ ] **Step 3: Update the operator runbook**

In `docs/operations/provision-ugoos.md`, add the room-scoped run:

```bash
./provision-coreelec.sh --target ugoos-theater --component room --room theater
```

State the display-powered-on precondition up front, show what a successful `room.*` report block looks like, and describe what each non-`ok` status means for the operator.

- [ ] **Step 4: Update the configuration boundary document**

In `config/README.md`, add a section for `config/rooms/<room>/room.conf`: it is a separate file with a separate key allowlist, it holds no secrets, and a key from one file is rejected by name in the other. List the ten keys.

- [ ] **Step 5: Verify the documented commands**

Run every command quoted in the documentation that does not contact a device:

```bash
bash provision-coreelec.sh --component room --room theater --print-component-plan
bash provision-coreelec.sh --help
```

Expected: both succeed, and the help text matches what the documentation claims.

- [ ] **Step 6: Commit**

```bash
git add docs/devices/ugoos-am6b-plus/room-desired-state.md \
  rooms/theater/devices/ugoos-am6b-plus.md \
  docs/operations/provision-ugoos.md config/README.md
git commit -m "docs: describe the room desired-state component

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Completion

After Task 7, the component is code-complete but **has never run against a device**. The live run on `ugoos-theater` is a separate, operator-gated step:

1. A dry read-only confirmation that the display probe resolves correctly against the live Kodi.
2. A real `--component room --room theater` run with the Sony powered on and on HDMI IN 4.
3. Confirm the `room.*` report block is all `ok`, then finalize the transaction.

Do not perform any of these without asking first. Propose each step and wait for approval.
