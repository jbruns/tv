# Arctic Fuse Season and Episode View Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision the Arctic Fuse season and episode library view types idempotently, rebuild the compiled view include on every skin-effective run, and verify both surfaces semantically.

**Architecture:** The transform merges two keys into a JSON file owned by
`script.skinvariables` rather than owning the whole file. A new remote stage,
`buildviews`, runs over SSH between the deployment transaction and
verification, asks the device to recompile the include, and waits for the
result to settle. The verification probe then observes both surfaces — the
source by parsed value, the compiled include by asserting that exactly one
`Exp_View_*` expression claims each content type in the library scope.

**Tech Stack:** Bash 5 (`provision-coreelec.sh`), POSIX sh for everything
emitted to the device, Python 3 for the settings transformer and the
verification probe, Kodi 21 JSON-RPC, `kodi-send` over the Kodi EventServer.

**Spec:** `docs/superpowers/specs/2026-09-17-arctic-fuse-viewtypes-design.md`

## Global Constraints

- Managed intent is exactly two values, both in the `library` scope:
  `seasons` = `"509"`, `episodes` = `"549"`. Values are **strings** in the
  JSON, confirmed on the device.
- The `plugins` scope and the other 35 `library` content types are never
  written and never verified.
- Source path, relative to the storage root:
  `.kodi/userdata/addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json`
- Compiled path, relative to the storage root:
  `.kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml`
- Everything new is gated on the `skin` component: `coreelec_component_effective skin`
  on the host, `selected("skin")` in the probe, `apply_skin` on the device.
- **Any script emitted for `ssh_keyed "sh -c '...'"` must contain no single
  quote character at all** — not in code, not in a heredoc delimiter, not in
  an English apostrophe inside a message. This is asserted at runtime for the
  audio probe and will be asserted for the new stage.
- New test functions must be appended to the trailing backslash-continued
  `run_all_tests \` list at the bottom of their suite. A guard test fails the
  suite if a `test_*` function is not registered.
- `git add` explicit paths only. Never commit `.agents/` or `skills-lock.json`.
- Run a suite with `bash tests/<file>.sh`. There is no master runner.

---

### Task 1: Merge the managed view types into the source JSON

**Files:**
- Modify: `provision-coreelec.sh` — the settings transformer, immediately
  after the `skinvariables-shortcut-powermenu.json` write (around `:995`) and
  before the `# --- Arctic Fuse smart playlists` comment.
- Test: `tests/test-coreelec-settings.sh`

**Interfaces:**
- Consumes: existing transformer helpers `write_json_atomic(path, value)`,
  `register_managed_directory(path)`, the local `addon_data` path variable,
  and the module constant `SKIN_ID` (`"skin.arctic.fuse.3"`).
- Produces: the source JSON at
  `<root>/.kodi/userdata/addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json`
  containing `{"library": {..., "seasons": "509", "episodes": "549"}}` with
  every pre-existing key preserved. Later tasks rely on this path and on the
  string-typed values.

- [ ] **Step 1: Add a path helper to the settings test suite**

`tests/test-coreelec-settings.sh` already has `skinvariables_node_path` around
`:1508`. Add this immediately after it:

```bash
# The view types source is a sibling of the `nodes` directory, not a node.
skinvariables_viewtypes_path() {
  local root="$1"
  printf '%s/.kodi/userdata/addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json' \
    "${root}"
}

# Reads one library-scope view id out of the source JSON.
viewtypes_library_value() {
  local path="$1" content="$2"
  python3 -c '
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    document = json.load(handle)
sys.stdout.write(str(document["library"].get(sys.argv[2], "")))
' "${path}" "${content}"
}
```

- [ ] **Step 2: Write the failing tests**

Append these six test functions to `tests/test-coreelec-settings.sh`, just
before the `run_all_tests \` block:

```bash
test_managed_view_types_are_written_into_the_library_scope() {
  local root payload path
  root="$(make_scratch_dir)"
  trap 'rm -rf -- "${root}"' RETURN
  payload="${root}/payload.env"
  write_full_payload "${payload}"

  run_transform "${root}" "${payload}" >/dev/null

  path="$(skinvariables_viewtypes_path "${root}")"
  assert_eq "509" "$(viewtypes_library_value "${path}" seasons)" \
    "seasons must land on List Flixart" || return 1
  assert_eq "549" "$(viewtypes_library_value "${path}" episodes)" \
    "episodes must land on List Flixart 2" || return 1
}

test_unmanaged_library_view_types_are_preserved() {
  local root payload path
  root="$(make_scratch_dir)"
  trap 'rm -rf -- "${root}"' RETURN
  payload="${root}/payload.env"
  write_full_payload "${payload}"
  path="$(skinvariables_viewtypes_path "${root}")"
  mkdir -p "$(dirname "${path}")"
  cat > "${path}" <<'JSON'
{"library": {"movies": "502", "seasons": "521", "episodes": "501", "tvshows": "577"},
 "plugins": {"movies": "500", "seasons": "521", "episodes": "501"}}
JSON

  run_transform "${root}" "${payload}" >/dev/null

  assert_eq "502" "$(viewtypes_library_value "${path}" movies)" \
    "an unmanaged library content type must be left alone" || return 1
  assert_eq "577" "$(viewtypes_library_value "${path}" tvshows)" \
    "a second unmanaged library content type must be left alone" || return 1
}

test_the_plugins_scope_is_never_touched() {
  local root payload path observed
  root="$(make_scratch_dir)"
  trap 'rm -rf -- "${root}"' RETURN
  payload="${root}/payload.env"
  write_full_payload "${payload}"
  path="$(skinvariables_viewtypes_path "${root}")"
  mkdir -p "$(dirname "${path}")"
  cat > "${path}" <<'JSON'
{"library": {"seasons": "521", "episodes": "501"},
 "plugins": {"seasons": "521", "episodes": "501"}}
JSON

  run_transform "${root}" "${payload}" >/dev/null

  observed="$(python3 -c '
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    document = json.load(handle)
sys.stdout.write(json.dumps(document["plugins"], sort_keys=True))
' "${path}")"
  assert_eq '{"episodes": "501", "seasons": "521"}' "${observed}" \
    "the plugins scope must survive the transform unchanged" || return 1
}

test_an_absent_view_types_source_is_created_with_only_the_managed_keys() {
  local root payload path observed
  root="$(make_scratch_dir)"
  trap 'rm -rf -- "${root}"' RETURN
  payload="${root}/payload.env"
  write_full_payload "${payload}"

  run_transform "${root}" "${payload}" >/dev/null

  path="$(skinvariables_viewtypes_path "${root}")"
  observed="$(python3 -c '
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    document = json.load(handle)
sys.stdout.write(json.dumps(document, sort_keys=True))
' "${path}")"
  assert_eq '{"library": {"episodes": "549", "seasons": "509"}}' "${observed}" \
    "an absent source becomes a minimal document the add-on fills in" || return 1
}

test_a_malformed_view_types_source_is_replaced_rather_than_fatal() {
  local root payload path
  root="$(make_scratch_dir)"
  trap 'rm -rf -- "${root}"' RETURN
  payload="${root}/payload.env"
  write_full_payload "${payload}"
  path="$(skinvariables_viewtypes_path "${root}")"
  mkdir -p "$(dirname "${path}")"
  printf 'NOT JSON AT ALL' > "${path}"

  run_transform "${root}" "${payload}" >/dev/null \
    || { fail "a malformed source must not abort the transform"; return 1; }

  assert_eq "509" "$(viewtypes_library_value "${path}" seasons)" \
    "the managed value is established over the wreckage" || return 1
}

