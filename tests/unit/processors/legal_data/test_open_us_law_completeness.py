"""Unit tests for the exhaustive 50-state-plus-DC completeness oracle (OUL-003).

Acceptance: Completeness requires exact jurisdiction set equality, closed
bundle or pagination frontiers, zero failed-final units, replayable
response hashes, no caps or fixture transports, and aggregate-to-
jurisdiction key and digest equality.
"""

from __future__ import annotations

import copy

import pytest
from jsonschema import Draft202012Validator

from ipfs_datasets_py.processors.legal_data.open_us_law_completeness import (
    ALL_GATES,
    CANONICAL_JURISDICTIONS,
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
    FAMILY_KEY_FIELDS,
    FORBIDDEN_DEFAULT_JURISDICTIONS,
    GOAL_ID,
    PROGRAM_ID,
    RECEIPT_SCHEMA_VERSION,
    SCHEMA_VERSION,
    TASK_ID,
    CompletenessAdmissionError,
    FindingKind,
    JurisdictionSetError,
    ReceiptSchemaError,
    canonical_jurisdiction_codes,
    closed_jurisdiction_receipt,
    compute_aggregate_body_digest,
    compute_aggregate_frontier_digest,
    compute_aggregate_key_digest,
    evaluate_aggregate_receipt,
    evaluate_completion_receipt,
    evaluate_full_scrape_receipt,
    evaluate_jurisdiction_receipt,
    evaluate_jurisdiction_set_receipt,
    exact_51_aggregate_receipt,
    exact_51_manifest,
    is_forbidden_default_jurisdiction,
    is_opt_in_dc_policy,
    load_receipt_schema,
    normalize_postal_code,
    receipt_schema_path,
    reconcile_disposition,
    require_complete,
    require_schema_valid,
    sha256_text,
    union_jurisdiction_keys,
    validate_jurisdiction_set,
    validate_receipt_schema,
)


# ---------------------------------------------------------------------------
# Schema / sealed set
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "open-us-law-completeness-oracle-v1"
    assert RECEIPT_SCHEMA_VERSION == "open-us-law-full-scrape-receipt-v1"
    assert TASK_ID == "OUL-003"
    assert GOAL_ID == "OUL-G010"
    assert PROGRAM_ID == "open-us-law-reindex-v1"
    assert EXPECTED_JURISDICTION_COUNT == 51
    assert len(ALL_GATES) >= 8


def test_canonical_jurisdiction_set_is_exact_51_including_dc() -> None:
    codes = canonical_jurisdiction_codes()
    assert len(codes) == 51
    assert len(set(codes)) == 51
    assert codes.count("DC") == 1
    assert codes[-1] == "DC"
    assert set(codes) == CANONICAL_JURISDICTIONS
    assert set(CANONICAL_JURISDICTION_ORDER) == CANONICAL_JURISDICTIONS
    assert not (set(codes) & FORBIDDEN_DEFAULT_JURISDICTIONS)
    validate_jurisdiction_set(codes)


def test_validate_jurisdiction_set_rejects_missing_extra_pr_and_duplicates() -> None:
    codes = list(canonical_jurisdiction_codes())
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(codes[:-1])
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(codes + ["PR"])
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(codes + ["US"])
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(codes + ["AL"])


def test_normalize_postal_code_rejects_unknown_and_forbidden() -> None:
    assert normalize_postal_code("or") == "OR"
    with pytest.raises(JurisdictionSetError):
        normalize_postal_code("XX")
    with pytest.raises(JurisdictionSetError):
        normalize_postal_code("PR")
    with pytest.raises(JurisdictionSetError):
        normalize_postal_code("FED")
    assert is_forbidden_default_jurisdiction("PR")
    assert is_forbidden_default_jurisdiction("US")
    assert not is_forbidden_default_jurisdiction("DC")


def test_receipt_schema_file_is_valid_draft_2020_12() -> None:
    path = receipt_schema_path()
    assert path.is_file(), f"missing schema: {path}"
    schema = load_receipt_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "Open US Law Full Scrape Receipt v1"
    Draft202012Validator.check_schema(schema)


# ---------------------------------------------------------------------------
# Disposition arithmetic
# ---------------------------------------------------------------------------


def test_reconcile_disposition_ok_and_mismatch() -> None:
    ok, detail = reconcile_disposition(
        {
            "discovered": 10,
            "fetched": 8,
            "excluded": 1,
            "quarantined": 1,
            "failed_final": 0,
            "duplicates": 2,
        }
    )
    assert ok is True
    assert "reconciles" in detail

    bad, bad_detail = reconcile_disposition(
        {
            "discovered": 100,
            "fetched": 50,
            "excluded": 10,
            "quarantined": 5,
            "failed_final": 0,
        }
    )
    assert bad is False
    assert "discovered=100" in bad_detail


