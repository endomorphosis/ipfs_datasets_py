"""Focused contract vectors for pure selected-versus-full oracle metrics (DSS-008)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    NormalizedTestStatus,
    OracleApplicability,
    SelectionFallback,
    TestOracleComparison,
    TestOutcome,
    TestRunFacts,
    TestSelection,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.oracle import (
    TEST_SELECTION_ORACLE_INTERFACE,
    TestOracleError,
    compare_test_selection_oracle,
    compute_changed_outcome_node_ids,
    compute_new_regressions,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _selection(
    selected: list[str],
    *,
    fallback: SelectionFallback = SelectionFallback.NONE,
    universe_count: int = 0,
    fallback_reasons: list[str] | None = None,
) -> TestSelection:
    return TestSelection(
        previous_root_cid=None,
        current_root_cid=_cid("oracle-root"),
        selected_pytest_node_ids=selected,
        known_test_universe_count=universe_count,
        fallback=fallback,
        fallback_reasons=tuple(fallback_reasons or ()),
    )


def _outcome(
    node_id: str,
    status: NormalizedTestStatus | str,
    fingerprint: str | None = None,
) -> TestOutcome:
    return TestOutcome(
        node_id=node_id,
        status=status,
        failure_fingerprint=fingerprint,
    )


def _facts(run_id: str, outcomes: list[TestOutcome]) -> TestRunFacts:
    return TestRunFacts(run_id=run_id, outcomes=outcomes)


NODE_A = "tests/test_mod.py::test_a"
NODE_B = "tests/test_mod.py::test_b"
NODE_C = "tests/test_mod.py::test_c"
NODE_D = "tests/test_other.py::test_d"


def test_interface_constant() -> None:
    assert TEST_SELECTION_ORACLE_INTERFACE == "TestSelectionOracle@1"


def test_controlled_perfect_selection_zero_fn_and_missed_regressions() -> None:
    """Controlled case: precise selection has zero FN and zero missed regressions."""
    baseline = _facts(
        "baseline",
        [
            _outcome(NODE_A, NormalizedTestStatus.PASSED),
            _outcome(NODE_B, NormalizedTestStatus.PASSED),
            _outcome(NODE_C, NormalizedTestStatus.PASSED),
            _outcome(NODE_D, NormalizedTestStatus.PASSED),
        ],
    )
    # Candidate introduces a regression only on NODE_A.
    candidate = _facts(
        "candidate",
        [
            _outcome(NODE_A, NormalizedTestStatus.FAILED, "assert-a"),
            _outcome(NODE_B, NormalizedTestStatus.PASSED),
            _outcome(NODE_C, NormalizedTestStatus.PASSED),
            _outcome(NODE_D, NormalizedTestStatus.PASSED),
        ],
    )
    authored = [NODE_A, NODE_B]
    selection = _selection([NODE_A, NODE_B], universe_count=4)
    selected_run = _facts(
        "selected",
        [
            _outcome(NODE_A, NormalizedTestStatus.FAILED, "assert-a"),
            _outcome(NODE_B, NormalizedTestStatus.PASSED),
        ],
    )

    result = compare_test_selection_oracle(
        selection,
        baseline_full=baseline,
        selected_run=selected_run,
        candidate_full=candidate,
        authored_oracle=authored,
    )

    assert result.applicability == OracleApplicability.APPLICABLE.value
    assert list(result.new_regressions) == [NODE_A]
    assert list(result.missed_regressions) == []
    assert list(result.true_positives) == [NODE_A, NODE_B]
    assert list(result.false_negatives) == []
    assert list(result.false_positives) == []
    assert result.fixture_recall_bp == 10_000
    assert result.fixture_precision_bp == 10_000
    assert result.regression_recall_bp == 10_000
    assert result.selected_count == 2
    assert result.full_count == 4
    assert result.selection_ratio_bp == 5_000
    assert result.execution_reduction_bp == 5_000
    assert result.fallback_rate_bp == 0
    assert NODE_A in result.changed_outcome_node_ids


def test_false_negative_and_missed_regression_detected() -> None:
    baseline = _facts(
        "baseline",
        [
            _outcome(NODE_A, NormalizedTestStatus.PASSED),
            _outcome(NODE_B, NormalizedTestStatus.PASSED),
            _outcome(NODE_C, NormalizedTestStatus.PASSED),
        ],
    )
    candidate = _facts(
        "candidate",
        [
            _outcome(NODE_A, NormalizedTestStatus.FAILED, "boom-a"),
            _outcome(NODE_B, NormalizedTestStatus.ERROR, "err-b"),
            _outcome(NODE_C, NormalizedTestStatus.PASSED),
        ],
    )
    # Selection only catches A; B is a missed regression and oracle FN.
    selection = _selection([NODE_A], universe_count=3)
    selected_run = _facts(
        "selected",
        [_outcome(NODE_A, NormalizedTestStatus.FAILED, "boom-a")],
    )

    result = compare_test_selection_oracle(
        selection,
        baseline_full=baseline,
        selected_run=selected_run,
        candidate_full=candidate,
        authored_oracle=[NODE_A, NODE_B],
    )

    assert list(result.new_regressions) == [NODE_A, NODE_B]
    assert list(result.missed_regressions) == [NODE_B]
    assert list(result.true_positives) == [NODE_A]
    assert list(result.false_negatives) == [NODE_B]
    assert list(result.false_positives) == []
    assert result.fixture_recall_bp == 5_000
    assert result.fixture_precision_bp == 10_000
    assert result.regression_recall_bp == 5_000


def test_false_positive_selection_outside_authored_oracle() -> None:
    baseline = _facts(
        "baseline",
        [
            _outcome(NODE_A, NormalizedTestStatus.PASSED),
            _outcome(NODE_B, NormalizedTestStatus.PASSED),
            _outcome(NODE_C, NormalizedTestStatus.PASSED),
        ],
    )
    candidate = _facts(
        "candidate",
        [
            _outcome(NODE_A, NormalizedTestStatus.FAILED, "a"),
            _outcome(NODE_B, NormalizedTestStatus.PASSED),
            _outcome(NODE_C, NormalizedTestStatus.PASSED),
        ],
    )
    selection = _selection([NODE_A, NODE_C], universe_count=3)
    selected_run = _facts(
        "selected",
        [
            _outcome(NODE_A, NormalizedTestStatus.FAILED, "a"),
            _outcome(NODE_C, NormalizedTestStatus.PASSED),
        ],
    )

    result = compare_test_selection_oracle(
        selection,
        baseline_full=baseline,
        selected_run=selected_run,
        candidate_full=candidate,
        authored_oracle=[NODE_A],
    )

    assert list(result.true_positives) == [NODE_A]
    assert list(result.false_negatives) == []
    assert list(result.false_positives) == [NODE_C]
    assert result.fixture_precision_bp == 5_000
    assert result.fixture_recall_bp == 10_000


def test_baseline_known_failures_not_attributed_to_candidate() -> None:
    """Identical baseline fail/error/timeout fingerprints are excluded."""
    baseline = _facts(
        "baseline",
        [
            _outcome(NODE_A, NormalizedTestStatus.FAILED, "known-assert"),
            _outcome(NODE_B, NormalizedTestStatus.ERROR, "known-error"),
            _outcome(NODE_C, NormalizedTestStatus.TIMEOUT, "known-timeout"),
            _outcome(NODE_D, NormalizedTestStatus.PASSED),
        ],
    )
    candidate = _facts(
        "candidate",
        [
            _outcome(NODE_A, NormalizedTestStatus.FAILED, "known-assert"),
            _outcome(NODE_B, NormalizedTestStatus.ERROR, "known-error"),
            _outcome(NODE_C, NormalizedTestStatus.TIMEOUT, "known-timeout"),
            _outcome(NODE_D, NormalizedTestStatus.FAILED, "new-d"),
        ],
    )
    selection = _selection([NODE_D], universe_count=4)
    selected_run = _facts(
        "selected",
        [_outcome(NODE_D, NormalizedTestStatus.FAILED, "new-d")],
    )

    result = compare_test_selection_oracle(
        selection,
        baseline_full=baseline,
        selected_run=selected_run,
        candidate_full=candidate,
        authored_oracle=[NODE_D],
    )

    assert list(result.new_regressions) == [NODE_D]
    assert list(result.missed_regressions) == []
    assert NODE_A not in result.new_regressions
    assert NODE_B not in result.new_regressions
    assert NODE_C not in result.new_regressions


def test_changed_fingerprint_is_new_regression() -> None:
    baseline = _facts(
        "baseline",
        [_outcome(NODE_A, NormalizedTestStatus.FAILED, "old-assert")],
    )
    candidate = _facts(
        "candidate",
        [_outcome(NODE_A, NormalizedTestStatus.FAILED, "new-assert")],
    )
    assert list(compute_new_regressions(baseline, candidate)) == [NODE_A]


def test_pass_skip_xfail_are_not_regressions() -> None:
    baseline = _facts(
        "baseline",
        [
            _outcome(NODE_A, NormalizedTestStatus.PASSED),
            _outcome(NODE_B, NormalizedTestStatus.SKIPPED),
            _outcome(NODE_C, NormalizedTestStatus.XFAILED),
        ],
    )
    candidate = _facts(
        "candidate",
        [
            _outcome(NODE_A, NormalizedTestStatus.SKIPPED),
            _outcome(NODE_B, NormalizedTestStatus.XFAILED),
            _outcome(NODE_C, NormalizedTestStatus.PASSED),
        ],
    )
    assert list(compute_new_regressions(baseline, candidate)) == []
    changed = compute_changed_outcome_node_ids(baseline, candidate)
    assert set(changed) == {NODE_A, NODE_B, NODE_C}


def test_empty_oracle_never_fabricates_perfect_metrics() -> None:
    baseline = _facts(
        "baseline",
        [
            _outcome(NODE_A, NormalizedTestStatus.PASSED),
            _outcome(NODE_B, NormalizedTestStatus.PASSED),
        ],
    )
    candidate = _facts(
        "candidate",
        [
            _outcome(NODE_A, NormalizedTestStatus.FAILED, "x"),
            _outcome(NODE_B, NormalizedTestStatus.PASSED),
        ],
    )
    selection = _selection([NODE_A], universe_count=2)
    selected_run = _facts(
        "selected",
        [_outcome(NODE_A, NormalizedTestStatus.FAILED, "x")],
    )

    for authored in (None, (), []):
        result = compare_test_selection_oracle(
            selection,
            baseline_full=baseline,
            selected_run=selected_run,
            candidate_full=candidate,
            authored_oracle=authored,
        )
        assert result.applicability == OracleApplicability.NOT_APPLICABLE.value
        assert list(result.true_positives) == []
        assert list(result.false_negatives) == []
        assert list(result.false_positives) == []
        assert result.fixture_recall_bp is None
        assert result.fixture_precision_bp is None
        # Empty fixture denom must not look like 100% success.
        assert result.fixture_recall_bp != 10_000
        assert result.fixture_precision_bp != 10_000


def test_empty_selection_with_oracle_yields_zero_recall_null_precision() -> None:
    baseline = _facts(
        "baseline",
        [_outcome(NODE_A, NormalizedTestStatus.PASSED)],
    )
    candidate = _facts(
        "candidate",
        [_outcome(NODE_A, NormalizedTestStatus.FAILED, "x")],
    )
    selection = _selection([], universe_count=1)
    selected_run = _facts("selected", [])

    result = compare_test_selection_oracle(
        selection,
        baseline_full=baseline,
        selected_run=selected_run,
        candidate_full=candidate,
        authored_oracle=[NODE_A],
    )

    assert result.applicability == OracleApplicability.APPLICABLE.value
    assert list(result.false_negatives) == [NODE_A]
    assert list(result.true_positives) == []
    assert result.fixture_recall_bp == 0
    assert result.fixture_precision_bp is None
    assert list(result.missed_regressions) == [NODE_A]
    assert result.regression_recall_bp == 0


def test_no_new_regressions_yields_null_regression_recall() -> None:
    baseline = _facts(
        "baseline",
        [_outcome(NODE_A, NormalizedTestStatus.PASSED)],
    )
    candidate = _facts(
        "candidate",
        [_outcome(NODE_A, NormalizedTestStatus.PASSED)],
    )
    selection = _selection([NODE_A], universe_count=1)
    selected_run = _facts(
        "selected",
        [_outcome(NODE_A, NormalizedTestStatus.PASSED)],
    )

    result = compare_test_selection_oracle(
        selection,
        baseline_full=baseline,
        selected_run=selected_run,
        candidate_full=candidate,
        authored_oracle=[NODE_A],
    )

    assert list(result.new_regressions) == []
    assert result.regression_recall_bp is None


def test_full_suite_fallback_is_measured_with_zero_missed_regressions() -> None:
    """Full pytest fallback executes everything; measured, not claimed precise."""
    baseline = _facts(
        "baseline",
        [
            _outcome(NODE_A, NormalizedTestStatus.PASSED),
            _outcome(NODE_B, NormalizedTestStatus.PASSED),
            _outcome(NODE_C, NormalizedTestStatus.PASSED),
        ],
    )
    candidate = _facts(
        "candidate",
        [
            _outcome(NODE_A, NormalizedTestStatus.FAILED, "a"),
            _outcome(NODE_B, NormalizedTestStatus.FAILED, "b"),
            _outcome(NODE_C, NormalizedTestStatus.PASSED),
        ],
    )
    # Domain-wide fallback clears the selection list (DSS-007 contract).
    selection = _selection(
        [],
        fallback=SelectionFallback.FULL_PYTEST,
        universe_count=3,
        fallback_reasons=["dynamic_pytest_plugin"],
    )
    selected_run = candidate  # accelerate runs full suite

    result = compare_test_selection_oracle(
        selection,
        baseline_full=baseline,
        selected_run=selected_run,
        candidate_full=candidate,
        authored_oracle=[NODE_A, NODE_B],
    )

    assert result.fallback_rate_bp == 10_000
    assert result.selected_count == 3
    assert result.full_count == 3
    assert result.selection_ratio_bp == 10_000
    assert result.execution_reduction_bp == 0
    assert list(result.missed_regressions) == []
    assert list(result.false_negatives) == []
    assert list(result.new_regressions) == [NODE_A, NODE_B]
    assert result.regression_recall_bp == 10_000
    # Full suite is not "precise" relative to a narrow authored oracle.
    assert result.fixture_precision_bp is not None
    assert result.fixture_precision_bp < 10_000
    assert result.fixture_recall_bp == 10_000


def test_both_fallback_covers_pytest_membership() -> None:
    baseline = _facts(
        "baseline",
        [_outcome(NODE_A, NormalizedTestStatus.PASSED)],
    )
    candidate = _facts(
        "candidate",
        [_outcome(NODE_A, NormalizedTestStatus.TIMEOUT, "hang")],
    )
    selection = _selection([], fallback=SelectionFallback.BOTH, universe_count=1)
    result = compare_test_selection_oracle(
        selection,
        baseline_full=baseline,
        selected_run=candidate,
        candidate_full=candidate,
        authored_oracle=[NODE_A],
    )
    assert result.fallback_rate_bp == 10_000
    assert list(result.missed_regressions) == []
    assert list(result.false_negatives) == []


def test_empty_full_suite_denominators_are_null() -> None:
    selection = _selection([])
    empty = _facts("empty", [])
    result = compare_test_selection_oracle(
        selection,
        baseline_full=empty,
        selected_run=empty,
        candidate_full=empty,
        authored_oracle=None,
    )
    assert result.full_count == 0
    assert result.selected_count == 0
    assert result.selection_ratio_bp is None
    assert result.execution_reduction_bp is None
    assert result.regression_recall_bp is None
    assert result.fixture_precision_bp is None
    assert result.fixture_recall_bp is None
    assert result.applicability == OracleApplicability.NOT_APPLICABLE.value
    assert result.fallback_rate_bp == 0


def test_changed_outcomes_include_added_and_removed_nodes() -> None:
    baseline = _facts(
        "baseline",
        [
            _outcome(NODE_A, NormalizedTestStatus.PASSED),
            _outcome(NODE_B, NormalizedTestStatus.PASSED),
        ],
    )
    candidate = _facts(
        "candidate",
        [
            _outcome(NODE_A, NormalizedTestStatus.PASSED),
            _outcome(NODE_C, NormalizedTestStatus.PASSED),
        ],
    )
    assert list(compute_changed_outcome_node_ids(baseline, candidate)) == [
        NODE_B,
        NODE_C,
    ]


def test_comparison_round_trip_and_cid_stability() -> None:
    baseline = _facts(
        "baseline",
        [
            _outcome(NODE_A, NormalizedTestStatus.PASSED),
            _outcome(NODE_B, NormalizedTestStatus.FAILED, "known"),
        ],
    )
    candidate = _facts(
        "candidate",
        [
            _outcome(NODE_A, NormalizedTestStatus.FAILED, "new"),
            _outcome(NODE_B, NormalizedTestStatus.FAILED, "known"),
        ],
    )
    selection = _selection([NODE_A], universe_count=2)
    selected_run = _facts(
        "selected",
        [_outcome(NODE_A, NormalizedTestStatus.FAILED, "new")],
    )
    result = compare_test_selection_oracle(
        selection,
        baseline_full=baseline,
        selected_run=selected_run,
        candidate_full=candidate,
        authored_oracle=[NODE_A],
    )
    restored = TestOracleComparison.from_dict(result.to_dict())
    assert restored == result
    assert restored.comparison_cid == result.comparison_cid
    assert result.selection_cid == selection.selection_cid
    assert result.baseline_facts_cid == baseline.facts_cid
    assert result.selected_facts_cid == selected_run.facts_cid
    assert result.candidate_full_facts_cid == candidate.facts_cid


def test_explicit_statuses_pass_fail_error_skip_xfail_timeout() -> None:
    statuses = [
        (NODE_A, NormalizedTestStatus.PASSED, None),
        (NODE_B, NormalizedTestStatus.FAILED, "f"),
        (NODE_C, NormalizedTestStatus.ERROR, "e"),
        (NODE_D, NormalizedTestStatus.SKIPPED, None),
        ("tests/t.py::test_xfail", NormalizedTestStatus.XFAILED, None),
        ("tests/t.py::test_timeout", NormalizedTestStatus.TIMEOUT, "t"),
        ("tests/t.py::test_xpassed", NormalizedTestStatus.XPASSED, None),
    ]
    baseline = _facts(
        "baseline",
        [_outcome(node, NormalizedTestStatus.PASSED) for node, _, _ in statuses],
    )
    candidate = _facts(
        "candidate",
        [_outcome(node, status, fp) for node, status, fp in statuses],
    )
    new_regs = compute_new_regressions(baseline, candidate)
    assert set(new_regs) == {NODE_B, NODE_C, "tests/t.py::test_timeout"}


def test_input_type_errors_fail_closed() -> None:
    selection = _selection([NODE_A])
    facts = _facts("r", [_outcome(NODE_A, NormalizedTestStatus.PASSED)])
    with pytest.raises(TestOracleError, match="selection"):
        compare_test_selection_oracle(  # type: ignore[arg-type]
            "not-a-selection",
            baseline_full=facts,
            selected_run=facts,
            candidate_full=facts,
        )
    with pytest.raises(TestOracleError, match="baseline_full"):
        compare_test_selection_oracle(
            selection,
            baseline_full="nope",  # type: ignore[arg-type]
            selected_run=facts,
            candidate_full=facts,
        )
    with pytest.raises(TestOracleError, match="authored_oracle"):
        compare_test_selection_oracle(
            selection,
            baseline_full=facts,
            selected_run=facts,
            candidate_full=facts,
            authored_oracle="tests/t.py::test",  # type: ignore[arg-type]
        )
    with pytest.raises(TestOracleError, match="duplicate"):
        compare_test_selection_oracle(
            selection,
            baseline_full=facts,
            selected_run=facts,
            candidate_full=facts,
            authored_oracle=[NODE_A, NODE_A],
        )


def test_full_proofs_only_fallback_is_not_pytest_full_rate() -> None:
    baseline = _facts(
        "baseline",
        [_outcome(NODE_A, NormalizedTestStatus.PASSED)],
    )
    candidate = _facts(
        "candidate",
        [_outcome(NODE_A, NormalizedTestStatus.FAILED, "x")],
    )
    selection = _selection(
        [NODE_A],
        fallback=SelectionFallback.FULL_PROOFS,
        universe_count=1,
    )
    result = compare_test_selection_oracle(
        selection,
        baseline_full=baseline,
        selected_run=candidate,
        candidate_full=candidate,
        authored_oracle=[NODE_A],
    )
    assert result.fallback_rate_bp == 0
    assert result.selected_count == 1
    assert list(result.missed_regressions) == []
