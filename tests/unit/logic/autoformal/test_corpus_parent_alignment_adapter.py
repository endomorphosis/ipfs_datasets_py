"""Independent complete-source alignment custody remains candidate evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_parent_occurrence_adapter as base_owner
from ipfs_datasets_py.logic.autoformal import corpus_source
from ipfs_datasets_py.logic.autoformal import legal_official_document_views as official_owner
from ipfs_datasets_py.logic.autoformal import legal_parent_source_alignment as alignment_owner
from ipfs_datasets_py.logic.autoformal import legal_source_view_inventory as document_owner
from ipfs_datasets_py.utils.cid_utils import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def pretty(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False).encode()


def helper(filename, name):
    """Reuse authored fixtures; actual package owners perform every operation."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def document(section=1, body="aa"):
    return helper(
        "test_legal_parent_source_alignment.py", "authored_alignment_document_fixture"
    ).document(section, body)


def missing_document(section=1):
    item = document(section)
    item["raw_bytes"] = None
    item["view_report"] = official_owner.prepare_official_document_view(
        None,
        **{
            key: item[key]
            for key in (
                "descriptor",
                "expected_descriptor_sha256",
                "expected_raw_sha256",
                "expected_raw_bytes",
            )
        },
    )
    item["expected_view_report_sha256"] = sha(canonical(item["view_report"]))
    return item


def redocument(item, raw):
    """Retain the fixture acquisition shape and rebuild every independent pin."""
    item = deepcopy(item)
    item["raw_bytes"] = raw
    item["descriptor"]["raw_sha256"] = item["expected_raw_sha256"] = sha(raw)
    item["descriptor"]["raw_bytes"] = item["expected_raw_bytes"] = len(raw)
    item["expected_descriptor_sha256"] = sha(canonical(item["descriptor"]))
    item["view_report"] = official_owner.prepare_official_document_view(
        raw,
        **{
            key: item[key]
            for key in (
                "descriptor", "expected_descriptor_sha256", "expected_raw_sha256", "expected_raw_bytes"
            )
        },
    )
    assert item["view_report"]["status"] == "comparison_view_extracted"
    item["expected_view_report_sha256"] = sha(canonical(item["view_report"]))
    return item


def case(tmp_path, *, docs=None, **base_options):
    data = helper(
        "test_corpus_parent_occurrence_adapter.py", "authored_complete_base_corpus_fixture"
    ).case(tmp_path, **base_options)
    base = base_owner.build_parent_occurrence_corpus(**data["arguments"])
    docs = [document(1), document(2)] if docs is None else docs
    alignment_arguments = {
        "expected_parent_text_views_report_sha256": data["arguments"]["expected_report_pins"][
            "parent_text_views"
        ]["canonical_sha256"],
        "parent_text_views_inputs": data["arguments"]["replay_inputs"]["parent_text_views_inputs"],
        "document_inputs": docs,
        "expected_document_population_sha256": document_owner.view_document_population_sha256(docs),
    }
    report = alignment_owner.prepare_parent_source_alignment(
        data["reports"]["parent_text_views"], **alignment_arguments
    )
    base_bytes = {
        "manifest": pretty(base["manifest"]) + b"\n",
        "records": b"".join(canonical(record) + b"\n" for record in base["records"]),
    }
    raw_report = pretty(report) + b"\n"
    return {
        "base": base,
        "base_data": data,
        "alignment": report,
        "arguments": {
            "base_corpus_bytes": base_bytes,
            "expected_base_corpus_pins": {key: sha(raw) for key, raw in base_bytes.items()},
            "base_report_bytes": data["arguments"]["report_bytes"],
            "expected_base_report_pins": data["arguments"]["expected_report_pins"],
            "base_replay_inputs": data["arguments"]["replay_inputs"],
            "alignment_report_bytes": raw_report,
            "expected_alignment_report_pins": {
                "raw_sha256": sha(raw_report),
                "canonical_sha256": sha(canonical(report)),
            },
            "document_inputs": docs,
            "expected_document_population_sha256": alignment_arguments[
                "expected_document_population_sha256"
            ],
        },
    }


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_parent_alignment_adapter

    return corpus_parent_alignment_adapter


def build(owner, data, **options):
    return owner.build_parent_alignment_corpus(**data["arguments"], **options)


def validate(owner, bundle, data, **options):
    return owner.validate_parent_alignment_corpus(bundle, **data["arguments"], **options)


def reseal(record):
    return contracts.seal_record(
        {key: deepcopy(value) for key, value in record.items() if key not in {"cid_scope", "record_cid"}}
    )


def repin_alignment(data, mutate):
    report = json.loads(data["arguments"]["alignment_report_bytes"])
    mutate(report)
    report["source_alignment_sha256"] = sha(
        canonical({key: value for key, value in report.items() if key != "source_alignment_sha256"})
    )
    raw = pretty(report) + b"\n"
    data["arguments"]["alignment_report_bytes"] = raw
    data["arguments"]["expected_alignment_report_pins"] = {
        "raw_sha256": sha(raw), "canonical_sha256": sha(canonical(report))
    }


def repin_base_manifest(data, mutate):
    manifest = json.loads(data["arguments"]["base_corpus_bytes"]["manifest"])
    mutate(manifest)
    manifest = reseal(manifest)
    raw = pretty(manifest) + b"\n"
    data["arguments"]["base_corpus_bytes"]["manifest"] = raw
    data["arguments"]["expected_base_corpus_pins"]["manifest"] = sha(raw)


def entries(bundle):
    return [entry for page in bundle["pages"] for entry in page["entries"]]


