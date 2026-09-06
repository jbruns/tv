# Task 2 Report: Unattended Service Validation

## Status
- Implemented unattended read-only validation for Home Assistant Weather, NextPVR, and PM4K local mode in `lib/coreelec-addon-workflows.sh`.
- Added fixture-driven TDD coverage in `tests/test-coreelec-addon-workflows.sh`.
- Updated `docs/runbook.md` with the new post-deployment validation workflow and status meanings.
- Created commit: `8dd4efb375e317a080632be333b193fc1f15cd7a` (`feat: validate configured CoreELEC addon services`).

## Files Changed
- `lib/coreelec-addon-workflows.sh`
- `tests/test-coreelec-addon-workflows.sh`
- `docs/runbook.md`

## TDD Evidence

### RED
Command:
```bash
bash tests/test-coreelec-addon-workflows.sh
```

Output:
```text
ok - test_help_lists_supported_addons_and_interaction_levels
ok - test_default_run_never_starts_account_authorization
ok - test_requested_addon_must_be_in_the_pinned_manifest
ok - test_introspection_rejects_a_missing_required_method
ok - test_gui_guard_accepts_expected_window_and_control
ok - test_gui_guard_rejects_an_unexpected_window_without_sending_input
ok - test_rpc_request_ids_never_contain_secret_values
ok - test_report_contains_statuses_but_no_secret_values
not ok - test_weather_check_accepts_config_and_entity_responses
    # tests/test-coreelec-addon-workflows.sh: line 397: check_home_assistant_weather: command not found
    # assert_eq: weather check performs two HTTP requests and one Kodi launch (expected=3 actual=0)
not ok - test_weather_check_reports_unauthorized_without_echoing_token
    # tests/test-coreelec-addon-workflows.sh: line 428: check_home_assistant_weather: command not found
    # assert_eq: unauthorized weather checks stop before entity or add-on launch (expected=1 actual=0)
not ok - test_nextpvr_check_uses_the_configured_protocol_host_port_and_pin
    # tests/test-coreelec-addon-workflows.sh: line 462: check_nextpvr: command not found
    # assert_eq: NextPVR check performs backend login and advisory Kodi observation (expected=3 actual=0)
not ok - test_nextpvr_check_requires_a_successful_session_login
    # tests/test-coreelec-addon-workflows.sh: line 497: check_nextpvr: command not found
    # assert_eq: failed NextPVR login stops before the advisory Kodi call (expected=2 actual=0)
not ok - test_pm4k_local_check_requires_identity_and_token_authorized_root
    # tests/test-coreelec-addon-workflows.sh: line 530: check_pm4k_local: command not found
    # assert_eq: PM4K local check launches the add-on after both Plex probes pass (expected=3 actual=0)
not ok - test_service_checks_do_not_modify_addon_settings
    # tests/test-coreelec-addon-workflows.sh: line 622: check_home_assistant_weather: command not found
    # tests/test-coreelec-addon-workflows.sh: line 623: check_nextpvr: command not found
    # tests/test-coreelec-addon-workflows.sh: line 624: check_pm4k_local: command not found
    # assert_contains: weather check completed (needle=weather_status=configured haystack=$'weather_status=\nnextpvr_status=\npm4k_status=')

8/14 tests passed
Failed: test_weather_check_accepts_config_and_entity_responses
test_weather_check_reports_unauthorized_without_echoing_token
test_nextpvr_check_uses_the_configured_protocol_host_port_and_pin
test_nextpvr_check_requires_a_successful_session_login
test_pm4k_local_check_requires_identity_and_token_authorized_root
test_service_checks_do_not_modify_addon_settings
```

### GREEN
Command:
```bash
bash tests/test-coreelec-addon-workflows.sh
```

