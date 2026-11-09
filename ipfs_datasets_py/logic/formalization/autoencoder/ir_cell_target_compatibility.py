"""Evaluation-only target coverage for cached cells and declared normative labels.

These stdlib evaluators never load models, fit vocabularies or change assets.
Cached cell profiles retain their original source-pinned codec contracts. The
normative branch inspects declared labels against the inherited fixed32 codec.
Coverage establishes no native grammar, numerical compatibility, source fidelity
or reviewed legal meaning. Targets remain solely inside evaluation.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import ir_cell_routing as routing
from . import ir_cell_runtime as runtime
from . import authored_scalar_holdout as authored
from . import normative_legal_ir_runtime as normative

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


NORMATIVE_REQUEST_SCHEMA = "normative-legal-ir-target-inspection-request/v1"
NORMATIVE_SCHEMA = "normative-legal-ir-target-inspection/v1"
MAX_NORMATIVE_REQUEST_BYTES = 2 * 1024 * 1024
MAX_NORMATIVE_ROWS = 64
_NORMATIVE_CODEC_SHA256 = "cba3e5384e2bee12e709ccc8e9ee430e51cf09a8fc2e8abdd57143fdaa38dba2"
# These identify existing input contracts, not new routes or authenticated assets.
_NORMATIVE_CONTRACTS = (
    "normative-selected-cached-legal-ir/v1",
    "normative-retained-source-cache-legal-ir/v1",
    "arbitrary-native-source-cache-legal-ir/v1",
)


def _normative_request(raw, expected):
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_NORMATIVE_REQUEST_BYTES,
             "bounded exact normative inspection bytes required")
    _require(runtime._hash(expected) and hashlib.sha256(raw).hexdigest() == expected,
             "independent normative inspection request SHA256 differs")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=routing._pairs,
                       parse_float=routing._float, parse_constant=routing._constant)
    # Bound complete JSON before canonicalization; reject lone Unicode surrogates.
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        _require(depth <= 64 and nodes <= 100_000, "normative inspection JSON exceeds structural bound")
        if type(item) is str:
            item.encode("utf-8")
        elif type(item) is dict:
            pending.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
    _require(type(value) is dict and set(value) == {"schema", "decoder_request", "rows"}
             and value["schema"] == NORMATIVE_REQUEST_SCHEMA, "closed normative inspection request required")
    request = value["decoder_request"]
    _require(type(request) is dict and request.get("decoder_contract_id") in _NORMATIVE_CONTRACTS,
             "existing normative decoder contract declaration required")
    normative._validate_request(request, _decoder_contract_id=request["decoder_contract_id"])
    _require(request["ir_family_id"] == "legal_ir" and type(request["dimension"]) is int
             and request["dimension"] in (384, 768) and request["dimension_role"] == "input_embedding"
             and request["task_id"] == "semantic_IR_reconstruction" and runtime._hash(request["checkpoint_sha256"]),
             "exact normative family, width, role, task and declared checkpoint SHA256 required")
    rows = value["rows"]
    _require(type(rows) is list and 1 <= len(rows) <= MAX_NORMATIVE_ROWS,
             "one to 64 normative target rows required")
    identifiers = set()
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source_sha256", "canonical_ir"},
                 "closed normative evaluation row required; runtime inputs remain separate")
        runtime._text(row["id"], 512, "normative evaluation row id")
        _require(row["id"] not in identifiers, "duplicate normative evaluation row id")
        identifiers.add(row["id"])
        _require(runtime._hash(row["source_sha256"]), "declared exact source SHA256 required")
        target = row["canonical_ir"]
        _require(target is None or type(target) is dict, "normative target must be a JSON object or null")
        _require(target is None or len(_raw(target)) <= MAX_TARGET_BYTES,
                 "normative target exceeds evaluator byte bound")
    return value


def _normative_target_shape(target):
    """A restricted declaration fragment, not the inherited native recognizer.

    Eight source/scalar slots are not a claim that native syntax ends at eight
    rules. Role vocabularies and qualifier meanings are deliberately unassessed.
    No target is normalized, flattened, sorted, deduplicated or repaired.
    """
    if set(target) != {"rules"} or type(target["rules"]) is not list:
        return False
    if not 1 <= len(target["rules"]) <= 8:
        return False
    for rule in target["rules"]:
        if type(rule) is not dict or set(rule) != set(_FIELDS):
            return False
        for field in _FIELDS:
            values = rule[field] if field in _FIELDS[4:] else [rule[field]]
            if type(values) is not list:
                return False
            try:
                for atom in values:
                    _legal_atom(field, atom)
            except TargetCompatibilityError:
                return False
    return True


def inspect_normative_legal_ir_targets(request_raw: bytes, *, expected_request_sha256: str):
    """Inspect complete supplied labels against the fixed normative32 codec.

    This pure, evaluation-only API opens no paths, models, caches or network.
    The independent request hash pins caller-supplied bytes only. Checkpoint and
    source hashes are declarations: their payloads, physical occurrences, saved
    transforms, runtime bindings, producer execution and legal review are NOT
    authenticated. All supplied labels remain unreviewed; null stays pending.

    Lexical coverage and complete BOS/EOS-inclusive length are independent of
    the restricted seven-facet declaration shape and of native grammar. Every
    selected row remains in order, including unsupported shapes and overflow.
    """
    try:
        value = _normative_request(request_raw, expected_request_sha256)
        vocabulary = tuple(normative._VOCABULARY)
        # Reuse the actual historical encoder/canonicalizer, not its stricter
        # TRAIN role bank. No numerical dependency is imported or invoked.
        _require(vocabulary == tuple(authored.VOCABULARY) and len(vocabulary) == 32,
                 "inherited normative codec inventories differ")
        codec = {"schema": "typed-json-lexical/v1", "target_vocabulary": list(vocabulary)}
        codec_sha = hashlib.sha256(authored.raw(codec)).hexdigest()
        _require(codec_sha == _NORMATIVE_CODEC_SHA256, "fixed normative32 codec identity differs")
        rows = []
        for row in value["rows"]:
            target = row["canonical_ir"]
            result = dict(id=row["id"], source_sha256=row["source_sha256"],
                source_identity_scope="caller_declared_hash_only", source_binding_verified=False,
                target_sha256=None, target_digest_encoding="json-sort-compact-ensure_ascii-true/v1",
                status="pending", reason="label_absent", lexical_encoding_covered=None, target_shape_supported=None,
                token_count_including_bos_eos=None, lexical_token_count=None,
                canonical_token_sequence_sha256=None, over_limit=None, missing_tokens=[],
                native_grammar_verified=False, field_roles_verified=False, reviewed_target=False, target_inspection_scope="evaluation_only")
            if target is not None:
                target_raw = authored.raw(target)
                lexical = _TOKEN.findall(target_raw.decode("utf-8"))
                _require("".join(lexical).encode("utf-8") == target_raw,
                         "complete normative target lexical analysis differs")
                tokens = ["<bos>", *lexical, "<eos>"]
                missing = [{"position": index, "token": token} for index, token in enumerate(tokens)
                           if token not in vocabulary]
                over = len(tokens) > 512
                covered = not missing and not over
                shape = _normative_target_shape(target)
                result.update(target_sha256=hashlib.sha256(target_raw).hexdigest(),
                    status="unsupported" if not shape else "covered" if covered else "incompatible",
                    reason="outside_inspection_shape_profile" if not shape else None if covered else "fixed_codec_oov_or_output_limit",
                    lexical_encoding_covered=covered, target_shape_supported=shape,
                    token_count_including_bos_eos=len(tokens), lexical_token_count=len(lexical),
                    over_limit=over, missing_tokens=missing,
                    canonical_token_sequence_sha256=hashlib.sha256(_raw(tokens)).hexdigest())
                if covered:
                    # This is only the exact pure lexical encode/roundtrip; it
                    # does not call a native grammar or inspect source meaning.
                    ids = authored._encode(target, codec)
                    _require(ids == [vocabulary.index(token) for token in tokens],
                             "inherited normative lexical encoder differs")
            rows.append(result)
        return deepcopy(dict(schema=NORMATIVE_SCHEMA, request_sha256=expected_request_sha256,
            request_bytes=len(request_raw), decoder_request=value["decoder_request"],
            codec_profile=dict(schema=codec["schema"], codec_sha256=codec_sha, vocabulary_size=32,
                vocabulary_changed=False, max_target_tokens=512, token_count_includes_bos_eos=True,
                target_shape_profile="flat-seven-facet-declarations-one-to-eight-rules/v1",
                qualifier_values="string_lists_preserved_without_normalization",
                inherited_native_grammar_verified=False),
            rows=rows, counts=dict(selected=len(rows),
                covered=sum(row["status"] == "covered" for row in rows),
                incompatible=sum(row["status"] == "incompatible" for row in rows),
                unsupported=sum(row["status"] == "unsupported" for row in rows),
                pending=sum(row["status"] == "pending" for row in rows),
                with_oov=sum(bool(row["missing_tokens"]) for row in rows),
                over_limit=sum(row["over_limit"] is True for row in rows)),
            authority={**_AUTHORITY, "checkpoint_binding_verified": False, "source_binding_verified": False,
                "preprocessing_binding_verified": False, "runtime_bindings_verified": False,
                "reviewed_targets_established": False, "semantic_representability_verified": False},
            model_load_performed=False, inference_executed=False, targets_forwarded_to_model=False,
            file_io_performed=False, network_executed=False, source_payloads_replayed=False,
            evaluation_scope="Caller-declared inputs and unreviewed labels only; fixed lexical codec and complete output budget. No source/checkpoint replay, native grammar, numerical compatibility, review, training eligibility or Lean admission."))
    except TargetCompatibilityError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as error:
        raise TargetCompatibilityError("malformed normative target inspection binding: " + str(error)) from error


BOUND_NORMATIVE_SCHEMA = "normative-legal-ir-bound-target-inspection/v1"
_RUNTIME_COMMON_OPTIONS = {"checkpoint_pin", "preprocessing_pin", "donor_checkpoint_pin",
                           "source_owner_pins", "row_ids"}
_RUNTIME_SOURCE_OPTIONS = {
    _NORMATIVE_CONTRACTS[0]: {"source_inputs_pin", "source_contexts_pin"},
    _NORMATIVE_CONTRACTS[1]: {"source_cache_pin", "source_plan_pin", "production_pin"},
    _NORMATIVE_CONTRACTS[2]: {"source_cache_pin", "source_requests_pin", "native384_receipt_refs",
                             "native768_report_refs", "source_artifact_pins"},
}
_RUNTIME_SOURCE_SCOPES = (
    "original_saved_source_cache_rows",
    "retained48_source_native_cache_rows",
    "explicit_new_source_span_occurrences_and_native_record_consistency",
)


def _normative_runtime_options(value, expected, contract):
    """Detach a pinned, bounded, plain JSON source-only preparation packet."""
    _require(runtime._hash(expected), "independent canonical runtime options SHA256 required")
    _require(type(value) is dict, "source-only runtime options object required")
    required = _RUNTIME_COMMON_OPTIONS | _RUNTIME_SOURCE_OPTIONS[contract]
    _require(len(value) <= len(required) + 2, "closed source-only runtime options required")
    _require(required <= set(value) <= required | {"deadline_seconds", "max_reference_bytes"},
             "closed source-only runtime options required; targets/request/extra fields forbidden")
    pending, nodes, string_bytes = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        _require(depth <= 64 and nodes <= 100_000, "runtime options exceed structural bound")
        _require(type(item) in (dict, list, str, int, float, bool, type(None)), "plain JSON runtime options required")
        if type(item) is str:
            _require(len(item) <= MAX_NORMATIVE_REQUEST_BYTES, "runtime option string exceeds bound")
            string_bytes += len(item.encode("utf-8"))
            _require(string_bytes <= MAX_NORMATIVE_REQUEST_BYTES, "runtime option strings exceed aggregate bound")
        elif type(item) is dict:
            _require(2 * len(item) <= 100_000 - nodes - len(pending), "runtime options exceed structural bound")
            _require(all(type(key) is str for key in item), "exact string runtime option keys required")
            pending.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif type(item) is list:
            _require(len(item) <= 100_000 - nodes - len(pending), "runtime options exceed structural bound")
            pending.extend((child, depth + 1) for child in item)
    raw = _raw(value, ascii=False)
    _require(len(raw) <= MAX_NORMATIVE_REQUEST_BYTES and runtime._hash(expected)
             and hashlib.sha256(raw).hexdigest() == expected,
             "independent canonical runtime options SHA256 differs or options exceed byte bound")
    return json.loads(raw), raw


def _prepare_normative_target_binding(request, options):
    contract = request["decoder_contract_id"]
    if contract == _NORMATIVE_CONTRACTS[0]:
        prepare = normative.prepare_normative_legal_ir_runtime
    elif contract == _NORMATIVE_CONTRACTS[1]:
        from . import normative_cached_legal_ir_runtime as cached
        prepare = cached.prepare_normative_cached_legal_ir_runtime
    else:
        from . import arbitrary_native_legal_ir_runtime as arbitrary
        prepare = arbitrary.prepare_arbitrary_native_legal_ir_runtime
    # Every call receives a fresh source-only packet; labels are never arguments.
    packet = deepcopy(options)
    declared = deepcopy(request)
    result = prepare(declared, **packet)
    _require(_raw(packet, ascii=False) == _raw(options, ascii=False)
             and _raw(declared) == _raw(request), "preparation mutated its source-only arguments")
    return result


def preflight_normative_legal_ir_targets(request_raw: bytes, *, expected_request_sha256: str,
        runtime_options, expected_runtime_options_sha256: str):
    """Bind fixed-codec inspection to genuine opening/closing runtime preparation.

    Runtime options use compact, sorted, ensure_ascii=False UTF8 JSON for their
    independent expected digest. Existing preparation owners replay the selected
    assets and source-only caches; no model is opened. Targets remain evaluator
    inputs. Mechanical binding does not authenticate law/edition, meanings,
    reviewer decisions, producer execution, numerical quality or Lean admission.
    """
    try:
        selected = _normative_request(request_raw, expected_request_sha256)
        request = selected["decoder_request"]
        contract = request["decoder_contract_id"]
        options, options_raw = _normative_runtime_options(runtime_options, expected_runtime_options_sha256, contract)
        identifiers = [row["id"] for row in selected["rows"]]
        _require(type(options["row_ids"]) is list and options["row_ids"] == identifiers,
                 "inspection rows must exactly match selected runtime IDs and order")
        live_opening = _prepare_normative_target_binding(request, options)
        _require(type(live_opening) is dict, "prepared normative plan object required")
        opening_raw = _raw(live_opening, ascii=False)
        opening = json.loads(opening_raw)
        _require(type(opening) is dict and _raw(opening["request"]) == _raw(request)
                 and opening["row_ids"] == identifiers and opening["decoder_contract_id"] == contract,
                 "prepared normative request or ordered row binding differs")
        receipts = opening["row_receipts"]
        sources = opening["source_inputs"]["rows"]
        _require(type(receipts) is list and type(sources) is list
                 and len(receipts) == len(sources) == len(identifiers), "complete prepared row population required")
        for row, receipt, source in zip(selected["rows"], receipts, sources):
            _require(receipt["id"] == source["id"] == row["id"]
                     and receipt["source_sha256"] == row["source_sha256"]
                     == hashlib.sha256(source["source_text"].encode("utf-8")).hexdigest(),
                     "selected source text SHA256 or occurrence ID differs")
        # Do not re-run generic source validation here: the arbitrary owner
        # preserves distinct physical occurrences even when prose is identical.
        inspection = inspect_normative_legal_ir_targets(
            request_raw, expected_request_sha256=expected_request_sha256)
        _require(opening["codec_sha256"] == inspection["codec_profile"]["codec_sha256"]
                 and hashlib.sha256(_raw(opening["codec"])).hexdigest() == _NORMATIVE_CODEC_SHA256
                 and type(opening["budgets"]["decoder_output_tokens"]) is int
                 and opening["budgets"]["decoder_output_tokens"] == 512
                 and opening["artifact_receipts"]["checkpoint"]["sha256"] == request["checkpoint_sha256"],
                 "prepared checkpoint, frozen codec or complete output budget differs")
        closing = _prepare_normative_target_binding(request, options)
        _require(_raw(closing, ascii=False) == opening_raw, "runtime binding changed during target inspection")
        _require(_raw(live_opening, ascii=False) == opening_raw, "opening preparation plan mutated during inspection")
        _require(_raw(options, ascii=False) == options_raw, "captured runtime options changed during inspection")
        selected_fields = ("artifact_receipts", "source_owner_receipts", "row_receipts", "codec_sha256",
                           "model_tensor_sha256", "input_transform_sha256", "saved_preprocessing_sha256",
                           "complete_runtime_io_contract", "input_contract", "decoder_contract", "consistency_scope")
        binding = {name: deepcopy(opening[name]) for name in selected_fields}
        binding.update(runtime_plan_schema=opening["schema"], decoder_contract_id=contract,
            runtime_plan_sha256=hashlib.sha256(opening_raw).hexdigest(),
            runtime_plan_digest_encoding="json-sort-compact-ensure_ascii-false/v1",
            runtime_options_sha256=expected_runtime_options_sha256,
            runtime_options_digest_encoding="json-sort-compact-ensure_ascii-false/v1",
            source_binding_scope=_RUNTIME_SOURCE_SCOPES[_NORMATIVE_CONTRACTS.index(contract)],
            source_text_bytes_matched=True, selected_order_matched=True,
            physical_source_span_contract=contract == _NORMATIVE_CONTRACTS[2],
            source_artifact_receipts=deepcopy(opening.get("source_artifact_receipts")),
            source_cache_binding=deepcopy(opening.get("source_cache_binding")),
            historical_evidence_receipts=deepcopy(opening.get("historical_evidence_receipts")),
            historical_evidence_link_counts=deepcopy(opening.get("historical_evidence_link_counts")),
            historical_evidence_policy=deepcopy(opening.get("historical_evidence_policy")))
        return deepcopy(dict(schema=BOUND_NORMATIVE_SCHEMA, inspection=inspection, runtime_binding=binding,
            counts=inspection["counts"], opening_and_closing_preparations_matched=True,
            source_only_preparation_calls=2, targets_forwarded_to_preparation=False,
            targets_forwarded_to_model=False, model_load_performed=False, inference_executed=False,
            runtime_assets_read_by_existing_preparation=True,
            authority={**_AUTHORITY, "producer_execution_authenticated": False, "legal_source_edition_authenticated": False,
                       "reviewed_targets_established": False, "semantic_representability_verified": False},
            evaluation_scope="Existing runtime asset/source-byte consistency plus fixed lexical target inspection. Per-file and repeated endpoint fences, not an atomic snapshot. No reviewed target/source meaning, producer attestation, numerical quality, training eligibility or Lean admission."))
    except TargetCompatibilityError:
        raise
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as error:
        raise TargetCompatibilityError("cannot bind normative target inspection: " + str(error)) from error

__all__ = ["SCHEMA", "NORMATIVE_SCHEMA", "NORMATIVE_REQUEST_SCHEMA", "TargetCompatibilityError",
           "preflight_ir_cell_cached_targets", "inspect_normative_legal_ir_targets",
           "BOUND_NORMATIVE_SCHEMA", "preflight_normative_legal_ir_targets"]


COMPACT_ROLE_BOS_REQUEST_SCHEMA = "compact-role-bos-source-preflight-request/v1"
COMPACT_ROLE_BOS_SCHEMA = "compact-role-bos-source-preflight/v1"
_COMPACT_ROLE_PINS = (
    ("role", "legal_compact_content_role_trained_runtime_v1.py", 29650, "42dd29ad96e9ca8c28be071fe63292fca8b0155f7284eeac52c9306bfd921814"),
    ("source", "legal_compact_content_source_binding_v1.py", 29968, "7727ccc82edd771685831e97e614231190bc32a6229b442a1510bf7bc3f15955"),
    ("tokens", "legal_compact_content_tokens_v1.py", 24899, "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
    ("budget", "legal_compact_content_completion_budget_v1.py", 14328, "0d7362815dad5048652020d03967af4908123d74887e71e1823c62aa958783a7"),
    ("consumer", "legal_compact_content_role_budget_runtime_v1.py", 17993, "77325d00ed754679997fbe95caf70f14aa214d1b32e9994ac40f2c0ef739d59e"),
    ("copy", "legal_compact_content_prepared_runtime_v3.py", 53267, "a7d7cedfa482537ac76a9ccf9a49a79f6108e89268b02ca3b355abcfe774ec1e"),
)


def _compact_role_owners():
    import importlib
    import os
    import stat
    modules, observations = {}, []
    paths = [(None, Path(__file__).absolute(), None, None)] + [
        (key, Path(__file__).absolute().with_name(name), size, digest)
        for key, name, size, digest in _COMPACT_ROLE_PINS]
    for key, path, size, digest in paths:
        _require(path.resolve(strict=True) == path, "unaliased compact role owner required")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            before = os.fstat(stream.fileno())
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 4 * 1024**2,
                     "bounded single-link compact role owner required")
            raw = stream.read(before.st_size + 1)
            stream_stat = os.fstat(stream.fileno())
        witness = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns, item.st_nlink)
        actual = hashlib.sha256(raw).hexdigest()
        _require(len(raw) == before.st_size and witness(before) == witness(stream_stat) == witness(path.lstat())
                 and (size is None or (len(raw), actual) == (size, digest)), "compact role owner bytes changed")
        observations.append((dict(path=str(path), bytes=len(raw), sha256=actual), witness(before)))
        if key is not None:
            module = importlib.import_module(__package__ + "." + path.stem)
            _require(type(module.__file__) is str and Path(module.__file__).absolute() == path,
                     "compact role owner import origin differs")
            modules[key] = module
    return modules, observations


def _compact_role_request(request_raw, expected):
    _require(type(request_raw) is bytes and 0 < len(request_raw) <= 8 * 1024**2
             and runtime._hash(expected) and hashlib.sha256(request_raw).hexdigest() == expected,
             "bounded independently pinned compact role request required")
    value = json.loads(request_raw.decode("utf-8"), object_pairs_hook=routing._pairs,
                       parse_float=routing._float, parse_constant=routing._constant)
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop(); nodes += 1
        _require(depth <= 64 and nodes <= 100000, "compact role request exceeds structural bound")
        if type(item) is str: item.encode("utf-8")
        elif type(item) is dict: pending.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif type(item) is list: pending.extend((child, depth + 1) for child in item)
    _require(type(value) is dict and set(value) == {"schema", "max_new_tokens", "rows"}
             and value["schema"] == COMPACT_ROLE_BOS_REQUEST_SCHEMA, "closed compact role request required")
    _require(type(value["max_new_tokens"]) is int and 1 <= value["max_new_tokens"] <= 511,
             "compact role allowance must be a plain integer in 1..511")
    _require(type(value["rows"]) is list and 1 <= len(value["rows"]) <= 16, "one to 16 compact role rows required")
    ids, receipts = set(), {}
    for row in value["rows"]:
        _require(type(row) is dict and set(row) == {"id", "source_request", "expected_source_request_sha256",
            "input_id", "receipt_ref", "context_raw_utf8", "expected_context_sha256", "context_origin",
            "target_content_raw_utf8", "expected_target_content_sha256"}, "closed compact role row required")
        runtime._text(row["id"], 512, "compact role row ID")
        _require(row["id"] not in ids and type(row["source_request"]) is dict
                 and runtime._hash(row["expected_source_request_sha256"]), "distinct rows and pinned source requests required")
        ids.add(row["id"]); runtime._text(row["input_id"], 512, "compact role input ID")
        ref = row["receipt_ref"]
        _require(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"}
                 and type(ref["path"]) is str and 0 < len(ref["path"]) <= 4096
                 and Path(ref["path"]).is_absolute() and type(ref["bytes"]) is int
                 and 0 < ref["bytes"] <= 64 * 1024**2 and runtime._hash(ref["sha256"]), "closed bounded receipt reference required")
        _require(ref["path"] not in receipts or receipts[ref["path"]] == ref, "conflicting receipt path references")
        receipts[ref["path"]] = ref
        for field, expected_field, nullable in (("context_raw_utf8", "expected_context_sha256", False),
                ("target_content_raw_utf8", "expected_target_content_sha256", True)):
            text, digest = row[field], row[expected_field]
            if nullable and text is None: _require(digest is None, "null target requires null target pin"); continue
            _require(type(text) is str and 0 < len(text) <= 512 * 1024 and runtime._hash(digest), "bounded pinned UTF8 packet required")
            raw = text.encode("utf-8")
            _require(len(raw) <= 512 * 1024 and hashlib.sha256(raw).hexdigest() == digest, "compact role raw packet pin differs")
        _require(row["context_origin"] in ("authored_fixture", "target_derived_label", "caller_supplied_unverified"),
                 "declared context origin required")
    _require(sum(ref["bytes"] for ref in receipts.values()) <= 64 * 1024**2, "aggregate unique receipt bytes exceed 64 MiB")
    return value


def _compact_role_false(report):
    _require(type(report) is dict and type(report.get("authority")) is dict and report["authority"]
             and all(flag is False for flag in report["authority"].values())
             and all(type(report.get(key)) is int and report[key] == 0 for key in ("training_mask", "evaluation_gold_mask")),
             "compact role producer must preserve false authority and integer-zero masks")


def preflight_compact_role_bos_sources(request_raw, checkpoint, *, expected_request_sha256,
        expected_checkpoint_sha256, expected_policy_sha256, source_resolver):
    """Bind exact source receipts, intact role metadata and fixed-BOS budgets without generation."""
    failure = guard = None
    try:
        selected = _compact_role_request(request_raw, expected_request_sha256)
        _require(callable(source_resolver) and runtime._hash(expected_checkpoint_sha256)
                 and runtime._hash(expected_policy_sha256), "resolver and independent role/policy pins required")
        modules, observed = _compact_role_owners(); helper = modules["copy"]
        frozen = helper._copy(checkpoint, helper.MAX_CHECKPOINT_BYTES)
        checkpoint_token = helper._fingerprint(frozen, helper.MAX_CHECKPOINT_BYTES)
        _require(helper._digest(frozen, helper.MAX_CHECKPOINT_BYTES) == expected_checkpoint_sha256,
                 "complete compact role checkpoint SHA256 differs")
        request_token = _raw(selected, ascii=False)
        live_reports = []
        def guard():
            current, pins = _compact_role_owners()
            _require(pins == observed and all(current[key] is module for key, module in modules.items()),
                     "compact role dependency custody changed")
            _require(helper._fingerprint(checkpoint, helper.MAX_CHECKPOINT_BYTES) == checkpoint_token
                     == helper._fingerprint(frozen, helper.MAX_CHECKPOINT_BYTES)
                     and _raw(selected, ascii=False) == request_token, "compact role operation inputs changed")
            for report, token in live_reports:
                _require(helper._fingerprint(report, 16 * 1024**2) == token, "opening compact role report mutated")
        def inspect():
            guard(); offered = helper._copy(frozen, helper.MAX_CHECKPOINT_BYTES)
            report = modules["role"].inspect(offered, expected_checkpoint_sha256=expected_checkpoint_sha256,
                                           expected_policy_sha256=expected_policy_sha256)
            _require(helper._fingerprint(offered, helper.MAX_CHECKPOINT_BYTES) == checkpoint_token,
                     "role inspection mutated checkpoint input")
            guard(); return report
        def prepare(row):
            guard(); offered = deepcopy(row["source_request"]); receipt = deepcopy(row["receipt_ref"])
            report = modules["source"].prepare_compact_source_conditioning_v1(offered, receipt,
                expected_source_request_sha256=row["expected_source_request_sha256"], input_id=row["input_id"],
                source_resolver=source_resolver)
            _require(_raw(offered, ascii=False) == _raw(row["source_request"], ascii=False)
                     and _raw(receipt) == _raw(row["receipt_ref"]), "source preparation mutated arguments")
            guard(); return report
        guard(); opening_role = inspect()
        live_reports.append((opening_role, helper._fingerprint(opening_role, 16 * 1024**2)))
        _compact_role_false(opening_role)
        _require(opening_role["schema"] == modules["role"].INSPECT_SCHEMA and opening_role["profile"] == modules["role"].PROFILE
                 and all(type(opening_role[key]) is int and opening_role[key] == 0
                         for key in ("model_restore_count", "numerical_forward_count"))
                 and all(opening_role[key] is False for key in ("model_executed", "training_executed",
                         "optimizer_constructed", "optimizer_state_restored")), "pure role inspection contract differs")
        codec = modules["tokens"].build_compact_content_token_codec_v1()
        codec_sha = modules["tokens"].compact_content_token_codec_sha256(codec)
        live_reports.append((codec, helper._fingerprint(codec, 16 * 1024**2)))
        _require(opening_role["checkpoint_sha256"] == expected_checkpoint_sha256
                 and opening_role["objective_policy_sha256"] == expected_policy_sha256
                 and opening_role["codec_sha256"] == codec_sha and frozen["codec"] == codec,
                 "intact role checkpoint or fixed codec binding differs")
        consumer = modules["consumer"]
        _require(consumer.BOS_SCHEMA == "legal-role-budget-content-generation/v2"
                 and consumer.BOS_PROFILE == "bounded-bos-role-compact384-completion-budget-inference/v2"
                 and consumer.MAX_TOTAL_IDS == 512 and consumer.MAX_BOS_NEW_TOKENS == 511,
                 "fixed BOS consumer contract differs")
        opening, rows = [], []
        for row in selected["rows"]:
            report = prepare(row); opening.append(helper._copy(report, 16 * 1024**2))
            live_reports.append((report, helper._fingerprint(report, 16 * 1024**2)))
            _compact_role_false(report)
            source_input = row["source_request"]["input"]
            _require(report["schema"] == modules["source"].CONDITIONING_SCHEMA
                     and report["profile"] == modules["source"].CONDITIONING_PROFILE
                     and _raw(report["input"], ascii=False) == _raw(source_input, ascii=False)
                     and _raw(report["source_span"], ascii=False) == _raw(source_input["source"], ascii=False)
                     and report["source_sha256"] == hashlib.sha256(source_input["text"].encode("utf-8")).hexdigest()
                     and report["encoder_executed_by_adapter"] is False, "source producer/profile/input commitments differ")
            embedded = report["status"] == "embedded"
            _require(report["source_receipt_binding_verified"] is embedded
                     and report["source_bytes_verified"] is (report["status"] != "missing_input")
                     and ((type(report["conditioning"]) is list and len(report["conditioning"]) == 384
                           and all(type(number) is float and abs(number) <= 1e8 for number in report["conditioning"])
                           and runtime._hash(report["native_vector_bits_sha256"])
                           and helper._digest(report["conditioning"]) == report["conditioning_sha256"])
                          if embedded else report["conditioning"] is report["conditioning_sha256"]
                          is report["native_vector_bits_sha256"] is None), "source availability/vector commitments differ")
            _require(report["occurrence_id"] == row["id"] and report["input_id"] == row["input_id"]
                     and report["source_request_sha256"] == row["expected_source_request_sha256"]
                     and report["receipt"] == row["receipt_ref"]
                     and report["status"] in ("embedded", "missing_input", "token_limit_exceeded"), "source occurrence binding differs")
            context_raw = row["context_raw_utf8"].encode("utf-8")
            options = dict(expected_context_sha256=row["expected_context_sha256"], codec=deepcopy(codec), expected_codec_sha256=codec_sha)
            live_reports.append((options, helper._fingerprint(options, 16 * 1024**2)))
            guard(); prefix = modules["budget"].allowed_token_ids([1], context_raw,
                remaining_new_tokens=selected["max_new_tokens"], **options); guard()
            live_reports.append((prefix, helper._fingerprint(prefix, 16 * 1024**2)))
            _compact_role_false(prefix)
            _require(prefix["schema"] == modules["budget"].PREFIX_SCHEMA and prefix["policy"] == modules["budget"].POLICY
                     and prefix["offered_ids"] == [1] and prefix["remaining_new_tokens"] == selected["max_new_tokens"]
                     and prefix["codec_sha256"] == codec_sha and prefix["context_raw_sha256"] == row["expected_context_sha256"],
                     "fixed BOS prefix/context/budget commitments differ")
            target = dict(disposition="pending", error=None, total_ids=None, new_ids=None, within_allowance=None,
                original_content_raw_sha256=row["expected_target_content_sha256"], canonical_content_sha256=None, target_ids_sha256=None)
            if row["target_content_raw_utf8"] is not None:
                try:
                    encoded = modules["tokens"].encode_compact_content_tokens_v1(row["target_content_raw_utf8"].encode("utf-8"),
                        context_raw, expected_content_sha256=row["expected_target_content_sha256"], **options)
                except modules["tokens"].CompactContentTokensError as error:
                    target.update(disposition="not_encoded", error=dict(**{"class": type(error).__name__}, message=str(error)))
                else:
                    live_reports.append((encoded, helper._fingerprint(encoded, 16 * 1024**2)))
                    _compact_role_false(encoded)
                    ids = encoded["target_ids"]; total = len(ids)
                    _require(encoded["schema"] == modules["tokens"].ENCODING_SCHEMA
                             and encoded["status"] == "encoded_unreviewed_content"
                             and encoded["original_content_raw_sha256"] == row["expected_target_content_sha256"]
                             and encoded["context_raw_sha256"] == row["expected_context_sha256"]
                             and encoded["context_sha256"] == prefix["context_sha256"] and encoded["codec_sha256"] == codec_sha
                             and encoded["total_token_count"] == total and encoded["lexical_token_count"] == total - 2
                             and 2 <= total <= 512 and ids[0] == 1 and ids[-1] == 2
                             and all(type(item) is int and 0 <= item < 537 for item in ids)
                             and hashlib.sha256(encoded["canonical_content_raw_utf8"].encode("utf-8")).hexdigest()
                                 == encoded["content_sha256"], "encoded target/public producer commitments differ")
                    target.update(canonical_content_sha256=encoded["content_sha256"], target_ids_sha256=helper._digest(ids))
                    target.update(disposition="encoded", total_ids=total, new_ids=total - 1,
                                  within_allowance=total - 1 <= selected["max_new_tokens"])
                guard()
            fields = ("status", "occurrence_id", "input_id", "source_sha256", "source_span", "receipt",
                      "conditioning_sha256", "native_vector_bits_sha256")
            source = {name: deepcopy(report[name]) for name in fields}
            source["conditioning_available"] = report["status"] == "embedded"
            source.update({name: deepcopy(report[name]) for name in ("schema", "profile", "input", "source_request_sha256",
                "encoder_binding", "encoder_binding_sha256", "source_bytes_verified", "source_receipt_binding_verified",
                "encoder_executed_by_adapter")})
            source["source_report_sha256"] = helper._digest(report, 16 * 1024**2)
            rows.append(dict(id=row["id"], source=source, context_origin=row["context_origin"],
                context_raw_sha256=row["expected_context_sha256"], prefix_report=prefix, target=target))
        closing = [prepare(row) for row in selected["rows"]]; closing_role = inspect(); guard()
        _require(helper._fingerprint(closing) == helper._fingerprint(opening)
                 and helper._fingerprint(closing_role) == helper._fingerprint(opening_role),
                 "compact role opening/closing reports differ")
        counts = dict(rows=len(rows), embedded=sum(row["source"]["conditioning_available"] for row in rows))
        counts["unavailable"] = len(rows) - counts["embedded"]
        for name, disposition in (("pending_targets", "pending"), ("encoded_targets", "encoded"), ("not_encoded_targets", "not_encoded")):
            counts[name] = sum(row["target"]["disposition"] == disposition for row in rows)
        counts.update(targets_within_allowance=sum(row["target"]["within_allowance"] is True for row in rows),
                      targets_over_allowance=sum(row["target"]["within_allowance"] is False for row in rows))
        result = dict(schema=COMPACT_ROLE_BOS_SCHEMA, request_sha256=expected_request_sha256,
            checkpoint_sha256=expected_checkpoint_sha256, objective_policy_sha256=expected_policy_sha256,
            checkpoint_inspection=opening_role, rows=rows, counts=counts,
            consumer=dict(schema=consumer.BOS_SCHEMA, profile=consumer.BOS_PROFILE, prefix_ids=[1], prefix_origin="bos_seed",
                max_new_tokens=selected["max_new_tokens"], max_total_ids=512, max_report_bytes=16 * 1024**2,
                conditioning_dimension=384, vocabulary_size=537, codec_sha256=codec_sha),
            dependency_pins=[pin for pin, _ in observed], opening_and_closing_preparations_matched=True,
            source_only_preparation_calls=2 * len(rows), checkpoint_inspection_calls=2,
            targets_forwarded_to_runtime=False, generation_ready=False, execution_packet=None,
            model_restore_count=0, numerical_forward_count=0, encoder_executed=False, training_executed=False,
            authority={**_AUTHORITY, "conditioning_space_training_compatibility_verified": False,
                       "context_permission_verified": False, "source_encoder_authenticated": False},
            training_mask=0, evaluation_gold_mask=0,
            blockers=["conditioning_space_training_compatibility_unqualified", "context_permission_unverified"],
            limitations=["Source and repeated endpoint consistency are not atomic custody or runtime attestation.",
                "Role validation reads historical training targets; new reference targets are inspector-only.",
                "Native conditioning compatibility is unqualified, not proven mathematically incompatible.",
                "Context origin is a caller declaration, not inference permission; no statutory or Lean authority."])
        raw = helper._wire(result, 16 * 1024**2); guard(); return json.loads(raw)
    except TargetCompatibilityError as error:
        failure = error; raise
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as error:
        failure = TargetCompatibilityError("cannot preflight compact role BOS sources: " + str(error)); raise failure from error
    except BaseException as error:
        failure = error; raise
    finally:
        if guard is not None:
            try: guard()
            except BaseException:
                if failure is None: raise
                BaseException.add_note(failure, "A closing compact role source/input custody check also failed.")


__all__ += ["COMPACT_ROLE_BOS_REQUEST_SCHEMA", "COMPACT_ROLE_BOS_SCHEMA", "preflight_compact_role_bos_sources"]


# A separate singleton-prefix inspector.  No numerical or generation consumer
# is supplied, and the existing cached/normative/BOS APIs above stay intact.
COUNTED_PREFIX_SCHEMA = 'legal-counted-content-prefix-inspection/v1'
COUNTED_PREFIX_PROFILE = 'authored-counted28-singleton-prefix-inspection/v1'
MAX_COUNTED_PREFIX_INPUT_BYTES = 262144
MAX_COUNTED_PREFIX_REPORT_BYTES = 1048576
MAX_COUNTED_PREFIX_CONTEXT_BYTES = 65536
MAX_COUNTED_PREFIX_CODEC_BYTES = 32768
_COUNTED_PREFIX_SELF_PATH = Path(__file__).absolute()
_COUNTED_PREFIX_SELF_SHA = hashlib.sha256(_COUNTED_PREFIX_SELF_PATH.read_bytes()).hexdigest()
_COUNTED_PREFIX_OWNER_SHA = 'df91798d11e2b0da36afc75e0bc1a8b6d0a3d08bc255e7362d1c200e5e9baa13'
_COUNTED_PREFIX_CODEC_SHA = '8a1e8e0f8c6c2259b7c1040d3518974b1c84ac6d532521199f46a76b7d78dcd8'
_COUNTED_PREFIX_CONTEXT_SHA = 'e8bef8e39571c3cc319bbde14e66ae568df0e6bcd5844d3ad88c366b8b801a70'
_COUNTED_PREFIX_CONTENT_SHA = '399d384e4adc3b19b2632579a8c1ec50195ca77c1c741a5096331920da29131c'
_COUNTED_PREFIX_SEQUENCE_SHA = '379d20155e87e5d286e8ed9071ba687851aa29b23d46b507db2123f0710e4a08'
_COUNTED_PREFIX_SHA = re.compile(r'[0-9a-f]{64}\Z')
_COUNTED_PREFIX_TYPED_SPECS = (
    ('ipfs_datasets_py.logic.parsers', 'logic/parsers/__init__.py'),
    ('ipfs_datasets_py.logic.syntax_core', 'logic/syntax_core/__init__.py'),
    ('ipfs_datasets_py.logic.families.namespaces', 'logic/families/namespaces.py'),
    ('ipfs_datasets_py.logic.syntax_core.algebra', 'logic/syntax_core/algebra.py'),
    ('ipfs_datasets_py.logic.syntax_core.ast', 'logic/syntax_core/ast.py'),
    ('ipfs_datasets_py.logic.syntax_core.contracts', 'logic/syntax_core/contracts.py'),
    ('ipfs_datasets_py.logic.syntax_core.diagnostics', 'logic/syntax_core/diagnostics.py'),
    ('ipfs_datasets_py.logic.syntax_core.lexer', 'logic/syntax_core/lexer.py'),
    ('ipfs_datasets_py.logic.syntax_core.registry', 'logic/syntax_core/registry.py'),
    ('ipfs_datasets_py.logic.syntax_core.signatures', 'logic/syntax_core/signatures.py'),
    ('ipfs_datasets_py.logic.parsers.fol', 'logic/parsers/fol.py'),
)
_COUNTED_PREFIX_OWNER_SPEC = ('ipfs_datasets_py.logic.autoformal.legal_counted_frame_v1',
                              'logic/autoformal/legal_counted_frame_v1.py')
_COUNTED_PREFIX_FALSE = {**_AUTHORITY, **dict.fromkeys((
    'source_bound', 'source_semantics_verified', 'independently_reviewed', 'accepted', 'admitted',
    'semantic_graph_admitted', 'training_qualified', 'evaluation_gold_qualified', 'Lean_admitted',
    'source_dependence_established', 'permitted_inference_context_verified',
    'checkpoint_compatibility_verified', 'conditioning_space_training_compatibility_verified',
    'numerical_runtime_available', 'model_executed', 'training_executed',
), False)}
_COUNTED_PREFIX_LIMITATIONS = [
    'This inspector derives one existing authored singleton through the genuine counted request, projection and encoding owners; no caller target or identity sidecar is an input.',
    'Every admissible next token is forced by one fixed content/context pair. Grammar completion is source-independent and establishes no learned reconstruction or model convergence.',
    'The supplied counted context is target-derived declaration data. No independently permitted inference context, source-conditioned numerical head, checkpoint or generation runtime is supplied.',
    'Finite wrong or out-of-vocabulary ID sequences are retained as rejected data; malformed types, unsafe bounds, foreign codec and altered context are refused without truncation.',
    'A complete candidate is independently replayed through the public counted token decoder. This is typed syntax custody, not a complete statutory norm, reviewed legal meaning, eligibility or Lean admission.',
    'Known canonical source and sequential input/return fences do not attest arbitrary loaded bytecode, mutable globals, third-party libraries, atomic concurrency or a hermetic interpreter.',
]
_COUNTED_PREFIX_FIELDS = {
    'schema', 'profile', 'status', 'reason', 'offered_ids', 'allowed_token_ids',
    'matched_prefix_length', 'completion_tokens_remaining', 'remaining_token_slots',
    'max_sequence_tokens', 'canonical_sequence_token_count', 'canonical_sequence_sha256',
    'content_sha256', 'context_sha256', 'context_raw_sha256', 'codec_sha256',
    'profile_is_singleton', 'admissible_content_count', 'source_dependence_established',
    'context_origin', 'permitted_inference_context_verified', 'numerical_runtime_available',
    'checkpoint_compatibility_verified', 'complete_candidate', 'producer_pins', 'authority',
    'training_mask', 'evaluation_gold_mask', 'limitations',
}


def _counted_prefix_copy(value, maximum=None, *, allow_bytes=False):
    """Bound ordinary values before whole serialization or lazy operation imports."""
    maximum = MAX_COUNTED_PREFIX_REPORT_BYTES if maximum is None else maximum
    remaining, budget, active = 20000, maximum, set()

    def visit(item, depth):
        nonlocal remaining, budget
        remaining -= 1
        _require(remaining >= 0 and depth <= 64, 'bounded counted prefix structure required')
        if type(item) in (dict, list):
            _require(id(item) not in active and len(item) <= remaining,
                     'cyclic or oversized counted prefix metadata refused')
            active.add(id(item)); budget -= 2 + max(0, len(item) - 1)
            try:
                if type(item) is dict:
                    _require(all(type(key) is str for key in item), 'ordinary counted prefix keys required')
                    budget -= len(item)
                    result = {visit(key, depth + 1): visit(child, depth + 1) for key, child in item.items()}
                else:
                    result = [visit(child, depth + 1) for child in item]
            finally:
                active.remove(id(item))
        elif type(item) is bytes and allow_bytes:
            budget -= len(item); result = item
        elif type(item) is str:
            _require(len(item) <= maximum, 'bounded counted prefix text required')
            budget -= 2
            for character in item:
                code = ord(character)
                _require(code != 0 and not 0xD800 <= code <= 0xDFFF,
                         'ordinary non-NUL scalar UTF8 metadata required')
                budget -= (2 if character in '\"\\\b\f\n\r\t' else 6 if code < 32 else
                           1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)
                _require(budget >= 0, 'complete counted prefix byte bound exceeded')
            result = item
        elif item is None or type(item) is bool:
            budget -= 4 if item is None or item is True else 5; result = item
        elif type(item) is int:
            _require(-(1 << 63) < item < (1 << 63), 'bounded plain counted prefix integer required')
            budget -= len(str(item)); result = item
        else:
            raise TargetCompatibilityError('ordinary counted prefix values without floats required')
        _require(budget >= 0, 'complete counted prefix byte bound exceeded; no truncation')
        return result

    return visit(value, 0)


def _counted_prefix_wire(value, maximum=None):
    maximum = MAX_COUNTED_PREFIX_REPORT_BYTES if maximum is None else maximum
    captured = _counted_prefix_copy(value, maximum)
    raw = json.dumps(captured, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                     allow_nan=False).encode('utf-8')
    _require(len(raw) <= maximum, 'complete counted prefix JSON byte bound exceeded')
    return raw


def _counted_prefix_fingerprint(value, maximum=None):
    """Bound once, then hash type-separated structure and plain scalar encodings."""
    captured = _counted_prefix_copy(value, maximum, allow_bytes=True)
    result = hashlib.sha256()
    def visit(item):
        if type(item) is dict:
            result.update(b'd' + str(len(item)).encode() + b':')
            for key in sorted(item):visit(key); visit(item[key])
        elif type(item) is list:
            result.update(b'l' + str(len(item)).encode() + b':')
            for child in item:visit(child)
        else:
            # The complete copy has already refused foreign keys/containers,
            # unsafe integers, floats and unbounded or invalid scalar text.
            raw = item if type(item) is bytes else json.dumps(item, sort_keys=True,
                separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
            result.update((b'b' if type(item) is bytes else b'j') + str(len(raw)).encode() + b':' + raw)
    visit(captured)
    return result.hexdigest()


def _counted_prefix_pairs(rows):
    result = {}
    for key, value in rows:
        _require(key not in result, 'duplicate counted prefix context key refused')
        result[key] = value
    return result


def _counted_prefix_reject_number(_):
    raise TargetCompatibilityError('counted prefix context permits no float or nonfinite numbers')


def _counted_prefix_preflight(original):
    ids = original['prefix_ids']
    _require(type(ids) is list and len(ids) <= 512 and
             all(type(item) is int and -(1 << 63) < item < (1 << 63) for item in ids),
             'zero to512 bounded plain integer prefix IDs required; bools and truncation refused')
    _require(type(original['context_raw']) is bytes and
             0 < len(original['context_raw']) <= MAX_COUNTED_PREFIX_CONTEXT_BYTES,
             'bounded exact nonempty context bytes required')
    for field in ('expected_context_sha256', 'expected_codec_sha256'):
        _require(type(original[field]) is str and _COUNTED_PREFIX_SHA.fullmatch(original[field]),
                 'independent lowercase counted prefix pin required: ' + field)
    _require(hashlib.sha256(original['context_raw']).hexdigest() == original['expected_context_sha256'],
             'independent original counted context raw pin differs')
    _require(original['expected_codec_sha256'] == _COUNTED_PREFIX_CODEC_SHA,
             'exact selected counted28 codec pin required before operation imports')
    data = _counted_prefix_copy(original, MAX_COUNTED_PREFIX_INPUT_BYTES, allow_bytes=True)
    _require(type(data['codec']) is dict and hashlib.sha256(_counted_prefix_wire(
        data['codec'], MAX_COUNTED_PREFIX_CODEC_BYTES)).hexdigest() == _COUNTED_PREFIX_CODEC_SHA,
        'complete original counted28 codec differs')
    try:
        context = json.loads(data['context_raw'].decode('utf-8'), object_pairs_hook=_counted_prefix_pairs,
            parse_float=_counted_prefix_reject_number, parse_constant=_counted_prefix_reject_number)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise TargetCompatibilityError('duplicate-free bounded counted context JSON required') from error
    _require(type(context) is dict and hashlib.sha256(_counted_prefix_wire(
        context, MAX_COUNTED_PREFIX_CONTEXT_BYTES)).hexdigest() == _COUNTED_PREFIX_CONTEXT_SHA,
        'exact existing counted frame/signature/ordered-role context required before imports')
    return data


def _counted_prefix_source(path, expected=None):
    """Read only a fixed canonical path, never a path offered in a report."""
    import os
    import stat
    _require(path.is_absolute() and path.resolve(strict=True) == path,
             'known unaliased counted prefix source required')
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 4*1024**2,
             'bounded single-link regular counted prefix source required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        raw = os.read(fd, before.st_size + 1)
        closed = os.fstat(fd)
    finally:
        os.close(fd)
    after = path.lstat()
    identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_nlink,
                              item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    digest = hashlib.sha256(raw).hexdigest()
    _require(identity(before) == identity(opened) == identity(closed) == identity(after) and
             len(raw) == before.st_size and (expected is None or digest == expected),
             'known counted prefix producer changed')
    return digest, identity(before)


def _counted_prefix_root():
    root = _COUNTED_PREFIX_SELF_PATH.parents[3]
    _require(root.name == 'ipfs_datasets_py' and _COUNTED_PREFIX_SELF_PATH ==
             root/'logic/formalization/autoencoder/ir_cell_target_compatibility.py' and
             type(__file__) is str and Path(__file__).absolute() == _COUNTED_PREFIX_SELF_PATH,
             'canonical counted prefix compatibility owner origin required')
    return root


def _counted_prefix_origins(root):
    import sys
    for name, relative in (_COUNTED_PREFIX_OWNER_SPEC, *_COUNTED_PREFIX_TYPED_SPECS):
        module = sys.modules.get(name)
        if module is not None:
            _require(type(getattr(module, '__file__', None)) is str and
                     Path(module.__file__).absolute() == root/relative,
                     'known counted prefix operation owner origin differs')


def _counted_prefix_sources(root):
    result = {str(_COUNTED_PREFIX_SELF_PATH): _counted_prefix_source(
        _COUNTED_PREFIX_SELF_PATH, _COUNTED_PREFIX_SELF_SHA)}
    for name, relative in (_COUNTED_PREFIX_OWNER_SPEC, *_COUNTED_PREFIX_TYPED_SPECS):
        result[str(root/relative)] = _counted_prefix_source(root/relative,
            _COUNTED_PREFIX_OWNER_SHA if name == _COUNTED_PREFIX_OWNER_SPEC[0] else None)
    return result


def _counted_prefix_owners():
    import importlib
    root = _counted_prefix_root()
    _counted_prefix_origins(root)
    before = _counted_prefix_sources(root)
    counted = importlib.import_module(_COUNTED_PREFIX_OWNER_SPEC[0])
    _counted_prefix_origins(root)
    _require(_counted_prefix_sources(root) == before, 'counted prefix sources changed during owner import')
    return counted, root, before


def _counted_prefix_fence(owners, original, captured, commitment, witnesses=()):
    counted, root, before = owners
    _require(_counted_prefix_fingerprint(original, MAX_COUNTED_PREFIX_INPUT_BYTES) == commitment and
        _counted_prefix_fingerprint(captured, MAX_COUNTED_PREFIX_INPUT_BYTES) == commitment,
        'counted prefix original or detached inputs changed')
    _require(_counted_prefix_root() == root, 'counted prefix canonical package changed')
    _counted_prefix_origins(root)
    _require(_counted_prefix_sources(root) == before, 'counted prefix producer closure changed')
    for offered, detached, token in witnesses:
        _require(_counted_prefix_fingerprint(offered) == token and
                 _counted_prefix_fingerprint(detached) == token,
                 'genuine counted owner return changed during inspection')


def _counted_prefix_watch(value, witnesses):
    captured = _counted_prefix_copy(value)
    token = _counted_prefix_fingerprint(captured)
    witnesses.append((value, captured, token))
    return captured


def _counted_prefix_no_authority(value):
    if type(value) is dict:
        for name, child in value.items():
            if name == 'authority':
                _require(type(child) is dict and child and all(type(flag) is bool and flag is False
                         for flag in child.values()), 'counted prefix dependency authority must remain false')
            if name.endswith('_mask'):
                _require(type(child) is int and child == 0, 'counted prefix masks must remain integer zero')
            if name in {'checkpoint_compatibility_verified', 'numerical_head_compatible',
                        'permitted_inference_context_verified', 'source_dependence_established'}:
                _require(child is False, 'counted prefix grants no model or context compatibility')
            _counted_prefix_no_authority(child)
    elif type(value) is list:
        for child in value:_counted_prefix_no_authority(child)


def _counted_prefix_finish(report, fence):
    fence()
    _require(type(report) is dict and set(report) == _COUNTED_PREFIX_FIELDS,
             'closed counted prefix report required')
    token = _counted_prefix_fingerprint(report)
    result = _counted_prefix_copy(report)
    _counted_prefix_wire(result)
    _require(_counted_prefix_fingerprint(report) == token and
             _counted_prefix_fingerprint(result) == token,
             'complete counted prefix report changed during serialization')
    fence()
    return result


def inspect_counted_content_prefix_v1(prefix_ids, context_raw, *, expected_context_sha256,
                                      codec, expected_codec_sha256):
    """Inspect one offered prefix of the fixed authored language without a target input."""
    original = dict(prefix_ids=prefix_ids, context_raw=context_raw,
        expected_context_sha256=expected_context_sha256, codec=codec,
        expected_codec_sha256=expected_codec_sha256)
    data = _counted_prefix_preflight(original)
    commitment = _counted_prefix_fingerprint(data, MAX_COUNTED_PREFIX_INPUT_BYTES)
    owners = _counted_prefix_owners()
    counted, root, before = owners
    witnesses = []
    fence = lambda: _counted_prefix_fence(owners, original, data, commitment, witnesses)
    failure = None
    try:
        fence()
        fixed_codec = _counted_prefix_watch(counted.build_counted_frame_token_codec_v1(), witnesses)
        fence()
        _require(_counted_prefix_wire(fixed_codec) == _counted_prefix_wire(data['codec']) and
                 counted.counted_frame_token_codec_sha256(fixed_codec) == data['expected_codec_sha256'],
                 'genuine counted codec differs from independently committed original')
        fence()
        request = _counted_prefix_watch(counted.authored_counted_frame_request(), witnesses)
        fence()
        request_raw = _counted_prefix_wire(request)
        request_sha = hashlib.sha256(request_raw).hexdigest()
        projection = _counted_prefix_watch(counted.project_counted_frame_request_v1(request_raw,
            expected_request_sha256=request_sha), witnesses)
        fence()
        trusted_counted = {path: state[0] for path, state in before.items()
                           if path != str(_COUNTED_PREFIX_SELF_PATH)}
        _require(projection['producer_pins'] == trusted_counted and
                 projection['schema'] == 'legal-counted-compact-projection/v1' and
                 projection['profile'] == 'authored-at-most-three-many-sorted-compact/v1' and
                 projection['status'] == 'authored_counted_content_projected_unreviewed' and
                 projection['context_origin'] == 'target_derived_authored_declaration' and
                 projection['original_request_sha256'] == request_sha and
                 projection['original_expression_sha256'] == hashlib.sha256(_counted_prefix_wire(
                     request['expression'])).hexdigest() and
                 projection['counted_report']['request_sha256'] == request_sha and
                 _counted_prefix_wire(projection['counted_report']['request']) == request_raw and
                 _counted_prefix_wire(projection['counts']) == _counted_prefix_wire(
                     projection['counted_report']['counts']) == _counted_prefix_wire(dict(
                         nodes=49,quantifiers=6,membership_occurrences=4,equality_occurrences=6,variable_occurrences=24)),
                 'genuine counted projection changed its original declaration or producers')
        content_raw = _counted_prefix_wire(projection['content'])
        _require(hashlib.sha256(content_raw).hexdigest() == projection['content_sha256'] == _COUNTED_PREFIX_CONTENT_SHA and
                 hashlib.sha256(_counted_prefix_wire(projection['context'])).hexdigest() ==
                 projection['context_sha256'] == _COUNTED_PREFIX_CONTEXT_SHA,
                 'genuine counted projection changed singleton content/context')
        _counted_prefix_no_authority(projection)
        encoding = _counted_prefix_watch(counted.encode_counted_frame_tokens_v1(content_raw,
            data['context_raw'], expected_content_sha256=projection['content_sha256'],
            expected_context_sha256=data['expected_context_sha256'], codec=data['codec'],
            expected_codec_sha256=data['expected_codec_sha256']), witnesses)
        fence()
        sequence = encoding['target_ids']
        _require(type(sequence) is list and len(sequence) == 293 and
                 all(type(item) is int and 0 <= item < 28 for item in sequence) and
                 sequence[0] == 1 and sequence[-1] == 2 and
                 hashlib.sha256(_counted_prefix_wire(sequence)).hexdigest() == _COUNTED_PREFIX_SEQUENCE_SHA and
                 encoding['producer_pins'] == trusted_counted and
                 encoding['schema'] == 'legal-counted-compact-token-encoding/v1' and
                 encoding['profile'] == 'authored-at-most-three-many-sorted-compact/v1' and
                 encoding['status'] == 'encoded_unreviewed_counted_content' and
                 encoding['content_sha256'] == _COUNTED_PREFIX_CONTENT_SHA and
                 encoding['context_sha256'] == _COUNTED_PREFIX_CONTEXT_SHA and
                 encoding['context_raw_sha256'] == data['expected_context_sha256'] and
                 encoding['codec_sha256'] == data['expected_codec_sha256'] and
                 encoding['canonical_content_raw_utf8'].encode('utf-8') == content_raw and
                 type(encoding['total_token_count']) is int and encoding['total_token_count'] == len(sequence) and
                 type(encoding['lexical_token_count']) is int and encoding['lexical_token_count'] == 291 and
                 encoding['lexical_tokens'] == [fixed_codec['vocabulary'][index] for index in sequence[1:-1]] and
                 ''.join(encoding['lexical_tokens']).encode('utf-8') == content_raw and
                 _counted_prefix_wire(encoding['counts']) == _counted_prefix_wire(projection['counts']),
                 'genuine counted encoding changed the exact singleton lexical sequence')
        _counted_prefix_no_authority(encoding)
        ids = data['prefix_ids']
        matched = 0
        for actual, expected in zip(ids, sequence):
            if actual != expected:break
            matched += 1
        candidate = None
        if any(item < 0 or item >= 28 for item in ids):
            status, reason, allowed, needed = 'rejected', 'out_of_vocabulary_id', [], None
        elif matched != len(ids):
            status, reason, allowed, needed = 'rejected', 'prefix_mismatch', [], None
        elif len(ids) < len(sequence):
            status, reason, allowed, needed = 'prefix', None, [sequence[len(ids)]], len(sequence) - len(ids)
        else:
            status, reason, allowed, needed = 'complete', None, [], 0
            candidate = _counted_prefix_watch(counted.decode_counted_frame_tokens_v1(ids, data['context_raw'],
                expected_context_sha256=data['expected_context_sha256'], codec=data['codec'],
                expected_codec_sha256=data['expected_codec_sha256']), witnesses)
            fence()
            _require(candidate['schema'] == 'legal-counted-compact-token-candidate/v1' and
                     candidate['profile'] == 'authored-at-most-three-many-sorted-compact/v1' and
                     candidate['status'] == 'valid_candidate' and candidate['generated_ids'] == ids and
                     _counted_prefix_wire(candidate['framing']) == _counted_prefix_wire(dict(
                         bos_present=True,eos_terminal=True,token_ids_valid=True,interior_special_tokens=False,terminated=True)) and
                     candidate['producer_pins'] == trusted_counted and
                     candidate['content_sha256'] == _COUNTED_PREFIX_CONTENT_SHA and
                     candidate['context_sha256'] == _COUNTED_PREFIX_CONTEXT_SHA and
                     candidate['context_raw_sha256'] == data['expected_context_sha256'] and
                     candidate['codec_sha256'] == data['expected_codec_sha256'] and
                     candidate['canonical_content_raw_utf8'].encode('utf-8') == content_raw and
                     _counted_prefix_wire(candidate['prediction']) == _counted_prefix_wire(encoding['prediction']) and
                     _counted_prefix_wire(candidate['counts']) == _counted_prefix_wire(encoding['counts']) ==
                     _counted_prefix_wire(projection['counts']),
                     'complete offered counted prefix differs from genuine typed public decoding')
            _counted_prefix_no_authority(candidate)
        report = dict(schema=COUNTED_PREFIX_SCHEMA, profile=COUNTED_PREFIX_PROFILE, status=status,
            reason=reason, offered_ids=ids, allowed_token_ids=allowed, matched_prefix_length=matched,
            completion_tokens_remaining=needed, remaining_token_slots=512-len(ids), max_sequence_tokens=512,
            canonical_sequence_token_count=293, canonical_sequence_sha256=_COUNTED_PREFIX_SEQUENCE_SHA,
            content_sha256=_COUNTED_PREFIX_CONTENT_SHA, context_sha256=_COUNTED_PREFIX_CONTEXT_SHA,
            context_raw_sha256=data['expected_context_sha256'], codec_sha256=data['expected_codec_sha256'],
            profile_is_singleton=True, admissible_content_count=1, source_dependence_established=False,
            context_origin='target_derived_authored_declaration', permitted_inference_context_verified=False,
            numerical_runtime_available=False, checkpoint_compatibility_verified=False,
            complete_candidate=candidate, producer_pins={path: state[0] for path, state in before.items()},
            authority=dict(_COUNTED_PREFIX_FALSE), training_mask=0, evaluation_gold_mask=0,
            limitations=list(_COUNTED_PREFIX_LIMITATIONS))
        return _counted_prefix_finish(report, fence)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:fence()
        except BaseException:
            if failure is None:raise
            BaseException.add_note(failure, 'A closing counted prefix source/input check also failed.')


__all__ += ['COUNTED_PREFIX_SCHEMA', 'inspect_counted_content_prefix_v1']


# Explicit content-bound declarations for the vector boundary only. This does
# not widen existing registry lanes or modify any checkpoint/runtime contract.
CONDITIONING_SPACE_CONTRACT_SCHEMA = "legal-conditioning-space-contract/v1"
SOURCE_HEAD_CONDITIONING_SCHEMA = "legal-source-head-conditioning-inspection/v1"
MAX_CONDITIONING_CONTRACT_BYTES = 4 * 1024**2
_CONDITIONING_COMPONENTS = ("producer", "preprocessing", "ordered_transforms", "basis")
_CONDITIONING_FIELDS = {"schema", "artifact_sha256", "boundary", "dimension", "producer",
    "preprocessing", "ordered_transforms", "basis", "required_side_inputs"}
_CONDITIONING_AUTHORITY = dict.fromkeys(("source_producer_execution_authenticated",
    "checkpoint_compatible", "runtime_ready", "context_permission_verified",
    "training_qualified", "source_semantics_verified", "proof_authority",
    "model_convergence_proven"), False)


def _conditioning_contract(raw, expected, *, head):
    """Read bounded immutable JSON declarations without file or model access."""
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_CONDITIONING_CONTRACT_BYTES,
             "bounded exact UTF8 conditioning contract bytes required")
    _require(type(expected) is str and re.fullmatch(r"[0-9a-f]{64}", expected) is not None
             and hashlib.sha256(raw).hexdigest() == expected,
             "independent conditioning contract raw SHA256 differs")
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate conditioning contract JSON key")
            result[key] = value
        return result
    def constant(_):
        raise TargetCompatibilityError("nonfinite conditioning metadata is forbidden")
    def integer(token):
        _require(len(token) <= 20, "conditioning metadata integer exceeds bound")
        value = int(token)
        _require(-(1 << 63) <= value < (1 << 63), "conditioning metadata integer exceeds bound")
        return value
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                       parse_constant=constant, parse_int=integer)
    remaining = 50000
    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        _require(remaining >= 0 and depth <= 32, "conditioning metadata tree exceeds bound")
        if type(item) is dict:
            for key, child in item.items():
                _require(type(key) is str, "plain conditioning metadata keys required")
                visit(key, depth + 1); visit(child, depth + 1)
        elif type(item) is list:
            for child in item: visit(child, depth + 1)
        elif type(item) is str:
            item.encode("utf-8")
        elif type(item) is float:
            _require(float("-inf") < item < float("inf"), "finite conditioning metadata required")
        else:
            _require(item is None or type(item) in (bool, int), "plain conditioning metadata required")
    visit(value, 0)
    _require(type(value) is dict and set(value) == _CONDITIONING_FIELDS
             and value["schema"] == CONDITIONING_SPACE_CONTRACT_SCHEMA,
             "closed conditioning-space contract required")
    _require(type(value["artifact_sha256"]) is str
             and re.fullmatch(r"[0-9a-f]{64}", value["artifact_sha256"]) is not None,
             "conditioning artifact content declaration required")
    _require(value["boundary"] in ("encoder_output", "decoder_input")
             and (not head or value["boundary"] == "decoder_input"),
             "explicit encoder-output source or decoder-input boundary required")
    _require(type(value["dimension"]) is int and value["dimension"] in (8, 384, 768, 4096),
             "exact supported conditioning dimension required")
    def component(item):
        _require(type(item) is dict and type(item.get("schema")) is str
                 and 0 < len(item["schema"]) <= 128 and bool(item["schema"].strip()),
                 "full structured conditioning component declaration required")
    for name in ("producer", "preprocessing", "basis"):
        if value[name] is not None: component(value[name])
    for name in ("ordered_transforms", "required_side_inputs"):
        items = value[name]
        if name == "ordered_transforms" and items is None: continue
        _require(type(items) is list and len(items) <= 64,
                 "bounded complete ordered conditioning component list required")
        for item in items: component(item)
    return value


def inspect_source_head_conditioning_v1(source_contract_raw, head_contract_raw, *,
        expected_source_contract_sha256, expected_head_contract_sha256):
    """Compare independently pinned complete vector-contract declarations only.

    An encoder-output source needs an explicit adapter before comparison with a
    decoder input; no transform is inferred or applied. A decoder-input source
    must describe the actual ordered preprocessing at that boundary, including
    saved centering/scaling. A declared mismatch does not establish a model's
    mathematical inability to learn or exclude an existing qualified adapter.
    Matching this component never verifies the complete contextual model input.
    """
    try:
        source = _conditioning_contract(source_contract_raw,
            expected_source_contract_sha256, head=False)
        head = _conditioning_contract(head_contract_raw,
            expected_head_contract_sha256, head=True)
        digests = {"source": {}, "head": {}}
        mismatched = ["dimension"] if source["dimension"] != head["dimension"] else []
        unresolved = []
        for name in _CONDITIONING_COMPONENTS:
            for label, contract in (("source", source), ("head", head)):
                digests[label][name] = (None if contract[name] is None else
                    hashlib.sha256(_raw(contract[name], ascii=False)).hexdigest())
            if source[name] is None or head[name] is None:
                unresolved.append(name)
            elif _raw(source[name], ascii=False) != _raw(head[name], ascii=False):
                mismatched.append(name)
        if source["boundary"] != head["boundary"]:
            relation, disposition = "adapter_required", "adapter_required"
        elif mismatched:
            relation, disposition = "different", "refused_contract_mismatch"
        elif unresolved:
            relation, disposition = "unknown", "conditioning_contract_unresolved"
        else:
            relation, disposition = "matching", "declared_contract_match"
        result = dict(schema=SOURCE_HEAD_CONDITIONING_SCHEMA,
            source_contract_sha256=expected_source_contract_sha256,
            head_contract_sha256=expected_head_contract_sha256,
            source_artifact_sha256=source["artifact_sha256"],
            head_artifact_sha256=head["artifact_sha256"],
            source_boundary=source["boundary"], head_boundary=head["boundary"],
            source_dimension=source["dimension"], head_dimension=head["dimension"],
            relation=relation, disposition=disposition, mismatched_components=mismatched,
            unresolved_components=unresolved, component_sha256=digests,
            required_side_inputs={"source": source["required_side_inputs"],
                                  "head": head["required_side_inputs"]},
            comparison_scope="caller_declared_conditioning_component_only",
            full_decoder_input_verified=False, execution_ready=False,
            model_calls=0, training_calls=0, authority=dict(_CONDITIONING_AUTHORITY),
            training_mask=0, evaluation_gold_mask=0,
            limitations=[
                "Independent raw hashes bind declarations, not original producer execution or checkpoint validity.",
                "Compare exact ordered transforms at the decoder-input boundary; a raw encoder output requires an explicit adapter.",
                "A declared contract mismatch is not mathematical incompatibility or evidence that no suitable adapter exists.",
                "Missing producer, preprocessing, transform or basis content stays unresolved; width alone establishes no match.",
                "Required side inputs are retained declarations, not verified clauses, masks, raw text or permitted context.",
                "A matching vector contract grants no full input, model, training, semantic, proof or convergence qualification.",
            ])
        return json.loads(_raw(result, ascii=False))
    except TargetCompatibilityError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as error:
        raise TargetCompatibilityError("cannot inspect source/head conditioning: " + str(error)) from error


__all__ += ["CONDITIONING_SPACE_CONTRACT_SCHEMA", "SOURCE_HEAD_CONDITIONING_SCHEMA",
            "MAX_CONDITIONING_CONTRACT_BYTES", "inspect_source_head_conditioning_v1"]


# This opt-in raw-artifact profile does not alter existing file-reader limits.
NORMATIVE_CHECKPOINT_CONDITIONING_SCHEMA = "legal-normative-checkpoint-conditioning-inspection/v1"
MAX_NORMATIVE_CONDITIONING_ARTIFACT_BYTES = 32 * 1024**2
MAX_NORMATIVE_CONDITIONING_TOTAL_BYTES = 64 * 1024**2
_NORMATIVE_TRAINING_FIELDS = {"schema", "complete", "dimensions", "inputs_sha256", "plan_sha256",
    "bounded768_production_sha256", "historical8_production_sha256", "native768_cached_report",
    "source_aliases", "representation_kinds", "original384_paragraph_and_clause_views_preserved",
    "admitted", "downloads_performed", "encoder_context_increased", "formalized", "proof_authority",
    "qualified", "roundtrip_ok", "source_semantics_verified", "target_access", "targets_attached",
    "teacher_checkpoint_loaded", "training_executed"}
_NORMATIVE_TRAINING_FALSE = ("admitted", "downloads_performed", "encoder_context_increased", "formalized",
    "proof_authority", "qualified", "roundtrip_ok", "source_semantics_verified", "target_access",
    "targets_attached", "teacher_checkpoint_loaded", "training_executed")


def _normative_checkpoint_wire(value, dumps):
    """Check plain captured trees before callback-free canonical serialization."""
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop(); count += 1
        if depth > 70 or count > 4_000_000:
            raise TargetCompatibilityError("aggregate captured metadata exceeds structural bound")
        if type(item) is dict:
            if not all(type(key) is str for key in item):
                raise TargetCompatibilityError("plain captured metadata keys required")
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) not in (str, int, float, bool, type(None)):
            raise TargetCompatibilityError("plain captured metadata required")
    return dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                 allow_nan=False).encode("utf-8")


def inspect_normative_checkpoint_conditioning_v1(checkpoint_raw, preprocessing_raw, donor_raw,
        training_inputs_raw=None, *, expected_checkpoint_sha256, expected_preprocessing_sha256,
        expected_donor_sha256, expected_training_inputs_sha256=None, training_recipe_name):
    """Bind original retained head metadata and optional original TRAIN provenance.

    The existing contextual document/source validators run without opening a
    model. Entire original metadata is parsed, including historical training
    count-prior information. Neither label independence nor permission follows.
    Recipes are described only: no vector, normalization or adapter is executed.
    """
    dumps, loads = json.dumps, json.loads
    plain_wire = _normative_checkpoint_wire
    wire = lambda value: plain_wire(value, dumps)
    owner = normative.contextual
    def need(okay, message):
        if not okay: raise TargetCompatibilityError(message)
    def digest(value): return hashlib.sha256(wire(value)).hexdigest()
    raw = dict(checkpoint=checkpoint_raw, preprocessing=preprocessing_raw,
               donor=donor_raw, training_inputs=training_inputs_raw)
    pins = dict(checkpoint=expected_checkpoint_sha256, preprocessing=expected_preprocessing_sha256,
                donor=expected_donor_sha256, training_inputs=expected_training_inputs_sha256)
    recipe_owner = normative._RECIPES
    need(type(training_recipe_name) is str and training_recipe_name in ("normative-wording-zero", "normative-wording-ce")
         and type(recipe_owner) is dict and all(type(k) is str for k in recipe_owner)
         and set(recipe_owner) == {"normative-wording-zero", "normative-wording-ce"},
         "explicit supported normative training recipe required")
    recipe_owner_wire = wire(recipe_owner)
    need(recipe_owner_wire == wire({
        "normative-wording-zero": {"name": "normative-wording-zero", "weight": 0.0},
        "normative-wording-ce": {"name": "normative-wording-ce", "weight": 0.05}}),
        "original named normative recipe metadata differs")
    selected_recipe = loads(wire(recipe_owner[training_recipe_name]))
    selected_recipe_wire = wire(selected_recipe)
    total = 0
    for name, payload in raw.items():
        if name == "training_inputs" and payload is None:
            need(pins[name] is None, "absent original TRAIN bytes require absent pin")
            continue
        need(type(payload) is bytes and 0 < len(payload) <= MAX_NORMATIVE_CONDITIONING_ARTIFACT_BYTES,
             "bounded plain original artifact bytes required: " + name)
        need(type(pins[name]) is str and re.fullmatch(r"[0-9a-f]{64}", pins[name]) is not None
             and hashlib.sha256(payload).hexdigest() == pins[name], "original artifact raw SHA256 differs: " + name)
        total += len(payload)
    need(total <= MAX_NORMATIVE_CONDITIONING_TOTAL_BYTES, "original artifact aggregate byte bound exceeded")
    documents = checked = head_checked = None
    original_wire = checked_wire = head_wire = None
    validated_rows = []
    def guard():
        need(normative._RECIPES is recipe_owner and wire(recipe_owner) == recipe_owner_wire
             and wire(selected_recipe) == selected_recipe_wire, "original normative recipe metadata changed")
        need(wire(documents) == original_wire, "captured original metadata changed during inspection")
        if checked is not None:
            need(wire(checked) == checked_wire, "actual original document validator return changed")
        for returned, rows, contexts in validated_rows:
            need(type(returned) is dict and all(type(k) is str for k in returned)
                 and list(returned) == [row["id"] for row in rows], "actual original source validator return changed")
            for index, row in enumerate(rows):
                item = returned[row["id"]]
                need(type(item) is tuple and len(item) == 3 and type(item[0]) is int
                     and item[0] == index and item[1] is row and item[2] is contexts[row["id"]],
                     "actual original source row validator return changed")
        if head_checked is not None:
            need(wire(head_checked) == head_wire, "actual derived head contract validator return changed")
    failure = None
    try:
        documents = {name: None if payload is None else owner._json(payload) for name, payload in raw.items()}
        original_wire = wire(documents)
        cp, pp = documents["checkpoint"], documents["preprocessing"]
        need(type(cp) is dict and type(cp.get("dimension")) is int and cp["dimension"] in (384, 768),
             "retained normative384/768 checkpoint required")
        dimension = cp["dimension"]
        checked = owner._documents(cp, pp, documents["donor"], dimension,
                                    _selected_recipe=selected_recipe)
        expected_checked = {"checkpoint": cp, "preprocessing": pp,
            "donor_checkpoint": {key: documents["donor"][key] for key in ("codec", "config", "model_state")}}
        checked_wire = wire(checked)
        need(checked_wire == wire(expected_checked), "actual original document validator return differs")
        guard()
        need(digest(cp["codec"]) == _NORMATIVE_CODEC_SHA256, "original fixed normative32 codec differs")
        need(cp["lineage"]["teacher_checkpoint_sha256"] == expected_donor_sha256,
             "original raw donor lineage differs")
        training = documents["training_inputs"]
        representation = counts = None
        unresolved = ["original_training_inputs_unprovided"] if training is None else []
        if training is not None:
            need(type(training) is dict and set(training) == _NORMATIVE_TRAINING_FIELDS
                 and training["schema"] == "matched-dimension-source-inputs/v1"
                 and training["complete"] is True and training["original384_paragraph_and_clause_views_preserved"] is True
                 and all(training[k] is False for k in _NORMATIVE_TRAINING_FALSE),
                 "complete original matched-dimension source provenance required")
            need(type(training["inputs_sha256"]) is str and training["inputs_sha256"] == digest(
                {k: v for k, v in training.items() if k != "inputs_sha256"}), "original TRAIN root canonical digest differs")
            lanes = training["dimensions"]
            need(type(lanes) is dict and 1 <= len(lanes) <= 3 and set(lanes) <= {"8", "384", "768"}
                 and str(dimension) in lanes, "original selected dimension lane required")
            lane = lanes[str(dimension)]
            need(type(lane) is dict and set(lane) == {"train", "validation", "clause_cache",
                 "source_contexts", "context_binding", "representation"}, "closed original selected training lane required")
            need(digest(lane) == cp["lineage"]["input_provenance_sha256"] == pp["source_inputs_sha256"],
                 "original selected TRAIN provenance differs from checkpoint and preprocessing")
            need(wire(lane["representation"]) == wire(pp["representation"])
                 and wire(lane["context_binding"]) == wire(pp["source_binding"]),
                 "original TRAIN representation or context binding differs")
            contexts = lane["source_contexts"]
            need(type(contexts) is dict and set(contexts) == {"train", "validation"}
                 and digest(contexts) == lane["context_binding"]["contexts_sha256"],
                 "original complete source-context digest differs")
            for split, identity in (("train", "expected_training_ids"), ("validation", "forbidden_validation_ids")):
                rows = lane[split]
                need(type(rows) is list and [r["id"] for r in rows] == pp["paragraph_normalization"][identity],
                     "original ordered training/validation identities differ")
                returned = owner._source_rows(rows, contexts[split], dimension, [r["id"] for r in rows])
                validated_rows.append((returned, rows, contexts[split])); guard()
            need(digest(contexts["train"]) == pp["clause_normalization"]["training_contexts_sha256"],
                 "original TRAIN clause-normalization context join differs")
            representation = lane["representation"]
            need(type(representation) is dict and type(representation.get("dimension")) is int
                 and representation["dimension"] == dimension, "recorded training representation dimension differs")
            counts = {split: len(lane[split]) for split in ("train", "validation")}
        profile = None if representation is None else representation.get("profile_id")
        need(profile is None or (type(profile) is str and 0 < len(profile) <= 8192 and profile.strip()),
             "bounded recorded training profile required or null")
        if training is not None and profile is None: unresolved.append("recorded_training_profile_unprovided")
        transform = {"schema": "retained-normative-input-transform/v1", "recipe": cp["input_transform"]}
        paragraph = {"schema": "retained-normative-paragraph-feature-normalization/v1", "recipe": pp["paragraph_normalization"]}
        clause = {"schema": "retained-normative-clause-feature-normalization/v1", "recipe": pp["clause_normalization"]}
        head = dict(schema=CONDITIONING_SPACE_CONTRACT_SCHEMA, artifact_sha256=expected_checkpoint_sha256,
            boundary="decoder_input", dimension=dimension,
            producer=None if profile is None else {"schema": "retained-training-representation/v1", "representation": representation},
            preprocessing={"schema": "retained-normative-vector-preprocessing/v1",
                "projection_policy": pp.get("projection_policy"), "source_text_normalization": "unprovided"},
            ordered_transforms=[transform, paragraph],
            basis=None if profile is None else {"schema": "recorded-training-representation-basis/v1", "profile_id": profile, "dimension": dimension},
            required_side_inputs=[{"schema": "retained-normative-clause-conditioning/v1", "dimension": dimension,
                "max_source_clauses": 8, "ordered_transforms": [transform,
                    {"schema": "zero-pad-clause-context/v1", "slots": 8}, clause],
                "padding_mask": "source_derived_contiguous_nonempty_bool8"}])
        head_wire = wire(head)
        head_checked = _conditioning_contract(head_wire, hashlib.sha256(head_wire).hexdigest(), head=True)
        guard()
        report = dict(schema=NORMATIVE_CHECKPOINT_CONDITIONING_SCHEMA, artifact_raw_sha256=pins,
            dimension=dimension, training_recipe_name=training_recipe_name, checkpoint_documents_validated=True,
            original_training_provenance_sha256=cp["lineage"]["input_provenance_sha256"],
            original_training_provenance_bound=training is not None, training_representation=representation,
            training_counts=counts, training_artifact_parsed=training is not None,
            source_only_training_rows_checked=training is not None,
            head_contract=head_checked, head_contract_sha256=hashlib.sha256(head_wire).hexdigest(), unresolved=unresolved,
            execution_ready=False, full_decoder_input_verified=False, model_calls=0, training_calls=0,
            authority=dict.fromkeys(("source_producer_execution_authenticated", "checkpoint_compatible", "runtime_ready",
                "context_permission_verified", "target_independence_verified", "training_qualified", "source_semantics_verified",
                "proof_authority", "model_convergence_proven"), False), training_mask=0, evaluation_gold_mask=0,
            limitations=["Raw hashes bind original metadata bytes; producer execution, checkpoint numerical validity and source meaning are not authenticated.",
                "Entire supplied original metadata is parsed, including historical training count-prior information; no label-independence or permitted-context claim follows.",
                "Population digests bind provenance only. A recorded profile identifies a declared space, not certified encoder weights or learned compatibility.",
                "Paragraph and clause transform chains are separate retained recipes, not applied vectors or an executed adapter; no current inference source is accepted.",
                "Missing original TRAIN or null profile leaves producer and basis unresolved; no source/head, training, semantic, proof or convergence promotion follows."])
        output_raw = wire(report); output = loads(output_raw)
        guard()
        need(wire(output) == output_raw, "detached checkpoint conditioning report changed")
        return output
    except TargetCompatibilityError as error:
        failure = error; raise
    except (ValueError, TypeError, KeyError, OSError, UnicodeError, OverflowError, RecursionError) as error:
        failure = TargetCompatibilityError("cannot inspect normative checkpoint conditioning: " + str(error)); raise failure from error
    except BaseException as error:
        failure = error; raise
    finally:
        if documents is not None and original_wire is not None:
            try: guard()
            except BaseException:
                if failure is None: raise
                BaseException.add_note(failure, "A closing original checkpoint metadata check also failed.")


__all__ += ["NORMATIVE_CHECKPOINT_CONDITIONING_SCHEMA", "MAX_NORMATIVE_CONDITIONING_ARTIFACT_BYTES",
            "MAX_NORMATIVE_CONDITIONING_TOTAL_BYTES", "inspect_normative_checkpoint_conditioning_v1"]
