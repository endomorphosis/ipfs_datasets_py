"""Bounded learned instruction <-> IntentIR candidates using a shared backend.

Semantic slots come from autoregressive model predictions, never from a source
parser or a training-example lookup. The codec only validates those slots and
adds native identifiers/provenance. Native compilation is deterministic; neither
successful reconstruction nor compilation proves that the input was understood.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re

SCHEMA = "intent-instruction-roundtrip/v1"
CHECKPOINT_SCHEMA = "intent-roundtrip-checkpoint/v1"
PACKAGE_SCHEMA = "intent-roundtrip-package/v1"
FRAME_KEYS = ("actor", "action", "object", "modality")
MODALS = {"intended": "intends to", "required": "must", "prohibited": "must not",
          "permitted": "may", "recommended": "should"}
AUTHORITY = {"authority": "unverified_candidate_only", "proof_authority": False,
             "execution_authority": False, "completion_authority": False,
             "omission_authority": False, "combination_semantics_verified": False}
SCOPE = ["single_clause_actor_action_object_modality",
         "lowercase_controlled_english_development_model",
         "no_conditions_quantifiers_workflow_or_case_sensitive_code_identifiers",
         "weak_source_and_authored_supervision_not_reviewed_semantic_gold",
         "source_semantics_unverified_and_cross_domain_proofs_not_run"]
_WORDS = re.compile(r"[a-z][a-z0-9_-]*(?: [a-z][a-z0-9_-]*)*\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_frame(frame):
    """The first codec is deliberately closed; unsupported meaning is rejected."""
    if type(frame) is not dict or set(frame) != set(FRAME_KEYS):
        raise ValueError("exact Intent roundtrip frame required")
    for key, bound in (("actor", 4), ("action", 1), ("object", 12)):
        value = frame[key]
        if (type(value) is not str or len(value) > 160 or not _WORDS.fullmatch(value)
                or len(value.split()) > bound):
            raise ValueError("unsupported Intent roundtrip slot")
    if type(frame["modality"]) is not str or frame["modality"] not in MODALS:
        raise ValueError("unsupported Intent roundtrip modality")
    return dict(frame)


def frame_to_sequence(frame):
    frame = validate_frame(frame)
    return " ".join(f"<{key}> {frame[key]}" for key in FRAME_KEYS)


def sequence_to_frame(text):
    if type(text) is not str or len(text) > 1024:
        raise ValueError("bounded predicted semantic sequence required")
    match = re.fullmatch(r"\s*<actor>\s+([^<>]+?)\s+<action>\s+([^<>]+?)\s+"
                         r"<object>\s+([^<>]+?)\s+<modality>\s+([^<>]+?)\s*", text)
    if not match:
        raise ValueError("predicted semantic sequence has invalid slot boundaries")
    return validate_frame({key: _join_word_tokens(" ".join(value.split()))
                           for key, value in zip(FRAME_KEYS, match.groups())})


def _join_word_tokens(text):
    # The shared tokenizer emits word-internal hyphens as separate tokens.
    # In this codec only word-internal hyphens are legal (no arithmetic), so
    # rejoining them is presentation decoding, not semantic slot prediction.
    return re.sub(r"(?<=[a-z0-9_])\s*-\s*(?=[a-z0-9_])", "-", text)


def canonical_frame_text(frame):
    """Training/evaluation target and IR label, not the learned inverse output."""
    frame = validate_frame(frame)
    return f"{frame['actor']} {MODALS[frame['modality']]} {frame['action']} {frame['object']}."


def normalized_text_to_frame(text):
    """Check the neural inverse's controlled grammar; never parse model inputs."""
    if type(text) is not str or len(text) > 1024:
        raise ValueError("bounded inverse text required")
    match = re.fullmatch(r"([a-z][a-z0-9_ -]*?) (must not|intends to|must|may|should) "
                         r"([a-z][a-z0-9_-]*) ([a-z][a-z0-9_ -]*?)\s*\.", _join_word_tokens(text.strip()))
    if not match:
        raise ValueError("inverse text is outside the controlled grammar")
    actor, modal, action, obj = match.groups()
    return validate_frame({"actor": " ".join(actor.split()), "action": action,
                           "object": " ".join(obj.split()),
                           "modality": {v: k for k, v in MODALS.items()}[modal]})