# ---------------------------------------------------------------------------
# Closed builders pass schema + oracle
# ---------------------------------------------------------------------------


def test_closed_pagination_receipt_passes_oracle_and_schema() -> None:
    receipt = closed_jurisdiction_receipt("MN", frontier_method="pagination")
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.status == "pass"
    assert verdict.complete is True
    assert verdict.admitted is True
    assert verdict.kinds == ()
    assert verdict.findings == ()
    require_complete(receipt, kind="jurisdiction")
    validate_receipt_schema(receipt)


def test_closed_bundle_receipt_passes_oracle_and_schema() -> None:
    receipt = closed_jurisdiction_receipt("OR", frontier_method="bundle")
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is True
    assert verdict.kinds == ()
    validate_receipt_schema(receipt)


def test_exact_51_aggregate_passes_oracle_and_schema() -> None:
    receipt = exact_51_aggregate_receipt()
    assert len(receipt["jurisdictions"]) == 51
    assert receipt["jurisdictions"][-1] == "DC"
    assert receipt["dc_count"] == 1
    assert "PR" not in receipt["jurisdictions"]
    verdict = evaluate_aggregate_receipt(receipt)
    assert verdict.complete is True, verdict.kinds
    assert verdict.kinds == ()
    validate_receipt_schema(receipt)
    require_schema_valid(receipt)


# ---------------------------------------------------------------------------
# Exact set / DC / PR-federal
# ---------------------------------------------------------------------------


def test_rejects_subset_manifest() -> None:
    subset = exact_51_aggregate_receipt(
        jurisdictions=["CA", "OR", "WA"],
        is_complete=True,
    )
    verdict = evaluate_aggregate_receipt(subset)
    assert verdict.complete is False
    assert "subset_manifest" in verdict.kinds
    assert "jurisdiction_set_mismatch" in verdict.kinds


def test_rejects_opt_in_dc() -> None:
    opt_in = exact_51_aggregate_receipt(
        include_dc=False,
        dc_policy="opt_in",
        is_complete=True,
    )
    opt_in["dc_optional"] = True
    assert is_opt_in_dc_policy(opt_in) is True
    verdict = evaluate_jurisdiction_set_receipt(opt_in)
    assert verdict.complete is False
    assert "opt_in_dc" in verdict.kinds
    assert "jurisdiction_set_mismatch" in verdict.kinds or "subset_manifest" in verdict.kinds


def test_rejects_pr_and_federal_in_default_set() -> None:
    codes = list(canonical_jurisdiction_codes()) + ["PR"]
    verdict = evaluate_jurisdiction_set_receipt({"jurisdictions": codes, "status": "success"})
    assert verdict.complete is False
    assert "pr_or_federal_in_default" in verdict.kinds
    assert "jurisdiction_set_mismatch" in verdict.kinds

    single = closed_jurisdiction_receipt("PR")
    single_verdict = evaluate_jurisdiction_receipt(single)
    assert single_verdict.complete is False
    assert "pr_or_federal_in_default" in single_verdict.kinds


def test_rejects_dc_counted_more_than_once() -> None:
    codes = list(canonical_jurisdiction_codes())
    codes.append("DC")
    verdict = evaluate_jurisdiction_set_receipt(
        {"jurisdictions": codes, "dc_count": 2, "includes_dc": True}
    )
    assert verdict.complete is False
    assert "dc_not_exactly_once" in verdict.kinds or "jurisdiction_set_mismatch" in verdict.kinds


def test_rejects_any_jurisdiction_set_other_than_exact_51() -> None:
    ok = evaluate_jurisdiction_set_receipt(
        {
            "jurisdictions": list(canonical_jurisdiction_codes()),
            "includes_dc": True,
            "dc_count": 1,
            "dc_policy": "required",
        }
    )
    assert ok.status == "pass"
    assert ok.kinds == ()

    extra = evaluate_jurisdiction_set_receipt(
        {
            "jurisdictions": list(canonical_jurisdiction_codes()) + ["GU"],
            "status": "success",
        }
    )
    assert extra.status == "fail"
    assert "jurisdiction_set_mismatch" in extra.kinds

    missing = evaluate_jurisdiction_set_receipt(
        {
            "jurisdictions": list(canonical_jurisdiction_codes())[:-1],
            "includes_dc": False,
            "status": "success",
        }
    )
    assert missing.status == "fail"
    assert "jurisdiction_set_mismatch" in missing.kinds


