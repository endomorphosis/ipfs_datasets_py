"""Unit tests for software-contract CIDv1 content identity (DSCON-G040)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    CID_BASE,
    CID_VECTORS_FIXTURE_RELPATH,
    CID_VERSION,
    ContentIdentityError,
    MULTIHASH_TYPE,
    PROFILE_ID,
    PROFILE_VERSION,
    SOURCE_CODEC,
    STRUCTURED_CODEC,
    StructuredIdentityError,
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_obj,
    cid_for_structured,
    cid_vectors_document,
    decode_and_recompute_source,
    decode_and_recompute_structured,
    load_cid_vectors,
    materialize_cid_vectors_fixture,
    profile_descriptor,
    validate_cid,
    validate_structured_value,
    verify_source_read,
    verify_structured_read,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[4]
PROFILE_DOC = PACKAGE_ROOT / "docs/software_contracts/CID_PROFILE_V1.md"
VECTORS_FIXTURE = PACKAGE_ROOT / CID_VECTORS_FIXTURE_RELPATH


# ---------------------------------------------------------------------------
# Profile / documentation surface
# ---------------------------------------------------------------------------


def test_profile_descriptor_is_versioned_and_domain_separated() -> None:
    descriptor = profile_descriptor()
    assert descriptor["profile_id"] == PROFILE_ID
    assert descriptor["profile_version"] == PROFILE_VERSION
    assert descriptor["cid_version"] == CID_VERSION
    assert descriptor["base"] == CID_BASE
    assert descriptor["multihash"] == MULTIHASH_TYPE
    assert descriptor["source_codec"] == SOURCE_CODEC == "raw"
    assert descriptor["structured_codec"] == STRUCTURED_CODEC == "dag-json"
    assert descriptor["cid_vectors_fixture"] == CID_VECTORS_FIXTURE_RELPATH
    assert "float" in descriptor["structured_rejected_types"]
    assert "repr_fallback" in descriptor["structured_rejected_types"]


def test_profile_document_exists_and_names_fixture_and_apis() -> None:
    text = PROFILE_DOC.read_text(encoding="utf-8")
    assert "software-contract-cid-profile-v1" in text
    assert "cid_for_bytes" in text
    assert "cid_for_obj" in text
    assert "decode-and-recompute" in text.lower() or "decode_and_recompute" in text
    assert CID_VECTORS_FIXTURE_RELPATH in text or "cid_vectors.json" in text
    assert "raw" in text and "dag-json" in text and "sha2-256" in text


# ---------------------------------------------------------------------------
# Source domain
# ---------------------------------------------------------------------------


def test_cid_for_bytes_uses_raw_sha2_256_base32_v1() -> None:
    cid = cid_for_bytes(b"hello")
    assert cid == "bafkreibm6jg3ux5qumhcn2b3flc3tyu6dmlb4xa7u5bf44yegnrjhc4yeq"
    assert cid == validate_cid(cid, codecs={SOURCE_CODEC})
    assert cid.startswith("b")  # lowercase base32 multibase prefix


def test_cid_for_bytes_rejects_non_bytes() -> None:
    with pytest.raises(TypeError):
        cid_for_bytes("hello")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        cid_for_bytes(bytearray(b"hello"))  # type: ignore[arg-type]


def test_decode_and_recompute_source_accepts_matching_payload() -> None:
    data = b"hello"
    cid = cid_for_bytes(data)
    assert decode_and_recompute_source(cid, data) == cid
    assert verify_source_read(cid, data) == data


def test_decode_and_recompute_source_rejects_tamper_and_wrong_codec() -> None:
    data = b"hello"
    cid = cid_for_bytes(data)
    with pytest.raises(ContentIdentityError):
        decode_and_recompute_source(cid, b"hello!")
    structured = cid_for_obj({"a": 1})
    with pytest.raises(ContentIdentityError):
        decode_and_recompute_source(structured, data)


# ---------------------------------------------------------------------------
# Structured domain
# ---------------------------------------------------------------------------


def test_canonical_dag_json_is_sorted_compact_utf8() -> None:
    encoded = canonical_dag_json_bytes({"b": 1, "a": 2})
    assert encoded == b'{"a":2,"b":1}'
    nested = canonical_dag_json_bytes(
        {"z": {"y": [1, "x", None, True]}, "a": "unicode-café"}
    )
    assert nested == b'{"a":"unicode-caf\xc3\xa9","z":{"y":[1,"x",null,true]}}'


def test_cid_for_obj_is_dag_json_and_key_order_independent() -> None:
    left = cid_for_obj({"b": 1, "a": 2})
    right = cid_for_obj({"a": 2, "b": 1})
    assert left == right
    assert left == cid_for_structured({"a": 2, "b": 1})
    assert left == "baguqeera2nrgvqykq7tppjscqiz3hructglwqzp2kueoijt4kqk4o2xxu5za"
    assert left == validate_cid(left, codecs={STRUCTURED_CODEC})
    assert left.startswith("bagu")  # CIDv1 dag-json base32 family


def test_structured_identity_rejects_disallowed_types() -> None:
    rejected: list[Any] = [
        1.5,
        float("nan"),
        float("inf"),
        b"bytes",
        bytearray(b"x"),
        {1, 2},
        frozenset({1}),
        (1, 2),
        Path("/tmp/x"),
        object(),
        complex(1, 2),
        math.nan,
    ]
    for value in rejected:
        with pytest.raises(StructuredIdentityError):
            validate_structured_value(value)
        with pytest.raises((StructuredIdentityError, TypeError, ValueError)):
            canonical_dag_json_bytes(value)
        with pytest.raises((StructuredIdentityError, TypeError, ValueError)):
            cid_for_obj(value)


def test_structured_identity_rejects_non_string_map_keys() -> None:
    with pytest.raises(StructuredIdentityError):
        validate_structured_value({1: "a"})  # type: ignore[dict-item]
    with pytest.raises(StructuredIdentityError):
        cid_for_obj({True: 1})  # type: ignore[dict-item]


def test_structured_identity_accepts_reviewed_scalars_and_containers() -> None:
    values: list[Any] = [
        None,
        True,
        False,
        0,
        -42,
        10**40,
        "café",
        [],
        {},
        [None, False, True, 0, 1, "s", [], {}],
        {"a": {"b": [1, "x"]}},
    ]
    for value in values:
        validate_structured_value(value)
        cid = cid_for_obj(value)
        assert decode_and_recompute_structured(cid, value) == cid
        assert verify_structured_read(cid, value) is value


def test_no_repr_fallback_for_host_objects() -> None:
    class Host:
        def __repr__(self) -> str:
            return "Host()"

    with pytest.raises(StructuredIdentityError):
        cid_for_obj({"host": Host()})


def test_decode_and_recompute_structured_rejects_tamper() -> None:
    obj = {"a": 1}
    cid = cid_for_obj(obj)
    with pytest.raises(ContentIdentityError):
        decode_and_recompute_structured(cid, {"a": 2})
    raw = cid_for_bytes(b"{}")
    with pytest.raises(ContentIdentityError):
        decode_and_recompute_structured(raw, obj)


def test_bool_is_not_int_for_identity() -> None:
    # JSON distinguishes true from 1; both are reviewed but different.
    assert cid_for_obj(True) != cid_for_obj(1)
    assert canonical_dag_json_bytes(True) == b"true"
    assert canonical_dag_json_bytes(1) == b"1"


# ---------------------------------------------------------------------------
# CID validation
# ---------------------------------------------------------------------------


def test_validate_cid_rejects_uppercase_wrong_profile_and_garbage() -> None:
    good = cid_for_bytes(b"hello")
    with pytest.raises(ContentIdentityError):
        validate_cid(good.upper())
    with pytest.raises(ContentIdentityError):
        validate_cid("")
    with pytest.raises(ContentIdentityError):
        validate_cid(None)  # type: ignore[arg-type]
    with pytest.raises(ContentIdentityError):
        validate_cid("not-a-cid")
    with pytest.raises(ContentIdentityError):
        validate_cid(good, codecs=set())


# ---------------------------------------------------------------------------
# Golden vectors (fixture path + live document)
# ---------------------------------------------------------------------------


def test_cid_vectors_document_matches_live_encoders() -> None:
    document = cid_vectors_document()
    assert document["schema"] == "ipfs-datasets.software-contract-cid-vectors.v1"
    assert document["profile"]["profile_id"] == PROFILE_ID
    assert document["vectors"], "golden vector set must be non-empty"

    by_id = {item["id"]: item for item in document["vectors"]}
    assert len(by_id) == len(document["vectors"])

    for item in document["vectors"]:
        assert item["version"] == CID_VERSION
        assert item["base"] == CID_BASE
        assert item["multihash"] == MULTIHASH_TYPE
        if item["domain"] == "source":
            data = bytes.fromhex(item["bytes_hex"])
            assert item["codec"] == SOURCE_CODEC
            assert cid_for_bytes(data) == item["expected_cid"]
            decode_and_recompute_source(item["expected_cid"], data)
        else:
            assert item["domain"] == "structured"
            assert item["codec"] == STRUCTURED_CODEC
            assert canonical_dag_json_bytes(item["value"]).hex() == item["canonical_hex"]
            assert cid_for_obj(item["value"]) == item["expected_cid"]
            decode_and_recompute_structured(item["expected_cid"], item["value"])

    # Key-order independence fixed point
    assert (
        by_id["structured.simple_map"]["expected_cid"]
        == by_id["structured.key_order_independent"]["expected_cid"]
    )
    # Known fixed points (cross-runtime anchors)
    assert by_id["source.hello"]["expected_cid"] == (
        "bafkreibm6jg3ux5qumhcn2b3flc3tyu6dmlb4xa7u5bf44yegnrjhc4yeq"
    )
    assert by_id["structured.simple_map"]["expected_cid"] == (
        "baguqeera2nrgvqykq7tppjscqiz3hructglwqzp2kueoijt4kqk4o2xxu5za"
    )


def test_load_cid_vectors_uses_fixture_when_present_or_live_document(
    tmp_path: Path,
) -> None:
    live = load_cid_vectors()
    assert live["schema"] == "ipfs-datasets.software-contract-cid-vectors.v1"

    # Missing path falls back to live document (hermetic).
    missing = tmp_path / "absent.json"
    assert load_cid_vectors(missing)["vectors"][0]["id"] == live["vectors"][0]["id"]

    # Materialized fixture must round-trip and match live encoders.
    written = materialize_cid_vectors_fixture(tmp_path)
    assert written == tmp_path / CID_VECTORS_FIXTURE_RELPATH
    loaded = load_cid_vectors(written)
    assert canonical_dag_json_bytes(loaded) == canonical_dag_json_bytes(live)

    # Tampered fixture is rejected.
    tampered = json.loads(written.read_text(encoding="utf-8"))
    tampered["vectors"][0]["expected_cid"] = cid_for_bytes(b"tamper")
    written.write_text(
        json.dumps(tampered, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(ContentIdentityError):
        load_cid_vectors(written)


def test_package_fixture_path_constant_and_optional_on_disk_parity() -> None:
    """Evidence path for DSCON-G040 golden vectors.

    The durable path is ``tests/fixtures/software_contracts/cid_vectors.json``.
    When the file exists it must match ``cid_vectors_document()``; when absent,
    the live document still proves the evidence terms via tests and profile docs.
    """

    assert CID_VECTORS_FIXTURE_RELPATH.endswith("cid_vectors.json")
    assert VECTORS_FIXTURE == PACKAGE_ROOT / CID_VECTORS_FIXTURE_RELPATH
    if VECTORS_FIXTURE.is_file():
        load_cid_vectors(VECTORS_FIXTURE)


def test_javascript_parity_contract_is_documented_on_every_vector() -> None:
    """Python/JS golden vectors must share expected_cid (cross-runtime contract)."""

    for item in cid_vectors_document()["vectors"]:
        assert "javascript" in item
        assert "python" in item
        assert item["expected_cid"] == validate_cid(
            item["expected_cid"],
            codecs={item["codec"]},
        )


def test_multiformats_codec_names_match_profile() -> None:
    from multiformats import CID

    raw = CID.decode(cid_for_bytes(b"x"))
    structured = CID.decode(cid_for_obj({"k": "v"}))
    assert raw.codec.name == "raw"
    assert structured.codec.name == "dag-json"
    assert raw.hashfun.name == structured.hashfun.name == "sha2-256"
    assert raw.version == structured.version == 1
    assert raw.base.name == structured.base.name == "base32"
