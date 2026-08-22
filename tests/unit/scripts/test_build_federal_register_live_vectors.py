"""Hermetic tests for LCR-071 live GTE-small vector + centroid routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.ops.legal_data.build_federal_register_live_vectors as vec


def _write_body(corpus_dir: Path, legal_id: str, text: str, *, content_hash: str) -> None:
    rel = f"bodies/{legal_id.replace(':', '_')}.json"
    path = corpus_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"legal_id": legal_id, "text": text, "content_hash": content_hash}),
        encoding="utf-8",
    )
    with (corpus_dir / "index.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "legal_id": legal_id,
                    "path": rel,
                    "status": "verified",
                    "content_hash": content_hash,
                }
            )
            + "\n"
        )


def test_missing_corpus_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(vec.LiveVectorError, match="corpus index missing"):
        vec.build_live_vectors(
            corpus_dir=tmp_path / "missing",
            vector_dir=tmp_path / "vectors",
            require_complete=False,
            write_receipt=False,
            backend="projection",
        )


def test_projection_backend_binds_centroid_routes(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    _write_body(
        corpus,
        "fr:2026-04129:2026-03-03",
        "Department of Energy notice 40 CFR 52.21",
        content_hash="ab" * 32,
    )
    _write_body(
        corpus,
        "fr:2026-04130:2026-03-03",
        "Environmental Protection Agency proposed rule",
        content_hash="cd" * 32,
    )
    report = vec.build_live_vectors(
        corpus_dir=corpus,
        vector_dir=tmp_path / "vectors",
        repository_root=tmp_path / "repo",
        require_complete=False,
        limit=2,
        backend="projection",
        write_receipt=True,
    )
    assert report["fixture_only"] is False
    assert report["authorizing_hub_upload"] is False
    assert report["vector_count"] == 2
    assert report["dimension"] == 384
    assert report["centroid_bounds_hold"] is True
    assert report["cluster_count"] >= 1
    assert (tmp_path / "vectors" / "vectors.npy").is_file()
    assert (tmp_path / "repo" / vec.VECTORS_RELPATH).is_file()
