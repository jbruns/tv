# Add-on Onboarding and Restart Sequencing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the CoreELEC add-on configuration report distinguish artifact/configuration success from authentication and synchronization completion, using only signals observed on the live device.

**Architecture:** Add small, single-purpose predicate functions to `lib/coreelec-addon-workflows.sh` that read add-on state from the device and emit fixed enumerated tokens. Each predicate's remote program is produced by its own `*_program` function so tests can execute it locally against a fixture `HOME` with no network and no SSH. `run_addon_workflow` composes those predicates into two orthogonal status values, and `configure-coreelec-addons.sh` emits both under a bumped report format.

**Tech Stack:** Bash 3.2 (macOS-compatible, no namerefs, no associative arrays), POSIX `sh` and Python 3 on the CoreELEC device, `sqlite3` from the Python standard library, the repository's own `tests/test-helper.sh` harness.

**Spec:** `docs/superpowers/specs/2026-09-16-addon-onboarding-restart-sequencing-design.md`

## Global Constraints

- Target shell is **Bash 3.2**. No `declare -A`, no `local -n`, no `${var,,}`.
- Device-side code is **POSIX `sh` plus Python 3**. BusyBox userland: `grep` has no `--include`, and `base64` does not exist.
- Every new predicate is **fail-closed**: unreadable, ambiguous, or malformed state never yields a success token.
- Every new report field emits **booleans, counts, or fixed enumerated tokens only**. No raw add-on settings value may reach a report — `PlexServerManager.servers[].connections[].token` holds live Plex tokens that `report_redaction_check` does not scan for.
- `config_status` values: `configured | already-configured | skipped | failed | dry-run`.
- `onboarding_status` values: `not-required | complete | pending-authentication | pending-sync | manual-required | unobservable | failed | dry-run`.
- Report format banner becomes exactly `coreelec-addon-configuration-report-2`.
- New tests must be added to the trailing backslash-continued `run_all_tests` list at the end of the test file or **they will not run**.
- Run the suite with `bash tests/test-coreelec-addon-workflows.sh`. Run everything with `ls tests/*.sh | grep -v test-helper | while read f; do bash "$f"; done`.

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `lib/coreelec-addon-workflows.sh` | Predicates and workflow composition | Modify |
| `configure-coreelec-addons.sh` | Report emission and format banner | Modify |
| `tests/test-coreelec-addon-workflows.sh` | Test coverage | Modify |
| `docs/devices/ugoos-am6b-plus/addon-onboarding-contract.md` | The contract itself | Create |
| `docs/operations/provision-ugoos.md` | Operator runbook | Modify |

---

### Task 1: Emby account-state predicate

Reads `servers_*.json` on the device and reports whether the Emby client holds a complete credential set. Local file state only — no network, so the report never fails because a media server is briefly down.

**Files:**
- Modify: `lib/coreelec-addon-workflows.sh` (insert after `coreelec_postdeploy_emby_state`, which ends at line 604)
- Test: `tests/test-coreelec-addon-workflows.sh`

**Interfaces:**
- Consumes: `coreelec_ssh_command` from `lib/coreelec-ssh.sh`.
- Produces:
  - `coreelec_postdeploy_emby_account_program()` — prints the remote program text to stdout. Takes no arguments. Reads nothing from stdin.
  - `coreelec_postdeploy_emby_account_state()` — runs that program on the device, prints exactly one of `absent`, `ambiguous`, `invalid`, `incomplete`, `present`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test-coreelec-addon-workflows.sh`, immediately before the `run_all_tests` call:

```bash
make_emby_account_fixture() {
  local home_dir="$1" content="$2" filename="${3:-servers_fe02bd703bb043ba92bf60a497794db5.json}"
  mkdir -p "${home_dir}/.kodi/userdata/addon_data/plugin.service.emby-next-gen"
  if [[ -n "${content}" ]]; then
    printf '%s' "${content}" \
      > "${home_dir}/.kodi/userdata/addon_data/plugin.service.emby-next-gen/${filename}"
  fi
}

run_emby_account_program() {
  local home_dir="$1"
  HOME="${home_dir}" bash -c "$(coreelec_postdeploy_emby_account_program)"
}

