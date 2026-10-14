"""Independent Arrow-written fixtures and handcrafted Parquet/Snappy encodings."""
from copy import deepcopy
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_parent_parquet_pages as pages
from ipfs_datasets_py.logic.autoformal import legal_producer_lineage as legacy


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def uvar(value):
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128); value >>= 7
    out.append(value)
    return bytes(out)


def zvar(value):
    return uvar(value * 2 if value >= 0 else -value * 2 - 1)


def header(*, count=3, raw_size=30, compressed_size=20, encoding=0):
    # Compact-Thrift PageHeader: fields1/2/3 I32, field5 STRUCT;
    # DataPageHeader required fields1/2/3/4 I32, then each STOP.
    return b"\x15" + zvar(0) + b"\x15" + zvar(raw_size) + b"\x15" + zvar(compressed_size) + b"\x2c" + (
        b"\x15" + zvar(count) + b"\x15" + zvar(encoding) + b"\x15\x06\x15\x06\x00\x00")


def snappy_literal(value):
    n = len(value)
    if n <= 60:
        tag = bytes([(n - 1) << 2])
    else:
        width = max(1, ((n - 1).bit_length() + 7) // 8)
        tag = bytes([(59 + width) << 2]) + (n - 1).to_bytes(width, "little")
    return uvar(n) + tag + value


def fixture(tmp_path, *, dictionary=True, groups=7, version="1.0", rows=31):
    schema = pa.schema([("ipfs_cid", pa.string()), ("title_number", pa.string()), ("section_number", pa.string()),
        ("text", pa.string()), ("counter", pa.int64()), ("nullable", pa.string()),
        ("candidate_urls", pa.list_(pa.string())), ("archived_source_urls", pa.list_(pa.null())),
        ("preferred_parquet_names", pa.list_(pa.string())), *[("extra_" + str(i), pa.string()) for i in range(36)]])
    expected = []
    for i in range(rows):
        expected.append({"ipfs_cid": "cid:" + str(i), "title_number": "10", "section_number": str(i + 1),
            "text": "Café 雪 " + str(i) + "." + "x" * 200, "counter": i - 17,
            "nullable": None if i % 2 else "", "candidate_urls": [None, [], [None], ["é", None, "雪"]][i % 4],
            "archived_source_urls": [None, [], [None], [None, None]][i % 4],
            "preferred_parquet_names": ["same", "same"], **{"extra_" + str(j): "literal:" + str(j) for j in range(36)}})
    path = tmp_path / "laws.parquet"
    pq.write_table(pa.Table.from_pylist(expected, schema=schema), path, compression="snappy",
        use_dictionary=dictionary, data_page_version=version, data_page_size=1024,
        write_batch_size=4, row_group_size=groups)
    descriptor = {"repository": "fixture/parent", "revision": "a" * 40, "path_in_repo": "laws.parquet",
        "local_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
        "row_count": rows, "profile": legacy.PARENT_PROFILE}
    return path, descriptor, expected


def reader_inputs(descriptor, expected, ordinals):
    preflight = pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=digest(descriptor))
    return {"expected_descriptor_sha256": digest(descriptor), "preflight_report": preflight,
        "expected_preflight_sha256": pages.parent_page_report_sha256(preflight), "row_ordinals": ordinals,
        "expected_row_sha256s": [digest(expected[i]) for i in ordinals]}


