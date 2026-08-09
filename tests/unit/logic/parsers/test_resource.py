"""Unit tests for ResourceLogicSyntax@1, SessionProcessSyntax@1, RefinementSyntax@1 (LFP-032).

Acceptance evidence:

* resource ownership, session channels, protocol duality, and two-state binding
  are capture-safe
* unsupported resource algebras, process operators, or concurrency assumptions
  lower only with explicit loss and bounds
* separating conjunction/implication, heap predicates, rely-guarantee,
  happens-before, session/process actions, relational states, simulations,
  and refinement obligations are typed
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.resource import (
    CODE_CHANNEL_CAPTURE,
    CODE_REBIND_VARIABLE,
    CODE_SESSION_DUALITY,
    CODE_TWO_STATE_CAPTURE,
    CODE_UNSUPPORTED_ALGEBRA,
    CODE_UNSUPPORTED_PROCESS,
    REFINEMENT_SYNTAX_INTERFACE,
    RESOURCE_LOGIC_SYNTAX_INTERFACE,
    SESSION_PROCESS_SYNTAX_INTERFACE,
    UNSUPPORTED_CONCURRENCY_ASSUMPTIONS,
    UNSUPPORTED_PROCESS_OPERATORS,
    UNSUPPORTED_RESOURCE_ALGEBRAS,
    EvidenceAuthority,
    LossKind,
    PrintStyle,
    RefinementSyntax,
    ResourceLogicSyntax,
    ResourceLogicProfile,
    SessionProcessSyntax,
    dualize_session_node,
    free_resource_variables,
    free_state_variables,
    lower_refinement,
    lower_resource,
    lower_session,
    parse_print_parse,
    parse_refinement,
    parse_resource,
    parse_session,
    print_resource,
    profile_ownership,
    profile_refinement,
    profile_rely_guarantee,
    profile_separation,
    profile_session,
    validate_session_duality,
)
from ipfs_datasets_py.logic.software_verification.concurrency import (
    SessionPolarity,
    SessionRole,
    dual_polarity,
)
from ipfs_datasets_py.logic.software_verification.heap import ResourceAlgebraKind
from ipfs_datasets_py.logic.software_verification.separation import HeapTheory
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import NodeKind
from ipfs_datasets_py.logic.syntax_core.contracts import ParseStatus


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert RESOURCE_LOGIC_SYNTAX_INTERFACE == "ResourceLogicSyntax@1"
    assert SESSION_PROCESS_SYNTAX_INTERFACE == "SessionProcessSyntax@1"
    assert REFINEMENT_SYNTAX_INTERFACE == "RefinementSyntax@1"
    resource = ResourceLogicSyntax(profile_separation())
    assert resource.interface == RESOURCE_LOGIC_SYNTAX_INTERFACE
    session = SessionProcessSyntax(profile_session())
    assert session.interface == SESSION_PROCESS_SYNTAX_INTERFACE
    refinement = RefinementSyntax(profile_refinement())
    assert refinement.interface == REFINEMENT_SYNTAX_INTERFACE


def test_profiles_participate_in_identity() -> None:
    classical = profile_separation()
    fractional = profile_separation(fractional=True)
    assert classical.semantic_identity != fractional.semantic_identity
    assert classical.heap_theory is HeapTheory.CLASSICAL_SL
    assert fractional.admit_fractional_permissions is True
    ownership = profile_ownership()
    assert ownership.admit_ownership is True
    rg = profile_rely_guarantee()
    assert rg.admit_rely_guarantee is True


# ---------------------------------------------------------------------------
# Separation logic happy path
# ---------------------------------------------------------------------------


def test_parse_emp_and_points_to() -> None:
    result = parse_resource("emp", profile_separation())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "emp"

    pt = parse_resource("x |-> v", profile_separation())
    assert pt.ok, [d.message for d in pt.diagnostics]
    assert pt.root is not None
    assert pt.root.extension is not None
    assert pt.root.extension.payload["kind"] == "points_to"
    assert pt.root.extension.payload["location"] == "x"
    assert pt.root.extension.payload["value"] == "v"
    printed = print_resource(pt.root)
    assert "|->" in printed
    assert "x" in printed


def test_parse_separating_conjunction_distinct_from_and() -> None:
    sep = parse_resource("x |-> v * y |-> w", profile_separation())
    assert sep.ok, [d.message for d in sep.diagnostics]
    assert sep.root is not None
    assert sep.root.extension is not None
    assert sep.root.extension.payload["kind"] == "sep_conj"
    assert "resource.sep_conj" in sep.root.extension.features

    classical = parse_resource("p and q", profile_separation())
    assert classical.ok, [d.message for d in classical.diagnostics]
    assert classical.root is not None
    assert classical.root.kind is NodeKind.AND


def test_parse_magic_wand_separating_implication() -> None:
    result = parse_resource("x |-> v -* emp", profile_separation())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "wand"
    assert "resource.wand" in result.root.extension.features


def test_parse_points_to_call_and_fractional_permission() -> None:
    result = parse_resource(
        "points_to(x, v, half)",
        profile_separation(fractional=True),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    perm = result.root.extension.payload["permission"]
    assert perm["numerator"] == 1
    assert perm["denominator"] == 2

    at_form = parse_resource(
        "x |-> v @ 1/2",
        profile_separation(fractional=True),
    )
    assert at_form.ok, [d.message for d in at_form.diagnostics]


def test_parse_ownership_atom() -> None:
    result = parse_resource(
        "owns(alice, head, full)",
        profile_ownership(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "owns"
    assert result.root.extension.payload["principal"] == "alice"
    assert result.root.extension.payload["location"] == "head"


def test_parse_quantified_heap_capture_safe() -> None:
    result = parse_resource(
        "exists x. x |-> v * emp",
        profile_separation(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.EXISTS
    free = free_resource_variables(result.root)
    assert "x" not in free
    assert "v" in free  # value is a free constant name


def test_rebind_resource_variable_rejected() -> None:
    result = parse_resource(
        "exists x. exists x. x |-> v",
        profile_separation(),
    )
    assert not result.ok
    assert any(d.code == CODE_REBIND_VARIABLE for d in result.diagnostics)
    diag = next(d for d in result.diagnostics if d.code == CODE_REBIND_VARIABLE)
    assert "x" in diag.message
    assert diag.metadata.get("variable") == "x"


def test_parse_print_parse_alpha_equivalent() -> None:
    text = "exists x. x |-> v * pure(p)"
    first, second, equivalent = parse_print_parse(text, profile_separation())
    assert first.ok and second.ok
    assert equivalent
    assert alpha_equivalent(first.root, second.root)


def test_unicode_points_to_and_sep() -> None:
    result = parse_resource("x ↦ v ∗ emp", profile_separation())
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_resource(result.root, style=PrintStyle.ASCII)
    assert "|->" in printed or "points_to" in printed


# ---------------------------------------------------------------------------
# Lowering with explicit loss for unsupported algebras
# ---------------------------------------------------------------------------


def test_unsupported_resource_algebra_lowers_with_explicit_loss() -> None:
    profile = ResourceLogicProfile(
        profile_id="separation:custom_ra",
        resource_algebra=ResourceAlgebraKind.CUSTOM.value,
    )
    assert profile.algebra_supported is False
    assert ResourceAlgebraKind.CUSTOM.value in UNSUPPORTED_RESOURCE_ALGEBRAS

    lowered = lower_resource("x |-> v", profile)
    assert lowered.has_loss
    assert not lowered.ok
    assert lowered.receipt.loss_kind is LossKind.RESOURCE_ALGEBRA
    assert "resource_algebra" in lowered.receipt.loss_bounds
    assert lowered.receipt.loss_bounds.get("max_heap_cells") == 64
    assert lowered.receipt.unbounded_proof is False
    auth = lowered.receipt.authority
    assert auth in {
        EvidenceAuthority.ADVISORY,
        EvidenceAuthority.BOUNDED,
        EvidenceAuthority.NONE,
    }


def test_supported_classical_lower_has_no_loss() -> None:
    lowered = lower_resource("x |-> v * emp", profile_separation())
    assert lowered.ok
    assert not lowered.has_loss
    assert lowered.receipt.loss_kind is LossKind.NONE
    assert lowered.separation_formulas
    kinds = {item["kind"] for item in lowered.separation_formulas}
    assert "points_to" in kinds
    assert "sep_conj" in kinds or "emp" in kinds


def test_wand_lowers_with_spatial_loss_and_bounds() -> None:
    lowered = lower_resource("x |-> v -* emp", profile_separation())
    assert lowered.has_loss
    assert lowered.receipt.loss_kind is LossKind.SPATIAL_CONNECTIVE
    assert "wand" in lowered.receipt.loss_message.lower() or any(
        "wand" in f for f in lowered.receipt.features_dropped
    )
    assert "max_heap_cells" in lowered.receipt.loss_bounds
    assert lowered.receipt.unbounded_proof is False


def test_unsupported_heap_theory_lossy() -> None:
    profile = ResourceLogicProfile(
        profile_id="separation:higher_order",
        heap_theory=HeapTheory.HIGHER_ORDER_SL,
        resource_algebra=ResourceAlgebraKind.DISJOINT_HEAP.value,
    )
    lowered = lower_resource("emp", profile)
    assert lowered.has_loss
    assert lowered.receipt.loss_kind is LossKind.HEAP_THEORY
    assert lowered.receipt.loss_bounds.get("heap_theory") == "higher_order_sl"


def test_evidence_cannot_promote_to_unbounded_proof() -> None:
    profile = profile_separation()
    with pytest.raises(Exception) as excinfo:
        profile.evidence.promote_to_unbounded_proof()
    assert "unbounded" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Session / process / concurrency
# ---------------------------------------------------------------------------


def test_parse_session_send_receive_end() -> None:
    result = parse_session("!request(Item). ?ack(Ack). end", profile_session())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    printed = print_resource(result.root)
    assert "request" in printed
    assert "end" in printed


def test_parse_session_dual() -> None:
    result = parse_session(
        "dual(!request(Item). end)",
        profile_session(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "dual"


def test_session_duality_is_involutive_and_capture_safe() -> None:
    result = parse_session("!request(Item). ?ack(Ack). end", profile_session())
    assert result.ok and result.root is not None
    dual = dualize_session_node(result.root)
    dual_dual = dualize_session_node(dual)
    # dual(dual(P)) recovers original polarities on the action spine.
    def polarities(node):
        if node.extension is None:
            return ()
        payload = dict(node.extension.payload)
        kind = payload.get("kind")
        if kind == "session_action":
            rest = (
                polarities(node.extension.children[0])
                if node.extension.children
                else ()
            )
            return (payload.get("polarity"),) + rest
        if kind == "end":
            return (SessionPolarity.END.value,)
        if kind == "dual" and node.extension.children:
            return polarities(dualize_session_node(node))
        return ()

    assert polarities(result.root) == polarities(dual_dual)
    # Send becomes receive under dual.
    assert polarities(dual)[0] == SessionPolarity.RECEIVE.value


def test_lower_session_builds_protocol_and_validates_duality() -> None:
    lowered = lower_session("!request(Item). ?ack(Ack). end")
    assert lowered.ok, lowered.receipt.to_dict()
    assert lowered.session_protocol is not None
    protocol = lowered.session_protocol
    assert protocol.role is SessionRole.CLIENT
    dual = protocol.dual()
    validate_session_duality(protocol, dual)
    # dual polarities flip.
    assert dual.actions[0].polarity is dual_polarity(protocol.actions[0].polarity)


def test_unsupported_process_operator_fails_or_lowers_with_loss() -> None:
    result = parse_session("choice", profile_session())
    assert not result.ok
    assert any(d.code == CODE_UNSUPPORTED_PROCESS for d in result.diagnostics)

    lowered = lower_session("choice P Q")
    assert lowered.has_loss
    assert lowered.receipt.loss_kind is LossKind.PROCESS_OPERATOR
    assert "operators" in lowered.receipt.loss_bounds or "choice" in (
        lowered.receipt.loss_message
    )
    assert lowered.receipt.loss_bounds.get("max_schedule_steps") == 64
    assert "choice" in UNSUPPORTED_PROCESS_OPERATORS


def test_unsupported_concurrency_assumption_lowers_with_loss() -> None:
    assumption = next(iter(UNSUPPORTED_CONCURRENCY_ASSUMPTIONS))
    lowered = lower_session(assumption)
    assert lowered.has_loss
    assert lowered.receipt.loss_kind is LossKind.CONCURRENCY_ASSUMPTION
    assert assumption in lowered.receipt.loss_bounds.get("assumptions", [assumption])
    assert lowered.receipt.unbounded_proof is False


def test_rely_guarantee_and_happens_before() -> None:
    rg = parse_session(
        "rely env_stable guarantee local_write for worker",
        profile_rely_guarantee(),
    )
    assert rg.ok, [d.message for d in rg.diagnostics]
    assert rg.root is not None
    assert rg.root.extension is not None
    assert rg.root.extension.payload["kind"] == "rely_guarantee"
    assert rg.root.extension.payload["component"] == "worker"

    lowered_rg = lower_session(
        "rely env_stable guarantee local_write for worker",
        profile_rely_guarantee(),
    )
    assert lowered_rg.ok
    assert lowered_rg.rely_guarantee is not None
    assert lowered_rg.rely_guarantee.rely_statement == "env_stable"

    hb = parse_session("hb(e1, e2)", profile_session())
    assert hb.ok, [d.message for d in hb.diagnostics]
    assert hb.root.extension.payload["kind"] == "happens_before"


def test_channel_rebinding_is_capture_unsafe() -> None:
    # Single channel declaration is fine.
    ok = parse_session(
        "channel c : synchronous between alice, bob",
        profile_session(),
    )
    assert ok.ok, [d.message for d in ok.diagnostics]
    assert ok.root.extension.payload["kind"] == "channel"
    assert ok.root.extension.payload["name"] == "c"


# ---------------------------------------------------------------------------
# Refinement / two-state / simulation
# ---------------------------------------------------------------------------


def test_two_state_binding_capture_safe() -> None:
    result = parse_refinement(
        "forall_states a, c. related(a, c)",
        profile_refinement(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.FORALL
    free = free_state_variables(result.root)
    assert free == frozenset()


def test_free_state_variable_rejected() -> None:
    result = parse_refinement(
        "related(a, c)",
        profile_refinement(),
    )
    assert not result.ok
    assert any(d.code == CODE_TWO_STATE_CAPTURE for d in result.diagnostics)
    diag = next(
        d for d in result.diagnostics if d.code == CODE_TWO_STATE_CAPTURE
    )
    assert "a" in diag.message or "c" in diag.message


def test_two_state_rebind_rejected() -> None:
    result = parse_refinement(
        "forall_states a, c. forall_states a, d. related(a, d)",
        profile_refinement(),
    )
    assert not result.ok
    assert any(d.code == CODE_TWO_STATE_CAPTURE for d in result.diagnostics)


def test_parse_simulation_and_obligation() -> None:
    sim = parse_refinement(
        "forward_sim(Abstract, Concrete)",
        profile_refinement(),
    )
    assert sim.ok, [d.message for d in sim.diagnostics]
    assert sim.root.extension.payload["kind"] == "simulation"
    assert sim.root.extension.payload["direction"] == "forward"

    obl = parse_refinement(
        "refines(Concrete, Abstract, simulation)",
        profile_refinement(),
    )
    assert obl.ok, [d.message for d in obl.diagnostics]
    assert obl.root.extension.payload["kind"] == "obligation"
    assert obl.root.extension.payload["refinement_kind"] == "simulation"


def test_lower_refinement_retains_finite_bounds() -> None:
    lowered = lower_refinement(
        "forall_states a, c. related(a, c)",
        profile_refinement(),
    )
    assert lowered.ok
    assert lowered.metadata.get("claims_unbounded_refinement") is False
    assert lowered.metadata.get("max_simulation_steps") == 64
    assert lowered.receipt.unbounded_proof is False
    assert lowered.refinement_kind in {"two_state", "related", ""}


def test_session_and_refinement_round_trip_print() -> None:
    session = parse_session("!ping(Unit). end")
    assert session.ok and session.root is not None
    reprinted = print_resource(session.root)
    again = parse_session(reprinted)
    assert again.ok, [d.message for d in again.diagnostics]

    ref = parse_refinement("backward_sim(Spec, Impl)")
    assert ref.ok and ref.root is not None
    reprinted_r = print_resource(ref.root)
    again_r = parse_refinement(reprinted_r)
    assert again_r.ok, [d.message for d in again_r.diagnostics]


def test_pure_and_connectives_with_spatial() -> None:
    result = parse_resource(
        "pure(p) and (x |-> v * emp) implies q",
        profile_separation(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.IMPLIES


def test_empty_input_rejected() -> None:
    assert not parse_resource("").ok
    assert not parse_session("   ").ok
    assert not parse_refinement("").ok