Output:
```text
ok - test_help_lists_supported_addons_and_interaction_levels
ok - test_default_run_never_starts_account_authorization
ok - test_requested_addon_must_be_in_the_pinned_manifest
ok - test_introspection_rejects_a_missing_required_method
ok - test_gui_guard_accepts_expected_window_and_control
ok - test_gui_guard_rejects_an_unexpected_window_without_sending_input
ok - test_rpc_request_ids_never_contain_secret_values
ok - test_report_contains_statuses_but_no_secret_values
ok - test_weather_check_accepts_config_and_entity_responses
ok - test_weather_check_reports_unauthorized_without_echoing_token
ok - test_nextpvr_check_uses_the_configured_protocol_host_port_and_pin
ok - test_nextpvr_check_requires_a_successful_session_login
ok - test_pm4k_local_check_requires_identity_and_token_authorized_root
ok - test_service_checks_do_not_modify_addon_settings

14/14 tests passed
```

## Verification

### Focused suite
Command:
```bash
bash tests/test-coreelec-addon-workflows.sh
```

Output:
```text
ok - test_help_lists_supported_addons_and_interaction_levels
ok - test_default_run_never_starts_account_authorization
ok - test_requested_addon_must_be_in_the_pinned_manifest
ok - test_introspection_rejects_a_missing_required_method
ok - test_gui_guard_accepts_expected_window_and_control
ok - test_gui_guard_rejects_an_unexpected_window_without_sending_input
ok - test_rpc_request_ids_never_contain_secret_values
ok - test_report_contains_statuses_but_no_secret_values
ok - test_weather_check_accepts_config_and_entity_responses
ok - test_weather_check_reports_unauthorized_without_echoing_token
ok - test_nextpvr_check_uses_the_configured_protocol_host_port_and_pin
ok - test_nextpvr_check_requires_a_successful_session_login
ok - test_pm4k_local_check_requires_identity_and_token_authorized_root
ok - test_service_checks_do_not_modify_addon_settings

14/14 tests passed
```

### Relevant full suite
Commands:
```bash
bash tests/test-coreelec-config.sh
bash tests/test-coreelec-settings.sh
bash tests/test-coreelec-report.sh
bash tests/test-coreelec-artifacts.sh
```

Outputs:

`bash tests/test-coreelec-config.sh`
```text
ok - test_defaults_are_pacific_english_us
ok - test_comments_blank_lines_and_values_are_parsed
ok - test_repeated_addon_artifacts_preserve_order
ok - test_duplicate_scalar_key_is_rejected
ok - test_unknown_key_is_rejected
ok - test_malformed_line_is_rejected
ok - test_shell_syntax_is_data_not_executed
ok - test_secret_key_in_config_is_rejected
ok - test_cli_value_overrides_config_value
ok - test_target_is_not_loaded_from_shared_config
ok - test_partial_youtube_credentials_are_rejected
ok - test_service_secret_without_endpoint_is_rejected
ok - test_missing_optional_secrets_are_allowed
ok - test_production_config_sets_pacific_english_us_baseline
ok - test_production_config_carries_no_secret_values
ok - test_production_config_locks_primary_addon_versions
ok - test_production_config_matches_the_reviewed_artifact_id_set
ok - test_production_config_records_immutable_upstream_sources
ok - test_production_config_records_each_artifact_exactly_once
ok - test_production_config_artifact_records_are_well_formed
ok - test_production_config_has_no_blocked_pins
ok - test_production_config_takes_binary_addons_from_the_installed_branch

22/22 tests passed
```

`bash tests/test-coreelec-settings.sh`
```text
ok - test_regional_settings_are_created
ok - test_duplicate_settings_are_collapsed
ok - test_existing_unmanaged_settings_are_preserved
ok - test_second_run_is_byte_identical
ok - test_tmdb_helper_keys_go_to_tmdb_helper_only
ok - test_youtube_credentials_require_all_three_values
ok - test_youtube_api_keys_json_has_expected_shape
ok - test_nextpvr_uses_instance_settings_format
ok - test_home_assistant_weather_uses_flat_settings_format
ok - test_weather_provider_changes_only_when_configured
ok - test_pm4k_local_mode_json_is_valid
ok - test_absent_optional_secrets_do_not_create_secret_settings
ok - test_absent_nextpvr_secret_preserves_an_existing_instance
ok - test_payload_values_survive_hostile_characters
ok - test_transformer_output_never_reveals_secrets
ok - test_atomic_writes_never_reuse_a_preexisting_temp_file
ok - test_atomic_writes_do_not_follow_a_symlinked_temp_path
ok - test_written_modes_ignore_a_permissive_umask
ok - test_a_failed_write_leaves_no_secret_temp_file
ok - test_present_but_empty_secret_is_rejected
ok - test_remote_payload_upload_replaces_a_permissive_file
ok - test_remote_backup_directory_is_private

22/22 tests passed
```

