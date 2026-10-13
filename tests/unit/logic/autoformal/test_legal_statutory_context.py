import copy
import codecs
import hashlib
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


def _encoded_document(text, *, declaration="", encoding="utf-8", bom=b""):
    raw = bom + (declaration + '<h3 class="section-head">&sect;1. Encoding fixture</h3>'
                 + f'<p class="statutory-body">{text}</p>').encode(encoding)
    return raw, context.extract_document(raw, url=URL, edition=2024, legal_id="usc:us:10:1")


def test_undeclared_utf8_never_uses_a_probabilistic_detector(monkeypatch):
    from bs4 import dammit

    def refuse_detector(*args, **kwargs):
        raise AssertionError("UTF8 source text must not depend on an encoding detector")

    monkeypatch.setattr(dammit, "_chardet_dammit", refuse_detector)
    text = "Élodie shall retain café receipts. 🏛"
    raw, document = _encoded_document(text)
    assert document["document_text"] == text
    assert document["html_sha256"] == hashlib.sha256(raw).hexdigest()
    selector = context.exact_view_occurrences(document, raw, text="🏛")[0]
    assert document["document_text"].encode()[selector["utf8_byte_start"]:selector["utf8_byte_end"]].decode() == "🏛"
    context.validate_document(document, raw)
    assert document["training_qualified"] is document["source_semantics_verified"] is False


@pytest.mark.parametrize("declaration", [
    '<meta charset="windows-1252">',
    '<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">',
    '<?xml version="1.0" encoding="windows-1252"?>',
])
def test_explicit_legacy_encoding_is_strictly_preserved(declaration):
    raw, document = _encoded_document("The café shall retain records – promptly.",
                                      declaration=declaration, encoding="cp1252")
    assert document["document_text"] == "The café shall retain records – promptly."
    assert document["html_sha256"] == hashlib.sha256(raw).hexdigest()
    context.validate_document(document, raw)


def test_valid_utf8_bytes_do_not_override_an_explicit_other_encoding():
    raw, document = _encoded_document("café", declaration='<meta charset="windows-1252">')
    assert document["document_text"] == "cafÃ©"
    assert document["html_sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("declaration", [
    '<meta charset="utf-8"><meta charset="windows-1252">',
    '<meta charset="utf-8" charset="windows-1252">',
    '<?xml version="1.0" encoding="windows-1252"?><meta charset="utf-8">',
])
def test_conflicting_explicit_encodings_abstain(declaration):
    with pytest.raises(ValueError, match="conflicting.*encoding"):
        _encoded_document("Duty.", declaration=declaration)


def test_equivalent_encoding_aliases_are_not_conflicts():
    _, document = _encoded_document("café", declaration='<meta charset="UTF-8"><meta charset="utf8">')
    assert document["document_text"] == "café"


@pytest.mark.parametrize("raw", [
    b'<meta charset="utf-8">' + RAW + b'\xff',
    RAW + b'\xff',
    b'<meta charset="ascii">' + RAW + "café".encode(),
    b'<meta charset="not-a-real-codec">' + RAW,
    b'<meta charset="base64_codec">' + RAW,
    b'<meta charset="">' + RAW,
    b'<meta http-equiv="Content-Type" content="text/html; charset=">' + RAW,
])
def test_invalid_or_unknown_encoding_never_replaces_or_guesses_bytes(raw):
    with pytest.raises(ValueError, match="encoding|UTF8"):
        context.extract_document(raw, url=URL, edition=2024, legal_id="usc:us:10:1")


@pytest.mark.parametrize("encoding,bom", [
    ("utf-8", codecs.BOM_UTF8),
    ("utf-16-le", codecs.BOM_UTF16_LE),
    ("utf-32-be", codecs.BOM_UTF32_BE),
])
def test_compatible_bom_and_declaration_preserve_source_bytes(encoding, bom):
    raw, document = _encoded_document("café", declaration=f'<meta charset="{encoding}">',
                                      encoding=encoding, bom=bom)
    assert document["document_text"] == "café"
    assert document["html_sha256"] == hashlib.sha256(raw).hexdigest()


def test_conflicting_bom_and_declaration_abstain():
    with pytest.raises(ValueError, match="conflicting.*encoding"):
        _encoded_document("Duty.", declaration='<meta charset="windows-1252">', bom=codecs.BOM_UTF8)


def test_comment_and_script_content_do_not_declare_source_encoding():
    declaration = ('<!-- <meta charset="windows-1252"> -->'
                   '<script>const example = \'<meta charset="windows-1252">\';</script>')
    _, document = _encoded_document("café", declaration=declaration)
    assert document["document_text"] == "café"
