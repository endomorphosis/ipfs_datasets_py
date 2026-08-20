"""Pure selected-versus-full test oracle metrics (DSS-008).

Accelerate supplies normalized baseline, selected-run, and candidate-full
:class:`TestRunFacts` together with a :class:`TestSelection`.  This module never
invokes pytest, never treats a green selected run as proof of complete
selection, and never fabricates 100 percent precision or recall from an empty
denominator or empty authored oracle.

Selection membership and fixture TP/FN/FP live strictly in the pytest-node-ID
domain.  Failure fingerprints identify whether the outcome at a node is the same
failure; they never decide whether a node was selected.  Known baseline
fail/error/timeout fingerprints are not attributed as candidate regressions.
"""

from __future__ import annotations

from typing import Final, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    NormalizedTestStatus,
    OracleApplicability,
    SelectionFallback,
    TestOracleComparison,
    TestOutcome,
    TestRunFacts,
    TestSelection,
)

TEST_SELECTION_ORACLE_INTERFACE: Final[str] = "TestSelectionOracle@1"

_BASIS_POINTS: Final[int] = 10_000

_REGRESSION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        NormalizedTestStatus.FAILED.value,
        NormalizedTestStatus.ERROR.value,
        NormalizedTestStatus.TIMEOUT.value,
    }
)

_FULL_PYTEST_FALLBACKS: Final[frozenset[str]] = frozenset(
    {
        SelectionFallback.FULL_PYTEST.value,
        SelectionFallback.BOTH.value,
    }
)


class TestOracleError(ValueError):
    """Raised when oracle comparison inputs fail closed verification."""


def _as_selection(value: object) -> TestSelection:
    if not isinstance(value, TestSelection):
        raise TestOracleError("selection must be a TestSelection")
    return value


def _as_run_facts(value: object, name: str) -> TestRunFacts:
    if not isinstance(value, TestRunFacts):
        raise TestOracleError(f"{name} must be TestRunFacts")
    return value


def _status_value(status: NormalizedTestStatus | str) -> str:
    if isinstance(status, NormalizedTestStatus):
        return status.value
    return str(status)


def _outcome_map(facts: TestRunFacts) -> dict[str, TestOutcome]:
    return {outcome.node_id: outcome for outcome in facts.outcomes}


def _is_regression_status(status: NormalizedTestStatus | str) -> bool:
    return _status_value(status) in _REGRESSION_STATUSES


def _failure_identity(
    outcome: TestOutcome,
) -> tuple[str, str | None]:
    """Identity of a fail/error/timeout outcome for baseline exclusion."""
    return (_status_value(outcome.status), outcome.failure_fingerprint)


def _ratio_bp(numerator: int, denominator: int) -> int | None:
    """Return ``numerator/denominator`` as integer basis points, or null."""
    if denominator <= 0:
        return None
    if numerator < 0:
        raise TestOracleError("ratio numerator must be nonnegative")
    # Floor to stay inside [0, 10000] without floating-point drift.
    value = (numerator * _BASIS_POINTS) // denominator
    if value > _BASIS_POINTS:
        return _BASIS_POINTS
    return value


def _normalize_authored_oracle(
    authored_oracle: Sequence[str] | None,
) -> tuple[str, ...]:
    if authored_oracle is None:
        return ()
    if isinstance(authored_oracle, (str, bytes)):
        raise TestOracleError("authored_oracle must be a sequence of node IDs")
    ordered: list[str] = []
    seen: set[str] = set()
    for item in authored_oracle:
        if type(item) is not str or not item or item != item.strip():
            raise TestOracleError(
                "authored_oracle entries must be nonempty trimmed node ID strings"
            )
        if item in seen:
            raise TestOracleError(
                f"authored_oracle must not contain duplicate node IDs: {item!r}"
            )
        seen.add(item)
        ordered.append(item)
    return tuple(sorted(ordered))


def _fallback_value(selection: TestSelection) -> str:
    fallback = selection.fallback
    if isinstance(fallback, SelectionFallback):
        return fallback.value
    return str(fallback)


def _is_full_pytest_fallback(selection: TestSelection) -> bool:
    return _fallback_value(selection) in _FULL_PYTEST_FALLBACKS


def _effective_selected_node_ids(
    selection: TestSelection,
    candidate_full: TestRunFacts,
) -> frozenset[str]:
    """Node IDs treated as selected for membership metrics.

    Domain-wide pytest fallback clears ``selected_pytest_node_ids`` and signals
    that accelerate runs the full suite.  Membership then covers every
    candidate-full node so full fallback is not misreported as total miss.
    """
    if _is_full_pytest_fallback(selection):
        return frozenset(outcome.node_id for outcome in candidate_full.outcomes)
    return frozenset(selection.selected_pytest_node_ids)


def compute_new_regressions(
    baseline_full: TestRunFacts,
    candidate_full: TestRunFacts,
) -> tuple[str, ...]:
    """Node IDs with candidate fail/error/timeout not identical in baseline.

    A baseline fail/error/timeout with the same status and failure fingerprint
    for the same node is a known failure and is not attributed to the candidate.
    """
    baseline = _outcome_map(baseline_full)
    found: list[str] = []
    for outcome in candidate_full.outcomes:
        if not _is_regression_status(outcome.status):
            continue
        previous = baseline.get(outcome.node_id)
        if previous is not None and _is_regression_status(previous.status):
            if _failure_identity(previous) == _failure_identity(outcome):
                continue
        found.append(outcome.node_id)
    return tuple(sorted(found))


