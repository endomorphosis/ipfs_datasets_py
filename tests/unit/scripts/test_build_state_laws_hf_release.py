"""Unit tests for the exact-51 state-law release candidate assembler (LCR-039)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    DEFAULT_DATASET_REPO_ID,
    PREVIOUS_PUBLIC_PIN,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
)
import scripts.ops.legal_data.build_state_laws_hf_release as cli


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "legal_corpora_reindex" / "release_candidate.json"
E2E_PATH = REPO_ROOT / "docs" / "reports" / "legal_corpora_reindex" / "local_e2e.json"


def test_cli_identity_and_help() -> None:
    assert cli.TASK_ID == "LCR-039"
    assert cli.GOAL_ID == "LCR-G070"
    parser = cli.build_parser()
    assert parser.prog == "build_state_laws_hf_release.py"
    assert cli.main(["--help"]) == 0


def test_hub_upload_forbidden() -> None:
    assert cli.main(["--hub-upload"]) == 1
    assert cli.main(["--no-fixture-only"]) == 1


def test_exact_51_family_rows_cover_canonical_set() -> None:
    rows = cli.exact_51_family_rows()
    codes = [str(row["jurisdiction"]).upper() for row in rows["corpus"]]
    assert codes == list(CANONICAL_JURISDICTION_ORDER)
    assert len(codes) == EXPECTED_JURISDICTION_COUNT
    assert codes[-1] == "DC"
    assert "PR" not in codes
    assert len(rows["bm25_documents"]) == EXPECTED_JURISDICTION_COUNT
    assert len(rows["vectors"]) == EXPECTED_JURISDICTION_COUNT
    assert len(rows["graph_nodes"]) == EXPECTED_JURISDICTION_COUNT
    assert len(rows["source_receipts"]) == EXPECTED_JURISDICTION_COUNT


def test_assemble_candidate_does_not_authorize_publication() -> None:
    payload = cli.assemble_candidate(repo_root=REPO_ROOT)
    cli.check_candidate_report(payload)
    assert payload["authorizing_for_publication"] is False
    assert payload["hub_upload"] is False
    assert payload["dataset_repo_id"] == DEFAULT_DATASET_REPO_ID
    assert payload["model_id"] == DEFAULT_EMBEDDING_MODEL_ID
    assert payload["model_revision"] == DEFAULT_EMBEDDING_MODEL_REVISION
    assert payload["previous_public_pin"] == PREVIOUS_PUBLIC_PIN
    assert payload["rollback_target"] == PREVIOUS_PUBLIC_PIN
    assert payload["jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT
    assert payload["validation"]["valid"] is True
    assert payload["multipart_plan"]["transactional_staging_ready"] is True


def test_committed_report_exists_and_matches_gate() -> None:
    assert E2E_PATH.is_file()
    assert REPORT_PATH.is_file()
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    cli.check_candidate_report(payload)
    assert payload["task_id"] == "LCR-039"
    assert payload["jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT


def test_cli_check_validates_frozen_report() -> None:
    assert cli.main(["--check"]) == 0
