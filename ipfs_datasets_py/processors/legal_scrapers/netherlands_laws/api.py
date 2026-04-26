"""Public API for the Netherlands legal data pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .builders.ipfs_indexes import build_all_indexes, build_bm25_index, build_knowledge_graph, build_vector_index
from .builders.ipfs_package import build_ipfs_cid_package
from .builders.normalized_package import build_normalized_package
from .upload import upload_datasets, verify_remote_datasets


async def scrape(
    *,
    output_dir: Path,
    document_urls: list[str] | None = None,
    seed_urls: list[str] | None = None,
    use_default_seeds: bool = False,
    max_documents: int | None = None,
    max_seed_pages: int | None = None,
    crawl_depth: int = 1,
    rate_limit_delay: float = 0.5,
    skip_existing: bool = False,
    resume: bool = False,
) -> dict[str, Any]:
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import scrape_netherlands_laws_from_parameters

    params = {
        "output_dir": str(output_dir),
        "document_urls": document_urls or [],
        "seed_urls": seed_urls or [],
        "use_default_seeds": use_default_seeds,
        "max_documents": max_documents,
        "max_seed_pages": max_seed_pages,
        "crawl_depth": crawl_depth,
        "rate_limit_delay": rate_limit_delay,
        "skip_existing": skip_existing,
        "resume": resume,
    }
    return await scrape_netherlands_laws_from_parameters(params)


def build_package_set(raw_dir: Path | None = None) -> dict[str, Path]:
    normalized = build_normalized_package(raw_dir=raw_dir)
    base = build_ipfs_cid_package(raw_dir=raw_dir)
    indexes = build_all_indexes(source_dir=base)
    return {"normalized": normalized, "base": base, "vector": indexes[0], "bm25": indexes[1], "knowledge-graph": indexes[2]}


def upload_all(targets: Iterable[str] | None = None, **kwargs: Any) -> list[dict[str, Any]]:
    return upload_datasets(targets, **kwargs)


def verify_all(targets: Iterable[str] | None = None, **kwargs: Any) -> list[dict[str, Any]]:
    return verify_remote_datasets(targets, **kwargs)
