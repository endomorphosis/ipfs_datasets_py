"""Independent full-source fixtures for unreviewed lexical sentence proposals."""
from copy import deepcopy
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_parent_parquet_pages as pages
from ipfs_datasets_py.logic.autoformal import legal_parent_text_views as views
from ipfs_datasets_py.logic.autoformal import legal_parent_sentence_candidates as owner


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def fixture(tmp_path, texts=None):
    texts = ["Metadata Heading. Café must act under section 12. Historical and Revision Notes Other text.",
             "Heading. Snow 雪 may act under this section! "] if texts is None else texts
    rows = [{"ipfs_cid": "cid:" + str(i), "title_number": "10", "section_number": str(i + 1),
        "law_name": "Heading", "text": text, "subsections_json": '{"(a)":"contaminated notes"}',
        "raw_json": '{"accepted":true}', "parser_warnings": []} for i, text in enumerate(texts)]
    schema = pa.schema([(key, pa.list_(pa.string()) if key == "parser_warnings" else pa.string()) for key in rows[0]])
    path = tmp_path / "parent.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="snappy", data_page_version="1.0", row_group_size=1)
    descriptor = {"repository": "fixture/parent", "revision": "a" * 40, "path_in_repo": path.name,
        "local_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size, "row_count": len(rows), "profile": pages.PARENT_PROFILE}
    preflight = pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=digest(descriptor))
    ordinals = list(range(len(rows))); row_pins = [digest(row) for row in rows]
    selected = pages.read_selected_parent_rows(descriptor, expected_descriptor_sha256=digest(descriptor),
        preflight_report=preflight, expected_preflight_sha256=digest(preflight), row_ordinals=ordinals, expected_row_sha256s=row_pins)
    replay = {"expected_selected_rows_report_sha256": digest(selected), "parent_descriptor": descriptor,
        "expected_parent_descriptor_sha256": digest(descriptor), "preflight_report": preflight,
        "expected_preflight_sha256": digest(preflight), "row_ordinals": ordinals, "expected_row_sha256s": row_pins}
    report = views.prepare_parent_text_views(selected, **replay)
    return report, {"expected_parent_text_views_report_sha256": digest(report), "parent_text_views_inputs": replay}


def materialize(tmp_path, texts=None):
    report, args = fixture(tmp_path, texts)
    return owner.prepare_parent_sentence_candidates(report, **args), report, args


def assert_partition(row, text):
    pieces = row["segments"]
    assert "".join(p["selector"]["text"] for p in pieces) == text
    assert "".join(p["selector"]["text"] for p in pieces).encode() == text.encode()
    assert pieces[0]["selector"]["char_start"] == 0 and pieces[-1]["selector"]["char_end"] == len(text)
    for a, b in zip(pieces, pieces[1:]):
        assert a["selector"]["char_end"] == b["selector"]["char_start"]
        assert a["selector"]["utf8byte_end"] == b["selector"]["utf8byte_start"]
    for piece in pieces:
        s = piece["selector"]
        assert text[s["char_start"]:s["char_end"]] == s["text"]
        assert text.encode()[s["utf8byte_start"]:s["utf8byte_end"]].decode() == s["text"]
        assert s["utf8byte_start"] == len(text[:s["char_start"]].encode())
        assert piece["selected_as_legal_sentence"] is False and piece["autoformalization_eligible"] is False
        assert all(flag is False for flag in piece["authority"].values())


