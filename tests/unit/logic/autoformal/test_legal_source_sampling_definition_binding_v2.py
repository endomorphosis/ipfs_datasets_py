"""Explicit fictional interpretations bind to source review without admission.

The fixture uses the existing real sampler, source custody, V2 definition
compiler and corpus adapter. Reviewer declarations below are synthetic and
unverified; they are neither statutory review evidence nor training targets.
Boundary spies only establish that malformed inputs cannot reach operation
owners. They do not substitute for the successful production path.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_definition_adapter_v2 as adapter
from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody
from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review as review
from ipfs_datasets_py.logic.autoformal import (
    legal_source_sampling_definition_binding_v2 as binding,
)
from ipfs_datasets_py.logic.autoformal.corpus_contracts import seal_record


_SPEC = importlib.util.spec_from_file_location(
    "_sampling_definition_binding_fictional_fixture",
    Path(__file__).with_name("test_legal_source_definition_bridge_v2.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)
_UNSET = object()


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(canonical(value))


def transport(value):
    # Original-byte custody must not collapse to a canonical JSON commitment.
    return json.dumps(
        value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
    ).encode("utf-8") + b"\n"


def reseal(value):
    return seal_record(
        {key: item for key, item in value.items() if key not in {"record_cid", "cid_scope"}}
    )


def prepared(**options):
    request, source = _FIXTURE.authored_request(**options)
    raw = source["raw_html"]
    replay = {
        key: value
        for key, value in source.items()
        if key not in {"raw_html", "sampling_report"}
    }
    bundle = review.prepare_sampling_review_bundle(raw, **replay)
    return {
        "request": request,
        "request_raw": transport(request),
        "raw": raw,
        "replay": replay,
        "bundle": bundle,
    }


def prepared_with_split_scope():
    """Keep a required scope parent and an unrelated parent in the real view.

    Fragmented paragraphs remain noncandidate sampler units. The independently
    authored definition stays in one ordinary paragraph; its explicit scope
    points to the first fragment of the preceding physical scope paragraph.
    """
    request, source = _FIXTURE.authored_request()
    raw = source["raw_html"].replace(
        b"(a) In this title:</p>",
        b"(a) In this title:<br>Scope continuation retained for review.</p>",
        1,
    ).replace(
        b"(b) Later authored body.</p>",
        b"(b) Later authored body.<br>Unrelated parent continuation.</p>",
        1,
    )
    descriptor = deepcopy(source["descriptor"])
    descriptor.update(raw_sha256=sha(raw), raw_bytes=len(raw))
    replay = {
        "descriptor": descriptor,
        "expected_descriptor_sha256": custody.acquisition_descriptor_sha256(descriptor),
        "expected_raw_sha256": sha(raw),
        "expected_raw_bytes": len(raw),
    }
    sampling = sampler.prepare_source_sampling(raw, **replay)
    records = {row["record_cid"]: row for row in sampling["records"]}
    units = [row for row in records.values() if row["schema"] == sampler.UNIT_SCHEMA]
    text = sampling["document_view_report"]["document"]["document_text"]

    def unit_text(unit):
        return records[unit["source_occurrence_ref"]["record_cid"]]["span_text"]

    def unit_ref(unit):
        return next(
            ref for ref in sampling["unit_refs"]
            if ref["record_cid"] == unit["record_cid"]
        )

    scope = next(unit for unit in units if unit_text(unit) == "(a) In this title:")
    definition = next(
        unit for unit in units if unit_text(unit).startswith('(1) The term "café filer"')
    )

    def reanchor(value):
        if type(value) is dict:
            if set(value) == {"char_start", "char_end", "text"}:
                start = text.index(value["text"])
                return {
                    "char_start": start,
                    "char_end": start + len(value["text"]),
                    "text": value["text"],
                }
            return {key: reanchor(item) for key, item in value.items()}
        if type(value) is list:
            return [reanchor(item) for item in value]
        return value

    request = reanchor(request)
    declaration = request["declaration"]
    declaration["source_version_ref"] = definition["source_version_ref"]
    declaration["normalized_view_id"] = definition["normalized_view_id"]
    declaration["scope_unit_ref"] = unit_ref(scope)
    declaration["contributor_unit_refs"] = [unit_ref(definition)]
    replay["expected_sampling_report_sha256"] = sampler.source_sampling_report_sha256(sampling)
    bundle = review.prepare_sampling_review_bundle(raw, **replay)
    return {
        "request": request,
        "request_raw": transport(request),
        "raw": raw,
        "replay": replay,
        "bundle": bundle,
    }


def split_parent_guides(case):
    """Select the two known fictional physical parents by their source text."""
    sampling = case["bundle"]["sampling_report"]
    records = {row["record_cid"]: row for row in sampling["records"]}
    parents = sampling["withheld_paragraph_contexts"]
    assert len(parents) == 2

    def guide_with_prefix(prefix):
        index, parent = next(
            (index, parent) for index, parent in enumerate(parents)
            if records[parent["source_occurrence_ref"]["record_cid"]]["span_text"].startswith(prefix)
        )
        subject = {"kind": "withheld_context", "index": index, "sha256": digest(parent)}
        return next(
            guide for guide in case["bundle"]["guides"]
            if guide["subject_ref"] == subject
        )

    return guide_with_prefix("(a) In this title:"), guide_with_prefix("(b) Later authored body.")


@pytest.fixture(scope="module")
def source_case():
    return prepared()


@pytest.fixture(scope="module")
def base_result(source_case):
    return prepare(source_case)


@pytest.fixture(scope="module")
def split_scope_case():
    return prepared_with_split_scope()


@pytest.fixture(scope="module")
def split_scope_result(split_scope_case):
    return prepare(split_scope_case)


def prepare(
    case,
    *,
    request_raw=_UNSET,
    bundle=_UNSET,
    responses=_UNSET,
    raw=_UNSET,
    **overrides,
):
    request_raw = case["request_raw"] if request_raw is _UNSET else request_raw
    bundle = case["bundle"] if bundle is _UNSET else bundle
    responses = [] if responses is _UNSET else responses
    raw = case["raw"] if raw is _UNSET else raw
    args = {
        "expected_request_sha256": sha(request_raw)
        if isinstance(request_raw, (bytes, bytearray, memoryview))
        else sha(case["request_raw"]),
        "expected_bundle_sha256": digest(bundle),
        "expected_response_sha256s": [digest(row) for row in responses],
        **case["replay"],
        **overrides,
    }
    return binding.prepare_definition_binding_v2(
        request_raw, bundle, responses, raw, **args
    )


def validate(case, result, *, responses=None, **overrides):
    responses = [] if responses is None else responses
    args = {
        "expected_binding_sha256": digest(result),
        "expected_request_sha256": sha(case["request_raw"]),
        "expected_bundle_sha256": digest(case["bundle"]),
        "expected_response_sha256s": [digest(row) for row in responses],
        **case["replay"],
        **overrides,
    }
    return binding.validate_definition_binding_v2(
        result,
        case["request_raw"],
        case["bundle"],
        responses,
        case["raw"],
        **args,
    )


def selected_guides(case):
    declaration = case["request"]["declaration"]
    cids = {
        row["record_cid"]
        for row in declaration["contributor_unit_refs"]
        + [declaration["scope_unit_ref"]]
    }
    units = {
        row["ordinal"]: row
        for row in case["bundle"]["sampling_report"]["records"]
        if row["schema"] == sampler.UNIT_SCHEMA
    }
    return [
        guide
        for guide in case["bundle"]["guides"]
        if guide["subject_ref"]["kind"] == "unit"
        and units[guide["subject_ref"]["index"]]["record_cid"] in cids
    ]


def response(
    case,
    guide,
    *,
    principal="synthetic-binding-reviewer-not-an-authenticated-person",
    source_only=False,
    unsupported=False,
    finding="An authored fixture proposal, not a reviewed legal interpretation.",
):
    value = deepcopy(guide["response_template"])
    value["bundle_sha256"] = digest(case["bundle"])
    value["reviewer_declaration"] = {
        "principal_id": principal,
        "role": "source_reviewer",
        "issued_at_utc": "2026-10-15T01:00:00Z",
        "identity_evidence_refs": [],
        "independence_evidence_refs": [],
    }
    value["exposure_declaration"] = {
        "candidate_interpretations_exposed": True,
        "organizer_source_metadata_exposed": True,
        "other_exposure": ["Synthetic fictional fixture with an explicit caller request."],
    }
    for field in ("source_answers", "meaning_proposals"):
        unresolved = source_only and field == "meaning_proposals"
        for answer in value[field]:
            answer.update(
                disposition="unresolved"
                if unresolved
                else "evidence_declared"
                if field == "source_answers"
                else "proposal",
                finding=finding,
                rationale="Exercise source-bound declaration custody without authenticating review.",
                evidence_refs=[]
                if unresolved
                else [deepcopy(guide["evidence_refs"][0])],
                unresolved_requirements=["Actual independent meaning review is absent."]
                if unresolved
                else [],
            )
    if unsupported:
        value["meaning_proposals"][0]["disposition"] = "unsupported"
    return review.record_sampling_review_response(
        case["bundle"],
        value,
        case["raw"],
        expected_bundle_sha256=digest(case["bundle"]),
        **case["replay"],
    )


def assert_no_authority(result):
    metadata = result["binding"]
    report = result["definition_report"]
    candidate = result["candidate"]
    population = result["population"]
    for item in (metadata, report, population):
        assert item["authority"]
        assert all(flag is False for flag in item["authority"].values())
    for item in (metadata, population):
        assert type(item["training_mask"]) is int and item["training_mask"] == 0
        assert (
            type(item["evaluation_gold_mask"]) is int
            and item["evaluation_gold_mask"] == 0
        )
    assert all(candidate[flag] is False for flag in adapter.FALSE_FLAGS)
    assert report["authority"]["backend_executed"] is False
    assert report["authority"]["lean_compilation_verified"] is False
    assert population["review_completed"] is False
    assert population["adjudication_performed"] is False
    assert population["latest_response_selected"] is False


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_explicit_request_compiles_without_inventing_pending_review(family):
    case = prepared(family=family)
    result = prepare(case)
    assert set(result) == {
        "schema", "binding", "definition_report", "candidate", "population"
    }
    metadata = result["binding"]
    report = result["definition_report"]
    population = result["population"]
    assert report["family"] == result["candidate"]["family"] == family
    assert report["declaration"] == case["request"]["declaration"]
    assert report["native_ast"]["quantifier"]["value"] == "∀"
    assert report["native_ast"]["formula"]["operator"]["value"] == "↔"
    assert result["candidate"]["definition_record"]["native_ast"] == report["native_ast"]
    assert metadata["status"] == "pending"
    assert metadata["response_count"] == 0 and metadata["response_refs"] == []
    assert metadata["interpretation_status"] == "unreviewed_caller_declaration"
    assert metadata["all_selected_subjects_have_declarations"] is False
    assert [row["subject_ref"] for row in metadata["required_subjects"]] == [
        guide["subject_ref"] for guide in selected_guides(case)
    ]
    assert metadata["selected_subject_count"] == 2
    assert all(
        row["state"] == "pending" and row["response_refs"] == []
        for row in metadata["required_subjects"]
    )
    assert [row["subject_ref"] for row in population["subjects"]] == [
        guide["subject_ref"] for guide in case["bundle"]["guides"]
    ]
    assert population["subject_count"] > metadata["selected_subject_count"]
    assert population["counts"]["pending"] == len(case["bundle"]["guides"])
    assert_no_authority(result)
    assert binding.definition_binding_sha256(result) == digest(result)
    assert validate(case, result) == result


def test_each_native_source_role_retains_exact_units_context_and_required_subjects(
    source_case, base_result
):
    metadata = base_result["binding"]
    report = base_result["definition_report"]
    assert metadata["source_role_population_complete"] is True
    assert metadata["selected_subject_population_complete"] is True
    assert [
        {key: value for key, value in row.items() if key != "subject_refs"}
        for row in metadata["source_role_bindings"]
    ] == report["source_bindings"]
    declaration = source_case["request"]["declaration"]
    assert sorted(digest(row["unit_ref"]) for row in metadata["selected_unit_roles"]) == sorted(
        digest(ref)
        for ref in declaration["contributor_unit_refs"] + [declaration["scope_unit_ref"]]
    )
    units = {
        row["ordinal"]: row
        for row in source_case["bundle"]["sampling_report"]["records"]
        if row["schema"] == sampler.UNIT_SCHEMA
    }
    guides = {
        guide["subject_ref"]["index"]: guide
        for guide in selected_guides(source_case)
    }
    for row in metadata["selected_unit_roles"]:
        subject = row["subject_ref"]
        unit = units[subject["index"]]
        assert subject["kind"] == "unit" and subject["sha256"] == digest(unit)
        assert row["unit_ref"]["record_cid"] == unit["record_cid"]
        assert row["unit_ref"]["sha256"] == digest(unit)
    for row in metadata["source_role_bindings"]:
        assert row["subject_refs"] == [guides[index]["subject_ref"] for index in row["block_indices"]]
    assert sha(source_case["request_raw"]) != digest(source_case["request"])


def test_repeated_unicode_leaves_keep_distinct_physical_occurrences():
    case = prepared(mode="repeated")
    result = prepare(case)
    rows = {
        row["role"]: row for row in result["binding"]["source_role_bindings"]
    }
    first, second = [rows[f"definition_body/{index:04d}"] for index in (0, 1)]
    assert first["source_occurrence_cid"] != second["source_occurrence_cid"]
    assert first["symbol"] == second["symbol"]
    assert first["subject_refs"] != second["subject_refs"]
    assert result["binding"]["selected_subject_count"] == 3
    origins = {
        row["record_cid"]: row for row in result["definition_report"]["source_occurrences"]
    }
    head = origins[rows["definition_head"]["source_occurrence_cid"]]
    assert head["span_text"] == "café filer"
    assert head["end_utf8"] - head["start_utf8"] == len("café filer".encode("utf-8"))
    assert head["end_utf8"] - head["start_utf8"] > len(head["span_text"])
    assert_no_authority(result)


def test_same_physical_atom_can_have_two_roles_without_losing_either():
    case = prepared()
    atom = deepcopy(case["request"]["declaration"]["body"]["operands"][0])
    case["request"]["declaration"]["body"] = {
        "op": "any", "operands": [deepcopy(atom), deepcopy(atom)]
    }
    case["request_raw"] = transport(case["request"])
    result = prepare(case)
    bodies = [
        row for row in result["binding"]["source_role_bindings"]
        if row["role"].startswith("definition_body/")
    ]
    assert [row["role"] for row in bodies] == ["definition_body/0000", "definition_body/0001"]
    assert bodies[0]["source_occurrence_cid"] == bodies[1]["source_occurrence_cid"]
    assert bodies[0]["context_cid"] == bodies[1]["context_cid"]
    assert bodies[0]["subject_refs"] == bodies[1]["subject_refs"]


def test_split_scope_keeps_the_exact_required_parent_and_complete_other_population(
    split_scope_case, split_scope_result
):
    case, result = split_scope_case, split_scope_result
    parent, unrelated = split_parent_guides(case)
    unit_guides = selected_guides(case)
    expected_subjects = {digest(guide["subject_ref"]) for guide in unit_guides + [parent]}
    metadata = result["binding"]
    assert len(unit_guides) == 2
    assert metadata["selected_subject_count"] == 3
    assert [row["subject_ref"] for row in metadata["required_subjects"]] == [
        guide["subject_ref"] for guide in case["bundle"]["guides"]
        if digest(guide["subject_ref"]) in expected_subjects
    ]
    required_parent = next(
        row for row in metadata["required_subjects"]
        if row["subject_ref"] == parent["subject_ref"]
    )
    assert set(required_parent["roles"]) == {"scope_block", "scope_literal"}
    assert required_parent["guide_ref"] == {
        "schema": parent["schema"],
        "record_cid": parent["record_cid"],
        "sha256": digest(parent),
    }
    scope_subject = next(
        row["subject_ref"] for row in metadata["selected_unit_roles"]
        if row["role"] == "scope_unit"
    )
    for row in metadata["source_role_bindings"]:
        assert unrelated["subject_ref"] not in row["subject_refs"]
        if row["role"] in {"scope_block", "scope_literal"}:
            assert row["subject_refs"] == [scope_subject, parent["subject_ref"]]
        else:
            assert parent["subject_ref"] not in row["subject_refs"]
    population = result["population"]
    assert [row["subject_ref"] for row in population["subjects"]] == [
        guide["subject_ref"] for guide in case["bundle"]["guides"]
    ]
    assert population["counts"]["pending"] == len(case["bundle"]["guides"])
    assert sum(row["subject_ref"]["kind"] == "withheld_context" for row in population["subjects"]) == 2
    assert all(row["response_refs"] == [] for row in metadata["required_subjects"])
    assert metadata["status"] == "pending"
    assert metadata["all_selected_subjects_have_declarations"] is False
    assert_no_authority(result)


def test_unit_only_declarations_stay_pending_until_the_exact_parent_is_supplied(
    split_scope_case, split_scope_result
):
    case = split_scope_case
    parent, unrelated = split_parent_guides(case)
    unit_responses = [response(case, guide) for guide in selected_guides(case)]
    unit_only = prepare(case, responses=unit_responses)
    parent_state = next(
        row for row in unit_only["binding"]["required_subjects"]
        if row["subject_ref"] == parent["subject_ref"]
    )
    assert parent_state["state"] == "pending" and parent_state["response_refs"] == []
    assert unit_only["binding"]["status"] == "pending"
    assert unit_only["binding"]["all_selected_subjects_have_declarations"] is False
    assert all(
        row["state"] == "declarations_recorded"
        for row in unit_only["binding"]["required_subjects"]
        if row["subject_ref"]["kind"] == "unit"
    )
    parent_response = response(case, parent)
    complete = prepare(case, responses=unit_responses + [parent_response])
    assert complete["binding"]["status"] == "declarations_recorded"
    assert complete["binding"]["all_selected_subjects_have_declarations"] is True
    assert complete["binding"]["response_count"] == complete["binding"]["selected_subject_count"] == 3
    complete_parent = next(
        row for row in complete["binding"]["required_subjects"]
        if row["subject_ref"] == parent["subject_ref"]
    )
    assert complete_parent["state"] == "declarations_recorded"
    assert [ref["record_cid"] for ref in complete_parent["response_refs"]] == [parent_response["record_cid"]]
    unrelated_state = next(
        row for row in complete["population"]["subjects"]
        if row["subject_ref"] == unrelated["subject_ref"]
    )
    assert unrelated_state["state"] == "pending" and unrelated_state["response_refs"] == []
    assert complete["population"]["all_subjects_have_declarations"] is False
    assert [row["subject_ref"] for row in complete["population"]["subjects"]] == [
        guide["subject_ref"] for guide in case["bundle"]["guides"]
    ]
    for result in (unit_only, complete):
        assert result["definition_report"] == split_scope_result["definition_report"]
        assert result["candidate"] == split_scope_result["candidate"]
        assert_no_authority(result)


def test_an_unrelated_withheld_parent_cannot_replace_the_required_scope_parent(split_scope_case):
    case = split_scope_case
    _, unrelated = split_parent_guides(case)
    offered = [response(case, guide) for guide in selected_guides(case)]
    offered.append(response(case, unrelated))
    with pytest.raises(ValueError):
        prepare(case, responses=offered)


@pytest.mark.parametrize(
    "change", ["required_omission", "role_omission", "parent_substitution", "population_omission"]
)
def test_resealed_parent_omission_or_substitution_cannot_change_source_closure(
    split_scope_case, split_scope_result, change
):
    case = split_scope_case
    parent, unrelated = split_parent_guides(case)
    result = deepcopy(split_scope_result)
    metadata = result["binding"]
    if change == "required_omission":
        metadata["required_subjects"] = [
            row for row in metadata["required_subjects"]
            if row["subject_ref"] != parent["subject_ref"]
        ]
        metadata["selected_subject_count"] -= 1
    elif change == "role_omission":
        for row in metadata["source_role_bindings"]:
            row["subject_refs"] = [
                ref for ref in row["subject_refs"] if ref != parent["subject_ref"]
            ]
    elif change == "parent_substitution":
        selected = next(
            row for row in metadata["required_subjects"]
            if row["subject_ref"] == parent["subject_ref"]
        )
        selected["subject_ref"] = deepcopy(unrelated["subject_ref"])
        selected["guide_ref"] = {
            "schema": unrelated["schema"],
            "record_cid": unrelated["record_cid"],
            "sha256": digest(unrelated),
        }
        for row in metadata["source_role_bindings"]:
            row["subject_refs"] = [
                deepcopy(unrelated["subject_ref"]) if ref == parent["subject_ref"] else ref
                for ref in row["subject_refs"]
            ]
    else:
        population = result["population"]
        population["subjects"] = [
            row for row in population["subjects"]
            if row["subject_ref"] != parent["subject_ref"]
        ]
        population["subject_count"] -= 1
        population["counts"]["pending"] -= 1
        result["population"] = reseal(population)
        metadata["population_ref"] = {
            "schema": result["population"]["schema"],
            "record_cid": result["population"]["record_cid"],
            "sha256": digest(result["population"]),
        }
    result["binding"] = reseal(metadata)
    with pytest.raises(ValueError):
        validate(case, result)


def test_source_only_response_leaves_meaning_pending_and_does_not_infer_an_AST(
    source_case, base_result
):
    offered = response(source_case, selected_guides(source_case)[0], source_only=True)
    result = prepare(source_case, responses=[offered])
    assert result["definition_report"] == base_result["definition_report"]
    assert result["candidate"] == base_result["candidate"]
    assert result["binding"]["status"] == "pending"
    assert result["binding"]["response_count"] == 1
    assert result["binding"]["all_selected_subjects_have_declarations"] is False
    assert_no_authority(result)


def test_free_text_proposal_cannot_replace_the_explicit_interpretation(
    source_case, base_result
):
    offered = response(
        source_case,
        selected_guides(source_case)[-1],
        finding="Fixture prose proposes an existential implication with the opposite body.",
    )
    result = prepare(source_case, responses=[offered])
    assert result["definition_report"] == base_result["definition_report"]
    assert result["candidate"] == base_result["candidate"]
    assert result["binding"]["status"] == "pending"
    assert_no_authority(result)


def test_complete_selected_declarations_keep_full_population_and_all_authority_false(
    source_case
):
    offered = [response(source_case, guide) for guide in selected_guides(source_case)]
    result = prepare(source_case, responses=offered)
    metadata = result["binding"]
    assert metadata["status"] == "declarations_recorded"
    assert metadata["all_selected_subjects_have_declarations"] is True
    assert metadata["response_count"] == len(offered) == metadata["selected_subject_count"]
    assert result["population"]["all_subjects_have_declarations"] is False
    assert result["population"]["counts"]["pending"] > 0
    assert [row["record_cid"] for row in metadata["response_refs"]] == [
        row["record_cid"] for row in offered
    ]
    assert_no_authority(result)
    assert validate(source_case, result, responses=offered) == result


def test_same_subject_conflicts_keep_both_reviewers_and_no_latest_winner(source_case):
    guide = selected_guides(source_case)[-1]
    a = response(source_case, guide, unsupported=True)
    b = response(source_case, guide, principal="another-unverified-fixture-principal")
    first = prepare(source_case, responses=[a, b])
    second = prepare(source_case, responses=[b, a])
    for result, offered in ((first, [a, b]), (second, [b, a])):
        assert result["binding"]["status"] == "disputed"
        selected = next(
            row for row in result["binding"]["required_subjects"]
            if row["subject_ref"] == guide["subject_ref"]
        )
        assert selected["state"] == "disputed"
        assert [row["record_cid"] for row in selected["response_refs"]] == [
            row["record_cid"] for row in offered
        ]
        assert_no_authority(result)
    assert first["population"]["counts"] == second["population"]["counts"]
    assert first["binding"]["response_refs"] != second["binding"]["response_refs"]
    assert first["candidate"] == second["candidate"]


def test_well_formed_response_for_an_unselected_subject_cannot_be_attached(source_case):
    selected = {digest(guide["subject_ref"]) for guide in selected_guides(source_case)}
    foreign = next(
        guide for guide in source_case["bundle"]["guides"]
        if digest(guide["subject_ref"]) not in selected
    )
    offered = response(source_case, foreign)
    with pytest.raises(ValueError):
        prepare(source_case, responses=[offered])


def test_identical_source_bytes_from_another_edition_cannot_supply_review(source_case):
    other = prepared(edition=2025)
    assert source_case["raw"] == other["raw"]
    offered = response(other, selected_guides(other)[-1])
    with pytest.raises(ValueError):
        prepare(source_case, responses=[offered])


@pytest.mark.parametrize("change", ["order", "missing", "hash", "duplicate", "tuple"])
def test_response_commitments_are_complete_distinct_and_ordered_before_owners(
    source_case, change
):
    offered = [response(source_case, guide) for guide in selected_guides(source_case)]
    pins = [digest(row) for row in offered]
    if change == "order":
        pins.reverse()
    elif change == "missing":
        pins.pop()
    elif change == "hash":
        pins[0] = "0" * 64
    elif change == "duplicate":
        offered = [offered[0], offered[0]]
        pins = [digest(offered[0])] * 2
    else:
        pins = tuple(pins)
    with patch.object(binding, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            prepare(source_case, responses=offered, expected_response_sha256s=pins)


@pytest.mark.parametrize(
    "change",
    ["request_pin", "bundle_pin", "raw_pin", "raw_length", "raw_boolean_length", "sampling_pin", "descriptor_pin"],
)
def test_independent_input_pins_refuse_before_operation_owners(source_case, change):
    key = {
        "request_pin": "expected_request_sha256",
        "bundle_pin": "expected_bundle_sha256",
        "raw_pin": "expected_raw_sha256",
        "raw_length": "expected_raw_bytes",
        "raw_boolean_length": "expected_raw_bytes",
        "sampling_pin": "expected_sampling_report_sha256",
        "descriptor_pin": "expected_descriptor_sha256",
    }[change]
    value = (
        len(source_case["raw"]) + 1 if change == "raw_length"
        else True if change == "raw_boolean_length"
        else "0" * 64
    )
    with patch.object(binding, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            prepare(source_case, **{key: value})


@pytest.mark.parametrize(
    "change",
    ["duplicate", "nested_duplicate", "nonfinite", "oversize", "truncated", "invalid_utf8", "mutable", "memoryview"],
)
def test_malformed_request_is_rejected_before_operation_owners(source_case, change):
    raw = source_case["request_raw"]
    if change == "duplicate":
        raw = raw.replace(b'"family": "fol"', b'"family": "fol", "family": "fol"', 1)
    elif change == "nested_duplicate":
        raw = raw.replace(b'"scope_kind": "title"', b'"scope_kind": "title", "scope_kind": "title"', 1)
    elif change == "nonfinite":
        raw = raw.replace(b'"legal_as_of_civil_date": null', b'"legal_as_of_civil_date": NaN', 1)
    elif change == "oversize":
        raw = b" " * (1024 * 1024 + 1)
    elif change == "truncated":
        raw = b"{"
    elif change == "invalid_utf8":
        raw = b"\xff"
    elif change == "mutable":
        raw = bytearray(raw)
    else:
        raw = memoryview(raw)
    assert raw != source_case["request_raw"] or type(raw) is not bytes
    with patch.object(binding, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            prepare(source_case, request_raw=raw)


@pytest.mark.parametrize("change", ["changed", "missing", "mutable"])
def test_raw_source_must_be_the_exact_immutable_original_before_owners(source_case, change):
    raw = source_case["raw"]
    if change == "changed":
        raw = raw[:-1] + (b"x" if raw[-1:] != b"x" else b"y")
    elif change == "missing":
        raw = None
    else:
        raw = bytearray(raw)
    with patch.object(binding, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            prepare(source_case, raw=raw)


@pytest.mark.parametrize("change", ["oversize", "nonfinite"])
def test_response_json_is_bounded_and_finite_before_owners(source_case, change):
    offered = response(source_case, selected_guides(source_case)[0])
    if change == "oversize":
        offered["source_answers"][0]["finding"] = "x" * (1024 * 1024 + 1)
    else:
        offered["source_answers"][0]["finding"] = float("nan")
    pin = sha(json.dumps(
        offered, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8"))
    with patch.object(binding, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            binding.prepare_definition_binding_v2(
                source_case["request_raw"], source_case["bundle"], [offered], source_case["raw"],
                expected_request_sha256=sha(source_case["request_raw"]),
                expected_bundle_sha256=digest(source_case["bundle"]),
                expected_response_sha256s=[pin], **source_case["replay"],
            )


@pytest.mark.parametrize("change", ["profile", "family", "operator", "scope", "contributor", "context"])
def test_unsupported_or_substituted_interpretation_never_falls_back_to_prose(
    source_case, change
):
    request = deepcopy(source_case["request"])
    if change == "profile":
        request["profile"] = "unsupported-binary-temporal-definition/v1"
    elif change == "family":
        request["family"] = "unsupported-family"
    elif change == "operator":
        request["declaration"]["body"] = {
            "op": "obligation", "operand": request["declaration"]["body"]
        }
    elif change == "scope":
        request["declaration"]["scope_unit_ref"] = deepcopy(
            request["declaration"]["contributor_unit_refs"][0]
        )
    elif change == "contributor":
        request["declaration"]["contributor_unit_refs"][0]["sha256"] = "0" * 64
    else:
        bundle = deepcopy(source_case["bundle"])
        context = next(
            row for row in bundle["sampling_report"]["records"]
            if row["schema"] == "legal-corpus-context-declaration/v1"
        )
        context["availability"] = "available"
        with pytest.raises(ValueError):
            prepare(source_case, bundle=bundle)
        return
    with pytest.raises(ValueError):
        prepare(source_case, request_raw=transport(request))


@pytest.mark.parametrize(
    "change",
    ["AST", "source_role", "subject", "population", "required_subject", "authority", "mask", "candidate_AST"],
)
def test_resealed_result_cannot_rewrite_meaning_source_review_or_authority(
    source_case, base_result, change
):
    result = deepcopy(base_result)
    if change == "AST":
        result["definition_report"]["native_ast"]["formula"]["operator"]["value"] = "→"
        result["definition_report"]["report_sha256"] = digest({
            key: value for key, value in result["definition_report"].items()
            if key != "report_sha256"
        })
    elif change == "source_role":
        rows = result["binding"]["source_role_bindings"]
        rows[0]["source_occurrence_cid"] = rows[-1]["source_occurrence_cid"]
    elif change == "subject":
        rows = result["binding"]["required_subjects"]
        rows[0]["subject_ref"] = deepcopy(rows[-1]["subject_ref"])
    elif change == "population":
        result["population"]["subjects"].pop()
        result["population"] = reseal(result["population"])
    elif change == "required_subject":
        result["binding"]["required_subjects"].pop()
    elif change == "authority":
        result["binding"]["authority"]["proof_authority"] = True
    elif change == "mask":
        result["binding"]["training_mask"] = 1
    else:
        record = result["candidate"]["definition_record"]
        record["native_ast"]["formula"]["operator"]["value"] = "→"
        result["candidate"]["definition_record"] = reseal(record)
        result["candidate"] = reseal(result["candidate"])
    result["binding"] = reseal(result["binding"])
    with pytest.raises(ValueError):
        validate(source_case, result)


def test_wrong_output_pin_is_rejected_before_operation_owners(source_case, base_result):
    with patch.object(binding, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            validate(source_case, base_result, expected_binding_sha256="0" * 64)


def test_public_module_import_is_stdlib_only_and_loads_no_operation_owner():
    script = r"""
import importlib.util, json, sys
blocked = ('ipfs_datasets_py', 'torch', 'transformers', 'tensorflow', 'numpy', 'multiformats', 'cbor2', 'cryptography', 'requests', 'pyarrow')
attempts = []
class DenyProduction:
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in blocked):
            attempts.append(fullname)
            raise AssertionError('Production owner reached during public import')
        return None
sys.meta_path.insert(0, DenyProduction())
spec = importlib.util.spec_from_file_location('_sampling_definition_binding_cold_import', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert not attempts
assert set(module.__all__) == {'prepare_definition_binding_v2', 'definition_binding_sha256', 'validate_definition_binding_v2'}
assert not any(any(name == prefix or name.startswith(prefix + '.') for prefix in blocked) for name in sys.modules)
print(json.dumps({'production_import_attempts': attempts, 'public_APIs': len(module.__all__)}))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, binding.__file__],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "production_import_attempts": [], "public_APIs": 3
    }
