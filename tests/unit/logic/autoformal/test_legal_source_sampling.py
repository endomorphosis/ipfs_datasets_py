"""Whole-source sampling must not turn citation fragments or notes into gold."""

import hashlib
import json
from copy import deepcopy
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import legal_official_document_views as views
from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody
from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler
from ipfs_datasets_py.logic.autoformal.corpus_contracts import (
    CorpusContractError,
    seal_record,
)


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


def fixture(statute=None, notes=None):
    return (
        '<html><head><meta charset="utf-8"><title>Fictional title</title></head><body>'
        "<span>2024 edition metadata</span><br><!-- field-start:head -->"
        '<h3 class="section-head">§1. Fictional section</h3><!-- field-end:head -->'
        "<!-- field-start:statute -->"
        + (
            statute
            if statute is not None
            else '<p class="statutory-body">(a) In this title:</p>'
            '<p class="statutory-body-1em">(1) Café filers may register. See Pub. L. 1.</p>'
            '<p class="statutory-body-1em">(2)(A) Includes a category.</p>'
            '<p class="statutory-body-block-1em">Such term does not include the exception.</p>'
        )
        + "<!-- field-end:statute --><!-- field-start:sourcecredit -->"
        '<p class="source-credit">Pub. L. 1, Stat. 2.</p><!-- field-end:sourcecredit -->'
        + (
            notes
            if notes is not None
            else "<!-- field-start:notes --><!-- field-start:miscellaneous-note -->"
            '<h4 class="note-head">Editorial Notes</h4><!-- field-end:miscellaneous-note -->'
            '<!-- field-start:amendment-note --><p class="statutory-body">Quoted shall text.</p>'
            "<!-- field-end:amendment-note --><!-- field-start:historicalandrevision-note -->"
            "<table><tr><td>Earlier</td><td>Later Café</td></tr></table>"
            "<!-- field-end:historicalandrevision-note --><!-- field-end:notes -->"
        )
        + "</body></html>"
    ).encode()


def inputs(raw):
    url = "https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-chap1-sec1.htm"
    descriptor = {
        "schema": custody.DESCRIPTOR_SCHEMA,
        "legal_id": "usc:us:10:1",
        "edition": 2024,
        "package_id": "USCODE-2024-title10",
        "granule_id": "USCODE-2024-title10-chap1-sec1",
        "url": url,
        "retrieved_at": "2026-10-15T01:00:00Z",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "http_provenance": {
            "requested_url": url,
            "final_url": url,
            "status_code": 200,
            "content_type": "text/html",
            "etag": None,
            "last_modified": None,
        },
    }
    return {
        "descriptor": descriptor,
        "expected_descriptor_sha256": custody.acquisition_descriptor_sha256(descriptor),
        "expected_raw_sha256": descriptor["raw_sha256"],
        "expected_raw_bytes": len(raw),
    }


def prepared(**options):
    raw = fixture(**options)
    args = inputs(raw)
    return raw, args, sampler.prepare_source_sampling(raw, **args)


def units(report):
    return [r for r in report["records"] if r["schema"] == sampler.UNIT_SCHEMA]


def occurrence(report, unit):
    return next(
        r
        for r in report["records"]
        if r["record_cid"] == unit["source_occurrence_ref"]["record_cid"]
    )


def test_preserves_all_blocks_full_clauses_tables_headers_and_note_controls():
    raw, args, report = prepared()
    doc = report["document_view_report"]["document"]
    assert report["status"] == "whole_source_blocks_prepared"
    assert report["counts"]["blocks"] == len(doc["blocks"]) == len(units(report)) == 11
    assert report["counts"]["records"] == 34
    assert [occurrence(report, u)["span_text"] for u in units(report)] == [
        b["text"] for b in doc["blocks"]
    ]
    assert doc["document_text"] == "\n".join(
        occurrence(report, u)["span_text"] for u in units(report)
    )
    assert report["counts"]["interblock_LF_separators"] == 10
    assert report["counts"]["strata"] == {
        "candidate_statute_paragraph": 4,
        "retained_context_control": 7,
    }
    long_unit = next(
        u for u in units(report) if "Café filers" in occurrence(report, u)["span_text"]
    )
    assert occurrence(report, long_unit)["span_text"].endswith("See Pub. L. 1.")
    assert (
        sampler.validate_source_sampling(
            report,
            raw,
            expected_report_sha256=sampler.source_sampling_report_sha256(report),
            **args,
        )
        == report
    )


