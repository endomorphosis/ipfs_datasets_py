"""Finite lexical transport and prefix choices for three authored FOL targets.

Typed construction, elaboration, projection, JSON bounds and FOL replay retain
their existing owners. This adapter adds no numerical model or general grammar.
Decoding and prefix inspection take no reference target or caller-selected cap.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

PROFILE = "authored-one-to-three-many-sorted-compact/v2"
CONTENT_SCHEMA = "legal-counted-threshold-content/v2"
CODEC_SCHEMA = "legal-counted-threshold-token-codec/v2"
ENCODING_SCHEMA = "legal-counted-threshold-token-encoding/v2"
CANDIDATE_SCHEMA = "legal-counted-threshold-token-candidate/v2"
PREFIX_SCHEMA = "legal-counted-threshold-prefix-inspection/v2"
_SELF_PATH = Path(__file__).absolute()
_SELF_PIN = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_FACTORY_NAME = "ipfs_datasets_py.logic.autoformal.legal_counted_frame_threshold_v2"
_FACTORY_SHA = "9e3c4e42d8cfb5ed851461f6cd2562a71c7d5a2c2b8ccd5ab4fdbcf06e168024"
_CONTEXT_SHA = "50424a78f7bd5b489de16fe1f4eb4ec38fb7d853b48d1b3b358429dc657ecb85"
_LIMITATIONS = [
    "The closed language has three explicitly authored limits, not arbitrary formulas or reviewed statutory examples.",
    "The common cap-free signature context is unreviewed syntactic information, not an independently permitted inference input.",
    "Prefix choices cover all matching forms; syntax validity and a branch choice do not demonstrate source-dependent learning.",
    "The old counted codec and all checkpoints retain their own identities; equal vocabulary width supplies no compatibility.",
    "No source encoder, numerical runtime, generation loop, trainer, legal interpretation, graph admission or Lean build is supplied.",
]


def _need(value, message):
    if not value:
        raise ValueError(message)


def _modules():
    factory = importlib.import_module(_FACTORY_NAME)
    path = _SELF_PATH.with_name("legal_counted_frame_threshold_v2.py")
    _need(type(getattr(factory, "__file__", None)) is str
          and Path(factory.__file__).absolute() == path,
          "canonical threshold factory required")
    _need(hashlib.sha256(path.read_bytes()).hexdigest() == _FACTORY_SHA,
          "threshold factory source generation differs")
    _need(hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest() == _SELF_PIN,
          "threshold codec producer changed since import")
    base = factory._base()
    return factory, base


def _hash(base, value):
    return hashlib.sha256(base._compact_wire(value)).hexdigest()


def _fixed_codec(base):
    codec = base.build_counted_frame_token_codec_v1()
    old_literal = json.dumps(base.COMPACT_CONTENT_SCHEMA, ensure_ascii=False)
    new_literal = json.dumps(CONTENT_SCHEMA, ensure_ascii=False)
    lexical = [new_literal if token == old_literal else token for token in codec["vocabulary"][3:]]
    codec.update(schema=CODEC_SCHEMA, profile=PROFILE,
        format="finite-json-lexical-counted-threshold-content/v2",
        content_schema=CONTENT_SCHEMA, context_schema="legal-counted-frame-signature-context/v2",
        vocabulary=["<pad>", "<bos>", "<eos>", *sorted(lexical)],
        admissible_maxima=[1, 2, 3], admissible_content_count=3, signature_context_cap_free=True,
        signature_context_sha256=_CONTEXT_SHA,
        implementation=dict(codec_owner_sha256=_SELF_PIN, threshold_factory_sha256=_FACTORY_SHA,
                            fixed_counted_owner_sha256=base._SELF_PIN))
    _need(len(codec["vocabulary"]) == len(set(codec["vocabulary"])) == 28,
          "exact distinct threshold28 vocabulary required")
    return codec


def _watch(base, original, observed):
    copied = base._compact_capture(original)
    observed.append((original, copied, base._compact_wire(copied)))
    return copied


def _codec(base, codec, expected, observed):
    base._digest(expected, "threshold codec")
    copied = _watch(base, codec, observed)
    _need(_hash(base, copied) == expected
          and base._compact_wire(copied) == base._compact_wire(_fixed_codec(base)),
          "independent exact threshold codec differs")
    return copied


def _context(factory, base, raw, expected):
    value = base._compact_parse(raw, expected, "threshold signature context")
    _need(_hash(base, value) == _CONTEXT_SHA
          and base._compact_wire(value) == base._compact_wire(factory._context(base)),
          "exact cap-free threshold signature context required")
    return value


def _owners(factory, base):
    pins = dict(factory._owners(base)[-1])
    pins[str(_SELF_PATH)] = _SELF_PIN
    _need(_modules() == (factory, base), "threshold codec operation owners changed")
    return pins


def _fence(factory, base, before, observed):
    _need(_owners(factory, base) == before, "threshold codec operation sources changed")
    for original, copied, raw in observed:
        _need(base._compact_wire(original) == raw and base._compact_wire(copied) == raw,
              "threshold codec caller or generated inputs changed")


def _base_report(base, before, schema):
    authority = dict(base.AUTHORITY)
    authority.update(permitted_inference_context_verified=False,
                     varied_reviewed_target_population_verified=False,
                     checkpoint_compatibility_verified=False)
    return dict(schema=schema, profile=PROFILE, producer_pins=dict(before), authority=authority,
        training_mask=0, evaluation_gold_mask=0, model_executed=False, training_executed=False,
        native_build_executed=False, checkpoint_compatibility_verified=False,
        numerical_runtime_available=False, source_dependence_established=False,
        permitted_inference_context_verified=False, profile_is_singleton=False,
        admissible_content_count=3, limitations=list(_LIMITATIONS))


def _run(factory, base, observed, work):
    before = _owners(factory, base)
    failure = None
    try:
        result = work(before)
        _fence(factory, base, before, observed)
        copied = base._compact_capture(result)
        raw = base._compact_wire(copied)
        _need(base._compact_wire(result) == raw, "threshold codec report changed during serialization")
        _fence(factory, base, before, observed)
        return copied
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _fence(factory, base, before, observed)
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing threshold codec source/input check also failed.")


def _entry(factory, base, codec, request, report, observed):
    raw_request = base._compact_wire(request, base.MAX_REQUEST_BYTES)
    _need(report["request"] == request and report["request_sha256"] == hashlib.sha256(raw_request).hexdigest()
          and report["maximum"] == request["maximum"]
          and report["producer_pins"] == factory._owners(base)[-1]
          and all(value is False for value in report["authority"].values())
          and type(report["training_mask"]) is int and report["training_mask"] == 0
          and type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0,
          "genuine authored threshold report differs")
    content, _, _ = base._compact_project_tree(report["typed_expression"]["root"])
    content["schema"] = CONTENT_SCHEMA
    content = _watch(base, content, observed)
    raw = base._compact_wire(content, base.MAX_REQUEST_BYTES)
    lexical = _watch(base, base._compact_lexical(content), observed)
    positions = {token:index for index, token in enumerate(codec["vocabulary"])}
    _need(all(token in positions for token in lexical), "threshold content outside exact vocabulary")
    ids = _watch(base, [1, *(positions[token] for token in lexical), 2], observed)
    _need(2 <= len(ids) <= 512, "complete threshold sequence exceeds token budget")
    _need(_hash(base, report["signature_context"]) == _CONTEXT_SHA,
          "threshold report changed cap-free context")
    return dict(maximum=request["maximum"], content=content, raw=raw, lexical=lexical,
                ids=ids, prediction=report, context=report["signature_context"])


def _catalog(factory, base, codec, observed):
    entries = []
    for maximum in (1, 2, 3):
        request = _watch(base, factory.authored_counted_threshold_request_v2(maximum), observed)
        raw = base._compact_wire(request, base.MAX_REQUEST_BYTES)
        report = _watch(base, factory.prepare_counted_threshold_v2(raw,
            expected_request_sha256=hashlib.sha256(raw).hexdigest()), observed)
        entries.append(_entry(factory, base, codec, request, report, observed))
    _need(len({_hash(base, entry["content"]) for entry in entries}) == 3
          and len({_hash(base, entry["context"]) for entry in entries}) == 1,
          "three distinct contents and one shared context required")
    return entries


def _complete_ids(base, generated_ids, observed):
    _need(type(generated_ids) is list and 2 <= len(generated_ids) <= 512
          and all(type(item) is int and 0 <= item < 28 for item in generated_ids),
          "complete plain in-range threshold IDs required within512")
    ids = _watch(base, generated_ids, observed)
    _need(2 <= len(ids) <= 512
          and all(type(item) is int and 0 <= item < 28 for item in ids),
          "captured complete threshold IDs must remain plain and in range")
    _need(ids[0] == 1 and ids[-1] == 2 and all(item >= 3 for item in ids[1:-1]),
          "single BOS and terminal EOS without interior special tokens required")
    return ids


def build_counted_threshold_token_codec_v2():
    """Publish this distinct metadata codec without importing typed operations."""
    factory, base = _modules()
    result = base._compact_capture(_fixed_codec(base))
    base._compact_wire(result)
    _need(_modules() == (factory, base), "threshold codec sources changed")
    return result


def counted_threshold_token_codec_sha256(codec):
    """Require the exact new codec; equal width is not an old-codec alias."""
    factory, base = _modules()
    observed = []
    copied = _watch(base, codec, observed)
    _need(base._compact_wire(copied) == base._compact_wire(_fixed_codec(base)),
          "exact threshold codec required")
    for original, detached, raw in observed:
        _need(base._compact_wire(original) == raw == base._compact_wire(detached),
              "threshold codec changed during hashing")
    _need(_modules() == (factory, base), "threshold codec hash sources changed")
    return _hash(base, copied)


def encode_counted_threshold_tokens_v2(request_raw, *, expected_request_sha256,
                                      codec, expected_codec_sha256):
    """Encode one explicitly authored declaration after genuine typed preparation."""
    factory, base = _modules()
    request = factory._parse(base, request_raw, expected_request_sha256)
    observed = []
    fixed = _codec(base, codec, expected_codec_sha256, observed)
    def work(before):
        report = _watch(base, factory.prepare_counted_threshold_v2(request_raw,
            expected_request_sha256=expected_request_sha256), observed)
        # Preserve arbitrary original whitespace while comparing declaration identity.
        canonical_raw = base._compact_wire(request, base.MAX_REQUEST_BYTES)
        canonical_report = report
        if canonical_raw != request_raw:
            canonical_report = _watch(base, factory.prepare_counted_threshold_v2(canonical_raw,
                expected_request_sha256=hashlib.sha256(canonical_raw).hexdigest()), observed)
        entry = _entry(factory, base, fixed, request, canonical_report, observed)
        result = _base_report(base, before, ENCODING_SCHEMA)
        result.update(status="encoded_unreviewed_threshold_content", target_ids=entry["ids"],
            lexical_tokens=entry["lexical"], lexical_token_count=len(entry["lexical"]),
            total_token_count=len(entry["ids"]), canonical_content_raw_utf8=entry["raw"].decode(),
            content_sha256=_hash(base, entry["content"]), context_raw_utf8=base._compact_wire(entry["context"]).decode(),
            context_sha256=_CONTEXT_SHA, codec_sha256=expected_codec_sha256,
            original_request_sha256=expected_request_sha256,
            context_origin="cap_free_authored_signature_context_permission_unreviewed",
            prediction=report, counts=dict(report["counts"]))
        return result
    return _run(factory, base, observed, work)


def decode_counted_threshold_tokens_v2(generated_ids, context_raw, *, expected_context_sha256,
                                      codec, expected_codec_sha256):
    """Decode complete offered tokens without an original request, target or cap."""
    factory, base = _modules()
    observed = []
    fixed = _codec(base, codec, expected_codec_sha256, observed)
    context = _context(factory, base, context_raw, expected_context_sha256)
    ids = _complete_ids(base, generated_ids, observed)
    raw = "".join(fixed["vocabulary"][index] for index in ids[1:-1]).encode()
    content = base._compact_parse(raw, hashlib.sha256(raw).hexdigest(), "threshold token content")
    _need(base._compact_wire(content) == raw
          and [fixed["vocabulary"][index] for index in ids[1:-1]] == base._compact_lexical(content),
          "canonical complete threshold JSON and lexical segmentation required")
    def work(before):
        entries = _catalog(factory, base, fixed, observed)
        matches = [entry for entry in entries if entry["raw"] == raw and entry["ids"] == ids]
        _need(len(matches) == 1, "offered tokens are outside the three-form typed threshold language")
        chosen = matches[0]
        _need(base._compact_wire(chosen["context"]) == base._compact_wire(context),
              "candidate threshold context differs")
        result = _base_report(base, before, CANDIDATE_SCHEMA)
        result.update(status="valid_candidate", generated_ids=ids,
            canonical_content_raw_utf8=raw.decode(), content_sha256=hashlib.sha256(raw).hexdigest(),
            context_sha256=_CONTEXT_SHA, context_raw_sha256=expected_context_sha256,
            codec_sha256=expected_codec_sha256, prediction=chosen["prediction"],
            counts=dict(chosen["prediction"]["counts"]), decoded_maximum=chosen["maximum"],
            context_origin="cap_free_authored_signature_context_permission_unreviewed",
            typed_projection_verified=True, framing=dict(bos_present=True,eos_terminal=True,
                token_ids_valid=True,interior_special_tokens=False,terminated=True))
        return result
    return _run(factory, base, observed, work)


def inspect_counted_threshold_prefix_v2(prefix_ids, context_raw, *, expected_context_sha256,
                                       codec, expected_codec_sha256):
    """Return next IDs over every matching form; a reference answer is never input."""
    factory, base = _modules()
    _need(type(prefix_ids) is list and len(prefix_ids) <= 512
          and all(type(item) is int and -(1 << 63) < item < (1 << 63) for item in prefix_ids),
          "zero to512 bounded plain integer threshold prefix IDs required")
    observed = []
    fixed = _codec(base, codec, expected_codec_sha256, observed)
    _context(factory, base, context_raw, expected_context_sha256)
    ids = _watch(base, prefix_ids, observed)
    _need(len(ids) <= 512
          and all(type(item) is int and -(1 << 63) < item < (1 << 63) for item in ids),
          "captured threshold prefix IDs must remain bounded plain integers")
    def work(before):
        entries = _catalog(factory, base, fixed, observed)
        matching = [entry for entry in entries if entry["ids"][:len(ids)] == ids]
        candidate = None
        if any(item < 0 or item >= 28 for item in ids):
            status, reason = "rejected", "out_of_vocabulary_id"
        elif not matching:
            status, reason = "rejected", "prefix_mismatch"
        elif any(len(entry["ids"]) == len(ids) for entry in matching):
            _need(len(matching) == 1, "complete threshold sequence must be unique")
            status, reason = "complete", None
            candidate = _watch(base, decode_counted_threshold_tokens_v2(ids, context_raw,
                expected_context_sha256=expected_context_sha256, codec=codec,
                expected_codec_sha256=expected_codec_sha256), observed)
            _need(candidate["status"] == "valid_candidate" and candidate["generated_ids"] == ids,
                  "complete offered prefix differs from genuine public threshold decode")
        else:
            status, reason = "prefix", None
        allowed = sorted({entry["ids"][len(ids)] for entry in matching if len(entry["ids"]) > len(ids)})
        remaining = [len(entry["ids"]) - len(ids) for entry in matching]
        result = _base_report(base, before, PREFIX_SCHEMA)
        result.update(status=status, reason=reason, offered_ids=ids, allowed_token_ids=allowed,
            matching_completion_count=len(matching), remaining_token_slots=512-len(ids), max_sequence_tokens=512,
            completion_tokens_remaining_min=min(remaining) if remaining else None,
            completion_tokens_remaining_max=max(remaining) if remaining else None,
            context_sha256=_CONTEXT_SHA, context_raw_sha256=expected_context_sha256,
            codec_sha256=expected_codec_sha256, context_origin="cap_free_authored_signature_context_permission_unreviewed",
            reference_target_used=False, complete_candidate=candidate)
        return result
    return _run(factory, base, observed, work)


__all__ = ["build_counted_threshold_token_codec_v2", "counted_threshold_token_codec_sha256",
           "encode_counted_threshold_tokens_v2", "decode_counted_threshold_tokens_v2",
           "inspect_counted_threshold_prefix_v2"]
