"""Independent source fixtures cannot turn literal alignment into legal binding."""
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_parent_parquet_pages as pages
from ipfs_datasets_py.logic.autoformal import legal_parent_text_views as parents
from ipfs_datasets_py.logic.autoformal import legal_official_document_views as official
from ipfs_datasets_py.logic.autoformal import legal_source_view_inventory as document_pins
from ipfs_datasets_py.logic.autoformal import legal_parent_source_alignment as owner


def wire(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(x): return hashlib.sha256(wire(x)).hexdigest()


class RenderOracle(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.fragments = []
    def handle_data(self, text):
        if text.strip(): self.fragments.append(text.strip())


def document(section, body="Shared Café aaaa.", *, edition=2024):
    raw = (f'<html><head><meta charset="utf-8"><title>Metadata {section}</title></head><body>'
        f'<h3 class="section-head">§{section}. Heading</h3><!-- field-start:statute -->'
        f'<p>{body}</p><!-- field-end:statute --><!-- field-start:notes -->'
        '<h4 class="notes-head">Historical and Revision Notes</h4><p>Shared Café.</p>'
        '<!-- field-end:notes --></body></html>').encode()
    package = f"USCODE-{edition}-title10"; granule = package + "-sec" + str(section)
    url = f"https://www.govinfo.gov/content/pkg/{package}/html/{granule}.htm"
    descriptor = {"schema": "legal-official-source-acquisition/v1", "legal_id": "usc:us:10:" + str(section),
        "url": url, "edition": edition, "package_id": package, "granule_id": granule,
        "retrieved_at": "2026-10-14T00:00:00+00:00", "raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_bytes": len(raw),
        "http_provenance": {"requested_url": url, "final_url": url, "status_code": 200,
            "content_type": "text/html", "etag": None, "last_modified": None}}
    trusted = {"descriptor": descriptor, "expected_descriptor_sha256": digest(descriptor),
        "expected_raw_sha256": descriptor["raw_sha256"], "expected_raw_bytes": len(raw)}
    report = official.prepare_official_document_view(raw, **trusted)
    assert report["status"] == "comparison_view_extracted"
    return {**trusted, "raw_bytes": raw, "view_report": report, "expected_view_report_sha256": digest(report)}


def fixture(tmp_path, texts=None, docs=None):
    docs = [document(1), document(2)] if docs is None else docs
    if texts is None:
        texts = []
        for item in docs[:2]:
            oracle = RenderOracle(); oracle.feed(item["raw_bytes"].decode()); oracle.close()
            texts.append(" ".join(oracle.fragments))
    rows = [{"ipfs_cid": "cid:" + str(i), "title_number": "10", "section_number": str(i + 1), "text": text,
        "law_name": "Heading", "source_url": docs[i % len(docs)]["descriptor"]["url"], "edition": "2024",
        "source_checksum": "declared-opaque-legacy-value", "subsections_json": '{"(a)":"unreviewed notes"}',
        **{"unknown_" + str(j): "retain:" + str(j) for j in range(36)}} for i, text in enumerate(texts)]
    schema = pa.schema([(key, pa.string()) for key in rows[0]])
    path = tmp_path / "parent.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="snappy", data_page_version="1.0")
    descriptor = {"repository": "fixture/parent", "revision": "a" * 40, "path_in_repo": path.name,
        "local_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
        "row_count": len(rows), "profile": pages.PARENT_PROFILE}
    preflight = pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=digest(descriptor))
    ordinals = list(range(len(rows))); row_hashes = [digest(row) for row in rows]
    selected = pages.read_selected_parent_rows(descriptor, expected_descriptor_sha256=digest(descriptor),
        preflight_report=preflight, expected_preflight_sha256=digest(preflight), row_ordinals=ordinals, expected_row_sha256s=row_hashes)
    replay = {"expected_selected_rows_report_sha256": digest(selected), "parent_descriptor": descriptor,
        "expected_parent_descriptor_sha256": digest(descriptor), "preflight_report": preflight,
        "expected_preflight_sha256": digest(preflight), "row_ordinals": ordinals, "expected_row_sha256s": row_hashes}
    parent = parents.prepare_parent_text_views(selected, **replay)
    return parent, {"expected_parent_text_views_report_sha256": digest(parent), "parent_text_views_inputs": replay,
        "document_inputs": docs, "expected_document_population_sha256": document_pins.view_document_population_sha256(docs)}


def materialize(tmp_path, texts=None, docs=None):
    parent, args = fixture(tmp_path, texts, docs)
    return owner.prepare_parent_source_alignment(parent, **args), parent, args


def assert_partition(parts, text, anchors, dimension):
    assert parts[0]["char_start"] == 0 and parts[-1]["char_end"] == len(text)
    assert "".join(text[p["char_start"]:p["char_end"]] for p in parts) == text
    for a, b in zip(parts, parts[1:]): assert a["char_end"] == b["char_start"]
    for part in parts:
        lo, hi = part["char_start"], part["char_end"]
        assert part["utf8_byte_start"] == len(text[:lo].encode()) and part["utf8_byte_end"] == len(text[:hi].encode())
        assert part["text_sha256"] == hashlib.sha256(text[lo:hi].encode()).hexdigest()
        key = "parent_selector" if dimension == "parent_literal_field" else "official_selector"
        expected = sorted(a["alignment_id"] for a in anchors if a[key]["char_start"] <= lo and hi <= a[key]["char_end"])
        assert part["alignment_ids"] == expected and part["coordinate_space"] == dimension
        assert part["legal_role_verified"] is False


def test_all_pairs_and_both_entire_coordinate_spaces_are_lossless_and_unselected(tmp_path):
    report, parent, args = materialize(tmp_path)
    assert report["row_count"] == report["document_count"] == 2 and report["comparison_count"] == 4
    assert report["parent_text_views_report"] == parent
    for number, row in enumerate(report["rows"]):
        text = parent["views"][number]["text_view"]["text"]
        assert [c["document_index"] for c in row["comparisons"]] == [0, 1]
        for comparison in row["comparisons"]:
            doc = report["official_documents"][comparison["document_index"]]["view_report"]["document"]
            anchors = comparison["exact_block_alignments"]
            assert anchors and all(flag is False for a in anchors for flag in a["authority"].values())
            assert_partition(comparison["parent_partition"], text, anchors, "parent_literal_field")
            assert_partition(comparison["official_partition"], doc["document_text"], anchors, "official_normalized_view")
            assert any(doc["document_text"][p["char_start"]:p["char_end"]] == "\n" and not p["alignment_ids"] for p in comparison["official_partition"])
    assert all(flag is False for flag in report["authority"].values())
    assert digest(report) == owner.parent_source_alignment_report_sha256(report)
    assert owner.validate_parent_source_alignment(report, parent, expected_report_sha256=digest(report), **args)["valid"]


def test_wrong_URL_and_legal_id_never_filter_shared_literal_block_candidates(tmp_path):
    report, _, _ = materialize(tmp_path)
    foreign = report["rows"][0]["comparisons"][1]
    assert foreign["association_observations"]["source_url_exact_match"] is False
    assert foreign["association_observations"]["literal_legal_id_exact_match"] is False
    assert any(a["parent_selector"]["text"] == "Shared Café." for a in foreign["exact_block_alignments"])
    assert foreign["association_observations"]["source_correspondence_verified"] is False


def test_all_overlapping_block_matches_are_distinct_with_exact_Unicode_byte_geometry(tmp_path):
    docs = [document(1, "aaaa")]
    text = "雪 Café aaaaa"
    report, _, _ = materialize(tmp_path, [text], docs)
    anchors = [a for a in report["rows"][0]["comparisons"][0]["exact_block_alignments"] if a["parent_selector"]["text"] == "aaaa"]
    assert [(a["parent_selector"]["char_start"], a["parent_selector"]["char_end"]) for a in anchors] == [(7,11),(8,12)]
    assert len({a["alignment_id"] for a in anchors}) == 2
    for a in anchors:
        selector = a["parent_selector"]
        assert selector["utf8byte_start"] == len(text[:selector["char_start"]].encode())
        assert a["official_selector"]["schema"] != selector["schema"]
        assert a["official_selector"]["text"] == selector["text"]


def test_exact_whole_render_observation_is_not_source_legal_role_or_byte_mapping_admission(tmp_path):
    report, _, _ = materialize(tmp_path)
    for index, row in enumerate(report["rows"]):
        comparison = row["comparisons"][index]
        assert comparison["exact_rendered_field_equal"] is True
        rendered = report["official_documents"][index]["rendered_field_view"]
        assert rendered["profile"] == owner.RENDER_PROFILE
        assert rendered["text_sha256"] == comparison["rendered_field_comparison"]["parent_text_sha256"]
        assert all(flag is False for flag in rendered["authority"].values())
        assert rendered["historical_producer_operation_verified"] is False and rendered["CSS_rendering_verified"] is False
        assert comparison["rendered_field_comparison"]["raw_HTML_coordinate_mapping_verified"] is False
        assert comparison["rendered_field_comparison"]["original_source_correspondence_verified"] is False


def test_data_event_render_preserves_internal_whitespace_and_NBSP_without_v2_coordinate_conversion(tmp_path):
    docs = [document(1, "a  b\u00a0c")]
    oracle = RenderOracle(); oracle.feed(docs[0]["raw_bytes"].decode()); oracle.close()
    original = " ".join(oracle.fragments)
    report, _, _ = materialize(tmp_path, [original], docs)
    rendered = report["official_documents"][0]["rendered_field_view"]
    assert "a  b\u00a0c" in rendered["text"] and rendered["text"] == original
    comparison = report["rows"][0]["comparisons"][0]
    assert comparison["exact_rendered_field_equal"] is True
    assert not any(a["parent_selector"]["text"] == "a b c" for a in comparison["exact_block_alignments"])
    assert rendered["coordinate_origin"]["official_normalized_view_coordinate_equivalence_verified"] is False
    for fragment in rendered["fragments"]:
        text = rendered["text"][fragment["char_start"]:fragment["char_end"]]
        assert hashlib.sha256(text.encode()).hexdigest() == fragment["text_sha256"]
        assert len(rendered["text"][:fragment["char_start"]].encode()) == fragment["utf8_byte_start"]


def test_edition_string_and_opaque_checksum_are_preserved_without_alias_coercion(tmp_path):
    report, _, _ = materialize(tmp_path)
    observations = report["rows"][0]["comparisons"][0]["association_observations"]
    assert observations["parent_edition_observation"]["value"] == "2024"
    assert observations["explicit_edition_exact_match"] is False
    assert observations["parent_source_checksum_observation"]["value"] == "declared-opaque-legacy-value"
    assert observations["declared_checksum_matches_raw_HTML"] is False


def test_duplicate_parent_strings_remain_distinct_physical_alignment_populations(tmp_path):
    report, _, _ = materialize(tmp_path, ["Shared Café.", "Shared Café."])
    a = report["rows"][0]["comparisons"][0]["exact_block_alignments"][0]
    b = report["rows"][1]["comparisons"][0]["exact_block_alignments"][0]
    assert a["parent_selector"]["text_sha256"] == b["parent_selector"]["text_sha256"]
    assert a["alignment_id"] != b["alignment_id"]


def test_large_official_view_does_not_borrow_smaller_parent_character_cap(tmp_path):
    body = "</p><p>".join(["q" * 200] * 400)
    docs = [document(1, body)]
    report, _, _ = materialize(tmp_path, ["Short unmatched parent field."], docs)
    official_text = report["official_documents"][0]["view_report"]["document"]["document_text"]
    assert len(official_text) > 65536 and report["comparison_count"] == 1


@pytest.mark.parametrize("missing", ["parent", "official"])
def test_unavailable_views_preserve_complete_pair_denominator_and_named_unknowns(tmp_path, missing):
    docs = [document(1)]
    texts = [None] if missing == "parent" else ["Parent preserved."]
    if missing == "official":
        item = docs[0]; item["raw_bytes"] = None
        item["view_report"] = official.prepare_official_document_view(None, **{k:item[k] for k in
            ("descriptor","expected_descriptor_sha256","expected_raw_sha256","expected_raw_bytes")})
        item["expected_view_report_sha256"] = digest(item["view_report"])
    report, _, _ = materialize(tmp_path, texts, docs)
    comparison = report["rows"][0]["comparisons"][0]
    assert report["comparison_count"] == 1 and comparison["exact_block_alignments"] == []
    assert comparison["exact_rendered_field_equal"] is None
    assert any(i["code"].endswith("view_unavailable") for i in comparison["issues"])
    assert bool(comparison["official_partition"]) == (missing == "parent")
    assert bool(comparison["parent_partition"]) == (missing == "official")


@pytest.mark.parametrize("damage", ["parent_full_pin","document_population","raw_hash","raw_bytes","descriptor","view_pin","order","missing","extra"])
def test_independent_complete_source_populations_and_raw_FULL_pins_are_required(tmp_path, damage):
    parent, args = fixture(tmp_path)
    docs = args["document_inputs"]
    if damage == "parent_full_pin": args["expected_parent_text_views_report_sha256"] = "0" * 64
    elif damage == "document_population": args["expected_document_population_sha256"] = "0" * 64
    elif damage == "raw_hash": docs[0]["expected_raw_sha256"] = "0" * 64
    elif damage == "raw_bytes": docs[0]["raw_bytes"] += b"changed"
    elif damage == "descriptor": docs[0]["expected_descriptor_sha256"] = "0" * 64
    elif damage == "view_pin": docs[0]["expected_view_report_sha256"] = "0" * 64
    elif damage == "order": docs.reverse()
    elif damage == "missing": docs.pop()
    else: docs.append(deepcopy(docs[0]))
    with pytest.raises(ValueError): owner.prepare_parent_source_alignment(parent, **args)


def test_rehashed_official_view_cannot_replace_fixed_original_HTML_regeneration(tmp_path):
    parent, args = fixture(tmp_path)
    item = args["document_inputs"][0]
    item["view_report"]["document"]["blocks"][0]["region_kind"] = "statute"
    item["expected_view_report_sha256"] = digest(item["view_report"])
    args["expected_document_population_sha256"] = document_pins.view_document_population_sha256(args["document_inputs"])
    with pytest.raises(ValueError): owner.prepare_parent_source_alignment(parent, **args)


@pytest.mark.parametrize("damage", ["omit_row","omit_doc","omit_anchor","parent_geometry","official_geometry","partition","partition_links",
    "render_text","render_seal","source_association","authority","seal"])
def test_self_resealed_alignment_cannot_forge_coverage_rendering_or_authority(tmp_path, damage):
    report, parent, args = materialize(tmp_path); original = digest(report)
    comparison = report["rows"][0]["comparisons"][0]
    if damage == "omit_row": report["rows"].pop()
    elif damage == "omit_doc": report["official_documents"].pop()
    elif damage == "omit_anchor": comparison["exact_block_alignments"].pop()
    elif damage == "parent_geometry": comparison["exact_block_alignments"][0]["parent_selector"]["char_start"] += 1
    elif damage == "official_geometry": comparison["exact_block_alignments"][0]["official_selector"]["utf8_byte_end"] += 1
    elif damage == "partition": comparison["official_partition"].pop()
    elif damage == "partition_links": comparison["parent_partition"][0]["alignment_ids"] = ["forged"]
    elif damage == "render_text": report["official_documents"][0]["rendered_field_view"]["text"] += "forged"
    elif damage == "render_seal": report["official_documents"][0]["rendered_field_view"]["rendered_field_sha256"] = "0" * 64
    elif damage == "source_association": comparison["association_observations"]["source_correspondence_verified"] = True
    elif damage == "authority": comparison["authority"]["training_qualified"] = True
    else: report["source_alignment_sha256"] = "0" * 64
    with pytest.raises(ValueError): owner.validate_parent_source_alignment(report, parent, expected_report_sha256=original, **args)
    with pytest.raises(ValueError): owner.validate_parent_source_alignment(report, parent, expected_report_sha256=digest(report), **args)


@pytest.mark.parametrize("bound", ["max_parent_views","max_documents","max_parent_characters","max_total_parent_characters",
    "max_official_characters","max_total_official_characters","max_total_raw_HTML_bytes","max_total_input_report_bytes",
    "max_blocks","max_block_bytes","max_alignments","max_partition_pieces","max_observation_bytes","max_report_bytes",
    "max_render_events","max_render_event_bytes","max_rendered_field_bytes","max_total_rendered_field_bytes"])
def test_lowered_complete_population_bounds_refuse_without_truncating_or_selecting_easy_sources(tmp_path, bound):
    parent, args = fixture(tmp_path); args["limits"] = {bound:1}
    with pytest.raises(ValueError): owner.prepare_parent_source_alignment(parent, **args)


def test_render_event_count_is_global_and_stops_before_excess_retention(tmp_path, monkeypatch):
    parent, args = fixture(tmp_path); args["limits"] = {"max_render_events":1}
    original = owner._charge; calls = []
    def observe(value, budget, bounds):
        if "event_index" in value and "data_sha256" in value: calls.append(value["event_index"])
        return original(value,budget,bounds)
    monkeypatch.setattr(owner,"_charge",observe)
    with pytest.raises(ValueError): owner.prepare_parent_source_alignment(parent, **args)
    assert calls == [0]


def test_bad_limit_names_booleans_and_raised_bounds_never_weaken_profile(tmp_path):
    parent, args = fixture(tmp_path)
    for limits in ({"max_alignments":True},{"max_documents":11},{"ignore_missing_source":1}):
        with pytest.raises(ValueError): owner.prepare_parent_source_alignment(parent, **args,limits=limits)


@pytest.mark.parametrize("population", ["replay_bundle", "official_reports"])
def test_nested_aggregate_input_budget_precedes_any_parent_snapshot(tmp_path, population, monkeypatch):
    parent, args = fixture(tmp_path)
    parent_bytes = len(wire(parent)); replay_bytes = len(wire(args["parent_text_views_inputs"]))
    cap = parent_bytes + replay_bytes - 1 if population == "replay_bundle" else parent_bytes + replay_bytes + len(wire(args["document_inputs"][0]["view_report"])) - 1
    args["limits"] = {"max_total_input_report_bytes": cap}
    monkeypatch.setattr(owner, "_parent_snapshot", lambda *a: pytest.fail("copied parent before complete nested input preflight"))
    with pytest.raises(ValueError): owner.prepare_parent_source_alignment(parent, **args)
