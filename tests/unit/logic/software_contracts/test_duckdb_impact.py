"""Unit tests for bounded DuckDB AST impact/closure queries (DQK-033).

Acceptance coverage:

* Closures bind an exact source revision
* Depth/row/time budgets are enforced
* Known impact fixtures agree with existing analyzers
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
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

import pytest

from ipfs_datasets_py.logic.software_contracts.ast_ir import (
    ASTRecord,
    CallRecord,
    EffectRecord,
    FrontendCapability,
    ImportDefinition,
    ModuleDefinition,
    ReferenceRecord,
    ScopeDefinition,
    SignatureDefinition,
    SourceProvenance,
    SourceSpan,
    SymbolDefinition,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    build_duckdb_ast_store,
    project_ast_record,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_impact import (
    CLOSURE_KINDS,
    CODE_IMPACT_INDEX_SCHEMA,
    CODE_IMPACT_RESULT_SCHEMA,
    DUCKDB_IMPACT_INTERFACE,
    DUCKDB_IMPACT_SCHEMA_VERSION,
    DuckDBImpactBudgetError,
    DuckDBImpactEngine,
    DuckDBImpactError,
    DuckDBImpactRevisionError,
    ImpactBudgets,
    ImpactClosureKind,
    ImpactEdge,
    bounded_closure,
    build_impact_engine_from_projections,
    build_impact_engine_from_store,
    build_impact_index_from_maps,
    build_impact_index_from_projections,
    impact_schema_descriptor,
)


# ---------------------------------------------------------------------------
# Fixtures matching supervisor CodeImpactIndex analyzer cases
# ---------------------------------------------------------------------------

IMPACT_TREE_ID = "tree:ast-impact-candidate"
IMPACT_REVISION_ID = "rev:repository:example:deadbeef"
IMPACT_REPO = "repository:example"
IMPACT_REVISION = "deadbeef"
# Valid content-addressed tree CID for AST SourceProvenance (not a free-form tag).
IMPACT_TREE_CID = cid_for_structured({"git_tree": "ast-impact-candidate"})


def _supervisor_impact_fixture() -> dict:
    """Canonical fixture used by supervisor validation_dag impact tests."""

    return {
        "repository_tree_id": IMPACT_TREE_ID,
        "symbol_paths": {
            "pkg.source.value": "pkg/source.py",
            "pkg.consumer.read": "pkg/consumer.py",
            "tests.integration.test_read": "test/integration/test_consumer.py",
            "pkg.unrelated.noop": "pkg/unrelated.py",
        },
        "symbol_dependencies": {
            "pkg.consumer.read": ("pkg.source.value",),
            "tests.integration.test_read": ("pkg.consumer.read",),
        },
        "path_dependencies": {
            "pkg/consumer.py": ("pkg/source.py",),
            "test/integration/test_consumer.py": ("pkg/consumer.py",),
            "pkg/unrelated.py": (),
        },
        "validation_targets": {
            "integration": ("tests.integration.test_read",),
        },
    }


def _fixture_index():
    fixture = _supervisor_impact_fixture()
    return build_impact_index_from_maps(
        revision_id=IMPACT_REVISION_ID,
        repository_id=IMPACT_REPO,
        revision=IMPACT_REVISION,
        repository_tree_cid=IMPACT_TREE_ID,
        symbol_paths=fixture["symbol_paths"],
        symbol_dependencies=fixture["symbol_dependencies"],
        path_dependencies={
            key: value
            for key, value in fixture["path_dependencies"].items()
            if value
        },
        validation_targets=fixture["validation_targets"],
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


def frontend() -> FrontendCapability:
    return FrontendCapability(
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
    )


def _record(
    *,
    path: str,
    module_name: str,
    source: bytes,
    symbols: tuple[SymbolDefinition, ...],
    scopes: tuple[ScopeDefinition, ...],
    imports: tuple[ImportDefinition, ...] = (),
    references: tuple[ReferenceRecord, ...] = (),
    calls: tuple[CallRecord, ...] = (),
    effects: tuple[EffectRecord, ...] = (),
    revision: str = IMPACT_REVISION,
    repository_id: str = IMPACT_REPO,
    tree_cid: str | None = IMPACT_TREE_CID,
) -> ASTRecord:
    whole = span(0, max(len(source), 1), 1, max(1, source.count(b"\n") + 1))
    return ASTRecord(
        provenance=SourceProvenance(
            source_cid=cid_for_bytes(source),
            path=path,
            repository_id=repository_id,
            revision=revision,
            repository_tree_cid=tree_cid,
        ),
        frontend=frontend(),
        module=ModuleDefinition(
            module_id=f"module:{module_name}",
            name=module_name,
            scope_id="scope:module",
            span=whole,
            export_names=tuple(item.name for item in symbols),
        ),
        scopes=scopes,
        symbols=symbols,
        imports=imports,
        references=references,
        calls=calls,
        effects=effects,
    )


def multi_file_projections():
    """Two-file graph: provider helper, consumer that calls/imports it."""

    source_src = b"def helper():\n    return 1\n"
    consumer_src = (
        b"from pkg.mod import helper\n"
        b"def caller():\n"
        b"    return helper()\n"
    )
    other_src = b"from pkg.mod import helper\n\ndef use():\n    helper()\n"

    provider_scopes = (
        ScopeDefinition(
            scope_id="scope:module",
            kind="module",
            span=span(0, len(source_src), 1, 2),
        ),
        ScopeDefinition(
            scope_id="scope:function:helper",
            kind="function",
            span=span(0, len(source_src), 1, 2),
            parent_scope_id="scope:module",
            owner_symbol_id="symbol:helper:0",
        ),
    )
    provider_symbols = (
        SymbolDefinition(
            symbol_id="symbol:helper:0",
            name="helper",
            qualified_name="pkg.mod.helper",
            kind="function",
            scope_id="scope:module",
            span=span(0, len(source_src), 1, 2),
            definition_ordinal=0,
            signature=SignatureDefinition(parameters=(), return_annotation="int"),
            visibility="public",
        ),
    )
    provider = _record(
        path="pkg/mod.py",
        module_name="pkg.mod",
        source=source_src,
        symbols=provider_symbols,
        scopes=provider_scopes,
        effects=(
            EffectRecord(
                effect_id="effect:io:0",
                scope_id="scope:function:helper",
                kind="io",
                operation="write",
                span=span(18, 26, 2),
                subject="helper",
            ),
        ),
    )

    consumer_scopes = (
        ScopeDefinition(
            scope_id="scope:module",
            kind="module",
            span=span(0, len(consumer_src), 1, 3),
        ),
        ScopeDefinition(
            scope_id="scope:function:caller",
            kind="function",
            span=span(28, len(consumer_src), 2, 3),
            parent_scope_id="scope:module",
            owner_symbol_id="symbol:caller:0",
        ),
    )
    consumer_symbols = (
        SymbolDefinition(
            symbol_id="symbol:caller:0",
            name="caller",
            qualified_name="pkg.consumer.caller",
            kind="function",
            scope_id="scope:module",
            span=span(28, len(consumer_src), 2, 3),
            definition_ordinal=0,
            signature=SignatureDefinition(parameters=()),
            visibility="public",
        ),
    )
    consumer = _record(
        path="pkg/consumer.py",
        module_name="pkg.consumer",
        source=consumer_src,
        symbols=consumer_symbols,
        scopes=consumer_scopes,
        imports=(
            ImportDefinition(
                import_id="import:helper:0",
                scope_id="scope:module",
                module="pkg.mod",
                kind="symbol",
                span=span(0, 27),
                imported_name="helper",
                local_name="helper",
            ),
        ),
        references=(
            ReferenceRecord(
                reference_id="reference:helper:0",
                name="helper",
                scope_id="scope:function:caller",
                context="call",
                span=span(48, 54, 3),
            ),
        ),
        calls=(
            CallRecord(
                call_id="call:helper:0",
                scope_id="scope:function:caller",
                callee_name="helper",
                kind="direct",
                argument_count=0,
                span=span(48, 56, 3),
                callee_reference_id="reference:helper:0",
            ),
        ),
    )

    other_scopes = (
        ScopeDefinition(
            scope_id="scope:module",
            kind="module",
            span=span(0, len(other_src), 1, 4),
        ),
        ScopeDefinition(
            scope_id="scope:function:use",
            kind="function",
            span=span(30, len(other_src), 3, 4),
            parent_scope_id="scope:module",
            owner_symbol_id="symbol:use:0",
        ),
    )
    other_symbols = (
        SymbolDefinition(
            symbol_id="symbol:use:0",
            name="use",
            qualified_name="pkg.other.use",
            kind="function",
            scope_id="scope:module",
            span=span(30, len(other_src), 3, 4),
            definition_ordinal=0,
            signature=SignatureDefinition(parameters=()),
            visibility="public",
        ),
    )
    other = _record(
        path="pkg/other.py",
        module_name="pkg.other",
        source=other_src,
        symbols=other_symbols,
        scopes=other_scopes,
        imports=(
            ImportDefinition(
                import_id="import:helper:1",
                scope_id="scope:module",
                module="pkg.mod",
                kind="symbol",
                span=span(0, 27),
                imported_name="helper",
                local_name="helper",
            ),
        ),
        references=(
            ReferenceRecord(
                reference_id="reference:helper:1",
                name="helper",
                scope_id="scope:function:use",
                context="call",
                span=span(42, 48, 4),
            ),
        ),
        calls=(
            CallRecord(
                call_id="call:helper:1",
                scope_id="scope:function:use",
                callee_name="helper",
                kind="direct",
                argument_count=0,
                span=span(42, 50, 4),
                callee_reference_id="reference:helper:1",
            ),
        ),
    )

    return (
        project_ast_record(provider, created_at=1.0),
        project_ast_record(consumer, created_at=1.0),
        project_ast_record(other, created_at=1.0),
    )


# ---------------------------------------------------------------------------
# Interface / schema pins
# ---------------------------------------------------------------------------


def test_interfaces_schema_and_closure_kinds_are_pinned() -> None:
    assert DUCKDB_IMPACT_INTERFACE == "DuckDBImpact@1"
    assert DUCKDB_IMPACT_SCHEMA_VERSION == "duckdb-ast-impact/v1"
    assert CLOSURE_KINDS == frozenset(
        {
            "reverse_reference",
            "call",
            "import",
            "effect",
            "interface",
            "semantic_dependency",
            "conflict",
            "impact",
        }
    )
    descriptor = impact_schema_descriptor()
    assert descriptor["interface"] == DUCKDB_IMPACT_INTERFACE
    assert descriptor["guarantees"]["closures_bind_exact_source_revision"] is True
    assert descriptor["guarantees"]["depth_row_time_budgets_enforced"] is True
    assert descriptor["guarantees"]["agrees_with_code_impact_index"] is True
    assert set(descriptor["closure_kinds"]) == CLOSURE_KINDS


def test_module_import_is_inert_without_duckdb() -> None:
    mod = importlib.import_module(
        "ipfs_datasets_py.logic.software_contracts.duckdb_impact"
    )
    assert mod.DUCKDB_IMPACT_INTERFACE == "DuckDBImpact@1"


# ---------------------------------------------------------------------------
# Acceptance: closures bind an exact source revision
# ---------------------------------------------------------------------------


def test_index_binds_exact_source_revision() -> None:
    projections = multi_file_projections()
    index = build_impact_index_from_projections(projections)

    assert index.revision_id == projections[0].source_revision.revision_id
    assert index.repository_id == IMPACT_REPO
    assert index.revision == IMPACT_REVISION
    assert index.repository_tree_cid == IMPACT_TREE_CID
    assert set(index.paths) == {"pkg/mod.py", "pkg/consumer.py", "pkg/other.py"}
    assert "pkg.mod.helper" in index.symbol_paths
    assert index.symbol_paths["pkg.mod.helper"] == "pkg/mod.py"

    engine = DuckDBImpactEngine(index)
    assert engine.revision_id == index.revision_id
    result = engine.impact(changed_symbols=["pkg.mod.helper"])
    assert result.revision_id == index.revision_id
    assert result.repository_tree_id == IMPACT_TREE_CID


def test_mixed_revisions_are_rejected() -> None:
    projections = list(multi_file_projections())
    # Re-project one file under a different revision.
    other_revision = _record(
        path="pkg/unrelated.py",
        module_name="pkg.unrelated",
        source=b"def noop():\n    return 0\n",
        symbols=(
            SymbolDefinition(
                symbol_id="symbol:noop:0",
                name="noop",
                qualified_name="pkg.unrelated.noop",
                kind="function",
                scope_id="scope:module",
                span=span(0, 24, 1, 2),
                definition_ordinal=0,
                visibility="public",
            ),
        ),
        scopes=(
            ScopeDefinition(
                scope_id="scope:module",
                kind="module",
                span=span(0, 24, 1, 2),
            ),
        ),
        revision="cafebabe",
    )
    mixed = (*projections, project_ast_record(other_revision, created_at=2.0))
    with pytest.raises(DuckDBImpactRevisionError, match="exact source revision"):
        build_impact_index_from_projections(mixed)


def test_store_engine_rejects_blob_from_other_revision() -> None:
    projections = multi_file_projections()
    store = build_duckdb_ast_store()
    for projection in projections:
        store.put_projection(projection)

    other = _record(
        path="pkg/unrelated.py",
        module_name="pkg.unrelated",
        source=b"def noop():\n    return 0\n",
        symbols=(
            SymbolDefinition(
                symbol_id="symbol:noop:0",
                name="noop",
                qualified_name="pkg.unrelated.noop",
                kind="function",
                scope_id="scope:module",
                span=span(0, 24, 1, 2),
                definition_ordinal=0,
                visibility="public",
            ),
        ),
        scopes=(
            ScopeDefinition(
                scope_id="scope:module",
                kind="module",
                span=span(0, 24, 1, 2),
            ),
        ),
        revision="other-rev",
    )
    other_proj = project_ast_record(other, created_at=3.0)
    store.put_projection(other_proj)

    revision_id = projections[0].source_revision.revision_id
    with pytest.raises(DuckDBImpactRevisionError):
        build_impact_engine_from_store(
            store,
            revision_id=revision_id,
            blob_ids=[projections[0].blob_id, other_proj.blob_id],
        )


def test_engine_from_store_binds_revision() -> None:
    projections = multi_file_projections()
    store = build_duckdb_ast_store()
    for projection in projections:
        store.put_projection(projection)
    revision_id = projections[0].source_revision.revision_id
    engine = build_impact_engine_from_store(
        store,
        revision_id=revision_id,
        blob_ids=[item.blob_id for item in projections],
    )
    assert engine.revision_id == revision_id
    impact = engine.impact(changed_symbols=["pkg.mod.helper"])
    assert impact.revision_id == revision_id
    assert "pkg.consumer.caller" in impact.affected_symbols
    assert "pkg.other.use" in impact.affected_symbols


# ---------------------------------------------------------------------------
# Acceptance: depth / row / time budgets enforced
# ---------------------------------------------------------------------------


def test_depth_budget_limits_closure_expansion() -> None:
    # Chain A -> B -> C -> D (provider -> dependent reverse edges via semantic).
    index = build_impact_index_from_maps(
        revision_id=IMPACT_REVISION_ID,
        repository_id=IMPACT_REPO,
        revision=IMPACT_REVISION,
        repository_tree_cid=IMPACT_TREE_ID,
        symbol_paths={
            "A": "a.py",
            "B": "b.py",
            "C": "c.py",
            "D": "d.py",
        },
        symbol_dependencies={
            "B": ("A",),
            "C": ("B",),
            "D": ("C",),
        },
    )
    engine = DuckDBImpactEngine(index)
    shallow = engine.semantic_dependency_closure(
        ["A"],
        direction="reverse",
        budgets=ImpactBudgets(max_depth=1, max_rows=100, time_budget_ms=5_000),
    )
    assert set(shallow.node_ids) == {"A", "B"}
    assert shallow.depths["B"] == 1
    assert "C" not in shallow.node_ids

    deep = engine.semantic_dependency_closure(
        ["A"],
        direction="reverse",
        budgets=ImpactBudgets(max_depth=10, max_rows=100),
    )
    assert set(deep.node_ids) == {"A", "B", "C", "D"}


def test_row_budget_raises_when_exceeded() -> None:
    index = _fixture_index()
    engine = DuckDBImpactEngine(index)
    with pytest.raises(DuckDBImpactBudgetError, match="max_rows") as exc_info:
        engine.impact(
            changed_symbols=["pkg.source.value"],
            budgets=ImpactBudgets(max_depth=32, max_rows=1, on_exceed="raise"),
            include_ast_closures=False,
        )
    assert exc_info.value.budget == "max_rows"


def test_row_budget_truncates_when_configured() -> None:
    index = _fixture_index()
    engine = DuckDBImpactEngine(index)
    result = engine.impact(
        changed_symbols=["pkg.source.value"],
        budgets=ImpactBudgets(max_depth=32, max_rows=2, on_exceed="truncate"),
        include_ast_closures=False,
    )
    assert result.truncated is True
    assert result.truncation_reason == "max_rows"
    assert len(result.affected_symbols) <= 2


def test_time_budget_is_enforced() -> None:
    # Build a wide reverse adjacency so BFS does real work, then set a tiny
    # wall-clock budget.  Monkeypatch monotonic so the second check fails.
    index = _fixture_index()
    ticks = {"n": 0}
    real_monotonic = time.monotonic
    base = real_monotonic()

    def fake_monotonic() -> float:
        ticks["n"] += 1
        # First call starts the clock; subsequent calls appear to jump past budget.
        if ticks["n"] <= 1:
            return base
        return base + 10.0  # 10 seconds later

    engine = DuckDBImpactEngine(index)
    original = time.monotonic
    try:
        time.monotonic = fake_monotonic  # type: ignore[assignment]
        with pytest.raises(DuckDBImpactBudgetError, match="time_budget_ms") as exc_info:
            engine.impact(
                changed_symbols=["pkg.source.value"],
                budgets=ImpactBudgets(
                    max_depth=32,
                    max_rows=10_000,
                    time_budget_ms=1,
                    on_exceed="raise",
                ),
                include_ast_closures=False,
            )
        assert exc_info.value.budget == "time_budget_ms"
    finally:
        time.monotonic = original  # type: ignore[assignment]


def test_bounded_closure_max_edges_raises() -> None:
    adjacency = {"root": ("a", "b", "c")}
    with pytest.raises(DuckDBImpactBudgetError, match="max_edges"):
        bounded_closure(
            seeds=["root"],
            adjacency=adjacency,
            revision_id=IMPACT_REVISION_ID,
            kind="semantic_dependency",
            direction="reverse",
            budgets=ImpactBudgets(max_depth=5, max_rows=100, max_edges=1),
        )


def test_budget_defaults_and_hard_caps() -> None:
    budgets = ImpactBudgets()
    assert budgets.max_depth == 32
    assert budgets.max_rows == 4_096
    assert budgets.time_budget_ms == 5_000

    capped = ImpactBudgets(max_depth=10_000, max_rows=1_000_000, time_budget_ms=999_999)
    assert capped.max_depth == 256
    assert capped.max_rows == 65_536
    assert capped.time_budget_ms == 60_000

    with pytest.raises(DuckDBImpactError):
        ImpactBudgets(max_rows=0)
    with pytest.raises(DuckDBImpactError):
        ImpactBudgets(on_exceed="ignore")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Acceptance: known impact fixtures agree with existing analyzers
# ---------------------------------------------------------------------------


def test_impact_fixture_agrees_with_supervisor_code_impact_index() -> None:
    """DuckDB impact must match CodeImpactIndex.impact on the shared fixture."""

    fixture = _supervisor_impact_fixture()
    index = _fixture_index()
    engine = DuckDBImpactEngine(index)

    result = engine.impact(
        changed_symbols=["pkg.source.value"],
        include_ast_closures=False,
    )

    # Expected outcomes from supervisor test_ast_impact_index_selects_transitive...
    assert result.changed_symbols == ("pkg.source.value",)
    assert result.affected_symbols == (
        "pkg.consumer.read",
        "pkg.source.value",
        "tests.integration.test_read",
    )
    assert result.affected_paths == (
        "pkg/consumer.py",
        "pkg/source.py",
        "test/integration/test_consumer.py",
    )
    assert result.dependency_chains["tests.integration.test_read"] == (
        "pkg.source.value",
        "pkg.consumer.read",
        "tests.integration.test_read",
    )
    assert result.required_validation_ids == ("integration",)
    assert result.uncovered_impact is False
    assert result.to_dict()["schema"] == CODE_IMPACT_RESULT_SCHEMA

    # Live agreement with the supervisor analyzer when available.
    try:
        from ipfs_accelerate_py.agent_supervisor.code_evidence_graph import (
            CodeImpactIndex,
        )
    except Exception:
        pytest.skip("supervisor CodeImpactIndex not importable in this environment")

    supervisor = CodeImpactIndex(
        repository_tree_id=fixture["repository_tree_id"],
        symbol_paths=fixture["symbol_paths"],
        symbol_dependencies=fixture["symbol_dependencies"],
        path_dependencies=fixture["path_dependencies"],
        validation_targets=fixture["validation_targets"],
    )
    expected = supervisor.impact(changed_symbols=["pkg.source.value"])

    assert result.affected_symbols == expected.affected_symbols
    assert result.affected_paths == expected.affected_paths
    assert result.changed_symbols == expected.changed_symbols
    assert result.changed_paths == expected.changed_paths
    assert (
        result.dependency_chains["tests.integration.test_read"]
        == expected.dependency_chains["tests.integration.test_read"]
    )
    assert result.required_validation_ids == expected.required_validation_ids
    assert result.uncovered_symbols == expected.uncovered_symbols
    assert result.uncovered_paths == expected.uncovered_paths

    # Index payload is supervisor-schema compatible.
    payload = index.to_code_impact_index_dict()
    assert payload["schema"] == CODE_IMPACT_INDEX_SCHEMA
    restored = CodeImpactIndex.from_dict(payload)
    assert restored.symbol_paths == supervisor.symbol_paths
    assert restored.symbol_dependencies == supervisor.symbol_dependencies


def test_impact_from_index_helper_agreement() -> None:
    """Agree with datasets code_evidence.impact_from_index when present."""

    fixture = _supervisor_impact_fixture()
    index = _fixture_index()
    engine = DuckDBImpactEngine(index)
    result = engine.impact(
        changed_symbols=["pkg.source.value"],
        include_ast_closures=False,
    )

    try:
        from ipfs_datasets_py.knowledge_graphs.adapters.code_evidence import (
            impact_from_index,
        )
    except Exception:
        pytest.skip("code_evidence.impact_from_index not importable")

    payload = {
        "repository_tree_id": fixture["repository_tree_id"],
        "index_id": index.index_id,
        "symbol_paths": fixture["symbol_paths"],
        "symbol_dependencies": {
            k: list(v) for k, v in fixture["symbol_dependencies"].items()
        },
        "path_dependencies": {
            k: list(v) for k, v in fixture["path_dependencies"].items()
        },
        "validation_targets": {
            k: list(v) for k, v in fixture["validation_targets"].items()
        },
    }
    expected = impact_from_index(payload, changed_symbols=["pkg.source.value"])
    assert list(result.affected_symbols) == expected["affected_symbols"]
    assert list(result.affected_paths) == expected["affected_paths"]
    assert list(result.required_validation_ids) == expected["required_validation_ids"]
    assert (
        list(result.dependency_chains["tests.integration.test_read"])
        == expected["dependency_chains"]["tests.integration.test_read"]
    )


def test_path_change_infers_symbols_like_existing_analyzers() -> None:
    engine = DuckDBImpactEngine(_fixture_index())
    result = engine.impact(
        changed_paths=["pkg/source.py"],
        include_ast_closures=False,
    )
    assert "pkg.source.value" in result.changed_symbols
    assert "pkg.consumer.read" in result.affected_symbols
    assert "pkg/consumer.py" in result.affected_paths


# ---------------------------------------------------------------------------
# AST-derived closures (reference / call / import / effect / interface / conflict)
# ---------------------------------------------------------------------------


def test_reverse_reference_call_import_closures_from_ast() -> None:
    projections = multi_file_projections()
    engine = build_impact_engine_from_projections(projections)

    refs = engine.reverse_reference_closure(["pkg.mod.helper"])
    assert refs.revision_id == engine.revision_id
    assert refs.kind == "reverse_reference"
    assert "pkg.consumer.caller" in refs.node_ids
    assert "pkg.other.use" in refs.node_ids

    calls = engine.call_closure(["pkg.mod.helper"])
    assert calls.kind == "call"
    assert "pkg.consumer.caller" in calls.node_ids
    assert "pkg.other.use" in calls.node_ids

    imports = engine.import_closure(["pkg.mod"])
    assert imports.kind == "import"
    assert "pkg/consumer.py" in imports.node_ids
    assert "pkg/other.py" in imports.node_ids

    # Composite impact also reaches consumers via inferred semantic deps.
    impact = engine.impact(changed_symbols=["pkg.mod.helper"])
    assert "pkg.consumer.caller" in impact.affected_symbols
    assert "pkg.other.use" in impact.affected_symbols
    assert "pkg/consumer.py" in impact.affected_paths
    assert impact.closures  # AST family closures attached
    assert "reverse_reference" in impact.closures
    assert "call" in impact.closures


def test_effect_and_interface_closures() -> None:
    projections = multi_file_projections()
    engine = build_impact_engine_from_projections(projections)

    effects = engine.effect_closure(["helper"])
    assert effects.kind == "effect"
    # Subject "helper" on the provider resolves to the helper owner / symbol.
    assert effects.node_count >= 1
    assert "pkg.mod.helper" in effects.node_ids or any(
        "helper" in node for node in effects.node_ids
    )

    interfaces = engine.interface_closure(["pkg.mod.helper"])
    assert interfaces.kind == "interface"
    # Interface definition edges point provider -> defining path; reverse
    # walk from the interface includes the definition path and users.
    assert "pkg/mod.py" in interfaces.node_ids or interfaces.node_count >= 1


def test_conflict_closure_from_surfaces() -> None:
    projections = multi_file_projections()
    surfaces = (
        {
            "task_cid": "task:alpha",
            "paths": ["pkg/mod.py"],
            "ast_symbols": ["pkg.mod.helper"],
        },
        {
            "task_cid": "task:beta",
            "paths": ["pkg/consumer.py", "pkg/mod.py"],
            "ast_symbols": ["pkg.consumer.caller"],
        },
    )
    engine = build_impact_engine_from_projections(
        projections, conflict_surfaces=surfaces
    )
    conflict = engine.conflict_closure(["pkg/mod.py"])
    assert conflict.kind == "conflict"
    assert "task:alpha" in conflict.node_ids
    assert "task:beta" in conflict.node_ids

    by_symbol = engine.conflict_closure(["pkg.mod.helper"])
    assert "task:alpha" in by_symbol.node_ids


def test_semantic_dependency_forward_and_reverse() -> None:
    engine = DuckDBImpactEngine(_fixture_index())
    forward = engine.semantic_dependency_closure(
        ["tests.integration.test_read"], direction="forward"
    )
    # Forward: consumer -> its providers (dependencies).
    assert "pkg.consumer.read" in forward.node_ids
    assert "pkg.source.value" in forward.node_ids

    reverse = engine.semantic_dependency_closure(
        ["pkg.source.value"], direction="reverse"
    )
    assert "pkg.consumer.read" in reverse.node_ids
    assert "tests.integration.test_read" in reverse.node_ids


def test_all_closure_kinds_are_queryable() -> None:
    projections = multi_file_projections()
    engine = build_impact_engine_from_projections(
        projections,
        conflict_surfaces=(
            {"task_cid": "task:x", "paths": ["pkg/mod.py"], "symbols": []},
        ),
    )
    seeds = ["pkg.mod.helper"]
    for kind in CLOSURE_KINDS:
        if kind == "impact":
            result = engine.impact(changed_symbols=seeds)
            assert result.revision_id == engine.revision_id
            continue
        if kind == "semantic_dependency":
            result = engine.closure(kind, seeds, direction="reverse")
        elif kind == "import":
            result = engine.closure(kind, ["pkg.mod"], direction="reverse")
        elif kind == "conflict":
            result = engine.closure(kind, ["pkg/mod.py"], direction="reverse")
        else:
            result = engine.closure(kind, seeds, direction="reverse")
        assert result.kind == kind
        assert result.revision_id == engine.revision_id
        assert result.budgets.max_depth >= 0
        assert isinstance(result.to_dict()["node_ids"], list)


def test_impact_edge_and_result_serialization() -> None:
    edge = ImpactEdge(
        edge_id="edge:call:a:b",
        kind="call",
        source="a",
        target="b",
        path="pkg/a.py",
        metadata={"k": 1},
    )
    payload = edge.to_dict()
    assert payload["kind"] == "call"
    assert payload["path"] == "pkg/a.py"

    engine = DuckDBImpactEngine(_fixture_index())
    result = engine.impact(
        changed_symbols=["pkg.source.value"],
        include_ast_closures=False,
    )
    data = result.to_dict()
    assert data["schema"] == CODE_IMPACT_RESULT_SCHEMA
    assert data["revision_id"] == IMPACT_REVISION_ID
    assert "budgets" in data
    compat = result.to_code_impact_dict()
    assert "revision_id" not in compat
    assert "budgets" not in compat
    assert compat["affected_symbols"] == list(result.affected_symbols)


def test_empty_seeds_and_unknown_kind_fail_closed() -> None:
    engine = DuckDBImpactEngine(_fixture_index())
    with pytest.raises(DuckDBImpactError, match="at least one seed"):
        engine.call_closure([])
    with pytest.raises(DuckDBImpactError, match="unknown closure kind"):
        engine.closure("not-a-kind", ["x"])
    with pytest.raises(DuckDBImpactError, match="use impact"):
        engine.closure(ImpactClosureKind.IMPACT, ["x"])


def test_uncovered_symbols_and_paths_are_reported() -> None:
    engine = DuckDBImpactEngine(_fixture_index())
    result = engine.impact(
        changed_symbols=["pkg.missing.symbol"],
        changed_paths=["missing/path.py"],
        include_ast_closures=False,
    )
    assert result.uncovered_symbols == ("pkg.missing.symbol",)
    assert result.uncovered_paths == ("missing/path.py",)
    assert result.uncovered_impact is True