# ---------------------------------------------------------------------------
# Frontiers
# ---------------------------------------------------------------------------


def test_rejects_open_pagination_frontier() -> None:
    receipt = closed_jurisdiction_receipt("FL", frontier_method="pagination")
    receipt["frontier"]["closed"] = False
    receipt["frontier"]["pagination_closed"] = False
    receipt["frontier"]["enumerator_closed"] = False
    receipt["frontier"]["unvisited_continuation_links"] = ["https://example/next"]
    receipt["frontier"]["visited_index_units"] = 1
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    for kind in (
        "open_frontier",
        "pagination_frontier_open",
        "enumerator_not_closed",
        "unvisited_continuation_links",
        "success_without_closure",
    ):
        assert kind in verdict.kinds


def test_rejects_open_bundle_frontier() -> None:
    receipt = closed_jurisdiction_receipt("TX", frontier_method="bundle")
    receipt["frontier"]["closed"] = False
    receipt["frontier"]["bundle_closed"] = False
    receipt["frontier"]["remaining_bundle_members"] = ["volume-9"]
    receipt["frontier"]["enumerated_member_count"] = 1
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "bundle_frontier_open" in verdict.kinds
    assert "open_frontier" in verdict.kinds


def test_either_closed_bundle_or_pagination_is_sufficient() -> None:
    pagination = closed_jurisdiction_receipt("CA", frontier_method="pagination")
    pagination["frontier"]["bundle_closed"] = False
    assert evaluate_jurisdiction_receipt(pagination).complete is True

    bundle = closed_jurisdiction_receipt("WA", frontier_method="bundle")
    bundle["frontier"]["pagination_closed"] = False
    # bundle strategy still requires enumerator_closed in the builder; keep it true
    assert evaluate_jurisdiction_receipt(bundle).complete is True

    neither = closed_jurisdiction_receipt("ID")
    neither["frontier"]["method"] = "bundle_and_pagination"
    neither["frontier"]["bundle_closed"] = False
    neither["frontier"]["pagination_closed"] = False
    neither["frontier"]["closed"] = False
    neither["frontier"]["enumerator_closed"] = False
    verdict = evaluate_jurisdiction_receipt(neither)
    assert verdict.complete is False
    assert "open_frontier" in verdict.kinds


# ---------------------------------------------------------------------------
# Failed-final, caps, fixture transport
# ---------------------------------------------------------------------------


def test_rejects_nonzero_failed_final() -> None:
    receipt = closed_jurisdiction_receipt("NY")
    receipt["disposition"]["failed_final"] = 1
    receipt["disposition"]["fetched"] = 7
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "failed_final_nonzero" in verdict.kinds
    assert "success_without_closure" in verdict.kinds


def test_rejects_sample_and_runtime_caps() -> None:
    receipt = closed_jurisdiction_receipt("IL")
    receipt["sample_cap"] = 10
    receipt["runtime_caps"] = {"max_statutes": 10}
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "sample_cap_present" in verdict.kinds
    assert "runtime_cap_present" in verdict.kinds


def test_rejects_fixture_and_synthetic_transports() -> None:
    fixture = closed_jurisdiction_receipt("GA")
    fixture["transport"] = {"kind": "fixture", "fixture": True, "synthetic": False}
    fixture_verdict = evaluate_jurisdiction_receipt(fixture)
    assert fixture_verdict.complete is False
    assert "fixture_transport" in fixture_verdict.kinds

    synthetic = closed_jurisdiction_receipt("NC")
    synthetic["transport"] = {"kind": "live_https", "fixture": False, "synthetic": True}
    synthetic["synthetic_receipt"] = True
    synthetic_verdict = evaluate_jurisdiction_receipt(synthetic)
    assert synthetic_verdict.complete is False
    assert "synthetic_receipt" in synthetic_verdict.kinds


def test_rejects_partial_checkpoint_promotion() -> None:
    receipt = closed_jurisdiction_receipt("CO")
    receipt["checkpoint"]["partial"] = True
    receipt["checkpoint"]["promoted_success"] = True
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "partial_checkpoint_promoted" in verdict.kinds


# ---------------------------------------------------------------------------
# Replayable response hashes
# ---------------------------------------------------------------------------


