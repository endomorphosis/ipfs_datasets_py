"""Tests for typed exception handling in logic harness retry paths."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import logic_harness as lh


def test_run_single_session_with_retry_handles_typed_value_error() -> None:
    harness = lh.LogicHarness(
        extractor=object(),
        critic=object(),
        config=lh.HarnessConfig(max_retries=1),
    )

    class BrokenSession:
        def run(self, data, context):
            raise ValueError("bad data")

    result = harness._run_single_session_with_retry(BrokenSession(), data="x", context=None, session_id=1)
    assert result.success is False


def test_run_single_session_with_retry_does_not_swallow_keyboard_interrupt() -> None:
    harness = lh.LogicHarness(
        extractor=object(),
        critic=object(),
        config=lh.HarnessConfig(max_retries=1),
    )

    class BrokenSession:
        def run(self, data, context):
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        harness._run_single_session_with_retry(BrokenSession(), data="x", context=None, session_id=2)
