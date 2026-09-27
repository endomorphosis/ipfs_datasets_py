"""Legacy JusticeDAO adapters that do not share the IR BM25 index.

Municipal subsections and Caselaw opinions are stored by CID. Caselaw
embeddings stay in three separate vector spaces and are not fused with BM25.
A capped Netherlands identifier is searchable only when it already matches
an IR document. Bodies, embedding floats, and paths are not read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ipfs_datasets_py.ducklake.legal_search_catalog import LegalSearchCatalogError
from ipfs_datasets_py.processors.legal_data.justicedao_release_registry import (
    CorpusRelease,
)
from ipfs_datasets_py.retrieval.hf_graphrag.engine import is_cidv1_key

_MUNICIPAL = "municipal-gnis"
_CASELAW_TEXT = "caselaw-text"
_CASELAW_EMBEDDINGS = "caselaw-embeddings"
_NETHERLANDS = "country:netherlands"
_MUNICIPAL_SPACE = "openai:text-embedding-3-small:1536"
_MUNICIPAL_MODEL = "text-embedding-3-small"
_CASELAW_SPACES = {
    "thenlper/gte-small:384": ("thenlper/gte-small", 384),
    "Alibaba-NLP/gte-large-en-v1.5:1024": ("Alibaba-NLP/gte-large-en-v1.5", 1024),
    "Alibaba-NLP/gte-Qwen2-1.5B-instruct:1536": (
        "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
        1536,
    ),
}


@dataclass(frozen=True)
class LegacyPinResult:
    """One legacy checkout. ``records`` counts CIDs, centroids, or aliases."""

    corpus_id: str
    hf_repo: str
    status: str
    records: int = 0

    def __post_init__(self) -> None:
        if self.status not in {
            "registered",
            "not_checked_out",
            "missing_index",
            "rejected",
            "skipped",
            "capped",
        }:
            raise LegalSearchCatalogError(f"unknown legacy pin status: {self.status}")
        if self.records < 0:
            raise LegalSearchCatalogError("legacy record count cannot be negative")
        if self.status not in {"registered", "capped"} and self.records != 0:
            raise LegalSearchCatalogError("only a read pin has legacy records")


def _index_parquet(checkout: Path, name: str) -> Path | None:
    root = checkout.expanduser().resolve()
    target = (root / "indexes" / name).resolve()
    if not target.is_file():
        return None
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise LegalSearchCatalogError("legacy index escaped the checkout") from exc
    if not relative.parts or relative.parts[0] != "indexes" or "data" in relative.parts:
        raise LegalSearchCatalogError("legacy index must live under indexes/")
    return target


def _table(path: Path, required: Sequence[str]):
    import pyarrow.parquet as pq

    names = set(pq.read_schema(path).names)
    missing = [name for name in required if name not in names]
    if missing:
        raise LegalSearchCatalogError(
            "legacy index is missing columns: " + ", ".join(missing),
            reason="rejected",
        )
    return pq.read_table(path, columns=list(required))


def _checkout(root: Path, release: CorpusRelease) -> Path | None:
    repo_name = release.hf_repo.split("/", 1)[-1]
    checkout = (root / repo_name).resolve()
    try:
        checkout.relative_to(root)
    except ValueError as exc:
        raise LegalSearchCatalogError("legacy checkout escaped the root") from exc
    if not checkout.is_dir():
        return None
    return checkout


def _insert_release(connection, release: CorpusRelease) -> None:
    connection.execute(
        """
        INSERT INTO corpus_release VALUES (?, ?, ?, ?, ?, TRUE, FALSE, FALSE)
        ON CONFLICT (corpus_id) DO NOTHING
        """,
        [
            release.corpus_id,
            release.hf_repo,
            release.layout_profile,
            release.coverage,
            release.primary_key,
        ],
    )


def _register_municipal(connection, release: CorpusRelease, checkout: Path) -> LegacyPinResult:
    path = _index_parquet(checkout, "subsection_cids.parquet")
    if path is None:
        return LegacyPinResult(release.corpus_id, release.hf_repo, "missing_index")
    table = _table(path, ("cid",))
    cids = [str(item or "").strip() for item in table.column("cid").to_pylist()]
    kept = [cid for cid in cids if is_cidv1_key(cid)]
    if not kept:
        return LegacyPinResult(release.corpus_id, release.hf_repo, "rejected")
    _insert_release(connection, release)
    for cid in kept:
        connection.execute(
            "INSERT INTO document_index VALUES (?, ?, 0) ON CONFLICT DO NOTHING",
            [release.corpus_id, cid],
        )
    connection.execute(
        """
        INSERT INTO vector_space VALUES (?, ?, ?, 1536, FALSE)
        ON CONFLICT DO NOTHING
        """,
        [release.corpus_id, _MUNICIPAL_SPACE, _MUNICIPAL_MODEL],
    )
    return LegacyPinResult(release.corpus_id, release.hf_repo, "registered", len(kept))


def _register_caselaw_text(connection, release: CorpusRelease, checkout: Path) -> LegacyPinResult:
    path = _index_parquet(checkout, "opinion_cids.parquet")
    if path is None:
        return LegacyPinResult(release.corpus_id, release.hf_repo, "missing_index")
    table = _table(path, ("cid",))
    kept = [str(item or "").strip() for item in table.column("cid").to_pylist()]
    kept = [cid for cid in kept if is_cidv1_key(cid)]
    if not kept:
        return LegacyPinResult(release.corpus_id, release.hf_repo, "rejected")
    _insert_release(connection, release)
    for cid in kept:
        connection.execute(
            "INSERT INTO document_index VALUES (?, ?, 0) ON CONFLICT DO NOTHING",
            [release.corpus_id, cid],
        )
    return LegacyPinResult(release.corpus_id, release.hf_repo, "registered", len(kept))


def _register_caselaw_embeddings(
    connection, release: CorpusRelease, checkout: Path
) -> LegacyPinResult:
    path = _index_parquet(checkout, "centroids.parquet")
    if path is None:
        return LegacyPinResult(release.corpus_id, release.hf_repo, "missing_index")
    table = _table(path, ("vector_space_id", "centroid_id", "shard_id"))
    rows = list(
        zip(
            table.column("vector_space_id").to_pylist(),
            table.column("centroid_id").to_pylist(),
            table.column("shard_id").to_pylist(),
        )
    )
    parsed: list[tuple[str, str, int]] = []
    for space_id, centroid_id, shard_id in rows:
        space = str(space_id or "").strip()
        centroid = str(centroid_id or "").strip()
        if space not in _CASELAW_SPACES or not centroid:
            return LegacyPinResult(release.corpus_id, release.hf_repo, "rejected")
        try:
            ordinal = int(shard_id)
        except (TypeError, ValueError):
            return LegacyPinResult(release.corpus_id, release.hf_repo, "rejected")
        if ordinal < 0:
            return LegacyPinResult(release.corpus_id, release.hf_repo, "rejected")
        parsed.append((space, centroid, ordinal))
    if not parsed:
        return LegacyPinResult(release.corpus_id, release.hf_repo, "rejected")
    _insert_release(connection, release)
    seen_spaces: set[str] = set()
    for space, _centroid, _ordinal in parsed:
        if space in seen_spaces:
            continue
        seen_spaces.add(space)
        model, dimensions = _CASELAW_SPACES[space]
        connection.execute(
            """
            INSERT INTO vector_space VALUES (?, ?, ?, ?, FALSE)
            ON CONFLICT DO NOTHING
            """,
            [release.corpus_id, space, model, dimensions],
        )
    for space, centroid, ordinal in parsed:
        connection.execute(
            """
            INSERT INTO vector_centroid VALUES (?, ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            [release.corpus_id, space, centroid, ordinal],
        )
    return LegacyPinResult(release.corpus_id, release.hf_repo, "registered", len(parsed))