test_a_second_transform_leaves_the_view_types_source_identical() {
  local root payload path before after
  root="$(make_scratch_dir)"
  trap 'rm -rf -- "${root}"' RETURN
  payload="${root}/payload.env"
  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null
  path="$(skinvariables_viewtypes_path "${root}")"
  before="$(sha256sum "${path}")"

  run_transform "${root}" "${payload}" >/dev/null

  after="$(sha256sum "${path}")"
  assert_eq "${before}" "${after}" \
    "the transform must be idempotent over its own output" || return 1
}
```

Register all six in the `run_all_tests \` list.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-settings.sh`
Expected: FAIL — five of the six fail because the file is never created
(`viewtypes_library_value` raises `FileNotFoundError`).
`test_the_plugins_scope_is_never_touched` passes only incidentally; keep it as
a regression guard.

- [ ] **Step 4: Implement the merge**

In `provision-coreelec.sh`, insert after the `skinvariables-shortcut-powermenu.json`
`write_json_atomic(...)` call and before `# --- Arctic Fuse smart playlists`:

```python
    # --- Arctic Fuse view types ---------------------------------------------
    # `script.skinvariables` owns this file and rewrites it on every rebuild,
    # merging the skin's own defaults back in. Owning the whole document would
    # therefore drift the moment Arctic Fuse adds a content type, so only the
    # two managed keys are set and everything else is left exactly as found.
    MANAGED_VIEW_TYPES = {"seasons": "509", "episodes": "549"}
    viewtypes_path = os.path.join(addon_data, "script.skinvariables",
                                  SKIN_ID + "-viewtypes.json")
    try:
        with open(viewtypes_path, "r", encoding="utf-8") as handle:
            viewtypes = json.load(handle)
    except Exception:
        viewtypes = None
    if not isinstance(viewtypes, dict):
        # Absent, empty, or unparseable. The add-on's make_defaultjson fills
        # in the rest on the next rebuild, and our values win that merge.
        viewtypes = {}
    library_views = viewtypes.get("library")
    if not isinstance(library_views, dict):
        library_views = {}
        viewtypes["library"] = library_views
    library_views.update(MANAGED_VIEW_TYPES)
    write_json_atomic(viewtypes_path, viewtypes)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-settings.sh`
Expected: PASS, 80/80.

- [ ] **Step 6: Prove the tests have teeth**

```bash
git stash push -- provision-coreelec.sh
bash tests/test-coreelec-settings.sh; echo "exit=$?"
git stash pop
```
Expected: the five new assertions fail with the transformer reverted.

- [ ] **Step 7: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-settings.sh
git commit -m "Provision the Arctic Fuse season and episode view types

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Back up and restore both view type surfaces

**Files:**
- Modify: `provision-coreelec.sh` — the `SKIN_SETTINGS_PATHS` heredoc inside
  `coreelec_managed_settings_paths_block` (around `:1155-1170`).
- Test: `tests/test-coreelec-artifacts.sh`

**Interfaces:**
- Consumes: the existing device-side `scoped_settings_paths` function, which
  feeds `copy_into_backup` during `transaction_state="backing up replaced paths"`
  and is restored from `${transaction}/files` by `rollback_transaction`.
- Produces: nothing new for later tasks. This task exists on its own because
  rollback correctness is independently reviewable.

Ordering note for the reviewer: `rollback_transaction` restores displaced
add-on directories *first* (`:1615-1626`) and the `files/` copies *second*
(`:1632-1639`), so a compiled include backed up as a file correctly overwrites
whatever the restored skin directory carried.

- [ ] **Step 1: Write the failing test**

Append to `tests/test-coreelec-artifacts.sh`:

```bash
# Both view type surfaces have to be recoverable. The source is ordinary
# managed settings; the compiled include is derived state that nonetheless
# has to be restored, because a rollback that reverts the source while
# leaving the compiled file at the new values ends internally inconsistent.
test_the_deploy_script_backs_up_both_view_type_surfaces() {
  local dir root emitted
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  emitted="$(bash "${PROVISIONER}" --emit-remote-script deploy "${root}")"
  assert_contains "${emitted}" \
    ".kodi/userdata/addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json" \
    "the view types source must be a scoped settings path" || return 1
  assert_contains "${emitted}" \
    ".kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml" \
    "the compiled view include must be a scoped settings path" || return 1
}

# The paths belong to the skin component alone: a core-only run must not
# carry them, or a narrowed run would restore skin state it never touched.
test_the_view_type_surfaces_are_scoped_to_the_skin_component() {
  local dir root emitted skin_block
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  emitted="$(bash "${PROVISIONER}" --emit-remote-script deploy "${root}")"
  skin_block="$(printf '%s\n' "${emitted}" \
    | awk '/SKIN_SETTINGS_PATHS$/{ inside = !inside; next } inside')"
  assert_contains "${skin_block}" \
    "skin.arctic.fuse.3-viewtypes.json" \
    "the source belongs inside the skin block" || return 1
  assert_contains "${skin_block}" \
    "script-skinviewtypes-includes.xml" \
    "the compiled include belongs inside the skin block" || return 1
}
```

Register both in `run_all_tests \`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-artifacts.sh`
Expected: FAIL — neither path appears in the emitted program.

- [ ] **Step 3: Add the paths**

In `provision-coreelec.sh`, inside the `SKIN_SETTINGS_PATHS` heredoc, add these
two lines immediately after the `skinvariables-shortcut-powermenu.json` line:

```
.kodi/userdata/addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json
.kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-artifacts.sh`
Expected: PASS, 89/89.

- [ ] **Step 5: Confirm the settings suite still passes**

Run: `bash tests/test-coreelec-settings.sh`
Expected: PASS, 80/80. The new source path is now backed up *and* written by
the transform, which is exactly the pattern every other managed settings file
follows.

- [ ] **Step 6: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-artifacts.sh
git commit -m "Back up and restore both Arctic Fuse view type surfaces

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Observe the view types source in the verification probe

**Files:**
- Modify: `provision-coreelec.sh` — the verification probe, after the
  `arctic_fuse.power_menu_configured` observation (around `:3407`); and the
  report aggregation, after the `arctic_fuse.power_menu_configured` check
  (around `:3867`).
- Test: `tests/test-coreelec-report.sh`

**Interfaces:**
- Consumes: the probe-local helpers `read_json(path)`, `observe(key, value)`,
  the `userdata` path variable, and the constant `SKIN_ID`; the report helper
  `coreelec_verify_boolean_observation "${observations}" KEY LABEL`.
- Produces: the probe constant `MANAGED_VIEW_TYPES = {"seasons": "509", "episodes": "549"}`
  — Task 4 reads this same dictionary — and the observation
  `arctic_fuse.viewtypes_source_configured`, reported as
  `arctic_fuse.viewtypes_source.{expected,observed,status}`.

- [ ] **Step 1: Seed the passing fixture**

`make_arctic_fuse_fixture_root` (around `:2928` in `tests/test-coreelec-report.sh`)
is the fixture every Arctic Fuse test starts from. Every new observation must
be satisfied there or the whole suite turns red. Add this next to the
`skinvariables-shortcut-powermenu.json` write:

