# Managed ALSA Audio Device Strings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `audiooutput.audiodevice`, `audiooutput.passthroughdevice` and `audiooutput.channels` under management so that audio output drift is reported instead of silently breaking passthrough.

**Architecture:** Configuration states *intent* as a stable symbolic name; a pre-transaction probe resolves that intent against the enumeration the running Kodi actually offers, and the transaction writes the resolved concrete value. This is the same shape as the existing display-resolution probe, and for the same reason: the concrete values embed a kernel card name and opaque enum ordinals that are not stable facts we can safely hard-code.

**Tech Stack:** Bash 3.2 (controller), POSIX `sh` + BusyBox + Python 3 (device), Kodi 21 JSON-RPC, `guisettings.xml`.

**Spec:** No separate spec document. This plan is the binding design, approved in chat on 2026-09-17. The source issue is #17; the excluded-from-`room` rationale is in the #7 design review.

## Global Constraints

- **The JSON-RPC settings category is `audio`, NOT `audiooutput`.** `{"section":"system","category":"audiooutput"}` returns `Invalid params` (`-32602`). This was confirmed live on `ugoos-theater`. Fixtures cannot catch this error, because a fixture replays whatever JSON the test author writes.
- The remote probe script **must not contain a single-quote character**. It is delivered as `sh -c '<script>'`. `coreelec_resolve_room_display` asserts this at `provision-coreelec.sh:5321`; the new resolver must assert the same.
- Controller is **Bash 3.2**: no `declare -A`, no `local -n`, no `${var,,}`, no `mapfile`, no `declare -g`.
- Device programs are **POSIX `sh` on BusyBox**: no `base64` binary, no `grep --include`, no `sqlite3`, and **never `paste`** (on CoreELEC `/usr/bin/paste` uploads stdin to a public pastebin).
- Secrets never appear in `argv`. The Kodi password reaches `curl` only through a mode-600 `curlrc` inside a `mktemp -d` directory removed by a trap, exactly as the display probe does it.
- New tests must be appended to the trailing backslash-continued `run_all_tests` list, or they silently never run.
- Test files run under `set -Eeuo pipefail` with `IFS=$'\n\t'`. A conditional emit written as `[[ -n "${x}" ]] && printf ...` is safe mid-function but returns 1 when it is a function's **last** statement, which aborts the caller. Write conditional emits as full `if` blocks. A bare `read` will not split on spaces under this `IFS`.
- Full suite: `ls tests/*.sh | grep -v test-helper | while read f; do bash "$f"; done` (~7 minutes).
- **Every verification test must compare against a value Kodi actually produced.** Hand-writing both sides of a comparison is what let the boolean-casing bug reach a live device in #7.

## Vocabulary

The symbolic intent names and the ALSA selector token each one resolves to:

| Intent | ALSA selector token | Live example value |
|---|---|---|
| `analog` | `@` | `ALSA:@\|Default (AML-AUGESOUND Analog)` |
| `sysdefault` | `sysdefault` | `ALSA:sysdefault:CARD=AMLAUGESOUND\|AML-AUGESOUND` |
| `hdmi-multichannel` | `surround71` | `ALSA:surround71:CARD=AMLAUGESOUND,DEV=0\|AML-AUGESOUND` |
| `spdif` | `iec958` | `ALSA:iec958:CARD=AMLAUGESOUND,DEV=0\|AML-AUGESOUND` |
| `hdmi` | `hdmi` | `ALSA:hdmi:CARD=AMLAUGESOUND,DEV=0\|AML-AUGESOUND` |

Token extraction from an option value: strip the leading `ALSA:`, take everything before the first `|`, then take everything before the first `:`. Non-`ALSA:` options (for example `PULSE:Default|Bluetooth Audio (PULSEAUDIO)`) are ignored entirely.

`audiooutput.channels` is resolved by matching the option **label** (`7.1`) and taking that option's integer value. The integer is an opaque Kodi enum ordinal and is never written from configuration.

## Live reference data (captured from `ugoos-theater`, 2026-09-17)

`audiooutput.audiodevice` options:

```
ALSA:@|Default (AML-AUGESOUND Analog)            => ALSA: Default (AML-AUGESOUND Analog), PCM
ALSA:sysdefault:CARD=AMLAUGESOUND|AML-AUGESOUND  => ALSA: AML-AUGESOUND, PCM
ALSA:surround71:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND => ALSA: AML-AUGESOUND, HDMI Multi Ch PCM
ALSA:iec958:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND => ALSA: AML-AUGESOUND, S/PDIF
ALSA:hdmi:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND   => ALSA: AML-AUGESOUND, HDMI
PULSE:Default|Bluetooth Audio (PULSEAUDIO)        => PULSE: Default, Bluetooth Audio (PULSEAUDIO)
```

`audiooutput.passthroughdevice` options are a strict subset: only `iec958` and `hdmi`.

`audiooutput.channels` options: `1`=>`2.0`, `2`=>`2.1`, `3`=>`3.0`, `4`=>`3.1`, `5`=>`4.0`, `6`=>`4.1`, `7`=>`5.0`, `8`=>`5.1`, `9`=>`7.0`, `10`=>`7.1`.

Current live state: `audiodevice` and `passthroughdevice` are hand-set (no `default="true"`); `channels` is `1` (2.0) and still `default="true"`, which is the latent misconfiguration this plan corrects.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf` | Shared AM6B+ baseline | Add `AUDIO_DEVICE`, `AUDIO_PASSTHROUGH_DEVICE` |
| `config/rooms/theater/room.conf` | Theater room desired state | Add `ROOM_AUDIO_CHANNELS` |
| `lib/coreelec-config.sh` | Strict never-`eval` config parsers | Accept + validate the three new keys |
| `provision-coreelec.sh` | Probe, payload, transformer, verify, report | New probe + resolver + writes + comparisons |
| `tests/test-coreelec-config.sh` | Config parser tests | Validation tests |
| `tests/test-coreelec-report.sh` | Probe/verify/report tests | Probe parser, verify, report tests |
| `docs/devices/ugoos-am6b-plus/audio-output.md` | Operator documentation | New |

## Variables

| Variable | Origin | Meaning |
|---|---|---|
| `AUDIO_DEVICE` | `provision.conf` | Symbolic intent for `audiooutput.audiodevice` |
| `AUDIO_PASSTHROUGH_DEVICE` | `provision.conf` | Symbolic intent for `audiooutput.passthroughdevice` |
| `ROOM_AUDIO_CHANNELS` | `room.conf` | Speaker layout label, e.g. `7.1` |
| `AUDIO_DEVICE_VALUE` | probe | Resolved concrete ALSA string |
| `AUDIO_PASSTHROUGH_DEVICE_VALUE` | probe | Resolved concrete ALSA string |
| `ROOM_AUDIO_CHANNELS_INDEX` | probe | Resolved Kodi enum ordinal |

---

### Task 1: Configuration surface for audio intent

**Files:**
- Modify: `lib/coreelec-config.sh` — `coreelec_config_defaults()` (~:234), `coreelec_config_assign()` (~:348), `coreelec_room_config_defaults()` (~:445), `coreelec_room_config_assign()`
- Modify: `config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf`
- Modify: `config/rooms/theater/room.conf`
- Test: `tests/test-coreelec-config.sh`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: shell variables `AUDIO_DEVICE`, `AUDIO_PASSTHROUGH_DEVICE` (from `provision.conf`) and `ROOM_AUDIO_CHANNELS` (from `room.conf`), each validated against a closed vocabulary. Task 3 reads all three.

The two audio-device keys belong to the **shared** parser, not the room parser: they are AM6B+ hardware facts identical in every room. `ROOM_AUDIO_CHANNELS` belongs to the **room** parser, because the speaker layout is a property of the room's AVR. The two allowlists are deliberately separate and must not leak into each other.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test-coreelec-config.sh`:

