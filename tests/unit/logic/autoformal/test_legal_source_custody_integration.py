"""Cross-owner custody observations must not acquire source or legal authority."""
from copy import deepcopy
import hashlib

import pytest

from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody
from ipfs_datasets_py.logic.autoformal import legal_span_provenance as provenance
from tests.unit.logic.autoformal.test_legal_official_source_custody import document_input, inputs


def test_authored_match_and_unique_official_comparison_do_not_attest_producer_source(tmp_path):
    row = dict(source_span_id="authored", legal_id="usc:us:10:1", source_text="Café",
        source_sha256=hashlib.sha256("Café".encode()).hexdigest(), source_revision="observed-short-revision",
        admitted=True, formalized=True, lake_ok=True, unknown_future={"retain": [1, 1, None]})
    observed, rows, trusted = inputs(tmp_path, rows=[row])
    assert observed["rows"][0]["classification"] == "exact_authored_projection_match"
    result = custody.prepare_source_occurrence_inventory(observed, rows, **trusted)
    item, = result["rows"]
    assert item["status"] == "single_exact_comparison_occurrence_unselected"
    assert item["selected_occurrence"] is None and item["governing_source_binding"] is None
    assert item["source_identity"]["declared_revision"] == "observed-short-revision"
    assert observed["rows"][0]["raw_row"] == row
    assert all(value is False for value in item["authority"].values())
    assert custody.validate_source_occurrence_inventory(result, observed, rows,
        expected_report_sha256=custody.source_occurrence_inventory_sha256(result), **trusted) == result


def test_duplicate_physical_rows_and_multiple_editions_preserve_all_comparison_occurrences(tmp_path):
    row = dict(source_span_id="same-presentation", legal_id="usc:us:10:1", source_text="Café")
    documents = [document_input(), document_input(edition=2023)]
    observed, rows, trusted = inputs(tmp_path, rows=[deepcopy(row), deepcopy(row)], documents=documents)
    result = custody.prepare_source_occurrence_inventory(observed, rows, **trusted)
    assert result["row_count"] == 2 and len(result["documents"]) == 2
    assert len({r["record_sha256"] for r in result["rows"]}) == 2
    assert len({r["raw_row_sha256"] for r in result["rows"]}) == 1
    assert all(r["exact_occurrence_count"] == 2 and r["selected_occurrence"] is None for r in result["rows"])
    assert [d["descriptor"]["edition"] for d in result["documents"]] == [2024, 2023]


def test_valid_provenance_from_another_cache_cannot_replace_the_trusted_occurrence_population(tmp_path):
    observed, rows, trusted = inputs(tmp_path)
    other = deepcopy(trusted["provenance_inputs"])
    other["cache_identity"]["revision"] = "f" * 40
    from ipfs_datasets_py.logic.autoformal import legal_span_cache_intake as intake
    other["expected_record_sha256s"] = [intake.record_sha256(row, ordinal=i,
        cache_identity=other["cache_identity"]) for i, row in enumerate(rows)]
    replacement = provenance.reconcile_span_provenance(rows, **other)
    trusted["expected_provenance_report_sha256"] = provenance.provenance_report_sha256(replacement)
    with pytest.raises(ValueError, match="independent|replay|differs"):
        custody.prepare_source_occurrence_inventory(replacement, rows, **trusted)


def test_exact_note_occurrence_retains_note_context_without_legal_role_inference(tmp_path):
    observed, rows, trusted = inputs(tmp_path, texts=("aaa note.",))
    result = custody.prepare_source_occurrence_inventory(observed, rows, **trusted)
    item, = result["rows"]
    occurrence, = item["comparison_documents"][0]["occurrences"]
    assert occurrence["paragraph_coverage"]["paragraph_kind_counts"] == {"notes_or_other": 1}
    assert occurrence["paragraph_coverage"]["paragraphs"][0]["note_headings"] == ["Editorial Notes"]
    assert item["exact_occurrence_count"] == 1 and item["selected_occurrence"] is None
    assert all(value is False for value in item["authority"].values())


def test_one_good_occurrence_cannot_hide_an_unavailable_comparison_document(tmp_path):
    documents = [document_input(), document_input(b"<html>unrecognized extraction</html>", edition=2023)]
    observed, rows, trusted = inputs(tmp_path, documents=documents)
    result = custody.prepare_source_occurrence_inventory(observed, rows, **trusted)
    item, = result["rows"]
    assert len(item["comparison_documents"]) == 2 and item["exact_occurrence_count"] == 1
    assert item["status"] == "comparison_inventory_incomplete_document_unavailable_or_unsupported"
    assert item["selected_occurrence"] is None
    assert result["documents"][1]["status"] == "comparison_extraction_rejected"


def test_hyphenated_identity_is_retained_without_an_invented_supported_extractor_profile(tmp_path):
    observed, rows, trusted = inputs(tmp_path, texts=("Café",), legal_ids=("usc:us:16:410oo-2",),
        documents=[document_input(legal_id="usc:us:16:410oo-2")])
    result = custody.prepare_source_occurrence_inventory(observed, rows, **trusted)
    item, = result["rows"]
    assert item["source_identity"]["legal_id"] == "usc:us:16:410oo-2"
    assert result["documents"][0]["status"] == "unsupported_section_identity_profile"
    assert item["status"] == "comparison_inventory_incomplete_document_unavailable_or_unsupported"
    assert item["selected_occurrence"] is None and item["governing_source_binding"] is None
