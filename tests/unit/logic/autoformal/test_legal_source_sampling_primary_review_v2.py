"""An association-bound V2 subject remains unsigned and keeps prior custody.

Successes replay real authored source, context, dependency, primary-reconstruction
and index owners. The adjacent fixture source is loaded by its exact file path;
no replacement product namespace, statutory payload, review key or model is used.
"""
from __future__ import annotations

import builtins
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as review
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_primary_section_index as primary
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_primary_review_v2 as owner


def _load_helper(filename, name):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_ASSOCIATION = _load_helper(
    "test_legal_source_sampling_primary_association_v2.py",
    "_primary_review_association_fixtures",
)
_SOURCE = _ASSOCIATION._SOURCE
_PRIMARY = _ASSOCIATION._PRIMARY


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def reseal(value):
    return contracts.seal_record({key: child for key, child in value.items()
                                  if key not in {"record_cid", "cid_scope"}})


def arguments(case, link, association, index, **overrides):
    return {
        "expected_association_sha256": digest(association),
        "association_replay_inputs": _ASSOCIATION.arguments(case, link, index),
        **overrides,
    }


def prepare(case, link, association, index, **kwargs):
    return owner.prepare_primary_association_definition_review_v2(
        association, link, case["binding"], case["subject"], index,
        **arguments(case, link, association, index, **kwargs),
    )


def validate(case, link, association, index, envelope, **kwargs):
    return owner.validate_primary_association_definition_review_v2(
        envelope, association, link, case["binding"], case["subject"], index,
        expected_preparation_sha256=digest(envelope),
        **arguments(case, link, association, index, **kwargs),
    )


def closure(manifest, root):
    """Independent ordered forward walk over public manifest data."""
    adjacency = {}
    for edge in manifest["edges"]:
        adjacency.setdefault(edge["dependent_id"], []).append(edge["dependency_id"])
    reachable, seen = [root], {root}
    for parent in reachable:
        for child in adjacency.get(parent, []):
            if child not in seen:
                seen.add(child)
                reachable.append(child)
    return reachable


def extend_original_manifest(case, *, missing_target="unavailable:external-law",
                             extra_artifact=None):
    """Add declared custody through public builders, keeping original evidence."""
    result = deepcopy(case)
    old = result["args"]["dependency_manifest"]
    artifacts, edges = deepcopy((old["artifacts"], old["edges"]))
    graph_id = result["preparation"]["graph_id"]
    if extra_artifact is None:
        extra_artifact = {
            "artifact_id": "authored:unknown-dependency",
            "artifact_sha256": sha(b"literal unknown authored artifact"),
            "dependency_pins": {kind: [] for kind in dependencies.PIN_KINDS},
        }
        extra_artifact["dependency_pins"]["revision"].append(
            {"key": "authored:missing-revision", "sha256": None}
        )
    artifacts.append(deepcopy(extra_artifact))
    artifacts.append({
        "artifact_id": "authored:unrelated-archival-evidence",
        "artifact_sha256": sha(b"unrelated declared artifact kept outside graph closure"),
        "dependency_pins": {kind: [] for kind in dependencies.PIN_KINDS},
    })
    edges.extend([
        {"dependent_id": graph_id, "dependency_id": extra_artifact["artifact_id"]},
        {"dependent_id": extra_artifact["artifact_id"], "dependency_id": missing_target},
        {"dependent_id": "authored:unrelated-archival-evidence",
         "dependency_id": "unavailable:unrelated-archival-law"},
    ])
    manifest = dependencies.build_dependency_manifest(
        artifacts, edges, expected_artifact_ids=[row["artifact_id"] for row in artifacts],
    )
    required = closure(manifest, graph_id)
    evidence = {key: result["args"][key] for key in (
        "candidate_inputs", "expected_candidate_pin", "context_inputs",
        "expected_context_population",
    )}
    subject = review.build_definition_review_subject_v2(
        result["preparation"], manifest, **evidence,
        expected_manifest_sha256=manifest["manifest_sha256"],
        required_dependency_ids=required,
    )
    result["subject"] = subject
    result["args"].update({
        "dependency_manifest": manifest,
        "expected_manifest_sha256": manifest["manifest_sha256"],
        "required_dependency_ids": required,
        "expected_subject_sha256": digest(subject),
    })
    return result