```bash
test_audio_device_intents_are_validated() {
  local dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN

  printf 'AUDIO_DEVICE=hdmi-multichannel\nAUDIO_PASSTHROUGH_DEVICE=hdmi\n' \
    > "${dir}/ok.conf"
  (
    coreelec_config_defaults
    coreelec_config_load "${dir}/ok.conf"
    [[ "${AUDIO_DEVICE}" == "hdmi-multichannel" ]] || exit 1
    [[ "${AUDIO_PASSTHROUGH_DEVICE}" == "hdmi" ]] || exit 1
  ) || { fail "valid audio intents must load"; return 1; }

  printf 'AUDIO_DEVICE=surround71\n' > "${dir}/bad.conf"
  local output
  output="$(
    (
      coreelec_config_defaults
      coreelec_config_load "${dir}/bad.conf"
    ) 2>&1
  )" && { fail "an ALSA selector token is not a valid intent"; return 1; }
  assert_contains "${output}" "AUDIO_DEVICE" \
    "the rejection names the offending key" || return 1

  printf 'ROOM_AUDIO_CHANNELS=7.1\n' > "${dir}/room.conf"
  output="$(
    (
      coreelec_config_defaults
      coreelec_config_load "${dir}/room.conf"
    ) 2>&1
  )" && { fail "a room key must not be accepted by the shared parser"; return 1; }
}

test_room_audio_channels_is_validated() {
  local dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN

  printf 'ROOM_AUDIO_CHANNELS=7.1\n' > "${dir}/ok.conf"
  (
    coreelec_room_config_defaults
    coreelec_room_config_load "${dir}/ok.conf"
    [[ "${ROOM_AUDIO_CHANNELS}" == "7.1" ]] || exit 1
  ) || { fail "a valid layout must load"; return 1; }

  printf 'ROOM_AUDIO_CHANNELS=10\n' > "${dir}/index.conf"
  output="$(
    (
      coreelec_room_config_defaults
      coreelec_room_config_load "${dir}/index.conf"
    ) 2>&1
  )" && { fail "Kodi's enum ordinal is not a valid layout label"; return 1; }
  assert_contains "${output}" "ROOM_AUDIO_CHANNELS" \
    "the rejection names the offending key" || return 1

  printf 'AUDIO_DEVICE=hdmi\n' > "${dir}/shared.conf"
  output="$(
    (
      coreelec_room_config_defaults
      coreelec_room_config_load "${dir}/shared.conf"
    ) 2>&1
  )" && { fail "a shared key must not be accepted by the room parser"; return 1; }
}
```

Register both in the trailing `run_all_tests` list.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-config.sh`
Expected: FAIL — `AUDIO_DEVICE` is currently an unknown key, so the "valid audio intents must load" assertion fails.

- [ ] **Step 3: Add the keys to both parsers**

In `coreelec_config_defaults()`, beside the other baseline defaults:

```bash
  AUDIO_DEVICE=""
  AUDIO_PASSTHROUGH_DEVICE=""
```

In `coreelec_config_assign()`, following the `ADDON_UPDATE_MODE` pattern at `lib/coreelec-config.sh:348`:

```bash
    AUDIO_DEVICE)
      coreelec_config_validate_enum "AUDIO_DEVICE" "${value}" \
        "analog" "sysdefault" "hdmi-multichannel" "spdif" "hdmi"
      AUDIO_DEVICE="${value}"
      ;;
    AUDIO_PASSTHROUGH_DEVICE)
      coreelec_config_validate_enum "AUDIO_PASSTHROUGH_DEVICE" "${value}" \
        "analog" "sysdefault" "hdmi-multichannel" "spdif" "hdmi"
      AUDIO_PASSTHROUGH_DEVICE="${value}"
      ;;
```

The passthrough key accepts the full vocabulary rather than only `spdif`/`hdmi`. Kodi offers a narrower option list for that setting, so an intent Kodi does not offer is caught by the probe in Task 2, which reports the actual available options. Rejecting it here as well would duplicate that check and hide the more informative message.

In `coreelec_room_config_defaults()`, beside the other room defaults:

```bash
  ROOM_AUDIO_CHANNELS=""
```

and immediately below the existing `ROOM_DISPLAY_RESOLUTION_INDEX=""` line, which carries the "resolved by the probe, never by configuration" comment, add:

```bash
  ROOM_AUDIO_CHANNELS_INDEX=""
```

In `coreelec_room_config_assign()`, beside the other room audio keys:

```bash
    ROOM_AUDIO_CHANNELS)
      coreelec_config_validate_enum "ROOM_AUDIO_CHANNELS" "${value}" \
        "2.0" "2.1" "3.0" "3.1" "4.0" "4.1" "5.0" "5.1" "7.0" "7.1"
      ROOM_AUDIO_CHANNELS="${value}"
      ;;
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-config.sh`
Expected: PASS.

- [ ] **Step 5: Set the production values**

In `config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf`, after the `# --- Regional baseline ---` block, add:

```
# --- Audio output -----------------------------------------------------------
# Stated as intent, not as the concrete ALSA string. The concrete value embeds
# the kernel card name (AMLAUGESOUND on this hardware), which is a driver
# detail rather than a stable fact, so the pre-transaction audio probe resolves
# the intent against the enumeration the running Kodi actually offers.
#
# hdmi-multichannel is ALSA surround71: multichannel PCM over HDMI, which is
# what decoded (non-bitstreamed) audio needs. Passthrough bitstreams go out the
# plain hdmi device.
AUDIO_DEVICE=hdmi-multichannel
AUDIO_PASSTHROUGH_DEVICE=hdmi
```

In `config/rooms/theater/room.conf`, in the existing audio block below the passthrough keys:

```
# The Denon drives a 7.1 layout. This governs only audio Kodi decodes itself;
# bitstreamed formats above are unaffected by it. Stated as a layout label
# because Kodi's channel setting is an opaque enum ordinal, resolved by the
# audio probe.
ROOM_AUDIO_CHANNELS=7.1
```

- [ ] **Step 6: Verify the production configuration still parses**