`bash tests/test-coreelec-report.sh`
```text
ok - test_all_expected_addon_versions_are_verified
ok - test_disabled_addon_is_failure
ok - test_unresolved_enables_are_named_in_the_report
ok - test_a_settled_run_reports_no_unresolved_enables
ok - test_missing_addon_is_failure
ok - test_addon_version_mismatch_is_failure
ok - test_active_skin_is_verified
ok - test_weather_provider_is_verified_only_when_configured
ok - test_timezone_cache_and_zoneinfo_are_verified
ok - test_regular_file_localtime_is_verified_by_content
ok - test_unexpected_device_date_output_is_advisory_not_fatal
ok - test_date_offset_reports_expected_and_observed_marks
ok - test_unreadable_verification_material_fails_without_exiting
ok - test_unreadable_manifest_rolls_back_the_deployment
ok - test_english_us_values_are_verified
ok - test_selected_subset_verifies_only_the_selected_addons
ok - test_emby_and_youtube_are_classified_manual
ok - test_configured_nextpvr_ha_and_pm4k_are_classified_configured
ok - test_missing_optional_values_are_classified_unconfigured
ok - test_report_lists_secret_presence_without_secret_values
ok - test_report_redacts_all_supplied_secret_values
ok - test_report_records_config_fingerprint_without_secrets
ok - test_report_lists_manual_actions_in_order
ok - test_report_states_addon_status_and_verification_per_addon
ok - test_report_keeps_subset_dependency_warning_explicit
ok - test_report_is_strict_key_value
ok - test_local_jsonrpc_unreachability_is_environmental_only
ok - test_report_fingerprint_tool_is_required_even_without_kodi
ok - test_verification_success_finalizes_and_commits
ok - test_verification_mismatch_is_fatal
ok - test_incomplete_rollback_is_fatal_with_recovery_path
ok - test_an_unanswered_probe_is_a_verification_failure
ok - test_failed_finalize_is_fatal
ok - test_remote_verify_script_passes_shell_syntax_check
ok - test_remote_verify_probe_reports_state_without_secrets
ok - test_remote_verify_probe_compares_a_copied_localtime_by_content
ok - test_remote_verify_probe_judges_device_date_against_the_requested_zone
ok - test_remote_verify_probe_fails_immediately_when_curl_is_missing
ok - test_remote_verify_probe_enables_a_disabled_addon_over_jsonrpc
ok - test_remote_verify_probe_converges_on_dependency_ordered_enables
ok - test_remote_verify_probe_fails_closed_on_an_addon_it_cannot_enable
ok - test_remote_verify_probe_keeps_going_when_an_enable_request_is_cut_off
ok - test_remote_verify_probe_reports_a_missing_addon
ok - test_remote_verify_probe_uses_a_private_curl_config_and_removes_it

44/44 tests passed
```

