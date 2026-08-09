"""Unit tests for USCIR-001 pinned US Code baseline audit freeze."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ops.legal_data.audit_uscode_hf_baseline import (
    BM25_DOCUMENT_COUNT,
    CANONICAL_CID_COUNT,
    CORPUS_ROW_COUNT,
    DATASET_REPO_ID,
    KG_ENTITY_COUNT,
    KG_RELATIONSHIP_COUNT,
    PINNED_REVISION,
    RECOVERY_ROW_COUNT,
    REPORT_SCHEMA,
    TITLE_COUNT,
    VECTOR_ROW_COUNT,
    BaselineAuditError,
    acceptance_projection,
    build_fixture_baseline_report,
    check_baseline_report,
    default_report_path,
    expected_acceptance,
    expected_title_numbers,
    load_baseline_report,
    main,
    validate_baseline_report,
    write_baseline_report,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_expected_title_numbers_cover_1_to_52_and_54() -> None:
    titles = expected_title_numbers()
    assert len(titles) == TITLE_COUNT == 53
    assert titles == list(range(1, 53)) + [54]
    assert 53 not in titles


def test_fixture_report_acceptance_matches_sealed_counts() -> None:
    report = build_fixture_baseline_report()
    acceptance = acceptance_projection(report)
    assert acceptance == expected_acceptance()
    assert acceptance == {
        "corpus_rows": 60_077,
        "canonical_cids": 60_068,
        "recovery_rows": 9,
        "vectors": 185_563,
        "bm25_documents": 60_068,
        "kg_entities": 180_257,
        "kg_relationships": 120_136,
        "titles": 53,
        "pinned_revision": PINNED_REVISION,
    }
    assert (
        acceptance["corpus_rows"]
        == acceptance["canonical_cids"] + acceptance["recovery_rows"]
    )


def test_fixture_report_accounts_for_legacy_artifacts_and_viewer() -> None:
    report = build_fixture_baseline_report()
    assert report["schema"] == REPORT_SCHEMA
    assert report["dataset"]["repo_id"] == DATASET_REPO_ID
    assert report["dataset"]["revision"] == PINNED_REVISION
    assert report["dataset"]["revision_pinned"] is True
    assert report["network_required"] is False

    counts = report["counts"]
    assert counts["corpus_rows"] == CORPUS_ROW_COUNT
    assert counts["canonical_cids"] == CANONICAL_CID_COUNT
    assert counts["recovery_rows"] == RECOVERY_ROW_COUNT
    assert counts["vectors"] == VECTOR_ROW_COUNT
    assert counts["bm25_documents"] == BM25_DOCUMENT_COUNT
    assert counts["kg_entities"] == KG_ENTITY_COUNT
    assert counts["kg_relationships"] == KG_RELATIONSHIP_COUNT
    assert counts["titles"] == TITLE_COUNT

    by_path = {item["path"]: item for item in report["artifacts"]}
    assert by_path["uscode_parquet/laws.parquet"]["row_count"] == CORPUS_ROW_COUNT
    assert by_path["uscode_parquet/laws.parquet"]["row_groups"] == 1
    assert by_path["uscode_parquet/cid_index.parquet"]["row_count"] == CANONICAL_CID_COUNT
    assert by_path["uscode_parquet/laws_bm25.parquet"]["row_count"] == BM25_DOCUMENT_COUNT
    assert (
        by_path["uscode_parquet/laws_embeddings.parquet"]["row_count"] == VECTOR_ROW_COUNT
    )
    assert (
        by_path["uscode_parquet/laws_knowledge_graph_entities.parquet"]["row_count"]
        == KG_ENTITY_COUNT
    )
    assert (
        by_path["uscode_parquet/laws_knowledge_graph_relationships.parquet"]["row_count"]
        == KG_RELATIONSHIP_COUNT
    )

    assert report["viewer"]["dataset_viewer_valid"] is False
    assert report["legacy_joins"]["corpus_to_embeddings"]["trusted_for_migration"] is False
    anomaly_codes = {item["code"] for item in report["identity_anomalies"]}
    assert "RECOVERY_ROWS_WITHOUT_CID" in anomaly_codes
    assert "POSITIONAL_EMBEDDING_JOIN" in anomaly_codes
    assert report["citations"]["usc_citation_occurrences"] == 105_055
    assert report["citations"]["public_law_occurrences"] == 234_393


def test_check_baseline_report_passes_for_fixture() -> None:
    report = build_fixture_baseline_report()
    result = check_baseline_report(report)
    assert result["ok"] is True
    assert result["pinned_revision"] == PINNED_REVISION
    assert result["mismatches"] == []


def test_validate_detects_count_tampering() -> None:
    report = build_fixture_baseline_report()
    report["counts"]["corpus_rows"] = 1
    report["acceptance"]["corpus_rows"] = 1
    mismatches = validate_baseline_report(report)
    assert any("corpus_rows" in item for item in mismatches)
    with pytest.raises(BaselineAuditError, match="baseline report check failed"):
        check_baseline_report(report)


def test_validate_detects_revision_tampering() -> None:
    report = build_fixture_baseline_report()
    report["dataset"]["revision"] = "main"
    report["acceptance"]["pinned_revision"] = "main"
    mismatches = validate_baseline_report(report)
    assert any("revision" in item or "pinned_revision" in item for item in mismatches)


def test_frozen_report_on_disk_matches_acceptance() -> None:
    path = default_report_path(_repo_root())
    assert path.is_file(), f"frozen report missing: {path}"
    report = load_baseline_report(path)
    check_baseline_report(report)
    assert acceptance_projection(report) == expected_acceptance()
    assert report["schema"] == REPORT_SCHEMA
    assert report["dataset"]["revision"] == PINNED_REVISION


def test_write_and_reload_round_trip(tmp_path: Path) -> None:
    report = build_fixture_baseline_report()
    out = tmp_path / "baseline.json"
    write_baseline_report(report, out)
    reloaded = load_baseline_report(out)
    assert acceptance_projection(reloaded) == expected_acceptance()
    check_baseline_report(reloaded)
    # Stable canonical JSON serialization
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")
    parsed = json.loads(text)
    assert parsed["counts"]["titles"] == 53


def test_main_fixture_only_check_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--fixture-only", "--check"])
    captured = capsys.readouterr()
    assert code == 0
    assert "ok=True" in captured.out
    assert PINNED_REVISION in captured.out
    assert "corpus=60077" in captured.out
    assert "canonical=60068" in captured.out
    assert "recovery=9" in captured.out
    assert "vectors=185563" in captured.out
    assert "titles=53" in captured.out


def test_main_check_without_fixture_only_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["--check"])
    captured = capsys.readouterr()
    assert code == 1
    assert "fixture-only" in captured.err


def test_main_write_and_check_tmp(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "uscode_sparse_graphrag_baseline.json"
    write_code = main(["--fixture-only", "--write", "--report", str(out)])
    assert write_code == 0
    assert out.is_file()
    check_code = main(["--fixture-only", "--check", "--report", str(out)])
    captured = capsys.readouterr()
    assert check_code == 0
    assert "ok=True" in captured.out


def test_main_detects_tampered_on_disk_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "tampered.json"
    report = build_fixture_baseline_report()
    report["counts"]["vectors"] = 0
    report["acceptance"]["vectors"] = 0
    write_baseline_report(report, out)
    code = main(["--fixture-only", "--check", "--report", str(out)])
    captured = capsys.readouterr()
    assert code == 1
    assert "error:" in captured.err


def test_constants_match_plan_acceptance_table() -> None:
    assert CORPUS_ROW_COUNT == 60_077
    assert CANONICAL_CID_COUNT == 60_068
    assert RECOVERY_ROW_COUNT == 9
    assert VECTOR_ROW_COUNT == 185_563
    assert BM25_DOCUMENT_COUNT == 60_068
    assert KG_ENTITY_COUNT == 180_257
    assert KG_RELATIONSHIP_COUNT == 120_136
    assert TITLE_COUNT == 53
    assert PINNED_REVISION == "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
    assert DATASET_REPO_ID == "justicedao/ipfs_uscode"


def test_machine_checkable_sections_present() -> None:
    """Effects clause: counts, schemas, row groups, identity, joins, citations, sizes, viewer."""
    report = build_fixture_baseline_report()
    required: list[str] = [
        "counts",
        "schemas",
        "row_groups",
        "identity_anomalies",
        "legacy_joins",
        "citations",
        "sizes",
        "viewer",
        "artifacts",
        "titles",
        "acceptance",
    ]
    for key in required:
        assert key in report, f"missing machine-checkable section {key}"
    assert report["row_groups"]["legacy_monoliths_exceed_target"] is True
    assert report["schemas"]["bm25"]["k1"] == 1.5
    assert report["schemas"]["vectors"]["dimension"] == 384
