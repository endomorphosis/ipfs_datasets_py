"""Grammar, binder, type, family, and proof-state constrained decoding tests."""

from __future__ import annotations

import math
from collections.abc import Sequence

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_grammar_decoder import (
    LEGAL_IR_CANONICAL_VOCABULARY_CID,
    LEGAL_IR_CONSTRAINT_MASK_NAMES,
    LEGAL_IR_CONSTRAINED_DECODER_INTERFACE,
    LEGAL_IR_CONSTRAINED_DECODER_SCHEMA,
    LEGAL_IR_GRAMMAR_FAMILIES,
    LEGAL_IR_MAX_BEAM_WIDTH,
    LEGAL_IR_MAX_DECODE_STEPS,
    LegalIRConstrainedDecodeConfig,
    LegalIRConstraintBypassError,
    LegalIRFrozenTokenizer,
    LegalIRGrammarDecoder,
    UnboundedLegalIRBeamError,
    admit_legal_ir_gold_path,
    apply_legal_ir_constraint_masks,
    build_compatible_learned_architecture,
    compare_constrained_vs_unconstrained_proof_calls,
    constrained_legal_ir_token_decode,
    gate_legal_ir_prover_call,
    legal_ir_constraint_masks,
)


def _valid_candidate(family: str) -> dict:
    candidates = {
        "deontic": {
            "family": "deontic",
            "rules": [
                {
                    "modality": "obligation",
                    "subject": "agency",
                    "action": "provide_notice",
                }
            ],
        },
        "frame_logic": {
            "family": "frame_logic",
            "triples": [
                {
                    "subject": "agency",
                    "relation": "must_provide",
                    "object": "notice",
                }
            ],
        },
        "tdfol": {
            "family": "tdfol",
            "formulas": [
                {
                    "quantifier": "forall",
                    "predicate": "ProvideNotice",
                    "arguments": ["agency", "notice"],
                }
            ],
        },
        "knowledge_graphs": {
            "family": "knowledge_graphs",
            "nodes": [
                {"id": "agency", "label": "Agency"},
                {"id": "notice", "label": "Notice"},
            ],
            "edges": [
                {
                    "source": "agency",
                    "target": "notice",
                    "label": "must_provide",
                }
            ],
        },
        "cec": {
            "family": "cec",
            "events": [{"id": "e1", "type": "omission"}],
            "counterexamples": [{"violates": "notice_obligation"}],
        },
        "external_provers": {
            "family": "external_provers",
            "backend": "unknown",
            "obligations": [{"id": "po1", "goal": "ProvideNotice"}],
        },
        "temporal": {
            "family": "temporal",
            "intervals": [{"id": "i1", "duration": "P30D"}],
            "relations": [{"before": "final_action", "after": "notice"}],
        },
        "provenance": {
            "family": "provenance",
            "source_refs": [{"citation": "5 U.S.C. 552", "span_hash": "abc"}],
            "evidence": [{"receipt_id": "r1", "source_hash": "def"}],
        },
        "decompiler": {
            "family": "decompiler",
            "target_view": "deontic.ir",
            "source_copy_policy": "hash_only",
            "steps": [{"op": "emit_rule", "slot": "obligation"}],
        },
    }
    return candidates[family]


def _minimal_gold_ids(family: str, tokenizer: LegalIRFrozenTokenizer) -> tuple[int, ...]:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_grammar_decoder import (
        default_legal_ir_production_specs,
    )

    type_piece = next(
        spec.output_type for spec in default_legal_ir_production_specs() if spec.family == family
    )
    family_entry = tokenizer.lookup(family)
    assert family_entry is not None
    return (
        tokenizer.bos_id,
        family_entry.token_id,
        tokenizer.require(type_piece, token_class="type").token_id,
        tokenizer.eos_id,
    )


def _gold_ids(family: str) -> tuple[int, ...]:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    try:
        return tokenizer.encode_canonical(_valid_candidate(family), family=family).token_ids
    except Exception:
        return _minimal_gold_ids(family, tokenizer)


def _gold_biased_logits(gold_ids: Sequence[int], vocab_size: int) -> list[list[float]]:
    rows: list[list[float]] = []
    for token_id in gold_ids:
        row = [0.0] * vocab_size
        row[int(token_id)] = 5.0
        rows.append(row)
    return rows


