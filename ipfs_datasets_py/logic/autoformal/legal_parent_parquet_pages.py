"""Bounded source-byte replay of selected physical rows in a Parquet profile.

The supported profile is plaintext Parquet, version-1 data pages, optional
UTF-8/INT64/null INT32 fields and optional three-level string/null lists, with
PLAIN or RLE_DICTIONARY values and RLE levels. SNAPPY is decoded as a bounded
raw block; UNCOMPRESSED is also supported. No Arrow row-group decoder runs.

Page size fields exclude headers, while column totals include them. Encoded
page bytes do not bound expanded dictionary values; selected values/lists and
whole retained rows therefore have separate limits. This is an explicit parser
input/output contract, not an operating-system memory quota. Byte/row custody
does not establish legal meaning, historical execution, official edition,
original character coordinates, training permission or Lean proof.

Primary format references:
https://github.com/apache/parquet-format/blob/master/src/main/thrift/parquet.thrift
https://github.com/apache/parquet-format/blob/master/Encodings.md
https://github.com/apache/thrift/blob/master/doc/specs/thrift-compact-protocol.md
https://github.com/google/snappy/blob/main/format_description.txt
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import zlib

PAGE_SCHEMA = "legal-parent-parquet-page-preflight/v1"
ROW_SCHEMA = "legal-parent-parquet-selected-rows/v1"
PROFILE = "plaintext_v1_optional_utf8_int64_null_three_level_lists/v1"
PARENT_PROFILE = "legacy_laws_parquet/v1"
FILE_FIELDS = {"repository", "revision", "path_in_repo", "local_path", "sha256", "bytes", "row_count", "profile"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REV = re.compile(r"[0-9a-f]{40}\Z")
DEFAULT_LIMITS = {
    "max_file_bytes": 512 * 1024**2, "max_footer_bytes": 1024**2,
    "max_header_bytes": 64 * 1024, "max_pages": 8192, "max_columns": 64,
    "max_row_groups": 128, "max_rows": 100_000, "max_column_values": 1_000_000,
    "max_page_compressed_bytes": 16 * 1024**2, "max_page_uncompressed_bytes": 32 * 1024**2,
    "max_dictionary_bytes": 16 * 1024**2, "max_page_values": 131_072,
    "max_selected_rows": 32, "max_selected_bytes": 32 * 1024**2,
    "max_row_bytes": 8 * 1024**2, "max_value_bytes": 8 * 1024**2,
    "max_list_values": 4096, "max_decoded_bytes": 256 * 1024**2,
}
AUTHORITY = dict.fromkeys(("historical_job_lineage_verified", "model_invocation_verified",
    "original_character_occurrence_attested", "official_edition_correspondence_verified",
    "source_authority_authenticated", "source_semantics_verified", "context_closure_verified",
    "authenticated_review_verified", "training_qualified", "proof_authority",
    "Lean_kernel_admission", "admitted", "formalized"), False)


class ParentParquetPagesError(ValueError):
    """Independent custody, finite bounds or the admitted format profile differ."""


def _need(ok, message):
    if not ok: raise ParentParquetPagesError(message)


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value), "independent lowercase SHA256 required")


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ParentParquetPagesError("finite canonical UTF-8 report required") from exc
    _need(len(raw) <= 64 * 1024**2, "complete report byte bound exceeded; no truncation")
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def parent_page_report_sha256(report):
    """Canonical SHA256 of the entire page report, INCLUDING its internal seal."""
    return _digest(report)


def parent_row_report_sha256(report):
    """Canonical SHA256 of the entire row report, INCLUDING its internal seal."""
    return _digest(report)


def _limits(values):
    _need(values is None or type(values) is dict, "lower-only limits object required")
    result = dict(DEFAULT_LIMITS)
    for key, value in (values or {}).items():
        _need(key in result and type(value) is int and 0 < value <= result[key], "unknown or raised parser limit: " + str(key))
        result[key] = value
    return result


def _descriptor(value, pin, limits):
    _sha(pin)
    _need(type(value) is dict and set(value) == FILE_FIELDS, "closed parent descriptor required")
    _sha(value["sha256"])
    _need(type(value["repository"]) is str and 0 < len(value["repository"].encode()) <= 256
        and bool(value["repository"].strip()), "literal repository required")
    _need(type(value["revision"]) is str and _REV.fullmatch(value["revision"]), "literal full revision required; no expansion")
    rel = value["path_in_repo"]
    _need(type(rel) is str and 0 < len(rel.encode()) <= 2048 and "\\" not in rel
        and not PurePosixPath(rel).is_absolute() and all(p not in ("", ".", "..") for p in rel.split("/")), "literal safe source repository path required")
    _need(type(value["local_path"]) is str and Path(value["local_path"]).is_absolute(), "explicit absolute parent path required")
    _need(type(value["bytes"]) is int and 12 <= value["bytes"] <= limits["max_file_bytes"]
        and type(value["row_count"]) is int and 0 < value["row_count"] <= limits["max_rows"]
        and value["profile"] == PARENT_PROFILE, "bounded supported parent descriptor required")
    _need(_digest(value) == pin, "independent complete parent descriptor differs")
    return deepcopy(value)


@contextmanager
def _opened(descriptor):
    path = Path(descriptor["local_path"])
    _need(path.resolve(strict=True) == path, "parent path is aliased")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        _need(stat.S_ISREG(before.st_mode) and before.st_size == descriptor["bytes"], "parent regularity/declared size differs")
        def guard():
            _need(identity(before) == identity(os.fstat(stream.fileno())) == identity(path.lstat())
                and path.resolve(strict=True) == path, "parent FD/path changed")
        def digest():
            stream.seek(0); hasher = hashlib.sha256(); size = 0
            while True:
                chunk = stream.read(min(1024**2, descriptor["bytes"] - size + 1))
                if not chunk: break
                size += len(chunk)
                _need(size <= descriptor["bytes"], "parent grew beyond independent size")
                hasher.update(chunk)
            _need(size == descriptor["bytes"] and hasher.hexdigest() == descriptor["sha256"], "independent complete parent SHA256 differs")
            guard(); stream.seek(0)
        guard(); digest()
        try: yield stream
        finally: guard(); digest()


class _Compact:
    """Budgeted compact-Thrift structs, with exact duplicate/type checks."""
    def __init__(self, raw, *, maximum, collection=256, nodes=65_536):
        self.raw = memoryview(raw); self.offset = 0; self.maximum = maximum
        self.collection = collection; self.nodes = nodes; self.used = 0

    def take(self, length):
        _need(type(length) is int and 0 <= length <= self.maximum
            and self.offset + length <= min(len(self.raw), self.maximum), "compact-Thrift byte bound/truncation")
        result = self.raw[self.offset:self.offset + length]; self.offset += length
        return result

    def byte(self): return self.take(1)[0]

    def varint(self, bits=64):
        value = 0
        for shift in range(0, bits, 7):
            byte = self.byte(); value |= (byte & 127) << shift
            if not byte & 128:
                _need(value < 1 << bits, "compact-Thrift varint overflow")
                return value
        raise ParentParquetPagesError("compact-Thrift varint length exceeded")

    def signed(self, bits):
        value = self.varint(bits)
        return (value >> 1) ^ -(value & 1)

    def value(self, kind, depth):
        self.used += 1
        _need(depth <= 12 and self.used <= self.nodes, "compact-Thrift structure budget exceeded")
        if kind in (1, 2): return kind == 1
        if kind == 3: return int.from_bytes(self.take(1), "little", signed=True)
        if kind in (4, 5, 6): return self.signed({4: 16, 5: 32, 6: 64}[kind])
        if kind == 7: return struct.unpack("<d", self.take(8))[0]
        if kind == 8: return bytes(self.take(self.varint(32)))
        if kind in (9, 10):
            header = self.byte(); size = header >> 4; element = header & 15
            if size == 15: size = self.varint(32)
            _need(size <= self.collection, "compact-Thrift collection bound exceeded")
            return [self.value(element, depth + 1) for _ in range(size)]
        if kind == 11:
            size = self.varint(32)
            _need(size <= self.collection, "compact-Thrift map bound exceeded")
            if not size: return []
            kinds = self.byte()
            return [[self.value(kinds >> 4, depth + 1), self.value(kinds & 15, depth + 1)] for _ in range(size)]
        if kind == 12: return self.struct(depth + 1)
        raise ParentParquetPagesError("unsupported compact-Thrift field type")

    def struct(self, depth=0):
        result = {}; previous = 0
        while True:
            header = self.byte()
            if header == 0: return result
            kind = header & 15; delta = header >> 4
            _need(kind != 0, "malformed compact-Thrift STOP field")
            key = previous + delta if delta else self.signed(16)
            _need(0 < key <= 32767 and key not in result, "duplicate/invalid compact-Thrift field identity")
            previous = key; result[key] = self.value(kind, depth)


def parse_page_header(raw, *, max_header_bytes=64 * 1024):
    """Return (numeric-field-ID struct, consumed bytes), with bounded parsing."""
    _need(type(raw) is bytes and type(max_header_bytes) is int
        and 0 < max_header_bytes <= DEFAULT_LIMITS["max_header_bytes"], "bounded page header bytes required")
    reader = _Compact(raw, maximum=max_header_bytes, collection=64, nodes=1024)
    return reader.struct(), reader.offset


def _varint(raw, offset, bits=32):
    value = 0
    for shift in range(0, bits, 7):
        _need(offset < len(raw), "truncated unsigned varint")
        byte = raw[offset]; offset += 1; value |= (byte & 127) << shift
        if not byte & 128:
            _need(value < 1 << bits, "unsigned varint overflow")
            return value, offset
    raise ParentParquetPagesError("unsigned varint length exceeded")


def decode_snappy_page(payload, *, expected_size, max_output_bytes=32 * 1024**2):
    """Decode a raw Snappy block; guard its embedded length before allocation."""
    _need(type(payload) is bytes and len(payload) <= DEFAULT_LIMITS["max_page_compressed_bytes"]
        and type(expected_size) is int and type(max_output_bytes) is int
        and 0 <= expected_size <= max_output_bytes <= DEFAULT_LIMITS["max_page_uncompressed_bytes"], "bounded Snappy input/output required")
    length, offset = _varint(payload, 0)
    _need(length == expected_size, "Snappy embedded output length differs before allocation")
    output = bytearray()
    while offset < len(payload):
        tag = payload[offset]; offset += 1; kind = tag & 3
        if kind == 0:
            length = (tag >> 2) + 1
            if length >= 61:
                width = length - 60
                _need(offset + width <= len(payload), "truncated Snappy literal length")
                length = int.from_bytes(payload[offset:offset + width], "little") + 1; offset += width
            _need(offset + length <= len(payload) and len(output) + length <= expected_size, "Snappy literal exceeds exact input/output bound")
            output.extend(payload[offset:offset + length]); offset += length
        else:
            if kind == 1:
                _need(offset < len(payload), "truncated Snappy copy")
                length = ((tag >> 2) & 7) + 4; distance = ((tag & 224) << 3) | payload[offset]; offset += 1
            else:
                width = 2 if kind == 2 else 4
                _need(offset + width <= len(payload), "truncated Snappy copy offset")
                length = (tag >> 2) + 1; distance = int.from_bytes(payload[offset:offset + width], "little"); offset += width
            _need(0 < distance <= len(output) and len(output) + length <= expected_size, "Snappy copy distance/output bound differs")
            start = len(output) - distance
            block = output[start:start + min(length, distance)]
            output.extend((block * ((length + len(block) - 1) // len(block)))[:length])
    _need(len(output) == expected_size, "Snappy output ended before declared length")
    return bytes(output)


def decode_rle_values(raw, *, bit_width, count, max_values=131_072):
    """Bounded RLE/bit-packed hybrid values (without the outer length prefix)."""
    _need(type(raw) is bytes and type(bit_width) is int and 0 <= bit_width <= 32
        and type(count) is int and type(max_values) is int
        and 0 <= count <= max_values <= DEFAULT_LIMITS["max_page_values"], "RLE cardinality/bit-width bound exceeded before allocation")
    output = []; offset = 0
    while offset < len(raw):
        header, offset = _varint(raw, offset)
        _need(header > 0, "zero RLE run is malformed")
        if header & 1:
            run = (header >> 1) * 8; size = run * bit_width // 8
            _need(run <= count - len(output) + 7 and offset + size <= len(raw), "bit-packed run cardinality/input bound exceeded")
            number = min(run, count - len(output))
            for index in range(number):
                bit = index * bit_width; start = offset + bit // 8; width = (bit % 8 + bit_width + 7) // 8
                value = (int.from_bytes(raw[start:start + width], "little") >> (bit % 8)) & ((1 << bit_width) - 1)
                output.append(value)
            offset += size
            _need(run == number or offset == len(raw), "bit-packed padding before stream end")
        else:
            run = header >> 1; width = (bit_width + 7) // 8
            _need(run <= count - len(output) and offset + width <= len(raw), "RLE run cardinality/input bound exceeded before allocation")
            value = int.from_bytes(raw[offset:offset + width], "little"); offset += width
            _need(value < 1 << bit_width, "RLE value exceeds bit width")
            output.extend([value] * run)
    _need(len(output) == count, "RLE logical value count differs")
    return output


def _json_metadata(value):
    if type(value) is bytes: return {"base64": base64.b64encode(value).decode("ascii")}
    if type(value) is dict: return {str(k): _json_metadata(v) for k, v in value.items()}
    if type(value) is list: return [_json_metadata(v) for v in value]
    return value


def _text(value, purpose):
    _need(type(value) is bytes and 0 < len(value) <= 256, "bounded literal " + purpose + " required")
    try: return value.decode("utf-8", errors="strict")
    except UnicodeError as exc: raise ParentParquetPagesError("invalid UTF-8 " + purpose) from exc


def _is_string(node):
    return (type(node.get(1)) is int and node[1] == 6
        and (6 in node or 10 in node)
        and (6 not in node or type(node[6]) is int and node[6] == 0)
        and (10 not in node or node[10] == {1: {}}))


def _is_null(node):
    return type(node.get(1)) is int and node[1] == 1 and 6 not in node and node.get(10) == {11: {}}


def _schema(elements, limits):
    _need(type(elements) is list and 1 < len(elements) <= 1 + 4 * limits["max_columns"]
        and all(type(e) is dict for e in elements), "bounded complete schema elements required")
    root = elements[0]
    _need(type(root.get(5)) is int and 0 < root[5] <= limits["max_columns"] and 1 not in root
        and (3 not in root or type(root[3]) is int and root[3] == 0),
        "supported literal schema root required")
    position = 1; fields = []; seen = set()
    for index in range(root[5]):
        _need(position < len(elements), "schema population incomplete")
        node = elements[position]; position += 1; name = _text(node.get(4), "column name")
        _need(name not in seen and type(node.get(3)) is int and node[3] == 1, "duplicate column or nonoptional top-level profile unsupported")
        seen.add(name)
        if 5 not in node:
            if _is_string(node): kind = "utf8"
            elif type(node.get(1)) is int and node[1] == 2 and 10 not in node and 6 not in node: kind = "int64"
            elif _is_null(node): kind = "null"
            else: raise ParentParquetPagesError("unsupported optional primitive/logical type profile")
            fields.append({"index": index, "name": name, "path": [name], "kind": kind,
                "physical_type": node[1], "max_definition_level": 1, "max_repetition_level": 0})
        else:
            _need(type(node[5]) is int and node[5] == 1 and 1 not in node
                and (6 in node or 10 in node)
                and (6 not in node or type(node[6]) is int and node[6] == 3)
                and (10 not in node or node[10] == {3: {}})
                and position + 1 < len(elements), "unsupported list outer schema profile")
            repeated, leaf = elements[position:position + 2]; position += 2
            _need(type(repeated.get(3)) is int and repeated[3] == 2
                and type(repeated.get(5)) is int and repeated[5] == 1
                and all(key not in repeated for key in (1, 6, 10))
                and type(leaf.get(3)) is int and leaf[3] == 1 and 5 not in leaf, "unsupported three-level optional list profile")
            if _is_string(leaf): kind = "list_utf8"
            elif _is_null(leaf): kind = "list_null"
            else: raise ParentParquetPagesError("unsupported list element profile")
            fields.append({"index": index, "name": name,
                "path": [name, _text(repeated.get(4), "list group name"), _text(leaf.get(4), "list element name")],
                "kind": kind, "physical_type": leaf[1], "max_definition_level": 3, "max_repetition_level": 1})
    _need(position == len(elements), "surplus schema elements are unsupported; no field projection")
    return fields


def _int(value, minimum=0): return type(value) is int and value >= minimum


def _preflight(stream, descriptor, pin, limits):
    stream.seek(0); _need(stream.read(4) == b"PAR1", "plaintext Parquet magic required")
    stream.seek(-8, os.SEEK_END); tail = stream.read(8)
    footer_size = int.from_bytes(tail[:4], "little")
    _need(tail[4:] == b"PAR1" and 0 < footer_size <= limits["max_footer_bytes"]
        and footer_size <= descriptor["bytes"] - 12, "Parquet footer bound/magic differs before parsing")
    footer_start = descriptor["bytes"] - footer_size - 8
    stream.seek(footer_start); raw_footer = stream.read(footer_size)
    parser = _Compact(raw_footer, maximum=limits["max_footer_bytes"])
    metadata = parser.struct()
    _need(parser.offset == footer_size and type(metadata.get(1)) is int and metadata[1] in (1, 2)
        and type(metadata.get(3)) is int and metadata[3] == descriptor["row_count"] and 8 not in metadata and 9 not in metadata,
        "complete supported plaintext footer version/population required")
    fields = _schema(metadata.get(2), limits)
    raw_groups = metadata.get(4)
    _need(type(raw_groups) is list and 0 < len(raw_groups) <= limits["max_row_groups"], "bounded row-group population required")
    groups = []; ranges = []; page_count = 0; source_rows = 0; all_header_bytes = 0
    for group_index, group in enumerate(raw_groups):
        _need(type(group) is dict and _int(group.get(3), 1) and group[3] <= limits["max_rows"]
            and type(group.get(1)) is list and len(group[1]) == len(fields), "complete bounded row-group geometry required")
        row_start = source_rows; source_rows += group[3]
        _need(source_rows <= limits["max_rows"], "aggregate row population bound exceeded")
        columns = []
        for field, chunk in zip(fields, group[1], strict=True):
            _need(type(chunk) is dict and 1 not in chunk and 8 not in chunk and 9 not in chunk
                and type(chunk.get(3)) is dict, "external/encrypted/missing column chunk unsupported")
            column = chunk[3]
            _need(type(column.get(1)) is int and column[1] == field["physical_type"] and column.get(3) == [p.encode() for p in field["path"]]
                and type(column.get(4)) is int and column[4] in (0, 1) and type(column.get(2)) is list
                and all(type(e) is int for e in column[2]) and set(column[2]) <= {0, 3, 8}, "literal column path/type/codec/encoding profile differs")
            _need(all(_int(column.get(k)) for k in (5, 6, 7, 9))
                and 0 < column[5] <= limits["max_column_values"] and column[7] > 0,
                "column value/size/offset declarations differ")
            if not field["max_repetition_level"]:
                _need(column[5] == group[3], "scalar column value/row population differs")
            else: _need(column[5] >= group[3], "list placeholder population differs")
            dictionary_offset = column.get(11)
            _need(dictionary_offset is None or _int(dictionary_offset, 4), "dictionary offset profile differs")
            start = dictionary_offset if dictionary_offset is not None else column[9]
            end = start + column[7]
            _need(4 <= start < end <= footer_start and start <= column[9] < end
                and (dictionary_offset is None or dictionary_offset < column[9]), "column range/data/dictionary offsets differ")
            ranges.append((start, end)); stream.seek(start)
            pages = []; total_raw = 0; total_compressed = 0; values = 0; seen_dictionary = False
            while stream.tell() < end:
                offset = stream.tell()
                raw = stream.read(min(limits["max_header_bytes"], end - offset)); stream.seek(offset)
                header, size = parse_page_header(raw, max_header_bytes=limits["max_header_bytes"])
                _need(set(header) <= {1, 2, 3, 4, 5, 7} and all(_int(header.get(k)) for k in (1, 2, 3))
                    and header[1] in (0, 2), "supported version-1 data/dictionary page required")
                page_type = header[1]
                _need(header[2] <= limits["max_page_uncompressed_bytes"]
                    and header[3] <= limits["max_page_compressed_bytes"]
                    and offset + size + header[3] <= end, "page compressed/uncompressed range bound exceeded before decoding")
                _need(4 not in header or type(header[4]) is int, "page CRC type differs")
                specific = header.get(5 if page_type == 0 else 7)
                _need(type(specific) is dict and _int(specific.get(1))
                    and specific[1] <= limits["max_page_values"], "page value cardinality bound exceeded before decoding")
                if page_type == 2:
                    _need(not pages and not seen_dictionary and dictionary_offset == offset
                        and 5 not in header and type(specific.get(2)) is int and specific[2] == 0
                        and header[2] <= limits["max_dictionary_bytes"], "dictionary must be first/unique/PLAIN/bounded")
                    seen_dictionary = True
                else:
                    _need(7 not in header and specific[1] > 0 and type(specific.get(2)) is int and specific[2] in (0, 8)
                        and type(specific.get(3)) is int and specific[3] == 3 and type(specific.get(4)) is int and specific[4] == 3
                        and (specific[2] != 8 or seen_dictionary), "version-1 value/level encoding or dictionary dependency unsupported")
                    if values == 0: _need(offset == column[9], "first data-page offset differs")
                    values += specific[1]
                    _need(values <= column[5], "page value population exceeds footer")
                page_count += 1; all_header_bytes += size
                _need(page_count <= limits["max_pages"], "aggregate page count bound exceeded")
                page = {"page_index": len(pages), "offset": offset, "header_bytes": size,
                    "header_sha256": hashlib.sha256(raw[:size]).hexdigest(), "type": page_type,
                    "compressed_bytes": header[3], "uncompressed_bytes": header[2],
                    "num_values": specific[1], "encoding": specific[2],
                    "crc32": header.get(4), "data_value_start": values - specific[1] if page_type == 0 else None}
                page["page_id"] = _digest({"source_sha256": descriptor["sha256"], "row_group": group_index,
                    "column_index": field["index"], "page": page})
                pages.append(page); total_raw += size + header[2]; total_compressed += size + header[3]
                stream.seek(offset + size + header[3])
            _need(stream.tell() == end and values == column[5] and total_raw == column[6]
                and total_compressed == column[7] and seen_dictionary == (dictionary_offset is not None), "complete column page/header/value/byte accounting differs")
            columns.append({"field": deepcopy(field), "codec": column[4], "num_values": column[5],
                "chunk_start": start, "chunk_end": end, "compressed_bytes": total_compressed,
                "uncompressed_bytes": total_raw, "pages": pages})
        _need(type(group.get(2)) is int and group[2] == sum(c["uncompressed_bytes"] for c in columns), "row-group uncompressed footer total differs")
        groups.append({"row_group": group_index, "row_start": row_start, "row_count": group[3], "columns": columns})
    _need(source_rows == descriptor["row_count"], "complete row-group population differs")
    ranges.sort()
    _need(ranges[0][0] == 4 and ranges[-1][1] == footer_start
        and all(left[1] == right[0] for left, right in zip(ranges, ranges[1:])), "column ranges overlap or surplus unsupported file bytes exist")
    report = {"schema": PAGE_SCHEMA, "decoder_profile": PROFILE, "descriptor": descriptor,
        "descriptor_sha256": pin, "limits": limits, "footer_bytes": footer_size,
        "footer_sha256": hashlib.sha256(raw_footer).hexdigest(), "original_footer_base64": base64.b64encode(raw_footer).decode(),
        "original_footer_metadata": _json_metadata(metadata), "source_schema": fields,
        "source_schema_sha256": _digest(fields), "row_count": source_rows, "row_groups": groups,
        "page_count": page_count, "header_bytes": all_header_bytes, "all_page_headers_inventoried": True,
        "page_bodies_decoded": 0, "whole_parent_rows_decoded": False, "authority": dict(AUTHORITY)}
    report["preflight_sha256"] = _digest(report)
    return report


def preflight_parent_pages(descriptor, *, expected_descriptor_sha256, limits=None):
    bounds = _limits(limits); source = _descriptor(descriptor, expected_descriptor_sha256, bounds)
    with _opened(source) as stream: return _preflight(stream, source, expected_descriptor_sha256, bounds)


def validate_parent_page_preflight(report, descriptor, *, expected_report_sha256, expected_descriptor_sha256, limits=None):
    _sha(expected_report_sha256)
    _need(parent_page_report_sha256(report) == expected_report_sha256, "independent full page-preflight report differs")
    expected = preflight_parent_pages(descriptor, expected_descriptor_sha256=expected_descriptor_sha256, limits=limits)
    _need(_wire(expected) == _wire(report), "page-preflight differs from complete source regeneration")
    return {"valid": True, "page_count": report["page_count"], "all_authority_false": True}


def _body(stream, column, page, limits, accounting, witnesses):
    accounting[0] += page["uncompressed_bytes"]
    _need(accounting[0] <= limits["max_decoded_bytes"], "aggregate decoded-page byte bound exceeded before allocation")
    stream.seek(page["offset"] + page["header_bytes"])
    compressed = stream.read(page["compressed_bytes"])
    _need(len(compressed) == page["compressed_bytes"], "truncated pinned page body")
    if page["crc32"] is not None:
        _need(zlib.crc32(compressed) == page["crc32"] & 0xffffffff, "page CRC differs")
    if column["codec"] == 1:
        raw = decode_snappy_page(compressed, expected_size=page["uncompressed_bytes"], max_output_bytes=limits["max_page_uncompressed_bytes"])
    else:
        _need(len(compressed) == page["uncompressed_bytes"], "UNCOMPRESSED page sizes differ")
        raw = compressed
    witnesses[page["page_id"]] = {"page_id": page["page_id"], "column_index": column["field"]["index"],
        "offset": page["offset"], "header_sha256": page["header_sha256"],
        "compressed_body_sha256": hashlib.sha256(compressed).hexdigest(),
        "decoded_body_sha256": hashlib.sha256(raw).hexdigest(), "uncompressed_bytes": len(raw)}
    return raw


def _plain_values(raw, kind, count, limits):
    view = memoryview(raw); offset = 0
    for _ in range(count):
        if kind in ("utf8", "list_utf8"):
            _need(offset + 4 <= len(view), "truncated PLAIN byte-array length")
            length = int.from_bytes(view[offset:offset + 4], "little"); offset += 4
            _need(length <= limits["max_value_bytes"] and offset + length <= len(view), "PLAIN value byte bound exceeded before materialization")
            value = view[offset:offset + length]; offset += length
        elif kind == "int64":
            _need(offset + 8 <= len(view), "truncated PLAIN INT64")
            value = int.from_bytes(view[offset:offset + 8], "little", signed=True); offset += 8
        else: raise ParentParquetPagesError("non-null values in NULL-annotated column")
        yield value
    _need(offset == len(view), "surplus PLAIN value bytes")


def _selected_value(value, kind):
    if kind == "int64": return value
    try: return bytes(value).decode("utf-8", errors="strict")
    except UnicodeError as exc: raise ParentParquetPagesError("selected UTF-8 value is malformed") from exc


def _value_json_bytes(value, kind):
    """Exact canonical UTF-8 JSON fragment bytes, without copying/decoding text."""
    if kind == "int64": return len(str(value))
    size = 2 + len(value)
    for byte in value:
        if byte in (34, 92): size += 1
        elif byte < 32: size += 1 if byte in (8, 9, 10, 12, 13) else 5
    return size


def _charge_selected(budget, ordinal, size, limits):
    """Reserve retained canonical bytes before Unicode copies or list append."""
    row_size = budget["rows"][ordinal] + size
    total = budget["total"] + size
    _need(row_size <= limits["max_row_bytes"], "selected complete row byte bound exceeded before materialization")
    _need(total <= limits["max_selected_bytes"], "aggregate selected-row byte bound exceeded before materialization")
    budget["rows"][ordinal] = row_size; budget["total"] = total


def _level_stream(raw, offset, maximum, count, limits):
    if maximum == 0: return [0] * count, offset
    _need(offset + 4 <= len(raw), "truncated version-1 level length")
    size = int.from_bytes(raw[offset:offset + 4], "little"); offset += 4
    _need(offset + size <= len(raw), "version-1 level bytes exceed page")
    levels = decode_rle_values(raw[offset:offset + size], bit_width=maximum.bit_length(),
        count=count, max_values=limits["max_page_values"])
    _need(all(value <= maximum for value in levels), "level exceeds schema maximum")
    return levels, offset + size


def _column_rows(stream, column, wanted, limits, accounting, witnesses, budget, row_start, group_rows):
    field = column["field"]; kind = field["kind"]; repeated = field["max_repetition_level"]
    selected = {}; evidence = {}; dictionary = None; dictionary_id = None; current_row = -1; current = None; current_ids = []
    element_row = False
    last = max(wanted)
    for page in column["pages"]:
        if page["type"] == 2:
            raw = _body(stream, column, page, limits, accounting, witnesses)
            dictionary = list(_plain_values(raw, kind, page["num_values"], limits))
            dictionary_id = page["page_id"]
            continue
        if not repeated:
            first = page["data_value_start"]; end = first + page["num_values"]
            if not any(first <= ordinal < end for ordinal in wanted): continue
        raw = _body(stream, column, page, limits, accounting, witnesses)
        reps, offset = _level_stream(raw, 0, field["max_repetition_level"], page["num_values"], limits)
        defs, offset = _level_stream(raw, offset, field["max_definition_level"], page["num_values"], limits)
        nonnull = sum(value == field["max_definition_level"] for value in defs)
        payload = raw[offset:]
        if page["encoding"] == 8:
            _need(dictionary is not None and payload, "dictionary values/bit width missing")
            ids = decode_rle_values(payload[1:], bit_width=payload[0], count=nonnull, max_values=limits["max_page_values"])
            _need(all(index < len(dictionary) for index in ids), "dictionary index out of range")
            values = (dictionary[index] for index in ids)
        else: values = _plain_values(payload, kind, nonnull, limits)
        for index, (rep, definition) in enumerate(zip(reps, defs, strict=True)):
            value = next(values) if definition == field["max_definition_level"] else None
            if not repeated:
                ordinal = page["data_value_start"] + index
                if ordinal in wanted:
                    _charge_selected(budget, row_start + ordinal, 4 if definition == 0 else _value_json_bytes(value, kind), limits)
                    selected[ordinal] = None if definition == 0 else _selected_value(value, kind)
                    evidence[ordinal] = [p for p in (dictionary_id if page["encoding"] == 8 else None, page["page_id"]) if p]
                continue
            if rep == 0:
                if current_row in wanted:
                    selected[current_row] = current; evidence[current_row] = list(dict.fromkeys(current_ids))
                current_row += 1
                _need(current_row < group_rows, "decoded list row population exceeds footer")
                current = None if definition == 0 else []
                element_row = definition >= 2
                current_ids = []
                if current_row in wanted:
                    _charge_selected(budget, row_start + current_row, 4 if definition == 0 else 2, limits)
            else:
                _need(current_row >= 0 and current is not None and element_row and definition >= 2,
                    "invalid list continuation/null-empty levels")
            if current_row in wanted:
                current_ids.append(page["page_id"])
                if definition >= 2:
                    _need(type(current) is list and len(current) < limits["max_list_values"], "selected list cardinality bound exceeded before allocation")
                    size = (1 if current else 0) + (4 if definition == 2 else _value_json_bytes(value, kind))
                    _charge_selected(budget, row_start + current_row, size, limits)
                    current.append(None if definition == 2 else _selected_value(value, kind))
                    if page["encoding"] == 8: current_ids.append(dictionary_id)
        _need(next(values, None) is None, "surplus decoded value population")
        if repeated and current_row > last: break
    if repeated and current_row in wanted:
        selected[current_row] = current; evidence[current_row] = list(dict.fromkeys(current_ids))
    _need(set(selected) == wanted, "requested physical column/list rows missing")
    return selected, evidence


def read_selected_parent_rows(descriptor, *, expected_descriptor_sha256, preflight_report,
        expected_preflight_sha256, row_ordinals, expected_row_sha256s, limits=None):
    bounds = _limits(limits); source = _descriptor(descriptor, expected_descriptor_sha256, bounds)
    _sha(expected_preflight_sha256)
    _need(parent_page_report_sha256(preflight_report) == expected_preflight_sha256, "independent full page-preflight pin differs")
    _need(type(row_ordinals) is list and 0 < len(row_ordinals) <= bounds["max_selected_rows"]
        and all(type(n) is int and 0 <= n < source["row_count"] for n in row_ordinals)
        and row_ordinals == sorted(set(row_ordinals)), "exact ordered distinct physical row requests required")
    _need(type(expected_row_sha256s) is list and len(expected_row_sha256s) == len(row_ordinals), "independent complete selected-row hash population required")
    for pin in expected_row_sha256s: _sha(pin)
    output = {}; row_evidence = {}; witnesses = {}; accounting = [0]
    budget = {"rows": {ordinal: 2 for ordinal in row_ordinals}, "total": 2 * len(row_ordinals)}
    _need(budget["total"] <= bounds["max_selected_bytes"] and 2 <= bounds["max_row_bytes"], "selected empty-row byte bounds exceeded")
    with _opened(source) as stream:
        current = _preflight(stream, source, expected_descriptor_sha256, bounds)
        _need(_wire(current) == _wire(preflight_report), "page-preflight differs from complete pinned source regeneration")
        for group in current["row_groups"]:
            absolute = [ordinal for ordinal in row_ordinals if group["row_start"] <= ordinal < group["row_start"] + group["row_count"]]
            if not absolute: continue
            wanted = {ordinal - group["row_start"] for ordinal in absolute}
            for ordinal in absolute:
                output[ordinal] = {"row_ordinal": ordinal, "row_group": group["row_group"],
                    "row_group_ordinal": ordinal - group["row_start"], "raw_row": {}}
                row_evidence[ordinal] = []
            for column in group["columns"]:
                for ordinal in absolute:
                    size = len(_wire(column["field"]["name"])) + 1 + (1 if output[ordinal]["raw_row"] else 0)
                    _charge_selected(budget, ordinal, size, bounds)
                values, references = _column_rows(stream, column, wanted, bounds, accounting, witnesses, budget, group["row_start"], group["row_count"])
                for ordinal in absolute:
                    local = ordinal - group["row_start"]
                    output[ordinal]["raw_row"][column["field"]["name"]] = values[local]
                    row_evidence[ordinal].extend(references[local])
                    _need(len(_wire(output[ordinal]["raw_row"])) <= bounds["max_row_bytes"], "selected complete row byte bound exceeded")
    rows = []; retained = 0
    for ordinal, pin in zip(row_ordinals, expected_row_sha256s, strict=True):
        row = output[ordinal]; raw = _wire(row["raw_row"]); retained += len(raw)
        _need(retained <= bounds["max_selected_bytes"], "aggregate selected-row byte bound exceeded; no truncation")
        _need(len(raw) == budget["rows"][ordinal], "selected preallocation JSON byte accounting differs")
        observed = hashlib.sha256(raw).hexdigest()
        _need(observed == pin, "independent physical selected-row SHA256 differs")
        row["raw_row_sha256"] = observed; row["page_witnesses"] = list(dict.fromkeys(row_evidence[ordinal])); rows.append(row)
    _need(retained == budget["total"], "aggregate selected preallocation byte accounting differs")
    report = {"schema": ROW_SCHEMA, "decoder_profile": PROFILE, "descriptor": source,
        "descriptor_sha256": expected_descriptor_sha256, "preflight_report_sha256": expected_preflight_sha256,
        "source_schema": deepcopy(preflight_report["source_schema"]), "source_schema_sha256": preflight_report["source_schema_sha256"],
        "limits": bounds, "requested_row_ordinals": deepcopy(row_ordinals), "expected_row_sha256s": deepcopy(expected_row_sha256s),
        "row_count": len(rows), "rows": rows, "selected_decoded_bytes": retained,
        "decoded_page_bytes": accounting[0], "decoded_page_witnesses": list(witnesses.values()),
        "complete_requested_population": True, "all_source_columns_retained": True,
        "whole_parent_population_inventoried": False, "original_character_coordinates_attested": False,
        "authority": dict(AUTHORITY)}
    report["row_report_sha256"] = _digest(report)
    return report


def validate_selected_parent_rows(report, descriptor, *, expected_report_sha256, **trusted_inputs):
    _sha(expected_report_sha256)
    _need(parent_row_report_sha256(report) == expected_report_sha256, "independent full selected-row report pin differs")
    expected = read_selected_parent_rows(descriptor, **trusted_inputs)
    _need(_wire(expected) == _wire(report), "selected-row report differs from exact pinned source regeneration")
    return {"valid": True, "row_count": report["row_count"], "all_authority_false": True}


__all__ = ["ParentParquetPagesError", "preflight_parent_pages", "validate_parent_page_preflight",
    "read_selected_parent_rows", "validate_selected_parent_rows", "parent_page_report_sha256",
    "parent_row_report_sha256", "parse_page_header", "decode_snappy_page", "decode_rle_values"]
