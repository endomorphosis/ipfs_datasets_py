"""Lossless formal-view transport and bounded hostile-input decoding."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
import zlib

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_logic_artifacts import (
    DOCUMENT_ENCODING, LogicArtifactError, PACK_THRESHOLD_BYTES, pack_document, unpack_document,
)


MARKER = "__legacy_span_logic_artifact__"


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _block(raw):
    return {MARKER: DOCUMENT_ENCODING, "compression": "zlib", "base64": base64.b64encode(zlib.compress(raw, 9)).decode(),
            "decoded_bytes": len(raw), "decoded_sha256": hashlib.sha256(raw).hexdigest()}


def _document():
    triples = [{"subject": f"frame-{index}", "predicate": "definition", "object": "ontology definition " * 80}
               for index in range(180)]
    return {
        "document_id": "native-bridge-source", "source_text": "The agency shall retain records.",
        "metadata": {"admitted": False, "source": "compiler"}, "frame_logic_triples": triples,
        "views": {
            "modal": {"format": "modal-ir-v1", "payload": {"triples": triples},
                      "metadata": {"ontology": "definition " * 10000}},
            "deontic": {"format": "deontic-formula-records", "payload": {"formula": "O(retain(agency,records))"}},
            "tdfol": {"format": "tdfol-formula-records", "payload": {"records": [{"formula": "∀x. P(x)"}]}},
            "dcec": {"format": "dcec-formula-records", "payload": {"records": [{"formula": "O(a,t,p)"}]}},
            "frame": {"format": "flogic-triples-v1", "payload": {"triples": triples}},
        },
    }


def test_roundtrip_preserves_every_formal_view_and_source_metadata():
    original = _document()
    before = deepcopy(original)
    packed = pack_document(original)
    assert original == before
    assert unpack_document(packed) == original
    assert packed["metadata"] == original["metadata"]
    assert packed["document_id"] == original["document_id"]
    assert packed["frame_logic_triples"][MARKER] == DOCUMENT_ENCODING
    assert packed["views"]["modal"]["payload"][MARKER] == DOCUMENT_ENCODING
    assert packed["views"]["modal"]["metadata"][MARKER] == DOCUMENT_ENCODING
    for family in ("deontic", "tdfol", "dcec"):
        assert packed["views"][family] == original["views"][family]
    assert len(_canonical(packed)) < len(_canonical(original)) / 10
    assert pack_document(original) == packed


def test_small_document_and_threshold_remain_directly_queryable():
    doc = {"views": {"family": {"payload": {"formula": "O(file)"}, "metadata": {}}}, "frame_logic_triples": []}
    assert pack_document(doc) == doc
    assert unpack_document(doc) == doc
    below = {"views": {"family": {"payload": "a" * (PACK_THRESHOLD_BYTES - 2)}}}
    assert pack_document(below) == below
    above = {"views": {"family": {"payload": "a" * (PACK_THRESHOLD_BYTES - 1)}}}
    assert MARKER in pack_document(above)["views"]["family"]["payload"]


def test_entire_document_limit_counts_literals_and_multiple_blocks():
    packed = pack_document(_document())
    with pytest.raises(LogicArtifactError, match="decoded byte limit"):
        unpack_document(packed, max_decoded_bytes=1000)
    raw = _canonical("x" * 1000)
    multi = {"left": _block(raw), "right": _block(raw)}
    with pytest.raises(LogicArtifactError, match="decoded byte limit"):
        unpack_document(multi, max_decoded_bytes=1500)
    with pytest.raises(LogicArtifactError, match="document exceeds decoded byte limit"):
        unpack_document({"unpacked": "x" * 1000}, max_decoded_bytes=100)
    original = _document()
    size = len(_canonical(original))
    assert unpack_document(packed, max_decoded_bytes=size) == original
    with pytest.raises(LogicArtifactError, match="document exceeds decoded byte limit"):
        unpack_document(packed, max_decoded_bytes=size - 1)


@pytest.mark.parametrize("change", [
    {MARKER: "unsupported/v2"}, {"compression": "gzip"}, {"decoded_bytes": -1},
    {"decoded_bytes": True}, {"decoded_sha256": "wrong"}, {"decoded_sha256": "a" * 64},
    {"base64": "!not base64!"}, {"extra": "ambiguous"},
])
def test_malformed_blocks_are_rejected(change):
    block = _block(_canonical({"formula": "O(file)"}))
    block.update(change)
    with pytest.raises(LogicArtifactError):
        unpack_document({"views": {"family": {"payload": block}}})


def test_decompression_bomb_cannot_exceed_declared_or_global_bound():
    block = _block(_canonical("x" * 70000))
    with pytest.raises(LogicArtifactError, match="decoded byte limit"):
        unpack_document({"payload": block}, max_decoded_bytes=1024)
    block["decoded_bytes"] = 128
    with pytest.raises(LogicArtifactError, match="declared decoded byte limit"):
        unpack_document({"payload": block})


@pytest.mark.parametrize("mutation", ["truncated", "trailing_stream", "length"])
def test_incomplete_or_extra_compressed_content_is_rejected(mutation):
    block = _block(_canonical({"formula": "O(file)"}))
    compressed = base64.b64decode(block["base64"])
    if mutation == "truncated":
        block["base64"] = base64.b64encode(compressed[:-1]).decode()
    elif mutation == "trailing_stream":
        block["base64"] = base64.b64encode(compressed + zlib.compress(b"{}")).decode()
    else:
        block["decoded_bytes"] += 1
    with pytest.raises(LogicArtifactError):
        unpack_document({"payload": block})


@pytest.mark.parametrize("raw", [b'{"x":NaN}', b'{"x":1,"x":2}', b'{ "x": 1 }', b'not-json'])
def test_noncanonical_or_ambiguous_encoded_json_is_rejected(raw):
    with pytest.raises(LogicArtifactError):
        unpack_document({"payload": _block(raw)})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), ("tuple",), {1: "non-string key"}])
def test_non_json_or_nonfinite_document_values_are_rejected(value):
    with pytest.raises(LogicArtifactError):
        pack_document({"payload": value})
    with pytest.raises(LogicArtifactError):
        unpack_document({"payload": value})


def test_reserved_markers_nested_wrappers_and_cycles_are_rejected():
    block = _block(_canonical({"formula": "O(file)"}))
    with pytest.raises(LogicArtifactError, match="reserved"):
        pack_document({"payload": block})
    with pytest.raises(LogicArtifactError, match="reserved"):
        unpack_document({"payload": _block(_canonical(block))})
    cyclic = {}
    cyclic["self"] = cyclic
    for operation in (pack_document, unpack_document):
        with pytest.raises(LogicArtifactError, match="cyclic"):
            operation(cyclic)


@pytest.mark.parametrize("limit", [0, -1, True, 0.5])
def test_invalid_whole_document_limits_are_rejected(limit):
    with pytest.raises(LogicArtifactError, match="positive integer"):
        unpack_document({}, max_decoded_bytes=limit)
