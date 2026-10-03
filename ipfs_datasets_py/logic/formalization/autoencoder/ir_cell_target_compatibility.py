"""Evaluation-only canonical target coverage for existing cached 384D assets.

This stdlib preflight never loads a model, fits a vocabulary or changes assets.
It mirrors two source-pinned lexical codecs, without invoking their native
grammar validators. Coverage is necessary for that canonical encoding only;
it establishes neither native validity, numerical runtime compatibility nor
source fidelity. Cached gold targets belong solely to this evaluator.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import ir_cell_routing as routing
from . import ir_cell_runtime as runtime

SCHEMA = "ir-cell-cached-target-compatibility/v1"
MAX_TARGET_BYTES = 512 * 1024  # Evaluator bound; not a Legal producer/token-budget claim.
_ARCHITECTURE = "residual-projection-latent-formula-gru/v1"
_FIELDS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
_SPECIAL = ("<pad>", "<bos>", "<eos>")
_TOKEN = re.compile(
    r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
    r'|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
    r'|true|false|null|[{}\[\],:]'
)
_POLICY = {
    "source_tokenization": "unicode_casefold_word_or_punctuation/v1",
    "source_unknown": "reject", "target_unknown": "reject",
    "vocabulary_origin": "training_examples_only", "identifier_hashing": False,
    "target_schema": "CanonicalRoundTripIR@1", "rule_count": 1,
    "field_order": list(_FIELDS), "qualifiers": "sorted_unique_input_required",
    "max_qualifiers_per_facet": 4, "max_source_tokens": 64,
    "max_target_tokens": 64, "max_vocabulary": 4096,
    "source_pad_id": 0, "source_unk_id": 1,
    "target_pad_id": 0, "target_bos_id": 1, "target_eos_id": 2,
    "truncation": "reject", "generation_fallback": "none",
}
_SOURCE_PROFILES = {
    "domain_384_autoencoder.py": (34679, "66c5ee320f9c7aacd3b246d0666c7fc3ee928e4679892e1e90c838e1b291dbc6"),
    "legal_formula_codec.py": (14622, "f90769a3d99131da5ba48bb84c6f830f521c92d98122bdaaa8dd88fc65042290"),
    "modal_latent_formula.py": (35427, "ec5bdcd752d157c9fc0257a45551cfe9ce7be172af767e8ed769bf1bc8a31d36"),
}
_LEGAL_FALSE = ("qualified", "admitted", "proof_authority", "semantic_correctness_verified", "promotion_performed")
_HEAD_FALSE = ("qualified", "admitted", "proof_authority", "semantic_correctness_verified",
               "promotion_performed", "formalized", "roundtrip_ok", "lake_executed", "publication_performed")
_DOMAIN_FALSE = ("qualified", "admitted", "proof_authority", "source_semantics_verified", "publication_performed")
_AUTHORITY = {**runtime._AUTHORITY, "native_grammar_verified": False,
              "checkpoint_numerically_validated": False, "canonical_encoding_is_source_fidelity": False}


class TargetCompatibilityError(runtime.IRCellRuntimeError):
    """Malformed, unsupported or changed evaluation bindings."""


def _require(condition, message):
    if not condition:
        raise TargetCompatibilityError(message)


def _raw(value, *, ascii=True):
    return json.dumps(value, ensure_ascii=ascii, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _typed(*values):
    return _raw(list(values), ascii=False).decode("utf-8")


_STRUCTURAL = _SPECIAL + tuple(item for field in _FIELDS for item in
    ((_typed("field", field), _typed("end", field)) if field in _FIELDS[4:]
     else (_typed("field", field),)))


def _false(value, names):
    _require(all(value.get(name) is False for name in names), "checkpoint authority must be explicitly false")


def _legal_atom(field, value):
    _require(type(value) is str and len(value) <= 4096, "bounded exact-string Legal atom required")
    if field == "modality":
        _require(value in ("O", "P", "F"), "Legal modality must be O, P or F")
    elif field != "object":
        _require(bool(value.strip()), "nonblank Legal actor/action/qualifier required")


def _source(name, declared):
    size, sha = _SOURCE_PROFILES[name]
    _require(declared == sha, "unrecognized checkpoint codec implementation")
    path = Path(__file__).resolve().parents[3] / "optimizers" / "logic_theorem_optimizer" / name
    pin = {"path": str(path), "bytes": size, "sha256": sha}
    routing._read_pin(pin)
    return pin


def _implementation(value, *, legal):
    _require(type(value) is dict, "codec implementation declaration required")
    if legal:
        _require(set(value) == {"files", "scope"} and
                 value["scope"] == "listed_latent_decoder_and_grammar_sources_only",
                 "unsupported Legal implementation declaration")
        files = value["files"]
        _require(type(files) is dict and set(files) == {"canonical_contracts.py", "legal_formula_codec.py",
                 "legal_ir_grammar_decoder.py", "modal_latent_formula.py", "tree_pin.py"}
                 and all(runtime._hash(sha) for sha in files.values()), "closed Legal implementation files required")
        return [_source(name, files[name]) for name in ("legal_formula_codec.py", "modal_latent_formula.py")]
    _require(set(value) == {"dependencies", "runtime", "scope"}
             and value["scope"] == "listed_numerical_and_native_validator_modules_only"
             and type(value["dependencies"]) is dict
             and all(type(name) is str and runtime._hash(sha) for name, sha in value["dependencies"].items()),
             "unsupported Domain implementation declaration")
    return [_source("domain_384_autoencoder.py", value["runtime"])]


def _vocabulary(value, structural, *, legal):
    _require(type(value) is list and len(structural) < len(value) <= 4096
             and all(type(token) is str and 0 < len(token) <= (4096 if legal else 16384) for token in value),
             "bounded target vocabulary required")
    _require(tuple(value[:len(structural)]) == structural and len(set(value)) == len(value)
             and value[len(structural):] == sorted(value[len(structural):]),
             "target vocabulary specials, uniqueness or ordering differs")
    if not legal:
        _require(all(_TOKEN.fullmatch(token) is not None for token in value[len(structural):]),
                 "Domain vocabulary contains an invalid lexical token")
    else:
        scalar_fields = set()
        for token in value[len(structural):]:
            atom = json.loads(token)
            _require(type(atom) is list and len(atom) == 3 and atom[0] == "atom"
                     and type(atom[1]) is str and atom[1] in _FIELDS and type(atom[2]) is str
                     and _raw(atom, ascii=False).decode("utf-8") == token,
                     "Legal vocabulary requires canonical field-specific typed atoms")
            _legal_atom(atom[1], atom[2])
            scalar_fields.add(atom[1])
        _require(set(_FIELDS[:4]) <= scalar_fields, "Legal vocabulary lacks a scalar facet")
    return tuple(value)


def _profile(checkpoint, family):
    _require(type(checkpoint.get("dimension")) is int and checkpoint["dimension"] == 384,
             "checkpoint requires exact 384D identity")
    if family != "legal_ir":
        _require(checkpoint.get("schema") == "domain-384-typed-autoencoder/v1"
                 and checkpoint.get("domain_id") == family
                 and checkpoint.get("architecture") == _ARCHITECTURE, "Domain checkpoint identity differs")
        _false(checkpoint, _DOMAIN_FALSE)
        receipts = _implementation(checkpoint.get("implementation"), legal=False)
        codec, config = checkpoint.get("codec"), checkpoint.get("config")
        _require(type(codec) is dict and set(codec) == {"schema", "target_vocabulary"}
                 and codec["schema"] == "typed-json-lexical/v1", "closed Domain codec required")
        _require(type(config) is dict and type(config.get("max_target_tokens")) is int
                 and 1 <= config["max_target_tokens"] <= 1024, "bounded exact target token limit required")
        return dict(id="domain-384-canonical-json-lexical/v1", available=True,
            vocabulary=_vocabulary(codec["target_vocabulary"], _SPECIAL, legal=False),
            max_target_tokens=config["max_target_tokens"], max_lexical_tokens=1022,
            implementation_declaration=deepcopy(checkpoint["implementation"]), source_receipts=receipts)
    _require(checkpoint.get("schema") == "legal-current-384-inference-package/v1"
             and checkpoint.get("runtime") == "legal_current_v2" and checkpoint.get("domain") == family,
             "Legal package identity differs")
    _false(checkpoint, _LEGAL_FALSE)
    _require("formula_checkpoint" in checkpoint, "explicit Legal formula head field required")
    head = checkpoint["formula_checkpoint"]
    if head is None:
        return dict(id="legal-latent-typed-atoms/v1", available=False,
                    reason="learned_formula_head_absent", source_receipts=[])
    _require(type(head) is dict and head.get("schema") == "modal-latent-formula-checkpoint/v1"
             and head.get("projection_id") == "typed_deontic_rule_v1", "Legal formula head identity differs")
    _false(head, _HEAD_FALSE)
    binding = head.get("binding")
    _require(type(binding) is dict and set(binding) == {"domain", "dimension", "lineage_id", "runtime_profile", "core_sha256"}
             and binding["domain"] == family and type(binding["dimension"]) is int and binding["dimension"] == 384
             and binding["lineage_id"] == "current_legal_v2" and binding["runtime_profile"] == "modal-latent-joint-formula/v1"
             and runtime._hash(binding["core_sha256"]) and _raw(binding) == _raw(checkpoint.get("core_binding")),
             "Legal formula/core binding differs")
    receipts = _implementation(head.get("implementation"), legal=True)
    producer = checkpoint.get("producer")
    _require(type(producer) is dict and _raw(producer.get("formula_implementation")) == _raw(head["implementation"]),
             "Legal package/head implementation declarations differ")
    codec, config = head.get("codec"), head.get("config")
    _require(type(codec) is dict and set(codec) == {"schema", "source_vocabulary", "target_vocabulary", "policy"}
             and codec["schema"] == "legal-source-formula-codec/v1"
             and _raw(codec["policy"]) == _raw(_POLICY)
             and codec["source_vocabulary"] == ["<pad>", "<unk>", "latent"], "closed latent Legal codec policy required")
    _require(type(config) is dict and config.get("architecture") == _ARCHITECTURE
             and type(config.get("max_target_tokens")) is int and config["max_target_tokens"] == 64
             and config.get("source_input") == "provenance_only_not_neural_input", "Legal latent target config differs")
    return dict(id="legal-latent-typed-atoms/v1", available=True,
        vocabulary=_vocabulary(codec["target_vocabulary"], _STRUCTURAL, legal=True),
        max_target_tokens=64, max_lexical_tokens=None,
        implementation_declaration=deepcopy(head["implementation"]), source_receipts=receipts)


def _pieces(target, family):
    _require(len(_raw(target)) <= MAX_TARGET_BYTES, "selected target exceeds evaluator byte bound")
    if family != "legal_ir":
        raw = _raw(target).decode("utf-8")
        _require(len(raw.encode("utf-8")) <= 128 * 1024, "Domain target exceeds codec byte bound")
        tokens = _TOKEN.findall(raw)
        _require("".join(tokens) == raw, "Domain target lexical encoding differs")
        if set(target) == {"kind", "document"}:
            _require(type(target["document"]) is dict and target["kind"] in
                     ("document", "intent_rich_ast" if family == "intent_ir" else "program_expression"),
                     "unsupported family fragment envelope")
        return ["<bos>", *tokens, "<eos>"], [None] * (len(tokens) + 2)
    _require(set(target) == {"rules"} and type(target["rules"]) is list and len(target["rules"]) == 1,
             "Legal target requires exactly one rule")
    rule = target["rules"][0]
    _require(type(rule) is dict and set(rule) == set(_FIELDS), "closed seven-facet Legal rule required")
    tokens, facets = ["<bos>"], [None]
    for field in _FIELDS:
        values = rule[field]
        if field in _FIELDS[:4]:
            _require(type(values) is str, "Legal scalar facet must be a string")
            values = [values]
        else:
            _require(type(values) is list and len(values) <= 4 and all(type(v) is str for v in values)
                     and values == sorted(set(values)), "Legal qualifiers must already be sorted unique strings")
        for value in values:
            _legal_atom(field, value)
        tokens.append(_typed("field", field)); facets.append(field)
        tokens.extend(_typed("atom", field, value) for value in values); facets.extend([field] * len(values))
        if field in _FIELDS[4:]:
            tokens.append(_typed("end", field)); facets.append(field)
    return [*tokens, "<eos>"], [*facets, None]


def preflight_ir_cell_cached_targets(directory_plan_pin, inventory_pins, request, *,
        package_manifest_pin, cache_split, row_ids, max_reference_bytes=runtime.MAX_REFERENCE_BYTES):
    """Report ordered gold-target canonical coverage; perform no loading/inference.

    Unsupported cells, malformed profiles and changed bytes raise. An absent
    Legal head is reported as unavailable, with no parser fallback. Legitimate
    OOV and overlength targets are counted among all selected rows. Endpoint
    rechecks fence individual files, without claiming an atomic snapshot.
    """
    try:
        options = runtime._capture_options(directory_plan_pin, inventory_pins, request,
            package_manifest_pin, cache_split, row_ids, max_reference_bytes)
        plan = runtime.prepare_ir_cell_runtime(**deepcopy(options))
        checkpoint_pin = plan["route"]["selected_checkpoint"]["receipt"]
        checkpoint = runtime._json(checkpoint_pin, node_limit=4_000_000)
        family = options["request"]["ir_family_id"]
        profile = _profile(checkpoint, family)
        saved = runtime._json(plan["cache_receipt"], node_limit=4_000_000)
        rows = []
        vocabulary = set(profile.get("vocabulary", ()))
        for receipt in plan["row_receipts"]:
            row = saved["rows"][receipt["row_index"]]
            _require(row["id"] == receipt["id"], "target row association differs")
            _require(len(_raw(row["target"])) <= MAX_TARGET_BYTES, "selected target exceeds evaluator byte bound")
            result = {**deepcopy(receipt), "target_sha256": hashlib.sha256(_raw(row["target"])).hexdigest(),
                      "target_digest_encoding": "json-sort-compact-ensure_ascii-true/v1",
                      "native_grammar_verified": False, "target_inspection_scope": "evaluation_only"}
            if not profile["available"]:
                result.update(status="unsupported", reason=profile["reason"], canonical_encoding_representable=None,
                    token_count_including_bos_eos=None, over_limit=None, missing_tokens=[])
            else:
                tokens, facets = _pieces(row["target"], family)
                missing = [{"position": position, "token": token, "facet": facets[position]}
                           for position, token in enumerate(tokens) if token not in vocabulary]
                over = len(tokens) > profile["max_target_tokens"] or (
                    profile["max_lexical_tokens"] is not None and len(tokens) - 2 > profile["max_lexical_tokens"])
                covered = not missing and not over
                result.update(status="covered" if covered else "incompatible",
                    canonical_encoding_representable=covered, token_count_including_bos_eos=len(tokens),
                    lexical_token_count=len(tokens) - 2, max_target_tokens=profile["max_target_tokens"],
                    over_limit=over, missing_tokens=missing,
                    canonical_token_sequence_sha256=hashlib.sha256(_raw(tokens)).hexdigest())
            rows.append(result)
        repeated = runtime.prepare_ir_cell_runtime(**deepcopy(options))
        _require(_raw(repeated) == _raw(plan), "target preflight binding changed during evaluation")
        for pin in profile["source_receipts"]:
            routing._read_pin(pin)
        profile = {key: value for key, value in profile.items() if key != "vocabulary"} | {
            "vocabulary_size": len(vocabulary), "vocabulary_changed": False}
        return deepcopy(dict(schema=SCHEMA, request=options["request"], codec_profile=profile,
            package_manifest_receipt=plan["package_manifest_receipt"], package_file_receipts=plan["package_file_receipts"],
            checkpoint_receipt=checkpoint_pin, directory_plan_receipt=options["directory_plan_pin"],
            inventory_receipts=options["inventory_pins"], cache_receipt=plan["cache_receipt"],
            cache_split=cache_split, row_ids=options["row_ids"], rows=rows,
            evaluator_max_target_bytes=MAX_TARGET_BYTES,
            counts=dict(selected=len(rows), covered=sum(row["status"] == "covered" for row in rows),
                incompatible=sum(row["status"] == "incompatible" for row in rows),
                unsupported=sum(row["status"] == "unsupported" for row in rows),
                with_oov=sum(bool(row["missing_tokens"]) for row in rows),
                over_limit=sum(row["over_limit"] is True for row in rows)),
            model_load_performed=False, inference_executed=False, targets_forwarded_to_model=False,
            original_weights_changed=False, new_embeddings_generated=False, authority=dict(_AUTHORITY),
            consistency_scope=runtime._SCOPE,
            evaluation_scope="Known canonical lexical encoding only; native grammar, alternative JSON spellings, numerical runtime compatibility and source reconstruction are unverified."))
    except (runtime.IRCellRuntimeError, routing.RoutingError) as error:
        raise TargetCompatibilityError(str(error)) from error
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as error:
        raise TargetCompatibilityError("malformed target codec evaluation binding") from error


__all__ = ["SCHEMA", "TargetCompatibilityError", "preflight_ir_cell_cached_targets"]
