"""Fictional cross-bundle declarations exercise transport, never legal review.

These tests reuse the real sampler, custody, CID and review owners through the
existing authored fixture. No actual statutory response or training target is
created, and no model, solver, subprocess or network operation is invoked here.
"""

import importlib.util
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review as review
from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody
from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler
from ipfs_datasets_py.logic.autoformal.corpus_contracts import seal_record

_fixture_spec = importlib.util.spec_from_file_location(
    "_sampling_context_fictional_review_fixture",
    Path(__file__).with_name("test_legal_source_sampling_review.py"),
)
_fixture_owner = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_owner)
prepared = _fixture_owner.prepared
declaration = _fixture_owner.declaration
digest = _fixture_owner.digest


def source(**options):
    raw, replay, bundle = prepared(**options)
    return dict(
        bundle=bundle,
        raw=raw,
        expected_bundle_sha256=digest(bundle),
        replay_inputs=replay,
    )


def candidate_indices(entry):
    return [
        i
        for i, guide in enumerate(entry["bundle"]["guides"])
        if guide["sampling_stratum"] == "candidate_statute_paragraph"
    ]


def nomination(target, target_index, supporting, supporting_index, role="scope nomination"):
    return dict(
        target_bundle_sha256=target["expected_bundle_sha256"],
        target_subject_ref=deepcopy(target["bundle"]["guides"][target_index]["subject_ref"]),
        supporting_bundle_sha256=supporting["expected_bundle_sha256"],
        supporting_subject_ref=deepcopy(supporting["bundle"]["guides"][supporting_index]["subject_ref"]),
        role=role,
    )


def inputs(*, withheld=False):
    target = source(
        statute='<p class="statutory-body">A fictional filer may submit.</p>'
        '<p class="statutory-body">Another fictional filer may register.</p>'
    )
    supporting = source(
        statute='<p class="statutory-body">In this fictional title:</p>'
        '<p class="statutory-body">A filer means a fictional person.</p>'
        + ('<p class="statutory-body">Act<br>only if approved.</p>' if withheld else "")
    )
    links = [nomination(target, candidate_indices(target)[0], supporting, candidate_indices(supporting)[0])]
    return [target, supporting], links


def prepare_context(sources, attachments, **kwargs):
    return review.prepare_sampling_review_context(
        sources, attachments, expected_attachments_sha256=digest(attachments), **kwargs
    )


def context_case(**options):
    sources, attachments = inputs(**options)
    return sources, attachments, prepare_context(sources, attachments)


def offered_declaration(sources, packet, *, complete=True):
    value = declaration(sources[0]["bundle"], candidate_indices(sources[0])[0], complete=complete)
    if complete:
        value["source_answers"][0]["evidence_refs"] = deepcopy(packet["attachments"][0]["evidence_refs"][:1])
    return value


def record(sources, attachments, packet, value, **kwargs):
    return review.record_sampling_review_context_response(
        packet, value, sources, attachments,
        expected_context_sha256=digest(packet),
        expected_declaration_sha256=digest(value),
        expected_attachments_sha256=digest(attachments),
        **kwargs,
    )


def summarize(sources, attachments, packet, responses, **kwargs):
    return review.summarize_sampling_review_context_population(
        packet, responses, sources, attachments,
        expected_context_sha256=digest(packet),
        expected_response_sha256s=[digest(r) for r in responses],
        expected_attachments_sha256=digest(attachments),
        **kwargs,
    )


def validate_context(sources, attachments, packet):
    return review.validate_sampling_review_context(
        packet, sources, attachments,
        expected_context_sha256=digest(packet),
        expected_attachments_sha256=digest(attachments),
    )


def validate_response(sources, attachments, packet, value, response):
    return review.validate_sampling_review_context_response(
        response, packet, value, sources, attachments,
        expected_response_sha256=digest(response),
        expected_context_sha256=digest(packet),
        expected_declaration_sha256=digest(value),
        expected_attachments_sha256=digest(attachments),
    )


