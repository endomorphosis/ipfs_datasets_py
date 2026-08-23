"""Content-addressed four-repository source-state root for EAAEF-007.

This module builds a semantic/provenance root over the frozen External Agent
source forest. It does not open DuckDB, Quack, or DuckLake, and it does not
admit Plan R2.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA = "ExternalAgentSourceStateRoot@1"
PLANNING_FOREST_ROOT = "sha256:ed543c10f6aa90e093c8ae8b8866934e0cc1614e1be49ddcdc5dd7a2ce8565fa"
REPOSITORIES = (
    "ipfs_accelerate_py",
    "ipfs_datasets_py",
    "ipfs_kit_py",
    "Mcp-Plus-Plus",
)

_DATASETS_ROOT = Path(__file__).resolve().parents[2]
_SUPERPROJECT = _DATASETS_ROOT.parent
_CAMPAIGN = _SUPERPROJECT / "docs/architecture/external_agent_autonomous_execution_fabric"
_SOURCE_MANIFEST = _CAMPAIGN / "source_reconciliation_manifest.json"

SURFACE_PATHS = {
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


def _require_exact_repositories(value: Mapping[str, Any], *, field: str) -> None:
    expected = set(REPOSITORIES)
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            f"{field} must identify exactly the four EAAEF repositories; "
            f"missing={missing!r}, unexpected={unexpected!r}"
        )


def _require_git_oid(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 40:
        raise ValueError(f"{field} must be a 40-character Git object identity")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} must be a lowercase hexadecimal Git object identity")
    return value


def _require_sha256_cid(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValueError(f"{field} must be a sha256 content identity")
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field} must contain a lowercase SHA-256 digest")
    return value


def _validate_source_forest(source: Mapping[str, Any]) -> dict[str, Any]:
    if source.get("schema") != "SourceReconciliationManifest@1":
        raise ValueError("source reconciliation manifest schema mismatch")

    payload = source.get("source_forest_payload")
    if not isinstance(payload, Mapping):
        raise ValueError("source_forest_payload must be an object")
    if payload.get("schema") != "ExternalAgentSourceForest@1":
        raise ValueError("source forest payload schema mismatch")

    repositories = payload.get("repositories")
    selected = source.get("selected_integration_roots")
    if not isinstance(repositories, Mapping):
        raise ValueError("source_forest_payload.repositories must be an object")
    if not isinstance(selected, Mapping):
        raise ValueError("selected_integration_roots must be an object")
    _require_exact_repositories(repositories, field="source_forest_payload.repositories")
    _require_exact_repositories(selected, field="selected_integration_roots")

    for name in REPOSITORIES:
        repository = repositories[name]
        integration_root = selected[name]
        if not isinstance(repository, Mapping) or not isinstance(integration_root, Mapping):
            raise ValueError(f"repository identity for {name!r} must be an object")
        for object_kind in ("commit", "tree"):
            expected = _require_git_oid(
                repository.get(object_kind),
                field=f"source_forest_payload.repositories.{name}.{object_kind}",
            )
            actual = _require_git_oid(
                integration_root.get(object_kind),
                field=f"selected_integration_roots.{name}.{object_kind}",
            )
            if actual != expected:
                raise ValueError(
                    f"selected integration {object_kind} for {name!r} does not "
                    "match the frozen source forest"
                )

    source_root = source.get("source_forest_root")
    if canonical_cid(payload) != source_root:
        raise ValueError("source_forest_root does not match its canonical payload")
    if source_root != PLANNING_FOREST_ROOT:
        raise ValueError("planning source_forest_root drifted")
    return dict(source)


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


def load_source_forest(
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and verify the frozen four-repository planning manifest.

    The default is valid only when this repository is checked out at the
    conventional ``ipfs_datasets_py`` gitlink beneath the accelerator root.
    Standalone callers must provide the manifest explicitly; absence is an
    error rather than an invitation to synthesize repository evidence.
    """

    path = Path(manifest_path) if manifest_path is not None else _SOURCE_MANIFEST
    if not path.is_file():
        raise FileNotFoundError(
            "the frozen EAAEF source reconciliation manifest is unavailable at "
            f"{path}; pass manifest_path explicitly for a standalone checkout"
        )
    source = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(source, Mapping):
        raise ValueError("source reconciliation manifest must be a JSON object")
    return _validate_source_forest(source)


