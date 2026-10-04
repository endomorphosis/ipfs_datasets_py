"""Repository-corpus gate for the package-only Python AST baseline."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.logic.software_contracts.python_frontend import (
    PythonASTExtractor,
)


SUBMODULE_ROOT = Path(__file__).resolve().parents[4]
SUPERPROJECT_ROOT = SUBMODULE_ROOT.parent
BASELINE_ROOT = (
    SUPERPROJECT_ROOT
    / "data"
    / "datasets_contract_analysis"
    / "scans"
    / "ipfs_datasets_py"
    / "baseline"
)


def _git(*arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments],
        cwd=SUBMODULE_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _load(name: str) -> dict:
    return json.loads((BASELINE_ROOT / name).read_text(encoding="utf-8"))


def test_checked_in_ast_baseline_is_current_complete_and_content_addressed() -> None:
    receipt = _load("ast-baseline.json")
    result_index = _load("ast-result-index.json")

    assert receipt["authority"] == "STATIC_AST_BASELINE_ONLY"
    assert receipt["status"] == "complete"
    assert receipt["blockers"] == []
    assert receipt["repository"]["commit"] == _git(
        "rev-parse", "HEAD"
    ).decode().strip()
    assert receipt["repository"]["tree"] == _git(
        "rev-parse", "HEAD^{tree}"
    ).decode().strip()

    coverage = receipt["coverage"]
    assert coverage["enumeration_complete"] is True
    assert coverage["analysis_complete"] is True
    assert coverage["eligible_blob_count"] == coverage["terminal_count"]
    assert coverage["eligible_blob_count"] == (
        coverage["parsed_count"]
        + coverage["explicit_unsupported_count"]
        + coverage["frontend_exception_count"]
        + coverage["resource_exhausted_count"]
        + coverage["source_unavailable_count"]
    )
    assert coverage["frontend_exception_count"] == 0
    assert coverage["resource_exhausted_count"] == 0
    assert coverage["source_unavailable_count"] == 0
    assert coverage["unattempted_count"] == 0

    receipt_identity = dict(receipt)
    claimed_receipt_cid = receipt_identity.pop("receipt_cid")
    assert cid_for_structured(receipt_identity) == claimed_receipt_cid

    index_identity = dict(result_index)
    claimed_index_cid = index_identity.pop("index_cid")
    assert cid_for_structured(index_identity) == claimed_index_cid
    assert claimed_index_cid == receipt["artifacts"]["result_index_cid"]

    leaves = result_index["result_leaves"]
    assert len(leaves) == coverage["eligible_blob_count"]
    assert len({(leaf["path"], leaf["git_oid"]) for leaf in leaves}) == len(
        leaves
    )
    assert not [
        leaf
        for leaf in leaves
        if leaf["disposition"]
        in {"frontend_exception", "resource_exhausted", "source_unavailable"}
    ]


def test_tracked_paths_with_spaces_produce_ast_records() -> None:
    paths = (
        "ipfs_datasets_py/processors/multimedia/omni_converter_mk2/core/"
        "content_extractor/processors/_get_processor_resource_configs copy.py",
        "ipfs_datasets_py/workflow_automation/background_task_engine copy.py",
        "scripts/audit_docs_drift copy.py",
    )
    extractor = PythonASTExtractor()
    for path in paths:
        source = _git("show", f"HEAD:{path}")
        record = extractor.extract(
            source,
            path=path,
            repository_id="repository:ipfs_datasets_py",
            revision=_git("rev-parse", "HEAD").decode().strip(),
            repository_tree_cid=_load("ast-baseline.json")["repository"][
                "repository_root_cid"
            ],
        )
        assert record.provenance.path == path
        assert record.cid