Run: `bash tests/test-coreelec-config.sh`
Expected: PASS, including the existing `test_production_config_*` tests.

- [ ] **Step 7: Commit**

```bash
git add lib/coreelec-config.sh tests/test-coreelec-config.sh \
  config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf \
  config/rooms/theater/room.conf
git commit -m "feat: accept audio output intent in configuration (Task 1)"
```

---

### Task 2: The remote audio probe script

**Files:**
- Modify: `provision-coreelec.sh` — add `coreelec_remote_audio_probe_script()` beside `coreelec_remote_display_probe_script()` (~:3506); register it in the `--emit-remote-script` dispatch (~:3634)
- Test: `tests/test-coreelec-report.sh`

**Interfaces:**
- Consumes: nothing from Task 1 at runtime. The probe receives intents on stdin as `KEY=value` lines and never reads the controller's shell variables.
- Produces: `coreelec_remote_audio_probe_script()`, emitting a POSIX `sh` program. Input lines: `KODI_WEB_USER`, `KODI_WEB_PASSWORD`, `KODI_PORT`, and any of `AUDIO_DEVICE`, `AUDIO_PASSTHROUGH_DEVICE`, `ROOM_AUDIO_CHANNELS`. Output lines, one per intent supplied: `audio_device=<concrete ALSA string>`, `audio_passthrough_device=<concrete ALSA string>`, `audio_channels=<integer>`. Task 3 parses exactly these three keys. `--emit-remote-script audio-probe` prints the program.

The program must contain **no single-quote character** and must use the `audio` category, not `audiooutput`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test-coreelec-report.sh`:

```bash
# Mirrors the shape Kodi actually returns, taken from ugoos-theater on
# 2026-09-17: device options carry a PULSE entry that must be ignored, the
# passthrough list is a strict subset, and channels are label/ordinal pairs.
write_audio_probe_stub() {
  local dir="$1" card="${2:-AMLAUGESOUND}"
  local bin_dir="${dir}/bin" response="${dir}/stub-response.json"
  mkdir -p "${bin_dir}"
  python3 - "${response}" "${card}" <<'PYEOF'
import json
import sys

path, card = sys.argv[1], sys.argv[2]


def alsa(selector, friendly="AML-AUGESOUND"):
    return "ALSA:%s|%s" % (selector, friendly)


device_options = [
    {"label": "ALSA: Default, PCM", "value": alsa("@", "Default")},
    {"label": "ALSA: PCM", "value": alsa("sysdefault:CARD=%s" % card)},
    {"label": "ALSA: HDMI Multi Ch PCM",
     "value": alsa("surround71:CARD=%s,DEV=0" % card)},
    {"label": "ALSA: S/PDIF", "value": alsa("iec958:CARD=%s,DEV=0" % card)},
    {"label": "ALSA: HDMI", "value": alsa("hdmi:CARD=%s,DEV=0" % card)},
    {"label": "PULSE: Default", "value": "PULSE:Default|Bluetooth Audio"},
]
passthrough_options = [
    {"label": "ALSA: S/PDIF", "value": alsa("iec958:CARD=%s,DEV=0" % card)},
    {"label": "ALSA: HDMI", "value": alsa("hdmi:CARD=%s,DEV=0" % card)},
]
channel_options = [
    {"label": layout, "value": index} for index, layout in enumerate(
        ["2.0", "2.1", "3.0", "3.1", "4.0", "4.1", "5.0", "5.1", "7.0", "7.1"],
        start=1)
]
document = {
    "jsonrpc": "2.0", "id": 1,
    "result": {"settings": [
        {"id": "audiooutput.audiodevice", "options": device_options},
        {"id": "audiooutput.passthroughdevice",
         "definition": {"options": passthrough_options}},
        {"id": "audiooutput.channels", "options": channel_options},
    ]},
}
with open(path, "w") as handle:
    json.dump(document, handle)
PYEOF
  cat > "${bin_dir}/curl" <<STUB
#!/bin/sh
cat "${response}"
STUB
  chmod +x "${bin_dir}/curl"
}

# Runs the emitted probe the way the device does: parameter lines on stdin,
# the stubbed curl first on PATH, TMPDIR private so mktemp -d is observable.
run_audio_probe() {
  local dir="$1" device="$2" passthrough="$3" channels="$4" script
  mkdir -p "${dir}/tmp"
  script="$(bash "${PROVISIONER}" --emit-remote-script audio-probe)"
  # These test files run under `set -Eeuo pipefail`, so a bare
  # `[[ -n "${x}" ]] && printf ...` would abort the whole suite whenever the
  # condition is false. Every conditional emit here is a full `if` block.
  {
    printf 'KODI_WEB_USER=kodi\nKODI_WEB_PASSWORD=hunter2\nKODI_PORT=8080\n'
    if [[ -n "${device}" ]]; then
      printf 'AUDIO_DEVICE=%s\n' "${device}"
    fi
    if [[ -n "${passthrough}" ]]; then
      printf 'AUDIO_PASSTHROUGH_DEVICE=%s\n' "${passthrough}"
    fi
    if [[ -n "${channels}" ]]; then
      printf 'ROOM_AUDIO_CHANNELS=%s\n' "${channels}"
    fi
  } | PATH="${dir}/bin:${PATH}" TMPDIR="${dir}/tmp" sh -c "${script}"
}

test_audio_probe_resolves_intents_to_concrete_values() {
  local dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_audio_probe_stub "${dir}"
  output="$(run_audio_probe "${dir}" "hdmi-multichannel" "hdmi" "7.1")"
  assert_contains "${output}" \
    "audio_device=ALSA:surround71:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND" \
    "the multichannel intent resolves to surround71" || return 1
  assert_contains "${output}" \
    "audio_passthrough_device=ALSA:hdmi:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND" \
    "the passthrough intent resolves to hdmi" || return 1
  assert_contains "${output}" "audio_channels=10" \
    "the 7.1 label resolves to Kodi's ordinal" || return 1
}

# The whole reason intent is stored instead of the concrete string: a card
# rename must not require touching configuration.
test_audio_probe_survives_a_card_rename() {
  local dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_audio_probe_stub "${dir}" "AMLT9015"
  output="$(run_audio_probe "${dir}" "hdmi-multichannel" "hdmi" "")"
  assert_contains "${output}" \
    "audio_device=ALSA:surround71:CARD=AMLT9015,DEV=0|AML-AUGESOUND" \
    "the intent resolves against whatever the card is called" || return 1
}

test_audio_probe_resolves_only_what_it_is_asked_for() {
  local dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_audio_probe_stub "${dir}"
  output="$(run_audio_probe "${dir}" "" "" "5.1")"
  assert_contains "${output}" "audio_channels=8" \
    "a channels-only run resolves channels" || return 1
  assert_not_contains "${output}" "audio_device=" \
    "a channels-only run must not emit a device line" || return 1
}

