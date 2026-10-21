"""Complete-parent scan checks against independent physical fixtures.

The real scan belongs to a separately enrolled owned profile. Independent
Arrow-written rows and a handcrafted crossing-page list supply complete-row
oracles without a second productive parent decoder. No selected API limit,
partition assignment, training permission or source authority is widened.
"""
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import errno

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_parent_parquet_pages as pages
from tests.unit.logic.autoformal.test_legal_parent_parquet_pages import (
    compact_struct, fixture, header,
)

MANIFEST = "parent-source-metadata.json"
EVIDENCE_NAME = "complete-parent-metadata-engineering-evidence.json"
OLD_SELECTED_DEFAULTS = {
    "max_file_bytes": 512 * 1024**2, "max_footer_bytes": 1024**2,
    "max_header_bytes": 64 * 1024, "max_pages": 8192, "max_columns": 64,
    "max_row_groups": 128, "max_rows": 100_000, "max_column_values": 1_000_000,
    "max_page_compressed_bytes": 16 * 1024**2, "max_page_uncompressed_bytes": 32 * 1024**2,
    "max_dictionary_bytes": 16 * 1024**2, "max_page_values": 131_072,
    "max_selected_rows": 32, "max_selected_bytes": 32 * 1024**2,
    "max_row_bytes": 8 * 1024**2, "max_value_bytes": 8 * 1024**2,
    "max_list_values": 4096, "max_decoded_bytes": 256 * 1024**2,
}
REAL_ORDINALS = [2720, 2721, 2722, 2724, 2726, 2727, 3345, 3352, 3353,
    3354, 3355, 3357, 3358]


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(wire(value)).hexdigest()


def input_report(tmp_path, expected, *, schema=None, dictionary=True, groups=None):
    target = tmp_path / "input.parquet"
    pq.write_table(pa.Table.from_pylist(expected, schema=schema), target,
        compression="snappy", use_dictionary=dictionary, data_page_version="1.0",
        data_page_size=256, write_batch_size=1, row_group_size=groups or len(expected))
    descriptor = {"repository": "fixture/complete-parent", "revision": "a" * 40,
        "path_in_repo": target.name, "local_path": str(target),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "bytes": target.stat().st_size,
        "row_count": len(expected), "profile": pages.PARENT_PROFILE}
    preflight = pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=sha(descriptor))
    return descriptor, preflight


def scan(descriptor, preflight, output, **limits):
    manifest = pages.scan_parent_source_metadata(descriptor,
        expected_descriptor_sha256=sha(descriptor), preflight_report=preflight,
        expected_preflight_sha256=pages.parent_page_report_sha256(preflight),
        output_directory=output, limits=pages.ParentMetadataScanLimits(**limits))
    assert manifest["parent"] == descriptor
    assert manifest["parent_descriptor_sha256"] == sha(descriptor)
    assert manifest["preflight_report_sha256"] == pages.parent_page_report_sha256(preflight)
    assert manifest["source_schema"] == preflight["source_schema"]
    assert manifest["source_schema_sha256"] == preflight["source_schema_sha256"] == sha(manifest["source_schema"])
    return manifest


def physical_key(descriptor, ordinal):
    return {"repository_id": descriptor["repository"], "revision": descriptor["revision"],
        "path_in_repo": descriptor["path_in_repo"], "artifact_sha256": descriptor["sha256"],
        "artifact_bytes": descriptor["bytes"], "parquet_row_index": ordinal}


def assert_metadata(row, raw, descriptor, ordinal):
    key = physical_key(descriptor, ordinal)
    assert row["physical_key"] == key
    assert row["physical_section_id"] == "sha256:" + sha(key)
    assert row["full_raw_row_sha256"] == sha(raw)
    assert row["raw_row_canonical_bytes"] == len(wire(raw))
    text = raw.get("text")
    if type(text) is str:
        assert row["text"] == {"sha256": hashlib.sha256(text.encode()).hexdigest(),
            "utf8_bytes": len(text.encode()), "unicode_characters": len(text)}
        assert row["normalized_content_sha256"] == hashlib.sha256(" ".join(text.split()).casefold().encode()).hexdigest()
        assert row["disposition"] == ("stored_text_available" if text else "empty_text")
    else:
        assert row["text"] is row["normalized_content_sha256"] is None
        assert row["disposition"] == ("missing_text" if text is None else "unsupported_text_type")
    assert "raw_row" not in row
    assert row["group_id"] is row["split"] is row["inference_view"] is None
    assert type(row["training_mask"]) is type(row["evaluation_gold_mask"]) is int
    assert row["training_mask"] == row["evaluation_gold_mask"] == 0
    assert row["authority"] and all(value is False for value in row["authority"].values())


