"""Opt-in observed-TRAIN literal alias consistency for anchored candidates.

Fitting aggregates caller-declared TRAIN anchor correspondences. Inference
checks each candidate's exact source occurrence against that separately pinned
profile; it neither constructs an answer nor consults query reference IR.
Known alias agreement is not source fidelity. Missing aliases and collisions
remain unassessed, and consistent wrong TRAIN correspondences can pass.
"""
from __future__ import annotations

import hashlib
import json

from . import canonical_byte_codec as byte_codec

PROFILE_SCHEMA = "canonical-observed-train-alias-profile/v1"
BINDING_SCHEMA = "canonical-source-symbol-bindings/v1"
NORMALIZATION = "unicode-casefold-whitespace-collapse-no-lexical-expansion/v1"
CHECKSUM_RECIPE = "sha256_canonical_sorted_compact_UTF8_JSON_without_content_sha256"
MAX_EXAMPLES = 256
MAX_ENTRIES = 4096
MAX_PROFILE_BYTES = 2 * 1024 * 1024
MAX_SYMBOLS_PER_ALIAS = 256
MAX_ANCHORS_PER_EXAMPLE = 196
MAX_OBSERVATIONS = MAX_EXAMPLES * MAX_ANCHORS_PER_EXAMPLE
MAX_NORMALIZED_CHARS = 3 * byte_codec.MAX_SOURCE_CHARS
_FACETS = ("action", "actor", "conditions", "exceptions", "modality", "object", "temporal")
_FALSE = {field: False for field in (
    "model_executed", "prover_executed", "source_fidelity_established", "qualified",
    "proof_authority", "accepted", "independent_semantic_review_completed")}
_PROFILE_FIELDS = {"schema", "normalization", "checksum_recipe", "training_manifest_sha256",
                   "training_pair_count", "training_anchor_count", "alias_entry_count",
                   "ambiguous_alias_count", "entries", "training_supervision_consumed",
                   "query_reference_accessed", "correspondence_origin", "fit_operation",
                   "semantic_scope", "examples_persisted", "content_sha256", *_FALSE}
