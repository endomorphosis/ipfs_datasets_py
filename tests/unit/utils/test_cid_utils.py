"""Tests for the shared multiformats-backed CID utilities."""

from __future__ import annotations

import builtins
import math

import pytest

from benchmarks.logic_pipeline.content_addressing import (
    canonical_dag_json_bytes as benchmark_canonical_dag_json_bytes,
    cid_for_bytes as benchmark_cid_for_bytes,
    cid_for_dag_json as benchmark_cid_for_dag_json,
    validate_cid as benchmark_validate_cid,
)
from ipfs_datasets_py.utils.cid_utils import (
    canonical_dag_json_bytes,
    canonical_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
    cid_for_obj,
    validate_cid,
)


def test_isolated_benchmark_bridge_matches_the_shared_reference_utility() -> None:
    payload = {"unicode": "café", "nested": {"z": 2, "a": 1}}
    raw = "A licensed agency shall retain each record.".encode("utf-8")

    assert benchmark_canonical_dag_json_bytes(payload) == (
        canonical_dag_json_bytes(payload)
    )
    assert benchmark_cid_for_dag_json(payload) == cid_for_dag_json(payload)
    assert benchmark_cid_for_bytes(raw) == cid_for_bytes(raw)


def test_isolated_bridge_fallback_matches_multiformats_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"unicode": "λ", "nested": {"z": 2, "a": [1, True, None]}}
    raw = b"\x00exact source bytes\n"
    expected_dag_json = cid_for_dag_json(payload)
    expected_raw = cid_for_bytes(raw)
    real_import = builtins.__import__

    def reject_multiformats(
        name: str,
        *args: object,
        **kwargs: object,
    ) -> object:
        if name == "multiformats" or name.startswith("multiformats."):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_multiformats)

    assert benchmark_cid_for_dag_json(payload) == expected_dag_json
    assert benchmark_cid_for_bytes(raw) == expected_raw
    assert (
        benchmark_validate_cid(
            expected_dag_json,
            codecs=("dag-json",),
        )
        == expected_dag_json
    )
    assert (
        benchmark_validate_cid(expected_raw, codecs=("raw",))
        == expected_raw
    )


def test_raw_and_dag_json_cids_are_canonical_cidv1() -> None:
    raw_cid = cid_for_bytes(b'{"a":1}')
    dag_json_cid = cid_for_dag_json({"a": 1})

    assert raw_cid.startswith("b")
    assert dag_json_cid.startswith("b")
    assert raw_cid != dag_json_cid
    assert validate_cid(raw_cid, codecs=("raw",)) == raw_cid
    assert validate_cid(dag_json_cid, codecs=("dag-json",)) == dag_json_cid


def test_dag_json_cid_is_stable_across_mapping_order() -> None:
    left = {"unicode": "café", "nested": {"z": 2, "a": 1}}
    right = {"nested": {"a": 1, "z": 2}, "unicode": "café"}

    assert canonical_dag_json_bytes(left) == canonical_dag_json_bytes(right)
    assert cid_for_dag_json(left) == cid_for_dag_json(right)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_dag_json_canonicalization_rejects_nonfinite_numbers(bad: float) -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        canonical_dag_json_bytes({"value": bad})


def test_dag_json_canonicalization_does_not_stringify_python_objects() -> None:
    marker = object()

    with pytest.raises(TypeError, match="JSON serializable"):
        canonical_dag_json_bytes({"value": marker})

    # The pre-existing serializer remains compatible for legacy callers.
    assert canonical_json_bytes({"value": marker})


@pytest.mark.parametrize(
    "value",
    [
        {1: "integer-key"},
        {None: "null-key"},
        {True: "boolean-key"},
        {"nested": {1: "integer-key"}},
    ],
)
def test_dag_json_rejects_non_string_map_keys_without_cid_collisions(
    value: object,
) -> None:
    for canonicalizer in (
        canonical_dag_json_bytes,
        benchmark_canonical_dag_json_bytes,
    ):
        with pytest.raises(TypeError, match="non-string DAG-JSON map key"):
            canonicalizer(value)


def test_dag_json_rejects_python_tuple_projection() -> None:
    for canonicalizer in (
        canonical_dag_json_bytes,
        benchmark_canonical_dag_json_bytes,
    ):
        with pytest.raises(TypeError, match="JSON serializable as DAG-JSON"):
            canonicalizer({"items": ("a", "b")})


def test_legacy_object_cid_remains_raw_and_distinct_from_dag_json() -> None:
    payload = {"a": 1}
    legacy_cid = cid_for_obj(payload)
    dag_json_cid = cid_for_dag_json(payload)

    assert validate_cid(legacy_cid, codecs=("raw",)) == legacy_cid
    assert validate_cid(dag_json_cid, codecs=("dag-json",)) == dag_json_cid
    assert legacy_cid != dag_json_cid


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-cid",
        "BAFKREIF2PALL7DYBZ7VECQKA3ZO24IRDWABWDI4WC55JZNAQ75Q7EAAVVU",
    ],
)
def test_validate_cid_rejects_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError, match="CID"):
        validate_cid(value)


def test_validate_cid_enforces_codec() -> None:
    raw_cid = cid_for_bytes(b"abc")

    with pytest.raises(ValueError, match="version/base/codec/multihash"):
        validate_cid(raw_cid, codecs=("dag-json",))


def test_validate_cid_rejects_truncated_sha2_256_multihash() -> None:
    from multiformats import CID, multihash

    truncated = str(
        CID(
            "base32",
            1,
            "raw",
            multihash.wrap(bytes(16), "sha2-256"),
        )
    )

    for validator in (validate_cid, benchmark_validate_cid):
        with pytest.raises(ValueError, match="version/base/codec/multihash"):
            validator(truncated)
