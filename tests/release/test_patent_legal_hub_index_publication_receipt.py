"""Release tests: Hub index publication receipt staged vs promoted (PATLAW-179).

Acceptance:

* Receipt cannot claim promoted success offline without a real promote
  evidence blob.
* Staged-only state is valid and non-vacuous.
* Digests bind all three index families plus corpus.

Validation:

    python -m pytest tests/release/test_patent_legal_hub_index_publication_receipt.py -q
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (
    PROMOTION_RECEIPT_SCHEMA,
)
from ipfs_datasets_py.processors.domains.patent.hub_index_package import (
    INDEX_FAMILIES,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SEAL_SCRIPT = (
    REPO_ROOT
    / "scripts/ops/legal_data/seal_patent_legal_hub_index_publication_receipt.py"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "data/release/patent_legal_intelligence"
    / "hub_index_publication_receipt.schema.json"
)


def _load_seal_module():
    spec = importlib.util.spec_from_file_location(
        "seal_patent_legal_hub_index_publication_receipt", SEAL_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seal = _load_seal_module()


def _hex(n: int = 64, seed: str = "a") -> str:
    unit = (seed * 64)[:64]
    return (unit * ((n // 64) + 1))[:n]


PLAN = _hex(64, "1")
DIFF = _hex(64, "2")
# CIDs must match base32 alphabet (a-z, 2-7) for schema cidV1 pattern.
PKG_ROOT = "baguqeerapublicationreceiptpackageaaaaaaaaaaaaaaaaaaaaaa"
CORPUS = "baguqeeracorpusrootcidfixtureaaaaaaaaaaaaaaaaaaaaaaaaaa"
BM25 = "baguqeerabm25rootcidfixtureaaaaaaaaaaaaaaaaaaaaaaaaaaa"
VECTORS = "baguqeeravectorsrootcidfixtureaaaaaaaaaaaaaaaaaaaaaaaa"
GRAPH = "baguqeeragraphrootcidfixtureaaaaaaaaaaaaaaaaaaaaaaaaa"
SHA_A = _hex(40, "a")
SHA_B = _hex(40, "b")
SHA_C = _hex(40, "c")
SHA_D = _hex(40, "d")
BASE_A = _hex(40, "e")
PROMOTED_A = _hex(40, "f")
PROMOTED_B = _hex(40, "0")
PROMOTED_C = _hex(40, "1")
PROMOTED_D = _hex(40, "2")
PKG_DIGEST = _hex(64, "9")
CORPUS_DIGEST = _hex(64, "c")
BM25_DIGEST = _hex(64, "d")
VECTOR_DIGEST = _hex(64, "e")
GRAPH_DIGEST = _hex(64, "f")


def _stage_receipt(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "staged_pending_approval",
        "receipt_schema": "patent-legal-hub-index-stage-receipt/v1",
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
        "package_digest_sha256": PKG_DIGEST,
        "main_published": False,
        "pointers_moved": False,
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
        "schema_version": "patent-legal-hub-index-verification-receipt/v1",
        "status": "verified",
        "package_root_cid": PKG_ROOT,
        "projection_digests": {
            "corpus": {"root_cid": CORPUS, "sha256": CORPUS_DIGEST},
            "bm25": {"root_cid": BM25, "sha256": BM25_DIGEST},
            "vectors": {"root_cid": VECTORS, "sha256": VECTOR_DIGEST},
            "knowledge_graph": {"root_cid": GRAPH, "sha256": GRAPH_DIGEST},
        },
    }
    payload.update(overrides)
    return payload


def _promote_checklist(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "checklist_schema": "patent-legal-hub-index-promote-checklist/v1",
        "task_id": "PATLAW-178",
        "status": "awaiting_human_promote",
        "disposition": "staged_not_promoted",
        "package_root_cid": PKG_ROOT,
        "plan_digest": PLAN,
        "staged_diff_digest": DIFF,
        "auto_promote": False,
        "main_published": False,
        "projection_digests": {
            "corpus": {"root_cid": CORPUS},
            "bm25": {"root_cid": BM25},
            "vectors": {"root_cid": VECTORS},
            "knowledge_graph": {"root_cid": GRAPH},
        },
    }
    payload.update(overrides)
    return payload


def _promote_evidence(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": PROMOTION_RECEIPT_SCHEMA,
        "status": "promoted",
        "organization": "justicedao",
        "version_tag": "v2",
        "release_id": "hub-index-v2-demo",
        "release_root_cid": PKG_ROOT,
        "package_root_cid": PKG_ROOT,
        "plan_digest": PLAN,
        "staged_diff_digest": DIFF,
        "approval_id": "approval-fixture-001",
        "main_published": True,
        "pointers_moved": False,
        "live_network": False,
        "fake_service": True,
        "repositories": [
            {
                "dataset_id": "justicedao/patent-legal-corpus",
                "parent_commit": BASE_A,
                "promoted_commit_sha": PROMOTED_A,
                "target_revision": "main",
            },
            {
                "dataset_id": "justicedao/patent-legal-bm25",
                "parent_commit": BASE_A,
                "promoted_commit_sha": PROMOTED_B,
                "target_revision": "main",
            },
            {
                "dataset_id": "justicedao/patent-legal-vectors",
                "parent_commit": BASE_A,
                "promoted_commit_sha": PROMOTED_C,
                "target_revision": "main",
            },
            {
                "dataset_id": "justicedao/patent-legal-knowledge-graph",
                "parent_commit": BASE_A,
                "promoted_commit_sha": PROMOTED_D,
                "target_revision": "main",
            },
        ],
    }
    payload.update(overrides)
    return payload


def _seal(**kwargs: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "stage_receipt": _stage_receipt(),
        "verification_receipt": _verification_receipt(),
        "promote_checklist": _promote_checklist(),
        "mode": "offline",
        "sealed_at_utc": "2026-08-04T00:00:00Z",
        "receipt_id": "hub-index-pub-fixture",
    }
    defaults.update(kwargs)
    return seal.seal_publication_receipt(**defaults)


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _assert_schema(receipt: dict[str, Any]) -> None:
    validator = Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(receipt), key=lambda e: list(e.path))
    assert not errors, "; ".join(
        f"{'.'.join(str(p) for p in e.path)}: {e.message}" for e in errors[:8]
    )


# ---------------------------------------------------------------------------
# Identity / schema pins
# ---------------------------------------------------------------------------


def test_module_identity_pins() -> None:
    assert seal.TASK_ID == "PATLAW-179"
    assert seal.GOAL_ID == "PATLAW-G213"
    assert seal.RECEIPT_SCHEMA == "patent-legal-hub-index-publication-receipt/v1"
    assert SCHEMA_PATH.is_file()
    assert SEAL_SCRIPT.is_file()


def test_schema_file_is_valid_json_schema() -> None:
    schema = _schema()
    assert schema["$schema"].startswith("https://json-schema.org/")
    assert schema["properties"]["task_id"]["const"] == "PATLAW-179"
    assert schema["properties"]["disposition"]["enum"] == [
        "staged_not_promoted",
        "promoted",
    ]


# ---------------------------------------------------------------------------
# Staged-only is valid and non-vacuous
# ---------------------------------------------------------------------------


def test_staged_only_accepted_and_non_vacuous() -> None:
    receipt = _seal()
    assert receipt["status"] == "accepted"
    assert receipt["disposition"] == "staged_not_promoted"
    assert receipt["main_published"] is False
    assert receipt["publication_claim"]["promoted"] is False
    assert receipt["publication_claim"]["asserted"] is False
    assert receipt["publication_claim"]["reviewed_promote_evidence_present"] is False
    assert receipt["acceptance"]["staged_only_valid"] is True
    assert receipt["acceptance"]["non_vacuous"] is True
    assert receipt["acceptance"]["no_fabricated_promote"] is True
    assert receipt["evidence"]["promote_evidence"]["present"] is False
    assert receipt["evidence"]["promote_evidence"]["validated"] is False
    assert receipt["auto_promote"] is False
    assert receipt["unattended_hub_write"] is False
    assert receipt["pointers_moved"] is False
    assert receipt["tokens_used"] is False
    assert receipt["live_network"] is False
    assert re.fullmatch(r"[0-9a-f]{64}", receipt["receipt_digest_sha256"])
    _assert_schema(receipt)


def test_staged_only_binds_stage_verify_and_checklist() -> None:
    receipt = _seal()
    assert receipt["evidence"]["stage_receipt"]["present"] is True
    assert receipt["evidence"]["verification_receipt"]["present"] is True
    assert receipt["evidence"]["promote_checklist"]["present"] is True
    assert receipt["acceptance"]["verification_bound"] is True
    assert receipt["acceptance"]["checklist_bound"] is True
    assert receipt["package_root_cid"] == PKG_ROOT
    assert receipt["plan_digest"] == PLAN
    assert receipt["staged_diff_digest"] == DIFF


# ---------------------------------------------------------------------------
# Digests bind three index families + corpus
# ---------------------------------------------------------------------------


def test_digests_bind_all_index_families_plus_corpus() -> None:
    receipt = _seal()
    assert set(receipt["index_families"]) == set(INDEX_FAMILIES)
    assert set(receipt["index_families_present"]) == set(INDEX_FAMILIES)
    assert set(receipt["projections"]) == {
        "corpus",
        "bm25",
        "vectors",
        "knowledge_graph",
    }
    for family in seal.PROJECTION_FAMILIES:
        assert family in receipt["projection_digests"]
        assert receipt["projection_digests"][family]["root_cid"]
    assert receipt["projection_digests"]["corpus"]["root_cid"] == CORPUS
    assert receipt["projection_digests"]["bm25"]["root_cid"] == BM25
    assert receipt["projection_digests"]["vectors"]["root_cid"] == VECTORS
    assert receipt["projection_digests"]["knowledge_graph"]["root_cid"] == GRAPH
    assert receipt["acceptance"]["digests_bind_all_index_families"] is True
    assert receipt["acceptance"]["digests_bind_corpus"] is True


def test_missing_index_family_fails_closed() -> None:
    stage = _stage_receipt()
    del stage["bm25_root_cid"]
    verify = _verification_receipt()
    del verify["projection_digests"]["bm25"]
    checklist = _promote_checklist()
    del checklist["projection_digests"]["bm25"]
    with pytest.raises(seal.EvidenceGapError, match="bm25"):
        _seal(
            stage_receipt=stage,
            verification_receipt=verify,
            promote_checklist=checklist,
        )


def test_missing_corpus_fails_closed() -> None:
    stage = _stage_receipt()
    del stage["corpus_root_cid"]
    verify = _verification_receipt()
    del verify["projection_digests"]["corpus"]
    checklist = _promote_checklist()
    del checklist["projection_digests"]["corpus"]
    with pytest.raises(seal.EvidenceGapError, match="corpus"):
        _seal(
            stage_receipt=stage,
            verification_receipt=verify,
            promote_checklist=checklist,
        )


# ---------------------------------------------------------------------------
# Cannot claim promoted offline without real promote evidence
# ---------------------------------------------------------------------------


def test_claim_promoted_offline_without_evidence_fails() -> None:
    with pytest.raises(seal.FabricatedPromoteError, match="promote evidence"):
        _seal(mode="offline", claim_promoted=True, promote_evidence=None)


def test_claim_promoted_live_without_evidence_fails() -> None:
    with pytest.raises(seal.FabricatedPromoteError, match="promote evidence"):
        _seal(mode="live", claim_promoted=True, promote_evidence=None)


def test_stage_receipt_claiming_main_published_without_evidence_fails() -> None:
    with pytest.raises(seal.FabricatedPromoteError, match="main_published"):
        _seal(stage_receipt=_stage_receipt(main_published=True))


def test_stage_shaped_blob_rejected_as_promote_evidence() -> None:
    fake = _stage_receipt(status="staged_pending_approval")
    with pytest.raises(seal.FabricatedPromoteError):
        _seal(promote_evidence=fake, claim_promoted=True)


def test_empty_promote_blob_rejected() -> None:
    with pytest.raises(seal.FabricatedPromoteError):
        _seal(
            promote_evidence={"status": "maybe", "note": "not real"},
            claim_promoted=True,
        )


# ---------------------------------------------------------------------------
# Real promote evidence seals promoted disposition
# ---------------------------------------------------------------------------


def test_promoted_with_real_evidence_accepted() -> None:
    receipt = _seal(
        promote_evidence=_promote_evidence(),
        claim_promoted=True,
        mode="offline",
    )
    assert receipt["status"] == "accepted"
    assert receipt["disposition"] == "promoted"
    assert receipt["main_published"] is True
    assert receipt["publication_claim"]["promoted"] is True
    assert receipt["publication_claim"]["asserted"] is True
    assert receipt["publication_claim"]["reviewed_promote_evidence_present"] is True
    assert receipt["evidence"]["promote_evidence"]["present"] is True
    assert receipt["evidence"]["promote_evidence"]["validated"] is True
    assert receipt["evidence"]["promote_evidence"]["approval_id"] == (
        "approval-fixture-001"
    )
    assert len(receipt["promoted_repositories"]) == 4
    assert receipt["acceptance"]["promote_evidence_bound"] is True
    assert receipt["acceptance"]["no_fabricated_promote"] is True
    # Offline seal with real (fake-service) promote evidence is allowed.
    assert receipt["mode"] == "offline"
    assert receipt["live_network"] is False
    _assert_schema(receipt)


def test_promote_evidence_without_claim_flag_still_promotes() -> None:
    """Presence of validated promote evidence alone sets disposition=promoted."""
    receipt = _seal(promote_evidence=_promote_evidence())
    assert receipt["disposition"] == "promoted"
    assert receipt["main_published"] is True


def test_promote_evidence_plan_digest_mismatch_fails() -> None:
    pe = _promote_evidence(plan_digest=_hex(64, "7"))
    with pytest.raises(seal.EvidenceGapError, match="plan_digest"):
        _seal(promote_evidence=pe)


def test_promote_evidence_package_root_mismatch_fails() -> None:
    pe = _promote_evidence(
        package_root_cid="baguqeeraotherrootcidfixtureaaaaaaaaaaaaaaaaaaaaaaa",
        release_root_cid="baguqeeraotherrootcidfixtureaaaaaaaaaaaaaaaaaaaaaaa",
    )
    with pytest.raises(seal.EvidenceGapError, match="package_root_cid"):
        _seal(promote_evidence=pe)


# ---------------------------------------------------------------------------
# Required inputs / credentials / unpinned
# ---------------------------------------------------------------------------


def test_missing_plan_digest_fails_closed() -> None:
    stage = _stage_receipt()
    del stage["plan_digest"]
    with pytest.raises(seal.EvidenceGapError, match="plan_digest"):
        _seal(stage_receipt=stage)


def test_missing_package_root_fails_closed() -> None:
    stage = _stage_receipt()
    del stage["package_root_cid"]
    del stage["release_root_cid"]
    with pytest.raises(seal.EvidenceGapError, match="package_root_cid"):
        _seal(stage_receipt=stage)


def test_rejects_credential_shaped_stage_receipt() -> None:
    stage = _stage_receipt()
    stage["hf_token"] = "hf_abcdefghijklmnopqrstuv"
    with pytest.raises(seal.PublicationReceiptError, match="credential"):
        _seal(stage_receipt=stage)


def test_rejects_unpinned_staged_commit() -> None:
    stage = _stage_receipt()
    stage["repositories"][0]["staged_commit_sha"] = "main"
    with pytest.raises(seal.PublicationReceiptError, match="unpinned"):
        _seal(stage_receipt=stage)


def test_missing_verification_blocks_when_required() -> None:
    receipt = _seal(
        verification_receipt=None,
        require_verification=True,
    )
    assert receipt["status"] == "blocked"
    assert "verification_receipt_required" in receipt["blockers"]
    assert receipt["acceptance"]["non_vacuous"] is False


def test_missing_verification_allowed_when_opted_out() -> None:
    receipt = _seal(
        verification_receipt=None,
        require_verification=False,
    )
    assert receipt["status"] == "accepted"
    assert receipt["disposition"] == "staged_not_promoted"
    assert receipt["acceptance"]["verification_bound"] is False


# ---------------------------------------------------------------------------
# Schema validation helper + digest stability
# ---------------------------------------------------------------------------


def test_validate_receipt_against_schema_helper() -> None:
    receipt = _seal()
    seal.validate_receipt_against_schema(receipt, schema_path=SCHEMA_PATH)


def test_receipt_digest_stable_for_identical_inputs() -> None:
    a = _seal()
    b = _seal()
    assert a["receipt_digest_sha256"] == b["receipt_digest_sha256"]


def test_promoted_and_staged_digests_differ() -> None:
    staged = _seal()
    promoted = _seal(promote_evidence=_promote_evidence())
    assert staged["receipt_digest_sha256"] != promoted["receipt_digest_sha256"]
    assert staged["disposition"] != promoted["disposition"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_staged_receipt(tmp_path: Path) -> None:
    stage_path = tmp_path / "stage.json"
    verify_path = tmp_path / "verify.json"
    checklist_path = tmp_path / "checklist.json"
    out_path = tmp_path / "publication.json"
    stage_path.write_text(
        json.dumps(_stage_receipt()) + "\n", encoding="utf-8"
    )
    verify_path.write_text(
        json.dumps(_verification_receipt()) + "\n", encoding="utf-8"
    )
    checklist_path.write_text(
        json.dumps(_promote_checklist()) + "\n", encoding="utf-8"
    )

    code = seal.main(
        [
            "--stage-receipt",
            str(stage_path),
            "--verification-receipt",
            str(verify_path),
            "--promote-checklist",
            str(checklist_path),
            "--output",
            str(out_path),
            "--mode",
            "offline",
            "--require-accepted",
        ]
    )
    assert code == 0
    assert out_path.is_file()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["task_id"] == "PATLAW-179"
    assert payload["disposition"] == "staged_not_promoted"
    assert payload["status"] == "accepted"
    _assert_schema(payload)


def test_cli_claim_promoted_without_evidence_fails(tmp_path: Path) -> None:
    stage_path = tmp_path / "stage.json"
    verify_path = tmp_path / "verify.json"
    checklist_path = tmp_path / "checklist.json"
    stage_path.write_text(
        json.dumps(_stage_receipt()) + "\n", encoding="utf-8"
    )
    verify_path.write_text(
        json.dumps(_verification_receipt()) + "\n", encoding="utf-8"
    )
    checklist_path.write_text(
        json.dumps(_promote_checklist()) + "\n", encoding="utf-8"
    )

    code = seal.main(
        [
            "--stage-receipt",
            str(stage_path),
            "--verification-receipt",
            str(verify_path),
            "--promote-checklist",
            str(checklist_path),
            "--claim-promoted",
            "--mode",
            "offline",
        ]
    )
    assert code == 1


def test_cli_promoted_with_evidence(tmp_path: Path) -> None:
    stage_path = tmp_path / "stage.json"
    verify_path = tmp_path / "verify.json"
    checklist_path = tmp_path / "checklist.json"
    pe_path = tmp_path / "promote.json"
    out_path = tmp_path / "publication.json"
    stage_path.write_text(
        json.dumps(_stage_receipt()) + "\n", encoding="utf-8"
    )
    verify_path.write_text(
        json.dumps(_verification_receipt()) + "\n", encoding="utf-8"
    )
    checklist_path.write_text(
        json.dumps(_promote_checklist()) + "\n", encoding="utf-8"
    )
    pe_path.write_text(
        json.dumps(_promote_evidence()) + "\n", encoding="utf-8"
    )

    code = seal.main(
        [
            "--stage-receipt",
            str(stage_path),
            "--verification-receipt",
            str(verify_path),
            "--promote-checklist",
            str(checklist_path),
            "--promote-evidence",
            str(pe_path),
            "--output",
            str(out_path),
            "--mode",
            "offline",
            "--require-accepted",
        ]
    )
    assert code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["disposition"] == "promoted"
    assert payload["main_published"] is True
    _assert_schema(payload)


def test_policy_flags_always_fail_closed() -> None:
    receipt = _seal()
    policy = receipt["policy"]
    assert policy["fail_closed"] is True
    assert policy["promoted_requires_real_evidence"] is True
    assert policy["offline_cannot_fabricate_promote"] is True
    assert policy["no_auto_promote"] is True
    assert policy["no_unattended_hub_write"] is True
    assert policy["pointers_never_moved_by_sealer"] is True
    assert policy["staged_only_non_vacuous"] is True
