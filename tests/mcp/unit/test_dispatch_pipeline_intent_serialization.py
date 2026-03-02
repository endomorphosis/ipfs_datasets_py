"""Regression tests for PipelineIntent serialization robustness."""

from __future__ import annotations

from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineIntent


class _NonSerializable:
    def __repr__(self) -> str:
        return "<non-serializable>"


def test_pipeline_intent_accepts_non_serializable_params() -> None:
    intent = PipelineIntent(
        tool_name="example_tool",
        actor="alice",
        params={"value": _NonSerializable()},
    )

    assert isinstance(intent.intent_cid, str)
    assert intent.intent_cid.startswith("bafy-mock-intent-")


def test_pipeline_intent_accepts_circular_params() -> None:
    params = {}
    params["self"] = params

    intent = PipelineIntent(
        tool_name="example_tool",
        actor="bob",
        params=params,
    )

    assert isinstance(intent.intent_cid, str)
    assert intent.intent_cid.startswith("bafy-mock-intent-")
