"""Candidate-only inspection of preserved donor decoder output formats.

This companion binds exact supplied transports and calls existing receipt and
grammar inspectors. It does not run a model or turn seven-facet output into a
rich relational request. Capture descriptors and receipt chains are declarations
whose consistency alone does not authenticate numerical execution.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


SCHEMA = "legal-ir-decoder-output-compatibility/v1"
PROFILE = "preserved-donor-output-versus-relational-request/v1"
CAPTURE_SCHEMA = "legal-ir-decoder-capture-binding/v1"
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
MAX_CODEC_BYTES = 4 * 1024 * 1024
MAX_CAPTURE_BINDING_BYTES = 128 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_JSON_NODES = 500000
MAX_JSON_DEPTH = 96
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CAPTURE_FIELDS = {"schema", "id", "source_sha256", "control", "head", "variant", "dimension",
    "checkpoint_sha256", "model_state_sha256", "input_vector_sha256", "numerical_input_sha256",
    "receipt_sha256", "codec_sha256"}
_OUTPUT_FIELDS = {"schema", "profile", "status", "inputs", "capture_binding", "generation",
    "legacy_output", "rich_relational_compatibility", "producer_pins", "authority",
    "execution_authenticated", "training_mask", "evaluation_gold_mask", "limitations"}
FALSE_AUTHORITY = dict.fromkeys((
    "numerical_execution_authenticated", "latent_only_verified", "source_commitments_verified",
    "model_execution_verified", "decoder_accuracy_established", "teacher_qualified",
    "source_semantics_verified", "source_bound", "legal_roles_verified", "applicability_verified",
    "governing_use_verified", "independently_reviewed", "accepted", "admitted",
    "semantic_equivalence_verified", "legal_equivalence_verified", "semantic_graph_admitted",
    "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
    "model_executed", "training_executed", "backend_executed", "Lean_admitted", "proof_authority",
    "generation_declarations_are_independent_proof", "partition_membership_verified",
    "reviewed_targets_verified", "encoder_identity_verified", "rich_relational_output_verified",
), False)
_SELF_PATH = Path(__file__).absolute()
_REPO = _SELF_PATH.parents[4]
_SOURCE_RELS = (
    "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_source_generation.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/contextual_legal_ir_output.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/decoder_source_fidelity.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_formula_codec.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_grammar_decoder.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_family_evaluator.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/snapshot_evaluator.py",
    "ipfs_datasets_py/utils/cid_utils.py",
)
_OPERATION_SNAPSHOTS = None


class LegalIRDecoderOutputCompatibilityError(ValueError):
    """Original transport, codec asset, trusted source or complete bound failed."""


def _need(condition, message):
    if not condition:
        raise LegalIRDecoderOutputCompatibilityError(message)


def _is_sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _copy(value, maximum, budget=None):
    """Detach finite ordinary JSON, bounding strings before UTF8 encoding."""
    remaining = maximum
    budget = [MAX_JSON_NODES] if budget is None else budget

    def visit(item, depth):
        nonlocal remaining
        budget[0] -= 1
        _need(budget[0] >= 0 and depth <= MAX_JSON_DEPTH, "ordinary JSON node/depth bound exceeded")
        if type(item) is dict:
            _need(len(item) <= budget[0], "ordinary JSON object bound exceeded")
            remaining -= 2 + len(item)
            _need(remaining >= 0, "ordinary JSON byte bound exceeded")
            result = {}
            for key, child in item.items():
                _need(type(key) is str, "ordinary JSON string keys required")
                result[visit(key, depth + 1)] = visit(child, depth + 1)
            return result
        if type(item) is list:
            _need(len(item) <= budget[0], "ordinary JSON list bound exceeded")
            remaining -= 2 + len(item)
            _need(remaining >= 0, "ordinary JSON byte bound exceeded")
            return [visit(child, depth + 1) for child in item]
        if type(item) is str:
            _need(len(item) <= remaining, "ordinary JSON string bound exceeded")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError:
                raise LegalIRDecoderOutputCompatibilityError("valid ordinary UTF8 required") from None
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(abs(item) <= (1 << 63) - 1, "bounded ordinary integer required")
            remaining -= len(str(item))
        elif type(item) is float:
            _need(math.isfinite(item), "finite ordinary JSON required")
            remaining -= len(repr(item))
        else:
            raise LegalIRDecoderOutputCompatibilityError("ordinary finite JSON required")
        _need(remaining >= 0, "ordinary JSON byte bound exceeded")
        return item

    return visit(value, 0)


def _wire(value, maximum):
    checked = _copy(value, maximum)
    try:
        raw = json.dumps(checked, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise LegalIRDecoderOutputCompatibilityError("bounded ordinary UTF8 JSON required") from None
    _need(len(raw) <= maximum, "complete JSON byte bound exceeded; truncation refused")
    return raw


def _digest(value, maximum):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _pairs(entries):
    result = {}
    for key, value in entries:
        _need(key not in result, "duplicate outer JSON key refused")
        result[key] = value
    return result


def _transport(raw, expected, maximum, budget):
    _need(_is_sha(expected), "independent whole-transport SHA256 required")
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded original transport bytes required")
    _need(hashlib.sha256(raw).hexdigest() == expected, "independent whole-transport pin differs")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                LegalIRDecoderOutputCompatibilityError("finite outer JSON required")))
    except (ValueError, UnicodeError, RecursionError):
        raise LegalIRDecoderOutputCompatibilityError("duplicate-free finite original UTF8 JSON required") from None
    value = _copy(value, maximum, budget)
    _wire(value, maximum)
    return value


def _preflight(receipt_raw, codec_raw, capture_raw, receipt_sha, codec_sha, capture_sha):
    budget = [MAX_JSON_NODES]
    receipt = _transport(receipt_raw, receipt_sha, MAX_RECEIPT_BYTES, budget)
    codec = _transport(codec_raw, codec_sha, MAX_CODEC_BYTES, budget)
    capture = _transport(capture_raw, capture_sha, MAX_CAPTURE_BINDING_BYTES, budget)
    _need(type(receipt) is dict and type(codec) is dict, "original receipt and codec objects required")
    _need(type(capture) is dict and set(capture) == _CAPTURE_FIELDS
          and capture["schema"] == CAPTURE_SCHEMA, "closed external capture binding required")
    for name, maximum in (("id", 256), ("control", 128)):
        text = capture[name]
        _need(type(text) is str and 0 < len(text) <= maximum and bool(text.strip())
              and text.isprintable(), "bounded printable capture identity/control required")
    for name in ("source_sha256", "checkpoint_sha256", "model_state_sha256", "input_vector_sha256",
                 "numerical_input_sha256", "receipt_sha256", "codec_sha256"):
        _need(_is_sha(capture[name]), "lowercase capture SHA256 required")
    _need(type(capture["dimension"]) is int and capture["dimension"] in (8, 384, 768),
          "explicit supported capture dimension required")
    _need(type(capture["head"]) is str and type(capture["variant"]) is str,
          "explicit capture head and variant required")
    _need(capture["receipt_sha256"] == receipt_sha and capture["codec_sha256"] == codec_sha,
          "external capture transport pins differ")
    for external, internal in (("head", "head"), ("variant", "variant"), ("dimension", "input_dimension"),
            ("model_state_sha256", "model_state_sha256_before"), ("input_vector_sha256", "input_vector_sha256"),
            ("numerical_input_sha256", "numerical_input_sha256")):
        _need(type(capture[external]) is type(receipt.get(internal))
              and capture[external] == receipt.get(internal), "external capture and receipt binding differ")
    return receipt, codec, capture


def _snapshot(path):
    _need(path.is_absolute(), "absolute trusted fixed source required")
    try:
        for parent in (path.parent, *path.parent.parents):
            _need(stat.S_ISDIR(parent.lstat().st_mode), "unaliased trusted source parents required")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            before = os.fstat(stream.fileno())
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                  and 0 < before.st_size <= MAX_SOURCE_BYTES, "bounded regular trusted source required")
            raw = stream.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(stream.fileno())
        identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                                  value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
        _need(len(raw) == before.st_size and identity(before) == identity(after) == identity(path.lstat()),
              "trusted source changed during snapshot")
    except OSError:
        raise LegalIRDecoderOutputCompatibilityError("trusted fixed source snapshot refused") from None
    return hashlib.sha256(raw).hexdigest(), identity(before)


_SELF_SNAPSHOT = _snapshot(_SELF_PATH)
_SELF_PIN = _SELF_SNAPSHOT[0]


def _trusted_sources():
    global _OPERATION_SNAPSHOTS
    paths = (_SELF_PATH, *(_REPO / relative for relative in _SOURCE_RELS))
    snapshots = {str(path): _snapshot(path) for path in paths}
    _need(snapshots[str(_SELF_PATH)][0] == _SELF_PIN
          and snapshots[str(_SELF_PATH)] == _SELF_SNAPSHOT, "compatibility owner changed since import")
    if _OPERATION_SNAPSHOTS is None:
        _OPERATION_SNAPSHOTS = dict(snapshots)
    _need(snapshots == _OPERATION_SNAPSHOTS, "trusted source identity or bytes changed since first use")
    return {path: observed[0] for path, observed in snapshots.items()}, snapshots


def _owners():
    from . import gte_decoder_source_generation, contextual_legal_ir_output, decoder_source_fidelity
    from ...legal_ir import canonical_contracts
    from ....optimizers.logic_theorem_optimizer import (
        legal_formula_codec, legal_ir_grammar_decoder, legal_ir_family_evaluator, snapshot_evaluator)
    from ....utils import cid_utils
    modules = (gte_decoder_source_generation, contextual_legal_ir_output, decoder_source_fidelity,
               canonical_contracts, legal_formula_codec, legal_ir_grammar_decoder,
               legal_ir_family_evaluator, snapshot_evaluator, cid_utils)
    for module, relative in zip(modules, _SOURCE_RELS):
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == _REPO / relative,
              "fixed public owner source identity required")
    return gte_decoder_source_generation, contextual_legal_ir_output, legal_formula_codec


def prepare_legal_ir_decoder_output_compatibility_v1(receipt_raw, codec_raw, capture_binding_raw, *,
        expected_receipt_sha256, expected_codec_sha256, expected_capture_binding_sha256):
    """Inspect a declared generation receipt and only its emitted native tokens.

    Whole transports and the closed capture descriptor are checked before lazy
    public owner imports. Neither checkpoint/source bodies nor reference targets
    are read. Invalid generated grammar remains an accounted candidate outcome.
    """
    receipt, codec, capture = _preflight(receipt_raw, codec_raw, capture_binding_raw,
        expected_receipt_sha256, expected_codec_sha256, expected_capture_binding_sha256)
    originals = ((receipt, MAX_RECEIPT_BYTES), (codec, MAX_CODEC_BYTES), (capture, MAX_CAPTURE_BINDING_BYTES))
    tokens = tuple(_digest(value, bound) for value, bound in originals)
    pins, initial = _trusted_sources()

    def fence():
        _need(tuple(_digest(value, bound) for value, bound in originals) == tokens,
              "detached original compatibility inputs changed")
        current, snapshots = _trusted_sources()
        _need(current == pins and snapshots == initial, "trusted operation sources changed during inspection")

    generation_owner, lexical, legacy = _owners()
    fence()
    try:
        inspection = generation_owner.inspect_source_only_generation(receipt)
    except ValueError:
        fence()
        raise LegalIRDecoderOutputCompatibilityError("original source-only generation receipt refused") from None
    fence()
    _need(type(codec.get("target_vocabulary")) is list
          and len(codec["target_vocabulary"]) == receipt["vocabulary_size"],
          "receipt and exact supplied codec vocabulary sizes differ")
    primary = receipt["head"] == "primary384"
    # The empty public lexical inspection validates the entire codec even when
    # a generated candidate's inherited budget cannot enter that owner.
    try:
        if primary:
            lexical.inspect_contextual_legal_predictions([], codec=codec, output_limit=4)
        else:
            legacy.validate_codec(codec)
    except ValueError:
        fence()
        raise LegalIRDecoderOutputCompatibilityError("original complete native codec asset refused") from None
    fence()
    native = {"format": "typed-json-lexical/v1" if primary else "typed-deontic-rule/v1",
        "grammar_valid": False, "complete_candidate": False, "ordered_generated_ir": None,
        "canonical_contract_ir": None, "canonicalization_checked": False,
        "canonicalization_changed_payload": None, "reason_codes": [], "inspection_errors": []}
    reasons = native["reason_codes"]
    if not receipt["terminated"]:
        reasons.append("generation_incomplete")
    ids = receipt["generated_ids"]
    if primary:
        if receipt["inherited_max_target_tokens"] > 512:
            reasons.append("lexical_target_token_budget_exceeded")
        else:
            prediction = {"id": capture["id"], "token_ids": ids[1:-1] if receipt["terminated"] else ids[1:],
                "generation_status": "eos" if receipt["terminated"] else "output_limit",
                "eos_reached": receipt["terminated"]}
            try:
                observed = lexical.inspect_contextual_legal_predictions([prediction], codec=codec,
                    output_limit=receipt["inherited_max_target_tokens"])["rows"][0]
            except ValueError:
                fence()
                raise LegalIRDecoderOutputCompatibilityError("public lexical candidate inspection refused") from None
            fence()
            native.update({"grammar_valid": observed["canonical_contract_valid"],
                "complete_candidate": observed["complete_candidate"],
                "ordered_generated_ir": observed["ordered_generated_ir"],
                "canonical_contract_ir": observed["canonical_contract_ir"],
                "inspection_errors": list(observed["errors"]),
                "canonicalization_checked": observed["canonical_contract_ir"] is not None,
                "canonicalization_changed_payload": observed["canonicalization_changed_payload"]
                    if observed["canonical_contract_ir"] is not None else None})
            if observed["errors"] or not observed["canonical_contract_valid"]:
                reasons.append("lexical_generated_output_invalid")
    elif receipt["inherited_max_target_tokens"] > legacy.MAX_TARGET_TOKENS or len(ids) > legacy.MAX_TARGET_TOKENS:
        reasons.append("legacy_target_token_budget_exceeded")
    else:
        try:
            native["ordered_generated_ir"] = legacy.decode_target(codec, ids)
        except legacy.CodecError as error:
            fence()
            reasons.append("legacy_codec_rejected_generated_tokens")
            native["inspection_errors"] = [str(error)[:512]]
        else:
            fence()
            native["grammar_valid"] = True
            native["complete_candidate"] = True
    generation = {name: receipt[name] for name in (
        "variant", "head", "input_dimension", "input_vector_sha256", "numerical_input_sha256",
        "generated_ids", "generated_ids_sha256", "terminated", "truncated", "stop_reason",
        "inherited_max_target_tokens", "effective_max_new_tokens")}
    generation["model_state_sha256"] = receipt["model_state_sha256_before"]
    generation["receipt_inspection_sha256"] = _digest(inspection, MAX_RECEIPT_BYTES)
    report = {"schema": SCHEMA, "profile": PROFILE,
        "status": "candidate_output_inspected_relational_profile_unsupported",
        "inputs": {name: {"sha256": expected, "bytes": len(raw)} for name, raw, expected in (
            ("receipt", receipt_raw, expected_receipt_sha256), ("codec", codec_raw, expected_codec_sha256),
            ("capture_binding", capture_binding_raw, expected_capture_binding_sha256))},
        "capture_binding": capture, "generation": generation, "legacy_output": native,
        "rich_relational_compatibility": {"supported": False, "status": "unsupported_profile",
            "reason": "emitted_format_outside_relational_profile", "request_utf8": None, "request_sha256": None},
        "producer_pins": pins, "authority": dict(FALSE_AUTHORITY), "execution_authenticated": False,
        "training_mask": 0, "evaluation_gold_mask": 0,
        "limitations": [
            "Raw receipt, codec and external capture bytes are independently pinned; their consistency does not attest actual execution, source commitments, checkpoint contents or target withholding.",
            "Source, checkpoint and model/input hashes in the capture descriptor remain caller declarations; this adapter does not read those bodies or invent an encoder identity.",
            "Only the existing source-only receipt inspector, lexical generated-output inspector and full tagged legacy codec are used; no model, encoder, training or numerical API is invoked.",
            "Generated IDs include original BOS and emitted EOS; interior special tokens, truncation and invalid grammar are preserved without repair or a source/reference fallback.",
            "Lexical ordered IR and the separately computed canonical contract IR preserve any canonicalization change; tagged legacy success uses full stored codec policy without fitting a replacement.",
            "Native format conformance is separate from the unsupported rich relational request profile: no TypedExpression, predicate signature, ordered role declaration, relational request or batch encoder binding is manufactured.",
            "This is a candidate-only companion, not a selected-population accuracy evaluator, independently reviewed legal reference, source-equivalence proof, training admission or Lean build.",
            "Fixed file snapshots do not generally prove executed bytecode for preloaded unanchored modules; a qualified fresh checked-buffer native run supplies a separate execution context.",
            "Input scope is duplicate-free finite UTF8 JSON; arbitrary nonUTF8 model byte streams and complete-bound overflows refuse intake rather than being repaired or truncated.",
        ]}
    raw = _wire(report, MAX_OUTPUT_BYTES)
    fence()
    return json.loads(raw)


def legal_ir_decoder_output_compatibility_sha256(report):
    """Hash the complete bounded companion; a self-address grants no authority."""
    detached = _copy(report, MAX_OUTPUT_BYTES)
    _need(type(detached) is dict and set(detached) == _OUTPUT_FIELDS
          and detached["schema"] == SCHEMA and detached["profile"] == PROFILE,
          "complete closed decoder output compatibility report required")
    return _digest(detached, MAX_OUTPUT_BYTES)


def validate_legal_ir_decoder_output_compatibility_v1(report, receipt_raw, codec_raw, capture_binding_raw, *,
        expected_report_sha256, expected_receipt_sha256, expected_codec_sha256, expected_capture_binding_sha256):
    """Require the independent full output pin and regenerate from original bytes."""
    _need(_is_sha(expected_report_sha256), "independent complete compatibility SHA256 required")
    offered = _copy(report, MAX_OUTPUT_BYTES)
    _need(legal_ir_decoder_output_compatibility_sha256(offered) == expected_report_sha256,
          "independent complete compatibility pin differs")
    original = _wire(offered, MAX_OUTPUT_BYTES)
    regenerated = prepare_legal_ir_decoder_output_compatibility_v1(receipt_raw, codec_raw, capture_binding_raw,
        expected_receipt_sha256=expected_receipt_sha256, expected_codec_sha256=expected_codec_sha256,
        expected_capture_binding_sha256=expected_capture_binding_sha256)
    _need(original == _wire(regenerated, MAX_OUTPUT_BYTES), "compatibility differs from full original-bound regeneration")
    return regenerated


__all__ = ["LegalIRDecoderOutputCompatibilityError", "prepare_legal_ir_decoder_output_compatibility_v1",
    "legal_ir_decoder_output_compatibility_sha256", "validate_legal_ir_decoder_output_compatibility_v1"]