def assert_unsigned(envelope, *, blocked=False):
    assert set(envelope) == {"schema", "profile", "preparation", "subject", "dependency_manifest"}
    assert envelope["schema"] == "legal-source-sampling-primary-definition-review-envelope/v2"
    assert envelope["profile"] == "unsigned-association-bound-v2-definition-review/v1"
    record = envelope["preparation"]
    assert record["schema"] == "legal-source-sampling-primary-definition-review-preparation/v2"
    assert record["view"] == "candidate" and record["unsigned"] is True
    assert record["status"] == (
        "blocked_unresolved_primary_association" if blocked
        else "unsigned_association_bound_definition_review_subject"
    )
    assert record["authority"] and all(value is False for value in record["authority"].values())
    assert type(record["training_mask"]) is int and record["training_mask"] == 0
    assert type(record["evaluation_gold_mask"]) is int and record["evaluation_gold_mask"] == 0
    assert record["unresolved_claims"] == [
        "official_source_primary_package_equivalence", "governing_version_and_applicability",
        "independent_legal_interpretation", "independent_formal_interpretation", "authenticated_exposure",
    ]
    assert owner.primary_association_definition_review_sha256(envelope) == digest(envelope)
    if blocked:
        assert envelope["subject"] is None and envelope["dependency_manifest"] is None
    else:
        assert envelope["subject"]["schema"] == review.SUBJECT_SCHEMA
        assert envelope["dependency_manifest"]["schema"] == dependencies.SCHEMA


@pytest.fixture(scope="module")
def base_case():
    return _SOURCE.joined_case()


@pytest.fixture(scope="module")
def base_link(base_case):
    return _SOURCE.prepare(base_case)


@pytest.mark.parametrize("family,shape", [("fol", "opaque"), ("tdfol", "nested")])
def test_actual_public_owners_create_distinct_complete_unsigned_subject(tmp_path, family, shape):
    case = _SOURCE.joined_case(family, shape=shape)
    link = _SOURCE.prepare(case)
    path, index_args = _PRIMARY.fixture(tmp_path)
    before = deepcopy((case, link))
    original_bytes = path.read_bytes()
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = _ASSOCIATION.prepare(case, link, index)
        association_before = deepcopy(association)
        envelope = prepare(case, link, association, index)
        assert_unsigned(envelope)
        subject, manifest = envelope["subject"], envelope["dependency_manifest"]
        assert subject != case["subject"]
        assert digest(subject) != digest(case["subject"])
        assert subject["native_binding"] == case["preparation"]
        assert subject["graph_id"] == case["subject"]["graph_id"]
        assert subject["context_slot_ids"] == case["subject"]["context_slot_ids"]
        assert subject["required_dependency_ids"] == closure(manifest, subject["graph_id"])
        old = case["args"]["dependency_manifest"]
        assert manifest["artifacts"][:len(old["artifacts"])] == old["artifacts"]
        assert manifest["edges"][:len(old["edges"])] == old["edges"]
        assert manifest["expected_artifact_ids"][:len(old["expected_artifact_ids"])] == old["expected_artifact_ids"]
        assert manifest["manifest_sha256"] != old["manifest_sha256"]
        assert validate(case, link, association, index, envelope) == envelope
        assert association == association_before
    assert before == (case, link)
    assert path.read_bytes() == original_bytes


@pytest.mark.parametrize("shape,split", [("shared", False), ("opaque", True)])
def test_role_sharing_and_withheld_unrelated_population_are_preserved(tmp_path, shape, split):
    case = _SOURCE.joined_case(shape=shape, split=split)
    link = _SOURCE.prepare(case)
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = _ASSOCIATION.prepare(case, link, index)
        envelope = prepare(case, link, association, index)
        assert_unsigned(envelope)
        assert envelope["subject"]["native_binding"] == case["subject"]["native_binding"]
        # The complete population stays committed by the full association ref;
        # it must never shrink to the selected response or occurrence subset.
        assert association["population_subject_count"] == len(association["population_subjects"])
        assert association["population_subject_count"] > len(association["required_subjects"])
        assert validate(case, link, association, index, envelope) == envelope