def records_of_kind(bundle, kind):
    record_map = {record["record_cid"]: record for record in bundle["records"]}
    return [record_map[entry["record_cid"]] for entry in entries(bundle) if entry["kind"] == kind]


def original_value(data, record):
    value = data["alignment"]
    for component in record["external_binding"]["json_pointer"].split("/")[1:]:
        component = component.replace("~1", "/").replace("~0", "~")
        value = value[int(component)] if type(value) is list else value[component]
    return value


def assert_inventory(bundle):
    assert set(bundle) == {"manifest", "pages", "records"}
    inventory = entries(bundle)
    assert [row["ordinal"] for row in inventory] == list(range(len(bundle["records"])))
    assert [row["record_cid"] for row in inventory] == [row["record_cid"] for row in bundle["records"]]
    assert len({row["record_cid"] for row in bundle["records"]}) == len(bundle["records"])
    assert len(bundle["pages"]) == len(bundle["manifest"]["page_refs"])
    for record, entry in zip(bundle["records"], inventory, strict=True):
        assert set(entry) == {"ordinal", "record_cid", "sha256", "kind"}
        assert entry["sha256"] == sha(canonical_dag_json_bytes(record))
        assert reseal(record) == record
        assert len(canonical_dag_json_bytes(record)) <= contracts.MAX_RECORD_BYTES
    first = 0
    for ordinal, (page, reference) in enumerate(
        zip(bundle["pages"], bundle["manifest"]["page_refs"], strict=True)
    ):
        assert page["schema"] == "legal-corpus-parent-alignment-page/v1"
        assert page["page_ordinal"] == reference["page_ordinal"] == ordinal
        assert page["first_record_ordinal"] == reference["first_record_ordinal"] == first
        assert reference["page_cid"] == page["record_cid"]
        assert reference["sha256"] == sha(canonical_dag_json_bytes(page))
        assert reference["record_count"] == len(page["entries"])
        assert reference["first_record_cid"] == page["entries"][0]["record_cid"]
        assert reference["last_record_cid"] == page["entries"][-1]["record_cid"]
        assert reseal(page) == page and len(canonical_dag_json_bytes(page)) <= contracts.MAX_RECORD_BYTES
        first += len(page["entries"])
    assert reseal(bundle["manifest"]) == bundle["manifest"]
    assert len(canonical_dag_json_bytes(bundle["manifest"])) <= contracts.MAX_RECORD_BYTES


def assert_projection_counts(bundle, data):
    report = data["alignment"]
    expected = {
        "document": len(report["official_documents"]),
        "comparison": sum(len(row["comparisons"]) for row in report["rows"]),
        "alignment": report["alignment_count"],
        "block": sum(
            len(item["view_report"]["document"]["blocks"])
            for item in report["official_documents"]
            if item["view_report"]["document"] is not None
        ),
        "parent_partition": sum(
            len(c["parent_partition"]) for row in report["rows"] for c in row["comparisons"]
        ),
        "official_partition": sum(
            len(c["official_partition"]) for row in report["rows"] for c in row["comparisons"]
        ),
        "render_event": report["render_data_event_count"],
        "render_fragment": sum(
            len(item["rendered_field_view"]["fragments"])
            for item in report["official_documents"]
            if item["rendered_field_view"] is not None
        ),
        "render_gap": sum(
            max(0, len(item["rendered_field_view"]["fragments"]) - 1)
            for item in report["official_documents"]
            if item["rendered_field_view"] is not None
        ),
    }
    counts = Counter(row["kind"] for row in entries(bundle))
    for kind, count in expected.items():
        assert counts[kind] == count
    assert_inventory(bundle)


def test_complete_detached_population_replays_both_original_source_owners(owner, tmp_path):
    data = case(tmp_path)
    before = canonical(data["base"])
    bundle = build(owner, data)
    assert_projection_counts(bundle, data)
    assert validate(owner, bundle, data) == bundle
    assert canonical(data["base"]) == before
    assert not {r["record_cid"] for r in data["base"]["records"]} & {
        r["record_cid"] for r in bundle["records"]
    }


def test_raw_and_FULL_alignment_digests_bind_distinct_original_bytes(owner, tmp_path):
    data = case(tmp_path)
    pins = data["arguments"]["expected_alignment_report_pins"]
    assert pins["raw_sha256"] != pins["canonical_sha256"]
    assert pins["canonical_sha256"] != data["alignment"]["source_alignment_sha256"]
    bundle = build(owner, data)
    for record in bundle["records"]:
        if "external_binding" not in record:
            continue
        bound = record["external_binding"]
        assert bound["value_sha256"] == sha(canonical(original_value(data, record)))
        assert bound["report_raw_sha256"] == pins["raw_sha256"]
        assert bound["report_canonical_sha256"] == pins["canonical_sha256"]
        assert bound["report_raw_cid"] == cid_for_bytes(data["arguments"]["alignment_report_bytes"])


def test_reformatted_original_report_changes_custody_while_retaining_literal_population(owner, tmp_path):
    data = case(tmp_path)
    original_bundle = build(owner, data)
    canonical_sha = data["arguments"]["expected_alignment_report_pins"]["canonical_sha256"]
    raw = canonical(data["alignment"])
    data["arguments"]["alignment_report_bytes"] = raw
    data["arguments"]["expected_alignment_report_pins"]["raw_sha256"] = sha(raw)
    assert data["arguments"]["expected_alignment_report_pins"]["canonical_sha256"] == canonical_sha
    second = build(owner, data)
    assert_projection_counts(second, data)
    assert second["manifest"]["record_cid"] != original_bundle["manifest"]["record_cid"]
    assert validate(owner, second, data) == second
    with pytest.raises(ValueError):
        validate(owner, original_bundle, data)