`bash tests/test-coreelec-artifacts.sh`
```text
ok - test_artifact_record_requires_four_fields
ok - test_artifact_record_rejects_non_https_url
ok - test_artifact_record_rejects_invalid_sha256
ok - test_artifact_record_accepts_kodi_version_punctuation
ok - test_artifact_record_still_rejects_shell_metacharacters_in_version
ok - test_artifact_record_rejects_version_starting_with_tilde
ok - test_matching_checksum_id_and_version_pass
ok - test_checksum_mismatch_fails
ok - test_addon_id_mismatch_fails
ok - test_addon_version_mismatch_fails
ok - test_multiple_top_level_directories_fail
ok - test_parent_traversal_entry_fails
ok - test_absolute_path_entry_fails
ok - test_duplicate_artifact_id_fails
ok - test_remote_deploy_stops_kodi_after_staging_validation
ok - test_remote_deploy_traps_kodi_restart
ok - test_remote_deploy_backs_up_each_replaced_path
ok - test_remote_deploy_extracts_into_staging_before_replace
ok - test_remote_deploy_records_manifest
ok - test_remote_deploy_has_rollback_for_replaced_paths
ok - test_remote_deploy_rejects_manifest_path_injection
ok - test_remote_deploy_uses_addon_xml_id_not_zip_directory_name
ok - test_remote_deploy_finalize_releases_rollback_material
ok - test_remote_deploy_rolls_back_automatically_when_a_step_fails
ok - test_remote_deploy_refuses_a_second_pending_transaction
ok - test_automatic_rollback_restores_settings_written_before_the_failure
ok - test_remote_stage_upload_replaces_a_stale_bundle
ok - test_rendered_remote_scripts_are_posix_clean
ok - test_the_public_key_program_installs_the_key_through_the_device_login_shell
ok - test_the_public_key_install_never_sends_a_quoted_program_in_the_ssh_argv
ok - test_addon_selection_defaults_to_the_locked_manifest
ok - test_addon_selection_filters_to_requested_ids
ok - test_addon_selection_rejects_an_unlocked_id
ok - test_deploy_script_embeds_the_fixture_transformer_verbatim
ok - test_provisioner_never_installs_addons_through_kodi
ok - test_a_malformed_transaction_pointer_never_arms_rollback
ok - test_a_stale_transaction_pointer_is_reported_when_it_is_cleared
ok - test_a_rollback_that_cannot_record_its_state_reports_failure
ok - test_the_remote_transaction_revalidates_every_plan_field
ok - test_the_transaction_never_changes_the_shared_backup_directory
ok - test_the_render_flag_is_an_alias_of_the_deploy_emitter
ok - test_the_artifact_bundle_is_staged_before_the_secret_payload
ok - test_a_failed_bundle_upload_never_uploads_the_secret_payload
ok - test_a_failed_deployment_discards_the_remote_secret_payload
ok - test_an_unlocked_addon_is_refused_before_any_remote_call
ok - test_a_default_run_survives_the_empty_addon_array_under_bash_3_2
ok - test_an_unreachable_target_fails_with_an_actionable_error
ok - test_a_keyed_but_failing_identity_read_fails_with_an_actionable_error
ok - test_the_audit_report_is_key_value_and_names_the_pending_transaction

49/49 tests passed
```

## Self-Review
- Confirmed the new service checks remain read-only; the tests verify no add-on settings files are modified.
- Confirmed secrets stay out of SSH argv and observable output in the new unauthorized-path tests.
- Confirmed NextPVR uses the pinned add-on's lower-case MD5 login derivation before session login.
- Confirmed PM4K and HA launches occur only after their prerequisite service checks succeed.
- Reviewed the committed diff and `git --no-pager show --stat --check --summary HEAD`; no whitespace or patch-format issues were reported.

## Concerns
- None.

## Fix Round 1/5

### Findings addressed
- Moved local secret-bearing Python helper inputs off argv and onto environment variables, including `coreelec_postdeploy_md5_hex`.
- Corrected direct `check_pm4k_local` absent-config behavior from `authorization-required` to `skipped`.
- Renamed `combined_md5` to `login_hash_input`.

### Covering tests
- `test_weather_check_accepts_config_and_entity_responses`
- `test_nextpvr_check_uses_the_configured_protocol_host_port_and_pin`
- `test_pm4k_local_check_requires_identity_and_token_authorized_root`
- `test_pm4k_local_check_skips_when_local_configuration_is_absent`
- `test_service_checks_do_not_modify_addon_settings`
- `bash tests/test-coreelec-addon-workflows.sh`
- `bash tests/test-coreelec-report.sh`