def assert_manifest(manifest, output):
    assert manifest["schema"] == "legal-parent-complete-source-metadata/v1"
    assert manifest["profile"] == "historical-parent-complete-source-metadata/v1"
    assert manifest["scope"] == "declared_parent_artifact_only"
    assert json.loads((output / MANIFEST).read_bytes()) == manifest
    assert manifest["manifest_sha256"] == sha({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    assert manifest["group_id"] is manifest["split"] is manifest["inference_view"] is None
    assert type(manifest["training_mask"]) is type(manifest["evaluation_gold_mask"]) is int
    assert manifest["training_mask"] == manifest["evaluation_gold_mask"] == 0
    assert manifest["authority"] and all(value is False for value in manifest["authority"].values())
    assert manifest["raw_rows_stored"] is manifest["source_text_stored"] is False
    assert manifest["grouping_metadata_complete"] is False
    assert manifest["all_source_columns_hashed"] is True
    assert manifest["coverage"] == {"declared_parent_rows": manifest["parent"]["row_count"],
        "replayed_parent_rows": manifest["row_count"], "whole_parent_inventoried": True}
    assert manifest["row_count"] == manifest["parent"]["row_count"]
    assert len({row["page_id"] for row in manifest["decoded_page_witnesses"]}) == manifest["page_count"]
    assert sum(row["uncompressed_bytes"] for row in manifest["decoded_page_witnesses"]) == manifest["decoded_page_bytes"]
    assert sum(row["bytes"] for row in manifest["shards"]) == manifest["total_metadata_bytes"]


def read_shards(manifest, output):
    """Check the additive owner's closed manifest and every bounded shard."""
    assert_manifest(manifest, output)
    rows = []
    for shard in manifest["shards"]:
        relative = shard["relative_path"]
        assert not Path(relative).is_absolute() and all(part not in ("", ".", "..") for part in relative.split("/"))
        path = output / relative
        assert path.resolve(strict=True) == path and output in path.parents
        raw = path.read_bytes()
        assert len(raw) == shard["bytes"] and hashlib.sha256(raw).hexdigest() == shard["sha256"]
        decoded = [json.loads(line) for line in raw.splitlines()]
        assert len(decoded) == shard["row_count"]
        assert shard["start_ordinal"] == len(rows)
        assert shard["end_ordinal"] == len(rows) + len(decoded)
        assert [row["physical_key"]["parquet_row_index"] for row in decoded] == list(range(shard["start_ordinal"], shard["end_ordinal"]))
        rows.extend(decoded)
    assert len(rows) == manifest["row_count"]
    assert sum(row["raw_row_canonical_bytes"] for row in rows) == manifest["raw_row_canonical_bytes"]
    return rows


@pytest.mark.parametrize("dictionary", [False, True])
def test_complete_all45_fields_match_independent_sorted_canonical_row_oracle(tmp_path, dictionary):
    source = tmp_path / "source"
    source.mkdir()
    _, descriptor, expected = fixture(source, dictionary=dictionary, rows=31, groups=7)
    preflight = pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=sha(descriptor))
    output = tmp_path / "scan"
    manifest = scan(descriptor, preflight, output)
    observed = read_shards(manifest, output)
    assert len(observed) == len(expected) == 31
    assert [row["physical_key"]["parquet_row_index"] for row in observed] == list(range(31))
    for ordinal, (row, raw) in enumerate(zip(observed, expected, strict=True)):
        assert len(raw) == 45
        assert_metadata(row, raw, descriptor, ordinal)
    assert b"literal:35" not in (output / MANIFEST).read_bytes()


def test_every_dictionary_and_data_page_is_decoded_exactly_once_with_expansion_charged(tmp_path, monkeypatch):
    repeated = 'quote" slash\\ controls\n\t\u0000 Café 雪' * 100
    expected = [{"ipfs_cid": "same", "title_number": "10", "section_number": "1",
        "text": repeated, "values": [repeated, None, repeated]} for _ in range(19)]
    descriptor, preflight = input_report(tmp_path, expected)
    calls = Counter()
    original = pages._body
    def observed_body(stream, column, page, *arguments):
        calls[page["page_id"]] += 1
        return original(stream, column, page, *arguments)
    monkeypatch.setattr(pages, "_body", observed_body)
    output = tmp_path / "scan"
    manifest = scan(descriptor, preflight, output)
    expected_pages = [page for group in preflight["row_groups"] for column in group["columns"] for page in column["pages"]]
    assert calls == Counter({page["page_id"]: 1 for page in expected_pages})
    rows = read_shards(manifest, output)
    assert sum(row["raw_row_canonical_bytes"] for row in rows) == sum(len(wire(row)) for row in expected)
    for ordinal, (row, raw) in enumerate(zip(rows, expected, strict=True)):
        assert_metadata(row, raw, descriptor, ordinal)


def test_dictionary_expansion_has_a_separate_canonical_budget_from_decoded_pages(tmp_path):
    repeated = "expanded dictionary value 雪 " * 300
    expected = [{"text": repeated, "values": [repeated, repeated]} for _ in range(19)]
    descriptor, preflight = input_report(tmp_path, expected)
    decoded = sum(page["uncompressed_bytes"] for group in preflight["row_groups"]
        for column in group["columns"] for page in column["pages"])
    canonical = sum(len(wire(row)) for row in expected)
    assert decoded + 1024 < canonical
    output = tmp_path / "scan"
    with pytest.raises(ValueError):
        scan(descriptor, preflight, output, max_total_canonical_hashed_bytes=decoded + 1024)
    assert not (output / MANIFEST).exists()


def crossing_list_parent(tmp_path):
    """Independent two-page list where row0 continues into page1."""
    root = [(4, 8, b"schema"), (5, 5, 1)]
    outer = [(3, 5, 1), (4, 8, b"values"), (5, 5, 1), (6, 5, 3), (10, 12, [(3, 12, [])])]
    repeated = [(3, 5, 2), (4, 8, b"list"), (5, 5, 1)]
    leaf = [(1, 5, 6), (3, 5, 1), (4, 8, b"element"), (6, 5, 0), (10, 12, [(1, 12, [])])]
    def page(repetitions, definitions, value):
        reps = b"".join(b"\x02" + bytes([item]) for item in repetitions)
        defs = b"".join(b"\x02" + bytes([item]) for item in definitions)
        encoded = value.encode("utf-8")
        body = len(reps).to_bytes(4, "little") + reps + len(defs).to_bytes(4, "little") + defs
        body += len(encoded).to_bytes(4, "little") + encoded
        return header(count=2, raw_size=len(body), compressed_size=len(body)) + body
    payload = page([0, 1], [3, 2], "é") + page([1, 0], [3, 1], "雪")
    metadata = [(1, 5, 6), (2, 9, (5, [0, 3])), (3, 9, (8, [b"values", b"list", b"element"])),
        (4, 5, 0), (5, 6, 4), (6, 6, len(payload)), (7, 6, len(payload)), (9, 6, 4)]
    group = [(1, 9, (12, [[(3, 12, metadata)]])), (2, 6, len(payload)), (3, 6, 2)]
    footer = compact_struct([(1, 5, 1), (2, 9, (12, [root, outer, repeated, leaf])),
        (3, 6, 2), (4, 9, (12, [group]))])
    target = tmp_path / "crossing-list.parquet"
    target.write_bytes(b"PAR1" + payload + footer + len(footer).to_bytes(4, "little") + b"PAR1")
    descriptor = {"repository": "fixture/complete-parent", "revision": "a" * 40,
        "path_in_repo": target.name, "local_path": str(target),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "bytes": target.stat().st_size,
        "row_count": 2, "profile": pages.PARENT_PROFILE}
    preflight = pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=sha(descriptor))
    return descriptor, preflight, [{"values": ["é", None, "雪"]}, {"values": []}]