The fixture already declares `local userdata=...` and
`local nodes_dir="${userdata}/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3"`
at `:2933`. The view types source is a sibling of `nodes`, not of the skin
subdirectory, so it is addressed from `userdata`:

```bash
  cat > "${userdata}/addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json" <<'JSON'
{"library": {"movies": "502", "seasons": "509", "episodes": "549"},
 "plugins": {"seasons": "521", "episodes": "501"}}
JSON
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test-coreelec-report.sh`:

Every Arctic Fuse probe test in this suite follows one shape — a scratch
directory, a fixture root built inside it, a stubbed JSON-RPC `curl`, and a
three-argument probe call. Copy it exactly; `make_arctic_fuse_fixture_root`
takes the scratch directory as its argument and prints the storage root.

```bash
# The source path, spelled once so the tests below stay readable.
viewtypes_source_path() {
  printf '%s/.kodi/userdata/addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json' "$1"
}

test_the_view_types_source_is_observed_as_configured() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"

  assert_contains "${output}" "arctic_fuse.viewtypes_source_configured=1" \
    "the seeded fixture carries the managed view types" || return 1
}

test_a_drifted_season_view_fails_the_view_types_source() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  cat > "$(viewtypes_source_path "${root}")" <<'JSON'
{"library": {"seasons": "521", "episodes": "549"}}
JSON

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"

  assert_contains "${output}" "arctic_fuse.viewtypes_source_configured=0" \
    "a season view someone changed in the UI is drift" || return 1
}

test_an_absent_view_types_source_is_observed_as_unconfigured() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  rm -f "$(viewtypes_source_path "${root}")"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"

  assert_contains "${output}" "arctic_fuse.viewtypes_source_configured=0" \
    "an absent source observes 0 rather than raising" || return 1
}

test_a_malformed_view_types_source_is_observed_as_unconfigured() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  printf 'NOT JSON' > "$(viewtypes_source_path "${root}")"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"

  assert_contains "${output}" "arctic_fuse.viewtypes_source_configured=0" \
    "a malformed source observes 0 rather than raising" || return 1
  assert_contains "${output}" "arctic_fuse.power_menu_configured=1" \
    "and the probe still finishes its other observations" || return 1
}
```

Register all four in `run_all_tests \`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-report.sh`
Expected: FAIL — the key is never emitted, so all four `assert_contains` miss.

- [ ] **Step 4: Implement the observation**

In the probe, after the `arctic_fuse.power_menu_configured` observation:

```python
    # --- Arctic Fuse view types --------------------------------------------
    MANAGED_VIEW_TYPES = {"seasons": "509", "episodes": "549"}

    viewtypes_source = read_json(os.path.join(
        userdata, "addon_data", "script.skinvariables",
        SKIN_ID + "-viewtypes.json"))
    source_library = None
    if isinstance(viewtypes_source, dict):
        source_library = viewtypes_source.get("library")
    if isinstance(source_library, dict):
        viewtypes_source_ok = all(
            str(source_library.get(content, "")) == view
            for content, view in MANAGED_VIEW_TYPES.items())
    else:
        viewtypes_source_ok = False
    observe("arctic_fuse.viewtypes_source_configured",
            1 if viewtypes_source_ok else 0)
```

- [ ] **Step 5: Wire the observation into the report**

In `verify_remote_baseline`, after the `arctic_fuse.power_menu_configured`
block:

```bash
  coreelec_verify_boolean_observation "${observations}" \
    "arctic_fuse.viewtypes_source_configured" "arctic_fuse.viewtypes_source" \
    || { failures=$((failures + 1)); arctic_fuse_failures=$((arctic_fuse_failures + 1)); }
```

- [ ] **Step 6: Seed the pass observations fixture**

`write_pass_observations` is the observation fixture the conclude and report
tests use. Add `arctic_fuse.viewtypes_source_configured=1` to it. Search the
file for `arctic_fuse.power_menu_configured=1` and add the new line beside it;
there may be more than one such fixture writer, so grep for every occurrence:

```bash
grep -n "arctic_fuse.power_menu_configured=1" tests/test-coreelec-report.sh
```

Add the new line after each hit.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-report.sh`
Expected: PASS, 183/183.

- [ ] **Step 8: Prove the report wiring has teeth**

Add one more test asserting the observation reaches `arctic_fuse.status`:

```bash
test_a_drifted_view_types_source_fails_the_arctic_fuse_status() {
  local dir config manifest observations output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  sed -i.bak 's/^arctic_fuse.viewtypes_source_configured=1$/arctic_fuse.viewtypes_source_configured=0/' \
    "${observations}"

  set +e
  output="$(run_report "${config}" "${dir}" "${observations}" "${manifest}" 2>&1)"
  set -e

  assert_contains "${output}" "arctic_fuse.viewtypes_source.status=mismatch" \
    "the drifted source is reported as a mismatch" || return 1
  assert_contains "${output}" "arctic_fuse.status=mismatch" \
    "and it fails the component as a whole" || return 1
}
```

Register it and rerun: `bash tests/test-coreelec-report.sh`
Expected: PASS, 184/184.

If `run_report` writes to a file rather than stdout, read the report file the
way the neighbouring tests do — copy the pattern from the nearest existing
`arctic_fuse.status` assertion rather than inventing one.

- [ ] **Step 9: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-report.sh
git commit -m "Verify the Arctic Fuse view types source

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Observe the compiled view include in the verification probe

**Files:**
- Modify: `provision-coreelec.sh` — the verification probe, immediately after
  the `arctic_fuse.viewtypes_source_configured` observation; and the report
  aggregation, immediately after the `arctic_fuse.viewtypes_source` check.
- Test: `tests/test-coreelec-report.sh`

**Interfaces:**
- Consumes: `MANAGED_VIEW_TYPES` from Task 3, the probe's `storage_root`
  variable, `observe`, `SKIN_ID`, and `xml.etree.ElementTree as ET` (already
  imported at the top of the probe).
- Produces: the observation `arctic_fuse.viewtypes_compiled_configured`,
  reported as `arctic_fuse.viewtypes_compiled.{expected,observed,status}`.

Read back from the device, these are the exact expression bodies the check has
to discriminate between:

```
Exp_View_509 [[!String.IsEqual(Container.Property(param.info),episode_group_seasons) + Container.Content(seasons) + [String.IsEmpty(Container.PluginName)]]]
Exp_View_549 [[Container.Content(episodes) + [String.IsEmpty(Container.PluginName)]]]
Exp_View_521 [[String.IsEqual(Container.Property(param.info),episode_group_seasons) + Container.Content(seasons) + [[String.IsEmpty(Container.PluginName)] | [!String.IsEmpty(Container.PluginName)]]] | ...
```

`Exp_View_521` carries the `Container.Content(seasons)` token but serves both
scopes, so it compiles to the disjunction and does not contain the clause.
That is why the clause must be matched whole and not split into tokens.

- [ ] **Step 1: Add a compiled-include writer to the report test suite**

Add next to the other Arctic Fuse fixture writers in
`tests/test-coreelec-report.sh`:

```bash
# Writes a compiled view include holding one expression per named content
# type, in the exact grammar script.skinvariables emits. `plugins_view`, when
# given, adds the plugins-scope twin so the tests can prove the library
# clause is what discriminates.
write_compiled_viewtypes() {
  local root="$1" seasons_view="$2" episodes_view="$3"
  local dir="${root}/.kodi/addons/skin.arctic.fuse.3/1080i"
  mkdir -p "${dir}"
  cat > "${dir}/script-skinviewtypes-includes.xml" <<XML
<includes>
    <expression name="Exp_View_${seasons_view}">[[!String.IsEqual(Container.Property(param.info),episode_group_seasons) + Container.Content(seasons) + [String.IsEmpty(Container.PluginName)]]]</expression>
    <expression name="Exp_View_${episodes_view}">[[Container.Content(episodes) + [String.IsEmpty(Container.PluginName)]]]</expression>
    <expression name="Exp_View_521">[[String.IsEqual(Container.Property(param.info),episode_group_seasons) + Container.Content(seasons) + [[String.IsEmpty(Container.PluginName)] | [!String.IsEmpty(Container.PluginName)]]]]</expression>
    <expression name="Exp_View_500">[[Container.Content(seasons) + [!String.IsEmpty(Container.PluginName)]]]</expression>
</includes>
XML
}

compiled_viewtypes_path() {
  printf '%s/.kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml' "$1"
}
```

Then call `write_compiled_viewtypes "${root}" 509 549` from
`make_arctic_fuse_fixture_root`, so the passing fixture satisfies the new
observation.

- [ ] **Step 2: Write the failing tests**

```bash
test_the_compiled_view_include_is_observed_as_configured() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"

  assert_contains "${output}" "arctic_fuse.viewtypes_compiled_configured=1" \
    "the seeded include claims both content types in the library scope" || return 1
}