def test_every_Unicode_character_and_gap_is_preserved_with_exact_context_windows(tmp_path):
    text = " \tCafé acts.\n雪 waits!\u00a0Last fragment  "
    report, source, args = materialize(tmp_path, [text])
    row = report["rows"][0]; assert_partition(row, text)
    assert sum(p["kind"] == "raw_whitespace_gap" for p in row["segments"]) >= 3
    for piece in row["segments"]:
        s = piece["selector"]
        for name, target in (("prefix", text[max(0, s["char_start"] - 256):s["char_start"]]),
                             ("suffix", text[s["char_end"]:min(len(text), s["char_end"] + 256)])):
            context = piece["context"][name]
            assert context is None if not target else context["text"] == target
        assert not piece["context"]["definitions_resolved"] and not piece["context"]["cross_section_context_resolved"]
    assert report["population_complete"] and report["all_candidates_autoformalization_ineligible"]
    assert report["total_source_characters"] == len(text)
    assert owner.parent_sentence_candidates_report_sha256(report) == digest(report)
    assert owner.validate_parent_sentence_candidates(report, source, expected_report_sha256=digest(report), **args)["valid"]


def test_abbreviations_dotted_citations_and_decimal_periods_are_explicitly_ambiguous(tmp_path):
    text = "U.S.C. § 1.5 and Pub. L. 123. Jan. 1. A. item remains. Next!"
    report, _, _ = materialize(tmp_path, [text]); row = report["rows"][0]
    assert_partition(row, text)
    observations = row["boundary_observations"]
    decimal = next(o for o in observations if o["selector"]["char_start"] == text.index("1.5") + 1)
    assert decimal["split_candidate"] is False and "decimal_or_number_component" in decimal["issues"]
    assert any("abbreviation_period_unresolved" in o["issues"] for o in observations)
    assert any("initial_or_dotted_citation_period_unresolved" in o["issues"] for o in observations)
    assert all(o["boundary_verified"] is False for o in observations)


def test_balanced_groups_and_quotes_keep_internal_terminators_as_unresolved_observations(tmp_path):
    text = "Start (citation. still here) and “quoted! still inside” finishes. Next?"
    report, _, _ = materialize(tmp_path, [text]); row = report["rows"][0]
    assert_partition(row, text)
    observations = row["boundary_observations"]
    assert any("inside_delimiter_group_boundary_unresolved" in o["issues"] for o in observations)
    assert any("inside_quotation_boundary_unresolved" in o["issues"] for o in observations)
    assert not row["issues"]


@pytest.mark.parametrize("tail", [") unmatched.", "(unclosed.", '"unclosed.', "[wrong).", "<p>markup.</p>"])
def test_invalid_whole_source_state_cannot_select_easy_earlier_sentences(tmp_path, tail):
    text = "Apparently complete. " + tail
    report, _, _ = materialize(tmp_path, [text]); row = report["rows"][0]
    assert_partition(row, text)
    assert row["issues"]
    assert all(p["kind"] != "lexical_sentence_boundary_candidate" for p in row["segments"])
    assert all(p["autoformalization_eligible"] is False for p in row["segments"])


def test_multiclause_semicolons_exceptions_and_terminal_fragments_are_not_simplified(tmp_path):
    text = "A shall act; provided that B consents, except when C objects. Remaining fragment"
    report, _, _ = materialize(tmp_path, [text]); row = report["rows"][0]
    assert_partition(row, text)
    assert any("provided that B consents, except when C objects" in p["selector"]["text"] for p in row["segments"])
    assert any(p["kind"] == "unresolved_fragment" for p in row["segments"])
    assert all(p["region_intersections"]["source_region_roles_verified"] is False for p in row["segments"])


def test_frontmatter_notes_headings_and_repeated_markers_are_retained_unclassified(tmp_path):
    text = "Metadata Heading. Heading says act. Historical and Revision Notes Amendments say other. Amendments final."
    report, _, _ = materialize(tmp_path, [text]); row = report["rows"][0]
    assert_partition(row, text)
    assert sum(m["marker_text"] == "Heading" for m in row["marker_observations"]) == 2
    assert sum(m["marker_text"] == "Amendments" for m in row["marker_observations"]) == 2
    assert all(p["disposition"] in ("unresolved_unclassified_source_local_candidate", "raw_gap_observation") for p in row["segments"])
    assert report["producer_segmentation_fields_used_as_gold"] is False
    assert report["diagnostic_cache_fragments_used_as_gold"] is False


