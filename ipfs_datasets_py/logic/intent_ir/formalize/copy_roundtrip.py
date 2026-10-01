"""Learned single-clause IntentIR candidates with source-token copying.

This additive adapter keeps the old lexical codec and its checkpoints intact.
Copy addressability is a numerical capability, never evidence of understanding.
Neither source instructions nor expected targets enter the inverse decoder.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re

from . import roundtrip
from .roundtrip import (AUTHORITY, _raw, _sha, _SHA, frame_to_sequence,
    sequence_to_frame, frame_to_intent_ir, intent_ir_to_frame, normalized_text_to_frame)

SCHEMA = "intent-instruction-copy-roundtrip/v1"
CHECKPOINT_SCHEMA = "intent-copy-roundtrip-checkpoint/v1"
PACKAGE_SCHEMA = "intent-copy-roundtrip-package/v1"
SCOPE = list(roundtrip.SCOPE) + [
    "learned_source_token_copying_does_not_establish_semantic_correctness",
    "open_vocabulary_addressability_with_unchanged_single_clause_codec_bounds",
]
MAX_REPORT_BYTES = 262_144


def _adapter_sha256():
    from . import extended_projections, projection_request
    pins = {__name__: _sha(Path(__file__).read_bytes()),
            "frozen_roundtrip_adapter": roundtrip._adapter_sha256(),
            **extended_projections.projection_producer_pins(),
            projection_request.__name__: _sha(Path(projection_request.__file__).read_bytes())}
    return _sha(_raw(pins))


def register_intent_copy_checkpoint(backend_descriptor, *, output, corpus_sha256):
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_copy import load_paired_copy
    load_paired_copy(backend_descriptor)
    output = Path(output).resolve(strict=True)
    backend_path = Path(backend_descriptor["path"]).resolve(strict=True)
    relative = backend_path.relative_to(output).as_posix()
    if type(corpus_sha256) is not str or not _SHA.fullmatch(corpus_sha256):
        raise ValueError("training corpus digest required")
    manifest = {"schema": PACKAGE_SCHEMA,
        "backend": {"schema": backend_descriptor["schema"], "file": relative,
                    "sha256": backend_descriptor["sha256"]},
        "adapter_sha256": _adapter_sha256(), "corpus_sha256": corpus_sha256,
        "scope": list(SCOPE), **AUTHORITY}
    path = output / "manifest.json"
    with path.open("xb") as stream:
        stream.write(_raw(manifest))
    descriptor = {"schema": CHECKPOINT_SCHEMA, "path": str(path), "sha256": _sha(path.read_bytes())}
    load_intent_copy_checkpoint(descriptor)
    return descriptor


def load_intent_copy_checkpoint(descriptor):
    """Load only a hash-bound inert package colocated with its copied weights."""
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_copy import load_paired_copy, SCHEMA as BACKEND_SCHEMA
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_text import _read, _json
    if (type(descriptor) is not dict or set(descriptor) != {"schema", "path", "sha256"}
            or descriptor["schema"] != CHECKPOINT_SCHEMA or type(descriptor["path"]) is not str
            or type(descriptor["sha256"]) is not str or not _SHA.fullmatch(descriptor["sha256"])):
        raise ValueError("closed Intent copy checkpoint descriptor required")
    path = Path(descriptor["path"])
    raw = _read(path, 65536)
    if _sha(raw) != descriptor["sha256"]:
        raise ValueError("Intent copy manifest digest differs")
    manifest = _json(raw)
    if (type(manifest) is not dict or set(manifest) != {
            "schema", "backend", "adapter_sha256", "corpus_sha256", "scope", *AUTHORITY}
            or manifest["schema"] != PACKAGE_SCHEMA or manifest["scope"] != SCOPE
            or type(manifest["corpus_sha256"]) is not str or not _SHA.fullmatch(manifest["corpus_sha256"])
            or any(type(manifest[k]) is not type(v) or manifest[k] != v for k, v in AUTHORITY.items())
            or manifest["adapter_sha256"] != _adapter_sha256()):
        raise ValueError("Intent copy manifest or installed adapter differs")
    backend = manifest["backend"]
    if (type(backend) is not dict or set(backend) != {"schema", "file", "sha256"}
            or backend["schema"] != BACKEND_SCHEMA or type(backend["file"]) is not str):
        raise ValueError("closed colocated copy backend descriptor required")
    relative = PurePosixPath(backend["file"])
    if (not relative.parts or relative.is_absolute() or any(p in (".", "..") for p in relative.parts)
            or relative.as_posix() != backend["file"]):
        raise ValueError("copy backend must remain inside its package")
    backend_path = path.parent / relative
    if backend_path.resolve(strict=True) != backend_path:
        raise ValueError("copy backend path must be canonical without symlinks")
    backend_descriptor = {"schema": backend["schema"], "path": str(backend_path), "sha256": backend["sha256"]}
    return {"manifest": manifest, "descriptor": dict(descriptor),
            "backend_descriptor": backend_descriptor, "backend": load_paired_copy(backend_descriptor)}


def generation_usable(report):
    """Unknown tokens may be addressed by copying; invalid predictions abstain."""
    return (report.get("status") == "generated" and report.get("ended") is True
            and report.get("input_coverage_complete") is True
            and report.get("uncovered_input_tokens") == []
            and "<unk>" not in report.get("tokens", []))


def decode_copy_intent_text(checkpoint_descriptor, document, *, weight_ablation=None):
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_copy import infer_paired_copy
    loaded = load_intent_copy_checkpoint(checkpoint_descriptor)
    return infer_paired_copy(loaded["backend_descriptor"], frame_to_sequence(intent_ir_to_frame(document)),
                            "decode", max_new_tokens=96, weight_ablation=weight_ablation)


def _base(instruction, checkpoint_descriptor):
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_copy import infer_paired_copy
    from ...formalization.autoencoder.domain_targets import prepare_intent_targets
    if type(instruction) is not str:
        raise ValueError("exact original instruction string required")
    raw = instruction.encode()
    report = {"schema": SCHEMA, "status": "fail_open_no_checkpoint",
        "instruction_sha256": _sha(raw), "instruction_bytes": len(raw), "checkpoint_sha256": None,
        "learned": {"encoder": None, "decoder": None, "frame": None, "normalized_text": None},
        "candidate_intent_ir": None, "projections": None, "gaps": list(SCOPE),
        "extended_projections": None, "extension_status": "not_applicable", "projection_request": None,
        "continue_planning": True, "raw_instruction_preserved": True,
        "training_steps": 0, "provider_calls": 0, "download_calls": 0, **AUTHORITY}
    if not instruction.strip() or len(instruction) > 4096 or len(instruction.split()) > 48:
        report["status"] = "fail_open_input_out_of_scope"
        return report
    if checkpoint_descriptor is None:
        return report
    try:
        loaded = load_intent_copy_checkpoint(checkpoint_descriptor)
        report["checkpoint_sha256"] = checkpoint_descriptor["sha256"]
        encoded = infer_paired_copy(loaded["backend_descriptor"], " ".join(instruction.lower().split()),
                                    "encode", max_new_tokens=96)
        report["learned"]["encoder"] = encoded
        if not generation_usable(encoded):
            report["status"] = "fail_open_encoder_generation"
            return report
        frame = sequence_to_frame(encoded["generated_text"])
        report["learned"]["frame"] = frame
        candidate = frame_to_intent_ir(frame, instruction=instruction)
        decoded = infer_paired_copy(loaded["backend_descriptor"],
            frame_to_sequence(intent_ir_to_frame(candidate)), "decode", max_new_tokens=96)
        report["learned"]["decoder"] = decoded
        if not generation_usable(decoded):
            report["status"] = "fail_open_decoder_generation"
            return report
        text = roundtrip._join_word_tokens(re.sub(r"\s+([.,!?])", r"\1", decoded["generated_text"]).strip())
        report["learned"]["normalized_text"] = text
        if normalized_text_to_frame(text) != frame:
            report["status"] = "fail_open_reconstruction_mismatch"
            return report
        report["candidate_intent_ir"] = candidate.to_dict()
        report["projections"] = prepare_intent_targets(candidate).to_dict()
        report["status"] = "semantic_candidate_advice"
    except Exception as exc:
        report["candidate_intent_ir"] = report["projections"] = None
        report["status"] = "fail_open_checkpoint_or_decode_error"
        report["gaps"].append("error_category:" + type(exc).__name__)
    return report


def _finish(report):
    report["report_sha256"] = _sha(_raw(report))
    return report


def prepare_copy_intent_instruction(instruction, checkpoint_descriptor=None, *, projection_request=None):
    """Generate optional advisory IR; preserve the original instruction on failure."""
    report = _base(instruction, checkpoint_descriptor)
    if report["status"] == "semantic_candidate_advice":
        try:
            from .extended_projections import project_intent_families
            options = {}
            if projection_request is not None:
                from .projection_request import validate_intent_projection_request
                report["projection_request"] = validate_intent_projection_request(projection_request,
                    instruction=instruction, document=report["candidate_intent_ir"],
                    checkpoint_sha256=report["checkpoint_sha256"])
                options = {"context": projection_request["context"],
                           "requested_families": projection_request["requested_families"]}
            report["extended_projections"] = project_intent_families(report["candidate_intent_ir"], **options)
            report["extension_status"] = "projected_with_explicit_frontiers"
            if len(_raw({**report, "report_sha256": "0" * 64})) > MAX_REPORT_BYTES:
                raise ValueError("copy projection report exceeds its byte budget")
        except Exception as exc:
            report["extended_projections"] = None
            report["extension_status"] = "fail_open_projection_error"
            report["gaps"].append("extended_projection_error_category:" + type(exc).__name__)
    return _finish(report)


def validate_copy_intent_report(report, *, instruction, checkpoint_descriptor=None):
    """Replay installed numerical inference and native compilation from source."""
    if type(report) is not dict or report.get("schema") != SCHEMA:
        raise ValueError("Intent copy report required")
    if report.get("extension_status") == "fail_open_projection_error":
        base = _base(instruction, checkpoint_descriptor)
        gaps = report.get("gaps")
        if (base["status"] != "semantic_candidate_advice" or type(gaps) is not list
                or len(gaps) != len(base["gaps"]) + 1 or type(gaps[-1]) is not str
                or not re.fullmatch(r"extended_projection_error_category:[A-Za-z_][A-Za-z0-9_]{0,127}", gaps[-1])):
            raise ValueError("failed copy extension requires independently replayable base advice")
        if report.get("projection_request") is not None:
            from .projection_request import validate_intent_projection_request
            base["projection_request"] = validate_intent_projection_request(report["projection_request"],
                instruction=instruction, document=base["candidate_intent_ir"],
                checkpoint_sha256=base["checkpoint_sha256"])
        base["extension_status"] = "fail_open_projection_error"
        base["gaps"].append(gaps[-1])
        expected = _finish(base)
    else:
        expected = prepare_copy_intent_instruction(instruction, checkpoint_descriptor,
                                                  projection_request=report.get("projection_request"))
    if _raw(report) != _raw(expected):
        raise ValueError("Intent copy report differs from numerical/source/projection replay")
    return report
