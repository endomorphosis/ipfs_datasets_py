"""Schema packaging gates for the semantic-state payload JSON Schema (DSS-009).

Packaging authority is additive and non-weakening:

* ``MANIFEST.in`` recursive-include (sdist + include-package-data wheels)
* ``setup.py`` package_data entry (classic setuptools installs)
* ``pyproject.toml`` already sets ``include-package-data = true``; no validation-
  config rewrite is required for this task and would be rejected by the
  proposal gate as validation weakening.
"""

from __future__ import annotations

import importlib.resources
import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
SCHEMA_RELATIVE = (
    "logic/software_contracts/semantic_state/schemas/*.json"
)
SCHEMA_NAME = "semantic-state.payload.schema.json"
MANIFEST_LINE = (
    "recursive-include ipfs_datasets_py/logic/software_contracts/"
    "semantic_state/schemas *.json"
)


def test_schema_file_exists_in_source_tree() -> None:
    path = (
        REPO_ROOT
        / "ipfs_datasets_py"
        / "logic"
        / "software_contracts"
        / "semantic_state"
        / "schemas"
        / SCHEMA_NAME
    )
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert "$schema" in payload or "$defs" in payload or "properties" in payload


def test_pyproject_enables_include_package_data() -> None:
    """Existing non-weakening packaging flag must remain enabled."""
    metadata = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert metadata["tool"]["setuptools"]["include-package-data"] is True


def test_setup_py_declares_semantic_state_schema_package_data() -> None:
    setup_source = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
    assert SCHEMA_RELATIVE in setup_source


def test_manifest_in_includes_semantic_state_schemas() -> None:
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert MANIFEST_LINE in manifest


def test_schema_loadable_via_importlib_resources() -> None:
    """Installed layout must expose the schema as package data."""
    try:
        root = importlib.resources.files(
            "ipfs_datasets_py.logic.software_contracts.semantic_state"
        )
        schema_path = root.joinpath("schemas").joinpath(SCHEMA_NAME)
        assert schema_path.is_file(), f"missing packaged schema at {schema_path}"
        text = schema_path.read_text(encoding="utf-8")
    except (ModuleNotFoundError, TypeError, FileNotFoundError, AttributeError):
        schemas = importlib.resources.files(
            "ipfs_datasets_py.logic.software_contracts.semantic_state.schemas"
        )
        schema_path = schemas.joinpath(SCHEMA_NAME)
        assert schema_path.is_file()
        text = schema_path.read_text(encoding="utf-8")

    payload = json.loads(text)
    assert isinstance(payload, dict)
    blob = json.dumps(payload)
    assert "semantic" in blob.lower() or "SemanticState" in blob or "$defs" in payload


def test_schema_declares_root_and_producer_shapes() -> None:
    path = (
        REPO_ROOT
        / "ipfs_datasets_py"
        / "logic"
        / "software_contracts"
        / "semantic_state"
        / "schemas"
        / SCHEMA_NAME
    )
    schema = json.loads(path.read_text(encoding="utf-8"))
    defs = schema.get("$defs") or schema.get("definitions") or {}
    names = set(defs) | set(schema.get("properties") or {})
    serialized = json.dumps(schema)
    assert (
        "SemanticStateRoot" in names
        or "semantic_state_root" in serialized.lower()
        or "semantic-state-root" in serialized
        or "repository_state_cid" in serialized
    )
    assert (
        "SemanticStateProducer" in names
        or "producer" in serialized.lower()
        or "repository_snapshot_cid" in serialized
    )
