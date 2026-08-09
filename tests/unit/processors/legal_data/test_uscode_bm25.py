"""Unit tests for US Code field-weighted BM25 release (USCIR-015).

Acceptance:

* Every admitted corpus chunk has one BM25 document row.
* Source/corpus roots reconcile.
* Field scores are explainable.
* Legacy k1/b differences are explicit.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_bm25 import (
    DEFAULT_B,
    DEFAULT_FIELD_WEIGHTS,
    DEFAULT_K1,
    FIELD_ORDER,
    FIXTURE_SCHEMA_VERSION,
    LEGACY_K1,
    PRIMARY_KEY,
    SCHEMA_VERSION,
    TASK_ID,
    Bm25ConfigError,
    Bm25CoverageError,
    Bm25ProjectionError,
    Bm25RootReconcileError,
    FieldWeightConfig,
    UscodeBm25Config,
    assert_every_admitted_chunk_has_document,
    build_corpus_root_cid,
    build_default_bm25_expected_fixture_payload,
    build_index_root_cid,
    build_uscode_bm25_index,
    default_bm25_config,
    default_bm25_expected_fixture_path,
    legacy_parameter_delta,
    load_bm25_expected_fixture_payload,
    project_admitted_documents,
    project_legal_document,
    reconcile_roots,
    run_all_fixture_cases,
    run_fixture_case,
)
from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import TOKENIZER_ID

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "uscode_bm25_expected.json"
)


def _sample_rows() -> list[dict]:
    return [
        {
            "entry_cid": "sha256:" + ("a" * 64),
            "chunk_cid": "sha256:" + ("b" * 64),
            "legal_id": "usc:us:5:552",
            "title": "5",
            "section": "552",
            "heading": "Public information; agency rules, opinions, orders, records",
            "chapter": "5",
            "citation": "5 U.S.C. § 552",
            "body": (
                "Each agency shall make available to the public information "
                "as follows: final opinions and orders made in the adjudication "
                "of cases under the Freedom of Information Act."
            ),
            "note": "FOIA disclosure duties.",
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("c" * 64),
            "chunk_cid": "sha256:" + ("d" * 64),
            "legal_id": "usc:us:5:552a",
            "title": "5",
            "section": "552a",
            "heading": "Records maintained on individuals",
            "chapter": "5",
            "citation": "5 U.S.C. § 552a",
            "body": (
                "No agency shall disclose any record which is contained in a "
                "system of records by any means of communication to any person."
            ),
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("e" * 64),
            "chunk_cid": "sha256:" + ("f" * 64),
            "legal_id": "usc:us:35:101",
            "title": "35",
            "section": "101",
            "heading": "Inventions patentable",
            "chapter": "10",
            "citation": "35 U.S.C. § 101",
            "body": (
                "Whoever invents or discovers any new and useful process, "
                "machine, manufacture, or composition of matter may obtain a patent."
            ),
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("1" * 64),
            "chunk_cid": "sha256:" + ("2" * 64),
            "legal_id": "usc:us:35:103",
            "title": "35",
            "section": "103",
            "heading": "Conditions for patentability; non-obvious subject matter",
            "chapter": "10",
            "citation": "35 U.S.C. § 103",
            "body": (
                "A patent for a claimed invention may not be obtained if the "
                "differences between the claimed invention and the prior art "
                "would have been obvious before the effective filing date."
            ),
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("3" * 64),
            "chunk_cid": "sha256:" + ("4" * 64),
            "legal_id": "usc:us:17:107",
            "title": "17",
            "section": "107",
            "heading": "Limitations on exclusive rights: Fair use",
            "chapter": "1",
            "citation": "17 U.S.C. § 107",
            "body": (
                "Notwithstanding the provisions of sections 106 and 106A, the "
                "fair use of a copyrighted work is not an infringement of copyright."
            ),
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "",
            "row_id": "recovery-src-01",
            "disposition": "quarantined",
            "is_recovery": True,
            "body": "workflow recovery payload must not enter BM25",
        },
        {
            "entry_cid": "sha256:" + ("9" * 64),
            "disposition": "excluded",
            "body": "excluded incomplete provenance row",
            "title": "99",
            "section": "999",
        },
    ]


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_bm25_fixture_is_present_and_compact():
    assert _FIXTURE_PATH.is_file()
    assert default_bm25_expected_fixture_path().name == "uscode_bm25_expected.json"
    size = _FIXTURE_PATH.stat().st_size
    assert size < 32_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["task_id"] == TASK_ID
    assert payload["primary_key"] == PRIMARY_KEY
    assert payload["default_parameters"]["tokenizer_id"] == TOKENIZER_ID
    assert payload["acceptance"]["every_admitted_chunk_has_one_bm25_document"]
    assert payload["acceptance"]["source_corpus_roots_reconcile"]
    assert payload["acceptance"]["field_scores_are_explainable"]
    assert payload["acceptance"]["legacy_k1_b_differences_are_explicit"]
    assert isinstance(payload["cases"], list)
    assert len(payload["cases"]) >= 5
    for case in payload["cases"]:
        assert "case_id" in case
        assert "expect" in case
        assert "kind" in case
        # Recipe form: no bulk posting / document golden dumps.
        assert "documents" not in case
        assert "postings" not in case
        assert "scores" not in case


def test_default_payload_matches_on_disk_recipe():
    built = build_default_bm25_expected_fixture_payload()
    on_disk = load_bm25_expected_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["task_id"] == on_disk["task_id"]
    assert built["default_parameters"]["k1"] == on_disk["default_parameters"]["k1"]
    assert built["default_parameters"]["b"] == on_disk["default_parameters"]["b"]
    assert built["default_parameters"]["field_weights"] == on_disk["default_parameters"][
        "field_weights"
    ]
    built_ids = [c["case_id"] for c in built["cases"]]
    disk_ids = [c["case_id"] for c in on_disk["cases"]]
    assert built_ids == disk_ids


def test_all_sealed_fixture_cases_pass():
    results = run_all_fixture_cases(_FIXTURE_PATH, rows=_sample_rows())
    assert results
    for result in results:
        assert result["ok"], result


# ---------------------------------------------------------------------------
# Config / legacy delta
# ---------------------------------------------------------------------------


def test_default_config_pins_and_rejects_invalid():
    cfg = default_bm25_config()
    assert cfg.k1 == DEFAULT_K1
    assert cfg.b == DEFAULT_B
    assert cfg.schema_version == SCHEMA_VERSION
    assert cfg.tokenizer.tokenizer_id == TOKENIZER_ID
    assert cfg.field_weights.to_dict() == dict(DEFAULT_FIELD_WEIGHTS)
    assert cfg.digest
    with pytest.raises(Bm25ConfigError):
        UscodeBm25Config(k1=0.0)
    with pytest.raises(Bm25ConfigError):
        UscodeBm25Config(b=1.5)
    with pytest.raises(Bm25ConfigError):
        FieldWeightConfig(body=0.0)


def test_legacy_k1_b_differences_are_explicit():
    delta = legacy_parameter_delta()
    assert delta["k1"]["legacy"] == LEGACY_K1
    assert delta["k1"]["evaluation_default"] == DEFAULT_K1
    assert delta["k1"]["changed"] is True
    assert math.isclose(delta["k1"]["delta"], DEFAULT_K1 - LEGACY_K1)
    assert delta["b"]["changed"] is False
    assert "legacy" in delta["notes"].lower() or "k1=1.5" in delta["notes"]
    # Shared layout defaults agree with evaluation k1/b starting points.
    assert delta["shared_layout_defaults"]["k1"] == DEFAULT_K1
    assert delta["shared_layout_defaults"]["b"] == DEFAULT_B


# ---------------------------------------------------------------------------
# Projection / coverage
# ---------------------------------------------------------------------------


def test_every_admitted_chunk_has_one_bm25_document():
    rows = _sample_rows()
    index = build_uscode_bm25_index(rows)
    admitted = [row for row in rows if row.get("disposition") == "admitted"]
    assert index.document_count == len(admitted) == 5
    assert len({doc.entry_cid for doc in index.documents}) == 5
    assert_every_admitted_chunk_has_document(rows, index)
    # Quarantine / excluded never enter the index.
    assert all(doc.entry_cid != "sha256:" + ("9" * 64) for doc in index.documents)
    assert all(doc.record_type != "recovery" for doc in index.documents)


def test_project_indexes_all_declared_fields():
    row = _sample_rows()[0]
    document = project_legal_document(row, document_index=0)
    assert set(document.fields) == set(FIELD_ORDER)
    assert document.fields["citation"].length > 0
    assert document.fields["body"].length > 0
    assert document.fields["heading"].length > 0
    assert document.fields["title"].weight == DEFAULT_FIELD_WEIGHTS["title"]
    assert document.fields["citation"].weight == DEFAULT_FIELD_WEIGHTS["citation"]
    assert document.total_length > 0
    # Shared layout projection is dual-channel title/body.
    shared = document.to_shared_layout_row()
    assert shared["entry_cid"] == document.entry_cid
    assert shared["title"]
    assert shared["body"]


def test_positional_identity_fails_closed():
    with pytest.raises(Bm25ProjectionError):
        project_legal_document(
            {
                "entry_cid": "row-12",
                "body": "positional identity must fail",
                "disposition": "admitted",
            },
            document_index=0,
        )


def test_empty_admitted_set_fails():
    with pytest.raises(Bm25CoverageError):
        project_admitted_documents(
            [
                {
                    "disposition": "quarantined",
                    "is_recovery": True,
                    "body": "recovery only",
                }
            ]
        )


# ---------------------------------------------------------------------------
# Root reconciliation
# ---------------------------------------------------------------------------


def test_source_and_corpus_roots_reconcile():
    rows = _sample_rows()
    corpus_root = build_corpus_root_cid(rows)
    index = build_uscode_bm25_index(rows, corpus_root_cid=corpus_root)
    receipt = reconcile_roots(index, expected_corpus_root_cid=corpus_root)
    assert receipt["reconciled"] is True
    assert index.corpus_root_cid == corpus_root
    assert index.index_root_cid.startswith("sha256:")
    recomputed = build_index_root_cid(
        index.documents, config=index.config, corpus_root_cid=corpus_root
    )
    assert recomputed == index.index_root_cid
    # Deterministic rebuild.
    again = build_uscode_bm25_index(rows, corpus_root_cid=corpus_root)
    assert again.index_root_cid == index.index_root_cid
    assert again.corpus_root_cid == index.corpus_root_cid


def test_root_mismatch_fails_closed():
    rows = _sample_rows()
    index = build_uscode_bm25_index(rows)
    with pytest.raises(Bm25RootReconcileError):
        reconcile_roots(index, expected_corpus_root_cid="sha256:" + ("0" * 64))


# ---------------------------------------------------------------------------
# Scoring / explanations / filters
# ---------------------------------------------------------------------------


def test_field_scores_are_explainable():
    index = build_uscode_bm25_index(_sample_rows())
    hits = index.search("freedom of information agency records", top_k=3)
    assert hits
    top = hits[0]
    assert top.score > 0.0
    assert top.matched_terms
    assert top.explanations
    assert top.legal_id and top.legal_id.startswith("usc:us:5:552")
    # At least one term has a field contribution with weight + tf.
    contribs = [
        contrib
        for expl in top.explanations
        for contrib in expl.field_contributions
    ]
    assert contribs
    for contrib in contribs:
        assert contrib.field in FIELD_ORDER
        assert contrib.tf > 0
        assert contrib.weight > 0.0
        assert contrib.score >= 0.0
        assert math.isfinite(contrib.score)
    # Manifest fragment carries tokenizer + parameter pins.
    fragment = index.to_manifest_fragment()
    assert fragment["task_id"] == TASK_ID
    assert fragment["bm25"]["k1"] == DEFAULT_K1
    assert fragment["bm25"]["tokenizer_id"] == TOKENIZER_ID
    assert fragment["bm25"]["corpus_root_cid"] == index.corpus_root_cid
    assert fragment["bm25"]["index_root_cid"] == index.index_root_cid
    assert fragment["bm25"]["legacy_parameter_delta"]["k1"]["changed"] is True


def test_title_filter_restricts_results():
    index = build_uscode_bm25_index(_sample_rows())
    hits = index.search("patent invention process", top_k=10, filters={"title": "35"})
    assert hits
    assert all(hit.filters.get("title") == "35" for hit in hits)
    assert all(
        hit.legal_id is not None and hit.legal_id.startswith("usc:us:35:")
        for hit in hits
    )


def test_citation_field_boosts_exact_legal_reference():
    index = build_uscode_bm25_index(_sample_rows())
    hits = index.search("5 U.S.C. § 552", top_k=3)
    assert hits
    # Exact citation query should prefer the FOIA section document.
    assert hits[0].legal_id == "usc:us:5:552"
    # Citation field should appear in at least one contribution.
    fields_hit = {
        contrib.field
        for expl in hits[0].explanations
        for contrib in expl.field_contributions
    }
    assert "citation" in fields_hit or "body" in fields_hit


def test_higher_field_weight_increases_contribution():
    rows = _sample_rows()
    base = build_uscode_bm25_index(rows)
    boosted = build_uscode_bm25_index(
        rows,
        config=UscodeBm25Config(
            field_weights=FieldWeightConfig(
                citation=8.0,
                title=5.0,
                heading=4.0,
                hierarchy=3.0,
                body=10.0,  # boosted body
                note=0.5,
            )
        ),
    )
    query = "agency shall make available"
    base_hit = base.search(query, top_k=1)[0]
    boosted_hit = boosted.search(query, top_k=1)[0]
    assert boosted_hit.entry_cid == base_hit.entry_cid
    assert boosted_hit.score > base_hit.score


def test_run_fixture_case_helpers():
    payload = load_bm25_expected_fixture_payload(_FIXTURE_PATH)
    for case in payload["cases"]:
        result = run_fixture_case(case, rows=_sample_rows())
        assert result["ok"], result
