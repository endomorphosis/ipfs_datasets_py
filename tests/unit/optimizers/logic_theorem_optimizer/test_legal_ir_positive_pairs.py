"""Unit tests for typed proof-aware ``IRPositivePair@1`` mining."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.training_contracts import (
    EvidenceStatus,
    ExampleDisposition,
    IRCompilerTrace,
    IRDecompilerTrace,
    IRPositivePair,
    IRProofTrace,
    IRRoundTripTrace,
    IRTrainingExample,
    IRTranslationTrace,
    LabelAuthority,
    LabelEvidence,
    PreservationClass,
    ProducerKind,
    ProofOutcome,
    RepresentationKind,
    SemanticRelationship,
    StatementAuthority,
    ToolBinding,
    TraceStatus,
    TrainingContractValidationError,
)
from ipfs_datasets_py.logic.formalization.training_transforms import TraceReference
from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind
from ipfs_datasets_py.logic.ir_core.source_lineage import RightsDisposition
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_positive_pairs import (
    INDEPENDENT_VERIFICATION_CLASSES,
    IR_POSITIVE_PAIR_INTERFACE,
    IR_POSITIVE_PAIR_MINER_VERSION,
    POSITIVE_EQUIVALENCE_CLASSES,
    WEAKER_THAN_EXACT,
    PositivePairAdmissionError,
    PositivePairCandidate,
    PositivePairMinerError,
    PositivePairRejection,
    PositivePairShardConflictError,
    candidate_from_proof_identity,
    candidate_from_recipe_case,
    candidate_from_round_trip,
    candidate_from_transformation,
    canonical_positive_pair_recipe,
    cas_write_json,
    classify_positive_pair_candidate,
    equivalence_class_catalog,
    load_positive_pair_shards,
    loss_pair_admissions,
    make_relationship_evidence,
    make_statement,
    mine_canonical_positive_pairs,
    mine_from_records,
    mine_positive_pairs,
    positive_pair_authorities,
    resolve_positive_pair_data_dir,
    sealed_campaign_lineage,
    write_positive_pair_shards,
)


DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"
DIGEST_C = f"sha256:{'c' * 64}"
DIGEST_D = f"sha256:{'d' * 64}"
DIGEST_E = f"sha256:{'e' * 64}"
DIGEST_F = f"sha256:{'f' * 64}"


def _tool(kind: ProducerKind, name: str) -> ToolBinding:
    return ToolBinding(
        tool_id=f"tool:{name}",
        tool_version="1.0",
        producer_kind=kind,
        config_digest=DIGEST_D,
        implementation_digest=DIGEST_E,
    )


def _lineage(**changes: object):
    values = {
        "lineage_group_ids": ("lineage:pgir-040-trace",),
        "source_record_ids": ("source:pgir-040-trace",),
        "split_name": "train",
        "rights_disposition": RightsDisposition.ADMITTED,
    }
    values.update(changes)
    return sealed_campaign_lineage(**values)  # type: ignore[arg-type]


def _statement(name: str, digest: str, **kwargs):
    return make_statement(
        name,
        digest=digest,
        lineage_group_ids=("lineage:pgir-040-trace",),
        source_record_ids=("source:pgir-040-trace",),
        **kwargs,
    )


def _proof_trace(name: str, digest: str, *, claim_digest: str = DIGEST_A) -> IRProofTrace:
    statement = _statement(name, digest, representation=RepresentationKind.PROVER_SYNTAX)
    receipt = DIGEST_B
    evidence = LabelEvidence(
        evidence_id=f"evidence:proof:{name}",
        evidence_digest=receipt,
        authority=LabelAuthority.INDEPENDENT_PROOF_CHECKER,
        status=EvidenceStatus.VERIFIED,
        subject_statement_ids=(statement.statement_id,),
        subject_statement_digests=(statement.statement_digest,),
        producer_id="tool:kernel",
        producer_version="1.0",
        independent=True,
        result_authority=AuthorityKind.THEOREM_PROOF,
    )
    return IRProofTrace(
        trace_id=f"trace:proof:{name}",
        lineage=_lineage(),
        statement=statement,
        claim_id="claim:shared",
        claim_digest=claim_digest,
        obligation_id="obligation:1",
        obligation_digest=DIGEST_C,
        assumption_ids=("assumption:1",),
        assumption_digests=(DIGEST_D,),
        request_digest=DIGEST_E,
        attempt_digest=DIGEST_F,
        result_digest=DIGEST_A,
        output_digest=DIGEST_C,
        producer=_tool(ProducerKind.PROVER, "prover"),
        outcome=ProofOutcome.PROVED,
        evidence=(evidence,),
        checker=_tool(ProducerKind.CHECKER, "kernel"),
        proof_receipt_digest=receipt,
    )



def _fictional_explicit_recipe_candidate(case):
    """Explicit trusted-caller test metadata; no real checker or review ran."""
    seed = candidate_from_recipe_case(case)
    authority = LabelAuthority(case.get("authority") or case.get("required_authority")
                               or LabelAuthority.CANONICAL_VALIDATOR.value)
    status = EvidenceStatus(case.get("evidence_status") or EvidenceStatus.VERIFIED.value)
    independent = case.get("independent", case.get("required_independent"))
    result = case.get("result_authority") or case.get("required_result_authority")
    label = make_relationship_evidence(
        seed.left, seed.right, seed.relationship,
        evidence_id="fixture:explicit-positive:" + case["case_id"],
        authority=authority, status=status, independent=independent,
        result_authority=AuthorityKind(result) if result else None,
        producer_id="fixture:declared-caller-label-not-a-real-checker", producer_version="1",
    )
    return candidate_from_recipe_case(case, evidence=(label,))


def _fictional_explicit_positive_population():
    return mine_positive_pairs(tuple(_fictional_explicit_recipe_candidate(case)
        for case in canonical_positive_pair_recipe()["cases"]))


def test_canonical_recipe_covers_every_typed_equivalence_class() -> None:
    result = _fictional_explicit_positive_population()

    assert result.interface == IR_POSITIVE_PAIR_INTERFACE
    assert result.miner_version == IR_POSITIVE_PAIR_MINER_VERSION
    assert set(result.covered_classes) == {item.value for item in POSITIVE_EQUIVALENCE_CLASSES}
    assert len(result.admitted) == 8
    assert result.rejected == ()
    assert result.identity() == _fictional_explicit_positive_population().identity()


def test_every_admitted_pair_has_complete_lineage_and_authority() -> None:
    result = _fictional_explicit_positive_population()

    for item in result.admitted:
        pair = item.pair
        assert pair.schema_version == "ir-positive-pair/v1"
        assert pair.lineage.split_name == "train"
        assert pair.lineage.rights_disposition is RightsDisposition.ADMITTED
        assert pair.lineage.corpus_manifest_id == "corp:jdao-pinset-1"
        assert pair.lineage.split_manifest_digest.startswith("sha256:")
        assert pair.lineage.lineage_group_ids
        assert pair.lineage.source_record_ids
        assert pair.left_authority not in {
            StatementAuthority.UNKNOWN,
            StatementAuthority.MODEL_CANDIDATE,
        }
        assert pair.right_authority not in {
            StatementAuthority.UNKNOWN,
            StatementAuthority.MODEL_CANDIDATE,
        }
        assert pair.evidence
        assert all(evidence.status is EvidenceStatus.VERIFIED for evidence in pair.evidence)
        assert item.example.disposition is ExampleDisposition.ADMITTED
        assert item.example.training_eligible is True
        restored = IRPositivePair.from_json(pair.to_json())
        assert restored.cid == pair.cid


def test_logical_and_proof_classes_require_independent_verification() -> None:
    result = _fictional_explicit_positive_population()
    required = {item.value for item in INDEPENDENT_VERIFICATION_CLASSES}
    seen = {
        item.pair.relationship.value
        for item in result.admitted
        if item.pair.relationship in INDEPENDENT_VERIFICATION_CLASSES
    }
    assert seen == required
    for item in result.admitted:
        if item.pair.relationship not in INDEPENDENT_VERIFICATION_CLASSES:
            continue
        evidence = item.pair.evidence[0]
        assert evidence.independent is True
        assert evidence.authority in {
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
            LabelAuthority.INDEPENDENT_PROOF_CHECKER,
        }

    logical = _fictional_explicit_recipe_candidate(
        {
            "authority": LabelAuthority.CANONICAL_VALIDATOR.value,
            "case_id": "logical-not-independent",
            "independent": False,
            "relationship": SemanticRelationship.LOGICALLY_EQUIVALENT.value,
        }
    )
    assert classify_positive_pair_candidate(logical) is PositivePairRejection.UNVERIFIED_EVIDENCE
    mined = mine_positive_pairs((logical,))
    assert mined.admitted == ()
    assert mined.rejected[0].reason is PositivePairRejection.UNVERIFIED_EVIDENCE


def test_equisatisfiable_and_paraphrase_cannot_be_emitted_as_exact() -> None:
    for relationship in (
        SemanticRelationship.EQUISATISFIABLE,
        SemanticRelationship.PARAPHRASE,
    ):
        assert relationship in WEAKER_THAN_EXACT
        authority = (
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER
            if relationship is SemanticRelationship.EQUISATISFIABLE
            else LabelAuthority.HUMAN_REVIEW
        )
        candidate = _fictional_explicit_recipe_candidate(
            {
                "authority": authority.value,
                "case_id": f"{relationship.value}-claimed-exact",
                "claimed_exact": True,
                "independent": relationship is SemanticRelationship.EQUISATISFIABLE,
                "relationship": relationship.value,
                "result_authority": (
                    AuthorityKind.SATISFIABILITY.value
                    if relationship is SemanticRelationship.EQUISATISFIABLE
                    else ""
                ),
            }
        )
        assert (
            classify_positive_pair_candidate(candidate)
            is PositivePairRejection.WEAKER_CLASS_AS_EXACT
        )


def test_cross_split_siblings_and_indivisible_lineage_groups_are_rejected() -> None:
    cross = _fictional_explicit_recipe_candidate(
        {
            "case_id": "cross-split",
            "relationship": SemanticRelationship.EXACT.value,
            "sibling_split": "holdout",
        }
    )
    assert classify_positive_pair_candidate(cross) is PositivePairRejection.CROSS_SPLIT_SIBLING

    holdout = _fictional_explicit_recipe_candidate(
        {
            "case_id": "holdout-pair",
            "relationship": SemanticRelationship.EXACT.value,
            "split": "holdout",
        }
    )
    assert classify_positive_pair_candidate(holdout) is PositivePairRejection.NON_TRAINING_SPLIT

    grouped = _fictional_explicit_recipe_candidate(
        {
            "case_id": "lineage-split",
            "lineage_group": "lineage:shared",
            "relationship": SemanticRelationship.EXACT.value,
        }
    )
    assert (
        classify_positive_pair_candidate(
            grouped, split_assignments={"lineage:shared": "holdout"}
        )
        is PositivePairRejection.LINEAGE_GROUP_SPLIT
    )


def test_model_only_proof_labels_are_rejected() -> None:
    left = make_statement(
        "model-left",
        representation=RepresentationKind.PROVER_SYNTAX,
        lineage_group_ids=("lineage:model",),
        source_record_ids=("source:model",),
    )
    right = make_statement(
        "model-right",
        representation=RepresentationKind.PROOF_STATE,
        lineage_group_ids=("lineage:model",),
        source_record_ids=("source:model",),
    )
    evidence = make_relationship_evidence(
        left,
        right,
        SemanticRelationship.PROOF_EQUIVALENT,
        evidence_id="evidence:model-proof",
        authority=LabelAuthority.MODEL_OUTPUT,
        status=EvidenceStatus.CANDIDATE,
        independent=False,
        result_authority=None,
    )
    candidate = PositivePairCandidate(
        candidate_id="candidate:model-proof",
        left=left,
        right=right,
        left_authority=StatementAuthority.INDEPENDENTLY_VERIFIED,
        right_authority=StatementAuthority.INDEPENDENTLY_VERIFIED,
        relationship=SemanticRelationship.PROOF_EQUIVALENT,
        lineage=sealed_campaign_lineage(
            lineage_group_ids=("lineage:model",),
            source_record_ids=("source:model",),
        ),
        evidence=(evidence,),
        source_kind="proof",
        receipt_kind="kernel",
        preservation=PreservationClass.PROOF,
    )
    assert (
        classify_positive_pair_candidate(candidate)
        is PositivePairRejection.MODEL_ONLY_PROOF_LABEL
    )


def test_duplicates_are_filtered_and_weaker_labels_do_not_replace_exact() -> None:
    exact = _fictional_explicit_recipe_candidate(
        {
            "case_id": "dup-exact",
            "left_name": "shared-left",
            "relationship": SemanticRelationship.EXACT.value,
            "right_name": "shared-right",
        }
    )
    paraphrase = _fictional_explicit_recipe_candidate(
        {
            "authority": LabelAuthority.HUMAN_REVIEW.value,
            "case_id": "dup-paraphrase",
            "claimed_exact": False,
            "left_name": "shared-left",
            "relationship": SemanticRelationship.PARAPHRASE.value,
            "right_name": "shared-right",
        }
    )
    swapped = replace(
        exact,
        candidate_id="candidate:dup-exact-swapped",
        left=exact.right,
        right=exact.left,
        left_authority=exact.right_authority,
        right_authority=exact.left_authority,
    )
    result = mine_positive_pairs((exact, paraphrase, swapped, exact))

    assert len(result.admitted) == 1
    assert result.admitted[0].pair.relationship is SemanticRelationship.EXACT
    reasons = {item.reason for item in result.rejected}
    assert PositivePairRejection.DUPLICATE_PAIR in reasons
    assert PositivePairRejection.SUPERSEDED_WEAKER_CLASS in reasons


def test_reconstruction_kernel_and_translation_receipts_are_emitted() -> None:
    result = _fictional_explicit_positive_population()
    kinds = {item.kind for item in result.receipts}
    assert {"reconstruction", "kernel", "translation"} <= kinds
    kernel = next(item for item in result.receipts if item.kind == "kernel")
    assert kernel.independent is True
    assert kernel.authority == LabelAuthority.INDEPENDENT_PROOF_CHECKER.value
    reconstruction = [item for item in result.receipts if item.kind == "reconstruction"]
    assert reconstruction
    assert any(item.relationship == SemanticRelationship.EXACT.value for item in reconstruction)


def test_round_trip_and_translation_traces_mine_into_typed_pairs() -> None:
    source = _statement("src", DIGEST_A)
    ir = _statement("ir", DIGEST_B, representation=RepresentationKind.CANONICAL_IR)
    reconstructed = _statement("nl", DIGEST_C)
    compiler = IRCompilerTrace(
        trace_id="trace:compiler-exact",
        lineage=_lineage(),
        source=source,
        target=ir,
        producer=_tool(ProducerKind.DETERMINISTIC_COMPILER, "compiler"),
        source_authority=StatementAuthority.SOURCE_ASSERTED,
        target_authority=StatementAuthority.DETERMINISTICALLY_DERIVED,
        relationship=SemanticRelationship.EXACT,
        preservation=PreservationClass.LOSSLESS,
        status=TraceStatus.SUCCEEDED,
        evidence=(
            make_relationship_evidence(
                source,
                ir,
                SemanticRelationship.EXACT,
                evidence_id="evidence:compile",
                authority=LabelAuthority.CANONICAL_VALIDATOR,
            ),
        ),
    )
    reverse = IRDecompilerTrace(
        trace_id="trace:decompiler-exact",
        lineage=_lineage(),
        source=ir,
        target=reconstructed,
        producer=_tool(ProducerKind.DETERMINISTIC_DECOMPILER, "decompiler"),
        source_authority=StatementAuthority.DETERMINISTICALLY_DERIVED,
        target_authority=StatementAuthority.DETERMINISTICALLY_DERIVED,
        relationship=SemanticRelationship.EXACT,
        preservation=PreservationClass.LOSSLESS,
        status=TraceStatus.SUCCEEDED,
        evidence=(
            make_relationship_evidence(
                ir,
                reconstructed,
                SemanticRelationship.EXACT,
                evidence_id="evidence:decompile",
                authority=LabelAuthority.CANONICAL_VALIDATOR,
            ),
        ),
    )
    round_trip = IRRoundTripTrace(
        trace_id="trace:round-trip-exact",
        lineage=_lineage(),
        original=source,
        reconstructed=reconstructed,
        forward=TraceReference.from_trace(compiler),
        reverse=TraceReference.from_trace(reverse),
        relationship=SemanticRelationship.EXACT,
        preservation=PreservationClass.LOSSLESS,
        evidence=(
            make_relationship_evidence(
                source,
                reconstructed,
                SemanticRelationship.EXACT,
                evidence_id="evidence:round-trip",
                authority=LabelAuthority.CANONICAL_VALIDATOR,
            ),
        ),
    )
    prover = _statement("prover", DIGEST_F, representation=RepresentationKind.PROVER_SYNTAX)
    translation = IRTranslationTrace(
        trace_id="trace:translation-smt",
        lineage=_lineage(),
        source=ir,
        target=prover,
        producer=_tool(ProducerKind.DETERMINISTIC_TRANSLATOR, "translator"),
        source_authority=StatementAuthority.CANONICALLY_VALIDATED,
        target_authority=StatementAuthority.DETERMINISTICALLY_DERIVED,
        relationship=SemanticRelationship.TRANSLATION_EQUIVALENT,
        preservation=PreservationClass.SEMANTIC,
        status=TraceStatus.SUCCEEDED,
        evidence=(
            make_relationship_evidence(
                ir,
                prover,
                SemanticRelationship.TRANSLATION_EQUIVALENT,
                evidence_id="evidence:translate",
                authority=LabelAuthority.INDEPENDENT_TRANSLATION_CHECKER,
                independent=True,
            ),
        ),
    )
    result = mine_from_records(traces=(round_trip, translation, compiler))

    classes = {item.pair.relationship for item in result.admitted}
    assert SemanticRelationship.EXACT in classes
    assert SemanticRelationship.TRANSLATION_EQUIVALENT in classes
    assert candidate_from_round_trip(round_trip).receipt_kind == "reconstruction"
    assert candidate_from_transformation(translation).receipt_kind == "translation"


def test_same_claim_proofs_mine_a_kernel_backed_proof_pair() -> None:
    left = _proof_trace("theorem-a", DIGEST_A)
    right = _proof_trace("theorem-b", DIGEST_C)
    result = mine_from_records(proof_pairs=((left, right),))

    assert len(result.admitted) == 1
    pair = result.admitted[0].pair
    assert pair.relationship is SemanticRelationship.PROOF_EQUIVALENT
    assert result.admitted[0].receipt.kind == "kernel"
    assert pair.evidence[0].authority is LabelAuthority.INDEPENDENT_PROOF_CHECKER
    assert pair.evidence[0].independent is True
    candidate = candidate_from_proof_identity(left, right)
    assert candidate.split_name == "train"


def test_candidate_statement_authority_and_missing_lineage_fail_closed() -> None:
    candidate = _fictional_explicit_recipe_candidate(
        {
            "case_id": "model-candidate",
            "left_authority": StatementAuthority.MODEL_CANDIDATE.value,
            "relationship": SemanticRelationship.EXACT.value,
        }
    )
    assert (
        classify_positive_pair_candidate(candidate)
        is PositivePairRejection.CANDIDATE_STATEMENT_AUTHORITY
    )

    denied = _fictional_explicit_recipe_candidate(
        {
            "case_id": "denied-rights",
            "relationship": SemanticRelationship.EXACT.value,
            "rights": RightsDisposition.DENIED.value,
        }
    )
    assert classify_positive_pair_candidate(denied) is PositivePairRejection.RIGHTS_NOT_ADMITTED


def test_unverified_evidence_cannot_admit_a_positive_pair() -> None:
    candidate = _fictional_explicit_recipe_candidate(
        {
            "case_id": "unverified",
            "evidence_status": EvidenceStatus.CANDIDATE.value,
            "relationship": SemanticRelationship.EXACT.value,
        }
    )
    assert classify_positive_pair_candidate(candidate) is PositivePairRejection.UNVERIFIED_EVIDENCE


def test_sealed_shards_regenerate_and_stay_content_addressed(tmp_path: Path) -> None:
    # Historical recipe-generated records remain byte-identical archive data.
    # Decoding their old claimed labels grants no fresh source/proof/review gate.
    data_dir = resolve_positive_pair_data_dir()
    tracked = [data_dir / name for name in ("manifest.json", "recipe.json", "receipts.json", "classes.json")]
    original = {str(path): path.read_bytes() for path in tracked}
    manifest = json.loads(original[str(data_dir / "manifest.json")])
    assert manifest["pair_count"] == 8
    assert len(load_positive_pair_shards(data_dir)) == 8
    pending = write_positive_pair_shards(tmp_path / "unattested")
    assert pending["manifest"]["pair_count"] == 0
    assert pending["manifest"]["manifest_cid"] != manifest["manifest_cid"]
    explicit = _fictional_explicit_positive_population()
    generated = write_positive_pair_shards(tmp_path / "explicit", result=explicit)
    repeated = write_positive_pair_shards(tmp_path / "explicit", result=explicit)
    assert generated == repeated
    assert generated["manifest"]["pair_count"] == 8
    pairs = load_positive_pair_shards(tmp_path / "explicit")
    assert len(pairs) == 8
    for pair in pairs:
        example = IRTrainingExample.classify(
            example_id=f"example:{pair.pair_id}", record=pair,
            selected_evidence_id=pair.evidence[0].evidence_id,
        )
        assert example.training_eligible
    assert all(row["admitted"] for row in loss_pair_admissions(pairs))
    assert all(Path(path).read_bytes() == raw for path, raw in original.items())


def test_shard_compare_and_swap_refuses_divergent_payloads(tmp_path: Path) -> None:
    path = tmp_path / "shard.json"
    cas_write_json(path, {"ok": True})
    cas_write_json(path, {"ok": True})
    with pytest.raises(PositivePairShardConflictError):
        cas_write_json(path, {"ok": False})


def test_raise_on_reject_surfaces_negative_authority() -> None:
    candidate = _fictional_explicit_recipe_candidate(
        {
            "authority": LabelAuthority.MODEL_OUTPUT.value,
            "case_id": "model-exact",
            "evidence_status": EvidenceStatus.CANDIDATE.value,
            "relationship": SemanticRelationship.EXACT.value,
        }
    )
    with pytest.raises(PositivePairAdmissionError, match="model_only_evidence"):
        mine_positive_pairs((candidate,), raise_on_reject=True)


def test_class_catalog_authorities_match_training_contract() -> None:
    catalog = equivalence_class_catalog()
    by_name = {item["relationship"]: item for item in catalog["classes"]}
    for relationship in POSITIVE_EQUIVALENCE_CLASSES:
        expected = {item.value for item in positive_pair_authorities(relationship)}
        assert set(by_name[relationship.value]["authorities"]) == expected
        assert by_name[relationship.value]["independent_verification_required"] is (
            relationship in INDEPENDENT_VERIFICATION_CLASSES
        )


def test_canonical_recipe_is_stable_and_compact() -> None:
    first = canonical_positive_pair_recipe()
    second = canonical_positive_pair_recipe()
    assert first == second
    assert first["recipe_cid"].startswith("b")
    encoded = json.dumps(first)
    assert "IRPositivePair@" not in encoded
    assert len(first["cases"]) == 8


def test_unknown_relationship_is_rejected_by_the_pair_contract() -> None:
    with pytest.raises(PositivePairMinerError, match="unknown positive-pair relationship"):
        _fictional_explicit_recipe_candidate(
            {
                "case_id": "unknown-rel",
                "relationship": "close_enough",
            }
        )


# PGIR-040: recipe declarations are proposals, not checker/review executions.
# No payload, compiler trace, kernel receipt, human review, or licensed source
# is supplied by these fictional attack inputs.
@pytest.mark.parametrize("relationship", [
    SemanticRelationship.LOGICALLY_EQUIVALENT,
    SemanticRelationship.PROOF_EQUIVALENT,
    SemanticRelationship.PARAPHRASE,
])
def test_pgir040_recipe_enums_alone_cannot_mint_semantic_review_authority(relationship):
    recipe = canonical_positive_pair_recipe()
    case = next(dict(item) for item in recipe["cases"]
                if item["relationship"] == relationship.value)
    # Changing the fixture identifier supplies no independent evidence.
    case["case_id"] = "fictional-unattested-" + relationship.value
    candidate = candidate_from_recipe_case(case)
    mined = mine_positive_pairs((candidate,))
    assert mined.admitted == ()
    assert mined.receipts == ()


def test_pgir040_default_recipe_without_trace_inputs_cannot_admit_training_pairs():
    # Deterministic equality needs actual bound values or verified traces too;
    # arbitrary endpoint names and fixed campaign metadata are insufficient.
    mined = mine_canonical_positive_pairs()
    assert mined.admitted == ()
    assert mined.receipts == ()


@pytest.mark.parametrize("case", canonical_positive_pair_recipe()["cases"], ids=lambda case: case["case_id"])
def test_pgir040_explicit_fictional_labels_preserve_class_coverage(case):
    candidate = _fictional_explicit_recipe_candidate(case)
    result = mine_positive_pairs((candidate,))
    assert len(result.admitted) == 1
    assert result.admitted[0].example.training_eligible
    assert result.admitted[0].receipt.evidence_id.startswith("fixture:explicit-positive:")


def test_pgir040_recipe_metadata_without_evidence_cannot_admit_any_class():
    for case in canonical_positive_pair_recipe()["cases"]:
        claimed = dict(case, authority=case["required_authority"],
                       evidence_status=EvidenceStatus.VERIFIED.value)
        candidate = candidate_from_recipe_case(claimed)
        assert candidate.evidence == ()
        assert mine_positive_pairs((candidate,)).admitted == ()


@pytest.mark.parametrize("field,value", [
    ("authority", LabelAuthority.MODEL_OUTPUT.value),
    ("evidence_status", EvidenceStatus.UNKNOWN.value),
    ("independent", False),
    ("result_authority", AuthorityKind.SATISFIABILITY.value),
])
def test_pgir040_recipe_cannot_override_explicit_checked_label(field, value):
    case = next(c for c in canonical_positive_pair_recipe()["cases"]
                if c["relationship"] == SemanticRelationship.PROOF_EQUIVALENT.value)
    candidate = _fictional_explicit_recipe_candidate(case)
    with pytest.raises(PositivePairAdmissionError, match="metadata cannot override"):
        candidate_from_recipe_case(dict(case, **{field: value}), evidence=candidate.evidence)


@pytest.mark.parametrize("field", ["left_name", "right_name"])
def test_pgir040_explicit_label_must_bind_the_current_endpoint(field):
    case = canonical_positive_pair_recipe()["cases"][0]
    candidate = _fictional_explicit_recipe_candidate(case)
    with pytest.raises(TrainingContractValidationError, match="another statement"):
        candidate_from_recipe_case(dict(case, **{field: "fictional-other-endpoint"}),
                                   evidence=candidate.evidence)


def test_pgir040_explicit_label_must_bind_the_current_relationship():
    case = canonical_positive_pair_recipe()["cases"][0]
    candidate = _fictional_explicit_recipe_candidate(case)
    label = replace(candidate.evidence[0], relationship=SemanticRelationship.PARAPHRASE)
    with pytest.raises(TrainingContractValidationError, match="relationship does not match"):
        candidate_from_recipe_case(case, evidence=(label,))


def test_pgir040_mapping_cannot_impersonate_explicit_typed_evidence():
    case = canonical_positive_pair_recipe()["cases"][0]
    candidate = _fictional_explicit_recipe_candidate(case)
    with pytest.raises(PositivePairAdmissionError, match="LabelEvidence"):
        candidate_from_recipe_case(case, evidence=(candidate.evidence[0].to_dict(),))


def test_pgir040_pending_first_label_cannot_steal_training_or_receipt_selection():
    case = canonical_positive_pair_recipe()["cases"][0]
    candidate = _fictional_explicit_recipe_candidate(case)
    pending = replace(candidate.evidence[0], evidence_id="fixture:a-pending", status=EvidenceStatus.CANDIDATE)
    checked = replace(candidate.evidence[0], evidence_id="fixture:z-checked")
    for labels in ((pending, checked), (checked, pending)):
        result = mine_positive_pairs((candidate_from_recipe_case(case, evidence=labels),))
        assert len(result.admitted) == 1
        assert result.admitted[0].receipt.evidence_id == checked.evidence_id
        assert result.admitted[0].example.selected_evidence_id == checked.evidence_id


def test_pgir040_pending_label_alone_remains_nontraining():
    case = canonical_positive_pair_recipe()["cases"][0]
    candidate = _fictional_explicit_recipe_candidate(case)
    pending = replace(candidate.evidence[0], status=EvidenceStatus.CANDIDATE)
    result = mine_positive_pairs((candidate_from_recipe_case(case, evidence=(pending,)),))
    assert result.admitted == ()
    assert result.receipts == ()


def test_pgir040_recipe_cannot_relabel_a_receipt_as_kernel_evidence():
    case = canonical_positive_pair_recipe()["cases"][0]
    candidate = _fictional_explicit_recipe_candidate(case)
    proof = next(c for c in canonical_positive_pair_recipe()["cases"]
                 if c["relationship"] == SemanticRelationship.PROOF_EQUIVALENT.value)
    with pytest.raises(PositivePairAdmissionError, match="receipt kind"):
        candidate_from_recipe_case(dict(case, receipt_kind=proof["receipt_kind"]),
                                   evidence=candidate.evidence)



def test_pgir040_explicit_labels_are_detached_from_caller_records():
    case = canonical_positive_pair_recipe()["cases"][0]
    supplied = _fictional_explicit_recipe_candidate(case).evidence[0]
    candidate = candidate_from_recipe_case(case, evidence=(supplied,))
    assert candidate.evidence[0] is not supplied
    assert candidate.evidence[0].to_dict() == supplied.to_dict()


def test_pgir040_label_iterable_is_consumed_exactly_once():
    case = canonical_positive_pair_recipe()["cases"][0]
    supplied = _fictional_explicit_recipe_candidate(case).evidence[0]
    class Once:
        calls = 0
        def __iter__(self):
            self.calls += 1
            assert self.calls == 1
            yield supplied
    labels = Once()
    candidate = candidate_from_recipe_case(case, evidence=labels)
    assert labels.calls == 1
    assert len(mine_positive_pairs((candidate,)).admitted) == 1


def test_pgir040_explicit_label_cannot_reuse_stale_endpoint_digests():
    case = canonical_positive_pair_recipe()["cases"][0]
    supplied = _fictional_explicit_recipe_candidate(case).evidence[0]
    stale = replace(supplied, subject_statement_digests=(DIGEST_A, DIGEST_B))
    with pytest.raises(TrainingContractValidationError, match="another statement"):
        candidate_from_recipe_case(case, evidence=(stale,))


# PGIR-040 follow-up: decoding a pair does not select a training admission.
@pytest.mark.parametrize("population", [
    "historical_recipe_archive",
    "pair_without_evidence",
    "explicit_fixture_without_selected_training_example",
])
def test_pgir040_loss_projection_requires_selected_training_admission(population):
    if population == "historical_recipe_archive":
        pairs = load_positive_pair_shards(resolve_positive_pair_data_dir())
        assert len(pairs) == 8
    elif population == "pair_without_evidence":
        archived = load_positive_pair_shards(resolve_positive_pair_data_dir())
        pairs = (replace(archived[0], evidence=()),)
        assert pairs[0].evidence == ()
    else:
        pairs = _fictional_explicit_positive_population().pairs
        assert len(pairs) == 8
    rows = loss_pair_admissions(pairs)
    assert len(rows) == len(pairs)
    assert all(row["admitted"] is False for row in rows)
    assert all(row["pair_class"] == "positive" for row in rows)
    assert {(row["left_id"], row["right_id"]) for row in rows} == {
        (pair.left.statement_id, pair.right.statement_id) for pair in pairs
    }


def test_pgir040_empty_loss_projection_preserves_empty_population():
    assert loss_pair_admissions(()) == ()



def test_pgir040_raw_pair_cannot_enable_cosine_loss():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_loss_configuration import (
        AllRecordCosineMaximizationError, IRLossBatch, IRLossPairAdmission,
        IRLossRecord, evaluate_ir_composite_loss,
    )
    archived = load_positive_pair_shards(resolve_positive_pair_data_dir())[0]
    pair = replace(archived, evidence=())
    row = loss_pair_admissions((pair,))[0]
    records = (
        IRLossRecord(record_id=pair.left.statement_id, lineage_id="fixture:projection-left", latent=(1.0, 0.0)),
        IRLossRecord(record_id=pair.right.statement_id, lineage_id="fixture:projection-right", latent=(0.0, 1.0)),
    )
    admission = IRLossPairAdmission(
        left_id=row["left_id"], right_id=row["right_id"],
        pair_class=row["pair_class"], admitted=row["admitted"],
    )
    with pytest.raises(AllRecordCosineMaximizationError, match="explicit pair admissions"):
        evaluate_ir_composite_loss(IRLossBatch(records=records, pair_admissions=(admission,)))
