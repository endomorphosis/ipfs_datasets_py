"""Contract tests for StructuralAdmission@1 repair admission gates."""

from __future__ import annotations

import pytest

from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRule,
    CanonicalRuleIR,
)
from benchmarks.semantic_roundtrip.selective_repair import (
    DECLARED_STRUCTURAL_CONSTRAINTS,
    StructuralTool,
)
from benchmarks.semantic_roundtrip.structural_admission import (
    DEFAULT_ADMISSION_TIMEOUT_SECONDS,
    STRUCTURAL_ADMISSION_INTERFACE,
    STRUCTURAL_ADMISSION_METRICS_INTERFACE,
    STRUCTURAL_ADMISSION_RECEIPT_INTERFACE,
    STRUCTURAL_ADMISSION_SCHEMA,
    VALIDATOR_REJECT,
    AdmissionDisposition,
    StructuralAdmissionError,
    StructuralAdmissionGate,
    StructuralAdmissionPolicy,
    StructuralAdmissionResult,
    admit_hybrid_repair,
    aggregate_structural_admission_metrics,
    make_error_binding,
    make_passing_binding,
    make_rejecting_binding,
    make_timeout_binding,
)


PRIOR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="",
        ),
    )
)
CANDIDATE = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="records",
        ),
    )
)
VACUOUS = CanonicalRuleIR(())
EXTRA_RULE = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="records",
        ),
        CanonicalRule(
            modality="P",
            actor="processor",
            action="retain",
            object="records",
        ),
    )
)
OBJECT_PATH = "rules[0].object"


def _hammer_pass() -> StructuralAdmissionGate:
    return StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(
            make_passing_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
            ),
        ),
    )


def _lean_pass() -> StructuralAdmissionGate:
    return StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.LEAN,)),
        validators=(
            make_passing_binding(
                validator_id="lean",
                tool=StructuralTool.LEAN,
            ),
        ),
    )


def _both_pass() -> StructuralAdmissionGate:
    return StructuralAdmissionGate(
        StructuralAdmissionPolicy(
            tools=(StructuralTool.HAMMER_CVC5, StructuralTool.LEAN),
        ),
        validators=(
            make_passing_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
            ),
            make_passing_binding(
                validator_id="lean",
                tool=StructuralTool.LEAN,
            ),
        ),
    )


def test_interface_and_policy_constants() -> None:
    assert STRUCTURAL_ADMISSION_INTERFACE == "StructuralAdmission@1"
    assert STRUCTURAL_ADMISSION_RECEIPT_INTERFACE.endswith("Receipt@1")
    assert STRUCTURAL_ADMISSION_METRICS_INTERFACE.endswith("Metrics@1")
    assert STRUCTURAL_ADMISSION_SCHEMA.startswith("ipfs-datasets.")
    assert VALIDATOR_REJECT == "validator_reject"
    assert DEFAULT_ADMISSION_TIMEOUT_SECONDS == 5.0
    policy = StructuralAdmissionPolicy()
    assert policy.tools == (
        StructuralTool.HAMMER_CVC5,
        StructuralTool.LEAN,
    )
    assert policy.structural_constraints == DECLARED_STRUCTURAL_CONSTRAINTS
    assert policy.fail_closed_on_timeout is True
    payload = policy.to_dict()
    assert payload["interface"] == STRUCTURAL_ADMISSION_INTERFACE
    assert policy.digest == policy.digest


def test_accept_admits_candidate_and_records_delta() -> None:
    gate = _both_pass()
    result = gate.admit(
        PRIOR,
        CANDIDATE,
        allowed_field_paths=(OBJECT_PATH,),
    )
    assert result.disposition is AdmissionDisposition.ACCEPTED
    assert result.accepted is True
    assert result.rejected is False
    assert result.admitted_l1 == CANDIDATE
    assert result.prior_l1 == PRIOR
    assert result.prior_l1_unchanged is False
    assert result.rejection_reason is None
    assert result.accepted_repair_delta == 1
    assert result.field_change_count == 1
    assert result.end_to_end_loss is None
    assert len(result.check_receipts) == 2
    assert all(item.passed for item in result.check_receipts)
    assert all(item.semantic_authority is False for item in result.check_receipts)
    payload = result.to_dict()
    assert payload["disposition"] == "accepted"
    assert payload["accepted_repair_delta"] == 1
    assert payload["end_to_end_loss"] is None
    assert payload["proof_pass_is_not_end_to_end_loss"] is True
    assert payload["separate_from_end_to_end_loss"] is True
    assert payload["semantic_authority"] is False


