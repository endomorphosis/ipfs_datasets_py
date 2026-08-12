"""DSS-010 controlled selection/oracle acceptance: zero false negatives.

Runs the public scan → semantic-state → invalidation → selection pipeline for
every independently declared mutation case, then compares selection membership
against the authored fixture oracle via the pure oracle metrics API.  Datasets
never executes pytest; outcome facts are normalized records supplied here the
same way accelerate would supply them.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

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
    compare_test_selection_oracle,
    extend_semantic_invalidation,
    select_tests_and_proofs,
    verify_semantic_state_bundle,
    view_semantic_state_bundle,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    BindingKind,
    BindingScope,
    EnvironmentBinding,
    NormalizedTestStatus,
    OracleApplicability,
    SelectionFallback,
    SelectionPolicy,
    SemanticStateBundle,
    TestOutcome,
    TestRunFacts,
    TestSelection,
)
from tests.fixtures.software_contracts.semantic_state import (
    MutationCase,
    apply_mutation,
    case_ids,
    load_controlled_fixture,
    materialize_baseline,
)

_POLICY = SelectionPolicy(policy_id="controlled-oracle-acceptance", allow_full_fallback=True)

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

_FULL_PYTEST = frozenset(
    {
        SelectionFallback.FULL_PYTEST.value,
        SelectionFallback.BOTH.value,
    }
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _init_git_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "oracle@example.invalid")
    _git(repo, "config", "user.name", "Oracle Acceptance")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "baseline")


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


def _build(
    index: RepositoryState,
    repo: Path,
    *,
    previous_bundle: SemanticStateBundle | None = None,
) -> SemanticStateBundle:
    bundle = build_semantic_state(
        index,
        environment_bindings=_injected_bindings(repo),
        previous_bundle=previous_bundle,
    )
    verify_semantic_state_bundle(bundle)
    return bundle


@dataclass(frozen=True, slots=True)
class CaseSelectionResult:
    case: MutationCase
    selection: TestSelection
    previous_root_cid: str
    current_root_cid: str


@pytest.fixture(scope="module")
def baseline_tree(tmp_path_factory) -> tuple[Path, RepositoryState, SemanticStateBundle]:
    root = tmp_path_factory.mktemp("oracle-baseline")
    repo = root / "repo"
    materialize_baseline(repo)
    _init_git_repo(repo)
    index = scan_repository(repo)
    bundle = _build(index, repo)
    return repo, index, bundle


def _select_for_case(
    baseline: tuple[Path, RepositoryState, SemanticStateBundle],
    work: Path,
    case: MutationCase,
) -> CaseSelectionResult:
    base_repo, prev_index, prev_bundle = baseline
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(base_repo, work)
    apply_mutation(work, case.case_id)
    _commit_all(work, case.case_id)

    curr_index = scan_repository(work, previous_state=prev_index)
    curr_bundle = _build(curr_index, work, previous_bundle=prev_bundle)

    delta = diff_repository_states(prev_index, curr_index)
    isi_plan = calculate_invalidation(prev_index, curr_index, delta)
    prev_view = view_semantic_state_bundle(prev_bundle)
    curr_view = view_semantic_state_bundle(curr_bundle)
    invalidation = extend_semantic_invalidation(
        prev_index,
        curr_index,
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
        previous_index=prev_index,
        current_index=curr_index,
    )
    return CaseSelectionResult(
        case=case,
        selection=selection,
        previous_root_cid=prev_bundle.root.root_cid,
        current_root_cid=curr_bundle.root.root_cid,
    )


def _fallback_value(selection: TestSelection) -> str:
    fb = selection.fallback
    return fb.value if isinstance(fb, SelectionFallback) else str(fb)


def _facts_all_pass(run_id: str, node_ids: Sequence[str]) -> TestRunFacts:
    return TestRunFacts(
        run_id=run_id,
        outcomes=[
            TestOutcome(node_id=node_id, status=NormalizedTestStatus.PASSED)
            for node_id in sorted(node_ids)
        ],
    )


def _facts_with_regressions(
    run_id: str,
    universe: Sequence[str],
    failing: Sequence[str],
) -> TestRunFacts:
    failing_set = set(failing)
    outcomes: list[TestOutcome] = []
    for node_id in sorted(universe):
        if node_id in failing_set:
            outcomes.append(
                TestOutcome(
                    node_id=node_id,
                    status=NormalizedTestStatus.FAILED,
                    failure_fingerprint=f"regression:{node_id}",
                )
            )
        else:
            outcomes.append(
                TestOutcome(node_id=node_id, status=NormalizedTestStatus.PASSED)
            )
    return TestRunFacts(run_id=run_id, outcomes=outcomes)


def _selected_run_facts(
    selection: TestSelection,
    candidate_full: TestRunFacts,
) -> TestRunFacts:
    """Simulate accelerate executing selection (or full suite under fallback)."""
    fb = _fallback_value(selection)
    if fb in _FULL_PYTEST:
        outcomes = list(candidate_full.outcomes)
    else:
        selected = set(selection.selected_pytest_node_ids)
        outcomes = [
            outcome
            for outcome in candidate_full.outcomes
            if outcome.node_id in selected
        ]
    return TestRunFacts(run_id="selected-sim", outcomes=outcomes)


@pytest.mark.parametrize("case_id", list(case_ids()))
def test_controlled_case_has_zero_selection_false_negatives(
    baseline_tree: tuple[Path, RepositoryState, SemanticStateBundle],
    tmp_path: Path,
    case_id: str,
) -> None:
    fixture = load_controlled_fixture()
    case = fixture.get_case(case_id)
    result = _select_for_case(baseline_tree, tmp_path / case_id, case)
    selection = result.selection
    universe = fixture.test_universe

    # Synthetic accelerate-supplied run facts (datasets does not run pytest).
    baseline_full = _facts_all_pass("baseline-full", universe)
    # Authored affected tests are the only nodes that may fail under the patch.
    candidate_full = _facts_with_regressions(
        "candidate-full",
        universe,
        case.affected_tests,
    )
    selected_run = _selected_run_facts(selection, candidate_full)

    comparison = compare_test_selection_oracle(
        selection,
        baseline_full=baseline_full,
        selected_run=selected_run,
        candidate_full=candidate_full,
        authored_oracle=case.affected_tests if case.affected_tests else None,
    )

    # Zero fixture false negatives and zero missed regressions.
    assert list(comparison.false_negatives) == [], (
        f"{case_id}: false negatives {comparison.false_negatives}; "
        f"selected={selection.selected_pytest_node_ids}; "
        f"fallback={_fallback_value(selection)}; "
        f"reasons={selection.fallback_reasons}"
    )
    assert list(comparison.missed_regressions) == [], (
        f"{case_id}: missed regressions {comparison.missed_regressions}"
    )

    if case.formatting_only or not case.affected_tests:
        assert comparison.applicability == OracleApplicability.NOT_APPLICABLE.value
        assert comparison.fixture_recall_bp is None
    else:
        assert comparison.applicability == OracleApplicability.APPLICABLE.value
        assert comparison.fixture_recall_bp == 10_000

    if case.requires_full_fallback:
        fb = _fallback_value(selection)
        selected = set(selection.selected_pytest_node_ids)
        # Opaque cases must either force full pytest fallback or still cover the
        # authored oracle without false negatives (already asserted).
        assert fb in _FULL_PYTEST or set(case.affected_tests) <= selected

    # Environment / plugin / config paths on this fixture force domain fallback.
    if case_id in {"config", "lock", "dynamic", "monkey", "fixture", "plugin"}:
        assert _fallback_value(selection) in _FULL_PYTEST, (
            f"{case_id}: expected full pytest fallback, got "
            f"{_fallback_value(selection)} reasons={selection.fallback_reasons}"
        )
        assert comparison.fallback_rate_bp == 10_000

    # Precise local body selection stays bounded (proof IDs are best-effort
    # when the sealed graph exposes proof subjects; test FN is the gate).
    if case_id == "local_body":
        assert _fallback_value(selection) == SelectionFallback.NONE.value
        assert len(selection.selected_pytest_node_ids) < len(universe)


def test_identical_inputs_share_selection_root_binding(
    baseline_tree: tuple[Path, RepositoryState, SemanticStateBundle],
) -> None:
    """Same sealed index rebuilds to the same root used as selection current_root."""
    repo, index, bundle = baseline_tree
    again = _build(index, repo, previous_bundle=bundle)
    assert again.root.root_cid == bundle.root.root_cid
