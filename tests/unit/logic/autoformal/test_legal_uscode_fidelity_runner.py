"""Integration checks for official-source selection and immutable context replay."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[4]
SCRIPT = ROOT / "scripts/ops/legal_ir/evaluate_legal_uscode_fidelity.py"
spec = importlib.util.spec_from_file_location("fidelity_runner_review", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
context = runner.context
URL = "https://www.govinfo.gov/content/pkg/USCODE-2024-title5/html/USCODE-2024-title5-chap1-sec1.htm"


def html(interleave=False, heading="§1. Example"):
    note = '<p class="note-body">An editorial paragraph.</p>'
    return (f'<h3 class="section-head">{heading}</h3>'
            '<p class="statutory-body">(a) In general.—</p>'
            + (note if interleave else "")
            + '<p class="statutory-body-1em">(1) The agency shall act under paragraph (2).</p>'
            '<p class="statutory-body-1em">(2) The agency may file.</p>'
            '<p class="statutory-body">(b) Exceptions.—None.</p>'
            '<p class="source-credit">(Pub. L. 1.)</p>'
            '<h4>Editorial Notes</h4>' + note).encode()


def document(raw=None):
    return context.extract_document(raw or html(), url=URL, edition=2024, legal_id="usc:us:5:1")


def manifest(tmp_path):
    documents, sources = [], []
    for identity, suffix in runner.SECTIONS.items():
        title, section = identity.split(":")
        url = f"https://www.govinfo.gov/content/pkg/USCODE-2024-title{title}/html/USCODE-2024-{suffix}.htm"
        raw = html(heading=f"§{section}. Example title {title}")
        doc = context.extract_document(raw, url=url, edition=2024, legal_id="usc:us:" + identity)
        hp = tmp_path / (identity.replace(":", "-") + ".html"); hp.write_bytes(raw)
        dr = runner.write(hp.with_suffix(".json"), doc)
        sources.extend(runner.make_sources(doc, dr))
        documents.append({"document": dr, "raw_html": runner.reference(hp)})
    sr = runner.write(tmp_path / "sources.json", sources)
    from collections import Counter
    return {"schema": "legal-official-uscode-diagnostic-manifest/v1",
            "documents": documents,
            "sources": sr,
            "training_qualified": False, "statutory_accuracy_available": False,
            "implementation": [runner.reference(SCRIPT), runner.reference(context.__file__)],
            "counts": {"documents": len(documents), "views": len(sources),
                       "view_kinds": dict(Counter(s["kind"] for s in sources)),
                       "distinct_texts": len({s["source_sha256"] for s in sources})}}


def test_all_paragraphs_and_enclosing_blocks_are_exposed_diagnostics():
    d = document(); rows = runner.make_sources(d, {"path": "d.json"})
    assert len([r for r in rows if r["kind"] == "paragraph"]) == 4
    blocks = [r for r in rows if r["kind"] == "enclosing_block"]
    assert len(blocks) == 1 and blocks[0]["subsection_path"] == "(a)"
    assert "editorial" not in blocks[0]["source_text"]
    assert "Pub. L." not in next(r for r in rows if r["kind"] == "full_codified_body")["source_text"]
    assert all(r["training_qualified"] is False and r["independent_reference"] is None for r in rows)
    assert all(r["split"] == "exposed_diagnostic_only" for r in rows)


def test_every_source_coordinate_and_hash_reconstructs_exact_text():
    d = document()
    rows = runner.make_sources(d, {"path": "d.json"})
    for row in rows:
        assert row["source_text"] == d["document_text"][row["char_start"]:row["char_end"]]
        assert row["source_sha256"] == context.sha(row["source_text"])
    assert len({r["id"] for r in rows}) == len(rows)


def test_inline_reference_does_not_create_or_reparent_subsections():
    d = document()
    assert [p["subsection_path"] for p in d["paragraphs"] if p["kind"] == "codified_body"] == ["(a)", "(a)(1)", "(a)(2)", "(b)"]


def test_interleaved_notes_fail_closed_before_body_slice():
    with pytest.raises(ValueError):
        d = document(html(interleave=True))
        runner.make_sources(d, {"path": "d.json"})


@pytest.mark.parametrize("legal_id", ["usc:us:18:1", "usc:us:5:2"])
def test_legal_id_must_match_official_url(legal_id):
    with pytest.raises(ValueError):
        context.extract_document(html(), url=URL, edition=2024, legal_id=legal_id)


def test_heading_must_match_section_identity():
    with pytest.raises(ValueError):
        document(html(heading="§2. Different section"))


def test_two_section_headings_are_not_silently_merged():
    raw = html() + b'<h3 class="section-head">Section 1 again</h3>'
    with pytest.raises(ValueError):
        document(raw)


def test_equal_paragraph_and_body_views_remain_distinct():
    raw = b'<h3 class="section-head">&#167;1. Example</h3><p class="statutory-body">An agency shall file.</p>'
    rows = runner.make_sources(document(raw), {"path": "d.json"})
    assert len(rows) == 2 and rows[0]["source_sha256"] == rows[1]["source_sha256"]
    assert rows[0]["id"] != rows[1]["id"]


def test_manifest_replays_source_inventory(tmp_path):
    value = manifest(tmp_path)
    assert runner.validate_manifest(value) == runner.read(value["sources"])


def test_duplicate_document_entries_are_rejected(tmp_path):
    value = manifest(tmp_path)
    value["documents"].append(deepcopy(value["documents"][0]))
    with pytest.raises(ValueError):
        runner.validate_manifest(value)


def test_manifest_count_tampering_is_rejected(tmp_path):
    value = manifest(tmp_path); value["counts"]["views"] += 1
    with pytest.raises(ValueError):
        runner.validate_manifest(value)


def test_missing_declared_pilot_section_rejected(tmp_path):
    value = manifest(tmp_path); value["documents"].pop()
    with pytest.raises(ValueError, match="five-section"):
        runner.validate_manifest(value)


def test_unreviewed_sources_cannot_claim_training_qualification(tmp_path):
    value = manifest(tmp_path); value["training_qualified"] = True
    with pytest.raises(ValueError, match="authority claims"):
        runner.validate_manifest(value)


def test_changed_official_html_bytes_are_rejected(tmp_path):
    value = manifest(tmp_path)
    Path(value["documents"][0]["raw_html"]["path"]).write_bytes(html() + b'changed')
    with pytest.raises(ValueError, match="HTML changed"):
        runner.validate_manifest(value)


def test_changed_source_inventory_bytes_are_rejected(tmp_path):
    value = manifest(tmp_path)
    Path(value["sources"]["path"]).write_text("[]")
    with pytest.raises(ValueError, match="artifact bytes"):
        runner.validate_manifest(value)
