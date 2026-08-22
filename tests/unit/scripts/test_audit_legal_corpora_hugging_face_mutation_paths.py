"""Tests for the LCR-084 Hugging Face mutation-path inventory."""

from __future__ import annotations

import scripts.ops.legal_data.audit_legal_corpora_hugging_face_mutation_paths as audit


def test_inventory_finds_unprotected_protected_repo_writes() -> None:
    report = audit.inventory_mutation_paths()
    assert report["authorizing_hub_upload"] is False
    assert report["callsite_count"] >= 1
    assert report["unprotected_count"] >= 1
    assert report["status"] == "blocked"
    paths = {item["path"] for item in report["unprotected_callsites"]}
    assert any("refresh_state_laws_corpus.py" in path for path in paths) or paths


def test_cli_check_exits_nonzero_while_unprotected_paths_remain() -> None:
    assert (
        audit.main(
            [
                "--protected-repo",
                "justicedao/ipfs_state_laws",
                "--protected-repo",
                "justicedao/ipfs_federal_register",
                "--require-runtime",
                "ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime",
                "--check",
            ]
        )
        == 1
    )