@pytest.mark.parametrize("pin", ["raw_sha256", "canonical_sha256"])
def test_alignment_requires_independent_raw_and_FULL_pins(owner, tmp_path, pin, monkeypatch):
    data = case(tmp_path)
    data["arguments"]["expected_alignment_report_pins"][pin] = "0" * 64
    if pin == "raw_sha256":
        monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("owners reached before raw pin refusal"))
    with pytest.raises(ValueError):
        build(owner, data)


@pytest.mark.parametrize("part", ["manifest", "records"])
def test_each_base_raw_component_is_independently_pinned_before_replay(
    owner, tmp_path, part, monkeypatch
):
    data = case(tmp_path)
    data["arguments"]["expected_base_corpus_pins"][part] = "0" * 64
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("owners reached before base raw pin refusal"))
    with pytest.raises(ValueError):
        build(owner, data)


@pytest.mark.parametrize(
    "damage",
    ["missing_base", "extra_base", "missing_base_pin", "extra_base_pin", "buffer", "empty_records",
     "missing_alignment_pin", "extra_alignment_pin", "missing_base_report", "extra_base_report",
     "missing_replay", "extra_replay", "loader_callback", "document_callback"],
)
def test_closed_inputs_preserve_original_full_populations_and_refuse_custom_intake(
    owner, tmp_path, damage
):
    data = case(tmp_path)
    args = data["arguments"]
    if damage == "missing_base":
        args["base_corpus_bytes"].pop("records")
    elif damage == "extra_base":
        args["base_corpus_bytes"]["selected_records"] = b"[]"
    elif damage == "missing_base_pin":
        args["expected_base_corpus_pins"].pop("records")
    elif damage == "extra_base_pin":
        args["expected_base_corpus_pins"]["verified"] = True
    elif damage == "buffer":
        args["alignment_report_bytes"] = bytearray(args["alignment_report_bytes"])
    elif damage == "empty_records":
        args["base_corpus_bytes"]["records"] = b""
        args["expected_base_corpus_pins"]["records"] = sha(b"")
    elif damage == "missing_alignment_pin":
        args["expected_alignment_report_pins"].pop("canonical_sha256")
    elif damage == "extra_alignment_pin":
        args["expected_alignment_report_pins"]["source_verified"] = True
    elif damage == "missing_base_report":
        args["base_report_bytes"].pop("parent_sentence_candidates")
    elif damage == "extra_base_report":
        args["base_report_bytes"]["selected_gold"] = b"{}"
    elif damage == "missing_replay":
        args["base_replay_inputs"].pop("expected_lineage_report_sha256")
    elif damage == "document_callback":
        args["document_inputs"][0]["loader"] = lambda: pytest.fail("custom loader ran")
    else:
        args["base_replay_inputs"]["loader" if damage == "loader_callback" else "reviewed"] = (
            lambda: pytest.fail("custom loader ran")
        ) if damage == "loader_callback" else True
    with pytest.raises(ValueError):
        build(owner, data)


@pytest.mark.parametrize("target", ["alignment", "base_manifest", "base_record"])
def test_duplicate_JSON_keys_refused_even_after_exact_raw_repin(owner, tmp_path, target):
    data = case(tmp_path)
    args = data["arguments"]
    if target == "alignment":
        raw = args["alignment_report_bytes"]
        raw = b'{"schema":"forged",' + raw.lstrip()[1:]
        args["alignment_report_bytes"] = raw
        args["expected_alignment_report_pins"]["raw_sha256"] = sha(raw)
    elif target == "base_manifest":
        raw = b'{"schema":"forged",' + args["base_corpus_bytes"]["manifest"].lstrip()[1:]
        args["base_corpus_bytes"]["manifest"] = raw
        args["expected_base_corpus_pins"]["manifest"] = sha(raw)
    else:
        lines = args["base_corpus_bytes"]["records"].splitlines()
        lines[0] = b'{"schema":"forged",' + lines[0][1:]
        raw = b"\n".join(lines) + b"\n"
        args["base_corpus_bytes"]["records"] = raw
        args["expected_base_corpus_pins"]["records"] = sha(raw)
    with pytest.raises(ValueError):
        build(owner, data)


@pytest.mark.parametrize("damage", ["subset", "order", "duplicate", "manifest_authority", "record_geometry"])
def test_repaired_base_custody_cannot_replace_complete_original_corpus_replay(owner, tmp_path, damage):
    data = case(tmp_path)
    if damage == "manifest_authority":
        repin_base_manifest(data, lambda m: m.__setitem__("admitted", True))
    else:
        records = [json.loads(line) for line in data["arguments"]["base_corpus_bytes"]["records"].splitlines()]
        if damage == "subset":
            records.pop()
        elif damage == "order":
            records.reverse()
        elif damage == "duplicate":
            records.append(deepcopy(records[0]))
        else:
            index = next(i for i, r in enumerate(records) if r["schema"] == corpus_source.SOURCE_OCCURRENCE_SCHEMA)
            records[index]["start_utf8"] += 1
            records[index] = reseal(records[index])
        raw = b"".join(canonical(record) + b"\n" for record in records)
        data["arguments"]["base_corpus_bytes"]["records"] = raw
        data["arguments"]["expected_base_corpus_pins"]["records"] = sha(raw)
    with pytest.raises(ValueError):
        build(owner, data)