def test_reject_leaves_prior_l1_unchanged_and_records_validator_reject() -> None:
    gate = StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(
            make_rejecting_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
                detail="candidate violates structural constraint",
            ),
        ),
    )
    result = gate.admit(
        PRIOR,
        CANDIDATE,
        allowed_field_paths=(OBJECT_PATH,),
    )
    assert result.disposition is AdmissionDisposition.VALIDATOR_REJECT
    assert result.rejection_reason == VALIDATOR_REJECT
    assert result.admitted_l1 == PRIOR
    assert result.admitted_l1 == result.prior_l1
    assert result.prior_l1_unchanged is True
    assert result.candidate_l1 == CANDIDATE
    assert result.accepted is False
    assert result.rejected is True
    assert result.accepted_repair_delta == 0
    assert result.end_to_end_loss is None
    assert result.check_receipts[0].passed is False
    payload = result.to_dict()
    assert payload["rejection_reason"] == "validator_reject"
    assert payload["prior_l1_unchanged"] is True
    assert payload["admitted_l1"] == PRIOR.to_dict()
    assert payload["accepted_repair_delta"] == 0


def test_timeout_fail_closed_retains_prior_l1() -> None:
    gate = StructuralAdmissionGate(
        StructuralAdmissionPolicy(
            tools=(StructuralTool.LEAN,),
            timeout_seconds=0.05,
            fail_closed_on_timeout=True,
        ),
        validators=(
            make_timeout_binding(
                validator_id="lean",
                tool=StructuralTool.LEAN,
                sleep_seconds=2.0,
            ),
        ),
    )
    result = gate.admit(
        PRIOR,
        CANDIDATE,
        allowed_field_paths=(OBJECT_PATH,),
    )
    assert result.disposition is AdmissionDisposition.TIMEOUT
    assert result.rejection_reason == VALIDATOR_REJECT
    assert result.prior_l1_unchanged is True
    assert result.admitted_l1 == PRIOR
    assert result.accepted_repair_delta == 0
    assert result.check_receipts[0].timed_out is True
    assert result.check_receipts[0].passed is False
    assert "fail-closed" in (result.detail or "").lower()


def test_validator_error_fail_closed_retains_prior_l1() -> None:
    gate = StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(
            make_error_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
            ),
        ),
    )
    result = gate.admit(
        PRIOR,
        CANDIDATE,
        allowed_field_paths=(OBJECT_PATH,),
    )
    assert result.disposition is AdmissionDisposition.ERROR
    assert result.rejection_reason == VALIDATOR_REJECT
    assert result.prior_l1_unchanged is True
    assert result.admitted_l1 == PRIOR
    assert result.accepted_repair_delta == 0


def test_local_constraint_reject_without_tool_invocation() -> None:
    gate = StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(
            make_passing_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
            ),
        ),
    )
    vacuous = gate.admit(PRIOR, VACUOUS, allowed_field_paths=(OBJECT_PATH,))
    assert vacuous.disposition is AdmissionDisposition.VALIDATOR_REJECT
    assert vacuous.rejection_reason == VALIDATOR_REJECT
    assert vacuous.admitted_l1 == PRIOR
    assert vacuous.check_receipts == ()
    assert "vacuous" in (vacuous.detail or "")

    cardinality = gate.admit(
        PRIOR, EXTRA_RULE, allowed_field_paths=(OBJECT_PATH,)
    )
    assert cardinality.disposition is AdmissionDisposition.VALIDATOR_REJECT
    assert cardinality.admitted_l1 == PRIOR
    assert "cardinality" in (cardinality.detail or "")