def frame_to_intent_ir(frame, *, instruction):
    """Materialize native IR from predicted slots, with explicitly inferred nodes."""
    from ..schema import (IntentIRDocument, IntentKind, IntentStatement, StatementKind,
                          IntentModality, IntentAction, SourceRef, SourceSpan,
                          NodeGrounding, ReviewStatus)
    from ..decoder import decode_intent_ir

    frame = validate_frame(frame)
    if type(instruction) is not str or not instruction.strip() or len(instruction) > 65536:
        raise ValueError("bounded original instruction required for source binding")
    digest = _sha(instruction.encode())
    source = SourceRef(ref_id="source", source_uri="instruction:learned-intent-roundtrip",
                       source_id=digest, source_revision=digest, content_sha256=digest,
                       review_status=ReviewStatus.MACHINE_EXTRACTED,
                       span=SourceSpan(0, len(instruction)))
    statement = IntentStatement(statement_id="goal", kind=StatementKind.GOAL,
        modality=IntentModality(frame["modality"]), normalized_text=canonical_frame_text(frame),
        source_ref_ids=("source",), predicate=frame["action"],
        arguments=(frame["actor"], frame["object"]), confidence=0.0,
        review_status=ReviewStatus.MACHINE_EXTRACTED, grounding=NodeGrounding.INFERRED)
    action = IntentAction(action_id="action", actor=frame["actor"], verb=frame["action"],
        object_refs=(frame["object"],), source_ref_ids=("source",), grounding=NodeGrounding.INFERRED)
    document = IntentIRDocument(document_id="intent-roundtrip:" + digest,
        title="Learned single-clause intent candidate", intent_kind=IntentKind.DECLARATIVE,
        sources=(source,), statements=(statement,), actions=(action,),
        entry_action_ids=("action",), terminal_action_ids=("action",), tags=("learned-candidate",))
    document.validate()
    return decode_intent_ir(document.to_dict())


def intent_ir_to_frame(document):
    """Accept only the supported native subset; never silently drop constraints."""
    from ..schema import IntentIRDocument, StatementKind, IntentKind, NodeGrounding
    from ..decoder import decode_intent_ir
    if type(document) is dict:
        document = decode_intent_ir(document)
    if not isinstance(document, IntentIRDocument):
        raise ValueError("native Intent IR required")
    document.validate()
    if (len(document.statements) != 1 or len(document.actions) != 1 or document.control_edges
            or document.intent_kind is not IntentKind.DECLARATIVE):
        raise ValueError("IR contains semantics outside the learned single-clause codec")
    statement, action = document.statements[0], document.actions[0]
    if (statement.kind is not StatementKind.GOAL or len(statement.arguments) != 2
            or len(action.object_refs) != 1
            or any(getattr(action, key) for key in ("tool_refs", "input_refs", "output_refs",
                "precondition_ids", "effect_ids", "verification_ids"))
            or document.entry_action_ids != (action.action_id,)
            or document.terminal_action_ids != (action.action_id,)
            or statement.grounding is not NodeGrounding.INFERRED
            or action.grounding is not NodeGrounding.INFERRED):
        raise ValueError("IR has unsupported action constraints or grounding")
    frame = validate_frame({"actor": action.actor, "action": action.verb,
        "object": action.object_refs[0], "modality": statement.modality.value})
    if (statement.predicate != frame["action"]
            or statement.arguments != (frame["actor"], frame["object"])
            or statement.normalized_text != canonical_frame_text(frame)):
        raise ValueError("native statement/action semantic fields disagree")
    return frame


def _adapter_sha256():
    from .. import schema, decoder, canonicalize
    from . import compiler, decompiler, typed_compiler
    from ...formalization.autoencoder import domain_targets
    modules = (schema, decoder, canonicalize, compiler, decompiler, typed_compiler, domain_targets)
    pins = {m.__name__: _sha(Path(m.__file__).read_bytes()) for m in modules}
    pins[__name__] = _sha(Path(__file__).read_bytes())
    return _sha(_raw(pins))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate checkpoint key")
        result[key] = value
    return result


