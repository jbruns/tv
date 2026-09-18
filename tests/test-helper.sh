#!/bin/bash

# Minimal, dependency-free test harness for the CoreELEC provisioning shell
# libraries. Test files source this helper, then source the library under
# test, define test_* functions, and finish by calling run_all_tests with the
# list of test function names. Every test_* function defined in a suite must
# appear in that list; run_all_tests refuses to run a suite that omits one.

TESTS_TOTAL=0
TESTS_PASSED=0
FAILED_TEST_NAMES=()

assert_eq() {
  local expected="$1" actual="$2" message="${3:-values differ}"
  if [[ "${expected}" != "${actual}" ]]; then
    printf 'assert_eq: %s (expected=%q actual=%q)\n' "${message}" "${expected}" "${actual}" >&2
    return 1
  fi
  return 0
}

assert_contains() {
  local haystack="$1" needle="$2" message="${3:-expected substring not found}"
  case "${haystack}" in
    *"${needle}"*) return 0 ;;
  esac
  printf 'assert_contains: %s (needle=%q haystack=%q)\n' "${message}" "${needle}" "${haystack}" >&2
  return 1
}

assert_not_contains() {
  local haystack="$1" needle="$2" message="${3:-unexpected substring found}"
  case "${haystack}" in
    *"${needle}"*)
      printf 'assert_not_contains: %s (needle=%q haystack=%q)\n' "${message}" "${needle}" "${haystack}" >&2
      return 1
      ;;
  esac
  return 0
}

assert_success() {
  local status="$1" message="${2:-expected success}"
  if (( status != 0 )); then
    printf 'assert_success: %s (status=%s)\n' "${message}" "${status}" >&2
    return 1
  fi
  return 0
}

assert_failure() {
  local status="$1" message="${2:-expected failure}"
  if (( status == 0 )); then
    printf 'assert_failure: %s (status=%s)\n' "${message}" "${status}" >&2
    return 1
  fi
  return 0
}

assert_manifest_rows_are_sequential() {
  local manifest="$1"
  local expected=1
  local index id version filename extra
  while IFS=$'\t' read -r index id version filename extra; do
    [[ -n "${index}" ]] || continue
    if [[ -n "${extra}" ]]; then
      printf 'assert_manifest_rows_are_sequential: expected four tab-separated fields (line starts %q)\n' "${index}" >&2
      return 1
    fi
    if [[ "${index}" != "${expected}" ]]; then
      printf 'assert_manifest_rows_are_sequential: expected index %s, got %s for %s\n' "${expected}" "${index}" "${id}" >&2
      return 1
    fi
    if [[ "${filename}" != "${expected}.zip" ]]; then
      printf 'assert_manifest_rows_are_sequential: expected filename %s.zip, got %s for %s\n' "${expected}" "${filename}" "${id}" >&2
      return 1
    fi
    expected=$((expected + 1))
  done < "${manifest}"
  return 0
}

# Creates an isolated scratch directory under the repository working tree
# (never under a system temp directory) so fixture files never escape the
# project and are always cleaned up by the caller.
make_scratch_dir() {
  local dir attempt
  for attempt in 1 2 3 4 5; do
    dir="${PWD}/.coreelec-test.$$.${RANDOM}.${RANDOM}"
    if mkdir -m 700 "${dir}" 2>/dev/null; then
      printf '%s\n' "${dir}"
      return 0
    fi
  done
  printf 'failed to create project-local scratch directory\n' >&2
  return 1
}

# Isolation from ambient operator secrets, without mutating the environment
# the rest of the test file runs in. `stash_unset_env` removes the named
# variables and records whether each one was set; `restore_stashed_env` puts
# them back exactly, including leaving an unset variable unset.
ENV_STASH=()

stash_unset_env() {
  local name
  ENV_STASH=()
  for name in "$@"; do
    if [[ -n "${!name+set}" ]]; then
      ENV_STASH+=("${name}=${!name}")
    else
      ENV_STASH+=("${name}")
    fi
    unset "${name}"
  done
}

