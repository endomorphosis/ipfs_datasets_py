"""Authored fictional examples, never actual source/meaning review evidence.

Root must hydrate this next to test_legal_source_sampling.py and run under a
separately qualified native owner. These tests deliberately exercise REAL
sampler/source/CID owners. The draft author does not execute them.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review as intake
from ipfs_datasets_py.logic.autoformal.corpus_contracts import seal_record

# Reuse the existing sampler's fictional HTML/acquisition fixture, rather than
# replacing the extraction/source/CID owners with implementation-shaped doubles.
_fixture_spec = importlib.util.spec_from_file_location(
    "_source_sampling_review_fictional_fixture",
    Path(__file__).with_name("test_legal_source_sampling.py"),
)
_fixture_owner = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_owner)
fixture, inputs = _fixture_owner.fixture, _fixture_owner.inputs


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def test_cold_public_import_is_stdlib_only_and_calls_no_operation_owner():
    script = r"""
import importlib.util, json, sys
blocked = ('ipfs_datasets_py', 'multiformats', 'cbor2', 'cryptography', 'torch', 'numpy', 'transformers', 'pyarrow', 'requests')
attempts = []
class DenyProduction:
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in blocked):
            attempts.append(fullname)
            raise AssertionError('Production import during public module import')
        return None
sys.meta_path.insert(0, DenyProduction())
spec = importlib.util.spec_from_file_location('_sampling_review_cold_import', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert not attempts
assert not any(any(name == prefix or name.startswith(prefix + '.') for prefix in blocked) for name in sys.modules)
assert len(module.__all__) == 6
print(json.dumps({'production_import_attempts': attempts, 'public_APIs': len(module.__all__)}))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, intake.__file__],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "production_import_attempts": [],
        "public_APIs": 6,
    }


def prepared(**options):
    raw = fixture(**options)
    args = inputs(raw)
    report = sampler.prepare_source_sampling(raw, **args)
    replay = dict(
        args,
        expected_sampling_report_sha256=sampler.source_sampling_report_sha256(report),
    )
    bundle = intake.prepare_sampling_review_bundle(raw, **replay)
    return raw, replay, bundle


def declaration(
    bundle, index=0, *, complete=False, principal="synthetic-reviewer-not-a-real-person"
):
    guide = bundle["guides"][index]
    result = deepcopy(guide["response_template"])
    result["bundle_sha256"] = digest(bundle)
    result["reviewer_declaration"] = dict(
        principal_id=principal,
        role="source_reviewer",
        issued_at_utc="2026-10-15T01:00:00Z",
        identity_evidence_refs=[],
        independence_evidence_refs=[],
    )
    result["exposure_declaration"] = dict(
        candidate_interpretations_exposed=False,
        organizer_source_metadata_exposed=True,
        other_exposure=["Fictional test fixture only; no real reviewer claim."],
    )
    for field in ("source_answers", "meaning_proposals"):
        for answer in result[field]:
            answer.update(
                disposition=(
                    "evidence_declared" if field == "source_answers" else "proposal"
                )
                if complete
                else "unresolved",
                finding="Synthetic test declaration, not an admitted source finding or legal target.",
                rationale="Exercise the intake contract on authored fictional evidence only.",
                evidence_refs=[deepcopy(guide["evidence_refs"][0])] if complete else [],
                unresolved_requirements=[]
                if complete
                else ["Actual independent source/meaning review is absent."],
            )
    return result


def record(raw, replay, bundle, value):
    return intake.record_sampling_review_response(
        bundle,
        value,
        raw,
        expected_bundle_sha256=intake.sampling_review_bundle_sha256(bundle),
        **replay,
    )


def summary(raw, replay, bundle, responses):
    return intake.summarize_sampling_review_population(
        bundle,
        responses,
        raw,
        expected_bundle_sha256=digest(bundle),
        expected_response_sha256s=[digest(r) for r in responses],
        **replay,
    )


def test_real_sampler_replay_once_and_complete_context_retained_once():
    raw, replay, initial = prepared()
    with patch.object(
        sampler, "prepare_source_sampling", wraps=sampler.prepare_source_sampling
    ) as call:
        bundle = intake.prepare_sampling_review_bundle(raw, **replay)
        assert call.call_count == 1
        assert (
            intake.validate_sampling_review_bundle(
                bundle, raw, expected_bundle_sha256=digest(bundle), **replay
            )
            == bundle
        )
        assert call.call_count == 2
    assert bundle == initial
    assert set(bundle) == {
        "schema",
        "limits",
        "manifest",
        "sampling_report",
        "question_catalog",
        "guides",
    }
    assert (
        bundle["sampling_report"]["document_view_report"]["document"][
            "document_text"
        ].count("Quoted shall text.")
        == 1
    )
    assert all(
        "document_text" not in g and "sampling_report" not in g
        for g in bundle["guides"]
    )
    assert bundle["manifest"]["sampling_report_stored_once"] is True