def test_complete_sources_and_withheld_population_are_retained_without_review():
    sources, attachments, packet = context_case(withheld=True)
    assert review.sampling_review_context_sha256(packet) == digest(packet)
    assert validate_context(sources, attachments, packet) == packet
    assert packet["schema"] != review.SCHEMA
    assert len(packet["sources"]) == 2
    for original, retained in zip(sources, packet["sources"], strict=True):
        assert digest(original["bundle"]) == digest(retained["bundle"])
        assert retained["bundle_sha256"] == original["expected_bundle_sha256"]
    expected_count = sum(len(s["bundle"]["guides"]) for s in sources)
    assert packet["counts"]["subjects"] == expected_count
    assert packet["counts"]["attachments"] == 1
    assert packet["counts"]["withheld_contexts"] == 1
    summary = summarize(sources, attachments, packet, [])
    assert summary["subject_count"] == expected_count
    assert summary["counts"]["pending"] == expected_count
    assert any(row["subject_ref"]["kind"] == "withheld_context" for row in summary["subjects"])
    assert len({(r["bundle_sha256"], digest(r["subject_ref"])) for r in summary["subjects"]}) == expected_count
    assert summary["response_count"] == 0
    assert summary["review_completed"] is summary["adjudication_performed"] is False
    for result in (packet, summary):
        assert not any(result["authority"].values())
        assert result["training_mask"] == result["evaluation_gold_mask"] == 0


def test_context_response_roundtrip_and_summary_keep_distinct_unverified_domain():
    sources, attachments, packet = context_case()
    value = offered_declaration(sources, packet)
    response = record(sources, attachments, packet, value)
    assert response["schema"] != review.RESPONSE_SCHEMA
    assert response["declaration"] == value
    assert response["declaration_sha256"] == digest(value)
    assert response["context_sha256"] == digest(packet)
    assert validate_response(sources, attachments, packet, value, response) == response
    summary = summarize(sources, attachments, packet, [response])
    assert summary["schema"] != review.POPULATION_SCHEMA
    assert summary["counts"]["declarations_recorded"] == 1
    assert summary["counts"]["pending"] == summary["subject_count"] - 1
    assert summary["response_count"] == summary["attachment_count"] == 1
    assert not summary["review_completed"] and not summary["all_subjects_have_declarations"]
    assert not any(response["authority"].values())
    assert response["training_mask"] == response["evaluation_gold_mask"] == 0
    assert "signature" not in response and "meaning_target" not in response
    value["source_answers"][0]["finding"] = "Changed by caller after recording."
    assert response["declaration"]["source_answers"][0]["finding"] != value["source_answers"][0]["finding"]


def test_attached_evidence_is_scoped_to_exact_target_not_every_subject():
    sources, attachments, packet = context_case()
    value = declaration(sources[0]["bundle"], candidate_indices(sources[0])[1], complete=True)
    value["source_answers"][0]["evidence_refs"] = deepcopy(packet["attachments"][0]["evidence_refs"][:1])
    with pytest.raises(ValueError):
        record(sources, attachments, packet, value)


def test_two_nominated_targets_cannot_exchange_their_attached_evidence_envelopes():
    sources, attachments = inputs()
    second_index = candidate_indices(sources[0])[1]
    attachments.append(nomination(sources[0], second_index, sources[1], candidate_indices(sources[1])[0]))
    packet = prepare_context(sources, attachments)
    value = declaration(sources[0]["bundle"], second_index, complete=True)
    value["source_answers"][0]["evidence_refs"] = deepcopy(packet["attachments"][1]["evidence_refs"][:1])
    response = record(sources, attachments, packet, value)
    assert validate_response(sources, attachments, packet, value, response) == response
    value["source_answers"][0]["evidence_refs"] = deepcopy(packet["attachments"][0]["evidence_refs"][:1])
    with pytest.raises(ValueError):
        record(sources, attachments, packet, value)


def test_unlinked_supporting_guide_evidence_remains_unavailable():
    sources, attachments, packet = context_case()
    foreign = [nomination(sources[0], candidate_indices(sources[0])[0], sources[1], candidate_indices(sources[1])[1])]
    foreign_packet = prepare_context(sources, foreign)
    value = offered_declaration(sources, packet)
    value["source_answers"][0]["evidence_refs"] = deepcopy(foreign_packet["attachments"][0]["evidence_refs"][:1])
    with pytest.raises(ValueError):
        record(sources, attachments, packet, value)