test_emby_account_state_reports_each_credential_condition() {
  local dir complete
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  complete='{"ServerId":"fe02bd703bb043ba92bf60a497794db5","AccessToken":"emby-access-token-secret","UserId":"1f2e3d4c5b6a7988796a5b4c3d2e1f00"}'

  mkdir -p "${dir}/absent"
  assert_eq "absent" "$(run_emby_account_program "${dir}/absent")" \
    "a missing servers file is absent" || return 1

  make_emby_account_fixture "${dir}/present" "${complete}"
  assert_eq "present" "$(run_emby_account_program "${dir}/present")" \
    "a complete credential set is present" || return 1

  make_emby_account_fixture "${dir}/invalid" 'not json at all'
  assert_eq "invalid" "$(run_emby_account_program "${dir}/invalid")" \
    "unparseable credentials fail closed" || return 1

  make_emby_account_fixture "${dir}/incomplete" '{"ServerId":"fe02bd703bb043ba92bf60a497794db5","AccessToken":"","UserId":"1f2e3d4c5b6a7988796a5b4c3d2e1f00"}'
  assert_eq "incomplete" "$(run_emby_account_program "${dir}/incomplete")" \
    "an empty access token is incomplete" || return 1

  make_emby_account_fixture "${dir}/ambiguous" "${complete}"
  make_emby_account_fixture "${dir}/ambiguous" "${complete}" "servers_aaaabbbbccccddddeeeeffff00001111.json"
  assert_eq "ambiguous" "$(run_emby_account_program "${dir}/ambiguous")" \
    "two servers files fail closed" || return 1

  make_emby_account_fixture "${dir}/mismatch" "${complete}" "servers_0000000000000000000000000000ffff.json"
  assert_eq "invalid" "$(run_emby_account_program "${dir}/mismatch")" \
    "a filename that disagrees with ServerId fails closed" || return 1

  assert_not_contains "$(run_emby_account_program "${dir}/present")" "emby-access-token-secret" \
    "the access token is never printed" || return 1
}
```

Register it by appending to the `run_all_tests` list:

```bash
  test_emby_account_state_reports_each_credential_condition \
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test-coreelec-addon-workflows.sh 2>&1 | tail -20`
Expected: FAIL with `coreelec_postdeploy_emby_account_program: command not found`.

- [ ] **Step 3: Write minimal implementation**

Insert into `lib/coreelec-addon-workflows.sh` after `coreelec_postdeploy_emby_state` ends (after its closing `}` on line 604):

```bash
coreelec_postdeploy_emby_account_program() {
  cat <<'EOF'
set -eu
python3 - <<'PYEOF'
import glob
import json
import os
import sys

paths = sorted(glob.glob(os.path.expanduser(
    "~/.kodi/userdata/addon_data/plugin.service.emby-next-gen/servers_*.json")))
if not paths:
    sys.stdout.write("absent\n")
    raise SystemExit(0)
if len(paths) != 1:
    sys.stdout.write("ambiguous\n")
    raise SystemExit(0)

try:
    with open(paths[0], "r", encoding="utf-8") as handle:
        server = json.load(handle)
except Exception:
    sys.stdout.write("invalid\n")
    raise SystemExit(0)

if not isinstance(server, dict):
    sys.stdout.write("invalid\n")
    raise SystemExit(0)

server_id = server.get("ServerId")
token = server.get("AccessToken")
user_id = server.get("UserId")
if not all(isinstance(value, str) and value.strip()
           for value in (server_id, token, user_id)):
    sys.stdout.write("incomplete\n")
    raise SystemExit(0)

if os.path.basename(paths[0]) != "servers_%s.json" % server_id:
    sys.stdout.write("invalid\n")
    raise SystemExit(0)

sys.stdout.write("present\n")
PYEOF
EOF
}