def test_unbounded_beam_and_parser_bypass_are_rejected() -> None:
    with pytest.raises(UnboundedLegalIRBeamError):
        LegalIRConstrainedDecodeConfig(beam_width=LEGAL_IR_MAX_BEAM_WIDTH + 1)
    with pytest.raises(UnboundedLegalIRBeamError):
        LegalIRConstrainedDecodeConfig(max_steps=LEGAL_IR_MAX_DECODE_STEPS + 1)
    with pytest.raises(UnboundedLegalIRBeamError):
        LegalIRConstrainedDecodeConfig(beam_width=0)
    with pytest.raises(LegalIRConstraintBypassError):
        LegalIRConstrainedDecodeConfig(parser_pruning=False)
    with pytest.raises(LegalIRConstraintBypassError):
        LegalIRConstrainedDecodeConfig(type_checks=False)


def test_constraint_masks_are_separately_inspectable() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    masks = legal_ir_constraint_masks((), family="deontic", tokenizer=tokenizer)

    assert tuple(LEGAL_IR_CONSTRAINT_MASK_NAMES) == (
        "valid_token",
        "grammar",
        "binder",
        "type",
        "family",
    )
    assert masks.to_dict()["schema"] == LEGAL_IR_CONSTRAINED_DECODER_SCHEMA
    assert tokenizer.bos_id in set(masks.allowed_token_ids())
    assert tokenizer.lookup("obligation").token_id not in set(masks.allowed_token_ids())
    assert sum(masks.layer("valid_token")) >= 1
    assert sum(masks.layer("grammar")) >= 1
    assert len(masks.intersected()) == tokenizer.vocabulary_size


@pytest.mark.parametrize("family", LEGAL_IR_GRAMMAR_FAMILIES)
def test_gold_paths_remain_admitted_for_every_family(family: str) -> None:
    gold = _gold_ids(family)
    admission = admit_legal_ir_gold_path(gold, family=family)

    assert admission.admitted is True
    assert admission.family == family
    assert admission.illegal_index == -1
    assert admission.token_ids[0] == LegalIRFrozenTokenizer.canonical().bos_id
    assert admission.token_ids[-1] == LegalIRFrozenTokenizer.canonical().eos_id


def test_family_operator_leakage_is_masked_in_tdfol_body() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    gold = _gold_ids("tdfol")
    after_type = gold[:3]
    masks = legal_ir_constraint_masks(after_type, family="tdfol", tokenizer=tokenizer)
    obligation_id = tokenizer.require("obligation", token_class="operator").token_id
    forall_id = tokenizer.require("forall", token_class="binder").token_id

    assert obligation_id not in set(masks.allowed_token_ids())
    assert forall_id in set(masks.allowed_token_ids())
    deontic_body = legal_ir_constraint_masks(
        tokenizer.encode_canonical(_valid_candidate("deontic"), family="deontic").token_ids[:3],
        family="deontic",
        tokenizer=tokenizer,
    )
    assert forall_id not in set(deontic_body.allowed_token_ids())


def test_type_mask_only_admits_the_family_output_type() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    prefix = (
        tokenizer.bos_id,
        tokenizer.require("deontic", token_class="family").token_id,
    )
    masks = legal_ir_constraint_masks(prefix, family="deontic", tokenizer=tokenizer)
    allowed = set(masks.allowed_token_ids())

    assert tokenizer.require("DeonticRule", token_class="type").token_id in allowed
    assert tokenizer.require("TDFOLFormula", token_class="type").token_id not in allowed
    assert tokenizer.require("obligation", token_class="operator").token_id not in allowed


def test_family_mask_blocks_cross_family_tokens_at_family_slot() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    masks = legal_ir_constraint_masks((tokenizer.bos_id,), family="deontic", tokenizer=tokenizer)
    allowed = set(masks.allowed_token_ids())

    assert tokenizer.require("deontic", token_class="family").token_id in allowed
    assert tokenizer.require("tdfol", token_class="family").token_id not in allowed


def test_apply_masks_zeroes_illegal_logits() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    masks = legal_ir_constraint_masks((), family="deontic", tokenizer=tokenizer)
    logits = [9.0] * tokenizer.vocabulary_size
    masked = apply_legal_ir_constraint_masks(logits, masks)

    assert masked[tokenizer.bos_id] == 9.0
    assert masked[tokenizer.require("obligation").token_id] <= -1.0e8


