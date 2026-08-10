"""Unit tests for the DQP-039 DuckDB code-evidence adapter (DQK-034).

Acceptance coverage:

* The adapter verifies the exact DQP release/tree/schema identity
* No whole-artifact JSON load is required
* Datasets and supervisor projections remain schema compatible
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    """Prefer the admitted accelerate checkout over the nested worktree copy."""

    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

from ipfs_datasets_py.knowledge_graphs.adapters import code_evidence as ce  # noqa: E402
from ipfs_datasets_py.knowledge_graphs.adapters.duckdb_code_evidence import (  # noqa: E402
    ADAPTER_SCHEMA_VERSION,
    DUCKDB_CODE_EVIDENCE_INTERFACE,
    DUCKDB_CODE_EVIDENCE_SCHEMA,
    DQP_PROGRAM_ID,
    DQP_RELEASE_RECEIPT_INTERFACE,
    DQP_RELEASE_RECEIPT_SCHEMA,
    DQP_RELEASE_TASK_ID,
    DQP_VERIFICATION_SCHEMA,
    DQPReleaseIdentity,
    DuckDBCodeEvidenceAdapter,
    DuckDBCodeEvidenceError,
    IdentityMismatchError,
    SchemaCompatibilityError,
    WholeArtifactLoadError,
    assert_schema_compatible,
    build_duckdb_code_evidence_adapter,
    schema_compatibility_report,
    verify_dqp_release_identity,
)
from ipfs_datasets_py.logic.software_contracts.ast_ir import (  # noqa: E402
    ASTRecord,
    CallRecord,
    FrontendCapability,
    ImportDefinition,
    ModuleDefinition,
    ParameterDefinition,
    ReferenceRecord,
    ScopeDefinition,
    SignatureDefinition,
    SourceProvenance,
    SourceSpan,
    SymbolDefinition,
)
from ipfs_datasets_py.logic.software_contracts.content import (  # noqa: E402
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (  # noqa: E402
    DUCKDB_AST_STORE_INTERFACE,
    SUPERVISOR_BLOB_SUMMARY_SCHEMA,
    project_ast_record,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_impact import (  # noqa: E402
    ImpactBudget,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

COMMIT = "a" * 40
TREE = "b" * 40
SCHEMA_CHECKSUM = "sha256:" + ("c" * 64)
STORE_GENERATION = "store-gen:dqp-039:1"
QUACK_PROFILE = "duckdb-quack@1.5.5"
SOURCE_REVISION = "rev:src-fixture-001"
SOURCE = (
    b"from os import environ\n"
    b"async def fetch(value: int = 1) -> str:\n"
    b"    await client(value=value)\n"
)


def _identity_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": DQP_RELEASE_RECEIPT_SCHEMA,
        "program_id": DQP_PROGRAM_ID,
        "task_id": DQP_RELEASE_TASK_ID,
        "interface": DQP_RELEASE_RECEIPT_INTERFACE,
        "accelerator_commit": COMMIT,
        "accelerator_tree": TREE,
        "schema_checksum": SCHEMA_CHECKSUM,
        "store_generation": STORE_GENERATION,
        "quack_profile": QUACK_PROFILE,
        "accepted": True,
        "decision_cid": "bafydecision0001",
        "receipt_cid": "bafyreceipt0001",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def identity() -> DQPReleaseIdentity:
    return verify_dqp_release_identity(_identity_payload())


@pytest.fixture
def adapter(identity: DQPReleaseIdentity) -> DuckDBCodeEvidenceAdapter:
    return build_duckdb_code_evidence_adapter(
        identity, source_revision=SOURCE_REVISION
    )


def _span(
    start: int = 0,
    end: int = 1,
    line: int = 1,
    end_line: int | None = None,
) -> SourceSpan:
    return SourceSpan(
        start_byte=start,
        end_byte=end,
        start_line=line,
        start_column=0,
        end_line=line if end_line is None else end_line,
        end_column=max(end - start, 0),
    )


def _ast_record(*, revision: str = SOURCE_REVISION) -> ASTRecord:
    whole = _span(0, len(SOURCE), 1, 3)
    function_span = _span(23, len(SOURCE), 2, 3)
    call_span = _span(50, 70, 3)
    root_scope = ScopeDefinition(
        scope_id="scope:module",
        kind="module",
        span=whole,
    )
    function_scope = ScopeDefinition(
        scope_id="scope:function:fetch",
        kind="function",
        span=function_span,
        parent_scope_id="scope:module",
        owner_symbol_id="symbol:fetch:0",
    )
    signature = SignatureDefinition(
        parameters=(
            ParameterDefinition(
                name="value",
                kind="positional_or_named",
                position=0,
                annotation="int",
                default_kind="literal",
            ),
        ),
        return_annotation="str",
        is_async=True,
    )
    symbol = SymbolDefinition(
        symbol_id="symbol:fetch:0",
        name="fetch",
        qualified_name="example.fetch",
        kind="function",
        scope_id="scope:module",
        span=function_span,
        definition_ordinal=0,
        signature=signature,
        visibility="public",
        decorator_names=(),
        flags=("coroutine",),
    )
    reference = ReferenceRecord(
        reference_id="reference:client:0",
        name="client",
        scope_id="scope:function:fetch",
        context="call",
        span=call_span,
    )
    return ASTRecord(
        provenance=SourceProvenance(
            source_cid=cid_for_bytes(SOURCE),
            path="src/example.py",
            repository_id="repository:example",
            revision=revision,
            repository_tree_cid=cid_for_structured({"git_tree": TREE}),
        ),
        frontend=FrontendCapability(
            frontend_name="cpython-ast",
            frontend_version="3.12.4",
            language="python",
            language_version="3.12",
            capabilities=(
                "unsupported_constructs",
                "symbols",
                "references",
                "modules",
                "calls",
            ),
            source_extensions=(".pyi", ".py"),
            toolchain_cid=cid_for_structured(
                {"frontend": "cpython-ast", "version": "3.12.4"}
            ),
        ),
        module=ModuleDefinition(
            module_id="module:example",
            name="example",
            scope_id="scope:module",
            span=whole,
            export_names=("fetch",),
        ),
        scopes=(function_scope, root_scope),
        symbols=(symbol,),
        imports=(
            ImportDefinition(
                import_id="import:os.environ:0",
                scope_id="scope:module",
                module="os",
                kind="symbol",
                span=_span(0, 22, 1),
                imported_name="environ",
                local_name="environ",
            ),
        ),
        references=(reference,),
        calls=(
            CallRecord(
                call_id="call:client:0",
                scope_id="scope:function:fetch",
                callee_name="client",
                kind="direct",
                argument_count=1,
                span=call_span,
                callee_reference_id=reference.reference_id,
                named_argument_names=("value",),
                is_awaited=True,
            ),
        ),
        effects=(),
        diagnostics=(),
        unsupported=(),
    )


# ---------------------------------------------------------------------------
# Acceptance: exact DQP release/tree/schema identity
# ---------------------------------------------------------------------------


def test_verify_dqp_release_identity_extracts_exact_triple() -> None:
    identity = verify_dqp_release_identity(_identity_payload())
    assert identity.accelerator_commit == COMMIT
    assert identity.accelerator_tree == TREE
    assert identity.schema_checksum == SCHEMA_CHECKSUM
    assert identity.store_generation == STORE_GENERATION
    assert identity.quack_profile == QUACK_PROFILE
    assert identity.task_id == DQP_RELEASE_TASK_ID
    assert identity.interface == DQP_RELEASE_RECEIPT_INTERFACE
    assert identity.triple == (COMMIT, TREE, SCHEMA_CHECKSUM)


def test_verify_rejects_unaccepted_and_process_status() -> None:
    with pytest.raises(DuckDBCodeEvidenceError, match="not accepted"):
        verify_dqp_release_identity(_identity_payload(accepted=False))
    with pytest.raises(DuckDBCodeEvidenceError, match="process status"):
        verify_dqp_release_identity(
            _identity_payload(master_alive=True, release_status="done")
        )
    with pytest.raises(DuckDBCodeEvidenceError, match="Git OID"):
        verify_dqp_release_identity(
            _identity_payload(accelerator_commit="not-a-git-oid")
        )
    with pytest.raises(DuckDBCodeEvidenceError, match="sha256"):
        verify_dqp_release_identity(
            _identity_payload(schema_checksum="deadbeef")
        )


def test_verify_accepts_verification_schema() -> None:
    identity = verify_dqp_release_identity(
        _identity_payload(schema=DQP_VERIFICATION_SCHEMA)
    )
    assert identity.accelerator_tree == TREE


def test_adapter_verify_identity_exact_match(
    adapter: DuckDBCodeEvidenceAdapter,
) -> None:
    matched = adapter.verify_identity(_identity_payload())
    assert matched.triple == (COMMIT, TREE, SCHEMA_CHECKSUM)
    assert adapter.stats()["identity_checks"] >= 1

    with pytest.raises(IdentityMismatchError, match="identity mismatch"):
        adapter.verify_identity(
            _identity_payload(accelerator_tree="d" * 40)
        )
    with pytest.raises(IdentityMismatchError, match="schema"):
        adapter.verify_identity(
            _identity_payload(schema_checksum="sha256:" + ("e" * 64))
        )
    with pytest.raises(IdentityMismatchError, match="store_generation"):
        adapter.verify_identity(
            _identity_payload(store_generation="store-gen:other")
        )


def test_cutover_identity_must_agree() -> None:
    with pytest.raises(IdentityMismatchError, match="cutover"):
        verify_dqp_release_identity(
            _identity_payload(
                cutover={
                    "accelerator_commit": COMMIT,
                    "accelerator_tree": "f" * 40,
                    "schema_checksum": SCHEMA_CHECKSUM,
                    "store_generation": STORE_GENERATION,
                    "quack_profile": QUACK_PROFILE,
                }
            )
        )


# ---------------------------------------------------------------------------
# Acceptance: no whole-artifact JSON load
# ---------------------------------------------------------------------------


def test_refuses_whole_artifact_json_load(
    adapter: DuckDBCodeEvidenceAdapter,
) -> None:
    with pytest.raises(WholeArtifactLoadError, match="refuses whole-artifact"):
        adapter.load_whole_artifact_json("/tmp/bundle.json")
    with pytest.raises(WholeArtifactLoadError):
        adapter.load_bundle("anything")
    with pytest.raises(WholeArtifactLoadError):
        adapter.load_code_evidence_graph_artifact({})
    with pytest.raises(WholeArtifactLoadError):
        adapter.load_analysis_ast_index_artifact({})
    with pytest.raises(WholeArtifactLoadError):
        adapter.load_conflict_graph_artifact({})
    assert adapter.stats()["refused_whole_artifact_loads"] >= 5


def test_row_wise_ast_dependency_conflict_evidence_without_json(
    adapter: DuckDBCodeEvidenceAdapter,
) -> None:
    """Consumers can query AST/dependency/conflict/evidence via rows only."""

    projection = project_ast_record(_ast_record())
    stored = adapter.put_ast_projection(projection)
    assert stored.blob_id
    assert stored.ast_blob.store_schema_version

    # AST lookup by path/symbol — no JSON artifact involved.
    ast_hits = adapter.ast_lookup(path="src/example.py", symbol="fetch")
    assert ast_hits["source_revision"] == SOURCE_REVISION
    assert ast_hits["result_count"] == 1
    assert "example.fetch" in ast_hits["results"][0]["qualified_symbols"]
    assert ast_hits["results"][0]["schema"] == SUPERVISOR_BLOB_SUMMARY_SCHEMA
    assert ast_hits["dqp_identity"]["accelerator_commit"] == COMMIT

    # Dependency closure via impact edges (DQK-033 store reuse).
    adapter.put_impact_edge("mod.A", "mod.B", "import")
    adapter.put_impact_edge("mod.B", "mod.C", "call")
    adapter.put_impact_edges(
        [
            {"source": "mod.A", "target": "mod.D", "kind": "reference"},
            ("mod.E", "mod.B", "call"),
        ]
    )
    fwd = adapter.dependency_closure(["mod.A"], direction="forward")
    assert fwd.source_revision == SOURCE_REVISION
    assert set(fwd.nodes) == {"mod.A", "mod.B", "mod.C", "mod.D"}
    shallow = adapter.dependency_closure(
        ["mod.A"],
        direction="forward",
        budget=ImpactBudget(max_depth=0),
    )
    assert shallow.nodes == ("mod.A",)

    # Evidence rows (supervisor-compatible node schema).
    node_a = adapter.put_evidence_node(
        {
            "kind": "task",
            "record_key": "task:DQK-034",
            "provenance": "task",
            "task_id": "DQK-034",
            "tree_id": TREE,
            "record": {"title": "code evidence adapter"},
        }
    )
    node_b = adapter.put_evidence_node(
        {
            "kind": "symbol",
            "record_key": "symbol:example.fetch",
            "provenance": "ast",
            "symbol": "example.fetch",
            "record": {"path": "src/example.py"},
        }
    )
    edge = adapter.put_evidence_edge(
        {
            "source": node_a["node_id"],
            "target": node_b["node_id"],
            "kind": "defines_symbol",
            "provenance": "ast",
            "provenance_record_id": "ast-blob:example",
        }
    )
    assert edge["schema"] == ce.CODE_EVIDENCE_EDGE_SCHEMA
    evidence = adapter.evidence_query(node_ids=[node_a["node_id"]])
    assert evidence["node_count"] == 1
    assert evidence["edge_count"] == 1
    assert evidence["supervisor_schema"] == ce.CODE_EVIDENCE_GRAPH_SCHEMA
    assert evidence["source_revision"] == SOURCE_REVISION

    # Conflict rows.
    adapter.put_conflict_surface(
        {
            "task_id": "DQK-034",
            "task_cid": "task-cid-034",
            "predicted_paths": ["src/example.py"],
            "predicted_symbols": ["example.fetch"],
        }
    )
    adapter.put_conflict_edge(
        {
            "left_task_cid": "task-cid-034",
            "right_task_cid": "task-cid-033",
            "weight": 1.0,
            "reasons": ["path_overlap"],
        }
    )
    conflicts = adapter.conflict_query(task_cid="task-cid-034", blocking_only=True)
    assert conflicts["edge_count"] == 1
    assert conflicts["surface"]["task_id"] == "DQK-034"
    assert conflicts["supervisor_schema"] == ce.CONFLICT_GRAPH_SCHEMA
    assert conflicts["dqp_identity"]["schema_checksum"] == SCHEMA_CHECKSUM


# ---------------------------------------------------------------------------
# Acceptance: datasets and supervisor projections remain schema compatible
# ---------------------------------------------------------------------------


def test_schema_compatibility_report_and_assert() -> None:
    report = schema_compatibility_report()
    assert report["compatible"] is True
    assert report["mismatches"] == {}
    assert report["guarantees"]["no_second_ast_schema"] is True
    assert (
        report["supervisor_pins"]["code_evidence_graph"]
        == ce.CODE_EVIDENCE_GRAPH_SCHEMA
    )
    assert (
        report["supervisor_pins"]["conflict_graph"] == ce.CONFLICT_GRAPH_SCHEMA
    )
    assert (
        report["supervisor_pins"]["analysis_ast_index"]
        == ce.ANALYSIS_AST_INDEX_SCHEMA
    )
    assert (
        report["datasets_pins"]["duckdb_ast_store_interface"]
        == DUCKDB_AST_STORE_INTERFACE
    )
    assert (
        report["supervisor_pins"]["supervisor_blob_summary"]
        == SUPERVISOR_BLOB_SUMMARY_SCHEMA
    )
    asserted = assert_schema_compatible()
    assert asserted["compatible"] is True


def test_adapter_pins_and_descriptor(
    adapter: DuckDBCodeEvidenceAdapter, identity: DQPReleaseIdentity
) -> None:
    assert adapter.interface == DUCKDB_CODE_EVIDENCE_INTERFACE
    assert adapter.schema == DUCKDB_CODE_EVIDENCE_SCHEMA
    assert adapter.identity == identity
    assert adapter.source_revision == SOURCE_REVISION
    desc = adapter.descriptor()
    assert desc["interface"] == DUCKDB_CODE_EVIDENCE_INTERFACE
    assert desc["schema_version"] == ADAPTER_SCHEMA_VERSION
    assert desc["guarantees"]["verifies_exact_dqp_release_tree_schema_identity"]
    assert desc["guarantees"]["no_whole_artifact_json_load"]
    assert desc["guarantees"]["datasets_supervisor_schema_compatible"]
    assert desc["guarantees"]["does_not_reimplement_supervisor_stores"]
    assert desc["reuses"]["duckdb_ast_store"] == DUCKDB_AST_STORE_INTERFACE
    assert desc["dqp_identity"]["accelerator_tree"] == TREE


def test_supervisor_and_datasets_node_edge_schemas_align(
    adapter: DuckDBCodeEvidenceAdapter,
) -> None:
    """Ingested evidence rows keep supervisor schema identities intact."""

    node = adapter.put_evidence_node(
        {
            "schema": ce.CODE_EVIDENCE_NODE_SCHEMA,
            "kind": "proof",
            "record_key": "proof:1",
            "provenance": "proof",
            "record": {"status": "valid"},
        }
    )
    assert node["schema"] == ce.CODE_EVIDENCE_NODE_SCHEMA
    edge = adapter.put_evidence_edge(
        {
            "schema": ce.CODE_EVIDENCE_EDGE_SCHEMA,
            "source": node["node_id"],
            "target": node["node_id"],
            "kind": "derived_from",
            "provenance": "proof",
            "provenance_record_id": "proof-run-1",
        }
    )
    assert edge["schema"] == ce.CODE_EVIDENCE_EDGE_SCHEMA


def test_module_exports_stable_public_surface() -> None:
    mod = importlib.import_module(
        "ipfs_datasets_py.knowledge_graphs.adapters.duckdb_code_evidence"
    )
    for name in (
        "DuckDBCodeEvidenceAdapter",
        "DQPReleaseIdentity",
        "verify_dqp_release_identity",
        "assert_schema_compatible",
        "build_duckdb_code_evidence_adapter",
        "schema_compatibility_report",
        "DUCKDB_CODE_EVIDENCE_INTERFACE",
        "DQP_RELEASE_TASK_ID",
    ):
        assert hasattr(mod, name), name


def test_construction_from_mapping_verifies_identity() -> None:
    adapter = DuckDBCodeEvidenceAdapter(
        _identity_payload(), source_revision=SOURCE_REVISION
    )
    assert adapter.identity.accelerator_commit == COMMIT
    with pytest.raises(DuckDBCodeEvidenceError):
        DuckDBCodeEvidenceAdapter(
            _identity_payload(accepted=False),
            source_revision=SOURCE_REVISION,
        )