def test_original_unknown_artifacts_missing_pins_and_missing_targets_survive_superset(tmp_path):
    case = extend_original_manifest(_SOURCE.joined_case())
    link = _SOURCE.prepare(case)
    path, index_args = _PRIMARY.fixture(tmp_path)
    old = deepcopy(case["args"]["dependency_manifest"])
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = _ASSOCIATION.prepare(case, link, index)
        envelope = prepare(case, link, association, index)
        assert_unsigned(envelope)
        manifest, subject = envelope["dependency_manifest"], envelope["subject"]
        assert manifest["artifacts"][:len(old["artifacts"])] == old["artifacts"]
        assert manifest["edges"][:len(old["edges"])] == old["edges"]
        assert manifest["missing_dependencies"] == old["missing_dependencies"]
        assert "unavailable:external-law" in subject["required_dependency_ids"]
        assert {"artifact_id": "unavailable:external-law", "artifact_sha256": None} in subject["dependency_artifacts"]
        assert "authored:unrelated-archival-evidence" not in subject["required_dependency_ids"]
        assert "unavailable:unrelated-archival-law" not in subject["required_dependency_ids"]
        assert "authored:unrelated-archival-evidence" in manifest["expected_artifact_ids"]
        assert case["args"]["dependency_manifest"] == old
        assert validate(case, link, association, index, envelope) == envelope


def test_every_primary_witness_mapping_and_actual_producer_pin_is_reachable(
        tmp_path, base_case, base_link):
    nodes = [
        _PRIMARY.node("section"), _PRIMARY.node("package", "source_package", None),
        _PRIMARY.node("release", "release_point", None,
                      node_key="release_point:us/pl/119/102", label="us/pl/119/102"),
    ]
    edges = [
        _PRIMARY.edge("package-evidence-a"), _PRIMARY.edge("package-evidence-b"),
        _PRIMARY.edge("release-evidence-a", target="release"),
        _PRIMARY.edge("release-evidence-b", target="release"),
    ]
    path, index_args = _PRIMARY.fixture(tmp_path, nodes=nodes, edges=edges)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = _ASSOCIATION.prepare(base_case, base_link, index)
        envelope = prepare(base_case, base_link, association, index)
        assert_unsigned(envelope)
        record, subject, manifest = (envelope[key] for key in
                                      ("preparation", "subject", "dependency_manifest"))
        by_id = {row["artifact_id"]: row for row in manifest["artifacts"]}
        reachable = subject["required_dependency_ids"]
        old_manifest = base_case["args"]["dependency_manifest"]
        wrappers = {
            "sampled-primary-review-association:sha256:" + digest(association): digest(association),
            "sampled-primary-review-correspondence:sha256:" + digest(base_link): digest(base_link),
            "sampled-primary-review-previous-subject:sha256:" + digest(base_case["subject"]): digest(base_case["subject"]),
            "sampled-primary-review-previous-manifest:sha256:" + digest(old_manifest): digest(old_manifest),
        }
        for artifact_id, expected in wrappers.items():
            assert artifact_id in reachable
            assert by_id[artifact_id]["artifact_sha256"] == expected
        assert record["primary_artifact_refs"] == association["primary_artifact_refs"]
        assert len(record["primary_artifact_refs"]) == 8
        for ref in association["primary_artifact_refs"]:
            assert ref["artifact_id"] in reachable
            assert by_id[ref["artifact_id"]]["artifact_sha256"] == ref["artifact_sha256"]
        producers = record["producer_pins"]
        assert producers and set(association["producer_pins"]) <= set(producers)
        assert str(Path(owner.__file__).resolve()) in producers
        for producer_path, source_sha256 in producers.items():
            assert source_sha256 == sha(Path(producer_path).read_bytes())
            artifact_id = "sampled-primary-review-producer:sha256:" + sha(producer_path.encode("utf-8"))
            assert artifact_id in reachable
            assert by_id[artifact_id]["artifact_sha256"] == source_sha256
        assert record["previous_required_dependency_ids"] == base_case["subject"]["required_dependency_ids"]
        assert record["required_dependency_ids"] == reachable
        assert record["population_ref"] == association["population_ref"]
        assert record["population_counts"] == association["population_counts"]
        assert record["population_subject_count"] == association["population_subject_count"]
        assert record["response_count"] == association["response_count"]
        assert record["selected_unit_roles"] == association["selected_unit_roles"]
        assert record["context_slot_ids"] == association["context_slot_ids"]
        assert record["association_ref"]["sha256"] == digest(association)
        assert record["correspondence_ref"]["sha256"] == digest(base_link)
        assert record["previous_subject_ref"]["sha256"] == digest(base_case["subject"])
        assert record["previous_preparation_ref"]["sha256"] == digest(base_case["preparation"])
        assert record["previous_manifest_ref"] == {
            "schema": old_manifest["schema"], "sha256": digest(old_manifest),
            "manifest_sha256": old_manifest["manifest_sha256"],
        }
        assert record["dependency_manifest_ref"] == {
            "schema": manifest["schema"], "sha256": digest(manifest),
            "manifest_sha256": manifest["manifest_sha256"],
        }
        assert record["subject_ref"] == {"schema": subject["schema"], "sha256": digest(subject)}
        assert record["review_subject_created"] is True
        assert record["assessment_created"] is False and record["signatures_created"] is False


