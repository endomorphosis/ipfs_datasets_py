"""Authored source/primary associations preserve evidence without legal gold.

The actual sampler, correspondence validator, reconstruction, primary index and
artifact-reference owner operate on new regular-file fixtures. No statutory
payload, authenticated reviewer, trust key, model or Lean execution is supplied.
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
from ipfs_datasets_py.logic.autoformal import legal_primary_section_index as primary
from ipfs_datasets_py.logic.autoformal import legal_source_graph_proposals as proposals
from ipfs_datasets_py.logic.autoformal import (
    legal_source_sampling_definition_review_v2 as correspondence_owner,
)
from ipfs_datasets_py.logic.autoformal import (
    legal_source_sampling_primary_association_v2 as owner,
)


def _load_helper(filename, name):
    """Load the real adjacent fixture source without resolving a tests package."""
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_SOURCE = _load_helper(
    "test_legal_source_sampling_definition_review_v2.py",
    "_sampled_primary_association_source_fixtures",
)
_PRIMARY = _load_helper(
    "test_legal_primary_section_index.py",
    "_sampled_primary_association_index_fixtures",
)


def wire(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def transport(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
    ).encode("utf-8") + b"\n"


def reseal(value):
    return contracts.seal_record({
        key: child for key, child in value.items()
        if key not in {"record_cid", "cid_scope"}
    })


def mapping_for(link, **overrides):
    return {
        "schema": owner.MAPPING_SCHEMA,
        "correspondence_sha256": digest(link),
        "source_identity_sha256": digest(link["source_identity"]),
        "source_occurrence_cids": [
            row["occurrence_ref"]["record_cid"]
            for row in link["occurrence_context_links"]
        ],
        "legal_id": "usc:us:10:1",
        "section_entry_cid": _PRIMARY.identity("section"),
        "source_package_entry_cid": _PRIMARY.identity("package"),
        **overrides,
    }


def arguments(case, link, index, *, mapping=None, mapping_raw=None, **overrides):
    if mapping_raw is None:
        mapping_raw = transport(mapping_for(link) if mapping is None else mapping)
    return {
        "expected_correspondence_sha256": digest(link),
        "correspondence_replay_inputs": deepcopy(case["args"]),
        "mapping_raw": mapping_raw,
        "expected_mapping_file_sha256": sha(mapping_raw),
        "expected_index_sha256": index.index_sha256,
        **overrides,
    }


def prepare(case, link, index, **kwargs):
    return owner.prepare_sampled_primary_association_v2(
        link, case["binding"], case["subject"], index,
        **arguments(case, link, index, **kwargs),
    )


def validate(case, link, index, association, **kwargs):
    return owner.validate_sampled_primary_association_v2(
        association, link, case["binding"], case["subject"], index,
        expected_association_sha256=digest(association),
        **arguments(case, link, index, **kwargs),
    )


def assert_unsigned(association, *, unresolved=False):
    assert association["schema"] == owner.SCHEMA
    assert association["profile"] == owner.PROFILE
    assert association["view"] == "candidate" and association["unsigned"] is True
    assert association["status"] == (
        "unresolved_primary_association" if unresolved else "declared_primary_association_only"
    )
    assert association["association_basis"] == (
        "independently_pinned_caller_mapping_not_source_equivalence"
    )
    assert association["authority"] and all(
        value is False for value in association["authority"].values()
    )
    assert type(association["training_mask"]) is int and association["training_mask"] == 0
    assert type(association["evaluation_gold_mask"]) is int and association["evaluation_gold_mask"] == 0
    assert owner.sampled_primary_association_sha256(association) == digest(association)


PRESERVED_FIELDS = (
    "source_identity", "population_ref", "population_subjects", "population_counts",
    "population_subject_count", "response_count", "selected_unit_roles", "required_subjects",
    "source_role_bindings", "occurrence_context_links", "candidate_ref", "subject_ref",
    "dependency_manifest_ref", "context_slot_ids",
)


@pytest.fixture(scope="module")
def base_case():
    return _SOURCE.joined_case()


@pytest.fixture(scope="module")
def base_link(base_case):
    return _SOURCE.prepare(base_case)


@pytest.mark.parametrize("family,shape", [("fol", "opaque"), ("tdfol", "nested")])
def test_real_source_and_primary_join_retains_full_population_and_every_input(
        tmp_path, family, shape):
    case = _SOURCE.joined_case(family, shape=shape)
    link = _SOURCE.prepare(case)
    before = deepcopy((link, case["binding"], case["subject"], case["args"]))
    path, index_args = _PRIMARY.fixture(tmp_path)
    candidate_bytes = path.read_bytes()
    with primary.PrimarySectionIndex(path, **index_args) as index:
        receipt, identity = index.receipt, index.primary_identity
        mapping = mapping_for(link)
        mapping_before = deepcopy(mapping)
        raw = transport(mapping)
        association = prepare(case, link, index, mapping_raw=raw)
        assert_unsigned(association)
        assert association["issues"] == []
        for field in PRESERVED_FIELDS:
            assert association[field] == link[field]
        assert association["population_subject_count"] > len(association["required_subjects"])
        assert association["correspondence_ref"] == {
            "schema": link["schema"], "record_cid": link["record_cid"], "sha256": digest(link),
        }
        assert association["mapping"] == mapping_before
        assert association["mapping_transport"] == {
            "utf8": raw.decode("utf-8"), "bytes": len(raw), "sha256": sha(raw),
        }
        assert association["primary_index_receipt"] == receipt
        assert association["primary_identity"] == identity
        assert association["primary_lookup"] == index.lookup_sections("usc:us:10:1")
        section, = association["primary_lookup"]["sections"]
        assert association["primary_artifact_refs"] == proposals.required_primary_artifacts(mapping, section)
        # Opaque producer data survives but does not become sidecar authority.
        assert section["section_observation"]["original_body"]["unknown"]["admitted"] is True
        assert validate(case, link, index, association, mapping_raw=raw) == association
        assert index.receipt == receipt and index.primary_identity == identity
        assert mapping == mapping_before
    assert path.read_bytes() == candidate_bytes
    assert before == (link, case["binding"], case["subject"], case["args"])
    assert case["args"]["candidate_inputs"] == case["original_bytes"]


def test_raw_mapping_bytes_are_distinct_from_canonical_mapping_identity(tmp_path, base_case, base_link):
    path, index_args = _PRIMARY.fixture(tmp_path)
    mapping = mapping_for(base_link)
    compact, pretty = wire(mapping), transport(mapping)
    assert compact != pretty and sha(compact) != sha(pretty)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        first = prepare(base_case, base_link, index, mapping_raw=compact)
        second = prepare(base_case, base_link, index, mapping_raw=pretty)
        assert first["mapping"] == second["mapping"] == mapping
        assert first["primary_artifact_refs"] == second["primary_artifact_refs"]
        mapping_ref = first["primary_artifact_refs"][-1]
        assert mapping_ref == {
            "artifact_id": "legal-primary-source-mapping:sha256:" + digest(mapping),
            "artifact_sha256": digest(mapping),
            "role": "declared_primary_source_correspondence_only",
        }
        assert first["mapping_transport"]["sha256"] == sha(compact)
        assert second["mapping_transport"]["sha256"] == sha(pretty)
        assert first["record_cid"] != second["record_cid"]
        assert digest(first) != digest(second)
        assert validate(base_case, base_link, index, first, mapping_raw=compact) == first
        with pytest.raises(ValueError):
            validate(base_case, base_link, index, first, mapping_raw=pretty)


def test_mapping_byte_ceiling_accepts_exact_boundary_without_clipping(tmp_path, base_case, base_link):
    raw = wire(mapping_for(base_link))
    raw += b" " * (owner.MAX_MAPPING_BYTES - len(raw))
    assert len(raw) == 64 * 1024
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = prepare(base_case, base_link, index, mapping_raw=raw)
        assert association["mapping_transport"]["utf8"].encode("utf-8") == raw
        assert association["mapping_transport"]["bytes"] == len(raw)
        assert_unsigned(association)


def test_old_artifact_owner_keeps_all_typed_relationship_and_release_witnesses(
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
    original = [json.loads(raw) for raw in path.read_bytes().splitlines()][1:]
    by_id = {row["declared_identity"]["entry_cid"]: row for row in original}
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = prepare(base_case, base_link, index)
        assert_unsigned(association)
        section, = association["primary_lookup"]["sections"]
        assert association["primary_artifact_refs"] == proposals.required_primary_artifacts(
            mapping_for(base_link), section)
        expected = [
            ("section", "declared_primary_section"),
            ("package", "declared_primary_source_package"),
            ("package-evidence-a", "declared_HAS_SOURCE_transport_evidence"),
            ("package-evidence-b", "declared_HAS_SOURCE_transport_evidence"),
            ("release", "declared_primary_release_point"),
            ("release-evidence-a", "declared_HAS_SOURCE_release_context_evidence"),
            ("release-evidence-b", "declared_HAS_SOURCE_release_context_evidence"),
        ]
        assert len(association["primary_artifact_refs"]) == len(expected) + 1
        for ref, (key, role) in zip(association["primary_artifact_refs"][:-1], expected, strict=True):
            identity = _PRIMARY.identity(key)
            assert ref == {"artifact_id": identity,
                "artifact_sha256": by_id[identity]["record_sha256"], "role": role}
        assert len(section["has_source_observations"]) == 4
        assert len(section["source_packages"][0]["has_source_observations"]) == 2
        assert len(section["release_points"][0]["has_source_observations"]) == 2


@pytest.mark.parametrize("shape", ["shared", "opaque"])
def test_shared_roles_and_unrelated_withheld_parents_are_never_filtered(tmp_path, shape):
    case = _SOURCE.joined_case(shape=shape, split=shape == "opaque")
    link = _SOURCE.prepare(case)
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = prepare(case, link, index)
        for field in PRESERVED_FIELDS:
            assert association[field] == link[field]
        if shape == "shared":
            assert any(len(row["source_role_bindings"]) > 1
                       for row in association["occurrence_context_links"])
        else:
            required, unrelated = _SOURCE._BINDING.split_parent_guides(case["source"])
            assert required["subject_ref"] in [row["subject_ref"] for row in association["required_subjects"]]
            assert unrelated["subject_ref"] not in [row["subject_ref"] for row in association["required_subjects"]]
            assert unrelated["subject_ref"] in [row["subject_ref"] for row in association["population_subjects"]]
        assert_unsigned(association)


@pytest.mark.parametrize("unsupported", [False, True])
def test_recorded_source_declarations_cannot_create_primary_or_semantic_authority(tmp_path, unsupported):
    case = _SOURCE.joined_case(responses=lambda source: [
        _SOURCE._BINDING.response(source, guide, unsupported=unsupported)
        for guide in _SOURCE._BINDING.selected_guides(source)
    ])
    link = _SOURCE.prepare(case)
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = prepare(case, link, index)
        assert {row["state"] for row in association["required_subjects"]} == {
            "unsupported" if unsupported else "declarations_recorded"
        }
        assert association["response_count"] == link["response_count"] > 0
        assert association["population_subjects"] == link["population_subjects"]
        assert_unsigned(association)


@pytest.mark.parametrize("declaration", ["no_section", "no_package", "neither", "wrong_section", "wrong_package"])
def test_missing_or_unmatched_declared_anchors_remain_explicit_unresolved_sidecars(
        tmp_path, base_case, base_link, declaration):
    mapping = mapping_for(base_link)
    if declaration in {"no_section", "neither"}:
        mapping["section_entry_cid"] = None
    if declaration in {"no_package", "neither"}:
        mapping["source_package_entry_cid"] = None
    if declaration == "wrong_section":
        mapping["section_entry_cid"] = _PRIMARY.identity("different-section")
    if declaration == "wrong_package":
        mapping["source_package_entry_cid"] = _PRIMARY.identity("different-package")
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        lookup = index.lookup_sections(mapping["legal_id"])
        association = prepare(base_case, base_link, index, mapping=mapping)
        assert_unsigned(association, unresolved=True)
        assert association["issues"] and association["primary_artifact_refs"] == []
        assert association["mapping"] == mapping and association["primary_lookup"] == lookup
        assert validate(base_case, base_link, index, association, mapping=mapping) == association


@pytest.mark.parametrize("damage", [
    "missing_section", "two_sections", "duplicate_section", "conflicting_section",
    "missing_target", "wrong_target_kind", "reversed_relationship", "duplicate_edge",
    "conflicting_edge", "duplicate_package", "conflicting_package",
])
def test_physical_primary_ambiguity_conflict_and_dangling_evidence_remain_visible(
        tmp_path, base_case, base_link, damage):
    nodes = [_PRIMARY.node("section"), _PRIMARY.node("package", "source_package", None)]
    edges = [_PRIMARY.edge()]
    if damage == "missing_section":
        nodes.pop(0)
    elif damage == "two_sections":
        nodes.append(_PRIMARY.node("another-section"))
    elif damage == "duplicate_section":
        nodes.append(deepcopy(nodes[0]))
    elif damage == "conflicting_section":
        nodes.append(_PRIMARY.node("section", label="different literal body"))
    elif damage == "missing_target":
        edges = [_PRIMARY.edge(target="absent")]
    elif damage == "wrong_target_kind":
        nodes[1]["node_type"] = "code"
    elif damage == "reversed_relationship":
        edges = [_PRIMARY.edge(source="package", target="section")]
    elif damage == "duplicate_edge":
        edges.append(deepcopy(edges[0]))
    elif damage == "conflicting_edge":
        edges.append(_PRIMARY.edge(target="section"))
    elif damage == "duplicate_package":
        nodes.append(deepcopy(nodes[1]))
    else:
        nodes.append(_PRIMARY.node("package", "source_package", None, source_cid="different"))
    path, index_args = _PRIMARY.fixture(tmp_path, nodes=nodes, edges=edges)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        lookup = index.lookup_sections("usc:us:10:1")
        association = prepare(base_case, base_link, index)
        assert_unsigned(association, unresolved=True)
        assert association["issues"] and association["primary_artifact_refs"] == []
        assert association["primary_lookup"] == lookup
        assert association["primary_index_receipt"]["rows"] == len(nodes) + len(edges)
        assert association["population_subjects"] == base_link["population_subjects"]


@pytest.mark.parametrize("legal_id", ["usc:us:10:01", "USC:US:10:1", "usc:us:10:2"])
def test_release_shape_valid_aliases_are_literal_lookup_gaps_not_normalized(
        tmp_path, base_case, base_link, legal_id):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        mapping = mapping_for(base_link, legal_id=legal_id)
        association = prepare(base_case, base_link, index, mapping=mapping)
        assert_unsigned(association, unresolved=True)
        assert association["primary_lookup"]["legal_id"] == legal_id
        assert association["primary_lookup"]["sections"] == []
        assert association["primary_artifact_refs"] == []


@pytest.mark.parametrize("legal_id", ["10 USC 1", "usc:us:10:1 ", " usc:us:10:1"])
def test_release_shape_or_trimmed_alias_cannot_rewrite_mapping_legal_id(
        tmp_path, base_case, base_link, legal_id):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        with pytest.raises(ValueError):
            prepare(base_case, base_link, index, mapping=mapping_for(base_link, legal_id=legal_id))


@pytest.mark.parametrize("pin_name", [
    "expected_correspondence_sha256", "expected_mapping_file_sha256", "expected_index_sha256",
])
def test_independent_input_pins_cannot_be_replaced_by_self_consistency(
        tmp_path, base_case, base_link, pin_name):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        with pytest.raises(ValueError):
            prepare(base_case, base_link, index, **{pin_name: sha(pin_name.encode())})


@pytest.mark.parametrize("damage", [
    "correspondence", "source_identity", "missing_occurrence", "reordered_occurrences",
    "duplicate_occurrence", "substituted_occurrence",
])
def test_rehashed_mapping_cannot_substitute_source_identity_or_any_ordered_occurrence(
        base_case, base_link, damage):
    mapping = mapping_for(base_link)
    if damage == "correspondence":
        mapping["correspondence_sha256"] = sha(b"other correspondence")
    elif damage == "source_identity":
        mapping["source_identity_sha256"] = sha(b"other source")
    elif damage == "missing_occurrence":
        mapping["source_occurrence_cids"].pop()
    elif damage == "reordered_occurrences":
        mapping["source_occurrence_cids"].reverse()
    elif damage == "duplicate_occurrence":
        mapping["source_occurrence_cids"][-1] = mapping["source_occurrence_cids"][0]
    else:
        mapping["source_occurrence_cids"][-1] = _PRIMARY.identity("other occurrence")
    raw = transport(mapping)
    with patch.object(owner, "_owners", side_effect=AssertionError("operation owner reached")) as operation:
        with pytest.raises(ValueError):
            owner.prepare_sampled_primary_association_v2(
                base_link, base_case["binding"], base_case["subject"], object(),
                expected_correspondence_sha256=digest(base_link),
                correspondence_replay_inputs=base_case["args"], mapping_raw=raw,
                expected_mapping_file_sha256=sha(raw), expected_index_sha256="a" * 64,
            )
        operation.assert_not_called()


@pytest.mark.parametrize("damage", [
    "unknown_field", "missing_field", "wrong_schema", "duplicate_key", "invalid_json",
    "invalid_utf8", "nonfinite", "wrong_raw_type", "over_mapping_bytes",
    "occurrences_type", "occurrences_over_count", "empty_occurrences", "nonstring_occurrence",
    "boolean_section", "list_package", "blank_id", "nul_id", "oversized_unicode_id",
])
def test_closed_mapping_json_and_finite_types_refuse_before_operation_imports(
        base_case, base_link, damage):
    mapping = mapping_for(base_link)
    raw = None
    if damage == "unknown_field":
        mapping["authority"] = True
    elif damage == "missing_field":
        mapping.pop("source_identity_sha256")
    elif damage == "wrong_schema":
        mapping["schema"] = "another-mapping/v1"
    elif damage == "duplicate_key":
        raw = b'{"schema":"duplicate",' + wire(mapping)[1:]
    elif damage == "invalid_json":
        raw = b"{not JSON"
    elif damage == "invalid_utf8":
        raw = b"\xff"
    elif damage == "nonfinite":
        raw = wire(mapping).replace(b'"source_package_entry_cid":', b'"extra":NaN,"source_package_entry_cid":')
    elif damage == "wrong_raw_type":
        raw = bytearray(transport(mapping))
    elif damage == "over_mapping_bytes":
        raw = wire(mapping) + b" " * owner.MAX_MAPPING_BYTES
    elif damage == "occurrences_type":
        mapping["source_occurrence_cids"] = {"not": "an ordered list"}
    elif damage == "occurrences_over_count":
        mapping["source_occurrence_cids"] = [_PRIMARY.identity(str(i)) for i in range(257)]
    elif damage == "empty_occurrences":
        mapping["source_occurrence_cids"] = []
    elif damage == "nonstring_occurrence":
        mapping["source_occurrence_cids"][0] = True
    elif damage == "boolean_section":
        mapping["section_entry_cid"] = True
    elif damage == "list_package":
        mapping["source_package_entry_cid"] = ["not literal"]
    elif damage == "blank_id":
        mapping["legal_id"] = " "
    elif damage == "nul_id":
        mapping["legal_id"] = "usc:us:10:1\x00"
    else:
        mapping["legal_id"] = "é" * 2049
    if raw is None:
        raw = transport(mapping)
    with patch.object(owner, "_owners", side_effect=AssertionError("operation owner reached")) as operation:
        with pytest.raises(ValueError):
            owner.prepare_sampled_primary_association_v2(
                base_link, base_case["binding"], base_case["subject"], object(),
                expected_correspondence_sha256=digest(base_link),
                correspondence_replay_inputs=base_case["args"], mapping_raw=raw,
                expected_mapping_file_sha256=sha(raw), expected_index_sha256="a" * 64,
            )
        operation.assert_not_called()


@pytest.mark.parametrize("damage", ["extra", "missing", "binary_aggregate", "nonfinite", "deep", "invalid_pin"])
def test_complete_replay_preflight_is_closed_and_bounded_before_lazy_owners(
        base_case, base_link, damage):
    replay = deepcopy(base_case["args"])
    expected_index = "a" * 64
    if damage == "extra":
        replay["caller_verifier"] = "unrequested callback"
    elif damage == "missing":
        replay.pop("context_inputs")
    elif damage == "binary_aggregate":
        replay["candidate_inputs"]["raw_html"] = b"x" * (128 * 1024 * 1024 + 1)
    elif damage == "nonfinite":
        replay["dependency_manifest"]["invalid"] = float("inf")
    elif damage == "deep":
        value = "leaf"
        for _ in range(65):
            value = [value]
        replay["dependency_manifest"]["invalid"] = value
    else:
        expected_index = True
    raw = transport(mapping_for(base_link))
    with patch.object(owner, "_owners", side_effect=AssertionError("operation owner reached")) as operation:
        with pytest.raises(ValueError):
            owner.prepare_sampled_primary_association_v2(
                base_link, base_case["binding"], base_case["subject"], object(),
                expected_correspondence_sha256=digest(base_link),
                correspondence_replay_inputs=replay, mapping_raw=raw,
                expected_mapping_file_sha256=sha(raw), expected_index_sha256=expected_index,
            )
        operation.assert_not_called()


def test_old_public_validator_replays_the_complete_original_input_closure(tmp_path, base_case, base_link):
    path, index_args = _PRIMARY.fixture(tmp_path)
    original = correspondence_owner.validate_definition_review_correspondence_v2
    with primary.PrimarySectionIndex(path, **index_args) as index:
        with patch.object(correspondence_owner, "validate_definition_review_correspondence_v2", wraps=original) as replay:
            association = prepare(base_case, base_link, index)
        replay.assert_called_once()
        positional, keywords = replay.call_args
        assert positional == (base_link, base_case["binding"], base_case["subject"])
        assert keywords == {
            "expected_correspondence_sha256": digest(base_link), **base_case["args"],
        }
        assert positional[0] is not base_link
        assert_unsigned(association)


@pytest.mark.parametrize("damage", ["raw_source", "binding_pin", "subject_pin", "context_order", "dependency_closure"])
def test_original_source_subject_and_dependency_evidence_cannot_be_swapped_for_self_pins(
        tmp_path, base_case, base_link, damage):
    replay = deepcopy(base_case["args"])
    if damage == "raw_source":
        replay["candidate_inputs"]["raw_html"] += b" "
        replay["expected_candidate_pin"]["raw_sha256"] = sha(replay["candidate_inputs"]["raw_html"])
        replay["expected_candidate_pin"]["raw_bytes"] += 1
    elif damage == "binding_pin":
        replay["expected_binding_sha256"] = sha(b"other binding")
    elif damage == "subject_pin":
        replay["expected_subject_sha256"] = sha(b"other subject")
    elif damage == "context_order":
        replay["context_inputs"].reverse()
        replay["expected_context_population"].reverse()
    else:
        replay["required_dependency_ids"].pop()
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        with pytest.raises(ValueError):
            prepare(base_case, base_link, index, correspondence_replay_inputs=replay)


def test_exact_live_index_type_and_independent_receipt_are_required(tmp_path, base_case, base_link):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        kwargs = arguments(base_case, base_link, index)
    class Impostor:
        def guard(self):
            raise AssertionError("unrequested caller callback invoked")
    with pytest.raises(ValueError):
        owner.prepare_sampled_primary_association_v2(
            base_link, base_case["binding"], base_case["subject"], Impostor(), **kwargs)
    with pytest.raises(ValueError):
        owner.prepare_sampled_primary_association_v2(
            base_link, base_case["binding"], base_case["subject"], index, **kwargs)


def test_closed_index_cannot_revalidate_a_retained_association(tmp_path, base_case, base_link):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        kwargs = arguments(base_case, base_link, index)
        association = owner.prepare_sampled_primary_association_v2(
            base_link, base_case["binding"], base_case["subject"], index, **kwargs)
    with pytest.raises(ValueError):
        owner.validate_sampled_primary_association_v2(
            association, base_link, base_case["binding"], base_case["subject"], index,
            expected_association_sha256=digest(association), **kwargs)


def test_source_file_mutation_invalidates_live_index_before_association_replay(tmp_path, base_case, base_link):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with pytest.raises(primary.PrimarySectionIndexError):
        with primary.PrimarySectionIndex(path, **index_args) as index:
            association = prepare(base_case, base_link, index)
            kwargs = arguments(base_case, base_link, index)
            with path.open("ab") as stream:
                stream.write(b" ")
            with pytest.raises(primary.PrimarySectionIndexError):
                owner.validate_sampled_primary_association_v2(
                    association, base_link, base_case["binding"], base_case["subject"], index,
                    expected_association_sha256=digest(association), **kwargs)


@pytest.mark.parametrize("damage", [
    "authority", "training_boolean", "gold_float", "population", "occurrence_order",
    "roles", "context_slots", "mapping", "transport", "lookup", "artifact_refs", "identity",
])
def test_resealing_complete_sidecar_tampering_cannot_replace_original_regeneration(
        tmp_path, base_case, base_link, damage):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        original = prepare(base_case, base_link, index)
        offered = deepcopy(original)
        if damage == "authority":
            offered["authority"]["source_semantics_verified"] = True
        elif damage == "training_boolean":
            offered["training_mask"] = False
        elif damage == "gold_float":
            offered["evaluation_gold_mask"] = 0.0
        elif damage == "population":
            offered["population_subjects"].pop()
        elif damage == "occurrence_order":
            offered["occurrence_context_links"].reverse()
        elif damage == "roles":
            offered["source_role_bindings"].reverse()
        elif damage == "context_slots":
            offered["context_slot_ids"].reverse()
        elif damage == "mapping":
            offered["mapping"]["source_package_entry_cid"] = _PRIMARY.identity("other")
        elif damage == "transport":
            offered["mapping_transport"]["utf8"] += " "
        elif damage == "lookup":
            offered["primary_lookup"]["sections"][0]["section_observation"]["original_body"]["label"] += " substituted"
        elif damage == "artifact_refs":
            offered["primary_artifact_refs"].pop()
        else:
            offered["primary_identity"]["revision"] = "c" * 40
        offered = reseal(offered)
        assert digest(offered) != digest(original)
        with pytest.raises(ValueError):
            validate(base_case, base_link, index, offered)


def test_wrong_independent_sidecar_pin_refuses_before_regeneration(tmp_path, base_case, base_link):
    path, index_args = _PRIMARY.fixture(tmp_path)
    with primary.PrimarySectionIndex(path, **index_args) as index:
        association = prepare(base_case, base_link, index)
        with patch.object(owner, "prepare_sampled_primary_association_v2", side_effect=AssertionError("regeneration reached")) as regenerate:
            with pytest.raises(ValueError):
                owner.validate_sampled_primary_association_v2(
                    association, base_link, base_case["binding"], base_case["subject"], index,
                    expected_association_sha256=sha(b"different complete sidecar"),
                    **arguments(base_case, base_link, index),
                )
            regenerate.assert_not_called()


def test_full_lookup_over_result_bound_refuses_without_truncating_or_mutating_inputs(
        tmp_path, base_case, base_link):
    nodes = [_PRIMARY.node("section")]
    edges = []
    for i in range(18):
        key = "package" if i == 0 else "additional-package-" + str(i)
        nodes.append(_PRIMARY.node(key, "source_package", None, opaque_padding="x" * 60_000))
        edges.append(_PRIMARY.edge("source-evidence-" + str(i), target=key))
    path, index_args = _PRIMARY.fixture(tmp_path, nodes=nodes, edges=edges)
    original = path.read_bytes()
    with primary.PrimarySectionIndex(path, **index_args) as index:
        lookup = index.lookup_sections("usc:us:10:1")
        assert len(wire(lookup)) > owner.MAX_RECORD_BYTES
        assert len(lookup["sections"][0]["source_packages"]) == 18
        receipt = index.receipt
        with pytest.raises(ValueError):
            prepare(base_case, base_link, index)
        assert index.receipt == receipt and index.lookup_sections("usc:us:10:1") == lookup
    assert path.read_bytes() == original


def test_public_import_of_real_module_source_has_no_operation_import_or_write(monkeypatch):
    path = Path(owner.__file__)
    name = "_sampled_primary_association_cold_public_source"
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
            raise AssertionError("operation owner imported during public module import")
        return original_import(import_name, *args, **kwargs)
    def checked_open(file, mode="r", *args, **kwargs):
        if type(mode) is str and any(flag in mode for flag in "wax+"):
            attempts.append("file write")
            raise AssertionError("public module import wrote a file")
        return original_open(file, mode, *args, **kwargs)
    def checked_os_open(file, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            attempts.append("descriptor write")
            raise AssertionError("public module import wrote through os.open")
        return original_os_open(file, flags, *args, **kwargs)
    with patch.object(builtins, "__import__", checked_import), patch.object(builtins, "open", checked_open), patch.object(io, "open", checked_open), patch.object(os, "open", checked_os_open):
        spec.loader.exec_module(cold)
    assert attempts == []
    assert cold._OPERATION_PINS is None
    assert cold.SCHEMA == owner.SCHEMA and cold.PROFILE == owner.PROFILE
    assert all(hasattr(cold, symbol) for symbol in (
        "prepare_sampled_primary_association_v2", "validate_sampled_primary_association_v2",
        "sampled_primary_association_sha256",
    ))
