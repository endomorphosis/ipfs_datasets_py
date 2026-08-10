"""Unit tests for the sealed Federal Register gold set (LCR-051).

Acceptance: Gold cases are source-cited, checksum-sealed, diverse, leak-free,
and include hard negatives and missing-body cases.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_gold import (
    BODY_DISPOSITIONS_WITHOUT_FULL_TEXT,
    FIXTURE_FILENAME,
    FIXTURE_ID,
    GOAL_ID,
    PARTITIONS,
    REQUIRED_AGENCIES,
    REQUIRED_DOCUMENT_TYPES,
    REQUIRED_LABEL_KINDS,
    REQUIRED_QUERY_KINDS,
    SCHEMA_VERSION,
    TASK_ID,
    FederalRegisterGoldSet,
    GoldChecksumError,
    GoldDiversityError,
    GoldLabelError,
    apply_seal,
    compute_manifest_digest,
    default_gold_fixture_path,
    diversity_report,
    load_and_validate_gold,
    load_gold_fixture,
    load_gold_set,
    materialize_gold_payload,
    sealed_body,
    validate_diversity,
    validate_hard_negatives,
    validate_missing_body_cases,
    validate_partitions_leak_free,
    validate_source_citations,
    verify_checksum_seal,
    write_gold_fixture,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    DEFAULT_OBSERVATION_CUTOFF,
    PREVIOUS_PUBLIC_PIN,
    validate_legal_id,
    validate_official_url,
)


# ---------------------------------------------------------------------------
# Session bootstrap: ensure sealed fixture is on disk for admission/tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _ensure_sealed_fixture() -> Path:
    """Ensure the gold fixture path exists and expands to a sealed payload."""

    path = default_gold_fixture_path()
    assert path.is_file(), f"missing gold fixture recipe/envelope: {path}"
    # Compact recipe fixtures expand via materialize; full envelopes validate
    # in place. Prefer the compact on-disk recipe (admission policy).
    payload = load_and_validate_gold(path)
    assert payload["manifest_digest"]
    assert payload["frozen"] is True
    return path


@pytest.fixture(scope="module")
def gold(_ensure_sealed_fixture: Path) -> dict[str, Any]:
    return load_and_validate_gold(_ensure_sealed_fixture)


@pytest.fixture(scope="module")
def gold_set(_ensure_sealed_fixture: Path) -> FederalRegisterGoldSet:
    return load_gold_set(_ensure_sealed_fixture)

@pytest.fixture(scope="module")
def docs_by_id(gold: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {d["document_id"]: d for d in gold["documents"]}


# ---------------------------------------------------------------------------
# Fixture presence, schema, checksum seal
# ---------------------------------------------------------------------------


def test_gold_fixture_present_and_schema(gold: dict[str, Any]) -> None:
    path = default_gold_fixture_path()
    assert path.is_file(), f"missing gold fixture: {path}"
    assert path.name == FIXTURE_FILENAME
    assert gold["schema_version"] == SCHEMA_VERSION
    assert gold["fixture_id"] == FIXTURE_ID
    assert gold["task_id"] == TASK_ID
    assert gold["goal_id"] == GOAL_ID
    assert gold["frozen"] is True
    assert gold["ground_truth_policy"]
    assert gold["currentness_disclaimer"]
    assert "wall-clock" in gold["currentness_disclaimer"].lower() or "current" in gold["currentness_disclaimer"].lower()
    size = path.stat().st_size
    assert size < 512_000, f"gold fixture unexpectedly large: {size} bytes"
    assert size > 400, f"gold fixture unexpectedly small: {size} bytes"
    # On-disk form may be a compact recipe; expanded envelope is larger.
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    if on_disk.get("use_builtin_recipe") or on_disk.get("format") == "sealed_recipe_v1":
        assert on_disk.get("task_id") == TASK_ID
        assert on_disk.get("frozen") is True
    else:
        assert "documents" in on_disk
        assert on_disk.get("manifest_digest") == gold["manifest_digest"]

def test_checksum_seal_verifies(gold: dict[str, Any]) -> None:
    digest = verify_checksum_seal(gold)
    assert len(digest) == 64
    assert digest == gold["manifest_digest"]
    assert digest == gold["content_checksum"]
    assert digest == compute_manifest_digest(gold)
    assert gold["seal"]["algorithm"] == "sha256"
    assert TASK_ID in gold["seal"]["task_id"]


def test_tamper_breaks_checksum_seal(gold: dict[str, Any]) -> None:
    tampered = copy.deepcopy(gold)
    tampered["documents"][0]["title"] = "TAMPERED TITLE"
    with pytest.raises(GoldChecksumError):
        verify_checksum_seal(tampered)

    tampered2 = copy.deepcopy(gold)
    tampered2["manifest_digest"] = "0" * 64
    with pytest.raises(GoldChecksumError):
        verify_checksum_seal(tampered2)


def test_materialize_matches_loaded_seal(gold: dict[str, Any]) -> None:
    fresh = materialize_gold_payload()
    assert fresh["manifest_digest"] == gold["manifest_digest"]
    assert sealed_body(fresh) == sealed_body(gold)
    # Loader expansion of the on-disk recipe/envelope is stable.
    again = load_gold_fixture(default_gold_fixture_path())
    assert again["manifest_digest"] == gold["manifest_digest"]

# ---------------------------------------------------------------------------
# Source-cited documents
# ---------------------------------------------------------------------------


def test_documents_are_source_cited(gold: dict[str, Any]) -> None:
    validate_source_citations(gold["documents"])
    for doc in gold["documents"]:
        validate_legal_id(doc["legal_id"])
        validate_official_url(doc["official_source_url"])
        assert "federalregister.gov" in doc["official_source_url"]
        assert doc["source_checksum"]
        assert doc["entry_cid"] != doc["source_cid"]
        assert doc["legal_id"].startswith(
            f"fr:{doc['document_number']}:{doc['publication_date']}"
        )


def test_release_authority_bound(gold: dict[str, Any]) -> None:
    auth = gold["release_authority"]
    assert auth["observation_cutoff"] == DEFAULT_OBSERVATION_CUTOFF
    assert auth["pinned_baseline_revision"] == PREVIOUS_PUBLIC_PIN
    assert auth["provider"]
    assert "federalregister.gov" in auth["official_sources"]


# ---------------------------------------------------------------------------
# Diversity: agencies, types, eras, corrections/withdrawals
# ---------------------------------------------------------------------------


def test_temporal_and_agency_diversity(gold: dict[str, Any]) -> None:
    report = validate_diversity(gold)
    for agency in REQUIRED_AGENCIES:
        assert agency in report["agencies"], f"missing agency {agency}"
    for doc_type in REQUIRED_DOCUMENT_TYPES:
        assert doc_type in report["document_types"], f"missing type {doc_type}"
    assert len(report["publication_years"]) >= 5
    assert len(report["eras"]) >= 2
    assert "corrects" in report["correction_relations"]
    assert "withdraws" in report["correction_relations"]

    # Explicit withdrawal and correction documents exist
    relations = {d.get("correction_relation") for d in gold["documents"]}
    assert "corrects" in relations
    assert "withdraws" in relations


def test_diversity_report_helper(gold: dict[str, Any]) -> None:
    report = diversity_report(gold)
    assert len(report["agencies"]) >= len(REQUIRED_AGENCIES)


# ---------------------------------------------------------------------------
# Leak-free partitions
# ---------------------------------------------------------------------------


def test_partitions_are_leak_free(gold: dict[str, Any]) -> None:
    validate_partitions_leak_free(gold)
    assert tuple(gold["partitions"]) == PARTITIONS
    for partition in PARTITIONS:
        assert gold["counts"]["partition_query_counts"][partition] >= 1
        assert len(gold["partition_index"][partition]) >= 1

    query_ids = [q["query_id"] for q in gold["queries"]]
    assert len(query_ids) == len(set(query_ids))

    # No cross-partition query text
    texts = {}
    for query in gold["queries"]:
        key = " ".join(query["query_text"].lower().split())
        texts.setdefault(key, set()).add(query["partition"])
    for key, parts in texts.items():
        assert len(parts) == 1, f"leaked query text across {parts}: {key[:60]}"


# ---------------------------------------------------------------------------
# Judgments, query/label kinds, filters
# ---------------------------------------------------------------------------


def test_judgments_join_stable_identities(
    gold: dict[str, Any], docs_by_id: dict[str, dict[str, Any]]
) -> None:
    query_ids = {q["query_id"] for q in gold["queries"]}
    judged = set()
    for judgment in gold["judgments"]:
        assert judgment["query_id"] in query_ids
        doc = docs_by_id[judgment["document_id"]]
        assert judgment["legal_id"] == doc["legal_id"]
        assert judgment["entry_cid"] == doc["entry_cid"]
        assert judgment["grade"]
        assert judgment["label_kind"]
        judged.add(judgment["query_id"])
    assert judged == query_ids


def test_query_and_label_kind_coverage(gold: dict[str, Any]) -> None:
    query_kinds = {q["query_kind"] for q in gold["queries"]}
    label_kinds = {j["label_kind"] for j in gold["judgments"]}
    assert REQUIRED_QUERY_KINDS.issubset(query_kinds)
    assert REQUIRED_LABEL_KINDS.issubset(label_kinds)


def test_agency_date_type_filters_bound(gold: dict[str, Any], gold_set: FederalRegisterGoldSet) -> None:
    filter_queries = [
        q
        for q in gold["queries"]
        if q["query_kind"] in {"filter_agency", "filter_date", "filter_type"}
    ]
    assert len(filter_queries) >= 3
    for query in filter_queries:
        assert query.get("filters"), f"{query['query_id']} missing filters"

    epa = gold_set.filter_documents(agency_code="EPA")
    assert epa
    assert all(d["agency_code"] == "EPA" for d in epa)

    notices = gold_set.filter_documents(document_type="notice")
    assert notices
    assert all(d["document_type"] == "notice" for d in notices)

    june_2020 = gold_set.filter_documents(
        publication_date_from="2020-06-01",
        publication_date_to="2020-06-30",
    )
    assert june_2020
    assert all(d["publication_date"].startswith("2020-06") for d in june_2020)


# ---------------------------------------------------------------------------
# Graph paths (citation / correction / withdrawal relationships)
# ---------------------------------------------------------------------------


def test_graph_paths_include_correction_and_withdrawal(
    gold: dict[str, Any], docs_by_id: dict[str, dict[str, Any]]
) -> None:
    assert gold["graph_paths"]
    relations = set()
    for path in gold["graph_paths"]:
        assert path["query_id"]
        assert path["partition"] in PARTITIONS
        assert len(path["nodes"]) >= 2
        for edge in path["edges"]:
            relations.add(edge["relation"])
            assert edge["source"] in path["nodes"]
            assert edge["target"] in path["nodes"]
        for node_id, ref in zip(path["nodes"], path["node_refs"]):
            doc = docs_by_id[node_id]
            assert ref["legal_id"] == doc["legal_id"]
            assert ref["entry_cid"] == doc["entry_cid"]
    assert "corrects" in relations
    assert "withdraws" in relations


# ---------------------------------------------------------------------------
# Hard negatives
# ---------------------------------------------------------------------------


def test_hard_negatives_present_and_consistent(gold: dict[str, Any]) -> None:
    validate_hard_negatives(gold)
    assert gold["counts"]["hard_negatives"] == len(gold["hard_negatives"])
    assert gold["counts"]["hard_negatives"] >= 3

    kinds = {c["control_kind"] for c in gold["hard_negatives"]}
    for required in (
        "fabricated_document_number",
        "wrong_agency",
        "wrong_document_type",
    ):
        assert required in kinds

    partitions = {c["partition"] for c in gold["hard_negatives"]}
    assert set(PARTITIONS).issubset(partitions)

    exact_pairs = {
        (j["query_id"], j["document_id"])
        for j in gold["judgments"]
        if j["grade"] == "exact"
    }
    for control in gold["hard_negatives"]:
        qid = control.get("query_id")
        for doc_id in control.get("must_not_grade_exact_document_ids") or []:
            assert (qid, doc_id) not in exact_pairs


def test_hard_negative_contradiction_detected(gold: dict[str, Any]) -> None:
    broken = copy.deepcopy(gold)
    control = broken["hard_negatives"][0]
    banned = control.get("must_not_grade_exact_document_ids") or []
    if not banned:
        pytest.skip("no banned docs on first hard negative")
    # Force an exact judgment that contradicts the hard negative
    broken["judgments"].append(
        {
            "query_id": control["query_id"],
            "document_id": banned[0],
            "legal_id": next(
                d["legal_id"]
                for d in broken["documents"]
                if d["document_id"] == banned[0]
            ),
            "entry_cid": next(
                d["entry_cid"]
                for d in broken["documents"]
                if d["document_id"] == banned[0]
            ),
            "grade": "exact",
            "label_kind": "exact_document",
            "notes": "intentional contradiction",
        }
    )
    # Re-seal so schema path reaches hard-negative checks if seal checked first
    with pytest.raises(GoldLabelError):
        validate_hard_negatives(broken)


# ---------------------------------------------------------------------------
# Missing-body cases
# ---------------------------------------------------------------------------


def test_missing_body_cases_present(gold: dict[str, Any]) -> None:
    validate_missing_body_cases(gold)
    assert gold["counts"]["missing_body_cases"] >= 2

    non_body = [
        d
        for d in gold["documents"]
        if d["text_availability"] in BODY_DISPOSITIONS_WITHOUT_FULL_TEXT
        or d.get("body_present") is False
    ]
    assert len(non_body) >= 2

    for case in gold["missing_body_cases"]:
        assert case["must_not_claim_full_text"] is True
        assert case["text_availability"] in BODY_DISPOSITIONS_WITHOUT_FULL_TEXT
        assert case["body_present"] is False

    # No exact_document grade on missing-body docs
    missing_ids = {c["document_id"] for c in gold["missing_body_cases"]}
    for judgment in gold["judgments"]:
        if judgment["document_id"] in missing_ids:
            assert judgment["label_kind"] == "missing_body" or judgment["grade"] != "exact"
            assert not (
                judgment["grade"] == "exact"
                and judgment["label_kind"] == "exact_document"
            )


def test_time_sensitive_and_abstention_flags(gold: dict[str, Any]) -> None:
    special = [
        q
        for q in gold["queries"]
        if q["query_kind"] in {"time_sensitive", "abstention"}
        or q["expectation"] in {"time_sensitive", "abstention", "known_ambiguity"}
    ]
    assert special
    for query in special:
        assert query["must_expose_cutoff"] is True
        assert query["abstain_if_unscoped"] is True
    assert any(j["label_kind"] == "known_ambiguity" for j in gold["judgments"])

# ---------------------------------------------------------------------------
# Counts and evaluator loader API
# ---------------------------------------------------------------------------


def test_counts_reconcile(gold: dict[str, Any]) -> None:
    assert gold["counts"]["documents"] == len(gold["documents"])
    assert gold["counts"]["queries"] == len(gold["queries"])
    assert gold["counts"]["judgments"] == len(gold["judgments"])
    assert gold["counts"]["graph_paths"] == len(gold["graph_paths"])
    assert gold["counts"]["hard_negatives"] == len(gold["hard_negatives"])
    assert gold["counts"]["missing_body_cases"] == len(gold["missing_body_cases"])


def test_load_gold_set_api(gold_set: FederalRegisterGoldSet, gold: dict[str, Any]) -> None:
    assert gold_set.manifest_digest == gold["manifest_digest"]
    assert len(gold_set.documents) == gold["counts"]["documents"]
    assert len(gold_set.queries) == gold["counts"]["queries"]
    assert gold_set.queries_for_partition("test")
    assert gold_set.documents_by_id()
    sample_qid = gold["queries"][0]["query_id"]
    assert gold_set.judgments_for_query(sample_qid)


def test_validate_rejects_missing_agency_diversity(gold: dict[str, Any]) -> None:
    broken = copy.deepcopy(gold)
    for doc in broken["documents"]:
        if doc["agency_code"] == "EPA":
            doc["agency_code"] = "ZZZ"
    with pytest.raises(GoldDiversityError):
        validate_diversity(broken)


def test_apply_seal_round_trip(gold: dict[str, Any]) -> None:
    body = sealed_body(gold)
    resealed = apply_seal(body)
    assert resealed["manifest_digest"] == gold["manifest_digest"]


def test_write_gold_fixture_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "federal_register_gold_v1.json"
    written = write_gold_fixture(target)
    assert written == target
    loaded = load_and_validate_gold(target)
    assert loaded["manifest_digest"] == materialize_gold_payload()["manifest_digest"]
    assert loaded["counts"]["hard_negatives"] >= 3
    assert loaded["counts"]["missing_body_cases"] >= 2
