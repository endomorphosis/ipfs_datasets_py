"""Contract tests for PlateauCodexPacket@1 prover-gated Codex packets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRule,
    CanonicalRuleIR,
)
from benchmarks.semantic_roundtrip.plateau_codex_packet import (
    ALLOWED_PREDICTED_FILE_PREFIXES,
    DEFAULT_BASELINE_ARM_ID,
    DEFAULT_BASELINE_E2E,
    DEFAULT_HOLDOUT_VALIDATION_COMMANDS,
    DEFAULT_PREDICTED_FILES,
    DEFAULT_REPAIR_DEV_PACKET_METRICS_RELATIVE_PATH,
    DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS,
    DEFAULT_VALIDATION_COMMANDS,
    ExpansionHandle,
    HOLDOUT_BASELINE_E2E,
    HOLDOUT_POPULATION_KIND,
    NON_IMPLEMENTABLE_DISPOSITIONS,
    PACKET_TOKEN_BUDGET,
    PLATEAU_CODEX_PACKET_EVIDENCE,
    PLATEAU_CODEX_PACKET_INTERFACE,
    PLATEAU_CODEX_PACKET_SCHEMA,
    PacketBindings,
    PlateauAdmissionReceipt,
    PlateauCodexPacket,
    PlateauCodexPacketError,
    ProofObligation,
    ProverCheckReceipt,
    REPAIR_DEV_BASELINE_E2E,
    REPAIR_DEV_PACKET_CONTEXT_METRICS_INTERFACE,
    REPAIR_DEV_POPULATION_KIND,
    ResidualRef,
    TeacherProposal,
    assert_catalog_allowed_for_packets,
    baseline_l1_digest,
    build_holdout_codex_packet,
    build_holdout_packet_from_proposal_admission,
    build_holdout_packets_from_residual_catalog,
    build_packet_from_proposal_admission,
    build_plateau_codex_packet,
    build_repair_dev_codex_packet,
    build_repair_dev_packet_context_metrics,
    build_repair_dev_packet_from_proposal_admission,
    build_repair_dev_packets_from_residual_catalog,
    disposition_is_implementable,
    extract_catalog_bindings,
    mint_proof_obligations,
    plan_expansion_handles,
    residual_ref_from_catalog_facet,
    residual_refs_from_catalog,
    stable_residual_id,
    write_repair_dev_packet_context_metrics,
)
from benchmarks.semantic_roundtrip.residual_catalog import (
    CATALOG_STATUS_NOT_MEASURED,
    CATALOG_STATUS_UNSUPPORTED,
)
from benchmarks.semantic_roundtrip.selective_repair import (
    DECLARED_STRUCTURAL_CONSTRAINTS,
    StructuralTool,
)
from benchmarks.semantic_roundtrip.structural_admission import (
    AdmissionDisposition,
    StructuralAdmissionGate,
    StructuralAdmissionPolicy,
    admit_hybrid_repair,
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
OBJECT_PATH = "rules[0].object"


def _residual(
    residual_id: str = "resid-legal-object",
    case_id: str = "legal_doc_1",
) -> ResidualRef:
    return ResidualRef(
        residual_id=residual_id,
        case_id=case_id,
        field_paths=(OBJECT_PATH,),
        facet="object",
        estimated_forward_contribution=0.05,
        catalog_digest="a" * 64,
        detail="missing object atom on pilot residual",
    )


def _proposal(
    proposal_id: str = "prop-leanstral-1",
    residual_id: str = "resid-legal-object",
    candidate: CanonicalRuleIR | None = CANDIDATE,
) -> TeacherProposal:
    return TeacherProposal(
        proposal_id=proposal_id,
        teacher="leanstral",
        residual_ref_ids=(residual_id,),
        allowed_field_paths=(OBJECT_PATH,),
        candidate_l1=candidate,
        detail="selective object fill proposal",
        semantic_authority=False,
    )


def _accept_gate() -> StructuralAdmissionGate:
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


def _reject_gate() -> StructuralAdmissionGate:
    return StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(
            make_rejecting_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
                detail="candidate violates structural constraint",
            ),
        ),
    )


def _timeout_gate() -> StructuralAdmissionGate:
    return StructuralAdmissionGate(
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


def _error_gate() -> StructuralAdmissionGate:
    return StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(
            make_error_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
            ),
        ),
    )


def test_interface_constants_and_defaults() -> None:
    assert PLATEAU_CODEX_PACKET_INTERFACE == "PlateauCodexPacket@1"
    assert PLATEAU_CODEX_PACKET_SCHEMA.startswith("ipfs-datasets.")
    assert PLATEAU_CODEX_PACKET_EVIDENCE == "PLATEV020PKT"
    assert DEFAULT_BASELINE_ARM_ID.endswith("deterministic")
    assert DEFAULT_BASELINE_E2E == pytest.approx(0.088333333)
    assert DEFAULT_PREDICTED_FILES
    assert DEFAULT_VALIDATION_COMMANDS
    assert "benchmarks/semantic_roundtrip/constructors/" in (
        ALLOWED_PREDICTED_FILE_PREFIXES
    )
    assert AdmissionDisposition.VALIDATOR_REJECT in NON_IMPLEMENTABLE_DISPOSITIONS
    assert AdmissionDisposition.TIMEOUT in NON_IMPLEMENTABLE_DISPOSITIONS
    assert AdmissionDisposition.ERROR in NON_IMPLEMENTABLE_DISPOSITIONS
    assert disposition_is_implementable(AdmissionDisposition.ACCEPTED) is True
    assert (
        disposition_is_implementable(AdmissionDisposition.VALIDATOR_REJECT)
        is False
    )


def test_accepted_packet_is_implementable_with_required_fields() -> None:
    admission = admit_hybrid_repair(
        PRIOR,
        CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=(OBJECT_PATH,),
    )
    assert admission.disposition is AdmissionDisposition.ACCEPTED

    packet = build_packet_from_proposal_admission(
        packet_id="pkt-legal-accept-1",
        baseline_l1=PRIOR,
        residual_ref=_residual(),
        proposal=_proposal(),
        admission=admission,
        case_id="legal_doc_1",
        detail="accepted object fill for legal_doc_1",
    )

    assert packet.implementable is True
    assert packet.baseline_l1_digest == baseline_l1_digest(PRIOR)
    assert packet.baseline_l1_digest == packet.baseline_l1_digest
    assert len(packet.residual_refs) == 1
    assert packet.residual_refs[0].residual_id == "resid-legal-object"
    assert len(packet.proposals) == 1
    assert packet.proposals[0].teacher == "leanstral"
    assert packet.proposals[0].semantic_authority is False
    assert len(packet.admission_receipts) == 1
    receipt = packet.admission_receipts[0]
    assert receipt.disposition is AdmissionDisposition.ACCEPTED
    assert receipt.semantic_authority is False
    assert all(
        check.semantic_authority is False for check in receipt.check_receipts
    )
    assert packet.proof_obligation_ids == ()
    assert packet.proof_obligations == ()
    assert packet.predicted_files
    assert packet.validation_commands
    assert packet.admitted_field_changes
    assert all(
        change.canonical_field == "object"
        for change in packet.admitted_field_changes
    )
    payload = packet.to_dict()
    assert payload["interface"] == PLATEAU_CODEX_PACKET_INTERFACE
    assert payload["schema"] == PLATEAU_CODEX_PACKET_SCHEMA
    assert payload["baseline_l1_digest"] == packet.baseline_l1_digest
    assert payload["implementable"] is True
    assert payload["semantic_authority"] is False
    assert payload["proof_obligation_ids"] == []
    assert "packet_digest" in payload
    assert payload["packet_digest"] == packet.packet_digest


@pytest.mark.parametrize(
    "gate_factory,expected_disposition",
    [
        (_reject_gate, AdmissionDisposition.VALIDATOR_REJECT),
        (_timeout_gate, AdmissionDisposition.TIMEOUT),
        (_error_gate, AdmissionDisposition.ERROR),
    ],
)
def test_reject_timeout_error_force_implementable_false(
    gate_factory,
    expected_disposition: AdmissionDisposition,
) -> None:
    admission = admit_hybrid_repair(
        PRIOR,
        CANDIDATE,
        gate=gate_factory(),
        allowed_field_paths=(OBJECT_PATH,),
    )
    assert admission.disposition is expected_disposition

    packet = build_packet_from_proposal_admission(
        packet_id=f"pkt-{expected_disposition.value}",
        baseline_l1=PRIOR,
        residual_ref=_residual(),
        proposal=_proposal(),
        admission=admission,
    )

    assert packet.implementable is False
    assert packet.primary_disposition is expected_disposition
    assert packet.admitted_field_changes == ()
    assert packet.proof_obligation_ids
    assert len(packet.proof_obligations) >= 1
    for obligation in packet.proof_obligations:
        assert obligation.semantic_authority is False
        assert obligation.disposition in {
            expected_disposition.value,
            "validator_reject",
        }
        assert obligation.obligation_id in packet.proof_obligation_ids
    for receipt in packet.admission_receipts:
        assert receipt.semantic_authority is False
        assert receipt.implementable_authority is False
        for check in receipt.check_receipts:
            assert check.semantic_authority is False


def test_not_applicable_is_not_implementable() -> None:
    admission = admit_hybrid_repair(
        PRIOR,
        None,
        gate=_accept_gate(),
    )
    assert admission.disposition is AdmissionDisposition.NOT_APPLICABLE
    packet = build_plateau_codex_packet(
        packet_id="pkt-not-applicable",
        baseline_l1=PRIOR,
        residual_refs=(_residual(),),
        proposals=(),
        admission_results=(admission,),
    )
    assert packet.implementable is False
    assert packet.proof_obligations == ()
    assert packet.admitted_field_changes == ()


def test_round_trip_serialize_deserialize_preserves_digest() -> None:
    admission = admit_hybrid_repair(
        PRIOR,
        CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=(OBJECT_PATH,),
    )
    original = build_packet_from_proposal_admission(
        packet_id="pkt-roundtrip",
        baseline_l1=PRIOR,
        residual_ref=_residual(),
        proposal=_proposal(),
        admission=admission,
        predicted_files=(
            "benchmarks/semantic_roundtrip/constructors/typed_deontic.py",
            "tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py",
        ),
        validation_commands=DEFAULT_VALIDATION_COMMANDS,
    )
    payload = original.to_dict()
    restored = PlateauCodexPacket.from_dict(payload)
    assert restored.packet_digest == original.packet_digest
    assert restored.to_dict() == original.to_dict()
    assert restored.implementable is True
    assert restored.baseline_l1 == PRIOR
    assert restored.proof_obligation_ids == original.proof_obligation_ids

    as_json = original.to_json()
    from_json = PlateauCodexPacket.from_json(as_json)
    assert from_json.packet_digest == original.packet_digest
    # Canonical JSON is stable under re-encode.
    assert json.loads(as_json)["packet_digest"] == original.packet_digest


def test_digest_mismatch_is_rejected() -> None:
    admission = admit_hybrid_repair(
        PRIOR,
        CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=(OBJECT_PATH,),
    )
    packet = build_packet_from_proposal_admission(
        packet_id="pkt-tamper",
        baseline_l1=PRIOR,
        residual_ref=_residual(),
        proposal=_proposal(),
        admission=admission,
    )
    payload = packet.to_dict()
    payload["packet_digest"] = "0" * 64
    with pytest.raises(PlateauCodexPacketError, match="packet_digest mismatch"):
        PlateauCodexPacket.from_dict(payload)


def test_cannot_force_implementable_true_on_reject() -> None:
    admission = admit_hybrid_repair(
        PRIOR,
        CANDIDATE,
        gate=_reject_gate(),
        allowed_field_paths=(OBJECT_PATH,),
    )
    receipt = PlateauAdmissionReceipt.from_structural_admission(
        admission, proposal_id="prop-leanstral-1"
    )
    residual = _residual()
    proposal = _proposal()
    with pytest.raises(PlateauCodexPacketError, match="implementable"):
        PlateauCodexPacket(
            packet_id="pkt-forced",
            baseline_l1=PRIOR,
            residual_refs=(residual,),
            proposals=(proposal,),
            admission_receipts=(receipt,),
            proof_obligations=(),
            predicted_files=DEFAULT_PREDICTED_FILES,
            validation_commands=DEFAULT_VALIDATION_COMMANDS,
            implementable=True,
            admitted_field_changes=tuple(admission.field_changes),
        )


def test_semantic_authority_forbidden_on_prover_and_teacher() -> None:
    with pytest.raises(PlateauCodexPacketError, match="semantic authority"):
        TeacherProposal(
            proposal_id="p1",
            teacher="leanstral",
            residual_ref_ids=(),
            allowed_field_paths=(OBJECT_PATH,),
            semantic_authority=True,
        )
    with pytest.raises(PlateauCodexPacketError, match="semantic authority"):
        ProverCheckReceipt(
            validator_id="lean",
            tool="lean",
            passed=True,
            timed_out=False,
            elapsed_seconds=0.01,
            constraints=DECLARED_STRUCTURAL_CONSTRAINTS,
            semantic_authority=True,
        )
    with pytest.raises(PlateauCodexPacketError, match="semantic authority"):
        ProofObligation(
            obligation_id="PO-1",
            constraint="non_vacuous_candidate",
            disposition="validator_reject",
            semantic_authority=True,
        )


def test_predicted_files_must_stay_on_det_surface() -> None:
    admission = admit_hybrid_repair(
        PRIOR,
        CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=(OBJECT_PATH,),
    )
    with pytest.raises(PlateauCodexPacketError, match="predicted file"):
        build_packet_from_proposal_admission(
            packet_id="pkt-bad-files",
            baseline_l1=PRIOR,
            residual_ref=_residual(),
            proposal=_proposal(),
            admission=admission,
            predicted_files=("/etc/passwd",),
        )
    with pytest.raises(PlateauCodexPacketError, match="predicted file"):
        build_packet_from_proposal_admission(
            packet_id="pkt-bad-files-2",
            baseline_l1=PRIOR,
            residual_ref=_residual(),
            proposal=_proposal(),
            admission=admission,
            predicted_files=("scripts/evil.py",),
        )


def test_mint_proof_obligations_from_reject() -> None:
    admission = admit_hybrid_repair(
        PRIOR,
        CANDIDATE,
        gate=_reject_gate(),
        allowed_field_paths=(OBJECT_PATH,),
    )
    obligations = mint_proof_obligations(
        admission,
        residual_ref_ids=("resid-legal-object",),
        proposal_id="prop-1",
        packet_id="pkt-1",
    )
    assert obligations
    assert all(item.semantic_authority is False for item in obligations)
    assert all(item.disposition == "validator_reject" for item in obligations)
    assert mint_proof_obligations(
        admit_hybrid_repair(
            PRIOR,
            CANDIDATE,
            gate=_accept_gate(),
            allowed_field_paths=(OBJECT_PATH,),
        )
    ) == ()


def test_packet_required_keys_for_supervisor_consumption() -> None:
    """Supervisor materializer depends on these sealed keys."""

    admission = admit_hybrid_repair(
        PRIOR,
        CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=(OBJECT_PATH,),
    )
    packet = build_packet_from_proposal_admission(
        packet_id="pkt-supervisor-keys",
        baseline_l1=PRIOR,
        residual_ref=_residual(),
        proposal=_proposal(),
        admission=admission,
    )
    payload = packet.to_dict()
    required = {
        "interface",
        "schema",
        "packet_id",
        "packet_digest",
        "baseline_l1",
        "baseline_l1_digest",
        "baseline_arm_id",
        "residual_refs",
        "proposals",
        "admission_receipts",
        "proof_obligation_ids",
        "proof_obligations",
        "predicted_files",
        "validation_commands",
        "implementable",
        "admitted_field_changes",
        "semantic_authority",
    }
    assert required.issubset(payload.keys())
    assert payload["baseline_arm_id"] == DEFAULT_BASELINE_ARM_ID
    # Non-implementable reject path also exposes obligation ids.
    rejected = build_packet_from_proposal_admission(
        packet_id="pkt-supervisor-reject",
        baseline_l1=PRIOR,
        residual_ref=_residual(),
        proposal=_proposal(),
        admission=admit_hybrid_repair(
            PRIOR,
            CANDIDATE,
            gate=_reject_gate(),
            allowed_field_paths=(OBJECT_PATH,),
        ),
    )
    reject_payload = rejected.to_dict()
    assert reject_payload["implementable"] is False
    assert reject_payload["proof_obligation_ids"]
    assert reject_payload["admission_receipts"][0]["semantic_authority"] is False


def test_local_constraint_reject_still_non_implementable() -> None:
    vacuous = CanonicalRuleIR(())
    gate = StructuralAdmissionGate(
        StructuralAdmissionPolicy(tools=(StructuralTool.HAMMER_CVC5,)),
        validators=(
            make_passing_binding(
                validator_id="hammer_cvc5",
                tool=StructuralTool.HAMMER_CVC5,
            ),
        ),
    )
    admission = gate.admit(PRIOR, vacuous, allowed_field_paths=(OBJECT_PATH,))
    assert admission.disposition is AdmissionDisposition.VALIDATOR_REJECT
    packet = build_packet_from_proposal_admission(
        packet_id="pkt-vacuous",
        baseline_l1=PRIOR,
        residual_ref=_residual(),
        proposal=_proposal(candidate=vacuous),
        admission=admission,
    )
    assert packet.implementable is False
    assert packet.proof_obligations


def test_proposal_unknown_residual_is_rejected() -> None:
    admission = admit_hybrid_repair(
        PRIOR,
        CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=(OBJECT_PATH,),
    )
    with pytest.raises(PlateauCodexPacketError, match="unknown residual"):
        build_plateau_codex_packet(
            packet_id="pkt-bad-residual",
            baseline_l1=PRIOR,
            residual_refs=(_residual(),),
            proposals=(
                TeacherProposal(
                    proposal_id="prop-x",
                    teacher="leanstral",
                    residual_ref_ids=("missing-resid",),
                    allowed_field_paths=(OBJECT_PATH,),
                    candidate_l1=CANDIDATE,
                ),
            ),
            admission_results=(admission,),
            proposal_ids_for_admissions=("prop-x",),
        )


# ---------------------------------------------------------------------------
# Holdout population (PLAT2-030)
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[4]
HOLDOUT_CATALOG_PATH = (
    ROOT
    / "workspace"
    / "benchmarks"
    / "semantic-roundtrip-compositions"
    / "holdout_residual_catalog.json"
)

# Selective-repair activation holdout cases use conditions / extra-rule facets.
HOLDOUT_CONDITIONS_PATH = "rules[0].conditions"
HOLDOUT_PRIOR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="records",
            conditions=("if_requested",),
        ),
    )
)
HOLDOUT_CANDIDATE = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="records",
            conditions=(),
        ),
    )
)


def _holdout_residual(
    residual_id: str = "resid-low-confidence-conditions",
    case_id: str = "low_confidence_object",
    field_path: str = HOLDOUT_CONDITIONS_PATH,
) -> ResidualRef:
    return ResidualRef(
        residual_id=residual_id,
        case_id=case_id,
        field_paths=(field_path,),
        facet="conditions",
        estimated_forward_contribution=0.1,
        catalog_digest="b" * 64,
        detail="holdout residual facet for low_confidence_object",
    )


def _holdout_proposal(
    proposal_id: str = "prop-holdout-1",
    residual_id: str = "resid-low-confidence-conditions",
    candidate: CanonicalRuleIR | None = HOLDOUT_CANDIDATE,
    field_path: str = HOLDOUT_CONDITIONS_PATH,
) -> TeacherProposal:
    return TeacherProposal(
        proposal_id=proposal_id,
        teacher="leanstral",
        residual_ref_ids=(residual_id,),
        allowed_field_paths=(field_path,),
        candidate_l1=candidate,
        detail="holdout selective conditions repair proposal",
        semantic_authority=False,
    )


def test_holdout_constants_and_validation_commands() -> None:
    assert HOLDOUT_BASELINE_E2E == pytest.approx(0.0)
    assert HOLDOUT_POPULATION_KIND == "holdout"
    assert DEFAULT_HOLDOUT_VALIDATION_COMMANDS
    assert any(
        "test_holdout_cases" in cmd for cmd in DEFAULT_HOLDOUT_VALIDATION_COMMANDS
    )
    assert any(
        "test_structural_admission" in cmd
        for cmd in DEFAULT_HOLDOUT_VALIDATION_COMMANDS
    )


def test_residual_refs_from_holdout_catalog() -> None:
    assert HOLDOUT_CATALOG_PATH.is_file(), (
        "holdout_residual_catalog.json must exist (PLAT2-010)"
    )
    catalog = json.loads(HOLDOUT_CATALOG_PATH.read_text(encoding="utf-8"))
    assert catalog.get("population_kind") == "holdout"

    refs = residual_refs_from_catalog(catalog, nonzero_only=True)
    assert refs, "holdout catalog should yield nonzero residual refs"
    case_ids = {ref.case_id for ref in refs}
    assert "low_confidence_object" in case_ids
    assert "contradictory_modality" in case_ids
    # Zero-loss missing_temporal has no residual facets in the flat list.
    assert "missing_temporal" not in case_ids

    for ref in refs:
        assert ref.catalog_digest == catalog["catalog_cid"]
        assert ref.field_paths
        assert ref.residual_id
        assert stable_residual_id(ref.case_id, ref.field_paths[0])

    # Facet projection helper round-trips a catalog row.
    facet = catalog["residuals"][0]
    single = residual_ref_from_catalog_facet(
        facet, catalog_digest=catalog["catalog_cid"]
    )
    assert single.case_id == facet["case_id"]
    assert single.field_paths == (facet["field_path"],)
    assert single.estimated_forward_contribution == pytest.approx(
        float(facet["loss_contribution"])
    )


def test_holdout_accepted_packet_is_implementable() -> None:
    residual = _holdout_residual()
    admission = admit_hybrid_repair(
        HOLDOUT_PRIOR,
        HOLDOUT_CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=(HOLDOUT_CONDITIONS_PATH,),
    )
    assert admission.disposition is AdmissionDisposition.ACCEPTED

    packet = build_holdout_packet_from_proposal_admission(
        packet_id="holdout-pkt-accept-1",
        baseline_l1=HOLDOUT_PRIOR,
        residual_ref=residual,
        proposal=_holdout_proposal(),
        admission=admission,
    )
    assert packet.implementable is True
    assert packet.baseline_e2e == pytest.approx(HOLDOUT_BASELINE_E2E)
    assert packet.case_id == "low_confidence_object"
    assert packet.predicted_files == DEFAULT_PREDICTED_FILES
    assert packet.validation_commands == DEFAULT_HOLDOUT_VALIDATION_COMMANDS
    assert packet.admitted_field_changes
    assert "holdout" in (packet.detail or "").lower()
    payload = packet.to_dict()
    assert payload["implementable"] is True
    assert payload["semantic_authority"] is False
    assert payload["baseline_e2e"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    "gate_factory,expected_disposition",
    [
        (_reject_gate, AdmissionDisposition.VALIDATOR_REJECT),
        (_timeout_gate, AdmissionDisposition.TIMEOUT),
        (_error_gate, AdmissionDisposition.ERROR),
    ],
)
def test_holdout_reject_timeout_error_not_implementable(
    gate_factory, expected_disposition: AdmissionDisposition
) -> None:
    residual = _holdout_residual()
    admission = admit_hybrid_repair(
        HOLDOUT_PRIOR,
        HOLDOUT_CANDIDATE,
        gate=gate_factory(),
        allowed_field_paths=(HOLDOUT_CONDITIONS_PATH,),
    )
    assert admission.disposition is expected_disposition

    packet = build_holdout_packet_from_proposal_admission(
        packet_id=f"holdout-pkt-{expected_disposition.value}",
        baseline_l1=HOLDOUT_PRIOR,
        residual_ref=residual,
        proposal=_holdout_proposal(),
        admission=admission,
    )
    assert packet.implementable is False
    assert packet.admitted_field_changes == ()
    assert packet.baseline_e2e == pytest.approx(HOLDOUT_BASELINE_E2E)
    # Reject/timeout/error mint obligations for supervisor notes.
    if expected_disposition is not AdmissionDisposition.ERROR:
        assert packet.proof_obligation_ids or packet.proof_obligations is not None


def test_holdout_cannot_force_implementable_on_reject() -> None:
    residual = _holdout_residual()
    admission = admit_hybrid_repair(
        HOLDOUT_PRIOR,
        HOLDOUT_CANDIDATE,
        gate=_reject_gate(),
        allowed_field_paths=(HOLDOUT_CONDITIONS_PATH,),
    )
    packet = build_holdout_codex_packet(
        packet_id="holdout-pkt-force-reject",
        baseline_l1=HOLDOUT_PRIOR,
        residual_refs=(residual,),
        proposals=(_holdout_proposal(),),
        admission_results=(admission,),
        proposal_ids_for_admissions=("prop-holdout-1",),
    )
    assert packet.implementable is False
    with pytest.raises(PlateauCodexPacketError, match="implementable"):
        PlateauCodexPacket(
            packet_id=packet.packet_id,
            baseline_l1=packet.baseline_l1,
            residual_refs=packet.residual_refs,
            proposals=packet.proposals,
            admission_receipts=packet.admission_receipts,
            proof_obligations=packet.proof_obligations,
            predicted_files=packet.predicted_files,
            validation_commands=packet.validation_commands,
            implementable=True,
            case_id=packet.case_id,
            admitted_field_changes=(),
            baseline_e2e=HOLDOUT_BASELINE_E2E,
        )


def test_build_holdout_packets_from_residual_catalog() -> None:
    catalog = json.loads(HOLDOUT_CATALOG_PATH.read_text(encoding="utf-8"))
    refs = residual_refs_from_catalog(
        catalog, case_ids=("low_confidence_object",), nonzero_only=True
    )
    assert refs
    residual = refs[0]
    admission = admit_hybrid_repair(
        HOLDOUT_PRIOR,
        HOLDOUT_CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=residual.field_paths,
    )
    proposal = TeacherProposal(
        proposal_id="prop-from-catalog",
        teacher="residual_catalog",
        residual_ref_ids=(),
        allowed_field_paths=residual.field_paths,
        candidate_l1=HOLDOUT_CANDIDATE,
        detail="catalog-driven holdout proposal",
    )
    packets = build_holdout_packets_from_residual_catalog(
        catalog,
        baseline_l1_by_case={"low_confidence_object": HOLDOUT_PRIOR},
        proposals_by_case={"low_confidence_object": proposal},
        admissions_by_case={"low_confidence_object": admission},
        case_ids=("low_confidence_object",),
    )
    assert len(packets) == 1
    packet = packets[0]
    assert packet.implementable is True
    assert packet.case_id == "low_confidence_object"
    assert packet.packet_id.startswith("holdout-pkt-")
    assert all(
        any(
            packet_path.startswith(prefix)
            for prefix in ALLOWED_PREDICTED_FILE_PREFIXES
        )
        for packet_path in packet.predicted_files
    )
    assert packet.validation_commands
    assert any("pytest" in cmd for cmd in packet.validation_commands)


# ---------------------------------------------------------------------------
# Repair-development population (PLAT2-030 normative path)
# ---------------------------------------------------------------------------

REPAIR_DEV_CATALOG_PATH = (
    ROOT
    / "workspace"
    / "benchmarks"
    / "semantic-roundtrip-compositions"
    / "repair_dev_residual_catalog.json"
)
REPAIR_DEV_CONDITIONS_PATH = "rules[0].conditions"
REPAIR_DEV_PRIOR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="records",
            conditions=("if_requested",),
        ),
    )
)
REPAIR_DEV_CANDIDATE = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="records",
            conditions=(),
        ),
    )
)


def _repair_dev_residual(
    residual_id: str = "resid-repair-dev-conditions",
    case_id: str = "low_confidence_object",
    field_path: str = REPAIR_DEV_CONDITIONS_PATH,
    catalog_digest: str | None = None,
) -> ResidualRef:
    return ResidualRef(
        residual_id=residual_id,
        case_id=case_id,
        field_paths=(field_path,),
        facet="conditions",
        estimated_forward_contribution=0.1,
        catalog_digest=catalog_digest or ("d" * 64),
        detail="repair_development residual facet",
    )


def _repair_dev_proposal(
    proposal_id: str = "prop-repair-dev-1",
    residual_id: str = "resid-repair-dev-conditions",
    field_path: str = REPAIR_DEV_CONDITIONS_PATH,
) -> TeacherProposal:
    return TeacherProposal(
        proposal_id=proposal_id,
        teacher="leanstral",
        residual_ref_ids=(residual_id,),
        allowed_field_paths=(field_path,),
        candidate_l1=REPAIR_DEV_CANDIDATE,
        detail="repair_development selective conditions repair proposal",
        semantic_authority=False,
    )


def test_repair_dev_constants_and_validation_commands() -> None:
    assert REPAIR_DEV_BASELINE_E2E == pytest.approx(0.0)
    assert REPAIR_DEV_POPULATION_KIND == "repair_development"
    assert DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS
    assert any(
        "test_structural_admission" in cmd
        for cmd in DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS
    )
    assert any(
        "test_plateau_codex_packet" in cmd
        for cmd in DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS
    )
    assert any(
        "test_holdout_baseline" in cmd
        for cmd in DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS
    )
    assert any(
        "test_residual_catalog" in cmd
        for cmd in DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS
    )
    assert any(
        "test_plateau_supervisor_materialize" in cmd
        for cmd in DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS
    )


def test_assert_catalog_allows_repair_dev_only() -> None:
    assert REPAIR_DEV_CATALOG_PATH.is_file()
    catalog = json.loads(REPAIR_DEV_CATALOG_PATH.read_text(encoding="utf-8"))
    kind = assert_catalog_allowed_for_packets(catalog)
    assert kind == REPAIR_DEV_POPULATION_KIND

    blind = dict(catalog)
    blind["population_kind"] = "authorized_blind_evaluation"
    with pytest.raises(PlateauCodexPacketError, match="blind"):
        assert_catalog_allowed_for_packets(blind)

    pilotish = dict(catalog)
    pilotish["population_kind"] = "pilot"
    with pytest.raises(PlateauCodexPacketError, match="population kinds"):
        assert_catalog_allowed_for_packets(pilotish)


def test_repair_dev_accepted_packet_binds_context_and_is_implementable() -> None:
    catalog = json.loads(REPAIR_DEV_CATALOG_PATH.read_text(encoding="utf-8"))
    residual = _repair_dev_residual(catalog_digest=catalog["catalog_cid"])
    admission = admit_hybrid_repair(
        REPAIR_DEV_PRIOR,
        REPAIR_DEV_CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=(REPAIR_DEV_CONDITIONS_PATH,),
    )
    assert admission.disposition is AdmissionDisposition.ACCEPTED

    packet = build_repair_dev_packet_from_proposal_admission(
        packet_id="repair-dev-pkt-accept-1",
        baseline_l1=REPAIR_DEV_PRIOR,
        residual_ref=residual,
        proposal=_repair_dev_proposal(),
        admission=admission,
        catalog=catalog,
        acceptance_ids=("ACC-repair-dev-conditions",),
    )
    assert packet.implementable is True
    assert packet.population_kind == REPAIR_DEV_POPULATION_KIND
    assert packet.baseline_e2e == pytest.approx(REPAIR_DEV_BASELINE_E2E)
    assert packet.bindings is not None
    assert packet.bindings.catalog_cid == catalog["catalog_cid"]
    assert packet.bindings.tree_cid == catalog["tree_cid"]
    assert packet.bindings.population_cid == catalog["population_cid"]
    assert packet.bindings.baseline_cid == catalog["baseline"]["report_cid"]
    assert packet.bindings.population_kind == REPAIR_DEV_POPULATION_KIND
    assert packet.bindings.assumptions
    assert packet.bindings.evidence_status
    assert packet.bindings.acceptance_ids == ("ACC-repair-dev-conditions",)
    assert packet.bindings.invalidators
    assert packet.bindings.provenance
    assert packet.bindings.structural_obligation_ids == packet.proof_obligation_ids
    assert packet.invariant_context is not None
    assert packet.invariant_context.failing_facet
    assert packet.invariant_context.counterexample_handle
    assert packet.invariant_context.canonical_spec_rule_handles
    assert packet.invariant_context.changed_ast_dependency_slice
    assert packet.invariant_context.pilot_regression_requirements
    assert packet.invariant_context.proof_receipt_digests
    assert packet.invariant_context.excludes_gold_target_bodies is True
    assert packet.invariant_context.excludes_blind_ids_sources_gold is True
    assert packet.token_count is not None
    assert packet.token_budget == PACKET_TOKEN_BUDGET
    assert packet.token_count <= PACKET_TOKEN_BUDGET
    assert packet.omitted_handle_coverage == pytest.approx(1.0)
    assert packet.validation_commands == DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS
    payload = packet.to_dict()
    assert "gold_value" not in json.dumps(payload)
    assert "source_text" not in json.dumps(payload)
    assert payload["bindings"]["catalog_cid"] == catalog["catalog_cid"]
    restored = PlateauCodexPacket.from_dict(payload)
    assert restored.packet_digest == packet.packet_digest
    assert restored.bindings is not None
    assert restored.invariant_context is not None


def test_repair_dev_reject_and_not_measured_not_implementable() -> None:
    catalog = json.loads(REPAIR_DEV_CATALOG_PATH.read_text(encoding="utf-8"))
    residual = _repair_dev_residual(catalog_digest=catalog["catalog_cid"])
    admission = admit_hybrid_repair(
        REPAIR_DEV_PRIOR,
        REPAIR_DEV_CANDIDATE,
        gate=_reject_gate(),
        allowed_field_paths=(REPAIR_DEV_CONDITIONS_PATH,),
    )
    packet = build_repair_dev_packet_from_proposal_admission(
        packet_id="repair-dev-pkt-reject",
        baseline_l1=REPAIR_DEV_PRIOR,
        residual_ref=residual,
        proposal=_repair_dev_proposal(),
        admission=admission,
        catalog=catalog,
    )
    assert packet.implementable is False
    assert packet.implementable_blockers
    assert any("admission" in b or "no_accepted" in b for b in packet.implementable_blockers)

    bindings = extract_catalog_bindings(
        catalog, case_id="low_confidence_object"
    )
    stale_bindings = PacketBindings(
        baseline_cid=bindings.baseline_cid,
        tree_cid=bindings.tree_cid,
        population_cid=bindings.population_cid,
        catalog_cid=bindings.catalog_cid,
        population_kind=bindings.population_kind,
        assumptions=bindings.assumptions,
        evidence_status=CATALOG_STATUS_NOT_MEASURED,
        structural_obligation_ids=(),
        invalidators=bindings.invalidators,
        acceptance_ids=(),
        provenance=dict(bindings.provenance),
    )
    accept = admit_hybrid_repair(
        REPAIR_DEV_PRIOR,
        REPAIR_DEV_CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=(REPAIR_DEV_CONDITIONS_PATH,),
    )
    blocked = build_repair_dev_codex_packet(
        packet_id="repair-dev-pkt-not-measured",
        baseline_l1=REPAIR_DEV_PRIOR,
        residual_refs=(residual,),
        proposals=(_repair_dev_proposal(),),
        admission_results=(accept,),
        proposal_ids_for_admissions=("prop-repair-dev-1",),
        bindings=stale_bindings,
        catalog=catalog,
    )
    assert blocked.implementable is False
    assert any(
        "evidence_status" in b for b in blocked.implementable_blockers
    )

    unsupported_bindings = PacketBindings(
        baseline_cid=bindings.baseline_cid,
        tree_cid=bindings.tree_cid,
        population_cid=bindings.population_cid,
        catalog_cid=bindings.catalog_cid,
        population_kind=bindings.population_kind,
        assumptions=bindings.assumptions,
        evidence_status=CATALOG_STATUS_UNSUPPORTED,
        structural_obligation_ids=(),
        invalidators=bindings.invalidators,
        acceptance_ids=(),
        provenance=dict(bindings.provenance),
    )
    blocked_u = build_repair_dev_codex_packet(
        packet_id="repair-dev-pkt-unsupported",
        baseline_l1=REPAIR_DEV_PRIOR,
        residual_refs=(residual,),
        proposals=(_repair_dev_proposal(),),
        admission_results=(accept,),
        proposal_ids_for_admissions=("prop-repair-dev-1",),
        bindings=unsupported_bindings,
        catalog=catalog,
    )
    assert blocked_u.implementable is False

    # Missing required evidence without catalog-derived bindings.
    missing = build_repair_dev_codex_packet(
        packet_id="repair-dev-pkt-missing-evidence",
        baseline_l1=REPAIR_DEV_PRIOR,
        residual_refs=(residual,),
        proposals=(_repair_dev_proposal(),),
        admission_results=(accept,),
        proposal_ids_for_admissions=("prop-repair-dev-1",),
        bindings=None,
        catalog=None,
        require_repair_dev_evidence=True,
    )
    assert missing.implementable is False
    assert any(
        "missing_required_evidence" in b for b in missing.implementable_blockers
    )


def test_repair_dev_stale_bindings_force_non_implementable() -> None:
    catalog = json.loads(REPAIR_DEV_CATALOG_PATH.read_text(encoding="utf-8"))
    residual = _repair_dev_residual(catalog_digest=catalog["catalog_cid"])
    accept = admit_hybrid_repair(
        REPAIR_DEV_PRIOR,
        REPAIR_DEV_CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=(REPAIR_DEV_CONDITIONS_PATH,),
    )
    stale = PacketBindings(
        baseline_cid=catalog["baseline"]["report_cid"],
        tree_cid="baguqeerstale0000000000000000000000000000000000000000000000000",
        population_cid=catalog["population_cid"],
        catalog_cid=catalog["catalog_cid"],
        population_kind=REPAIR_DEV_POPULATION_KIND,
        assumptions=tuple(catalog.get("assumptions") or ()),
        evidence_status="semantic_scored",
        provenance={},
    )
    packet = build_repair_dev_codex_packet(
        packet_id="repair-dev-pkt-stale",
        baseline_l1=REPAIR_DEV_PRIOR,
        residual_refs=(residual,),
        proposals=(_repair_dev_proposal(),),
        admission_results=(accept,),
        proposal_ids_for_admissions=("prop-repair-dev-1",),
        bindings=stale,
        catalog=catalog,
    )
    assert packet.implementable is False
    assert any("stale_binding" in b for b in packet.implementable_blockers)


def test_expansion_handles_and_token_budget_ledger() -> None:
    catalog = json.loads(REPAIR_DEV_CATALOG_PATH.read_text(encoding="utf-8"))
    residual = _repair_dev_residual(catalog_digest=catalog["catalog_cid"])
    accept = admit_hybrid_repair(
        REPAIR_DEV_PRIOR,
        REPAIR_DEV_CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=(REPAIR_DEV_CONDITIONS_PATH,),
    )
    big = ExpansionHandle(
        handle_id="exp-large-slice",
        content_digest="a" * 64,
        kind="ast_slice",
        token_estimate=PACKET_TOKEN_BUDGET,
        included=True,
        detail="optional large slice",
    )
    small = ExpansionHandle(
        handle_id="exp-small-cue",
        content_digest="b" * 64,
        kind="diagnostic_cue",
        token_estimate=8,
        included=True,
        detail="tiny cue",
    )
    planned, omitted, coverage, total = plan_expansion_handles(
        (small, big),
        base_token_count=100,
        token_budget=PACKET_TOKEN_BUDGET,
    )
    assert coverage == pytest.approx(1.0)
    assert "exp-large-slice" in omitted
    assert any(h.handle_id == "exp-small-cue" and h.included for h in planned)
    assert total <= PACKET_TOKEN_BUDGET

    packet = build_repair_dev_codex_packet(
        packet_id="repair-dev-pkt-expand",
        baseline_l1=REPAIR_DEV_PRIOR,
        residual_refs=(residual,),
        proposals=(_repair_dev_proposal(),),
        admission_results=(accept,),
        proposal_ids_for_admissions=("prop-repair-dev-1",),
        catalog=catalog,
        expansion_handles=planned,
    )
    assert packet.omitted_handle_ids
    assert packet.omitted_handle_coverage == pytest.approx(1.0)
    assert packet.token_count is not None
    assert packet.token_count <= PACKET_TOKEN_BUDGET


def test_forbidden_gold_body_in_bindings_rejected() -> None:
    with pytest.raises(PlateauCodexPacketError, match="forbidden"):
        PacketBindings(
            baseline_cid="baguqeerabase",
            tree_cid="baguqeeratree",
            population_cid="baguqeerapop",
            catalog_cid="baguqeeracat",
            population_kind=REPAIR_DEV_POPULATION_KIND,
            assumptions=(),
            evidence_status="semantic_scored",
            provenance={"gold_value": {"action": "delete"}},
        )


def test_build_repair_dev_packets_and_context_metrics(tmp_path: Path) -> None:
    sealed = json.loads(REPAIR_DEV_CATALOG_PATH.read_text(encoding="utf-8"))
    # Project sealed CID bindings onto a conditions-shaped residual so the
    # synthetic prior/candidate admission path can authorize implementable work.
    catalog = {
        "assumptions": sealed.get("assumptions") or (),
        "baseline": sealed["baseline"],
        "catalog_cid": sealed["catalog_cid"],
        "population_cid": sealed["population_cid"],
        "population_kind": sealed["population_kind"],
        "provenance": sealed.get("provenance") or {},
        "residuals": [
            {
                "canonical_field": "conditions",
                "case_id": "low_confidence_object",
                "field_path": REPAIR_DEV_CONDITIONS_PATH,
                "loss_contribution": 0.1,
                "residual_kind": "field_mismatch",
                "suggested_trigger_kind": "contradictory",
            }
        ],
        "status": {
            "by_case": {
                "low_confidence_object": {
                    "evaluation_status": "semantic_scored",
                    "reason": "success",
                    "semantic_score_eligible": True,
                }
            }
        },
        "tree_cid": sealed["tree_cid"],
    }
    refs = residual_refs_from_catalog(
        catalog, case_ids=("low_confidence_object",), nonzero_only=True
    )
    assert refs
    residual = refs[0]
    admission = admit_hybrid_repair(
        REPAIR_DEV_PRIOR,
        REPAIR_DEV_CANDIDATE,
        gate=_accept_gate(),
        allowed_field_paths=residual.field_paths,
    )
    proposal = TeacherProposal(
        proposal_id="prop-from-repair-catalog",
        teacher="residual_catalog",
        residual_ref_ids=(),
        allowed_field_paths=residual.field_paths,
        candidate_l1=REPAIR_DEV_CANDIDATE,
        detail="catalog-driven repair_development proposal",
    )
    packets = build_repair_dev_packets_from_residual_catalog(
        catalog,
        baseline_l1_by_case={"low_confidence_object": REPAIR_DEV_PRIOR},
        proposals_by_case={"low_confidence_object": proposal},
        admissions_by_case={"low_confidence_object": admission},
        case_ids=("low_confidence_object",),
        acceptance_ids_by_case={
            "low_confidence_object": ("ACC-low-confidence",)
        },
    )
    assert len(packets) == 1
    packet = packets[0]
    assert packet.implementable is True
    assert packet.population_kind == REPAIR_DEV_POPULATION_KIND
    assert packet.packet_id.startswith("repair-dev-pkt-")
    assert packet.bindings is not None
    assert packet.invariant_context is not None

    metrics = build_repair_dev_packet_context_metrics(
        packets, catalog=catalog
    )
    assert metrics["interface"] == REPAIR_DEV_PACKET_CONTEXT_METRICS_INTERFACE
    assert metrics["population_kind"] == REPAIR_DEV_POPULATION_KIND
    assert metrics["aggregate"]["packet_count"] == 1
    assert metrics["aggregate"]["implementable_count"] == 1
    assert metrics["packet_token_budget"]["max_tokens"] == PACKET_TOKEN_BUDGET
    assert metrics["metrics_cid"]
    assert metrics["packets"][0]["token_count"] >= 0

    out = tmp_path / "repair_dev_packet_context_metrics.json"
    written = write_repair_dev_packet_context_metrics(
        packets, path=out, catalog=catalog
    )
    assert out.is_file()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["metrics_cid"] == written["metrics_cid"]
    assert DEFAULT_REPAIR_DEV_PACKET_METRICS_RELATIVE_PATH.endswith(
        "repair_dev_packet_context_metrics.json"
    )
