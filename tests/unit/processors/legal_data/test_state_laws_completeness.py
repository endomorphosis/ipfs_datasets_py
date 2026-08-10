"""Unit tests for the full-scrape completion and admission oracle (LCR-003).

Acceptance: Rejects subset manifests, opt-in DC, success with open
frontier/failed-final/sample cap, partial checkpoint promotion, stale index
keys, and any jurisdiction set other than exact 51.
"""

from __future__ import annotations

import copy

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    ALL_GATES,
    CANONICAL_JURISDICTIONS,
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
    FIXTURE_SCHEMA,
    SCHEMA_VERSION,
    TASK_ID,
    CompletenessAdmissionError,
    FindingKind,
    JurisdictionSetError,
    assert_fixture_oracle,
    canonical_jurisdiction_codes,
    closed_jurisdiction_receipt,
    default_fixture_path,
    evaluate_completion_receipt,
    evaluate_corpus_manifest,
    evaluate_fixture_case,
    evaluate_jurisdiction_receipt,
    evaluate_jurisdiction_set_receipt,
    exact_51_manifest,
    is_opt_in_dc_policy,
    load_completion_receipts_fixture,
    normalize_postal_code,
    reconcile_disposition,
    require_complete,
    run_fixture_oracle,
    validate_jurisdiction_set,
)


# ---------------------------------------------------------------------------
# Schema / sealed set
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "state-laws-completeness-oracle-v1"
    assert FIXTURE_SCHEMA == "ipfs_datasets_py/state-laws-completion-receipts@1"
    assert TASK_ID == "LCR-003"
    assert EXPECTED_JURISDICTION_COUNT == 51
    assert len(ALL_GATES) >= 8


def test_canonical_jurisdiction_set_is_exact_51_including_dc() -> None:
    codes = canonical_jurisdiction_codes()
    assert len(codes) == 51
    assert len(set(codes)) == 51
    assert "DC" in codes
    assert codes[-1] == "DC"
    assert set(codes) == CANONICAL_JURISDICTIONS
    assert set(CANONICAL_JURISDICTION_ORDER) == CANONICAL_JURISDICTIONS
    validate_jurisdiction_set(codes)


def test_validate_jurisdiction_set_rejects_missing_extra_and_duplicates() -> None:
    codes = list(canonical_jurisdiction_codes())
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(codes[:-1])
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(codes + ["PR"])
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(codes + ["AL"])


def test_normalize_postal_code_rejects_unknown() -> None:
    assert normalize_postal_code("or") == "OR"
    with pytest.raises(JurisdictionSetError):
        normalize_postal_code("XX")
    with pytest.raises(JurisdictionSetError):
        normalize_postal_code("PR")


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
# Fixture integrity
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return load_completion_receipts_fixture()


def test_fixture_exists_and_has_schema(fixture_payload: dict) -> None:
    path = default_fixture_path()
    assert path.is_file(), f"missing fixture: {path}"
    assert fixture_payload["schema"] == FIXTURE_SCHEMA
    assert fixture_payload["task_id"] == TASK_ID
    assert isinstance(fixture_payload["cases"], list) and fixture_payload["cases"]
    assert fixture_payload["jurisdiction_contract"]["required_count"] == 51
    assert "DC" in fixture_payload["jurisdiction_contract"]["required_codes"]


def test_fixture_oracle_matches_expected_labels() -> None:
    report = assert_fixture_oracle()
    assert report["ok"] is True
    assert report["mismatches"] == []
    assert report["case_count"] == len(load_completion_receipts_fixture()["cases"])


def test_run_fixture_oracle_reports_all_cases() -> None:
    report = run_fixture_oracle()
    assert report["task_id"] == TASK_ID
    assert report["ok"] is True
    case_ids = {item["case_id"] for item in report["results"]}
    for required in (
        "closed_ok_mn",
        "subset_manifest",
        "opt_in_dc_legacy_all",
        "success_open_frontier",
        "success_failed_final",
        "success_sample_cap",
        "partial_checkpoint_promotion",
        "stale_index_keys",
        "exact_set_ok_51",
    ):
        assert required in case_ids


# ---------------------------------------------------------------------------
# Acceptance: each rejection class
# ---------------------------------------------------------------------------


def _case(fixture_payload: dict, case_id: str) -> dict:
    return next(item for item in fixture_payload["cases"] if item["case_id"] == case_id)


def test_closed_ok_receipt_passes(fixture_payload: dict) -> None:
    verdict = evaluate_fixture_case(_case(fixture_payload, "closed_ok_mn"))
    assert verdict.status == "pass"
    assert verdict.complete is True
    assert verdict.admitted is True
    assert verdict.kinds == ()
    assert verdict.findings == ()