def test_untriggered_field_change_is_validator_reject() -> None:
    gate = _hammer_pass()
    # Candidate also flips actor, which is outside the allowed repair path.
    bad = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="O",
                actor="processor",
                action="delete",
                object="records",
            ),
        )
    )
    result = gate.admit(PRIOR, bad, allowed_field_paths=(OBJECT_PATH,))
    assert result.disposition is AdmissionDisposition.VALIDATOR_REJECT
    assert result.rejection_reason == VALIDATOR_REJECT
    assert result.admitted_l1 == PRIOR
    assert result.prior_l1_unchanged is True


def test_not_applicable_when_no_candidate_or_identity() -> None:
    gate = _lean_pass()
    none_result = gate.admit(PRIOR, None)
    assert none_result.disposition is AdmissionDisposition.NOT_APPLICABLE
    assert none_result.admitted_l1 == PRIOR
    assert none_result.prior_l1_unchanged is True
    assert none_result.accepted_repair_delta == 0

    same = gate.admit(PRIOR, PRIOR)
    assert same.disposition is AdmissionDisposition.NOT_APPLICABLE
    assert same.admitted_l1 == PRIOR
    assert same.prior_l1_unchanged is True


def test_hybrid_entry_point_accept_and_reject() -> None:
    accepted = admit_hybrid_repair(
        PRIOR,
        CANDIDATE,
        gate=_both_pass(),
        allowed_field_paths=(OBJECT_PATH,),
    )
    assert accepted.disposition is AdmissionDisposition.ACCEPTED
    assert accepted.admitted_l1 == CANDIDATE

    rejected = admit_hybrid_repair(
        PRIOR,
        CANDIDATE,
        gate=StructuralAdmissionGate(
            StructuralAdmissionPolicy(tools=(StructuralTool.LEAN,)),
            validators=(
                make_rejecting_binding(
                    validator_id="lean",
                    tool=StructuralTool.LEAN,
                ),
            ),
        ),
        allowed_field_paths=(OBJECT_PATH,),
    )
    assert rejected.disposition is AdmissionDisposition.VALIDATOR_REJECT
    assert rejected.rejection_reason == VALIDATOR_REJECT
    assert rejected.admitted_l1 == PRIOR


def test_metrics_include_reject_rate_and_accepted_repair_delta() -> None:
    accept = _both_pass().admit(
        PRIOR, CANDIDATE, allowed_field_paths=(OBJECT_PATH,)
    )
    reject = StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(
            make_rejecting_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
            ),
        ),
    ).admit(PRIOR, CANDIDATE, allowed_field_paths=(OBJECT_PATH,))
    timeout = StructuralAdmissionGate(
        StructuralAdmissionPolicy(
            tools=(StructuralTool.LEAN,),
            timeout_seconds=0.05,
        ),
        validators=(
            make_timeout_binding(
                validator_id="lean",
                tool=StructuralTool.LEAN,
                sleep_seconds=2.0,
            ),
        ),
    ).admit(PRIOR, CANDIDATE, allowed_field_paths=(OBJECT_PATH,))
    n_a = _lean_pass().admit(PRIOR, None)

    metrics = aggregate_structural_admission_metrics(
        (accept, reject, timeout, n_a)
    )
    assert metrics.attempts == 4
    assert metrics.accepted == 1
    assert metrics.rejected == 2
    assert metrics.timeouts == 1
    assert metrics.not_applicable == 1
    assert metrics.reject_rate == pytest.approx(2 / 3)
    assert metrics.accept_rate == pytest.approx(1 / 3)
    assert metrics.accepted_repair_delta == pytest.approx(1.0)
    assert metrics.total_accepted_field_changes == 1
    assert metrics.end_to_end_loss is None
    payload = metrics.to_dict()
    assert payload["reject_rate"] == pytest.approx(2 / 3)
    assert payload["accepted_repair_delta"] == pytest.approx(1.0)
    assert payload["end_to_end_loss"] is None
    assert payload["proof_pass_is_not_end_to_end_loss"] is True
    assert payload["separate_from_end_to_end_loss"] is True
    assert payload["interface"] == STRUCTURAL_ADMISSION_METRICS_INTERFACE


