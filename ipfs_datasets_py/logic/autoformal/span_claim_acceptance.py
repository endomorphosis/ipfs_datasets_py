"""Bounded T02 engineering evidence checks; no model, law or Lean admission.

The runner executes the existing complete private-native regression collection.
A caller must provide a live lease verifier. Offline verification additionally
requires an independently retained invocation binding, not report assertions.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

SCHEMA = "span-claim-engineering-acceptance/v1"
MANIFEST_SCHEMA = "span-claim-engineering-manifest/v1"
CRITERION = "OBLIGATION-F-T02"
MAX_BYTES = 2 * 1024 * 1024
TEST_MODULES = (
    "tests/unit/logic/autoformal/test_span_cache_claims.py",
    "tests/unit/duckdb_control/test_span_cache_claims_quack.py",
)
FALSE = dict(qualified=False, admitted=False, formalized=False, roundtrip_ok=False,
             legal_semantics_verified=False, model_executed=False, lake_executed=False,
             production_migration_verified=False, owner_authentication_conferred=False)
SOURCE_FILES = (
    "ipfs_datasets_py/logic/autoformal/span_cache.py",
    "ipfs_datasets_py/logic/autoformal/span_cache_claims.py",
    "ipfs_datasets_py/logic/autoformal/supervisor_queue.py",
    "ipfs_datasets_py/duckdb_control/span_cache_claims_quack.py",
    "ipfs_datasets_py/duckdb_control/span_cache_quack.py",
    "ipfs_datasets_py/duckdb_control/autoencoder_quack.py",
    "ipfs_datasets_py/duckdb_control/autoencoder_quack_wire.py",
    "ipfs_datasets_py/duckdb_control/autoencoder_registry.py",
    "ipfs_datasets_py/duckdb_control/connections.py",
    "ipfs_datasets_py/duckdb_control/contracts.py",
    "ipfs_datasets_py/duckdb_control/capabilities.py",
    "ipfs_datasets_py/ducklake/capabilities.py",
    "ipfs_datasets_py/ducklake/quack_catalog.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py",
    "ipfs_datasets_py/logic/autoformal/span_claim_acceptance.py",
    "scripts/ops/legal_ir/check_span_claim_acceptance.py",
    "scripts/ops/legal_ir/span_claim_acceptance_test.py",
    "pytest.ini", "conftest.py", "tests/conftest.py",
) + TEST_MODULES
# Exact observed collection for the published, private-native T02 regressions.
# Changes to tests require an explicit reviewed case inventory update.
EXPECTED_CASES = (
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_closed_worker_packets_cannot_change_assignment[ClaimSpansFenced-payload0]',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_closed_worker_packets_cannot_change_assignment[ClaimSpansFenced-payload1]',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_closed_worker_packets_cannot_change_assignment[ClaimSpansFenced-payload2]',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_closed_worker_packets_cannot_change_assignment[ReadClaimedSpanFenced-payload3]',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_closed_worker_packets_cannot_change_assignment[ReleaseSpansFenced-payload4]',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_closed_worker_packets_cannot_change_assignment[ResolveSpanOperation-payload5]',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_current_claim_fields_are_verified_by_native_owner[claim_token-forged-token]',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_current_claim_fields_are_verified_by_native_owner[fence-999]',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_current_claim_fields_are_verified_by_native_owner[source_revision-hub:cccccccccccccccccccccccccccccccccccccccc]',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_current_claim_fields_are_verified_by_native_owner[source_sha256-cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc]',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_expiry_is_structured_refusal_and_does_not_release_newer_claim',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_foreign_process_cannot_serve_bind_or_close_inherited_gateway',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_long_source_reply_refuses_without_truncating_original_span',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_mutation_requires_explicit_owner_profile_and_source_binding_is_not_rpc',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_native_facade_receipts_replay_and_resolve_exact_worker_payload',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_owner_source_revision_update_retires_old_claim_without_rewriting_history',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_owner_thread_identity_cannot_be_replaced',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_owner_tick_yields_even_when_producer_continuously_refills_queue[False]',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_owner_tick_yields_even_when_producer_continuously_refills_queue[True]',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_owner_timeout_cancels_unstarted_mutation',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_private_native_endpoint_cannot_add_worker_selected_source_or_sql',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_private_native_endpoint_claim_finish_resolve_and_sql_denials',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_two_private_worker_endpoints_share_one_native_catalog_owner',
    'tests/unit/duckdb_control/test_span_cache_claims_quack.py::test_worker_operation_namespace_does_not_replace_another_workers_receipt',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_baseexception_after_receipt_insert_rolls_back_receipt_and_outputs',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_baseexception_during_second_row_rolls_back_first_row_and_terms',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_binding_never_invents_missing_source_revision',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_caught_nested_failure_poison_rolls_back_successful_inner_mutation',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_closed_connection_refuses_before_database_access',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_command_bound_refuses_without_mutation',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_conflicting_operation_retry_cannot_change_rows_or_terms[code]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_conflicting_operation_retry_cannot_change_rows_or_terms[command]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_conflicting_operation_retry_cannot_change_rows_or_terms[paths]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_conflicting_operation_retry_cannot_change_rows_or_terms[result]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_conflicting_operation_retry_cannot_change_rows_or_terms[span_set]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_constitution_compile_cache_receipt_never_claims_roundtrip_or_formalization',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_deadline_boundary_blocks_new_operations[finish]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_deadline_boundary_blocks_new_operations[release]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_deadline_crossed_after_receipt_insert_rolls_back_every_native_table[claim]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_deadline_crossed_after_receipt_insert_rolls_back_every_native_table[finish]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_deadline_crossed_after_receipt_insert_rolls_back_every_native_table[release]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_deadline_crossed_during_output_work_rolls_back_all_result_and_term_writes',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_duplicate_batch_ids_refuse_before_writes[bind]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_duplicate_batch_ids_refuse_before_writes[claim]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_duplicate_batch_ids_refuse_before_writes[finish]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_duplicate_batch_ids_refuse_before_writes[release]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_exact_finish_retry_remains_original_after_expiry',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_exact_release_retry_remains_original_after_expiry',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_existing_text_limits_refuse_completion_before_row_or_term_changes',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_expired_claim_can_be_reclaimed_but_old_work_cannot_finish',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_explicit_sha256_revision_is_supported_without_derivation',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_failure_after_result_insert_rolls_back_result_rows_terms_and_receipt',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_foreign_thread_cannot_use_original_native_connection',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[finish-claim_token-wrong-token]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[finish-claim_worker-wrong-worker]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[finish-expires_at-True]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[finish-fence-999]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[finish-legal_id-usc:us:9:999]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[finish-owner_generation-999]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[finish-owner_generation-True]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[finish-schema-wrong-schema]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[finish-source_revision-hub:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[finish-source_sha256-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[finish-source_span_id-unknown]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[release-claim_token-wrong-token]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[release-claim_worker-wrong-worker]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[release-expires_at-True]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[release-fence-999]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[release-legal_id-usc:us:9:999]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[release-owner_generation-999]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[release-owner_generation-True]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[release-schema-wrong-schema]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[release-source_revision-hub:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[release-source_sha256-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_forged_claim_refuses_without_any_table_mutation[release-source_span_id-unknown]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_fork_identity_is_rejected_before_database_access',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_full_result_history_survives_native_owner_restart',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_full_result_ledger_preserves_rule_repair_and_diagnostics_on_both_dispositions[False]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_full_result_ledger_preserves_rule_repair_and_diagnostics_on_both_dispositions[True]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_full_result_read_requires_exact_original_payload_and_detects_tampering',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_full_utf8_text_is_preserved_and_decompilation_limit_refuses_whole_batch',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_historical_retry_survives_legitimate_native_restart[claim]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_historical_retry_survives_legitimate_native_restart[finish]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_historical_retry_survives_legitimate_native_restart[release]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_inconsistent_cached_source_bytes_hash_cannot_be_bound',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_invalid_lease_refuses_without_mutation[-1]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_invalid_lease_refuses_without_mutation[0]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_invalid_lease_refuses_without_mutation[20]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_invalid_lease_refuses_without_mutation[86401]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_invalid_lease_refuses_without_mutation[True]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_invalid_lease_refuses_without_mutation[inf]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_invalid_lease_refuses_without_mutation[nan]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_later_native_connection_fences_older_generation',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_legacy_release_does_not_let_old_fenced_claim_finish',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_legacy_source_edit_cannot_silently_carry_forward_source_binding',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_legacy_unknown_claim_is_not_replaced_by_fenced_owner',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_mixed_finish_updates_rows_terms_and_receipt_atomically',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_mutable_or_unpinned_revision_refuses[AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_mutable_or_unpinned_revision_refuses[aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_mutable_or_unpinned_revision_refuses[derived-source-version]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_mutable_or_unpinned_revision_refuses[latest]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_mutable_or_unpinned_revision_refuses[main]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_native_generation_transition_conflicts_with_inflight_completion_owner_row',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_nonfinite_clock_after_output_work_rolls_back_every_native_table',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_nonfinite_or_non_numeric_owner_clock_refuses[1000]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_nonfinite_or_non_numeric_owner_clock_refuses[True]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_nonfinite_or_non_numeric_owner_clock_refuses[inf]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_nonfinite_or_non_numeric_owner_clock_refuses[nan]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_owner_uses_exact_native_connection_and_one_facade',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_read_source_requires_current_live_claim',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_receipt_without_complete_result_history_is_explicitly_unavailable',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_release_and_reclaim_fences_prior_token',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_result_lookup_refuses_oversized_full_response_without_truncation',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_source_rebinding_conflict_is_whole_batch_atomic',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_source_revision_cas_rebinding_retires_claims_and_preserves_exact_retries',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_unexpired_lease_prevents_another_claim',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_worker_cannot_smuggle_source_or_authority_fields[compiler_status]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_worker_cannot_smuggle_source_or_authority_fields[formalized]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_worker_cannot_smuggle_source_or_authority_fields[roundtrip_ok]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_worker_cannot_smuggle_source_or_authority_fields[source_span_id]',
    'tests/unit/logic/autoformal/test_span_cache_claims.py::test_worker_cannot_smuggle_source_or_authority_fields[text]',
)

SCENARIOS = {
    "source_and_current_claim_fencing": ("test_forged_claim_refuses", "test_binding_never_invents", "test_mutable_or_unpinned", "test_legacy_source_edit", "test_current_claim_fields"),
    "atomic_rows_terms_results_and_receipts": ("test_mixed_finish", "test_baseexception", "test_caught_nested", "test_failure_after_result"),
    "historical_exact_retry_and_conflict": ("test_exact_finish_retry", "test_exact_release_retry", "test_historical_retry", "test_conflicting_operation", "test_full_result_history"),
    "deadline_and_owner_generation": ("test_deadline_boundary", "test_deadline_crossed", "test_native_generation_transition", "test_later_native_connection", "test_foreign_thread", "test_fork_identity"),
    "source_rebinding_and_retained_outputs": ("test_source_revision_cas", "test_full_result_ledger", "test_full_result_read", "test_source_rebinding_conflict"),
    "actual_scoped_native_quack": ("test_private_native_endpoint", "test_two_private_worker_endpoints", "test_worker_operation_namespace", "test_owner_tick_yields", "test_owner_timeout"),
    "bounds_and_non_admission": ("test_constitution_compile", "test_worker_cannot_smuggle", "test_full_utf8", "test_command_bound", "test_result_lookup_refuses", "test_long_source_reply"),
}


class SpanClaimAcceptanceError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise SpanClaimAcceptanceError(message)


def raw(value):
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise SpanClaimAcceptanceError("finite UTF-8 JSON required") from exc
    need(len(result) <= MAX_BYTES, "acceptance material exceeds byte bound")
    return result


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def closed(value, fields, label):
    need(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def load_json(data):
    need(type(data) is bytes and len(data) <= MAX_BYTES, "bounded JSON bytes required")
    def pairs(rows):
        result = {}
        for key, value in rows:
            need(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def nonfinite(value):
        raise SpanClaimAcceptanceError("nonfinite JSON constant")
    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_constant=nonfinite)
        raw(value)
        return value
    except (ValueError, UnicodeError) as exc:
        raise SpanClaimAcceptanceError("invalid bounded JSON") from exc


def scenario_manifest():
    return [{"scenario_id": key, "required_cases": sorted(case for case in EXPECTED_CASES
             if any(case.split("::", 1)[1].startswith(prefix) for prefix in prefixes))}
            for key, prefixes in sorted(SCENARIOS.items())]


def validate_lease(lease, *, expected=None):
    closed(lease, ("lease_id", "policy_sha256", "lane", "owner_pid", "request_id",
        "cpu_slots", "memory_mb", "child_process_slots"), "native lease observation")
    need(type(lease["lease_id"]) is str and lease["lease_id"]
        and type(lease["policy_sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", lease["policy_sha256"])
        and type(lease["request_id"]) is str and lease["request_id"]
        and lease["lane"] == "validation" and type(lease["owner_pid"]) is int and lease["owner_pid"] > 0
        and type(lease["cpu_slots"]) is int and lease["cpu_slots"] >= 1
        and type(lease["memory_mb"]) is int and lease["memory_mb"] >= 1536
        and type(lease["child_process_slots"]) is int and lease["child_process_slots"] >= 2,
        "missing native validation reservation")
    need(expected is None or lease == expected, "native lease binding changed")
    return lease


def source_pins(root):
    root = Path(root).resolve()
    result = []
    for name in SOURCE_FILES:
        path = root / name
        need(path.is_file() and path.resolve().is_relative_to(root) and not path.is_symlink(), "missing or aliased producer source")
        data = path.read_bytes()
        need(len(data) <= 4 * MAX_BYTES, "individual producer source exceeds bound")
        result.append(dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
    return result


def validate_manifest(value):
    closed(value, ("schema", "criterion_key", "task_cid", "validation_key", "repository_commit",
        "declared_native_tree_id", "source_pins", "test_modules", "expected_cases", "scenarios"), "engineering manifest")
    need(value["schema"] == MANIFEST_SCHEMA and value["criterion_key"] == CRITERION, "wrong engineering criterion/schema")
    need(type(value["repository_commit"]) is str and re.fullmatch(r"[0-9a-f]{40}", value["repository_commit"]), "exact repository commit required")
    for name in ("task_cid", "validation_key", "declared_native_tree_id"):
        need(type(value[name]) is str and 0 < len(value[name]) <= 512, "explicit native binding identity required")
    need(value["test_modules"] == list(TEST_MODULES) and value["expected_cases"] == list(EXPECTED_CASES), "complete exact native test collection required")
    need(value["scenarios"] == scenario_manifest() and all(x["required_cases"] for x in value["scenarios"]), "complete predeclared scenario coverage required")
    pins = value["source_pins"]
    need(type(pins) is list and len(pins) == len(SOURCE_FILES), "complete producer source pins required")
    for pin, name in zip(pins, SOURCE_FILES):
        closed(pin, ("path", "bytes", "sha256"), "source pin")
        need(pin["path"] == name and type(pin["bytes"]) is int and pin["bytes"] > 0
            and type(pin["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]), "invalid exact source pin")
    raw(value)
    return value


def parse_junit(data):
    need(type(data) is bytes and len(data) <= MAX_BYTES and b"<!DOCTYPE" not in data.upper()
         and b"<!ENTITY" not in data.upper(), "bounded plain JUnit required")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise SpanClaimAcceptanceError("invalid JUnit") from exc
    need(root.tag in ("testsuite", "testsuites"), "JUnit root must be a suite collection")
    cases = root.findall(".//testcase")
    seen = []
    for case in cases:
        name = case.get("name", "")
        classname = case.get("classname", "")
        need(name and classname, "JUnit testcase identity missing")
        seen.append(classname.replace(".", "/") + ".py::" + name)
        need(not any(case.find(tag) is not None for tag in ("failure", "error", "skipped")), "native testcase did not pass")
    need(len(seen) == len(set(seen)) and sorted(seen) == list(EXPECTED_CASES), "duplicate/missing/unexpected native testcase")
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    need(suites, "JUnit suites missing")
    declared = 0
    for suite in suites:
        need(suite.get("failures") == "0" and suite.get("errors") == "0" and suite.get("skipped") == "0", "native JUnit suite has failure/error/skip")
        count = suite.get("tests", "")
        need(count.isdigit(), "JUnit declared collection count missing")
        declared += int(count)
    need(declared == len(cases), "JUnit declared/actual collection differs")
    return seen


def verify_report(manifest, report, junit_bytes, event_bytes, *, expected_invocation):
    """Check observations against an independently retained live invocation.

    An offline caller must authenticate/custody-bind these bytes separately;
    repaired hashes or this mechanical verifier never supply owner trust.
    """
    validate_manifest(manifest)
    closed(report, ("schema", "manifest_sha256", "invocation", "pins_before", "pins_after", "returncode",
        "junit", "events", "lease_before", "lease_after", "elapsed_seconds", "cleanup_complete", *FALSE), "live run report")
    need(report["schema"] == SCHEMA and report["manifest_sha256"] == digest(manifest), "report/manifest identity differs")
    need(report["invocation"] == expected_invocation, "independent invocation binding differs")
    closed(expected_invocation, ("run_id", "repository_root", "repository_commit", "argv",
        "manifest_sha256", "lease_id", "policy_sha256", "resource_request_id"), "retained invocation")
    need(expected_invocation["repository_commit"] == manifest["repository_commit"], "invocation source commit differs")
    need(expected_invocation["manifest_sha256"] == digest(manifest), "independent manifest binding differs")
    for lease in (report["lease_before"], report["lease_after"]):
        validate_lease(lease, expected=report["lease_before"])
        need(lease["lease_id"] == expected_invocation["lease_id"]
            and lease["policy_sha256"] == expected_invocation["policy_sha256"]
            and lease["request_id"] == expected_invocation["resource_request_id"]
            and lease["lane"] == "validation" and type(lease["owner_pid"]) is int and lease["owner_pid"] > 0
            and type(lease["cpu_slots"]) is int and lease["cpu_slots"] >= 1
            and type(lease["memory_mb"]) is int and lease["memory_mb"] >= 1536
            and type(lease["child_process_slots"]) is int and lease["child_process_slots"] >= 2,
            "missing/mismatched native validation reservation")
    need(all(report[name] is False for name in FALSE), "report attempts authority promotion")
    need(report["returncode"] == 0 and type(report["returncode"]) is int and report["cleanup_complete"] is True, "live runner did not complete cleanly")
    need(type(report["elapsed_seconds"]) in (int, float) and math.isfinite(report["elapsed_seconds"])
        and 0 <= report["elapsed_seconds"] <= 180, "invalid native elapsed/deadline observation")
    need(report["pins_before"] == manifest["source_pins"] == report["pins_after"], "producer/test source drift")
    for descriptor, data in ((report["junit"], junit_bytes), (report["events"], event_bytes)):
        closed(descriptor, ("bytes", "sha256"), "evidence reference")
        need(type(descriptor["bytes"]) is int and descriptor["bytes"] == len(data)
            and descriptor["sha256"] == hashlib.sha256(data).hexdigest(), "forged evidence reference")
    cases = parse_junit(junit_bytes)
    events = load_json(event_bytes)
    closed(events, ("run_id", "phases", "origins", "duckdb_version", "transport_schema", "native_storage_opt_in"), "execution evidence")
    need(events["run_id"] == expected_invocation["run_id"] and events["native_storage_opt_in"] == "1", "native run identity/opt-in differs")
    need(events["duckdb_version"] == "1.5.5" and events["transport_schema"] == "ipfs_datasets_py/autoencoder-quack-prototype@1", "native engine/transport identity differs")
    phases = events["phases"]
    need(type(phases) is list and len(phases) == 3 * len(EXPECTED_CASES), "complete independent pytest phase stream required")
    by_case = Counter()
    for phase in phases:
        closed(phase, ("nodeid", "when", "outcome"), "pytest phase")
        need(phase["nodeid"] in EXPECTED_CASES and phase["when"] in ("setup", "call", "teardown") and phase["outcome"] == "passed", "invalid/missing/skipped native test phase")
        by_case[(phase["nodeid"], phase["when"])] += 1
    need(all(by_case[(case, when)] == 1 for case in EXPECTED_CASES for when in ("setup", "call", "teardown")), "duplicate/missing native test phase")
    expected_origins = {x["path"]: x for x in manifest["source_pins"] if x["path"].startswith("ipfs_datasets_py/")}
    origins = events["origins"]
    need(type(origins) is list and origins, "actual imported source origins required")
    seen = set()
    for origin in origins:
        closed(origin, ("path", "bytes", "sha256"), "import origin")
        need(origin["path"] not in seen and origin["path"] in expected_origins and origin == expected_origins[origin["path"]], "forged/drifted/duplicate source origin")
        seen.add(origin["path"])
    for required in ("ipfs_datasets_py/logic/autoformal/span_cache.py", "ipfs_datasets_py/logic/autoformal/span_cache_claims.py", "ipfs_datasets_py/duckdb_control/span_cache_claims_quack.py", "ipfs_datasets_py/duckdb_control/autoencoder_quack.py"):
        need(required in seen, "required native producer was not imported")
    return dict(schema=SCHEMA, criterion_key=CRITERION, validation_key=manifest["validation_key"],
        task_cid=manifest["task_cid"], declared_native_tree_id=manifest["declared_native_tree_id"],
        manifest_sha256=digest(manifest), report_sha256=digest(report), engineering_gate_passed=True,
        actual_test_count=len(cases), actual_test_skips=0, scenario_ids=[x["scenario_id"] for x in manifest["scenarios"]],
        scope="complete private-native transactional/transport engineering regressions; independent native owner material and production migration remain required", **FALSE)


_OBSERVER = '''import hashlib, json, os, pathlib, sys
phases = []
def pytest_runtest_logreport(report):
    phases.append(dict(nodeid=report.nodeid, when=report.when, outcome=report.outcome))
def pytest_sessionfinish(session, exitstatus):
    root = pathlib.Path(os.environ['IPFS_DATASETS_T02_OBSERVER_ROOT']).resolve()
    origins = []
    for rel in json.loads(os.environ['IPFS_DATASETS_T02_OBSERVER_FILES']):
        if not rel.startswith('ipfs_datasets_py/'):
            continue
        name = rel[:-3].replace('/', '.')
        module = sys.modules.get(name)
        if module is None:
            continue
        path = pathlib.Path(module.__file__).resolve()
        if path != (root / rel).resolve():
            raise RuntimeError('native producer import escaped declared tree')
        data = path.read_bytes()
        origins.append(dict(path=rel, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
    import duckdb
    from ipfs_datasets_py.duckdb_control import autoencoder_quack
    value = dict(run_id=os.environ['IPFS_DATASETS_T02_OBSERVER_RUN'], phases=phases, origins=origins,
        duckdb_version=duckdb.__version__, transport_schema=autoencoder_quack.SCHEMA,
        native_storage_opt_in=os.environ.get('IPFS_DATASETS_RUN_NATIVE_STORAGE_PROBE'))
    with open(os.environ['IPFS_DATASETS_T02_OBSERVER_OUTPUT'], 'x') as stream:
        json.dump(value, stream, sort_keys=True, separators=(',', ':'), allow_nan=False)
'''


def _head(root):
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    return result.stdout.strip()


def _command(runtime, junit_path):
    return [sys.executable, "-B", "-m", "pytest", "-c", "pytest.ini", "-o", "addopts=",
        "-o", "cache_dir=" + str(runtime / "cache"),
        "--import-mode=importlib", "--strict-markers", "--run-network", "-q",
        "-p", "anyio.pytest_plugin", "-p", "pytest_asyncio.plugin",
        "-p", "t02_native_observer", "--basetemp", str(runtime / "pytest"),
        "--junitxml", str(junit_path), *TEST_MODULES]


def _failure_record(output, manifest, invocation, before, after, lease_before, lease_after,
                    returncode, elapsed, cleanup_complete, error_type):
    evidence = {}
    for name in ("native-tests.junit.xml", "native-events.json"):
        path = output / name
        if not path.is_file():
            evidence[name] = None
            continue
        size = path.stat().st_size
        if size > MAX_BYTES:
            evidence[name] = dict(bytes=size, sha256=None, refusal="evidence_exceeds_bound")
            continue
        data = path.read_bytes()
        need(len(data) <= MAX_BYTES, "failure evidence changed beyond bound")
        evidence[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    return dict(schema="span-claim-engineering-failure/v1", status="blocked_engineering_checker",
        manifest_sha256=digest(manifest), invocation=invocation, pins_before=before, pins_after=after,
        lease_before=lease_before, lease_after=lease_after, returncode=returncode,
        elapsed_seconds=elapsed, cleanup_complete=cleanup_complete, evidence=evidence,
        error_type=error_type, synthetic_junit_or_phases_created=False, **FALSE)


def run_private_checks(root, manifest, output, *, lease_verifier):
    """Execute the full native collection under an explicitly verified lease.

    ``lease_verifier.verify()`` must actually authenticate the caller's active
    native reservation. No default checker, boolean opt-out or new scheduler
    policy is supplied here. The CLI provides the concrete native verifier.
    """
    validate_manifest(manifest)
    need(lease_verifier is not None and callable(getattr(lease_verifier, "verify", None)), "explicit native lease verifier required")
    root, output = Path(root).resolve(), Path(output).resolve()
    need(not output.exists() and not output.parent.is_symlink(), "fresh owner output directory required")
    need(_head(root) == manifest["repository_commit"], "repository commit differs before execution")
    before = source_pins(root)
    need(before == manifest["source_pins"], "source pins differ before execution")
    first_lease = validate_lease(lease_verifier.verify())
    output.mkdir(parents=True)
    run_id = uuid.uuid4().hex
    child = None
    started = time.monotonic()
    invocation, after, last_lease, runtime = None, None, None, None
    try:
        with tempfile.TemporaryDirectory(prefix="t02-private-native-", dir=output) as temporary:
            runtime = Path(temporary)
            plugin = runtime / "t02_native_observer.py"
            plugin.write_text(_OBSERVER, encoding="utf-8")
            junit_path, event_path = output / "native-tests.junit.xml", output / "native-events.json"
            command = _command(runtime, junit_path)
            environment = dict(os.environ)
            # Keep verified explicit dependency roots supplied by the launcher,
            # while isolating code, bytecode, temp inputs and pytest cache state.
            environment.pop("PYTEST_PLUGINS", None)
            environment.update(PYTEST_ADDOPTS="", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONOPTIMIZE="0",
                PYTHONPYCACHEPREFIX=str(runtime / "pyc"),
                PYTHONPATH=os.pathsep.join([str(runtime), str(root), environment.get("PYTHONPATH", "")]),
                IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS="0", IPFS_DATASETS_RUN_NATIVE_STORAGE_PROBE="1",
                IPFS_DATASETS_T02_OBSERVER_ROOT=str(root), IPFS_DATASETS_T02_OBSERVER_RUN=run_id,
                IPFS_DATASETS_T02_OBSERVER_FILES=json.dumps(list(SOURCE_FILES)),
                IPFS_DATASETS_T02_OBSERVER_OUTPUT=str(event_path),
                CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
                OPENBLAS_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
            invocation = dict(run_id=run_id, repository_root=str(root), repository_commit=manifest["repository_commit"],
                argv=command, manifest_sha256=digest(manifest), lease_id=first_lease["lease_id"], policy_sha256=first_lease["policy_sha256"],
                resource_request_id=first_lease["request_id"])
            # Retain the launcher's observation independently of the child report.
            (output / "invocation.json").write_bytes(raw(invocation) + b"\n")
            try:
                with (output / "stdout.log").open("xb") as stdout, (output / "stderr.log").open("xb") as stderr:
                    child = subprocess.Popen(command, cwd=root, env=environment, stdin=subprocess.DEVNULL,
                        stdout=stdout, stderr=stderr, start_new_session=True)
                    while child.poll() is None:
                        need(time.monotonic() - started < 180, "bounded native checker deadline exceeded")
                        validate_lease(lease_verifier.verify(), expected=first_lease)
                        time.sleep(0.25)
                last_lease = validate_lease(lease_verifier.verify(), expected=first_lease)
            finally:
                if child is not None and child.poll() is None:
                    # Only the newly created, unreaped process group is owned here.
                    import signal
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=10)
            need(_head(root) == manifest["repository_commit"], "repository changed during execution")
            after = source_pins(root)
            junit_bytes = junit_path.read_bytes()
            event_bytes = event_path.read_bytes()
            need(len(junit_bytes) <= MAX_BYTES and len(event_bytes) <= MAX_BYTES, "native evidence exceeds byte bound")
            report = dict(schema=SCHEMA, manifest_sha256=digest(manifest), invocation=invocation,
                pins_before=before, pins_after=after, returncode=child.returncode,
                junit=dict(bytes=len(junit_bytes), sha256=hashlib.sha256(junit_bytes).hexdigest()),
                events=dict(bytes=len(event_bytes), sha256=hashlib.sha256(event_bytes).hexdigest()),
                lease_before=first_lease, lease_after=last_lease, elapsed_seconds=time.monotonic()-started,
                cleanup_complete=False, **FALSE)
        report["cleanup_complete"] = True
        (output / "execution-report.json").write_bytes(raw(report) + b"\n")
        checked = verify_report(manifest, report, junit_bytes, event_bytes, expected_invocation=invocation)
        (output / "checked-report.json").write_bytes(raw(checked) + b"\n")
        return checked
    except BaseException as error:
        try:
            after = source_pins(root)
        except Exception:
            after = None
        record = _failure_record(output, manifest, invocation, before, after,
            first_lease, last_lease, None if child is None else child.returncode,
            time.monotonic()-started, runtime is None or not runtime.exists(), type(error).__name__)
        with (output / "failure-execution-report.json").open("xb") as stream:
            stream.write(raw(record) + b"\n")
        raise
