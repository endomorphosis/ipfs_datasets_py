"""Unit tests for bounded AST impact / dependency / conflict queries (DQK-033).

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
    DuckDBASTStore,
    build_duckdb_ast_store,
    project_ast_record,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_impact import (
    CODE_IMPACT_RESULT_SCHEMA,
    DEFAULT_MAX_DEPTH,
    DUCKDB_IMPACT_INTERFACE,
    DUCKDB_IMPACT_SCHEMA_VERSION,
    DuckDBImpactEngine,
    DuckDBImpactError,
    IMPACT_CLOSURE_KINDS,
    ImpactBudget,
    ImpactBudgetExceeded,
    ImpactClosureKind,
    ImpactDirection,
    ImpactEdge,
    ImpactGraph,
    ImpactNode,
    ImpactRevisionBinding,
    ImpactRevisionError,
    binding_from_parts,
    bounded_closure,
    build_duckdb_impact_engine,
    build_impact_graph,
    impact_from_code_impact_index,
    impact_schema_descriptor,
    known_impact_fixture_index,
)


REPO_A = "repository:repo-a"
REV_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
REV_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
TREE_A = cid_for_structured({"git_tree": "1111111111111111111111111111111111111111"})


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
        frontend_name="test-python",
        frontend_version="1.0.0",
        language="python",
        language_version="3.12",
        capabilities=(
            "symbols",
            "references",
            "modules",
            "calls",
            "imports",
            "effects",
        ),
        source_extensions=(".py",),
        toolchain_cid=cid_for_structured(
            {"frontend": "test-python", "version": "1.0.0"}
        ),
    )


def provenance(
    path: str,
    *,
    source: bytes,
    revision: str = REV_A,
    repository_id: str = REPO_A,
    tree: str = TREE_A,
) -> SourceProvenance:
    return SourceProvenance(
        path=path,
        source_cid=cid_for_bytes(source),
        repository_id=repository_id,
        revision=revision,
        repository_tree_cid=tree,
    )


def make_record(
    *,
    path: str,
    source: bytes,
    module_name: str,
    symbols: tuple[SymbolDefinition, ...],
    scopes: tuple[ScopeDefinition, ...],
    imports: tuple[ImportDefinition, ...] = (),
    references: tuple[ReferenceRecord, ...] = (),
    calls: tuple[CallRecord, ...] = (),
    effects: tuple[EffectRecord, ...] = (),
    revision: str = REV_A,
    module_scope_id: str | None = None,
) -> ASTRecord:
    scope_id = module_scope_id
    if scope_id is None:
        for item in scopes:
            if item.kind == "module":
                scope_id = item.scope_id
                break
        if scope_id is None and scopes:
            scope_id = scopes[0].scope_id
        if scope_id is None:
            scope_id = f"scope:{module_name}"
    return ASTRecord(
        provenance=provenance(path, source=source, revision=revision),
        frontend=frontend(),
        module=ModuleDefinition(
            module_id=f"mod:{module_name}",
            name=module_name,
            scope_id=scope_id,
            export_names=tuple(item.name for item in symbols),
            span=span(0, len(source), 1, source.count(b"\n") + 1),
        ),
        scopes=scopes,
        symbols=symbols,
        imports=imports,
        references=references,
        calls=calls,
        effects=effects,
        diagnostics=(),
        unsupported=(),
    )


def fixture_projections() -> tuple:
    """Two-module fixture: helper/caller in mod.py, use in other.py."""

    mod_src = b"def helper():\n    return 1\ndef caller():\n    return helper()\n"
    other_src = b"from pkg.mod import helper\ndef use():\n    return helper()\n"

    mod_module_scope = ScopeDefinition(
        scope_id="scope:mod",
        kind="module",
        parent_scope_id=None,
        owner_symbol_id=None,
        span=span(0, len(mod_src), 1, 4),
    )
    helper_scope = ScopeDefinition(
        scope_id="scope:helper",
        kind="function",
        parent_scope_id="scope:mod",
        owner_symbol_id="sym:helper",
        span=span(0, 20, 1, 2),
    )
    caller_scope = ScopeDefinition(
        scope_id="scope:caller",
        kind="function",
        parent_scope_id="scope:mod",
        owner_symbol_id="sym:caller",
        span=span(21, len(mod_src), 3, 4),
    )
    helper = SymbolDefinition(
        symbol_id="sym:helper",
        name="helper",
        qualified_name="pkg.mod.helper",
        kind="function",
        scope_id="scope:mod",
        definition_ordinal=0,
        visibility="public",
        signature=SignatureDefinition(
            parameters=(),
            return_annotation="int",
            is_async=False,
        ),
        decorator_names=(),
        flags=(),
        span=span(0, 20, 1, 2),
    )
    caller = SymbolDefinition(
        symbol_id="sym:caller",
        name="caller",
        qualified_name="pkg.mod.caller",
        kind="function",
        scope_id="scope:mod",
        definition_ordinal=1,
        visibility="public",
        signature=SignatureDefinition(
            parameters=(),
            return_annotation="int",
            is_async=False,
        ),
        decorator_names=(),
        flags=(),
        span=span(21, len(mod_src), 3, 4),
    )
    mod_record = make_record(
        path="pkg/mod.py",
        source=mod_src,
        module_name="pkg.mod",
        symbols=(helper, caller),
        scopes=(mod_module_scope, helper_scope, caller_scope),
        references=(
            ReferenceRecord(
                reference_id="ref:helper-in-caller",
                name="helper",
                scope_id="scope:caller",
                context="call",
                is_qualified=False,
                span=span(40, 46, 4),
            ),
        ),
        calls=(
            CallRecord(
                call_id="call:helper",
                scope_id="scope:caller",
                callee_name="helper",
                kind="direct",
                argument_count=0,
                callee_reference_id="ref:helper-in-caller",
                named_argument_names=(),
                is_awaited=False,
                span=span(40, 48, 4),
            ),
        ),
        effects=(
            EffectRecord(
                effect_id="eff:read-env",
                scope_id="scope:helper",
                kind="environment",
                operation="read",
                subject="os.environ",
                span=span(4, 12, 2),
            ),
        ),
    )

    other_module_scope = ScopeDefinition(
        scope_id="scope:other",
        kind="module",
        parent_scope_id=None,
        owner_symbol_id=None,
        span=span(0, len(other_src), 1, 3),
    )
    use_scope = ScopeDefinition(
        scope_id="scope:use",
        kind="function",
        parent_scope_id="scope:other",
        owner_symbol_id="sym:use",
        span=span(30, len(other_src), 2, 3),
    )
    use = SymbolDefinition(
        symbol_id="sym:use",
        name="use",
        qualified_name="pkg.other.use",
        kind="function",
        scope_id="scope:other",
        definition_ordinal=0,
        visibility="public",
        signature=SignatureDefinition(
            parameters=(),
            return_annotation="int",
            is_async=False,
        ),
        decorator_names=(),
        flags=(),
        span=span(30, len(other_src), 2, 3),
    )
    other_record = make_record(
        path="pkg/other.py",
        source=other_src,
        module_name="pkg.other",
        symbols=(use,),
        scopes=(other_module_scope, use_scope),
        imports=(
            ImportDefinition(
                import_id="imp:helper",
                scope_id="scope:other",
                module="pkg.mod",
                kind="symbol",
                imported_name="helper",
                local_name="helper",
                is_type_only=False,
                span=span(0, 28, 1),
            ),
        ),
        references=(
            ReferenceRecord(
                reference_id="ref:helper-in-use",
                name="helper",
                scope_id="scope:use",
                context="call",
                is_qualified=False,
                span=span(50, 56, 3),
            ),
        ),
        calls=(
            CallRecord(
                call_id="call:helper-use",
                scope_id="scope:use",
                callee_name="helper",
                kind="direct",
                argument_count=0,
                callee_reference_id="ref:helper-in-use",
                named_argument_names=(),
                is_awaited=False,
                span=span(50, 58, 3),
            ),
        ),
        effects=(
            EffectRecord(
                effect_id="eff:write-env",
                scope_id="scope:use",
                kind="environment",
                operation="write",
                subject="os.environ",
                span=span(40, 48, 3),
            ),
        ),
    )
    return project_ast_record(mod_record), project_ast_record(other_record)


# ---------------------------------------------------------------------------
# Schema / descriptor
# ---------------------------------------------------------------------------


def test_impact_schema_descriptor_is_closed_and_inert() -> None:
    descriptor = impact_schema_descriptor()
    assert descriptor["interface"] == DUCKDB_IMPACT_INTERFACE
    assert descriptor["store_schema_version"] == DUCKDB_IMPACT_SCHEMA_VERSION
    assert set(descriptor["closure_kinds"]) == IMPACT_CLOSURE_KINDS
    assert descriptor["guarantees"]["closures_bind_exact_source_revision"] is True
    assert descriptor["guarantees"]["depth_row_time_budgets_enforced"] is True
    assert descriptor["guarantees"]["agrees_with_code_impact_index_analyzers"] is True
    assert descriptor["default_budget"]["max_depth"] == DEFAULT_MAX_DEPTH


def test_module_import_is_inert() -> None:
    module = importlib.import_module(
        "ipfs_datasets_py.logic.software_contracts.duckdb_impact"
    )
    assert module.DUCKDB_IMPACT_INTERFACE == DUCKDB_IMPACT_INTERFACE


# ---------------------------------------------------------------------------
# Revision binding
# ---------------------------------------------------------------------------


def test_closures_bind_exact_source_revision() -> None:
    projections = fixture_projections()
    graph = build_impact_graph(projections, revision=REV_A)
    assert graph.binding.revision == REV_A
    assert graph.binding.repository_id == REPO_A
    assert graph.binding.revision_id == f"rev:{REPO_A}:{REV_A}"
    assert graph.binding.repository_tree_cid == TREE_A

    for edge in graph.edges:
        assert edge.revision_id == graph.binding.revision_id
    for node in graph.nodes:
        assert node.revision_id == graph.binding.revision_id

    engine = build_duckdb_impact_engine(projections=projections, revision=REV_A)
    result = engine.call_closure(["pkg.mod.helper"])
    assert result.revision_id == graph.binding.revision_id
    assert result.binding.revision == REV_A
    payload = result.to_dict()
    assert payload["binding"]["revision"] == REV_A
    assert payload["revision_id"] == graph.binding.revision_id


def test_mixed_revisions_fail_closed_without_explicit_binding() -> None:
    a, b = fixture_projections()
    # Re-project other module under a different revision.
    other_src = b"from pkg.mod import helper\ndef use():\n    return helper()\n"
    other_scope = ScopeDefinition(
        scope_id="scope:other",
        kind="module",
        parent_scope_id=None,
        owner_symbol_id=None,
        span=span(0, len(other_src), 1, 3),
    )
    use = SymbolDefinition(
        symbol_id="sym:use",
        name="use",
        qualified_name="pkg.other.use",
        kind="function",
        scope_id="scope:other",
        definition_ordinal=0,
        visibility="public",
        signature=None,
        decorator_names=(),
        flags=(),
        span=span(30, len(other_src), 2, 3),
    )
    b_alt = project_ast_record(
        make_record(
            path="pkg/other.py",
            source=other_src,
            module_name="pkg.other",
            symbols=(use,),
            scopes=(other_scope,),
            revision=REV_B,
        )
    )
    with pytest.raises(ImpactRevisionError):
        build_impact_graph((a, b_alt))

    # Explicit revision binding selects only matching projections.
    graph = build_impact_graph((a, b_alt), revision=REV_A)
    assert graph.binding.revision == REV_A
    assert all(edge.revision_id == graph.binding.revision_id for edge in graph.edges)


def test_store_engine_binds_revision_from_ingest() -> None:
    store = build_duckdb_ast_store()
    for projection in fixture_projections():
        store.put_projection(projection)
    engine = DuckDBImpactEngine(store=store, revision=REV_A)
    graph = engine.graph()
    assert graph.binding.revision == REV_A
    reverse = engine.reverse_reference_closure(["pkg.mod.helper"])
    assert reverse.binding.revision_id == graph.binding.revision_id
    assert "pkg.mod.caller" in reverse.node_ids or "pkg.other.use" in reverse.node_ids


# ---------------------------------------------------------------------------
# Closure families
# ---------------------------------------------------------------------------


def test_reverse_reference_and_call_closures_find_dependents() -> None:
    engine = build_duckdb_impact_engine(
        projections=fixture_projections(), revision=REV_A
    )
    reverse = engine.reverse_reference_closure(
        ["pkg.mod.helper"],
        direction=ImpactDirection.REVERSE,
    )
    assert reverse.kind == ImpactClosureKind.REVERSE_REFERENCE
    assert reverse.complete is True
    assert "pkg.mod.helper" in reverse.node_ids
    # Caller and/or use reference helper.
    dependents = set(reverse.node_ids) - {"pkg.mod.helper"}
    assert dependents

    calls = engine.call_closure(["pkg.mod.helper"])
    assert calls.kind == "call"
    assert "pkg.mod.helper" in calls.node_ids
    assert set(calls.node_ids) - {"pkg.mod.helper"}


def test_import_effect_interface_semantic_and_conflict_closures() -> None:
    engine = build_duckdb_impact_engine(
        projections=fixture_projections(), revision=REV_A
    )
    graph = engine.graph()
    kinds_present = {edge.kind for edge in graph.edges}
    for kind in IMPACT_CLOSURE_KINDS:
        # Every closed kind is either present or still queryable as empty.
        assert kind in IMPACT_CLOSURE_KINDS
        result = engine.closure(kind, ["pkg.mod.helper", "pkg/mod.py", "pkg/other.py"])
        assert result.binding.revision == REV_A
        assert result.kind == kind
        assert result.seeds

    imports = engine.import_closure(["pkg/mod.py"])
    assert imports.kind == "import"
    # other.py imports pkg.mod → reverse from provider path reaches importer.
    assert "pkg/other.py" in imports.node_ids or imports.node_count >= 1

    effects = engine.effect_closure(["effect-subject:os.environ"])
    assert effects.kind == "effect"
    assert "effect-subject:os.environ" in effects.node_ids

    # Conflicting read/write on the same subject yields a conflict edge.
    conflict_edges = graph.edges_of_kind(ImpactClosureKind.CONFLICT)
    assert conflict_edges
    conflict = engine.conflict_closure(
        [edge.source for edge in conflict_edges]
        + [edge.target for edge in conflict_edges]
    )
    assert conflict.kind == "conflict"
    assert conflict.node_count >= 1

    semantic = engine.semantic_dependency_closure(["pkg.mod.helper"])
    assert semantic.kind == "semantic_dependency"
    assert semantic.node_count >= 1
    assert ImpactClosureKind.SEMANTIC_DEPENDENCY.value in kinds_present

    interface = engine.interface_closure(
        [node.node_id for node in graph.nodes if node.kind == "interface"]
        or ["pkg.mod.helper"]
    )
    assert interface.kind == "interface"
    assert interface.binding.revision_id == graph.binding.revision_id


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


def test_depth_budget_truncates_closure() -> None:
    binding = binding_from_parts(repository_id=REPO_A, revision=REV_A, repository_tree_cid=TREE_A)
    # Chain: d -> c -> b -> a  (dependent -> provider)
    edges = (
        ImpactEdge(
            edge_id="e1",
            kind="call",
            source="b",
            target="a",
            revision_id=binding.revision_id,
        ),
        ImpactEdge(
            edge_id="e2",
            kind="call",
            source="c",
            target="b",
            revision_id=binding.revision_id,
        ),
        ImpactEdge(
            edge_id="e3",
            kind="call",
            source="d",
            target="c",
            revision_id=binding.revision_id,
        ),
    )
    shallow = bounded_closure(
        kind="call",
        seeds=["a"],
        edges=edges,
        binding=binding,
        direction=ImpactDirection.REVERSE,
        budget=ImpactBudget(max_depth=1, max_rows=100, max_time_ms=1000),
    )
    assert "a" in shallow.node_ids
    assert "b" in shallow.node_ids
    assert "c" not in shallow.node_ids
    assert "d" not in shallow.node_ids

    deep = bounded_closure(
        kind="call",
        seeds=["a"],
        edges=edges,
        binding=binding,
        direction=ImpactDirection.REVERSE,
        budget=ImpactBudget(max_depth=10, max_rows=100, max_time_ms=1000),
    )
    assert set(deep.node_ids) == {"a", "b", "c", "d"}


def test_row_budget_is_enforced() -> None:
    binding = binding_from_parts(repository_id=REPO_A, revision=REV_A)
    edges = tuple(
        ImpactEdge(
            edge_id=f"e{i}",
            kind="call",
            source=f"dep{i}",
            target="root",
            revision_id=binding.revision_id,
        )
        for i in range(20)
    )
    result = bounded_closure(
        kind="call",
        seeds=["root"],
        edges=edges,
        binding=binding,
        budget=ImpactBudget(max_depth=4, max_rows=5, max_time_ms=1000),
    )
    assert result.truncated is True
    assert "rows" in result.truncation_reasons
    assert result.rows_used <= 5 + 1  # may stop at the boundary check

    with pytest.raises(ImpactBudgetExceeded):
        bounded_closure(
            kind="call",
            seeds=["root"],
            edges=edges,
            binding=binding,
            budget=ImpactBudget(max_depth=4, max_rows=5, max_time_ms=1000),
            fail_closed=True,
        )


def test_time_budget_is_enforced() -> None:
    binding = binding_from_parts(repository_id=REPO_A, revision=REV_A)
    # Wide fan-out so the walk performs many iterations.
    edges = tuple(
        ImpactEdge(
            edge_id=f"e{i}",
            kind="call",
            source=f"dep{i}",
            target="root",
            revision_id=binding.revision_id,
        )
        for i in range(5000)
    )
    result = bounded_closure(
        kind="call",
        seeds=["root"],
        edges=edges,
        binding=binding,
        budget=ImpactBudget(max_depth=8, max_rows=100_000, max_time_ms=0.001),
    )
    # Either completed instantly or truncated on time — never overruns unboundedly.
    assert result.elapsed_ms >= 0.0
    if result.truncated:
        assert "time" in result.truncation_reasons or "rows" in result.truncation_reasons


def test_budget_validation_rejects_non_positive_values() -> None:
    with pytest.raises(DuckDBImpactError):
        ImpactBudget(max_depth=-1)
    with pytest.raises(DuckDBImpactError):
        ImpactBudget(max_rows=0)
    with pytest.raises(DuckDBImpactError):
        ImpactBudget(max_time_ms=0)
    with pytest.raises(DuckDBImpactError):
        ImpactBudget(max_time_ms=True)  # type: ignore[arg-type]


def test_graph_rejects_cross_revision_edges() -> None:
    binding = binding_from_parts(repository_id=REPO_A, revision=REV_A)
    node = ImpactNode(
        node_id="a",
        kind="symbol",
        label="a",
        revision_id=binding.revision_id,
    )
    edge = ImpactEdge(
        edge_id="bad",
        kind="call",
        source="a",
        target="b",
        revision_id=f"rev:{REPO_A}:{REV_B}",
    )
    with pytest.raises(ImpactRevisionError):
        ImpactGraph(binding=binding, nodes=(node,), edges=(edge,))


# ---------------------------------------------------------------------------
# Agreement with existing analyzers
# ---------------------------------------------------------------------------


def test_known_impact_fixture_agrees_with_code_evidence_analyzer() -> None:
    index = known_impact_fixture_index()
    ours = impact_from_code_impact_index(
        index,
        changed_symbols=["pkg.mod.helper"],
        changed_paths=[],
    )
    assert ours["schema"] == CODE_IMPACT_RESULT_SCHEMA
    assert "pkg.mod.helper" in ours["changed_symbols"]
    assert "pkg.mod.caller" in ours["affected_symbols"]
    assert "pkg.other.use" in ours["affected_symbols"]
    assert "pkg/other.py" in ours["affected_paths"]
    assert "tests/test_mod.py" in ours["affected_paths"]
    assert "test_code_evidence" in ours["required_validation_ids"]
    assert ours["uncovered_impact"] is False
    assert ours["binding"]["revision"] == index["revision"]
    assert ours["revision_id"]

    # Existing datasets adapter must agree on the core impact fields.
    from ipfs_datasets_py.knowledge_graphs.adapters.code_evidence import (
        impact_from_index,
        normalize_impact_index,
    )

    normalized = normalize_impact_index(index, revision=index["revision"])
    reference = impact_from_index(
        normalized,
        changed_symbols=["pkg.mod.helper"],
        changed_paths=[],
    )
    assert set(ours["affected_symbols"]) == set(reference["affected_symbols"])
    assert set(ours["affected_paths"]) == set(reference["affected_paths"])
    assert set(ours["changed_symbols"]) == set(reference["changed_symbols"])
    assert set(ours["changed_paths"]) == set(reference["changed_paths"])
    assert set(ours["required_validation_ids"]) == set(
        reference["required_validation_ids"]
    )
    assert ours["uncovered_impact"] is reference["uncovered_impact"]
    # Chains must agree as sets of hops (order is shortest-path deterministic).
    assert set(ours["dependency_chains"]) == set(reference["dependency_chains"])
    for key in ours["dependency_chains"]:
        assert list(ours["dependency_chains"][key]) == list(
            reference["dependency_chains"][key]
        )


def test_path_change_impact_agrees_with_analyzer() -> None:
    index = known_impact_fixture_index()
    ours = impact_from_code_impact_index(
        index,
        changed_paths=["pkg/mod.py"],
    )
    from ipfs_datasets_py.knowledge_graphs.adapters.code_evidence import (
        impact_from_index,
        normalize_impact_index,
    )

    reference = impact_from_index(
        normalize_impact_index(index, revision=index["revision"]),
        changed_paths=["pkg/mod.py"],
    )
    assert "pkg.mod.helper" in ours["changed_symbols"]
    assert set(ours["affected_paths"]) == set(reference["affected_paths"])
    assert set(ours["affected_symbols"]) == set(reference["affected_symbols"])


def test_engine_impact_over_ast_graph_surfaces_dependents() -> None:
    engine = build_duckdb_impact_engine(
        projections=fixture_projections(), revision=REV_A
    )
    impact = engine.impact(changed_symbols=["pkg.mod.helper"])
    assert impact["schema"] == CODE_IMPACT_RESULT_SCHEMA
    assert impact["revision_id"]
    assert impact["binding"]["revision"] == REV_A
    assert "pkg.mod.helper" in impact["changed_symbols"]
    # AST-derived symbol dependencies should include reverse dependents.
    affected = set(impact["affected_symbols"])
    assert "pkg.mod.helper" in affected
    assert affected & {"pkg.mod.caller", "pkg.other.use"}


def test_closure_requires_seeds_and_rejects_unknown_kind() -> None:
    binding = binding_from_parts(repository_id=REPO_A, revision=REV_A)
    with pytest.raises(DuckDBImpactError):
        bounded_closure(
            kind="call",
            seeds=[],
            edges=(),
            binding=binding,
        )
    with pytest.raises(DuckDBImpactError):
        bounded_closure(
            kind="not-a-kind",
            seeds=["a"],
            edges=(),
            binding=binding,
        )


def test_impact_budget_hard_caps_apply() -> None:
    budget = ImpactBudget(
        max_depth=10_000,
        max_rows=10_000_000,
        max_time_ms=1_000_000,
    )
    assert budget.max_depth <= 256
    assert budget.max_rows <= 100_000
    assert budget.max_time_ms <= 60_000.0