### RED
Command:
```bash
bash tests/test-coreelec-addon-workflows.sh
```

Output:
```text
ok - test_help_lists_supported_addons_and_interaction_levels
ok - test_default_run_never_starts_account_authorization
ok - test_requested_addon_must_be_in_the_pinned_manifest
ok - test_introspection_rejects_a_missing_required_method
ok - test_gui_guard_accepts_expected_window_and_control
ok - test_gui_guard_rejects_an_unexpected_window_without_sending_input
ok - test_rpc_request_ids_never_contain_secret_values
ok - test_report_contains_statuses_but_no_secret_values
not ok - test_weather_check_accepts_config_and_entity_responses
    # assert_not_contains: weather token must not leak into local python argv (needle=home-assistant-token-secret haystack=$'- home-assistant-token-secret\n\n-\n\n-\n\n-\n\n-\n\n- Addons.ExecuteAddon addons-executeaddon {"addonid":"weather.ha"}\n\n-\n\n- GET https://ha.example.lan:8123/api/config {"Authorization":"******","Accept":"application/json"}\n\n-\n\n-\n\n-\n\n-\n\n- home-assistant-token-secret\n\n- GET https://ha.example.lan:8123/api/states/weather.forecast_home {"Authorization":"******","Accept":"application/json"}\n\n-')
ok - test_weather_check_reports_unauthorized_without_echoing_token
not ok - test_nextpvr_check_uses_the_configured_protocol_host_port_and_pin
    # assert_not_contains: NextPVR PIN must not leak into local python argv (needle=2468 haystack=$'- GET https://nextpvr.example.lan:8867/service?method=session.initiate&ver=1.0&device=xbmc {}\n\n-\n\n-\n\n-\n\n- PVR.GetChannelGroups pvr-getchannelgroups {"channeltype":"tv"}\n\n-\n\n-\n\n-\n\n-\n\n-\n\n- 2468\n\n- :e82c4b19b8151ddc25d4d93baf7b908f:salt-456\n\n- GET https://nextpvr.example.lan:8867/service?method=session.login&sid=sid-123&md5=0eaf144b5f0da21157228964835736a6 {}\n\n-')
ok - test_nextpvr_check_requires_a_successful_session_login
not ok - test_pm4k_local_check_requires_identity_and_token_authorized_root
    # assert_not_contains: PM4K token must not leak into local python argv (needle=plex-token-secret haystack=$'- GET http://plex.example.lan:32400/identity {"Accept":"application/json"}\n\n-\n\n-\n\n- Addons.ExecuteAddon addons-executeaddon {"addonid":"script.plexmod"}\n\n-\n\n-\n\n-\n\n-\n\n-\n\n- plex-token-secret\n\n- GET http://plex.example.lan:32400/ {"Accept":"application/json","X-Plex-Token":"plex-token-secret"}\n\n-\n\n-')
not ok - test_pm4k_local_check_skips_when_local_configuration_is_absent
    # assert_contains: PM4K local check must skip when local mode is not configured (needle=workflow_status=skipped haystack=$'service.script.plexmod.failure=not-configured\nworkflow_status=authorization-required')
ok - test_service_checks_do_not_modify_addon_settings

11/15 tests passed
Failed: test_weather_check_accepts_config_and_entity_responses
test_nextpvr_check_uses_the_configured_protocol_host_port_and_pin
test_pm4k_local_check_requires_identity_and_token_authorized_root
test_pm4k_local_check_skips_when_local_configuration_is_absent
```

### GREEN
Command:
```bash
bash tests/test-coreelec-addon-workflows.sh
```