def test_raw_transport_mapping_and_full_manifest_hash_namespaces_stay_distinct(
        tmp_path, base_case, base_link):
    path, index_args = _PRIMARY.fixture(tmp_path)
    mapping = _ASSOCIATION.mapping_for(base_link)
    compact, pretty = wire(mapping), _ASSOCIATION.transport(mapping)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        envelopes = []
        for raw in (compact, pretty):
            association = _ASSOCIATION.prepare(base_case, base_link, index, mapping_raw=raw)
            replay = _ASSOCIATION.arguments(base_case, base_link, index, mapping_raw=raw)
            envelope = prepare(base_case, base_link, association, index,
                               association_replay_inputs=replay)
            envelopes.append(envelope)
            manifest = envelope["dependency_manifest"]
            assert manifest["manifest_sha256"] != digest(manifest)
            mapping_ref = association["primary_artifact_refs"][-1]
            assert mapping_ref["artifact_sha256"] == digest(mapping)
            assert mapping_ref["artifact_sha256"] != sha(pretty)
            assert envelope["preparation"]["association_ref"]["sha256"] == digest(association)
            assert envelope["preparation"]["subject_ref"]["sha256"] == digest(envelope["subject"])
        assert envelopes[0]["subject"] != envelopes[1]["subject"]
        assert envelopes[0]["preparation"]["record_cid"] != envelopes[1]["preparation"]["record_cid"]
        assert digest(envelopes[0]) != digest(envelopes[1])


@pytest.mark.parametrize("missing", ["section", "package", "both", "wrong_package"])
def test_unresolved_association_has_typed_blocked_envelope_without_new_subject(
        tmp_path, base_case, base_link, missing):
    mapping = _ASSOCIATION.mapping_for(base_link)
    if missing in {"section", "both"}:
        mapping["section_entry_cid"] = None
    if missing in {"package", "both"}:
        mapping["source_package_entry_cid"] = None
    if missing == "wrong_package":
        mapping["source_package_entry_cid"] = _PRIMARY.identity("different package")
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        replay = _ASSOCIATION.arguments(base_case, base_link, index, mapping=mapping)
        association = _ASSOCIATION.prepare(base_case, base_link, index, mapping=mapping)
        envelope = prepare(base_case, base_link, association, index,
                           association_replay_inputs=replay)
        assert_unsigned(envelope, blocked=True)
        assert validate(base_case, base_link, association, index, envelope,
                        association_replay_inputs=replay) == envelope


def test_new_primary_artifact_cannot_silently_fill_original_missing_target(tmp_path):
    case = extend_original_manifest(_SOURCE.joined_case(), missing_target=_PRIMARY.identity("section"))
    link = _SOURCE.prepare(case)
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = _ASSOCIATION.prepare(case, link, index)
        assert association["status"] == "declared_primary_association_only"
        with pytest.raises(ValueError):
            prepare(case, link, association, index)