def register_intent_roundtrip_checkpoint(backend_descriptor, *, output, corpus_sha256):
    """Bind a shared paired model to this codec, without copying domain weights."""
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_text import load_paired_text
    load_paired_text(backend_descriptor)
    output = Path(output).resolve()
    backend_path = Path(backend_descriptor["path"]).resolve()
    relative = backend_path.relative_to(output).as_posix()
    if not _SHA.fullmatch(corpus_sha256):
        raise ValueError("training corpus digest required")
    manifest = {"schema": PACKAGE_SCHEMA, "backend": {"schema": backend_descriptor["schema"],
        "file": relative, "sha256": backend_descriptor["sha256"]},
        "adapter_sha256": _adapter_sha256(), "corpus_sha256": corpus_sha256,
        "scope": list(SCOPE), **AUTHORITY}
    path = output / "manifest.json"
    with path.open("xb") as stream:
        stream.write(_raw(manifest))
    return {"schema": CHECKPOINT_SCHEMA, "path": str(path), "sha256": _sha(path.read_bytes())}


def load_intent_roundtrip_checkpoint(descriptor):
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_text import load_paired_text
    if (type(descriptor) is not dict or set(descriptor) != {"schema", "path", "sha256"}
            or descriptor["schema"] != CHECKPOINT_SCHEMA or type(descriptor["path"]) is not str
            or type(descriptor["sha256"]) is not str or not _SHA.fullmatch(descriptor["sha256"])):
        raise ValueError("closed Intent roundtrip descriptor required")
    path = Path(descriptor["path"])
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("absolute regular manifest file required")
    with path.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536 or _sha(raw) != descriptor["sha256"]:
        raise ValueError("Intent roundtrip manifest digest/bound differs")
    manifest = json.loads(raw, object_pairs_hook=_unique)
    if (type(manifest) is not dict or set(manifest) != {
            "schema", "backend", "adapter_sha256", "corpus_sha256", "scope", *AUTHORITY}
            or manifest["schema"] != PACKAGE_SCHEMA or manifest["scope"] != SCOPE
            or type(manifest["corpus_sha256"]) is not str or not _SHA.fullmatch(manifest["corpus_sha256"])
            or any(type(manifest[k]) is not type(v) or manifest[k] != v for k, v in AUTHORITY.items())):
        raise ValueError("Intent roundtrip manifest contract differs")
    if manifest["adapter_sha256"] != _adapter_sha256():
        raise ValueError("Intent roundtrip adapter source differs")
    backend = manifest["backend"]
    if type(backend) is not dict or set(backend) != {"schema", "file", "sha256"} or type(backend["file"]) is not str:
        raise ValueError("closed colocated backend descriptor required")
    relative = PurePosixPath(backend["file"])
    if relative.is_absolute() or any(part in (".", "..") for part in relative.parts) or str(relative) != backend["file"]:
        raise ValueError("backend must remain inside its package")
    backend_path = path.parent / relative
    if backend_path.resolve().parent != backend_path.parent.resolve() or not backend_path.resolve().is_relative_to(path.parent.resolve()):
        raise ValueError("backend package path escaped")
    for parent in [backend_path, *list(backend_path.parents)[:len(relative.parts) - 1]]:
        if parent.is_symlink():
            raise ValueError("backend package symlink is not allowed")
    backend_descriptor = {"schema": backend["schema"], "path": str(backend_path), "sha256": backend["sha256"]}
    return {"manifest": manifest, "descriptor": dict(descriptor),
            "backend_descriptor": backend_descriptor, "backend": load_paired_text(backend_descriptor)}


def decode_intent_text(checkpoint_descriptor, document, *, weight_ablation=None):
    """Learned inverse takes only typed IR. Original instruction is not an input."""
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_text import infer_paired_text
    loaded = load_intent_roundtrip_checkpoint(checkpoint_descriptor)
    return infer_paired_text(loaded["backend_descriptor"], frame_to_sequence(intent_ir_to_frame(document)),
                            "decode", max_new_tokens=96, weight_ablation=weight_ablation)