@pytest.mark.parametrize("family", LEGAL_IR_GRAMMAR_FAMILIES)
def test_bounded_beam_recovers_gold_and_never_exceeds_width(family: str) -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    gold = _gold_ids(family)
    result = constrained_legal_ir_token_decode(
        _gold_biased_logits(gold, tokenizer.vocabulary_size),
        family=family,
        gold_token_ids=gold,
        tokenizer=tokenizer,
        config=LegalIRConstrainedDecodeConfig(beam_width=4, max_steps=64, family=family),
    )

    assert result.accepted is True
    assert result.token_ids == gold
    assert result.gold_path_preserved is True
    assert result.beam_width <= LEGAL_IR_MAX_BEAM_WIDTH
    assert result.steps <= LEGAL_IR_MAX_DECODE_STEPS
    assert result.schema == LEGAL_IR_CONSTRAINED_DECODER_SCHEMA
    assert result.telemetry.contract == LEGAL_IR_CONSTRAINED_DECODER_INTERFACE
    assert len(result.hypotheses) <= 4


def test_parser_prunes_invalid_high_score_family_leakage() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    gold = _gold_ids("deontic")
    logits = _gold_biased_logits(gold, tokenizer.vocabulary_size)
    tdfol_id = tokenizer.require("tdfol", token_class="family").token_id
    logits[1][tdfol_id] = 99.0

    result = constrained_legal_ir_token_decode(
        logits,
        family="deontic",
        gold_token_ids=gold,
        tokenizer=tokenizer,
        config=LegalIRConstrainedDecodeConfig(beam_width=4, max_steps=64, family="deontic"),
    )

    assert result.accepted is True
    assert result.token_ids[1] == gold[1]
    assert tdfol_id not in result.token_ids[:3]


def test_proof_state_pruning_is_optional_and_drops_closed_goal_tactics() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    gold = _gold_ids("tdfol")
    after_type = gold[:3]
    hammer_id = tokenizer.require("hammer", token_class="tactic").token_id
    open_masks = legal_ir_constraint_masks(
        after_type,
        family="tdfol",
        tokenizer=tokenizer,
        config=LegalIRConstrainedDecodeConfig(proof_state_pruning=False),
    )
    closed_masks = legal_ir_constraint_masks(
        after_type,
        family="tdfol",
        tokenizer=tokenizer,
        proof_state={"status": "proved", "open_goals": 0},
        config=LegalIRConstrainedDecodeConfig(proof_state_pruning=True),
    )

    assert hammer_id in set(open_masks.allowed_token_ids())
    assert hammer_id not in set(closed_masks.allowed_token_ids())


def test_fallback_is_explicit_when_no_finished_hypothesis_exists() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    empty_logits = [[-1.0e8] * tokenizer.vocabulary_size]
    rejected = constrained_legal_ir_token_decode(
        empty_logits,
        family="deontic",
        tokenizer=tokenizer,
        config=LegalIRConstrainedDecodeConfig(
            beam_width=2,
            max_steps=2,
            fallback="reject",
            family="deontic",
        ),
    )
    gold = _gold_ids("deontic")
    rescued = constrained_legal_ir_token_decode(
        empty_logits,
        family="deontic",
        gold_token_ids=gold,
        tokenizer=tokenizer,
        config=LegalIRConstrainedDecodeConfig(
            beam_width=2,
            max_steps=2,
            fallback="gold_if_admitted",
            family="deontic",
        ),
    )

    assert rejected.accepted is False
    assert rejected.fallback_used == "reject"
    assert "no_finished_hypothesis" in rejected.telemetry.rejection_reasons
    assert rescued.accepted is True
    assert rescued.fallback_used == "gold_if_admitted"
    assert rescued.token_ids == gold


def test_invalid_candidates_fail_before_prover_calls() -> None:
    calls: list[object] = []

    def prover(payload: object) -> dict:
        calls.append(payload)
        return {"proved": True}

    valid = gate_legal_ir_prover_call(
        _valid_candidate("deontic"),
        family="deontic",
        prover=prover,
    )
    invalid = gate_legal_ir_prover_call(
        {"family": "deontic", "rules": [{"modality": "maybe", "subject": "x", "action": "y"}]},
        family="deontic",
        prover=prover,
    )

    assert valid.admitted is True
    assert valid.prover_calls == 1
    assert invalid.admitted is False
    assert invalid.prover_calls == 0
    assert invalid.telemetry.prover_calls_avoided == 1
    assert len(calls) == 1