def test_controls_and_every_ordered_unit_have_blank_guides_not_reviews():
    _, _, bundle = prepared()
    report = bundle["sampling_report"]
    assert len(bundle["guides"]) == report["counts"]["units"] == 11
    assert [g["subject_ref"]["index"] for g in bundle["guides"]] == list(range(11))
    assert bundle["manifest"]["counts"]["strata"] == report["counts"]["strata"]
    assert (
        sum(
            g["sampling_stratum"] == "retained_context_control"
            for g in bundle["guides"]
        )
        == 7
    )
    for guide in bundle["guides"]:
        assert guide["status"] == "blank_not_a_review"
        assert guide["training_mask"] == guide["evaluation_gold_mask"] == 0
        assert not any(guide["authority"].values())
        template = guide["response_template"]
        assert set(template) == intake.DECLARATION_FIELDS
        assert template["bundle_sha256"] is None
        assert template["question_catalog_ref"] == guide["question_catalog_ref"]
        assert guide["unresolved"] is True
        assert guide["unanswered_question_ids"] == [q for q, _, _ in intake.QUESTIONS]
        assert all(v is None for v in template["exposure_declaration"].values())
        assert all(
            a["disposition"] is a["finding"] is a["rationale"] is None
            for a in template["source_answers"] + template["meaning_proposals"]
        )


def test_catalog_preserves_all_thirteen_prior_questions_plus_two_norm_questions():
    _, _, bundle = prepared()
    questions = bundle["question_catalog"]["questions"]
    assert [q["question_id"] for q in questions] == [
        "source_role",
        "authority_edition",
        "scope_applicability",
        "complete_meaning_unit",
        "dependency_inventory",
        "reference_targets",
        "notes_construction",
        "definition_operator",
        "term_and_sense",
        "body_structure",
        "legal_sort_arity",
        "definition_use",
        "formal_profile_fit",
        "meaning_statement",
        "meaning_arguments_qualifiers",
    ]
    provenance = bundle["question_catalog"]["catalog_provenance"]
    assert provenance["retained_question_count"] == 13
    assert (
        provenance["artifact_sha256"]
        == "72b2f94b893f36d6021822e48849259ed11db7fb64645a745c802ec5f1f5fb4a"
    )
    assert provenance["authentication_or_admission_equivalence_claimed"] is False


def test_blank_template_needs_explicit_bundle_and_completed_declarations():
    raw, replay, bundle = prepared()
    template = deepcopy(bundle["guides"][0]["response_template"])
    with pytest.raises(ValueError):
        record(raw, replay, bundle, template)
    template["bundle_sha256"] = digest(bundle)
    with pytest.raises(ValueError):
        record(raw, replay, bundle, template)


def test_repeated_unicode_occurrences_do_not_merge_or_relabel_coordinates():
    _, _, bundle = prepared(statute='<p class="statutory-body">Café Ω.</p>' * 2)
    guides = [
        g
        for g in bundle["guides"]
        if g["sampling_stratum"] == "candidate_statute_paragraph"
    ]
    assert len(guides) == 2
    assert guides[0]["source_occurrence_ref"] != guides[1]["source_occurrence_ref"]
    assert guides[0]["subject_ref"] != guides[1]["subject_ref"]
    assert (
        bundle["manifest"]["coordinate_profile"]
        == "sampler_markup_v2_only_not_native_v1_or_raw_HTML_offsets"
    )
    report = bundle["sampling_report"]
    records = {r["record_cid"]: r for r in report["records"]}
    second = records[guides[1]["source_occurrence_ref"]["record_cid"]]
    assert second["start_utf8"] > second["start_char"]


@pytest.mark.parametrize(
    "paragraph",
    [
        '<p class="statutory-body">The officer shall act<br>only if approved.</p>',
        '<p class="statutory-body">The officer shall act<div>only if approved.</div>Unless exempt.</p>',
    ],
)
def test_withheld_parent_is_a_separate_subject_and_every_piece_survives(paragraph):
    raw, replay, bundle = prepared(statute=paragraph)
    report = bundle["sampling_report"]
    assert len(report["withheld_paragraph_contexts"]) == 1
    assert len(bundle["guides"]) == report["counts"]["units"] + 1
    parent = bundle["guides"][-1]
    assert parent["subject_ref"]["kind"] == "withheld_context"
    assert parent["sampling_stratum"] == "withheld_parent_context"
    assert any(ref["kind"] == "withheld_context" for ref in parent["evidence_refs"])
    assert (
        intake.validate_sampling_review_bundle(
            bundle, raw, expected_bundle_sha256=digest(bundle), **replay
        )
        == bundle
    )
    state = summary(raw, replay, bundle, [])
    assert state["counts"]["pending"] == len(bundle["guides"])
    assert len(state["subjects"]) == report["counts"]["units"] + 1


