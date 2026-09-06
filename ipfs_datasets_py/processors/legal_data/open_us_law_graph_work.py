"""Append-only JSONL work shards for legal GraphRAG projection.

Lets a crash resume structure and citation passes without rewriting the
full in-memory graph. Parts are 4096-row batches. The sealed
``projection.json`` is still the complete-stage artifact. Shared by
Open US Law, state-law, US Code, and Federal Register projectors.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    canonical_json_dumps,
)

GRAPH_WORK_SCHEMA = "legal-graph-projection-work-v1"
LEGACY_GRAPH_WORK_SCHEMAS = frozenset(
    {
        GRAPH_WORK_SCHEMA,
        "open-us-law-graph-projection-work-v1",
    }
)
MANIFEST_NAME = "manifest.json"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def empty_manifest(corpus_digest: str) -> dict[str, Any]:
    return {
        "citation_parts": 0,
        "citation_rows_done": 0,
        "corpus_digest": str(corpus_digest or ""),
        "edge_count": 0,
        "node_count": 0,
        "schema": GRAPH_WORK_SCHEMA,
        "stage": "structure",
        "structure_parts": 0,
        "structure_rows_done": 0,
    }


def read_manifest(root: Path) -> dict[str, Any] | None:
    path = root / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") not in LEGACY_GRAPH_WORK_SCHEMAS:
        return None
    return payload


def write_manifest(root: Path, manifest: Mapping[str, Any]) -> None:
    _atomic_write_text(root / MANIFEST_NAME, canonical_json_dumps(dict(manifest)) + "\n")


def reset_work_dir(root: Path, corpus_digest: str) -> dict[str, Any]:
    if root.exists():
        shutil.rmtree(root)
    (root / "structure").mkdir(parents=True)
    (root / "citations").mkdir(parents=True)
    manifest = empty_manifest(corpus_digest)
    write_manifest(root, manifest)
    return manifest


def prepare_work_dir(root: Path, corpus_digest: str) -> dict[str, Any]:
    """Resume a matching work dir, or start a new one."""

    digest = str(corpus_digest or "")
    existing = read_manifest(root)
    if (
        existing is not None
        and str(existing.get("corpus_digest") or "") == digest
        and digest
        and (root / "structure").is_dir()
        and (root / "citations").is_dir()
    ):
        return existing
    return reset_work_dir(root, digest)


def append_jsonl_part(
    directory: Path,
    part_index: int,
    records: Sequence[Mapping[str, Any]],
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"part-{int(part_index):06d}.jsonl"
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(canonical_json_dumps(dict(record)))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)
    return path


def iter_jsonl_parts(directory: Path) -> Iterator[dict[str, Any]]:
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("part-*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    yield payload
