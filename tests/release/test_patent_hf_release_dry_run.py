"""Release tests: Hub dry-run staging verification (PATLAW-168).

Acceptance:

* Dry-run staging verifies manifests, DLP/rights gates, and viewer contracts
  without uploading to main or mutating remote default branches.
* A staging receipt is recorded for human approval (no unattended publish).
* Credentials never appear in receipts; default mode is offline dry-run.

Validation:

    python -m pytest tests/release/test_patent_hf_release_dry_run.py -q
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (
    CANONICAL_REPOSITORY_NAMES,
    ORGANIZATION,
    default_public_coverage,
)
from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (
    default_test_base_revisions,
    materialize_minimal_release_tree,
    reject_credentials_in_payload,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_policy_v2 import (
    VIEWER_ENDPOINTS,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_v2 import (
    FieldPartition,
    PrivacyReview,
    ReleaseRowV2,
    build_patent_hf_release_v2,
    stage_patent_hf_release_v2,
)
from ipfs_datasets_py.processors.domains.patent.release_policy import (
    RightsReview,
    RightsReviewStatus,
    SourceLineage,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE_SCRIPT = REPO_ROOT / "scripts/ops/legal_data/stage_patent_hf_release.py"
RUNBOOK = REPO_ROOT / "docs/operations/PATENT_LEGAL_HUB_DRY_RUN.md"
BASE_SHA = "0" * 40


def _load_stage_module():
    spec = importlib.util.spec_from_file_location(
        "stage_patent_hf_release", STAGE_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


stage_mod = _load_stage_module()


# ---------------------------------------------------------------------------
# Compact public-row recipe (avoid bulk golden dumps)
# ---------------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lineage(
    *,
    source_id: str = "govinfo/uscode",
    revision: str = "2024-title-35",
    uri: str = "https://www.govinfo.gov/app/details/USCODE-2024-title35",
    body: str = "uscode-2024-title35",
) -> SourceLineage:
    return SourceLineage(
        source_id=source_id,
        source_revision=revision,
        source_uri=uri,
        source_sha256=_sha(body),
        authority="official",
    )


def _rights() -> RightsReview:
    return RightsReview(
        license_expression="public-domain-US-government",
        review_status=RightsReviewStatus.REVIEWED,
        reviewed_by="patent-legal-governance",
        reviewed_at="2026-08-01T00:00:00Z",
        redistribution_allowed=True,
    )


def _privacy() -> PrivacyReview:
    return PrivacyReview(
        review_status="reviewed",
        reviewed_by="patent-legal-privacy",
        reviewed_at="2026-08-01T00:00:00Z",
        privacy_class="public",
    )


def _row(
    *,
    record_id: str,
    config_name: str = "usc",
    authoritative: dict | None = None,
    ai_derived: dict | None = None,
    corpus_record_id: str = "",
    lineage: SourceLineage | None = None,
    node_id: str = "",
    src_node_id: str = "",
    dst_node_id: str = "",
    document_id: str = "",
    term: str = "",
) -> ReleaseRowV2:
    return ReleaseRowV2(
        record_id=record_id,
        config_name=config_name,
        classification="public_official",
        source_lineage=lineage or _lineage(),
        rights_review=_rights(),
        privacy_review=_privacy(),
        fields=FieldPartition(
            authoritative=authoritative or {"text": f"body-{record_id}"},
            ai_derived=ai_derived or {},
        ),
        corpus_record_id=corpus_record_id,
        node_id=node_id,
        src_node_id=src_node_id,
        dst_node_id=dst_node_id,
        document_id=document_id,
        term=term,
    )


def _public_rows() -> list[ReleaseRowV2]:
    claims = _row(
        record_id="claim:US7654321B2:1",
        config_name="claims",
        authoritative={"claim_number": 1, "text": "A system comprising a processor"},
        lineage=_lineage(
            source_id="uspto/public-pair",
            revision="grant-2020-01-01",
            uri="https://data.uspto.gov/apis/patent-file-wrapper",
            body="uspto-grant-2020",
        ),
    )
    usc = _row(
        record_id="usc:35:101",
        config_name="usc",
        authoritative={
            "citation": "35 U.S.C. § 101",
            "text": "Whoever invents or discovers any new and useful process",
        },
    )
    vector = _row(
        record_id="vec:claim:US7654321B2:1",
        config_name="vectors",
        corpus_record_id=claims.record_id,
        authoritative={
            "model_id": "patent-legal-minilm/v2",
            "model_revision": "rev-2026-08-01",
            "embedding_dim": 384,
            "has_embedding": True,
        },
        ai_derived={"embedding_norm": 1.0},
        lineage=claims.source_lineage,
    )
    bm25_doc = _row(
        record_id="bm25doc:claim:US7654321B2:1",
        config_name="bm25_documents",
        corpus_record_id=claims.record_id,
        authoritative={"text_preview": "A system comprising", "token_count": 4},
        lineage=claims.source_lineage,
    )
    bm25_post = _row(
        record_id="bm25post:system",
        config_name="bm25_postings",
        document_id=bm25_doc.record_id,
        term="system",
        authoritative={"tf": 1, "df": 1},
        lineage=claims.source_lineage,
    )
    node_a = _row(
        record_id="node:US7654321B2",
        config_name="graph_nodes",
        node_id="US7654321B2",
        authoritative={"label": "US7654321B2", "kind": "patent"},
        lineage=claims.source_lineage,
    )
    node_b = _row(
        record_id="node:US1234567A",
        config_name="graph_nodes",
        node_id="US1234567A",
        authoritative={"label": "US1234567A", "kind": "patent"},
        lineage=claims.source_lineage,
    )
    edge = _row(
        record_id="edge:cites:1",
        config_name="graph_edges",
        src_node_id=node_a.node_id,
        dst_node_id=node_b.node_id,
        authoritative={"relation": "cites"},
        lineage=claims.source_lineage,
    )
    return [usc, claims, vector, bm25_doc, bm25_post, node_a, node_b, edge]


def _stage_admissible_tree(tmp_path: Path) -> Path:
    release = build_patent_hf_release_v2(
        _public_rows(),
        dry_run=True,
        coverage=default_public_coverage(as_of="2026-08-01"),
    )
    out = tmp_path / "staged-public"
    stage_patent_hf_release_v2(release, out, dry_run=False)
    return out


def _json_blob(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _assert_no_credentials(payload: object) -> None:
    reject_credentials_in_payload(payload, label="test_receipt")
    text = _json_blob(payload)
    lowered = text.casefold()
    assert "bearer " not in lowered
    assert "password=" not in lowered
    assert "fake-operator-token" not in text
    assert not re.search(r"(?<![a-z0-9_-])hf_[A-Za-z0-9]{12,}", text)


def _assert_no_main_mutation(payload: Any) -> None:
    assert payload.get("main_published") is False
    assert payload.get("remote_default_branches_mutated") is False
    assert payload.get("remote_write_contacted") is False
    assert payload.get("pointers_moved") is False
    assert payload.get("live_network") is False
    assert payload.get("tokens_used") is False
    assert payload.get("authenticated_upload") is False
    assert payload.get("uses_hf_api_upload_file") is False
    branch = str(payload.get("branch_name") or "").casefold()
    assert branch not in {"main", "master", "refs/heads/main", "refs/heads/master"}


@pytest.fixture
def bases() -> dict[str, str]:
    return default_test_base_revisions(sha=BASE_SHA)


@pytest.fixture
def minimal_tree(tmp_path: Path) -> Path:
    root = tmp_path / "minimal"
    materialize_minimal_release_tree(root)
    return root


@pytest.fixture
def public_tree(tmp_path: Path) -> Path:
    return _stage_admissible_tree(tmp_path)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in (
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
        "HUGGINGFACE_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# ---------------------------------------------------------------------------
# Declared outputs / identity
# ---------------------------------------------------------------------------


def test_declared_outputs_exist() -> None:
    assert STAGE_SCRIPT.is_file()
    assert RUNBOOK.is_file()
    assert Path(__file__).is_file()


def test_module_identity() -> None:
    assert stage_mod.TASK_ID == "PATLAW-168"
    assert stage_mod.GOAL_ID == "PATLAW-G202"
    assert stage_mod.DRY_RUN_RECEIPT_SCHEMA == (
        "patent-legal-hf-dry-run-staging-receipt/v1"
    )
    assert "rights_dlp" in stage_mod.EXPECTED_GATE_NAMES
    assert "dataset_viewer" in stage_mod.EXPECTED_GATE_NAMES
    sig = inspect.signature(stage_mod.run_dry_run)
    assert sig.parameters["verify_gates"].default is True
    assert sig.parameters["require_admitted"].default is False


def test_runbook_documents_dry_run_contract() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "PATLAW-168" in text
    assert "dry-run" in text.casefold()
    assert "stage_patent_hf_release" in text
    assert "manifest" in text.casefold()
    assert "dlp" in text.casefold() or "rights" in text.casefold()
    assert "viewer" in text.casefold()
    assert "main" in text.casefold()
    assert "human" in text.casefold() or "approval" in text.casefold()


def test_cli_default_mode_is_dry_run() -> None:
    parser = stage_mod._parser()
    assert parser.get_default("mode") == "dry-run"


# ---------------------------------------------------------------------------
# Happy path — full public tree
# ---------------------------------------------------------------------------


def test_dry_run_verifies_manifests_dlp_and_viewer(
    public_tree: Path,
    bases: dict[str, str],
    clean_env: pytest.MonkeyPatch,
) -> None:
    result = stage_mod.run_dry_run(
        local_root=public_tree,
        manifest=None,
        organization=ORGANIZATION,
        base_revisions=bases,
        branch_name=None,
        target_revision="main",
        version_tag=None,
        release_id=None,
        require_admitted=True,
    )
    assert result["status"] == "dry_run_only"
    assert result["verification_status"] == "verified"
    assert result["receipt_schema"] == stage_mod.DRY_RUN_RECEIPT_SCHEMA
    assert result["task_id"] == "PATLAW-168"
    assert result["goal_id"] == "PATLAW-G202"
    assert result["dry_run"] is True
    assert result["manifest_verified"] is True
    assert result["manifest_verification"]["verified"] is True
    assert result["manifest_verification"]["artifact_count"] >= 1
    assert result["gates_run"] is True
    assert result["admitted"] is True
    assert result["plan_digest"]
    assert result["staged_diff_digest"]
    assert result["release_root_cid"]
    assert result["human_approval_required"] is True
    assert result["next_operator_actions"]

    dlp = result["dlp_rights_gates"]
    assert dlp is not None
    assert dlp["admitted"] is True
    assert dlp["credentials_resolved"] is False
    assert dlp["rights_dlp_passed"] is True
    gate_names = {g["name"] for g in dlp["gate_results"]}
    for expected in (
        "cards_configs",
        "parquet",
        "rights_dlp",
        "orphans",
        "count_parity",
        "stale_sources",
        "dataset_viewer",
    ):
        assert expected in gate_names
    assert all(g["passed"] for g in dlp["gate_results"])

    viewer = result["viewer_contracts"]
    assert viewer["passed"] is True
    assert set(viewer["endpoints_checked"]) == set(VIEWER_ENDPOINTS)

    repo_ids = set(result["repository_ids"])
    assert repo_ids >= {f"{ORGANIZATION}/{n}" for n in CANONICAL_REPOSITORY_NAMES}

    _assert_no_main_mutation(result)
    _assert_no_credentials(result)


def test_cli_dry_run_writes_staging_receipt(
    public_tree: Path,
    bases: dict[str, str],
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,
) -> None:
    bases_path = tmp_path / "bases.json"
    bases_path.write_text(json.dumps(bases), encoding="utf-8")
    receipt_path = tmp_path / "dry-run-receipt.json"
    code = stage_mod.main(
        [
            "--mode",
            "dry-run",
            "--local-root",
            str(public_tree),
            "--base-revisions-file",
            str(bases_path),
            "--receipt-out",
            str(receipt_path),
            "--require-admitted",
        ]
    )
    assert code == 0
    assert receipt_path.is_file()
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["status"] == "dry_run_only"
    assert payload["verification_status"] == "verified"
    assert payload["admitted"] is True
    assert payload["main_published"] is False
    assert payload["remote_default_branches_mutated"] is False
    assert payload["plan_digest"]
    assert payload["staged_diff_digest"]
    _assert_no_credentials(payload)


def test_verify_manifest_integrity_standalone(
    public_tree: Path,
    clean_env: pytest.MonkeyPatch,
) -> None:
    report = stage_mod.verify_manifest_integrity(public_tree)
    assert report["verified"] is True
    assert report["status"] == "manifest_verified"
    assert report["artifact_count"] >= len(CANONICAL_REPOSITORY_NAMES)
    assert report["organization"] == ORGANIZATION
    _assert_no_credentials(report)


def test_run_admission_gates_standalone(
    public_tree: Path,
    clean_env: pytest.MonkeyPatch,
) -> None:
    admission = stage_mod.run_admission_gates(
        public_tree, require_admitted=True
    )
    assert admission["admitted"] is True
    assert admission["viewer_contracts_passed"] is True
    assert admission["rights_dlp_passed"] is True
    assert set(admission["viewer_endpoints_checked"]) == set(VIEWER_ENDPOINTS)
    _assert_no_credentials(admission)


# ---------------------------------------------------------------------------
# Fail-closed paths
# ---------------------------------------------------------------------------


def test_manifest_digest_mismatch_fails_closed(
    public_tree: Path,
    bases: dict[str, str],
    clean_env: pytest.MonkeyPatch,
) -> None:
    # Corrupt one staged file after materialization.
    victims = list(public_tree.rglob("*.parquet"))
    assert victims
    victims[0].write_bytes(b"CORRUPTED-NOT-PARQUET")
    with pytest.raises(Exception):
        stage_mod.run_dry_run(
            local_root=public_tree,
            manifest=None,
            organization=ORGANIZATION,
            base_revisions=bases,
            branch_name=None,
            target_revision="main",
            version_tag=None,
            release_id=None,
        )


def test_missing_manifest_fails_closed(
    tmp_path: Path,
    bases: dict[str, str],
    clean_env: pytest.MonkeyPatch,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(Exception):
        stage_mod.run_dry_run(
            local_root=empty,
            manifest=None,
            organization=ORGANIZATION,
            base_revisions=bases,
            branch_name=None,
            target_revision="main",
            version_tag=None,
            release_id=None,
        )


def test_minimal_tree_reports_gate_rejection_without_upload(
    minimal_tree: Path,
    bases: dict[str, str],
    clean_env: pytest.MonkeyPatch,
) -> None:
    """Minimal fixture may fail cards/configs; still never touches main."""
    result = stage_mod.run_dry_run(
        local_root=minimal_tree,
        manifest=None,
        organization=ORGANIZATION,
        base_revisions=bases,
        branch_name=None,
        target_revision="main",
        version_tag=None,
        release_id=None,
        require_admitted=False,
    )
    assert result["status"] == "dry_run_only"
    assert result["manifest_verified"] is True
    assert result["gates_run"] is True
    # Minimal tree lacks dataset_configs/coverage — admission should refuse.
    assert result["admitted"] is False
    assert result["verification_status"] == "rejected"
    assert result["dlp_rights_gates"]["reason_codes"]
    _assert_no_main_mutation(result)
    _assert_no_credentials(result)


def test_require_admitted_exits_nonzero_on_reject(
    minimal_tree: Path,
    bases: dict[str, str],
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,
) -> None:
    bases_path = tmp_path / "bases.json"
    bases_path.write_text(json.dumps(bases), encoding="utf-8")
    code = stage_mod.main(
        [
            "--mode",
            "dry-run",
            "--local-root",
            str(minimal_tree),
            "--base-revisions-file",
            str(bases_path),
            "--require-admitted",
        ]
    )
    assert code == 1


def test_force_viewer_invalid_rejects_viewer_contracts(
    public_tree: Path,
    bases: dict[str, str],
    clean_env: pytest.MonkeyPatch,
) -> None:
    result = stage_mod.run_dry_run(
        local_root=public_tree,
        manifest=None,
        organization=ORGANIZATION,
        base_revisions=bases,
        branch_name=None,
        target_revision="main",
        version_tag=None,
        release_id=None,
        force_viewer_invalid=True,
        require_admitted=False,
    )
    assert result["admitted"] is False
    assert result["viewer_contracts"]["passed"] is False
    assert result["verification_status"] == "rejected"
    _assert_no_main_mutation(result)


def test_premature_credentials_fail_closed(
    public_tree: Path,
    bases: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Construct a token-shaped value at runtime (never store full literal).
    monkeypatch.setenv("HF_TOKEN", "hf_" + ("x" * 28))
    with pytest.raises(Exception):
        stage_mod.run_dry_run(
            local_root=public_tree,
            manifest=None,
            organization=ORGANIZATION,
            base_revisions=bases,
            branch_name=None,
            target_revision="main",
            version_tag=None,
            release_id=None,
            verify_gates=True,
        )


def test_skip_admission_gates_plan_only(
    minimal_tree: Path,
    bases: dict[str, str],
    clean_env: pytest.MonkeyPatch,
) -> None:
    result = stage_mod.run_dry_run(
        local_root=minimal_tree,
        manifest=None,
        organization=ORGANIZATION,
        base_revisions=bases,
        branch_name=None,
        target_revision="main",
        version_tag=None,
        release_id=None,
        verify_gates=False,
    )
    assert result["status"] == "dry_run_only"
    assert result["verification_status"] == "plan_only"
    assert result["gates_run"] is False
    assert result["admitted"] is None
    assert result["dlp_rights_gates"] is None
    assert result["manifest_verified"] is True
    assert result["plan_digest"]
    _assert_no_main_mutation(result)


def test_branch_name_cannot_be_main(
    public_tree: Path,
    bases: dict[str, str],
    clean_env: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(Exception):
        stage_mod.run_dry_run(
            local_root=public_tree,
            manifest=None,
            organization=ORGANIZATION,
            base_revisions=bases,
            branch_name="main",
            target_revision="main",
            version_tag=None,
            release_id=None,
            verify_gates=False,
        )


def test_dry_run_never_reads_token_env_for_upload(
    public_tree: Path,
    bases: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With gates skipped, dry-run must still ignore token env for network."""
    # Gates skip so premature-credential assertion is not the failure mode.
    monkeypatch.setenv("HF_TOKEN", "hf_" + ("z" * 30))
    result = stage_mod.run_dry_run(
        local_root=public_tree,
        manifest=None,
        organization=ORGANIZATION,
        base_revisions=bases,
        branch_name=None,
        target_revision="main",
        version_tag=None,
        release_id=None,
        verify_gates=False,
    )
    assert result["tokens_used"] is False
    assert result["live_network"] is False
    assert result["authenticated_upload"] is False
    blob = _json_blob(result)
    assert "hf_" + ("z" * 30) not in blob


def test_source_has_no_live_hfapi_import() -> None:
    source = STAGE_SCRIPT.read_text(encoding="utf-8")
    assert "HfApi(" not in source
    assert "from huggingface_hub" not in source
    assert "import huggingface_hub" not in source
    assert "upload_file" not in source or "uses_hf_api_upload_file" in source
