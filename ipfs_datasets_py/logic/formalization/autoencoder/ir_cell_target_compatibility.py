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
