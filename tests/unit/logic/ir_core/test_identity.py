"""Golden contracts for shared IR canonicalization and identity."""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from decimal import Decimal

import pytest

from ipfs_datasets_py.logic.ir_core.canonical import (
    CANONICAL_JSON_PROFILE,
    CanonicalizationError,
    CollectionKind,
    CollectionRule,
    CollectionSchema,
    canonical_bytes,
    canonical_json,
)
from ipfs_datasets_py.logic.ir_core.identity import (
    CID_CODEC,
    CID_VERSION,
    DIGEST_ALGORITHM,
    IDENTITY_PROFILE,
    MULTIBASE,
    CanonicalIdentity,
    cid_for_bytes,
    identity_for,
    verify_identity,
)


def test_canonical_utf8_json_golden_vector() -> None:
    first = {
        "z": None,
        "number": Decimal("12.3400"),
        "negative_zero": -0.0,
        "text": "cafe\u0301",
        "array": [True, 1.0, 1e-7],
    }
    reordered = {
        "array": [True, 1, Decimal("0.00000010")],
        "text": "caf\u00e9",
        "negative_zero": 0,
        "number": 12.34,
        "z": None,
    }
    expected = (
        b'{"array":[true,1,0.0000001],"negative_zero":0,"number":12.34,'
        b'"text":"caf\xc3\xa9","z":null}'
    )

    assert canonical_bytes(first) == expected
    assert canonical_bytes(reordered) == expected
    assert canonical_json(first).encode("utf-8") == expected
    assert not expected.endswith(b"\n")


@dataclass(frozen=True)
class _Fixture:
    name: str
    enabled: bool


def test_dataclasses_tuples_and_string_enums_are_json_values() -> None:
    value = {"fixture": _Fixture("node", True), "kinds": (CollectionKind.ORDERED,)}
    assert canonical_json(value) == (
        '{"fixture":{"enabled":true,"name":"node"},"kinds":["ordered"]}'
    )


@pytest.mark.parametrize(
    "value, match",
    [
        ({1: "not a JSON object"}, "object key"),
        ({"number": float("nan")}, "NaN"),
        ({"number": float("inf")}, "infinite"),
        ({"binary": b"bytes"}, "unsupported type bytes"),
        ({"text": "\ud800"}, "unpaired Unicode surrogate"),
        ({"e\u0301": 1, "\u00e9": 2}, "collide after Unicode normalization"),
    ],
)
def test_noncanonical_or_non_json_values_fail_closed(value: object, match: str) -> None:
    with pytest.raises(CanonicalizationError, match=match):
        canonical_bytes(value)


def test_ordered_set_like_and_multiset_semantics_are_distinct() -> None:
    rules = CollectionSchema(
        {
            "/steps": "ordered",
            "/tags": "set-like",
            "/votes": "multiset",
            "/nodes": "ordered",
            "/nodes/*/refs": "set-like",
        },
        require_explicit=True,
    )
    first = {
        "steps": ["prepare", "commit"],
        "tags": ["b", "a", "a"],
        "votes": ["yes", "no", "yes"],
        "nodes": [{"refs": ["z", "a"]}],
    }
    equivalent = {
        "nodes": [{"refs": ["a", "z", "a"]}],
        "votes": ["yes", "yes", "no"],
        "tags": ["a", "b"],
        "steps": ["prepare", "commit"],
    }

    expected = (
        b'{"nodes":[{"refs":["a","z"]}],"steps":["prepare","commit"],'
        b'"tags":["a","b"],"votes":["no","yes","yes"]}'
    )
    assert canonical_bytes(first, collection_schema=rules) == expected
    assert canonical_bytes(equivalent, collection_schema=rules) == expected

    reversed_steps = {**equivalent, "steps": list(reversed(equivalent["steps"]))}
    fewer_votes = {**equivalent, "votes": ["yes", "no"]}
    assert canonical_bytes(reversed_steps, collection_schema=rules) != expected
    assert canonical_bytes(fewer_votes, collection_schema=rules) != expected


def test_strict_collection_schema_rejects_an_undeclared_array() -> None:
    schema = CollectionSchema(
        [CollectionRule("/tags", CollectionKind.SET)],
        require_explicit=True,
    )
    with pytest.raises(CanonicalizationError, match="/steps.*no declared"):
        canonical_bytes({"tags": [], "steps": []}, collection_schema=schema)