@pytest.mark.parametrize(
    "damage",
    ["row_subset", "document_subset", "anchor_subset", "parent_geometry", "official_geometry",
     "selector_coercion", "partition_links", "render_text", "render_events", "authority"],
)
def test_repaired_alignment_outer_hash_and_self_seal_cannot_replace_source_regeneration(
    owner, tmp_path, damage
):
    data = case(tmp_path)
    def mutate(report):
        comparison = report["rows"][0]["comparisons"][0]
        anchor = comparison["exact_block_alignments"][0]
        if damage == "row_subset":
            report["rows"].pop()
        elif damage == "document_subset":
            report["official_documents"].pop()
        elif damage == "anchor_subset":
            comparison["exact_block_alignments"].pop()
        elif damage == "parent_geometry":
            anchor["parent_selector"]["utf8byte_start"] += 1
        elif damage == "official_geometry":
            anchor["official_selector"]["char_end"] += 1
        elif damage == "selector_coercion":
            anchor["official_selector"]["schema"] = "legal-statutory-occurrence-selector/v2"
        elif damage == "partition_links":
            comparison["parent_partition"][0]["alignment_ids"] = ["invented"]
        elif damage == "render_text":
            report["official_documents"][0]["rendered_field_view"]["text"] += "forged"
        elif damage == "render_events":
            report["official_documents"][0]["rendered_field_view"]["events"].pop()
        else:
            comparison["association_observations"]["source_correspondence_verified"] = True
    repin_alignment(data, mutate)
    with pytest.raises(ValueError):
        build(owner, data)