@pytest.mark.parametrize("dictionary", [False, True])
def test_all_45_columns_sparse_physical_rows_equal_independent_Arrow_oracle(tmp_path, dictionary):
    path, descriptor, expected = fixture(tmp_path, dictionary=dictionary)
    oracle = pq.read_table(path).to_pylist()
    assert oracle == expected
    ordinals = [0, 3, 6, 7, 18, 30]
    args = reader_inputs(descriptor, expected, ordinals)
    report = pages.read_selected_parent_rows(descriptor, **args)
    assert [row["row_ordinal"] for row in report["rows"]] == ordinals
    assert [row["raw_row"] for row in report["rows"]] == [oracle[i] for i in ordinals]
    assert [row["raw_row_sha256"] for row in report["rows"]] == args["expected_row_sha256s"]
    assert all(len(row["raw_row"]) == 45 for row in report["rows"])
    assert [row["row_group"] for row in report["rows"]] == [i // 7 for i in ordinals]
    assert [row["row_group_ordinal"] for row in report["rows"]] == [i % 7 for i in ordinals]
    assert all(value is False for value in report["authority"].values())
    assert pages.parent_row_report_sha256(report) == digest(report)
    pages.validate_selected_parent_rows(report, descriptor, expected_report_sha256=digest(report), **args)


def test_null_empty_and_null_element_lists_are_distinct_not_coerced(tmp_path):
    _, descriptor, expected = fixture(tmp_path, groups=31)
    args = reader_inputs(descriptor, expected, [0, 1, 2, 3])
    rows = pages.read_selected_parent_rows(descriptor, **args)["rows"]
    assert [r["raw_row"]["candidate_urls"] for r in rows] == [None, [], [None], ["é", None, "雪"]]
    assert [r["raw_row"]["archived_source_urls"] for r in rows] == [None, [], [None], [None, None]]
    assert rows[0]["raw_row"]["nullable"] == "" and rows[1]["raw_row"]["nullable"] is None


def test_repeated_identical_rows_remain_distinct_physical_occurrences(tmp_path):
    path, descriptor, expected = fixture(tmp_path, rows=4)
    expected[1] = deepcopy(expected[0])
    pq.write_table(pa.Table.from_pylist(expected), path, compression="snappy", data_page_version="1.0")
    descriptor.update(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    report = pages.read_selected_parent_rows(descriptor, **reader_inputs(descriptor, expected, [0, 1]))
    assert report["rows"][0]["raw_row_sha256"] == report["rows"][1]["raw_row_sha256"]
    assert [r["row_ordinal"] for r in report["rows"]] == [0, 1]


def test_dictionary_fallback_multiple_pages_match_independent_writer(tmp_path):
    _, descriptor, expected = fixture(tmp_path, groups=31)
    path = tmp_path / "fallback.parquet"
    pq.write_table(pa.Table.from_pylist(expected), path, compression="snappy", use_dictionary=True,
        dictionary_pagesize_limit=64, data_page_size=1024, write_batch_size=2, data_page_version="1.0")
    descriptor.update(local_path=str(path), path_in_repo=path.name, bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    ordinals = [0, 3, 18, 30]
    report = pages.read_selected_parent_rows(descriptor, **reader_inputs(descriptor, expected, ordinals))
    assert [r["raw_row"] for r in report["rows"]] == [expected[i] for i in ordinals]


def test_compact_header_consumption_is_exact_and_does_not_consume_payload():
    raw = header() + b"payload bytes outside header"
    parsed, consumed = pages.parse_page_header(raw)
    assert consumed == len(header())
    assert parsed[1] == 0 and parsed[2] == 30 and parsed[3] == 20
    assert parsed[5] == {1: 3, 2: 0, 3: 3, 4: 3}


@pytest.mark.parametrize("raw", [b"", b"\x15", b"\x15\x80" * 20, b"\xfc\x00", header()[:-1]])
def test_malformed_compact_headers_fail_before_payload_decoding(raw):
    with pytest.raises(ValueError): pages.parse_page_header(raw)


def test_compact_header_byte_ceiling_precedes_complete_parse():
    with pytest.raises(ValueError): pages.parse_page_header(header(), max_header_bytes=4)


@pytest.mark.parametrize("length", [1, 59, 60, 61, 255, 256, 65537])
def test_handcrafted_Snappy_literal_lengths_are_exact(length):
    raw = (b"abc\x00" * ((length + 3) // 4))[:length]
    assert pages.decode_snappy_page(snappy_literal(raw), expected_size=length) == raw


@pytest.mark.parametrize("kind", [1, 2, 3])
def test_Snappy_copy_forms_allow_overlapping_copy_without_wrong_identity(kind):
    # One literal 'a', then overlapping offset-one copy emits another seven.
    tag = bytes([1 | ((7 - 4) << 2), 1]) if kind == 1 else bytes([kind | ((7 - 1) << 2)]) + (1).to_bytes(2 if kind == 2 else 4, "little")
    assert pages.decode_snappy_page(b"\x08\x00a" + tag, expected_size=8) == b"a" * 8


@pytest.mark.parametrize("payload,expected", [(b"\x09\x00a", 8), (b"\x08\x02\x01\x00", 8),
    (b"\x08\x02\x00\x00", 8), (b"\x01\x00a\x00b", 1), (b"\x80" * 8, 1), (b"\x05\xf0", 5)])
def test_Snappy_size_offset_truncation_and_trailing_bytes_are_closed(payload, expected):
    with pytest.raises(ValueError): pages.decode_snappy_page(payload, expected_size=expected)


def test_Snappy_declared_expansion_bomb_rejected_before_output_allocation():
    with pytest.raises(ValueError):
        pages.decode_snappy_page(uvar(2**31), expected_size=2**31, max_output_bytes=1024)


def test_RLE_and_bitpacked_values_follow_independent_little_endian_encoding():
    assert pages.decode_rle_values(uvar(9 << 1) + b"\x02", bit_width=2, count=9) == [2] * 9
    # Apache format example: values0..7 at width3 packed as88 c6 fa.
    assert pages.decode_rle_values(b"\x03\x88\xc6\xfa", bit_width=3, count=8) == list(range(8))
    assert pages.decode_rle_values(b"\x03\x88\xc6\xfa", bit_width=3, count=5) == list(range(5))


@pytest.mark.parametrize("raw,width,count", [(b"\x00", 1, 1), (b"\x02", 3, 1),
    (b"\x03\x01", 3, 8), (b"\x02\x04", 2, 1), (b"\x04\x01", 1, 1), (b"\x02\x01\x02\x01", 1, 1)])
def test_RLE_invalid_run_lengths_values_counts_and_trailing_data_refused(raw, width, count):
    with pytest.raises(ValueError): pages.decode_rle_values(raw, bit_width=width, count=count)


def test_RLE_huge_run_and_count_ceiling_refused_before_population_creation():
    with pytest.raises(ValueError):
        pages.decode_rle_values(uvar((2**30) << 1) + b"\x00", bit_width=1, count=2**30, max_values=16)


@pytest.mark.parametrize("damage", ["file_hash", "bytes", "descriptor_pin", "row_hash", "ordinals_order", "ordinals_duplicate", "ordinals_missing", "preflight_pin"])
def test_independent_file_page_population_and_selected_row_pins_cannot_be_retargeted(tmp_path, damage):
    _, descriptor, expected = fixture(tmp_path)
    args = reader_inputs(descriptor, expected, [0, 7])
    if damage == "file_hash": descriptor["sha256"] = "0" * 64; args["expected_descriptor_sha256"] = digest(descriptor)
    elif damage == "bytes": descriptor["bytes"] += 1; args["expected_descriptor_sha256"] = digest(descriptor)
    elif damage == "descriptor_pin": args["expected_descriptor_sha256"] = "0" * 64
    elif damage == "row_hash": args["expected_row_sha256s"][0] = "0" * 64
    elif damage == "ordinals_order": args["row_ordinals"].reverse()
    elif damage == "ordinals_duplicate": args["row_ordinals"] = [0, 0]
    elif damage == "ordinals_missing": args["row_ordinals"].pop()
    else: args["expected_preflight_sha256"] = "0" * 64
    with pytest.raises(ValueError): pages.read_selected_parent_rows(descriptor, **args)


def test_preflight_and_selected_report_resealing_cannot_replace_regeneration(tmp_path):
    _, descriptor, expected = fixture(tmp_path)
    args = reader_inputs(descriptor, expected, [0, 7])
    preflight = deepcopy(args["preflight_report"])
    preflight["authority"][next(iter(preflight["authority"]))] = True
    with pytest.raises(ValueError):
        pages.validate_parent_page_preflight(preflight, descriptor, expected_report_sha256=digest(preflight), expected_descriptor_sha256=digest(descriptor))
    report = pages.read_selected_parent_rows(descriptor, **args)
    report["rows"][0]["raw_row"]["extra_35"] = "forged unknown field"
    with pytest.raises(ValueError): pages.validate_selected_parent_rows(report, descriptor, expected_report_sha256=digest(report), **args)


def test_unsupported_DATA_PAGE_V2_never_falls_back_to_unbounded_reader(tmp_path, monkeypatch):
    _, descriptor, _ = fixture(tmp_path, version="2.0")
    monkeypatch.setattr(pq.ParquetFile, "iter_batches", lambda *a, **kw: pytest.fail("Arrow decoder fallback invoked"))
    with pytest.raises(ValueError): pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=digest(descriptor))


def test_preflight_page_size_limit_precedes_codec_invocation(tmp_path, monkeypatch):
    _, descriptor, _ = fixture(tmp_path)
    monkeypatch.setattr(pages, "decode_snappy_page", lambda *a, **kw: pytest.fail("codec invoked before page bound"))
    with pytest.raises(ValueError):
        pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=digest(descriptor), limits={"max_page_uncompressed_bytes": 1})


def test_original_v1_group_guard_is_preserved_even_for_new_readable_fixture(tmp_path, monkeypatch):
    _, descriptor, expected = fixture(tmp_path)
    monkeypatch.setattr(legacy, "MAX_PARQUET_GROUP_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(ValueError): legacy.read_parent_row_witnesses(descriptor, expected_descriptor_sha256=digest(descriptor), row_ordinals=[0])
    report = pages.read_selected_parent_rows(descriptor, **reader_inputs(descriptor, expected, [0]))
    assert report["rows"][0]["raw_row"] == expected[0]


@pytest.mark.parametrize("shape,bound", [
    ("repeated_list", "max_row_bytes"),
    ("repeated_list", "max_selected_bytes"),
    ("repeated_scalars", "max_selected_bytes"),
])
def test_dictionary_expansion_budget_precedes_selected_value_copies(tmp_path, monkeypatch, shape, bound):
    # Compressed dictionary IDs can refer repeatedly to a much larger value.
    # A page/dictionary byte cap alone does not bound the selected expansion.
    value = "x" * 4096
    expected = [{"values": [value] * 8}] if shape == "repeated_list" else [{"value": value} for _ in range(8)]
    path = tmp_path / "repeated-dictionary.parquet"
    pq.write_table(pa.Table.from_pylist(expected), path, compression="snappy",
        use_dictionary=True, data_page_version="1.0")
    descriptor = {"repository": "fixture/parent", "revision": "a" * 40, "path_in_repo": path.name,
        "local_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size, "row_count": len(expected), "profile": legacy.PARENT_PROFILE}
    limits = {bound: 8192}
    preflight = pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=digest(descriptor), limits=limits)
    converted = []
    original = pages._selected_value
    def observe_copy(raw, kind, *args, **kwargs):
        converted.append(len(raw))
        return original(raw, kind, *args, **kwargs)
    monkeypatch.setattr(pages, "_selected_value", observe_copy)
    with pytest.raises(ValueError):
        pages.read_selected_parent_rows(descriptor, expected_descriptor_sha256=digest(descriptor),
            preflight_report=preflight, expected_preflight_sha256=digest(preflight),
            row_ordinals=list(range(len(expected))), expected_row_sha256s=[digest(row) for row in expected], limits=limits)
    # The offending value must be refused before its materialization, rather
    # than after retaining all eight copies and serializing a completed column.
    assert sum(converted) <= limits[bound]
    assert len(converted) < 8


def compact_struct(fields):
    """Small independent typed compact-Thrift writer for physical fixtures."""
    def encode(kind, value):
        if kind in (5, 6): return zvar(value)
        if kind == 8: return uvar(len(value)) + value
        if kind == 12: return compact_struct(value)
        if kind == 9:
            element, values = value
            prefix = bytes([(len(values) << 4) | element]) if len(values) < 15 else bytes([0xf0 | element]) + uvar(len(values))
            return prefix + b"".join(encode(element, item) for item in values)
        raise AssertionError("fixture writer unsupported kind")
    result = bytearray(); previous = 0
    for key, kind, value in fields:
        delta = key - previous
        result.extend(bytes([(delta << 4) | kind]) if 0 < delta < 16 else bytes([kind]) + zvar(key))
        result.extend(encode(kind, value)); previous = key
    result.append(0)
    return bytes(result)


def physical_plain_fixture(tmp_path, *, list_profile=False, conflicting=False, continuation_after_empty=False):
    """A complete file, including independent footer offsets and level bytes."""
    name = b"values" if list_profile else b"value"
    root = [(4, 8, b"schema"), (5, 5, 1)]
    string_annotation = [(1, 12, [])]
    list_annotation = [(3, 12, [])]
    leaf = [(1, 5, 6), (3, 5, 1), (4, 8, b"element" if list_profile else name), (6, 5, 0),
        (10, 12, string_annotation)]
    if list_profile:
        outer = [(3, 5, 1), (4, 8, name), (5, 5, 1), (6, 5, 3),
            (10, 12, string_annotation if conflicting else list_annotation)]
        repeated = [(3, 5, 2), (4, 8, b"list"), (5, 5, 1)]
        schema = [root, outer, repeated, leaf]
        path = [name, b"list", b"element"]
        reps = b"\x02\x00\x02\x01" if continuation_after_empty else b"\x02\x00"
        defs = b"\x02\x01\x02\x03" if continuation_after_empty else b"\x02\x03"
        body = len(reps).to_bytes(4, "little") + reps
    else:
        if conflicting: leaf[-1] = (10, 12, list_annotation)
        schema = [root, leaf]; path = [name]; defs = b"\x02\x01"; body = b""
    body += len(defs).to_bytes(4, "little") + defs + (1).to_bytes(4, "little") + b"x"
    count = 2 if continuation_after_empty else 1
    page = header(count=count, raw_size=len(body), compressed_size=len(body)) + body
    metadata = [(1, 5, 6), (2, 9, (5, [0, 3])), (3, 9, (8, path)), (4, 5, 0),
        (5, 6, count), (6, 6, len(page)), (7, 6, len(page)), (9, 6, 4)]
    chunk = [(3, 12, metadata)]
    group = [(1, 9, (12, [chunk])), (2, 6, len(page)), (3, 6, 1)]
    footer = compact_struct([(1, 5, 1), (2, 9, (12, schema)), (3, 6, 1), (4, 9, (12, [group]))])
    target = tmp_path / "handcrafted.parquet"
    target.write_bytes(b"PAR1" + page + footer + len(footer).to_bytes(4, "little") + b"PAR1")
    descriptor = {"repository": "fixture/parent", "revision": "a" * 40, "path_in_repo": target.name,
        "local_path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "bytes": target.stat().st_size, "row_count": 1, "profile": legacy.PARENT_PROFILE}
    return descriptor, [{name.decode(): ["x"] if list_profile else "x"}]


def test_32bit_Snappy_length_varint_cannot_consume_a_sixth_zero_byte():
    with pytest.raises(ValueError):
        pages.decode_snappy_page(b"\x80\x80\x80\x80\x80\x00", expected_size=0)


@pytest.mark.parametrize("list_profile", [False, True])
def test_conflicting_converted_and_logical_schema_annotations_are_not_OR_aliases(tmp_path, list_profile, monkeypatch):
    descriptor, expected = physical_plain_fixture(tmp_path, list_profile=list_profile)
    assert [row["raw_row"] for row in pages.read_selected_parent_rows(descriptor, **reader_inputs(descriptor, expected, [0]))["rows"]] == expected
    descriptor, _ = physical_plain_fixture(tmp_path, list_profile=list_profile, conflicting=True)
    monkeypatch.setattr(pages, "_selected_value", lambda *a, **kw: pytest.fail("conflicting schema reached value materialization"))
    with pytest.raises(ValueError):
        pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=digest(descriptor))


def test_repetition_one_cannot_continue_an_empty_list_placeholder(tmp_path, monkeypatch):
    descriptor, expected = physical_plain_fixture(tmp_path, list_profile=True)
    assert pages.read_selected_parent_rows(descriptor, **reader_inputs(descriptor, expected, [0]))["rows"][0]["raw_row"] == expected[0]
    descriptor, expected = physical_plain_fixture(tmp_path, list_profile=True, continuation_after_empty=True)
    args = reader_inputs(descriptor, expected, [0])
    monkeypatch.setattr(pages, "_selected_value", lambda *a, **kw: pytest.fail("invalid empty-list continuation materialized a value"))
    with pytest.raises(ValueError):
        pages.read_selected_parent_rows(descriptor, **args)
