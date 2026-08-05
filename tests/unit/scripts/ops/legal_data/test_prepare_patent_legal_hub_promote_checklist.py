"""Unit tests for PATLAW-178 promote checklist preparation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from scripts.ops.legal_data.prepare_patent_legal_hub_promote_checklist import (
    CHECKLIST_SCHEMA,
    ContentFreeViolationError,
    EvidenceGapError,
    PROJECTION_FAMILIES,
    PromoteChecklistError,
    TASK_ID,
    UnpinnedRevisionError,
    build_promote_checklist,
    main,
)


def _hex(n: int = 64, seed: str = "a") -> str:
    unit = (seed * 64)[:64]
    return (unit * ((n // 64) + 1))[:n]


PLAN = _hex(64, "1")
DIFF = _hex(64, "2")
PKG_ROOT = "baguqeerapromotechecklistpackage000000000000000000000000001"
CORPUS = "baguqeeracorpusroot00000000000000000000000000000000000001"
BM25 = "baguqeerabm25root0000000000000000000000000000000000000001"
VECTORS = "baguqeeravectorsroot0000000000000000000000000000000000001"
GRAPH = "baguqeeragraphroot000000000000000000000000000000000000001"
SHA_A = _hex(40, "a")
SHA_B = _hex(40, "b")
SHA_C = _hex(40, "c")
SHA_D = _hex(40, "d")
BASE_A = _hex(40, "e")


def _stage_receipt(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "staged_pending_approval",
        "receipt_schema": "patent-legal-hub-index-stage/v1",
        "organization": "justicedao",
        "version_tag": "v2",
        "release_id": "hub-index-v2-demo",
        "package_root_cid": PKG_ROOT,
        "release_root_cid": PKG_ROOT,
        "plan_digest": PLAN,
        "staged_diff_digest": DIFF,
        "branch_name": "stage/patent-legal/hub-index-v2",
        "corpus_root_cid": CORPUS,
        "bm25_root_cid": BM25,
        "vector_root_cid": VECTORS,
        "graph_root_cid": GRAPH,
        "package_digest_sha256": _hex(64, "9"),
        "repositories": [
            {
                "dataset_id": "justicedao/patent-legal-corpus",
                "base_commit": BASE_A,
                "branch_name": "stage/patent-legal/hub-index-v2",
                "staged_commit_sha": SHA_A,
                "pull_request_number": 11,
            },
            {
                "dataset_id": "justicedao/patent-legal-bm25",
                "base_commit": BASE_A,
                "branch_name": "stage/patent-legal/hub-index-v2",
                "staged_commit_sha": SHA_B,
            },
            {
                "dataset_id": "justicedao/patent-legal-vectors",
                "base_commit": BASE_A,
                "branch_name": "stage/patent-legal/hub-index-v2",
                "staged_commit_sha": SHA_C,
            },
            {
                "dataset_id": "justicedao/patent-legal-knowledge-graph",
                "base_commit": BASE_A,
                "branch_name": "stage/patent-legal/hub-index-v2",
                "staged_commit_sha": SHA_D,
            },
        ],
    }
    payload.update(overrides)
    return payload


def _verification_receipt(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "verified",
        "package_root_cid": PKG_ROOT,
        "projection_digests": {
            "corpus": {"root_cid": CORPUS, "sha256": _hex(64, "c")},
            "bm25": {"root_cid": BM25, "sha256": _hex(64, "d")},
            "vectors": {"root_cid": VECTORS, "sha256": _hex(64, "e")},
            "knowledge_graph": {"root_cid": GRAPH, "sha256": _hex(64, "f")},
        },
    }
    payload.update(overrides)
    return payload


def test_build_binds_core_digests_and_projections() -> None:
    checklist = build_promote_checklist(
        stage_receipt=_stage_receipt(),
        verification_receipt=_verification_receipt(),
        generated_at="2026-08-04T00:00:00+00:00",
    )
    assert checklist["task_id"] == TASK_ID
    assert checklist["checklist_schema"] == CHECKLIST_SCHEMA
    assert checklist["package_root_cid"] == PKG_ROOT
    assert checklist["plan_digest"] == PLAN
    assert checklist["staged_diff_digest"] == DIFF
    assert checklist["auto_promote"] is False
    assert checklist["main_published"] is False
    assert checklist["disposition"] == "staged_not_promoted"
    for family in PROJECTION_FAMILIES:
        assert family in checklist["projection_digests"]
        assert checklist["projection_digests"][family]["root_cid"]
    assert len(checklist["staged_repositories"]) == 4
    assert checklist["acceptance"]["no_auto_promote_path"] is True
    assert re.fullmatch(r"[0-9a-f]{64}", checklist["checklist_digest_sha256"])


def test_all_steps_require_human_and_are_not_automated() -> None:
    checklist = build_promote_checklist(stage_receipt=_stage_receipt())
    assert checklist["steps"]
    for step in checklist["steps"]:
        assert step["requires_human"] is True
        assert step["automated_by_this_tool"] is False
        assert step["auto_promote"] is False
    step_ids = {s["step_id"] for s in checklist["steps"]}
    assert {
        "review-evidence",
        "sign-approval",
        "promote",
        "pin-verify",
        "canary",
        "rollback",
    } <= step_ids


def test_missing_plan_digest_fails_closed() -> None:
    stage = _stage_receipt()
    del stage["plan_digest"]
    with pytest.raises(EvidenceGapError, match="plan_digest"):
        build_promote_checklist(stage_receipt=stage)


def test_missing_staged_diff_digest_fails_closed() -> None:
    stage = _stage_receipt()
    del stage["staged_diff_digest"]
    with pytest.raises(EvidenceGapError, match="staged_diff_digest"):
        build_promote_checklist(stage_receipt=stage)


def test_missing_package_root_fails_closed() -> None:
    stage = _stage_receipt()
    del stage["package_root_cid"]
    del stage["release_root_cid"]
    with pytest.raises(EvidenceGapError, match="package_root_cid"):
        build_promote_checklist(stage_receipt=stage)


@pytest.mark.parametrize("token", ["main", "latest", "HEAD", "Master", "origin/main"])
def test_rejects_unpinned_target_revision(token: str) -> None:
    stage = _stage_receipt(target_revision=token)
    with pytest.raises(UnpinnedRevisionError):
        build_promote_checklist(stage_receipt=stage)


def test_rejects_unpinned_staged_commit_sha() -> None:
    stage = _stage_receipt()
    stage["repositories"][0]["staged_commit_sha"] = "main"
    with pytest.raises(UnpinnedRevisionError):
        build_promote_checklist(stage_receipt=stage)


def test_rejects_default_branch_as_stage_branch() -> None:
    stage = _stage_receipt(branch_name="main")
    with pytest.raises(UnpinnedRevisionError):
        build_promote_checklist(stage_receipt=stage)


def test_rejects_credential_shaped_stage_receipt() -> None:
    stage = _stage_receipt()
    stage["hf_token"] = "hf_abcdefghijklmnopqrstuv"
    with pytest.raises(PromoteChecklistError, match="credentials"):
        build_promote_checklist(stage_receipt=stage)


def test_verification_root_mismatch_recorded_as_gap() -> None:
    checklist = build_promote_checklist(
        stage_receipt=_stage_receipt(),
        verification_receipt=_verification_receipt(
            package_root_cid="baguqeeraotherroot00000000000000000000000000000000001"
        ),
    )
    kinds = {g["kind"] for g in checklist["evidence_gaps"]}
    assert "verification_package_root_mismatch" in kinds


def test_missing_verification_is_gap_not_hard_fail() -> None:
    checklist = build_promote_checklist(stage_receipt=_stage_receipt())
    assert checklist["verification_bound"] is False
    kinds = {g["kind"] for g in checklist["evidence_gaps"]}
    assert "verification_receipt_absent" in kinds


def test_missing_projection_digests_recorded_as_gaps() -> None:
    stage = _stage_receipt()
    for key in (
        "corpus_root_cid",
        "bm25_root_cid",
        "vector_root_cid",
        "graph_root_cid",
    ):
        del stage[key]
    checklist = build_promote_checklist(stage_receipt=stage)
    families = {
        g["family"]
        for g in checklist["evidence_gaps"]
        if g.get("kind") == "missing_projection_digest"
    }
    assert families == set(PROJECTION_FAMILIES)


def test_missing_repositories_recorded_as_gap() -> None:
    stage = _stage_receipt(repositories=[])
    checklist = build_promote_checklist(stage_receipt=stage)
    kinds = {g["kind"] for g in checklist["evidence_gaps"]}
    assert "missing_staged_repositories" in kinds
    assert checklist["acceptance"]["binds_staged_commit_sha"] is False


def test_package_manifest_fills_projection_roots() -> None:
    stage = _stage_receipt()
    for key in (
        "corpus_root_cid",
        "bm25_root_cid",
        "vector_root_cid",
        "graph_root_cid",
        "package_digest_sha256",
    ):
        del stage[key]
    manifest = {
        "package_root_cid": PKG_ROOT,
        "corpus_root_cid": CORPUS,
        "bm25_root_cid": BM25,
        "vector_root_cid": VECTORS,
        "graph_root_cid": GRAPH,
        "package_digest_sha256": _hex(64, "8"),
    }
    checklist = build_promote_checklist(
        stage_receipt=stage, package_manifest=manifest
    )
    assert checklist["projection_digests"]["bm25"]["root_cid"] == BM25
    assert checklist["package_digest_sha256"] == _hex(64, "8")


def test_admission_mismatch_recorded_as_gap() -> None:
    checklist = build_promote_checklist(
        stage_receipt=_stage_receipt(),
        admission_receipt={
            "package_root_cid": "baguqeeraadmissionmismatch0000000000000000000000001"
        },
    )
    kinds = {g["kind"] for g in checklist["evidence_gaps"]}
    assert "admission_package_root_mismatch" in kinds


def test_digest_is_stable_for_identical_inputs() -> None:
    kwargs = dict(
        stage_receipt=_stage_receipt(),
        verification_receipt=_verification_receipt(),
        generated_at="2026-08-04T00:00:00+00:00",
    )
    a = build_promote_checklist(**kwargs)
    b = build_promote_checklist(**kwargs)
    assert a["checklist_digest_sha256"] == b["checklist_digest_sha256"]


def test_cli_writes_output(tmp_path: Path) -> None:
    stage_path = tmp_path / "stage.json"
    stage_path.write_text(json.dumps(_stage_receipt()), encoding="utf-8")
    out = tmp_path / "checklist.json"
    rc = main(["--stage-receipt", str(stage_path), "--output", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["task_id"] == TASK_ID
    assert payload["plan_digest"] == PLAN


def test_cli_require_no_gaps_fails_when_gaps(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage = _stage_receipt(repositories=[])
    stage_path = tmp_path / "stage.json"
    stage_path.write_text(json.dumps(stage), encoding="utf-8")
    rc = main(["--stage-receipt", str(stage_path), "--require-no-gaps"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "evidence_gaps" in err or "error:" in err


def test_cli_fail_on_missing_verification(tmp_path: Path) -> None:
    stage_path = tmp_path / "stage.json"
    stage_path.write_text(json.dumps(_stage_receipt()), encoding="utf-8")
    rc = main(
        ["--stage-receipt", str(stage_path), "--fail-on-missing-verification"]
    )
    assert rc == 1


def test_cli_accepts_verification_receipt(tmp_path: Path) -> None:
    stage_path = tmp_path / "stage.json"
    verify_path = tmp_path / "verify.json"
    stage_path.write_text(json.dumps(_stage_receipt()), encoding="utf-8")
    verify_path.write_text(json.dumps(_verification_receipt()), encoding="utf-8")
    out = tmp_path / "checklist.json"
    rc = main(
        [
            "--stage-receipt",
            str(stage_path),
            "--verification-receipt",
            str(verify_path),
            "--output",
            str(out),
            "--require-no-gaps",
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["verification_bound"] is True
    assert payload["evidence_gaps"] == []


def test_content_free_reject_unknown_top_level_via_monkeypatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard: if a future change injects a free-form key, content-free fails."""
    import scripts.ops.legal_data.prepare_patent_legal_hub_promote_checklist as mod

    original = mod.build_promote_checklist

    def _wrap(**kwargs: Any) -> dict[str, Any]:
        checklist = original(**kwargs)
        checklist["narrative_blob"] = "should not be allowed"
        # re-run content free assertion path by calling private helper
        with pytest.raises(ContentFreeViolationError):
            mod._assert_content_free_keys(checklist)
        # strip for return if someone uses return value
        del checklist["narrative_blob"]
        return checklist

    monkeypatch.setattr(mod, "build_promote_checklist", _wrap)
    checklist = mod.build_promote_checklist(stage_receipt=_stage_receipt())
    assert "narrative_blob" not in checklist


