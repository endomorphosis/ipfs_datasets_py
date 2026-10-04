import copy
import pytest

from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context

URL = "https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-sec1.htm"
RAW = b'''<h3 class="section-head">&sect;1. Example</h3>
<p class="statutory-body">(a) Duty.</p>
<p class="statutory-body-1em">(1) The officer shall act under paragraph (3) if authorized.</p>
<p class="statutory-body-2em">(A) Written authority; and</p>
<p class="statutory-body-2em">(B) necessary resources.</p>
<p class="statutory-body-1em">(2) Unless waived, the duty applies.</p>
<p class="statutory-body">(b) Definition.</p>
<p class="source-credit">(Added in 2024.)</p>
<h4 class="note-head">Editorial Notes</h4>
<p class="note-body">Old law said the officer shall file a report.</p>'''


def document():
    return context.extract_document(RAW, url=URL, edition=2024, legal_id="usc:us:10:1")


def test_inline_reference_does_not_change_subsection_hierarchy():
    doc = document()
    assert [p["subsection_path"] for p in doc["paragraphs"][:6]] == ["(a)", "(a)(1)", "(a)(1)(A)", "(a)(1)(B)", "(a)(2)", "(b)"]
    assert doc["blocks"][1]["descendant_paragraphs"] == [2, 3]
    assert "Unless" not in doc["document_text"][doc["blocks"][1]["char_start"]:doc["blocks"][1]["char_end"]]


def test_notes_are_retained_but_not_codified_body():
    doc = document()
    assert doc["paragraphs"][-1]["kind"] == "notes_or_other"
    assert "shall file" in doc["document_text"]
    assert len(doc["blocks"]) == 6


@pytest.mark.parametrize("mutation", ["offset", "parent", "body", "admission"])
def test_mutation_rejected_even_when_text_hash_is_repaired(mutation):
    doc = document()
    if mutation == "offset":
        doc["paragraphs"][1]["char_start"] += 1
    elif mutation == "parent":
        doc["paragraphs"][3]["parent_path"] = "(b)"
    elif mutation == "body":
        doc["document_text"] = doc["document_text"].replace("if authorized", "unconditionally")
        doc["document_text_sha256"] = context.sha(doc["document_text"])
    else:
        doc["training_qualified"] = True
    with pytest.raises(ValueError):
        context.validate_document(doc, RAW)


def test_rejects_edition_mix_and_ambiguous_document():
    with pytest.raises(ValueError):
        context.extract_document(RAW, url=URL, edition=2025, legal_id="usc:us:10:1")
    with pytest.raises(ValueError):
        context.extract_document(RAW + b'<h3 class="section-head">Second section</h3>', url=URL, edition=2024, legal_id="usc:us:10:1")


def test_modality_words_in_notes_do_not_make_them_operative():
    doc = document()
    assert doc["paragraphs"][-1]["kind"] == "notes_or_other"
    assert doc["training_qualified"] is False
    assert doc["source_semantics_verified"] is False


def test_literal_scope_loss_is_diagnostic_never_semantic_gold():
    text = "The Secretary shall, to the maximum extent practicable, avoid requirements."
    source = {"id": "test", "source_text": text, "kind": "paragraph"}
    prediction = {"source_sha256": context.sha(text), "status": "decoded",
                  "canonical_ir": {"rules": [{"actor": "The Secretary", "action": "avoid", "object": "requirements"}]}}
    result = context.inspect_prediction(source, prediction)
    assert [c["text"] for c in result["unretained_cues"]] == ["to the maximum extent practicable"]
    assert result["reference_accuracy"] is None and result["training_qualified"] is False
    prediction["source_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        context.inspect_prediction(source, prediction)


def test_identical_legal_id_does_not_merge_distinct_headings():
    first = document()
    raw2 = RAW.replace(b"Example", b"Different provision")
    second = context.extract_document(raw2, url=URL.replace("sec1.htm", "sec1-1.htm"), edition=2024, legal_id=first["legal_id"])
    assert first["document_id"] != second["document_id"]
