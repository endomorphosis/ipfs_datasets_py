"""Replay adversarial source-copy candidates through LegalIR guardrails."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    generate_legal_ir_proof_obligations,
)
from ipfs_datasets_py.logic.modal.codec import _source_copy_reward_hack_penalty
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    hammer_guidance_metric_block,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "source_copy_reward_hack_replay.jsonl"
)
SCHEMA_VERSION = "legal-ir-source-copy-reward-hack-replay-v1"
MUST_FAIL_CASES = {
    "raw_source_span_is_used_as_ir",
    "cosine_improves_but_symbolic_validity_regresses",
    "decompiler_output_copies_source_without_structure",
}


def _records() -> list[dict[str, Any]]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _contains_text(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, dict):
        return any(_contains_text(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_text(item, expected) for item in value)
    return False


def test_replay_fixture_is_hash_bound_and_covers_every_adversarial_clause() -> None:
    records = _records()

    assert len(records) == len(MUST_FAIL_CASES)
    assert {record["must_fail_when"] for record in records} == MUST_FAIL_CASES
    assert len({record["case_id"] for record in records}) == len(records)
    for record in records:
        source_span = record["source_span"]
        source_text = source_span["text"]
        assert record["schema_version"] == SCHEMA_VERSION
        assert source_span["sha256"] == hashlib.sha256(
            source_text.encode("utf-8")
        ).hexdigest()
        assert record["expected"]["accepted"] is False
        assert _contains_text(record["candidate"]["ir_payload"], source_text)
        assert record["candidate"]["metrics"][
            "compiler_ir_cosine_similarity"
        ] > record["baseline"]["metrics"]["compiler_ir_cosine_similarity"]


@pytest.mark.parametrize("record", _records(), ids=lambda item: item["case_id"])
def test_copied_candidate_trips_copy_symbolic_and_hammer_guardrails(
    record: dict[str, Any],
) -> None:
    baseline = record["baseline"]["metrics"]
    candidate = record["candidate"]["metrics"]
    artifact = record["hammer_guidance_artifacts"][0]

    computed_penalty = _source_copy_reward_hack_penalty(
        source_span_copy_ratio=candidate["source_span_copy_ratio"],
        text_reconstruction_similarity=candidate[
            "source_decompiled_text_embedding_cosine_similarity"
        ],
        structural_text_similarity=max(
            0.0, 1.0 - candidate["structural_text_reconstruction_loss"]
        ),
    )
    hammer_metrics = hammer_guidance_metric_block(record)

    assert computed_penalty > 0.35
    assert candidate["source_copy_reward_hack_penalty"] > 0.35
    assert candidate["symbolic_validity_success_rate"] < baseline[
        "symbolic_validity_success_rate"
    ]
    assert artifact["source_copy_rejected"] is True
    assert artifact["trusted"] is False
    assert set(record["expected"]["failed_obligation_kinds"]) <= set(
        artifact["proof_obligation_ids"]
    )
    assert hammer_metrics["hammer_proof_success_rate"] == 0.0
    assert hammer_metrics["hammer_reconstruction_success_rate"] == 0.0
    assert hammer_metrics["source_copy_penalty"] == 1.0
    assert hammer_metrics["symbolic_validity_success_rate"] == 0.0


@pytest.mark.parametrize("record", _records(), ids=lambda item: item["case_id"])
def test_verifier_owned_decompiler_obligations_never_embed_the_copied_span(
    record: dict[str, Any],
) -> None:
    source_text = record["source_span"]["text"]
    sample = build_us_code_sample(
        title="fixture",
        section=record["case_id"],
        text=source_text,
    )

    obligations = generate_legal_ir_proof_obligations(sample)
    decompiler_obligations = {
        obligation.kind: obligation
        for obligation in obligations
        if obligation.legal_ir_view == "modal.decompiler"
    }

    assert {
        "decompiler_round_trip_signature",
        "decompiler_structural_summary",
        "decompiler_modality_retention",
        "decompiler_source_copy_guardrail",
    } <= set(decompiler_obligations)
    assert decompiler_obligations[
        "decompiler_source_copy_guardrail"
    ].metadata["source_copy_policy"] == "hash_only"
    for obligation in obligations:
        assert source_text not in obligation.statement
        assert obligation.metadata.get("source_span_sha256") != source_text