def test_vector_alias_normalized_to_vectors() -> None:
    stage = _stage_receipt()
    for key in (
        "corpus_root_cid",
        "bm25_root_cid",
        "vector_root_cid",
        "graph_root_cid",
    ):
        del stage[key]
    stage["projection_digests"] = {
        "vector": {"root_cid": VECTORS},
        "graph": {"root_cid": GRAPH},
        "corpus": {"root_cid": CORPUS},
        "bm25": {"root_cid": BM25},
    }
    checklist = build_promote_checklist(stage_receipt=stage)
    assert "vectors" in checklist["projection_digests"]
    assert "knowledge_graph" in checklist["projection_digests"]


def test_expanded_path_digests_are_content_free() -> None:
    """Live pin-verify path→sha256 maps must not break checklist allowlist."""

    path_digest = _hex(64, "7")
    verification = _verification_receipt(
        projection_digests={
            "corpus": {
                "root_cid": CORPUS,
                "artifacts-inventory.json": path_digest,
                "indexes/corpus/documents.jsonl": path_digest,
            },
            "bm25": {
                "root_cid": BM25,
                "indexes/bm25/bm25-postings.jsonl": path_digest,
            },
            "vectors": {
                "root_cid": VECTORS,
                "indexes/vectors/vectors.jsonl": path_digest,
            },
            "knowledge_graph": {
                "root_cid": GRAPH,
                "indexes/knowledge_graph/graph.jsonld": path_digest,
            },
        }
    )
    checklist = build_promote_checklist(
        stage_receipt=_stage_receipt(),
        verification_receipt=verification,
    )
    assert (
        checklist["projection_digests"]["corpus"]["artifacts-inventory.json"]
        == path_digest
    )
    assert (
        checklist["projection_digests"]["bm25"][
            "indexes/bm25/bm25-postings.jsonl"
        ]
        == path_digest
    )
    assert checklist["evidence_gaps"] == []