def test_real_completed_declaration_roundtrip_keeps_all_authority_false():
    raw, replay, bundle = prepared()
    offered = declaration(bundle, complete=True)
    response = record(raw, replay, bundle, offered)
    assert (
        intake.validate_sampling_review_response(
            response,
            bundle,
            raw,
            expected_response_sha256=digest(response),
            expected_bundle_sha256=digest(bundle),
            **replay,
        )
        == response
    )
    assert response["status"] == "recorded_unverified_declaration"
    assert not any(response["authority"].values())
    assert response["training_mask"] == response["evaluation_gold_mask"] == 0
    assert "signature" not in response and "meaning_target" not in response
    state = summary(raw, replay, bundle, [response])
    assert state["counts"]["declarations_recorded"] == 1
    assert state["counts"]["pending"] == len(bundle["guides"]) - 1
    assert not state["review_completed"] and not state["adjudication_performed"]
    offered["source_answers"][0]["finding"] = "Caller changed after record."
    assert (
        response["source_answers"][0]["finding"]
        != offered["source_answers"][0]["finding"]
    )


def test_structured_unresolved_and_explicit_unknown_exposure_remain_pending():
    raw, replay, bundle = prepared()
    response = record(raw, replay, bundle, declaration(bundle))
    assert summary(raw, replay, bundle, [response])["counts"]["pending"] == len(
        bundle["guides"]
    )
    value = declaration(bundle, complete=True)
    value["exposure_declaration"] = {key: None for key in intake.EXPOSURE_FIELDS}
    response = record(raw, replay, bundle, value)
    assert summary(raw, replay, bundle, [response])["subjects"][0]["state"] == "pending"


def test_unsupported_disagreement_and_no_latest_response_winner():
    raw, replay, bundle = prepared()
    value = declaration(bundle, complete=True)
    value["meaning_proposals"][0]["disposition"] = "unsupported"
    unsupported = record(raw, replay, bundle, value)
    assert (
        summary(raw, replay, bundle, [unsupported])["subjects"][0]["state"]
        == "unsupported"
    )
    another = record(
        raw,
        replay,
        bundle,
        declaration(
            bundle, complete=True, principal="another-unverified-fixture-principal"
        ),
    )
    combined = summary(raw, replay, bundle, [unsupported, another])
    assert combined["subjects"][0]["state"] == "disputed"
    assert len(combined["subjects"][0]["response_refs"]) == 2
    assert combined["latest_response_selected"] is False
    assert (
        summary(raw, replay, bundle, [another, unsupported])["counts"]
        == combined["counts"]
    )


def test_different_prose_does_not_automatically_establish_agreement_or_dispute():
    raw, replay, bundle = prepared()
    a = declaration(bundle, complete=True)
    b = declaration(
        bundle, complete=True, principal="another-unverified-fixture-principal"
    )
    b["meaning_proposals"][0]["finding"] = (
        "Different free-text proposal; no semantic adjudication is attempted."
    )
    state = summary(
        raw,
        replay,
        bundle,
        [record(raw, replay, bundle, a), record(raw, replay, bundle, b)],
    )
    assert state["subjects"][0]["state"] == "declarations_recorded"
    assert not state["review_completed"]


def test_precedence_keeps_unresolved_and_unknown_exposure_reasons():
    raw, replay, bundle = prepared()
    value = declaration(bundle, complete=True)
    value["meaning_proposals"][0]["disposition"] = "unsupported"
    value["source_answers"][0].update(
        disposition="unresolved",
        unresolved_requirements=["A source-context dependency is still unavailable."],
    )
    value["exposure_declaration"] = {key: None for key in intake.EXPOSURE_FIELDS}
    response = record(raw, replay, bundle, value)
    item = summary(raw, replay, bundle, [response])["subjects"][0]
    assert item["state"] == "unsupported"
    assert "unresolved_question:source_role" in item["reasons"]
    assert "unknown_exposure:other_exposure" in item["reasons"]
    other = record(
        raw,
        replay,
        bundle,
        declaration(bundle, complete=True, principal="other-synthetic-principal"),
    )
    item = summary(raw, replay, bundle, [response, other])["subjects"][0]
    assert item["state"] == "disputed"
    assert "unresolved_question:source_role" in item["reasons"]
    assert "unknown_exposure:candidate_interpretations_exposed" in item["reasons"]


