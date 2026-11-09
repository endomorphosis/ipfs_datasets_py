"""Exact supplied-text coordinates preserve legacy identities without authority."""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.autoformal import uscode_ingest as ingest


def document(text="The agency shall act.", **metadata):
    return {"legal_id": "usc:10:1", "title": "10", "section": "1", **metadata, "text": text}


def validate(report, documents, **kwargs):
    return ingest.validate_uscode_source_coordinates(
        report,
        documents,
        expected_report_sha256=ingest.uscode_source_coordinates_sha256(report),
        **kwargs,
    )


def reseal(report):
    """An attacker can rewrite a public self-seal; replay must still refuse."""
    report.pop("source_coordinates_sha256")
    payload = json.dumps(
        report, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    report["source_coordinates_sha256"] = hashlib.sha256(payload).hexdigest()
    return report


def test_unicode_characters_and_utf8_bytes_recover_exact_original_sentences():
    text = " \tΩ agency shall act.\r\nCafé may file!  "
    documents = [document(text)]
    report = ingest.inventory_uscode_source_coordinates(documents)
    assert validate(report, documents) is None
    assert report["documents"][0]["source_text"] == text
    assert report["documents"][0]["source_utf8_bytes"] == len(text.encode("utf-8"))
    for span, expected in zip(report["spans"], ["Ω agency shall act.", "Café may file!"]):
        assert span["source_text"] == span["text"] == expected
        assert text[span["source_char_start"]:span["source_char_end"]] == expected
        assert text.encode("utf-8")[span["source_utf8_byte_start"]:span["source_utf8_byte_end"]].decode("utf-8") == expected
        assert span["source_text_sha256"] == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert len(report["spans"]) == 2
    assert report["spans"][0]["source_char_end"] != report["spans"][0]["source_utf8_byte_end"]
    assert report["spans"][1]["source_char_start"] != report["spans"][1]["source_utf8_byte_start"]


def test_crlf_nbsp_and_padding_preserve_original_internal_whitespace():
    text = " \r\nAlpha\u00a0\t shall\r\n act.\tBeta may act!  "
    report = ingest.inventory_uscode_source_coordinates([document(text)])
    assert report["documents"][0]["normalized_text"] == "Alpha shall act. Beta may act!"
    first, second = report["spans"]
    assert first["source_text"] == "Alpha\u00a0\t shall\r\n act."
    assert first["text"] == "Alpha shall act."
    assert first["source_char_start"] == 3
    assert first["normalized_char_start"] == 0
    assert first["normalized_char_end"] == len("Alpha shall act.")
    assert second["source_text"] == "Beta may act!"
    assert second["source_char_end"] == len(text) - 2
    assert second["normalized_char_start"] == len("Alpha shall act. ")
    assert first["source_text_sha256"] != first["span_text_sha256"]
    assert validate(report, [document(text)]) is None


def test_duplicate_sentences_ids_and_empty_inputs_keep_both_ordinal_spaces():
    documents = [document(""), document("May act. May act."), document("\r\n\u00a0 "), document("May act.")]
    report = ingest.inventory_uscode_source_coordinates(documents)
    assert [row["input_document_ordinal"] for row in report["documents"]] == [0, 1, 2, 3]
    assert [row["document_ordinal"] for row in report["documents"]] == [None, 0, None, 1]
    assert [row["input_document_ordinal"] for row in report["spans"]] == [1, 1, 3]
    assert [row["document_ordinal"] for row in report["spans"]] == [0, 0, 1]
    assert [row["source_char_start"] for row in report["spans"]] == [0, 9, 0]
    assert [row["source_char_end"] for row in report["spans"]] == [8, 17, 8]
    assert len({row["source_span_id"] for row in report["spans"]}) == 3
    assert validate(report, documents) is None


def test_empty_population_is_valid_and_empty_documents_are_not_lost():
    empty = ingest.inventory_uscode_source_coordinates([])
    assert empty["documents"] == empty["spans"] == []
    assert validate(empty, []) is None
    report = ingest.inventory_uscode_source_coordinates((document(""), document("\t\r\n")))
    assert len(report["documents"]) == 2
    assert report["spans"] == []
    assert all(row["document_ordinal"] is None for row in report["documents"])


def test_mapping_is_bounded_evidence_without_legal_or_original_file_authority():
    documents = [document("May act.", annotations={"unreviewed": [True, None, 1.5]})]
    original = deepcopy(documents)
    report = ingest.inventory_uscode_source_coordinates(documents)
    assert documents == original
    assert report["documents"][0]["source_metadata"]["annotations"] == original[0]["annotations"]
    assert report["authority"] == {
        "source_authority_authenticated": False,
        "legal_meaning_verified": False,
        "training_authorized": False,
        "training_gold_qualified": False,
        "formalized": False,
        "admitted": False,
    }
    assert report["coordinate_origin"]["field"] == "text"
    assert report["coordinate_origin"]["parquet_file_byte_mapping_verified"] is False
    assert report["coordinate_origin"]["raw_html_byte_mapping_verified"] is False
    assert validate(report, documents) is None


def test_default_legacy_inventory_has_exact_frozen_output_and_unchanged_ids():
    documents = [document("The agency shall act. The officer may file.")]
    expected_document = {
        "canonical_citation": "10 U.S.C. 1", "document_id": "usc:10:1",
        "entry_cid": "", "legal_id": "usc:10:1", "record_sha256": "",
        "release_point": "", "retrieval_method": "sparse_bm25", "score": None,
        "section": "1", "source": "uscode", "text": documents[0]["text"],
        "text_sha256": "410356ef8d2e0771f0452005c5abe1861b8f1f889b478d845ed8ef9da8af914a",
        "title": "10",
    }
    common_span = {
        "canonical_citation": "10 U.S.C. 1", "document_ordinal": 0,
        "entry_cid": "", "legal_id": "usc:10:1", "reason": "", "release_point": "",
        "retrieval_method": "sparse_bm25", "retrieval_score": None, "section": "1",
        "status": "uncompiled", "title": "10", "unit_id": "usc:10:1",
    }
    expected_spans = [
        {**common_span, "id": "usc:10:1.span-1", "text": "The agency shall act.",
         "source_span_id": "uscode-span-b444f672882e93c4488db379dd9f912f48f665e6c0ed7ccd3b1801cfdb11168f",
         "span_text_sha256": "c39e2f2928461a26393a03da873de4db7aa21640af98d80d1d2654fe21c69d04"},
        {**common_span, "id": "usc:10:1.span-2", "text": "The officer may file.",
         "source_span_id": "uscode-span-0611c5ab29593f6da80a521ac7e2e5ce564216c672ac1f7f80de563394dd233d",
         "span_text_sha256": "28ce294c8dd9e1248dc6fdb282775e7215e39c22a7ad5409b5751eeb94da70ea"},
    ]
    expected = {
        "admitted": False, "compiled": False, "documents": [expected_document],
        "edges": [], "formalized": False, "query": "", "release_id": "",
        "retrieval": {"authority": False, "document_count": 1, "method": "sparse_bm25", "query": "", "span_count": 2},
        "span_identity_schema": "uscode-sparse-autoformal-span-v1", "spans": expected_spans,
    }
    assert ingest.inventory_uscode_documents(documents) == expected
    coordinates = ingest.inventory_uscode_source_coordinates(documents)
    assert [row["source_span_id"] for row in coordinates["spans"]] == [row["source_span_id"] for row in expected_spans]
    assert ingest.inventory_uscode_documents(documents) == expected


def test_valid_replacement_report_cannot_satisfy_stale_independent_pin():
    documents = [document()]
    original = ingest.inventory_uscode_source_coordinates(documents)
    replacement_documents = [document("The agency may act.")]
    replacement = ingest.inventory_uscode_source_coordinates(replacement_documents)
    with pytest.raises(ingest.USCodeSourceCoordinatesError):
        ingest.validate_uscode_source_coordinates(
            replacement, replacement_documents,
            expected_report_sha256=ingest.uscode_source_coordinates_sha256(original),
        )


@pytest.mark.parametrize("field", ["source_char_end", "source_utf8_byte_end"])
def test_rehashed_mutated_selector_is_refused_by_replay(field):
    documents = [document("Ω agency shall act.")]
    report = ingest.inventory_uscode_source_coordinates(documents)
    report["spans"][0][field] -= 1
    reseal(report)
    with pytest.raises(ingest.USCodeSourceCoordinatesError):
        validate(report, documents)


def test_original_text_and_metadata_are_independently_bound():
    documents = [document()]
    report = ingest.inventory_uscode_source_coordinates(documents)
    for modified in ([document("The agency may act.")], [document(section="2")]):
        with pytest.raises(ingest.USCodeSourceCoordinatesError):
            validate(report, modified)


@pytest.mark.parametrize("field", ["query", "release_id"])
def test_query_and_release_are_bound_to_exact_invocation(field):
    documents = [document()]
    parameters = {"query": "source only", "release_id": "edition-2024"}
    report = ingest.inventory_uscode_source_coordinates(documents, **parameters)
    assert validate(report, documents, **parameters) is None
    parameters[field] += "-changed"
    with pytest.raises(ingest.USCodeSourceCoordinatesError):
        validate(report, documents, **parameters)


@pytest.mark.parametrize(
    "documents,kwargs",
    [
        ("text", {}),
        ({"text": "May act."}, {}),
        ([document(123)], {}),
        ([document()], {"query": True}),
        ([document()], {"release_id": None}),
        ([document(score=float("nan"))], {}),
        ([document(extra=[None] * 100)], {"limits": {"max_metadata_bytes": 64}}),
    ],
    ids=["string-population", "mapping-population", "nonstring-text", "boolean-query", "null-release", "nonfinite-metadata", "broad-metadata-lowered-limit"],
)
def test_strict_input_types_refuse_lossy_coercion(documents, kwargs):
    with pytest.raises(ingest.USCodeSourceCoordinatesError):
        ingest.inventory_uscode_source_coordinates(documents, **kwargs)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_spans": True},
        {"max_spans": 1.0},
        {"max_spans": 0},
        {"unrecognized_limit": 1},
        {"max_spans": ingest.SOURCE_COORDINATE_LIMITS["max_spans"] + 1},
    ],
    ids=["boolean", "float", "zero", "unknown", "raised-ceiling"],
)
def test_limits_are_positive_exact_integers_and_lower_only(limits):
    with pytest.raises(ingest.USCodeSourceCoordinatesError):
        ingest.inventory_uscode_source_coordinates([document()], limits=limits)