def test_list_continuation_across_pages_keeps_null_and_empty_rows_distinct(tmp_path):
    descriptor, preflight, expected = crossing_list_parent(tmp_path)
    output = tmp_path / "scan"
    rows = read_shards(scan(descriptor, preflight, output), output)
    assert len(rows) == 2
    for ordinal, (row, raw) in enumerate(zip(rows, expected, strict=True)):
        assert_metadata(row, raw, descriptor, ordinal)


@pytest.mark.parametrize("kind", ["null", "empty", "unsupported", "missing"])
def test_all_physical_rows_survive_text_unavailability_without_partition_eligibility(tmp_path, kind):
    value = None if kind == "null" else "" if kind == "empty" else 42
    expected = [{"ipfs_cid": "cid", "title_number": "10", "section_number": "1",
        **({} if kind == "missing" else {"text": value})}]
    schema = pa.schema([("ipfs_cid", pa.string()), ("title_number", pa.string()), ("section_number", pa.string())]
        + ([] if kind == "missing" else [("text", pa.int64() if kind == "unsupported" else pa.string())]))
    descriptor, preflight = input_report(tmp_path, expected, schema=schema)
    output = tmp_path / "scan"
    rows = read_shards(scan(descriptor, preflight, output), output)
    assert len(rows) == 1
    assert_metadata(rows[0], expected[0], descriptor, 0)


