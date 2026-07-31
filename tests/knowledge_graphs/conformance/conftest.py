"""Pytest fixtures for KGP-020 cross-surface conformance."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterator

import pytest

from .harness import close_all, open_all_surfaces, seed_catalog
from .surfaces import SurfaceAdapter, load_seed_graph, load_vector_catalog


@pytest.fixture
def kg_paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "kg_catalog.sqlite", tmp_path / "kg_payloads"


@pytest.fixture
def vector_catalog() -> dict:
    return load_vector_catalog()


@pytest.fixture
def seed_graph() -> dict:
    return load_seed_graph()


@pytest.fixture
def seeded_catalog(kg_paths) -> dict:
    catalog, store = kg_paths
    meta = seed_catalog(catalog, store)
    meta["catalog"] = catalog
    meta["store"] = store
    return meta


@pytest.fixture
def surfaces(kg_paths) -> Iterator[Dict[str, SurfaceAdapter]]:
    catalog, store = kg_paths
    opened = open_all_surfaces(catalog, store)
    try:
        yield opened
    finally:
        close_all(opened)


@pytest.fixture
def seeded_surfaces(seeded_catalog) -> Iterator[Dict[str, SurfaceAdapter]]:
    catalog = seeded_catalog["catalog"]
    store = seeded_catalog["store"]
    opened = open_all_surfaces(catalog, store)
    try:
        yield opened
    finally:
        close_all(opened)