def test_proof_pass_is_not_end_to_end_loss_by_itself() -> None:
    """A structural pass must not be treated as lower end-to-end loss."""

    result = _both_pass().admit(
        PRIOR, CANDIDATE, allowed_field_paths=(OBJECT_PATH,)
    )
    assert result.disposition is AdmissionDisposition.ACCEPTED
    assert all(receipt.passed for receipt in result.check_receipts)
    # Explicit contract: no end-to-end loss field is derived from proof pass.
    assert result.end_to_end_loss is None
    assert result.to_dict()["end_to_end_loss"] is None
    assert result.to_dict()["proof_pass_is_not_end_to_end_loss"] is True
    # Accepted-repair delta is a field-change count, not a protocol loss.
    assert isinstance(result.accepted_repair_delta, int)
    assert 0.0 <= float(result.accepted_repair_delta)
    # Reject path also never invents E2E loss from structural outcome.
    rejected = StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(
            make_rejecting_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
            ),
        ),
    ).admit(PRIOR, CANDIDATE, allowed_field_paths=(OBJECT_PATH,))
    assert rejected.end_to_end_loss is None
    assert rejected.accepted_repair_delta == 0


def test_local_constraints_only_gate_can_accept() -> None:
    gate = StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(),
    )
    result = gate.admit(
        PRIOR, CANDIDATE, allowed_field_paths=(OBJECT_PATH,)
    )
    assert result.disposition is AdmissionDisposition.ACCEPTED
    assert result.admitted_l1 == CANDIDATE
    assert result.check_receipts == ()


def test_policy_rejects_invalid_configuration() -> None:
    with pytest.raises(StructuralAdmissionError):
        StructuralAdmissionPolicy(timeout_seconds=0)
    with pytest.raises(StructuralAdmissionError):
        StructuralAdmissionPolicy(timeout_seconds=120)
    with pytest.raises(StructuralAdmissionError):
        StructuralAdmissionPolicy(tools=())
    with pytest.raises(StructuralAdmissionError):
        StructuralAdmissionPolicy(
            structural_constraints=("not_a_real_constraint",)
        )


def test_gate_requires_policy_tool_coverage() -> None:
    with pytest.raises(StructuralAdmissionError):
        StructuralAdmissionGate(
            StructuralAdmissionPolicy(
                tools=(StructuralTool.HAMMER_CVC5, StructuralTool.LEAN),
            ),
            validators=(
                make_passing_binding(
                    validator_id="hammer_cvc5",
                    tool=StructuralTool.HAMMER_CVC5,
                ),
            ),
        )


def test_result_contract_rejects_inconsistent_accept() -> None:
    with pytest.raises(StructuralAdmissionError):
        StructuralAdmissionResult(
            disposition=AdmissionDisposition.ACCEPTED,
            prior_l1=PRIOR,
            candidate_l1=CANDIDATE,
            admitted_l1=PRIOR,  # wrong: accept must admit candidate
            prior_l1_unchanged=False,
            rejection_reason=None,
            check_receipts=(),
            field_changes=(),
            policy_digest="abc",
        )
    with pytest.raises(StructuralAdmissionError):
        StructuralAdmissionResult(
            disposition=AdmissionDisposition.VALIDATOR_REJECT,
            prior_l1=PRIOR,
            candidate_l1=CANDIDATE,
            admitted_l1=CANDIDATE,  # wrong: reject must keep prior
            prior_l1_unchanged=True,
            rejection_reason=VALIDATOR_REJECT,
            check_receipts=(),
            field_changes=(),
            policy_digest="abc",
        )
    with pytest.raises(StructuralAdmissionError):
        StructuralAdmissionResult(
            disposition=AdmissionDisposition.VALIDATOR_REJECT,
            prior_l1=PRIOR,
            candidate_l1=CANDIDATE,
            admitted_l1=PRIOR,
            prior_l1_unchanged=True,
            rejection_reason="something_else",
            check_receipts=(),
            field_changes=(),
            policy_digest="abc",
        )


def test_gate_identity_is_stable() -> None:
    gate = _both_pass()
    assert gate.interface == STRUCTURAL_ADMISSION_INTERFACE
    assert "hammer_cvc5" in gate.identity
    assert "lean" in gate.identity
    assert gate.policy.digest in gate.identity
