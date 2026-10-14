"""Literal field coordinates cannot become selected statutory source roles."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_parent_parquet_pages as pages
from ipfs_datasets_py.logic.autoformal import legal_parent_text_views as owner


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def fixture(tmp_path, texts=None, *, text_type=pa.string()):
    texts = ["Metadata Café §1. Heading aa aa. Historical and Revision Notes aa. Amendments 雪.",
             "Heading again. Heading. Effective Date ©."] if texts is None else texts
    schema = pa.schema([("ipfs_cid", pa.string()), ("title_number", pa.string()), ("section_number", pa.string()),
        ("text", text_type), ("law_name", pa.string()), ("subsections_json", pa.string()),
        ("raw_json", pa.string()), ("parser_warnings", pa.list_(pa.string())),
        *[("unknown_" + str(i), pa.string()) for i in range(37)]])
    rows = [{"ipfs_cid": "cid:" + str(i), "title_number": "10", "section_number": str(i + 1),
        "text": text, "law_name": "Heading", "subsections_json": '{"(a)":"contaminated notes"}',
        "raw_json": '{"asserted_body":"not independently verified"}', "parser_warnings": [],
        **{"unknown_" + str(j): "retain:" + str(j) for j in range(37)}} for i, text in enumerate(texts)]
    path = tmp_path / "parent.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="snappy", data_page_version="1.0", row_group_size=1)
    descriptor = {"repository": "fixture/parent", "revision": "a" * 40, "path_in_repo": path.name,
        "local_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size, "row_count": len(rows), "profile": pages.PARENT_PROFILE}
    preflight = pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=digest(descriptor))
    ordinals = list(range(len(rows))); pins = [digest(row) for row in rows]
    selected = pages.read_selected_parent_rows(descriptor, expected_descriptor_sha256=digest(descriptor),
        preflight_report=preflight, expected_preflight_sha256=digest(preflight), row_ordinals=ordinals, expected_row_sha256s=pins)
    args = {"expected_selected_rows_report_sha256": digest(selected), "parent_descriptor": descriptor,
        "expected_parent_descriptor_sha256": digest(descriptor), "preflight_report": preflight,
        "expected_preflight_sha256": digest(preflight), "row_ordinals": ordinals, "expected_row_sha256s": pins}
    return selected, args


def report_for(tmp_path, texts=None):
    selected, args = fixture(tmp_path, texts)
    return owner.prepare_parent_text_views(selected, **args), selected, args


def test_complete_literal_views_retain_all_45_fields_and_no_producer_segmentation_gold(tmp_path):
    report, selected, args = report_for(tmp_path)
    assert report["selected_rows_report"] == selected and report["row_count"] == 2
    assert all(len(row["raw_row"]) == 45 for row in selected["rows"])
    assert report["all_original_row_fields_retained"] and report["population_complete"]
    assert not report["whole_parent_population_covered"]
    for envelope, row in zip(report["views"], selected["rows"], strict=True):
        view = envelope["text_view"]
        assert view["text"] == row["raw_row"]["text"]
        assert view["char_count"] == len(view["text"]) and view["utf8_bytes"] == len(view["text"].encode())
        assert view["producer_segmentation_fields_are_observations_only"]
        assert view["regions"][0]["region_kind"] == "entire_text_unclassified"
        assert view["regions"][0]["char_start"] == 0 and view["regions"][0]["char_end"] == len(view["text"])
        assert all(flag is False for flag in view["authority"].values())
        assert view["coordinate_origin"]["normalization"] == "none"
    assert owner.parent_text_views_report_sha256(report) == digest(report)
    assert owner.validate_parent_text_views(report, selected, expected_report_sha256=digest(report), **args)["valid"]


def test_unicode_byte_ranges_are_exact_original_field_coordinates_with_all_overlaps(tmp_path):
    text = "Café 雪 aaaa Café"
    report, selected, args = report_for(tmp_path, [text])
    occurrences = owner.exact_parent_text_occurrences(report, selected, expected_report_sha256=digest(report), row_ordinal=0, text="aa", **args)
    assert [(r["char_start"], r["char_end"]) for r in occurrences] == [(7, 9), (8, 10), (9, 11)]
    for selector in occurrences:
        assert text[selector["char_start"]:selector["char_end"]] == selector["text"]
        assert text.encode()[selector["utf8byte_start"]:selector["utf8byte_end"]].decode() == selector["text"]
        assert selector["utf8byte_start"] == len(text[:selector["char_start"]].encode())
        assert selector["schema"] == owner.SELECTOR_SCHEMA
        assert selector["coordinate_origin"]["raw_html_byte_mapping_verified"] is False
        assert selector["coordinate_origin"]["parquet_file_byte_mapping_verified"] is False
        assert all(flag is False for flag in selector["authority"].values())


def test_marker_candidates_preserve_every_repeat_and_never_partition_a_body(tmp_path):
    text = "Heading Metadata Heading. Amendments quote Heading and Amendments. Effective Date."
    report, _, _ = report_for(tmp_path, [text])
    view = report["views"][0]["text_view"]; markers = view["marker_observations"]
    assert sum(m["marker_text"] == "Heading" for m in markers) == 3
    assert sum(m["marker_text"] == "Amendments" for m in markers) == 2
    assert all(m["legal_role_verified"] is False for m in markers)
    for marker in markers:
        assert text[marker["char_start"]:marker["char_end"]] == marker["marker_text"]
        assert text.encode()[marker["utf8byte_start"]:marker["utf8byte_end"]].decode() == marker["marker_text"]
    assert len(view["regions"]) == 1 and view["regions"][0]["region_kind"] == "entire_text_unclassified"
    assert view["authority"]["governing_body_selected"] is False


def test_identical_strings_have_distinct_physical_occurrence_view_identities(tmp_path):
    report, _, _ = report_for(tmp_path, ["Same text.", "Same text."])
    a, b = [row["text_view"] for row in report["views"]]
    assert a["text_sha256"] == b["text_sha256"]
    assert a["view_sha256"] != b["view_sha256"] and a["source_identity"]["row_ordinal"] != b["source_identity"]["row_ordinal"]


def test_literal_source_revision_separates_views_even_if_labels_and_text_match(tmp_path):
    selected, args = fixture(tmp_path, ["Same text."])
    before = owner.prepare_parent_text_views(selected, **args)
    changed = deepcopy(args); changed["parent_descriptor"]["revision"] = "b" * 40
    changed["expected_parent_descriptor_sha256"] = digest(changed["parent_descriptor"])
    preflight = pages.preflight_parent_pages(changed["parent_descriptor"], expected_descriptor_sha256=changed["expected_parent_descriptor_sha256"])
    changed["preflight_report"] = preflight; changed["expected_preflight_sha256"] = digest(preflight)
    current = pages.read_selected_parent_rows(changed["parent_descriptor"], expected_descriptor_sha256=changed["expected_parent_descriptor_sha256"],
        preflight_report=preflight, expected_preflight_sha256=digest(preflight), row_ordinals=changed["row_ordinals"], expected_row_sha256s=changed["expected_row_sha256s"])
    changed["expected_selected_rows_report_sha256"] = digest(current)
    after = owner.prepare_parent_text_views(current, **changed)
    assert before["views"][0]["text_view"]["text_sha256"] == after["views"][0]["text_view"]["text_sha256"]
    assert before["views"][0]["text_view"]["view_sha256"] != after["views"][0]["text_view"]["view_sha256"]


def test_view_identity_ignores_local_copy_path_but_full_custody_report_does_not(tmp_path):
    selected, args = fixture(tmp_path, ["Café exact text."])
    before = owner.prepare_parent_text_views(selected, **args)
    changed = deepcopy(args); source = Path(changed["parent_descriptor"]["local_path"])
    destination = tmp_path / "other" / source.name; destination.parent.mkdir(); shutil.copyfile(source, destination)
    changed["parent_descriptor"]["local_path"] = str(destination)
    changed["expected_parent_descriptor_sha256"] = digest(changed["parent_descriptor"])
    preflight = pages.preflight_parent_pages(changed["parent_descriptor"], expected_descriptor_sha256=changed["expected_parent_descriptor_sha256"])
    changed["preflight_report"] = preflight; changed["expected_preflight_sha256"] = digest(preflight)
    current = pages.read_selected_parent_rows(changed["parent_descriptor"], expected_descriptor_sha256=changed["expected_parent_descriptor_sha256"],
        preflight_report=preflight, expected_preflight_sha256=digest(preflight), row_ordinals=changed["row_ordinals"], expected_row_sha256s=changed["expected_row_sha256s"])
    changed["expected_selected_rows_report_sha256"] = digest(current)
    after = owner.prepare_parent_text_views(current, **changed)
    assert before["views"][0]["text_view"] == after["views"][0]["text_view"]
    assert digest(before) != digest(after)
    with pytest.raises(ValueError): owner.prepare_parent_text_views(selected, **changed)


@pytest.mark.parametrize("texts", [[None, "Available."], ["", "Available."]])
def test_missing_or_empty_text_is_preserved_as_a_physical_unresolved_row(tmp_path, texts):
    report, selected, _ = report_for(tmp_path, texts)
    assert report["row_count"] == 2 and report["selected_rows_report"] == selected
    assert report["views"][0]["text_view"] is None
    assert report["views"][0]["disposition"].startswith("unresolved_")
    assert report["views"][1]["text_view"] is not None


def test_nontext_original_field_is_retained_without_coercion(tmp_path):
    selected, args = fixture(tmp_path, [123], text_type=pa.int64())
    report = owner.prepare_parent_text_views(selected, **args)
    assert report["views"][0]["text_view"] is None
    assert report["selected_rows_report"]["rows"][0]["raw_row"]["text"] == 123


def test_unavailable_text_never_turns_an_invalid_query_into_an_empty_verified_population(tmp_path):
    report, selected, args = report_for(tmp_path, [None])
    assert owner.exact_parent_text_occurrences(report, selected, expected_report_sha256=digest(report),
        row_ordinal=0, text="literal", **args) == []
    with pytest.raises(ValueError):
        owner.exact_parent_text_occurrences(report, selected, expected_report_sha256=digest(report),
            row_ordinal=0, text="", **args)


@pytest.mark.parametrize("damage", ["full_selected_pin", "descriptor_pin", "preflight_pin", "row_pin", "order", "missing", "extra", "unknown_raw", "file_bytes"])
def test_complete_trusted_parent_population_and_pins_cannot_be_replaced(tmp_path, damage):
    selected, args = fixture(tmp_path)
    if damage == "full_selected_pin": args["expected_selected_rows_report_sha256"] = "0" * 64
    elif damage == "descriptor_pin": args["expected_parent_descriptor_sha256"] = "0" * 64
    elif damage == "preflight_pin": args["expected_preflight_sha256"] = "0" * 64
    elif damage == "row_pin": args["expected_row_sha256s"][0] = "0" * 64
    elif damage == "order": selected["rows"].reverse()
    elif damage == "missing": selected["rows"].pop()
    elif damage == "extra": selected["rows"].append(deepcopy(selected["rows"][0]))
    elif damage == "unknown_raw": selected["rows"][0]["raw_row"]["unknown_36"] = "forged"
    else: Path(args["parent_descriptor"]["local_path"]).write_bytes(b"changed source bytes")
    if damage in ("order", "missing", "extra", "unknown_raw"):
        args["expected_selected_rows_report_sha256"] = digest(selected)
    with pytest.raises(ValueError): owner.prepare_parent_text_views(selected, **args)


@pytest.mark.parametrize("damage", ["text", "char_count", "bytes", "region", "marker", "authority", "selected_raw", "drop_view", "view_order", "seal", "unknown"])
def test_report_self_resealing_cannot_override_full_fixed_parent_regeneration(tmp_path, damage):
    report, selected, args = report_for(tmp_path)
    pin = digest(report); view = report["views"][0]["text_view"]
    if damage == "text": view["text"] += " forged"
    elif damage == "char_count": view["char_count"] += 1
    elif damage == "bytes": view["utf8_bytes"] += 1
    elif damage == "region": view["regions"][0]["char_start"] += 1
    elif damage == "marker": view["marker_observations"][0]["char_start"] += 1
    elif damage == "authority": view["authority"]["formalization_eligible"] = True
    elif damage == "selected_raw": report["selected_rows_report"]["rows"][0]["raw_row"]["raw_json"] = "forged"
    elif damage == "drop_view": report["views"].pop()
    elif damage == "view_order": report["views"].reverse()
    elif damage == "seal": report["text_views_sha256"] = "0" * 64
    else: report["selected_original_occurrence"] = "invented"
    with pytest.raises(ValueError): owner.validate_parent_text_views(report, selected, expected_report_sha256=pin, **args)
    with pytest.raises(ValueError): owner.validate_parent_text_views(report, selected, expected_report_sha256=digest(report), **args)


def test_public_occurrence_api_cannot_accept_rehashed_view_or_partial_parent_inputs(tmp_path):
    report, selected, args = report_for(tmp_path)
    report["views"][0]["text_view"]["text"] = "forged aa"
    with pytest.raises(ValueError):
        owner.exact_parent_text_occurrences(report, selected, expected_report_sha256=digest(report), row_ordinal=0, text="aa", **args)
    with pytest.raises(TypeError):
        owner.exact_parent_text_occurrences(report, selected, expected_report_sha256=digest(report), row_ordinal=0, text="aa")


@pytest.mark.parametrize("bound,value", [("max_text_bytes", 1), ("max_total_text_bytes", 1),
    ("max_views", 1), ("max_markers", 1), ("max_report_bytes", 1), ("max_observation_bytes", 1)])
def test_population_limits_refuse_before_retaining_a_partial_report(tmp_path, bound, value, monkeypatch):
    selected, args = fixture(tmp_path)
    args["limits"] = {bound: value}
    original = owner.deepcopy
    def watch_copy(value):
        if value is selected: pytest.fail("retained selected rows after exceeded text-view bound")
        return original(value)
    monkeypatch.setattr(owner, "deepcopy", watch_copy)
    with pytest.raises(ValueError): owner.prepare_parent_text_views(selected, **args)


def test_complete_overlapping_occurrence_limit_refuses_without_selecting_first_match(tmp_path):
    report, selected, args = report_for(tmp_path, ["aaaa"])
    args["limits"] = {"max_occurrences": 2}
    report = owner.prepare_parent_text_views(selected, **args)
    with pytest.raises(ValueError):
        owner.exact_parent_text_occurrences(report, selected, expected_report_sha256=digest(report), row_ordinal=0, text="aa", **args)


def test_selector_byte_budget_refuses_full_repeated_population(tmp_path):
    report, selected, args = report_for(tmp_path, ["aaaa"])
    args["limits"] = {"max_observation_bytes": 1}
    report = owner.prepare_parent_text_views(selected, **args)
    with pytest.raises(ValueError):
        owner.exact_parent_text_occurrences(report, selected, expected_report_sha256=digest(report), row_ordinal=0, text="aa", **args)


@pytest.mark.parametrize("literal", ["", None, 123])
def test_exact_query_is_never_string_coerced_or_empty(tmp_path, literal):
    report, selected, args = report_for(tmp_path)
    with pytest.raises(ValueError):
        owner.exact_parent_text_occurrences(report, selected, expected_report_sha256=digest(report), row_ordinal=0, text=literal, **args)