test_audio_probe_fails_closed_on_an_unavailable_output() {
  local dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_audio_probe_stub "${dir}"
  # Kodi offers only iec958 and hdmi for passthrough, never surround71.
  output="$(run_audio_probe "${dir}" "hdmi" "hdmi-multichannel" "" 2>&1)" \
    && { fail "an unavailable passthrough output must fail the probe"; return 1; }
  assert_contains "${output}" "audiooutput.passthroughdevice" \
    "the failure names the setting" || return 1
}

test_audio_probe_fails_closed_on_an_unavailable_layout() {
  local dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_audio_probe_stub "${dir}"
  output="$(run_audio_probe "${dir}" "" "" "9.1" 2>&1)" \
    && { fail "a layout Kodi does not offer must fail the probe"; return 1; }
  assert_contains "${output}" "audiooutput.channels" \
    "the failure names the setting" || return 1
}

test_audio_probe_rejects_an_unknown_parameter() {
  local dir output script
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_audio_probe_stub "${dir}"
  mkdir -p "${dir}/tmp"
  script="$(bash "${PROVISIONER}" --emit-remote-script audio-probe)"
  output="$(printf 'KODI_WEB_USER=kodi\nNOT_A_PARAMETER=1\n' \
    | PATH="${dir}/bin:${PATH}" TMPDIR="${dir}/tmp" sh -c "${script}" 2>&1)" \
    && { fail "an unknown parameter must be rejected"; return 1; }
  assert_contains "${output}" "unknown parameter" \
    "the rejection says what went wrong" || return 1
}

test_audio_probe_reports_an_unreachable_kodi() {
  local dir output script
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_failing_curl_stub "${dir}"
  mkdir -p "${dir}/tmp"
  script="$(bash "${PROVISIONER}" --emit-remote-script audio-probe)"
  output="$(printf 'KODI_WEB_USER=kodi\nAUDIO_DEVICE=hdmi\n' \
    | PATH="${dir}/bin:${PATH}" TMPDIR="${dir}/tmp" sh -c "${script}" 2>&1)" \
    && { fail "an unreachable Kodi must fail the probe"; return 1; }
  assert_contains "${output}" "could not reach Kodi" \
    "the failure is attributed to Kodi, not to parsing" || return 1
}

test_audio_probe_contains_no_single_quote() {
  local script
  script="$(bash "${PROVISIONER}" --emit-remote-script audio-probe)"
  case "${script}" in
    *"'"*) fail "the audio probe must not contain a single quote"; return 1 ;;
  esac
}

# The category is "audio". Asking for "audiooutput" returns Invalid params
# (-32602) from a real Kodi 21, which no fixture can discover for us.
test_audio_probe_requests_the_audio_category() {
  local script
  script="$(bash "${PROVISIONER}" --emit-remote-script audio-probe)"
  assert_contains "${script}" '"category":"audio"' \
    "the probe asks for the audio category" || return 1
  assert_not_contains "${script}" '"category":"audiooutput"' \
    "audiooutput is not a valid category" || return 1
}
```

Register all nine in the trailing `run_all_tests` list.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-report.sh`
Expected: FAIL — `--emit-remote-script audio-probe` is rejected, because `audio-probe` is not yet a known script name.

- [ ] **Step 3: Write the probe script generator**

Add immediately after `coreelec_remote_display_probe_script()` in `provision-coreelec.sh`:

```bash
# Resolves audio output intent against the enumeration the running Kodi
# offers. The concrete ALSA strings embed the kernel card name, and the
# channel setting is an opaque enum ordinal; neither is a stable fact worth
# hard-coding into configuration that ships to every room. An intent Kodi does
# not offer fails the probe rather than silently selecting something else --
# "the output I asked for is gone" is exactly the drift this manages.
coreelec_remote_audio_probe_script() {
  cat <<'REMOTE_AUDIO_PROBE_BODY'
set -eu
umask 077
probe_user=""
probe_password=""
probe_port="8080"
probe_device=""
probe_passthrough=""
probe_channels=""
while IFS= read -r probe_line; do
  case "${probe_line}" in
    KODI_WEB_USER=*) probe_user="${probe_line#KODI_WEB_USER=}" ;;
    KODI_WEB_PASSWORD=*) probe_password="${probe_line#KODI_WEB_PASSWORD=}" ;;
    KODI_PORT=*) probe_port="${probe_line#KODI_PORT=}" ;;
    AUDIO_DEVICE=*) probe_device="${probe_line#AUDIO_DEVICE=}" ;;
    AUDIO_PASSTHROUGH_DEVICE=*) probe_passthrough="${probe_line#AUDIO_PASSTHROUGH_DEVICE=}" ;;
    ROOM_AUDIO_CHANNELS=*) probe_channels="${probe_line#ROOM_AUDIO_CHANNELS=}" ;;
    "") ;;
    *) printf "audio probe rejected an unknown parameter\n" >&2; exit 1 ;;
  esac
done

[ -n "${probe_user}" ] || { printf "audio probe requires a Kodi user\n" >&2; exit 1; }
if [ -z "${probe_device}" ] && [ -z "${probe_passthrough}" ] && [ -z "${probe_channels}" ]; then
  printf "audio probe requires at least one intent\n" >&2
  exit 1
fi

probe_dir="$(mktemp -d)"
trap "rm -rf -- ${probe_dir}" EXIT INT TERM

# The password reaches curl only through a mode-600 configuration file in a
# directory the trap removes: it never appears in argv or in the process list.
printf "user = \"%s:%s\"\n" "${probe_user}" "${probe_password}" \
  > "${probe_dir}/curlrc"
# The category is audio. audiooutput is not a valid category and Kodi 21
# answers it with Invalid params (-32602).
cat > "${probe_dir}/request.json" <<PROBE_REQUEST
{"jsonrpc":"2.0","id":1,"method":"Settings.GetSettings","params":{"level":"expert","filter":{"section":"system","category":"audio"}}}
PROBE_REQUEST

if ! curl --silent --show-error --fail --max-time 20 \
  --config "${probe_dir}/curlrc" \
  --header "Content-Type: application/json" \
  --data "@${probe_dir}/request.json" \
  "http://127.0.0.1:${probe_port}/jsonrpc" > "${probe_dir}/response.json"; then
  printf "audio probe could not reach Kodi on port %s\n" "${probe_port}" >&2
  exit 1
fi

printf "%s\n%s\n%s\n" "${probe_device}" "${probe_passthrough}" "${probe_channels}" \
  > "${probe_dir}/wanted"

python3 - "${probe_dir}/response.json" "${probe_dir}/wanted" <<PROBE_PARSE
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    try:
        document = json.load(handle)
    except ValueError:
        raise SystemExit("audio probe could not parse Kodi response")

with open(sys.argv[2], "r", encoding="utf-8") as handle:
    wanted_device = handle.readline().strip()
    wanted_passthrough = handle.readline().strip()
    wanted_channels = handle.readline().strip()

settings = document.get("result", {}).get("settings")
if not isinstance(settings, list):
    raise SystemExit("audio probe did not receive a settings list")

by_id = {}
for setting in settings:
    if isinstance(setting, dict) and "id" in setting:
        by_id[setting["id"]] = setting

TOKENS = {
    "analog": "@",
    "sysdefault": "sysdefault",
    "hdmi-multichannel": "surround71",
    "spdif": "iec958",
    "hdmi": "hdmi",
}


def option_pairs(setting_id):
    setting = by_id.get(setting_id)
    if setting is None:
        raise SystemExit("audio probe: Kodi did not report %s" % setting_id)
    raw = setting.get("options")
    if not isinstance(raw, list):
        definition = setting.get("definition")
        if isinstance(definition, dict):
            raw = definition.get("options")
    if not isinstance(raw, list):
        return []
    pairs = []
    for option in raw:
        if isinstance(option, dict) and "label" in option and "value" in option:
            pairs.append((str(option["label"]).strip(), option["value"]))
    return pairs


def resolve_device(setting_id, intent):
    token = TOKENS.get(intent)
    if token is None:
        raise SystemExit("audio probe: unknown audio intent: %s" % intent)
    offered = []
    matches = []
    for _label, value in option_pairs(setting_id):
        text = str(value)
        if not text.startswith("ALSA:"):
            continue
        selector = text[5:].split("|")[0]
        offered.append(selector.split(":")[0])
        if selector.split(":")[0] == token:
            matches.append(text)
    if len(matches) != 1:
        raise SystemExit(
            "audio probe: %s offers no single %s output for intent %s; "
            "Kodi offers: %s"
            % (setting_id, token, intent, ", ".join(offered) or "nothing"))
    return matches[0]


def resolve_channels(layout):
    offered = []
    matches = []
    for label, value in option_pairs("audiooutput.channels"):
        offered.append(label)
        if label == layout:
            matches.append(value)
    if len(matches) != 1:
        raise SystemExit(
            "audio probe: audiooutput.channels does not offer layout %s; "
            "Kodi offers: %s" % (layout, ", ".join(offered) or "nothing"))
    return matches[0]


if wanted_device:
    sys.stdout.write("audio_device=%s\n"
                     % resolve_device("audiooutput.audiodevice", wanted_device))
if wanted_passthrough:
    sys.stdout.write(
        "audio_passthrough_device=%s\n"
        % resolve_device("audiooutput.passthroughdevice", wanted_passthrough))
if wanted_channels:
    sys.stdout.write("audio_channels=%s\n" % resolve_channels(wanted_channels))
PROBE_PARSE
REMOTE_AUDIO_PROBE_BODY
}
```