@pytest.mark.parametrize(
    "damage", ["population_pin", "order", "missing", "extra", "raw_hash", "raw_bytes", "view_pin", "descriptor_pin"]
)
def test_complete_official_document_population_and_original_sources_are_required(owner, tmp_path, damage):
    data = case(tmp_path)
    args = data["arguments"]
    docs = args["document_inputs"]
    if damage == "population_pin":
        args["expected_document_population_sha256"] = "0" * 64
    elif damage == "order":
        docs.reverse()
    elif damage == "missing":
        docs.pop()
    elif damage == "extra":
        docs.append(deepcopy(docs[0]))
    elif damage == "raw_hash":
        docs[0]["expected_raw_sha256"] = "0" * 64
    elif damage == "raw_bytes":
        docs[0]["raw_bytes"] += b"changed"
    elif damage == "view_pin":
        docs[0]["expected_view_report_sha256"] = "0" * 64
    else:
        docs[0]["expected_descriptor_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        build(owner, data)


@pytest.mark.parametrize("missing", ["parent", "official", "zero_match", "zero_documents"])
def test_zero_and_unavailable_cells_remain_in_complete_declared_population(owner, tmp_path, missing):
    options = {}
    docs = [document(1)]
    if missing == "parent":
        options["parent_texts"] = [None, "aa"]
    elif missing == "official":
        docs = [missing_document()]
    elif missing == "zero_match":
        options["parent_texts"] = ["雪 unrelated field.", "Different original text."]
    else:
        docs = []
    data = case(tmp_path, docs=docs, **options)
    bundle = build(owner, data)
    assert_projection_counts(bundle, data)
    assert len(records_of_kind(bundle, "comparison")) == len(data["alignment"]["rows"]) * len(docs)
    assert len(records_of_kind(bundle, "alignment")) == data["alignment"]["alignment_count"]
    assert validate(owner, bundle, data) == bundle


def test_literal_Unicode_and_duplicate_physical_rows_do_not_merge_source_coordinates(owner, tmp_path):
    data = case(
        tmp_path,
        docs=[document(1, "é"), document(2, "aaaa")],
        source_text="é",
        parent_texts=["雪 é e\u0301 é aaaaa. ", "雪 é e\u0301 é aaaaa. "],
    )
    bundle = build(owner, data)
    assert_projection_counts(bundle, data)
    alignments = records_of_kind(bundle, "alignment")
    assert len(alignments) == data["alignment"]["alignment_count"]
    official_schemas = set()
    parent_identities = set()
    overlap_starts = []
    for record in alignments:
        value = original_value(data, record)
        parent, official = value["parent_selector"], value["official_selector"]
        official_schemas.add(official["schema"])
        parent_identities.add(sha(canonical(parent["source_identity"])))
        text = data["alignment"]["parent_text_views_report"]["views"][record["parent_index"]]["text_view"]["text"]
        assert text[parent["char_start"]:parent["char_end"]] == parent["text"] == official["text"]
        assert text.encode()[parent["utf8byte_start"]:parent["utf8byte_end"]].decode() == parent["text"]
        assert parent["text"] != "e\u0301"
        if parent["text"] == "aaaa" and record["parent_index"] == 0:
            overlap_starts.append(parent["char_start"])
    assert official_schemas == {"legal-official-markup-occurrence-selector/v2"}
    assert len(parent_identities) == 2
    assert sorted(overlap_starts) == [9, 10]


def test_all_new_core_origins_have_exact_source_bytes_and_half_open_geometry(owner, tmp_path):
    data = case(tmp_path, docs=[document(1, "aaaa"), document(2, "aa")])
    bundle = build(owner, data)
    assert_projection_counts(bundle, data)
    records = {record["record_cid"]: record for record in [*data["base"]["records"], *bundle["records"]]}
    texts = {}
    parent_cids = data["base"]["manifest"]["populations"]["parents"]
    for parent_cid, view in zip(parent_cids, data["alignment"]["parent_text_views_report"]["views"], strict=True):
        texts[records[parent_cid]["source_version_cid"]] = view["text_view"]["text"]
    for record in records_of_kind(bundle, "document"):
        index = record["document_index"]
        item = data["alignment"]["official_documents"][index]
        for role, text in (
            ("normalized_source_version_cid", item["view_report"]["document"]["document_text"]),
            ("rendered_source_version_cid", item["rendered_field_view"]["text"]),
        ):
            version_cid = record["related_records"][role]
            version = records[version_cid]
            texts[version_cid] = text
            assert version["raw_artifact"]["sha256"] == data["arguments"]["document_inputs"][index]["expected_raw_sha256"]
            assert version["raw_artifact"]["cid"] == cid_for_bytes(data["arguments"]["document_inputs"][index]["raw_bytes"])
            assert version["raw_artifact"]["media_type"] == "text/html"
            assert version["extracted_view"]["sha256"] == sha(text.encode())
            assert version["historical_aliases"] == []
    for occurrence in records_of_kind(bundle, "source_occurrence"):
        text = texts[occurrence["source_version_cid"]]
        lo, hi = occurrence["start_char"], occurrence["end_char"]
        assert text[lo:hi] == occurrence["span_text"]
        assert sha(text[lo:hi].encode()) == occurrence["span_sha256"]
        assert occurrence["start_utf8"] == len(text[:lo].encode())
        assert occurrence["end_utf8"] == len(text[:hi].encode())
        assert occurrence["historical_aliases"] == []
    for record in bundle["records"]:
        if "context_cid" not in record or record["source_occurrence_cid"] is None:
            continue
        occurrence = records[record["source_occurrence_cid"]]
        context = records[record["context_cid"]]
        assert record["source_version_cid"] == occurrence["source_version_cid"]
        assert context["source_occurrence_cid"] == occurrence["record_cid"]
        assert context["availability"] == "required_unavailable"
    for filename in ("legal_parent_source_alignment.py", "legal_official_document_views.py", "legal_statutory_context.py", "legal_span_section_bridge.py"):
        path = Path(alignment_owner.__file__).with_name(filename).resolve()
        assert bundle["manifest"]["producer_pins"][str(path)] == sha(path.read_bytes())


def test_anchor_reuse_classification_binds_original_base_before_new_ranges_exist(owner, tmp_path):
    data = case(tmp_path, docs=[document(1, "aaaa"), document(2, "aa")])
    bundle = build(owner, data)
    baseline = {record["record_cid"]: record for record in data["base"]["records"]}
    original_geometry = {
        tuple(record[key] for key in ("source_version_cid", "start_char", "end_char", "start_utf8", "end_utf8")): record
        for record in baseline.values() if record["schema"] == corpus_source.SOURCE_OCCURRENCE_SCHEMA
    }
    original_contexts = {record["source_occurrence_cid"]: record for record in baseline.values() if record["schema"] == corpus_source.CONTEXT_DECLARATION_SCHEMA}
    classified = Counter()
    distinct = {True: set(), False: set()}
    for record in records_of_kind(bundle, "alignment"):
        selector = original_value(data, record)["parent_selector"]
        key = (record["source_version_cid"], selector["char_start"], selector["char_end"], selector["utf8byte_start"], selector["utf8byte_end"])
        existing = original_geometry.get(key)
        present = existing is not None
        assert record["observations"]["parent_geometry_present_in_original_base"] is present
        classified[present] += 1
        distinct[present].add(key)
        if existing is not None:
            assert record["source_occurrence_cid"] == existing["record_cid"]
            assert record["context_cid"] == original_contexts[existing["record_cid"]]["record_cid"]
        else:
            assert record["source_occurrence_cid"] not in baseline
    assert classified[True] and classified[False]
    counts = bundle["manifest"]["counts"]
    assert counts["parent_anchor_observations_reusing_base"] == classified[True]
    assert counts["parent_anchor_observations_missing_in_base"] == classified[False]
    assert counts["distinct_parent_anchor_geometries_reusing_base"] == len(distinct[True])
    assert counts["distinct_parent_anchor_geometries_missing_in_base"] == len(distinct[False])


def test_equal_normalized_and_rendered_body_literals_keep_distinct_profile_identities(owner, tmp_path):
    item = document()
    data = case(tmp_path, docs=[item], parent_texts=["aa", "aa"])
    bundle = build(owner, data)
    by_cid = {record["record_cid"]: record for record in bundle["records"]}
    related = records_of_kind(bundle, "document")[0]["related_records"]
    normalized = by_cid[related["normalized_source_version_cid"]]
    rendered = by_cid[related["rendered_source_version_cid"]]
    assert normalized["record_cid"] != rendered["record_cid"]
    assert normalized["raw_artifact"] == rendered["raw_artifact"]
    assert normalized["extracted_view"]["sha256"] != rendered["extracted_view"]["sha256"]
    assert normalized["extracted_view"]["normalization_profile"] == official_owner.NORMALIZATION_PROFILE
    assert rendered["extracted_view"]["normalization_profile"] == rendered["extracted_view"]["extraction_profile"] == alignment_owner.RENDER_PROFILE
    assert normalized["extracted_view"]["extraction_profile"] != rendered["extracted_view"]["extraction_profile"]
    normalized_body = [record for record in records_of_kind(bundle, "source_occurrence") if record["source_version_cid"] == normalized["record_cid"] and record["span_text"] == "aa"]
    rendered_body = [record for record in records_of_kind(bundle, "source_occurrence") if record["source_version_cid"] == rendered["record_cid"] and record["span_text"] == "aa"]
    assert len(normalized_body) == len(rendered_body) == 1
    assert normalized_body[0]["span_sha256"] == rendered_body[0]["span_sha256"] == sha(b"aa")
    assert normalized_body[0]["record_cid"] != rendered_body[0]["record_cid"]


def test_render_events_and_derived_join_gaps_preserve_their_actual_coordinate_origins(owner, tmp_path):
    item = document(body=" aa </p>\n<p> Café ")
    data = case(tmp_path, docs=[item])
    bundle = build(owner, data)
    assert_projection_counts(bundle, data)
    records = {record["record_cid"]: record for record in bundle["records"]}
    events = records_of_kind(bundle, "render_event")
    assert any(record["observations"]["fragment_index"] is None for record in events)
    stripped = 0
    for record in events:
        event = original_value(data, record)
        assert record["observations"] == event
        assert record["source_occurrence_cid"] is record["context_cid"] is None
        reference = record["related_records"]["render_fragment_record_cid"]
        if event["fragment_index"] is None:
            assert reference is None
        else:
            fragment = records[reference]
            assert fragment["owner_identity"]["fragment_index"] == event["fragment_index"]
            assert fragment["owner_identity"]["event_index"] == event["event_index"]
            if event["strip_prefix_characters"] or event["strip_suffix_characters"]:
                assert event["data_sha256"] != fragment["observations"]["text_sha256"]
                stripped += 1
    assert stripped > 0
    for gap in records_of_kind(bundle, "render_gap"):
        assert gap["external_binding"]["json_pointer"] == "/official_documents/0/rendered_field_view"
        assert gap["owner_identity"]["derived_origin"] == "one_ASCII_space_between_nonempty_render_fragments/v1"
        left = records[gap["related_records"]["left_fragment_record_cid"]]
        right = records[gap["related_records"]["right_fragment_record_cid"]]
        occurrence = records[gap["source_occurrence_cid"]]
        assert occurrence["span_text"] == " " and occurrence["span_sha256"] == sha(b" ")
        assert occurrence["start_char"] == left["observations"]["char_end"]
        assert occurrence["end_char"] == right["observations"]["char_start"]
        assert right["owner_identity"]["fragment_index"] == left["owner_identity"]["fragment_index"] + 1


def test_repeated_acquisitions_share_physical_origins_and_keep_every_custody_wrapper(owner, tmp_path):
    first = document()
    second = deepcopy(first)
    second["descriptor"]["retrieved_at"] = "2026-10-14T01:00:00+00:00"
    second["expected_descriptor_sha256"] = sha(canonical(second["descriptor"]))
    second["view_report"] = official_owner.prepare_official_document_view(
        second["raw_bytes"],
        **{key: second[key] for key in ("descriptor", "expected_descriptor_sha256", "expected_raw_sha256", "expected_raw_bytes")},
    )
    second["expected_view_report_sha256"] = sha(canonical(second["view_report"]))
    assert first["expected_descriptor_sha256"] != second["expected_descriptor_sha256"]
    assert first["expected_view_report_sha256"] != second["expected_view_report_sha256"]
    data = case(tmp_path, docs=[first, second])
    bundle = build(owner, data)
    assert_projection_counts(bundle, data)
    documents = records_of_kind(bundle, "document")
    assert len(documents) == 2 and documents[0]["record_cid"] != documents[1]["record_cid"]
    assert documents[0]["related_records"] == documents[1]["related_records"]
    assert len(records_of_kind(bundle, "source_version")) == 2
    assert validate(owner, bundle, data) == bundle


def test_source_pin_drift_after_manifest_sealing_refuses_complete_projection(owner, tmp_path, monkeypatch):
    data = case(tmp_path)
    state = {"drift": False}
    seal = contracts.seal_record
    pins = owner._pins
    def observed_seal(payload):
        result = seal(payload)
        if payload.get("schema") == owner.SCHEMA:
            state["drift"] = True
        return result
    def observed_pins(owners):
        result = pins(owners)
        if state["drift"]:
            result[next(iter(result))] = "0" * 64
        return result
    monkeypatch.setattr(contracts, "seal_record", observed_seal)
    monkeypatch.setattr(owner, "_pins", observed_pins)
    with pytest.raises(contracts.CorpusContractError):
        build(owner, data)
    assert state["drift"]


def test_source_pin_drift_during_final_validator_comparison_refuses_return(owner, tmp_path, monkeypatch):
    data = case(tmp_path)
    bundle = build(owner, data)
    state = {"replayed": False, "drift": False}
    original_build = owner.build_parent_alignment_corpus
    original_canonical = owner.canonical_dag_json_bytes
    original_pins = owner._pins
    last_cid = bundle["records"][-1]["record_cid"]
    def observed_build(**arguments):
        result = original_build(**arguments)
        state["replayed"] = True
        return result
    def observed_canonical(value):
        result = original_canonical(value)
        if state["replayed"] and type(value) is dict and value.get("record_cid") == last_cid:
            state["drift"] = True
        return result
    def observed_pins(owners):
        result = original_pins(owners)
        if state["drift"]:
            result[next(iter(result))] = "0" * 64
        return result
    monkeypatch.setattr(owner, "build_parent_alignment_corpus", observed_build)
    monkeypatch.setattr(owner, "canonical_dag_json_bytes", observed_canonical)
    monkeypatch.setattr(owner, "_pins", observed_pins)
    with pytest.raises(contracts.CorpusContractError):
        validate(owner, bundle, data)
    assert state["replayed"] and state["drift"]


@pytest.mark.parametrize("schema", [[], {}], ids=["list", "object"])
def test_resealed_nontext_schema_is_a_contract_refusal(owner, tmp_path, schema):
    data = case(tmp_path)
    bundle = build(owner, data)
    # A fresh valid seal with a nontext schema cannot be obtained through the
    # common owner; bind one directly so the adapter must reject malformed data.
    record = deepcopy(bundle["records"][-1])
    record["schema"] = schema
    record["record_cid"] = cid_for_dag_json({key: value for key, value in record.items() if key != "record_cid"})
    bundle["records"][-1] = record
    with pytest.raises(contracts.CorpusContractError):
        validate(owner, bundle, data)


def test_detached_collection_exceeds_one_envelope_without_weakening_common_limits(owner, tmp_path):
    docs = [document(section, "z" * 40000) for section in range(1, 11)]
    data = case(tmp_path, docs=docs, parent_texts=["Unmatched parent field.", "Distinct original row."], source_text="unmatched cache")
    bundle = build(owner, data)
    assert_projection_counts(bundle, data)
    assert len(canonical(bundle)) > contracts.MAX_RECORD_BYTES
    assert contracts.MAX_RECORD_BYTES == 1024 * 1024
    assert max(len(canonical_dag_json_bytes(record)) for record in bundle["records"]) <= contracts.MAX_RECORD_BYTES
    assert max(len(canonical_dag_json_bytes(page)) for page in bundle["pages"]) <= contracts.MAX_RECORD_BYTES
    assert len(canonical_dag_json_bytes(bundle["manifest"])) <= contracts.MAX_RECORD_BYTES
    assert validate(owner, bundle, data) == bundle


def test_new_inventory_pages_cover_all_records_without_copying_old_corpus(owner, tmp_path):
    data = case(tmp_path)
    limits = {"max_records_per_page": 3}
    bundle = build(owner, data, limits=limits)
    assert_inventory(bundle)
    assert len(bundle["pages"]) > 2
    assert all(len(page["entries"]) <= 3 for page in bundle["pages"])
    assert len(bundle["pages"][-1]["entries"]) in (1, 2, 3)
    assert validate(owner, bundle, data, limits=limits) == bundle
    assert contracts.MAX_RECORD_BYTES == 1024 * 1024


@pytest.mark.parametrize(
    "damage",
    ["record_subset", "record_order", "record_duplicate", "page_subset", "page_order",
     "page_duplicate", "entry_subset", "entry_order", "entry_SHA", "entry_kind",
     "page_ordinal", "first_ordinal", "root_ref_tail", "root_page_count", "authority"],
)
def test_resealed_paging_and_population_changes_fail_independent_full_replay(owner, tmp_path, damage):
    data = case(tmp_path)
    limits = {"max_records_per_page": 3}
    bundle = build(owner, data, limits=limits)
    if damage == "record_subset":
        bundle["records"].pop()
    elif damage == "record_order":
        bundle["records"].reverse()
    elif damage == "record_duplicate":
        bundle["records"].append(deepcopy(bundle["records"][0]))
    elif damage == "page_subset":
        bundle["pages"].pop()
    elif damage == "page_order":
        bundle["pages"].reverse()
    elif damage == "page_duplicate":
        bundle["pages"].append(deepcopy(bundle["pages"][0]))
    elif damage == "root_ref_tail":
        bundle["manifest"]["page_refs"][-1]["last_record_cid"] = bundle["records"][0]["record_cid"]
        bundle["manifest"] = reseal(bundle["manifest"])
    elif damage == "root_page_count":
        bundle["manifest"]["page_refs"].pop()
        bundle["manifest"] = reseal(bundle["manifest"])
    else:
        page = bundle["pages"][0]
        if damage == "entry_subset":
            page["entries"].pop()
        elif damage == "entry_order":
            page["entries"].reverse()
        elif damage == "entry_SHA":
            page["entries"][0]["sha256"] = "0" * 64
        elif damage == "entry_kind":
            page["entries"][0]["kind"] = "reviewed_definition"
        elif damage == "page_ordinal":
            page["page_ordinal"] = 1
        elif damage == "first_ordinal":
            page["first_record_ordinal"] = 1
        else:
            page["admitted"] = True
        bundle["pages"][0] = reseal(page)
        bundle["manifest"]["page_refs"][0]["page_cid"] = bundle["pages"][0]["record_cid"]
        bundle["manifest"]["page_refs"][0]["sha256"] = sha(canonical(bundle["pages"][0]))
        bundle["manifest"] = reseal(bundle["manifest"])
    with pytest.raises(ValueError):
        validate(owner, bundle, data, limits=limits)


@pytest.mark.parametrize(
    "damage", ["CID_list", "CID_object", "entry_bool", "page_bool", "first_ordinal_bool"]
)
def test_malformed_inventory_types_are_contract_refusals_before_replay(owner, tmp_path, monkeypatch, damage):
    data = case(tmp_path)
    limits = {"max_records_per_page": 3}
    bundle = build(owner, data, limits=limits)
    page_index = 1 if damage == "page_bool" else 0
    page = bundle["pages"][page_index]
    if damage == "CID_list":
        page["entries"][0]["record_cid"] = []
    elif damage == "CID_object":
        page["entries"][0]["record_cid"] = {}
    elif damage == "entry_bool":
        page["entries"][0]["ordinal"] = False
    elif damage == "page_bool":
        page["page_ordinal"] = True
    else:
        page["first_record_ordinal"] = False
    page = reseal(page)
    bundle["pages"][page_index] = page
    bundle["manifest"]["page_refs"][page_index]["page_cid"] = page["record_cid"]
    bundle["manifest"]["page_refs"][page_index]["sha256"] = sha(canonical(page))
    bundle["manifest"] = reseal(bundle["manifest"])
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("malformed inventory reached source replay"))
    with pytest.raises(contracts.CorpusContractError):
        validate(owner, bundle, data, limits=limits)


