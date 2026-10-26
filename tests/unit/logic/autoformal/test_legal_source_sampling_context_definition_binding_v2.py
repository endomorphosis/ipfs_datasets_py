"""Fictional contextual declarations preserve exact definition subject roles.

The successful path uses the actual custody, sampler, contextual review,
definition compiler and corpus adapter. Authored responses are deliberately
unverified fixture declarations, never legal review or training gold. No model,
network, solver, Lean build or subprocess is invoked by this module.
"""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody
from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review as review
from ipfs_datasets_py.logic.autoformal import (
    legal_source_sampling_definition_binding_v2 as binding,
    legal_source_sampling_context_definition_binding_v2 as contextual,
)
from ipfs_datasets_py.logic.autoformal.corpus_contracts import seal_record


_SPEC = importlib.util.spec_from_file_location(
    "_context_definition_binding_fictional_fixture",
    Path(__file__).with_name("test_legal_source_sampling_definition_binding_v2.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BASE)
digest, sha, transport = _BASE.digest, _BASE.sha, _BASE.transport
_UNSET = object()


def source_entry(case):
    return dict(
        bundle=case["bundle"], raw=case["raw"],
        expected_bundle_sha256=digest(case["bundle"]), replay_inputs=case["replay"],
    )


def use_source(case, *, edition=None):
    """A second fictional page, produced by the existing source owners."""
    raw = case["raw"].replace(
        b"Later authored body.",
        "A café filer may submit a fictional request.".encode("utf-8"),
    )
    assert raw != case["raw"]
    descriptor = deepcopy(case["replay"]["descriptor"])
    if edition is not None:
        old = str(descriptor["edition"])
        descriptor["edition"] = edition
        for key in ("package_id", "granule_id", "url"):
            descriptor[key] = descriptor[key].replace(old, str(edition))
        for key in ("requested_url", "final_url"):
            descriptor["http_provenance"][key] = descriptor["http_provenance"][key].replace(old, str(edition))
    descriptor.update(raw_sha256=sha(raw), raw_bytes=len(raw))
    replay = dict(
        descriptor=descriptor,
        expected_descriptor_sha256=custody.acquisition_descriptor_sha256(descriptor),
        expected_raw_sha256=sha(raw), expected_raw_bytes=len(raw),
    )
    sampling = sampler.prepare_source_sampling(raw, **replay)
    replay["expected_sampling_report_sha256"] = sampler.source_sampling_report_sha256(sampling)
    bundle = review.prepare_sampling_review_bundle(raw, **replay)
    return dict(bundle=bundle, raw=raw, expected_bundle_sha256=digest(bundle), replay_inputs=replay)


def guide_text(entry, guide):
    records = {row["record_cid"]: row for row in entry["bundle"]["sampling_report"]["records"]}
    return records[guide["source_occurrence_ref"]["record_cid"]]["span_text"]


def use_guide(entry):
    return next(
        guide for guide in entry["bundle"]["guides"]
        if guide["subject_ref"]["kind"] == "unit"
        and "A café filer may submit a fictional request." in guide_text(entry, guide)
    )


def attachment(target, target_guide, supporting, supporting_guide, role):
    return dict(
        target_bundle_sha256=target["expected_bundle_sha256"],
        target_subject_ref=deepcopy(target_guide["subject_ref"]),
        supporting_bundle_sha256=supporting["expected_bundle_sha256"],
        supporting_subject_ref=deepcopy(supporting_guide["subject_ref"]),
        role=role,
    )


def prepared(*, split=False, family="fol"):
    case = _BASE.prepared_with_split_scope() if split else _BASE.prepared(family=family)
    definition, use = source_entry(case), use_source(case)
    required = _BASE.selected_guides(case)
    if split:
        required.append(_BASE.split_parent_guides(case)[0])
    selected = {digest(guide["subject_ref"]) for guide in required}
    required = [g for g in case["bundle"]["guides"] if digest(g["subject_ref"]) in selected]
    target = use_guide(use)
    attachments = [
        attachment(definition, guide, use, target, "fictional contextual support nomination")
        for guide in required
    ]
    attachments.append(attachment(
        use, target, definition, _BASE.selected_guides(case)[-1],
        "fictional definition for a related norm-use target",
    ))
    sources = [definition, use]
    context = review.prepare_sampling_review_context(
        sources, attachments, expected_attachments_sha256=digest(attachments),
    )
    return dict(
        case=case, sources=sources, attachments=attachments, context=context,
        required_guides=required, use_guide=target,
    )


def prepare(case, *, request_raw=_UNSET, context=_UNSET, sources=_UNSET,
            attachments=_UNSET, responses=None, **overrides):
    request_raw = case["case"]["request_raw"] if request_raw is _UNSET else request_raw
    context = case["context"] if context is _UNSET else context
    sources = case["sources"] if sources is _UNSET else sources
    attachments = case["attachments"] if attachments is _UNSET else attachments
    responses = [] if responses is None else responses
    pins = dict(
        expected_request_sha256=sha(request_raw),
        expected_definition_bundle_sha256=digest(case["case"]["bundle"]),
        expected_context_sha256=digest(context),
        expected_response_sha256s=[digest(row) for row in responses],
        expected_attachments_sha256=digest(attachments),
    )
    pins.update(overrides)
    return binding.prepare_contextual_definition_binding_v2(
        request_raw, context, responses, sources, attachments, **pins,
    )


def validate(case, result, *, responses=None, **overrides):
    responses = [] if responses is None else responses
    pins = dict(
        expected_binding_sha256=digest(result),
        expected_request_sha256=sha(case["case"]["request_raw"]),
        expected_definition_bundle_sha256=digest(case["case"]["bundle"]),
        expected_context_sha256=digest(case["context"]),
        expected_response_sha256s=[digest(row) for row in responses],
        expected_attachments_sha256=digest(case["attachments"]),
    )
    pins.update(overrides)
    return binding.validate_contextual_definition_binding_v2(
        result, case["case"]["request_raw"], case["context"], responses,
        case["sources"], case["attachments"], **pins,
    )


def response(case, guide, *, source_index=0, principal="unverified-fictional-principal",
             source_only=False, unsupported=False, cite_attached=True,
             finding="Authored fictional response, not an independent legal review."):
    entry = case["sources"][source_index]
    value = deepcopy(guide["response_template"])
    value["bundle_sha256"] = entry["expected_bundle_sha256"]
    value["reviewer_declaration"] = dict(
        principal_id=principal, role="source_reviewer", issued_at_utc="2026-10-15T01:00:00Z",
        identity_evidence_refs=[], independence_evidence_refs=[],
    )
    value["exposure_declaration"] = dict(
        candidate_interpretations_exposed=True, organizer_source_metadata_exposed=True,
        other_exposure=["Explicit authored fictional context and definition fixture."],
    )
    attached = next(
        a for a in case["context"]["attachments"]
        if a["nomination"]["target_bundle_sha256"] == entry["expected_bundle_sha256"]
        and a["nomination"]["target_subject_ref"] == guide["subject_ref"]
    )
    refs = attached["evidence_refs"][:1] if cite_attached else guide["evidence_refs"][:1]
    for field in ("source_answers", "meaning_proposals"):
        for answer in value[field]:
            unresolved = source_only and field == "meaning_proposals"
            answer.update(
                disposition="unresolved" if unresolved else "evidence_declared" if field == "source_answers" else "proposal",
                finding=finding,
                rationale="Exercise source custody without confirming meaning or identity.",
                evidence_refs=[] if unresolved else deepcopy(refs),
                unresolved_requirements=["Independent meaning review absent."] if unresolved else [],
            )
    if unsupported:
        value["meaning_proposals"][0]["disposition"] = "unsupported"
    return review.record_sampling_review_context_response(
        case["context"], value, case["sources"], case["attachments"],
        expected_context_sha256=digest(case["context"]),
        expected_declaration_sha256=digest(value),
        expected_attachments_sha256=digest(case["attachments"]),
    )


def reseal(value):
    return seal_record({key: item for key, item in value.items() if key not in {"record_cid", "cid_scope"}})


def assert_no_authority(result):
    _BASE.assert_no_authority(result["base_binding"])
    for key in ("contextual_binding", "contextual_population"):
        item = result[key]
        assert item["authority"] and all(flag is False for flag in item["authority"].values())
        for mask in ("training_mask", "evaluation_gold_mask"):
            assert type(item[mask]) is int and item[mask] == 0
    assert result["contextual_population"]["review_completed"] is False
    assert result["contextual_population"]["adjudication_performed"] is False
    assert result["contextual_population"]["latest_response_selected"] is False


@pytest.fixture(scope="module")
def source_case():
    return prepared()


@pytest.fixture(scope="module")
def pending_result(source_case):
    return prepare(source_case)


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_pending_context_preserves_real_native_definition_and_entire_population(family):
    case = prepared(family=family)
    result = prepare(case)
    assert set(result) == {"schema", "base_binding", "contextual_binding", "contextual_population"}
    assert result["schema"] == "legal-source-sampling-context-definition-binding/v2"
    assert result["base_binding"] == _BASE.prepare(case["case"])
    assert result["base_binding"]["definition_report"]["family"] == family
    assert result["base_binding"]["definition_report"]["native_ast"]["formula"]["operator"]["value"] == "↔"
    metadata = result["contextual_binding"]
    assert metadata["status"] == "pending"
    assert metadata["all_required_subjects_have_direct_declarations"] is False
    assert metadata["related_target_responses"] == []
    assert metadata["required_support_nomination_count"] == 1
    nomination = metadata["required_support_nominations"][0]
    assert nomination["nomination"] == case["attachments"][-1]
    assert nomination["applicability_verified"] is False
    assert nomination["direct_definition_review_credit"] is False
    assert nomination["available_attached_evidence_count"] == len(case["context"]["attachments"][-1]["evidence_refs"])
    assert nomination["available_attached_evidence_sha256s"] == [
        digest(ref) for ref in case["context"]["attachments"][-1]["evidence_refs"]
    ]
    assert [row["subject_ref"] for row in metadata["required_subjects"]] == [
        guide["subject_ref"] for guide in case["required_guides"]
    ]
    assert all(row["direct_response_refs"] == [] for row in metadata["required_subjects"])
    population = result["contextual_population"]
    expected = [
        (entry["expected_bundle_sha256"], guide["subject_ref"])
        for entry in case["sources"] for guide in entry["bundle"]["guides"]
    ]
    assert [(row["bundle_sha256"], row["subject_ref"]) for row in population["subjects"]] == expected
    assert population["counts"]["pending"] == population["subject_count"] == len(expected)
    assert binding.contextual_definition_binding_sha256(result) == digest(result)
    assert validate(case, result) == result
    assert_no_authority(result)


def test_scope_only_nomination_is_retained_without_claiming_definition_contributor(source_case):
    case = deepcopy(source_case)
    scope = next(
        guide for guide in case["required_guides"]
        if "In this title:" in guide_text(case["sources"][0], guide)
    )
    case["attachments"][-1] = attachment(
        case["sources"][1], case["use_guide"], case["sources"][0], scope,
        "scope only; definition body is not nominated",
    )
    case["context"] = review.prepare_sampling_review_context(
        case["sources"], case["attachments"], expected_attachments_sha256=digest(case["attachments"]),
    )
    result = prepare(case)
    metadata = result["contextual_binding"]
    assert metadata["status"] == "pending"
    assert metadata["response_count"] == 0
    assert metadata["required_support_nomination_count"] == 1
    row = metadata["required_support_nominations"][0]
    assert set(row["required_definition_roles"]) == {"scope_unit", "scope_block", "scope_literal"}
    assert row["nomination"]["supporting_subject_ref"] == scope["subject_ref"]
    assert row["direct_definition_review_credit"] is False
    for subject in metadata["required_subjects"]:
        expected = [row["nomination_sha256"]] if subject["subject_ref"] == scope["subject_ref"] else []
        assert subject["supporting_nomination_sha256s"] == expected
        assert subject["direct_response_refs"] == [] and subject["state"] == "pending"
    assert_no_authority(result)


def test_direct_definition_responses_complete_only_their_actual_source_roles(source_case):
    offered = [response(source_case, guide) for guide in source_case["required_guides"]]
    result = prepare(source_case, responses=offered)
    metadata = result["contextual_binding"]
    assert metadata["status"] == "declarations_recorded"
    assert metadata["all_required_subjects_have_direct_declarations"] is True
    assert metadata["related_target_responses"] == []
    base_roles = result["base_binding"]["binding"]["required_subjects"]
    for row, original, offered_row in zip(metadata["required_subjects"], base_roles, offered, strict=True):
        assert row["bundle_sha256"] == digest(source_case["case"]["bundle"])
        assert row["subject_ref"] == original["subject_ref"]
        assert row["roles"] == original["roles"]
        assert row["state"] == "declarations_recorded"
        assert [ref["record_cid"] for ref in row["direct_response_refs"]] == [offered_row["record_cid"]]
    assert result["base_binding"]["binding"]["status"] == "pending"
    assert result["base_binding"]["binding"]["response_count"] == 0
    assert result["contextual_population"]["counts"]["pending"] > 0
    assert_no_authority(result)
    assert validate(source_case, result, responses=offered) == result


def test_related_norm_use_response_never_counts_as_definition_review(source_case, pending_result):
    offered = response(source_case, source_case["use_guide"], source_index=1)
    result = prepare(source_case, responses=[offered])
    metadata = result["contextual_binding"]
    assert metadata["status"] == "pending"
    assert metadata["all_required_subjects_have_direct_declarations"] is False
    assert all(row["state"] == "pending" and row["direct_response_refs"] == [] for row in metadata["required_subjects"])
    assert len(metadata["related_target_responses"]) == 1
    related = metadata["related_target_responses"][0]
    assert related["response_ref"]["record_cid"] == offered["record_cid"]
    assert related["bundle_sha256"] == source_case["sources"][1]["expected_bundle_sha256"]
    assert related["subject_ref"] == source_case["use_guide"]["subject_ref"]
    assert related["direct_definition_review_credit"] is False
    support = related["required_support_links"]
    assert len(support) == 1
    original = source_case["context"]["attachments"][-1]
    assert support[0]["nomination"] == original["nomination"]
    assert support[0]["nomination_sha256"] == original["nomination_sha256"]
    assert support[0]["cited_evidence_refs"] == original["evidence_refs"][:1]
    assert support[0]["cited_evidence_count"] == 1
    required = next(row for row in metadata["required_subjects"] if row["subject_ref"] == original["nomination"]["supporting_subject_ref"])
    assert support[0]["required_definition_roles"] == required["roles"]
    assert result["base_binding"] == pending_result["base_binding"]
    population = result["contextual_population"]
    assert population["counts"]["declarations_recorded"] == 1
    assert population["response_count"] == 1
    assert_no_authority(result)


def test_related_nomination_without_an_actual_support_citation_is_rejected(source_case):
    offered = response(source_case, source_case["use_guide"], source_index=1, cite_attached=False)
    with pytest.raises(ValueError):
        prepare(source_case, responses=[offered])


@pytest.mark.parametrize("target_is_unselected_definition", [False, True])
def test_valid_context_response_for_unrelated_subjects_is_not_definition_evidence(
    source_case, target_is_unselected_definition
):
    case = deepcopy(source_case)
    definition, use = case["sources"]
    required = {digest(g["subject_ref"]) for g in case["required_guides"]}
    unrelated = next(g for g in definition["bundle"]["guides"] if digest(g["subject_ref"]) not in required)
    if target_is_unselected_definition:
        case["attachments"].append(attachment(
            definition, unrelated, use, case["use_guide"], "unrelated target nomination",
        ))
        target, source_index = unrelated, 0
    else:
        case["attachments"][-1] = attachment(
            use, case["use_guide"], definition, unrelated, "unrelated supporting subject nomination",
        )
        target, source_index = case["use_guide"], 1
    case["context"] = review.prepare_sampling_review_context(
        case["sources"], case["attachments"], expected_attachments_sha256=digest(case["attachments"]),
    )
    offered = response(case, target, source_index=source_index)
    with pytest.raises(ValueError):
        prepare(case, responses=[offered])


def test_prose_cannot_rewrite_the_explicit_ast(source_case, pending_result):
    offered = response(source_case, source_case["required_guides"][-1], finding="Fixture prose asserts a contradictory existential implication.")
    result = prepare(source_case, responses=[offered])
    assert result["base_binding"] == pending_result["base_binding"]
    assert_no_authority(result)


def test_source_only_declaration_does_not_complete_meaning_review(source_case):
    offered = response(source_case, source_case["required_guides"][0], source_only=True)
    result = prepare(source_case, responses=[offered])
    assert result["contextual_binding"]["status"] == "pending"
    assert_no_authority(result)


def test_conflicts_preserve_every_response_without_a_latest_winner(source_case):
    guide = source_case["required_guides"][-1]
    a = response(source_case, guide, unsupported=True)
    b = response(source_case, guide, principal="second-unverified-fictional-principal")
    results = [prepare(source_case, responses=offered) for offered in ([a, b], [b, a])]
    for result, offered in zip(results, ([a, b], [b, a]), strict=True):
        assert result["contextual_binding"]["status"] == "disputed"
        row = next(r for r in result["contextual_binding"]["required_subjects"] if r["subject_ref"] == guide["subject_ref"])
        assert row["state"] == "disputed"
        assert [ref["record_cid"] for ref in row["direct_response_refs"]] == [r["record_cid"] for r in offered]
        assert_no_authority(result)
    assert results[0]["base_binding"] == results[1]["base_binding"]


def test_unsupported_declaration_stays_unsupported_without_admission(source_case):
    offered = response(source_case, source_case["required_guides"][-1], unsupported=True)
    result = prepare(source_case, responses=[offered])
    assert result["contextual_binding"]["status"] == "unsupported"
    assert_no_authority(result)


def test_split_scope_requires_its_physical_parent_even_with_related_responses():
    case = prepared(split=True)
    parent, unrelated = _BASE.split_parent_guides(case["case"])
    offered = [response(case, guide) for guide in _BASE.selected_guides(case["case"])]
    offered.append(response(case, case["use_guide"], source_index=1))
    partial = prepare(case, responses=offered)
    row = next(r for r in partial["contextual_binding"]["required_subjects"] if r["subject_ref"] == parent["subject_ref"])
    assert set(row["roles"]) == {"scope_block", "scope_literal"}
    assert row["state"] == "pending" and row["direct_response_refs"] == []
    assert partial["contextual_binding"]["status"] == "pending"
    offered.append(response(case, parent))
    complete = prepare(case, responses=offered)
    assert complete["contextual_binding"]["status"] == "declarations_recorded"
    assert complete["contextual_binding"]["all_required_subjects_have_direct_declarations"] is True
    unrelated_row = next(r for r in complete["contextual_population"]["subjects"] if r["bundle_sha256"] == digest(case["case"]["bundle"]) and r["subject_ref"] == unrelated["subject_ref"])
    assert unrelated_row["state"] == "pending"
    assert complete["base_binding"] == partial["base_binding"]
    assert_no_authority(complete)


@pytest.mark.parametrize("key", ["expected_request_sha256", "expected_definition_bundle_sha256", "expected_context_sha256", "expected_attachments_sha256"])
def test_independent_context_input_pin_cannot_be_substituted(source_case, key):
    with pytest.raises(ValueError):
        prepare(source_case, **{key: "0" * 64})


@pytest.mark.parametrize("change", ["missing", "reordered", "duplicate", "wrong", "tuple"])
def test_response_pins_are_exact_ordered_and_unique(source_case, change):
    offered = [response(source_case, guide) for guide in source_case["required_guides"]]
    pins = [digest(row) for row in offered]
    if change == "missing":
        pins.pop()
    elif change == "reordered":
        pins.reverse()
    elif change == "duplicate":
        offered = [offered[0], offered[0]]
        pins = [digest(offered[0])] * 2
    elif change == "wrong":
        pins[0] = "0" * 64
    else:
        pins = tuple(pins)
    with pytest.raises(ValueError):
        prepare(source_case, responses=offered, expected_response_sha256s=pins)


def test_wrong_request_source_edition_cannot_rebind_equal_text(source_case):
    other = _BASE.prepared(edition=2025)
    assert other["raw"] == source_case["case"]["raw"]
    with pytest.raises(ValueError):
        prepare(source_case, request_raw=other["request_raw"])


def test_exact_definition_bundle_is_required_not_similar_supporting_source(source_case):
    with pytest.raises(ValueError):
        prepare(source_case, expected_definition_bundle_sha256=source_case["sources"][1]["expected_bundle_sha256"])


def test_v1_response_cannot_be_downgraded_into_context_domain(source_case):
    offered = _BASE.response(source_case["case"], source_case["required_guides"][0])
    with pytest.raises(ValueError):
        prepare(source_case, responses=[offered])


def test_context_response_cannot_be_submitted_to_unchanged_v1_binding(source_case):
    offered = response(source_case, source_case["required_guides"][0])
    with pytest.raises(ValueError):
        _BASE.prepare(source_case["case"], responses=[offered])


@pytest.mark.parametrize("change", ["raw", "bundle", "replay", "extra_source"])
def test_source_inventory_must_match_the_exact_context(source_case, change):
    sources = deepcopy(source_case["sources"])
    if change == "raw":
        sources[0]["raw"] = sources[0]["raw"][:-1] + b"x"
    elif change == "bundle":
        sources[0]["bundle"]["manifest"]["authority"]["source_semantics_verified"] = True
        sources[0]["expected_bundle_sha256"] = digest(sources[0]["bundle"])
    elif change == "replay":
        sources[0]["replay_inputs"]["expected_raw_sha256"] = "0" * 64
    else:
        sources.append(source_entry(_BASE.prepared(edition=2025)))
    with pytest.raises(ValueError):
        prepare(source_case, sources=sources)


@pytest.mark.parametrize("change", ["attachment_role", "attachment_support", "context_flag", "context_mask", "request_family", "request_operator"])
def test_resealed_inputs_cannot_change_context_or_supported_meaning(source_case, change):
    if change.startswith("request"):
        request = deepcopy(source_case["case"]["request"])
        if change == "request_family":
            request["family"] = "unsupported-family"
        else:
            request["declaration"]["body"] = {"op": "obligation", "operand": request["declaration"]["body"]}
        with pytest.raises(ValueError):
            prepare(source_case, request_raw=transport(request))
        return
    context = deepcopy(source_case["context"])
    if change == "attachment_role":
        context["attachments"][0]["nomination"]["role"] = "Changed unreviewed role"
    elif change == "attachment_support":
        context["attachments"][0]["nomination"]["supporting_subject_ref"]["sha256"] = "0" * 64
    elif change == "context_flag":
        flag = next(iter(context["authority"]))
        context["authority"][flag] = 0
    else:
        context["training_mask"] = False
    with pytest.raises(ValueError):
        prepare(source_case, context=context)


@pytest.mark.parametrize("change", ["authority", "false_zero", "mask_false", "roles", "subject", "population", "AST"])
def test_resealed_result_requires_complete_canonical_regeneration(source_case, pending_result, change):
    result = deepcopy(pending_result)
    metadata = result["contextual_binding"]
    if change in ("authority", "false_zero"):
        flag = next(iter(metadata["authority"]))
        metadata["authority"][flag] = True if change == "authority" else 0
    elif change == "mask_false":
        metadata["training_mask"] = False
    elif change == "roles":
        metadata["required_subjects"][0]["roles"] = []
    elif change == "subject":
        metadata["required_subjects"][0]["subject_ref"] = deepcopy(metadata["required_subjects"][-1]["subject_ref"])
    elif change == "population":
        result["contextual_population"]["subjects"].pop()
        result["contextual_population"] = reseal(result["contextual_population"])
    else:
        result["base_binding"]["definition_report"]["native_ast"]["formula"]["operator"]["value"] = "→"
    result["contextual_binding"] = reseal(metadata)
    with pytest.raises(ValueError):
        validate(source_case, result)


def test_wrong_output_pin_rejects_even_a_correct_result(source_case, pending_result):
    with pytest.raises(ValueError):
        validate(source_case, pending_result, expected_binding_sha256="0" * 64)


@pytest.mark.parametrize("change", ["context", "definition_edition", "declaration", "response_flag"])
def test_response_custody_cannot_be_resealed_for_another_context_or_source(source_case, change):
    offered = response(source_case, source_case["required_guides"][0])
    if change == "context":
        offered["context_sha256"] = "0" * 64
    elif change == "definition_edition":
        other = source_entry(_BASE.prepared(edition=2025))
        offered["declaration"]["bundle_sha256"] = other["expected_bundle_sha256"]
        offered["declaration_sha256"] = digest(offered["declaration"])
    elif change == "declaration":
        offered["declaration_sha256"] = "0" * 64
    else:
        flag = next(iter(offered["authority"]))
        offered["authority"][flag] = 0
    offered = reseal(offered)
    with pytest.raises(ValueError):
        prepare(source_case, responses=[offered])


@pytest.mark.parametrize("bound", ["MAX_CONTEXT_BYTES", "MAX_SOURCE_INPUT_BYTES", "MAX_SUBJECTS", "MAX_ATTACHMENTS", "MAX_RESPONSES", "MAX_RESPONSE_POPULATION_BYTES"])
def test_complete_population_and_byte_bounds_precede_operation_owners(source_case, bound):
    offered = [response(source_case, guide) for guide in source_case["required_guides"]]
    with patch.object(contextual, bound, 1):
        with patch.object(contextual, "_owners", side_effect=AssertionError("operation owners reached")):
            with pytest.raises(ValueError):
                prepare(source_case, responses=offered)


@pytest.mark.parametrize("raw", [b"{", b' {"a":1,"a":2}', b'{"n":NaN}', b"\xff", b" " * (1024 * 1024 + 1)])
def test_malformed_nonfinite_or_oversize_original_request_fails_before_owners(source_case, raw):
    with patch.object(contextual, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            prepare(source_case, request_raw=raw)


def test_source_limit_rejects_before_operation_owners(source_case):
    sources = source_case["sources"] * 3
    with patch.object(contextual, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            prepare(source_case, sources=sources)


def test_output_bound_does_not_truncate_a_complete_qualified_companion(source_case):
    with patch.object(contextual, "MAX_OUTPUT_BYTES", 1):
        with pytest.raises(ValueError):
            prepare(source_case)
