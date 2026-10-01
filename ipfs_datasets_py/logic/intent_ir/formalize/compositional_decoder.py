"""Explicit source-grammar composition of independently learned atomic clauses.

This is a hybrid parser/decoder. Connectives and atomic guard syntax belong to
the frozen source grammar; they are not claimed as neural predictions. Every
action atom must pass the existing learned encoder, learned inverse and exact
source agreement on its original child-clause slice. No parser-produced atom,
target sequence or normalized instruction is supplied to the encoder.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from . import rich_decoder as direct
from . import rich_grammar as grammar
from .rich_logic import project_rich_intent_logic

SCHEMA = "intent-grammar-composed-roundtrip/v1"
METHOD = "grammar_composition_with_neural_leaves"
_COUNT_KEYS = ("encoder_executions", "decoder_executions")


def _span(source, start, end, role):
    text = source[start:end]
    return {"role": role, "start_char": start, "end_char": end,
        "start_byte": len(source[:start].encode()), "end_byte": len(source[:end].encode()),
        "text": text, "text_sha256": direct.sha(text.encode())}


def _source_parts(source, kind):
    """Locate original slices after whole-input grammar admission, not labels."""
    if kind in {"and", "or", "then"}:
        found = None
        for pattern, selected in ((r"\s+and\s+then\s+", "then"), (r"\s+then\s+", "then"),
                                   (r"\s+and\s+", "and"), (r"\s+or\s+", "or")):
            match = re.search(pattern, source)
            if match:
                if selected != kind:
                    raise ValueError("source connective differs from admitted constructor")
                found = match
                break
        if found is None:
            raise ValueError("admitted connective has no exact source span")
        return [_span(source, 0, found.start(), "left_clause"),
                _span(source, found.start(), found.end(), "symbolic_connective"),
                _span(source, found.end(), len(source), "right_clause")]
    if kind == "if":
        # A single comma is required by the frozen admitted guard grammar.
        match = re.search(r",\s+", source)
        if match is None:
            raise ValueError("admitted guard has no exact source delimiter")
        return [_span(source, 0, match.end(), "symbolic_guard_prefix"),
                _span(source, match.end(), len(source), "body_clause")]
    raise ValueError("only admitted compound constructors can be composed")


def _check_cached_base(report, instruction, checkpoint, context, beam_width, weight_ablation):
    if (type(report) is not dict or report.get("schema") != direct.SCHEMA or
            report.get("instruction_sha256") != direct.sha(instruction.encode()) or
            report.get("checkpoint") != checkpoint or report.get("context") != context or
            report.get("beam_width") != beam_width or report.get("weight_ablation") != weight_ablation or
            report.get("project") is not True or
            report.get("report_sha256") != direct.sha(direct.wire(
                {key: value for key, value in report.items() if key != "report_sha256"}))):
        raise ValueError("cached direct report differs from exact source/checkpoint/options binding")
    counts = report.get("counts")
    if (type(counts) is not dict or set(counts) != set(_COUNT_KEYS) or
            any(type(value) is not int or value < 0 for value in counts.values())):
        raise ValueError("cached direct inference counts are invalid")


def prepare_composed_rich_intent(instruction, checkpoint=None, *, context=None, base_report=None,
                                 weight_ablation=None, beam_width=None):
    """Try direct inference, then compose actual learned atoms if it failed.

    ``base_report`` can reuse an already executed failed direct stage. Its hash
    and bindings are checked, but its counts are diagnostic until whole-report
    replay. Cached atom/success reports are numerically replayed before return.
    The composed acceptance decision never depends on a cached prediction.
    """
    if type(instruction) is not str:
        raise ValueError("exact original instruction required")
    if base_report is not None and type(base_report) is not dict:
        raise ValueError("direct inference report required")
    selected_beam = (base_report.get("beam_width", 8) if base_report is not None else 8) if beam_width is None else beam_width
    selected_ablation = base_report.get("weight_ablation") if base_report is not None and weight_ablation is None else weight_ablation
    if type(selected_beam) is not int or not 0 <= selected_beam <= 16:
        raise ValueError("bounded explicit beam width required")
    options = {"context": context, "beam_width": selected_beam, "weight_ablation": selected_ablation}
    reused = base_report is not None
    if reused:
        _check_cached_base(base_report, instruction, checkpoint, context, selected_beam, selected_ablation)
        baseline = deepcopy(base_report)
    else:
        baseline = direct.prepare_rich_intent_instruction(instruction, checkpoint, **options)
    try:
        expected = grammar.parse_instruction(instruction)
    except (ValueError, TypeError):
        if reused:
            direct.validate_rich_intent_report(baseline, instruction=instruction, checkpoint_descriptor=checkpoint)
        return baseline
    if expected["kind"] == "atom" or baseline.get("rich_ir") is not None:
        if reused:
            direct.validate_rich_intent_report(baseline, instruction=instruction, checkpoint_descriptor=checkpoint)
        return baseline
    report = {"schema": SCHEMA, "decoding_method": METHOD,
        "instruction_sha256": direct.sha(instruction.encode()), "instruction": instruction,
        "checkpoint": deepcopy(checkpoint), "status": "fail_open_composed_leaf_rejected",
        "learned": {"encoder": None, "decoder": None, "ast": None, "normalized_text": None},
        "encoder_search": None, "decoder_searches": [], "rich_ir": None, "logic": None,
        "source_agreement": False, "counts": dict(baseline["counts"]),
        "executed_here_counts": {key: 0 if reused else baseline["counts"][key] for key in _COUNT_KEYS},
        "phase_counts": {"direct": dict(baseline["counts"]), "neural_leaves": {key: 0 for key in _COUNT_KEYS}},
        "direct_report": baseline, "cached_direct_stage_reused": reused,
        "cached_direct_stage_is_numerically_replayed_here": False,
        "neural_leaves": [], "composition": None,
        "continue_planning": True, "raw_instruction_preserved": True,
        "training_steps": 0, "llm_calls": 0, "context": deepcopy(context),
        "weight_ablation": selected_ablation, "beam_width": selected_beam, "project": True,
        "whole_AST_generated_by_neural_encoder": False, "whole_inverse_generated_by_neural_decoder": False,
        "producer_pins": {**direct._pins(), __name__: direct.sha(Path(__file__).read_bytes())},
        **direct.AUTHORITY}

    def finish():
        report["report_sha256"] = direct.sha(direct.wire(report))
        return report

    try:
        parts = _source_parts(instruction, expected["kind"])
        if "".join(part["text"] for part in parts) != instruction:
            raise ValueError("composition omitted source characters")
        report["composition"] = {"constructor": expected["kind"], "source_parts": parts,
            "constructor_origin": "explicit_source_grammar", "guard_origin":
                "explicit_source_grammar" if expected["kind"] == "if" else None,
            "guard": deepcopy(expected["guard"]) if expected["kind"] == "if" else None,
            "atomic_semantic_slots_origin": "actual_neural_forward_inverse_source_agreement",
            "inverse_scaffolding_origin": "explicit_source_grammar",
            "all_source_characters_accounted": True, "neural_structure_prediction_claimed": False}
        for part in parts:
            if part["role"].startswith("symbolic_"):
                continue
            # Crucially, no parsed slots, synthesized terminal punctuation, or
            # normalized inverse text is ever substituted for this source slice.
            leaf = direct.prepare_rich_intent_instruction(part["text"], checkpoint,
                context=None, beam_width=selected_beam, weight_ablation=selected_ablation, project=False)
            report["neural_leaves"].append({"source_span": deepcopy(part), "inference": leaf})
            for key in _COUNT_KEYS:
                report["counts"][key] += leaf["counts"][key]
                report["phase_counts"]["neural_leaves"][key] += leaf["counts"][key]
                report["executed_here_counts"][key] += leaf["counts"][key]
            if (leaf.get("status") != "source_supported_rich_candidate" or leaf.get("source_agreement") is not True or
                    leaf.get("rich_ir") is None or leaf["rich_ir"]["ast"].get("kind") != "atom"):
                report["reason"] = "a required raw source clause lacks an accepted neural roundtrip"
                return finish()
        atoms = [row["inference"]["rich_ir"]["ast"] for row in report["neural_leaves"]]
        inverses = [row["inference"]["learned"]["normalized_text"] for row in report["neural_leaves"]]
        kind = expected["kind"]
        if kind == "if":
            guard = deepcopy(expected["guard"])
            combined = {"kind": "if", "guard": guard, "body": deepcopy(atoms[0])}
            inverse = f"if {guard['subject']} is {'not ' if guard['negated'] else ''}{guard['property']}, " + inverses[0]
        else:
            combined = {"kind": kind, "left": deepcopy(atoms[0]), "right": deepcopy(atoms[1])}
            inverse = inverses[0].removesuffix(".") + " " + kind + " " + inverses[1]
        # Full-source grammar appears only in this independent final check and
        # in the explicitly disclosed symbolic constructor/guard contribution.
        grammar.validate_ast(combined)
        if combined != expected or grammar.parse_instruction(inverse, normalized_inverse=True) != expected:
            raise ValueError("composed neural leaves or whole inverse differ from complete source")
        logic = project_rich_intent_logic(combined, instruction=instruction, context=context)
        report.update(status="source_supported_grammar_composed_candidate", source_agreement=True,
            rich_ir={"schema": "intent-rich-ir/v1", "ast": combined, "source_sha256": report["instruction_sha256"]},
            logic=logic, learned={"encoder": None, "decoder": None, "ast": combined, "normalized_text": inverse})
    except Exception as exc:
        report.update(status="fail_open_composition_error", error_type=type(exc).__name__, reason=str(exc))
    return finish()


def validate_composed_rich_intent(report, *, instruction, checkpoint=None, checkpoint_descriptor=None):
    """Numerically replay direct and atomic stages, including any cached stage."""
    if checkpoint is not None and checkpoint_descriptor is not None and checkpoint != checkpoint_descriptor:
        raise ValueError("conflicting replay checkpoint identities")
    selected = checkpoint if checkpoint is not None else checkpoint_descriptor
    if type(report) is not dict:
        raise ValueError("rich composition report required")
    if report.get("schema") == direct.SCHEMA:
        return direct.validate_rich_intent_report(report, instruction=instruction, checkpoint_descriptor=selected)
    if report.get("schema") != SCHEMA:
        raise ValueError("known rich composition report required")
    expected = prepare_composed_rich_intent(instruction, selected, context=report["context"],
        beam_width=report["beam_width"], weight_ablation=report["weight_ablation"])
    if expected.get("schema") != SCHEMA:
        raise ValueError("rich composition differs from actual neural replay")
    # Reusing a validated direct stage changes work done in this invocation,
    # not its predictions or total phase costs. Preserve only that audited flag.
    if report.get("cached_direct_stage_reused") is True:
        expected["cached_direct_stage_reused"] = True
        expected["executed_here_counts"] = dict(expected["phase_counts"]["neural_leaves"])
        expected["report_sha256"] = direct.sha(direct.wire({key: value for key, value in expected.items()
                                                            if key != "report_sha256"}))
    if direct.wire(expected) != direct.wire(report):
        raise ValueError("rich composition differs from actual neural replay")
    return report


__all__ = ["SCHEMA", "METHOD", "prepare_composed_rich_intent", "validate_composed_rich_intent"]
