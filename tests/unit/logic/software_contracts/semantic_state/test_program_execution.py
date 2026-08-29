"""Contract vectors for dynamic execution-state, event, and trace records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
    AbstractExecutionStateIdentity,
    ExecutionTraceIdentity,
    ProgramEventIdentity,
    RawExecutionStateIdentity,
    StackFrameIdentity,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    ABSTRACT_PROGRAM_STATE_INTERFACE,
    ABSTRACT_PROGRAM_STATE_SCHEMA,
    EXECUTION_OBSERVATION_INTERFACE,
    EXECUTION_OBSERVATION_SCHEMA,
    EXECUTION_TRACE_INTERFACE,
    EXECUTION_TRACE_SCHEMA,
    PROGRAM_EVENT_INTERFACE,
    PROGRAM_EVENT_SCHEMA,
    PROGRAM_EXECUTION_STATE_INTERFACE,
    PROGRAM_EXECUTION_STATE_SCHEMA,
    REQUIRED_EVENT_KINDS,
    STACK_FRAME_STATE_INTERFACE,
    STACK_FRAME_STATE_SCHEMA,
    AbstractProgramState,
    AbstractionSoundnessClaim,
    CompletenessClaim,
    EventKind,
    EventOrigin,
    ExceptionSnapshot,
    ExecutionObservation,
    ExecutionTrace,
    ExecutionTraceSegment,
    HandlerKind,
    HandlerState,
    HeapBound,
    ObservationStatus,
    PrivacyClass,
    ProgramEvent,
    ProgramExecutionError,
    ProgramExecutionState,
    ProgramLanguage,
    RedactionProfile,
    StackFrameState,
    StateAbstractionReceipt,
    assemble_execution_trace,
    assemble_program_execution_state,
    bind_abstraction_receipt,
    canonical_program_execution_bytes,
    canonicalize_program_execution_value,
    decode_execution_observation,
    decode_program_execution_record,
    load_payload_schema,
    loads_program_execution_json,
    observe_program_event,
    program_execution_cid_for,
    public_execution_view,
)


SCHEMA_PATH = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py"
    / "logic"
    / "software_contracts"
    / "semantic_state"
    / "schemas"
    / "program-execution.payload.schema.json"
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _source() -> str:
    return cid_for_bytes(b"def ping():\n    return pong()\n")


def _tree() -> str:
    return _cid("tree:exact-v1")


def _env() -> str:
    return _cid("env:python-3.12")


def _code(name: str = "pkg.mod.ping") -> str:
    return _cid(f"code:{name}")


def _capture() -> str:
    return _cid("capture-profile-v1")


def _subject() -> str:
    return _cid("subject:pkg.mod.ping")


def _frame(ordinal: int = 0, name: str = "pkg.mod.ping", **overrides: Any) -> StackFrameState:
    fields: dict[str, Any] = {
        "ordinal": ordinal,
        "language": "python",
        "tree_cid": _tree(),
        "source_cid": _source(),
        "code_cid": _code(name),
        "environment_binding_cid": _env(),
        "logical_name": name,
        "line": 2 + ordinal,
        "column": 4,
        "state_summary": {"locals": {"x": ordinal}},
        "exception_snapshot_cid": None,
        "handler_state_cid": None,
        "exception_active": False,
        "handler_active": False,
        "redacted_dimensions": (),
        "unavailable_dimensions": (),
        "completeness_claim": CompletenessClaim.FULL_STATE,
        "privacy_class": PrivacyClass.INTERNAL,
    }
    fields.update(overrides)
    return StackFrameState(**fields)


def _exception(**overrides: Any) -> ExceptionSnapshot:
    inner = _frame(0, "pkg.mod.ping")
    outer = _frame(1, "pkg.mod.caller")
    fields: dict[str, Any] = {
        "language": "python",
        "exception_type": "ValueError",
        "tree_cid": _tree(),
        "source_cid": _source(),
        "code_cid": _code(),
        "environment_binding_cid": _env(),
        "exception_value_summary": {"type": "ValueError", "bounded": True},
        "traceback_stack_frame_cids": (
            inner.stack_frame_state_cid,
            outer.stack_frame_state_cid,
        ),
        "raised_at_event_cid": None,
        "handler_state_cid": None,
        "future_execution": False,
        "unavailable_dimensions": (),
        "completeness_claim": CompletenessClaim.FULL_STATE,
    }
    fields.update(overrides)
    return ExceptionSnapshot(**fields)


def _handler(exception: ExceptionSnapshot | None = None, **overrides: Any) -> HandlerState:
    matching = exception.exception_snapshot_cid if exception is not None else _cid("exc")
    fields: dict[str, Any] = {
        "language": "python",
        "handler_kind": HandlerKind.EXCEPT,
        "tree_cid": _tree(),
        "source_cid": _source(),
        "code_cid": _code("pkg.mod.recover"),
        "environment_binding_cid": _env(),
        "logical_name": "pkg.mod.recover",
        "stack_ordinal": 1,
        "handler_active": True,
        "matching_exception_snapshot_cid": matching,
        "unavailable_dimensions": (),
    }
    fields.update(overrides)
    return HandlerState(**fields)


def _event(
    kind: str = "call",
    *,
    origin: str = "observed",
    predecessor: str | None = None,
    frames: Sequence[StackFrameState] | None = None,
    **overrides: Any,
) -> ProgramEvent:
    stack = frames if frames is not None else (_frame(0), _frame(1, "pkg.mod.caller"))
    fields: dict[str, Any] = {
        "event_kind": kind,
        "event_origin": origin,
        "observation_status": (
            ObservationStatus.INFERRED_UNTRUSTED if origin != "observed" else ObservationStatus.OBSERVED
        ),
        "language": "python",
        "tree_cid": _tree(),
        "source_cid": _source(),
        "code_cid": _code(),
        "environment_binding_cid": _env(),
        "subject_cid": _subject(),
        "logical_name": "pkg.mod.ping",
        "payload": {"callee": "pkg.mod.pong"} if kind == "call" else {},
        "line": 2,
        "column": 4,
        "predecessor_event_cid": predecessor,
        "stack_frame_cids": tuple(frame.stack_frame_state_cid for frame in stack),
        "exception_snapshot_cid": None,
        "handler_state_cid": None,
        "redaction_profile_cid": None,
        "redacted_dimensions": (),
        "unavailable_dimensions": (),
        "completeness_claim": CompletenessClaim.FULL_STATE if origin == "observed" else CompletenessClaim.PARTIAL,
        "privacy_class": PrivacyClass.INTERNAL,
    }
    if origin != "observed" and "unavailable_dimensions" not in overrides:
        fields["unavailable_dimensions"] = ("future_state",)
        fields["completeness_claim"] = CompletenessClaim.PARTIAL
    if kind == "raise":
        exception = overrides.pop("exception", None) or _exception()
        fields["exception_snapshot_cid"] = exception.exception_snapshot_cid
    if kind in {"catch", "handler"}:
        handler = overrides.pop("handler", None) or _handler(_exception())
        fields["handler_state_cid"] = handler.handler_state_cid
    fields.update(overrides)
    return ProgramEvent(**fields)


def _state(**overrides: Any) -> ProgramExecutionState:
    inner = _frame(0)
    outer = _frame(1, "pkg.mod.caller")
    fields: dict[str, Any] = {
        "language": "python",
        "capture_profile_cid": _capture(),
        "tree_cid": _tree(),
        "source_cid": _source(),
        "environment_binding_cid": _env(),
        "frames": [inner, outer],
        "observed_state": {"locals": {"x": 1}},
        "heap_summary": {"objects": 2},
        "heap_bound": HeapBound.BOUNDED_ABSTRACT,
        "privacy_class": PrivacyClass.INTERNAL,
        "includes_raw_bodies": False,
    }
    fields.update(overrides)
    if "frames" in fields or "code_cid" not in fields:
        return assemble_program_execution_state(**fields)
    return ProgramExecutionState(**fields)


def _sample_payloads() -> list[dict[str, Any]]:
    inner = _frame(0)
    outer = _frame(1, "pkg.mod.caller")
    exception = _exception()
    handler = _handler(exception)
    redaction = RedactionProfile(
        privacy_class=PrivacyClass.PUBLIC,
        redacted_dimensions=("secrets",),
        unavailable_dimensions=(),
        completeness_claim=CompletenessClaim.REDACTED,
    )
    raising_frame = _frame(
        0,
        exception_snapshot_cid=exception.exception_snapshot_cid,
        exception_active=True,
        state_summary={"locals": {"x": 1}},
    )
    state = assemble_program_execution_state(
        capture_profile_cid=_capture(),
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        frames=[raising_frame, outer],
        exception=exception,
        handler=handler,
        observed_state={"locals": {"x": 1}},
        heap_summary={"objects": 1},
    )
    abstract = AbstractProgramState(
        language="python",
        raw_execution_state_cid=state.program_execution_state_cid,
        abstraction_profile_cid=_cid("abstraction-interval-v1"),
        tree_cid=_tree(),
        environment_binding_cid=_env(),
        abstract_state={"locals": {"x": "int"}},
        stack_frame_cids=state.stack_frame_cids,
        unavailable_dimensions=("native_stack",),
        observation_status=ObservationStatus.OBSERVED,
        completeness_claim=CompletenessClaim.PARTIAL,
    )
    call = _event("call", frames=(inner, outer))
    ret = _event("return", predecessor=call.program_event_cid, frames=(outer,), payload={"value": 1})
    raised = _event(
        "raise",
        predecessor=ret.program_event_cid,
        frames=(raising_frame, outer),
        exception=exception,
    )
    caught = _event(
        "catch",
        predecessor=raised.program_event_cid,
        frames=(raising_frame, outer),
        handler=handler,
    )
    line = _event("line", frames=(inner,), payload={"statement": "x = 1"})
    yielded = _event("yield", frames=(inner,), payload={"value": 0})
    awaited = _event("await", frames=(inner,), payload={"awaitable": "sleep"})
    external = _event("external", frames=(inner,), payload={"effect": "open"})
    predicted = _event(
        "call",
        origin="predicted",
        frames=(inner, outer),
        observation_status=ObservationStatus.INFERRED_UNTRUSTED,
        unavailable_dimensions=("future_state",),
        completeness_claim=CompletenessClaim.PARTIAL,
    )
    observation = observe_program_event(call)
    trace = assemble_execution_trace(
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        events=[call, ret, raised, caught],
        states=[state],
        privacy_class=PrivacyClass.INTERNAL,
    )
    segment = ExecutionTraceSegment(
        language="python",
        tree_cid=_tree(),
        environment_binding_cid=_env(),
        parent_trace_cid=trace.execution_trace_cid,
        start_event_cid=call.program_event_cid,
        end_event_cid=caught.program_event_cid,
        event_cids=[
            call.program_event_cid,
            ret.program_event_cid,
            raised.program_event_cid,
            caught.program_event_cid,
        ],
    )
    child_trace = assemble_execution_trace(
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        events=[call, ret, raised, caught],
        states=[state],
        segments=[segment],
        parent_trace_cid=trace.execution_trace_cid,
        privacy_class=PrivacyClass.INTERNAL,
    )
    receipt = bind_abstraction_receipt(
        state,
        abstract,
        soundness_claim=AbstractionSoundnessClaim.OVER_APPROXIMATION,
    )
    return [
        redaction.to_dict(),
        exception.to_dict(),
        handler.to_dict(),
        inner.to_dict(),
        outer.to_dict(),
        raising_frame.to_dict(),
        state.to_dict(),
        abstract.to_dict(),
        call.to_dict(),
        ret.to_dict(),
        raised.to_dict(),
        caught.to_dict(),
        line.to_dict(),
        yielded.to_dict(),
        awaited.to_dict(),
        external.to_dict(),
        predicted.to_dict(),
        observation.to_dict(),
        segment.to_dict(),
        trace.to_dict(),
        child_trace.to_dict(),
        receipt.to_dict(),
    ]


def test_public_interfaces_are_versioned_at_1() -> None:
    assert STACK_FRAME_STATE_INTERFACE == "StackFrameState@1"
    assert PROGRAM_EXECUTION_STATE_INTERFACE == "ProgramExecutionState@1"
    assert PROGRAM_EVENT_INTERFACE == "ProgramEvent@1"
    assert EXECUTION_TRACE_INTERFACE == "ExecutionTrace@1"
    assert ABSTRACT_PROGRAM_STATE_INTERFACE == "AbstractProgramState@1"
    assert EXECUTION_OBSERVATION_INTERFACE == "ExecutionObservation@1"
    assert STACK_FRAME_STATE_SCHEMA.endswith("@1")
    assert PROGRAM_EXECUTION_STATE_SCHEMA.endswith("@1")
    assert PROGRAM_EVENT_SCHEMA.endswith("@1")
    assert EXECUTION_TRACE_SCHEMA.endswith("@1")
    assert EXECUTION_OBSERVATION_SCHEMA.endswith("@1")
    assert ABSTRACT_PROGRAM_STATE_SCHEMA.endswith("@1")


def test_closed_event_grammar_covers_required_kinds() -> None:
    represented = set()
    inner = _frame(0)
    outer = _frame(1, "pkg.mod.caller")
    exception = _exception()
    handler = _handler(exception)
    for kind in sorted(REQUIRED_EVENT_KINDS):
        kwargs: dict[str, Any] = {"frames": (inner, outer)}
        if kind == "unavailable":
            kwargs.update(
                {
                    "origin": "observed",
                    "observation_status": ObservationStatus.UNAVAILABLE,
                    "unavailable_dimensions": ("event_body",),
                    "completeness_claim": CompletenessClaim.UNAVAILABLE,
                }
            )
        elif kind == EventKind.RAISE.value:
            kwargs["exception"] = exception
        elif kind in {EventKind.CATCH.value, EventKind.HANDLER.value}:
            kwargs["handler"] = handler
        event = _event(kind, **kwargs)
        represented.add(event.event_kind)
        decoded = decode_program_execution_record(event.to_dict())
        assert decoded.event_kind == kind
        assert decoded.code_cid == _code()
        assert decoded.environment_binding_cid == _env()
        assert decoded.tree_cid == _tree()
        assert decoded.source_cid == _source()
    assert represented == REQUIRED_EVENT_KINDS
    with pytest.raises(ProgramExecutionError, match="unsupported value"):
        _event("syscall")


def test_events_bind_exact_code_and_environment() -> None:
    event = _event("call")
    payload = event.identity_payload()
    assert payload["code_cid"] == _code()
    assert payload["environment_binding_cid"] == _env()
    assert payload["tree_cid"] == _tree()
    assert payload["source_cid"] == _source()
    assert "timestamp" not in payload
    assert "wall_clock" not in payload
    rebound = _event("call", code_cid=_code("pkg.mod.other"))
    assert rebound.program_event_cid != event.program_event_cid
    retargeted = _event("call", environment_binding_cid=_cid("env:other"))
    assert retargeted.program_event_cid != event.program_event_cid


def test_call_stack_order_is_preserved_and_reordering_changes_identity() -> None:
    inner = _frame(0)
    outer = _frame(1, "pkg.mod.caller")
    state = assemble_program_execution_state(
        capture_profile_cid=_capture(),
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        frames=[inner, outer],
        observed_state={"locals": {"x": 1}},
    )
    assert list(state.stack_frame_cids) == [
        inner.stack_frame_state_cid,
        outer.stack_frame_state_cid,
    ]
    assert inner.ordinal == 0
    assert outer.ordinal == 1
    swapped = ProgramExecutionState(
        language="python",
        capture_profile_cid=_capture(),
        tree_cid=_tree(),
        source_cid=_source(),
        code_cid=inner.code_cid,
        environment_binding_cid=_env(),
        observed_state={"locals": {"x": 1}},
        heap_summary={"objects": 2},
        heap_bound=HeapBound.BOUNDED_ABSTRACT,
        stack_frame_cids=[outer.stack_frame_state_cid, inner.stack_frame_state_cid],
    )
    assert swapped.program_execution_state_cid != state.program_execution_state_cid
    with pytest.raises(ProgramExecutionError, match="contiguous from 0"):
        assemble_program_execution_state(
            capture_profile_cid=_capture(),
            tree_cid=_tree(),
            source_cid=_source(),
            environment_binding_cid=_env(),
            frames=[outer, inner],
        )


def test_exception_and_handler_state_are_preserved() -> None:
    exception = _exception()
    handler = _handler(exception)
    frame = _frame(
        0,
        exception_snapshot_cid=exception.exception_snapshot_cid,
        handler_state_cid=handler.handler_state_cid,
        exception_active=True,
        handler_active=True,
    )
    state = assemble_program_execution_state(
        capture_profile_cid=_capture(),
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        frames=[frame],
        exception=exception,
        handler=handler,
        observed_state={"locals": {"x": 1}},
    )
    assert state.exception_snapshot_cid == exception.exception_snapshot_cid
    assert state.handler_state_cid == handler.handler_state_cid
    restored = decode_program_execution_record(state.to_dict())
    assert restored.exception_snapshot_cid == exception.exception_snapshot_cid
    assert restored.handler_state_cid == handler.handler_state_cid
    event = _event("raise", frames=(frame,), exception=exception)
    assert event.exception_snapshot_cid == exception.exception_snapshot_cid
    caught = _event("catch", frames=(frame,), handler=handler)
    assert caught.handler_state_cid == handler.handler_state_cid


def test_exception_snapshots_are_not_future_execution() -> None:
    with pytest.raises(ProgramExecutionError, match="not future execution"):
        _exception(future_execution=True)
    snapshot = _exception()
    payload = snapshot.to_dict()
    assert payload["future_execution"] is False
    assert "next_event_cid" not in payload
    assert "continuation_cid" not in payload
    decoded = decode_program_execution_record(payload)
    assert isinstance(decoded, ExceptionSnapshot)
    assert not isinstance(decoded, ProgramEvent)
    with pytest.raises(ProgramExecutionError, match="future-execution"):
        ExceptionSnapshot.from_dict({**payload, "next_event_cid": _cid("next")})
    with pytest.raises(ProgramExecutionError, match="future-execution"):
        ExceptionSnapshot.from_dict({**payload, "continuation_cid": _cid("cont")})
    forged = dict(payload)
    forged["schema"] = PROGRAM_EVENT_SCHEMA
    with pytest.raises(ProgramExecutionError, match="missing fields|unknown fields"):
        ProgramEvent.from_dict(forged)


def test_predicted_and_simulated_events_cannot_decode_as_observations() -> None:
    observed = _event("call")
    observation = observe_program_event(observed)
    assert observation.event_origin == EventOrigin.OBSERVED.value
    assert observation.observation_status == ObservationStatus.OBSERVED.value
    assert observation.event_cid == observed.program_event_cid
    assert decode_execution_observation(observed.to_dict()).execution_observation_cid == (
        observation.execution_observation_cid
    )
    predicted = _event("call", origin="predicted")
    simulated = _event("return", origin="simulated")
    with pytest.raises(ProgramExecutionError, match="cannot decode as observations"):
        observe_program_event(predicted)
    with pytest.raises(ProgramExecutionError, match="cannot decode as observations"):
        decode_execution_observation(predicted.to_dict())
    with pytest.raises(ProgramExecutionError, match="cannot decode as observations"):
        decode_execution_observation(simulated)
    with pytest.raises(ProgramExecutionError, match="cannot decode as observations"):
        ExecutionObservation.from_dict(
            {
                **observation.to_dict(),
                "event_origin": "predicted",
            }
        )
    with pytest.raises(ProgramExecutionError, match="cannot decode as observations"):
        _event("call", origin="predicted", observation_status=ObservationStatus.OBSERVED)


def test_redaction_never_claims_full_state_and_secrets_fail_closed() -> None:
    with pytest.raises(ProgramExecutionError, match="never claims full state"):
        _frame(redacted_dimensions=("locals",), completeness_claim=CompletenessClaim.FULL_STATE)
    with pytest.raises(ProgramExecutionError, match="secret fields"):
        _frame(state_summary={"locals": {"x": 1}, "password": "s3cret"})
    with pytest.raises(ProgramExecutionError, match="secret fields"):
        _state(observed_state={"api_key": "k", "locals": {"x": 1}})
    profile = RedactionProfile(
        privacy_class=PrivacyClass.PUBLIC,
        redacted_dimensions=("secrets", "raw_body"),
        completeness_claim=CompletenessClaim.REDACTED,
    )
    with pytest.raises(ProgramExecutionError, match="never claims full state"):
        RedactionProfile(
            privacy_class=PrivacyClass.PUBLIC,
            redacted_dimensions=("secrets",),
            completeness_claim=CompletenessClaim.FULL_STATE,
        )
    redacted_state = assemble_program_execution_state(
        capture_profile_cid=_capture(),
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        frames=[_frame(0)],
        redaction=profile,
        observed_state={"locals": {"x": 1}},
        completeness_claim=CompletenessClaim.REDACTED,
    )
    assert redacted_state.completeness_claim != CompletenessClaim.FULL_STATE.value
    assert "secrets" in redacted_state.redacted_dimensions
    with pytest.raises(ProgramExecutionError, match="cannot appear in observed_state"):
        assemble_program_execution_state(
            capture_profile_cid=_capture(),
            tree_cid=_tree(),
            source_cid=_source(),
            environment_binding_cid=_env(),
            frames=[_frame(0)],
            redaction=profile,
            observed_state={"secrets": {"token": 1}, "locals": {"x": 1}},
            completeness_claim=CompletenessClaim.REDACTED,
        )


def test_raw_and_public_views_remain_separated() -> None:
    private = assemble_program_execution_state(
        capture_profile_cid=_capture(),
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        frames=[_frame(0)],
        observed_state={"locals": {"x": 1}},
        privacy_class=PrivacyClass.PRIVATE,
        includes_raw_bodies=True,
        completeness_claim=CompletenessClaim.PARTIAL,
        unavailable_dimensions=("native_stack",),
    )
    public = public_execution_view(private)
    assert public.privacy_class == PrivacyClass.PUBLIC.value
    assert public.includes_raw_bodies is False
    assert public.completeness_claim != CompletenessClaim.FULL_STATE.value
    assert public.program_execution_state_cid != private.program_execution_state_cid
    assert public.observed_state == {}
    with pytest.raises(ProgramExecutionError, match="remain private"):
        assemble_program_execution_state(
            capture_profile_cid=_capture(),
            tree_cid=_tree(),
            source_cid=_source(),
            environment_binding_cid=_env(),
            frames=[_frame(0)],
            privacy_class=PrivacyClass.PUBLIC,
            includes_raw_bodies=True,
        )
    call = _event("call")
    private_trace = assemble_execution_trace(
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        events=[call],
        states=[private],
        privacy_class=PrivacyClass.PRIVATE,
        includes_raw_bodies=True,
        unavailable_dimensions=("native_stack",),
        completeness_claim=CompletenessClaim.PARTIAL,
    )
    public_trace = private_trace.public_view()
    assert public_trace.includes_raw_bodies is False
    assert public_trace.privacy_class == PrivacyClass.PUBLIC.value
    assert public_trace.raw_execution_state_cids == ()
    assert public_trace.execution_trace_cid != private_trace.execution_trace_cid


def test_partial_and_incomplete_state_is_explicit() -> None:
    incomplete = assemble_program_execution_state(
        capture_profile_cid=_capture(),
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        frames=(),
        code_cid=_code(),
        observed_state={},
        heap_bound=HeapBound.UNAVAILABLE,
        unavailable_dimensions=("call_stack", "heap", "native_stack"),
        completeness_claim=CompletenessClaim.PARTIAL,
        observation_status=ObservationStatus.UNAVAILABLE,
    )
    assert incomplete.stack_frame_cids == ()
    assert "call_stack" in incomplete.unavailable_dimensions
    assert incomplete.completeness_claim != CompletenessClaim.FULL_STATE.value
    with pytest.raises(ProgramExecutionError, match="cannot claim full state"):
        assemble_program_execution_state(
            capture_profile_cid=_capture(),
            tree_cid=_tree(),
            source_cid=_source(),
            environment_binding_cid=_env(),
            frames=(),
            code_cid=_code(),
            unavailable_dimensions=("call_stack",),
            completeness_claim=CompletenessClaim.FULL_STATE,
        )
    with pytest.raises(ProgramExecutionError, match="raw-memory identity"):
        _state(heap_bound="raw_memory")


def test_timestamp_fields_are_excluded_from_identity() -> None:
    event = _event("call")
    state = _state()
    with pytest.raises(ProgramExecutionError, match="unknown fields|non-semantic"):
        ProgramEvent.from_dict({**event.to_dict(), "timestamp": "2026-01-01T00:00:00Z"})
    with pytest.raises(ProgramExecutionError, match="unknown fields|non-semantic"):
        ProgramExecutionState.from_dict({**state.to_dict(), "wall_clock": 1})
    with pytest.raises(ProgramExecutionError, match="non-semantic fields"):
        _event("call", payload={"value": 1, "observed_at": "now"})
    with pytest.raises(ProgramExecutionError, match="non-semantic fields"):
        _state(observed_state={"locals": {"x": 1}, "timestamp": "now"})
    left = _event("line", payload={"statement": "x = 1"})
    right = _event("line", payload={"statement": "x = 1"})
    assert left.program_event_cid == right.program_event_cid
    assert "timestamp" not in left.identity_payload()
    assert "hostname" not in state.identity_payload()


def test_raw_and_abstract_identities_are_distinct_and_profile_bound() -> None:
    raw = _state()
    abstract = AbstractProgramState(
        language="python",
        raw_execution_state_cid=raw.program_execution_state_cid,
        abstraction_profile_cid=_cid("abstraction-interval-v1"),
        tree_cid=_tree(),
        environment_binding_cid=_env(),
        abstract_state={"locals": {"x": "int"}},
        stack_frame_cids=raw.stack_frame_cids,
        unavailable_dimensions=("native_stack",),
        completeness_claim=CompletenessClaim.PARTIAL,
    )
    other = AbstractProgramState(
        language="python",
        raw_execution_state_cid=raw.program_execution_state_cid,
        abstraction_profile_cid=_cid("abstraction-sign-v1"),
        tree_cid=_tree(),
        environment_binding_cid=_env(),
        abstract_state={"locals": {"x": "int"}},
        stack_frame_cids=raw.stack_frame_cids,
        unavailable_dimensions=("native_stack",),
        completeness_claim=CompletenessClaim.PARTIAL,
    )
    assert raw.program_execution_state_cid != abstract.abstract_program_state_cid
    assert abstract.abstract_program_state_cid != other.abstract_program_state_cid
    receipt = bind_abstraction_receipt(raw, abstract)
    assert receipt.raw_execution_state_cid == raw.program_execution_state_cid
    assert receipt.abstract_program_state_cid == abstract.abstract_program_state_cid
    with pytest.raises(ProgramExecutionError, match="must remain distinct"):
        StateAbstractionReceipt(
            language="python",
            raw_execution_state_cid=raw.program_execution_state_cid,
            abstract_program_state_cid=raw.program_execution_state_cid,
            abstraction_profile_cid=_cid("profile"),
        )
    raw_identity = RawExecutionStateIdentity.from_dict(raw.to_identity_record())
    abstract_identity = AbstractExecutionStateIdentity.from_dict(abstract.to_identity_record())
    assert raw_identity.raw_execution_state_cid != abstract_identity.abstract_execution_state_cid
    assert "abstraction_profile_cid" not in raw_identity.identity_payload()


def test_traces_preserve_repeats_and_parent_identity() -> None:
    call = _event("call")
    ret = _event("return", predecessor=call.program_event_cid)
    again = _event("call", predecessor=ret.program_event_cid)
    repeated = assemble_execution_trace(
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        events=[call, ret, call],
    )
    collapsed = assemble_execution_trace(
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        events=[call, ret],
    )
    assert list(repeated.event_cids) == [
        call.program_event_cid,
        ret.program_event_cid,
        call.program_event_cid,
    ]
    assert repeated.execution_trace_cid != collapsed.execution_trace_cid
    parented = assemble_execution_trace(
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        events=[call, ret, again],
        parent_trace_cid=repeated.execution_trace_cid,
    )
    unparented = assemble_execution_trace(
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        events=[call, ret, again],
    )
    assert parented.parent_trace_cid == repeated.execution_trace_cid
    assert parented.execution_trace_cid != unparented.execution_trace_cid
    identity = ExecutionTraceIdentity.from_dict(repeated.to_identity_record())
    assert list(identity.event_cids) == list(repeated.event_cids)
    segment = ExecutionTraceSegment(
        language="python",
        tree_cid=_tree(),
        environment_binding_cid=_env(),
        parent_trace_cid=repeated.execution_trace_cid,
        start_event_cid=call.program_event_cid,
        end_event_cid=call.program_event_cid,
        event_cids=[call.program_event_cid, ret.program_event_cid, call.program_event_cid],
    )
    assert segment.parent_trace_cid == repeated.execution_trace_cid
    assert list(segment.event_cids)[0] == segment.start_event_cid
    assert list(segment.event_cids)[-1] == segment.end_event_cid


def test_records_round_trip_and_rehash() -> None:
    for payload in _sample_payloads():
        record = decode_program_execution_record(payload)
        assert record.to_dict() == payload
        claimed = payload[record.CID_FIELD]
        assert decode_and_recompute_structured(claimed, record.identity_payload()) == claimed
        again = json.loads(json.dumps(payload, sort_keys=True))
        assert decode_program_execution_record(again).to_dict() == payload
        encoded = canonical_dag_json_bytes(payload).decode("utf-8")
        decoded = loads_program_execution_json(encoded)
        assert decode_program_execution_record(decoded).to_dict() == payload


def test_unknown_fields_versions_and_forged_cids_fail_closed() -> None:
    payload = _event("call").to_dict()
    with pytest.raises(ProgramExecutionError, match="unknown fields"):
        ProgramEvent.from_dict({**payload, "hnsw": True})
    with pytest.raises(ProgramExecutionError, match="schema version"):
        ProgramEvent.from_dict({**payload, "schema": PROGRAM_EVENT_SCHEMA.replace("@1", "@99")})
    forged = dict(payload)
    forged["program_event_cid"] = _cid("forged")
    with pytest.raises(ProgramExecutionError, match="does not verify"):
        ProgramEvent.from_dict(forged)
    with pytest.raises(ProgramExecutionError, match="unsupported program-execution schema"):
        decode_program_execution_record({"schema": "not-a-payload", "x": 1})
    frame_identity = StackFrameIdentity.from_dict(_frame(0).to_identity_record())
    event_identity = ProgramEventIdentity.from_dict(_event("call").to_identity_record())
    assert frame_identity.stack_frame_cid
    assert event_identity.program_event_cid


def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected() -> None:
    with pytest.raises(ProgramExecutionError, match="duplicate JSON key"):
        loads_program_execution_json('{"a":1,"a":2}')
    with pytest.raises(ProgramExecutionError, match="nonfinite"):
        loads_program_execution_json("NaN")
    with pytest.raises(ProgramExecutionError, match="nonfinite"):
        loads_program_execution_json("Infinity")
    with pytest.raises(ProgramExecutionError, match="floats are rejected"):
        loads_program_execution_json('{"score":1.5}')
    with pytest.raises(ProgramExecutionError, match="strict DAG-JSON"):
        canonicalize_program_execution_value({"x": 1.5})


def test_unsupported_language_fails_closed() -> None:
    with pytest.raises(ProgramExecutionError, match="typed unavailable"):
        _frame(language="javascript")
    with pytest.raises(ProgramExecutionError, match="typed unavailable"):
        _event("call", language="rust")
    assert ProgramLanguage.PYTHON.value in {"python"}
    assert set(item.value for item in ProgramLanguage) >= {
        "javascript",
        "typescript",
        "rust",
        "c",
        "cpp",
        "java",
        "shell",
    }


def test_canonical_identity_vectors_are_stable() -> None:
    frame = _frame(0)
    expected = frame.identity_payload()
    assert frame.stack_frame_state_cid == cid_for_structured(expected)
    assert frame.canonical_bytes() == canonical_dag_json_bytes(expected)
    assert frame.stack_frame_state_cid == program_execution_cid_for(expected)
    shuffled = _frame(0, unavailable_dimensions=("b", "a"), completeness_claim=CompletenessClaim.PARTIAL)
    same = _frame(0, unavailable_dimensions=("a", "b"), completeness_claim=CompletenessClaim.PARTIAL)
    assert shuffled.stack_frame_state_cid == same.stack_frame_state_cid
    assert list(shuffled.unavailable_dimensions) == ["a", "b"]
    assert canonical_program_execution_bytes(frame.identity_payload()) == frame.canonical_bytes()


def test_payload_schema_validates_closed_records_and_rejects_unknowns() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    payloads = _sample_payloads()
    for payload in payloads:
        validator.validate(payload)
    loaded = load_payload_schema()
    assert loaded["$id"].endswith("program-execution.payload.schema.json")
    extra = dict(payloads[0])
    extra["embedding"] = [0, 1]
    assert list(validator.iter_errors(extra))
    bad_version = dict(payloads[0])
    bad_version["schema"] = "ipfs-datasets.software-contracts.redaction-profile@99"
    assert list(validator.iter_errors(bad_version))
    assert list(validator.iter_errors({"schema": "not-a-payload", "x": 1}))
    event_payload = next(item for item in payloads if item.get("schema") == PROGRAM_EVENT_SCHEMA)
    predicted_as_observed = dict(event_payload)
    predicted_as_observed["event_origin"] = "predicted"
    predicted_as_observed["observation_status"] = "observed"
    assert list(validator.iter_errors(predicted_as_observed))
    snapshot_payload = next(
        item
        for item in payloads
        if item.get("schema") == "ipfs-datasets.software-contracts.exception-snapshot@1"
    )
    future = dict(snapshot_payload)
    future["future_execution"] = True
    assert list(validator.iter_errors(future))
    timed = dict(event_payload)
    timed["timestamp"] = "now"
    assert list(validator.iter_errors(timed))
    assert SCHEMA_PATH.is_file()
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "program-event@1" in text
    assert "additionalProperties" in text
    assert "predicted" in text
    assert "future_execution" in text