def compute_changed_outcome_node_ids(
    baseline_full: TestRunFacts,
    candidate_full: TestRunFacts,
) -> tuple[str, ...]:
    """Node IDs whose normalized status or failure fingerprint changed."""
    baseline = _outcome_map(baseline_full)
    candidate = _outcome_map(candidate_full)
    changed: list[str] = []
    for node_id in sorted(set(baseline) | set(candidate)):
        left = baseline.get(node_id)
        right = candidate.get(node_id)
        if left is None or right is None:
            changed.append(node_id)
            continue
        if _status_value(left.status) != _status_value(right.status):
            changed.append(node_id)
            continue
        if left.failure_fingerprint != right.failure_fingerprint:
            changed.append(node_id)
    return tuple(changed)


def compare_test_selection_oracle(
    selection: TestSelection,
    *,
    baseline_full: TestRunFacts,
    selected_run: TestRunFacts,
    candidate_full: TestRunFacts,
    authored_oracle: Sequence[str] | None = None,
) -> TestOracleComparison:
    """Compute honest selected-versus-full oracle metrics.

    Parameters
    ----------
    selection:
        Pure test/proof selection under evaluation.
    baseline_full:
        Normalized full-suite outcomes before the candidate change.
    selected_run:
        Normalized outcomes from executing the selection (or full suite under
        fallback).  Recorded by CID; membership metrics use ``selection``.
    candidate_full:
        Normalized full-suite outcomes after the candidate change.
    authored_oracle:
        Optional controlled affected-test node IDs.  ``None`` or empty yields
        ``not_applicable`` fixture metrics (never fabricated 100 percent).
    """
    selection = _as_selection(selection)
    baseline_full = _as_run_facts(baseline_full, "baseline_full")
    selected_run = _as_run_facts(selected_run, "selected_run")
    candidate_full = _as_run_facts(candidate_full, "candidate_full")
    oracle_nodes = _normalize_authored_oracle(authored_oracle)

    effective_selected = _effective_selected_node_ids(selection, candidate_full)
    declared_selected = frozenset(selection.selected_pytest_node_ids)

    new_regressions = compute_new_regressions(baseline_full, candidate_full)
    new_regression_set = frozenset(new_regressions)
    missed_regressions = tuple(
        sorted(node_id for node_id in new_regressions if node_id not in effective_selected)
    )

    if oracle_nodes:
        applicability = OracleApplicability.APPLICABLE
        oracle_set = frozenset(oracle_nodes)
        true_positives = tuple(sorted(effective_selected & oracle_set))
        false_negatives = tuple(sorted(oracle_set - effective_selected))
        false_positives = tuple(sorted(effective_selected - oracle_set))
        fixture_recall_bp = _ratio_bp(len(true_positives), len(oracle_set))
        fixture_precision_bp = _ratio_bp(len(true_positives), len(effective_selected))
    else:
        applicability = OracleApplicability.NOT_APPLICABLE
        true_positives = ()
        false_negatives = ()
        false_positives = ()
        fixture_recall_bp = None
        fixture_precision_bp = None

    full_count = len(candidate_full.outcomes)
    full_pytest_fallback = _is_full_pytest_fallback(selection)

    # Counts reflect what selection declared; full-suite fallback is measured
    # via fallback_rate_bp and effective membership above.
    if full_pytest_fallback:
        # Accelerate executes the full suite; report execution size honestly.
        selected_count = full_count
        selection_ratio_bp = _ratio_bp(full_count, full_count) if full_count else None
        execution_reduction_bp = _ratio_bp(0, full_count) if full_count else None
        fallback_rate_bp = _BASIS_POINTS
    else:
        selected_count = len(declared_selected)
        selection_ratio_bp = _ratio_bp(selected_count, full_count)
        if full_count:
            reduction = full_count - selected_count
            if reduction < 0:
                reduction = 0
            execution_reduction_bp = _ratio_bp(reduction, full_count)
        else:
            execution_reduction_bp = None
        fallback_rate_bp = 0

    changed_outcome_node_ids = compute_changed_outcome_node_ids(
        baseline_full, candidate_full
    )

    caught = len(new_regression_set & effective_selected)
    regression_recall_bp = _ratio_bp(caught, len(new_regressions))

    return TestOracleComparison(
        selection_cid=selection.selection_cid,
        baseline_facts_cid=baseline_full.facts_cid,
        selected_facts_cid=selected_run.facts_cid,
        candidate_full_facts_cid=candidate_full.facts_cid,
        applicability=applicability,
        new_regressions=new_regressions,
        missed_regressions=missed_regressions,
        true_positives=true_positives,
        false_negatives=false_negatives,
        false_positives=false_positives,
        fixture_recall_bp=fixture_recall_bp,
        fixture_precision_bp=fixture_precision_bp,
        selected_count=selected_count,
        full_count=full_count,
        selection_ratio_bp=selection_ratio_bp,
        execution_reduction_bp=execution_reduction_bp,
        fallback_rate_bp=fallback_rate_bp,
        changed_outcome_node_ids=changed_outcome_node_ids,
        regression_recall_bp=regression_recall_bp,
    )


def outcomes_by_node_id(facts: TestRunFacts) -> Mapping[str, TestOutcome]:
    """Return an immutable node-ID map for inspection and tests."""
    facts = _as_run_facts(facts, "facts")
    return dict(_outcome_map(facts))


__all__ = [
    "TEST_SELECTION_ORACLE_INTERFACE",
    "TestOracleError",
    "compare_test_selection_oracle",
    "compute_changed_outcome_node_ids",
    "compute_new_regressions",
    "outcomes_by_node_id",
]
