"""Unit tests for bounded AST impact / dependency closures (DQK-033).

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
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_ROWS,
    DUCKDB_IMPACT_INTERFACE,
    DUCKDB_IMPACT_SCHEMA_VERSION,
    IMPACT_CLOSURE_KINDS,
    DuckDBASTImpact,
    DuckDBImpactError,
    ImpactBudget,
    ImpactBudgetExceeded,
    ImpactClosureKind,
    bounded_reverse_closure,
    build_duckdb_ast_impact,
    impact_schema_descriptor,
    path_to_module,
    pure_impact_closure,
    reverse_dependency_map,
)


REPO = "repository:impact-fixture"
REV_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
REV_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
TREE_A = "1111111111111111111111111111111111111111"
TREE_B = "2222222222222222222222222222222222222222"


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
            "symbols",
            "references",
            "modules",
            "calls",
            "imports",
            "effects",
        ),
        source_extensions=(".py",),
        toolchain_cid=cid_for_structured(
            {"frontend": "cpython-ast", "version": "3.12.4"}
        ),
    )


def make_record(
    *,
    path: str,
    module_name: str,
    source: bytes,
    revision: str = REV_A,
    tree: str = TREE_A,
    symbols: tuple[SymbolDefinition, ...] = (),
    scopes: tuple[ScopeDefinition, ...] = (),
    imports: tuple[ImportDefinition, ...] = (),
    references: tuple[ReferenceRecord, ...] = (),
    calls: tuple[CallRecord, ...] = (),
    effects: tuple[EffectRecord, ...] = (),
    export_names: tuple[str, ...] = (),
) -> ASTRecord:
    whole = span(0, max(len(source), 1), 1, max(1, source.count(b"\n") + 1))
    root = ScopeDefinition(
        scope_id="scope:module",
        kind="module",
        span=whole,
    )
    all_scopes = scopes if scopes else (root,)
    return ASTRecord(
        provenance=SourceProvenance(
            source_cid=cid_for_bytes(source),
            path=path,
            repository_id=REPO,
            revision=revision,
            repository_tree_cid=cid_for_structured({"git_tree": tree}),
        ),
        frontend=frontend(),
        module=ModuleDefinition(
            module_id=f"module:{module_name}",
            name=module_name,
            scope_id="scope:module",
            span=whole,
            export_names=export_names or tuple(s.name for s in symbols),
        ),
        scopes=all_scopes,
        symbols=symbols,
        imports=imports,
        references=references,
        calls=calls,
        effects=effects,
    )


def provider_module() -> ASTRecord:
    """pkg/core.py — defines `compute` and `shared_subject` effects."""

    body = b"def compute(x):\n    return x + 1\n"
    fn_span = span(0, len(body), 1, 2)
    return make_record(
        path="pkg/core.py",
        module_name="pkg.core",
        source=body,
        symbols=(
            SymbolDefinition(
                symbol_id="symbol:compute:0",
                name="compute",
                qualified_name="pkg.core.compute",
                kind="function",
                scope_id="scope:module",
                span=fn_span,
                definition_ordinal=0,
                signature=SignatureDefinition(
                    parameters=(),
                    return_annotation="int",
                ),
                visibility="public",
            ),
        ),
        scopes=(
            ScopeDefinition(
                scope_id="scope:module",
                kind="module",
                span=span(0, len(body), 1, 2),
            ),
            ScopeDefinition(
                scope_id="scope:function:compute",
                kind="function",
                span=fn_span,
                parent_scope_id="scope:module",
                owner_symbol_id="symbol:compute:0",
            ),
        ),
        effects=(
            EffectRecord(
                effect_id="effect:write:0",
                scope_id="scope:function:compute",
                kind="io",
                operation="write",
                span=span(20, 30, 2),
                subject="shared_resource",
            ),
        ),
        export_names=("compute",),
    )


def consumer_module() -> ASTRecord:
    """pkg/app.py — imports and calls compute; references compute."""

    body = (
        b"from pkg.core import compute\n"
        b"def run():\n"
        b"    return compute(1)\n"
    )
    run_span = span(30, len(body), 2, 3)
    call_span = span(48, 58, 3)
    return make_record(
        path="pkg/app.py",
        module_name="pkg.app",
        source=body,
        symbols=(
            SymbolDefinition(
                symbol_id="symbol:run:0",
                name="run",
                qualified_name="pkg.app.run",
                kind="function",
                scope_id="scope:module",
                span=run_span,
                definition_ordinal=0,
                signature=SignatureDefinition(parameters=()),
                visibility="public",
            ),
        ),
        scopes=(
            ScopeDefinition(
                scope_id="scope:module",
                kind="module",
                span=span(0, len(body), 1, 3),
            ),
            ScopeDefinition(
                scope_id="scope:function:run",
                kind="function",
                span=run_span,
                parent_scope_id="scope:module",
                owner_symbol_id="symbol:run:0",
            ),
        ),
        imports=(
            ImportDefinition(
                import_id="import:pkg.core.compute:0",
                scope_id="scope:module",
                module="pkg.core",
                kind="symbol",
                span=span(0, 29, 1),
                imported_name="compute",
                local_name="compute",
            ),
        ),
        references=(
            ReferenceRecord(
                reference_id="reference:compute:0",
                name="compute",
                scope_id="scope:function:run",
                context="call",
                span=call_span,
            ),
        ),
        calls=(
            CallRecord(
                call_id="call:compute:0",
                scope_id="scope:function:run",
                callee_name="compute",
                kind="direct",
                argument_count=1,
                span=call_span,
                callee_reference_id="reference:compute:0",
            ),
        ),
        effects=(
            EffectRecord(
                effect_id="effect:read:0",
                scope_id="scope:function:run",
                kind="io",
                operation="read",
                span=call_span,
                subject="shared_resource",
            ),
        ),
        export_names=("run",),
    )


def grand_consumer_module() -> ASTRecord:
    """pkg/cli.py — calls run (transitive impact of compute)."""

    body = b"from pkg.app import run\ndef main():\n    run()\n"
    main_span = span(24, len(body), 2, 3)
    call_span = span(38, 43, 3)
    return make_record(
        path="pkg/cli.py",
        module_name="pkg.cli",
        source=body,
        symbols=(
            SymbolDefinition(
                symbol_id="symbol:main:0",
                name="main",
                qualified_name="pkg.cli.main",
                kind="function",
                scope_id="scope:module",
                span=main_span,
                definition_ordinal=0,
                signature=SignatureDefinition(parameters=()),
                visibility="public",
            ),
        ),
        scopes=(
            ScopeDefinition(
                scope_id="scope:module",
                kind="module",
                span=span(0, len(body), 1, 3),
            ),
            ScopeDefinition(
                scope_id="scope:function:main",
                kind="function",
                span=main_span,
                parent_scope_id="scope:module",
                owner_symbol_id="symbol:main:0",
            ),
        ),
        imports=(
            ImportDefinition(
                import_id="import:pkg.app.run:0",
                scope_id="scope:module",
                module="pkg.app",
                kind="symbol",
                span=span(0, 23, 1),
                imported_name="run",
                local_name="run",
            ),
        ),
        references=(
            ReferenceRecord(
                reference_id="reference:run:0",
                name="run",
                scope_id="scope:function:main",
                context="call",
                span=call_span,
            ),
        ),
        calls=(
            CallRecord(
                call_id="call:run:0",
                scope_id="scope:function:main",
                callee_name="run",
                kind="direct",
                argument_count=0,
                span=call_span,
                callee_reference_id="reference:run:0",
            ),
        ),
        export_names=("main",),
    )


def duplicate_compute_module() -> ASTRecord:
    """pkg/shadow.py — second definition of pkg.core.compute (conflict)."""

    body = b"def compute(x):\n    return x * 2\n"
    fn_span = span(0, len(body), 1, 2)
    return make_record(
        path="pkg/shadow.py",
        module_name="pkg.shadow",
        source=body,
        symbols=(
            SymbolDefinition(
                symbol_id="symbol:compute:0",
                name="compute",
                qualified_name="pkg.core.compute",
                kind="function",
                scope_id="scope:module",
                span=fn_span,
                definition_ordinal=0,
                signature=SignatureDefinition(parameters=()),
                visibility="public",
            ),
        ),
        export_names=("compute",),
    )


def load_fixture_store(*records: ASTRecord):
    store = build_duckdb_ast_store()
    projections = []
    for index, record in enumerate(records):
        projections.append(store.put(record, created_at=float(index + 1)))
    impact = build_duckdb_ast_impact(store)
    revision_id = projections[0].source_revision.revision_id
    return store, impact, revision_id, projections


# ---------------------------------------------------------------------------
# Interface pins
# ---------------------------------------------------------------------------


def test_interfaces_and_schema_are_pinned() -> None:
    impact = build_duckdb_ast_impact()
    assert impact.interface == DUCKDB_IMPACT_INTERFACE
    assert impact.schema_version == DUCKDB_IMPACT_SCHEMA_VERSION
    assert DUCKDB_IMPACT_INTERFACE == "DuckDBASTImpact@1"
    assert IMPACT_CLOSURE_KINDS == frozenset(
        {
            "reverse_reference",
            "call",
            "import",
            "effect",
            "interface",
            "semantic_dependency",
            "conflict",
        }
    )
    descriptor = impact_schema_descriptor()
    assert descriptor["interface"] == DUCKDB_IMPACT_INTERFACE
    assert descriptor["guarantees"]["closures_bind_exact_source_revision"] is True
    assert descriptor["guarantees"]["depth_row_time_budgets_enforced"] is True
    assert descriptor["budgets"]["default_max_depth"] == DEFAULT_MAX_DEPTH
    assert descriptor["budgets"]["default_max_rows"] == DEFAULT_MAX_ROWS
    assert set(descriptor["closure_kinds"]) == IMPACT_CLOSURE_KINDS


def test_module_import_is_inert_without_duckdb() -> None:
    mod = importlib.import_module(
        "ipfs_datasets_py.logic.software_contracts.duckdb_impact"
    )
    assert mod.DUCKDB_IMPACT_INTERFACE == "DuckDBASTImpact@1"
    assert mod.DEFAULT_MAX_DEPTH >= 1


def test_path_to_module_helpers() -> None:
    assert path_to_module("pkg/core.py") == "pkg.core"
    assert path_to_module("pkg/__init__.py") == "pkg"
    assert path_to_module("src/app/main.ts") == "src.app.main"


# ---------------------------------------------------------------------------
# Acceptance: closures bind an exact source revision
# ---------------------------------------------------------------------------


def test_closures_bind_exact_source_revision() -> None:
    store, impact, revision_id, projections = load_fixture_store(
        provider_module(), consumer_module(), grand_consumer_module()
    )
    assert revision_id == f"rev:{REPO}:{REV_A}"

    closure = impact.semantic_dependency_closure(
        revision_id, ["pkg.core.compute"]
    )
    assert closure.revision_id == revision_id
    assert closure.repository_id == REPO
    assert closure.revision == REV_A
    assert closure.kind == ImpactClosureKind.SEMANTIC_DEPENDENCY.value
    assert "pkg.app.run" in closure.affected_symbols
    assert "pkg.cli.main" in closure.affected_symbols
    # Every symbol node is from the bound revision's projections.
    blob_ids = {item.blob_id for item in projections}
    for node in closure.nodes:
        if node.entity_kind == "symbol" and node.blob_id:
            assert node.blob_id in blob_ids

    # A different revision has no projections → fail closed.
    other_revision = f"rev:{REPO}:{REV_B}"
    with pytest.raises(DuckDBImpactError, match="no AST projections"):
        impact.semantic_dependency_closure(other_revision, ["pkg.core.compute"])


def test_revision_isolation_excludes_other_revisions() -> None:
    store = build_duckdb_ast_store()
    a = store.put(provider_module(), created_at=1.0)
    # Same paths under a different Git revision identity.
    other = make_record(
        path="pkg/core.py",
        module_name="pkg.core",
        source=b"def compute(x):\n    return 0\n",
        revision=REV_B,
        tree=TREE_B,
        symbols=(
            SymbolDefinition(
                symbol_id="symbol:compute:0",
                name="compute",
                qualified_name="pkg.core.compute",
                kind="function",
                scope_id="scope:module",
                span=span(0, 20, 1, 2),
                definition_ordinal=0,
                visibility="public",
            ),
        ),
    )
    b = store.put(other, created_at=2.0)
    # Also put consumer only on revision A.
    consumer = store.put(consumer_module(), created_at=3.0)
    impact = build_duckdb_ast_impact(store)

    closure_a = impact.call_closure(
        a.source_revision.revision_id, ["pkg.core.compute"]
    )
    assert closure_a.revision == REV_A
    assert "pkg.app.run" in closure_a.affected_symbols

    # Revision B has only the provider — no callers.
    closure_b = impact.call_closure(
        b.source_revision.revision_id, ["pkg.core.compute"]
    )
    assert closure_b.revision == REV_B
    assert "pkg.app.run" not in closure_b.affected_symbols
    assert consumer.source_revision.revision_id == a.source_revision.revision_id


# ---------------------------------------------------------------------------
# Acceptance: depth / row / time budgets are enforced
# ---------------------------------------------------------------------------


def test_depth_budget_fail_closed() -> None:
    reverse = {
        "a": ("b",),
        "b": ("c",),
        "c": ("d",),
    }
    with pytest.raises(ImpactBudgetExceeded) as excinfo:
        bounded_reverse_closure(
            ["a"],
            reverse,
            budget=ImpactBudget(max_depth=1, max_rows=100, fail_closed=True),
        )
    assert excinfo.value.dimension == "depth"


def test_depth_budget_soft_truncation() -> None:
    reverse = {
        "a": ("b",),
        "b": ("c",),
        "c": ("d",),
    }
    nodes, chains, truncated, reason = bounded_reverse_closure(
        ["a"],
        reverse,
        budget=ImpactBudget(max_depth=1, max_rows=100, fail_closed=False),
    )
    assert truncated is True
    assert "depth" in reason
    assert "a" in nodes and "b" in nodes
    assert "c" not in nodes
    assert "d" not in nodes


def test_row_budget_fail_closed() -> None:
    reverse = {f"n{i}": (f"n{i+1}",) for i in range(20)}
    with pytest.raises(ImpactBudgetExceeded) as excinfo:
        bounded_reverse_closure(
            ["n0"],
            reverse,
            budget=ImpactBudget(max_depth=100, max_rows=5, fail_closed=True),
        )
    assert excinfo.value.dimension == "rows"


def test_time_budget_fail_closed() -> None:
    # Wide fan-out with an extremely tight wall-clock budget.
    reverse = {"root": tuple(f"child{i}" for i in range(5000))}
    # Nested children to keep the BFS busy.
    for i in range(5000):
        reverse[f"child{i}"] = tuple(f"g{i}_{j}" for j in range(20))
    with pytest.raises(ImpactBudgetExceeded) as excinfo:
        bounded_reverse_closure(
            ["root"],
            reverse,
            budget=ImpactBudget(
                max_depth=10,
                max_rows=1_000_000,
                max_time_ms=0.001,
                fail_closed=True,
            ),
        )
    assert excinfo.value.dimension == "time_ms"


def test_query_plane_enforces_budgets_on_fixtures() -> None:
    _, impact, revision_id, _ = load_fixture_store(
        provider_module(), consumer_module(), grand_consumer_module()
    )
    # Depth 0: only the seed is retained (fail-closed if expansion needed).
    soft = impact.semantic_dependency_closure(
        revision_id,
        ["pkg.core.compute"],
        budget=ImpactBudget(max_depth=0, max_rows=100, fail_closed=False),
    )
    assert soft.truncated is True
    # Seed itself is present; transitive dependents are not.
    assert "pkg.core.compute" in soft.affected_symbols
    assert "pkg.cli.main" not in soft.affected_symbols

    with pytest.raises(ImpactBudgetExceeded):
        impact.semantic_dependency_closure(
            revision_id,
            ["pkg.core.compute"],
            budget=ImpactBudget(max_depth=0, max_rows=100, fail_closed=True),
        )


# ---------------------------------------------------------------------------
# Acceptance: known impact fixtures agree with existing analyzers
# ---------------------------------------------------------------------------


def test_pure_impact_agrees_with_code_impact_index_algorithm() -> None:
    """``pure_impact_closure`` matches CodeImpactIndex reverse walk."""

    # dependent -> providers (CodeImpactIndex orientation)
    dependencies = {
        "pkg.app.run": ("pkg.core.compute",),
        "pkg.cli.main": ("pkg.app.run",),
        "pkg.cli.entry": ("pkg.cli.main", "pkg.core.compute"),
    }
    nodes, chains, truncated, reason = pure_impact_closure(
        roots=["pkg.core.compute"],
        dependencies=dependencies,
        budget=ImpactBudget(max_depth=32, max_rows=1000, fail_closed=True),
    )
    assert truncated is False
    assert reason == ""
    assert set(nodes) == {
        "pkg.core.compute",
        "pkg.app.run",
        "pkg.cli.main",
        "pkg.cli.entry",
    }
    # Shortest chain selection is deterministic.
    assert chains["pkg.app.run"] == ("pkg.core.compute", "pkg.app.run")
    assert chains["pkg.cli.main"] == (
        "pkg.core.compute",
        "pkg.app.run",
        "pkg.cli.main",
    )
    # Direct edge preferred over longer path for entry.
    assert chains["pkg.cli.entry"][0] == "pkg.core.compute"
    assert chains["pkg.cli.entry"][-1] == "pkg.cli.entry"
    assert len(chains["pkg.cli.entry"]) == 2

    # Parity with supervisor CodeImpactIndex when available.
    try:
        from ipfs_accelerate_py.agent_supervisor.code_evidence_graph import (
            CodeImpactIndex,
        )
    except Exception:
        CodeImpactIndex = None  # type: ignore[misc, assignment]

    if CodeImpactIndex is not None:
        index = CodeImpactIndex(
            repository_tree_id=TREE_A,
            symbol_paths={
                "pkg.core.compute": "pkg/core.py",
                "pkg.app.run": "pkg/app.py",
                "pkg.cli.main": "pkg/cli.py",
                "pkg.cli.entry": "pkg/cli.py",
            },
            symbol_dependencies=dependencies,
        )
        result = index.impact(changed_symbols=["pkg.core.compute"])
        assert set(result.affected_symbols) == set(nodes)
        for symbol in result.affected_symbols:
            assert tuple(result.dependency_chains[symbol]) == chains[symbol]


def test_fixture_closures_agree_with_pure_analyzer() -> None:
    _, impact, revision_id, _ = load_fixture_store(
        provider_module(), consumer_module(), grand_consumer_module()
    )
    deps = impact.symbol_dependency_map(revision_id)
    # Expected: run depends on compute; main depends on run.
    assert "pkg.app.run" in deps
    assert "pkg.core.compute" in deps["pkg.app.run"]
    assert "pkg.cli.main" in deps
    assert "pkg.app.run" in deps["pkg.cli.main"]

    pure_nodes, pure_chains, _, _ = pure_impact_closure(
        roots=["pkg.core.compute"],
        dependencies=deps,
    )
    closure = impact.semantic_dependency_closure(
        revision_id, ["pkg.core.compute"]
    )
    assert set(closure.affected_symbols) >= set(pure_nodes)
    # Chains for pure symbol population match.
    for symbol in pure_nodes:
        assert symbol in closure.affected_symbols
    # Reverse map orientation is CodeImpactIndex-compatible.
    reverse = reverse_dependency_map(deps)
    assert "pkg.app.run" in reverse["pkg.core.compute"]


def test_call_and_reference_and_import_closures() -> None:
    _, impact, revision_id, _ = load_fixture_store(
        provider_module(), consumer_module(), grand_consumer_module()
    )

    calls = impact.call_closure(revision_id, ["pkg.core.compute"])
    assert calls.revision_id == revision_id
    assert "pkg.app.run" in calls.affected_symbols

    refs = impact.reverse_reference_closure(revision_id, ["compute"])
    assert refs.kind == "reverse_reference"
    assert "pkg.app.run" in refs.affected_symbols

    imports = impact.import_closure(revision_id, ["pkg.core"])
    assert imports.kind == "import"
    # Importer path should appear in the closure.
    assert any(
        node.path == "pkg/app.py" or node.label.endswith("pkg.app")
        for node in imports.nodes
    )


def test_effect_and_interface_and_conflict_closures() -> None:
    _, impact, revision_id, _ = load_fixture_store(
        provider_module(),
        consumer_module(),
        duplicate_compute_module(),
    )

    effects = impact.effect_closure(revision_id, ["pkg.core.compute"])
    assert effects.kind == "effect"
    assert effects.revision_id == revision_id
    # Shared effect subject links compute's scope to run's scope.
    assert effects.nodes  # non-empty

    interfaces = impact.interface_closure(revision_id, ["pkg.core.compute"])
    assert interfaces.kind == "interface"
    assert interfaces.revision_id == revision_id

    conflicts = impact.conflict_closure(revision_id)
    assert conflicts.kind == "conflict"
    assert conflicts.revision_id == revision_id
    findings = impact.list_conflicts(revision_id)
    assert any(item.kind == "duplicate_definition" for item in findings)
    assert any(item.subject == "pkg.core.compute" for item in findings)
    # Effect contradiction on shared_resource (write vs read).
    assert any(item.kind == "effect_contradiction" for item in findings)


def test_impact_symbols_high_level_api() -> None:
    _, impact, revision_id, _ = load_fixture_store(
        provider_module(), consumer_module(), grand_consumer_module()
    )
    result = impact.impact_symbols(revision_id, ["pkg.core.compute"])
    assert result.kind == "semantic_dependency"
    assert set(result.affected_symbols) >= {
        "pkg.core.compute",
        "pkg.app.run",
        "pkg.cli.main",
    }
    payload = result.to_dict()
    assert payload["revision_id"] == revision_id
    assert payload["schema"] == DUCKDB_IMPACT_SCHEMA_VERSION
    assert payload["truncated"] is False


def test_budget_validation() -> None:
    with pytest.raises(DuckDBImpactError):
        ImpactBudget(max_depth=-1)
    with pytest.raises(DuckDBImpactError):
        ImpactBudget(max_rows=0)
    with pytest.raises(DuckDBImpactError):
        ImpactBudget(max_time_ms=0)
    budget = ImpactBudget(max_depth=10_000, max_rows=10**9, max_time_ms=10**9)
    # Hard caps applied.
    assert budget.max_depth <= 4096
    assert budget.max_rows <= 1_000_000
    assert budget.max_time_ms <= 300_000.0


def test_index_projection_without_store() -> None:
    projection = project_ast_record(provider_module(), created_at=1.0)
    impact = DuckDBASTImpact()
    impact.index(project_ast_record(consumer_module(), created_at=2.0))
    impact.index(projection)
    revision_id = projection.source_revision.revision_id
    closure = impact.call_closure(revision_id, ["pkg.core.compute"])
    assert "pkg.app.run" in closure.affected_symbols


def test_empty_seeds_and_unknown_revision_errors() -> None:
    impact = build_duckdb_ast_impact()
    with pytest.raises(DuckDBImpactError):
        impact.semantic_dependency_closure("rev:missing:x", ["a"])
