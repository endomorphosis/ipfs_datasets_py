"""Corpus differential and migration verification reports (KGP-028).

Validates that :mod:`ipfs_datasets_py.knowledge_graphs.migration.verifier`
produces revision-bound count/schema/checksum/provenance and golden-query
diffs for every named corpus, classifies expected ordering/precision
differences explicitly, supports sample and full modes, fails on unexplained
missing/extra entities/edges/results, and retains bounded evidence for each
mismatch.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from ipfs_datasets_py.knowledge_graphs.migration.verifier import (
    KNOWN_CORPORA,
    REPORT_SCHEMA_VERSION,
    CorpusDifferentialVerifier,
    CorpusSnapshot,
    DiffMode,
    DifferenceClassification,
    DifferenceKind,
    DifferentialVerificationError,
    ExpectedDifference,
    MultiCorpusDifferentialReport,
    build_minimal_snapshot,
    verify_all_corpora,
    verify_corpus_pair,
)

pytestmark = pytest.mark.integration

# Stable fixture revision (40-char hex) matching adapter LOCAL_FIXTURE_REVISION.
FIXTURE_REVISION = "0" * 40
OTHER_REVISION = "1" * 40

CORPUS_FIXTURES: dict[str, dict[str, Any]] = {
    "cvefixes": {
        "counts": {
            "graph_nodes": 4,
            "graph_edges": 3,
            "original_data_rows": 1,
        },
        "schema": {
            "schema_version": "cvefixes-huggingface-release/v1",
            "primary_key": "entry_cid",
            "node_types": ["cve", "cwe", "commit", "code_unit"],
            "edge_types": ["CLASSIFIED_AS", "FIXED_BY", "CHANGES"],
        },
        "checksums": {
            "data/graph/nodes/part-000000.parquet": "a" * 64,
            "data/graph/edges/part-000000.parquet": "b" * 64,
            "indexes/bm25_keyword_shards.parquet": "c" * 64,
        },
        "provenance": {
            "source_dataset_id": "jerauby/CVEfixes",
            "source_revision": "deadbeef" * 5,
            "graph_root_cid": "b" + "a" * 58,
        },
        "entities": [
            {"id": "node-cve-1", "type": "cve", "label": "CVE-2018-1000524"},
            {"id": "node-cwe-1", "type": "cwe", "label": "CWE-22"},
            {"id": "node-commit-1", "type": "commit", "label": "abc123"},
            {"id": "node-file-1", "type": "code_unit", "label": "path.c"},
        ],
        "edges": [
            {
                "id": "e1",
                "type": "CLASSIFIED_AS",
                "source": "node-cve-1",
                "target": "node-cwe-1",
            },
            {
                "id": "e2",
                "type": "FIXED_BY",
                "source": "node-cve-1",
                "target": "node-commit-1",
            },
            {
                "id": "e3",
                "type": "CHANGES",
                "source": "node-commit-1",
                "target": "node-file-1",
            },
        ],
        "golden_queries": {
            "bm25_overflow": [
                {"entry_cid": "entry-a", "score": 1.5},
            ],
            "traverse_cve": [
                {"id": "node-cve-1"},
                {"id": "node-cwe-1"},
                {"id": "node-commit-1"},
            ],
        },
    },
    "skillcenter": {
        "counts": {
            "graph_nodes": 5,
            "graph_edges": 4,
            "corpus_rows": 2,
            "vector_rows": 2,
        },
        "schema": {
            "schema_version": "skillcenter-huggingface-release/v3",
            "primary_key": "entry_cid",
            "node_types": ["skill", "category"],
            "edge_types": ["IN_CATEGORY", "RELATED_TO"],
        },
        "checksums": {
            "data/graph/nodes/part-000000.parquet": "d" * 64,
            "data/corpus/part-000000.parquet": "e" * 64,
        },
        "provenance": {
            "corpus_cid": "b" + "c" * 58,
            "graph_cid": "b" + "d" * 58,
            "bm25_sqlite_cid": "b" + "e" * 58,
            "vector_faiss_cid": "b" + "f" * 58,
        },
        "entities": [
            {"id": "skill-1", "type": "skill", "name": "credentials"},
            {"id": "skill-2", "type": "skill", "name": "networking"},
            {"id": "cat-1", "type": "category", "name": "security"},
            {"id": "cat-2", "type": "category", "name": "ops"},
            {"id": "skill-3", "type": "skill", "name": "logging"},
        ],
        "edges": [
            {
                "id": "se1",
                "type": "IN_CATEGORY",
                "source": "skill-1",
                "target": "cat-1",
            },
            {
                "id": "se2",
                "type": "IN_CATEGORY",
                "source": "skill-2",
                "target": "cat-2",
            },
            {
                "id": "se3",
                "type": "RELATED_TO",
                "source": "skill-1",
                "target": "skill-2",
            },
            {
                "id": "se4",
                "type": "RELATED_TO",
                "source": "skill-2",
                "target": "skill-3",
            },
        ],
        "golden_queries": {
            "rank_skills_credentials": [
                {"entry_cid": "skill-1", "score": 2.0},
                {"entry_cid": "skill-2", "score": 1.0},
            ],
            "hybrid_credentials": [
                {"entry_cid": "skill-1", "score": 0.9},
            ],
        },
    },
    "two_eleven": {
        "counts": {
            "graph_nodes": 6,
            "graph_edges": 5,
            "documents": 3,
        },
        "schema": {
            "schema_version": "two-eleven-retrieval-package/v1",
            "node_types": ["organization", "location", "service"],
            "edge_types": ["LOCATED_IN", "OFFERS"],
        },
        "checksums": {
            "graph/nodes.parquet": "1" * 64,
            "graph/edges.parquet": "2" * 64,
            "documents/docs.parquet": "3" * 64,
        },
        "provenance": {
            "package_root_cid": "b" + "1" * 58,
            "source_tree": "211-AI/data/retrieval_package",
        },
        "entities": [
            {"id": "org-1", "type": "organization", "label": "Food Bank"},
            {"id": "loc-1", "type": "location", "label": "Portland"},
            {"id": "svc-1", "type": "service", "label": "food pantry"},
            {"id": "org-2", "type": "organization", "label": "Shelter"},
            {"id": "loc-2", "type": "location", "label": "Salem"},
            {"id": "svc-2", "type": "service", "label": "housing"},
        ],
        "edges": [
            {
                "id": "te1",
                "type": "LOCATED_IN",
                "source": "org-1",
                "target": "loc-1",
            },
            {
                "id": "te2",
                "type": "OFFERS",
                "source": "org-1",
                "target": "svc-1",
            },
            {
                "id": "te3",
                "type": "LOCATED_IN",
                "source": "org-2",
                "target": "loc-2",
            },
            {
                "id": "te4",
                "type": "OFFERS",
                "source": "org-2",
                "target": "svc-2",
            },
            {
                "id": "te5",
                "type": "LOCATED_IN",
                "source": "svc-1",
                "target": "loc-1",
            },
        ],
        "golden_queries": {
            "keyword_food_pantry": [
                {"doc_id": "doc-1", "score": 3.1},
                {"doc_id": "doc-2", "score": 1.2},
            ],
            "geography_portland_or": [
                {"id": "loc-1", "city": "Portland", "state": "OR"},
            ],
        },
    },
    "code_evidence": {
        "counts": {
            "objective_nodes": 3,
            "semantic_nodes": 4,
            "ast_nodes": 5,
            "conflict_nodes": 1,
            "evidence_nodes": 2,
            "impact_nodes": 2,
        },
        "schema": {
            "schema_version": "code-evidence-bundle/v1",
            "graph_kinds": [
                "objective",
                "semantic_dependency",
                "ast_index",
                "conflict",
                "code_evidence",
                "impact_index",
            ],
        },
        "checksums": {
            "objective_graph.json": "aa" * 32,
            "semantic_dependency_graph.json": "bb" * 32,
            "code_evidence_graph.json": "cc" * 32,
        },
        "provenance": {
            "bundle_revision": FIXTURE_REVISION,
            "source": "agent-supervisor",
        },
        "entities": [
            {"id": "obj-1", "type": "objective", "title": "Harden graphs"},
            {"id": "sem-1", "type": "module", "path": "kg/adapters.py"},
            {"id": "ast-1", "type": "function", "name": "validate"},
            {"id": "ev-1", "type": "evidence", "ref": "KGP-027"},
        ],
        "edges": [
            {
                "id": "ce1",
                "type": "DEPENDS_ON",
                "source": "obj-1",
                "target": "sem-1",
            },
            {
                "id": "ce2",
                "type": "IMPLEMENTS",
                "source": "sem-1",
                "target": "ast-1",
            },
            {
                "id": "ce3",
                "type": "SUPPORTED_BY",
                "source": "obj-1",
                "target": "ev-1",
            },
        ],
        "golden_queries": {
            "impact_of_sem-1": [
                {"id": "obj-1"},
                {"id": "ast-1"},
            ],
            "provenance_ev-1": [
                {"id": "ev-1", "ref": "KGP-027"},
            ],
        },
    },
}


def _snapshot(
    corpus_id: str,
    *,
    revision: str = FIXTURE_REVISION,
    mutate: Any = None,
) -> CorpusSnapshot:
    payload = copy.deepcopy(CORPUS_FIXTURES[corpus_id])
    snap = build_minimal_snapshot(
        corpus_id,
        revision,
        counts=payload["counts"],
        schema=payload["schema"],
        checksums=payload["checksums"],
        provenance=payload["provenance"],
        entities=payload["entities"],
        edges=payload["edges"],
        golden_queries=payload["golden_queries"],
        metadata={"fixture": True},
    )
    if mutate is not None:
        mutate(snap)
    return snap


def _identical_pair(corpus_id: str) -> tuple[CorpusSnapshot, CorpusSnapshot]:
    return _snapshot(corpus_id), _snapshot(corpus_id)


# ---------------------------------------------------------------------------
# Happy path: every corpus, full + sample modes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corpus_id", sorted(CORPUS_FIXTURES))
@pytest.mark.parametrize("mode", [DiffMode.FULL, DiffMode.SAMPLE])
def test_identical_snapshots_pass_for_every_corpus(
    corpus_id: str, mode: DiffMode
) -> None:
    baseline, candidate = _identical_pair(corpus_id)
    report = verify_corpus_pair(baseline, candidate, mode=mode)
    assert report.passed is True
    assert report.corpus_id == corpus_id
    assert report.mode is mode
    assert report.baseline_revision == FIXTURE_REVISION
    assert report.candidate_revision == FIXTURE_REVISION
    assert report.baseline_fingerprint == report.candidate_fingerprint
    assert report.report_digest
    assert len(report.report_digest) == 64
    assert report.unexpected_mismatches == []
    payload = report.to_dict()
    assert payload["schema"] == REPORT_SCHEMA_VERSION
    assert payload["passed"] is True
    for section in (
        "count_diff",
        "schema_diff",
        "checksum_diff",
        "provenance_diff",
        "entity_diff",
        "edge_diff",
        "golden_query_diff",
    ):
        assert payload[section]["matched"] is True, section


def test_multi_corpus_report_covers_every_known_corpus() -> None:
    pairs = [_identical_pair(cid) for cid in sorted(KNOWN_CORPORA)]
    assert {p[0].corpus_id for p in pairs} == set(KNOWN_CORPORA)
    multi = verify_all_corpora(pairs, mode=DiffMode.FULL)
    assert isinstance(multi, MultiCorpusDifferentialReport)
    assert multi.passed is True
    assert len(multi.reports) == len(KNOWN_CORPORA)
    assert set(multi.to_dict()["corpus_ids"]) == set(KNOWN_CORPORA)
    assert multi.report_digest
    multi.raise_if_failed()


def test_from_validation_receipt_extracts_revision_bound_fields() -> None:
    receipt = {
        "schema": "cvefixes-corpus-validation-receipt/v1",
        "manifest": {
            "schema_version": "cvefixes-huggingface-release/v1",
            "primary_key": "entry_cid",
            "counts": {"graph_nodes": 4, "graph_edges": 3},
        },
        "provenance": {
            "source_dataset_id": "jerauby/CVEfixes",
            "graph_root_cid": "b" + "a" * 58,
        },
        "shards": {
            "kinds": {
                "graph_nodes": {"shard_count": 1},
                "graph_edges": {"shard_count": 1},
            },
            "checksums": {
                "data/graph/nodes/part-000000.parquet": "a" * 64,
            },
        },
    }
    snap = CorpusSnapshot.from_validation_receipt(
        corpus_id="cvefixes",
        revision=FIXTURE_REVISION,
        receipt=receipt,
        entities=[{"id": "node-cve-1", "type": "cve"}],
        golden_queries={"bm25": [{"entry_cid": "entry-a"}]},
    )
    assert snap.counts["graph_nodes"] == 4
    assert snap.schema["schema_version"] == "cvefixes-huggingface-release/v1"
    assert snap.schema["shard_kinds"] == ["graph_edges", "graph_nodes"]
    assert snap.checksums["data/graph/nodes/part-000000.parquet"] == "a" * 64
    assert snap.provenance["source_dataset_id"] == "jerauby/CVEfixes"
    assert snap.revision == FIXTURE_REVISION
    assert snap.fingerprint()


# ---------------------------------------------------------------------------
# Fail-closed: missing / extra entities, edges, results
# ---------------------------------------------------------------------------


def test_unexplained_missing_entity_fails_with_bounded_evidence() -> None:
    baseline = _snapshot("cvefixes")
    candidate = _snapshot(
        "cvefixes",
        mutate=lambda s: s.entities.__setitem__(
            slice(0, None),
            [e for e in s.entities if e["id"] != "node-cwe-1"],
        ),
    )
    # counts still list 4 nodes — also a count mismatch; strip counts to isolate entity.
    candidate.counts = dict(baseline.counts)
    report = verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)
    assert report.passed is False
    assert any(
        m.classification is DifferenceClassification.MISSING
        and "node-cwe-1" in m.path
        for m in report.unexpected_mismatches
    )
    evidence = next(
        m for m in report.evidence if "node-cwe-1" in m.path
    )
    assert evidence.entity_ids == ["node-cwe-1"]
    assert evidence.baseline is not None
    assert evidence.candidate is None
    # Bounded: serializable and finite.
    raw = json.dumps(evidence.to_dict())
    assert len(raw) < 50_000
    with pytest.raises(DifferentialVerificationError, match="cvefixes"):
        report.raise_if_failed()


def test_unexplained_extra_edge_fails() -> None:
    baseline = _snapshot("skillcenter")
    candidate = _snapshot(
        "skillcenter",
        mutate=lambda s: s.edges.append(
            {
                "id": "se-extra",
                "type": "RELATED_TO",
                "source": "skill-1",
                "target": "skill-3",
            }
        ),
    )
    candidate.counts = dict(baseline.counts)
    report = verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)
    assert report.passed is False
    assert any(
        m.classification is DifferenceClassification.EXTRA and "se-extra" in m.path
        for m in report.unexpected_mismatches
    )


def test_unexplained_missing_golden_query_result_fails() -> None:
    baseline = _snapshot("two_eleven")
    candidate = _snapshot(
        "two_eleven",
        mutate=lambda s: s.golden_queries.__setitem__(
            "keyword_food_pantry",
            [s.golden_queries["keyword_food_pantry"][0]],
        ),
    )
    report = verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)
    assert report.passed is False
    assert any(
        m.classification is DifferenceClassification.MISSING
        and m.query_name == "keyword_food_pantry"
        for m in report.unexpected_mismatches
    )
    assert any(
        "missing" in " ".join(m.notes).lower() or m.classification is DifferenceClassification.MISSING
        for m in report.unexpected_mismatches
    )


def test_unexplained_extra_golden_query_result_fails() -> None:
    baseline = _snapshot("code_evidence")
    candidate = _snapshot(
        "code_evidence",
        mutate=lambda s: s.golden_queries["impact_of_sem-1"].append(
            {"id": "ghost-node"}
        ),
    )
    report = verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)
    assert report.passed is False
    assert any(
        m.classification is DifferenceClassification.EXTRA
        and m.query_name == "impact_of_sem-1"
        for m in report.unexpected_mismatches
    )


def test_count_checksum_schema_provenance_mismatches_fail() -> None:
    baseline = _snapshot("cvefixes")
    candidate = _snapshot("cvefixes")
    candidate.counts["graph_nodes"] = 99
    candidate.checksums["data/graph/nodes/part-000000.parquet"] = "f" * 64
    candidate.schema["schema_version"] = "cvefixes-huggingface-release/v9"
    candidate.provenance["graph_root_cid"] = "b" + "z" * 58
    report = verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)
    assert report.passed is False
    paths = {m.path for m in report.unexpected_mismatches}
    assert "counts.graph_nodes" in paths
    assert "checksums.data/graph/nodes/part-000000.parquet" in paths
    assert "schema.schema_version" in paths
    assert "provenance.graph_root_cid" in paths
    assert report.count_diff.matched is False
    assert report.checksum_diff.matched is False
    assert report.schema_diff.matched is False
    assert report.provenance_diff.matched is False


def test_mismatches_cannot_be_auto_waived() -> None:
    """Conflict policy: no silent waiver without ExpectedDifference."""

    baseline = _snapshot("skillcenter")
    candidate = _snapshot("skillcenter")
    candidate.counts["graph_nodes"] = 0
    # Empty expected_differences → must fail.
    verifier = CorpusDifferentialVerifier(
        mode=DiffMode.FULL, expected_differences=[]
    )
    report = verifier.compare(baseline, candidate)
    assert report.passed is False
    assert report.unexpected_mismatches


# ---------------------------------------------------------------------------
# Explicit classification of expected ordering / precision differences
# ---------------------------------------------------------------------------


def test_ordering_only_golden_query_requires_expected_ordering() -> None:
    baseline = _snapshot("skillcenter")
    candidate = _snapshot("skillcenter")
    results = list(candidate.golden_queries["rank_skills_credentials"])
    candidate.golden_queries["rank_skills_credentials"] = list(reversed(results))

    # Without declaration → fail.
    failed = verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)
    assert failed.passed is False
    assert any(
        m.path == "golden_queries.rank_skills_credentials"
        for m in failed.unexpected_mismatches
    )

    # With explicit expected_ordering → pass.
    declared = [
        ExpectedDifference(
            kind=DifferenceKind.GOLDEN_QUERY,
            classification=DifferenceClassification.EXPECTED_ORDERING,
            path="golden_queries.rank_skills_credentials",
            reason="BM25 ranker may reorder equal-score ties across runtimes",
            corpus_id="skillcenter",
        )
    ]
    passed = verify_corpus_pair(
        baseline,
        candidate,
        mode=DiffMode.FULL,
        expected_differences=declared,
    )
    assert passed.passed is True
    assert any(
        "expected_ordering" in item
        for item in passed.golden_query_diff.expected_classifications
    )
    # Evidence retained even for expected diffs.
    assert any(
        m.classification is DifferenceClassification.EXPECTED_ORDERING
        for m in passed.evidence
    )


def test_precision_only_score_requires_expected_precision() -> None:
    baseline = _snapshot("two_eleven")
    candidate = _snapshot("two_eleven")
    # Tiny float drift on the same result identity.
    candidate.golden_queries["keyword_food_pantry"] = [
        {"doc_id": "doc-1", "score": 3.1 + 1e-12},
        {"doc_id": "doc-2", "score": 1.2},
    ]

    failed = verify_corpus_pair(
        baseline,
        candidate,
        mode=DiffMode.FULL,
        precision_atol=1e-9,
        precision_rtol=1e-9,
    )
    # 1e-12 is within 1e-9 → precision-only; still fails without declaration.
    assert failed.passed is False

    declared = [
        ExpectedDifference(
            kind=DifferenceKind.GOLDEN_QUERY,
            classification=DifferenceClassification.EXPECTED_PRECISION,
            path="golden_queries.keyword_food_pantry",
            reason="float score serialization differs across numpy/pyarrow builds",
            corpus_id="two_eleven",
        )
    ]
    passed = verify_corpus_pair(
        baseline,
        candidate,
        mode=DiffMode.FULL,
        expected_differences=declared,
        precision_atol=1e-9,
        precision_rtol=1e-9,
    )
    assert passed.passed is True
    assert any(
        m.classification is DifferenceClassification.EXPECTED_PRECISION
        for m in passed.evidence
    )


def test_expected_declared_can_cover_schema_drift() -> None:
    baseline = _snapshot("code_evidence")
    candidate = _snapshot("code_evidence")
    candidate.schema["optional_extension"] = "experimental_kind"

    failed = verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)
    assert failed.passed is False

    declared = [
        ExpectedDifference(
            kind=DifferenceKind.SCHEMA,
            classification=DifferenceClassification.EXPECTED_DECLARED,
            path="schema.optional_extension",
            reason="candidate advertises optional unknown kinds (KGP-027)",
            corpus_id="code_evidence",
        )
    ]
    passed = verify_corpus_pair(
        baseline,
        candidate,
        mode=DiffMode.FULL,
        expected_differences=declared,
    )
    assert passed.passed is True


def test_expected_difference_rejects_unexpected_classification() -> None:
    with pytest.raises(ValueError, match="expected_"):
        ExpectedDifference(
            kind=DifferenceKind.COUNT,
            classification=DifferenceClassification.MISSING,
            path="counts.graph_nodes",
            reason="invalid",
        )


# ---------------------------------------------------------------------------
# Sample vs full modes
# ---------------------------------------------------------------------------


def test_sample_mode_ignores_entities_outside_sample_universe() -> None:
    baseline = _snapshot("cvefixes")
    candidate = _snapshot("cvefixes")
    # Extra entity only present in candidate — outside explicit sample.
    candidate.entities.append(
        {"id": "node-extra-outside-sample", "type": "cve", "label": "CVE-X"}
    )
    candidate.counts = dict(baseline.counts)

    full = verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)
    assert full.passed is False

    sample = verify_corpus_pair(
        baseline,
        candidate,
        mode=DiffMode.SAMPLE,
        sample_entity_ids=["node-cve-1", "node-cwe-1"],
        sample_edge_ids=["e1"],
    )
    assert sample.passed is True
    assert sample.entity_diff.details["mode"] == "sample"
    assert sample.entity_diff.details["compared_id_count"] == 2


def test_sample_mode_still_fails_on_missing_sampled_entity() -> None:
    baseline = _snapshot("cvefixes")
    candidate = _snapshot(
        "cvefixes",
        mutate=lambda s: s.entities.__setitem__(
            slice(0, None),
            [e for e in s.entities if e["id"] != "node-cve-1"],
        ),
    )
    candidate.counts = dict(baseline.counts)
    report = verify_corpus_pair(
        baseline,
        candidate,
        mode=DiffMode.SAMPLE,
        sample_entity_ids=["node-cve-1", "node-cwe-1"],
    )
    assert report.passed is False
    assert any("node-cve-1" in m.path for m in report.unexpected_mismatches)


def test_sample_mode_still_checks_counts_checksums_provenance() -> None:
    baseline = _snapshot("two_eleven")
    candidate = _snapshot("two_eleven")
    candidate.provenance["package_root_cid"] = "b" + "9" * 58
    report = verify_corpus_pair(
        baseline,
        candidate,
        mode=DiffMode.SAMPLE,
        sample_entity_ids=["org-1"],
        sample_edge_ids=["te1"],
    )
    assert report.passed is False
    assert any(
        m.path == "provenance.package_root_cid" for m in report.unexpected_mismatches
    )


def test_full_mode_compares_all_entities_and_edges() -> None:
    baseline = _snapshot("skillcenter")
    candidate = _snapshot("skillcenter")
    # Mutate the last entity only.
    candidate.entities[-1] = {
        **candidate.entities[-1],
        "name": "logging-renamed",
    }
    report = verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)
    assert report.passed is False
    assert "skill-3" in report.entity_diff.changed_keys


# ---------------------------------------------------------------------------
# Evidence bounds and content addressing
# ---------------------------------------------------------------------------


def test_evidence_is_bounded_for_large_payloads() -> None:
    big_blob = {"blob": "x" * 100_000, "nested": list(range(5000))}
    baseline = build_minimal_snapshot(
        "cvefixes",
        FIXTURE_REVISION,
        entities=[{"id": "huge", "payload": big_blob}],
        counts={"graph_nodes": 1},
    )
    candidate = build_minimal_snapshot(
        "cvefixes",
        FIXTURE_REVISION,
        entities=[{"id": "huge", "payload": {"blob": "y" * 100_000}}],
        counts={"graph_nodes": 1},
    )
    report = verify_corpus_pair(
        baseline,
        candidate,
        mode=DiffMode.FULL,
        max_evidence_bytes=512,
        max_evidence_items=8,
    )
    assert report.passed is False
    assert len(report.evidence) <= 8
    for item in report.evidence:
        encoded = json.dumps(item.to_dict())
        # Evidence values themselves are clipped; total row stays manageable.
        assert len(encoded) < 20_000
        if isinstance(item.baseline, dict) and item.baseline.get("_truncated"):
            assert item.baseline["_max_bytes"] == 512


def test_report_digest_is_content_addressed_and_stable() -> None:
    baseline, candidate = _identical_pair("code_evidence")
    a = verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)
    b = verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)
    assert a.report_digest == b.report_digest
    assert len(a.report_digest) == 64

    # Changing a count must change the digest.
    candidate2 = _snapshot("code_evidence")
    candidate2.counts["objective_nodes"] = 99
    c = verify_corpus_pair(baseline, candidate2, mode=DiffMode.FULL)
    assert c.report_digest != a.report_digest


def test_revision_mismatch_fails_unless_declared() -> None:
    baseline = _snapshot("cvefixes", revision=FIXTURE_REVISION)
    candidate = _snapshot("cvefixes", revision=OTHER_REVISION)
    failed = verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)
    assert failed.passed is False
    assert any(m.path == "revision" for m in failed.unexpected_mismatches)

    declared = [
        ExpectedDifference(
            kind=DifferenceKind.REVISION,
            classification=DifferenceClassification.EXPECTED_DECLARED,
            path="revision",
            reason="candidate re-bound to migrated catalog revision",
            corpus_id="cvefixes",
        )
    ]
    passed = verify_corpus_pair(
        baseline,
        candidate,
        mode=DiffMode.FULL,
        expected_differences=declared,
    )
    assert passed.passed is True


def test_corpus_id_mismatch_raises() -> None:
    baseline = _snapshot("cvefixes")
    candidate = _snapshot("skillcenter")
    with pytest.raises(DifferentialVerificationError, match="corpus_id"):
        verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)


def test_require_known_corpus_rejects_unknown() -> None:
    snap = build_minimal_snapshot("not-a-corpus", FIXTURE_REVISION)
    verifier = CorpusDifferentialVerifier(
        mode=DiffMode.FULL, require_known_corpus=True
    )
    with pytest.raises(DifferentialVerificationError, match="unknown corpus"):
        verifier.compare(snap, snap)


def test_multi_corpus_fails_if_any_member_fails() -> None:
    pairs = [_identical_pair(cid) for cid in sorted(KNOWN_CORPORA)]
    # Break one corpus.
    broken_baseline, broken_candidate = pairs[0]
    broken_candidate = _snapshot(broken_baseline.corpus_id)
    broken_candidate.counts = {
        k: v + 1 for k, v in broken_candidate.counts.items()
    }
    pairs[0] = (broken_baseline, broken_candidate)
    multi = verify_all_corpora(pairs, mode=DiffMode.SAMPLE)
    assert multi.passed is False
    with pytest.raises(DifferentialVerificationError, match="multi-corpus"):
        multi.raise_if_failed()


def test_snapshot_requires_revision_binding() -> None:
    with pytest.raises(ValueError, match="revision"):
        CorpusSnapshot(corpus_id="cvefixes", revision="")


def test_assert_equivalent_returns_report_when_matched() -> None:
    baseline, candidate = _identical_pair("two_eleven")
    verifier = CorpusDifferentialVerifier(mode=DiffMode.SAMPLE)
    report = verifier.assert_equivalent(baseline, candidate)
    assert report.passed is True


def test_compare_all_requires_pairs() -> None:
    verifier = CorpusDifferentialVerifier(mode=DiffMode.FULL)
    with pytest.raises(DifferentialVerificationError, match="at least one"):
        verifier.compare_all([])


def test_expected_difference_round_trip() -> None:
    original = ExpectedDifference(
        kind=DifferenceKind.PROVENANCE,
        classification=DifferenceClassification.EXPECTED_DECLARED,
        path="provenance.source_revision",
        reason="source pin differs by design in shadow mode",
        corpus_id="cvefixes",
    )
    restored = ExpectedDifference.from_dict(original.to_dict())
    assert restored == original


def test_section_diffs_serialize_for_offline_reproduction() -> None:
    baseline = _snapshot("cvefixes")
    candidate = _snapshot("cvefixes")
    candidate.entities = [e for e in candidate.entities if e["id"] != "node-file-1"]
    candidate.edges = [e for e in candidate.edges if e["id"] != "e3"]
    candidate.counts = dict(baseline.counts)
    report = verify_corpus_pair(baseline, candidate, mode=DiffMode.FULL)
    blob = report.to_dict()
    # Enough evidence to reproduce: paths, ids, clipped baseline payloads.
    assert blob["entity_diff"]["missing_keys"] == ["node-file-1"]
    assert blob["edge_diff"]["missing_keys"] == ["e3"]
    entity_ev = next(m for m in blob["evidence"] if "node-file-1" in m["path"])
    assert entity_ev["entity_ids"] == ["node-file-1"]
    assert entity_ev["baseline"]["label"] == "path.c"
    edge_ev = next(m for m in blob["evidence"] if "e3" in m["path"])
    assert edge_ev["edge_ids"] == ["e3"]
    # Round-trip through JSON for offline tooling.
    restored = json.loads(json.dumps(blob))
    assert restored["report_digest"] == blob["report_digest"]
    assert restored["passed"] is False