@pytest.mark.parametrize("same_hash", [False, True])
def test_new_primary_artifact_id_collision_with_original_population_refuses(tmp_path, same_hash):
    initial = _SOURCE.joined_case()
    link = _SOURCE.prepare(initial)
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        first = _ASSOCIATION.prepare(initial, link, index)
        section_ref = first["primary_artifact_refs"][0]
        artifact = {
            "artifact_id": section_ref["artifact_id"],
            "artifact_sha256": section_ref["artifact_sha256"] if same_hash else sha(b"colliding artifact"),
            "dependency_pins": {kind: [] for kind in dependencies.PIN_KINDS},
        }
        case = extend_original_manifest(initial, extra_artifact=artifact)
        new_link = _SOURCE.prepare(case)
        association = _ASSOCIATION.prepare(case, new_link, index)
        with pytest.raises(ValueError):
            prepare(case, new_link, association, index)


@pytest.mark.parametrize("pin", [
    "expected_association_sha256", "expected_correspondence_sha256",
    "expected_mapping_file_sha256", "expected_index_sha256",
])
def test_independent_outer_and_original_association_pins_cannot_be_substituted(
        tmp_path, base_case, base_link, pin):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = _ASSOCIATION.prepare(base_case, base_link, index)
        args = arguments(base_case, base_link, association, index)
        if pin == "expected_association_sha256":
            args[pin] = sha(b"different association")
        else:
            args["association_replay_inputs"][pin] = sha(b"different independent input")
        with pytest.raises(ValueError):
            owner.prepare_primary_association_definition_review_v2(
                association, base_link, base_case["binding"], base_case["subject"], index, **args,
            )


@pytest.mark.parametrize("damage", [
    "original_subject", "original_manifest", "required_order", "raw_source",
    "context_order", "binding_pin", "source_identity",
])
def test_complete_old_association_replay_is_required_before_new_review_subject(
        tmp_path, base_case, base_link, damage):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = _ASSOCIATION.prepare(base_case, base_link, index)
        args = arguments(base_case, base_link, association, index)
        case, link = deepcopy((base_case, base_link))
        old = args["association_replay_inputs"]["correspondence_replay_inputs"]
        if damage == "original_subject":
            case["subject"]["context_slot_ids"].reverse()
            old["expected_subject_sha256"] = digest(case["subject"])
        elif damage == "original_manifest":
            old["dependency_manifest"]["artifacts"].pop()
        elif damage == "required_order":
            old["required_dependency_ids"].reverse()
        elif damage == "raw_source":
            old["candidate_inputs"]["raw_html"] += b" "
            old["expected_candidate_pin"]["raw_sha256"] = sha(old["candidate_inputs"]["raw_html"])
            old["expected_candidate_pin"]["raw_bytes"] += 1
        elif damage == "context_order":
            old["context_inputs"].reverse()
            old["expected_context_population"].reverse()
        elif damage == "binding_pin":
            old["expected_binding_sha256"] = sha(b"other original binding")
        else:
            link["source_identity"]["tampered"] = "unrelated version"
        with pytest.raises(ValueError):
            owner.prepare_primary_association_definition_review_v2(
                association, link, case["binding"], case["subject"], index, **args,
            )


@pytest.mark.parametrize("damage", [
    "extra_replay", "missing_replay", "dict_subclass", "nonfinite", "deep",
    "oversized_association", "binary_aggregate", "boolean_pin",
])
def test_finite_ordinary_preflight_refuses_before_lazy_operation_owners(
        tmp_path, base_case, base_link, damage):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = _ASSOCIATION.prepare(base_case, base_link, index)
        args = arguments(base_case, base_link, association, index)
        offered = deepcopy(association)
        replay = args["association_replay_inputs"]
        if damage == "extra_replay":
            replay["caller_callback"] = "not permitted"
        elif damage == "missing_replay":
            replay.pop("mapping_raw")
        elif damage == "dict_subclass":
            class CustomDict(dict):
                pass
            offered = CustomDict(offered)
        elif damage == "nonfinite":
            offered["extra"] = float("inf")
        elif damage == "deep":
            value = "leaf"
            for _ in range(65):
                value = [value]
            offered["extra"] = value
        elif damage == "oversized_association":
            offered["extra"] = "x" * (1024 * 1024 + 1)
        elif damage == "binary_aggregate":
            replay["correspondence_replay_inputs"]["candidate_inputs"]["raw_html"] = b"x" * (128 * 1024 * 1024 + 1)
        else:
            args["expected_association_sha256"] = True
        with patch.object(owner, "_owners", side_effect=AssertionError("operation owner reached")) as operation:
            with pytest.raises(ValueError):
                owner.prepare_primary_association_definition_review_v2(
                    offered, base_link, base_case["binding"], base_case["subject"], object(), **args,
                )
            operation.assert_not_called()