def test_rejects_subset_manifest(fixture_payload: dict) -> None:
    verdict = evaluate_fixture_case(_case(fixture_payload, "subset_manifest"))
    assert verdict.status == "fail"
    assert "subset_manifest" in verdict.kinds
    assert "jurisdiction_set_mismatch" in verdict.kinds
    assert "requested_scope_completion" in verdict.kinds or verdict.complete is False


def test_rejects_opt_in_dc(fixture_payload: dict) -> None:
    case = _case(fixture_payload, "opt_in_dc_legacy_all")
    assert is_opt_in_dc_policy(case["receipt"]) is True
    verdict = evaluate_fixture_case(case)
    assert verdict.status == "fail"
    assert "opt_in_dc" in verdict.kinds
    assert "jurisdiction_set_mismatch" in verdict.kinds or "subset_manifest" in verdict.kinds


def test_rejects_success_with_open_frontier(fixture_payload: dict) -> None:
    verdict = evaluate_fixture_case(_case(fixture_payload, "success_open_frontier"))
    assert verdict.status == "fail"
    for kind in (
        "open_frontier",
        "enumerator_not_closed",
        "unvisited_continuation_links",
        "success_without_closure",
    ):
        assert kind in verdict.kinds


def test_rejects_success_with_failed_final(fixture_payload: dict) -> None:
    verdict = evaluate_fixture_case(_case(fixture_payload, "success_failed_final"))
    assert verdict.status == "fail"
    assert "failed_final_nonzero" in verdict.kinds
    assert "success_without_closure" in verdict.kinds


def test_rejects_success_with_sample_cap(fixture_payload: dict) -> None:
    verdict = evaluate_fixture_case(_case(fixture_payload, "success_sample_cap"))
    assert verdict.status == "fail"
    assert "sample_cap_present" in verdict.kinds
    assert "runtime_cap_present" in verdict.kinds


def test_rejects_partial_checkpoint_promotion(fixture_payload: dict) -> None:
    verdict = evaluate_fixture_case(
        _case(fixture_payload, "partial_checkpoint_promotion")
    )
    assert verdict.status == "fail"
    assert "partial_checkpoint_promoted" in verdict.kinds


def test_rejects_stale_index_keys(fixture_payload: dict) -> None:
    verdict = evaluate_fixture_case(_case(fixture_payload, "stale_index_keys"))
    assert verdict.status == "fail"
    assert "stale_index_keys" in verdict.kinds
    assert "derived_key_parity_mismatch" in verdict.kinds


def test_rejects_any_jurisdiction_set_other_than_exact_51(
    fixture_payload: dict,
) -> None:
    ok = evaluate_fixture_case(_case(fixture_payload, "exact_set_ok_51"))
    assert ok.status == "pass"
    assert ok.kinds == ()

    extra = evaluate_fixture_case(_case(fixture_payload, "exact_set_extra_pr"))
    assert extra.status == "fail"
    assert "jurisdiction_set_mismatch" in extra.kinds

    # Missing a single sealed code is also rejected.
    missing = evaluate_jurisdiction_set_receipt(
        {
            "jurisdictions": list(canonical_jurisdiction_codes())[:-1],
            "includes_dc": False,
            "status": "success",
        },
        case_id="missing_one",
    )
    assert missing.status == "fail"
    assert "jurisdiction_set_mismatch" in missing.kinds


def test_rejects_disposition_arithmetic_mismatch(fixture_payload: dict) -> None:
    verdict = evaluate_fixture_case(
        _case(fixture_payload, "disposition_arithmetic_mismatch")
    )
    assert verdict.status == "fail"
    assert "disposition_arithmetic_mismatch" in verdict.kinds


def test_rejects_registry_basis_success(fixture_payload: dict) -> None:
    verdict = evaluate_fixture_case(_case(fixture_payload, "registry_basis_success"))
    assert verdict.status == "fail"
    assert "partial_checkpoint_promoted" in verdict.kinds
    assert "requested_scope_completion" in verdict.kinds


def test_corpus_exact_51_pass(fixture_payload: dict) -> None:
    verdict = evaluate_fixture_case(_case(fixture_payload, "corpus_exact_51_pass"))
    assert verdict.status == "pass"
    assert verdict.complete is True
    assert verdict.kinds == ()


# ---------------------------------------------------------------------------
# Programmatic builders and require_complete
# ---------------------------------------------------------------------------


