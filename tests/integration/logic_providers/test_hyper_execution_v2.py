"""Integration tests: split AutoHyper / MCHyper capability paths (LFP2-032).

Acceptance (fail-closed):

* One engine's support cannot establish another's capability.
* Every result identifies engine, system, formula, bounds, and witness status.
* Engine identities, system models, quantifier-prefix ceilings, finite/bounded
  semantics, and witness replay remain separated per path.

Interfaces: HyperProviderEvidence@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.hyperproperties.adapters import (
    AUTOHYPER_CAPABILITY,
    HYPERLTL_CAPABILITY,
    MCHYPER_CAPABILITY,
    AutoHyperBackend,
    HyperEngine,
    HyperLTLBackend,
    MCHyperBackend,
)
from ipfs_datasets_py.logic.backends.hyperproperties.execution_v2 import (
    HYPER_EXECUTION_V2_TASK_ID,
    HYPER_PROVIDER_EVIDENCE_V2_INTERFACE,
    HyperAuthorityError,
    HyperBoundsBindingV2,
    HyperCapabilityReceiptV2,
    HyperClaimKind,
    HyperDisposition,
    HyperExecutionEngineV2,
    HyperExecutionError,
    HyperExecutionMode,
    HyperExecutionRequestV2,
    HyperFormulaBindingV2,
    HyperProviderEvidenceV2,
    HyperProviderKind,
    HyperSemanticsKind,
    HyperSystemBindingV2,
    HyperSystemKind,
    HyperWitnessBindingV2,
    HyperWitnessStatus,
    capability_for,
    engine_support_establishes_other,
    execute_autohyper,
    execute_hyper,
    execute_hyperltl,
    execute_mchyper,
    non_authoritative_signal_establishes,
    normalize_hyper_provider,
)
from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner,
    RawProcessResult,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_verification.hyperproperties import (
    HyperpropertyFormula,
    HyperpropertyIR,
    HyperpropertyKind,
    InformationFlowPolicy,
    ObservationKind,
    ObservationSpec,
    QuantifierBinding,
    SecurityLabel,
    SecurityLevel,
    SelfCompositionBound,
    TraceQuantifier,
    TraceVariable,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _policy(
    *,
    observations: tuple[str, ...] = ("status", "public_token"),
) -> InformationFlowPolicy:
    labels = (
        SecurityLabel("label:user", "user_id", SecurityLevel.LOW, ObservationKind.INPUT),
        SecurityLabel(
            "label:secret", "secret", SecurityLevel.HIGH, ObservationKind.INPUT
        ),
        SecurityLabel(
            "label:status", "status", SecurityLevel.LOW, ObservationKind.OUTPUT
        ),
        SecurityLabel(
            "label:token",
            "public_token",
            SecurityLevel.LOW,
            ObservationKind.OUTPUT,
        ),
    )
    observation_specs = tuple(
        ObservationSpec(
            f"obs:{field}",
            field,
            ObservationKind.OUTPUT,
            SecurityLevel.LOW,
        )
        for field in observations
    )
    return InformationFlowPolicy(
        policy_id="policy:ni-v1",
        low_input_fields=("user_id",),
        high_input_fields=("secret",),
        observation_fields=observations,
        labels=labels,
        observations=observation_specs,
        subject_fields=("task_id",),
        description="Two-trace noninterference policy",
    )


def _bound(
    *,
    max_traces: int = 8,
    max_pairs: int = 16,
) -> SelfCompositionBound:
    return SelfCompositionBound(
        "bound:finite",
        max_traces=max_traces,
        max_pairs=max_pairs,
        max_steps=64,
        description="Finite self-composition envelope",
    )


def _document(
    *,
    max_traces: int = 8,
    max_pairs: int = 16,
) -> HyperpropertyIR:
    return HyperpropertyIR.noninterference_document(
        policy=_policy(),
        bound=_bound(max_traces=max_traces, max_pairs=max_pairs),
        metadata={"subject": "information-flow"},
    )


def _alternating_document(
    *,
    signature: tuple[TraceQuantifier, ...],
) -> HyperpropertyIR:
    variables = tuple(
        TraceVariable(f"var:pi{index + 1}", f"pi{index + 1}")
        for index in range(len(signature))
    )
    prefix = tuple(
        QuantifierBinding(
            f"bind:{index}",
            quantifier,
            variables[index].variable_id,
            index,
        )
        for index, quantifier in enumerate(signature)
    )
    formula = HyperpropertyFormula(
        formula_id="formula:alternating",
        kind=HyperpropertyKind.GENERAL,
        variables=variables,
        quantifier_prefix=prefix,
        matrix_statement=" ".join(
            f"{item.quantifier.value} {variables[index].name}."
            for index, item in enumerate(prefix)
        )
        + " true",
    )
    return HyperpropertyIR(
        formula=formula,
        information_flow_policy=_policy(),
        self_composition_bound=_bound(),
    )


def _process_runner(
    stdout: str,
    *,
    returncode: int | None = 0,
    timed_out: bool = False,
    unavailable: bool = False,
) -> BoundedToolRunner:
    def execute(invocation, _cancellation):
        del invocation
        return RawProcessResult(
            returncode=returncode,
            stdout=stdout,
            elapsed_seconds=0.012,
            timed_out=timed_out,
            process_tree_terminated=timed_out,
            error="executable not found" if unavailable else "",
        )

    return BoundedToolRunner(executor=execute)


def _engine_with(
    *,
    hyper_stdout: str = "sat\n",
    auto_stdout: str = "SAT\n",
    mc_stdout: str = "Property proved. Time = 0.01 sec\n",
    hyper_which=None,
    auto_which=None,
    mc_which=None,
) -> HyperExecutionEngineV2:
    hyper_which = hyper_which or (
        lambda name: "/bin/hyperltl" if name in {"hyperltl", "hyperltl-sat"} else None
    )
    auto_which = auto_which or (
        lambda name: "/bin/AutoHyper" if name in {"AutoHyper", "autohyper"} else None
    )
    mc_which = mc_which or (
        lambda name: "/bin/mchyper" if name in {"mchyper", "MCHyper"} else None
    )
    return HyperExecutionEngineV2(
        hyperltl=HyperLTLBackend(
            runner=_process_runner(hyper_stdout),
            which=hyper_which,
            executable="/bin/hyperltl",
        ),
        autohyper=AutoHyperBackend(
            runner=_process_runner(auto_stdout),
            which=auto_which,
            executable="/bin/AutoHyper",
        ),
        mchyper=MCHyperBackend(
            runner=_process_runner(mc_stdout),
            which=mc_which,
            executable="/bin/mchyper",
        ),
    )


# ---------------------------------------------------------------------------
# Interface / typing surface
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    engine = HyperExecutionEngineV2()
    assert engine.INTERFACE == HYPER_PROVIDER_EVIDENCE_V2_INTERFACE
    assert engine.interface == "HyperProviderEvidence@2"
    assert engine.TASK_ID == HYPER_EXECUTION_V2_TASK_ID
    assert engine.TASK_ID == "LFP2-032"
    assert HyperExecutionRequestV2.interface == "HyperExecutionRequest@2"


def test_provider_normalization() -> None:
    assert normalize_hyper_provider("autohyper") is HyperProviderKind.AUTOHYPER
    assert normalize_hyper_provider("mc-hyper") is HyperProviderKind.MCHYPER
    assert normalize_hyper_provider("hyper_ltl") is HyperProviderKind.HYPERLTL
    assert normalize_hyper_provider(HyperEngine.AUTOHYPER) is HyperProviderKind.AUTOHYPER
    assert normalize_hyper_provider(HyperProviderKind.MCHYPER) is HyperProviderKind.MCHYPER
    with pytest.raises(HyperExecutionError):
        normalize_hyper_provider("z3")
    with pytest.raises(HyperExecutionError):
        normalize_hyper_provider("hyperltl_autohyper_mchyper")


# ---------------------------------------------------------------------------
# Independent capabilities: one engine cannot establish another
# ---------------------------------------------------------------------------


def test_each_engine_capability_is_independent() -> None:
    hyper = capability_for(HyperProviderKind.HYPERLTL)
    auto = capability_for(HyperProviderKind.AUTOHYPER)
    mc = capability_for(HyperProviderKind.MCHYPER)

    assert hyper is HYPERLTL_CAPABILITY or hyper == HYPERLTL_CAPABILITY
    assert auto == AUTOHYPER_CAPABILITY
    assert mc == MCHYPER_CAPABILITY

    assert hyper.engine is HyperEngine.HYPERLTL
    assert auto.engine is HyperEngine.AUTOHYPER
    assert mc.engine is HyperEngine.MCHYPER

    assert set(hyper.executable_candidates) != set(auto.executable_candidates)
    assert set(auto.executable_candidates) != set(mc.executable_candidates)
    assert auto.supports_forall_exists is False
    assert mc.supports_exists_forall is False
    assert auto.max_quantifier_alternations != hyper.max_quantifier_alternations or (
        auto.supports_forall_exists != hyper.supports_forall_exists
    )


def test_engine_support_never_establishes_other_engine() -> None:
    for source in HyperProviderKind:
        for target in HyperProviderKind:
            assert (
                engine_support_establishes_other(
                    source,
                    target,
                    source_available=True,
                    source_supported=True,
                )
                is False
            )


def test_available_autohyper_does_not_establish_mchyper_capability() -> None:
    # AutoHyper present, MCHyper missing.
    engine = HyperExecutionEngineV2(
        hyperltl=HyperLTLBackend(which=lambda _n: None),
        autohyper=AutoHyperBackend(
            runner=_process_runner("SAT\n"),
            executable="/bin/AutoHyper",
            which=lambda name: "/bin/AutoHyper" if name in {"AutoHyper", "autohyper"} else None,
        ),
        mchyper=MCHyperBackend(which=lambda _n: None),
    )
    auto_cap = engine.capability_receipt(HyperProviderKind.AUTOHYPER)
    mc_cap = engine.capability_receipt(HyperProviderKind.MCHYPER)

    assert auto_cap.available is True
    assert mc_cap.available is False
    assert auto_cap.establishes(HyperProviderKind.MCHYPER) is False
    assert auto_cap.establishes(HyperProviderKind.HYPERLTL) is False
    assert mc_cap.establishes(HyperProviderKind.AUTOHYPER) is False

    auto_result = engine.execute(
        HyperExecutionRequestV2(
            request_id="req:auto:only",
            provider=HyperProviderKind.AUTOHYPER,
            document=_document(),
            mode=HyperExecutionMode.ENGINE,
        )
    )
    assert auto_result.evidence.available is True
    assert auto_result.evidence.establishes_other_engine(HyperProviderKind.MCHYPER) is False
    assert auto_result.evidence.establishes_other_engine(HyperProviderKind.HYPERLTL) is False
    wire = auto_result.evidence.to_dict()
    assert wire["claim_other_engine_capability"] is False


def test_split_capability_execution_keeps_engines_isolated() -> None:
    engine = _engine_with()
    aiger = b"aag 0 0 0 0 0\n"
    results = engine.execute_split_capabilities(
        _document(),
        request_id_prefix="req:split",
        system_models={"mchyper": aiger},
    )
    assert set(results) == set(HyperProviderKind)
    engines_seen = {result.evidence.engine for result in results.values()}
    assert engines_seen == set(HyperProviderKind)

    for kind, result in results.items():
        assert result.engine is kind
        assert result.evidence.engine is kind
        assert result.evidence.capability.engine is kind
        assert result.evidence.bindings_complete() is True
        for other in HyperProviderKind:
            if other is kind:
                continue
            assert result.evidence.establishes_other_engine(other) is False

    # Distinct quantifier ceilings remain on each path.
    assert (
        results[HyperProviderKind.AUTOHYPER].evidence.bounds.max_quantifier_alternations
        == AUTOHYPER_CAPABILITY.max_quantifier_alternations
    )
    assert (
        results[HyperProviderKind.MCHYPER].evidence.bounds.max_quantifier_alternations
        == MCHYPER_CAPABILITY.max_quantifier_alternations
    )
    assert (
        results[HyperProviderKind.HYPERLTL].evidence.bounds.max_quantifier_alternations
        == HYPERLTL_CAPABILITY.max_quantifier_alternations
    )


def test_capability_receipt_rejects_cross_engine_relabel() -> None:
    with pytest.raises(HyperAuthorityError, match="re-labeled|match"):
        HyperCapabilityReceiptV2(
            engine=HyperProviderKind.AUTOHYPER,
            available=True,
            supported_prefix=True,
            capability=MCHYPER_CAPABILITY.to_dict(),  # wrong engine payload
        )


# ---------------------------------------------------------------------------
# Every result identifies engine, system, formula, bounds, witness status
# ---------------------------------------------------------------------------


def test_result_binds_engine_system_formula_bounds_witness() -> None:
    engine = _engine_with()
    result = engine.execute(
        HyperExecutionRequestV2(
            request_id="req:bind:auto",
            provider=HyperProviderKind.AUTOHYPER,
            document=_document(),
            mode=HyperExecutionMode.ENGINE,
        )
    )
    evidence = result.evidence
    assert evidence.interface == HYPER_PROVIDER_EVIDENCE_V2_INTERFACE
    assert evidence.bindings_complete() is True

    # Engine
    assert evidence.engine is HyperProviderKind.AUTOHYPER
    assert evidence.capability.engine is HyperProviderKind.AUTOHYPER

    # System
    assert isinstance(evidence.system, HyperSystemBindingV2)
    assert evidence.system.system_kind is HyperSystemKind.EXPLICIT
    assert evidence.system.system_id
    assert evidence.system.model_present is True
    assert evidence.system.system_digest  # default explicit system is digested
    assert evidence.system.observation_policy_id == "policy:ni-v1"

    # Formula
    assert isinstance(evidence.formula, HyperFormulaBindingV2)
    assert evidence.formula.formula_id
    assert evidence.formula.formula_digest
    assert evidence.formula.quantifier_signature == ("forall", "forall")
    assert evidence.formula.alternation_count == 0
    assert evidence.formula.matrix_statement
    assert evidence.formula.formula_text  # translated text bound

    # Bounds
    assert isinstance(evidence.bounds, HyperBoundsBindingV2)
    assert evidence.bounds.finite_only is True
    assert evidence.bounds.authorizes_universal_proof is False
    assert evidence.bounds.semantics is HyperSemanticsKind.ENGINE_BOUNDED
    assert evidence.bounds.max_quantifier_alternations == (
        AUTOHYPER_CAPABILITY.max_quantifier_alternations
    )
    assert evidence.bounds.supports_forall_exists is False
    assert evidence.bounds.max_traces == 8
    assert evidence.bounds.max_pairs == 16

    # Witness status
    assert isinstance(evidence.witness, HyperWitnessBindingV2)
    assert evidence.witness.status is HyperWitnessStatus.ABSENT  # satisfied, no cex
    assert evidence.witness.formula_id == evidence.formula.formula_id
    assert evidence.witness.authorizes_universal_proof is False

    # Authority ceiling
    assert evidence.result_authority is ResultAuthority.HYPERPROPERTY
    assert evidence.authority_ceiling is ToolchainAuthorityCeiling.BOUNDED
    assert evidence.translation_ceiling is EvidenceAuthority.BOUNDED
    assert evidence.is_theorem_authority is False
    assert evidence.is_proved is False
    assert evidence.proof_established is False
    assert evidence.theorem_established is False
    assert evidence.hyperproperty_established is True

    wire = evidence.to_dict()
    assert wire["bindings_complete"] is True
    assert wire["engine"] == "autohyper"
    assert "system" in wire
    assert "formula" in wire
    assert "bounds" in wire
    assert "witness" in wire
    assert "witness_status" in wire
    assert wire["claim_theorem"] is False
    assert wire["claim_proof"] is False
    assert wire["authorizes_universal_proof"] is False


def test_mchyper_binds_aiger_system_and_requires_model() -> None:
    engine = _engine_with()
    aiger = b"aag 1 1 0 0 0\n"
    with_model = execute_mchyper(
        _document(),
        request_id="req:mc:with-model",
        system_model=aiger,
        engine=engine,
    )
    assert with_model.evidence.system.system_kind is HyperSystemKind.AIGER
    assert with_model.evidence.system.model_required is True
    assert with_model.evidence.system.model_present is True
    assert with_model.evidence.system.system_digest
    assert with_model.evidence.hyperproperty_established is True
    assert with_model.disposition is HyperDisposition.SATISFIED

    missing = execute_mchyper(
        _document(),
        request_id="req:mc:no-model",
        system_model=None,
        engine=engine,
    )
    assert missing.disposition is HyperDisposition.UNSUPPORTED
    assert missing.evidence.system.model_required is True
    assert missing.evidence.system.model_present is False
    assert missing.evidence.hyperproperty_established is False
    assert missing.evidence.bindings_complete() is True  # still binds ids


def test_hyperltl_system_kind_is_none() -> None:
    engine = _engine_with()
    result = execute_hyperltl(
        _document(),
        request_id="req:hltl:1",
        engine=engine,
    )
    assert result.evidence.engine is HyperProviderKind.HYPERLTL
    assert result.evidence.system.system_kind is HyperSystemKind.NONE
    assert result.evidence.system.model_required is False
    assert result.evidence.formula.quantifier_signature == ("forall", "forall")
    assert result.evidence.bounds.supports_exists_forall is True
    assert result.evidence.bounds.supports_forall_exists is True


def test_witness_status_on_violation_with_replay() -> None:
    counterexample = """\
