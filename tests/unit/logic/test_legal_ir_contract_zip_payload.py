"""Compressed inventory preserves exact JSON semantics with bounded decoding."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import stat
import struct
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load("inventory_zip_contract_owner", "scripts/ops/legal_ir/legal_ir_supervisor_contract.py")
helper = load("inventory_zip_materializer_owner", "scripts/ops/legal_ir/materialize_legal_ir_inventory.py")


def archive(entries, *, comment=b"", extra=b"", compression=zipfile.ZIP_DEFLATED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as opened:
        opened.comment = comment
        for filename, mode, content in entries:
            info = zipfile.ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = mode << 16
            info.extra = extra
            info.compress_type = compression
            opened.writestr(info, content)
    return stream.getvalue()


@pytest.mark.parametrize("label", ["sections", "spans", "entities"])
def test_single_zip_member_and_legacy_json_retain_exact_plaintext_and_false_flags(label):
    rows = [{"id": "fixture:17", "text": "Álpha\n\tExact  source bytes.",
             "admitted": False, "formalized": False}]
    content = helper.raw(rows)
    assert contract.payload({label: content}, label) == rows
    assert contract.payload({label: helper.zipped_array(label, content)}, label) == rows


@pytest.mark.parametrize("attack", ["path", "wrong_member", "directory", "symlink", "multiple", "extra", "comment", "nonarray", "unsupported"])
def test_archive_authority_and_container_escapes_are_refused(attack):
    name, mode, content = "spans.json", stat.S_IFREG | 0o600, b"[]"
    extra = comment = b""
    compression = zipfile.ZIP_DEFLATED
    if attack == "path":
        name = "../spans.json"
    elif attack == "wrong_member":
        name = "other.json"
    elif attack == "directory":
        name, mode = "spans.json/", stat.S_IFDIR | 0o700
    elif attack == "symlink":
        mode, content = stat.S_IFLNK | 0o777, b"/etc/passwd"
    elif attack == "extra":
        extra = b"\x01\x00\x00\x00"
    elif attack == "comment":
        comment = b"unreviewed archive comment"
    elif attack == "nonarray":
        content = b'{"not":"an inventory array"}'
    elif attack == "unsupported":
        compression = zipfile.ZIP_BZIP2
    entries = [(name, mode, content)]
    if attack == "multiple":
        entries.append(("foreign.json", stat.S_IFREG | 0o600, b"[]"))
    raw = archive(entries, comment=comment, extra=extra, compression=compression)
    with pytest.raises(ValueError):
        contract.payload({"spans": raw}, "spans")


@pytest.mark.parametrize("attack", ["encrypted", "local_extra", "crc", "declared_size", "huge_size", "truncated", "trailing"])
def test_corrupt_or_oversized_archives_cannot_complete(attack):
    raw = bytearray(helper.zipped_array("spans", b'[{"text":"actual"}]'))
    central = raw.find(b"PK\x01\x02")
    if attack == "encrypted":
        raw[6:8] = struct.pack("<H", 1)
        raw[central + 8:central + 10] = struct.pack("<H", 1)
    elif attack == "local_extra":
        raw[28:30] = struct.pack("<H", 1)
    elif attack == "crc":
        raw[14:18] = raw[central + 16:central + 20] = struct.pack("<L", 0)
    elif attack in {"declared_size", "huge_size"}:
        size = 128 * 1024 * 1024 + 1 if attack == "huge_size" else 1
        raw[22:26] = raw[central + 24:central + 28] = struct.pack("<L", size)
    elif attack == "truncated":
        del raw[-1:]
    else:
        raw.extend(b"unreviewed trailing bytes")
    with pytest.raises(ValueError):
        contract.payload({"spans": bytes(raw)}, "spans")


def test_zip_cannot_expand_into_other_task_family_payloads():
    raw = archive([("source.json", stat.S_IFREG | 0o600, b"[]")])
    with pytest.raises(contract.ContractError, match="only supported for USC"):
        contract.payload({"source": raw}, "source")


def test_data_hidden_after_deflate_eof_is_refused_even_with_consistent_zip_sizes():
    raw = bytearray(helper.zipped_array("spans", b"[]"))
    central = raw.find(b"PK\x01\x02")
    compressed_size = struct.unpack("<L", raw[18:22])[0]
    hidden = b"unreviewed data after the compressed stream"
    raw[central:central] = hidden
    central += len(hidden)
    raw[18:22] = struct.pack("<L", compressed_size + len(hidden))
    raw[central + 20:central + 24] = struct.pack("<L", compressed_size + len(hidden))
    end = len(raw) - 22
    raw[end + 16:end + 20] = struct.pack("<L", central)
    with pytest.raises(contract.ContractError, match="stream is incomplete, trailing"):
        contract.payload({"spans": bytes(raw)}, "spans")


def test_stored_json_member_has_the_same_bounded_semantics():
    raw = archive([("spans.json", stat.S_IFREG | 0o600, b"[]")], compression=zipfile.ZIP_STORED)
    assert contract.payload({"spans": raw}, "spans") == []