def test_duplicate_parent_text_and_labels_never_merge_physical_candidates(tmp_path):
    report, _, _ = materialize(tmp_path, ["Same sentence.", "Same sentence."])
    first, second = report["rows"]
    assert first["source_text_sha256"] == second["source_text_sha256"]
    assert first["view_sha256"] != second["view_sha256"]
    assert first["segments"][0]["sentence_candidate_id"] != second["segments"][0]["sentence_candidate_id"]


def test_all_surface_dependency_mentions_are_retained_without_target_or_scope_selection(tmp_path):
    text = "Subject to subsection (a), section 12 and this section; such paragraph remains unresolved."
    report, _, _ = materialize(tmp_path, [text]); row = report["rows"][0]
    assert_partition(row, text)
    dependencies = row["dependency_candidates"]
    assert [d["selector"]["text"] for d in dependencies] == ["subsection (a)", "section 12", "this section", "such paragraph"]
    assert all(d["target_candidates"] == [] and d["selected_target"] is None and not d["reference_scope_verified"] for d in dependencies)
    linked = {identity for p in row["segments"] for identity in p["dependency_candidate_ids"]}
    assert linked == {d["dependency_candidate_id"] for d in dependencies}


@pytest.mark.parametrize("missing", [None, ""])
def test_unavailable_text_remains_in_complete_physical_parent_denominator(tmp_path, missing):
    report, _, _ = materialize(tmp_path, [missing, "Available sentence."])
    assert report["row_count"] == 2 and report["rows"][0]["segments"] == []
    assert report["rows"][0]["disposition"] == "unresolved_parent_text_view_unavailable"
    assert report["rows"][1]["segments"]


@pytest.mark.parametrize("damage", ["view_pin", "selected_pin", "descriptor_pin", "preflight_pin", "row_pin", "missing_input", "extra_input"])
def test_complete_external_parent_view_and_request_pins_are_required(tmp_path, damage):
    source, args = fixture(tmp_path)
    replay = args["parent_text_views_inputs"]
    if damage == "view_pin": args["expected_parent_text_views_report_sha256"] = "0" * 64
    elif damage == "selected_pin": replay["expected_selected_rows_report_sha256"] = "0" * 64
    elif damage == "descriptor_pin": replay["expected_parent_descriptor_sha256"] = "0" * 64
    elif damage == "preflight_pin": replay["expected_preflight_sha256"] = "0" * 64
    elif damage == "row_pin": replay["expected_row_sha256s"][0] = "0" * 64
    elif damage == "missing_input": replay.pop("parent_descriptor")
    else: replay["trusted_reader"] = "arbitrary callback"
    with pytest.raises(ValueError): owner.prepare_parent_sentence_candidates(source, **args)


@pytest.mark.parametrize("damage", ["source_text", "omit_row", "row_order", "omit_segment", "geometry", "context", "authority", "dependency", "seal"])
def test_self_resealed_sentence_reports_cannot_forge_coverage_or_acceptance(tmp_path, damage):
    report, source, args = materialize(tmp_path); pin = digest(report)
    row = report["rows"][0]
    if damage == "source_text": row["source_text"] += " forged"
    elif damage == "omit_row": report["rows"].pop()
    elif damage == "row_order": report["rows"].reverse()
    elif damage == "omit_segment": row["segments"].pop()
    elif damage == "geometry": row["segments"][0]["selector"]["utf8byte_start"] += 1
    elif damage == "context": row["segments"][0]["context"]["definitions_resolved"] = True
    elif damage == "authority": row["segments"][0]["autoformalization_eligible"] = True
    elif damage == "dependency": row["dependency_candidates"][0]["selected_target"] = "guessed"
    else: report["sentence_candidates_sha256"] = "0" * 64
    with pytest.raises(ValueError): owner.validate_parent_sentence_candidates(report, source, expected_report_sha256=pin, **args)
    with pytest.raises(ValueError): owner.validate_parent_sentence_candidates(report, source, expected_report_sha256=digest(report), **args)


