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
    DEFAULT_VALIDATION_COMMANDS,
    HOLDOUT_BASELINE_E2E,
    HOLDOUT_POPULATION_KIND,
    NON_IMPLEMENTABLE_DISPOSITIONS,
    PLATEAU_CODEX_PACKET_EVIDENCE,
    PLATEAU_CODEX_PACKET_INTERFACE,
    PLATEAU_CODEX_PACKET_SCHEMA,
    PlateauAdmissionReceipt,
    PlateauCodexPacket,
    PlateauCodexPacketError,
    ProofObligation,
    ProverCheckReceipt,
    ResidualRef,
    TeacherProposal,
    baseline_l1_digest,
    build_holdout_codex_packet,
    build_holdout_packet_from_proposal_admission,
    build_holdout_packets_from_residual_catalog,
    build_packet_from_proposal_admission,
    build_plateau_codex_packet,
    disposition_is_implementable,
    mint_proof_obligations,
    residual_ref_from_catalog_facet,
    residual_refs_from_catalog,
    stable_residual_id,
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
