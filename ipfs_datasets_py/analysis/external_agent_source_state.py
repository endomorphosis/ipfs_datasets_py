"""Content-addressed four-repository source-state root for EAAEF-007.

This module builds a semantic/provenance root over the frozen External Agent
source forest. It does not open DuckDB, Quack, or DuckLake, and it does not
admit Plan R2.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "ExternalAgentSourceStateRoot@1"
PLANNING_FOREST_ROOT = (
    "sha256:ed543c10f6aa90e093c8ae8b8866934e0cc1614e1be49ddcdc5dd7a2ce8565fa"
)
REPOSITORIES = (
    "ipfs_accelerate_py",
    "ipfs_datasets_py",
    "ipfs_kit_py",
    "Mcp-Plus-Plus",
)

_DATASETS_ROOT = Path(__file__).resolve().parents[2]
_SUPERPROJECT = _DATASETS_ROOT.parent
_CAMPAIGN = (
    _SUPERPROJECT / "docs/architecture/external_agent_autonomous_execution_fabric"
)
_SOURCE_MANIFEST = _CAMPAIGN / "source_reconciliation_manifest.json"

_SURFACE_PATHS = {
    "ipfs_accelerate_py": (
        "test/api/test_external_agent_source_reconciliation.py",
        "docs/architecture/external_agent_autonomous_execution_fabric/source_reconciliation_manifest.json",
    ),
    "ipfs_datasets_py": (
        "ipfs_datasets_py/logic/ir_core/axes.py",
        "ipfs_datasets_py/logic/backends/protocol_v2.py",
        "docs/architecture/external_agent_fabric_reconciliation.json",
    ),
    "ipfs_kit_py": (
        "ipfs_kit_py/proof_seal_store/contracts.py",
        "ipfs_kit_py/semantic_governor_store/contracts.py",
        "ipfs_kit_py/mcp_server/mcplusplus/state_root_adapter.py",
        "docs/external_agent_fabric_kit_contracts.md",
    ),
    "Mcp-Plus-Plus": (
        "schemas/state/state-ref-1.schema.json",
        "schemas/durable/durable-executor-1.schema.json",
        "docs/architecture/decisions/0004-state-modes.md",
        "docs/architecture/decisions/0005-durable-executor.md",
    ),
}

_REPO_ROOTS = {
    "ipfs_accelerate_py": _SUPERPROJECT,
    "ipfs_datasets_py": _DATASETS_ROOT,
    "ipfs_kit_py": _SUPERPROJECT / "ipfs_kit_py",
    "Mcp-Plus-Plus": _SUPERPROJECT / "ipfs_accelerate_py/mcplusplus",
}


def canonical_cid(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _ast_digest(path: Path) -> str | None:
    if path.suffix != ".py":
        return None
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    dumped = ast.dump(tree, include_attributes=False)
    return "sha256:" + hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def load_source_forest() -> dict[str, Any]:
    source = json.loads(_SOURCE_MANIFEST.read_text(encoding="utf-8"))
    payload = source["source_forest_payload"]
    if canonical_cid(payload) != source["source_forest_root"]:
        raise ValueError("source_forest_root does not match its canonical payload")
    if source["source_forest_root"] != PLANNING_FOREST_ROOT:
        raise ValueError("planning source_forest_root drifted")
    return source


def surface_inventory() -> dict[str, list[dict[str, str]]]:
    inventory: dict[str, list[dict[str, str]]] = {}
    for name, relatives in _SURFACE_PATHS.items():
        root = _REPO_ROOTS[name]
        rows: list[dict[str, str]] = []
        for relative in relatives:
            path = root / relative
            row = {
                "path": relative,
                "content_cid": _file_digest(path),
            }
            ast_cid = _ast_digest(path)
            if ast_cid is not None:
                row["ast_cid"] = ast_cid
            rows.append(row)
        inventory[name] = rows
    return inventory


def build_source_state_root(
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_obj = dict(source) if source is not None else load_source_forest()
    payload = source_obj["source_forest_payload"]
    inventory = surface_inventory()
    record = {
        "schema": SCHEMA,
        "planning_source_forest_root": source_obj["source_forest_root"],
        "source_forest_payload": payload,
        "selected_integration_roots": source_obj["selected_integration_roots"],
        "surface_inventory": inventory,
        "plan_r2_admitted": False,
        "ducklake_authoritative": False,
    }
    root = canonical_cid(record)
    delta = {
        "schema": "ExternalAgentSourceStateDelta@1",
        "planning_source_forest_root": source_obj["source_forest_root"],
        "post_reconciliation_root": root,
        "changed": root != source_obj["source_forest_root"],
    }
    invalidation = {
        "schema": "ExternalAgentSourceStateInvalidation@1",
        "invalidates": [source_obj["source_forest_root"]] if delta["changed"] else [],
        "reason": (
            "post-reconciliation surface inventory is a distinct semantic root"
            if delta["changed"]
            else "post-reconciliation root equals planning forest root"
        ),
    }
    return {
        "schema": SCHEMA,
        "source_state_root": root,
        "record": record,
        "delta": delta,
        "invalidation": invalidation,
    }


def verify_source_state_root(bundle: Mapping[str, Any]) -> dict[str, Any]:
    if bundle.get("schema") != SCHEMA:
        raise ValueError("source-state bundle schema mismatch")
    recomputed = canonical_cid(bundle["record"])
    if recomputed != bundle.get("source_state_root"):
        raise ValueError("source_state_root does not match its record")
    if bundle["record"]["plan_r2_admitted"] is not False:
        raise ValueError("source-state root must not admit Plan R2")
    if bundle["record"]["ducklake_authoritative"] is not False:
        raise ValueError("DuckLake must remain non-authoritative")
    return {
        "verified": True,
        "source_state_root": recomputed,
        "plan_r2_admitted": False,
    }
