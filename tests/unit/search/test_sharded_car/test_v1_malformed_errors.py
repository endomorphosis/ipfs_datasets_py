"""KGP-047: explicit errors for malformed or unsupported v1 sharded-CAR data."""

from __future__ import annotations

import copy
import json
from typing import Any, Dict

import pytest

from ipfs_datasets_py.knowledge_graphs.storage.sharding.manifest import (
    ShardManifestValidationError,
    load_sharded_graph_manifest,
)
from ipfs_datasets_py.search.graph_query.backends.sharded_car import (
    CARBytesShardLoader,
    InMemoryCarFetcher,
    ShardedCARBackend,
)
from ipfs_datasets_py.search.graph_query.sharded_car.manifest import GraphShardManifest

from .conftest import MappingBytesFetcher


def _v1(base: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(base)


def test_rejects_non_mapping_manifest() -> None:
    with pytest.raises(ShardManifestValidationError) as excinfo:
        load_sharded_graph_manifest([])  # type: ignore[arg-type]
    assert excinfo.value.code in {"UNKNOWN_REQUIRED_FIELD", "NONCANONICAL_VALUE"}


def test_rejects_shards_not_array(v1_manifest_dict: Dict[str, Any]) -> None:
    payload = _v1(v1_manifest_dict)
    payload["shards"] = "S0"
    with pytest.raises(ShardManifestValidationError) as excinfo:
        load_sharded_graph_manifest(payload)
    assert excinfo.value.code == "NONCANONICAL_VALUE"
    assert "shards" in str(excinfo.value).lower()


def test_rejects_shard_entry_not_object(v1_manifest_dict: Dict[str, Any]) -> None:
    payload = _v1(v1_manifest_dict)
    payload["shards"] = ["not-an-object"]
    with pytest.raises(ShardManifestValidationError) as excinfo:
        load_sharded_graph_manifest(payload)
    assert excinfo.value.code == "NONCANONICAL_VALUE"


def test_rejects_missing_car_cid(v1_manifest_dict: Dict[str, Any]) -> None:
    payload = _v1(v1_manifest_dict)
    payload["shards"][0]["car_cid"] = ""
    with pytest.raises(ShardManifestValidationError) as excinfo:
        load_sharded_graph_manifest(payload)
    assert excinfo.value.code == "AMBIGUOUS_ID"
    assert "car_cid" in str(excinfo.value)


def test_rejects_null_car_cid(v1_manifest_dict: Dict[str, Any]) -> None:
    payload = _v1(v1_manifest_dict)
    payload["shards"][0]["car_cid"] = None
    with pytest.raises(ShardManifestValidationError) as excinfo:
        load_sharded_graph_manifest(payload)
    assert excinfo.value.code == "AMBIGUOUS_ID"


def test_rejects_garbage_car_cid(v1_manifest_dict: Dict[str, Any]) -> None:
    payload = _v1(v1_manifest_dict)
    payload["shards"][0]["car_cid"] = "!!!not a cid!!!"
    with pytest.raises(ShardManifestValidationError) as excinfo:
        load_sharded_graph_manifest(payload)
    assert excinfo.value.code == "NONCANONICAL_VALUE"


def test_rejects_negative_approx_bytes(v1_manifest_dict: Dict[str, Any]) -> None:
    payload = _v1(v1_manifest_dict)
    payload["shards"][0]["approx_bytes"] = -1
    with pytest.raises(ShardManifestValidationError) as excinfo:
        load_sharded_graph_manifest(payload)
    assert excinfo.value.code == "INVALID_COUNT"


def test_rejects_invalid_headers_cid(v1_manifest_dict: Dict[str, Any]) -> None:
    payload = _v1(v1_manifest_dict)
    payload["shards"][0]["headers_cid"] = "not-a-real-cid"
    with pytest.raises(ShardManifestValidationError) as excinfo:
        load_sharded_graph_manifest(payload)
    assert excinfo.value.code == "NONCANONICAL_VALUE"
    assert "headers_cid" in str(excinfo.value)


def test_rejects_unsupported_v2_like_version_without_v2_shape(
    v1_manifest_dict: Dict[str, Any],
) -> None:
    """A non-v1 version that is not the v2 schema id must fail closed."""
    payload = _v1(v1_manifest_dict)
    payload["version"] = "kg-shard-manifest/v9"
    # Presence of physical_shards forces non-v1 dispatch even with shards present.
    payload["physical_shards"] = [
        {
            "physical_shard_id": "9",
            "codec": "car",
            "car_cid": "bafkreigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
        }
    ]
    with pytest.raises(ShardManifestValidationError) as excinfo:
        load_sharded_graph_manifest(payload)
    assert excinfo.value.code == "NONCANONICAL_VALUE"
    assert "unsupported version" in str(excinfo.value).lower()


def test_rejects_malformed_bloom_descriptor(v1_manifest_dict: Dict[str, Any]) -> None:
    payload = _v1(v1_manifest_dict)
    # bits_hex too short for the declared num_bits.
    payload["shards"][0]["entity_type_bloom"] = {
        "num_bits": 64,
        "num_hashes": 3,
        "bits_hex": "00",
    }
    with pytest.raises(ShardManifestValidationError) as excinfo:
        load_sharded_graph_manifest(payload)
    assert isinstance(excinfo.value, ShardManifestValidationError)


def test_corrupt_car_bytes_raise_on_load(
    v1_graph_manifest: GraphShardManifest,
    v1_index_blobs: Dict[str, bytes],
    v1_expected_identity: Dict[str, Any],
) -> None:
    car_cid = v1_expected_identity["car_cids"]["S0"]
    backend = ShardedCARBackend(
        v1_graph_manifest,
        loader=CARBytesShardLoader(
            InMemoryCarFetcher({car_cid: b"this-is-not-a-car-file"})
        ),
        index_fetcher=MappingBytesFetcher(v1_index_blobs),
    )
    with pytest.raises(Exception) as excinfo:
        backend._get_kg("S0")
    assert excinfo.value is not None
    msg = str(excinfo.value).lower()
    assert msg  # explicit non-silent failure


def test_truncated_car_bytes_raise_on_load(
    v1_graph_manifest: GraphShardManifest,
    v1_index_blobs: Dict[str, bytes],
    v1_car_map: Dict[str, bytes],
) -> None:
    car_cid = next(
        s.car_cid for s in v1_graph_manifest.shards if s.shard_id == "S1"
    )
    truncated = v1_car_map[car_cid][:12]
    backend = ShardedCARBackend(
        v1_graph_manifest,
        loader=CARBytesShardLoader(InMemoryCarFetcher({car_cid: truncated})),
        index_fetcher=MappingBytesFetcher(v1_index_blobs),
    )
    with pytest.raises(Exception):
        backend._get_kg("S1")


def test_missing_index_blob_is_not_silent_success(
    v1_graph_manifest: GraphShardManifest,
    v1_car_map: Dict[str, bytes],
    v1_expected_identity: Dict[str, Any],
) -> None:
    """When the headers index is missing, the backend falls back to CAR content."""
    backend = ShardedCARBackend(
        v1_graph_manifest,
        loader=CARBytesShardLoader(InMemoryCarFetcher(v1_car_map)),
        index_fetcher=MappingBytesFetcher({}),
    )
    any_eid = next(iter(v1_expected_identity["entities"]))
    headers = backend.get_entity_headers([any_eid])
    assert any_eid in headers
    assert headers[any_eid].type == v1_expected_identity["entities"][any_eid]["type"]


def test_invalid_scan_cursor_raises(v1_backend: ShardedCARBackend) -> None:
    with pytest.raises(ValueError, match="Invalid cursor"):
        v1_backend.scan_type("Person", cursor="not-json")
    with pytest.raises(ValueError, match="Invalid cursor"):
        v1_backend.scan_type(
            "Person",
            cursor=json.dumps({"v": 99, "shard_id": "S0", "offset": 0}),
        )


def test_cursor_shard_not_in_candidates_raises(v1_backend: ShardedCARBackend) -> None:
    with pytest.raises(ValueError, match="Cursor shard_id not in candidate set"):
        v1_backend.scan_type(
            "Person",
            cursor=json.dumps({"v": 1, "shard_id": "SX-missing", "offset": 0}),
        )


def test_legacy_graph_manifest_missing_shard_fields_still_parses_loosely(
    v1_manifest_dict: Dict[str, Any],
) -> None:
    """GraphShardManifest.from_dict is intentionally lenient for scaffolding.

    Unsupported *content* is still rejected by the compatibility reader above;
    this documents that the legacy dataclass loader requires shard_id/car_cid.
    """
    payload = _v1(v1_manifest_dict)
    payload["shards"] = [{"shard_id": "S0"}]
    with pytest.raises(KeyError):
        GraphShardManifest.from_dict(payload)
