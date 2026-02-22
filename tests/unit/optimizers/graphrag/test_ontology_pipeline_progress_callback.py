"""
Test progress callback parameter for OntologyPipeline.run()
"""
import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


def test_pipeline_run_with_progress_callback():
    """
    Verify that OntologyPipeline.run() invokes progress_callback for each
    refinement round with correct signature (round_num, max_rounds, current_score).
    """
    # Setup
    pipeline = OntologyPipeline(max_rounds=2)
    test_data = "The company processes customer data with strict security measures."

    # Track callback invocations
    callback_calls: list[tuple] = []

    def progress_callback(round_num: int, max_rounds: int, score: float) -> None:
        """Capture callback parameters for assertion."""
        callback_calls.append((round_num, max_rounds, score))

    # Execute with refine=True to trigger multi-round refinement
    result = pipeline.run(
        data=test_data,
        data_source="test",
        data_type="text",
        refine=True,
        progress_callback=progress_callback,
    )

    # Verify callback was invoked at least once
    assert len(callback_calls) >= 1, "Progress callback was never invoked"

    # Verify callback parameters in each call
    for i, (round_num, max_rounds, score) in enumerate(callback_calls):
        assert isinstance(round_num, int), f"Call {i}: round_num should be int, got {type(round_num)}"
        assert round_num >= 1, f"Call {i}: round_num should be >= 1, got {round_num}"
        assert isinstance(max_rounds, int), f"Call {i}: max_rounds should be int, got {type(max_rounds)}"
        assert max_rounds >= 1, f"Call {i}: max_rounds should be >= 1, got {max_rounds}"
        assert round_num <= max_rounds, f"Call {i}: round_num {round_num} should be <= max_rounds {max_rounds}"
        assert isinstance(score, float), f"Call {i}: score should be float, got {type(score)}"
        assert 0.0 <= score <= 1.0, f"Call {i}: score should be in [0.0, 1.0], got {score}"

    # Verify result is returned correctly
    assert result is not None
    assert hasattr(result, "entities")
    assert hasattr(result, "relationships")


def test_pipeline_run_without_progress_callback():
    """
    Verify that OntologyPipeline.run() works normally when progress_callback is None.
    """
    # Setup
    pipeline = OntologyPipeline(max_rounds=2)
    test_data = "Alice talks to Bob about the contract."

    # Execute without progress callback (default None)
    result = pipeline.run(
        data=test_data,
        data_source="test",
        data_type="text",
        refine=True,
    )

    # Verify result is returned correctly
    assert result is not None
    assert hasattr(result, "entities")
    assert hasattr(result, "score")


def test_pipeline_run_callback_exception_doesnt_crash():
    """
    Verify that exceptions in progress_callback do not crash the pipeline.
    Callback failures should be logged but the pipeline continues.
    """
    # Setup
    pipeline = OntologyPipeline(max_rounds=2)
    test_data = "The system processes requests constantly."

    def failing_callback(round_num: int, max_rounds: int, score: float) -> None:
        """A callback that always raises an exception."""
        raise ValueError("Deliberate callback failure for testing")

    # Execute — should NOT raise even though callback fails
    result = pipeline.run(
        data=test_data,
        data_source="test",
        data_type="text",
        refine=True,
        progress_callback=failing_callback,
    )

    # Verify pipeline completed despite callback failure
    assert result is not None
    assert len(result.entities) >= 0


def test_pipeline_run_without_refine_no_callback_invocations():
    """
    Verify that progress_callback is never invoked when refine=False.
    """
    # Setup
    pipeline = OntologyPipeline(max_rounds=2)
    test_data = "Simple business document with entities."

    # Track callback invocations
    callback_calls: list[tuple] = []

    def progress_callback(round_num: int, max_rounds: int, score: float) -> None:
        """Capture callback parameters."""
        callback_calls.append((round_num, max_rounds, score))

    # Execute with refine=False
    result = pipeline.run(
        data=test_data,
        data_source="test",
        data_type="text",
        refine=False,
        progress_callback=progress_callback,
    )

    # Verify callback was NOT invoked (no refinement rounds)
    assert len(callback_calls) == 0, "Callback should not be invoked when refine=False"

    # Verify result is still returned
    assert result is not None