Output:
```text
ok - test_help_lists_supported_addons_and_interaction_levels
ok - test_default_run_never_starts_account_authorization
ok - test_requested_addon_must_be_in_the_pinned_manifest
ok - test_introspection_rejects_a_missing_required_method
ok - test_gui_guard_accepts_expected_window_and_control
ok - test_gui_guard_rejects_an_unexpected_window_without_sending_input
ok - test_rpc_request_ids_never_contain_secret_values
ok - test_report_contains_statuses_but_no_secret_values
ok - test_weather_check_accepts_config_and_entity_responses
ok - test_weather_check_reports_unauthorized_without_echoing_token
ok - test_nextpvr_check_uses_the_configured_protocol_host_port_and_pin
ok - test_nextpvr_check_requires_a_successful_session_login
ok - test_pm4k_local_check_requires_identity_and_token_authorized_root
ok - test_pm4k_local_check_skips_when_local_configuration_is_absent
ok - test_service_checks_do_not_modify_addon_settings

15/15 tests passed
```

### Verification
Command:
```bash
bash tests/test-coreelec-report.sh
```

Output:
```text
ok - test_all_expected_addon_versions_are_verified
ok - test_disabled_addon_is_failure
ok - test_unresolved_enables_are_named_in_the_report
ok - test_a_settled_run_reports_no_unresolved_enables
ok - test_missing_addon_is_failure
ok - test_addon_version_mismatch_is_failure
ok - test_active_skin_is_verified
ok - test_weather_provider_is_verified_only_when_configured
ok - test_timezone_cache_and_zoneinfo_are_verified
ok - test_regular_file_localtime_is_verified_by_content
ok - test_unexpected_device_date_output_is_advisory_not_fatal
ok - test_date_offset_reports_expected_and_observed_marks
ok - test_unreadable_verification_material_fails_without_exiting
ok - test_unreadable_manifest_rolls_back_the_deployment
ok - test_english_us_values_are_verified
ok - test_selected_subset_verifies_only_the_selected_addons
ok - test_emby_and_youtube_are_classified_manual
ok - test_configured_nextpvr_ha_and_pm4k_are_classified_configured
ok - test_missing_optional_values_are_classified_unconfigured
ok - test_report_lists_secret_presence_without_secret_values
ok - test_report_redacts_all_supplied_secret_values
ok - test_report_records_config_fingerprint_without_secrets
ok - test_report_lists_manual_actions_in_order
ok - test_report_states_addon_status_and_verification_per_addon
ok - test_report_keeps_subset_dependency_warning_explicit
ok - test_report_is_strict_key_value
ok - test_local_jsonrpc_unreachability_is_environmental_only
ok - test_report_fingerprint_tool_is_required_even_without_kodi
ok - test_verification_success_finalizes_and_commits
ok - test_verification_mismatch_is_fatal
ok - test_incomplete_rollback_is_fatal_with_recovery_path
ok - test_an_unanswered_probe_is_a_verification_failure
ok - test_failed_finalize_is_fatal
ok - test_remote_verify_script_passes_shell_syntax_check
ok - test_remote_verify_probe_reports_state_without_secrets
ok - test_remote_verify_probe_compares_a_copied_localtime_by_content
ok - test_remote_verify_probe_judges_device_date_against_the_requested_zone
ok - test_remote_verify_probe_fails_immediately_when_curl_is_missing
ok - test_remote_verify_probe_enables_a_disabled_addon_over_jsonrpc
ok - test_remote_verify_probe_converges_on_dependency_ordered_enables
ok - test_remote_verify_probe_fails_closed_on_an_addon_it_cannot_enable
ok - test_remote_verify_probe_keeps_going_when_an_enable_request_is_cut_off
ok - test_remote_verify_probe_reports_a_missing_addon
ok - test_remote_verify_probe_uses_a_private_curl_config_and_removes_it

44/44 tests passed
```

### Changed files
- `lib/coreelec-addon-workflows.sh`
- `tests/test-coreelec-addon-workflows.sh`
- `.superpowers/sdd/2026-09-06-coreelec-post-deployment-addon-configuration/task-2-report.md`

### Commit
- `fix: keep post-deployment secrets out of local python argv`