test_a_compiled_include_naming_another_episode_view_is_unconfigured() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  write_compiled_viewtypes "${root}" 509 501

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"

  assert_contains "${output}" "arctic_fuse.viewtypes_compiled_configured=0" \
    "an episodes clause owned by another view is drift" || return 1
}

test_a_missing_compiled_view_include_is_unconfigured() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  rm -f "$(compiled_viewtypes_path "${root}")"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"

  assert_contains "${output}" "arctic_fuse.viewtypes_compiled_configured=0" \
    "the silent-revert case observes 0" || return 1
}

# The rebuild is not atomic: a mid-write read returns an empty file. That is
# a retryable observation, never an exception that kills the probe.
test_an_empty_compiled_view_include_is_unconfigured() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  : > "$(compiled_viewtypes_path "${root}")"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"

  assert_contains "${output}" "arctic_fuse.viewtypes_compiled_configured=0" \
    "a half-written include observes 0 rather than raising" || return 1
  assert_contains "${output}" "arctic_fuse.power_menu_configured=1" \
    "and the probe still finishes its other observations" || return 1
}

# Two expressions claiming one content type in one scope is not a state the
# skin can resolve, so it must never read as configured.
test_two_owners_of_one_content_type_are_unconfigured() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  cat > "$(compiled_viewtypes_path "${root}")" <<'XML'
<includes>
    <expression name="Exp_View_509">[[Container.Content(seasons) + [String.IsEmpty(Container.PluginName)]]]</expression>
    <expression name="Exp_View_577">[[Container.Content(seasons) + [String.IsEmpty(Container.PluginName)]]]</expression>
    <expression name="Exp_View_549">[[Container.Content(episodes) + [String.IsEmpty(Container.PluginName)]]]</expression>
</includes>
XML

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"

  assert_contains "${output}" "arctic_fuse.viewtypes_compiled_configured=0" \
    "an ambiguous include must not read as configured" || return 1
}

# The plugins scope shares the content token and must neither be mistaken for
# the library scope nor satisfy the library check on its own.
test_a_plugins_scope_clause_does_not_satisfy_the_library_check() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  cat > "$(compiled_viewtypes_path "${root}")" <<'XML'
<includes>
    <expression name="Exp_View_509">[[Container.Content(seasons) + [!String.IsEmpty(Container.PluginName)]]]</expression>
    <expression name="Exp_View_549">[[Container.Content(episodes) + [String.IsEmpty(Container.PluginName)]]]</expression>
</includes>
XML

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"

  assert_contains "${output}" "arctic_fuse.viewtypes_compiled_configured=0" \
    "a plugins-scope clause leaves the library scope unclaimed" || return 1
}
```

Register all six in `run_all_tests \`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-report.sh`
Expected: FAIL — the key is never emitted.

- [ ] **Step 4: Implement the observation**

In the probe, directly after the source observation from Task 3:

```python
    def compiled_view_owner(includes_root, content):
        """The one `Exp_View_*` expression that claims `content` in the
        library scope, or None when zero or several do.

        `[String.IsEmpty(Container.PluginName)]` on its own is the library
        scope. The plugins scope negates it, and a view serving both scopes
        compiles to the disjunction of the two, so neither contains this
        clause. Matching the clause whole also keeps `Container.Content(seasons)`
        from colliding with `episode-groups-seasons`, which shares the token
        but is discriminated by its `episode_group_seasons` guard."""
        clause = ("Container.Content(%s) + [String.IsEmpty(Container.PluginName)]"
                  % content)
        owners = []
        for node in includes_root.iter("expression"):
            name = node.get("name") or ""
            if not name.startswith("Exp_View_"):
                continue
            if clause in (node.text or ""):
                owners.append(name)
        if len(owners) != 1:
            return None
        return owners[0]

    # A missing or half-written include parses as nothing and observes 0.
    # Verification retries, so a mid-rebuild read costs an attempt rather
    # than the run.
    try:
        compiled_root = ET.parse(os.path.join(
            storage_root, ".kodi", "addons", SKIN_ID, "1080i",
            "script-skinviewtypes-includes.xml")).getroot()
    except Exception:
        compiled_root = None
    if compiled_root is None or compiled_root.tag != "includes":
        viewtypes_compiled_ok = False
    else:
        viewtypes_compiled_ok = all(
            compiled_view_owner(compiled_root, content) == "Exp_View_" + view
            for content, view in MANAGED_VIEW_TYPES.items())
    observe("arctic_fuse.viewtypes_compiled_configured",
            1 if viewtypes_compiled_ok else 0)
```

- [ ] **Step 5: Wire the observation into the report**

After the `arctic_fuse.viewtypes_source` block:

```bash
  coreelec_verify_boolean_observation "${observations}" \
    "arctic_fuse.viewtypes_compiled_configured" "arctic_fuse.viewtypes_compiled" \
    || { failures=$((failures + 1)); arctic_fuse_failures=$((arctic_fuse_failures + 1)); }
```

Add `arctic_fuse.viewtypes_compiled_configured=1` to every observation fixture
that already carries `arctic_fuse.viewtypes_source_configured=1`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-report.sh`
Expected: PASS, 190/190.

- [ ] **Step 7: Confirm no other suite regressed**

Run each of the eight suites:

```bash
for suite in addon-workflows artifacts config env lifecycle report settings ha-package; do
  printf '== %s\n' "${suite}"
  bash "tests/test-coreelec-${suite}.sh" 2>&1 | tail -3
