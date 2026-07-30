"""Shared fixtures for frozen v1 sharded-CAR compatibility tests (KGP-047).

The legacy import path ``ipfs_datasets_py.data_transformation.ipld.knowledge_graph``
was relocated to ``ipfs_datasets_py.processors.storage.ipld.knowledge_graph``.
Install a thin alias before importing the supported sharded-CAR reader so the
frozen fixtures exercise production code without mutating library sources.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, Mapping

import pytest

# ---------------------------------------------------------------------------
# Import alias for migrated IPLD knowledge-graph module
# ---------------------------------------------------------------------------

_ALIAS_ROOT = "ipfs_datasets_py.data_transformation"
_ALIAS_IPLD = f"{_ALIAS_ROOT}.ipld"
_ALIAS_KG = f"{_ALIAS_IPLD}.knowledge_graph"


def _install_data_transformation_alias() -> None:
    if _ALIAS_KG in sys.modules:
        return
    import ipfs_datasets_py.processors.storage.ipld.knowledge_graph as kg_mod

    root = types.ModuleType(_ALIAS_ROOT)
    root.__path__ = []  # type: ignore[attr-defined]
    sys.modules[_ALIAS_ROOT] = root

    ipld = types.ModuleType(_ALIAS_IPLD)
    ipld.__path__ = []  # type: ignore[attr-defined]
    sys.modules[_ALIAS_IPLD] = ipld

    sys.modules[_ALIAS_KG] = kg_mod


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
        try:
            return self._blobs[cid]
        except KeyError as exc:
            raise KeyError(f"No index bytes for cid={cid}") from exc


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
def v1_car_bytes(v1_fixture_dir: Path, v1_expected_identity: Dict[str, Any]) -> Dict[str, bytes]:
    cars: Dict[str, bytes] = {}
    for sid, expected_sha in v1_expected_identity["car_sha256"].items():
        data = (v1_fixture_dir / f"{sid}.car").read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        assert actual == expected_sha, f"frozen CAR {sid} digests drifted"
        cars[sid] = data
    return cars


@pytest.fixture(scope="session")
def v1_car_map(
    v1_car_bytes: Dict[str, bytes], v1_expected_identity: Dict[str, Any]
) -> Dict[str, bytes]:
    """Map car_cid -> CAR bytes as the production fetcher would see them."""
    return {
        v1_expected_identity["car_cids"][sid]: data
        for sid, data in v1_car_bytes.items()
    }


@pytest.fixture(scope="session")
def v1_graph_manifest(v1_manifest_dict: Dict[str, Any]) -> GraphShardManifest:
    return GraphShardManifest.from_dict(v1_manifest_dict)


@pytest.fixture
def v1_backend(
    v1_graph_manifest: GraphShardManifest,
    v1_car_map: Dict[str, bytes],
    v1_index_blobs: Dict[str, bytes],
) -> ShardedCARBackend:
    return ShardedCARBackend(
        v1_graph_manifest,
        loader=CARBytesShardLoader(fetcher=InMemoryCarFetcher(cars=v1_car_map)),
        index_fetcher=MappingBytesFetcher(v1_index_blobs),
        cache_size=8,
    )