restore_stashed_env() {
  local entry name
  for entry in ${ENV_STASH[@]+"${ENV_STASH[@]}"}; do
    name="${entry%%=*}"
    if [[ "${entry}" == *=* ]]; then
      export "${name}=${entry#*=}"
    else
      unset "${name}"
    fi
  done
  ENV_STASH=()
}

# Runs one named test function in a subshell (via command substitution) so
# test state, `set -e` failures, and stray `exit` calls never affect the
# runner or other tests. Captures combined stdout/stderr for failure reports.
# `set -e` is re-enabled inside that subshell so a failing assertion aborts the
# test immediately; without it only the final assertion in a test body would
# decide the result.
run_test() {
  local test_name="$1" output rc
  TESTS_TOTAL=$((TESTS_TOTAL + 1))
  set +e
  output="$(set -e; "${test_name}" 2>&1)"
  rc=$?
  set -e
  if (( rc == 0 )); then
    TESTS_PASSED=$((TESTS_PASSED + 1))
    printf 'ok - %s\n' "${test_name}"
  else
    FAILED_TEST_NAMES+=("${test_name}")
    printf 'not ok - %s\n' "${test_name}"
    if [[ -n "${output}" ]]; then
      printf '%s\n' "${output}" | sed 's/^/    # /'
    fi
  fi
  sweep_scratch_dirs
}

# `make_scratch_dir` relies on each test's `trap ... RETURN` to clean up, but
# that trap never fires when `set -e` aborts the test subshell mid-way. Failing
# tests therefore leaked their scratch directories into the working tree. Sweep
# after every test instead, matched on this runner's own PID so a concurrently
# running suite never has its directories removed underneath it.
sweep_scratch_dirs() {
  local dir
  for dir in "${PWD}"/.coreelec-test."$$".*; do
    [[ -d "${dir}" ]] && rm -rf -- "${dir}"
  done
  return 0
}

# Registration is manual: a suite ends by passing its test names to
# `run_all_tests`. A test that is defined but never passed in used to be
# skipped silently, and the suite still reported all green -- five such tests
# hid a credential-leak regression until #14. Fail the suite instead.
assert_every_test_is_registered() {
  local suite="$1" registered="" defined name missing=()

  [[ -r "${suite}" ]] || return 0
  shift
  # Built by hand rather than with "${*}": the suites set IFS=$'\n\t', which
  # would join the names with a newline and break a space-delimited match.
  for name in "$@"; do
    registered="${registered} ${name} "
  done

  defined="$(sed -n 's/^\(test_[A-Za-z0-9_]*\)().*/\1/p' "${suite}")"
  for name in ${defined}; do
    case "${registered}" in
      *" ${name} "*) ;;
      *) missing+=("${name}") ;;
    esac
  done

  (( ${#missing[@]} > 0 )) || return 0
  printf '\n%d test(s) defined in %s but never registered with run_all_tests:\n' \
    "${#missing[@]}" "${suite}" >&2
  printf '  %s\n' "${missing[@]}" >&2
  printf 'Add them to the run_all_tests list, or delete them.\n' >&2
  return 1
}

run_all_tests() {
  local test_name
  if ! assert_every_test_is_registered "${BASH_SOURCE[1]}" "$@"; then
    return 1
  fi
  for test_name in "$@"; do
    if [[ -n "${TEST_FILTER:-}" && ! "${test_name}" =~ ${TEST_FILTER} ]]; then
      continue
    fi
    run_test "${test_name}"
  done
  if (( TESTS_TOTAL == 0 )); then
    printf 'No tests selected (TEST_FILTER=%s)\n' "${TEST_FILTER:-}" >&2
    return 1
  fi
  printf '\n%d/%d tests passed\n' "${TESTS_PASSED}" "${TESTS_TOTAL}"
  if (( ${#FAILED_TEST_NAMES[@]} > 0 )); then
    printf 'Failed: %s\n' "${FAILED_TEST_NAMES[*]}"
    return 1
  fi
  return 0
}