def test_same_paragraph_in_another_edition_cannot_substitute_source_identity():
    sources, attachments = inputs()
    original = sources[1]
    args = deepcopy(original["replay_inputs"])
    args.pop("expected_sampling_report_sha256")
    descriptor = args["descriptor"]
    descriptor["edition"] = 2023
    for key in ("package_id", "granule_id", "url"):
        descriptor[key] = descriptor[key].replace("2024", "2023")
    for key in ("requested_url", "final_url"):
        descriptor["http_provenance"][key] = descriptor["http_provenance"][key].replace("2024", "2023")
    args["expected_descriptor_sha256"] = custody.acquisition_descriptor_sha256(descriptor)
    report = sampler.prepare_source_sampling(original["raw"], **args)
    replay = dict(args, expected_sampling_report_sha256=sampler.source_sampling_report_sha256(report))
    bundle = review.prepare_sampling_review_bundle(original["raw"], **replay)
    other = dict(bundle=bundle, raw=original["raw"], expected_bundle_sha256=digest(bundle), replay_inputs=replay)
    old_guide = original["bundle"]["guides"][candidate_indices(original)[0]]
    new_guide = other["bundle"]["guides"][candidate_indices(other)[0]]
    assert old_guide["source_occurrence_ref"] != new_guide["source_occurrence_ref"]
    sources[1] = other
    attachments[0]["supporting_bundle_sha256"] = other["expected_bundle_sha256"]
    # Keeping the old exact subject despite identical raw text must be refused.
    with pytest.raises(ValueError):
        prepare_context(sources, attachments)


def test_repeated_support_text_is_not_a_unique_occurrence_key():
    sources, _ = inputs()
    sources[1] = source(statute='<p class="statutory-body">Same fictional term.</p>' * 2)
    first, second = candidate_indices(sources[1])
    attachments = [nomination(sources[0], candidate_indices(sources[0])[0], sources[1], first)]
    packet = prepare_context(sources, attachments)
    foreign = [nomination(sources[0], candidate_indices(sources[0])[0], sources[1], second)]
    foreign_packet = prepare_context(sources, foreign)
    assert attachments[0]["supporting_subject_ref"] != foreign[0]["supporting_subject_ref"]
    value = offered_declaration(sources, packet)
    value["source_answers"][0]["evidence_refs"] = deepcopy(foreign_packet["attachments"][0]["evidence_refs"][:1])
    with pytest.raises(ValueError):
        record(sources, attachments, packet, value)


def test_target_bound_envelopes_cannot_be_forged_by_changing_role_or_occurrence():
    sources, attachments, packet = context_case()
    value = offered_declaration(sources, packet)
    ref = value["source_answers"][0]["evidence_refs"][0]
    ref["role"] = "a differently nominated role"
    with pytest.raises(ValueError):
        record(sources, attachments, packet, value)


def test_original_v1_owner_rejects_attached_evidence_and_new_response():
    sources, attachments, packet = context_case()
    value = offered_declaration(sources, packet)
    target = sources[0]
    with pytest.raises(ValueError):
        review.record_sampling_review_response(
            target["bundle"], value, target["raw"],
            expected_bundle_sha256=target["expected_bundle_sha256"], **target["replay_inputs"],
        )
    response = record(sources, attachments, packet, value)
    with pytest.raises(ValueError):
        review.summarize_sampling_review_population(
            target["bundle"], [response], target["raw"],
            expected_bundle_sha256=target["expected_bundle_sha256"],
            expected_response_sha256s=[digest(response)], **target["replay_inputs"],
        )


def test_context_summary_rejects_legacy_responses_and_exact_duplicate_records():
    sources, attachments, packet = context_case()
    value = offered_declaration(sources, packet)
    response = record(sources, attachments, packet, value)
    with patch.object(review, "_owners") as owners:
        with pytest.raises(ValueError):
            summarize(sources, attachments, packet, [response, response])
        assert not owners.called
    target = sources[0]
    original = declaration(target["bundle"], candidate_indices(target)[0], complete=True)
    legacy = review.record_sampling_review_response(
        target["bundle"], original, target["raw"],
        expected_bundle_sha256=target["expected_bundle_sha256"], **target["replay_inputs"],
    )
    with pytest.raises(ValueError):
        summarize(sources, attachments, packet, [legacy])