@pytest.mark.parametrize(
    "change", ["omit", "duplicate", "reorder", "foreign", "source_as_meaning"]
)
def test_missing_duplicate_substituted_or_cross_category_answers_refuse(change):
    raw, replay, bundle = prepared()
    value = declaration(bundle, complete=True)
    if change == "omit":
        value["source_answers"].pop()
    elif change == "duplicate":
        value["source_answers"][1] = deepcopy(value["source_answers"][0])
    elif change == "reorder":
        value["source_answers"].reverse()
    elif change == "foreign":
        value["source_answers"][0]["question_id"] = "unknown"
    else:
        value["meaning_proposals"][0] = deepcopy(value["source_answers"][0])
    with pytest.raises(ValueError):
        record(raw, replay, bundle, value)


@pytest.mark.parametrize(
    "change",
    [
        "finding",
        "rationale",
        "evidence",
        "unresolved",
        "resolved",
        "gold",
        "principal",
        "role",
        "time",
        "exposure",
    ],
)
def test_substantive_answer_identity_exposure_and_no_authority_escape(change):
    raw, replay, bundle = prepared()
    value = declaration(bundle, complete=True)
    answer = value["source_answers"][0]
    if change in ("finding", "rationale"):
        answer[change] = " "
    elif change == "evidence":
        answer["evidence_refs"] = []
    elif change == "unresolved":
        answer["disposition"] = "unresolved"
    elif change == "resolved":
        answer["disposition"] = "resolved"
    elif change == "gold":
        value["training_mask"] = 1
    elif change == "principal":
        value["reviewer_declaration"]["principal_id"] = None
    elif change == "role":
        value["reviewer_declaration"]["role"] = "authenticated"
    elif change == "time":
        value["reviewer_declaration"]["issued_at_utc"] = "2026-02-30T01:00:00Z"
    else:
        del value["exposure_declaration"]["candidate_interpretations_exposed"]
    with pytest.raises(ValueError):
        record(raw, replay, bundle, value)


def test_other_occurrence_selector_cannot_substitute_for_subject_evidence():
    raw, replay, bundle = prepared(statute='<p class="statutory-body">Café Ω.</p>' * 2)
    guides = [
        g
        for g in bundle["guides"]
        if g["sampling_stratum"] == "candidate_statute_paragraph"
    ]
    first_index = bundle["guides"].index(guides[0])
    own = {digest(r) for r in guides[0]["evidence_refs"]}
    foreign = next(r for r in guides[1]["evidence_refs"] if digest(r) not in own)
    value = declaration(bundle, first_index, complete=True)
    value["source_answers"][0]["evidence_refs"] = [foreign]
    with pytest.raises(ValueError, match="subject-scoped"):
        record(raw, replay, bundle, value)


def test_boolean_subject_index_and_rehashed_response_authority_are_rejected():
    raw, replay, bundle = prepared()
    value = declaration(bundle, 1, complete=True)
    value["subject_ref"]["index"] = True
    with pytest.raises(ValueError, match="typed sampler"):
        record(raw, replay, bundle, value)
    response = record(raw, replay, bundle, declaration(bundle, complete=True))
    payload = {
        k: v for k, v in response.items() if k not in ("record_cid", "cid_scope")
    }
    payload["authority"]["meaning_admitted"] = True
    bad = seal_record(payload)
    with pytest.raises(ValueError, match="regeneration"):
        intake.validate_sampling_review_response(
            bad,
            bundle,
            raw,
            expected_response_sha256=digest(bad),
            expected_bundle_sha256=digest(bundle),
            **replay,
        )


@pytest.mark.parametrize(
    "change",
    [
        "drop_control",
        "reorder",
        "withheld",
        "filled_guide",
        "question",
        "view",
        "authority",
    ],
)
def test_rehashed_bundle_tamper_is_not_authorized_by_outer_pins(change):
    raw, replay, bundle = prepared(
        statute='<p class="statutory-body">Act<br>if approved.</p>'
    )
    bad = deepcopy(bundle)
    if change == "drop_control":
        bad["guides"].pop(0)
    elif change == "reorder":
        bad["guides"].reverse()
    elif change == "withheld":
        bad["sampling_report"]["withheld_paragraph_contexts"] = []
    elif change == "filled_guide":
        bad["guides"][0]["response_template"]["source_answers"][0]["finding"] = (
            "Pretend reviewed."
        )
    elif change == "question":
        bad["question_catalog"]["questions"][0]["prompt"] = "Changed question."
    elif change == "view":
        bad["sampling_report"]["document_view_report"]["document"]["document_text"] += (
            " changed"
        )
    else:
        bad["manifest"]["authority"]["meaning_admitted"] = True
    with pytest.raises(ValueError):
        intake.validate_sampling_review_bundle(
            bad, raw, expected_bundle_sha256=digest(bad), **replay
        )