@pytest.mark.parametrize("damage", ["authority", "derived_geometry"])
def test_fully_repaired_leaf_record_and_inventory_still_require_original_replay(owner, tmp_path, damage):
    data = case(tmp_path)
    bundle = build(owner, data)
    last = bundle["records"][-1]
    assert last["kind"] == "render_gap"
    if damage == "authority":
        last["admitted"] = True
    else:
        last["observations"]["char_end"] += 1
    last = reseal(last)
    bundle["records"][-1] = last
    page = bundle["pages"][-1]
    page["entries"][-1]["record_cid"] = last["record_cid"]
    page["entries"][-1]["sha256"] = sha(canonical(last))
    page = reseal(page)
    bundle["pages"][-1] = page
    reference = bundle["manifest"]["page_refs"][-1]
    reference["page_cid"] = page["record_cid"]
    reference["sha256"] = sha(canonical(page))
    reference["last_record_cid"] = last["record_cid"]
    bundle["manifest"] = reseal(bundle["manifest"])
    assert_inventory(bundle)
    with pytest.raises(contracts.CorpusContractError):
        validate(owner, bundle, data)


@pytest.mark.parametrize(
    "limit",
    ["max_alignment_report_bytes", "max_base_manifest_bytes", "max_base_records_bytes",
     "max_replay_bytes", "max_total_input_bytes", "max_records", "max_collection_bytes",
     "max_page_bytes", "max_pages"],
)
def test_complete_lowered_bounds_refuse_without_retaining_easy_prefixes(owner, tmp_path, limit):
    data = case(tmp_path)
    limits = {limit: 1}
    if limit == "max_pages":
        limits["max_records_per_page"] = 3
    with pytest.raises(ValueError):
        build(owner, data, limits=limits)


