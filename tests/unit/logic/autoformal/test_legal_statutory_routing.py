"""Tests of declared routing boundaries; no independent legal-gold assertions."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
from ipfs_datasets_py.logic.autoformal import legal_statutory_routing as routing
from scripts.ops.legal_ir import evaluate_legal_uscode_fidelity as views

URL = "https://www.govinfo.gov/content/pkg/USCODE-2024-title5/html/USCODE-2024-title5-chap1-sec1.htm"
OFFICIAL = Path("/home/barberb/lift_coding/artifacts/legal-decoder-uscode-fidelity-20261003/official-context-02")


def fixture(tmp_path, paragraphs, *, note=None, name="case"):
    html = '<meta charset="utf-8"><h3 class="section-head">§1. Authored routing fixture</h3>'
    for depth, text in paragraphs:
        cls = "statutory-body" + (f"-{depth}em" if depth else "")
        html += f'<p class="{cls}">{text}</p>'
    if note:
        html += f'<h4>Editorial Notes</h4><p class="note-body">{note}</p>'
    raw = html.encode()
    document = context.extract_document(raw, url=URL, edition=2024, legal_id="usc:us:5:1")
    path = tmp_path / (name + ".json")
    path.write_text(json.dumps(document), encoding="utf-8")
    sources = views.make_sources(document, routing.file_ref(path))
    return document, raw, sources


def route_first(tmp_path, text):
    document, raw, sources = fixture(tmp_path, [(0, text)])
    return routing.route_source(sources[0], document, raw)


@pytest.mark.parametrize("text", [
    "The harbor master shall retain the register.",
    "The permit bureau may issue a replacement certificate.",
    "The custodian must not disclose the access code.",
    "If the application is complete, the clerk shall record the submission.",
    "Unless a storm occurs, the depot may open its gates.",
    "Before January 12, 2028, the archive shall transfer the ledger.",
    "The auditor shall, to the maximum extent practicable, preserve the receipts.",
    "The definitions clerk shall deliver the parcel.",
])
def test_self_contained_candidates_survive_routing(tmp_path, text):
    decision = route_first(tmp_path, text)
    assert decision["route"] == "possible_norm" and decision["decoder_eligible"] is True
    assert decision["context_resolved"] is False and decision["source_semantics_verified"] is False
    assert decision["training_qualified"] is False and decision["reference_accuracy"] is None


@pytest.mark.parametrize("text,expected", [
    ('The term "registry" means a collection of filed certificates.', "definition"),
    ("(a) Definitions.—In this section:", "definition"),
    ("(b) Applicability.—This section shall apply to later filings.", "applicability"),
    ("(c) Paragraph (1) shall take effect on January 1, 2027.", "applicability"),
    ("Enrollment shall be deemed to be an application.", "interpretive"),
    ("Nothing in this section shall be construed to authorize entry.", "interpretive"),
    ("(a) In General.—", "structural"),
    ("The filing shall contain the following:", "incomplete_list"),
    ("The board may open the office and shall publish its hours.", "needs_context"),
    ("Shall retain the ledger.", "needs_context"),
    ("And the board shall retain the ledger.", "needs_context"),
    ("The board shall retain...", "needs_context"),
    ("It shall retain the ledger.", "needs_context"),
    ("The board shall comply with section 3573.", "needs_context"),
])
def test_explicit_out_of_profile_constructions_defer(tmp_path, text, expected):
    decision = route_first(tmp_path, text)
    assert decision["route"] == expected and decision["decoder_eligible"] is False
    assert decision["semantic_rejection"] is False


def test_official_note_region_overrides_normative_wording(tmp_path):
    d, raw, sources = fixture(tmp_path, [(0, "The bureau shall file the report.")], note="The prior text stated that the bureau shall file the report.")
    source = next(s for s in sources if s["kind"] == "notes_control")
    result = routing.route_source(source, d, raw)
    assert result["route"] == "notes" and not result["decoder_eligible"]


def test_inherited_list_tail_is_retained_with_ancestor(tmp_path):
    d, raw, sources = fixture(tmp_path, [(0, "(a) The bureau shall retain—"), (1, "(1) invoices;"), (1, "(2) receipts.")])
    result = routing.route_source(sources[1], d, raw)
    assert result["route"] == "incomplete_list" and not result["decoder_eligible"]
    assert result["context_bundle"]["ancestors"][0]["subsection_path"] == "(a)"


def test_full_clause_with_substantive_ancestor_requires_context(tmp_path):
    d, raw, sources = fixture(tmp_path, [(0, "(a) If a permit is valid—"), (1, "(1) The clerk shall record the request.")])
    result = routing.route_source(sources[1], d, raw)
    assert result["route"] == "needs_context" and not result["decoder_eligible"]


def test_local_locator_resolution_is_not_semantic_closure(tmp_path):
    d, raw, sources = fixture(tmp_path, [(0, "(a) In General.—"), (1, "(1) The clerk shall act under paragraph (2)."), (1, "(2) The clerk may issue a certificate.")])
    result = routing.route_source(sources[1], d, raw)
    refs = result["context_bundle"]["resolved_local_locators"]
    assert refs[0]["target"]["subsection_path"] == "(a)(2)"
    assert refs[0]["semantic_dependency_resolved"] is False
    assert result["route"] == "needs_context"


def test_context_bundle_keeps_definitions_and_applicability(tmp_path):
    d, raw, sources = fixture(tmp_path, [(0, '(a) Definitions.—In this section:'), (1, '(1) The term "bureau" means the filing office.'), (0, "(b) The bureau shall retain the ledger."), (0, "(c) Applicability.—This section shall apply after January 1, 2028.")])
    result = routing.route_source(sources[2], d, raw)
    bundle = result["context_bundle"]
    assert len(bundle["same_section_definitions"]) == 1
    assert "filing office" in bundle["same_section_definitions"][0]["text"]
    assert bundle["same_section_applicability"][0]["subsection_path"] == "(c)"
    assert bundle["semantic_closure_verified"] is False
    assert result["route"] == "needs_context" and not result["decoder_eligible"]
    assert bundle["explicitly_used_defined_terms"][0]["term"] == "bureau"
    for kind in ["source_intervals", "ancestors", "same_section_definitions", "same_section_applicability"]:
        for span in bundle[kind]:
            assert d["document_text"][span["char_start"]:span["char_end"]] == span["text"]
            assert context.sha(span["text"]) == span["text_sha256"]


def test_source_duty_cannot_silently_drop_separate_applicability(tmp_path):
    d, raw, sources = fixture(tmp_path, [(0, "(a) The clerk shall retain the ledger."), (0, "(b) Applicability.—This section shall apply after January 1, 2028.")])
    result = routing.route_source(sources[0], d, raw)
    assert result["route"] == "needs_context" and not result["decoder_eligible"]
    assert "applicability" in result["reasons"][0]


def test_used_defined_term_defers_even_without_other_cross_reference(tmp_path):
    d, raw, sources = fixture(tmp_path, [(0, '(a) Definitions.—In this section:'), (1, '(1) The term "registrar" means the regional records officer.'), (0, "(b) The registrar shall file the index.")])
    result = routing.route_source(sources[2], d, raw)
    assert result["route"] == "needs_context" and not result["decoder_eligible"]
    assert result["context_bundle"]["explicitly_used_defined_terms"][0]["term"] == "registrar"


@pytest.mark.parametrize("field,value", [("source_text", "changed"), ("source_sha256", "bad"), ("char_start", 1), ("id", "wrong"), ("kind", "notes_control"), ("legal_id", "usc:us:5:2"), ("training_qualified", True)])
def test_caller_source_tampering_rejected(tmp_path, field, value):
    d, raw, sources = fixture(tmp_path, [(0, "The board shall retain the ledger.")])
    source = deepcopy(sources[0]); source[field] = value
    with pytest.raises(ValueError, match="caller source"):
        routing.route_source(source, d, raw)


def test_caller_document_tampering_rejected(tmp_path):
    d, raw, sources = fixture(tmp_path, [(0, "The board shall retain the ledger.")])
    d["paragraphs"][0]["kind"] = "notes_or_other"
    with pytest.raises(ValueError, match="deterministic"):
        routing.route_source(sources[0], d, raw)


def test_caller_html_tampering_rejected(tmp_path):
    d, raw, sources = fixture(tmp_path, [(0, "The board shall retain the ledger.")])
    with pytest.raises(ValueError, match="deterministic"):
        routing.route_source(sources[0], d, raw + b" ")


def test_document_reference_tampering_rejected(tmp_path):
    d, raw, sources = fixture(tmp_path, [(0, "The board shall retain the ledger.")])
    Path(sources[0]["document"]["path"]).write_text("{}")
    with pytest.raises(ValueError, match="reference changed"):
        routing.route_source(sources[0], d, raw)


@pytest.mark.skipif(not (OFFICIAL / "manifest.json").exists(), reason="pinned local five-section integration corpus unavailable")
def test_all_86_actual_views_preserve_identity_hierarchy_and_context():
    manifest = json.loads((OFFICIAL / "manifest.json").read_text())
    sources = views.validate_manifest(manifest)
    documents = {routing.read_ref(x["document"])["document_id"]: (routing.read_ref(x["document"]), Path(x["raw_html"]["path"]).read_bytes()) for x in manifest["documents"]}
    results = [routing.route_source(s, *documents[s["document_id"]]) for s in sources]
    assert len(results) == len(sources) == 86
    assert [r["source_id"] for r in results] == [s["id"] for s in sources]
    assert {r["source_identity"]["legal_id"] for r in results} == {"usc:us:" + k for k in views.SECTIONS}
    for source, result in zip(sources, results, strict=True):
        assert result["route"] in routing.ROUTES
        assert result["decoder_eligible"] == (result["route"] == "possible_norm")
        if source["kind"] == "notes_control":
            assert result["route"] == "notes"
        if source["legal_id"] == "usc:us:18:3284" and source["kind"] == "paragraph":
            assert result["route"] == "interpretive"
        if source["legal_id"] == "usc:us:40:3318" and source["subsection_path"] == "(c)(1)(A)":
            assert result["route"] == "incomplete_list"
            assert [p["subsection_path"] for p in result["context_bundle"]["ancestors"]] == ["(c)", "(c)(1)"]
        if source["legal_id"] == "usc:us:10:4873" and source["subsection_path"] == "(d)(3)":
            assert result["route"] == "needs_context"
            assert result["context_bundle"]["same_section_definitions"]
            assert result["context_bundle"]["same_section_applicability"]