done
```

The `ha-package` and `addon-workflows` files may carry a different prefix;
list `tests/` first and run whatever is there. Expected: every suite green.

- [ ] **Step 8: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-report.sh
git commit -m "Verify the compiled Arctic Fuse view include semantically

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Add the buildviews remote stage

**Files:**
- Modify: `provision-coreelec.sh` — add `coreelec_remote_buildviews_script`
  after `coreelec_remote_audio_probe_script` (which ends around `:3860`); add
  the `buildviews)` case and extend the `die` message in
  `coreelec_emit_remote_script` (around `:3865-3880`); update the usage text
  at `:126`.
- Test: `tests/test-coreelec-report.sh` (behavioural, alongside the audio
  probe tests), `tests/test-coreelec-artifacts.sh` (emission and rejection).

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `coreelec_remote_buildviews_script` — a shell function printing a
  POSIX sh program to stdout. The program reads `KEY=VALUE` lines on stdin:
  `KODI_WEB_USER`, `KODI_WEB_PASSWORD`, `KODI_PORT`, `STORAGE_ROOT`,
  `SKIN_ID`, `ATTEMPTS`, `RETRY_DELAY`, `SETTLE_ATTEMPTS`. It prints nothing
  on stdout, exits `0` on success, and exits `1` with a message on stderr when
  Kodi is unreachable, when `services.esenabled` is false, or when
  `kodi-send` is missing. Task 6 calls it.

**The single-quote rule applies to every byte of this function's output.** No
apostrophes in messages, no `<<'DELIMITER'` inside the emitted program, no
`python3 -c '...'`. Follow `coreelec_remote_audio_probe_script`, which solves
the same problem with `<<PROBE_REQUEST` files and double-quoted Python.

- [ ] **Step 1: Write the failing emission tests**

Append to `tests/test-coreelec-artifacts.sh`:

```bash
test_the_buildviews_stage_is_emittable() {
  local script
  script="$(bash "${PROVISIONER}" --emit-remote-script buildviews)"
  assert_contains "${script}" "action=buildviews" \
    "the stage must ask the add-on to rebuild its views" || return 1
  assert_contains "${script}" "no_reload=True" \
    "the rebuild must not reload the skin under verification" || return 1
  assert_contains "${script}" "force=True" \
    "the rebuild is unconditional" || return 1
}

# The host runs this through `sh -c '...'`, so a single quote anywhere in the
# program would end the quoting and hand the rest to the remote shell.
test_the_buildviews_stage_contains_no_single_quote() {
  local script
  script="$(bash "${PROVISIONER}" --emit-remote-script buildviews)"
  case "${script}" in
    *"'"*) fail "the buildviews stage must contain no single quote"; return 1 ;;
  esac
}

test_an_unknown_remote_stage_is_still_rejected_by_name() {
  local output
  set +e
  output="$(bash "${PROVISIONER}" --emit-remote-script buildview 2>&1)"
  set -e
  assert_contains "${output}" "buildviews" \
    "the rejection lists the stage it almost matched" || return 1
  assert_contains "${output}" "not: buildview" \
    "the rejection names what was asked for" || return 1
}
```

Register all three in `run_all_tests \`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-artifacts.sh`
Expected: FAIL — `--emit-remote-script buildviews` dies with the unknown-stage
message.

- [ ] **Step 3: Implement the stage**

Add after `coreelec_remote_audio_probe_script`:

```bash
# --- Remote view rebuild -----------------------------------------------------
#
# `script.skinvariables` compiles its view types JSON into an XML include that
# lives inside the skin add-on directory, which provisioning replaces wholesale.
# Nothing else rebuilds it -- a Kodi restart provably does not -- so this stage
# runs on every skin-effective run, between the deployment transaction and
# verification.
#
# The one deterministic trigger is a script invocation, and the only way to
# reach it is kodi-send: JSON-RPC Addons.ExecuteAddon runs the add-on as a
# plugin, ignores the action, and returns OK regardless.
coreelec_remote_buildviews_script() {
  cat <<'REMOTE_BUILDVIEWS_BODY'
set -eu
umask 077
bv_user=""
bv_password=""
bv_port="8080"
bv_root="/storage"
bv_skin="skin.arctic.fuse.3"
bv_attempts="24"
bv_delay="5"
bv_settle="12"
while IFS= read -r bv_line; do
  case "${bv_line}" in
    KODI_WEB_USER=*) bv_user="${bv_line#KODI_WEB_USER=}" ;;
    KODI_WEB_PASSWORD=*) bv_password="${bv_line#KODI_WEB_PASSWORD=}" ;;
    KODI_PORT=*) bv_port="${bv_line#KODI_PORT=}" ;;
    STORAGE_ROOT=*) bv_root="${bv_line#STORAGE_ROOT=}" ;;
    SKIN_ID=*) bv_skin="${bv_line#SKIN_ID=}" ;;
    ATTEMPTS=*) bv_attempts="${bv_line#ATTEMPTS=}" ;;
    RETRY_DELAY=*) bv_delay="${bv_line#RETRY_DELAY=}" ;;
    SETTLE_ATTEMPTS=*) bv_settle="${bv_line#SETTLE_ATTEMPTS=}" ;;
    "") ;;
    *) printf "the view rebuild rejected an unknown parameter\n" >&2; exit 1 ;;
  esac
done

[ -n "${bv_user}" ] || { printf "the view rebuild requires a Kodi user\n" >&2; exit 1; }
command -v kodi-send >/dev/null 2>&1 \
  || { printf "the view rebuild requires kodi-send on the device\n" >&2; exit 1; }

bv_dir="$(mktemp -d)"
trap "rm -rf -- ${bv_dir}" EXIT INT TERM

# The password reaches curl only through a mode-600 configuration file in a
# directory the trap removes: it never appears in argv or in the process list.
printf "user = \"%s:%s\"\n" "${bv_user}" "${bv_password}" > "${bv_dir}/curlrc"
cat > "${bv_dir}/ping.json" <<BUILDVIEWS_PING
{"jsonrpc":"2.0","id":1,"method":"JSONRPC.Ping"}
BUILDVIEWS_PING
cat > "${bv_dir}/es.json" <<BUILDVIEWS_ES
{"jsonrpc":"2.0","id":1,"method":"Settings.GetSettingValue","params":{"setting":"services.esenabled"}}
BUILDVIEWS_ES

bv_ask() {
  curl --silent --show-error --fail --max-time 20 \
    --config "${bv_dir}/curlrc" \
    --header "Content-Type: application/json" \
    --data "@${bv_dir}/$1" \
    "http://127.0.0.1:${bv_port}/jsonrpc"
}

# The deployment transaction restarts Kodi immediately before this stage, so
# readiness is polled rather than assumed.
bv_attempt=1
while :; do
  if bv_ask ping.json > "${bv_dir}/pong.out" 2>/dev/null; then
    break
  fi
  if [ "${bv_attempt}" -ge "${bv_attempts}" ]; then
    printf "the view rebuild could not reach Kodi on port %s\n" "${bv_port}" >&2
    exit 1
  fi
  sleep "${bv_delay}"
  bv_attempt=$((bv_attempt + 1))
done

# kodi-send speaks to the EventServer over UDP and is fire-and-forget: its
# exit status reports that a datagram left the box, never that Kodi acted on
# it. A disabled EventServer would make this whole stage a silent no-op, so
# the one thing that can be established beforehand is established.
bv_ask es.json > "${bv_dir}/es.out" \
  || { printf "the view rebuild could not read services.esenabled\n" >&2; exit 1; }
python3 - "${bv_dir}/es.out" <<BUILDVIEWS_ES_CHECK
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    try:
        document = json.load(handle)
    except ValueError:
        raise SystemExit("the view rebuild could not parse the Kodi answer")
if document.get("result") is not True:
    raise SystemExit(
        "the view rebuild needs the Kodi EventServer, and services.esenabled is off")
BUILDVIEWS_ES_CHECK

bv_compiled="${bv_root}/.kodi/addons/${bv_skin}/1080i/script-skinviewtypes-includes.xml"
kodi-send --action="RunScript(script.skinvariables,action=buildviews,force=True,no_reload=True)" \
  >/dev/null 2>&1 \
  || { printf "the view rebuild could not deliver kodi-send\n" >&2; exit 1; }

# The rebuild is not atomic: reading the file mid-write returns an empty one.
# Two identical non-empty digests in a row is the settling signal. The stage
# does not adjudicate the result -- verification reads the actual state and
# decides -- so an unsettled file warns and returns success.
bv_previous=""
bv_attempt=1
bv_settled=0
while [ "${bv_attempt}" -le "${bv_settle}" ]; do
  sleep 1
  if [ -s "${bv_compiled}" ]; then
    bv_sample="$(md5sum < "${bv_compiled}")"
    if [ -n "${bv_previous}" ] && [ "${bv_sample}" = "${bv_previous}" ]; then
      bv_settled=1
      break
    fi
    bv_previous="${bv_sample}"
  fi
  bv_attempt=$((bv_attempt + 1))
done
if [ "${bv_settled}" != "1" ]; then
  printf "the rebuilt view include did not settle; verification will decide\n" >&2
fi
exit 0
REMOTE_BUILDVIEWS_BODY
}
```

