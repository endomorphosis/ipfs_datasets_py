"""DSS-010 MCP++ wire boundary: datasets payloads stay application data only.

Proves that the semantic-state producer defines no MCP++ InterfaceDescriptor,
ExecutionEnvelope, ExecutionReceipt, or DAGEvent; never calculates an envelope
CID; and keeps request/attempt/provider fields out of the datasets root.
MCP++ Profile A/B/F remains the pinned generic outer-wire authority.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state import (
    SEMANTIC_STATE_API_SCHEMA,
    build_semantic_state,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    ROOT_EXCLUDED_FIELD_NAMES,
    BindingKind,
    BindingScope,
    EnvironmentBinding,
    SemanticStateProducer,
    SemanticStateRoot,
    SortedPairIndex,
)

PACKAGE_DIR = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py"
    / "logic"
    / "software_contracts"
    / "semantic_state"
)

# MCP++ generic wire types and envelope authorities — forbidden in datasets.
_FORBIDDEN_MCP_TYPE_NAMES: frozenset[str] = frozenset(
    {
        "InterfaceDescriptor",
        "ExecutionEnvelope",
        "ExecutionReceipt",
        "DAGEvent",
    }
)
_FORBIDDEN_ENVELOPE_HASHER_NAMES: frozenset[str] = frozenset(
    {
        "cid_for_envelope",
        "envelope_cid_for",
        "hash_envelope",
        "envelope_hasher",
        "compute_envelope_cid",
    }
)
_FORBIDDEN_ROOT_WIRE_FIELDS: frozenset[str] = frozenset(
    {
        "request_id",
        "attempt",
        "provider",
        "provider_output",
        "envelope",
        "envelope_cid",
        "execution_envelope",
        "execution_receipt",
        "dag_event",
        "interface_descriptor",
        "signature",
        "availability",
        "simulation",
        "simulation_flag",
    }
)

SCHEMA_PATH = PACKAGE_DIR / "schemas" / "semantic-state.payload.schema.json"


def _iter_package_py_files() -> tuple[Path, ...]:
    return tuple(sorted(PACKAGE_DIR.rglob("*.py")))


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _minimal_root() -> SemanticStateRoot:
    index = SortedPairIndex(pairs=[("k", _cid("block"))])
    producer = SemanticStateProducer(
        repository_state_cid=_cid("state"),
        repository_snapshot_cid=_cid("snapshot"),
        git_commit_oid_or_null=None,
        git_tree_oid_or_null=None,
        source_manifest_cid=_cid("manifest"),
        semantic_index_schema="ipfs-datasets.software-contracts.semantic-index@2",
        extractor_name="python-cpython-ast",
        extractor_version="1",
    )
    return SemanticStateRoot(
        repository_id="repo:mcp-boundary",
        producer=producer,
        symbol_fact_index_cid=index.index_cid,
        artifact_fact_index_cid=index.index_cid,
        semantic_link_index_cid=index.index_cid,
        symbol_node_index_cid=index.index_cid,
        capsule_index_cid=index.index_cid,
        environment_binding_set_cid=_cid("bindings"),
        analysis_limitation_index_cid=index.index_cid,
    )


# ---------------------------------------------------------------------------
# AST / export surface: no MCP++ types or envelope hashers
# ---------------------------------------------------------------------------


def test_package_defines_no_mcp_interface_descriptor_or_envelope_types() -> None:
    found_classes: list[str] = []
    found_imports: list[str] = []
    found_aliases: list[str] = []

    for path in _iter_package_py_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in _FORBIDDEN_MCP_TYPE_NAMES:
                found_classes.append(f"{path.name}:{node.name}")
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_MCP_TYPE_NAMES:
                        found_imports.append(f"{path.name}:from {node.module} import {alias.name}")
                    if alias.asname and alias.asname in _FORBIDDEN_MCP_TYPE_NAMES:
                        found_aliases.append(f"{path.name}:as {alias.asname}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_MCP_TYPE_NAMES or (
                        alias.asname and alias.asname in _FORBIDDEN_MCP_TYPE_NAMES
                    ):
                        found_imports.append(f"{path.name}:import {alias.name}")
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in _FORBIDDEN_MCP_TYPE_NAMES:
                        found_aliases.append(f"{path.name}:assign {target.id}")

    assert found_classes == []
    assert found_imports == []
    assert found_aliases == []


def test_package_defines_no_envelope_cid_hasher() -> None:
    found: list[str] = []
    for path in _iter_package_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in _FORBIDDEN_ENVELOPE_HASHER_NAMES:
                    found.append(f"{path.name}:{node.name}")
            if isinstance(node, ast.Name) and node.id in _FORBIDDEN_ENVELOPE_HASHER_NAMES:
                # Only flag definitions / attribute-free references that look like authorities.
                if isinstance(getattr(node, "ctx", None), ast.Store):
                    found.append(f"{path.name}:store {node.id}")
    assert found == []


def test_public_package_exports_exclude_mcp_wire_types() -> None:
    import ipfs_datasets_py.logic.software_contracts.semantic_state as pkg

    exported = set(pkg.__all__)
    assert _FORBIDDEN_MCP_TYPE_NAMES.isdisjoint(exported)
    for name in _FORBIDDEN_MCP_TYPE_NAMES:
        assert not hasattr(pkg, name)
    # Application API schema remains datasets-namespaced.
    assert SEMANTIC_STATE_API_SCHEMA.startswith(
        "ipfs-datasets.software-contracts.semantic-state"
    )


def test_root_excluded_field_names_cover_wire_and_provider_domain() -> None:
    missing = _FORBIDDEN_ROOT_WIRE_FIELDS - ROOT_EXCLUDED_FIELD_NAMES
    assert missing == frozenset(), f"ROOT_EXCLUDED_FIELD_NAMES missing {missing}"


def test_semantic_state_root_payload_has_no_request_attempt_provider_or_envelope() -> None:
    root = _minimal_root()
    payload = root.identity_payload()
    claim = root.to_dict()

    for field in _FORBIDDEN_ROOT_WIRE_FIELDS:
        assert field not in payload
        assert field not in claim

    # Closed application fields only — no MCP++ envelope shape.
    assert "schema" in payload
    assert payload["schema"].startswith("ipfs-datasets.software-contracts.")
    assert "envelope" not in json.dumps(payload)
    assert "dag_event" not in json.dumps(payload)


def test_root_rejects_injected_envelope_and_provider_fields() -> None:
    root = _minimal_root()
    forged = dict(root.to_dict())
    forged["request_id"] = "req-1"
    forged["attempt"] = 1
    forged["provider"] = "sim"
    forged["envelope_cid"] = _cid("envelope")
    forged["execution_envelope"] = {"x": 1}
    forged["dag_event"] = {"y": 2}
    forged["interface_descriptor"] = {"z": 3}

    with pytest.raises(Exception):
        SemanticStateRoot.from_dict(forged)


def test_payload_schema_rejects_mcp_envelope_fields() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    root = _minimal_root().to_dict()
    for field in (
        "envelope_cid",
        "execution_envelope",
        "dag_event",
        "request_id",
        "attempt",
        "provider",
    ):
        bad = dict(root)
        bad[field] = 1 if field == "attempt" else "x"
        errors = list(validator.iter_errors(bad))
        assert errors, f"schema must reject forbidden field {field!r}"


def test_binding_kind_interface_descriptor_is_application_not_mcp_type() -> None:
    """Environment BindingKind.INTERFACE_DESCRIPTOR is datasets application data.

    It must not be confused with MCP++ InterfaceDescriptor wire authority.
    """
    assert BindingKind.INTERFACE_DESCRIPTOR.value == "interface_descriptor"
    assert "InterfaceDescriptor" not in BindingKind.__members__
    # Constructing a binding uses the closed application kind string only.
    binding = EnvironmentBinding(
        binding_id="iface:controlled",
        kind=BindingKind.INTERFACE_DESCRIPTOR,
        version_cid=_cid("iface-v1"),
        scope=BindingScope.GLOBAL,
        extraction_authority="injected",
        confidence=AnalysisConfidence.EXACT,
    )
    payload = binding.identity_payload()
    assert payload["kind"] == "interface_descriptor"
    assert "InterfaceDescriptor" not in json.dumps(payload)
    assert "ExecutionEnvelope" not in json.dumps(payload)


def test_built_bundle_root_stays_free_of_wire_fields() -> None:
    source = "def sample(value: int) -> int:\n    return value\n"
    node = ast.parse(source).body[0]
    stable = stable_symbol_id(
        "repo:mcp-boundary",
        "python",
        "pkg/mod.py",
        "pkg.mod.sample",
        SymbolKind.FUNCTION,
        "pkg",
    )
    version = symbol_version_cid(stable, node, {"parameters": ["value"]}, (), {})
    symbol = SymbolRecord(
        stable,
        version,
        "repo:mcp-boundary",
        "python",
        "pkg/mod.py",
        "pkg.mod.sample",
        SymbolKind.FUNCTION,
        "pkg",
        cid_for_bytes(source.encode("utf-8")),
        None,
        AnalysisConfidence.EXACT,
        {"parameters": ["value"]},
        (),
        {},
        {},
        normalized_ast=node,
    )
    from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
        RepositoryState,
    )

    state = RepositoryState(
        "repo:mcp-boundary",
        symbols=(symbol,),
        artifacts=(),
        edges=(),
    )
    bundle = build_semantic_state(state)
    root_dict = bundle.root.to_dict()
    for field in _FORBIDDEN_ROOT_WIRE_FIELDS:
        assert field not in root_dict
    # Producer identity also excludes provider/request/attempt.
    producer = root_dict["producer"]
    for field in ("request_id", "attempt", "provider", "envelope_cid"):
        assert field not in producer


def test_models_module_source_documents_exclusion_not_implementation_of_mcp() -> None:
    models_path = PACKAGE_DIR / "models.py"
    source = models_path.read_text(encoding="utf-8")
    # Exclusion list mentions the names as forbidden strings, not as class bodies.
    tree = ast.parse(source)
    class_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    assert class_names.isdisjoint(_FORBIDDEN_MCP_TYPE_NAMES)
    # No function that computes envelope CIDs.
    func_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert func_names.isdisjoint(_FORBIDDEN_ENVELOPE_HASHER_NAMES)


def test_api_module_has_no_put_cas_provider_or_envelope_side_channels() -> None:
    import ipfs_datasets_py.logic.software_contracts.semantic_state.api as api

    source = inspect.getsource(api)
    # Storage-neutral: no kit provider / envelope hasher hooks in the public API.
    for banned in (
        "cid_for_envelope",
        "ExecutionEnvelope",
        "ExecutionReceipt",
        "DAGEvent",
        "InterfaceDescriptor",
        "ipfs_kit",
        "IpfsKit",
    ):
        assert banned not in source
