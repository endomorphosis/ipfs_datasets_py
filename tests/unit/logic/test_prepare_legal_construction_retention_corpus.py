"""Independent construction cases, document coordinates and selection embargo."""
from collections import Counter
import copy
import io
from pathlib import Path

import pytest

from scripts.ops.legal_ir import prepare_legal_construction_retention_corpus as corpus


@pytest.fixture(scope="module")
def panels():
    return corpus.make_panels()


def test_complete_paired_case_groups_have_identical_semantics(panels):
    rows, ledger = panels
    corpus.validate_panels(rows, ledger)
    assert len(rows["single"]) == 180
    groups = {}
    for a in ledger["single_rows"]:
        groups.setdefault(a["case_group"], []).append(a["family"])
    assert len(groups) == 30
    assert all(Counter(v) == Counter(corpus.FAMILIES) for v in groups.values())


def test_seen_anchors_match_all_six_fresh_case_targets(panels):
    rows, ledger = panels
    by_id = {r["id"]: r for r in rows["single"] + rows["anchor"]}
    cases = {a["case_group"]: by_id[a["id"]]["canonical_ir"] for a in ledger["anchor_rows"]}
    assert len(cases) == 30
    for a in ledger["single_rows"]:
        assert by_id[a["id"]]["canonical_ir"] == cases[a["case_group"]]


def test_all_six_families_have_all_modalities_and_all_present_qualifiers(panels):
    rows, ledger = panels
    by_id = {r["id"]: r for r in rows["single"]}
    for family in corpus.FAMILIES:
        rules = [by_id[a["id"]]["canonical_ir"]["rules"][0] for a in ledger["single_rows"] if a["family"] == family]
        assert Counter(r["modality"] for r in rules) == {"O": 10, "P": 10, "F": 10}
        assert all(all(len(r[f]) == 1 for f in ("conditions", "exceptions", "temporal")) for r in rules)


@pytest.mark.parametrize("family,field", [("postmodal_condition", "conditions"), ("postmodal_exception", "exceptions"), ("postmodal_temporal", "temporal")])
def test_postmodal_qualifier_has_explicit_coordinates_between_modal_and_action(family, field):
    row = corpus.render("single", 5, family)
    spans = row["facet_spans"]
    assert row["source_text"][slice(*row["trigger_span"])] == "must not"
    assert row["trigger_span"][1] < spans[field][0] < spans[field][1] < spans["action"][0]


def test_end_temporal_limit_precedes_all_trailing_conditions_and_exceptions(panels):
    for row in panels[0]["single"]:
        spans = row["facet_spans"]
        if spans["temporal"][0] > spans["object"][1]:
            for field in ("conditions", "exceptions"):
                if spans[field][0] > spans["object"][1]:
                    assert spans["temporal"][1] < spans[field][0]


def test_document_denominators_coordinates_and_repeated_occurrences(panels):
    rows, ledger = panels
    annotations = {a["candidate_id"]: a for a in ledger["document_rows"]}
    for panel in ("document_tuning", "document_challenge"):
        assert Counter(r["supported"] for r in rows[panel]) == {True: 72, False: 24}
        assert Counter(len(r["clauses"]) for r in rows[panel] if r["supported"]) == {1: 18, 2: 18, 3: 18, 4: 18}
        for row in rows[panel]:
            corpus.validate_document(row, annotations[row["candidate_id"]])
            if row["repeated_rule_occurrences"]:
                assert row["clauses"][0]["rule"] == row["clauses"][2]["rule"]
                assert row["clauses"][0]["char_end"] < row["clauses"][2]["char_start"]
            if not row["supported"]:
                assert row["clauses"] == []
                assert annotations[row["candidate_id"]]["clause_coordinates"] == []


@pytest.mark.parametrize("mutation", ["facet", "source", "case", "clause"])
def test_corrupted_annotation_binding_fails(panels, mutation):
    rows, ledger = copy.deepcopy(panels)
    if mutation == "facet":
        ledger["single_rows"][0]["facet_spans"]["actor"] = [0, 1]
    elif mutation == "source":
        ledger["single_rows"][0]["source_sha256"] = "0" * 64
    elif mutation == "case":
        ledger["single_rows"][0]["case_group"] = "different-case"
    else:
        ledger["document_rows"][0]["clause_coordinates"][0]["char_start"] = 1
    with pytest.raises(ValueError):
        corpus.validate_panels(rows, ledger)


def test_source_overlap_rejection_includes_document_clause(panels):
    rows = panels[0]
    document = next(r for r in rows["document_tuning"] if len(r["clauses"]) == 2)
    clause = document["clauses"][0]
    text = document["source_text"][clause["char_start"]:clause["char_end"]]
    with pytest.raises(ValueError, match="overlaps"):
        corpus.verify_disjoint(rows, {text.upper().replace(" ", "   ")})


def test_generic_layout_ignores_names_modality_spelling_and_terminal_punctuation():
    a = corpus.render("single", 0, "postmodal_condition")
    b = corpus.render("single", 1, "postmodal_condition")
    b["source_text"] = b["source_text"][:-1] + ";"
    assert corpus.generic_layout(a) == corpus.generic_layout(b)
    assert corpus.generic_layout(a) != corpus.generic_layout(corpus.render("single", 0, "postmodal_exception"))


def test_actual_pinned_pool_novelty_and_loader_deny_sealed_bytes(tmp_path, monkeypatch):
    manifest_ref = corpus.freeze(tmp_path / "corpus")
    manifest = corpus.read_ref(manifest_ref)
    assert manifest["construction_exposure_summary"]["fresh_single_layout_matches"] == 0
    assert manifest["construction_exposure_summary"]["all_document_tuning_clauses_have_verified_training_layout_exposure"]
    denied = {Path(manifest["artifacts"][k]["path"]).resolve() for k in corpus.SEALED}
    native_open = io.open

    def guarded_open(file, *args, **kwargs):
        if isinstance(file, (str, Path)) and Path(file).resolve() in denied:
            raise AssertionError("selection opened sealed reference bytes")
        return native_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    loaded = corpus.load_selection_inputs(manifest_ref["path"])
    assert {k: len(v) for k, v in loaded["tuning"].items()} == {"earlier": 96, "prior_new": 96, "temporal": 120}
    assert len(loaded["document_tuning"]) == 96
    assert len(loaded["fresh_sources"]) == 180
    assert len(loaded["anchor_sources"]) == 30
    assert len(loaded["fresh_document_sources"]) == 96
    assert all(set(r) == {"id", "source_text"} for r in loaded["fresh_sources"])
    assert all(set(r) == corpus.SOURCE_KEYS for r in loaded["fresh_document_sources"])