def test_live_index_lifetime_cannot_be_replaced_with_retained_receipt(tmp_path, base_case, base_link):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = _ASSOCIATION.prepare(base_case, base_link, index)
        args = arguments(base_case, base_link, association, index)
        envelope = prepare(base_case, base_link, association, index)
    for invalid in (index, object()):
        with pytest.raises(ValueError):
            owner.prepare_primary_association_definition_review_v2(
                association, base_link, base_case["binding"], base_case["subject"], invalid, **args,
            )
        with pytest.raises(ValueError):
            owner.validate_primary_association_definition_review_v2(
                envelope, association, base_link, base_case["binding"], base_case["subject"], invalid,
                expected_preparation_sha256=digest(envelope), **args,
            )


def test_wrong_full_envelope_pin_refuses_before_regeneration(tmp_path, base_case, base_link):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = _ASSOCIATION.prepare(base_case, base_link, index)
        envelope = prepare(base_case, base_link, association, index)
        with patch.object(owner, "prepare_primary_association_definition_review_v2",
                          side_effect=AssertionError("regeneration reached")) as regenerate:
            with pytest.raises(ValueError):
                owner.validate_primary_association_definition_review_v2(
                    envelope, association, base_link, base_case["binding"], base_case["subject"], index,
                    expected_preparation_sha256=sha(b"another complete envelope"),
                    **arguments(base_case, base_link, association, index),
                )
            regenerate.assert_not_called()


@pytest.mark.parametrize("damage", [
    "authority", "training_boolean", "gold_float", "association_ref", "population",
    "previous_closure", "new_closure", "primary_ref", "producer_pin", "unresolved_claims",
    "subject", "manifest_artifact", "manifest_edge", "companions_rebound",
])
def test_full_envelope_and_resealed_companions_cannot_replace_original_regeneration(
        tmp_path, base_case, base_link, damage):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = _ASSOCIATION.prepare(base_case, base_link, index)
        original = prepare(base_case, base_link, association, index)
        offered = deepcopy(original)
        record = offered["preparation"]
        if damage == "authority":
            record["authority"]["source_semantics_verified"] = True
        elif damage == "training_boolean":
            record["training_mask"] = False
        elif damage == "gold_float":
            record["evaluation_gold_mask"] = 0.0
        elif damage == "association_ref":
            record["association_ref"]["sha256"] = sha(b"substituted association")
        elif damage == "population":
            record["population_subject_count"] -= 1
        elif damage == "previous_closure":
            record["previous_required_dependency_ids"].reverse()
        elif damage == "new_closure":
            record["required_dependency_ids"].reverse()
        elif damage == "primary_ref":
            record["primary_artifact_refs"].pop()
        elif damage == "producer_pin":
            first = next(iter(record["producer_pins"]))
            record["producer_pins"][first] = sha(b"changed producer source")
        elif damage == "unresolved_claims":
            record["unresolved_claims"].pop()
        elif damage == "subject":
            offered["subject"]["context_slot_ids"].reverse()
            record["subject_ref"]["sha256"] = digest(offered["subject"])
        elif damage in {"manifest_artifact", "manifest_edge"}:
            manifest = offered["dependency_manifest"]
            if damage == "manifest_artifact":
                manifest["artifacts"][-1]["artifact_sha256"] = sha(b"substituted artifact")
            else:
                manifest["edges"].pop()
            offered["dependency_manifest"] = dependencies.build_dependency_manifest(
                manifest["artifacts"], manifest["edges"],
                expected_artifact_ids=manifest["expected_artifact_ids"],
            )
            new_manifest = offered["dependency_manifest"]
            record["dependency_manifest_ref"]["sha256"] = digest(new_manifest)
            record["dependency_manifest_ref"]["manifest_sha256"] = new_manifest["manifest_sha256"]
        else:
            # This remains a valid PUBLIC V2 subject and manifest. Rebinding all
            # companion hashes still cannot authorize a different outer record.
            manifest = offered["dependency_manifest"]
            artifacts, edges = deepcopy((manifest["artifacts"], manifest["edges"]))
            extra_id = "authored:additional-review-dependency"
            artifacts.append({
                "artifact_id": extra_id, "artifact_sha256": sha(b"extra authored evidence"),
                "dependency_pins": {kind: [] for kind in dependencies.PIN_KINDS},
            })
            edges.append({"dependent_id": base_case["subject"]["graph_id"], "dependency_id": extra_id})
            new_manifest = dependencies.build_dependency_manifest(
                artifacts, edges, expected_artifact_ids=[row["artifact_id"] for row in artifacts],
            )
            required = closure(new_manifest, base_case["subject"]["graph_id"])
            evidence = {key: base_case["args"][key] for key in (
                "candidate_inputs", "expected_candidate_pin", "context_inputs", "expected_context_population",
            )}
            subject = review.build_definition_review_subject_v2(
                base_case["preparation"], new_manifest, **evidence,
                expected_manifest_sha256=new_manifest["manifest_sha256"], required_dependency_ids=required,
            )
            offered["subject"], offered["dependency_manifest"] = subject, new_manifest
            record["required_dependency_ids"] = required
            record["subject_ref"] = {"schema": subject["schema"], "sha256": digest(subject)}
            record["dependency_manifest_ref"] = {"schema": new_manifest["schema"],
                "sha256": digest(new_manifest), "manifest_sha256": new_manifest["manifest_sha256"]}
        offered["preparation"] = reseal(record)
        assert digest(offered) != digest(original)
        with pytest.raises(ValueError):
            validate(base_case, base_link, association, index, offered)