def test_identity_golden_vector_and_fixed_profile() -> None:
    schema = CollectionSchema({"/tags": "set-like"})
    identity = identity_for(
        {"name": "demo", "tags": ["z", "a", "a"]},
        domain="intent",
        schema_version="1.0",
        collection_schema=schema,
    )

    assert identity.canonical_bytes == (
        b'{"canonical_json":"IRCanonicalJSON@1","domain":"intent",'
        b'"payload":{"name":"demo","tags":["a","z"]},'
        b'"profile":"IRCanonicalIdentity@1","schema_version":"1.0"}'
    )
    assert identity.digest == (
        "sha256:26c6ad917f0d35e24a48ae2e8a49ba9cf89ef3b8bdba4b3fcaf663c033515b06"
    )
    assert identity.cid == "bafkreibgy2wzc7yngxreusfof2fetou47cpphof5xjft7sxwmpadguk3ay"
    assert identity.to_dict() == {
        "cid": identity.cid,
        "digest": identity.digest,
        "domain": "intent",
        "profile": IDENTITY_PROFILE,
        "schema_version": "1.0",
    }
    assert identity.sha256 == identity.digest.split(":", 1)[1]
    assert verify_identity(
        identity,
        {"tags": ["a", "z"], "name": "demo"},
        collection_schema=schema,
    )
    assert not verify_identity(
        identity,
        {"tags": ["a", "x"], "name": "demo"},
        collection_schema=schema,
    )


def test_domain_and_schema_version_separate_otherwise_identical_payloads() -> None:
    payload = {"claim": "same bytes"}
    identities = {
        identity_for(payload, domain="legal", schema_version="1"),
        identity_for(payload, domain="security", schema_version="1"),
        identity_for(payload, domain="legal", schema_version="2"),
    }
    assert len({identity.digest for identity in identities}) == 3
    assert len({identity.cid for identity in identities}) == 3


def test_identity_preserves_arbitrary_precision_canonical_numbers() -> None:
    precise = identity_for(
        {"number": Decimal("1.0000000000000000001")},
        domain="test",
        schema_version="1",
    )
    rounded = identity_for({"number": 1}, domain="test", schema_version="1")

    assert b'"number":1.0000000000000000001' in precise.canonical_bytes
    assert precise != rounded


def test_ordered_semantics_affect_identity_but_set_and_multiset_order_do_not() -> None:
    ordered = CollectionSchema({"/items": "ordered"})
    set_like = CollectionSchema({"/items": "set-like"})
    multiset = CollectionSchema({"/items": "multiset"})
    forward = {"items": ["a", "a", "b"]}
    reverse = {"items": ["a", "a", "b"][::-1]}

    assert identity_for(
        forward, domain="test", schema_version="1", collection_schema=ordered
    ) != identity_for(reverse, domain="test", schema_version="1", collection_schema=ordered)
    assert identity_for(
        forward, domain="test", schema_version="1", collection_schema=set_like
    ) == identity_for(reverse, domain="test", schema_version="1", collection_schema=set_like)
    assert identity_for(
        forward, domain="test", schema_version="1", collection_schema=multiset
    ) == identity_for(reverse, domain="test", schema_version="1", collection_schema=multiset)
    assert identity_for(
        forward, domain="test", schema_version="1", collection_schema=multiset
    ) != identity_for(
        {"items": ["a", "b"]},
        domain="test",
        schema_version="1",
        collection_schema=multiset,
    )


def test_cid_is_identical_with_optional_dependency_present_or_absent(monkeypatch) -> None:
    payload = b"shared identity vector"
    expected = cid_for_bytes(payload)
    real_import = builtins.__import__

    def without_multiformats(name, *args, **kwargs):
        if name == "multiformats" or name.startswith("multiformats."):
            raise ImportError("simulated optional dependency absence")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_multiformats)
    assert cid_for_bytes(payload) == expected

    # When installed, the optional implementation is only an oracle.  The
    # production implementation above never imports it.
    monkeypatch.setattr(builtins, "__import__", real_import)
    try:
        from multiformats import CID, multihash
    except ImportError:
        reference = expected
    else:
        reference = str(
            CID(
                MULTIBASE,
                CID_VERSION,
                CID_CODEC,
                multihash.digest(payload, DIGEST_ALGORITHM),
            )
        )
    assert expected == reference


def test_identity_metadata_is_immutable_and_invalid_namespaces_fail() -> None:
    identity = identity_for({}, domain="legal", schema_version="1")
    assert isinstance(identity, CanonicalIdentity)
    with pytest.raises(Exception):  # frozen dataclass raises FrozenInstanceError
        identity.cid = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="surrounding whitespace"):
        identity_for({}, domain=" legal", schema_version="1")
    with pytest.raises(ValueError, match="control"):
        identity_for({}, domain="legal", schema_version="1\n")


def test_profile_constants_are_explicit() -> None:
    assert CANONICAL_JSON_PROFILE == "IRCanonicalJSON@1"
    assert IDENTITY_PROFILE == "IRCanonicalIdentity@1"
    assert (DIGEST_ALGORITHM, CID_VERSION, CID_CODEC, MULTIBASE) == (
        "sha2-256",
        1,
        "raw",
        "base32",
    )

