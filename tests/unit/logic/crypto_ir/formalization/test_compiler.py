"""Unit tests for Crypto IR formalization (CRYPTOIR-G320).

Coverage maps to acceptance:

* each lowering declares soundness scope and supported theory
* selected backends actually execute
* receipts bind obligation / model / tool / policy / capability / timeout
* opaque ``security_verification_condition`` JSON, prose, unsupported theory,
  unavailable solver, timeout, disagreement, incomplete model → non-proof
* SAT is not silently a security proof
* never submit opaque serialization to a backend that does not compile it
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.crypto_ir.formalization import (
    AnalysisReceipt,
    AttemptOutcome,
    BackendDescriptor,
    BackendResult,
    BackendStatus,
    FormalObligation,
    FormalizationError,
    InjectedBackend,
    LogicFamily,
    LoweredForm,
    LoweringContract,
    LoweringStatus,
    ObligationCompiler,
    ObligationPayloadKind,
    ProofAuthority,
    PropositionalBackend,
    ProverPortfolio,
    SoundnessScope,
    TheoryFragment,
    Z3SmtBackend,
    assert_sat_is_not_proof,
    build_analysis_receipt,
    default_lowering_contracts,
    detect_payload_kind,
    is_executable_payload,
    proof_authority_for_outcome,
)
from ipfs_datasets_py.logic.crypto_ir.formalization.portfolio import (
    DatalogBackend,
    TemporalMonitorBackend,
)
from ipfs_datasets_py.logic.crypto_ir.security_rules import (
    FormalTargetKind,
    ObligationCategory,
    ProofObligation,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import AnalysisOutcome


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _obligation(
    *,
    obligation_id: str = "obl.auth.1",
    formal_target_kind: FormalTargetKind = FormalTargetKind.PROPOSITIONAL,
    formal_target: str = "p",
    payload: object = "p",
    payload_kind: ObligationPayloadKind | None = None,
    model_digest: str = "deadbeefcafebabe0123456789abcdef",
    policy_id: str = "policy.security.v1",
    policy_revision: str = "1.0.0",
    capability_ids: tuple[str, ...] = ("cap.prover.propositional",),
    category: ObligationCategory = ObligationCategory.AUTHORIZATION,
    statement: str = "only authorized callers may invoke privileged entrypoints",
) -> FormalObligation:
    kwargs: dict = {
        "obligation_id": obligation_id,
        "category": category,
        "statement": statement,
        "formal_target": formal_target,
        "formal_target_kind": formal_target_kind,
        "model_digest": model_digest,
        "required_fact_ids": ("fact.auth.1",),
        "required_semantic_dimensions": ("privileges", "control_flow"),
        "payload": payload,
        "trusted_assumption_ids": ("asm.closed-world",),
        "policy_id": policy_id,
        "policy_revision": policy_revision,
        "capability_ids": capability_ids,
        "code_epoch": "epoch.1",
        "summary": "authorization obligation",
    }
    if payload_kind is not None:
        kwargs["payload_kind"] = payload_kind
    return FormalObligation(**kwargs)


# ---------------------------------------------------------------------------
# Payload detection and non-executable gates
# ---------------------------------------------------------------------------


def test_detect_opaque_security_verification_condition_json() -> None:
    kind = detect_payload_kind(
        {"family": "security_verification_condition", "claim": "opaque"}
    )
    assert kind is ObligationPayloadKind.SECURITY_VERIFICATION_CONDITION
    assert not is_executable_payload(kind)


def test_detect_prose_payload() -> None:
    kind = detect_payload_kind("The contract is fine under informal review.")
    assert kind is ObligationPayloadKind.PROSE
    assert not is_executable_payload(kind)


def test_detect_smtlib_payload() -> None:
    kind = detect_payload_kind("(assert true)\n(check-sat)\n")
    assert kind is ObligationPayloadKind.COMPILED_SMT_LIB
    assert is_executable_payload(kind)


# ---------------------------------------------------------------------------
# Lowering contracts declare soundness scope and theory
# ---------------------------------------------------------------------------


def test_default_contracts_declare_soundness_scope_and_theory() -> None:
    contracts = default_lowering_contracts()
    assert contracts
    for contract in contracts:
        assert isinstance(contract, LoweringContract)
        assert contract.soundness_scope.scope_id
        assert contract.soundness_scope.description
        assert contract.supported_theories
        assert contract.contract_id
        # Opaque refuse contract never produces executable output.
        if contract.target_logic_family is LogicFamily.OPAQUE:
            assert contract.produces_executable is False


def test_lowering_contract_identity_is_stable() -> None:
    c1 = default_lowering_contracts()[0]
    c2 = default_lowering_contracts()[0]
    assert c1.identity.digest == c2.identity.digest


# ---------------------------------------------------------------------------
# ObligationCompiler: sound lowerings and refusals
# ---------------------------------------------------------------------------


def test_compile_propositional_true() -> None:
    compiler = ObligationCompiler()
    form = compiler.compile(_obligation(payload="true"))
    assert form.status is LoweringStatus.COMPILED
    assert form.may_submit is True
    assert form.logic_family is LogicFamily.PROPOSITIONAL
    assert form.theory in {TheoryFragment.PROPOSITIONAL, TheoryFragment.QF_BOOL}
    assert form.soundness_scope_id
    assert "(assert true)" in form.body.lower()


def test_compile_propositional_contradiction() -> None:
    compiler = ObligationCompiler()
    form = compiler.compile(
        _obligation(payload="(assert p)\n(assert (not p))\n", formal_target="p")
    )
    # With SMT markers this may route to smt or prop depending on target kind.
    assert form.status is LoweringStatus.COMPILED
    assert form.may_submit is True


def test_compile_smt_lib_fragment() -> None:
    compiler = ObligationCompiler()
    obl = _obligation(
        formal_target_kind=FormalTargetKind.SMT_LIB,
        formal_target="(assert false)",
        payload="(assert false)\n(check-sat)\n",
        payload_kind=ObligationPayloadKind.COMPILED_SMT_LIB,
    )
    form = compiler.compile(obl)
    assert form.status is LoweringStatus.COMPILED
    assert form.may_submit is True
    assert form.logic_family is LogicFamily.SMT_LIB
    assert form.theory is TheoryFragment.QF_BOOL


def test_refuse_opaque_security_verification_condition() -> None:
    compiler = ObligationCompiler()
    obl = _obligation(
        formal_target_kind=FormalTargetKind.SMT_LIB,
        formal_target="security_verification_condition",
        payload={
            "family": "security_verification_condition",
            "obligation": "reentrancy",
            "json": True,
        },
        payload_kind=ObligationPayloadKind.SECURITY_VERIFICATION_CONDITION,
    )
    form = compiler.compile(obl)
    assert form.status is LoweringStatus.OPAQUE_REFUSED
    assert form.may_submit is False
    assert form.logic_family is LogicFamily.OPAQUE
    assert form.body == ""


def test_refuse_prose_payload() -> None:
    compiler = ObligationCompiler()
    obl = _obligation(
        formal_target_kind=FormalTargetKind.FOL,
        formal_target="narrative claim",
        payload="Informal prose claiming the code is safe under review.",
        payload_kind=ObligationPayloadKind.PROSE,
    )
    form = compiler.compile(obl)
    assert form.status is LoweringStatus.OPAQUE_REFUSED
    assert form.may_submit is False


def test_refuse_incomplete_model() -> None:
    compiler = ObligationCompiler()
    form = compiler.compile(
        _obligation(payload="true"),
        model_complete=False,
        missing_fact_ids=("fact.missing.1",),
    )
    assert form.status is LoweringStatus.INCOMPLETE_MODEL
    assert form.may_submit is False


def test_cannot_smuggle_opaque_json_as_compiled_smt() -> None:
    """Declared compiled kind with opaque JSON body must not become may_submit."""

    compiler = ObligationCompiler()
    obl = _obligation(
        formal_target_kind=FormalTargetKind.SMT_LIB,
        formal_target="svc",
        payload={"family": "security_verification_condition", "x": 1},
        # Attempt to declare compiled even though body is opaque JSON.
        payload_kind=ObligationPayloadKind.COMPILED_SMT_LIB,
    )
    form = compiler.compile(obl)
    assert form.may_submit is False
    assert form.status in {
        LoweringStatus.OPAQUE_REFUSED,
        LoweringStatus.UNSUPPORTED,
        LoweringStatus.NOT_MODELED,
    }


def test_compile_datalog_positive_rules() -> None:
    compiler = ObligationCompiler()
    obl = _obligation(
        formal_target_kind=FormalTargetKind.DATALOG,
        formal_target="edge",
        payload=["edge(a,b).", "path(X,Y) :- edge(X,Y)."],
        payload_kind=ObligationPayloadKind.DATALOG_RULES,
    )
    form = compiler.compile(obl)
    assert form.status is LoweringStatus.COMPILED
    assert form.may_submit is True
    assert form.logic_family is LogicFamily.DATALOG


def test_refuse_datalog_with_negation() -> None:
    compiler = ObligationCompiler()
    obl = _obligation(
        formal_target_kind=FormalTargetKind.DATALOG,
        formal_target="edge",
        payload=["edge(a,b).", "bad(X) :- edge(X,Y), not edge(Y,X)."],
        payload_kind=ObligationPayloadKind.DATALOG_RULES,
    )
    form = compiler.compile(obl)
    assert form.status is LoweringStatus.UNSUPPORTED
    assert form.may_submit is False


def test_compile_temporal_bounded_ltl() -> None:
    compiler = ObligationCompiler()
    obl = _obligation(
        formal_target_kind=FormalTargetKind.TEMPORAL,
        formal_target="G authorized",
        payload="G authorized  bound=32",
        payload_kind=ObligationPayloadKind.TEMPORAL_FORMULA,
    )
    form = compiler.compile(obl)
    assert form.status is LoweringStatus.COMPILED
    assert form.may_submit is True
    assert form.logic_family is LogicFamily.TEMPORAL


def test_from_proof_obligation_lift() -> None:
    po = ProofObligation(
        obligation_id="obl.from-po",
        category=ObligationCategory.REPLAY,
        statement="replay domain must bind chain id and nonce",
        formal_target="true",
        formal_target_kind=FormalTargetKind.PROPOSITIONAL,
        required_fact_ids=("fact.replay.1",),
        required_semantic_dimensions=("replay_domain",),
    )
    formal = FormalObligation.from_proof_obligation(
        po, model_digest="abc123def4567890", payload="true"
    )
    assert formal.obligation_id == "obl.from-po"
    form = ObligationCompiler().compile(formal)
    assert form.may_submit is True


# ---------------------------------------------------------------------------
# Portfolio: backends execute; opaque never submitted
# ---------------------------------------------------------------------------


def test_portfolio_refuses_opaque_without_calling_backends() -> None:
    calls: list[str] = []

    def factory(backend, form, timeout_ms):  # type: ignore[no-untyped-def]
        calls.append(form.form_id)
        return BackendResult(
            backend_id=backend.descriptor.backend_id,
            status=BackendStatus.SATISFIABLE,
            executed=True,
            logic_family=form.logic_family,
            timeout_ms=timeout_ms,
            obligation_id=form.obligation_id,
            form_id=form.form_id,
            model_digest=form.model_digest,
        )

    injected = InjectedBackend(
        BackendDescriptor(
            backend_id="backend.injected.z3",
            family="z3",
            logic_families=(LogicFamily.SMT_LIB, LogicFamily.PROPOSITIONAL),
            theories=(TheoryFragment.QF_BOOL,),
            tool_name="injected-z3",
            tool_version="test",
        ),
        result_factory=factory,
    )
    portfolio = ProverPortfolio(backends=(injected,), max_backends=2)
    compiler = ObligationCompiler()
    form = compiler.compile(
        _obligation(
            payload={"family": "security_verification_condition"},
            payload_kind=ObligationPayloadKind.SECURITY_VERIFICATION_CONDITION,
        )
    )
    run = portfolio.run(form, timeout_ms=100)
    assert form.may_submit is False
    assert run.selected_backend_ids == ()
    assert calls == []
    assert run.results[0].executed is False
    assert run.results[0].status in {
        BackendStatus.REFUSED,
        BackendStatus.NOT_MODELED,
    }


def test_propositional_backend_actually_executes_unsat() -> None:
    backend = PropositionalBackend()
    assert backend.is_available() is True
    form = LoweredForm(
        form_id="form.test.unsat",
        obligation_id="obl.test",
        model_digest="deadbeefcafebabe0123456789abcdef",
        contract_id="lowering.propositional.v1",
        status=LoweringStatus.COMPILED,
        logic_family=LogicFamily.PROPOSITIONAL,
        payload_kind=ObligationPayloadKind.PROPOSITIONAL_FORMULA,
        body="(assert p)\n(assert (not p))\n(check-sat)\n",
        theory=TheoryFragment.QF_BOOL,
        soundness_scope_id="scope.propositional.qf-bool",
        may_submit=True,
    )
    result = backend.execute(form, timeout_ms=500)
    assert result.executed is True
    assert result.status is BackendStatus.UNSATISFIABLE


def test_propositional_backend_sat_is_satisfiability_not_proof() -> None:
    backend = PropositionalBackend()
    form = LoweredForm(
        form_id="form.test.sat",
        obligation_id="obl.test",
        model_digest="deadbeefcafebabe0123456789abcdef",
        contract_id="lowering.propositional.v1",
        status=LoweringStatus.COMPILED,
        logic_family=LogicFamily.PROPOSITIONAL,
        payload_kind=ObligationPayloadKind.PROPOSITIONAL_FORMULA,
        body="(assert true)\n(check-sat)\n",
        theory=TheoryFragment.QF_BOOL,
        soundness_scope_id="scope.propositional.qf-bool",
        may_submit=True,
    )
    result = backend.execute(form, timeout_ms=500)
    assert result.executed is True
    assert result.status is BackendStatus.SATISFIABLE
    assert result.is_satisfiability_only is True
    assert result.is_proof_candidate is False


def test_portfolio_runs_propositional_backend_end_to_end() -> None:
    compiler = ObligationCompiler()
    portfolio = ProverPortfolio(
        backends=(PropositionalBackend(),),
        max_backends=1,
        default_timeout_ms=1_000,
    )
    obl = _obligation(payload="true")
    form = compiler.compile(obl)
    run = portfolio.run(form, timeout_ms=1_000)
    assert run.selected_backend_ids
    assert any(r.executed for r in run.results)
    assert run.results[0].status is BackendStatus.SATISFIABLE


def test_portfolio_records_unavailable_backend() -> None:
    unavailable = InjectedBackend(
        BackendDescriptor(
            backend_id="backend.injected.unavailable",
            family="z3",
            logic_families=(LogicFamily.PROPOSITIONAL, LogicFamily.SMT_LIB),
            theories=(TheoryFragment.QF_BOOL, TheoryFragment.PROPOSITIONAL),
            tool_name="missing-solver",
            tool_version="",
            capability_id="cap.prover.missing",
        ),
        available=False,
    )
    portfolio = ProverPortfolio(backends=(unavailable,), max_backends=1)
    form = ObligationCompiler().compile(_obligation(payload="true"))
    run = portfolio.run(form, timeout_ms=50)
    assert run.results[0].status is BackendStatus.UNAVAILABLE
    assert run.results[0].executed is False


def test_portfolio_disagreement_is_explicit() -> None:
    def sat_factory(backend, form, timeout_ms):  # type: ignore[no-untyped-def]
        return BackendResult(
            backend_id=backend.descriptor.backend_id,
            status=BackendStatus.SATISFIABLE,
            executed=True,
            logic_family=form.logic_family,
            timeout_ms=timeout_ms,
            obligation_id=form.obligation_id,
            form_id=form.form_id,
            model_digest=form.model_digest,
            tool_name=backend.descriptor.tool_name,
        )

    def unsat_factory(backend, form, timeout_ms):  # type: ignore[no-untyped-def]
        return BackendResult(
            backend_id=backend.descriptor.backend_id,
            status=BackendStatus.UNSATISFIABLE,
            executed=True,
            logic_family=form.logic_family,
            timeout_ms=timeout_ms,
            obligation_id=form.obligation_id,
            form_id=form.form_id,
            model_digest=form.model_digest,
            tool_name=backend.descriptor.tool_name,
        )

    a = InjectedBackend(
        BackendDescriptor(
            backend_id="backend.a",
            family="z3",
            logic_families=(LogicFamily.PROPOSITIONAL,),
            theories=(TheoryFragment.PROPOSITIONAL, TheoryFragment.QF_BOOL),
            tool_name="a",
        ),
        result_factory=sat_factory,
    )
    b = InjectedBackend(
        BackendDescriptor(
            backend_id="backend.b",
            family="cvc5",
            logic_families=(LogicFamily.PROPOSITIONAL,),
            theories=(TheoryFragment.PROPOSITIONAL, TheoryFragment.QF_BOOL),
            tool_name="b",
        ),
        result_factory=unsat_factory,
    )
    portfolio = ProverPortfolio(backends=(a, b), max_backends=2)
    form = ObligationCompiler().compile(_obligation(payload="true"))
    run = portfolio.run(form, timeout_ms=100)
    assert run.disagreement is True
    assert any(r.status is BackendStatus.DISAGREEMENT for r in run.results)


def test_backend_refuses_wrong_logic_family() -> None:
    backend = DatalogBackend()
    form = LoweredForm(
        form_id="form.wrong-family",
        obligation_id="obl.x",
        model_digest="deadbeefcafebabe0123456789abcdef",
        contract_id="lowering.smt-lib.v1",
        status=LoweringStatus.COMPILED,
        logic_family=LogicFamily.SMT_LIB,
        payload_kind=ObligationPayloadKind.COMPILED_SMT_LIB,
        body="(assert true)\n(check-sat)\n",
        theory=TheoryFragment.QF_BOOL,
        soundness_scope_id="scope.smt.qf-bool-lia-bv",
        may_submit=True,
    )
    result = backend.execute(form, timeout_ms=100)
    assert result.executed is False
    assert result.status is BackendStatus.REFUSED


def test_z3_backend_executes_when_available() -> None:
    backend = Z3SmtBackend()
    if not backend.is_available():
        pytest.skip("z3 not installed")
    form = LoweredForm(
        form_id="form.z3.true",
        obligation_id="obl.z3",
        model_digest="deadbeefcafebabe0123456789abcdef",
        contract_id="lowering.smt-lib.v1",
        status=LoweringStatus.COMPILED,
        logic_family=LogicFamily.SMT_LIB,
        payload_kind=ObligationPayloadKind.COMPILED_SMT_LIB,
        body="(assert true)\n(check-sat)\n",
        theory=TheoryFragment.QF_BOOL,
        soundness_scope_id="scope.smt.qf-bool-lia-bv",
        may_submit=True,
    )
    result = backend.execute(form, timeout_ms=2_000)
    assert result.executed is True
    assert result.status in {
        BackendStatus.SATISFIABLE,
        BackendStatus.UNSATISFIABLE,
        BackendStatus.UNKNOWN,
        BackendStatus.TIMEOUT,
        BackendStatus.ERROR,
    }
    # true should be sat under a working z3
    if result.status not in {BackendStatus.ERROR, BackendStatus.TIMEOUT, BackendStatus.UNKNOWN}:
        assert result.status is BackendStatus.SATISFIABLE


# ---------------------------------------------------------------------------
# Receipts: bindings, authority lattice, SAT ≠ proof
# ---------------------------------------------------------------------------


def test_receipt_binds_obligation_model_tool_policy_capability_timeout() -> None:
    compiler = ObligationCompiler()
    portfolio = ProverPortfolio(
        backends=(PropositionalBackend(),), max_backends=1, default_timeout_ms=750
    )
    obl = _obligation(payload="true")
    form = compiler.compile(obl)
    run = portfolio.run(form, timeout_ms=750)
    receipt = build_analysis_receipt(obl, form, run)
    assert isinstance(receipt, AnalysisReceipt)
    assert receipt.obligation_id == obl.obligation_id
    assert receipt.model_digest == obl.model_digest
    assert receipt.policy_id == obl.policy_id
    assert receipt.policy_revision == obl.policy_revision
    assert receipt.timeout_ms == 750
    assert receipt.capability_ids
    assert receipt.tool_ids or any(a.tool_name for a in receipt.attempts)
    assert receipt.binds_obligation_model_tool_policy_capability_timeout
    assert receipt.cannot_authorize_transaction() is True


def test_sat_receipt_is_satisfiability_only_not_proved() -> None:
    compiler = ObligationCompiler()
    portfolio = ProverPortfolio(backends=(PropositionalBackend(),), max_backends=1)
    obl = _obligation(payload="true")
    form = compiler.compile(obl)
    run = portfolio.run(form, timeout_ms=500)
    receipt = build_analysis_receipt(obl, form, run)
    assert receipt.outcome is AttemptOutcome.SATISFIABLE
    assert receipt.proof_authority is ProofAuthority.SATISFIABILITY_ONLY
    assert receipt.analysis_outcome is AnalysisOutcome.UNKNOWN
    with pytest.raises(FormalizationError, match="not a security proof"):
        assert_sat_is_not_proof(receipt.proof_authority)


def test_opaque_receipt_is_explicit_non_proof() -> None:
    compiler = ObligationCompiler()
    obl = _obligation(
        payload={"family": "security_verification_condition", "k": "v"},
        payload_kind=ObligationPayloadKind.SECURITY_VERIFICATION_CONDITION,
    )
    form = compiler.compile(obl)
    receipt = build_analysis_receipt(obl, form, None)
    assert receipt.proof_authority is ProofAuthority.NON_PROOF
    assert receipt.outcome in {
        AttemptOutcome.REFUSED,
        AttemptOutcome.NOT_MODELED,
        AttemptOutcome.UNSUPPORTED,
    }
    assert receipt.analysis_outcome is AnalysisOutcome.UNSUPPORTED
    assert all(not a.executed for a in receipt.attempts)


def test_incomplete_model_receipt_non_proof() -> None:
    compiler = ObligationCompiler()
    obl = _obligation(payload="true")
    form = compiler.compile(obl, model_complete=False, missing_fact_ids=("f.1",))
    receipt = build_analysis_receipt(obl, form)
    assert receipt.outcome is AttemptOutcome.INCOMPLETE_MODEL
    assert receipt.proof_authority is ProofAuthority.NON_PROOF
    assert receipt.analysis_outcome is AnalysisOutcome.INCONCLUSIVE


def test_disagreement_receipt_non_proof() -> None:
    def sat_factory(backend, form, timeout_ms):  # type: ignore[no-untyped-def]
        return BackendResult(
            backend_id=backend.descriptor.backend_id,
            status=BackendStatus.SATISFIABLE,
            executed=True,
            logic_family=form.logic_family,
            timeout_ms=timeout_ms,
            obligation_id=form.obligation_id,
            form_id=form.form_id,
            model_digest=form.model_digest,
            tool_name=backend.descriptor.tool_name,
            capability_id=backend.descriptor.capability_id,
        )

    def unsat_factory(backend, form, timeout_ms):  # type: ignore[no-untyped-def]
        return BackendResult(
            backend_id=backend.descriptor.backend_id,
            status=BackendStatus.UNSATISFIABLE,
            executed=True,
            logic_family=form.logic_family,
            timeout_ms=timeout_ms,
            obligation_id=form.obligation_id,
            form_id=form.form_id,
            model_digest=form.model_digest,
            tool_name=backend.descriptor.tool_name,
            capability_id=backend.descriptor.capability_id,
        )

    portfolio = ProverPortfolio(
        backends=(
            InjectedBackend(
                BackendDescriptor(
                    backend_id="backend.sat",
                    family="z3",
                    logic_families=(LogicFamily.PROPOSITIONAL,),
                    theories=(TheoryFragment.PROPOSITIONAL, TheoryFragment.QF_BOOL),
                    tool_name="sat-tool",
                    capability_id="cap.sat",
                ),
                result_factory=sat_factory,
            ),
            InjectedBackend(
                BackendDescriptor(
                    backend_id="backend.unsat",
                    family="cvc5",
                    logic_families=(LogicFamily.PROPOSITIONAL,),
                    theories=(TheoryFragment.PROPOSITIONAL, TheoryFragment.QF_BOOL),
                    tool_name="unsat-tool",
                    capability_id="cap.unsat",
                ),
                result_factory=unsat_factory,
            ),
        ),
        max_backends=2,
    )
    obl = _obligation(payload="true")
    form = ObligationCompiler().compile(obl)
    run = portfolio.run(form, timeout_ms=100)
    receipt = build_analysis_receipt(obl, form, run)
    assert receipt.disagreement is True
    assert receipt.outcome is AttemptOutcome.DISAGREEMENT
    assert receipt.proof_authority is ProofAuthority.NON_PROOF


def test_proof_authority_lattice() -> None:
    assert proof_authority_for_outcome(AttemptOutcome.PROVED) is ProofAuthority.PROOF
    assert (
        proof_authority_for_outcome(AttemptOutcome.DISPROVED) is ProofAuthority.DISPROOF
    )
    assert (
        proof_authority_for_outcome(AttemptOutcome.SATISFIABLE)
        is ProofAuthority.SATISFIABILITY_ONLY
    )
    assert (
        proof_authority_for_outcome(AttemptOutcome.TIMEOUT) is ProofAuthority.NON_PROOF
    )
    assert (
        proof_authority_for_outcome(AttemptOutcome.UNAVAILABLE)
        is ProofAuthority.NON_PROOF
    )


def test_timeout_injected_attempt_is_non_proof() -> None:
    def timeout_factory(backend, form, timeout_ms):  # type: ignore[no-untyped-def]
        return BackendResult(
            backend_id=backend.descriptor.backend_id,
            status=BackendStatus.TIMEOUT,
            executed=True,
            logic_family=form.logic_family,
            timeout_ms=timeout_ms,
            elapsed_ms=timeout_ms,
            obligation_id=form.obligation_id,
            form_id=form.form_id,
            model_digest=form.model_digest,
            tool_name=backend.descriptor.tool_name,
            reason="injected timeout",
        )

    portfolio = ProverPortfolio(
        backends=(
            InjectedBackend(
                BackendDescriptor(
                    backend_id="backend.timeout",
                    family="z3",
                    logic_families=(LogicFamily.PROPOSITIONAL,),
                    theories=(TheoryFragment.PROPOSITIONAL, TheoryFragment.QF_BOOL),
                    tool_name="timeout-tool",
                ),
                result_factory=timeout_factory,
            ),
        ),
        max_backends=1,
    )
    obl = _obligation(payload="true")
    form = ObligationCompiler().compile(obl)
    run = portfolio.run(form, timeout_ms=10)
    receipt = build_analysis_receipt(obl, form, run)
    assert receipt.outcome is AttemptOutcome.TIMEOUT
    assert receipt.proof_authority is ProofAuthority.NON_PROOF


def test_temporal_monitor_never_proof() -> None:
    backend = TemporalMonitorBackend()
    form = LoweredForm(
        form_id="form.temporal.1",
        obligation_id="obl.temporal",
        model_digest="deadbeefcafebabe0123456789abcdef",
        contract_id="lowering.temporal.v1",
        status=LoweringStatus.COMPILED,
        logic_family=LogicFamily.TEMPORAL,
        payload_kind=ObligationPayloadKind.TEMPORAL_FORMULA,
        body="G authorized bound=8\n",
        theory=TheoryFragment.LTL_BOUNDED,
        soundness_scope_id="scope.temporal.ltl-bounded",
        may_submit=True,
    )
    result = backend.execute(form, timeout_ms=100)
    assert result.executed is True
    assert result.status is not BackendStatus.PROVED
    assert result.status is not BackendStatus.DISPROVED


def test_find_violation_mode_can_prove_absence_of_counterexample() -> None:
    """query_mode=find_violation: unsat means no violation (proof candidate)."""

    form = LoweredForm(
        form_id="form.violation.unsat",
        obligation_id="obl.v",
        model_digest="deadbeefcafebabe0123456789abcdef",
        contract_id="lowering.propositional.v1",
        status=LoweringStatus.COMPILED,
        logic_family=LogicFamily.PROPOSITIONAL,
        payload_kind=ObligationPayloadKind.PROPOSITIONAL_FORMULA,
        body="(assert p)\n(assert (not p))\n(check-sat)\n",
        theory=TheoryFragment.QF_BOOL,
        soundness_scope_id="scope.propositional.qf-bool",
        may_submit=True,
        attributes={"query_mode": "find_violation"},
    )
    result = PropositionalBackend().execute(form, timeout_ms=200)
    assert result.executed is True
    assert result.status is BackendStatus.PROVED
    assert result.is_proof_candidate is True


def test_receipt_round_trip_dict_fields() -> None:
    compiler = ObligationCompiler()
    portfolio = ProverPortfolio(backends=(PropositionalBackend(),), max_backends=1)
    obl = _obligation(payload="false")
    form = compiler.compile(obl)
    run = portfolio.run(form, timeout_ms=200)
    receipt = build_analysis_receipt(obl, form, run)
    data = receipt.to_dict()
    assert data["obligation_id"] == obl.obligation_id
    assert data["model_digest"] == obl.model_digest
    assert data["policy_id"] == obl.policy_id
    assert "proof_authority" in data
    assert "attempts" in data
    assert receipt.identity.digest


def test_package_exports_ast_symbols() -> None:
    from ipfs_datasets_py.logic.crypto_ir import formalization as package

    for name in (
        "ObligationCompiler",
        "ProverPortfolio",
        "AnalysisReceipt",
        "ProofAuthority",
        "LoweringContract",
    ):
        assert hasattr(package, name), name