def test_identical_rows_never_collapse_physical_ordinals_or_source_hashes(tmp_path):
    expected = [{"ipfs_cid": "same", "title_number": "10", "section_number": "1", "text": "same 雪"}] * 5
    descriptor, preflight = input_report(tmp_path, expected)
    output = tmp_path / "scan"
    rows = read_shards(scan(descriptor, preflight, output), output)
    assert len({row["full_raw_row_sha256"] for row in rows}) == 1
    assert len({row["physical_section_id"] for row in rows}) == 5
    assert [row["physical_key"]["parquet_row_index"] for row in rows] == list(range(5))


def test_large_identity_keeps_exact_hash_length_and_disclosed_unavailable_literal(tmp_path):
    identity = "雪" * 200
    expected = [{"ipfs_cid": identity, "title_number": "10", "section_number": "1", "text": "literal source"}]
    descriptor, preflight = input_report(tmp_path, expected)
    output = tmp_path / "scan"
    rows = read_shards(scan(descriptor, preflight, output), output)
    row = rows[0]
    assert_metadata(row, expected[0], descriptor, 0)
    assert row["observed_identity"]["ipfs_cid"] is None
    assert row["observed_identity_status"]["ipfs_cid"] == "unsupported_size"
    assert row["observed_identity_evidence"]["ipfs_cid"] == {
        "sha256": hashlib.sha256(identity.encode()).hexdigest(), "utf8_bytes": 600}


