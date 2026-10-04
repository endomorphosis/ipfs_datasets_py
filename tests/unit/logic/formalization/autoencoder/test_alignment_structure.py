"""Open-vocabulary formal features retain canonical structure before hashing."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from copy import deepcopy

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_structure as subject
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CanonicalRoundTripIR,
    CanonicalRule,
)


def _target(*rules):
    return CanonicalRoundTripIR(tuple(rules or (_rule(),))).to_dict()


def _rule(**changes):
    fields = {"modality": "O", "actor": "clerk", "action": "retain", "object": "filing",
              "conditions": ("application_complete",), "exceptions": ("court_order",),
              "temporal": ("within_48_hours",)}
    fields.update(changes)
    return CanonicalRule(**fields)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def test_preparation_preserves_canonical_rule_order_and_facet_set_identity():
    first = _rule(modality="O", conditions=("fees_paid", "application_complete", "fees_paid"))
    second = _rule(modality="P", actor="officer", action="audit")
    left = _target(first, second)
    right = _target(second, _rule(conditions=("application_complete", "fees_paid")))
    assert left == right
    assert subject.prepare_structural_features(left) == subject.prepare_structural_features(right)


def test_duplicate_whole_rules_retain_multiplicity():
    once = subject.prepare_structural_features(_target(_rule()))
    twice = subject.prepare_structural_features(_target(_rule(), _rule()))
    assert once != twice
    assert subject.encode_structural_features(once) != subject.encode_structural_features(twice)


def test_same_global_facet_bags_do_not_erase_rule_local_coassociation():
    left = _target(_rule(conditions=("application_complete",), exceptions=("court_order",)),
                   _rule(conditions=("fees_paid",), exceptions=("legal_hold",)))
    right = _target(_rule(conditions=("application_complete",), exceptions=("legal_hold",)),
                    _rule(conditions=("fees_paid",), exceptions=("court_order",)))
    assert left != right
    for facet in ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal"):
        def bag(target, facet=facet):
            return sorted(value for rule in target["rules"]
                          for value in (rule[facet] if type(rule[facet]) is list else [rule[facet]]))
        assert bag(left) == bag(right)
    assert subject.prepare_structural_features(left) != subject.prepare_structural_features(right)


def test_unknown_atoms_remain_distinct_before_any_compression():
    left = subject.prepare_structural_features(_target(_rule(conditions=("new_condition_a",))))
    right = subject.prepare_structural_features(_target(_rule(conditions=("new_condition_b",))))
    assert left != right
    assert "new_condition_a" in _json(left)
    assert "new_condition_b" in _json(right)


def test_empty_object_and_facet_are_explicit_canonical_values():
    blank = subject.prepare_structural_features(_target(_rule(object="", conditions=(), exceptions=(), temporal=())))
    present = subject.prepare_structural_features(_target(_rule(object="filing", conditions=(), exceptions=(), temporal=())))
    assert blank != present
    missing = _target(_rule(object="", conditions=(), exceptions=(), temporal=()))
    del missing["rules"][0]["object"]
    with pytest.raises(ValueError):
        subject.prepare_structural_features(missing)


def test_delimiters_and_unicode_do_not_alias_exact_atom_boundaries():
    left = subject.prepare_structural_features(_target(_rule(actor="a|b", action="c", conditions=("café",))))
    right = subject.prepare_structural_features(_target(_rule(actor="a", action="b|c", conditions=("café",))))
    assert left != right
    assert "café" in _json(left)
    assert _json(left) == _json(json.loads(_json(left)))


@pytest.mark.parametrize("target", [None, [], {}, {"rules": []}, {"rules": "clerk"},
    {"rules": [], "source_text": "some source"},
    {"rules": [_rule().to_dict()], "binders": []},
    {"rules": [{**_rule().to_dict(), "binder": "x"}]},
    {"rules": [{**_rule().to_dict(), "modality": "forall"}]},
    {"rules": [{**_rule().to_dict(), "conditions": None}]},
    {"rules": [{**_rule().to_dict(), "actor": True}]},
])
def test_target_boundary_rejects_null_noncanonical_and_new_binder_schema(target):
    with pytest.raises(ValueError):
        subject.prepare_structural_features(target)


def test_feature_preparation_has_no_fit_or_source_vector_channel():
    target = _target()
    original = deepcopy(target)
    result = subject.prepare_structural_features(target)
    assert result["qualified"] is False
    assert target == original
    with pytest.raises(TypeError):
        subject.prepare_structural_features(target, training_targets=[target])
    with pytest.raises(TypeError):
        subject.prepare_structural_features(target, source_vector=[0.0] * 384)
    with pytest.raises(TypeError):
        subject.prepare_structural_features(target, dimension=384)


@pytest.mark.parametrize("dimension", [8, 384, 768, 1024, 2049, 8192, True, None, 2048.0])
def test_hash_dimension_is_its_own_bounded_formal_geometry(dimension):
    with pytest.raises(ValueError):
        subject.encode_structural_features(subject.prepare_structural_features(_target()), dimension=dimension)


@pytest.mark.parametrize("seed", [-1, 2**31, True, None, 0.0, "0"])
def test_hash_seed_has_declared_bounded_integer_values(seed):
    with pytest.raises(ValueError):
        subject.encode_structural_features(subject.prepare_structural_features(_target()), seed=seed)


@pytest.mark.parametrize("dimension", [2048, 4096])
@pytest.mark.parametrize("seed", [0, 1])
def test_hash_recipe_is_deterministic_json_and_does_not_mutate_features(dimension, seed):
    features = subject.prepare_structural_features(_target())
    original = deepcopy(features)
    encoded = subject.encode_structural_features(features, dimension=dimension, seed=seed)
    assert encoded == subject.encode_structural_features(features, dimension=dimension, seed=seed)
    assert encoded["qualified"] is False
    assert _json(encoded) == _json(json.loads(_json(encoded)))
    assert features == original


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _reseal(record):
    record["content_sha256"] = _digest({key: value for key, value in record.items()
                                       if key != "content_sha256"})
    return record


def test_exact_dictionary_restores_all_rule_occurrences_and_matches_numeric_envelope():
    target = _target(_rule(), _rule(), _rule(actor="officer", conditions=("new_atom",)))
    features = subject.prepare_structural_features(target)
    assert features["canonical_ir"] == target
    assert features["declaration_sha256"] == _digest(target)
    assert subject.restore_structural_ir(features) == target
    assert subject.validate_structural_features(features) is features
    descriptors = features["feature_dictionary"]
    assert features["unique_features"] == len(descriptors)
    assert features["total_occurrences"] == sum(item["count"] for item in descriptors)
    rule_occurrences = {item["name"]: item["count"] for item in descriptors
                        if item["descriptor"]["kind"] == "complete_rule"}
    assert sorted(rule_occurrences.values()) == [1, 2]
    envelope = features["numeric_envelope"]
    assert envelope["feature_names"] == [item["name"] for item in descriptors]
    assert envelope["feature_values"] == [float(item["count"]) for item in descriptors]
    assert features["exact_preservation_scope"] == "normalized_seven_facet_rule_multiset_with_opaque_atoms"
    assert features["sparse_values_without_names_are_shared_coordinates"] is False
    for field in ("vocabulary_fit", "binder_semantics_inferred", "native_semantics_verified",
                  "source_fidelity_established", "proof_authority", "qualified"):
        assert features[field] is False


def test_owner_normalizes_raw_rule_order_and_duplicate_qualifier_atoms():
    raw = {"rules": [_rule(modality="P").to_dict(), _rule().to_dict()]}
    raw["rules"][0]["conditions"] = ["fees_paid", "application_complete", "fees_paid"]
    features = subject.prepare_structural_features(raw)
    canonical = CanonicalRoundTripIR.from_dict(raw).to_dict()
    assert subject.restore_structural_ir(features) == canonical
    assert features["canonical_ir"] == canonical
    assert features["canonical_ir"] != raw
    assert features == subject.prepare_structural_features(CanonicalRoundTripIR.from_dict(raw))


def test_coordinate_identity_is_shared_across_declarations_and_atoms_are_facet_typed():
    left = subject.prepare_structural_features(_target(_rule(conditions=("shared_atom",), exceptions=())))
    right = subject.prepare_structural_features(_target(_rule(conditions=(), exceptions=("shared_atom",))))
    assert left["feature_space_id"] == right["feature_space_id"]
    left_items = {item["descriptor"]["facet"]: item for item in left["feature_dictionary"]
                  if item["descriptor"]["kind"] == "typed_atom" and item["descriptor"]["atom"] == "shared_atom"}
    right_items = {item["descriptor"]["facet"]: item for item in right["feature_dictionary"]
                   if item["descriptor"]["kind"] == "typed_atom" and item["descriptor"]["atom"] == "shared_atom"}
    assert left_items["conditions"]["name"] != right_items["exceptions"]["name"]
    for item in left["feature_dictionary"] + right["feature_dictionary"]:
        assert item["name"] == "syntax.term." + _digest(item["descriptor"])
    encoded_left = subject.encode_structural_features(left)
    encoded_right = subject.encode_structural_features(right)
    assert encoded_left["feature_space_id"] == encoded_right["feature_space_id"]
    assert encoded_left["declaration_sha256"] != encoded_right["declaration_sha256"]


@pytest.mark.parametrize("dimension", [2048, 4096])
def test_pigeonhole_collisions_are_disclosed_with_exact_integer_count_aggregation(dimension):
    # 64 bounded rules with 16 unique atoms per facet yield over 4096 distinct
    # descriptors. A modulo collision follows without adaptive seed searching.
    target = _target(*(_rule(actor=f"actor_{index}",
        conditions=tuple(f"condition_{index}_{atom}" for atom in range(16)),
        exceptions=tuple(f"exception_{index}_{atom}" for atom in range(16)),
        temporal=tuple(f"time_{index}_{atom}" for atom in range(16))) for index in range(64)))
    features = subject.prepare_structural_features(target)
    assert features["unique_features"] > dimension
    encoded = subject.encode_structural_features(features, dimension=dimension, seed=0)
    assert subject.validate_hashed_features(encoded, features) is encoded
    dictionary = {item["name"]: item["count"] for item in features["feature_dictionary"]}
    assert {item["name"]: item["count"] for item in encoded["token_trace"]} == dictionary
    counts, names = Counter(), {}
    for item in encoded["token_trace"]:
        assert type(item["index"]) is int and 0 <= item["index"] < dimension
        assert type(item["count"]) is int and item["count"] > 0
        expected_index = int.from_bytes(hashlib.sha256(_json({
            "profile": subject.HASH_PROFILE, "seed": 0, "feature_name": item["name"],
        }).encode("utf-8")).digest(), "big") % dimension
        assert item["index"] == expected_index
        counts[item["index"]] += item["count"]
        names.setdefault(item["index"], []).append(item)
    assert encoded["sparse_counts"] == [{"index": index, "value": counts[index]} for index in sorted(counts)]
    expected_collisions = [{"index": index, "distinct_features": len(entries), "features": entries}
                           for index, entries in sorted(names.items()) if len(entries) > 1]
    assert encoded["collision_buckets"] == expected_collisions
    assert encoded["collision_buckets"]
    assert encoded["distinct_feature_collision_pairs"] == sum(
        len(entries) * (len(entries) - 1) // 2 for entries in names.values())
    assert encoded["nonzero_coordinates"] == len(counts) < features["unique_features"]
    assert sum(item["value"] for item in encoded["sparse_counts"]) == features["total_occurrences"]
    assert encoded["coordinate_values_sha256"] == _digest(encoded["sparse_counts"])
    assert encoded["structural_features_sha256"] == features["content_sha256"]
    for field in ("lossless", "vocabulary_fit", "trained_embedding", "source_fidelity_established",
                  "proof_authority", "qualified"):
        assert encoded[field] is False


@pytest.mark.parametrize("change", [
    lambda record: record.update(qualified=True),
    lambda record: record.update(proof_authority=True),
    lambda record: record.update(binder_semantics_inferred=True),
    lambda record: record.update(family_id="fol"),
    lambda record: record.update(feature_space_id="forged-coordinate-space"),
    lambda record: record.update(total_occurrences=0),
    lambda record: record["canonical_ir"]["rules"][0].update(actor="other_actor"),
    lambda record: record["feature_dictionary"][0].update(count=100),
    lambda record: record["feature_dictionary"][0]["descriptor"].update(family_id="fol"),
    lambda record: record["numeric_envelope"]["feature_values"].__setitem__(0, 100.0),
    lambda record: record.update(unknown_field="extra"),
])
def test_resealed_structural_corruption_is_rejected_by_owner_reconstruction(change):
    record = subject.prepare_structural_features(_target())
    change(record)
    _reseal(record)
    with pytest.raises(ValueError):
        subject.validate_structural_features(record)
    with pytest.raises(ValueError):
        subject.restore_structural_ir(record)
    with pytest.raises(ValueError):
        subject.encode_structural_features(record)


@pytest.mark.parametrize("change", [
    lambda record: record.update(qualified=True),
    lambda record: record.update(lossless=True),
    lambda record: record.update(structural_features_sha256="0" * 64),
    lambda record: record["sparse_counts"][0].update(value=100),
    lambda record: record["token_trace"][0].update(index=2048),
    lambda record: record["token_trace"][0].update(count=True),
    lambda record: record.update(collision_buckets=[{"index": 0, "features": []}]),
    lambda record: record.update(distinct_feature_collision_pairs=999),
    lambda record: record.update(coordinate_values_sha256="0" * 64),
    lambda record: record.update(feature_space_id="forged-hash-space"),
    lambda record: record.update(extra_target="gold"),
])
def test_resealed_hash_corruption_cannot_override_declared_recipe(change):
    features = subject.prepare_structural_features(_target())
    record = subject.encode_structural_features(features)
    change(record)
    _reseal(record)
    with pytest.raises(ValueError):
        subject.validate_hashed_features(record, features)


@pytest.mark.parametrize("replacement", [True, 1.0])
def test_unresealed_numerical_aliases_do_not_bypass_structural_content_digest(replacement):
    record = subject.prepare_structural_features(_target())
    item = next(item for item in record["feature_dictionary"] if item["count"] == 1)
    item["count"] = replacement
    with pytest.raises(ValueError):
        subject.validate_structural_features(record)


@pytest.mark.parametrize("replacement", [True, 1.0])
def test_unresealed_numerical_aliases_do_not_bypass_hashed_content_digest(replacement):
    features = subject.prepare_structural_features(_target())
    record = subject.encode_structural_features(features)
    item = next(item for item in record["token_trace"] if item["count"] == 1)
    item["count"] = replacement
    with pytest.raises(ValueError):
        subject.validate_hashed_features(record, features)


@pytest.mark.parametrize("record", [None, {}, {"schema": subject.SCHEMA}])
def test_malformed_structural_records_raise_validation_error(record):
    with pytest.raises(ValueError):
        subject.validate_structural_features(record)


@pytest.mark.parametrize("record", [None, {}, {"schema": subject.HASH_SCHEMA}])
def test_malformed_hashed_records_raise_validation_error(record):
    with pytest.raises(ValueError):
        subject.validate_hashed_features(record, subject.prepare_structural_features(_target()))


@pytest.mark.parametrize("family", ["fol", "modal", "", True, None, "DEONTIC"])
def test_profile_does_not_invent_support_for_other_logic_families(family):
    with pytest.raises(ValueError):
        subject.prepare_structural_features(_target(), family_id=family)


@pytest.mark.parametrize("target", [
    _target(*(_rule() for _ in range(65))),
    _target(_rule(actor="a" * 257)),
    _target(_rule(conditions=tuple(f"condition_{index}" for index in range(17)))),
])
def test_prototype_resource_bounds_fail_without_truncation(target):
    with pytest.raises(ValueError):
        subject.prepare_structural_features(target)


def test_supplementary_binder_like_atom_strings_remain_opaque_not_certified():
    features = subject.prepare_structural_features(_target(_rule(actor="forall x clerk(x)")))
    assert subject.restore_structural_ir(features)["rules"][0]["actor"] == "forall x clerk(x)"
    assert features["configuration"]["binder_support"] is False
    assert features["binder_semantics_inferred"] is False


def test_preparation_and_encoding_do_not_import_optional_models_or_provers():
    script = r'''
import builtins
old_import = builtins.__import__
blocked = ("torch", "transformers", "sentence_transformers", "spacy",
           "ipfs_datasets_py.logic.deontic.converter", "ipfs_datasets_py.logic.provers")
def checked_import(name, *args, **kwargs):
    if any(name == root or name.startswith(root + ".") for root in blocked):
        raise AssertionError("forbidden dependency: " + name)
    return old_import(name, *args, **kwargs)
builtins.__import__ = checked_import
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_structure import prepare_structural_features, encode_structural_features
target = {"rules": [{"modality": "O", "actor": "clerk", "action": "retain", "object": "filing",
                     "conditions": ["novel_atom"], "exceptions": [], "temporal": []}]}
features = prepare_structural_features(target)
encoded = encode_structural_features(features)
assert encoded["qualified"] is False
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