def test_rejects_missing_and_mismatched_replay_hashes() -> None:
    missing = closed_jurisdiction_receipt("AZ")
    missing["hashes"] = {
        "request_sha256": sha256_text("request:AZ"),
        "response_sha256": sha256_text("response:AZ"),
        "admitted_body_sha256": sha256_text("body:AZ"),
    }
    del missing["replay"]
    missing_verdict = evaluate_jurisdiction_receipt(missing)
    assert missing_verdict.complete is False
    assert "replay_mismatch" in missing_verdict.kinds

    mismatched = closed_jurisdiction_receipt("NV")
    mismatched["replay"]["response_sha256"] = sha256_text("tampered")
    mismatch_verdict = evaluate_jurisdiction_receipt(mismatched)
    assert mismatch_verdict.complete is False
    assert "replay_mismatch" in mismatch_verdict.kinds

    no_hashes = closed_jurisdiction_receipt("UT")
    no_hashes["hashes"] = {
        "request_sha256": "",
        "response_sha256": "",
        "admitted_body_sha256": "",
    }
    no_hash_verdict = evaluate_jurisdiction_receipt(no_hashes)
    assert no_hash_verdict.complete is False
    assert "missing_response_hashes" in no_hash_verdict.kinds


def test_matching_replay_hashes_pass() -> None:
    receipt = closed_jurisdiction_receipt("ME")
    assert receipt["replay"]["response_sha256"] == receipt["hashes"]["response_sha256"]
    assert receipt["replay"]["request_sha256"] == receipt["hashes"]["request_sha256"]
    assert receipt["replay"]["admitted_body_sha256"] == receipt["hashes"]["admitted_body_sha256"]
    assert (
        receipt["replay"]["frontier_digest_sha256"]
        == receipt["frontier"]["frontier_digest_sha256"]
    )
    assert evaluate_jurisdiction_receipt(receipt).complete is True


# ---------------------------------------------------------------------------
# Aggregate key / digest equality
# ---------------------------------------------------------------------------


def test_aggregate_key_and_digest_equality() -> None:
    receipt = exact_51_aggregate_receipt()
    children = receipt["jurisdiction_receipts"]
    assert receipt["aggregate_keys"] == union_jurisdiction_keys(children)
    assert receipt["aggregate_digests"]["key_digest_sha256"] == compute_aggregate_key_digest(
        children
    )
    assert receipt["aggregate_digests"]["body_digest_sha256"] == compute_aggregate_body_digest(
        children
    )
    assert (
        receipt["aggregate_digests"]["frontier_digest_sha256"]
        == compute_aggregate_frontier_digest(children)
    )
    for field in FAMILY_KEY_FIELDS:
        assert set(receipt["family_parity"][field]) == set(receipt["aggregate_keys"])
    assert evaluate_aggregate_receipt(receipt).complete is True


def test_rejects_aggregate_key_mismatch() -> None:
    receipt = exact_51_aggregate_receipt()
    receipt["aggregate_keys"] = ["only-one-key"]
    verdict = evaluate_aggregate_receipt(receipt)
    assert verdict.complete is False
    assert "aggregate_key_mismatch" in verdict.kinds


def test_rejects_aggregate_digest_mismatch() -> None:
    receipt = exact_51_aggregate_receipt()
    receipt["aggregate_digests"]["key_digest_sha256"] = sha256_text("tampered-keys")
    receipt["aggregate_digests"]["body_digest_sha256"] = sha256_text("tampered-bodies")
    verdict = evaluate_aggregate_receipt(receipt)
    assert verdict.complete is False
    assert "aggregate_digest_mismatch" in verdict.kinds


def test_rejects_family_key_parity_mismatch() -> None:
    receipt = exact_51_aggregate_receipt()
    receipt["family_parity"]["bm25_keys"] = ["stale-bm25"]
    verdict = evaluate_aggregate_receipt(receipt)
    assert verdict.complete is False
    assert "family_key_parity_mismatch" in verdict.kinds


# ---------------------------------------------------------------------------
# Other fail-closed gates
# ---------------------------------------------------------------------------


def test_rejects_disposition_arithmetic_mismatch() -> None:
    receipt = closed_jurisdiction_receipt("WI")
    receipt["disposition"]["discovered"] = 99
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "disposition_arithmetic_mismatch" in verdict.kinds


def test_rejects_stale_index_keys() -> None:
    receipt = closed_jurisdiction_receipt("MI")
    receipt["index_keys"]["derived_keys"] = ["stale-key"]
    receipt["index_keys"]["stale_keys"] = ["stale-key"]
    receipt["index_keys"]["parity_ok"] = False
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "stale_index_keys" in verdict.kinds
    assert "derived_key_parity_mismatch" in verdict.kinds


