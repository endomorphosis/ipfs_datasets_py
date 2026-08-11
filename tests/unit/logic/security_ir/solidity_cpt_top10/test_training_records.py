"""CRYPTOIR-G770 unit tests for partitioned formal-learning records."""

from __future__ import annotations

import hashlib

import pytest

from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.formalize import (
    formalize_solidity_security_graph,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.graph import (
    build_solidity_security_graph,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.projector import (
    SolidityGraphProjector,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.source_snapshot import (
    adapt_solidity_cpt_row,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.training_records import (
    FormalLearningBundle,
    FormalLearningRecord,
    LabelStatus,
    TrainingRecordError,
    TrainingStreamKind,
    ValidatedProofReceipt,
    build_cpt_token_record,
    build_evaluation_only_record,
    build_instruction_record_from_formalization,
    build_learning_bundle_from_formalization,
    build_proof_attempt_record,
)


SOURCE = """\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;
contract Counter {
    uint256 public n;
    function inc() external { n += 1; }
}
"""


def _formalization():
    raw = {
        "text": SOURCE,
        "source": "etherscan",
        "address": "0x" + "c" * 40,
        "name": "Counter",
        "compiler": "v0.8.24",
        "license": "MIT",
        "path": "contracts/Counter.sol",
        "n_chars": len(SOURCE),
    }
    adapted = adapt_solidity_cpt_row(raw, row_index=2)
    projection = SolidityGraphProjector().project_adapted(
        adapted, quality_score=0.4
    )
    graph = build_solidity_security_graph((projection,))
    return formalize_solidity_security_graph(
        graph, partition_cid=graph.config_cid, quality_score=0.4
    )


def test_four_streams_remain_distinct() -> None:
    formalization = _formalization()
    digest = hashlib.sha256(SOURCE.encode()).hexdigest()
    receipt = ValidatedProofReceipt(
        receipt_id="receipt:demo:1",
        backend_id="backend:smt-stub",
        obligation_id=formalization.obligations[0].obligation_id
        if formalization.obligations
        else "obligation:placeholder",
        lowering_id="lowering:smt-lib:v1",
        executed=True,
        supported=True,
        receipt_digest=hashlib.sha256(b"receipt-body").hexdigest(),
    )
    bundle = build_learning_bundle_from_formalization(
        formalization,
        sample_prefix="sample-a",
        token_digest=digest,
        proof_receipt=receipt,
        evaluation_control_kind="held_out_mutation",
    )
    assert len(bundle.cpt_tokens) == 1
    assert len(bundle.instruction) == 1
    assert len(bundle.proof_attempt) == 1
    assert len(bundle.evaluation_only) == 1
    assert bundle.cpt_tokens[0].stream is TrainingStreamKind.CPT_TOKENS
    assert bundle.instruction[0].stream is TrainingStreamKind.INSTRUCTION
    assert bundle.proof_attempt[0].stream is TrainingStreamKind.PROOF_ATTEMPT
    assert bundle.evaluation_only[0].stream is TrainingStreamKind.EVALUATION_ONLY
    sample_ids = [item.sample_id for item in bundle.records()]
    assert len(sample_ids) == len(set(sample_ids))


def test_cpt_tokens_instruction_proof_and_eval_contracts() -> None:
    formalization = _formalization()
    cpt = build_cpt_token_record(
        sample_id="row-1:cpt",
        token_digest="a" * 64,
        graph_cid=formalization.graph_cid,
        source_cids=formalization.source_cids,
        config_cid=formalization.config_cid,
        partition_cid=formalization.partition_cid,
        quality_score=0.4,
    )
    assert cpt.label_status is LabelStatus.UNLABELED
    assert cpt.target is None
    assert cpt.quality_is_safety_label is False

    instruction = build_instruction_record_from_formalization(
        formalization, sample_id="row-1:instruction"
    )
    assert instruction.stream is TrainingStreamKind.INSTRUCTION
    if formalization.obligations:
        assert instruction.label_status is LabelStatus.INSTRUCTION_TARGET
        target = dict(instruction.target)
        assert target["is_proof"] is False
        assert target["obligation_is_not_proof"] is True
    features = dict(instruction.features)
    assert "solver_results" not in features
    assert "evaluation_label" not in features

    unlabeled_proof = build_proof_attempt_record(
        formalization, sample_id="row-1:proof-unlabeled"
    )
    assert unlabeled_proof.label_status is LabelStatus.UNLABELED
    assert unlabeled_proof.proof_receipt is None

    with pytest.raises(TrainingRecordError, match="validated execution receipt"):
        FormalLearningRecord(
            stream=TrainingStreamKind.PROOF_ATTEMPT,
            sample_id="row-1:proof-bad",
            features={
                "stream_kind": TrainingStreamKind.PROOF_ATTEMPT.value,
                "declaration_id": formalization.declaration_id,
            },
            target={"kind": "proof_attempt_label", "is_proof": True},
            label_status=LabelStatus.PROOF_BACKED,
            graph_cid=formalization.graph_cid,
            source_cids=formalization.source_cids,
            config_cid=formalization.config_cid,
            partition_cid=formalization.partition_cid,
            proof_receipt=None,
        )

    receipt = ValidatedProofReceipt(
        receipt_id="receipt:ok",
        backend_id="backend:z3",
        obligation_id="obligation:demo",
        lowering_id="lowering:smt",
        executed=True,
        supported=True,
        receipt_digest="b" * 64,
    )
    proof = build_proof_attempt_record(
        formalization,
        sample_id="row-1:proof",
        proof_receipt=receipt,
    )
    assert proof.label_status is LabelStatus.PROOF_BACKED
    assert proof.proof_receipt is not None
    assert proof.proof_receipt.executed is True
    # Features still exclude solver verdicts.
    assert "solver_verdict" not in dict(proof.features)

    evaluation = build_evaluation_only_record(
        formalization,
        sample_id="row-1:eval",
        control_kind="adversarial_poison",
        evaluation_label={"control": "poisoned_comment", "expected": "abstain"},
    )
    assert evaluation.stream is TrainingStreamKind.EVALUATION_ONLY
    assert evaluation.label_status is LabelStatus.EVALUATION_CONTROL
    assert dict(evaluation.features).get("evaluation_only") is True
    # Label stays in target, not features.
    assert "evaluation_label" not in dict(evaluation.features)
    assert evaluation.target is not None


def test_bundle_rejects_cross_stream_sample_ids() -> None:
    formalization = _formalization()
    shared = "shared-sample"
    cpt = build_cpt_token_record(
        sample_id=shared,
        token_digest="c" * 64,
        graph_cid=formalization.graph_cid,
        source_cids=formalization.source_cids,
        config_cid=formalization.config_cid,
    )
    instruction = build_instruction_record_from_formalization(
        formalization, sample_id=shared
    )
    with pytest.raises(TrainingRecordError, match="must not cross streams"):
        FormalLearningBundle(
            cpt_tokens=(cpt,),
            instruction=(instruction,),
            graph_cid=formalization.graph_cid,
            source_cids=formalization.source_cids,
            config_cid=formalization.config_cid,
        )


def test_unlabeled_rows_remain_unlabeled() -> None:
    formalization = _formalization()
    # Instruction without targets when obligations empty is unlabeled;
    # with obligations, force unlabeled by constructing manually.
    record = FormalLearningRecord(
        stream=TrainingStreamKind.INSTRUCTION,
        sample_id="row-unlabeled",
        features={
            "stream_kind": TrainingStreamKind.INSTRUCTION.value,
            "declaration_id": formalization.declaration_id,
            "declaration_digest": formalization.declaration_digest,
        },
        target=None,
        label_status=LabelStatus.UNLABELED,
        graph_cid=formalization.graph_cid,
        source_cids=formalization.source_cids,
        config_cid=formalization.config_cid,
        partition_cid=formalization.partition_cid,
        quality_score=None,
        quality_is_safety_label=False,
    )
    assert record.label_status is LabelStatus.UNLABELED
    assert record.target is None


def test_quality_never_safety_label_on_training_records() -> None:
    formalization = _formalization()
    record = build_instruction_record_from_formalization(
        formalization, sample_id="row-quality"
    )
    assert record.quality_is_safety_label is False
    with pytest.raises(TrainingRecordError, match="safety label"):
        FormalLearningRecord(
            stream=TrainingStreamKind.INSTRUCTION,
            sample_id="row-bad-quality",
            features={
                "stream_kind": TrainingStreamKind.INSTRUCTION.value,
                "declaration_id": "decl:x",
            },
            target=None,
            label_status=LabelStatus.UNLABELED,
            graph_cid=formalization.graph_cid,
            source_cids=formalization.source_cids,
            config_cid=formalization.config_cid,
            partition_cid=formalization.partition_cid,
            quality_is_safety_label=True,
        )


def test_features_reject_solver_and_model_score_leakage() -> None:
    formalization = _formalization()
    with pytest.raises(TrainingRecordError, match="solver results|model scores"):
        FormalLearningRecord(
            stream=TrainingStreamKind.INSTRUCTION,
            sample_id="row-leaky",
            features={
                "stream_kind": TrainingStreamKind.INSTRUCTION.value,
                "declaration_id": formalization.declaration_id,
                "solver_results": [{"status": "sat"}],
                "model_score": 0.99,
            },
            target=None,
            label_status=LabelStatus.UNLABELED,
            graph_cid=formalization.graph_cid,
            source_cids=formalization.source_cids,
            config_cid=formalization.config_cid,
            partition_cid=formalization.partition_cid,
        )


def test_proof_receipt_requires_executed_supported_lowering() -> None:
    with pytest.raises(TrainingRecordError, match="executed=True"):
        ValidatedProofReceipt(
            receipt_id="receipt:no",
            backend_id="backend:x",
            obligation_id="obligation:x",
            lowering_id="lowering:x",
            executed=False,
            supported=True,
            receipt_digest="d" * 64,
        )
    with pytest.raises(TrainingRecordError, match="supported=True"):
        ValidatedProofReceipt(
            receipt_id="receipt:no2",
            backend_id="backend:x",
            obligation_id="obligation:x",
            lowering_id="lowering:x",
            executed=True,
            supported=False,
            receipt_digest="d" * 64,
        )