def test_disagreement_unknown_exposure_and_unresolved_answers_are_not_closed():
    sources, attachments, packet = context_case()
    first = offered_declaration(sources, packet)
    first["meaning_proposals"][0]["disposition"] = "unsupported"
    first["source_answers"][0].update(disposition="unresolved", unresolved_requirements=["Context remains unavailable."])
    first["exposure_declaration"]["candidate_interpretations_exposed"] = None
    second = offered_declaration(sources, packet)
    second["reviewer_declaration"]["principal_id"] = "another-fictional-principal"
    responses = [record(sources, attachments, packet, v) for v in (first, second)]
    result = summarize(sources, attachments, packet, responses)
    subject = next(s for s in result["subjects"] if s["response_refs"])
    assert subject["state"] == "disputed"
    assert len(subject["response_refs"]) == 2
    assert "unresolved_question:source_role" in subject["reasons"]
    assert "unknown_exposure:candidate_interpretations_exposed" in subject["reasons"]
    assert result["latest_response_selected"] is False
    assert summarize(sources, attachments, packet, list(reversed(responses)))["counts"] == result["counts"]


@pytest.mark.parametrize("change", ["duplicate", "foreign_bundle", "foreign_subject", "boolean_index", "same_bundle", "blank_role", "extra_field"])
def test_malformed_or_unbound_attachments_refuse_before_replay(change):
    sources, attachments = inputs()
    if change == "duplicate":
        attachments.append(deepcopy(attachments[0]))
    elif change == "foreign_bundle":
        attachments[0]["supporting_bundle_sha256"] = "0" * 64
    elif change == "foreign_subject":
        attachments[0]["supporting_subject_ref"]["sha256"] = "0" * 64
    elif change == "boolean_index":
        attachments[0]["target_subject_ref"]["index"] = True
    elif change == "same_bundle":
        attachments[0]["supporting_bundle_sha256"] = attachments[0]["target_bundle_sha256"]
        attachments[0]["supporting_subject_ref"] = deepcopy(attachments[0]["target_subject_ref"])
    elif change == "blank_role":
        attachments[0]["role"] = " "
    else:
        attachments[0]["meaning_admitted"] = True
    with patch.object(review, "_owners") as owners:
        with pytest.raises(ValueError):
            prepare_context(sources, attachments)
        assert not owners.called


@pytest.mark.parametrize("change", ["duplicate", "unattached", "bundle_pin", "raw_pin"])
def test_incomplete_duplicated_or_unbound_sources_refuse_before_replay(change):
    sources, attachments = inputs()
    if change == "duplicate":
        sources.append(deepcopy(sources[0]))
    elif change == "unattached":
        sources.append(source(statute='<p class="statutory-body">Unattached fictional page.</p>'))
    elif change == "bundle_pin":
        sources[1]["expected_bundle_sha256"] = "0" * 64
    else:
        sources[1]["replay_inputs"]["expected_raw_sha256"] = "0" * 64
    with patch.object(review, "_owners") as owners:
        with pytest.raises(ValueError):
            prepare_context(sources, attachments)
        assert not owners.called


@pytest.mark.parametrize("change", ["drop_guide", "drop_withheld", "false_to_zero"])
def test_resealed_supporting_bundle_cannot_change_complete_population_or_types(change):
    sources, attachments = inputs(withheld=True)
    supporting = sources[1]
    if change == "drop_guide":
        supporting["bundle"]["guides"].pop()
    elif change == "drop_withheld":
        supporting["bundle"]["sampling_report"]["withheld_paragraph_contexts"] = []
    else:
        supporting["bundle"]["manifest"]["authority"]["meaning_admitted"] = 0
    supporting["expected_bundle_sha256"] = digest(supporting["bundle"])
    attachments[0]["supporting_bundle_sha256"] = supporting["expected_bundle_sha256"]
    with pytest.raises(ValueError):
        prepare_context(sources, attachments)