def test_constrained_decoding_reduces_proof_call_count_on_mutations() -> None:
    valid = _valid_candidate("deontic")
    leaked = {
        "family": "tdfol",
        "formulas": [
            {
                "quantifier": "forall",
                "predicate": "not a predicate",
                "arguments": [],
            }
        ],
    }
    mutated_tokens = list(_gold_ids("deontic"))
    tokenizer = LegalIRFrozenTokenizer.canonical()
    mutated_tokens[1] = tokenizer.require("tdfol", token_class="family").token_id
    comparison = compare_constrained_vs_unconstrained_proof_calls(
        [valid, leaked, mutated_tokens],
        family="deontic",
    )

    assert comparison["schema"] == LEGAL_IR_CONSTRAINED_DECODER_SCHEMA
    assert comparison["unconstrained_prover_calls"] == 3
    assert comparison["constrained_prover_calls"] == 1
    assert comparison["saved_proof_budget"] == 2
    assert comparison["prover_calls_avoided"] == 2


def test_decoder_methods_preserve_gold_and_do_not_mutate_vocabulary() -> None:
    decoder = LegalIRGrammarDecoder()
    tokenizer = decoder.frozen_tokenizer()
    cid_before = tokenizer.vocabulary_cid
    gold = decoder.encode_structured_output(_valid_candidate("deontic"), family="deontic")
    admission = decoder.admit_gold_path(gold.token_ids, family="deontic")
    decoded = decoder.decode_tokens(
        _gold_biased_logits(gold.token_ids, tokenizer.vocabulary_size),
        family="deontic",
        gold_token_ids=gold.token_ids,
        config=LegalIRConstrainedDecodeConfig(beam_width=3, max_steps=64, family="deontic"),
    )

    assert admission.admitted is True
    assert decoded.accepted is True
    assert decoded.token_ids == gold.token_ids
    assert tokenizer.vocabulary_cid == cid_before == LEGAL_IR_CANONICAL_VOCABULARY_CID
    with pytest.raises(Exception):
        tokenizer.add_token("new-piece", "operator")


def test_architecture_reconstruction_logits_stay_on_gold_when_biased() -> None:
    architecture = build_compatible_learned_architecture("shared_latent", seed=3)
    gold = _gold_ids("deontic")
    vocab = architecture.tokenizer.vocabulary_size

    def logits_fn(prefix: tuple[int, ...], step: int) -> list[float]:
        values = [0.0] * vocab
        hidden = architecture.encode_ids(prefix or (architecture.tokenizer.bos_id,))
        for index, component in enumerate(hidden):
            values[index % vocab] += float(component)
        if step < len(gold):
            values[gold[step]] += 8.0
        return values

    result = constrained_legal_ir_token_decode(
        logits_fn,
        family="deontic",
        gold_token_ids=gold,
        architecture=architecture,
        tokenizer=architecture.tokenizer,
        config=LegalIRConstrainedDecodeConfig(beam_width=2, max_steps=64, family="deontic"),
    )

    assert result.accepted is True
    assert result.token_ids == gold
    assert math.isfinite(result.score)


def test_mutation_property_illegal_prefixes_never_enter_allowed_set() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    gold = list(_gold_ids("frame_logic"))
    mutations = []
    mutations.append([*gold[:1], tokenizer.require("cec", token_class="family").token_id])
    mutations.append(
        [
            *gold[:2],
            tokenizer.require("DeonticRule", token_class="type").token_id,
        ]
    )
    mutations.append(
        [
            *gold[:3],
            tokenizer.require("obligation", token_class="operator").token_id,
        ]
    )
    for mutated in mutations:
        admission = admit_legal_ir_gold_path(mutated, family="frame_logic", tokenizer=tokenizer)
        assert admission.admitted is False
        assert admission.illegal_index >= 0
        gate = gate_legal_ir_prover_call(
            mutated,
            family="frame_logic",
            tokenizer=tokenizer,
            prover=lambda payload: (_ for _ in ()).throw(AssertionError(payload)),
        )
        assert gate.admitted is False
        assert gate.prover_calls == 0
