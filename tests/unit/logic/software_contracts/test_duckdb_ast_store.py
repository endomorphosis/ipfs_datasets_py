"""Unit tests for the normalized DuckDB AST / code-evidence store (DQK-031).

Acceptance coverage:

* Canonical AST IR identity and source spans survive projection
* Datasets and supervisor do not invent incompatible AST schemas
* Parse failures are durable queryable facts
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    """Prefer the admitted accelerate checkout over the nested worktree copy.

    The validator plugin rejects collection when nested validation-runtime
    bytes diverge from the admitted accelerate root.  Matching other DuckDB
    unit tests, reorder ``sys.path`` before any accelerate import so the
    sealed checkout wins.
    """

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

import pytest

from ipfs_datasets_py.logic.software_contracts.ast_ir import (
    ASTRecord,
    CallRecord,
    DiagnosticRecord,
    EffectRecord,
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
    UnsupportedConstruct,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ASTS_CATALOG_DDL,
    ASTS_CATALOG_NAME,
    ASTS_CATALOG_TABLES,
    AST_NODE_KINDS,
    DUCKDB_AST_STORE_INTERFACE,
    DUCKDB_AST_STORE_SCHEMA_VERSION,
    PARSE_FAILURE_DIAGNOSTIC_CODE,
    SUPERVISOR_BLOB_SUMMARY_SCHEMA,
    DuckDBASTStore,
    DuckDBASTStoreError,
    DuckDBASTStoreIntegrityError,
    ParseStatus,
    ast_store_schema_descriptor,
    build_duckdb_ast_store,
    project_ast_record,
    project_parse_failure,
    spans_survive_projection,
)
from ipfs_datasets_py.logic.software_contracts.schema_versions import (
    AST_IR_SCHEMA_VERSION,
)


SOURCE = (
    b"from os import environ\n"
    b"async def fetch(value: int = 1) -> str:\n"
    b"    await client(value=value)\n"
    b"    raise RuntimeError()\n"
)


def span(
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


def frontend(
    *,
    capabilities: tuple[str, ...] = (
        "unsupported_constructs",
        "symbols",
        "references",
        "modules",
        "calls",
    ),
) -> FrontendCapability:
    return FrontendCapability(
        frontend_name="cpython-ast",
        frontend_version="3.12.4",
        language="python",
        language_version="3.12",
        capabilities=capabilities,
        source_extensions=(".pyi", ".py"),
        toolchain_cid=cid_for_structured(
            {"frontend": "cpython-ast", "version": "3.12.4"}
        ),
    )


def complete_record() -> ASTRecord:
    whole = span(0, len(SOURCE), 1, 4)
    function_span = span(23, len(SOURCE), 2, 4)
    call_span = span(76, 95, 3)
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
            revision="0123456789abcdef",
            repository_tree_cid=cid_for_structured({"git_tree": "abc123"}),
        ),
        frontend=frontend(),
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
                span=span(0, 22),
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
        effects=(
            EffectRecord(
                effect_id="effect:raise:0",
                scope_id="scope:function:fetch",
                kind="exception",
                operation="raise",
                span=span(100, 120, 4),
                subject="RuntimeError",
            ),
            EffectRecord(
                effect_id="effect:await:0",
                scope_id="scope:function:fetch",
                kind="await",
                operation="await",
                span=call_span,
                subject="client",
            ),
        ),
        diagnostics=(
            DiagnosticRecord(
                code="frontend.unbound_candidate",
                severity="warning",
                message="client requires a separate resolution pass",
                span=call_span,
            ),
        ),
        unsupported=(
            UnsupportedConstruct(
                unsupported_id="unsupported:dynamic-import:0",
                code="frontend.dynamic_import",
                construct="dynamic_import",
                reason="Dynamic import targets are not statically enumerable.",
                span=span(0, 1),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Interface / catalog pins
# ---------------------------------------------------------------------------


def test_interfaces_schema_and_catalog_are_pinned() -> None:
    store = build_duckdb_ast_store()
    assert store.interface == DUCKDB_AST_STORE_INTERFACE
    assert store.schema_version == DUCKDB_AST_STORE_SCHEMA_VERSION
    assert DUCKDB_AST_STORE_INTERFACE == "DuckDBASTStore@1"
    assert ASTS_CATALOG_NAME == "asts"
    assert set(store.catalog_tables()) == set(ASTS_CATALOG_TABLES)
    assert ASTS_CATALOG_TABLES == (
        "source_revisions",
        "source_files",
        "ast_blobs",
        "ast_nodes",
        "scopes",
        "symbols",
        "imports",
        "references",
        "calls",
        "effects",
        "interfaces",
        "diagnostics",
        "invalidations",
    )
    for table in ASTS_CATALOG_TABLES:
        # Reserved SQL identifiers (e.g. references) are double-quoted in DDL.
        assert (
            f"CREATE TABLE IF NOT EXISTS {table}" in ASTS_CATALOG_DDL
            or f'CREATE TABLE IF NOT EXISTS "{table}"' in ASTS_CATALOG_DDL
        )

    descriptor = ast_store_schema_descriptor()
    assert descriptor["interface"] == DUCKDB_AST_STORE_INTERFACE
    assert descriptor["ast_ir_schema"]["identifier"] == AST_IR_SCHEMA_VERSION.identifier
    assert descriptor["guarantees"]["no_second_ast_schema"] is True
    assert set(descriptor["tables"]) == set(ASTS_CATALOG_TABLES)
    assert set(descriptor["node_kinds"]) == AST_NODE_KINDS


def test_module_import_is_inert_without_duckdb() -> None:
    """Importing the store must not require the duckdb package."""

    mod = importlib.import_module(
        "ipfs_datasets_py.logic.software_contracts.duckdb_ast_store"
    )
    assert mod.DUCKDB_AST_STORE_INTERFACE == "DuckDBASTStore@1"
    # duckdb may be present from other tests; the important property is that
    # import succeeded without opening a connection.
    assert mod.ASTS_CATALOG_NAME == "asts"


# ---------------------------------------------------------------------------
# Acceptance: identity and spans survive projection
# ---------------------------------------------------------------------------


def test_canonical_ast_ir_identity_survives_projection() -> None:
    record = complete_record()
    projection = project_ast_record(record, created_at=1.0)

    assert projection.ast_cid == record.cid
    assert projection.source_cid == record.provenance.source_cid
    assert projection.ast_blob.ast_schema_identifier == AST_IR_SCHEMA_VERSION.identifier
    assert projection.ast_blob.store_schema_version == DUCKDB_AST_STORE_SCHEMA_VERSION
    assert projection.ast_blob.parse_status == ParseStatus.OK.value
    assert projection.verify_identity(record) == record.cid

    # Full IR payload is retained for exact round-trip consumers.
    restored = ASTRecord.from_dict(json.loads(projection.ast_blob.payload_json))
    assert restored == record
    assert restored.cid == record.cid


def test_source_spans_survive_projection() -> None:
    record = complete_record()
    projection = project_ast_record(record, created_at=1.0)

    assert spans_survive_projection(record, projection)

    symbol = next(item for item in projection.symbols if item.symbol_id == "symbol:fetch:0")
    assert symbol.span.start_byte == record.symbols[0].span.start_byte
    assert symbol.span.end_byte == record.symbols[0].span.end_byte
    assert symbol.span.start_line == record.symbols[0].span.start_line
    assert symbol.span.end_line == record.symbols[0].span.end_line

    call = projection.calls[0]
    assert call.span.matches(record.calls[0].span)

    module_node = next(node for node in projection.nodes if node.node_kind == "module")
    assert module_node.span.matches(record.module.span)

    # Every span-bearing IR fact appears as an ast_nodes row with the same span.
    symbol_node = next(
        node
        for node in projection.nodes
        if node.node_kind == "symbol" and node.record_id == "symbol:fetch:0"
    )
    assert symbol_node.span.matches(record.symbols[0].span)


def test_projection_covers_all_catalog_fact_families() -> None:
    record = complete_record()
    projection = project_ast_record(record, created_at=1.0)
    counts = projection.table_row_counts()

    assert set(counts) == set(ASTS_CATALOG_TABLES)
    assert counts["source_revisions"] == 1
    assert counts["source_files"] == 1
    assert counts["ast_blobs"] == 1
    assert counts["scopes"] == len(record.scopes)
    assert counts["symbols"] == len(record.symbols)
    assert counts["imports"] == len(record.imports)
    assert counts["references"] == len(record.references)
    assert counts["calls"] == len(record.calls)
    assert counts["effects"] == len(record.effects)
    assert counts["diagnostics"] == len(record.diagnostics)
    assert counts["ast_nodes"] >= (
        1  # module
        + len(record.scopes)
        + len(record.symbols)
        + len(record.imports)
        + len(record.references)
        + len(record.calls)
        + len(record.effects)
        + len(record.unsupported)
    )
    assert counts["interfaces"] >= 1
    assert projection.interfaces[0].span.matches(record.symbols[0].span) or any(
        item.kind == "module" for item in projection.interfaces
    )


def test_verify_identity_fails_closed_on_drift() -> None:
    record = complete_record()
    projection = project_ast_record(record, created_at=1.0)
    # Mutate a copy of the blob identity via object replacement.
    from dataclasses import replace

    drifted = replace(
        projection,
        ast_blob=replace(projection.ast_blob, ast_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
    )
    with pytest.raises(DuckDBASTStoreIntegrityError):
        drifted.verify_identity(record)


# ---------------------------------------------------------------------------
# Acceptance: compatible schema with supervisor code-evidence plane
# ---------------------------------------------------------------------------


def test_supervisor_blob_summary_reuses_code_evidence_vocabulary() -> None:
    record = complete_record()
    projection = project_ast_record(record, created_at=1.0)
    summary = projection.to_supervisor_blob_summary()

    # Field names align with accelerate ASTBlobRecord / code-evidence graph.
    required = {
        "schema",
        "blob_identity",
        "source_sha256",
        "language",
        "qualified_symbols",
        "imports",
        "calls",
        "interfaces",
        "symbol_lines",
        "parse_error",
        "ast_cid",
        "ast_schema",
    }
    assert required.issubset(summary)
    assert summary["schema"] == SUPERVISOR_BLOB_SUMMARY_SCHEMA
    assert summary["ast_cid"] == record.cid
    assert summary["ast_schema"] == AST_IR_SCHEMA_VERSION.identifier
    assert "example.fetch" in summary["qualified_symbols"]
    assert summary["language"] == "python"
    assert summary["parse_error"] == ""
    assert summary["symbol_lines"]["example.fetch"] == [
        record.symbols[0].span.start_line,
        record.symbols[0].span.end_line,
    ]
    # No invented parallel AST schema identifier.
    assert "ast-ir-v2" not in json.dumps(summary)
    assert summary["ast_schema"] == "ipfs-datasets.software-contracts.ast-ir@1.0.0"


def test_store_rejects_incompatible_ast_schema_on_projection() -> None:
    record = complete_record()
    projection = project_ast_record(record, created_at=1.0)
    from dataclasses import replace

    bad = replace(
        projection,
        ast_blob=replace(
            projection.ast_blob,
            ast_schema_identifier="someone.else.invented-ast@9.9.9",
        ),
    )
    store = build_duckdb_ast_store()
    with pytest.raises(DuckDBASTStoreError, match="shared software-contract AST IR"):
        store.put_projection(bad)


def test_store_put_and_get_preserve_projection() -> None:
    record = complete_record()
    store = build_duckdb_ast_store()
    stored = store.put(record, created_at=42.0)

    loaded = store.get(stored.blob_id)
    assert loaded is not None
    assert loaded.ast_cid == record.cid
    assert store.get_by_ast_cid(record.cid) is loaded
    assert store.get_by_file_id(stored.source_file.file_id) is loaded
    assert spans_survive_projection(record, loaded)
    assert store.stats()["puts"] == 1
    assert store.stats()["size"] == 1


# ---------------------------------------------------------------------------
# Acceptance: parse failures are durable queryable facts
# ---------------------------------------------------------------------------


def test_parse_failures_are_durable_queryable_facts() -> None:
    provenance = SourceProvenance(
        source_cid=cid_for_bytes(b"def broken(:\n"),
        path="src/broken.py",
        repository_id="repository:example",
        revision="deadbeef",
        repository_tree_cid=None,
    )
    failure_span = span(4, 5, 1)
    store = build_duckdb_ast_store()
    projection = store.put_parse_failure(
        provenance=provenance,
        language="python",
        message="SyntaxError at line 1: invalid syntax",
        span=failure_span,
        created_at=99.0,
        frontend_name="cpython-ast",
        frontend_version="3.12.4",
    )

    assert projection.ast_blob.parse_status == ParseStatus.FAILED.value
    assert projection.ast_blob.parse_error
    assert projection.diagnostics
    assert all(item.is_parse_failure for item in projection.diagnostics)
    assert projection.diagnostics[0].code == PARSE_FAILURE_DIAGNOSTIC_CODE
    assert projection.diagnostics[0].span.matches(failure_span)
    assert projection.invalidations
    assert projection.invalidations[0].reason == "parse_failure"

    failures = store.query_parse_failures()
    assert len(failures) == 1
    assert failures[0].message == "SyntaxError at line 1: invalid syntax"
    assert failures[0].is_parse_failure is True

    by_path = store.query_parse_failures(path="src/broken.py")
    assert len(by_path) == 1
    by_revision = store.query_parse_failures(
        revision_id=projection.source_revision.revision_id
    )
    assert len(by_revision) == 1
    assert store.query_parse_failures(path="missing.py") == ()

    # Diagnostics API can filter to parse failures only.
    diags = store.query_diagnostics(parse_failures_only=True)
    assert len(diags) == 1
    assert diags[0].severity in {"error", "fatal", "warning", "info"}

    summary = projection.to_supervisor_blob_summary()
    assert summary["parse_error"]
    assert summary["qualified_symbols"] == []


def test_successful_projection_and_parse_failure_coexist() -> None:
    store = build_duckdb_ast_store()
    ok = store.put(complete_record(), created_at=1.0)
    store.put_parse_failure(
        provenance=SourceProvenance(
            source_cid=cid_for_bytes(b"not python"),
            path="src/bad.py",
            repository_id="repository:example",
            revision="0123456789abcdef",
        ),
        language="python",
        message="parse failed",
        created_at=2.0,
    )

    assert store.stats()["puts"] == 2
    assert store.stats()["parse_failures"] == 1
    assert len(store.query_parse_failures()) == 1
    assert len(store.query_diagnostics(blob_id=ok.blob_id)) == 1
    assert store.query_diagnostics(blob_id=ok.blob_id)[0].is_parse_failure is False


# ---------------------------------------------------------------------------
# Invalidations and supersession
# ---------------------------------------------------------------------------


def test_invalidate_is_queryable_and_removes_blob() -> None:
    store = build_duckdb_ast_store()
    stored = store.put(complete_record(), created_at=1.0)
    row = store.invalidate(
        blob_id=stored.blob_id,
        file_id=stored.source_file.file_id,
        revision_id=stored.source_revision.revision_id,
        reason="source_changed",
        actor_id="ingest",
        detail="blob bytes changed",
        created_at=3.0,
    )
    assert row.reason == "source_changed"
    assert store.get(stored.blob_id) is None
    invalidations = store.list_invalidations(blob_id=stored.blob_id)
    assert len(invalidations) == 1
    assert invalidations[0].detail == "blob bytes changed"


def test_replacing_same_file_records_blob_replaced_invalidation() -> None:
    store = build_duckdb_ast_store()
    first = complete_record()
    store.put(first, created_at=1.0)

    # Same path/revision, different source bytes => different AST CID.
    second_source = SOURCE + b"\n# trailing\n"
    second = ASTRecord(
        provenance=SourceProvenance(
            source_cid=cid_for_bytes(second_source),
            path=first.provenance.path,
            repository_id=first.provenance.repository_id,
            revision=first.provenance.revision,
            repository_tree_cid=first.provenance.repository_tree_cid,
        ),
        frontend=first.frontend,
        module=first.module,
        scopes=first.scopes,
        symbols=first.symbols,
        imports=first.imports,
        references=first.references,
        calls=first.calls,
        effects=first.effects,
        diagnostics=first.diagnostics,
        unsupported=first.unsupported,
    )
    stored_second = store.put(second, created_at=2.0)
    assert stored_second.ast_cid != first.cid
    reasons = {item.reason for item in store.list_invalidations()}
    assert "blob_replaced" in reasons
    assert store.get_by_file_id(stored_second.source_file.file_id) is stored_second


# ---------------------------------------------------------------------------
# Optional DuckDB persistence
# ---------------------------------------------------------------------------


def test_optional_duckdb_schema_install_and_persist() -> None:
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(database=":memory:")
    store = build_duckdb_ast_store(connection=connection)
    record = complete_record()
    projection = store.put(record, created_at=1.0)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert set(ASTS_CATALOG_TABLES).issubset(tables)

    blob_rows = connection.execute(
        "SELECT ast_cid, source_cid, parse_status FROM ast_blobs"
    ).fetchall()
    assert blob_rows == [
        (record.cid, record.provenance.source_cid, ParseStatus.OK.value)
    ]
    symbol_rows = connection.execute(
        "SELECT symbol_id, start_byte, end_byte, start_line, end_line "
        "FROM symbols"
    ).fetchall()
    assert len(symbol_rows) == 1
    assert symbol_rows[0][0] == "symbol:fetch:0"
    assert symbol_rows[0][1] == record.symbols[0].span.start_byte
    assert symbol_rows[0][2] == record.symbols[0].span.end_byte

    store.put_parse_failure(
        provenance=SourceProvenance(
            source_cid=cid_for_bytes(b"broken"),
            path="src/broken.py",
            repository_id="repository:example",
            revision="rev2",
        ),
        language="python",
        message="boom",
        created_at=2.0,
    )
    failures = connection.execute(
        "SELECT code, is_parse_failure, message FROM diagnostics "
        "WHERE is_parse_failure = TRUE"
    ).fetchall()
    assert len(failures) == 1
    assert failures[0][0] == PARSE_FAILURE_DIAGNOSTIC_CODE
    assert failures[0][1] is True

    # Identity columns still present after dual write.
    assert projection.ast_cid == record.cid


def test_project_ast_record_rejects_non_ast_record() -> None:
    with pytest.raises(DuckDBASTStoreError, match="exact ASTRecord"):
        project_ast_record({"not": "a record"})  # type: ignore[arg-type]


def test_project_parse_failure_rejects_non_provenance() -> None:
    with pytest.raises(DuckDBASTStoreError, match="SourceProvenance"):
        project_parse_failure(
            provenance={"path": "x"},  # type: ignore[arg-type]
            language="python",
            message="nope",
        )