def test_rejects_unofficial_source() -> None:
    receipt = closed_jurisdiction_receipt(
        "TX",
        official_source=False,
        source_domain="codes.findlaw.com",
    )
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "unofficial_source" in verdict.kinds


def test_rejects_nonzero_count_as_completeness_proof() -> None:
    receipt = closed_jurisdiction_receipt("CA")
    receipt["completion_claim"] = "nonzero_count"
    receipt["nonzero_count_proves_completeness"] = True
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "nonzero_count_insufficient" in verdict.kinds
    assert "requested_scope_completion" in verdict.kinds


def test_rejects_missing_typed_exclusion_evidence() -> None:
    receipt = closed_jurisdiction_receipt("LA")
    receipt["exclusions"] = []
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "missing_typed_evidence" in verdict.kinds


def test_rejects_text_quality_contamination() -> None:
    receipt = closed_jurisdiction_receipt("AR")
    receipt["text_quality"]["navigation_rejected"] = False
    receipt["text_quality"]["contaminated"] = True
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "text_quality_failure" in verdict.kinds


def test_rejects_missing_cids() -> None:
    receipt = closed_jurisdiction_receipt("KS")
    receipt["cids"]["source_cid"] = ""
    receipt["cids"]["entry_cid"] = "not-a-cid"
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "missing_cids" in verdict.kinds


def test_rejects_mutable_identity_timestamps() -> None:
    receipt = closed_jurisdiction_receipt("DE")
    receipt["legal_as_of"] = "latest"
    receipt["observed_at"] = "now"
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "mutable_timestamp" in verdict.kinds


def test_rejects_duplicate_logical_keys() -> None:
    receipt = closed_jurisdiction_receipt(
        "NH",
        canonical_keys=["nh:1", "nh:1"],
        derived_keys=["nh:1", "nh:1"],
    )
    receipt["logical_keys"]["unique"] = False
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "duplicate_logical_keys" in verdict.kinds


# ---------------------------------------------------------------------------
# require_complete + dispatch
# ---------------------------------------------------------------------------


def test_closed_builder_mutations_fail_require_complete() -> None:
    base = closed_jurisdiction_receipt("OR")
    require_complete(base, kind="jurisdiction")

    open_frontier = copy.deepcopy(base)
    open_frontier["frontier"]["closed"] = False
    open_frontier["frontier"]["pagination_closed"] = False
    open_frontier["frontier"]["enumerator_closed"] = False
    open_frontier["frontier"]["unvisited_continuation_links"] = ["https://example/next"]
    with pytest.raises(CompletenessAdmissionError):
        require_complete(open_frontier, kind="jurisdiction")

    failed_final = copy.deepcopy(base)
    failed_final["disposition"]["failed_final"] = 1
    failed_final["disposition"]["fetched"] = 7
    with pytest.raises(CompletenessAdmissionError):
        require_complete(failed_final, kind="jurisdiction")

    sample = copy.deepcopy(base)
    sample["sample_cap"] = 10
    sample["runtime_caps"] = {"max_statutes": 10}
    with pytest.raises(CompletenessAdmissionError):
        require_complete(sample, kind="jurisdiction")

    fixture = copy.deepcopy(base)
    fixture["transport"]["kind"] = "fixture"
    fixture["transport"]["fixture"] = True
    with pytest.raises(CompletenessAdmissionError):
        require_complete(fixture, kind="jurisdiction")


def test_evaluate_completion_receipt_dispatch() -> None:
    j_verdict = evaluate_completion_receipt(
        closed_jurisdiction_receipt("FL"),
        kind="jurisdiction",
    )
    assert j_verdict.complete is True

    m_verdict = evaluate_full_scrape_receipt(
        exact_51_manifest(),
        kind="aggregate",
    )
    assert m_verdict.complete is True


def test_finding_kind_aliases() -> None:
    assert FindingKind.coerce("exact_state_set_mismatch") is FindingKind.JURISDICTION_SET_MISMATCH
    assert FindingKind.coerce("stale_keys") is FindingKind.STALE_INDEX_KEYS
    assert FindingKind.coerce("dc_opt_in") is FindingKind.OPT_IN_DC
    assert FindingKind.coerce("fixture") is FindingKind.FIXTURE_TRANSPORT
    assert FindingKind.coerce("response_hash_mismatch") is FindingKind.REPLAY_MISMATCH


def test_schema_rejects_fixture_transport_on_closed_shape() -> None:
    receipt = closed_jurisdiction_receipt("VA")
    receipt["transport"]["kind"] = "fixture"
    receipt["transport"]["fixture"] = True
    with pytest.raises(ReceiptSchemaError):
        validate_receipt_schema(receipt)