- [ ] **Step 4: Register the script in the emit dispatch**

In the `case "${name}"` block near `provision-coreelec.sh:3634`, beside `display-probe`:

```bash
    audio-probe) coreelec_remote_audio_probe_script ;;
```

and extend the `die` message in the same `case` to list `audio-probe`:

```bash
      die "--emit-remote-script expects backup, payload, stage, deploy, rollback, finalize, verify, verify-probe, display-probe, audio-probe, or authorized-key, not: ${name}"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-report.sh`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-report.sh
git commit -m "feat: resolve audio output intent with a remote probe (Task 2)"
```

---


### Task 3: Resolve before the transaction, carry the values, write them

**Files:**
- Modify: `provision-coreelec.sh` — declare resolved variables (~:29-32); add `coreelec_resolve_audio_devices()` after `coreelec_resolve_room_display()` (~:5347); call it (~:5859); extend the payload builder (~:5448); extend the transformer (~:690-730)
- Test: `tests/test-coreelec-settings.sh`

**Interfaces:**
- Consumes: `AUDIO_DEVICE`, `AUDIO_PASSTHROUGH_DEVICE`, `ROOM_AUDIO_CHANNELS` (Task 1); `coreelec_remote_audio_probe_script()` (Task 2).
- Produces: shell variables `AUDIO_DEVICE_VALUE`, `AUDIO_PASSTHROUGH_DEVICE_VALUE`, `ROOM_AUDIO_CHANNELS_INDEX`; payload keys of the same names; and the three `guisettings.xml` writes. Task 4 compares against these same three variables.

The resolver runs in the display probe's window: after the administrator key is installed (idempotent, independently reversible) and before `create_remote_backup`, the first real state change. A failure there aborts with nothing to undo.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test-coreelec-settings.sh`:

```bash
test_core_transform_writes_the_resolved_audio_devices() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/root"
  payload="${dir}/payload"
  make_settings_fixture_root "${root}"
  write_scoped_base_payload "${payload}" 1 0 0 0 0 0
  append_payload_entry "${payload}" "AUDIO_DEVICE_VALUE" \
    "ALSA:surround71:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND"
  append_payload_entry "${payload}" "AUDIO_PASSTHROUGH_DEVICE_VALUE" \
    "ALSA:hdmi:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND"
  run_transform "${root}" "${payload}" >/dev/null

  settings="$(guisettings_path "${root}")"
  assert_setting_equals "${settings}" "audiooutput.audiodevice" \
    "ALSA:surround71:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND"
  assert_setting_equals "${settings}" "audiooutput.passthroughdevice" \
    "ALSA:hdmi:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND"
}

# The device strings are core state; a room-only run must not write them.
test_room_transform_writes_channels_but_not_the_devices() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/root"
  payload="${dir}/payload"
  make_settings_fixture_root "${root}"
  write_scoped_base_payload "${payload}" 0 0 0 0 0 1
  append_payload_entry "${payload}" "ROOM_NAME" "theater"
  append_payload_entry "${payload}" "ROOM_DISPLAY_WHITELIST" \
    "0384002160060.00000pstd"
  append_payload_entry "${payload}" "ROOM_DOLBY_VISION" "1"
  append_payload_entry "${payload}" "ROOM_DOLBY_VISION_MODE" "tv-led"
  append_payload_entry "${payload}" "ROOM_AUDIO_PASSTHROUGH" "1"
  append_payload_entry "${payload}" "ROOM_AUDIO_AC3" "1"
  append_payload_entry "${payload}" "ROOM_AUDIO_EAC3" "1"
  append_payload_entry "${payload}" "ROOM_AUDIO_DTS" "1"
  append_payload_entry "${payload}" "ROOM_AUDIO_TRUEHD" "1"
  append_payload_entry "${payload}" "ROOM_AUDIO_DTSHD" "1"
  append_payload_entry "${payload}" "ROOM_AUDIO_CHANNELS_INDEX" "10"
  run_transform "${root}" "${payload}" >/dev/null

  settings="$(guisettings_path "${root}")"
  assert_setting_equals "${settings}" "audiooutput.channels" "10"
  assert_setting_absent "${settings}" "audiooutput.audiodevice"
  assert_setting_absent "${settings}" "audiooutput.passthroughdevice"
}

# An unresolved value is never written: leaving the device exactly as it was
# beats pinning it to something that may mean a different output.
test_transform_skips_unresolved_audio_values() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/root"
  payload="${dir}/payload"
  make_settings_fixture_root "${root}"
  write_scoped_base_payload "${payload}" 1 0 0 0 0 0
  append_payload_entry "${payload}" "AUDIO_DEVICE_VALUE" ""
  append_payload_entry "${payload}" "AUDIO_PASSTHROUGH_DEVICE_VALUE" ""
  run_transform "${root}" "${payload}" >/dev/null

  settings="$(guisettings_path "${root}")"
  assert_setting_absent "${settings}" "audiooutput.audiodevice"
  assert_setting_absent "${settings}" "audiooutput.passthroughdevice"
}
```