def test_closed_builder_passes_and_mutations_fail() -> None:
    base = closed_jurisdiction_receipt("OR")
    assert evaluate_jurisdiction_receipt(base).complete is True
    require_complete(base, kind="jurisdiction_receipt")

    open_frontier = copy.deepcopy(base)
    open_frontier["frontier"]["closed"] = False
    open_frontier["frontier"]["enumerator_closed"] = False
    open_frontier["frontier"]["unvisited_continuation_links"] = ["https://example/next"]
    open_frontier["frontier"]["visited_index_units"] = 1
    with pytest.raises(CompletenessAdmissionError):
        require_complete(open_frontier, kind="jurisdiction_receipt")

    failed_final = copy.deepcopy(base)
    failed_final["disposition"]["failed_final"] = 1
    failed_final["disposition"]["fetched"] = 7
    with pytest.raises(CompletenessAdmissionError):
        require_complete(failed_final, kind="jurisdiction_receipt")

    sample = copy.deepcopy(base)
    sample["sample_cap"] = 10
    sample["runtime_caps"] = {"max_statutes": 10}
    with pytest.raises(CompletenessAdmissionError):
        require_complete(sample, kind="jurisdiction_receipt")

    partial = copy.deepcopy(base)
    partial["checkpoint"]["partial"] = True
    partial["checkpoint"]["promoted_success"] = True
    with pytest.raises(CompletenessAdmissionError):
        require_complete(partial, kind="jurisdiction_receipt")

    stale = copy.deepcopy(base)
    stale["index_keys"]["derived_keys"] = ["stale-key"]
    stale["index_keys"]["stale_keys"] = ["stale-key"]
    stale["index_keys"]["parity_ok"] = False
    with pytest.raises(CompletenessAdmissionError):
        require_complete(stale, kind="jurisdiction_receipt")


def test_exact_51_manifest_builder_and_subset_rejection() -> None:
    full = exact_51_manifest()
    assert evaluate_corpus_manifest(full).complete is True

    subset = exact_51_manifest(jurisdictions=["CA", "OR", "WA"], is_complete=True)
    verdict = evaluate_corpus_manifest(subset)
    assert verdict.complete is False
    assert "subset_manifest" in verdict.kinds

    opt_in = exact_51_manifest(
        include_dc=False,
        dc_policy="opt_in",
        is_complete=True,
    )
    opt_in["dc_optional"] = True
    opt_verdict = evaluate_corpus_manifest(opt_in)
    assert opt_verdict.complete is False
    assert "opt_in_dc" in opt_verdict.kinds


def test_nonzero_count_is_insufficient_without_gates() -> None:
    receipt = {
        "jurisdiction": "CA",
        "status": "success",
        "source_domain": "leginfo.legislature.ca.gov",
        "official_source": True,
        "mode": "full",
        "row_count": 9999,
        "completion_claim": "nonzero_count",
        "nonzero_count_proves_completeness": True,
        "runtime_caps": None,
        "sample_cap": None,
        "checkpoint": {
            "partial": False,
            "promoted_success": False,
            "completion_basis": "source_frontier",
        },
        "frontier": {
            "closed": True,
            "enumerator_closed": True,
            "unvisited_continuation_links": [],
            "expected_index_units": 1,
            "visited_index_units": 1,
        },
        "boundary_probes": {
            "first_hierarchy_unit": "title-1",
            "last_hierarchy_unit": "title-1",
        },
        "disposition": {
            "discovered": 1,
            "fetched": 1,
            "excluded": 0,
            "quarantined": 0,
            "failed_final": 0,
            "duplicates": 0,
        },
        "index_keys": {
            "canonical_keys": ["ca:1"],
            "derived_keys": ["ca:1"],
            "stale_keys": [],
            "parity_ok": True,
        },
    }
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "nonzero_count_insufficient" in verdict.kinds
    assert "requested_scope_completion" in verdict.kinds


def test_unofficial_source_rejected() -> None:
    receipt = closed_jurisdiction_receipt(
        "TX",
        official_source=False,
        source_domain="codes.findlaw.com",
    )
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "unofficial_source" in verdict.kinds


def test_replay_mismatch_rejected() -> None:
    receipt = closed_jurisdiction_receipt(
        "NY",
        replay={
            "first_frontier_digest": "aaa",
            "second_frontier_digest": "bbb",
            "closed": True,
        },
    )
    verdict = evaluate_jurisdiction_receipt(receipt)
    assert verdict.complete is False
    assert "replay_mismatch" in verdict.kinds


def test_finding_kind_aliases() -> None:
    assert FindingKind.coerce("exact_state_set_mismatch") is FindingKind.JURISDICTION_SET_MISMATCH
    assert FindingKind.coerce("stale_keys") is FindingKind.STALE_INDEX_KEYS
    assert FindingKind.coerce("dc_opt_in") is FindingKind.OPT_IN_DC


def test_evaluate_completion_receipt_dispatch() -> None:
    j_verdict = evaluate_completion_receipt(
        closed_jurisdiction_receipt("FL"),
        kind="jurisdiction_receipt",
    )
    assert j_verdict.complete is True

    m_verdict = evaluate_completion_receipt(
        exact_51_manifest(),
        kind="corpus_manifest",
    )
    assert m_verdict.complete is True