- [ ] **Step 4: Register the stage name**

In `coreelec_emit_remote_script`, add the case alongside `audio-probe)`:

```bash
    buildviews) coreelec_remote_buildviews_script ;;
```

and replace the `die` message with:

```bash
      die "--emit-remote-script expects backup, payload, stage, deploy, rollback, finalize, verify, verify-probe, display-probe, audio-probe, buildviews, or authorized-key, not: ${name}"
```

Update the usage text at `:126` to list `buildviews` alongside the other
probes.

- [ ] **Step 5: Run the emission tests to verify they pass**

Run: `bash tests/test-coreelec-artifacts.sh`
Expected: PASS, 92/92.

- [ ] **Step 6: Write the failing behavioural tests**

These run the emitted program exactly as the device does, with `curl`,
`kodi-send`, and `md5sum` stubbed on `PATH`. Append to
`tests/test-coreelec-report.sh`, next to the audio probe tests:

```bash
# Stubs the three device programs the stage depends on. `es_result` is the
# literal JSON the EventServer setting query answers with.
write_buildviews_stubs() {
  local dir="$1" es_result="${2:-true}"
  local bin_dir="${dir}/bin"
  mkdir -p "${bin_dir}"
  cat > "${bin_dir}/curl" <<STUB
#!/bin/sh
for arg in "\$@"; do
  case "\${arg}" in
    *es.json) printf '{"id":1,"jsonrpc":"2.0","result":${es_result}}' ; exit 0 ;;
    *ping.json) printf '{"id":1,"jsonrpc":"2.0","result":"pong"}' ; exit 0 ;;
  esac
done
exit 0
STUB
  cat > "${bin_dir}/kodi-send" <<STUB
#!/bin/sh
printf '%s\n' "\$*" >> "${dir}/kodi-send.log"
exit 0
STUB
  chmod +x "${bin_dir}/curl" "${bin_dir}/kodi-send"
}

run_buildviews() {
  local dir="$1" script
  mkdir -p "${dir}/tmp" "${dir}/storage/.kodi/addons/skin.arctic.fuse.3/1080i"
  printf '<includes/>\n' \
    > "${dir}/storage/.kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml"
  script="$(bash "${PROVISIONER}" --emit-remote-script buildviews)"
  {
    printf 'KODI_WEB_USER=kodi\nKODI_WEB_PASSWORD=hunter2\nKODI_PORT=8080\n'
    printf 'STORAGE_ROOT=%s/storage\n' "${dir}"
    printf 'ATTEMPTS=2\nRETRY_DELAY=0\nSETTLE_ATTEMPTS=3\n'
  } | PATH="${dir}/bin:${PATH}" TMPDIR="${dir}/tmp" sh -c "${script}"
}

test_the_buildviews_stage_asks_the_addon_to_rebuild() {
  local dir sent
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_buildviews_stubs "${dir}"
  run_buildviews "${dir}" >/dev/null 2>&1 \
    || { fail "the stage must succeed when the device answers"; return 1; }
  sent="$(cat "${dir}/kodi-send.log")"
  assert_contains "${sent}" "action=buildviews" \
    "the datagram carries the rebuild action" || return 1
  assert_contains "${sent}" "no_reload=True" \
    "and suppresses the skin reload" || return 1
}

# A disabled EventServer turns kodi-send into a silent no-op. The stage is the
# only place that can see this coming, so it fails loudly instead.
test_the_buildviews_stage_fails_when_the_event_server_is_off() {
  local dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_buildviews_stubs "${dir}" "false"
  output="$(run_buildviews "${dir}" 2>&1)" \
    && { fail "a disabled EventServer must fail the stage"; return 1; }
  assert_contains "${output}" "services.esenabled" \
    "the failure names the setting an operator has to change" || return 1
  assert_not_contains "$(cat "${dir}/kodi-send.log" 2>/dev/null || printf '')" \
    "buildviews" "and nothing is sent" || return 1
}

test_the_buildviews_stage_rejects_an_unknown_parameter() {
  local dir output script
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_buildviews_stubs "${dir}"
  script="$(bash "${PROVISIONER}" --emit-remote-script buildviews)"
  output="$(printf 'KODI_WEB_USER=kodi\nNONSENSE=1\n' \
    | PATH="${dir}/bin:${PATH}" sh -c "${script}" 2>&1)" \
    && { fail "an unknown parameter must fail the stage"; return 1; }
  assert_contains "${output}" "unknown parameter" \
    "the rejection says what went wrong" || return 1
}

test_the_buildviews_stage_requires_kodi_send() {
  local dir output script
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  write_buildviews_stubs "${dir}"
  rm -f "${dir}/bin/kodi-send"
  script="$(bash "${PROVISIONER}" --emit-remote-script buildviews)"
  # PATH is reduced to the stub directory alone so the real program, if the
  # host happens to have one, cannot satisfy the check.
  output="$(printf 'KODI_WEB_USER=kodi\n' \
    | PATH="${dir}/bin" sh -c "${script}" 2>&1)" \
    && { fail "a device without kodi-send must fail the stage"; return 1; }
  assert_contains "${output}" "kodi-send" \
    "the failure names the missing program" || return 1
}
```