@pytest.mark.parametrize("limits", [{"invented": 1}, {"max_records": True}, {"max_pages": 0}, {"max_pages": 257}])
def test_limits_are_closed_lower_only_integers(owner, tmp_path, limits):
    with pytest.raises(ValueError):
        build(owner, case(tmp_path), limits=limits)


@pytest.mark.parametrize("budget", ["max_alignment_report_bytes", "max_base_manifest_bytes", "max_base_records_bytes", "max_replay_bytes", "max_total_input_bytes"])
def test_intake_bounds_precede_any_lazy_owner_import_or_source_replay(owner, tmp_path, budget, monkeypatch):
    data = case(tmp_path)
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("owner imported before complete intake bound"))
    with pytest.raises(ValueError):
        build(owner, data, limits={budget: 1})


@pytest.mark.parametrize("wide_text", ["雪" * 400, "\\\"\n" * 400], ids=["unicode", "escaped"])
def test_wide_nested_replay_budget_is_refused_before_target_bulk_serialization(
    owner, tmp_path, monkeypatch, wide_text
):
    data = case(tmp_path)
    replay = data["arguments"]["base_replay_inputs"]
    replay["provenance_reports"][0]["rows"][0]["raw_row"]["wide_retained_observation"] = [wide_text] * 10
    original_dumps = json.dumps
    def guarded_dumps(value, *args, **kwargs):
        if value is replay:
            pytest.fail("complete over-budget replay was bulk serialized before refusal")
        return original_dumps(value, *args, **kwargs)
    monkeypatch.setattr(json, "dumps", guarded_dumps)
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("owner import preceded nested replay bound"))
    with pytest.raises(ValueError):
        build(owner, data, limits={"max_replay_bytes": 512})


