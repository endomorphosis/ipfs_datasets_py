"""Golden and behavioral contracts for shared IR canonical identity."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import sys

import pytest

from ipfs_datasets_py.logic.ir_core.canonical import (
    CANONICAL_JSON_PROFILE,
    CanonicalizationError,
    CollectionRule,
    CollectionSchema,
    CollectionSemantics,
    canonical_json,
    canonical_json_bytes,
)
from ipfs_datasets_py.logic.ir_core.identity import (
    IDENTITY_PROFILE,
    IDENTITY_PROFILE_NAME,
    MULTICODEC_CODE,
    MULTIHASH_CODE,
    canonical_identity,
    cid_v1,
    identity_preimage,
    sha256_digest,
)


GOLDEN_PAYLOAD = {
    "title": "Cafe\u0301",
    "numbers": [Decimal("1.2300"), -0.0, 7],
    "tags": ["beta", "alpha", "beta"],
    "steps": ["review", "publish"],
    "evidence": [
        {"id": "b", "weight": 2},
        {"weight": 1, "id": "a"},
    ],
}
GOLDEN_SCHEMA = CollectionSchema(
    {
        "/numbers": "ordered",
        "/tags": "set-like",
        "/steps": "ordered",
        "/evidence": "multiset",
    },
    require_declared=True,
)
GOLDEN_PAYLOAD_BYTES = (
    b'{"evidence":[{"id":"a","weight":1},{"id":"b","weight":2}],'
    b'"numbers":[1.23,0,7],"steps":["review","publish"],'
    b'"tags":["alpha","beta"],"title":"Caf\xc3\xa9"}'
)
GOLDEN_PREIMAGE = (
    b'{"canonicalization":"ir-canonical-json-v1",'
    b'"collection_semantics":{"/evidence":"multiset","/numbers":"ordered",'
    b'"/steps":"ordered","/tags":"set-like"},"domain":"intent",'
    b'"identity_profile":"ir-canonical-identity-v1","payload":'
    + GOLDEN_PAYLOAD_BYTES
    + b',"schema_version":"1.0.0"}'
)
GOLDEN_DIGEST = (
    "sha256:3d0104b4ad4a380413b0582327ee6406"
    "c353af3620d00c646a3b4631bdcb9a70"
)
GOLDEN_CID = "bafkreib5aecljlkkhacbhmcyemt64zagynj26nra2aggi2r3iyy33s42oa"


def _identity(payload: object, schema: CollectionSchema):
    return canonical_identity(
        payload,
        domain="test-domain",
        schema_version="test-v1",
        collection_schema=schema,
    )


def test_golden_canonical_bytes_digest_and_cid() -> None:
    assert CANONICAL_JSON_PROFILE == "ir-canonical-json-v1"
    assert IDENTITY_PROFILE_NAME == "ir-canonical-identity-v1"
    assert IDENTITY_PROFILE.multicodec == "raw"
    assert IDENTITY_PROFILE.multihash == "sha2-256"
    assert MULTICODEC_CODE == 0x55
    assert MULTIHASH_CODE == 0x12

    assert (
        canonical_json_bytes(
            GOLDEN_PAYLOAD,
            collection_schema=GOLDEN_SCHEMA,
        )
        == GOLDEN_PAYLOAD_BYTES
    )
    identity = canonical_identity(
        GOLDEN_PAYLOAD,
        domain="intent",
        schema_version="1.0.0",
        collection_schema=GOLDEN_SCHEMA,
    )

    assert identity.canonical_bytes == GOLDEN_PREIMAGE
    assert identity_preimage(
        GOLDEN_PAYLOAD,
        domain="intent",
        schema_version="1.0.0",
        collection_schema=GOLDEN_SCHEMA,
    ) == GOLDEN_PREIMAGE
    assert identity.digest == GOLDEN_DIGEST
    assert identity.hexdigest == GOLDEN_DIGEST.removeprefix("sha256:")
    assert identity.cid == GOLDEN_CID
    assert identity.identifier == GOLDEN_CID
    assert identity.to_dict() == {
        "cid": GOLDEN_CID,
        "digest": GOLDEN_DIGEST,
        "domain": "intent",
        "profile": "ir-canonical-identity-v1",
        "schema_version": "1.0.0",
    }


def test_canonical_json_normalizes_text_maps_literals_and_numbers() -> None:
    composed = {"e\u0301": "Cafe\u0301", "null": None, "truth": True}
    assert canonical_json(composed) == '{"null":null,"truth":true,"é":"Café"}'
    assert canonical_json(
        [Decimal("-0"), Decimal("100.000"), Decimal("0.0012300"), 1.0]
    ) == "[0,100,0.00123,1]"


@pytest.mark.parametrize(
    "value",
    [
        {"not-json": {1, 2}},
        {1: "non-string key"},
        float("nan"),
        float("inf"),
        Decimal("-Infinity"),
        b"bytes are not JSON strings",
    ],
)
def test_canonical_json_rejects_values_outside_the_profile(value: object) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes(value)


def test_map_keys_that_collide_after_unicode_normalization_are_rejected() -> None:
    with pytest.raises(CanonicalizationError, match="collide after NFC"):
        canonical_json_bytes({"é": 1, "e\u0301": 2})


def test_collection_schema_validates_pointers_and_semantics() -> None:
    assert CollectionRule("/items", "set-like").semantics is CollectionSemantics.SET_LIKE
    assert CollectionSemantics.SET is CollectionSemantics.SET_LIKE
    assert CollectionSchema({"/items": CollectionSemantics.MULTISET}).to_dict() == {
        "/items": "multiset"
    }

    with pytest.raises(CanonicalizationError, match="JSON Pointer"):
        CollectionSchema({"items": "ordered"})
    with pytest.raises(CanonicalizationError, match="invalid JSON Pointer escape"):
        CollectionSchema({"/bad~escape": "ordered"})
    with pytest.raises(CanonicalizationError, match="unknown collection semantics"):
        CollectionSchema({"/items": "bag"})


def test_collection_semantics_keyword_is_a_schema_alias() -> None:
    payload = {"items": ["b", "a"]}
    declarations = {"/items": "set-like"}

    assert canonical_json_bytes(
        payload, collection_semantics=declarations
    ) == canonical_json_bytes(payload, collection_schema=declarations)
    assert canonical_identity(
        payload,
        domain="test",
        schema_version="v1",
        collection_semantics=declarations,
    ) == canonical_identity(
        payload,
        domain="test",
        schema_version="v1",
        collection_schema=declarations,
    )
    with pytest.raises(TypeError, match="either collection_schema"):
        canonical_json_bytes(
            payload,
            collection_schema=declarations,
            collection_semantics=declarations,
        )


def test_strict_collection_schema_requires_every_sequence_declaration() -> None:
    schema = CollectionSchema({"/declared": "ordered"}, require_declared=True)
    with pytest.raises(CanonicalizationError, match="/undeclared"):
        canonical_json_bytes(
            {"declared": [], "undeclared": []},
            collection_schema=schema,
        )


def test_ordered_set_like_and_multiset_semantics_are_distinct() -> None:
    schema = CollectionSchema(
        {
            "/ordered": "ordered",
            "/set": "set-like",
            "/bag": "multiset",
        },
        require_declared=True,
    )
    original = {
        "ordered": ["a", "b"],
        "set": ["b", "a", "b"],
        "bag": ["b", "a", "b"],
    }
    unordered_permutation = {
        "ordered": ["a", "b"],
        "set": ["a", "b"],
        "bag": ["b", "b", "a"],
    }
    changed_order = {
        **unordered_permutation,
        "ordered": ["b", "a"],
    }
    changed_multiplicity = {
        **unordered_permutation,
        "bag": ["a", "b"],
    }

    assert _identity(original, schema) == _identity(unordered_permutation, schema)
    assert _identity(original, schema) != _identity(changed_order, schema)
    assert _identity(original, schema) != _identity(changed_multiplicity, schema)
    assert canonical_json(original, collection_schema=schema) == (
        '{"bag":["a","b","b"],"ordered":["a","b"],"set":["a","b"]}'
    )


def test_wildcard_rules_apply_below_unordered_or_ordered_collections() -> None:
    schema = CollectionSchema(
        {
            "/groups": "ordered",
            "/groups/*/members": "set-like",
        },
        require_declared=True,
    )
    left = {
        "groups": [
            {"name": "reviewers", "members": ["bob", "alice", "bob"]},
            {"name": "owners", "members": ["zoe"]},
        ]
    }
    members_reordered = {
        "groups": [
            {"name": "reviewers", "members": ["alice", "bob"]},
            {"name": "owners", "members": ["zoe"]},
        ]
    }
    groups_reordered = {"groups": list(reversed(members_reordered["groups"]))}

    assert _identity(left, schema) == _identity(members_reordered, schema)
    assert _identity(left, schema) != _identity(groups_reordered, schema)


def test_collection_declaration_is_bound_into_identity_preimage() -> None:
    payload = {"values": ["a", "b"]}
    ordered = CollectionSchema({"/values": "ordered"}, require_declared=True)
    set_like = CollectionSchema({"/values": "set-like"}, require_declared=True)

    # Even though these particular payload bytes are the same, the schema
    # declaration is explicit identity material.
    assert canonical_json_bytes(payload, collection_schema=ordered) == (
        canonical_json_bytes(payload, collection_schema=set_like)
    )
    assert _identity(payload, ordered) != _identity(payload, set_like)


def test_domain_and_schema_version_separate_otherwise_identical_payloads() -> None:
    payload = {"id": "same"}
    intent_v1 = canonical_identity(
        payload, domain="intent", schema_version="v1"
    )
    security_v1 = canonical_identity(
        payload, domain="security", schema_version="v1"
    )
    intent_v2 = canonical_identity(
        payload, domain="intent", schema_version="v2"
    )

    assert len({intent_v1.cid, security_v1.cid, intent_v2.cid}) == 3
    with pytest.raises(CanonicalizationError, match="domain"):
        canonical_identity(payload, domain="", schema_version="v1")
    with pytest.raises(CanonicalizationError, match="schema_version"):
        canonical_identity(payload, domain="intent", schema_version=" v1 ")


def test_fixed_cid_profile_matches_the_multiformat_wire_bytes() -> None:
    data = b"fixed profile"
    digest = hashlib.sha256(data).digest()
    expected_wire = bytes((0x01, 0x55, 0x12, 0x20)) + digest

    import base64

    expected = (
        "b"
        + base64.b32encode(expected_wire)
        .decode("ascii")
        .rstrip("=")
        .lower()
    )
    assert cid_v1(data) == expected
    assert sha256_digest(data) == f"sha256:{digest.hex()}"


def test_optional_cid_modules_cannot_change_the_golden_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = canonical_identity(
        GOLDEN_PAYLOAD,
        domain="intent",
        schema_version="1.0.0",
        collection_schema=GOLDEN_SCHEMA,
    )

    # These are the optional paths used by legacy implementations.  The shared
    # profile must not inspect either one.
    monkeypatch.setitem(sys.modules, "multiformats", None)
    monkeypatch.setitem(sys.modules, "ipfs_datasets_py.utils.cid_utils", None)
    without_optional_dependencies = canonical_identity(
        GOLDEN_PAYLOAD,
        domain="intent",
        schema_version="1.0.0",
        collection_schema=GOLDEN_SCHEMA,
    )

    assert without_optional_dependencies == baseline
    assert without_optional_dependencies.cid == GOLDEN_CID
    assert without_optional_dependencies.digest == GOLDEN_DIGEST


def test_cid_matches_optional_multiformats_when_it_is_available() -> None:
    multiformats = pytest.importorskip("multiformats")
    identity = canonical_identity(
        GOLDEN_PAYLOAD,
        domain="intent",
        schema_version="1.0.0",
        collection_schema=GOLDEN_SCHEMA,
    )
    multihash = multiformats.multihash.digest(
        identity.canonical_bytes,
        "sha2-256",
    )
    optional_cid = multiformats.CID("base32", 1, "raw", multihash)

    assert str(optional_cid) == GOLDEN_CID