@pytest.mark.parametrize("change", ["authority", "false_to_zero", "mask", "drop_guide", "drop_attachment", "support_ref"])
def test_rehashed_context_outputs_do_not_override_complete_regeneration(change):
    sources, attachments, packet = context_case()
    bad = deepcopy(packet)
    if change == "authority":
        bad["authority"]["meaning_admitted"] = True
    elif change == "false_to_zero":
        bad["authority"]["meaning_admitted"] = 0
    elif change == "mask":
        bad["training_mask"] = False
    elif change == "drop_guide":
        bad["sources"][1]["bundle"]["guides"].pop()
    elif change == "drop_attachment":
        bad["attachments"].clear()
    else:
        bad["attachments"][0]["supporting_guide_ref"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        validate_context(sources, attachments, bad)


@pytest.mark.parametrize("change", ["authority", "false_to_zero", "mask", "context_pin", "declaration"])
def test_resealed_response_cannot_promote_or_rebind_original_declaration(change):
    sources, attachments, packet = context_case()
    value = offered_declaration(sources, packet)
    response = record(sources, attachments, packet, value)
    bad = {k: deepcopy(v) for k, v in response.items() if k not in ("record_cid", "cid_scope")}
    if change == "authority":
        bad["authority"]["meaning_admitted"] = True
    elif change == "false_to_zero":
        bad["authority"]["meaning_admitted"] = 0
    elif change == "mask":
        bad["training_mask"] = False
    elif change == "context_pin":
        bad["context_sha256"] = "0" * 64
    else:
        bad["declaration"]["source_answers"][0]["finding"] = "Changed fictional answer."
        bad["declaration_sha256"] = digest(bad["declaration"])
    with pytest.raises(ValueError):
        validate_response(sources, attachments, packet, value, seal_record(bad))


@pytest.mark.parametrize("limits", [
    {"max_sources": 1}, {"max_subjects": 1}, {"max_input_bytes": 100},
    {"max_packet_bytes": 100}, {"max_bundle_bytes": 100},
    {"max_sources": True}, {"max_sources": 5}, {"unknown": 1},
])
def test_input_limits_refuse_before_replay_without_truncation(limits):
    sources, attachments = inputs()
    with patch.object(review, "_owners") as owners:
        with pytest.raises(ValueError):
            prepare_context(sources, attachments, limits=limits)
        assert not owners.called


def test_attachment_count_and_response_size_bounds_refuse_before_replay():
    sources, attachments = inputs()
    attachments.append(nomination(sources[0], candidate_indices(sources[0])[1], sources[1], candidate_indices(sources[1])[0]))
    with patch.object(review, "_owners") as owners:
        with pytest.raises(ValueError):
            prepare_context(sources, attachments, limits={"max_attachments": 1})
        assert not owners.called
    packet = prepare_context(sources, attachments)
    value = offered_declaration(sources, packet)
    with patch.object(review, "_owners") as owners:
        with pytest.raises(ValueError):
            record(sources, attachments, packet, value, limits={"max_response_bytes": 100})
        assert not owners.called


def test_complete_response_collection_has_a_separate_pre_replay_byte_bound():
    sources, attachments = inputs()
    packet = prepare_context(sources, attachments, limits={"max_response_input_bytes": 100})
    value = offered_declaration(sources, packet)
    response = record(sources, attachments, packet, value)
    assert validate_response(sources, attachments, packet, value, response) == response
    with patch.object(review, "_owners") as owners:
        with pytest.raises(ValueError, match="response input byte bound"):
            summarize(sources, attachments, packet, [response])
        assert not owners.called


def test_population_output_bound_refuses_instead_of_dropping_unreviewed_subjects():
    sources, attachments = inputs(withheld=True)
    packet = prepare_context(sources, attachments, limits={"max_population_bytes": 100})
    assert packet["counts"]["subjects"] == sum(len(s["bundle"]["guides"]) for s in sources)
    with pytest.raises(ValueError):
        summarize(sources, attachments, packet, [])


def test_wrong_independent_attachment_context_and_original_declaration_pins_refuse():
    sources, attachments, packet = context_case()
    value = offered_declaration(sources, packet)
    with pytest.raises(ValueError):
        review.prepare_sampling_review_context(sources, attachments, expected_attachments_sha256="0" * 64)
    with pytest.raises(ValueError):
        review.validate_sampling_review_context(packet, sources, attachments, expected_context_sha256="0" * 64, expected_attachments_sha256=digest(attachments))
    with pytest.raises(ValueError):
        review.record_sampling_review_context_response(packet, value, sources, attachments, expected_context_sha256=digest(packet), expected_declaration_sha256="0" * 64, expected_attachments_sha256=digest(attachments))