def _finish(report):
    report["report_sha256"] = _sha(_raw(report))
    return report


def prepare_roundtrip_intent_instruction(instruction, checkpoint_descriptor=None):
    """Optional local inference; failures preserve the full original planner input."""
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_text import infer_paired_text
    from ...formalization.autoencoder.domain_targets import prepare_intent_targets
    if type(instruction) is not str:
        raise ValueError("exact original instruction string required")
    raw = instruction.encode()
    report = {"schema": SCHEMA, "status": "fail_open_no_checkpoint",
        "instruction_sha256": _sha(raw), "instruction_bytes": len(raw), "checkpoint_sha256": None,
        "learned": {"encoder": None, "decoder": None, "frame": None, "normalized_text": None},
        "candidate_intent_ir": None, "projections": None, "gaps": list(SCOPE),
        "continue_planning": True, "raw_instruction_preserved": True,
        "training_steps": 0, "provider_calls": 0, "download_calls": 0, **AUTHORITY}
    if not instruction.strip() or len(instruction) > 4096 or len(instruction.split()) > 48:
        report["status"] = "fail_open_input_out_of_scope"
        return _finish(report)
    if checkpoint_descriptor is None:
        return _finish(report)
    try:
        loaded = load_intent_roundtrip_checkpoint(checkpoint_descriptor)
        report["checkpoint_sha256"] = checkpoint_descriptor["sha256"]
        # This codec is explicitly lower-case controlled English, not a code
        # identifier parser. Exact original bytes stay in the source binding.
        source = " ".join(instruction.lower().split())
        encoded = infer_paired_text(loaded["backend_descriptor"], source, "encode", max_new_tokens=96)
        report["learned"]["encoder"] = encoded
        if not _generation_usable(encoded):
            report["status"] = "fail_open_encoder_generation"
            return _finish(report)
        frame = sequence_to_frame(encoded["generated_text"])
        report["learned"]["frame"] = frame
        candidate = frame_to_intent_ir(frame, instruction=instruction)
        # Do not feed the original instruction into the inverse decoder.
        decoded = infer_paired_text(loaded["backend_descriptor"],
            frame_to_sequence(intent_ir_to_frame(candidate)), "decode", max_new_tokens=96)
        report["learned"]["decoder"] = decoded
        if not _generation_usable(decoded):
            report["status"] = "fail_open_decoder_generation"
            return _finish(report)
        text = _join_word_tokens(re.sub(r"\s+([.,!?])", r"\1", decoded["generated_text"]).strip())
        report["learned"]["normalized_text"] = text
        if normalized_text_to_frame(text) != frame:
            report["status"] = "fail_open_reconstruction_mismatch"
            return _finish(report)
        report["candidate_intent_ir"] = candidate.to_dict()
        report["projections"] = prepare_intent_targets(candidate).to_dict()
        report["status"] = "semantic_candidate_advice"
    except Exception as exc:
        # Optional advice never authorizes execution or swallows cancellation.
        report["candidate_intent_ir"] = None
        report["projections"] = None
        report["status"] = "fail_open_checkpoint_or_decode_error"
        report["gaps"].append("error_category:" + type(exc).__name__)
    return _finish(report)


def _generation_usable(report):
    """Filled against the shared backend's explicit status/coverage contract."""
    return (report.get("status") == "generated" and report.get("ended") is True
            and not report.get("input_oov_tokens") and "<unk>" not in report.get("tokens", []))


def validate_roundtrip_intent_report(report, *, instruction, checkpoint_descriptor=None):
    """Replay real weights and native compilation, not merely a self-signed hash."""
    if type(report) is not dict:
        raise ValueError("Intent roundtrip report required")
    expected = prepare_roundtrip_intent_instruction(instruction, checkpoint_descriptor)
    if _raw(report) != _raw(expected):
        raise ValueError("Intent roundtrip report differs from frozen numerical/source replay")
    return report
