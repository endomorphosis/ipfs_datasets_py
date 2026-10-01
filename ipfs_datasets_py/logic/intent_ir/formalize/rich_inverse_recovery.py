"""Recover token-faithful neural inverses using generated grammar boundaries.

Frozen model/grammar files stay unchanged. This adapter executes direct neural
inference itself; it never accepts an externally supplied cached prediction.
Only formatting of actual generated tokens can be recovered, followed by full
source agreement. Missing source-to-IR predictions remain failures.
"""
from __future__ import annotations

from pathlib import Path

from . import rich_decoder as direct
from . import rich_grammar as grammar
from .copy_roundtrip import generation_usable
from .rich_logic import project_rich_intent_logic

SCHEMA = "intent-rich-token-faithful-inverse-roundtrip/v1"
METHOD = "source_independent_generated_inverse_detokenization"


def prepare_inverse_recovered_rich_intent(instruction, checkpoint=None, *, context=None,
                                         beam_width=16, weight_ablation=None):
    """Run the frozen direct model and inspect its own retained inverse beams.

    The codec sees only a generated string. The original source and the learned
    forward AST are consulted after it produces its independent reconstruction.
    An encoded AST is never rendered as a substitute learned inverse.
    """
    from . import rich_inverse_codec as codec
    from ....optimizers.logic_theorem_optimizer import autoencoder_paired_copy as shared
    if type(instruction) is not str or type(beam_width) is not int or not 1 <= beam_width <= 16:
        raise ValueError("exact source and bounded inverse beam required")
    baseline = direct.prepare_rich_intent_instruction(instruction, checkpoint, context=context,
        beam_width=beam_width, weight_ablation=weight_ablation)
    if baseline["rich_ir"] is not None or baseline["counts"]["decoder_executions"] == 0:
        return baseline
    report = {"schema": SCHEMA, "decoding_method": METHOD, "status": "fail_open_no_token_faithful_inverse",
        "instruction": instruction, "instruction_sha256": direct.sha(instruction.encode()),
        "checkpoint": checkpoint, "context": context, "beam_width": beam_width,
        "weight_ablation": weight_ablation, "direct_report": baseline,
        "learned": {"encoder": None, "decoder": None, "ast": None, "normalized_text": None},
        "rich_ir": None, "logic": None, "source_agreement": False, "codec": None,
        "counts": dict(baseline["counts"]), "codec_attempts": 0,
        "codec_reads_source_or_expected_ast": False, "codec_supplies_new_tokens": False,
        "numerical_predictions_reused_only_within_current_invocation": True,
        "external_cached_predictions_accepted": False, "additional_neural_executions": 0,
        "whole_AST_generated_by_neural_encoder": True, "whole_inverse_generated_by_neural_decoder": True,
        "continue_planning": True, "raw_instruction_preserved": True,
        "training_steps": 0, "llm_calls": 0, "producer_pins": {**direct._pins(),
            codec.__name__: direct.sha(Path(codec.__file__).read_bytes()),
            __name__: direct.sha(Path(__file__).read_bytes())}, **direct.AUTHORITY}
    try:
        # Full neural source agreement is established before considering an
        # inverse. No source/AST object is passed into the codec function.
        expected = grammar.parse_instruction(instruction)
        forwards = [baseline["learned"]["encoder"], *(baseline.get("encoder_search") or {}).get("rows", [])]
        encoder, ast = None, None
        for candidate in forwards:
            if candidate is None or not generation_usable(candidate):
                continue
            try:
                prediction = grammar.sequence_to_ast(candidate["generated_text"])
            except (ValueError, TypeError):
                continue
            if prediction == expected:
                encoder, ast = candidate, prediction
                break
        if encoder is not None:
            for search in baseline["decoder_searches"]:
                for candidate in search["rows"]:
                    if not generation_usable(candidate):
                        continue
                    report["codec_attempts"] += 1
                    recovered = codec.recover_generated_inverse(candidate["generated_text"])
                    if (recovered.get("status") != "candidate" or recovered.get("token_equivalent") is not True
                            or shared.tokenize(recovered["text"]) != shared.tokenize(candidate["generated_text"])):
                        continue
                    independently_parsed = grammar.parse_instruction(recovered["text"], normalized_inverse=True)
                    if independently_parsed != ast or recovered["ast"] != ast:
                        continue
                    report.update(status="source_supported_token_faithful_inverse", source_agreement=True,
                        codec=recovered, learned={"encoder": encoder, "decoder": candidate,
                            "ast": ast, "normalized_text": recovered["text"]},
                        rich_ir={"schema": "intent-rich-ir/v1", "ast": ast,
                            "source_sha256": report["instruction_sha256"]},
                        logic=project_rich_intent_logic(ast, instruction=instruction, context=context))
                    break
                if report["rich_ir"] is not None:
                    break
    except Exception as exc:
        report.update(status="fail_open_inverse_codec_error", error_type=type(exc).__name__, reason=str(exc))
    report["report_sha256"] = direct.sha(direct.wire(report))
    return report


def validate_inverse_recovered_rich_intent(report, *, instruction, checkpoint_descriptor=None):
    """Replay actual checkpoint inference and token-preserving reconstruction."""
    if type(report) is not dict:
        raise ValueError("learned inverse recovery report required")
    if report.get("schema") == direct.SCHEMA:
        return direct.validate_rich_intent_report(report, instruction=instruction,
            checkpoint_descriptor=checkpoint_descriptor)
    if report.get("schema") != SCHEMA:
        raise ValueError("known inverse recovery report required")
    expected = prepare_inverse_recovered_rich_intent(instruction, checkpoint_descriptor,
        context=report["context"], beam_width=report["beam_width"], weight_ablation=report["weight_ablation"])
    if direct.wire(expected) != direct.wire(report):
        raise ValueError("inverse recovery differs from actual numerical replay")
    return report


__all__ = ["SCHEMA", "METHOD", "prepare_inverse_recovered_rich_intent", "validate_inverse_recovered_rich_intent"]
