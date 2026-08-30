"""Independent current-tree contract checks for the DOEP-061 semantic builder."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

DATASETS_ROOT = Path(__file__).resolve().parents[2]
if str(DATASETS_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASETS_ROOT))

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes  # noqa: E402
from ipfs_datasets_py.proof_context.context_pack import (  # noqa: E402
    AUTHORITY,
    DATASETS_SEMANTIC_BUILDER_FORBIDDEN_FIELDS,
    DATASETS_SEMANTIC_BUILDER_INTERFACE,
    DATASETS_SEMANTIC_BUILDER_OWNERSHIP,
    ContextPackConstructionError,
    DatasetsSemanticContextBuilder,
    build_context_pack,
    build_datasets_semantic_context,
)
from ipfs_datasets_py.proof_context.contracts import StaleContextError  # noqa: E402

MODULE_PATH = DATASETS_ROOT / "ipfs_datasets_py/proof_context/context_pack.py"
OUTPUT_PATH = DATASETS_ROOT / "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-061.json"
RECEIPT_PATH = DATASETS_ROOT / "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-061.json"
OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/proof_context/context_pack.py",
    "tests/doep/test_doep_061_implement_datasets_semantic_builder.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-061.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-061.json",
)
BASE_REPOSITORIES = {
    "ipfs_accelerate_py": {"commit": "87715e9295626e7918f7fc8a7b1a1531ab04208f", "tree": "1c9a399cc7a599d5904e5be2ae58c6be3650cff7"},
    "ipfs_datasets_py": {"commit": "3668b8857a9aa7b1a3c847be12725b5cd057d2e7", "tree": "456e09b51d6a07a3a5873436df24054768195320"},
    "ipfs_kit_py": {"commit": "b6c65ba732733d7e33852713ba18aa3b12235668", "tree": "14da7d92e130b7ba3523d0d6741a3ef7ef1e1bc2"},
    "lift_coding": {"commit": "bb8869ed72eb7002434345d9969efee729c4f7f6", "tree": "99e85bfe584b7688ffbeff86da1e612dd6893a42"},
}
TASK_CID = "sha256:f0068c1d1b2edf69d97ca0b4611019bed1b87b2c3fc0fff697d797f7c92152b8"
PLAN_CID = "sha256:6c197a4b92682b3b813656123e09956846dc4f5abadf417f37fb7cc0133ddba4"


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _kwargs(**overrides: Any) -> dict[str, Any]:
    values = {
        "repository_state_cid": _cid("repository-state"),
        "task_id": "DOEP-061",
        "target_source_cid": _cid("target"),
        "surrounding_source_cid": _cid("surrounding"),
        "test_source_cid": _cid("test"),
        "scanned_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
        "source_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
        "capsule_cids": (_cid("capsule"),),
    }
    values.update(overrides)
    return values


def _load(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    return result


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_declared_outputs_exist() -> None:
    assert MODULE_PATH.is_file()
    for relative in OWNER_RELATIVE_OUTPUTS:
        assert (DATASETS_ROOT / relative).is_file(), relative


def test_semantic_builder_reuses_the_canonical_builder_and_identity() -> None:
    fields = _kwargs()
    canonical = build_context_pack(**fields)
    via_function = build_datasets_semantic_context(**fields)
    via_class = DatasetsSemanticContextBuilder().build(**fields)
    assert via_function == canonical == via_class
    assert via_function.pack_cid == canonical.pack_cid
    assert via_function.producer == AUTHORITY
    assert DatasetsSemanticContextBuilder.interface == DATASETS_SEMANTIC_BUILDER_INTERFACE


def test_semantic_builder_preserves_fail_closed_checks() -> None:
    with pytest.raises(StaleContextError):
        build_datasets_semantic_context(**_kwargs(freshness="stale"))
    with pytest.raises(ContextPackConstructionError):
        DatasetsSemanticContextBuilder().build(
            **_kwargs(execution_admission=True)
        )


def test_semantic_builder_has_no_storage_or_admission_authority() -> None:
    assert DATASETS_SEMANTIC_BUILDER_OWNERSHIP == {
        "canonical_semantic_identity": "ipfs_datasets_py",
        "exact_bytes_cid_storage": "ipfs_kit_py",
        "operational_admission": "ipfs_accelerate_py",
    }
    assert {"storage_bytes", "execution_admission", "terminal_status"}.issubset(
        DATASETS_SEMANTIC_BUILDER_FORBIDDEN_FIELDS
    )
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "class DatasetsSemanticContextBuilder" in source
    assert "return build_context_pack(**kwargs)" in source


def test_manifest_and_receipt_bind_the_current_tree() -> None:
    manifest, receipt = _load(OUTPUT_PATH), _load(RECEIPT_PATH)
    assert manifest["task_id"] == receipt["task_id"] == "DOEP-061"
    assert manifest["task_cid"] == receipt["task_cid"] == TASK_CID
    assert manifest["plan_cid"] == receipt["plan_cid"] == PLAN_CID
    assert manifest["declared_outputs"] == receipt["expected_outputs"] == list(OWNER_RELATIVE_OUTPUTS)
    assert manifest["base_repositories"] == BASE_REPOSITORIES
    assert manifest["semantic_builder"]["reuses"] == "build_context_pack"
    assert manifest["semantic_builder"]["interface"] == DATASETS_SEMANTIC_BUILDER_INTERFACE
    assert receipt["required_evidence"]["source_commit_tree_gitlinks"] == BASE_REPOSITORIES
    digests = {relative: _digest(DATASETS_ROOT / relative) for relative in OWNER_RELATIVE_OUTPUTS[:-1]}
    encoded = json.dumps(digests, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert receipt["path_digests"] == digests
    assert receipt["required_evidence"]["changed_path_digest"] == "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
