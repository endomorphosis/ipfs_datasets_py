"""Contract vectors for abstraction profiles and abstract-state identity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    decode_and_recompute_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    CompletenessClaim,
    EventKind,
    HeapBound,
    ObservationStatus,
    PrivacyClass,
    ProgramEvent,
    ProgramExecutionState,
    StackFrameState,
    assemble_execution_trace,
    assemble_program_execution_state,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
    AbstractExecutionStateIdentity,
    RawExecutionStateIdentity,
    StateAbstractionProfileIdentity,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_abstraction import (
    ABSTRACTION_SOUNDNESS_RESULT_SCHEMA,
    CANONICAL_ABSTRACT_STATE_SCHEMA,
    FAMILY_DEFAULT_RELEVANT,
    IRRELEVANT_CATEGORIES,
    QUERY_FAMILIES,
    STATE_ABSTRACTION_PROFILE_INTERFACE,
    STATE_ABSTRACTION_PROFILE_SCHEMA,
    STATE_ABSTRACTION_RECEIPT_INTERFACE,
    STATE_ABSTRACTION_RECEIPT_SCHEMA,
    AbstractionSoundnessClaim,
    AbstractionSoundnessResult,
    CanonicalAbstractState,
    ProgramAbstractionError,
    ProgramLanguage,
    ProgramStateAbstractor,
    QueryFamily,
    StateAbstractionProfile,
    StateAbstractionReceipt,
    abstract_program_state,
    admitted_abstraction_profile,
    canonical_program_abstraction_bytes,
    canonicalize_program_abstraction_value,
    decode_program_abstraction_record,
    load_payload_schema,
    loads_program_abstraction_json,
    program_abstraction_cid_for,
)


SCHEMA_PATH = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py"
    / "logic"
    / "software_contracts"
    / "semantic_state"
    / "schemas"
    / "program-abstraction.payload.schema.json"
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


def _event(
    kind: str = "call",
    *,
    predecessor: str | None = None,
    frames: Sequence[StackFrameState] | None = None,
    **overrides: Any,
) -> ProgramEvent:
    stack = frames if frames is not None else (_frame(0), _frame(1, "pkg.mod.caller"))
    fields: dict[str, Any] = {
        "event_kind": kind,
        "event_origin": "observed",
        "observation_status": ObservationStatus.OBSERVED,
        "language": "python",
        "tree_cid": _tree(),
        "source_cid": _source(),
        "code_cid": _code(),
        "environment_binding_cid": _env(),
        "subject_cid": _subject(),
        "logical_name": "pkg.mod.ping",
        "payload": {"callee": "pkg.mod.pong"} if kind == "call" else {"value": 1},
        "line": 2,
        "column": 4,
        "predecessor_event_cid": predecessor,
        "stack_frame_cids": tuple(frame.stack_frame_state_cid for frame in stack),
        "exception_snapshot_cid": None,
        "handler_state_cid": None,
        "redaction_profile_cid": None,
        "redacted_dimensions": (),
        "unavailable_dimensions": (),
        "completeness_claim": CompletenessClaim.FULL_STATE,
        "privacy_class": PrivacyClass.INTERNAL,
    }
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
        "observed_state": {
            "callee": "pkg.mod.pong",
            "locals": {
                "x": 1,
                "ptr": "0x7fff0001",
                "alloc_id": "n-1",
                "path": "/tmp/a",
                "bag": [{"oid": "a"}, {"oid": "b"}],
            },
            "branch_predicate": "x > 0",
            "event_kind": "call",
            "line": 2,
            "exception_type": "ValueError",
            "handler_kind": "except",
            "contract_state": {"pre": "x > 0"},
            "failing_locals": {"x": 1},
            "assignments": [{"target": "x", "value": 1}],
            "event_order": [
                {"event_kind": "call", "logical_name": "pkg.mod.ping", "payload": {"callee": "pkg.mod.pong"}},
                {"event_kind": "return", "logical_name": "pkg.mod.ping", "payload": {"value": 1}},
            ],
        },
        "heap_summary": {
            "objects": [
                {"addr": "0x1000", "sort": "cell", "value": 1},
                {"addr": "0x2000", "sort": "cell", "value": 2},
            ],
            "scratch": {"n": 3},
        },
        "heap_bound": HeapBound.BOUNDED_ABSTRACT,
        "privacy_class": PrivacyClass.INTERNAL,
        "includes_raw_bodies": False,
    }
    fields.update(overrides)
    if "frames" in fields or "code_cid" not in fields:
        return assemble_program_execution_state(**fields)
    return ProgramExecutionState(**fields)


def _frames() -> tuple[StackFrameState, StackFrameState]:
    return (_frame(0), _frame(1, "pkg.mod.caller"))


def _run(
    raw: ProgramExecutionState,
    profile: StateAbstractionProfile,
    **kwargs: Any,
):
    return ProgramStateAbstractor(profile).abstract(raw, frames=_frames(), **kwargs)


def _sample_payloads() -> list[dict[str, Any]]:
    profile = admitted_abstraction_profile(QueryFamily.NEXT_CALL)
    raw = _state()
    outcome = _run(raw, profile)
    return [
        profile.to_dict(),
        outcome.canonical_abstract_state.to_dict(),
        outcome.soundness.to_dict(),
        outcome.receipt.to_dict(),
        admitted_abstraction_profile(QueryFamily.NEXT_EVENT).to_dict(),
        admitted_abstraction_profile(QueryFamily.INVERSE_TRACE).to_dict(),
        admitted_abstraction_profile(QueryFamily.REPAIR).to_dict(),
    ]


def test_public_interfaces_are_versioned() -> None:
    assert STATE_ABSTRACTION_PROFILE_INTERFACE == "StateAbstractionProfile@1"
    assert STATE_ABSTRACTION_RECEIPT_INTERFACE == "StateAbstractionReceipt@1"
    assert STATE_ABSTRACTION_PROFILE_SCHEMA.endswith("@1")
    assert STATE_ABSTRACTION_RECEIPT_SCHEMA.endswith("@1")
    assert tuple(QUERY_FAMILIES) == ("next_call", "next_event", "inverse_trace", "repair")
    assert set(IRRELEVANT_CATEGORIES) == {
        "addresses",
        "timestamps",
        "ids",
        "paths",
        "order",
        "values",
        "heap_regions",
    }


def test_irrelevant_variation_canonicalizes_under_admitted_next_call_profile() -> None:
    profile = admitted_abstraction_profile(QueryFamily.NEXT_CALL)
    baseline = _state()
    varied = _state(
        observed_state={
            "callee": "pkg.mod.pong",
            "locals": {
                "x": 1,
                "ptr": "0xaaaa0002",
                "alloc_id": "n-99",
                "path": "/tmp/other",
                "bag": [{"oid": "a"}, {"oid": "b"}],
            },
            "branch_predicate": "x > 0",
            "event_kind": "call",
            "line": 2,
            "exception_type": "ValueError",
            "handler_kind": "except",
            "contract_state": {"pre": "x > 0"},
            "failing_locals": {"x": 1},
            "assignments": [{"target": "x", "value": 1}],
            "event_order": [
                {"event_kind": "call", "logical_name": "pkg.mod.ping", "payload": {"callee": "pkg.mod.pong"}},
                {"event_kind": "return", "logical_name": "pkg.mod.ping", "payload": {"value": 1}},
            ],
        },
        heap_summary={
            "objects": [
                {"addr": "0x9999", "sort": "cell", "value": 2},
                {"addr": "0x1111", "sort": "cell", "value": 1},
            ],
            "scratch": {"n": 8},
        },
    )
    reordered_locals = _state(
        observed_state={
            "callee": "pkg.mod.pong",
            "locals": {
                "x": 1,
                "ptr": "0x7fff0001",
                "alloc_id": "n-1",
                "path": "/tmp/a",
                "bag": [{"oid": "b"}, {"oid": "a"}],
            },
            "branch_predicate": "x > 0",
            "event_kind": "call",
            "line": 2,
            "exception_type": "ValueError",
            "handler_kind": "except",
            "contract_state": {"pre": "x > 0"},
            "failing_locals": {"x": 1},
            "assignments": [{"target": "x", "value": 1}],
            "event_order": [
                {"event_kind": "call", "logical_name": "pkg.mod.ping", "payload": {"callee": "pkg.mod.pong"}},
                {"event_kind": "return", "logical_name": "pkg.mod.ping", "payload": {"value": 1}},
            ],
        }
    )
    left = _run(baseline, profile)
    right = _run(varied, profile)
    reordered = _run(reordered_locals, profile)
    assert baseline.program_execution_state_cid != varied.program_execution_state_cid
    assert left.canonical_abstract_state_cid == right.canonical_abstract_state_cid
    assert left.canonical_abstract_state_cid == reordered.canonical_abstract_state_cid
    assert left.receipt.abstract_program_state_cid != right.receipt.abstract_program_state_cid
    locals_map = left.canonical_abstract_state.abstract_state["locals"]
    assert locals_map["ptr"] == "<addr>"
    assert locals_map["alloc_id"] == "<id>"
    assert locals_map["path"] == "<path>"
    assert locals_map["x"] == 1


def test_transition_relevant_distinctions_survive_for_each_query_family() -> None:
    frames = _frames()
    next_call = admitted_abstraction_profile(QueryFamily.NEXT_CALL)
    other_callee = _state(
        observed_state={
            **_thaw_observed(_state()),
            "callee": "pkg.mod.other",
        }
    )
    other_local = _state(
        observed_state={
            **_thaw_observed(_state()),
            "locals": {
                "x": 2,
                "ptr": "0x7fff0001",
                "alloc_id": "n-1",
                "path": "/tmp/a",
                "bag": [{"oid": "a"}, {"oid": "b"}],
            },
        }
    )
    base_call = _run(_state(), next_call)
    assert (
        _run(other_callee, next_call).canonical_abstract_state_cid
        != base_call.canonical_abstract_state_cid
    )
    assert (
        _run(other_local, next_call).canonical_abstract_state_cid
        != base_call.canonical_abstract_state_cid
    )

    next_event = admitted_abstraction_profile(QueryFamily.NEXT_EVENT)
    other_kind = _state(observed_state={**_thaw_observed(_state()), "event_kind": "return"})
    assert (
        _run(_state(), next_event).canonical_abstract_state_cid
        != _run(other_kind, next_event).canonical_abstract_state_cid
    )

    inverse = admitted_abstraction_profile(QueryFamily.INVERSE_TRACE)
    call = _event("call")
    ret = _event("return", predecessor=call.program_event_cid)
    swapped = (_event("return"), _event("call"))
    left_inv = _run(_state(), inverse, events=(call, ret))
    right_inv = _run(_state(), inverse, events=swapped)
    assert left_inv.canonical_abstract_state_cid != right_inv.canonical_abstract_state_cid
    assert list(left_inv.canonical_abstract_state.abstract_state["event_order"])[0][
        "event_kind"
    ] == EventKind.CALL.value

    repair = admitted_abstraction_profile(QueryFamily.REPAIR)
    other_exc = _state(observed_state={**_thaw_observed(_state()), "exception_type": "TypeError"})
    other_heap = _state(
        heap_summary={
            "objects": [{"addr": "0x1000", "sort": "cell", "value": 9}],
            "scratch": {"n": 3},
        }
    )
    base_repair = _run(_state(), repair)
    assert (
        _run(other_exc, repair).canonical_abstract_state_cid
        != base_repair.canonical_abstract_state_cid
    )
    assert (
        _run(other_heap, repair).canonical_abstract_state_cid
        != base_repair.canonical_abstract_state_cid
    )
    same_heap_addrs = _state(
        heap_summary={
            "objects": [
                {"addr": "0xaaaa", "sort": "cell", "value": 1},
                {"addr": "0xbbbb", "sort": "cell", "value": 2},
            ],
            "scratch": {"n": 3},
        }
    )
    assert (
        _run(same_heap_addrs, repair).canonical_abstract_state_cid
        == base_repair.canonical_abstract_state_cid
    )
    assert frames[0].logical_name == "pkg.mod.ping"


def _thaw(value: Any) -> Any:
    if isinstance(value, dict) or hasattr(value, "items"):
        try:
            return {key: _thaw(item) for key, item in value.items()}
        except AttributeError:
            pass
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def _thaw_observed(state: ProgramExecutionState) -> dict[str, Any]:
    return _thaw(state.observed_state)


def test_profile_changes_alter_abstract_identity() -> None:
    raw = _state()
    next_call = admitted_abstraction_profile(QueryFamily.NEXT_CALL)
    renamed = admitted_abstraction_profile(
        QueryFamily.NEXT_CALL, profile_name="next-call-abstraction-v2"
    )
    next_event = admitted_abstraction_profile(QueryFamily.NEXT_EVENT)
    extra_relevant = admitted_abstraction_profile(
        QueryFamily.NEXT_CALL,
        relevant_dimensions=(*FAMILY_DEFAULT_RELEVANT["next_call"], "line"),
    )
    left = _run(raw, next_call)
    renamed_out = _run(raw, renamed)
    event_out = _run(raw, next_event)
    extra_out = _run(raw, extra_relevant)
    assert next_call.abstraction_profile_cid != renamed.abstraction_profile_cid
    assert next_call.abstraction_profile_cid != next_event.abstraction_profile_cid
    assert left.canonical_abstract_state_cid != renamed_out.canonical_abstract_state_cid
    assert left.canonical_abstract_state_cid != event_out.canonical_abstract_state_cid
    assert left.canonical_abstract_state_cid != extra_out.canonical_abstract_state_cid
    assert left.receipt.abstraction_profile_cid == next_call.abstraction_profile_cid
    identity = StateAbstractionProfileIdentity.from_dict(next_call.to_identity_record())
    assert identity.profile_name == next_call.profile_name
    assert "callee" in identity.dimensions


def test_raw_and_abstract_identities_remain_distinct() -> None:
    profile = admitted_abstraction_profile(QueryFamily.NEXT_CALL)
    raw = _state()
    receipt = abstract_program_state(raw, profile, frames=_frames())
    outcome = _run(raw, profile)
    assert receipt.raw_execution_state_cid == raw.program_execution_state_cid
    assert receipt.abstract_program_state_cid != raw.program_execution_state_cid
    assert receipt.canonical_abstract_state_cid != raw.program_execution_state_cid
    assert (
        outcome.abstract_program_state.abstraction_profile_cid
        == profile.abstraction_profile_cid
    )
    raw_identity = RawExecutionStateIdentity.from_dict(raw.to_identity_record())
    abstract_identity = AbstractExecutionStateIdentity.from_dict(
        outcome.abstract_program_state.to_identity_record()
    )
    assert raw_identity.raw_execution_state_cid != abstract_identity.abstract_execution_state_cid
    assert "abstraction_profile_cid" not in raw_identity.identity_payload()
    execution_receipt = ProgramStateAbstractor(profile).to_execution_receipt(
        raw, frames=_frames()
    )
    assert execution_receipt.raw_execution_state_cid == raw.program_execution_state_cid
    assert execution_receipt.abstract_program_state_cid == receipt.abstract_program_state_cid


def test_unavailable_dimensions_propagate_and_refuse_reuse() -> None:
    profile = admitted_abstraction_profile(QueryFamily.REPAIR)
    incomplete = assemble_program_execution_state(
        capture_profile_cid=_capture(),
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        frames=_frames(),
        observed_state={
            "callee": "pkg.mod.pong",
            "locals": {"x": 1},
            "exception_type": "ValueError",
            "contract_state": {"pre": "x > 0"},
            "failing_locals": {"x": 1},
            "handler_kind": "except",
        },
        heap_bound=HeapBound.UNAVAILABLE,
        unavailable_dimensions=("heap",),
        completeness_claim=CompletenessClaim.PARTIAL,
        observation_status=ObservationStatus.UNAVAILABLE,
    )
    outcome = _run(incomplete, profile)
    assert "heap" in outcome.receipt.unavailable_dimensions
    assert outcome.reuse_admitted is False
    assert outcome.soundness.reuse_admitted is False
    assert outcome.canonical_abstract_state.completeness_claim != CompletenessClaim.FULL_STATE.value
    mystery = _state(
        observed_state={
            **_thaw_observed(_state()),
            "mystery_scratch": {"n": 1},
        }
    )
    widened = _run(mystery, admitted_abstraction_profile(QueryFamily.NEXT_CALL))
    assert "mystery_scratch" in widened.soundness.unknown_relevance_dimensions
    assert "mystery_scratch" in widened.receipt.unavailable_dimensions
    assert "mystery_scratch" not in widened.canonical_abstract_state.abstract_state
    assert widened.reuse_admitted is False
    assert widened.soundness.soundness_claim == AbstractionSoundnessClaim.UNKNOWN.value


def test_unproved_heap_and_value_omission_cannot_admit_reuse() -> None:
    with pytest.raises(ProgramAbstractionError, match="unproved heap omission"):
        admitted_abstraction_profile(
            QueryFamily.REPAIR,
            irrelevant_normalizations=(
                "addresses",
                "ids",
                "order",
                "paths",
                "timestamps",
                "heap_regions",
            ),
            omitted_heap_regions=("scratch",),
            heap_omission_proved=False,
        )
    with pytest.raises(ProgramAbstractionError, match="unproved value omission"):
        admitted_abstraction_profile(
            QueryFamily.NEXT_CALL,
            irrelevant_normalizations=(
                "addresses",
                "ids",
                "order",
                "paths",
                "timestamps",
                "values",
            ),
            omitted_value_paths=("locals.tmp",),
            value_omission_proved=False,
        )
    with pytest.raises(ProgramAbstractionError, match="reuse is not admitted"):
        admitted_abstraction_profile(
            QueryFamily.NEXT_CALL,
            soundness_claim=AbstractionSoundnessClaim.UNKNOWN,
            reuse_admitted=True,
        )
    proved_heap = admitted_abstraction_profile(
        QueryFamily.REPAIR,
        irrelevant_normalizations=(
            "addresses",
            "heap_regions",
            "ids",
            "order",
            "paths",
            "timestamps",
        ),
        omitted_heap_regions=("scratch",),
        heap_omission_proved=True,
        soundness_claim=AbstractionSoundnessClaim.OVER_APPROXIMATION,
        reuse_admitted=True,
    )
    raw = _state()
    with_scratch = _run(raw, proved_heap)
    without_region = _run(
        _state(heap_summary={"objects": _thaw_heap_objects(raw), "other": {"n": 1}}),
        proved_heap,
    )
    assert "scratch" not in with_scratch.canonical_abstract_state.abstract_state["heap_summary"]
    assert with_scratch.reuse_admitted is True
    assert (
        with_scratch.canonical_abstract_state_cid
        != without_region.canonical_abstract_state_cid
    )


def _thaw_heap_objects(state: ProgramExecutionState) -> list[Any]:
    return _thaw(state.heap_summary)["objects"]


def test_unsound_profiles_fail_closed() -> None:
    with pytest.raises(ProgramAbstractionError, match="missing required relevant dimension"):
        StateAbstractionProfile(
            language="python",
            profile_name="broken-next-call",
            query_family=QueryFamily.NEXT_CALL,
            relevant_dimensions=("code_cid",),
        )
    with pytest.raises(ProgramAbstractionError, match="order cannot be normalized"):
        admitted_abstraction_profile(
            QueryFamily.INVERSE_TRACE,
            irrelevant_normalizations=("addresses", "ids", "order", "paths", "timestamps"),
        )
    with pytest.raises(ProgramAbstractionError, match="cannot claim exact"):
        admitted_abstraction_profile(
            QueryFamily.NEXT_CALL,
            soundness_claim=AbstractionSoundnessClaim.EXACT,
        )
    exact = StateAbstractionProfile(
        language="python",
        profile_name="exact-next-call",
        query_family=QueryFamily.NEXT_CALL,
        relevant_dimensions=FAMILY_DEFAULT_RELEVANT["next_call"],
        irrelevant_normalizations=(),
        soundness_claim=AbstractionSoundnessClaim.EXACT,
        reuse_admitted=True,
    )
    with pytest.raises(ProgramAbstractionError, match="exact soundness cannot widen"):
        _run(
            _state(observed_state={**_thaw_observed(_state()), "mystery_scratch": 1}),
            exact,
        )
    with pytest.raises(ProgramAbstractionError, match="typed unavailable"):
        admitted_abstraction_profile(QueryFamily.NEXT_CALL, language="javascript")
    with pytest.raises(ProgramAbstractionError, match="similarity"):
        admitted_abstraction_profile("nearest")
    with pytest.raises(ProgramAbstractionError, match="unknown fields|non-semantic"):
        StateAbstractionProfile.from_dict(
            {**admitted_abstraction_profile(QueryFamily.NEXT_CALL).to_dict(), "embedding": [0]}
        )
    with pytest.raises(ProgramAbstractionError, match="unknown fields"):
        StateAbstractionProfile.from_dict(
            {**admitted_abstraction_profile(QueryFamily.NEXT_CALL).to_dict(), "not_a_field": 1}
        )


def test_uncertainty_fails_closed_for_missing_family_slice() -> None:
    profile = admitted_abstraction_profile(QueryFamily.INVERSE_TRACE)
    missing = assemble_program_execution_state(
        capture_profile_cid=_capture(),
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        frames=_frames(),
        observed_state={
            "callee": "pkg.mod.pong",
            "locals": {"x": 1},
            "assignments": [{"target": "x", "value": 1}],
            "exception_type": "ValueError",
            "handler_kind": "except",
        },
    )
    outcome = ProgramStateAbstractor(profile).abstract(missing, frames=_frames(), events=())
    assert "event_order" in outcome.receipt.unavailable_dimensions
    assert outcome.reuse_admitted is False
    assert outcome.canonical_abstract_state.completeness_claim != CompletenessClaim.FULL_STATE.value


def test_receipts_and_soundness_round_trip_and_reject_forged_cids() -> None:
    profile = admitted_abstraction_profile(QueryFamily.NEXT_EVENT)
    outcome = _run(_state(), profile)
    receipt = StateAbstractionReceipt.from_dict(outcome.receipt.to_dict())
    soundness = AbstractionSoundnessResult.from_dict(outcome.soundness.to_dict())
    canonical = CanonicalAbstractState.from_dict(outcome.canonical_abstract_state.to_dict())
    restored_profile = StateAbstractionProfile.from_dict(profile.to_dict())
    assert receipt.state_abstraction_receipt_cid == outcome.receipt.state_abstraction_receipt_cid
    assert soundness.abstraction_soundness_result_cid == outcome.soundness.abstraction_soundness_result_cid
    assert canonical.canonical_abstract_state_cid == outcome.canonical_abstract_state_cid
    assert restored_profile.abstraction_profile_cid == profile.abstraction_profile_cid
    assert decode_program_abstraction_record(profile.to_dict()).abstraction_profile_cid == (
        profile.abstraction_profile_cid
    )
    forged = dict(outcome.receipt.to_dict())
    forged["state_abstraction_receipt_cid"] = _cid("forged")
    with pytest.raises(ProgramAbstractionError, match="does not verify"):
        StateAbstractionReceipt.from_dict(forged)
    with pytest.raises(ProgramAbstractionError, match="unsupported program-abstraction schema"):
        decode_program_abstraction_record({"schema": "not-a-payload", "x": 1})
    assert outcome.receipt.canonical_bytes() == canonical_program_abstraction_bytes(
        outcome.receipt.identity_payload()
    )
    assert outcome.receipt.state_abstraction_receipt_cid == program_abstraction_cid_for(
        outcome.receipt.identity_payload()
    )
    assert decode_and_recompute_structured(
        profile.abstraction_profile_cid, profile.identity_payload()
    )


def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected() -> None:
    with pytest.raises(ProgramAbstractionError, match="duplicate JSON key"):
        loads_program_abstraction_json('{"a":1,"a":2}')
    with pytest.raises(ProgramAbstractionError, match="nonfinite"):
        loads_program_abstraction_json("NaN")
    with pytest.raises(ProgramAbstractionError, match="nonfinite"):
        loads_program_abstraction_json("Infinity")
    with pytest.raises(ProgramAbstractionError, match="floats are rejected"):
        loads_program_abstraction_json('{"score":1.5}')
    with pytest.raises(ProgramAbstractionError, match="strict DAG-JSON"):
        canonicalize_program_abstraction_value({"x": 1.5})


def test_payload_schema_validates_closed_records_and_rejects_unknowns() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    payloads = _sample_payloads()
    for payload in payloads:
        validator.validate(payload)
    loaded = load_payload_schema()
    assert loaded["$id"].endswith("program-abstraction.payload.schema.json")
    extra = dict(payloads[0])
    extra["embedding"] = [0, 1]
    assert list(validator.iter_errors(extra))
    bad_version = dict(payloads[0])
    bad_version["schema"] = STATE_ABSTRACTION_PROFILE_SCHEMA.replace("@1", "@99")
    assert list(validator.iter_errors(bad_version))
    assert list(validator.iter_errors({"schema": "not-a-payload", "x": 1}))
    timed = dict(payloads[0])
    timed["timestamp"] = "now"
    assert list(validator.iter_errors(timed))
    inverse = next(
        item
        for item in payloads
        if item.get("query_family") == "inverse_trace" and item.get("schema") == STATE_ABSTRACTION_PROFILE_SCHEMA
    )
    illegal_order = dict(inverse)
    illegal_order["irrelevant_normalizations"] = ["addresses", "order"]
    assert list(validator.iter_errors(illegal_order))
    unknown_reuse = dict(
        next(item for item in payloads if item.get("schema") == ABSTRACTION_SOUNDNESS_RESULT_SCHEMA)
    )
    unknown_reuse["soundness_claim"] = "unknown"
    unknown_reuse["reuse_admitted"] = True
    assert list(validator.iter_errors(unknown_reuse))
    assert SCHEMA_PATH.is_file()
    assert CANONICAL_ABSTRACT_STATE_SCHEMA in json.dumps(schema)


def test_stack_order_and_trace_events_are_preserved_when_relevant() -> None:
    profile = admitted_abstraction_profile(QueryFamily.INVERSE_TRACE)
    inner = _frame(0, "pkg.mod.ping")
    outer = _frame(1, "pkg.mod.caller")
    call = _event("call", frames=(inner, outer))
    ret = _event("return", predecessor=call.program_event_cid, frames=(inner, outer))
    trace = assemble_execution_trace(
        tree_cid=_tree(),
        source_cid=_source(),
        environment_binding_cid=_env(),
        events=[call, ret],
    )
    outcome = ProgramStateAbstractor(profile).abstract(
        _state(), frames=(inner, outer), events=(call, ret), trace=trace
    )
    names = list(outcome.canonical_abstract_state.abstract_state["stack_logical_names"])
    assert names == ["pkg.mod.ping", "pkg.mod.caller"]
    kinds = [
        item["event_kind"]
        for item in outcome.canonical_abstract_state.abstract_state["event_order"]
    ]
    assert kinds == ["call", "return"]
    assert outcome.reuse_admitted is True


def test_admitted_profiles_are_query_family_specific() -> None:
    for family in QUERY_FAMILIES:
        profile = admitted_abstraction_profile(family)
        assert profile.query_family == family
        assert set(FAMILY_DEFAULT_RELEVANT[family]) <= set(profile.relevant_dimensions)
        raw = _state()
        receipt = abstract_program_state(raw, profile, frames=_frames())
        assert receipt.query_family == family
        assert receipt.reuse_admitted is True
        assert ProgramLanguage.PYTHON.value == "python"