@pytest.mark.parametrize(
    "key,documents,accepted,refused",
    [
        ("max_documents", [document("A."), document("B.")], 2, 1),
        ("max_text_bytes", [document("é")], 2, 1),
        ("max_total_text_bytes", [document("é"), document("é")], 4, 3),
        ("max_spans", [document("May act. May file.")], 2, 1),
        ("max_metadata_bytes", [document("May act.")], 512, 1),
        ("max_report_bytes", [document("May act.")], 8192, 1),
    ],
    ids=["document-count", "per-document-utf8", "total-utf8", "span-count", "metadata-json", "report-json"],
)
def test_each_declared_limit_enforces_its_own_population_bound(key, documents, accepted, refused):
    limits = {key: accepted}
    report = ingest.inventory_uscode_source_coordinates(documents, limits=limits)
    assert report["limits"][key] == accepted
    assert validate(report, documents, limits=limits) is None
    with pytest.raises(ingest.USCodeSourceCoordinatesError):
        ingest.inventory_uscode_source_coordinates(documents, limits={key: refused})


def test_span_limit_refuses_before_legacy_span_materialization(monkeypatch):
    calls = []

    def forbidden_legacy_inventory(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("oversized span population reached legacy inventory")

    monkeypatch.setattr(ingest, "inventory_uscode_documents", forbidden_legacy_inventory)
    with pytest.raises(ingest.USCodeSourceCoordinatesError):
        ingest.inventory_uscode_source_coordinates([document("May act. " * 20)], limits={"max_spans": 1})
    assert calls == []