coreelec_postdeploy_emby_account_state() {
  coreelec_ssh_command "$(coreelec_postdeploy_emby_account_program)"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test-coreelec-addon-workflows.sh 2>&1 | tail -5`
Expected: PASS, with the total test count increased by one.

- [ ] **Step 5: Commit**

```bash
git add lib/coreelec-addon-workflows.sh tests/test-coreelec-addon-workflows.sh
git commit -m "feat: add a network-free Emby account state predicate

Reads servers_*.json on the device and reports absent, ambiguous, invalid,
incomplete, or present. The remote program is emitted by its own function so
the test suite can run it locally against a fixture HOME.

Refs #6

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Emby sync-state predicate

Distinguishes "the Emby database exists" from "the library sync finished", which is the core correction of this workstream.

**Files:**
- Modify: `lib/coreelec-addon-workflows.sh` (insert after the Task 1 functions)
- Test: `tests/test-coreelec-addon-workflows.sh`

**Interfaces:**
- Consumes: `coreelec_ssh_command`.
- Produces:
  - `coreelec_postdeploy_emby_sync_program()` — prints the remote program text.
  - `coreelec_postdeploy_emby_sync_state()` — prints one line: `<state> <synced> <attempted>`, where `<state>` is one of `database-absent`, `sync-pending`, `synced`, `unreadable`, and the two integers are `LibrarySynced` and `LibrarySyncedMirrow` row counts (`0 0` when unknown).

Rationale, from the device: `plugin.service.emby-next-gen/database/library.py` writes `LibrarySyncedMirrow` before the per-library content loop and `LibrarySynced` only after it completes, while `emby_<ServerId>.db` is created at handshake.

- [ ] **Step 1: Write the failing test**

Add before the `run_all_tests` call:

```bash
make_emby_sync_fixture() {
  local home_dir="$1" synced="$2" attempted="$3"
  mkdir -p "${home_dir}/.kodi/userdata/Database"
  EMBY_FIXTURE_DB="${home_dir}/.kodi/userdata/Database/emby_fe02bd703bb043ba92bf60a497794db5.db" \
  EMBY_FIXTURE_SYNCED="${synced}" \
  EMBY_FIXTURE_ATTEMPTED="${attempted}" \
  python3 - <<'PYEOF'
import os
import sqlite3

connection = sqlite3.connect(os.environ["EMBY_FIXTURE_DB"])
for table in ("LibrarySynced", "LibrarySyncedMirrow"):
    connection.execute(
        "CREATE TABLE %s (EmbyLibraryId TEXT, EmbyLibraryName TEXT, "
        "EmbyType TEXT, KodiDBs TEXT)" % table)
for index in range(int(os.environ["EMBY_FIXTURE_SYNCED"])):
    connection.execute("INSERT INTO LibrarySynced VALUES (?,?,?,?)",
                       (str(index), "Movies", "Movie", "video"))
for index in range(int(os.environ["EMBY_FIXTURE_ATTEMPTED"])):
    connection.execute("INSERT INTO LibrarySyncedMirrow VALUES (?,?,?,?)",
                       (str(index), "Movies", "Movie", "video"))
connection.commit()
connection.close()
PYEOF
}

run_emby_sync_program() {
  local home_dir="$1"
  HOME="${home_dir}" bash -c "$(coreelec_postdeploy_emby_sync_program)"
}

test_emby_sync_state_separates_handshake_from_completed_sync() {
  local dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN

  mkdir -p "${dir}/nodb/.kodi/userdata/Database"
  assert_eq "database-absent 0 0" "$(run_emby_sync_program "${dir}/nodb")" \
    "no database means the handshake has not happened" || return 1

  make_emby_sync_fixture "${dir}/fresh" 0 0
  assert_eq "sync-pending 0 0" "$(run_emby_sync_program "${dir}/fresh")" \
    "an empty database is the false-success window and must stay pending" || return 1

  make_emby_sync_fixture "${dir}/partial" 9 16
  assert_eq "sync-pending 9 16" "$(run_emby_sync_program "${dir}/partial")" \
    "an interrupted sync stays pending" || return 1

  make_emby_sync_fixture "${dir}/started" 0 16
  assert_eq "sync-pending 0 16" "$(run_emby_sync_program "${dir}/started")" \
    "an attempted but unfinished sync stays pending" || return 1

  make_emby_sync_fixture "${dir}/done" 16 16
  assert_eq "synced 16 16" "$(run_emby_sync_program "${dir}/done")" \
    "equal non-empty counts mean the sync finished" || return 1

  mkdir -p "${dir}/corrupt/.kodi/userdata/Database"
  printf 'this is not a database' \
    > "${dir}/corrupt/.kodi/userdata/Database/emby_fe02bd703bb043ba92bf60a497794db5.db"
  assert_eq "unreadable 0 0" "$(run_emby_sync_program "${dir}/corrupt")" \
    "a corrupt database fails closed" || return 1

  make_emby_sync_fixture "${dir}/two" 16 16
  cp "${dir}/two/.kodi/userdata/Database/emby_fe02bd703bb043ba92bf60a497794db5.db" \
     "${dir}/two/.kodi/userdata/Database/emby_0000000000000000000000000000ffff.db"
  assert_eq "unreadable 0 0" "$(run_emby_sync_program "${dir}/two")" \
    "two Emby databases fail closed" || return 1
}
```

Register it:

```bash
  test_emby_sync_state_separates_handshake_from_completed_sync \
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test-coreelec-addon-workflows.sh 2>&1 | tail -20`
Expected: FAIL with `coreelec_postdeploy_emby_sync_program: command not found`.

- [ ] **Step 3: Write minimal implementation**

Append to `lib/coreelec-addon-workflows.sh` after the Task 1 functions:

```bash
coreelec_postdeploy_emby_sync_program() {
  cat <<'EOF'
set -eu
python3 - <<'PYEOF'
import glob
import os
import sqlite3
import sys

paths = sorted(glob.glob(os.path.expanduser(
    "~/.kodi/userdata/Database/emby_*.db")))
if not paths:
    sys.stdout.write("database-absent 0 0\n")
    raise SystemExit(0)
if len(paths) != 1:
    sys.stdout.write("unreadable 0 0\n")
    raise SystemExit(0)

try:
    connection = sqlite3.connect("file:%s?mode=ro" % paths[0], uri=True)
    synced = connection.execute(
        "SELECT COUNT(*) FROM LibrarySynced").fetchone()[0]
    attempted = connection.execute(
        "SELECT COUNT(*) FROM LibrarySyncedMirrow").fetchone()[0]
    connection.close()
except Exception:
    sys.stdout.write("unreadable 0 0\n")
    raise SystemExit(0)

# LibrarySyncedMirrow is written before each library's content loop and
# LibrarySynced only after it completes, so equal non-empty counts are the
# only proof that every attempted library finished.
if synced and synced == attempted:
    sys.stdout.write("synced %d %d\n" % (synced, attempted))
else:
    sys.stdout.write("sync-pending %d %d\n" % (synced, attempted))
PYEOF
EOF
}

coreelec_postdeploy_emby_sync_state() {
  coreelec_ssh_command "$(coreelec_postdeploy_emby_sync_program)"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test-coreelec-addon-workflows.sh 2>&1 | tail -5`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/coreelec-addon-workflows.sh tests/test-coreelec-addon-workflows.sh
git commit -m "feat: distinguish an Emby handshake from a completed library sync

LibrarySyncedMirrow is written before each library's content loop and
LibrarySynced only after it completes, while emby_<ServerId>.db is created at
handshake. Equal non-empty counts are therefore the only proof that the sync
finished; everything else stays pending.

Refs #6

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: PM4K server-binding predicate

An authenticated Plex account with no selected server leaves PM4K unusable at the TV. The existing token check cannot see that.

**Files:**
- Modify: `lib/coreelec-addon-workflows.sh` (insert after `coreelec_postdeploy_pm4k_account_token_present`, which ends at line 391)
- Test: `tests/test-coreelec-addon-workflows.sh`

**Interfaces:**
- Consumes: `coreelec_postdeploy_read_addon_data_file "script.plexmod" "settings.xml"`.
- Produces: `coreelec_postdeploy_pm4k_server_bound()` — prints `1` when a server is bound, `0` when not, and returns non-zero exit status when the settings are unparseable.

Observed shape on the device: `myplex.MyPlexAccount` is JSON with an `ID` field; `lastServerId.<ID>` holds the selected server UUID; `None.PlexServerManager` is JSON of the form `{"servers": [{"uuid": "...", ...}]}`.

- [ ] **Step 1: Write the failing test**

Add before the `run_all_tests` call:

```bash
pm4k_settings_xml() {
  local account_id="$1" last_server="$2" server_uuid="$3"
  printf '<settings>'
  printf '<setting id="myplex.MyPlexAccount">{"ID":"%s","authToken":"pm4k-account-token-secret"}</setting>' "${account_id}"
  if [[ -n "${last_server}" ]]; then
    printf '<setting id="lastServerId.%s">%s</setting>' "${account_id}" "${last_server}"
  fi
  printf '<setting id="None.PlexServerManager">{"servers":[{"name":"aMMc","uuid":"%s","connections":[{"token":"plex-connection-token-secret"}]}]}</setting>' "${server_uuid}"
  printf '</settings>'
}

run_pm4k_server_bound() {
  local dir="$1" settings="$2" bin_dir
  bin_dir="$(install_ssh_stub "${dir}")"
  printf '%s' "${settings}" > "${dir}/stub/response-default.json"
  (
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    coreelec_postdeploy_pm4k_server_bound
  )
}

test_pm4k_server_binding_is_checked_separately_from_the_account_token() {
  local dir bound
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN

  mkdir -p "${dir}/bound"
  bound="$(run_pm4k_server_bound "${dir}/bound" \
    "$(pm4k_settings_xml 650797 5f5119b42542da76aba1994246e691f6d26bf7e3 5f5119b42542da76aba1994246e691f6d26bf7e3)")"
  assert_eq "1" "${bound}" "a selected server present in the server list is bound" || return 1

  mkdir -p "${dir}/unselected"
  bound="$(run_pm4k_server_bound "${dir}/unselected" \
    "$(pm4k_settings_xml 650797 "" 5f5119b42542da76aba1994246e691f6d26bf7e3)")"
  assert_eq "0" "${bound}" "an authenticated account with no selected server is not bound" || return 1

  mkdir -p "${dir}/stale"
  bound="$(run_pm4k_server_bound "${dir}/stale" \
    "$(pm4k_settings_xml 650797 0000000000000000000000000000000000000000 5f5119b42542da76aba1994246e691f6d26bf7e3)")"
  assert_eq "0" "${bound}" "a selected server absent from the server list is not bound" || return 1

  mkdir -p "${dir}/empty"
  bound="$(run_pm4k_server_bound "${dir}/empty" '<settings></settings>')"
  assert_eq "0" "${bound}" "no account state means no binding" || return 1
}

test_pm4k_server_binding_never_emits_plex_secrets() {
  local dir emitted
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN

  mkdir -p "${dir}/bound"
  emitted="$(run_pm4k_server_bound "${dir}/bound" \
    "$(pm4k_settings_xml 650797 5f5119b42542da76aba1994246e691f6d26bf7e3 5f5119b42542da76aba1994246e691f6d26bf7e3)" 2>&1)"

  assert_not_contains "${emitted}" "plex-connection-token-secret" \
    "Plex connection tokens must never be emitted on any stream" || return 1
  assert_not_contains "${emitted}" "pm4k-account-token-secret" \
    "the Plex account token must never be emitted on any stream" || return 1
  assert_not_contains "${emitted}" "5f5119b42542da76aba1994246e691f6d26bf7e3" \
    "server UUIDs are internal state and must not be emitted" || return 1
}
```

Register both:

```bash
  test_pm4k_server_binding_is_checked_separately_from_the_account_token \
  test_pm4k_server_binding_never_emits_plex_secrets \
```

These two tests are the fail-closed guard the spec's Security Constraint
requires: because `coreelec_postdeploy_pm4k_server_bound` is the only path by
which `script.plexmod` settings reach the caller, proving it emits nothing but
`1` or `0` proves no Plex secret can reach a report.

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test-coreelec-addon-workflows.sh 2>&1 | tail -20`
Expected: FAIL with `coreelec_postdeploy_pm4k_server_bound: command not found`.

- [ ] **Step 3: Write minimal implementation**

Insert into `lib/coreelec-addon-workflows.sh` directly after `coreelec_postdeploy_pm4k_account_token_present` closes (line 391):

```bash
coreelec_postdeploy_pm4k_server_bound() {
  local settings_xml
  settings_xml="$(coreelec_postdeploy_read_addon_data_file "script.plexmod" "settings.xml")" || return 1
  SETTINGS_XML="${settings_xml}" python3 - <<'PYEOF'
import json
import os
import sys
import xml.etree.ElementTree as ET

text = os.environ.get("SETTINGS_XML", "")
if not text.strip():
    sys.stdout.write("0")
    raise SystemExit(0)

try:
    root = ET.fromstring(text)
except Exception:
    raise SystemExit(1)

settings = {}
for node in root.findall(".//setting"):
    settings[node.attrib.get("id", "")] = (node.text or "").strip()

account_state = settings.get("myplex.MyPlexAccount", "").strip()
if not account_state:
    sys.stdout.write("0")
    raise SystemExit(0)

try:
    account_id = (json.loads(account_state).get("ID") or "")
except Exception:
    raise SystemExit(1)
account_id = str(account_id).strip()
if not account_id:
    sys.stdout.write("0")
    raise SystemExit(0)

selected = settings.get("lastServerId.%s" % account_id, "").strip()
if not selected:
    sys.stdout.write("0")
    raise SystemExit(0)

manager_state = settings.get("None.PlexServerManager", "").strip()
if not manager_state:
    sys.stdout.write("0")
    raise SystemExit(0)

try:
    servers = json.loads(manager_state).get("servers") or []
except Exception:
    raise SystemExit(1)

known = set()
for server in servers:
    if isinstance(server, dict):
        uuid = server.get("uuid")
        if isinstance(uuid, str) and uuid.strip():
            known.add(uuid.strip())

sys.stdout.write("1" if selected in known else "0")
PYEOF
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test-coreelec-addon-workflows.sh 2>&1 | tail -5`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/coreelec-addon-workflows.sh tests/test-coreelec-addon-workflows.sh
git commit -m "feat: check that PM4K has a bound Plex server, not just a token

An authenticated account with no selected server leaves the add-on unusable at
the TV, which the existing token check cannot see. The predicate emits only 1
or 0 so that Plex connection tokens, which report redaction does not scan for,
can never reach a report.

Refs #6

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Retire the misleading `configured` rung in the legacy Emby ladder

`coreelec_postdeploy_emby_state` returns `configured` on mere database existence. It has no production caller, so this is a latent trap rather than an active bug. Rename the rung so it cannot be mistaken for onboarding success by whoever wires it up next.

**Files:**
- Modify: `lib/coreelec-addon-workflows.sh:600-603`
- Test: `tests/test-coreelec-addon-workflows.sh`

**Interfaces:**
- Produces: `coreelec_postdeploy_emby_state` now emits `handshake-complete` where it previously emitted `configured`. All other rungs are unchanged: `absent`, `ambiguous`, `invalid`, `incomplete`, `identity-mismatch`, `certificate-error`, `server-unavailable`, `handshake-pending`.

- [ ] **Step 1: Find every existing reference**

Run:

```bash
grep -rn 'emby_state\|handshake-pending' lib/ tests/ configure-coreelec-addons.sh
```

Record each hit. Expect matches in `lib/coreelec-addon-workflows.sh` inside `assist_emby_login` (around lines 639 and 682) and in the Emby assistant tests.

- [ ] **Step 2: Write the failing test**

Add before the `run_all_tests` call:

```bash
test_legacy_emby_ladder_never_reports_configured_on_database_existence() {
  local program
  program="$(declare -f coreelec_postdeploy_emby_state)"

  assert_not_contains "${program}" 'sys.stdout.write("configured\n")' \
    "database existence must not be reported as configured" || return 1
  assert_contains "${program}" 'sys.stdout.write("handshake-complete\n")' \
    "database existence is a completed handshake, not onboarding success" || return 1
}
```

Register it:

```bash
  test_legacy_emby_ladder_never_reports_configured_on_database_existence \
```

- [ ] **Step 3: Run test to verify it fails**

Run: `bash tests/test-coreelec-addon-workflows.sh 2>&1 | tail -20`
Expected: FAIL on "database existence must not be reported as configured".

- [ ] **Step 4: Write minimal implementation**

In `lib/coreelec-addon-workflows.sh`, change the final lines of the `coreelec_postdeploy_emby_state` Python block from:

```python
if not os.path.isfile(database):
    sys.stdout.write("handshake-pending\n")
    raise SystemExit(0)
sys.stdout.write("configured\n")
```

to:

```python
if not os.path.isfile(database):
    sys.stdout.write("handshake-pending\n")
    raise SystemExit(0)
# The database is created at handshake, before any library content is
# synchronized. Completion is decided by coreelec_postdeploy_emby_sync_state.
sys.stdout.write("handshake-complete\n")
```

Then update each reference found in Step 1. In `assist_emby_login`, any comparison against `configured` becomes `handshake-complete`.

- [ ] **Step 5: Run the full suite**

Run: `bash tests/test-coreelec-addon-workflows.sh 2>&1 | tail -5`
Expected: PASS. If an Emby assistant test fails on the old `configured` string, update that expectation to `handshake-complete`.

- [ ] **Step 6: Commit**

```bash
git add lib/coreelec-addon-workflows.sh tests/test-coreelec-addon-workflows.sh
git commit -m "fix: stop calling Emby database existence 'configured'

The ladder returned configured as soon as emby_<ServerId>.db existed, which is
created at handshake and proves nothing about library content. The rung becomes
handshake-complete so that wiring the ladder up cannot silently reintroduce a
false success.

Refs #6

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Two-axis `run_addon_workflow`

**Files:**
- Modify: `lib/coreelec-addon-workflows.sh:1302-1332` (`run_addon_workflow`)
- Modify: `tests/test-coreelec-addon-workflows.sh:573-581`, `:1421`, `:1446`
- Test: `tests/test-coreelec-addon-workflows.sh`

**Interfaces:**
- Consumes: `check_home_assistant_weather`, `check_nextpvr`, `authorize_pm4k_account`, `coreelec_postdeploy_weather_ready`, `coreelec_postdeploy_nextpvr_ready` (all unchanged, all still printing a single token); plus `coreelec_postdeploy_emby_account_state`, `coreelec_postdeploy_emby_sync_state`, `coreelec_postdeploy_pm4k_server_bound` from Tasks 1–3.
- Produces: `run_addon_workflow <addon-id>` prints exactly one line: `<config_status> <onboarding_status>`, space separated. Callers split with `read -r config_status onboarding_status`.

This is a breaking contract change; Step 1 updates the three existing call sites that assert a single token.

- [ ] **Step 1: Write the failing test**

Add before the `run_all_tests` call:

```bash
test_workflow_reports_configuration_and_onboarding_on_separate_axes() {
  local dir bin_dir output

  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    INTERACTIVE="0"
    coreelec_postdeploy_emby_account_state() { printf 'absent\n'; }
    printf 'emby=%s\n' "$(run_addon_workflow plugin.service.emby-next-gen)"
  } 2>&1)"
  assert_contains "${output}" "emby=configured pending-authentication" \
    "an Emby client with no credentials is configured but unauthenticated" || return 1

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    INTERACTIVE="0"
    coreelec_postdeploy_emby_account_state() { printf 'present\n'; }
    coreelec_postdeploy_emby_sync_state() { printf 'sync-pending 0 16\n'; }
    printf 'emby=%s\n' "$(run_addon_workflow plugin.service.emby-next-gen)"
  } 2>&1)"
  assert_contains "${output}" "emby=configured pending-sync" \
    "an authenticated client mid-sync is not complete" || return 1

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    INTERACTIVE="0"
    coreelec_postdeploy_emby_account_state() { printf 'present\n'; }
    coreelec_postdeploy_emby_sync_state() { printf 'synced 16 16\n'; }
    printf 'emby=%s\n' "$(run_addon_workflow plugin.service.emby-next-gen)"
  } 2>&1)"
  assert_contains "${output}" "emby=configured complete" \
    "a finished sync is complete" || return 1

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    INTERACTIVE="0"
    coreelec_postdeploy_emby_account_state() { printf 'invalid\n'; }
    printf 'emby=%s\n' "$(run_addon_workflow plugin.service.emby-next-gen)"
  } 2>&1)"
  assert_contains "${output}" "emby=configured manual-required" \
    "unreadable credentials fail closed" || return 1

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    INTERACTIVE="1"
    authorize_pm4k_account() { printf 'configured\n'; }
    coreelec_postdeploy_pm4k_server_bound() { printf '0'; }
    printf 'pm4k=%s\n' "$(run_addon_workflow script.plexmod)"
  } 2>&1)"
  assert_contains "${output}" "pm4k=configured manual-required" \
    "an authorized account with no bound server is not complete" || return 1

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    INTERACTIVE="1"
    authorize_pm4k_account() { printf 'already-configured\n'; }
    coreelec_postdeploy_pm4k_server_bound() { printf '1'; }
    printf 'pm4k=%s\n' "$(run_addon_workflow script.plexmod)"
  } 2>&1)"
  assert_contains "${output}" "pm4k=already-configured complete" \
    "a previously authorized account with a bound server is complete" || return 1

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    INTERACTIVE="0"
    coreelec_postdeploy_weather_ready() { return 1; }
    printf 'weather=%s\n' "$(run_addon_workflow weather.ha)"
  } 2>&1)"
  assert_contains "${output}" "weather=skipped not-required" \
    "an unready unattended add-on is skipped with no onboarding axis" || return 1
}
```

Update the three existing assertions:

- `tests/test-coreelec-addon-workflows.sh:574` — change `assert_eq "authorization-required" "${output}"` to `assert_eq "configured pending-authentication" "${output}"`.
- `:582` — change `assert_eq "authorization-required" "${output}"` to `assert_eq "configured pending-authentication" "${output}"`.
- `:1425` — change `pm4k_status=already-configured` to `pm4k_status=already-configured complete`.
- `:1450` — change `pm4k_status=manual-required` to `pm4k_status=configured manual-required`.

Register the new test:

```bash
  test_workflow_reports_configuration_and_onboarding_on_separate_axes \
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test-coreelec-addon-workflows.sh 2>&1 | tail -20`
Expected: FAIL — `run_addon_workflow` still prints a single token.

- [ ] **Step 3: Write minimal implementation**

Replace `run_addon_workflow` in `lib/coreelec-addon-workflows.sh` with:

```bash
coreelec_postdeploy_emby_onboarding_status() {
  local account_state sync_state sync_word synced attempted
  account_state="$(coreelec_postdeploy_emby_account_state 2>/dev/null || true)"
  case "${account_state}" in
    absent)
      printf 'pending-authentication\n'
      return 0
      ;;
    incomplete)
      printf 'pending-authentication\n'
      return 0
      ;;
    present) ;;
    *)
      coreelec_postdeploy_observe \
        "service.plugin.service.emby-next-gen.account_state" "${account_state:-unreadable}"
      printf 'manual-required\n'
      return 0
      ;;
  esac

  sync_state="$(coreelec_postdeploy_emby_sync_state 2>/dev/null || true)"
  read -r sync_word synced attempted <<EOF
${sync_state}
EOF
  coreelec_postdeploy_observe \
    "service.plugin.service.emby-next-gen.libraries_synced" "${synced:-0}"
  coreelec_postdeploy_observe \
    "service.plugin.service.emby-next-gen.libraries_attempted" "${attempted:-0}"

  case "${sync_word}" in
    synced) printf 'complete\n' ;;
    sync-pending|database-absent) printf 'pending-sync\n' ;;
    *) printf 'manual-required\n' ;;
  esac
}

coreelec_postdeploy_pm4k_onboarding_status() {
  local authorization="$1" bound
  case "${authorization}" in
    configured|already-configured) ;;
    authorization-required)
      printf 'pending-authentication\n'
      return 0
      ;;
    *)
      printf 'manual-required\n'
      return 0
      ;;
  esac

  bound="$(coreelec_postdeploy_pm4k_server_bound 2>/dev/null || true)"
  if [[ ! "${bound}" =~ ^[01]$ ]]; then
    coreelec_postdeploy_observe "service.script.plexmod.failure" "server-state-unreadable"
    printf 'manual-required\n'
    return 0
  fi
  coreelec_postdeploy_observe "service.script.plexmod.server_bound" "${bound}"
  if [[ "${bound}" == "1" ]]; then
    printf 'complete\n'
  else
    printf 'manual-required\n'
  fi
}

run_addon_workflow() {
  local addon_id="$1" config_status onboarding_status authorization

  case "${addon_id}" in
    weather.ha)
      if coreelec_postdeploy_weather_ready; then
        config_status="$(check_home_assistant_weather)"
      else
        config_status="skipped"
      fi
      onboarding_status="not-required"
      ;;
    pvr.nextpvr)
      if coreelec_postdeploy_nextpvr_ready; then
        config_status="$(check_nextpvr)"
      else
        config_status="skipped"
      fi
      onboarding_status="not-required"
      ;;
    script.plexmod)
      config_status="configured"
      if [[ "${INTERACTIVE:-0}" == "1" ]]; then
        authorization="$(authorize_pm4k_account)"
      else
        authorization="authorization-required"
      fi
      case "${authorization}" in
        already-configured) config_status="already-configured" ;;
      esac
      onboarding_status="$(coreelec_postdeploy_pm4k_onboarding_status "${authorization}")"
      ;;
    plugin.service.emby-next-gen)
      config_status="configured"
      onboarding_status="$(coreelec_postdeploy_emby_onboarding_status)"
      ;;
    *)
      die "No post-deployment workflow is defined for add-on: $1"
      ;;
  esac

  printf '%s %s\n' "${config_status}" "${onboarding_status}"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test-coreelec-addon-workflows.sh 2>&1 | tail -5`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/coreelec-addon-workflows.sh tests/test-coreelec-addon-workflows.sh
git commit -m "feat: report configuration and onboarding on separate axes

run_addon_workflow now prints a config_status and an onboarding_status. Emby
stops returning an unconditional authorization-required and instead reports the
observed rung of its ladder, and PM4K gains the server-binding check, so an
authorized account with no selected server is manual-required rather than
complete.

Refs #6

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Emit both axes in the report

**Files:**
- Modify: `configure-coreelec-addons.sh:218-248` (`write_report`)
- Test: `tests/test-coreelec-addon-workflows.sh`

**Interfaces:**
- Consumes: `run_addon_workflow` from Task 5.
- Produces: report lines `addon.<id>.config_status=<value>` and `addon.<id>.onboarding_status=<value>`, and the banner `report_format=coreelec-addon-configuration-report-2`. The single `addon.<id>.status` line is removed.

- [ ] **Step 1: Write the failing test**

Add before the `run_all_tests` call:

```bash
test_report_emits_both_status_axes_under_the_new_format() {
  local dir config env_file report
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  config="${dir}/postdeploy.conf"
  env_file="${dir}/.env"
  write_config "${config}" weather.ha script.plexmod
  write_shared_env_file "${env_file}" \
    'KODI_WEB_PASSWORD=kodi-web-password-secret'

  UGOOS_ENV_FILE="${env_file}" bash "${CLI_SCRIPT}" \
    --config "${config}" \
    --report-dir "${dir}/reports" \
    --target coreelec-theater \
    --dry-run >/dev/null 2>&1
  report="$(find_single_report "${dir}/reports")"

  assert_contains "$(cat "${report}")" "report_format=coreelec-addon-configuration-report-2" \
    "the format banner records the two-axis vocabulary" || return 1
  assert_contains "$(cat "${report}")" "addon.weather.ha.config_status=dry-run" \
    "dry-run is reported on the configuration axis" || return 1
  assert_contains "$(cat "${report}")" "addon.weather.ha.onboarding_status=dry-run" \
    "dry-run is reported on the onboarding axis" || return 1
  assert_contains "$(cat "${report}")" "addon.script.plexmod.config_status=dry-run" \
    "every selected add-on gets a configuration axis" || return 1
  assert_contains "$(cat "${report}")" "addon.script.plexmod.onboarding_status=dry-run" \
    "every selected add-on gets an onboarding axis" || return 1
  assert_not_contains "$(cat "${report}")" "addon.weather.ha.status=" \
    "the conflated single status field is gone" || return 1
  assert_contains "$(cat "${report}")" "addon.script.plexmod.interaction_level=" \
    "interaction level is retained" || return 1
}
```

Register it:

```bash
  test_report_emits_both_status_axes_under_the_new_format \
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test-coreelec-addon-workflows.sh 2>&1 | tail -20`
Expected: FAIL on the format banner assertion.

- [ ] **Step 3: Write minimal implementation**

In `configure-coreelec-addons.sh`, change the banner line from:

```bash
    printf 'report_format=coreelec-addon-configuration-report-1\n'
```

to:

```bash
    printf 'report_format=coreelec-addon-configuration-report-2\n'
```

Then replace the status emission block inside `write_report`:

```bash
      if [[ "${DRY_RUN}" == "1" ]]; then
        status="dry-run"
      else
        status="$(run_addon_workflow "${addon_id}")"
      fi
      printf 'addon.%s.status=%s\n' "${addon_id}" "${status}"
```

with:

```bash
      if [[ "${DRY_RUN}" == "1" ]]; then
        config_status="dry-run"
        onboarding_status="dry-run"
      else
        read -r config_status onboarding_status <<EOF
$(run_addon_workflow "${addon_id}")
EOF
      fi
      printf 'addon.%s.config_status=%s\n' "${addon_id}" "${config_status}"
      printf 'addon.%s.onboarding_status=%s\n' "${addon_id}" "${onboarding_status}"
```

Update the `local` declaration on the `write_report` line from:

```bash
  local file="$1" capability_state="$2" addon_id status
```

to:

```bash
  local file="$1" capability_state="$2" addon_id config_status onboarding_status
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test-coreelec-addon-workflows.sh 2>&1 | tail -5`
Expected: PASS. If `test_report_contains_statuses_but_no_secret_values` fails on the old `addon.<id>.status=` field name, update its expectations to the two new fields.

- [ ] **Step 5: Run the whole suite**

Run: `ls tests/*.sh | grep -v test-helper | while read f; do bash "$f"; done 2>&1 | tail -20`
Expected: every suite passes.

- [ ] **Step 6: Commit**

```bash
git add configure-coreelec-addons.sh tests/test-coreelec-addon-workflows.sh
git commit -m "feat: emit config_status and onboarding_status in the report

The report format becomes coreelec-addon-configuration-report-2 and the
conflated addon.<id>.status field is replaced by the two axes.

Refs #6

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Documentation

**Files:**
- Create: `docs/devices/ugoos-am6b-plus/addon-onboarding-contract.md`
- Modify: `docs/operations/provision-ugoos.md` (step 12 around line 146, and "Current rollout limits" at line 196)

**Interfaces:**
- Consumes: the vocabulary and predicates from Tasks 1–6.
- Produces: no code interfaces.

- [ ] **Step 1: Write the contract document**

Create `docs/devices/ugoos-am6b-plus/addon-onboarding-contract.md` containing, in this order:

1. **Purpose** — one paragraph: this is the evidence-based contract for add-on onboarding order, Kodi restart checkpoints, and completion signals, and it governs what the configuration report is allowed to claim.
2. **Onboarding order** — the six phases from the spec's "Onboarding Order" section, each with its stated reason it cannot move, and the explicit note that phase 6 cannot collapse into phase 4 because Arctic Fuse 3's Trakt widgets are populated from Emby library tags.
3. **Restart checkpoints** — the Class K and Class P table and the three rules from the spec's "Restart Contract" section, including the statement that the single restart is unconditional and that there are no unnecessary restarts to remove.
4. **Completion signals** — the per-add-on table from the spec's "Report Vocabulary" section, with the Emby ladder and the PM4K server-binding predicate spelled out.
5. **Evidence** — copy the spec's "Evidence" section verbatim, including the file-ownership hash table, the `LibrarySynced` / `LibrarySyncedMirrow` source citation with line numbers, the note that `LastIncrementalSync` is not a session-completion signal, and the observed sync timings.
6. **Security constraint** — the Plex connection token note and the rule that observations emit booleans, counts, or fixed tokens only.

Link to the spec at `../../superpowers/specs/2026-09-16-addon-onboarding-restart-sequencing-design.md`.

- [ ] **Step 2: Update the runbook's step 12**

In `docs/operations/provision-ugoos.md`, replace the step 12 paragraph that begins "After the manual Emby sign-in completes" with text that:

- tells the operator to re-run `./configure-coreelec-addons.sh` and read `addon.plugin.service.emby-next-gen.onboarding_status`;
- states that `pending-sync` means the library sync has not finished and the Trakt widgets are expected to be empty;
- states that `complete` means every attempted library finished syncing;
- keeps the existing explanation that Trakt tags come from Emby server metadata.

- [ ] **Step 3: Update the rollout limits**

In the "Current rollout limits" section at line 196, remove "post-install add-on sequencing" from the list of things component scoping does not fix, and add one sentence noting that the onboarding order, restart checkpoints, and completion signals are defined in the new contract document. Leave the weather and remux buffering limits unchanged.

- [ ] **Step 4: Add the two-axis report description**

In `docs/operations/provision-ugoos.md`, directly after the step 11
`configure-coreelec-addons.sh` invocation block, add a subsection titled
"Reading the configuration report" that states:

- the report banner is `coreelec-addon-configuration-report-2`;
- `addon.<id>.config_status` covers artifact and configuration work owned by
  provisioning, with values `configured`, `already-configured`, `skipped`,
  `failed`, `dry-run`;
- `addon.<id>.onboarding_status` covers authentication and synchronization,
  with values `not-required`, `complete`, `pending-authentication`,
  `pending-sync`, `manual-required`, `unobservable`, `failed`, `dry-run`;
- only `onboarding_status=complete` means an add-on is finished, and
  `config_status=configured` on its own never does;
- the previous single `addon.<id>.status` field is gone, and the mapping from
  it is in the spec's migration table.

- [ ] **Step 5: Verify links and run the suite**

Run:

```bash
grep -rn 'addon-onboarding-contract' docs/
ls tests/*.sh | grep -v test-helper | while read f; do bash "$f"; done 2>&1 | tail -20
```

Expected: the new document is referenced from the runbook, and every suite still passes. There are no documentation tests in this repository, so the prose is reviewed rather than tested.

- [ ] **Step 6: Commit**

```bash
git add docs/devices/ugoos-am6b-plus/addon-onboarding-contract.md docs/operations/provision-ugoos.md
git commit -m "docs: record the add-on onboarding and restart contract

Adds the operator-facing contract covering the six-phase onboarding order, the
Kodi restart checkpoints and the file-ownership evidence behind them, and the
per-add-on completion signals. Updates the runbook to describe the two-axis
report instead of telling the operator to expect an empty Trakt widget.

Closes #6

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Verification

After Task 7, confirm the whole repository is green:

```bash
ls tests/*.sh | grep -v test-helper | while read f; do bash "$f"; done
```

Expected: 8 suites pass, with the add-on workflow suite up by 7 tests from its starting 33, for 40 total.

No live-device validation is required: every predicate is exercised offline against fixtures, and the device evidence that justifies them is already captured in the spec. Deployment to `ugoos-theater` is the operator's decision and is out of scope for this plan.
