#!/bin/bash

# Minimal, dependency-free test harness for the CoreELEC provisioning shell
# libraries. Test files source this helper, then source the library under
# test, define test_* functions, and finish by calling run_all_tests with the
# list of test function names.

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

# Creates an isolated scratch directory under the repository working tree
# (never under a system temp directory) so fixture files never escape the
# project and are always cleaned up by the caller.
make_scratch_dir() {
  local dir
  dir="$(mktemp -d "${PWD}/.coreelec-test.XXXXXX")" || die "failed to create scratch directory"
  printf '%s\n' "${dir}"
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
}

run_all_tests() {
  local test_name
  for test_name in "$@"; do
    run_test "${test_name}"
  done
  printf '\n%d/%d tests passed\n' "${TESTS_PASSED}" "${TESTS_TOTAL}"
  if (( ${#FAILED_TEST_NAMES[@]} > 0 )); then
    printf 'Failed: %s\n' "${FAILED_TEST_NAMES[*]}"
    return 1
  fi
  return 0
}
