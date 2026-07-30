"""Shared fixtures for frozen v1 sharded-CAR compatibility tests."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, Mapping

import pytest

# ``search.graph_query.sharded_car`` imports
# ``ipfs_datasets_py.data_transformation.ipld.knowledge_graph``. In this tree the
# implementation lives under ``processors.storage.ipld``; install a stable alias
# so CAR loaders and publishers resolve the same IPLDKnowledgeGraph.
_ALIAS_ROOT = "ipfs_datasets_py.data_transformation"
_ALIAS_IPLD = f"{_ALIAS_ROOT}.ipld"
_ALIAS_KG = f"{_ALIAS_ROOT}.ipld.knowledge_graph"


def _install_data_transformation_alias() -> None:
    if _ALIAS_KG in sys.modules:
        return
    real = __import__(
        "ipfs_datasets_py.processors.storage.ipld.knowledge_graph",
        fromlist=["IPLDKnowledgeGraph"],
    )
    sys.modules[_ALIAS_KG] = real

    ipld_mod = types.ModuleType(_ALIAS_IPLD)
    ipld_mod.knowledge_graph = real  # type: ignore[attr-defined]
    sys.modules[_ALIAS_IPLD] = ipld_mod

    root_mod = types.ModuleType(_ALIAS_ROOT)
    root_mod.__path__ = []  # type: ignore[attr-defined]
    root_mod.ipld = ipld_mod  # type: ignore[attr-defined]
    sys.modules[_ALIAS_ROOT] = root_mod


_install_data_transformation_alias()

from ipfs_datasets_py.search.graph_query.backends.sharded_car import (  # noqa: E402
    CARBytesShardLoader,
    InMemoryCarFetcher,
    ShardedCARBackend,
)
from ipfs_datasets_py.search.graph_query.sharded_car.manifest import (  # noqa: E402
    GraphShardManifest,
)

FIXTURES_V1 = Path(__file__).resolve().parent / "fixtures" / "v1"


class MappingBytesFetcher:
    """In-memory BytesFetcher for index JSON blobs keyed by CID."""

    def __init__(self, blobs: Mapping[str, bytes]) -> None:
        self._blobs = dict(blobs)

    def fetch(self, cid: str) -> bytes:
        data = self._blobs.get(cid)
        if data is None:
            raise KeyError(f"No index bytes for cid={cid}")
        return data


@pytest.fixture(scope="session")
def v1_fixture_dir() -> Path:
    assert FIXTURES_V1.is_dir(), f"missing frozen fixtures at {FIXTURES_V1}"
    return FIXTURES_V1


@pytest.fixture(scope="session")
def v1_manifest_dict(v1_fixture_dir: Path) -> Dict[str, Any]:
    return json.loads((v1_fixture_dir / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def v1_expected_identity(v1_fixture_dir: Path) -> Dict[str, Any]:
    return json.loads(
        (v1_fixture_dir / "expected_identity.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="session")
def v1_index_blobs(v1_fixture_dir: Path) -> Dict[str, bytes]:
    raw = json.loads((v1_fixture_dir / "index_blobs.json").read_text(encoding="utf-8"))
    return {cid: base64.b64decode(b64) for cid, b64 in raw.items()}


@pytest.fixture(scope="session")
def v1_car_bytes(
    v1_fixture_dir: Path, v1_expected_identity: Dict[str, Any]
) -> Dict[str, bytes]:
    """Decode text-safe ``.car.b64`` fixtures; assert frozen SHA-256 digests.

    Binary ``.car`` blobs are not checked into the tree (proposal gate default
    is ``allow_binary=false``). Runtime bytes match the original frozen CARs.
    """
    out: Dict[str, bytes] = {}
    for shard_id, expected_digest in v1_expected_identity["car_sha256"].items():
        b64_path = v1_fixture_dir / f"{shard_id}.car.b64"
        assert b64_path.is_file(), f"missing text-safe CAR fixture: {b64_path.name}"
        data = base64.b64decode(b64_path.read_text(encoding="ascii").strip())
        digest = hashlib.sha256(data).hexdigest()
        assert digest == expected_digest, (
            f"frozen CAR {shard_id} digests drifted"
        )
        out[shard_id] = data
    return out


@pytest.fixture(scope="session")
def v1_car_map(
    v1_car_bytes: Dict[str, bytes], v1_expected_identity: Dict[str, Any]
) -> Dict[str, bytes]:
    """Map car_cid -> CAR bytes as the production fetcher would see them."""
    return {
        v1_expected_identity["car_cids"][shard_id]: data
        for shard_id, data in v1_car_bytes.items()
    }


@pytest.fixture(scope="session")
def v1_graph_manifest(v1_manifest_dict: Dict[str, Any]) -> GraphShardManifest:
    return GraphShardManifest.from_dict(v1_manifest_dict)


@pytest.fixture(scope="session")
def v1_backend(
    v1_graph_manifest: GraphShardManifest,
    v1_car_map: Dict[str, bytes],
    v1_index_blobs: Dict[str, bytes],
) -> ShardedCARBackend:
    return ShardedCARBackend(
        v1_graph_manifest,
        loader=CARBytesShardLoader(InMemoryCarFetcher(v1_car_map)),
        index_fetcher=MappingBytesFetcher(v1_index_blobs),
    )
