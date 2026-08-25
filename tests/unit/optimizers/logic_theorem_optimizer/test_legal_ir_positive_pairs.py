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


def test_canonical_recipe_covers_every_typed_equivalence_class() -> None:
    result = mine_canonical_positive_pairs()

    assert result.interface == IR_POSITIVE_PAIR_INTERFACE
    assert result.miner_version == IR_POSITIVE_PAIR_MINER_VERSION
    assert set(result.covered_classes) == {item.value for item in POSITIVE_EQUIVALENCE_CLASSES}
    assert len(result.admitted) == 8
    assert result.rejected == ()
    assert result.identity() == mine_canonical_positive_pairs().identity()


def test_every_admitted_pair_has_complete_lineage_and_authority() -> None:
    result = mine_canonical_positive_pairs()

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
    result = mine_canonical_positive_pairs()
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

    logical = candidate_from_recipe_case(
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
        candidate = candidate_from_recipe_case(
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
    cross = candidate_from_recipe_case(
        {
            "case_id": "cross-split",
            "relationship": SemanticRelationship.EXACT.value,
            "sibling_split": "holdout",
        }
    )
    assert classify_positive_pair_candidate(cross) is PositivePairRejection.CROSS_SPLIT_SIBLING

    holdout = candidate_from_recipe_case(
        {
            "case_id": "holdout-pair",
            "relationship": SemanticRelationship.EXACT.value,
            "split": "holdout",
        }
    )
    assert classify_positive_pair_candidate(holdout) is PositivePairRejection.NON_TRAINING_SPLIT

    grouped = candidate_from_recipe_case(
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
    exact = candidate_from_recipe_case(
        {
            "case_id": "dup-exact",
            "left_name": "shared-left",
            "relationship": SemanticRelationship.EXACT.value,
            "right_name": "shared-right",
        }
    )
    paraphrase = candidate_from_recipe_case(
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
    result = mine_canonical_positive_pairs()
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
    candidate = candidate_from_recipe_case(
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

    denied = candidate_from_recipe_case(
        {
            "case_id": "denied-rights",
            "relationship": SemanticRelationship.EXACT.value,
            "rights": RightsDisposition.DENIED.value,
        }
    )
    assert classify_positive_pair_candidate(denied) is PositivePairRejection.RIGHTS_NOT_ADMITTED


def test_unverified_evidence_cannot_admit_a_positive_pair() -> None:
    candidate = candidate_from_recipe_case(
        {
            "case_id": "unverified",
            "evidence_status": EvidenceStatus.CANDIDATE.value,
            "relationship": SemanticRelationship.EXACT.value,
        }
    )
    assert classify_positive_pair_candidate(candidate) is PositivePairRejection.UNVERIFIED_EVIDENCE


def test_sealed_shards_regenerate_and_stay_content_addressed(tmp_path: Path) -> None:
    data_dir = resolve_positive_pair_data_dir()
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    recipe = json.loads((data_dir / "recipe.json").read_text(encoding="utf-8"))
    receipts = json.loads((data_dir / "receipts.json").read_text(encoding="utf-8"))
    catalog = json.loads((data_dir / "classes.json").read_text(encoding="utf-8"))

    assert recipe["interface"] == "IRPositivePairRecipe@1"
    assert recipe["task_id"] == "PGIR-040"
    assert recipe["model_checkpoint_identity"] == "none/deterministic"
    assert set(recipe["classes"]) == {item.value for item in POSITIVE_EQUIVALENCE_CLASSES}
    assert {"reconstruction", "kernel", "translation"} <= set(receipts["kinds"])
    assert manifest["pair_count"] == 8
    assert manifest["split_name"] == "train"
    assert set(manifest["covered_classes"]) == {item.value for item in POSITIVE_EQUIVALENCE_CLASSES}

    regenerated = write_positive_pair_shards(tmp_path)
    assert regenerated["manifest"]["manifest_cid"] == manifest["manifest_cid"]
    assert regenerated["recipe"]["recipe_cid"] == recipe["recipe_cid"]
    assert regenerated["receipts"]["receipts_cid"] == receipts["receipts_cid"]
    assert regenerated["catalog"]["catalog_cid"] == catalog["catalog_cid"]

    pairs = load_positive_pair_shards(data_dir)
    assert len(pairs) == 8
    for pair in pairs:
        admitted = IRTrainingExample.classify(
            example_id=f"example:{pair.pair_id}",
            record=pair,
            selected_evidence_id=pair.evidence[0].evidence_id,
        )
        assert admitted.training_eligible
    admissions = loss_pair_admissions(pairs)
    assert all(item["admitted"] and item["pair_class"] == "positive" for item in admissions)


def test_shard_compare_and_swap_refuses_divergent_payloads(tmp_path: Path) -> None:
    path = tmp_path / "shard.json"
    cas_write_json(path, {"ok": True})
    cas_write_json(path, {"ok": True})
    with pytest.raises(PositivePairShardConflictError):
        cas_write_json(path, {"ok": False})


def test_raise_on_reject_surfaces_negative_authority() -> None:
    candidate = candidate_from_recipe_case(
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
        candidate_from_recipe_case(
            {
                "case_id": "unknown-rel",
                "relationship": "close_enough",
            }
        )