def test_complete_envelope_over_byte_bound_refuses_before_regeneration(
        tmp_path, base_case, base_link):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = _ASSOCIATION.prepare(base_case, base_link, index)
        envelope = prepare(base_case, base_link, association, index)
        offered = deepcopy(envelope)
        offered["preparation"]["over_bound"] = "x" * (4 * 1024 * 1024 + 1)
        with patch.object(owner, "prepare_primary_association_definition_review_v2",
                          side_effect=AssertionError("regeneration reached")) as regenerate:
            with pytest.raises(ValueError):
                owner.validate_primary_association_definition_review_v2(
                    offered, association, base_link, base_case["binding"], base_case["subject"], index,
                    expected_preparation_sha256=digest(offered),
                    **arguments(base_case, base_link, association, index),
                )
            regenerate.assert_not_called()


def test_public_import_is_standard_library_only_and_does_not_write(monkeypatch):
    path = Path(owner.__file__)
    name = "_primary_review_cold_public_source"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    cold = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, cold)
    attempts = []
    forbidden = ("ipfs_datasets_py", "numpy", "pyarrow", "multiformats", "torch", "transformers", "symai", "tensorflow")
    original_import, original_open, original_os_open = builtins.__import__, builtins.open, os.open
    def checked_import(import_name, *args, **kwargs):
        if any(import_name == root or import_name.startswith(root + ".") for root in forbidden):
            attempts.append(import_name)
            raise AssertionError("operation owner imported during public import")
        return original_import(import_name, *args, **kwargs)
    def checked_open(file, mode="r", *args, **kwargs):
        if type(mode) is str and any(flag in mode for flag in "wax+"):
            attempts.append("file write")
            raise AssertionError("public import wrote a file")
        return original_open(file, mode, *args, **kwargs)
    def checked_os_open(file, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            attempts.append("descriptor write")
            raise AssertionError("public import wrote through os.open")
        return original_os_open(file, flags, *args, **kwargs)
    with patch.object(builtins, "__import__", checked_import), patch.object(builtins, "open", checked_open), patch.object(io, "open", checked_open), patch.object(os, "open", checked_os_open):
        spec.loader.exec_module(cold)
    assert attempts == []
    assert cold.SCHEMA == owner.SCHEMA and cold.PROFILE == owner.PROFILE
    assert all(hasattr(cold, symbol) for symbol in (
        "prepare_primary_association_definition_review_v2",
        "validate_primary_association_definition_review_v2",
        "primary_association_definition_review_sha256",
    ))
