"""UIR-027: constrained Intent/IDL formal-to-UI synthesis."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.formalize.contracts import (
    CoverageDisposition,
    FormalView,
    ResultAuthority,
)
from ipfs_datasets_py.logic.ui_ux_ir.formalize.synthesis import (
    AdmissionDisposition,
    AdmissionGate,
    ExternalCandidateDraft,
    ReviewedFormalConstraint,
    SynthesisInputs,
    SynthesisPolicy,
    SynthesisProgramSeed,
    SynthesisProviderKind,
    TEMPLATE_PROVIDER_ID,
    UI_SYNTHESIZER_INTERFACE,
    UISynthesizer,
    admit_candidate,
    build_template_document,
    synthesize_template_candidate,
    synthesize_ui_ir,
)
from ipfs_datasets_py.logic.ui_ux_ir.model.bindings import (
    ConfirmationClass,
    RiskClass,
    UIActionBinding,
    UIProgramRef,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import (
    AuthorityKind,
    ProgramBindingTargetKind,
    ReviewStatus,
    TerminalOutcomeKind,
    UIComponent,
    UIIRDocument,
    UIIRValidationError,
    UISourceRef,
    UITerminalOutcome,
    UITrustBinding,
    validate_ui_ir,
)


def _source(ref_id: str = "source:skill-1") -> UISourceRef:
    return UISourceRef(
        ref_id=ref_id,
        source_uri="https://example.test/skills/one",
        source_id="skill-1",
        source_revision="rev-1",
        content_sha256="a" * 64,
        container_uri="hf://datasets/example/skills@rev-1/bundle.sqlite",
        container_sha256="b" * 64,
        review_status=ReviewStatus.TRUSTED_FIXTURE,
    )


def _mcp_seed(
    action_id: str = "submit",
    *,
    risk: RiskClass = RiskClass.MEDIUM,
    confirmation: ConfirmationClass = ConfirmationClass.NONE,
    formal_constraint_ids: tuple[str, ...] = (),
) -> SynthesisProgramSeed:
    return SynthesisProgramSeed(
        action_id=action_id,
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.MCP_IDL,
            mcp_idl_interface_cid=(
                "bafkreicotxqdc6qhz3h3miegt37q3iz2syjrhj7z4mhjd2sidi35bx3t5i"
            ),
            mcp_idl_method_name=action_id,
        ),
        risk_class=risk,
        confirmation_class=confirmation,
        source_ref_ids=("source:skill-1",),
        formal_constraint_ids=formal_constraint_ids,
        label=action_id,
    )


def _intent_seed(action_id: str = "action:build") -> SynthesisProgramSeed:
    return SynthesisProgramSeed(
        action_id=action_id,
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.INTENT_IR,
            intent_document_id="intent:skill-1",
            intent_action_id=action_id,
        ),
        risk_class=RiskClass.LOW,
        confirmation_class=ConfirmationClass.NONE,
        source_ref_ids=("source:skill-1",),
        formal_constraint_ids=("constraint:build-order",),
        label="Build",
    )


def _baseline_inputs(**overrides: object) -> SynthesisInputs:
    kwargs = {
        "document_id": "ui:synth:demo",
        "title": "Build and submit artifact",
        "sources": (_source(),),
        "program_seeds": (
            _intent_seed("action:build"),
            _mcp_seed("submit", risk=RiskClass.MEDIUM),
        ),
    }
    kwargs.update(overrides)
    return SynthesisInputs(**kwargs)  # type: ignore[arg-type]


def _constraints() -> tuple[ReviewedFormalConstraint, ...]:
    return (
        ReviewedFormalConstraint(
            constraint_id="constraint:build-order",
            view=FormalView.TDFOL,
            formula_ref="obligation:invoke(action:build)",
            coverage=CoverageDisposition.FULL,
            source_ref_ids=("source:skill-1",),
            required=True,
        ),
    )


def test_deterministic_template_baseline_works_without_model() -> None:
    result = synthesize_ui_ir(_baseline_inputs(), _constraints())
    assert result.interface == UI_SYNTHESIZER_INTERFACE
    assert result.template_provider_id == TEMPLATE_PROVIDER_ID
    assert result.result_authority is ResultAuthority.NONE
    assert result.candidates
    template = result.candidates[0]
    assert template.provider_kind is SynthesisProviderKind.DETERMINISTIC_TEMPLATE
    assert template.provider_id == TEMPLATE_PROVIDER_ID
    assert template.confidence == 1.0
    assert template.authority_kind is AuthorityKind.SYNTHESIS_CANDIDATE
    assert template.result_authority is ResultAuthority.NONE
    # Template candidate admits through all gates when inputs are complete.
    assert template.admission is not None
    assert template.admission.admitted is True
    assert template.candidate_id in result.admitted_candidate_ids
    validate_ui_ir(template.document)


def test_all_admission_gates_pass_on_template() -> None:
    candidate = synthesize_template_candidate(_baseline_inputs(), _constraints())
    assert candidate.admission is not None
    by_gate = {gate.gate: gate for gate in candidate.admission.gates}
    for gate in AdmissionGate:
        assert gate in by_gate
        assert by_gate[gate].disposition is AdmissionDisposition.PASS
        assert by_gate[gate].passed is True


def test_candidate_never_receives_elevated_authority_from_generation() -> None:
    result = synthesize_ui_ir(_baseline_inputs(), _constraints())
    assert result.denied_authorities == (
        "proof",
        "policy",
        "delegation",
        "execution",
    )
    for candidate in result.candidates:
        assert candidate.authority_kind is AuthorityKind.SYNTHESIS_CANDIDATE
        assert candidate.result_authority is ResultAuthority.NONE
        assert candidate.admission is not None
        assert candidate.admission.claims_proof is False
        assert candidate.admission.claims_policy_authority is False
        assert candidate.admission.claims_delegation is False
        assert candidate.admission.claims_execution is False
        assert candidate.document.proof_obligation_refs == ()
        for trust in candidate.document.trust_bindings:
            assert trust.authority_kind is AuthorityKind.SYNTHESIS_CANDIDATE


def test_missing_actions_clarify_or_fail_closed() -> None:
    result = synthesize_ui_ir(
        SynthesisInputs(
            document_id="ui:synth:empty",
            title="Empty",
            sources=(_source(),),
            program_seeds=(),
            action_bindings=(),
        )
    )
    template = result.candidates[0]
    assert template.admission is not None
    assert template.admission.admitted is False
    codes = {c.code for c in template.admission.clarifications}
    assert "seed.missing_actions" in codes or any(
        c.code.startswith("gate.fail.") for c in template.admission.clarifications
    )


def test_unresolved_source_refs_fail_source_gate() -> None:
    seed = SynthesisProgramSeed(
        action_id="orphan",
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.LOCAL_STATE,
            local_state_transition="state:idle",
        ),
        source_ref_ids=("source:does-not-exist",),
    )
    result = synthesize_ui_ir(
        SynthesisInputs(
            document_id="ui:synth:orphan-src",
            title="Orphan source",
            sources=(_source(),),
            program_seeds=(seed,),
        )
    )
    admission = result.candidates[0].admission
    assert admission is not None
    source_gate = next(g for g in admission.gates if g.gate is AdmissionGate.SOURCE)
    # Template remaps to fallback source for the document, but still records
    # clarification for unresolved seed refs; schema/source on the document
    # should still be consistent.
    assert any(
        c.code == "source.unresolved" for c in admission.clarifications
    ) or source_gate.disposition is not AdmissionDisposition.PASS


def test_missing_accessibility_fails_accessibility_gate() -> None:
    candidate = synthesize_template_candidate(_baseline_inputs(), _constraints())
    document = candidate.document
    # Strip accessibility to force gate failure.
    broken = UIIRDocument(
        document_id=document.document_id,
        title=document.title,
        sources=document.sources,
        components=document.components,
        entry_components=document.entry_components,
        terminal_outcomes=document.terminal_outcomes,
        program_bindings=document.program_bindings,
        localization=document.localization,
        input_modality_requirements=document.input_modality_requirements,
        output_modality_requirements=document.output_modality_requirements,
        modality_alternatives=document.modality_alternatives,
        device_capability_requirements=document.device_capability_requirements,
        formal_constraint_refs=document.formal_constraint_refs,
        trust_bindings=document.trust_bindings,
        accessibility=(),
        composition_edges=document.composition_edges,
        layout_regions=document.layout_regions,
        ux_tasks=document.ux_tasks,
        mcp_idl_bindings=document.mcp_idl_bindings,
        producer=document.producer,
        review=document.review,
        tags=document.tags,
    )
    receipt = admit_candidate(
        broken,
        candidate_id="cand:broken-a11y",
        confidence=1.0,
        policy=SynthesisPolicy(),
        constraints=_constraints(),
        formal_coverage=candidate.formal_coverage,
    )
    a11y = next(g for g in receipt.gates if g.gate is AdmissionGate.ACCESSIBILITY)
    assert a11y.disposition is AdmissionDisposition.FAIL
    assert receipt.admitted is False


def test_unknown_capability_fails_capability_gate() -> None:
    candidate = synthesize_template_candidate(
        SynthesisInputs(
            document_id="ui:synth:bad-cap",
            title="Bad capability",
            sources=(_source(),),
            program_seeds=(_mcp_seed("run"),),
            required_input_capabilities=("not_a_real_capability",),
            alternative_input_capabilities=("also_fake",),
        ),
        (),
    )
    cap = next(
        g for g in candidate.admission.gates if g.gate is AdmissionGate.CAPABILITY
    )
    assert cap.disposition is AdmissionDisposition.FAIL
    assert candidate.admission.admitted is False


def test_high_risk_without_confirmation_is_policy_repaired_or_rejected() -> None:
    # Seed with destructive risk and none confirmation: template infers confirm.
    seed = _mcp_seed(
        "delete",
        risk=RiskClass.DESTRUCTIVE,
        confirmation=ConfirmationClass.NONE,
    )
    candidate = synthesize_template_candidate(
        SynthesisInputs(
            document_id="ui:synth:delete",
            title="Delete",
            sources=(_source(),),
            program_seeds=(seed,),
        )
    )
    assert candidate.admission is not None
    for binding in candidate.document.program_bindings:
        if binding.risk_class == "destructive":
            assert binding.confirmation_class != "none"
    policy_gate = next(
        g for g in candidate.admission.gates if g.gate is AdmissionGate.POLICY
    )
    assert policy_gate.disposition is AdmissionDisposition.PASS


def test_learned_provider_output_remains_candidate_only() -> None:
    class _FakeProvider:
        def propose(self, inputs, constraints, policy):
            # Return a deliberately incomplete draft.
            source = _source()
            doc = UIIRDocument(
                document_id="ui:learned:bad",
                title="Learned draft",
                sources=(source,),
                components=(
                    UIComponent(
                        component_id="component:only",
                        role="button",
                        purpose="Learned button",
                        source_ref_ids=(source.ref_id,),
                    ),
                ),
                entry_components=("component:only",),
                terminal_outcomes=(
                    UITerminalOutcome(
                        outcome_id="outcome:ok",
                        kind=TerminalOutcomeKind.SUCCESS,
                        source_ref_ids=(source.ref_id,),
                    ),
                ),
                trust_bindings=(
                    UITrustBinding(
                        trust_id="trust:learned",
                        # Adversarial: attempt to claim proof authority.
                        authority_kind=AuthorityKind.PROOF,
                        subject_ref="ui:learned:bad",
                        source_ref_ids=(source.ref_id,),
                    ),
                ),
            )
            return (
                ExternalCandidateDraft(
                    draft_id="candidate:learned:1",
                    document=doc,
                    provider_id="fake.llm@test",
                    provider_kind=SynthesisProviderKind.LEARNED,
                    confidence=0.9,
                    provenance=("llm:fake",),
                ),
            )

    result = synthesize_ui_ir(
        _baseline_inputs(),
        _constraints(),
        learned_provider=_FakeProvider(),
    )
    learned = next(
        c
        for c in result.candidates
        if c.provider_kind is SynthesisProviderKind.LEARNED
    )
    assert learned.authority_kind is AuthorityKind.SYNTHESIS_CANDIDATE
    assert learned.result_authority is ResultAuthority.NONE
    assert learned.admission is not None
    assert learned.admission.admitted is False
    assert learned.admission.claims_proof is False
    policy_gate = next(
        g for g in learned.admission.gates if g.gate is AdmissionGate.POLICY
    )
    assert policy_gate.disposition is AdmissionDisposition.FAIL
    assert any("trust" in item or "authority" in item for item in policy_gate.counterexamples)


def test_adversarial_external_draft_cannot_claim_execution_or_delegation() -> None:
    source = _source()
    # Build a schema-valid-looking shell that still fails policy on authority.
    draft_doc = UIIRDocument(
        document_id="ui:adv:exec",
        title="Adversarial",
        sources=(source,),
        components=(
            UIComponent(
                component_id="component:root",
                role="form",
                purpose="Adversarial root",
                child_ids=("component:go",),
                source_ref_ids=(source.ref_id,),
            ),
            UIComponent(
                component_id="component:go",
                role="button",
                purpose="Go",
                parent_id="component:root",
                source_ref_ids=(source.ref_id,),
            ),
        ),
        entry_components=("component:root",),
        terminal_outcomes=(
            UITerminalOutcome(
                outcome_id="outcome:ok",
                kind=TerminalOutcomeKind.SUCCESS,
                source_ref_ids=(source.ref_id,),
            ),
        ),
        trust_bindings=(
            UITrustBinding(
                trust_id="trust:invocation",
                authority_kind=AuthorityKind.INVOCATION,
                subject_ref="ui:adv:exec",
                source_ref_ids=(source.ref_id,),
            ),
        ),
    )
    result = synthesize_ui_ir(
        _baseline_inputs(),
        _constraints(),
        external_drafts=(
            ExternalCandidateDraft(
                draft_id="candidate:adv:1",
                document=draft_doc,
                provider_id="adv.provider",
                provider_kind=SynthesisProviderKind.EXTERNAL,
                confidence=0.99,
            ),
        ),
    )
    adv = next(c for c in result.candidates if c.candidate_id == "candidate:adv:1")
    assert adv.admission is not None
    assert adv.admission.admitted is False
    assert adv.admission.claims_execution is False
    assert adv.admission.claims_delegation is False
    assert adv.candidate_id in result.rejected_candidate_ids


def test_partial_formal_coverage_clarifies_when_constraints_required() -> None:
    # Seed has no formal_constraint_ids while a required constraint is supplied;
    # no action carries full coverage → clarify rather than invent links.
    seed = _mcp_seed("run")
    result = synthesize_ui_ir(
        SynthesisInputs(
            document_id="ui:synth:partial",
            title="Partial formal",
            sources=(_source(),),
            program_seeds=(seed,),
        ),
        _constraints(),
    )
    admission = result.candidates[0].admission
    assert admission is not None
    formal = next(
        g for g in admission.gates if g.gate is AdmissionGate.FORMAL_COVERAGE
    )
    assert formal.disposition in {
        AdmissionDisposition.CLARIFY,
        AdmissionDisposition.FAIL,
    }
    assert admission.admitted is False
    assert any(
        c.code in {"formal.partial_action", "formal.unlinked_required", "gate.clarify.formal_coverage"}
        or c.code.startswith("gate.")
        for c in admission.clarifications
    )


def test_policy_hard_locks_authority_elevation_flags() -> None:
    policy = SynthesisPolicy(
        allow_proof_authority=True,  # type: ignore[arg-type]
        allow_policy_authority=True,  # type: ignore[arg-type]
        allow_delegation_authority=True,  # type: ignore[arg-type]
        allow_execution_authority=True,  # type: ignore[arg-type]
    )
    assert policy.allow_proof_authority is False
    assert policy.allow_policy_authority is False
    assert policy.allow_delegation_authority is False
    assert policy.allow_execution_authority is False


def test_ui_synthesizer_facade_and_action_bindings() -> None:
    binding = UIActionBinding(
        binding_id="bind:intent:validate",
        action_id="action:validate",
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.INTENT_IR,
            intent_document_id="intent:skill-1",
            intent_action_id="action:validate",
        ),
        risk_class=RiskClass.LOW,
        confirmation_class=ConfirmationClass.NONE,
        source_ref_ids=("source:skill-1",),
        formal_constraint_ids=("constraint:build-order",),
    )
    synth = UISynthesizer()
    result = synth.synthesize(
        SynthesisInputs(
            document_id="ui:synth:bindings",
            title="From bindings",
            sources=(_source(),),
            action_bindings=(binding,),
        ),
        _constraints(),
    )
    assert result.admitted_candidate_ids
    assert result.candidates[0].document.program_bindings


def test_build_template_document_is_deterministic() -> None:
    inputs = _baseline_inputs()
    constraints = _constraints()
    doc_a, cov_a, _ = build_template_document(inputs, constraints)
    doc_b, cov_b, _ = build_template_document(inputs, constraints)
    assert doc_a.to_dict() == doc_b.to_dict()
    assert [c.to_dict() for c in cov_a] == [c.to_dict() for c in cov_b]


def test_learned_provider_not_called_when_disabled() -> None:
    class _Boom:
        def propose(self, *args, **kwargs):
            raise AssertionError("provider must not be called when disabled")

    result = synthesize_ui_ir(
        _baseline_inputs(),
        _constraints(),
        SynthesisPolicy(allow_learned_providers=False),
        learned_provider=_Boom(),
    )
    assert all(
        c.provider_kind is SynthesisProviderKind.DETERMINISTIC_TEMPLATE
        for c in result.candidates
    )


def test_schema_gate_rejects_invalid_document() -> None:
    with pytest.raises(UIIRValidationError):
        validate_ui_ir(
            UIIRDocument(
                document_id="bad",
                title="",
                sources=(),
                components=(),
                entry_components=(),
                terminal_outcomes=(),
            )
        )