def test_wrong_bundle_source_or_response_pin_refuses():
    raw, replay, bundle = prepared()
    with pytest.raises(ValueError):
        intake.validate_sampling_review_bundle(
            bundle, raw, expected_bundle_sha256="0" * 64, **replay
        )
    with pytest.raises(ValueError):
        intake.prepare_sampling_review_bundle(
            raw, **dict(replay, expected_sampling_report_sha256="0" * 64)
        )
    response = record(raw, replay, bundle, declaration(bundle, complete=True))
    with pytest.raises(ValueError):
        intake.validate_sampling_review_response(
            response,
            bundle,
            raw,
            expected_response_sha256="0" * 64,
            expected_bundle_sha256=digest(bundle),
            **replay,
        )


def test_same_sampler_subject_cannot_rebind_answers_to_another_bundle_or_catalog():
    raw, replay, old = prepared()
    value = declaration(old, complete=True)
    changed = tuple(
        (q, kind, prompt + " Changed producer question.")
        for q, kind, prompt in intake.QUESTIONS
    )
    with patch.object(intake, "QUESTIONS", changed):
        new = intake.prepare_sampling_review_bundle(raw, **replay)
        assert new["guides"][0]["subject_ref"] == old["guides"][0]["subject_ref"]
        assert digest(new) != digest(old)
        with pytest.raises(ValueError, match="another bundle"):
            record(raw, replay, new, value)
        value["bundle_sha256"] = digest(new)
        with pytest.raises(ValueError, match="another question catalog"):
            record(raw, replay, new, value)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_subjects": 1},
        {"max_bundle_bytes": 100},
        {"max_subjects": True},
        {"max_subjects": 4097},
        {"unknown": 1},
    ],
)
def test_lowered_hard_limits_refuse_instead_of_truncating(limits):
    raw, replay, _ = prepared()
    with pytest.raises(ValueError):
        intake.prepare_sampling_review_bundle(raw, limits=limits, **replay)


def test_bad_bounded_inputs_refuse_before_operation_owner_import_or_replay():
    raw, replay, bundle = prepared()
    with patch.object(intake, "_owners") as owners:
        with pytest.raises(ValueError):
            intake.prepare_sampling_review_bundle(
                raw, **dict(replay, expected_raw_bytes=True)
            )
        with pytest.raises(ValueError):
            intake.prepare_sampling_review_bundle(
                raw, **dict(replay, descriptor={"bad": float("nan")})
            )
        bad = deepcopy(bundle)
        bad["limits"]["max_bundle_bytes"] = 100
        with pytest.raises(ValueError):
            intake.validate_sampling_review_bundle(
                bad, raw, expected_bundle_sha256=digest(bad), **replay
            )
        value = declaration(bundle, complete=True)
        value["source_answers"][0]["finding"] = "x" * (1024 * 1024 + 1)
        with pytest.raises(ValueError):
            record(raw, replay, bundle, value)
        assert owners.call_count == 0


def test_population_rejects_duplicates_before_replay_and_keeps_all_subjects():
    raw, replay, bundle = prepared()
    response = record(raw, replay, bundle, declaration(bundle, complete=True))
    with patch.object(intake, "_owners") as owners:
        with pytest.raises(ValueError, match="duplicate"):
            summary(raw, replay, bundle, [response, response])
        assert not owners.called
    state = summary(raw, replay, bundle, [response])
    assert (
        sum(state["counts"].values()) == state["subject_count"] == len(bundle["guides"])
    )
    assert state["response_count"] == 1 and not state["all_subjects_have_declarations"]


def test_explicit_missing_source_cannot_be_vacuous_review_completion():
    raw = fixture()
    args = inputs(raw)
    report = sampler.prepare_source_sampling(None, **args)
    replay = dict(args, expected_sampling_report_sha256=digest(report))
    bundle = intake.prepare_sampling_review_bundle(None, **replay)
    assert bundle["guides"] == []
    state = summary(None, replay, bundle, [])
    assert state["subject_count"] == 0 and not state["all_subjects_have_declarations"]
    assert not state["review_completed"] and state["population_issue"] is not None
    assert not any(state["authority"].values())
