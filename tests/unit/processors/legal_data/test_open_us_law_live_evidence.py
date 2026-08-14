"""Unit tests for the OUL-049 uncapped acquisition and offline certification bridge."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    LiveEvidenceRequiredError,
    sha256_bytes,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
    BRIDGE_TASK_ID,
    COHORT_EVIDENCE_SCHEMA_VERSION,
    GOAL_ID,
    PROGRAM_ID,
    PRODUCER,
    REJECTION_FIXTURE_COMPLETION,
    REJECTION_PLACEHOLDER,
    REJECTION_RAW_BYTES_UNCHECKED,
    REJECTION_SAMPLE,
    REJECTION_SELF_ASSERTED,
    REJECTION_ZERO_ROW_SUCCESS,
    SCHEMA_VERSION,
    FixtureCompletionForbiddenError,
    LiveHttpsTransport,
    OfficialFetch,
    SampleCapError,
    assert_uncapped,
    build_cohort_evidence_payload,
    build_receipt_from_artifacts,
    certify_cohort_offline,
    certify_jurisdiction_offline,
    collect_certification_rejections,
    compute_frontier_digest,
    create_evidence_root,
    default_cohort_report_path,
    is_cohort_evidence_payload,
    is_placeholder_cid,
    is_placeholder_digest,
    prove_fixture_behavior,
    validate_cohort_evidence,
    validate_cohort_evidence_schema_file,
    write_retained_artifacts,
)


def _live_fetch(code: str = "FL", *, rows: int = 4, fixture: bool = False) -> OfficialFetch:
    domain = {
        "FL": "www.leg.state.fl.us",
        "GA": "www.legis.ga.gov",
        "HI": "www.capitol.hawaii.gov",
        "ID": "legislature.idaho.gov",
    }[code]
    units = tuple(
        {
            "canonical_key": f"{code.lower()}:title-{index}",
            "text": f"official {code} statute unit {index} " + ("body " * 12),
        }
        for index in range(1, rows + 1)
    )
    request = f"GET /statutes HTTP/1.1\nhost: {domain}\n".encode("utf-8")
    body = "\n".join(str(item["text"]) for item in units).encode("utf-8")
    response = b"HTTP/1.1 200 OK\n\n" + body
    frontier = {
        "bundle_closed": False,
        "closed": True,
        "enumerator_closed": True,
        "expected_index_units": rows,
        "method": "pagination",
        "pagination_closed": True,
        "remaining_bundle_members": [],
        "toc_exhausted": True,
        "unvisited_continuation_links": [],
        "visited_index_units": rows,
    }
    frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
    return OfficialFetch(
        jurisdiction_code=code,
        request_bytes=request,
        response_bytes=response,
        body_bytes=body,
        source_domain=domain,
        source_path="/statutes",
        frontier=frontier,
        rows=units,
        transport_kind="fixture" if fixture else "live_https",
        fixture=fixture,
        first_hierarchy_unit=units[0]["canonical_key"],
        last_hierarchy_unit=units[-1]["canonical_key"],
    )


def test_schema_and_bridge_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "open-us-law-live-evidence-v1"
    assert COHORT_EVIDENCE_SCHEMA_VERSION == "open-us-law-cohort-evidence-v1"
    assert BRIDGE_TASK_ID == "OUL-049"
    assert GOAL_ID == "OUL-G021"
    assert PROGRAM_ID == "open-us-law-reindex-v1"
    assert PRODUCER == "open_us_law_live_evidence.py"
    assert default_cohort_report_path("C").name == "cohort_C.json"


def test_cohort_schema_file_is_sealed() -> None:
    payload = validate_cohort_evidence_schema_file()
    assert payload["title"] == "Open US Law Cohort Evidence v1"
    assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_uncapped_gate_rejects_samples_and_caps() -> None:
    assert_uncapped(sample_cap=None, runtime_caps=None, max_statutes=None, mode="full")
    with pytest.raises(SampleCapError):
        assert_uncapped(sample_cap=2)
    with pytest.raises(SampleCapError):
        assert_uncapped(max_statutes=10)
    with pytest.raises(SampleCapError):
        assert_uncapped(mode="sample")


def test_placeholder_and_self_asserted_digest_classifiers() -> None:
    assert is_placeholder_digest("0" * 64) is True
    assert is_placeholder_digest("deadbeef" * 8) is True
    assert is_placeholder_digest("not-a-hash") is True
    assert is_placeholder_digest(sha256_bytes(b"official-body")) is False
    assert is_placeholder_cid("bafyplaceholderaaaaaaaaa") is True
    assert is_placeholder_cid("") is True


def test_retained_artifacts_are_rehashed_offline(tmp_path: Path) -> None:
    root = create_evidence_root(tmp_path / "evidence", cohort="C")
    fetch = _live_fetch("FL", rows=5)
    write_retained_artifacts(root, fetch)
    verdict = certify_jurisdiction_offline(root, "FL")
    assert verdict.raw_bytes_checked is True
    assert verdict.row_count == 5
    assert verdict.fixture is False
    assert verdict.request_sha256 == sha256_bytes(fetch.request_bytes)
    assert verdict.admitted_body_sha256 == sha256_bytes(fetch.body_bytes)
    assert len(verdict.canonical_keys) == 5


def test_raw_bytes_unchecked_is_rejected() -> None:
    receipt = {
        "jurisdiction": "FL",
        "status": "success",
        "mode": "full",
        "row_count": 4,
        "official_source": True,
        "source_domain": "www.leg.state.fl.us",
        "hashes": {
            "request_sha256": sha256_bytes(b"req"),
            "response_sha256": sha256_bytes(b"resp"),
            "admitted_body_sha256": sha256_bytes(b"body"),
        },
        "replay": {
            "request_sha256": sha256_bytes(b"req"),
            "response_sha256": sha256_bytes(b"resp"),
            "admitted_body_sha256": sha256_bytes(b"body"),
            "frontier_digest_sha256": sha256_bytes(b"front"),
            "closed": True,
        },
        "frontier": {
            "closed": True,
            "enumerator_closed": True,
            "method": "pagination",
            "pagination_closed": True,
            "unvisited_continuation_links": [],
            "remaining_bundle_members": [],
            "expected_index_units": 4,
            "visited_index_units": 4,
            "frontier_digest_sha256": sha256_bytes(b"front"),
        },
    }
    kinds = collect_certification_rejections(receipt)
    assert REJECTION_RAW_BYTES_UNCHECKED in kinds
    assert REJECTION_SELF_ASSERTED in kinds


def test_zero_row_success_is_rejected() -> None:
    receipt = {
        "jurisdiction": "GA",
        "status": "success",
        "mode": "full",
        "row_count": 0,
        "disposition": {"fetched": 0, "discovered": 0, "excluded": 0, "quarantined": 0, "failed_final": 0},
        "hashes": {
            "request_sha256": sha256_bytes(b"req-ga"),
            "response_sha256": sha256_bytes(b"resp-ga"),
            "admitted_body_sha256": sha256_bytes(b"body-ga"),
        },
        "transport": {"kind": "live_https", "fixture": False, "synthetic": False},
        "boundary_probes": {
            "first_hierarchy_unit": "ga:1",
            "last_hierarchy_unit": "ga:1",
            "first_probe_ok": True,
            "last_probe_ok": True,
        },
    }
    kinds = collect_certification_rejections(
        receipt,
        request_bytes=b"req-ga",
        response_bytes=b"resp-ga",
        body_bytes=b"body-ga",
    )
    assert REJECTION_ZERO_ROW_SUCCESS in kinds


def test_placeholder_sample_and_self_asserted_are_rejected() -> None:
    receipt = {
        "jurisdiction": "HI",
        "status": "success",
        "mode": "sample",
        "sample_cap": 2,
        "row_count": 2,
        "hashes": {
            "request_sha256": "0" * 64,
            "response_sha256": "f" * 64,
            "admitted_body_sha256": "deadbeef" * 8,
        },
        "cids": {"source_cid": "bafyplaceholderaaaaaaaaa"},
        "transport": {"kind": "live_https", "fixture": False, "synthetic": False},
    }
    kinds = collect_certification_rejections(receipt)
    assert REJECTION_PLACEHOLDER in kinds
    assert REJECTION_SAMPLE in kinds
    assert REJECTION_SELF_ASSERTED in kinds


def test_fixture_transport_cannot_complete_a_jurisdiction(tmp_path: Path) -> None:
    root = create_evidence_root(tmp_path / "fixture", cohort="C")
    write_retained_artifacts(root, _live_fetch("ID", fixture=True))
    verdict = certify_jurisdiction_offline(root, "ID")
    assert verdict.ok is False
    assert verdict.fixture is True
    assert REJECTION_FIXTURE_COMPLETION in verdict.rejection_kinds


def test_live_https_transport_does_not_perform_implicit_network() -> None:
    with pytest.raises(Exception, match="implicit network"):
        LiveHttpsTransport().fetch_official("FL")


def test_checkpoint_resume_reuses_retained_bytes(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
        acquire_jurisdiction,
    )

    root = create_evidence_root(tmp_path / "resume", cohort="C")

    class _Once:
        def __init__(self) -> None:
            self.calls = 0

        def fetch_official(self, code: str) -> OfficialFetch:
            self.calls += 1
            return _live_fetch(code)

    transport = _Once()
    first = acquire_jurisdiction("HI", root, transport=transport, resume=True)
    second = acquire_jurisdiction("HI", root, transport=transport, resume=True)
    assert first.completed is True
    assert second.completed is True
    assert transport.calls == 1


def test_fixture_behavior_never_marks_cohort_complete(tmp_path: Path) -> None:
    report = prove_fixture_behavior("C", tmp_path / "soft", repo_root=Path(__file__).resolve().parents[4])
    assert report["software_behavior_proven"] is True
    assert report["cohort_complete"] is False
    assert report["fixture_execution"] is True
    assert report["fixture_proves_cohort_completion"] is False
    assert report["authorizing_for_publication"] is False
    assert report["jurisdictions"] == ["FL", "GA", "HI", "ID"]
    assert all(item["raw_bytes_checked"] for item in report["verdicts"])


def test_require_live_rejects_fixture_cohort(tmp_path: Path) -> None:
    prove_fixture_behavior("C", tmp_path / "soft", repo_root=Path(__file__).resolve().parents[4])
    with pytest.raises((FixtureCompletionForbiddenError, LiveEvidenceRequiredError)):
        certify_cohort_offline(
            tmp_path / "soft",
            "C",
            require_live=True,
            allow_fixture_software_proof=False,
        )


def test_cohort_evidence_payload_fixture_cannot_complete() -> None:
    from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
        CertificationVerdict,
    )

    verdicts = [
        CertificationVerdict(
            jurisdiction_code=code,
            ok=True,
            raw_bytes_checked=True,
            row_count=3,
            fixture=True,
            rejection_kinds=(),
            detail="fixture",
        )
        for code in ("FL", "GA", "HI", "ID")
    ]
    with pytest.raises(FixtureCompletionForbiddenError):
        build_cohort_evidence_payload(
            cohort="C",
            verdicts=verdicts,
            fixture_execution=True,
            require_live=True,
        )
    payload = build_cohort_evidence_payload(
        cohort="C",
        verdicts=verdicts,
        fixture_execution=True,
        require_live=False,
    )
    assert is_cohort_evidence_payload(payload) is True
    assert payload["cohort_complete"] is False
    assert payload["authorizing_for_publication"] is False
    validated = validate_cohort_evidence(payload, cohort="C", require_live=False)
    assert validated["cohort_complete"] is False


def test_declared_live_report_requires_raw_bytes() -> None:
    payload = build_cohort_evidence_payload(
        cohort="C",
        verdicts=(),
        fixture_execution=False,
        require_live=False,
    )
    mutated = copy.deepcopy(payload)
    mutated["cohort_complete"] = True
    mutated["status"] = "success"
    mutated["jurisdiction_receipts"] = {
        code: {"jurisdiction": code, "status": "success", "row_count": 4}
        for code in ("FL", "GA", "HI", "ID")
    }
    with pytest.raises((LiveEvidenceRequiredError, Exception)):
        validate_cohort_evidence(mutated, cohort="C", require_live=True)


def test_receipt_from_artifacts_embeds_recomputed_hashes(tmp_path: Path) -> None:
    root = create_evidence_root(tmp_path / "built")
    fetch = _live_fetch("GA", rows=6)
    write_retained_artifacts(root, fetch)
    receipt = build_receipt_from_artifacts(root, "GA")
    assert receipt["hashes"]["admitted_body_sha256"] == sha256_bytes(fetch.body_bytes)
    assert receipt["row_count"] == 6
    assert receipt["transport"]["fixture"] is False