def _repository_roots(
    repository_roots: Mapping[str, str | Path] | None,
) -> dict[str, Path]:
    supplied = _REPO_ROOTS if repository_roots is None else repository_roots
    _require_exact_repositories(supplied, field="repository_roots")
    roots = {name: Path(supplied[name]) for name in REPOSITORIES}
    for name, root in roots.items():
        if not root.is_dir():
            raise FileNotFoundError(
                f"repository root for {name!r} is unavailable at {root}; pass "
                "repository_roots explicitly for the exact four-repository forest"
            )
    return roots


def surface_inventory(
    repository_roots: Mapping[str, str | Path] | None = None,
) -> dict[str, list[dict[str, str]]]:
    roots = _repository_roots(repository_roots)
    inventory: dict[str, list[dict[str, str]]] = {}
    for name, relatives in SURFACE_PATHS.items():
        root = roots[name].resolve()
        rows: list[dict[str, str]] = []
        for relative in relatives:
            candidate = root / relative
            try:
                path = candidate.resolve(strict=True)
            except FileNotFoundError as exc:
                raise FileNotFoundError(
                    f"declared EAAEF surface is unavailable: {name}:{relative}"
                ) from exc
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ValueError(
                    f"declared EAAEF surface escapes repository root: {name}:{relative}"
                ) from exc
            if not path.is_file():
                raise FileNotFoundError(f"declared EAAEF surface is not a file: {name}:{relative}")
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
    *,
    manifest_path: str | Path | None = None,
    repository_roots: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    if source is not None and manifest_path is not None:
        raise ValueError("provide source or manifest_path, not both")
    source_obj = (
        _validate_source_forest(source) if source is not None else load_source_forest(manifest_path)
    )
    payload = source_obj["source_forest_payload"]
    inventory = surface_inventory(repository_roots)
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
    record = bundle.get("record")
    if not isinstance(record, Mapping) or record.get("schema") != SCHEMA:
        raise ValueError("source-state record schema mismatch")
    if record.get("planning_source_forest_root") != PLANNING_FOREST_ROOT:
        raise ValueError("source-state record does not bind the frozen planning root")
    payload = record.get("source_forest_payload")
    selected = record.get("selected_integration_roots")
    inventory = record.get("surface_inventory")
    if not isinstance(inventory, Mapping):
        raise ValueError("source-state surface inventory must be an object")
    _validate_source_forest(
        {
            "schema": "SourceReconciliationManifest@1",
            "source_forest_payload": payload,
            "source_forest_root": record["planning_source_forest_root"],
            "selected_integration_roots": selected,
        }
    )
    _require_exact_repositories(inventory, field="record surface inventory")
    for name in REPOSITORIES:
        rows = inventory[name]
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"record surface inventory for {name!r} must be non-empty")
        expected_paths = list(SURFACE_PATHS[name])
        actual_paths: list[object] = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise ValueError(f"record surface inventory row {name}[{index}] must be an object")
            actual_paths.append(row.get("path"))
            _require_sha256_cid(
                row.get("content_cid"),
                field=f"record surface inventory {name}[{index}].content_cid",
            )
            if str(row.get("path", "")).endswith(".py"):
                _require_sha256_cid(
                    row.get("ast_cid"),
                    field=f"record surface inventory {name}[{index}].ast_cid",
                )
        if actual_paths != expected_paths:
            raise ValueError(
                f"record surface inventory paths for {name!r} do not match the "
                "declared reconciliation surface"
            )

    recomputed = canonical_cid(record)
    if recomputed != bundle.get("source_state_root"):
        raise ValueError("source_state_root does not match its record")
    if record.get("plan_r2_admitted") is not False:
        raise ValueError("source-state root must not admit Plan R2")
    if record.get("ducklake_authoritative") is not False:
        raise ValueError("DuckLake must remain non-authoritative")

    changed = recomputed != PLANNING_FOREST_ROOT
    expected_delta = {
        "schema": "ExternalAgentSourceStateDelta@1",
        "planning_source_forest_root": PLANNING_FOREST_ROOT,
        "post_reconciliation_root": recomputed,
        "changed": changed,
    }
    if bundle.get("delta") != expected_delta:
        raise ValueError("source-state delta does not match the verified roots")
    expected_invalidation = {
        "schema": "ExternalAgentSourceStateInvalidation@1",
        "invalidates": [PLANNING_FOREST_ROOT] if changed else [],
        "reason": (
            "post-reconciliation surface inventory is a distinct semantic root"
            if changed
            else "post-reconciliation root equals planning forest root"
        ),
    }
    if bundle.get("invalidation") != expected_invalidation:
        raise ValueError("source-state invalidation does not match the verified delta")
    return {
        "verified": True,
        "source_state_root": recomputed,
        "plan_r2_admitted": False,
    }