Register all four in `run_all_tests \`.

Note for the implementer: `run_buildviews` reduces `ATTEMPTS`/`RETRY_DELAY`/
`SETTLE_ATTEMPTS` so the tests do not sleep. If the settle loop still costs
three seconds per test, that is acceptable; do not shorten it by making the
production default smaller.

- [ ] **Step 7: Run the behavioural tests**

Run: `bash tests/test-coreelec-report.sh`
Expected: PASS, 194/194. If the stubbed `curl` argument matching does not
distinguish the two request files, adjust the stub — the stage passes
`--data "@.../ping.json"` and `--data "@.../es.json"`, so matching on the
suffix is sufficient.

- [ ] **Step 8: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-artifacts.sh tests/test-coreelec-report.sh
git commit -m "Add a remote stage that rebuilds the Arctic Fuse view include

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Run the stage between deployment and verification

**Files:**
- Modify: `provision-coreelec.sh` — add `coreelec_run_remote_buildviews` and
  `coreelec_rebuild_skin_viewtypes` next to `coreelec_resolve_audio_devices`
  (around `:5770-5840`); call the latter from `coreelec_conclude_deployment`
  (`:5334`); stub the former in the `--conclude-fixture` seam (`:5489`).
- Test: `tests/test-coreelec-report.sh`

**Interfaces:**
- Consumes: `coreelec_remote_buildviews_script` from Task 5; the existing
  host globals `KODI_USER`, `KODI_WEB_PASSWORD`, `KODI_PORT`; `ssh_keyed`;
  `coreelec_component_effective`.
- Produces: `coreelec_run_remote_buildviews` — the SSH call alone, so the
  fixture seam can replace it without disabling the component gate; and
  `coreelec_rebuild_skin_viewtypes` — the gate plus logging, which always
  returns `0`.

The split matters. `coreelec_rebuild_skin_viewtypes` stays real under test so
the component gate is exercised; only the SSH call is stubbed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test-coreelec-report.sh`:

```bash
# The rebuild has to happen after the transaction has restarted Kodi and
# before verification reads the compiled include, or verification would
# observe the state the rebuild was supposed to establish.
test_the_view_rebuild_runs_between_deployment_and_verification() {
  local dir config manifest observations log
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  log="${dir}/conclude.log"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  run_conclude "${config}" "${observations}" "${manifest}" 0 0 "${log}" >/dev/null

  assert_eq "$(printf 'buildviews\nverify\nfinalize')" "$(cat "${log}")" \
    "the rebuild precedes verification, which precedes the commit" || return 1
}

# A run that did not ask for the skin has no business touching skin state.
test_a_core_only_run_never_rebuilds_the_view_include() {
  local dir config manifest observations log
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  log="${dir}/conclude.log"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  run_conclude_component core "${config}" "${observations}" "${manifest}" \
    0 0 "${log}" >/dev/null || true

  assert_not_contains "$(cat "${log}")" "buildviews" \
    "a core-only run leaves the skin alone" || return 1
}

# kodi-send cannot report success, so the stage cannot either. A failed
# rebuild must not abort a transaction that is already open: verification
# reads the real state and rolls back if the views are wrong.
test_a_failed_view_rebuild_still_reaches_verification() {
  local dir config manifest observations log output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  log="${dir}/conclude.log"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  # An assignment prefixed to a *function* call is not reliably exported to
  # the processes that function starts, so the variable is exported outright
  # and removed again.
  export COREELEC_BUILDVIEWS_FIXTURE_STATUS=1
  output="$(run_conclude "${config}" "${observations}" "${manifest}" 0 0 "${log}")"
  unset COREELEC_BUILDVIEWS_FIXTURE_STATUS

  assert_contains "$(cat "${log}")" "verify" \
    "verification still runs" || return 1
  assert_contains "${output}" "verification_result=pass" \
    "and remains the authority on the outcome" || return 1
}
```

Register all three in `run_all_tests \`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash tests/test-coreelec-report.sh`
Expected: FAIL — the log reads `verify\nfinalize`; `buildviews` never appears.

- [ ] **Step 3: Implement the host functions**

Add after `coreelec_resolve_audio_devices`:

```bash
# The SSH call alone, kept separate from the gate below so the conclude
# fixture can replace the device round trip without disabling the gate.
coreelec_run_remote_buildviews() {
  local script
  script="$(coreelec_remote_buildviews_script)"
  [[ "${script}" != *"'"* ]] \
    || die "Internal error: the remote view rebuild must not contain a single quote"
  {
    printf 'KODI_WEB_USER=%s\n' "${KODI_USER}"
    printf 'KODI_WEB_PASSWORD=%s\n' "${KODI_WEB_PASSWORD}"
    printf 'KODI_PORT=%s\n' "${KODI_PORT}"
    printf 'STORAGE_ROOT=%s\n' "/storage"
    printf 'ATTEMPTS=%s\n' "${COREELEC_BUILDVIEWS_ATTEMPTS:-24}"
    printf 'RETRY_DELAY=%s\n' "${COREELEC_BUILDVIEWS_RETRY_DELAY:-5}"
    printf 'SETTLE_ATTEMPTS=%s\n' "${COREELEC_BUILDVIEWS_SETTLE_ATTEMPTS:-12}"
  } | ssh_keyed "sh -c '${script}'" >/dev/null
}

# Rebuilds the compiled Arctic Fuse view include, between the deployment
# transaction and verification.
#
# This never fails the run. The transaction is already open by the time it is
# called, and kodi-send cannot report whether Kodi acted, so the stage makes
# the attempt and verification adjudicates: a rebuild that silently did
# nothing leaves the include missing or stale, both of which fail the semantic
# checks and roll the transaction back.
coreelec_rebuild_skin_viewtypes() {
  coreelec_component_effective skin || return 0

  info "Rebuilding the Arctic Fuse view include on the device" >&2
  coreelec_run_remote_buildviews \
    || warn "The view rebuild did not complete; verification will decide the outcome"
  return 0
}
```

- [ ] **Step 4: Call it from the conclusion**

In `coreelec_conclude_deployment`, between `DEPLOYMENT_STATE="pending-verification"`
and the `info "Verifying the deployed baseline..."` line:

```bash
  coreelec_rebuild_skin_viewtypes
```

- [ ] **Step 5: Stub the SSH call in the conclude fixture seam**

In the `if (( ${#CONCLUDE_FIXTURE[@]} > 0 )); then` block, alongside the
existing `coreelec_collect_remote_observations`, `finalize_remote_deployment`,
and `rollback_remote_deployment` stubs:

```bash
  coreelec_run_remote_buildviews() {
    printf 'buildviews\n' >> "${CONCLUDE_FIXTURE[4]}"
    return "${COREELEC_BUILDVIEWS_FIXTURE_STATUS:-0}"
  }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `bash tests/test-coreelec-report.sh`
Expected: PASS, 197/197.

- [ ] **Step 7: Run every suite**

Run each file in `tests/`. Expected: all green, 200 registered tests overall
or thereabouts. Reconcile any count drift against the suite banners rather
than against this plan.

- [ ] **Step 8: Prove the wiring has teeth**

```bash
git stash push -- provision-coreelec.sh
bash tests/test-coreelec-report.sh; echo "exit=$?"
git stash pop
```
Expected: the three ordering tests fail with the provisioner reverted.

- [ ] **Step 9: Commit**

```bash
git add provision-coreelec.sh tests/test-coreelec-report.sh
git commit -m "Rebuild the Arctic Fuse view include before verification

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Document the managed views and the defect they close

**Files:**
- Modify: `config/README.md` — the Arctic Fuse managed-state bullets around
  `:243-262`.
- Modify: `docs/operations/provision-ugoos.md` — a new operator section
  alongside "### Where the TV Shows and Movies hubs land".

**Interfaces:**
- Consumes: the behaviour built in Tasks 1 through 6.
- Produces: nothing code depends on.

- [ ] **Step 1: Extend `config/README.md`**

Add to the Arctic Fuse managed-state bullets:

