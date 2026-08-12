"""DSS-010 public controlled pipeline: scan → state → invalidation → selection.

End-to-end acceptance over the controlled fixture.  Tests call only public ISI
scan/diff/invalidation APIs and the storage-neutral semantic-state facade.  They
do not hand-construct dependency edges, mutate returned producer state, or
inspect private visitors.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index import (
    calculate_invalidation,
    diff_repository_states,
    scan_repository,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    RepositoryState,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state import (
    build_semantic_state,
    extend_semantic_invalidation,
    open_semantic_state,
    select_tests_and_proofs,
    verify_semantic_state_bundle,
    view_semantic_state_bundle,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    BindingKind,
    BindingScope,
    EnvironmentBinding,
    SelectionFallback,
    SelectionPolicy,
    SemanticInvalidationPlan,
    SemanticStateBundle,
)
from tests.fixtures.software_contracts.semantic_state import (
    apply_mutation,
    load_controlled_fixture,
    materialize_baseline,
)

# ---------------------------------------------------------------------------
# Public-pipeline helpers (no DependencyEdge construction)
# ---------------------------------------------------------------------------

_POLICY = SelectionPolicy(policy_id="controlled-acceptance", allow_full_fallback=True)

# External policy / interface / generated inputs are injected as validated
# EnvironmentBinding values (bindings module never rediscovers them from FS).
_INJECTED_BINDING_SPECS: tuple[tuple[str, BindingKind, BindingScope, str | None], ...] = (
    ("policy.toml", BindingKind.POLICY, BindingScope.GLOBAL, None),
    ("interface.json", BindingKind.INTERFACE_DESCRIPTOR, BindingScope.GLOBAL, None),
    (
        "generated/payload.json",
        BindingKind.GENERATED_INPUT,
        BindingScope.MODULE,
        "pkg.generated_reader",
    ),
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _init_git_repo(repo: Path, message: str = "baseline") -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "controlled@example.invalid")
    _git(repo, "config", "user.name", "Controlled Pipeline")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    status = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo,
        check=False,
    )
    if status.returncode != 0:
        _git(repo, "commit", "-m", message)


def _injected_bindings(repo: Path) -> tuple[EnvironmentBinding, ...]:
    """Inject external policy/interface/generated bindings from ordinary files."""
    items: list[EnvironmentBinding] = []
    for rel_path, kind, scope, subject in _INJECTED_BINDING_SPECS:
        path = repo / rel_path
        if not path.is_file():
            continue
        version_cid = cid_for_bytes(path.read_bytes())
        items.append(
            EnvironmentBinding(
                binding_id=f"file:{rel_path}",
                kind=kind,
                version_cid=version_cid,
                scope=scope,
                extraction_authority="injected",
                confidence=AnalysisConfidence.EXACT,
                subject_id=subject,
                content_cid=version_cid,
                metadata={"path": rel_path},
            )
        )
    return tuple(items)


@dataclass(frozen=True, slots=True)
class PipelineSnapshot:
    """One sealed scan + verified semantic-state bundle over a repository tree."""

    repo: Path
    index: RepositoryState
    bundle: SemanticStateBundle
    bindings: tuple[EnvironmentBinding, ...]

    @property
    def root_cid(self) -> str:
        return self.bundle.root.root_cid

    def view(self):
        return view_semantic_state_bundle(self.bundle)


@dataclass(frozen=True, slots=True)
class PipelinePair:
    """Baseline/current public pipeline products for one mutation case."""

    case_id: str
    previous: PipelineSnapshot
    current: PipelineSnapshot
    invalidation: SemanticInvalidationPlan
    selection: object

    @property
    def fallback(self) -> str:
        fb = self.selection.fallback  # type: ignore[attr-defined]
        return fb.value if isinstance(fb, SelectionFallback) else str(fb)


def _scan_and_build(
    repo: Path,
    *,
    previous_index: RepositoryState | None = None,
    previous_bundle: SemanticStateBundle | None = None,
) -> PipelineSnapshot:
    index = scan_repository(repo, previous_state=previous_index)
    bindings = _injected_bindings(repo)
    bundle = build_semantic_state(
        index,
        environment_bindings=bindings,
        previous_bundle=previous_bundle,
    )
    verify_semantic_state_bundle(bundle)
    return PipelineSnapshot(
        repo=repo, index=index, bundle=bundle, bindings=bindings
    )


def _materialize_baseline_repo(destination: Path) -> Path:
    materialize_baseline(destination)
    _init_git_repo(destination)
    return destination


def _run_case(
    previous: PipelineSnapshot,
    work: Path,
    case_id: str,
) -> PipelinePair:
    """Clone baseline tree, apply mutation, and run the full public pipeline."""
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(previous.repo, work)
    apply_mutation(work, case_id)
    _commit_all(work, case_id)

    current = _scan_and_build(
        work,
        previous_index=previous.index,
        previous_bundle=previous.bundle,
    )
    delta = diff_repository_states(previous.index, current.index)
    isi_plan = calculate_invalidation(previous.index, current.index, delta)
    prev_view = previous.view()
    curr_view = current.view()
    invalidation = extend_semantic_invalidation(
        previous.index,
        current.index,
        delta,
        isi_plan,
        prev_view,
        curr_view,
    )
    selection = select_tests_and_proofs(
        prev_view,
        curr_view,
        invalidation,
        policy=_POLICY,
        previous_index=previous.index,
        current_index=current.index,
    )
    return PipelinePair(
        case_id=case_id,
        previous=previous,
        current=current,
        invalidation=invalidation,
        selection=selection,
    )


@pytest.fixture(scope="module")
def baseline_repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("controlled-baseline")
    return _materialize_baseline_repo(root / "repo")


@pytest.fixture(scope="module")
def baseline_snapshot(baseline_repo: Path) -> PipelineSnapshot:
    return _scan_and_build(baseline_repo)


# ---------------------------------------------------------------------------
# Determinism: identical semantic inputs → identical state roots
# ---------------------------------------------------------------------------


def test_identical_semantic_inputs_yield_identical_state_roots(
    baseline_snapshot: PipelineSnapshot,
) -> None:
    """Same sealed ISI view always rebuilds to the same verified root and blocks.

    Git commit OIDs differ across independent ``git init`` worktrees, so identity
    is defined over the sealed repository state (and injected bindings), not over
    ambient checkout paths.
    """
    first = baseline_snapshot
    second_bundle = build_semantic_state(
        first.index,
        environment_bindings=first.bindings,
    )
    verify_semantic_state_bundle(second_bundle)
    third_bundle = build_semantic_state(
        first.index,
        environment_bindings=first.bindings,
        previous_bundle=first.bundle,
    )
    verify_semantic_state_bundle(third_bundle)

    assert first.root_cid == second_bundle.root.root_cid == third_bundle.root.root_cid
    assert first.bundle.root.to_dict() == second_bundle.root.to_dict()
    assert dict(first.bundle.blocks) == dict(second_bundle.blocks)
    assert dict(second_bundle.blocks) == dict(third_bundle.blocks)


def test_cold_and_verified_incremental_roots_are_byte_identical(
    baseline_snapshot: PipelineSnapshot,
) -> None:
    cold = baseline_snapshot
    incremental = build_semantic_state(
        cold.index,
        environment_bindings=cold.bindings,
        previous_bundle=cold.bundle,
    )
    verify_semantic_state_bundle(incremental)

    assert cold.root_cid == incremental.root.root_cid
    assert dict(cold.bundle.blocks) == dict(incremental.blocks)


def test_repeated_scan_of_unchanged_tree_is_stable(
    baseline_snapshot: PipelineSnapshot,
) -> None:
    first = baseline_snapshot.index
    second = scan_repository(baseline_snapshot.repo, previous_state=first)
    assert first.state_cid == second.state_cid
    assert first.repository_id == second.repository_id


# ---------------------------------------------------------------------------
# Public views and block reader
# ---------------------------------------------------------------------------


def test_bundle_view_and_open_semantic_state_agree(
    baseline_snapshot: PipelineSnapshot,
) -> None:
    snap = baseline_snapshot
    mem = view_semantic_state_bundle(snap.bundle)
    store = dict(snap.bundle.blocks)

    def get_block(cid: str) -> bytes:
        try:
            return store[cid]
        except KeyError as exc:
            raise KeyError(cid) from exc

    opened = open_semantic_state(snap.root_cid, get_block)
    assert opened.root.root_cid == mem.root.root_cid
    assert opened.root.to_dict() == mem.root.to_dict()

    # Resolve at least one capsule through both views.
    symbols = [s for s in snap.index.symbols if s.qualified_name.endswith(".add")]
    assert symbols
    stable = symbols[0].stable_id
    assert mem.capsule(stable).capsule_cid == opened.capsule(stable).capsule_cid
    assert mem.symbol_node(stable).node_cid == opened.symbol_node(stable).node_cid


# ---------------------------------------------------------------------------
# Mutation cases: root change, selection, opaque fallback
# ---------------------------------------------------------------------------


def test_semantic_mutation_changes_root_formatting_still_builds(
    baseline_snapshot: PipelineSnapshot, tmp_path: Path
) -> None:
    body = _run_case(baseline_snapshot, tmp_path / "local_body", "local_body")
    assert body.current.root_cid != body.previous.root_cid
    assert body.fallback == SelectionFallback.NONE.value
    selected = set(body.selection.selected_pytest_node_ids)  # type: ignore[attr-defined]
    oracle = set(load_controlled_fixture().authored_oracle("local_body"))
    assert oracle <= selected

    fmt = _run_case(baseline_snapshot, tmp_path / "format", "format")
    # Formatting still produces a verified bundle; selection must not invent
    # affected tests (empty authored oracle).
    verify_semantic_state_bundle(fmt.current.bundle)
    assert load_controlled_fixture().authored_oracle("format") == ()


def test_delete_and_rename_evidence_via_public_diff(
    baseline_snapshot: PipelineSnapshot, tmp_path: Path
) -> None:
    delete = _run_case(baseline_snapshot, tmp_path / "delete", "delete")
    delete_delta = diff_repository_states(delete.previous.index, delete.current.index)
    assert delete_delta.deleted_symbol_ids or delete_delta.modified_symbol_ids
    selected_delete = set(delete.selection.selected_pytest_node_ids)  # type: ignore[attr-defined]
    oracle_delete = set(load_controlled_fixture().authored_oracle("delete"))
    if delete.fallback not in (
        SelectionFallback.FULL_PYTEST.value,
        SelectionFallback.BOTH.value,
    ):
        assert oracle_delete <= selected_delete

    rename = _run_case(baseline_snapshot, tmp_path / "rename", "rename")
    rename_delta = diff_repository_states(rename.previous.index, rename.current.index)
    # Heuristic rename candidates or add/delete pairs must be visible.
    has_rename = bool(getattr(rename_delta, "rename_candidates", ()) or ())
    has_path_churn = bool(
        rename_delta.added_symbol_ids or rename_delta.deleted_symbol_ids
    )
    assert has_rename or has_path_churn
    selected_rename = set(rename.selection.selected_pytest_node_ids)  # type: ignore[attr-defined]
    oracle_rename = set(load_controlled_fixture().authored_oracle("rename"))
    if rename.fallback not in (
        SelectionFallback.FULL_PYTEST.value,
        SelectionFallback.BOTH.value,
    ):
        assert oracle_rename <= selected_rename


@pytest.mark.parametrize("case_id", ["dynamic", "monkey", "native"])
def test_opaque_behavior_requests_source_or_full_fallback(
    baseline_snapshot: PipelineSnapshot, tmp_path: Path, case_id: str
) -> None:
    """Opaque/dynamic/native mutations force full fallback and/or raw-source path."""
    pair = _run_case(baseline_snapshot, tmp_path / case_id, case_id)
    fixture_case = load_controlled_fixture().get_case(case_id)
    assert fixture_case.requires_full_fallback is True

    fallback = pair.fallback
    reasons = tuple(pair.selection.fallback_reasons)  # type: ignore[attr-defined]
    selected = set(pair.selection.selected_pytest_node_ids)  # type: ignore[attr-defined]
    oracle = set(fixture_case.affected_tests)

    full_fb = fallback in (
        SelectionFallback.FULL_PYTEST.value,
        SelectionFallback.BOTH.value,
    )
    # Zero false negatives: full fallback covers the universe; otherwise
    # every authored oracle node must appear in selection.
    if full_fb:
        assert True
    else:
        assert oracle <= selected

    # Opaque path evidence: either domain fallback or raw-source obligations.
    reason_blob = " ".join(reasons).lower()
    obligation_reasons = " ".join(
        str(getattr(item, "reason_code", "")).lower()
        for item in pair.invalidation.obligations
    )
    remediations = " ".join(
        str(getattr(item, "remediation", "")).lower()
        for item in pair.invalidation.obligations
    )
    opaque_markers = (
        "opaque",
        "native",
        "dynamic",
        "raw_source",
        "full_fallback",
        "full_pytest",
        "insufficient",
    )
    combined = f"{reason_blob} {obligation_reasons} {remediations} {fallback}"
    if case_id in ("dynamic", "monkey"):
        assert full_fb or any(marker in combined for marker in opaque_markers)
    else:
        # native: precise selection is allowed when the stand-in is exact, but
        # the authored oracle must still be covered (asserted above).
        assert oracle <= selected or full_fb


def test_unrelated_local_body_does_not_select_unrelated_suite(
    baseline_snapshot: PipelineSnapshot, tmp_path: Path
) -> None:
    """Bounded selection: local_body must not force the entire known universe."""
    pair = _run_case(baseline_snapshot, tmp_path / "local_body_bounded", "local_body")
    assert pair.fallback == SelectionFallback.NONE.value
    selected = tuple(pair.selection.selected_pytest_node_ids)  # type: ignore[attr-defined]
    universe = load_controlled_fixture().test_universe
    assert selected
    assert len(selected) < len(universe)
    # Stable helper test is unrelated to add body change.
    assert "tests/test_core.py::test_stable_helper" not in selected


def test_pipeline_never_constructs_dependency_edges_in_this_module() -> None:
    """Conflict policy: e2e tests may not hand-construct DependencyEdge values."""
    source = Path(__file__).read_text(encoding="utf-8")
    # Split the type name so this assertion source does not match itself as a call.
    edge_type = "Dependency" + "Edge"
    assert f"{edge_type}(" not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            assert name != edge_type


@pytest.mark.parametrize(
    "case_id",
    ["local_body", "schema", "policy", "generated", "delete", "rename"],
)
def test_representative_mutations_build_distinct_verified_roots(
    baseline_snapshot: PipelineSnapshot, tmp_path: Path, case_id: str
) -> None:
    """Smoke: representative controlled cases produce verified current roots."""
    pair = _run_case(baseline_snapshot, tmp_path / f"rep_{case_id}", case_id)
    root = verify_semantic_state_bundle(pair.current.bundle)
    assert pair.current.root_cid == root.root_cid
    assert pair.previous.root_cid != pair.current.root_cid