def test_all_new_envelopes_leave_review_governing_and_backend_flags_false(owner, tmp_path):
    data = case(tmp_path)
    bundle = build(owner, data)
    assert_projection_counts(bundle, data)
    flags = (
        "admitted", "formalized", "source_semantics_verified", "source_authenticity_verified",
        "source_region_roles_verified", "context_closure_verified", "independently_reviewed",
        "proof_authority", "training_qualified", "lean_compilation_verified", "backend_executed",
        "governing_body_selected", "governing_edition_verified",
    )
    for record in (bundle["manifest"], *bundle["pages"], *bundle["records"]):
        for flag in flags:
            if flag in record:
                assert record[flag] is False
        if "selected_occurrence" in record:
            assert record["selected_occurrence"] is None
        if "governing_source_binding" in record:
            assert record["governing_source_binding"] is None
    contexts = records_of_kind(bundle, "context")
    assert contexts
    assert all(record["availability"] == "required_unavailable" for record in contexts)
    assert all(record["dependency_verification"] == "declaration_only" for record in contexts)


def test_actual_public_module_import_is_inert():
    program = r'''
import sys
from ipfs_datasets_py.logic.autoformal import corpus_parent_alignment_adapter
assert callable(corpus_parent_alignment_adapter.build_parent_alignment_corpus)
assert not any(name == 'torch' or name.startswith('torch.') for name in sys.modules)
assert not any(name == 'transformers' or name.startswith('transformers.') for name in sys.modules)
assert not any(name == 'pyarrow' or name.startswith('pyarrow.') for name in sys.modules)
assert 'ipfs_datasets_py.logic.autoformal.legal_parent_source_alignment' not in sys.modules
assert 'ipfs_datasets_py.logic.autoformal.legal_parent_parquet_pages' not in sys.modules
print('inert public import verified')
'''
    repo = Path(__file__).resolve().parents[4]
    environment = dict(os.environ, IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0", PYTHONPATH=str(repo))
    result = subprocess.run([sys.executable, "-c", program], cwd=repo, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "inert public import verified"
