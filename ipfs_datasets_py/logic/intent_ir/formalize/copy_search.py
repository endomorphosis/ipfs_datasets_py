"""Optional learned search recovery with independent source and inverse checks."""
from __future__ import annotations

import re

from . import copy_roundtrip, roundtrip


def prepare_copy_intent_search(instruction, checkpoint_descriptor, *, beam_width=8):
    """Search learned alternatives; never synthesize missing semantic slots.

    Both directions consume the original frozen checkpoint. Source agreement
    filters complete generated frames after inference. The inverse receives
    only the predicted frame, never the source instruction or expected labels.
    """
    from .document_roundtrip import assess_frame_source_agreement
    from .instruction_scope import assess_intent_instruction_scope
    from .extended_projections import project_intent_families
    from ...formalization.autoencoder.domain_targets import prepare_intent_targets
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_search import infer_paired_copy_beam

    report = {"schema": "intent-instruction-beam-roundtrip/v1",
        "status": "fail_open_search_no_supported_candidate",
        "instruction_sha256": roundtrip._sha(instruction.encode()),
        "instruction_bytes": len(instruction.encode()), "checkpoint_sha256": None,
        "learned": {"encoder": None, "decoder": None, "frame": None, "normalized_text": None},
        "encoder_search": None, "decoder_searches": [], "source_agreement": None,
        "candidate_intent_ir": None, "projections": None, "extended_projections": None,
        "continue_planning": True, "raw_instruction_preserved": True,
        "training_steps": 0, "provider_calls": 0, "download_calls": 0,
        "source_semantics_verified": False, **roundtrip.AUTHORITY}
    if not assess_intent_instruction_scope(instruction)["eligible_for_inference"]:
        report["status"] = "fail_open_input_out_of_scope"
        return copy_roundtrip._finish(report)
    if checkpoint_descriptor is None:
        report["status"] = "fail_open_no_checkpoint"
        return copy_roundtrip._finish(report)
    try:
        loaded = copy_roundtrip.load_intent_copy_checkpoint(checkpoint_descriptor)
        report["checkpoint_sha256"] = checkpoint_descriptor["sha256"]
        backend = loaded["backend_descriptor"]
        enc = infer_paired_copy_beam(backend, " ".join(instruction.lower().split()), "encode",
                                     beam_width=beam_width)
        report["encoder_search"] = enc
        for candidate_row in enc["rows"]:
            if not copy_roundtrip.generation_usable(candidate_row):
                continue
            try:
                frame = roundtrip.sequence_to_frame(candidate_row["generated_text"])
            except ValueError:
                continue
            agreement = assess_frame_source_agreement(instruction, frame)
            if not agreement["matched"]:
                continue
            candidate = roundtrip.frame_to_intent_ir(frame, instruction=instruction)
            dec = infer_paired_copy_beam(backend, roundtrip.frame_to_sequence(frame), "decode",
                                         beam_width=beam_width)
            report["decoder_searches"].append(dec)
            for inverse_row in dec["rows"]:
                if not copy_roundtrip.generation_usable(inverse_row):
                    continue
                text = roundtrip._join_word_tokens(re.sub(r"\s+([.,!?])", r"\1",
                                                          inverse_row["generated_text"]).strip())
                try:
                    if roundtrip.normalized_text_to_frame(text) != frame:
                        continue
                except ValueError:
                    continue
                report.update(status="semantic_candidate_advice",
                    candidate_intent_ir=candidate.to_dict(), source_agreement=agreement,
                    projections=prepare_intent_targets(candidate).to_dict(),
                    extended_projections=project_intent_families(candidate.to_dict()))
                report["learned"] = {"encoder": candidate_row, "decoder": inverse_row,
                                    "frame": frame, "normalized_text": text}
                return copy_roundtrip._finish(report)
    except Exception as exc:
        report["status"] = "fail_open_checkpoint_or_search_error"
        report["error_category"] = type(exc).__name__
    return copy_roundtrip._finish(report)
