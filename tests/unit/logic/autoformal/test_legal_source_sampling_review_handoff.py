"""Fictional source handoffs preserve custody without supplying review answers.

The fixtures exercise the real sampler, CID records, V2 context packets and
sampling-review owner. No actual statutory interpretation or reviewer evidence
is created, and boundary spies do not replace those production owners.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review as intake
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review_handoff as handoffs
from ipfs_datasets_py.logic.autoformal import legal_statutory_context_v2 as contexts
from ipfs_datasets_py.logic.autoformal.corpus_contracts import seal_record


_SPEC = importlib.util.spec_from_file_location(
    "_source_sampling_handoff_fictional_fixture",
    Path(__file__).with_name("test_legal_source_sampling.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def transport(value):
    # Transport commitments deliberately differ from canonical FULL JSON hashes.
    return json.dumps(
        value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
    ).encode("utf-8") + b"\n"


def reseal(record):
    return seal_record(
        {k: v for k, v in record.items() if k not in {"record_cid", "cid_scope"}}
    )


def legacy_input(raw, replay, bundle, unit):
    report = bundle["sampling_report"]
    records = {row["record_cid"]: row for row in report["records"]}
    occurrence = records[unit["source_occurrence_ref"]["record_cid"]]
    original_context = records[unit["context_ref"]["record_cid"]]
    packet = contexts.build_context_packet_v2(
        report["document_view_report"],
        raw,
        char_start=occurrence["start_char"],
        char_end=occurrence["end_char"],
        expected_report_sha256=report["document_view_report_sha256"],
        **{
            key: replay[key]
            for key in (
                "descriptor",
                "expected_descriptor_sha256",
                "expected_raw_sha256",
                "expected_raw_bytes",
            )
        },
    )
    return {
        "schema": "legal-v2-actual-source-review-handoff-input/v1",
        "status": "unanswered_source_only_not_a_review_submission",
        "navigation_purpose": "scope_review_input",
        "sampling_report_full_canonical_sha256": replay[
            "expected_sampling_report_sha256"
        ],
        "unit": deepcopy(unit),
        "source_occurrence": deepcopy(occurrence),
        "original_context": deepcopy(original_context),
        "v2_context_packet": packet,
        "responses": {
            question_id: {"answer": None, "evidence_refs": [], "rationale": None}
            for question_id, _, _ in intake.QUESTIONS[:13]
        },
        "reviewer": None,
        "exposure_declaration": None,
        "meaning_target": None,
        "typed_AST": None,
        "definition_use_bindings": [],
        "authority": dict(packet["authority"]),
        "training_mask": 0,
        "evaluation_gold_mask": 0,
    }


def prepared(**options):
    raw = _FIXTURE.fixture(**options)
    replay = _FIXTURE.inputs(raw)
    report = sampler.prepare_source_sampling(raw, **replay)
    replay["expected_sampling_report_sha256"] = (
        sampler.source_sampling_report_sha256(report)
    )
    bundle = intake.prepare_sampling_review_bundle(raw, **replay)
    units = [
        row
        for row in report["records"]
        if row["schema"] == sampler.UNIT_SCHEMA and row["candidate_input"]
    ]
    return {
        "raw": raw,
        "replay": replay,
        "bundle": bundle,
        "units": units,
        "legacy": legacy_input(raw, replay, bundle, units[0]),
    }


@pytest.fixture(scope="module")
def source_case():
    return prepared()


def migrate(case, *, legacy=None, handoff_raw=None, **overrides):
    retained = transport(case["legacy"] if legacy is None else legacy)
    if handoff_raw is not None:
        retained = handoff_raw
    args = {
        "expected_handoff_sha256": hashlib.sha256(retained).hexdigest(),
        "expected_bundle_sha256": digest(case["bundle"]),
        **case["replay"],
        **overrides,
    }
    return handoffs.prepare_sampling_review_handoff(
        retained, case["bundle"], case["raw"], **args
    )


def validate(case, draft, *, legacy_raw=None, **overrides):
    retained = transport(case["legacy"]) if legacy_raw is None else legacy_raw
    return handoffs.validate_sampling_review_handoff(
        draft,
        retained,
        case["bundle"],
        case["raw"],
        **{
            "expected_handoff_record_sha256": digest(draft),
            "expected_handoff_sha256": hashlib.sha256(retained).hexdigest(),
            "expected_bundle_sha256": digest(case["bundle"]),
            **case["replay"],
            **overrides,
        },
    )


def test_blank_handoff_replays_exact_source_and_keeps_both_hash_namespaces(source_case):
    legacy_raw = transport(source_case["legacy"])
    draft = migrate(source_case, handoff_raw=legacy_raw)
    assert validate(source_case, draft) == draft
    assert handoffs.sampling_review_handoff_sha256(draft) == digest(draft)
    assert draft["origin"]["raw_sha256"] == hashlib.sha256(legacy_raw).hexdigest()
    assert draft["origin"]["raw_bytes"] == len(legacy_raw)
    assert draft["origin"]["full_canonical_sha256"] == digest(source_case["legacy"])
    assert draft["origin"]["raw_sha256"] != draft["origin"]["full_canonical_sha256"]
    assert draft["origin"]["sampling_report_full_canonical_sha256"] == (
        source_case["replay"]["expected_sampling_report_sha256"]
    )
    assert draft["source_version_ref"] == source_case["units"][0]["source_version_ref"]
    assert draft["source_occurrence_ref"] == source_case["units"][0]["source_occurrence_ref"]
    assert draft["context_ref"] == source_case["units"][0]["context_ref"]
    packet = source_case["legacy"]["v2_context_packet"]
    assert draft["v2_context_packet_ref"] == {
        "schema": packet["schema"],
        "packet_id": packet["packet_id"],
        "sha256": digest(packet),
    }
    assert draft["coordinate_profile"] == (
        "sampler_markup_v2_only_not_native_v1_or_raw_HTML_offsets"
    )


def test_migration_creates_fifteen_blank_questions_without_inventing_review(source_case):
    before = deepcopy(source_case["bundle"])
    draft = migrate(source_case)
    guide = next(
        row
        for row in before["guides"]
        if row["source_occurrence_ref"] == draft["source_occurrence_ref"]
    )
    expected_template = deepcopy(guide["response_template"])
    expected_template["bundle_sha256"] = digest(before)
    assert draft["response_template"] == expected_template
    expected_ids = [question_id for question_id, _, _ in intake.QUESTIONS]
    assert draft["legacy_question_ids"] == expected_ids[:13]
    assert draft["added_question_ids"] == expected_ids[13:]
    assert draft["unanswered_question_ids"] == expected_ids
    assert len(expected_ids) == 15
    assert all(value is None for value in expected_template["reviewer_declaration"].values())
    assert all(value is None for value in expected_template["exposure_declaration"].values())
    assert draft["evidence_refs"] == guide["evidence_refs"]
    assert draft["status"] == "blank_handoff_not_a_review_response"
    assert draft["response_recorded"] is draft["review_completed"] is False
    assert draft["training_mask"] == draft["evaluation_gold_mask"] == 0
    assert draft["authority"] and not any(draft["authority"].values())
    assert source_case["bundle"] == before
    # Handing off one subject neither drops other subjects nor records a review.
    population = intake.summarize_sampling_review_population(
        before,
        [],
        source_case["raw"],
        expected_bundle_sha256=digest(before),
        expected_response_sha256s=[],
        **source_case["replay"],
    )
    assert population["subject_count"] == len(before["guides"])
    assert population["response_count"] == 0
    assert all(row["state"] == "pending" for row in population["subjects"])
    with pytest.raises(ValueError):
        intake.record_sampling_review_response(
            before,
            draft["response_template"],
            source_case["raw"],
            expected_bundle_sha256=digest(before),
            **source_case["replay"],
        )


@pytest.mark.parametrize("malformation", ["duplicate", "nonfinite", "oversized"])
def test_ambiguous_or_oversized_transport_refuses_before_owner_loading(source_case, malformation):
    raw = transport(source_case["legacy"])
    if malformation == "duplicate":
        raw = b'{"schema":"shadowed",' + raw.lstrip()[1:]
    elif malformation == "nonfinite":
        raw = raw.replace(b'"training_mask": 0', b'"training_mask": NaN')
    else:
        raw = b" " * (1024 * 1024 + 1)
    with patch.object(
        handoffs, "_owners", side_effect=AssertionError("owner loaded before raw boundary")
    ) as owners:
        with pytest.raises(ValueError):
            migrate(source_case, handoff_raw=raw)
    owners.assert_not_called()


@pytest.mark.parametrize("pin", ["legacy_transport", "bundle", "sampler", "source"])
def test_independent_input_pins_cannot_be_replaced_by_internal_digests(source_case, pin):
    overrides = {
        "legacy_transport": {"expected_handoff_sha256": digest(source_case["legacy"])},
        "bundle": {"expected_bundle_sha256": "0" * 64},
        "sampler": {"expected_sampling_report_sha256": "0" * 64},
        "source": {"expected_raw_sha256": "0" * 64},
    }[pin]
    with pytest.raises(ValueError):
        migrate(source_case, **overrides)


@pytest.mark.parametrize("damage", ["occurrence", "context", "view", "unicode_geometry"])
def test_changed_transport_pin_cannot_authorize_foreign_source_bindings(source_case, damage):
    bad = deepcopy(source_case["legacy"])
    if damage in {"occurrence", "context"}:
        other = legacy_input(
            source_case["raw"],
            source_case["replay"],
            source_case["bundle"],
            source_case["units"][1],
        )
        field = "source_occurrence" if damage == "occurrence" else "original_context"
        bad[field] = other[field]
    elif damage == "view":
        bad["v2_context_packet"]["source_view_binding"]["normalized_view_id"] = (
            "legal-official-markup-view:sha256:" + "0" * 64
        )
    else:
        bad["source_occurrence"]["start_utf8"] += 1
        bad["source_occurrence"] = reseal(bad["source_occurrence"])
    with pytest.raises(ValueError):
        migrate(source_case, legacy=bad)


@pytest.mark.parametrize(
    "damage", ["unit", "answer", "reviewer", "exposure", "ast", "gold", "packet_authority"]
)
def test_nonblank_or_resealed_escalated_legacy_input_cannot_become_a_blank_handoff(source_case, damage):
    bad = deepcopy(source_case["legacy"])
    if damage == "unit":
        bad["unit"]["formal_outputs"] = [{"invented": True}]
        bad["unit"] = reseal(bad["unit"])
    elif damage == "answer":
        bad["responses"]["scope_applicability"]["answer"] = "Invented scope answer."
    elif damage == "reviewer":
        bad["reviewer"] = {"principal_id": "unverified-test-principal"}
    elif damage == "exposure":
        bad["exposure_declaration"] = {"candidate_interpretations_exposed": False}
    elif damage == "ast":
        bad["typed_AST"] = {"invented": True}
    elif damage == "gold":
        bad["training_mask"] = 1
        bad["authority"]["proof_authority"] = True
    else:
        packet = bad["v2_context_packet"]
        packet["authority"]["proof_authority"] = True
        packet["packet_id"] = "legal-official-markup-context-packet:sha256:" + digest(
            {k: v for k, v in packet.items() if k != "packet_id"}
        )
    with pytest.raises(ValueError):
        migrate(source_case, legacy=bad)


@pytest.mark.parametrize("damage", ["template", "catalog", "subject", "evidence", "mask", "authority"])
def test_resealed_output_requires_exact_regeneration_not_merely_a_valid_record_hash(source_case, damage):
    bad = deepcopy(migrate(source_case))
    if damage == "template":
        bad["response_template"]["meaning_proposals"][0]["finding"] = "Invented meaning."
    elif damage == "catalog":
        bad["question_catalog_ref"]["sha256"] = "0" * 64
        bad["response_template"]["question_catalog_ref"] = deepcopy(bad["question_catalog_ref"])
    elif damage == "subject":
        bad["subject_ref"]["index"] += 1
        bad["response_template"]["subject_ref"] = deepcopy(bad["subject_ref"])
    elif damage == "evidence":
        bad["evidence_refs"] = []
    elif damage == "mask":
        bad["evaluation_gold_mask"] = 1
    else:
        bad["authority"]["proof_authority"] = True
    bad = reseal(bad)
    with pytest.raises(ValueError):
        validate(source_case, bad)


def test_output_pin_is_required_independently_of_the_valid_sealed_record(source_case):
    draft = migrate(source_case)
    with pytest.raises(ValueError):
        validate(source_case, draft, expected_handoff_record_sha256="0" * 64)


def test_identical_unicode_text_keeps_distinct_occurrences_and_handoff_subjects():
    case = prepared(statute='<p class="statutory-body">Café Ω.</p>' * 2)
    first_legacy = case["legacy"]
    second_legacy = legacy_input(case["raw"], case["replay"], case["bundle"], case["units"][1])
    first = migrate(case)
    second = migrate(case, legacy=second_legacy)
    assert first_legacy["source_occurrence"]["span_text"] == second_legacy["source_occurrence"]["span_text"]
    assert first_legacy["source_occurrence"]["span_cid"] == second_legacy["source_occurrence"]["span_cid"]
    assert first["source_occurrence_ref"] != second["source_occurrence_ref"]
    assert first["subject_ref"] != second["subject_ref"]
    assert first["v2_context_packet_ref"] != second["v2_context_packet_ref"]
    bad = deepcopy(first_legacy)
    bad["v2_context_packet"] = second_legacy["v2_context_packet"]
    with pytest.raises(ValueError):
        migrate(case, legacy=bad)