_ENTRY_FIELDS = {"facet", "normalized_literal", "canonical_symbols", "observation_count"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("strict finite UTF8 JSON required") from error


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _seal(value):
    return {**value, "content_sha256": _digest(value)}


def _hash(value, field):
    _require(type(value) is str and len(value) == 64
             and all(character in "0123456789abcdef" for character in value),
             field + " must be lowercase SHA256")


def _text(value, maximum, field, *, allow_blank=False):
    _require(type(value) is str and (allow_blank or bool(value.strip())) and len(value) <= maximum,
             field + " must be bounded " + ("possibly blank " if allow_blank else "nonblank ") + "text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(field + " must be valid UTF8") from error
    return value


def normalize_literal(surface):
    """Casefold and collapse whitespace only; preserve punctuation and words."""
    _text(surface, byte_codec.MAX_SOURCE_CHARS, "literal surface", allow_blank=True)
    return " ".join(surface.casefold().split())


def _profile_body(entries, manifest, count, anchors):
    return {"schema": PROFILE_SCHEMA, "normalization": NORMALIZATION,
            "checksum_recipe": CHECKSUM_RECIPE, "training_manifest_sha256": manifest,
            "training_pair_count": count, "training_anchor_count": anchors,
            "alias_entry_count": len(entries),
            "ambiguous_alias_count": sum(len(entry["canonical_symbols"]) > 1 for entry in entries),
            "entries": entries, "training_supervision_consumed": True,
            "query_reference_accessed": False,
            "correspondence_origin": "caller_declared_TRAIN_exact_anchor_correspondences",
            "fit_operation": "deterministic_alias_aggregation_without_model_training",
            "semantic_scope": "observed_literal_facet_symbol_agreement_only",
            "examples_persisted": False, **_FALSE}


def fit_profile(training_examples):
    """Aggregate exact TRAIN anchor labels without lexical or grammar expansion.

    The caller must authenticate the cohort's TRAIN split and supervision masks.
    This constructor binds the exact validated inputs but cannot independently
    authenticate that external split. Repeated source texts retain all observed
    correspondences; conflicting symbols become explicitly ambiguous aliases.
    """
    _require(type(training_examples) in (list, tuple) and 1 <= len(training_examples) <= MAX_EXAMPLES,
             "one to 256 caller-declared TRAIN examples required")
    ids, examples, observed = set(), [], {}
    anchor_count = 0
    for row in training_examples:
        _require(type(row) is dict and set(row) == {"id", "source_text", "proposal"},
                 "closed TRAIN anchor example schema required")
        identity = _text(row["id"], 512, "TRAIN example id")
        _require(identity not in ids, "TRAIN example IDs must be unique")
        ids.add(identity)
        proposal = byte_codec.validate_proposal(row["proposal"], row["source_text"])
        examples.append({"id": identity, "source_text": row["source_text"], "proposal": proposal})
        for anchor in proposal["anchors"]:
            literal = normalize_literal(anchor["source_text"])
            _require(bool(literal), "TRAIN anchor literal cannot be blank")
            key = (anchor["facet"], literal)
            if key not in observed:
                _require(len(observed) < MAX_ENTRIES, "TRAIN alias entry bound exceeded; no truncation performed")
                observed[key] = {"symbols": set(), "count": 0}
            item = observed[key]
            item["symbols"].add(anchor["canonical_symbol"])
            _require(len(item["symbols"]) <= MAX_SYMBOLS_PER_ALIAS, "TRAIN alias collision set exceeds bound")
            item["count"] += 1
            anchor_count += 1
            _require(anchor_count <= MAX_OBSERVATIONS, "TRAIN anchor observation bound exceeded")
    entries = [{"facet": facet, "normalized_literal": literal,
                "canonical_symbols": sorted(observed[(facet, literal)]["symbols"]),
                "observation_count": observed[(facet, literal)]["count"]}
               for facet, literal in sorted(observed)]
    profile = _seal(_profile_body(entries, _digest(examples), len(examples), anchor_count))
    _require(len(_raw(profile)) <= MAX_PROFILE_BYTES, "alias profile exceeds byte bound; no truncation performed")
    return profile


def validate_profile(profile, *, expected_profile_sha256=None):
    """Check a detached closed profile and optional externally supplied identity.

    The pin names ``profile['content_sha256']`` under CHECKSUM_RECIPE, not file
    bytes or the hash of the full sealed object. Internal validation alone does
    not authenticate a claimed TRAIN manifest or its semantic correspondences.
    """
    _require(type(profile) is dict and set(profile) == _PROFILE_FIELDS, "closed TRAIN alias profile required")
    _require(len(_raw(profile)) <= MAX_PROFILE_BYTES, "alias profile exceeds byte bound")
    _hash(profile["training_manifest_sha256"], "training_manifest_sha256")
    _hash(profile["content_sha256"], "profile content_sha256")
    count, anchors = profile["training_pair_count"], profile["training_anchor_count"]
    _require(type(count) is int and 1 <= count <= MAX_EXAMPLES, "bounded TRAIN pair count required")
    _require(type(anchors) is int and 3 * count <= anchors <= MAX_ANCHORS_PER_EXAMPLE * count,
             "complete bounded TRAIN anchor count required")
    entries = profile["entries"]
    _require(type(entries) is list and 1 <= len(entries) <= MAX_ENTRIES, "bounded nonempty alias entries required")
    detached, keys, observed = [], [], 0
    facet_counts = dict.fromkeys(_FACETS, 0)
    for entry in entries:
        _require(type(entry) is dict and set(entry) == _ENTRY_FIELDS, "closed alias entry required")
        facet = entry["facet"]
        _require(type(facet) is str and facet in _FACETS, "known exact canonical facet required")
        literal = _text(entry["normalized_literal"], MAX_NORMALIZED_CHARS, "normalized literal")
        _require(literal == " ".join(literal.casefold().split()), "alias literal differs from versioned normalization")
        symbols = entry["canonical_symbols"]
        _require(type(symbols) is list and 1 <= len(symbols) <= MAX_SYMBOLS_PER_ALIAS,
                 "bounded nonempty canonical alias symbol set required")
        for symbol in symbols:
            _text(symbol, byte_codec.MAX_ATOM_CHARS, "canonical alias symbol")
            _require(facet != "modality" or symbol in ("O", "P", "F"), "modality alias symbol must be O, P or F")
        _require(symbols == sorted(set(symbols)), "alias symbols must already be sorted and unique")
        observations = entry["observation_count"]
        _require(type(observations) is int and len(symbols) <= observations <= MAX_OBSERVATIONS,
                 "bounded exact alias observation count required")
        observed += observations
        facet_counts[facet] += observations
        keys.append((facet, literal))
        detached.append({"facet": facet, "normalized_literal": literal,
                         "canonical_symbols": list(symbols), "observation_count": observations})
    _require(keys == sorted(set(keys)), "alias entries must follow sorted unique facet/literal keys")
    _require(observed == anchors, "alias observation sum differs from TRAIN anchor count")
    _require(all(facet_counts[facet] == count for facet in ("actor", "action", "modality")),
             "complete TRAIN actor/action/modality observation counts differ")
    _require(facet_counts["object"] <= count and all(facet_counts[facet] <= 64 * count
             for facet in ("conditions", "exceptions", "temporal")), "TRAIN facet observation bounds differ")
    expected = _seal(_profile_body(detached, profile["training_manifest_sha256"], count, anchors))
    _require(_raw(profile) == _raw(expected), "alias profile differs from closed normalized content and checksum")
    if expected_profile_sha256 is not None:
        _hash(expected_profile_sha256, "expected_profile_sha256")
        _require(expected["content_sha256"] == expected_profile_sha256, "alias profile differs from separately pinned identity")
    return expected


def assess_bindings(source_text, proposal, profile, *, expected_profile_sha256=None):
    """Assess candidate leaves against observed aliases; never repair an answer."""
    candidate = byte_codec.validate_proposal(proposal, source_text)
    aliases = validate_profile(profile, expected_profile_sha256=expected_profile_sha256)
    table = {(entry["facet"], entry["normalized_literal"]): entry["canonical_symbols"]
             for entry in aliases["entries"]}
    leaves, counts = [], {"matched_single_alias": 0, "known_alias_mismatch": 0,
                         "unknown_literal": 0, "ambiguous_alias": 0}
    for anchor in candidate["anchors"]:
        literal = normalize_literal(anchor["source_text"])
        recognized = table.get((anchor["facet"], literal), [])
        if not recognized:
            outcome = "unknown_literal"
        elif len(recognized) > 1:
            outcome = "ambiguous_alias"
        elif anchor["canonical_symbol"] != recognized[0]:
            outcome = "known_alias_mismatch"
        else:
            outcome = "matched_single_alias"
        counts[outcome] += 1
        leaves.append({"field_path": anchor["field_path"], "facet": anchor["facet"],
                       "start": anchor["start"], "end": anchor["end"],
                       "source_text": anchor["source_text"], "normalized_literal": literal,
                       "claimed_symbol": anchor["canonical_symbol"], "recognized_symbols": list(recognized),
                       "outcome": outcome})
    outcome = ("binding_inconsistent" if counts["known_alias_mismatch"] else
               "binding_unassessed" if counts["unknown_literal"] or counts["ambiguous_alias"] else
               "binding_consistent")
    return _seal({"schema": BINDING_SCHEMA, "checksum_recipe": CHECKSUM_RECIPE,
                  "source_sha256": candidate["source_sha256"], "proposal_sha256": _digest(candidate),
                  "profile_sha256": aliases["content_sha256"], "normalization": NORMALIZATION,
                  "outcome": outcome, "leaf_count": len(leaves), "leaf_outcome_counts": counts,
                  "leaves": leaves, "profile_training_supervision_consumed": True,
                  "query_reference_accessed": False, "target_access": False,
                  "target_access_scope": "query_reference_only",
                  "proposal_input_scope": "model_candidate_not_reference",
                  "assessment_scope": "per_leaf_observed_TRAIN_literal_alias_agreement",
                  "proposal_changed": False, "canonical_ir_repaired": False,
                  "training_executed": False, **_FALSE})


def validate_bindings(receipt, source_text, proposal, profile, *, expected_profile_sha256=None):
    """Recompute the exact detached alias assessment and reject resealed changes."""
    _require(type(receipt) is dict and receipt.get("schema") == BINDING_SCHEMA, "binding assessment schema required")
    expected = assess_bindings(source_text, proposal, profile, expected_profile_sha256=expected_profile_sha256)
    _require(_raw(receipt) == _raw(expected), "binding assessment differs from exact candidate/profile recomputation")
    return expected


__all__ = ["normalize_literal", "fit_profile", "validate_profile", "assess_bindings", "validate_bindings"]
