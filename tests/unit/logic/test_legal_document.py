"""Legal-document classification. No Lean and no model."""
from __future__ import annotations

import importlib.util
import hashlib
import sys
from pathlib import Path


def _processor():
    path = Path(__file__).resolve().parents[3] / "ipfs_datasets_py" / "logic" / "legal_document.py"
    spec = importlib.util.spec_from_file_location("legal_document_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LEASE = (
    "The tenant shall pay one hundred dollars. "
    "When payment is after the fifth day, the tenant shall pay an additional ten dollars."
)
AGE = (
    "No person shall be eligible who shall not have attained the age of thirty five years "
    "and been fourteen years a resident."
)
PREAMBLE = "We the People, in Order to form a more perfect Union, do ordain and establish this charter."


def test_amount_and_conjunction_patterns_share_one_classifier() -> None:
    processor = _processor()
    store = processor.DocumentStore()
    lease = store.open_document(LEASE, document_type="contract")
    age = store.open_document(AGE, document_type="statute")
    lease_pattern = store.obligations(lease["document_id"], lease["clauses"][0]["id"])["pattern"]
    age_pattern = store.obligations(age["document_id"], age["clauses"][0]["id"])["pattern"]
    assert lease_pattern["kind"] == "amount"
    assert lease_pattern["base"] == 100 and lease_pattern["cutoff"] == 5
    assert lease_pattern["late_day"] == 6 and lease_pattern["late_amount"] == 110
    assert age_pattern == {"kind": "conjunction", "bounds": [35, 14], "unit": "year"}
    assert "def " not in str(lease_pattern)


def test_a_preamble_abstains() -> None:
    processor = _processor()
    store = processor.DocumentStore()
    opened = store.open_document(PREAMBLE)
    record = store.obligations(opened["document_id"], opened["clauses"][0]["id"])
    assert record["disposition"] == "abstain"
    assert record["pattern"] is None
    assert store.coverage(opened["document_id"])["counts"]["abstain"] == 1


def test_a_semicolon_list_and_a_ceiling_abstain() -> None:
    processor = _processor()
    store = processor.DocumentStore()
    listed = "Congress shall lay taxes; Congress shall support armies for a term of two years."
    opened = store.open_document(listed)
    record = store.obligations(opened["document_id"], opened["clauses"][0]["id"])
    assert record["disposition"] == "abstain"
    assert record["reason"] == "mixed_patterns"
    ceiling = store.open_document("No appropriation shall be for a longer term than two years.")
    later = store.obligations(ceiling["document_id"], ceiling["clauses"][0]["id"])
    assert later["disposition"] == "abstain"
    assert later["reason"] == "unsupported_pattern"


def test_a_repeal_edge_inactivates_the_target() -> None:
    processor = _processor()
    store = processor.DocumentStore()
    text = "A person shall wait at least ten days.\n\nThe later rule shall wait at least twenty days."
    opened = store.open_document(text, edges=[{"kind": "repeal", "source": "1", "target": "0"}])
    first, second = opened["clauses"]
    assert first["disposition"] == "inactive"
    later = store.obligations(opened["document_id"], second["id"])["pattern"]
    assert later["kind"] == "threshold" and later["meet"] == 20 and later["fail"] == 19
    assert store.coverage(opened["document_id"])["counts"]["inactive"] == 1


def test_deontic_result_is_not_an_admit() -> None:
    processor = _processor()
    store = processor.DocumentStore()
    opened = store.open_document(AGE, document_type="statute")
    result = store.deontic_analyze(opened["document_id"], opened["clauses"][0]["id"])
    assert result.get("admitted") is False
    assert result.get("status") in {"structured", "abstain", "unavailable"}


def test_repeated_clauses_select_distinct_original_occurrences() -> None:
    processor = _processor()
    store = processor.DocumentStore()
    clause = "The agency shall retain the file."
    text = f"{clause}\n\n{clause}"
    opened = store.open_document(text, classify=False)
    first, second = opened["clauses"]
    assert (first["start"], first["end"]) == (0, len(clause))
    assert (second["start"], second["end"]) == (len(clause) + 2, len(text))
    assert all(text[row["start"]:row["end"]] == clause for row in (first, second))


def test_normalized_first_occurrence_is_not_skipped_for_a_later_literal_match() -> None:
    processor = _processor()
    store = processor.DocumentStore()
    first_raw = "The\t\tagency shall retain the file."
    clause = "The agency shall retain the file."
    text = first_raw + "\n\n" + clause
    opened = store.open_document(text, classify=False)
    first, second = opened["clauses"]
    assert text[first["start"]:first["end"]] == first_raw
    assert text[second["start"]:second["end"]] == clause
    assert [item.text for item in store.documents[opened["document_id"]].clauses] == [clause, clause]


def test_unicode_and_normalized_whitespace_have_explicit_byte_and_text_maps() -> None:
    processor = _processor()
    store = processor.DocumentStore()
    text = "Préface\r\n\r\nThe  agency shall\r\nretain the café file."
    opened = store.open_document(text, classify=False)
    row = opened["clauses"][-1]
    clause = store.clause(opened["document_id"], row["id"])
    assert clause.text == "The agency shall retain the café file."
    selector = row["source_selector"]
    assert selector["offset_unit"] == "unicode_codepoint"
    assert selector["encoding"] == "utf-8"
    assert selector["normalization"] == "whitespace-alignment-v1"
    raw = text[row["start"]:row["end"]]
    assert text.encode("utf-8")[selector["start_byte"]:selector["end_byte"]].decode("utf-8") == raw
    assert selector["start_byte"] > row["start"]
    assert selector["source_text_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert selector["raw_span_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert selector["clause_text_sha256"] == hashlib.sha256(clause.text.encode("utf-8")).hexdigest()
    rebuilt = []
    for item in selector["mapping"]:
        original = text[item["source_start"]:item["source_end"]]
        normalized = clause.text[item["text_start"]:item["text_end"]]
        assert original == normalized or (original.isspace() and normalized.isspace())
        assert text.encode("utf-8")[item["source_start_byte"]:item["source_end_byte"]].decode("utf-8") == original
        rebuilt.append(normalized)
    assert "".join(rebuilt) == clause.text
    assert selector["mapping"][0]["source_start"] == row["start"]
    assert selector["mapping"][-1]["source_end"] == row["end"]


def test_merged_amount_clause_preserves_text_and_covers_original_newlines() -> None:
    processor = _processor()
    store = processor.DocumentStore()
    text = LEASE.replace("dollars. When", "dollars.\r\n\r\nWhen")
    opened = store.open_document(text)
    assert len(opened["clauses"]) == 1
    row = opened["clauses"][0]
    clause = store.clause(opened["document_id"], row["id"])
    assert clause.text == LEASE
    assert (row["start"], row["end"]) == (0, len(text))
    assert clause.pattern["kind"] == "amount"


def test_custom_segmenter_cannot_invent_or_reorder_source_content() -> None:
    processor = _processor()
    store = processor.DocumentStore()
    for segmenter in (lambda _: ["invented"], lambda _: ["second", "first"]):
        opened = store.open_document("first second", segmenter=segmenter, document_id="bad")
        assert opened["error"] == "unresolvable_clause_selector"
        assert "bad" not in store.documents


def test_public_source_map_is_detached_from_stored_selector() -> None:
    processor = _processor()
    store = processor.DocumentStore()
    opened = store.open_document("The agency shall retain records.")
    row = opened["clauses"][0]
    row["source_selector"]["mapping"][0]["source_start"] = -1
    assert store.clause_view(opened["document_id"], row["id"])["source_selector"]["mapping"][0]["source_start"] == 0