def _register_netherlands_alias(
    connection, release: CorpusRelease, checkout: Path
) -> LegacyPinResult:
    path = _index_parquet(checkout, "bwbr_alias.parquet")
    if path is None:
        return LegacyPinResult(release.corpus_id, release.hf_repo, "missing_index")
    table = _table(path, ("bwbr_id", "entry_cid"))
    linked = 0
    capped = 0
    for bwbr_id, entry_cid in zip(
        table.column("bwbr_id").to_pylist(),
        table.column("entry_cid").to_pylist(),
    ):
        alias = str(bwbr_id or "").strip()
        cid = str(entry_cid or "").strip()
        if not alias:
            continue
        known = ()
        if is_cidv1_key(cid):
            known = connection.execute(
                """
                SELECT entry_cid FROM document_index
                WHERE corpus_id = ? AND entry_cid = ?
                """,
                [_NETHERLANDS, cid],
            ).fetchall()
        if known:
            coverage = "snapshot"
            searchable = True
            stored_cid = cid
            linked += 1
        else:
            coverage = "capped"
            searchable = False
            stored_cid = ""
            capped += 1
        connection.execute(
            """
            INSERT INTO legacy_alias VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (source_repo, alias_id) DO NOTHING
            """,
            [release.hf_repo, alias, _NETHERLANDS, stored_cid, coverage, searchable],
        )
    status = "capped" if capped or not linked else "registered"
    return LegacyPinResult(
        release.corpus_id, release.hf_repo, status, linked + capped
    )