unsat
TRACE pi1:
  public.user_id = alice
  obs.status = ok
TRACE pi2:
  public.user_id = alice
  obs.status = leak
DIFF field=status left=ok right=leak
"""
    engine = HyperExecutionEngineV2(
        hyperltl=HyperLTLBackend(
            runner=_process_runner(counterexample),
            executable="/bin/hyperltl",
        ),
        autohyper=AutoHyperBackend(which=lambda _n: None),
        mchyper=MCHyperBackend(which=lambda _n: None),
    )
    result = execute_hyperltl(
        _document(),
        request_id="req:cex:1",
        engine=engine,
    )
    assert result.disposition is HyperDisposition.VIOLATED
    assert result.witness_status is HyperWitnessStatus.COUNTEREXAMPLE_REPLAYED
    assert result.evidence.witness.replayed is True
    assert result.evidence.witness.trace_count == 2
    assert result.evidence.witness.difference_count >= 1
    assert result.evidence.witness.counterexample is not None
    assert result.evidence.hyperproperty_established is True
    assert result.evidence.external_tool_proof is True


# ---------------------------------------------------------------------------
# Quantifier-prefix ceilings stay engine-local
# ---------------------------------------------------------------------------


def test_exists_forall_unsupported_on_mchyper_only() -> None:
    document = _alternating_document(
        signature=(TraceQuantifier.EXISTS, TraceQuantifier.FORALL)
    )
    engine = _engine_with()
    aiger = b"aag 0 0 0 0 0\n"

    auto = execute_autohyper(
        document, request_id="req:ea:auto", engine=engine
    )
    mc = execute_mchyper(
        document,
        request_id="req:ea:mc",
        system_model=aiger,
        engine=engine,
    )
    # AutoHyper supports exists-forall; MCHyper does not.
    assert auto.evidence.bounds.supports_exists_forall is True
    assert auto.disposition is HyperDisposition.SATISFIED
    assert mc.disposition is HyperDisposition.UNSUPPORTED
    assert mc.evidence.bounds.supports_exists_forall is False
    assert auto.evidence.establishes_other_engine(HyperProviderKind.MCHYPER) is False
    assert mc.evidence.capability.engine is HyperProviderKind.MCHYPER


def test_forall_exists_unsupported_on_autohyper_only() -> None:
    document = _alternating_document(
        signature=(TraceQuantifier.FORALL, TraceQuantifier.EXISTS)
    )
    engine = _engine_with()
    aiger = b"aag 0 0 0 0 0\n"

    auto = execute_autohyper(
        document, request_id="req:ae:auto", engine=engine
    )
    mc = execute_mchyper(
        document,
        request_id="req:ae:mc",
        system_model=aiger,
        engine=engine,
    )
    assert auto.disposition is HyperDisposition.UNSUPPORTED
    assert auto.evidence.bounds.supports_forall_exists is False
    # MCHyper supports forall-exists.
    assert mc.evidence.bounds.supports_forall_exists is True
    assert mc.disposition is HyperDisposition.SATISFIED


# ---------------------------------------------------------------------------
# Mock / fallback / availability cannot establish hyperproperty or theorem
# ---------------------------------------------------------------------------


def test_non_authoritative_signals_never_establish_claims() -> None:
    for claim in HyperClaimKind:
        assert (
            non_authoritative_signal_establishes(
                claim,
                mock_output={"status": "satisfied"},
                fallback_output={"status": "satisfied"},
                available=True,
                confidence=1.0,
                fluent_text="Obviously holds.",
                other_engine_available=True,
            )
            is False
        )


def test_mock_output_rejected_and_still_binds_identifiers() -> None:
    result = execute_hyper(
        _document(),
        provider=HyperProviderKind.AUTOHYPER,
        request_id="req:mock:1",
        mock_output={"status": "satisfied", "proved": True},
        confidence=1.0,
        available=True,
        fluent_text="Mock says holds.",
        engine=_engine_with(),
    )
    assert result.disposition is HyperDisposition.MOCK_REJECTED
    assert result.hyperproperty_established is False
    assert result.evidence.mock_output_present is True
    assert result.evidence.mode is HyperExecutionMode.MOCK
    assert result.evidence.bindings_complete() is True
    assert result.evidence.engine is HyperProviderKind.AUTOHYPER
    assert result.evidence.formula.formula_id
    assert result.evidence.system.system_id
    assert result.evidence.bounds.finite_only is True
    assert result.evidence.witness.status is HyperWitnessStatus.NONE
    assert "mock_output_cannot_establish_hyperproperty" in result.evidence.diagnostics
    assert "mock_output_cannot_establish_other_engine_capability" in (
        result.evidence.diagnostics
    )
    wire = result.evidence.to_dict()
    assert wire["claim_hyperproperty"] is False
    assert wire["claim_theorem"] is False
    assert wire["is_proved"] is False


def test_fallback_output_rejected() -> None:
    result = execute_hyper(
        _document(),
        provider=HyperProviderKind.MCHYPER,
        request_id="req:fallback:1",
        fallback_output={"status": "satisfied"},
        available=False,
        engine=_engine_with(),
    )
    assert result.disposition is HyperDisposition.FALLBACK_REJECTED
    assert result.hyperproperty_established is False
    assert result.evidence.fallback_output_present is True
    assert result.evidence.mode is HyperExecutionMode.FALLBACK


def test_cannot_construct_evidence_with_mock_and_hyper_authority() -> None:
    document = _document()
    formula = HyperFormulaBindingV2.from_document(document)
    system = HyperSystemBindingV2.from_request(
        provider=HyperProviderKind.AUTOHYPER,
        document=document,
        system_model=None,
    )
    bounds = HyperBoundsBindingV2.from_capability(
        AUTOHYPER_CAPABILITY,
        bounds=ExecutionBounds(timeout_ms=100, max_steps=10),
        document=document,
    )
    witness = HyperWitnessBindingV2(
        status=HyperWitnessStatus.NONE,
        formula_id=document.formula.formula_id,
        observation_policy_id="policy:ni-v1",
    )
    capability = HyperCapabilityReceiptV2(
        engine=HyperProviderKind.AUTOHYPER,
        available=True,
        supported_prefix=True,
        capability=AUTOHYPER_CAPABILITY.to_dict(),
    )
    with pytest.raises(HyperAuthorityError, match="mock|fallback|capability"):
        HyperProviderEvidenceV2(
            evidence_id="ev:bad:mock",
            request_id="req:bad:mock",
            request_digest="0" * 64,
            engine=HyperProviderKind.AUTOHYPER,
            disposition=HyperDisposition.SATISFIED,
            mode=HyperExecutionMode.MOCK,
            formula=formula,
            system=system,
            bounds=bounds,
            witness=witness,
            capability=capability,
            hyperproperty_established=True,
            mock_output_present=True,
        )


def test_cannot_claim_theorem_result_status() -> None:
    document = _document()
    formula = HyperFormulaBindingV2.from_document(document)
    system = HyperSystemBindingV2.from_request(
        provider=HyperProviderKind.HYPERLTL,
        document=document,
        system_model=None,
    )
    bounds = HyperBoundsBindingV2.from_capability(
        HYPERLTL_CAPABILITY,
        bounds=ExecutionBounds(timeout_ms=100, max_steps=10),
        document=document,
    )
    witness = HyperWitnessBindingV2(
        status=HyperWitnessStatus.NONE,
        formula_id=document.formula.formula_id,
        observation_policy_id="policy:ni-v1",
    )
    capability = HyperCapabilityReceiptV2(
        engine=HyperProviderKind.HYPERLTL,
        available=True,
        supported_prefix=True,
        capability=HYPERLTL_CAPABILITY.to_dict(),
    )
    with pytest.raises(HyperAuthorityError, match="theorem"):
        HyperProviderEvidenceV2(
            evidence_id="ev:bad:theorem",
            request_id="req:bad:theorem",
            request_digest="0" * 64,
            engine=HyperProviderKind.HYPERLTL,
            disposition=HyperDisposition.SATISFIED,
            mode=HyperExecutionMode.ENGINE,
            formula=formula,
            system=system,
            bounds=bounds,
            witness=witness,
            capability=capability,
            result_status=ResultStatus.PROVED,
            hyperproperty_established=True,
        )


def test_capability_engine_mismatch_rejected() -> None:
    document = _document()
    formula = HyperFormulaBindingV2.from_document(document)
    system = HyperSystemBindingV2.from_request(
        provider=HyperProviderKind.AUTOHYPER,
        document=document,
        system_model=None,
    )
    bounds = HyperBoundsBindingV2.from_capability(
        AUTOHYPER_CAPABILITY,
        bounds=ExecutionBounds(timeout_ms=100, max_steps=10),
        document=document,
    )
    witness = HyperWitnessBindingV2(
        status=HyperWitnessStatus.NONE,
        formula_id=document.formula.formula_id,
        observation_policy_id="policy:ni-v1",
    )
    # Capability for MCHyper attached to AutoHyper evidence.
    capability = HyperCapabilityReceiptV2(
        engine=HyperProviderKind.MCHYPER,
        available=True,
        supported_prefix=True,
        capability=MCHYPER_CAPABILITY.to_dict(),
    )
    with pytest.raises(HyperAuthorityError, match="cannot establish"):
        HyperProviderEvidenceV2(
            evidence_id="ev:bad:cross",
            request_id="req:bad:cross",
            request_digest="0" * 64,
            engine=HyperProviderKind.AUTOHYPER,
            disposition=HyperDisposition.SATISFIED,
            mode=HyperExecutionMode.ENGINE,
            formula=formula,
            system=system,
            bounds=bounds,
            witness=witness,
            capability=capability,
            hyperproperty_established=True,
        )


# ---------------------------------------------------------------------------
# Unavailable engines remain non-success without elevating peers
# ---------------------------------------------------------------------------


def test_unavailable_engine_does_not_elevate_or_cross_establish() -> None:
    engine = HyperExecutionEngineV2(
        hyperltl=HyperLTLBackend(which=lambda _n: None),
        autohyper=AutoHyperBackend(which=lambda _n: None),
        mchyper=MCHyperBackend(which=lambda _n: None),
    )
    result = execute_autohyper(
        _document(),
        request_id="req:unavail:auto",
        engine=engine,
    )
    assert result.disposition is HyperDisposition.UNAVAILABLE
    assert result.evidence.hyperproperty_established is False
    assert result.evidence.result_status is ResultStatus.UNAVAILABLE
    assert result.evidence.bindings_complete() is True
    assert result.evidence.engine is HyperProviderKind.AUTOHYPER
    assert result.evidence.establishes_other_engine(HyperProviderKind.MCHYPER) is False
    assert result.evidence.establishes_other_engine(HyperProviderKind.HYPERLTL) is False


def test_capability_probe_mode_never_establishes_hyperproperty() -> None:
    engine = _engine_with()
    result = engine.execute(
        HyperExecutionRequestV2(
            request_id="req:probe:auto",
            provider=HyperProviderKind.AUTOHYPER,
            document=_document(),
            mode=HyperExecutionMode.CAPABILITY_PROBE,
        )
    )
    assert result.disposition is HyperDisposition.CAPABILITY_ONLY
    assert result.hyperproperty_established is False
    assert result.evidence.mode is HyperExecutionMode.CAPABILITY_PROBE
    assert result.evidence.bounds.semantics is HyperSemanticsKind.CAPABILITY_ONLY
    assert result.evidence.bindings_complete() is True
    assert result.evidence.capability.available is True


def test_backend_construction_rejects_swapped_engines() -> None:
    with pytest.raises(HyperAuthorityError, match="must own engine"):
        HyperExecutionEngineV2(
            hyperltl=AutoHyperBackend(),  # wrong engine for hyperltl slot
        )


def test_role_and_authority_ceiling() -> None:
    engine = _engine_with()
    result = execute_autohyper(
        _document(), request_id="req:role:1", engine=engine
    )
    assert result.evidence.role is ToolRole.AUTHORITY
    assert result.evidence.authority_ceiling is ToolchainAuthorityCeiling.BOUNDED
    assert result.evidence.result_authority is ResultAuthority.HYPERPROPERTY
    if result.backend_result is not None:
        assert result.backend_result.authority is ResultAuthority.HYPERPROPERTY