```markdown
- **Season and episode library views.** `library.seasons` is set to `509`
  (List Flixart) and `library.episodes` to `549` (List Flixart 2) in
  `addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json`. Only
  those two keys are written: `script.skinvariables` owns the file and merges
  the skin's defaults back into it on every rebuild, so provisioning claims
  the two values it cares about and leaves the other 35 content types and the
  entire `plugins` scope alone.
- **The compiled view include is derived state.**
  `skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml` is what the
  skin actually reads, and it lives inside the locked skin artifact directory
  that every skin deploy replaces wholesale. Provisioning rebuilds it on every
  skin-effective run rather than trying to own its bytes, and verifies it
  semantically: exactly one `Exp_View_*` expression must claim each managed
  content type in the library scope.
```

- [ ] **Step 2: Extend `docs/operations/provision-ugoos.md`**

Add a section:

```markdown
### Which view the season and episode lists use

Provisioning sets two Arctic Fuse library views and no others:

| List | View |
| --- | --- |
| Seasons | List Flixart |
| Episodes | List Flixart 2 |

Change either one in Kodi's UI and the next run puts it back. Every other
list — movies, TV shows, music, and everything reached through an add-on —
is left at whatever the skin or you chose.

**These apply at the next skin load, not instantly.** The rebuild deliberately
does not reload the skin, because reloading it mid-run makes Kodi rewrite the
very settings file verification is about to read. A run that restarted Kodi
is already correct; if you changed a view by hand and re-ran provisioning
without a restart, the list you are looking at keeps the old view until the
skin loads again.

**What this fixes.** Before this, any skin redeploy or version bump silently
reverted both views. The compiled include that the skin reads lives inside the
skin add-on directory, which provisioning replaces wholesale, and nothing
rebuilt it — not even a Kodi restart. The views reverted to Combined Landscape
and Row Landscape with nothing reporting a problem. Provisioning now rebuilds
that file on every run that touches the skin, and fails verification if it is
missing or wrong.

**If the rebuild fails.** It needs Kodi's Event Server, which is on by default
and which provisioning does not manage. If it has been turned off in
`Settings > Services > Control`, the run reports `services.esenabled` in the
failure and rolls back. Turn it back on and re-run.
```

- [ ] **Step 3: Check the rollout limits section**

Read the "## Current rollout limits" section near the end of
`docs/operations/provision-ugoos.md`. If it claims view types are unmanaged,
remove that claim. If it says nothing about them, leave it alone.

- [ ] **Step 4: Commit**

```bash
git add config/README.md docs/operations/provision-ugoos.md
git commit -m "Document the managed Arctic Fuse season and episode views

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 8: Verify on the device

**Files:** none. This task produces evidence for the pull request.

**Interfaces:**
- Consumes: everything above.
- Produces: the four proofs the spec asks for, pasted into the PR body.

Device facts the implementer needs:
- SSH: `ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater.lan.wavebe.am`
- The provisioner flag is `--target HOST`, never `--host`.
- Kodi's web user is `homeassistant`; the password is `KODI_WEB_PASSWORD` in `.env`.
- The audio probe runs before the transaction and needs a live Kodi on 8080,
  so a `--component skin` run cannot be started with Kodi stopped.
- The run prompts for confirmation about 25 seconds in. Drive it with a FIFO:
  `mkfifo /tmp/tvgate`, run the provisioner async with `< /tmp/tvgate`, hold
  the FIFO open with `(sleep 900 > /tmp/tvgate &)`, then `echo y > /tmp/tvgate`.
- BusyBox on the device has no `diff` and no `cmp`. Use `md5sum` or `python3`.
- **Never run `paste` on the device.** `/usr/bin/paste` uploads stdin to a
  public pastebin.

- [ ] **Step 1: Arm the device**

Turn on `input_boolean.ugoos_theater_keep_kodi_running` before anything else,
or Home Assistant will stop Kodi mid-run whenever the Bravia TV is off:

```bash
set -a; . ./.env; set +a
curl -sS -X POST -H "Authorization: Bearer ${HOME_ASSISTANT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"entity_id":"input_boolean.ugoos_theater_keep_kodi_running"}' \
  "${HOME_ASSISTANT_URL}/api/services/input_boolean/turn_on"
```

- [ ] **Step 2: Prove the run converges**

Run `--target ugoos-theater.lan.wavebe.am --component skin`. Confirm the
report carries `verification_result=pass`, `verification_failures=0`,
`arctic_fuse.viewtypes_source.status=ok`, and
`arctic_fuse.viewtypes_compiled.status=ok`. Record the report path.

- [ ] **Step 3: Prove it converges from drift**

On the device, set `library.episodes` to `501` in the source JSON, then re-run.
Confirm the run passes and the value is back at `549`:

```bash
ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater.lan.wavebe.am \
  'python3 -c "
import json
p = \"/storage/.kodi/userdata/addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json\"
d = json.load(open(p))
d[\"library\"][\"episodes\"] = \"501\"
json.dump(d, open(p, \"w\"))
print(d[\"library\"][\"episodes\"])
"'
```

- [ ] **Step 4: Prove the silent-revert defect is closed**

This is the point of the whole change. Delete the compiled include, confirm a
Kodi restart does not bring it back, then re-run and confirm the stage rebuilds
it:

```bash
ssh -i ~/.ssh/coreelec_admin_ed25519 root@ugoos-theater.lan.wavebe.am \
  'rm -f /storage/.kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml && \
   ls -l /storage/.kodi/addons/skin.arctic.fuse.3/1080i/ | head'
```

Re-run `--component skin` and confirm the file is back and
`arctic_fuse.viewtypes_compiled.status=ok`.

- [ ] **Step 5: Prove the views survive a restart**

Restart Kodi on the device, wait for the skin to load, and confirm the
compiled include is still present with the same digest and that
`library.seasons` and `library.episodes` still read `509` and `549`.

- [ ] **Step 6: Disarm the device**

Turn `input_boolean.ugoos_theater_keep_kodi_running` back off, and remove any
scratch files the verification left on the device.

- [ ] **Step 7: Open the pull request**

`gh pr create` mangles markdown passed through `--body`; write the body to a
file and use `--body-file`. The body must close the issue and carry the
evidence from Steps 2 through 5.

```bash
git push -u origin viewtypes-provisioning-27
gh pr create --title "Provision the Arctic Fuse season and episode view types" \
  --body-file /tmp/pr-27.md
```

Report the PR to the user and stop. **Do not merge it, and do not deploy
anything further.**

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: the merged source to
Task 1; backup and rollback to Task 2; the two verification observations to
Tasks 3 and 4; the `buildviews` stage, its EventServer check, its settling
behaviour, and `no_reload=True` to Task 5; the host placement between deploy
and verify and the component gate to Task 6; both documentation files to
Task 7; all four live proofs to Task 8.

**Two deliberate deviations from the spec, both strengthening it:**

1. The spec describes settling as "size and mtime stable across two
   consecutive samples". Task 5 samples `md5sum` instead. BusyBox has no
   portable per-file mtime reader that avoids single quotes, and a content
   digest subsumes both properties. Same bound, same behaviour, stronger
   signal.
2. The spec says the compiled include is "restored on rollback". Task 2
   achieves this by adding it to `scoped_settings_paths`, which backs it up
   only when it already exists. When it did not exist beforehand, rollback
   leaves the rebuilt file in place rather than deleting it. That is the
   better outcome: the file is derived state that matches the restored source
   only if it was rebuilt from it, and an absent include is the defect this
   change exists to close.

**One thing no task does, by design.** Nothing manages `services.esenabled`.
The spec scopes it out and Task 5 only fails loudly on it. If the device ever
has the Event Server disabled, that is a new issue for the service component.