@pytest.mark.parametrize("bound", ["max_parent_views", "max_source_characters", "max_total_source_characters",
    "max_segments", "max_boundary_observations", "max_dependency_candidates", "max_report_bytes"])
def test_lowered_population_caps_refuse_without_easy_sentence_selection(tmp_path, bound, monkeypatch):
    source, args = fixture(tmp_path, ["First under section 12 and this section. Second.", "More section 13."])
    args["limits"] = {bound: 1}
    monkeypatch.setattr(views, "_selector", lambda *a, **kw: pytest.fail("partial sentence population materialized"))
    with pytest.raises(ValueError): owner.prepare_parent_sentence_candidates(source, **args)


def test_long_candidate_is_retained_as_unresolved_without_dropping_characters(tmp_path):
    text = "A lengthy single unresolved fragment"
    source, args = fixture(tmp_path, [text]); args["limits"] = {"max_candidate_characters": 3}
    report = owner.prepare_parent_sentence_candidates(source, **args); row = report["rows"][0]
    assert_partition(row, text)
    assert any(issue["code"] == "candidate_length_exceeds_sentence_profile" for p in row["segments"] for issue in p["issues"])


def test_source_character_bound_precedes_lexical_scan(tmp_path, monkeypatch):
    source, args = fixture(tmp_path, [")" * 65537])
    monkeypatch.setattr(owner, "_scan", lambda *a: pytest.fail("over-bound source scanned"))
    with pytest.raises(ValueError): owner.prepare_parent_sentence_candidates(source, **args)


def test_delimiter_depth_bound_refuses_whole_source_instead_of_accepting_easy_prefix(tmp_path):
    source, args = fixture(tmp_path, ["Easy sentence. " + "(" * 65 + "x" + ")" * 65])
    with pytest.raises(ValueError): owner.prepare_parent_sentence_candidates(source, **args)


@pytest.mark.parametrize("closing", ["”", "’"])
def test_unmatched_curly_closing_quote_invalidates_easy_earlier_boundary(tmp_path, closing):
    text = "Good. Broken." + closing
    report, _, _ = materialize(tmp_path, [text]); row = report["rows"][0]
    assert_partition(row, text)
    assert row["issues"]
    assert all(piece["kind"] != "lexical_sentence_boundary_candidate" for piece in row["segments"])


def test_curly_apostrophe_inside_a_word_is_preserved_without_inventing_quote_scope(tmp_path):
    text = "A person’s rights remain. Next."
    report, _, _ = materialize(tmp_path, [text]); row = report["rows"][0]
    assert_partition(row, text)
    assert not row["issues"]


@pytest.mark.parametrize("mode", ["count", "bytes", "global_count"])
def test_structural_issue_budget_stops_before_excess_retention_and_applies_across_views(tmp_path, mode, monkeypatch):
    texts = ["]", "]"] if mode == "global_count" else ["]" * 64]
    source, args = fixture(tmp_path, texts)
    first = {"code": "unmatched_closing_delimiter", "char_position": 0}
    args["limits"] = {"max_structural_issue_bytes": len(wire(first)) + 1} if mode == "bytes" else {"max_structural_issue_observations": 1}
    original = owner.custody._wire; observed = []
    def watch(observation, *positional, **keywords):
        if type(observation) is dict and observation.get("code") == "unmatched_closing_delimiter":
            observed.append(observation["char_position"])
            assert len(observed) <= 2, "continued scanning after structural budget exhaustion"
        return original(observation, *positional, **keywords)
    monkeypatch.setattr(owner.custody, "_wire", watch)
    with pytest.raises(ValueError): owner.prepare_parent_sentence_candidates(source, **args)
    assert observed == ([0, 0] if mode == "global_count" else [0, 1])
