"""Unit tests for SessionProcessLogic@1 (LFP2-043).

Evidence subset:

* linear resources, tensor/lolli/with/plus/ofcourse
* session actions, channel polarity, duality (involution)
* process composition, process scope, progress model
* relational refinement direction
* resource duplication is never silently normalized
* parse/print/parse semantic round-trip
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.session_process import (
    CODE_OPERATOR_FORBIDDEN,
    CODE_PROCESS_SCOPE,
    CODE_PROGRESS_MISMATCH,
    CODE_PROGRESS_REQUIRED,
    CODE_REFINEMENT_DIRECTION,
    CODE_REFINEMENT_DIRECTION_MISMATCH,
    CODE_RESOURCE_DUPLICATION,
    LINEAR_FAMILY_ID,
    PROCESS_FAMILY_ID,
    REFINEMENT_FAMILY_ID,
    SESSION_FAMILY_ID,
    SESSION_PROCESS_LOGIC_INTERFACE,
    SESSION_PROCESS_PROFILE_INTERFACE,
    DualityReport,
    LinearityMode,
    LinearityReport,
    ProgressModel,
    RefinementDirectionKind,
    SessionProcessFamilyKind,
    SessionProcessLogic,
    SessionProcessLogicProfile,
    SessionProcessParser,
    SessionProcessPrinter,
    check_duality,
    check_linearity,
    check_process_scope,
    check_progress_model,
    check_refinement_direction,
    collect_resource_names,
    dualize_session_ast,
    parse_print_parse,
    parse_session_process,
    print_session_process,
    profile_linear,
    profile_process,
    profile_relational_refinement,
    profile_session,
    session_process_semantic_identity,
)
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseStatus,
    SyntaxContractError,
)


def _linear():
    return profile_linear()


def _session():
    return profile_session()


def _process():
    return profile_process()


def _refinement():
    return profile_relational_refinement()


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert SESSION_PROCESS_LOGIC_INTERFACE == "SessionProcessLogic@1"
    assert SESSION_PROCESS_PROFILE_INTERFACE == "SessionProcessLogicProfile@1"
    assert LINEAR_FAMILY_ID == "linear_logic"
    assert SESSION_FAMILY_ID == "session_process"
    assert PROCESS_FAMILY_ID == "process_calculus"
    assert REFINEMENT_FAMILY_ID == "refinement"

    logic = SessionProcessLogic(_session())
    assert logic.interface == SESSION_PROCESS_LOGIC_INTERFACE
    assert isinstance(logic.parser, SessionProcessParser)
    assert isinstance(logic.printer, SessionProcessPrinter)


def test_profiles_expose_linearity_duality_progress_direction() -> None:
    linear = _linear()
    assert linear.family is SessionProcessFamilyKind.LINEAR
    assert linear.family_id == LINEAR_FAMILY_ID
    assert linear.linearity_mode is LinearityMode.STRICT
    assert linear.reject_resource_duplication is True
    assert linear.semantic_identity["silent_resource_duplication_normalized"] is False

    session = _session()
    assert session.family is SessionProcessFamilyKind.SESSION
    assert session.admit_duality is True
    assert session.admit_session_actions is True

    process = _process()
    assert process.family is SessionProcessFamilyKind.PROCESS
    assert process.progress_model_kind is ProgressModel.FAIR
    assert process.require_progress_model is True
    assert process.enforce_process_scope is True

    refinement = _refinement()
    assert refinement.family is SessionProcessFamilyKind.RELATIONAL_REFINEMENT
    assert refinement.refinement_direction_kind is RefinementDirectionKind.FORWARD
    assert refinement.require_refinement_direction is True

    identity = session_process_semantic_identity(process)
    assert identity["progress_model"] == "fair"
    assert identity["family_id"] == PROCESS_FAMILY_ID


def test_profile_rejects_inconsistent_flags() -> None:
    with pytest.raises(SyntaxContractError, match="admit_linear_connectives"):
        SessionProcessLogicProfile(
            profile_id="bad_linear",
            family=SessionProcessFamilyKind.LINEAR,
            admit_linear_connectives=False,
        )
    with pytest.raises(SyntaxContractError, match="admit_duality"):
        SessionProcessLogicProfile(
            profile_id="bad_session",
            family=SessionProcessFamilyKind.SESSION,
            admit_session_actions=True,
            admit_duality=False,
        )
    with pytest.raises(SyntaxContractError, match="progress_model"):
        SessionProcessLogicProfile(
            profile_id="bad_process",
            family=SessionProcessFamilyKind.PROCESS,
            admit_process_composition=True,
            require_progress_model=True,
            progress_model=ProgressModel.NONE,
        )
    with pytest.raises(SyntaxContractError, match="refinement_direction"):
        SessionProcessLogicProfile(
            profile_id="bad_ref",
            family=SessionProcessFamilyKind.RELATIONAL_REFINEMENT,
            admit_refinement=True,
            require_refinement_direction=True,
            refinement_direction=RefinementDirectionKind.NONE,
        )


# ---------------------------------------------------------------------------
# Linear resources / linearity
# ---------------------------------------------------------------------------


def test_parse_linear_resource_tensor_lolli() -> None:
    result = parse_session_process(
        "resource(a) * resource(b) -o resource(c)",
        _linear(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "lolli"
    assert result.linearity is not None
    assert result.linearity.ok is True
    printed = print_session_process(result.root)
    assert "resource(a)" in printed
    assert "resource(b)" in printed
    assert "-o" in printed or "⊸" in printed


def test_parse_linear_with_plus_ofcourse() -> None:
    result = parse_session_process(
        "ofcourse resource(a) with resource(b) plus resource(c)",
        _linear(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "with"


def test_resource_duplication_not_silently_normalized() -> None:
    """Acceptance: resource duplication is never silently normalized."""

    result = parse_session_process(
        "resource(r) * resource(r)",
        _linear(),
    )
    assert not result.ok
    codes = {d.code for d in result.diagnostics}
    assert CODE_RESOURCE_DUPLICATION in codes
    assert result.root is not None
    # Multiplicity is preserved on the AST — not collapsed to one resource.
    names = collect_resource_names(result.root)
    assert names.count("r") == 2
    assert result.linearity is not None
    assert result.linearity.ok is False
    assert result.linearity.silently_normalized is False
    assert "r" in result.linearity.duplicated
    assert result.linearity.resource_counts["r"] == 2


def test_explicit_dup_rejected_under_linear_profile() -> None:
    result = parse_session_process("dup(r)", _linear())
    assert not result.ok
    codes = {d.code for d in result.diagnostics}
    assert CODE_RESOURCE_DUPLICATION in codes
    assert any("not silently normalized" in d.message for d in result.diagnostics)


def test_unrestricted_profile_allows_duplication_without_normalization_flag() -> None:
    # Affine/unrestricted still records multiplicity; never claims silent normalize.
    prof = SessionProcessLogicProfile(
        profile_id="linear_unrestricted",
        family=SessionProcessFamilyKind.LINEAR,
        linearity=LinearityMode.UNRESTRICTED,
        reject_resource_duplication=False,
        admit_linear_connectives=True,
        admit_session_actions=False,
        admit_process_composition=False,
        admit_refinement=False,
        admit_duality=False,
    )
    result = parse_session_process("resource(r) * resource(r)", prof)
    assert result.ok, [d.message for d in result.diagnostics]
    names = collect_resource_names(result.root)  # type: ignore[arg-type]
    assert names.count("r") == 2  # still not collapsed
    assert result.linearity is not None
    assert result.linearity.silently_normalized is False
    assert result.linearity.resource_counts["r"] == 2


def test_check_linearity_helper() -> None:
    result = parse_session_process(
        "resource(a) * resource(b)",
        _linear(),
        run_checks=False,
    )
    assert result.root is not None
    report = check_linearity(result.root, _linear())
    assert isinstance(report, LinearityReport)
    assert report.ok is True
    assert report.resource_counts == {"a": 1, "b": 1}


# ---------------------------------------------------------------------------
# Session / duality
# ---------------------------------------------------------------------------


def test_parse_session_send_recv_end() -> None:
    result = parse_session_process("!req(Msg). ?ack(Msg). end", _session())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "session_action"
    assert result.root.extension.payload["polarity"] == "send"
    printed = print_session_process(result.root)
    assert "!req" in printed
    assert "?ack" in printed
    assert "end" in printed


def test_parse_session_tau_and_dual() -> None:
    result = parse_session_process("dual(!req(Msg). end)", _session())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "dual"
    assert result.duality is not None
    assert result.duality.ok is True
    assert result.duality.involutive is True
    assert result.duality.polarity_flipped is True


def test_session_duality_involution() -> None:
    result = parse_session_process(
        "!req(Msg). ?ack(Unit). end",
        _session(),
        run_checks=False,
    )
    assert result.root is not None
    dual_once = dualize_session_ast(result.root)
    dual_twice = dualize_session_ast(dual_once)
    # dual twice recovers original polarities structurally
    report = check_duality(result.root, _session())
    assert isinstance(report, DualityReport)
    assert report.ok is True
    assert report.involutive is True
    # First dual flips send->receive
    assert dual_once.extension is not None
    assert dual_once.extension.payload["polarity"] == "receive"
    # Second dual recovers send
    assert dual_twice.extension is not None
    assert dual_twice.extension.payload["polarity"] == "send"


def test_session_construct_forbidden_under_linear_profile() -> None:
    result = parse_session_process("!req(Msg). end", _linear())
    assert not result.ok
    codes = {d.code for d in result.diagnostics}
    assert CODE_OPERATOR_FORBIDDEN in codes


# ---------------------------------------------------------------------------
# Process scope / progress model
# ---------------------------------------------------------------------------


def test_parse_process_par_new_nil() -> None:
    result = parse_session_process(
        "par(new(c). chan(c), nil)",
        _process(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "par"
    assert result.process_scope is not None
    assert result.process_scope.ok is True
    assert result.progress is not None
    assert result.progress.ok is True
    assert result.progress.profile_model == "fair"


def test_free_channel_fails_process_scope() -> None:
    result = parse_session_process("par(chan(c), nil)", _process())
    assert not result.ok
    codes = {d.code for d in result.diagnostics}
    assert CODE_PROCESS_SCOPE in codes
    assert result.process_scope is not None
    assert result.process_scope.ok is False
    assert "c" in result.process_scope.free_channels


def test_bound_channel_under_new_is_scoped() -> None:
    result = parse_session_process("new(c). chan(c)", _process())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.process_scope is not None
    assert result.process_scope.ok is True
    assert "c" in result.process_scope.bound_channels
    assert result.process_scope.free_channels == ()


def test_progress_model_surface_must_agree() -> None:
    result = parse_session_process(
        "par(progress(unfair), nil)",
        _process(),
    )
    assert not result.ok
    codes = {d.code for d in result.diagnostics}
    assert CODE_PROGRESS_MISMATCH in codes or CODE_PROGRESS_REQUIRED in codes
    assert result.progress is not None
    assert result.progress.ok is False


def test_progress_model_matching_surface_ok() -> None:
    result = parse_session_process(
        "par(progress(fair), nil)",
        _process(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.progress is not None
    assert result.progress.ok is True
    assert "fair" in result.progress.surface_models


def test_check_process_scope_helper() -> None:
    free = parse_session_process(
        "chan(x)",
        _process(),
        run_checks=False,
    )
    assert free.root is not None
    report = check_process_scope(free.root, _process())
    assert report.ok is False
    assert "x" in report.free_channels


def test_check_progress_model_helper() -> None:
    result = parse_session_process("nil", _process(), run_checks=False)
    assert result.root is not None
    report = check_progress_model(result.root, _process())
    assert report.ok is True
    assert report.profile_model == "fair"


# ---------------------------------------------------------------------------
# Relational refinement direction
# ---------------------------------------------------------------------------


def test_parse_refines_with_explicit_direction() -> None:
    result = parse_session_process(
        "refines(abs, conc, forward)",
        _refinement(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "refines"
    assert result.root.extension.payload["direction"] == "forward"
    assert result.refinement_direction is not None
    assert result.refinement_direction.ok is True
    printed = print_session_process(result.root)
    assert "refines(abs, conc, forward)" in printed


def test_parse_simulates_backward() -> None:
    prof = profile_relational_refinement(
        refinement_direction=RefinementDirectionKind.BACKWARD,
    )
    result = parse_session_process("simulates(abs, conc, backward)", prof)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["direction"] == "backward"


def test_refinement_direction_mismatch_fails() -> None:
    result = parse_session_process(
        "refines(abs, conc, backward)",
        _refinement(),  # default forward required
    )
    assert not result.ok
    codes = {d.code for d in result.diagnostics}
    assert CODE_REFINEMENT_DIRECTION_MISMATCH in codes or (
        CODE_REFINEMENT_DIRECTION in codes
    )
    assert result.refinement_direction is not None
    assert result.refinement_direction.ok is False


def test_refinement_fills_direction_from_profile_when_omitted() -> None:
    result = parse_session_process("refines(abs, conc)", _refinement())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["direction"] == "forward"
    # Printer re-emits explicit direction for round-trip.
    printed = print_session_process(result.root)
    assert "forward" in printed


def test_two_state_relational_binding() -> None:
    result = parse_session_process(
        "forall_states a, c. refines(a, c, forward)",
        _refinement(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "two_state"


def test_check_refinement_direction_helper() -> None:
    result = parse_session_process(
        "refines(abs, conc, forward)",
        _refinement(),
        run_checks=False,
    )
    assert result.root is not None
    report = check_refinement_direction(result.root, _refinement())
    assert report.ok is True
    assert "forward" in report.surface_directions


# ---------------------------------------------------------------------------
# Round-trip / cross-profile
# ---------------------------------------------------------------------------


def test_parse_print_parse_linear_round_trip() -> None:
    first, second, equivalent = parse_print_parse(
        "resource(a) * resource(b) -o resource(c)",
        _linear(),
    )
    assert first.ok and second.ok
    assert equivalent is True
    assert first.root is not None and second.root is not None
    assert alpha_equivalent(first.root, second.root)


def test_parse_print_parse_session_round_trip() -> None:
    first, second, equivalent = parse_print_parse(
        "!req(Msg). ?ack(Unit). end",
        _session(),
    )
    assert first.ok and second.ok
    assert equivalent is True


def test_parse_print_parse_process_round_trip() -> None:
    first, second, equivalent = parse_print_parse(
        "par(new(c). chan(c), progress(fair))",
        _process(),
    )
    assert first.ok and second.ok, (
        [d.message for d in first.diagnostics]
        + [d.message for d in second.diagnostics]
    )
    assert equivalent is True


def test_parse_print_parse_refinement_round_trip() -> None:
    first, second, equivalent = parse_print_parse(
        "refines(abs, conc, forward)",
        _refinement(),
    )
    assert first.ok and second.ok
    assert equivalent is True


def test_empty_input_rejected() -> None:
    result = parse_session_process("", _session())
    assert not result.ok
    assert result.status is ParseStatus.REJECTED


def test_facade_check_methods() -> None:
    logic = SessionProcessLogic(_session())
    result = logic.parse_text("!ping(Unit). end")
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert logic.check_duality(result.root).ok is True
    assert logic.check_linearity(result.root).ok is True

    linear_logic = SessionProcessLogic(_linear())
    lin = linear_logic.parse_text("resource(a) * resource(b)")
    assert lin.ok
    assert lin.root is not None
    assert linear_logic.check_linearity(lin.root).ok is True