def test_repeated_unicode_text_preserves_physical_occurrences_and_byte_coordinates():
    raw, _, report = prepared(statute='<p class="statutory-body">Café Ω.</p>' * 2)
    primary = [u for u in units(report) if u["candidate_input"]]
    first, second = [occurrence(report, u) for u in primary]
    assert first["span_text"] == second["span_text"]
    assert first["span_cid"] == second["span_cid"]
    assert first["record_cid"] != second["record_cid"]
    text = report["document_view_report"]["document"]["document_text"]
    assert second["start_utf8"] > second["start_char"]
    for item in [first, second]:
        assert (
            text.encode()[item["start_utf8"] : item["end_utf8"]].decode()
            == item["span_text"]
        )
    assert (
        report["document_view_report"]["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    )


def test_continuation_and_inline_labels_are_retained_without_attaching_legal_hierarchy():
    _, _, report = prepared()
    continuation = next(
        u
        for u in units(report)
        if occurrence(report, u)["span_text"].startswith("Such term")
    )
    assert continuation["candidate_input"] is True
    block = report["document_view_report"]["document"]["blocks"][
        continuation["ordinal"]
    ]
    assert block["classes"] == ["statutory-body-block-1em"]
    assert all(not u["authority"]["legal_hierarchy_verified"] for u in units(report))
    assert all(
        "parent_path" not in u and "subsection_path" not in u for u in units(report)
    )


def test_field_region_wins_over_statutory_looking_class_and_notes_remain_available():
    _, _, report = prepared()
    quoted = next(
        u
        for u in units(report)
        if occurrence(report, u)["span_text"] == "Quoted shall text."
    )
    assert (
        quoted["sampling_stratum"] == "retained_context_control"
        and not quoted["candidate_input"]
    )
    assert any(
        occurrence(report, u)["span_text"] == "Later Café" for u in units(report)
    )


def test_statute_headings_are_context_and_statutory_notes_are_not_discarded():
    _, _, report = prepared(
        statute='<h4 class="subsection-head">(a) Heading</h4>'
        '<p class="statutory-body">(1) A full paragraph.</p>',
        notes="<!-- field-start:notes --><!-- field-start:miscellaneous-note -->"
        '<h4 class="note-head">Statutory Notes and Related Subsidiaries</h4>'
        "<!-- field-end:miscellaneous-note --><!-- field-start:effectivedate-note -->"
        '<p class="note-body">A statutory note requires legal review.</p>'
        "<!-- field-end:effectivedate-note --><!-- field-end:notes -->",
    )
    heading = next(
        u for u in units(report) if occurrence(report, u)["span_text"] == "(a) Heading"
    )
    assert heading["sampling_stratum"] == "statute_structure_context"
    assert report["counts"]["region_kinds"]["statutory_notes"] == 2
    assert any(
        "statutory note" in occurrence(report, u)["span_text"] for u in units(report)
    )


def test_all_context_obligations_and_zero_masks_survive_with_no_definition_or_graph_claim():
    _, _, report = prepared()
    assert all(v is False for v in report["authority"].values())
    contexts = [
        r
        for r in report["records"]
        if r["schema"] == "legal-corpus-context-declaration/v1"
    ]
    assert len(contexts) == report["counts"]["units"]
    assert all(
        c["availability"] == "required_unavailable"
        and len(c["missing_requirements"]) == 6
        for c in contexts
    )
    assert all(c["dependency_verification"] == "declaration_only" for c in contexts)
    for u in units(report):
        assert u["training_mask"] == u["evaluation_gold_mask"] == 0
        assert (
            u["meaning_target"] is None
            and u["formal_outputs"] == u["semantic_assertions"] == []
        )
        assert all(v is False for v in u["authority"].values())


def test_official_source_is_prepared_once_per_operation_not_once_per_sample():
    raw = fixture()
    args = inputs(raw)
    with patch.object(
        views,
        "prepare_official_document_view",
        wraps=views.prepare_official_document_view,
    ) as prepare:
        report = sampler.prepare_source_sampling(raw, **args)
        assert prepare.call_count == 1
        sampler.validate_source_sampling(
            report, raw, expected_report_sha256=digest(report), **args
        )
        assert prepare.call_count == 2


@pytest.mark.parametrize(
    "mutation",
    ["drop_control", "reorder", "mask", "meaning", "context", "block", "authority"],
)
def test_rehashed_resealed_modified_population_cannot_validate(mutation):
    raw, args, report = prepared()
    bad = deepcopy(report)
    if mutation == "drop_control":
        del bad["records"][-3:]
        bad["unit_refs"].pop()
    elif mutation == "reorder":
        bad["unit_refs"].reverse()
    else:
        index = next(
            i
            for i, row in enumerate(bad["records"])
            if row["schema"] == sampler.UNIT_SCHEMA
        )
        row = {
            k: v
            for k, v in bad["records"][index].items()
            if k not in ("record_cid", "cid_scope")
        }
        if mutation == "mask":
            row["training_mask"] = 1
        elif mutation == "meaning":
            row["meaning_target"] = {"invented": True}
        elif mutation == "context":
            row["context_ref"]["sha256"] = "0" * 64
        elif mutation == "block":
            row["markup_block_ref"]["block_index"] += 1
        else:
            row["authority"]["legal_hierarchy_verified"] = True
        changed = seal_record(row)
        original_cid = bad["records"][index]["record_cid"]
        bad["records"][index] = changed
        bad["unit_refs"] = [
            (
                {
                    "schema": changed["schema"],
                    "record_cid": changed["record_cid"],
                    "sha256": digest(changed),
                }
                if ref["record_cid"] == original_cid
                else ref
            )
            for ref in bad["unit_refs"]
        ]
    bad["sampling_report_sha256"] = digest(
        {k: v for k, v in bad.items() if k != "sampling_report_sha256"}
    )
    with pytest.raises(CorpusContractError):
        sampler.validate_source_sampling(
            bad, raw, expected_report_sha256=digest(bad), **args
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_raw_sha256", "0" * 64),
        ("expected_descriptor_sha256", "0" * 64),
        ("expected_raw_bytes", 1),
    ],
)
def test_wrong_external_acquisition_pins_are_rejected(field, value):
    raw = fixture()
    with pytest.raises(ValueError):
        sampler.prepare_source_sampling(raw, **dict(inputs(raw), **{field: value}))


def test_missing_raw_and_unsupported_markup_keep_explicit_owner_dispositions():
    raw = fixture()
    missing = sampler.prepare_source_sampling(None, **inputs(raw))
    assert missing["status"] == "source_view_unavailable" and missing["records"] == []
    assert (
        missing["document_view_report"]["status"] == "raw_comparison_document_missing"
    )
    raw = fixture(statute="<script>Cannot omit this content.</script><p>Text</p>")
    refused = sampler.prepare_source_sampling(raw, **inputs(raw))
    assert refused["status"] == "source_view_unavailable" and refused["records"] == []
    assert (
        refused["document_view_report"]["status"] == "comparison_view_profile_refused"
    )
    assert refused["issues"] and refused["counts"]["units"] == 0


@pytest.mark.parametrize(
    "limit",
    [
        {"max_units": 1},
        {"max_report_bytes": 100},
        {"max_units": True},
        {"max_units": 2049},
        {"unknown": 1},
    ],
)
def test_finite_lowered_population_and_output_bounds_never_truncate(limit):
    raw = fixture()
    with pytest.raises(CorpusContractError):
        sampler.prepare_source_sampling(raw, **inputs(raw), limits=limit)


def test_result_is_detached_from_caller_descriptor_and_expected_report_pin_matters():
    raw, args, report = prepared()
    retained = deepcopy(report)
    args["descriptor"]["http_provenance"]["content_type"] = "changed"
    assert report == retained
    with pytest.raises(CorpusContractError):
        sampler.validate_source_sampling(
            report, raw, expected_report_sha256="0" * 64, **inputs(raw)
        )


@pytest.mark.parametrize(
    "paragraph",
    [
        '<p class="statutory-body">The officer shall act<br>only if approved.</p>',
        '<p class="statutory-body">The officer shall act<div>only if approved.</div></p>',
        '<p class="statutory-body">The officer shall act<div>only if approved.</div>Unless exempt.</p>',
    ],
)
def test_split_or_nested_paragraph_never_proposes_a_truncated_condition_input(
    paragraph,
):
    raw, args, report = prepared(statute=paragraph)
    assert report["counts"]["withheld_fragmented_paragraphs"] == 1
    assert not any(u["candidate_input"] for u in units(report))
    pieces = [u for u in units(report) if u["paragraph_fragment_withheld"]]
    assert len(pieces) >= 2
    (retained,) = report["withheld_paragraph_contexts"]
    parent = next(
        r
        for r in report["records"]
        if r["record_cid"] == retained["source_occurrence_ref"]["record_cid"]
    )
    assert (
        "shall act" in parent["span_text"] and "only if approved" in parent["span_text"]
    )
    assert parent["span_text"] == "\n".join(
        occurrence(report, u)["span_text"] for u in pieces
    )
    assert not retained["candidate_input"]
    assert (
        sampler.validate_source_sampling(
            report, raw, expected_report_sha256=digest(report), **args
        )
        == report
    )


def test_untrusted_report_declared_byte_budget_is_checked_before_source_replay():
    raw, args, report = prepared()
    report["limits"]["max_report_bytes"] = 100
    with patch.object(views, "prepare_official_document_view") as prepare:
        with pytest.raises(CorpusContractError, match="byte bound"):
            sampler.validate_source_sampling(
                report, raw, expected_report_sha256=digest(report), **args
            )
        assert not prepare.called


def test_public_hash_and_validator_refuse_report_above_fixed_hard_budget():
    raw, args, report = prepared()
    report["limitations"].append("x" * (32 * 1024 * 1024))
    with patch.object(views, "prepare_official_document_view") as prepare:
        with pytest.raises(CorpusContractError, match="hard byte bound"):
            sampler.source_sampling_report_sha256(report)
        with pytest.raises(CorpusContractError, match="hard byte bound"):
            sampler.validate_source_sampling(
                report, raw, expected_report_sha256="0" * 64, **args
            )
        assert not prepare.called
