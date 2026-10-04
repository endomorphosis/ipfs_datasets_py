"""Open-vocabulary structural features of existing canonical Legal IR.

Complete canonical rule descriptors retain qualifier coassociation and duplicate
rule multiplicity. Shared local descriptors expose typed atoms without replacing
those whole-rule descriptors. This is a declaration-feature extractor, not a
new logic kernel, binder parser, semantics interpreter, or proof authority.

The exact dictionary is an audit artifact. Fixed-coordinate hashed counts are
an explicitly lossy numerical input with collision traces; no vocabulary is fit.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict

SCHEMA = "canonical-legal-structural-features/v1"
HASH_SCHEMA = "canonical-legal-hashed-structural-features/v1"
PROFILE = "canonical-rule-and-local-opaque-atoms/v1"
HASH_PROFILE = "sha256-positive-counts-fixed-coordinates/v1"
MAX_RULES = 64
MAX_QUALIFIERS_PER_FACET = 16
MAX_ATOM_CHARS = 256
MAX_FEATURES = 8192
MAX_FEATURE_BYTES = 8 * 1024 * 1024
CORE_FACETS = ("modality", "actor", "action", "object")
QUALIFIER_FACETS = ("conditions", "exceptions", "temporal")
CONNECTIVES = {"conditions": "all", "exceptions": "any", "temporal": "all_opaque_constraints"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeEncodeError) as error:
        raise ValueError("finite ordinary UTF-8 JSON required") from error
    _require(len(raw) <= MAX_FEATURE_BYTES, "structural feature artifact exceeds byte bound")
    return raw


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def structural_configuration():
    return {"schema": SCHEMA, "profile": PROFILE, "family_id": "deontic", "domain_id": "legal_ir",
            "owner": "CanonicalRoundTripIR@1", "owner_normalization": "sorted_rules_preserved_duplicates_sorted_unique_qualifier_lists",
            "token_identity": "sha256_sorted_compact_utf8_json_no_unicode_normalization",
            "qualifier_connectives": dict(CONNECTIVES), "atoms": "opaque_exact_strings",
            "complete_rule_coassociation": True, "binder_support": False, "native_semantics_verified": False,
            "max_rules": MAX_RULES, "max_qualifiers_per_facet": MAX_QUALIFIERS_PER_FACET,
            "max_atom_chars": MAX_ATOM_CHARS, "max_features": MAX_FEATURES, "max_artifact_bytes": MAX_FEATURE_BYTES,
            "vocabulary_fit": False, "model_calls": 0, "qualified": False}


def _canonical(target):
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR

    supplied = target.to_dict() if isinstance(target, CanonicalRoundTripIR) else target
    _require(type(supplied) is dict and set(supplied) == {"rules"} and type(supplied["rules"]) is list
             and 1 <= len(supplied["rules"]) <= MAX_RULES, "bounded existing canonical Legal IR required")
    _raw(supplied)
    for rule in supplied["rules"]:
        _require(type(rule) is dict and set(rule) == set(CORE_FACETS + QUALIFIER_FACETS), "closed seven-facet rule required")
        for facet in CORE_FACETS:
            atom = rule[facet]
            _require(type(atom) is str and len(atom) <= MAX_ATOM_CHARS, "bounded exact core atom required")
        for facet in QUALIFIER_FACETS:
            atoms = rule[facet]
            _require(type(atoms) is list and len(atoms) <= MAX_QUALIFIERS_PER_FACET
                     and all(type(atom) is str and len(atom) <= MAX_ATOM_CHARS for atom in atoms), "bounded exact qualifier atoms required")
    return CanonicalRoundTripIR.from_dict(supplied)


def prepare_structural_features(target, *, family_id="deontic"):
    """Extract source-free features, retaining the normalized owner's payload.

    No source, reference annotation, compiler/prover result, or learned asset is
    accepted. Dictionary names remain necessary coordinates for sparse counts;
    values alone are not a comparable open-vocabulary model input.
    """
    from ipfs_datasets_py.logic.formalization.features import FormalizationFeatures

    _require(type(family_id) is str and family_id == "deontic", "this structural profile supports deontic Legal IR only")
    canonical = _canonical(target)
    payload = canonical.to_dict()
    descriptors, counts = {}, Counter()

    def add(kind, **fields):
        descriptor = {"profile": PROFILE, "family_id": family_id, "kind": kind, **fields}
        name = "syntax.term." + _digest(descriptor)
        _require(name not in descriptors or descriptors[name] == descriptor, "descriptor digest collision; exact names cannot be merged")
        descriptors[name] = descriptor
        counts[name] += 1
        _require(len(counts) <= MAX_FEATURES, "structural feature count exceeds bound")

    add("family")
    for rule in payload["rules"]:
        core = {facet: rule[facet] for facet in CORE_FACETS}
        add("complete_rule", rule=rule)
        add("core_tuple", core=core)
        for facet in CORE_FACETS:
            add("typed_atom", facet=facet, atom=rule[facet])
        for facet in QUALIFIER_FACETS:
            add("qualifier_list", facet=facet, connective=CONNECTIVES[facet], atoms=rule[facet])
            for atom in rule[facet]:
                add("typed_atom", facet=facet, atom=atom)
                add("core_qualifier", core=core, facet=facet, atom=atom)
    declaration_digest = _digest(payload)
    envelope = FormalizationFeatures.from_values(
        sample_id="canonical-form-" + declaration_digest[:24], domain="legal_ir",
        declaration_digest="sha256:" + declaration_digest, features=dict(counts),
        extractor_id="canonical_legal_structure", extractor_version="v1")
    configuration = structural_configuration()
    record = {"schema": SCHEMA, "profile": PROFILE, "configuration": configuration,
              "feature_space_id": "canonical-legal-structure:sha256:" + _digest(configuration),
              "family_id": family_id, "domain_id": "legal_ir", "canonical_ir": payload,
              "canonical_ir_cid": canonical.ir_cid, "declaration_sha256": declaration_digest,
              "feature_dictionary": [{"name": name, "count": counts[name], "descriptor": descriptors[name]}
                                     for name in sorted(counts)],
              "numeric_envelope": envelope.to_dict(), "unique_features": len(counts), "total_occurrences": sum(counts.values()),
              "exact_preservation_scope": "normalized_seven_facet_rule_multiset_with_opaque_atoms",
              "sparse_values_without_names_are_shared_coordinates": False,
              "vocabulary_fit": False, "binder_semantics_inferred": False, "native_semantics_verified": False,
              "source_fidelity_established": False, "proof_authority": False, "qualified": False}
    record["content_sha256"] = _digest(record)
    return record


def validate_structural_features(record):
    """Reject forged feature/dictionary content by rebuilding from owner IR."""
    _require(type(record) is dict and record.get("schema") == SCHEMA
             and "canonical_ir" in record and "family_id" in record, "structural feature schema required")
    _require(_raw(record) == _raw(prepare_structural_features(record["canonical_ir"], family_id=record["family_id"])),
             "structural features differ from the exact canonical declaration")
    return record


def restore_structural_ir(record):
    """Restore complete-rule occurrences from the feature dictionary itself."""
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR

    validate_structural_features(record)
    rules = [item["descriptor"]["rule"] for item in record["feature_dictionary"]
             if item["descriptor"]["kind"] == "complete_rule" for _ in range(item["count"])]
    restored = CanonicalRoundTripIR.from_dict({"rules": rules}).to_dict()
    _require(restored == record["canonical_ir"], "whole-rule features do not restore the owner declaration")
    return restored


def encode_structural_features(features, *, dimension=2048, seed=0):
    """Hash counts to fixed coordinates, retaining all modulo collision traces.

    These positive counts are a lossy baseline, not a trained embedding. The
    coordinate identity is shared across declarations and independent of their
    audit IDs or train/development membership.
    """
    validate_structural_features(features)
    _require(type(dimension) is int and dimension in (2048, 4096), "structural hash dimension must be 2048 or 4096")
    _require(type(seed) is int and 0 <= seed < 2**31, "bounded integer structural hash seed required")
    coordinate_config = {"profile": HASH_PROFILE, "structural_space_id": features["feature_space_id"],
                         "dimension": dimension, "seed": seed, "counts": "positive_unnormalized_integer_sum",
                         "recipe": "big_endian_sha256_sorted_compact_json_profile_seed_feature_name_mod_dimension"}
    buckets, trace = defaultdict(list), []
    for item in features["feature_dictionary"]:
        hashed = hashlib.sha256(_raw({"profile": HASH_PROFILE, "seed": seed, "feature_name": item["name"]})).digest()
        index = int.from_bytes(hashed, "big") % dimension
        entry = {"name": item["name"], "index": index, "count": item["count"]}
        buckets[index].append(entry)
        trace.append(entry)
    sparse = [{"index": index, "value": sum(item["count"] for item in entries)} for index, entries in sorted(buckets.items())]
    collisions = [{"index": index, "distinct_features": len(entries), "features": entries}
                  for index, entries in sorted(buckets.items()) if len(entries) > 1]
    record = {"schema": HASH_SCHEMA, "coordinate_configuration": coordinate_config,
              "feature_space_id": "canonical-legal-structure-hash:sha256:" + _digest(coordinate_config),
              "structural_features_sha256": features["content_sha256"], "declaration_sha256": features["declaration_sha256"],
              "dimension": dimension, "seed": seed, "sparse_counts": sparse, "nonzero_coordinates": len(sparse),
              "coordinate_values_sha256": _digest(sparse), "token_trace": trace, "collision_buckets": collisions,
              "distinct_feature_collision_pairs": sum(len(entries) * (len(entries) - 1) // 2 for entries in buckets.values()),
              "total_occurrences": features["total_occurrences"], "lossless": False, "vocabulary_fit": False,
              "trained_embedding": False, "source_fidelity_established": False, "proof_authority": False, "qualified": False}
    record["content_sha256"] = _digest(record)
    return record


def validate_hashed_features(record, structural_features):
    _require(type(record) is dict and record.get("schema") == HASH_SCHEMA
             and "dimension" in record and "seed" in record, "hashed structural feature schema required")
    expected = encode_structural_features(structural_features, dimension=record["dimension"], seed=record["seed"])
    _require(_raw(record) == _raw(expected), "hashed coordinates or collision traces differ from the declared recipe")
    return record