Register all three in the trailing `run_all_tests` list.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-settings.sh`
Expected: FAIL — the transformer writes no `audiooutput.audiodevice`, so `assert_setting_equals` finds nothing.

- [ ] **Step 3: Declare the resolved variables**

Beside the existing `ROOM_DISPLAY_RESOLUTION_INDEX=""` declaration near `provision-coreelec.sh:29`:

```bash
# Resolved by coreelec_resolve_audio_devices before the transaction opens.
# Declared here so a probe that returns nothing reaches its own die rather
# than an unbound-variable abort under set -u.
AUDIO_DEVICE_VALUE=""
AUDIO_PASSTHROUGH_DEVICE_VALUE=""
ROOM_AUDIO_CHANNELS_INDEX=""
```

- [ ] **Step 4: Add the resolver**

After `coreelec_resolve_room_display()`:

```bash
# Runs in the same pre-transaction window as the display probe: after the
# administrator key is installed and before create_remote_backup, so a failure
# aborts with nothing to undo. Device intents belong to core, the channel
# layout to room, so a run resolves only what its component scope asks for.
coreelec_resolve_audio_devices() {
  local script output line want_core=0 want_room=0

  coreelec_component_effective core && want_core=1
  coreelec_component_effective room && want_room=1
  (( want_core == 1 || want_room == 1 )) || return 0

  if (( want_core == 1 )); then
    [[ -n "${AUDIO_DEVICE}" ]] \
      || die "The core component requires AUDIO_DEVICE in the shared configuration"
    [[ -n "${AUDIO_PASSTHROUGH_DEVICE}" ]] \
      || die "The core component requires AUDIO_PASSTHROUGH_DEVICE in the shared configuration"
  fi
  if (( want_room == 1 )); then
    [[ -n "${ROOM_AUDIO_CHANNELS}" ]] \
      || die "The room component requires ROOM_AUDIO_CHANNELS in the room configuration"
  fi

  script="$(coreelec_remote_audio_probe_script)"
  [[ "${script}" != *"'"* ]] \
    || die "Internal error: the remote audio probe script must not contain a single quote"

  info "Resolving audio output against the running Kodi" >&2
  output="$(
    {
      printf 'KODI_WEB_USER=%s\n' "${KODI_USER}"
      printf 'KODI_WEB_PASSWORD=%s\n' "${KODI_WEB_PASSWORD}"
      printf 'KODI_PORT=%s\n' "${KODI_PORT}"
      if (( want_core == 1 )); then
        printf 'AUDIO_DEVICE=%s\n' "${AUDIO_DEVICE}"
        printf 'AUDIO_PASSTHROUGH_DEVICE=%s\n' "${AUDIO_PASSTHROUGH_DEVICE}"
      fi
      if (( want_room == 1 )); then
        printf 'ROOM_AUDIO_CHANNELS=%s\n' "${ROOM_AUDIO_CHANNELS}"
      fi
    } | ssh_keyed "sh -c '${script}'"
  )" || die "The audio probe failed. Nothing on the device has been changed apart from the administrator key."

  while IFS= read -r line; do
    case "${line}" in
      audio_device=*) AUDIO_DEVICE_VALUE="${line#audio_device=}" ;;
      audio_passthrough_device=*) AUDIO_PASSTHROUGH_DEVICE_VALUE="${line#audio_passthrough_device=}" ;;
      audio_channels=*) ROOM_AUDIO_CHANNELS_INDEX="${line#audio_channels=}" ;;
    esac
  done <<< "${output}"

  if (( want_core == 1 )); then
    [[ -n "${AUDIO_DEVICE_VALUE}" ]] \
      || die "The audio probe did not resolve an output device for ${AUDIO_DEVICE}"
    [[ -n "${AUDIO_PASSTHROUGH_DEVICE_VALUE}" ]] \
      || die "The audio probe did not resolve a passthrough device for ${AUDIO_PASSTHROUGH_DEVICE}"
    info "Resolved ${AUDIO_DEVICE} to ${AUDIO_DEVICE_VALUE}" >&2
    info "Resolved ${AUDIO_PASSTHROUGH_DEVICE} to ${AUDIO_PASSTHROUGH_DEVICE_VALUE}" >&2
  fi
  if (( want_room == 1 )); then
    case "${ROOM_AUDIO_CHANNELS_INDEX}" in
      ""|*[!0-9]*)
        die "The audio probe did not return a usable channel index for ${ROOM_AUDIO_CHANNELS}"
        ;;
    esac
    info "Resolved ${ROOM_AUDIO_CHANNELS} to Kodi channel index ${ROOM_AUDIO_CHANNELS_INDEX}" >&2
  fi
}
```

- [ ] **Step 5: Call the resolver**

Immediately after the existing `coreelec_resolve_room_display` call near `provision-coreelec.sh:5859`:

```bash
coreelec_resolve_audio_devices
```

- [ ] **Step 6: Carry the resolved values in the payload**

In the payload builder, before the existing `if coreelec_component_effective room; then` block:

```bash
  # The two device strings are AM6B+ hardware facts and belong to core; only
  # the channel layout is room state.
  if coreelec_component_effective core; then
    coreelec_settings_payload_entry AUDIO_DEVICE_VALUE "${AUDIO_DEVICE_VALUE}"
    coreelec_settings_payload_entry AUDIO_PASSTHROUGH_DEVICE_VALUE \
      "${AUDIO_PASSTHROUGH_DEVICE_VALUE}"
  fi
```

and inside the room block, beside `ROOM_DISPLAY_RESOLUTION_INDEX`:

```bash
    coreelec_settings_payload_entry ROOM_AUDIO_CHANNELS_INDEX \
      "${ROOM_AUDIO_CHANNELS_INDEX}"
```

- [ ] **Step 7: Write the settings in the transformer**

In the transformer's Python program, in the `if apply_core:` branch that already
sets the locale values, add:

```python
        audio_device = config("AUDIO_DEVICE_VALUE")
        if audio_device:
            kodi_values["audiooutput.audiodevice"] = audio_device
        audio_passthrough = config("AUDIO_PASSTHROUGH_DEVICE_VALUE")
        if audio_passthrough:
            kodi_values["audiooutput.passthroughdevice"] = audio_passthrough