def test_invalid_utf8_in_an_independently_rehashed_parent_is_fatal_not_a_dropped_row(tmp_path):
    target = tmp_path / "invalid-utf8.parquet"
    pq.write_table(pa.Table.from_pylist([{"text": "legalé"}]), target,
        compression=None, use_dictionary=False, data_page_version="1.0")
    descriptor = {"repository": "fixture/complete-parent", "revision": "a" * 40,
        "path_in_repo": target.name, "local_path": str(target),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "bytes": target.stat().st_size,
        "row_count": 1, "profile": pages.PARENT_PROFILE}
    preflight = pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=sha(descriptor))
    page = preflight["row_groups"][0]["columns"][0]["pages"][0]
    start = page["offset"] + page["header_bytes"]
    raw = target.read_bytes()
    location = raw.index("legalé".encode("utf-8"), start, start + page["compressed_bytes"]) + len(b"legal")
    target.write_bytes(raw[:location] + b"\xff\xff" + raw[location + 2:])
    descriptor["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    preflight = pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=sha(descriptor))
    output = tmp_path / "scan"
    with pytest.raises(ValueError):
        scan(descriptor, preflight, output)
    assert not (output / MANIFEST).exists()


def test_separate_scan_limits_leave_all_existing_selected_defaults_unchanged():
    assert pages.DEFAULT_LIMITS == OLD_SELECTED_DEFAULTS
    limits = pages.ParentMetadataScanLimits()
    assert limits.max_rows == 65536
    assert limits.max_total_decoded_page_bytes == 2 * 1024**3
    assert limits.max_total_canonical_hashed_bytes == 4 * 1024**3
    assert limits.max_metadata_row_bytes == 4096
    assert limits.max_identity_literal_bytes == 512
    assert limits.max_rows_per_metadata_shard == 4096
    assert limits.max_metadata_shard_bytes == 4 * 1024**2
    assert limits.max_metadata_shards == 128
    assert limits.max_manifest_bytes == 2 * 1024**2
    assert limits.max_total_metadata_package_bytes == 384 * 1024**2
    assert limits.max_resident_metadata_bytes == 256 * 1024**2
    assert limits.max_preflight_bytes == 8 * 1024**2


@pytest.mark.parametrize("field,value", [("max_rows", True), ("max_rows", 65537),
    ("max_total_decoded_page_bytes", 0), ("max_total_decoded_page_bytes", 2 * 1024**3 + 1),
    ("max_total_canonical_hashed_bytes", False), ("max_metadata_shards", -1),
    ("max_identity_literal_bytes", 513), ("not_a_scan_limit", 1)])
def test_unknown_boolean_nonpositive_and_raised_scan_limits_are_refused(field, value):
    with pytest.raises((ValueError, TypeError)):
        pages.ParentMetadataScanLimits(**{field: value})


@pytest.mark.parametrize("budget", ["max_rows", "max_total_decoded_page_bytes", "max_total_canonical_hashed_bytes",
    "max_metadata_row_bytes", "max_metadata_shard_bytes", "max_metadata_shards",
    "max_manifest_bytes", "max_total_metadata_package_bytes", "max_resident_metadata_bytes"])
def test_hard_scan_or_output_overflow_never_emits_a_complete_manifest(tmp_path, budget):
    expected = [{"ipfs_cid": "cid:" + str(i), "title_number": "10", "section_number": str(i),
        "text": "repeated dictionary value 雪 " * 200} for i in range(3)]
    descriptor, preflight = input_report(tmp_path, expected)
    output = tmp_path / "scan"
    limits = {budget: 1}
    if budget == "max_metadata_shards":
        limits["max_rows_per_metadata_shard"] = 1
    with pytest.raises(ValueError):
        scan(descriptor, preflight, output, **limits)
    assert not (output / MANIFEST).exists()


def test_manifest_is_published_only_after_the_genuine_final_parent_guard(tmp_path, monkeypatch):
    expected = [{"ipfs_cid": "cid", "title_number": "10", "section_number": "1", "text": "source"}]
    descriptor, preflight = input_report(tmp_path, expected)
    output = tmp_path / "scan"
    original = pages._opened
    observations = []
    @contextmanager
    def observe_genuine_guard(parent):
        with original(parent) as stream:
            yield stream
            assert not (output / MANIFEST).exists()
            observations.append("before_final_original_guard")
        assert not (output / MANIFEST).exists()
        observations.append("after_final_original_guard")
    monkeypatch.setattr(pages, "_opened", observe_genuine_guard)
    manifest = scan(descriptor, preflight, output)
    assert observations == ["before_final_original_guard", "after_final_original_guard"]
    assert (output / MANIFEST).is_file()
    assert len(read_shards(manifest, output)) == 1


def test_manifest_fsync_failure_never_publishes_the_complete_manifest_name(tmp_path, monkeypatch):
    descriptor, preflight = input_report(tmp_path, [{"text": "source"}])
    output = tmp_path / "scan"
    original = pages.os.fsync
    interrupted = []
    def fail_only_root_manifest_file(descriptor_number):
        if stat.S_ISREG(os.fstat(descriptor_number).st_mode):
            target = Path(os.readlink("/proc/self/fd/" + str(descriptor_number)))
            if target.parent == output:
                interrupted.append(str(target))
                raise OSError("independent manifest fsync failure")
        return original(descriptor_number)
    monkeypatch.setattr(pages.os, "fsync", fail_only_root_manifest_file)
    with pytest.raises((OSError, ValueError)):
        scan(descriptor, preflight, output)
    assert len(interrupted) == 1
    assert not (output / MANIFEST).exists()


@pytest.mark.parametrize("mutation_point", ["after_genuine_decode", "after_genuine_final_guard"])
def test_mutated_caller_limits_are_revalidated_before_any_unchecked_serialization(tmp_path, monkeypatch, mutation_point):
    descriptor, preflight = input_report(tmp_path, [{"text": "source"}])
    output = tmp_path / "scan"
    limits = pages.ParentMetadataScanLimits()
    replacement = ["bounded-noninteger-scan-limit-sentinel"]
    original_wire = pages._wire
    def contains_replacement(value):
        if value is replacement:
            return True
        if type(value) is dict:
            return any(contains_replacement(child) for child in value.values())
        if type(value) is list:
            return value == replacement or any(contains_replacement(child) for child in value)
        return False
    def refuse_unchecked_limits(value):
        assert not contains_replacement(value), "mutated noninteger limit reached unchecked JSON serialization"
        return original_wire(value)
    monkeypatch.setattr(pages, "_wire", refuse_unchecked_limits)
    if mutation_point == "after_genuine_decode":
        original_body = pages._body
        def mutate_after_decode(*arguments, **keywords):
            raw = original_body(*arguments, **keywords)
            object.__setattr__(limits, "max_rows", replacement)
            return raw
        monkeypatch.setattr(pages, "_body", mutate_after_decode)
    else:
        original_opened = pages._opened
        @contextmanager
        def mutate_after_final_guard(parent):
            with original_opened(parent) as stream:
                yield stream
            object.__setattr__(limits, "max_rows", replacement)
        monkeypatch.setattr(pages, "_opened", mutate_after_final_guard)
    with pytest.raises(pages.ParentParquetPagesError):
        pages.scan_parent_source_metadata(descriptor, expected_descriptor_sha256=sha(descriptor),
            preflight_report=preflight, expected_preflight_sha256=pages.parent_page_report_sha256(preflight),
            output_directory=output, limits=limits)
    assert limits.max_rows is replacement
    assert not (output / MANIFEST).exists()


@pytest.mark.parametrize("failure", ["new_root_parent_fsync", "partial_shard_cleanup_fsync"])
def test_real_opened_file_descriptors_close_even_when_output_fsync_fails(tmp_path, monkeypatch, failure):
    descriptor, preflight = input_report(tmp_path, [{"text": "source"}])
    output = tmp_path / "scan"
    original_open, original_fsync = pages.os.open, pages.os.fsync
    opened, injected = [], []
    def observe_real_open(*arguments, **keywords):
        fd = original_open(*arguments, **keywords)
        opened.append(fd)
        return fd
    def inject_one_real_fsync(fd):
        target = Path(os.readlink("/proc/self/fd/" + str(fd)))
        mode = os.fstat(fd).st_mode
        match = (failure == "new_root_parent_fsync" and stat.S_ISDIR(mode) and target == tmp_path)
        match |= (failure == "partial_shard_cleanup_fsync" and stat.S_ISREG(mode)
            and target.parent == output / "metadata")
        if match and not injected:
            injected.append(str(target))
            raise OSError("independent output fsync failure")
        return original_fsync(fd)
    monkeypatch.setattr(pages.os, "open", observe_real_open)
    monkeypatch.setattr(pages.os, "fsync", inject_one_real_fsync)
    if failure == "partial_shard_cleanup_fsync":
        original_append = pages._MetadataPackageWriter.append
        def interrupt_after_real_partial_append(writer, row):
            original_append(writer, row)
            raise KeyboardInterrupt("independent cancellation after one real shard row")
        monkeypatch.setattr(pages._MetadataPackageWriter, "append", interrupt_after_real_partial_append)
    with pytest.raises((OSError, KeyboardInterrupt)):
        scan(descriptor, preflight, output)
    assert len(injected) == 1 and not (output / MANIFEST).exists()
    for fd in set(opened):
        with pytest.raises(OSError) as closed:
            os.fstat(fd)
        assert closed.value.errno == errno.EBADF


@pytest.mark.parametrize("interruption", ["cancelled", "late_parent_mutation"])
def test_cancellation_or_parent_mutation_refuses_completion_without_erasing_diagnostics(tmp_path, monkeypatch, interruption):
    expected = [{"ipfs_cid": "cid", "title_number": "10", "section_number": "1", "text": "source"}]
    descriptor, preflight = input_report(tmp_path, expected)
    output = tmp_path / "scan"
    original = pages._body
    remaining = sum(len(column["pages"]) for group in preflight["row_groups"] for column in group["columns"])
    def interrupt_after_genuine_decode(stream, column, page, *arguments):
        nonlocal remaining
        result = original(stream, column, page, *arguments)
        remaining -= 1
        if interruption == "cancelled":
            raise KeyboardInterrupt("independent fixture cancellation")
        if remaining == 0:
            path = Path(descriptor["local_path"])
            raw = path.read_bytes()
            path.write_bytes(raw[:8] + bytes([raw[8] ^ 1]) + raw[9:])
        return result
    monkeypatch.setattr(pages, "_body", interrupt_after_genuine_decode)
    with pytest.raises(KeyboardInterrupt if interruption == "cancelled" else ValueError):
        scan(descriptor, preflight, output)
    assert not (output / MANIFEST).exists()


def test_shard_row_limits_preserve_contiguous_complete_ordinal_coverage(tmp_path):
    expected = [{"ipfs_cid": "cid:" + str(i), "title_number": "10", "section_number": str(i),
        "text": "source 雪"} for i in range(11)]
    descriptor, preflight = input_report(tmp_path, expected)
    output = tmp_path / "scan"
    manifest = scan(descriptor, preflight, output, max_rows_per_metadata_shard=3)
    assert [shard["row_count"] for shard in manifest["shards"]] == [3, 3, 3, 2]
    rows = read_shards(manifest, output)
    assert len(rows) == 11
    for ordinal, (row, raw) in enumerate(zip(rows, expected, strict=True)):
        assert_metadata(row, raw, descriptor, ordinal)


@pytest.mark.parametrize("damage", ["descriptor_pin", "preflight_pin", "changed_preflight"])
def test_independent_descriptor_and_preflight_pins_cannot_be_replaced(tmp_path, damage):
    expected = [{"text": "source"}]
    descriptor, preflight = input_report(tmp_path, expected)
    output = tmp_path / "scan"
    descriptor_pin, preflight_pin = sha(descriptor), pages.parent_page_report_sha256(preflight)
    if damage == "descriptor_pin": descriptor_pin = "0" * 64
    elif damage == "preflight_pin": preflight_pin = "0" * 64
    else:
        preflight["page_count"] += 1
        preflight_pin = pages.parent_page_report_sha256(preflight)
    with pytest.raises(ValueError):
        pages.scan_parent_source_metadata(descriptor, expected_descriptor_sha256=descriptor_pin,
            preflight_report=preflight, expected_preflight_sha256=preflight_pin,
            output_directory=output, limits=pages.ParentMetadataScanLimits())
    assert not (output / MANIFEST).exists()


def test_existing_output_is_never_overwritten_or_mistaken_for_fresh_completion(tmp_path):
    descriptor, preflight = input_report(tmp_path, [{"text": "source"}])
    output = tmp_path / "scan"
    output.mkdir()
    target = output / MANIFEST
    sentinel = b'{"complete":false,"fixture":"preexisting"}\n'
    target.write_bytes(sentinel)
    with pytest.raises((ValueError, OSError)):
        scan(descriptor, preflight, output)
    assert target.read_bytes() == sentinel


def pinned_json(variable, expected_bytes, expected_sha256):
    path = Path(os.environ[variable])
    assert path.is_absolute() and path.resolve(strict=True) == path
    raw = path.read_bytes()
    assert len(raw) == expected_bytes and hashlib.sha256(raw).hexdigest() == expected_sha256
    return json.loads(raw), {"path": str(path), "bytes": len(raw), "sha256": expected_sha256}


def test_real_complete_parent60077_rows_requires_separate_owned_scan_enrollment(tmp_path):
    # This assertion is an enrollment marker, not an admission mechanism. The
    # native runner must admit the reviewed scan profile before invoking
    # this case; the current selected32MiB/600second profile must not select it.
    assert os.environ["LEGAL_PARENT_COMPLETE_SCAN_ENROLLED"] == "1"
    pins, pins_ref = pinned_json("LEGAL_PARENT_ROW_PINS", 3439,
        "1400269e4a664d431dd79649c9014ee200e6466ca87c1fbe423127288271e2e1")
    preflight, preflight_ref = pinned_json("LEGAL_PARENT_COMPLETE_PREFLIGHT", 385155,
        "d63c65e876573a6824658c28e4b8511c8e990da81563805d3de5beac0b630e22")
    retained, retained_ref = pinned_json("LEGAL_PARENT_EXPECTED_SECTIONS", 123063,
        "14305627bc8148ea409d97acbb7c78610f3f5e37cd5d6ca63f1bcfd69e96db5e")
    descriptor = pins["source_descriptor"]
    assert descriptor["bytes"] == 374277662 and descriptor["row_count"] == 60077
    assert descriptor["sha256"] == "4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8"
    assert descriptor["revision"] == "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e"
    assert preflight["descriptor"] == descriptor and pins["row_ordinals"] == REAL_ORDINALS
    output = tmp_path / "real-complete-parent"
    manifest = scan(descriptor, preflight, output)
    assert_manifest(manifest, output)
    selected_hashes = dict(zip(REAL_ORDINALS, pins["expected_row_sha256s"], strict=True))
    selected_sections = {row["parquet_row_index"]: row for row in retained["source_sections"]}
    count, canonical_bytes, observed_selected = 0, 0, {}
    for shard in manifest["shards"]:
        assert shard["start_ordinal"] == count
        path = output / shard["relative_path"]
        assert path.resolve(strict=True) == path and output in path.parents
        raw = path.read_bytes()
        assert len(raw) == shard["bytes"] and hashlib.sha256(raw).hexdigest() == shard["sha256"]
        shard_count = 0
        for line in raw.splitlines():
            row = json.loads(line)
            key = physical_key(descriptor, count)
            assert row["physical_key"] == key and row["physical_section_id"] == "sha256:" + sha(key)
            assert row["group_id"] is row["split"] is row["inference_view"] is None
            assert type(row["training_mask"]) is type(row["evaluation_gold_mask"]) is int
            assert row["training_mask"] == row["evaluation_gold_mask"] == 0
            assert row["authority"] and all(value is False for value in row["authority"].values())
            canonical_bytes += row["raw_row_canonical_bytes"]
            if count in selected_hashes:
                section = selected_sections[count]
                text = section["text"]
                assert row["full_raw_row_sha256"] == selected_hashes[count]
                assert row["text"] == {"sha256": section["text_sha256"],
                    "utf8_bytes": len(text.encode()), "unicode_characters": len(text)}
                assert row["normalized_content_sha256"] == hashlib.sha256(" ".join(text.split()).casefold().encode()).hexdigest()
                assert row["observed_identity"]["ipfs_cid"] == section["entry_cid"]
                observed_selected[count] = row["full_raw_row_sha256"]
            count += 1
            shard_count += 1
        assert shard_count == shard["row_count"] and shard["end_ordinal"] == count
    assert count == 60077 and observed_selected == selected_hashes
    assert manifest["coverage"] == {"declared_parent_rows": 60077, "replayed_parent_rows": 60077,
        "whole_parent_inventoried": True}
    assert manifest["row_count"] == 60077 and manifest["page_count"] == 423
    assert manifest["decoded_page_bytes"] == 1169575763
    assert manifest["raw_row_canonical_bytes"] == canonical_bytes
    manifest_raw = (output / MANIFEST).read_bytes()
    evidence = {"schema": "legal-parent-complete-metadata-engineering-evidence/v1",
        "originals": {"independent_selected_row_pins": pins_ref, "complete_preflight": preflight_ref,
            "retained_sections_assertion_only": retained_ref},
        "manifest": {"path": str(output / MANIFEST), "bytes": len(manifest_raw),
            "sha256": hashlib.sha256(manifest_raw).hexdigest()},
        "complete_parent_rows": count, "source_columns": 45,
        "independent_selected_row_hashes_checked": 13, "decoded_page_bytes": 1169575763,
        "raw_row_canonical_bytes": canonical_bytes, "large_parent_copied": False,
        "training_mask": 0, "evaluation_gold_mask": 0, "inference_view": None,
        "real_source_partitions_constructed": False, "source_authority_authenticated": False,
        "source_semantics_verified": False, "original_producer_occurrence_attested": False,
        "model_executed": False, "training_executed": False, "Lean_admitted": False,
        "convergence_proved": False,
        "scope": "Complete physical parent metadata coverage only under a separately owned/admitted scan profile. Thirteen independently retained row hashes and source texts are assertions only; no current-release partition, original occurrence, source meaning, training or proof authority is supplied."}
    with (tmp_path / EVIDENCE_NAME).open("x") as stream:
        json.dump(evidence, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