def register_legacy_pins(
    connection,
    releases: Sequence[CorpusRelease],
    checkout_root: str | Path,
) -> tuple[LegacyPinResult, ...]:
    """Register municipal CIDs, Caselaw spaces, and capped Netherlands aliases."""

    root = Path(checkout_root).expanduser().resolve()
    if not root.is_dir():
        raise LegalSearchCatalogError("checkout root must be a directory")
    results: list[LegacyPinResult] = []
    for release in sorted(releases, key=lambda item: (item.corpus_id, item.hf_repo)):
        kind = release.layout_profile
        netherlands = (
            release.corpus_id == _NETHERLANDS and kind == "legacy-split" and not release.selected
        )
        if kind not in {_MUNICIPAL, _CASELAW_TEXT, _CASELAW_EMBEDDINGS} and not netherlands:
            results.append(LegacyPinResult(release.corpus_id, release.hf_repo, "skipped"))
            continue
        if kind in {_MUNICIPAL, _CASELAW_TEXT, _CASELAW_EMBEDDINGS} and not release.selected:
            results.append(LegacyPinResult(release.corpus_id, release.hf_repo, "skipped"))
            continue
        try:
            checkout = _checkout(root, release)
        except LegalSearchCatalogError:
            results.append(LegacyPinResult(release.corpus_id, release.hf_repo, "rejected"))
            continue
        if checkout is None:
            results.append(
                LegacyPinResult(release.corpus_id, release.hf_repo, "not_checked_out")
            )
            continue
        if kind == _MUNICIPAL:
            results.append(_register_municipal(connection, release, checkout))
        elif kind == _CASELAW_TEXT:
            results.append(_register_caselaw_text(connection, release, checkout))
        elif kind == _CASELAW_EMBEDDINGS:
            results.append(_register_caselaw_embeddings(connection, release, checkout))
        else:
            results.append(_register_netherlands_alias(connection, release, checkout))
    return tuple(results)


def lookup_legacy_alias(connection, alias_id: str) -> tuple[str, ...]:
    """Return IR document CIDs for a searchable alias. Capped aliases are omitted."""

    rows = connection.execute(
        """
        SELECT entry_cid FROM legacy_alias
        WHERE alias_id = ? AND searchable = TRUE AND entry_cid <> ''
        ORDER BY entry_cid
        """,
        [str(alias_id or "").strip()],
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def vector_spaces_for(connection, corpus_id: str) -> tuple[tuple[str, bool], ...]:
    """Return ``(vector_space_id, fuse_with_bm25)`` for one corpus."""

    rows = connection.execute(
        """
        SELECT vector_space_id, fuse_with_bm25
        FROM vector_space
        WHERE corpus_id = ?
        ORDER BY vector_space_id
        """,
        [corpus_id],
    ).fetchall()
    return tuple((str(space), bool(fuse)) for space, fuse in rows)