```

and in the existing `if apply_room:` branch, after the `resolution_index` block:

```python
        # Kodi's channel setting is an opaque enum ordinal resolved by the
        # audio probe. With nothing resolved the layout is left exactly as it
        # was rather than pinned to a number that may mean another layout.
        channels_index = config("ROOM_AUDIO_CHANNELS_INDEX")
        if channels_index:
            kodi_values["audiooutput.channels"] = channels_index
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-settings.sh`
Expected: PASS, including every pre-existing test.

- [ ] **Step 9: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-settings.sh
git commit -m "feat: write the resolved audio output settings (Task 3)"
```

---

### Task 4: Observe, verify, and report the audio settings

**Files:**
- Modify: `provision-coreelec.sh` — `CORE_SETTING_IDS` and `ROOM_SETTING_IDS` in the verify probe (~:2345-2365); the core verification block (~:4375); the room verification block (~:4680); the verify fixture seam (~:5053)
- Test: `tests/test-coreelec-report.sh`

**Interfaces:**
- Consumes: `AUDIO_DEVICE_VALUE`, `AUDIO_PASSTHROUGH_DEVICE_VALUE`, `ROOM_AUDIO_CHANNELS_INDEX` (Task 3).
- Produces: observation keys `setting.audiooutput.audiodevice`, `setting.audiooutput.passthroughdevice`, `setting.audiooutput.channels`; report keys `audio.device.*`, `audio.passthroughdevice.*`, `room.audio.channels.*`, each with `expected` / `observed` / `status`. Fixture seam keys `resolved.audio.device`, `resolved.audio.passthroughdevice`, `resolved.audio.channels`.

Each of the three compares independently: one output left pointing at the wrong ALSA device must never be hidden behind another one being correct. Where nothing was resolved, the status is `unobservable` and counts as a failure — there is no honest value to compare an observation against, and guessing is what this whole design avoids.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test-coreelec-report.sh`:

```bash
# Seeds the three resolved.* lines the fixture seam reads, so tests can reach
# the ok and mismatch branches rather than only unobservable.
# Full `if` blocks, not `[[ ... ]] && printf`: these files run under
# `set -Eeuo pipefail`, where a false condition would abort the suite.
write_resolved_audio() {
  local file="$1" device="$2" passthrough="$3" channels="$4"
  if [[ -n "${device}" ]]; then
    printf 'resolved.audio.device=%s\n' "${device}" >> "${file}"
  fi
  if [[ -n "${passthrough}" ]]; then
    printf 'resolved.audio.passthroughdevice=%s\n' "${passthrough}" >> "${file}"
  fi
  if [[ -n "${channels}" ]]; then
    printf 'resolved.audio.channels=%s\n' "${channels}" >> "${file}"
  fi
}

test_audio_verification_passes_when_the_device_matches() {
  local dir observations request output device
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  observations="${dir}/observations"
  request="${dir}/request"
  device="ALSA:surround71:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND"
  write_room_observations "${observations}"
  printf 'setting.audiooutput.audiodevice=%s\n' "${device}" >> "${observations}"
  printf 'setting.audiooutput.channels=10\n' >> "${observations}"
  write_resolved_audio "${observations}" "${device}" "" "10"
  printf 'components=core,room\n' > "${request}"
  output="$(run_room_verification "${observations}" "${request}" 2>&1 || true)"
  assert_contains "${output}" "audio.device.status=ok" \
    "a matching output device passes" || return 1
  assert_contains "${output}" "room.audio.channels.status=ok" \
    "a matching channel layout passes" || return 1
}

test_audio_verification_reports_a_changed_device() {
  local dir observations request output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  observations="${dir}/observations"
  request="${dir}/request"
  write_room_observations "${observations}"
  # The device drifted to the S/PDIF output: passthrough would silently stop
  # carrying TrueHD, which is the exact failure this work exists to catch.
  printf 'setting.audiooutput.audiodevice=ALSA:iec958:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND\n' \
    >> "${observations}"
  write_resolved_audio "${observations}" \
    "ALSA:surround71:CARD=AMLAUGESOUND,DEV=0|AML-AUGESOUND" "" ""
  printf 'components=core\n' > "${request}"
  output="$(run_room_verification "${observations}" "${request}" 2>&1 || true)"
  assert_contains "${output}" "audio.device.status=mismatch" \
    "a drifted output device is reported" || return 1
  assert_contains "${output}" "verification_result=fail" \
    "a drifted output device fails the run" || return 1
}

test_audio_verification_is_unobservable_without_a_resolved_value() {
  local dir observations request output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  observations="${dir}/observations"
  request="${dir}/request"
  write_room_observations "${observations}"
  printf 'setting.audiooutput.audiodevice=ALSA:hdmi:CARD=X,DEV=0|X\n' >> "${observations}"
  printf 'components=core\n' > "${request}"
  output="$(run_room_verification "${observations}" "${request}" 2>&1 || true)"
  assert_contains "${output}" "audio.device.status=unobservable" \
    "an unresolved device cannot be honestly compared" || return 1
  assert_contains "${output}" "verification_result=fail" \
    "unobservable fails closed" || return 1
}

test_audio_channels_are_not_verified_outside_the_room_scope() {
  local dir observations request output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  observations="${dir}/observations"
  request="${dir}/request"
  write_room_observations "${observations}"
  printf 'setting.audiooutput.audiodevice=ALSA:hdmi:CARD=X,DEV=0|X\n' >> "${observations}"
  write_resolved_audio "${observations}" "ALSA:hdmi:CARD=X,DEV=0|X" "" "10"
  printf 'components=core\n' > "${request}"
  output="$(run_room_verification "${observations}" "${request}" 2>&1 || true)"
  assert_not_contains "${output}" "room.audio.channels" \
    "a core-only run reports no room channel state" || return 1
}

test_verify_probe_observes_the_audio_settings() {
  local output
  output="$(run_verify_probe_with_components "core,room")"
  assert_contains "${output}" "setting.audiooutput.audiodevice=" \
    "core observes the output device" || return 1
  assert_contains "${output}" "setting.audiooutput.passthroughdevice=" \
    "core observes the passthrough device" || return 1
  assert_contains "${output}" "setting.audiooutput.channels=" \
    "room observes the channel layout" || return 1
}
```

Register all five in the trailing `run_all_tests` list.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-report.sh`
Expected: FAIL — no `audio.device.*` keys are emitted and the probe observes none of the three settings.

- [ ] **Step 3: Observe the settings**

In the verify probe source, extend the two ID lists:

```python
CORE_SETTING_IDS = [
    "locale.language",
    "locale.country",
    "locale.keyboardlayouts",
    "locale.timezonecountry",
    "locale.timezone",
    "audiooutput.audiodevice",
    "audiooutput.passthroughdevice",
]
```

and append to `ROOM_SETTING_IDS`:

```python
    "audiooutput.channels",
```

- [ ] **Step 4: Compare the core device strings**

In the core verification block (~`provision-coreelec.sh:4375`), after the existing locale comparisons:

```bash
    # Each output is its own independent pass/fail: one output left pointing
    # at the wrong ALSA device must never be hidden behind the other being
    # correct. Without a resolved value there is nothing correct to compare
    # the observation to, so it is reported unobservable rather than guessed.
    if [[ -n "${AUDIO_DEVICE_VALUE}" ]]; then
      coreelec_room_compare_setting "audio.device" \
        "${AUDIO_DEVICE_VALUE}" "setting.audiooutput.audiodevice" \
        "${observations}" \
        || failures=$((failures + 1))
    else
      printf 'audio.device.expected=%s\n' "${AUDIO_DEVICE}"
      printf 'audio.device.observed=%s\n' \
        "$(coreelec_observation_value setting.audiooutput.audiodevice "${observations}" || true)"
      printf 'audio.device.status=unobservable\n'
      failures=$((failures + 1))
    fi
    if [[ -n "${AUDIO_PASSTHROUGH_DEVICE_VALUE}" ]]; then
      coreelec_room_compare_setting "audio.passthroughdevice" \
        "${AUDIO_PASSTHROUGH_DEVICE_VALUE}" \
        "setting.audiooutput.passthroughdevice" "${observations}" \
        || failures=$((failures + 1))
    else
      printf 'audio.passthroughdevice.expected=%s\n' "${AUDIO_PASSTHROUGH_DEVICE}"
      printf 'audio.passthroughdevice.observed=%s\n' \
        "$(coreelec_observation_value setting.audiooutput.passthroughdevice "${observations}" || true)"
      printf 'audio.passthroughdevice.status=unobservable\n'
      failures=$((failures + 1))
    fi
```

`coreelec_room_compare_setting` is named for where it was first used, not for a room-only restriction; it is the generic expected/observed/status comparator and is the right helper here.

- [ ] **Step 5: Compare the room channel layout**

In the room verification block, after the six passthrough comparisons:

```bash
    if [[ -n "${ROOM_AUDIO_CHANNELS_INDEX}" ]]; then
      coreelec_room_compare_setting "room.audio.channels" \
        "${ROOM_AUDIO_CHANNELS_INDEX}" "setting.audiooutput.channels" \
        "${observations}" \
        || failures=$((failures + 1))
    else
      printf 'room.audio.channels.expected=%s\n' "${ROOM_AUDIO_CHANNELS}"
      printf 'room.audio.channels.observed=%s\n' \
        "$(coreelec_observation_value setting.audiooutput.channels "${observations}" || true)"
      printf 'room.audio.channels.status=unobservable\n'
      failures=$((failures + 1))
    fi
```

- [ ] **Step 6: Extend the verify fixture seam**

In the `VERIFY_FIXTURE` block near `provision-coreelec.sh:5053`, beside the existing `ROOM_DISPLAY_RESOLUTION_INDEX` assignment:

```bash
  AUDIO_DEVICE_VALUE="$(
    coreelec_observation_value resolved.audio.device \
      "${VERIFY_FIXTURE[0]}" || printf ''
  )"
  AUDIO_PASSTHROUGH_DEVICE_VALUE="$(
    coreelec_observation_value resolved.audio.passthroughdevice \
      "${VERIFY_FIXTURE[0]}" || printf ''
  )"
  ROOM_AUDIO_CHANNELS_INDEX="$(
    coreelec_observation_value resolved.audio.channels \
      "${VERIFY_FIXTURE[0]}" || printf ''
  )"
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-report.sh`
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `ls tests/*.sh | grep -v test-helper | while read f; do bash "$f"; done`
Expected: every file reports all tests passing. Adding IDs to `CORE_SETTING_IDS` changes what a core-scoped run observes, so pre-existing report tests are the ones most likely to need updating; update assertions only where the new observation keys are genuinely expected.

- [ ] **Step 9: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-report.sh
git commit -m "feat: verify and report the audio output settings (Task 4)"
```

---

### Task 5: Documentation

**Files:**
- Create: `docs/devices/ugoos-am6b-plus/audio-output.md`
- Modify: `docs/devices/ugoos-am6b-plus/room-desired-state.md` — cross-reference the channel layout key
- Modify: `config/README.md` — document the three new keys

**Interfaces:**
- Consumes: the finished behaviour from Tasks 1-4.
- Produces: operator documentation. Nothing depends on this task.

- [ ] **Step 1: Write the operator document**

Create `docs/devices/ugoos-am6b-plus/audio-output.md` covering:

- **What is managed:** `audiooutput.audiodevice` and `audiooutput.passthroughdevice` (component `core`), `audiooutput.channels` (component `room`).
- **Why intent rather than the concrete string:** the concrete values embed the kernel card name (`AMLAUGESOUND`), and the channel setting is an opaque Kodi enum ordinal. Both are resolved per run against the enumeration the running Kodi reports. Include the display-resolution precedent: that index was observed moving from 41 to 40 between two runs minutes apart on unchanged hardware.
- **The intent vocabulary:** reproduce the Vocabulary table from this plan.
- **Why a missing output is a failure, not a fallback:** the value of managing these is detecting drift. Silently selecting a different output would be indistinguishable from not noticing.
- **Which settings are room state and which are baseline:** the device strings are AM6B+ hardware facts identical in every room; the channel layout depends on the room's AVR. Note that `audiooutput.channels` governs only audio Kodi decodes itself — bitstreamed formats are unaffected by it.
- **Troubleshooting:** what `audio.device.status=mismatch` and `status=unobservable` mean, and that the probe's failure message lists the outputs Kodi actually offers.

- [ ] **Step 2: Cross-reference from the room document**

In `docs/devices/ugoos-am6b-plus/room-desired-state.md`, in the audio section, add `ROOM_AUDIO_CHANNELS` to the key list and link to `audio-output.md` for the resolution mechanism.

- [ ] **Step 3: Document the configuration keys**

In `config/README.md`, document `AUDIO_DEVICE` and `AUDIO_PASSTHROUGH_DEVICE` as shared keys and `ROOM_AUDIO_CHANNELS` as a room key, each with its accepted vocabulary.

- [ ] **Step 4: Commit**

```bash
git add docs/ config/README.md
git commit -m "docs: describe managed audio output (Task 5)"
```

---

## Live verification (after Task 5, before merge)

Fixtures cannot catch a wrong JSON-RPC category, a value Kodi renders differently than expected, or an option list that differs from the captured one. #7 shipped 515 passing tests and still failed its first live run on exactly that class of bug. Run against `ugoos-theater`:

1. `--print-component-plan` with `--component core --component room --room theater`, confirming the effective set.
2. A full run. Expect the resolver to log all three resolutions before the transaction opens, `verification_failures=0`, and `audio.device.status=ok`, `audio.passthroughdevice.status=ok`, `room.audio.channels.status=ok`.
3. Confirm on the device that `audiooutput.channels` moved from `1` to `10` and lost its `default="true"` attribute, and that passthrough still works by playing a TrueHD title.

Report the results on #17 before merging.
