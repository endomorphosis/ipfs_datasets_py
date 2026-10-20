"""Keyword and vector search inside one American municipal section.

A latitude and longitude select the municipality. Search then reads only
that authority's rows from the local v4 tree. It does not download the
Hub, does not load a neural embedding model, and does not add a float
column to a legal record.

Keyword search keeps a row only when every query token is a whole token
in the ordinance text or the citation. Vector search maps those tokens into a fixed binary hash vector
and ranks by the query-normalized integer inner product. A repeated
word cannot outweigh a section that actually contains the query terms.
Scores stay off the record. The order of the returned rows is the rank.
"""

from __future__ import annotations

import json
import math
import re
import zlib
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
    PlaceConstraint,
    fold_place,
    place_matches,
    prefix_folds,
)

_TREE = Path(
    "/home/barberb/.ipfs_datasets/country-laws-ir/norm-export/"
    "24cac8b72a91f1c196bef47a8bd0398b103f26ba/american_municipal_law_v4"
)
_INDEX_PATH = Path.home() / (
    ".ipfs_datasets/country-laws-ir/indexes/"
    "american-municipal-v4-24cac8b72a91-authority-parts.json"
)
_SOURCE_REVISION = "24cac8b72a91f1c196bef47a8bd0398b103f26ba"
_NORMALIZER = "american-municipal-html/v4+legal-record/v1"
_ROWS_KEPT = 17109461
_DIMENSION = 1 << 20
_COLUMNS = (
    "authority",
    "jurisdiction",
    "effective_date",
    "citation",
    "text",
    "entry_cid",
    "provenance",
    "language",
)
_TOKEN = re.compile(r"[0-9a-z]+")


class MunicipalSectionError(FileNotFoundError):
    """The local municipal tree or its authority index cannot be read."""


def search_terms(text_query: str) -> tuple[str, ...]:
    """Whole tokens, casefolded, length at least 2, in first-seen order."""

    seen: set[str] = set()
    terms: list[str] = []
    for token in _TOKEN.findall(text_query.casefold()):
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return tuple(terms)


def document_tokens(row: Mapping[str, object]) -> tuple[str, ...]:
    """Tokens of the stored ordinance text and citation."""

    return search_terms(_haystack(row))


def keyword_score(row: Mapping[str, object], terms: tuple[str, ...]) -> int:
    """Count of query tokens when every term is present, otherwise zero."""

    if not terms:
        return 0
    counts = Counter(document_tokens(row))
    if any(term not in counts for term in terms):
        return 0
    return sum(counts[term] for term in terms)


def vector_score(row: Mapping[str, object], terms: tuple[str, ...]) -> int:
    """Query-normalized inner product of binary token vectors.

    Each distinct token sets one bucket. Counts are not used, so a common
    word that collides with a query token cannot outrank a section that
    contains the query terms. The result is an integer. A document that
    shares no bucket with the query scores zero and is omitted.
    """

    if not terms:
        return 0
    query = _buckets(terms)
    document = _buckets(document_tokens(row))
    return _inner_millionths(query, document)


def rank_section(
    rows: tuple[dict[str, object], ...] | list[dict[str, object]],
    *,
    retrieval: str,
    text_query: str,
) -> tuple[dict[str, object], ...]:
    """Return matching rows, best score first. A zero score is omitted."""

    terms = search_terms(text_query)
    if not terms:
        return ()
    score_of = keyword_score if retrieval == "keyword" else vector_score
    ranked: list[tuple[int, str, dict[str, object]]] = []
    for row in rows:
        score = score_of(row, terms)
        if score <= 0:
            continue
        cid = row.get("entry_cid")
        ranked.append((score, cid if isinstance(cid, str) else "", row))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return tuple(item[2] for item in ranked)


def load_place_section(constraint: PlaceConstraint) -> tuple[dict[str, object], ...]:
    """Rows whose authority is this place. Other cities in a shard are dropped."""

    import pyarrow.parquet as pq

    tree = _require_tree()
    index = load_authority_index()
    parts = _parts_for(index, constraint)
    folded = corpus_authority_fold(constraint.name, constraint.state_code)
    found: list[dict[str, object]] = []
    for part in parts:
        path = tree / "data" / part / "laws.parquet"
        if not path.is_file():
            raise MunicipalSectionError(f"missing municipal shard {part}")
        table = pq.read_table(path, columns=list(_COLUMNS))
        columns = {name: table.column(name).to_pylist() for name in _COLUMNS}
        for index_row in range(table.num_rows):
            row = {name: columns[name][index_row] for name in _COLUMNS}
            authority = row.get("authority")
            if not isinstance(authority, str) or fold_place(authority) != folded:
                continue
            if not place_matches(row, constraint):
                continue
            found.append(row)
    return tuple(found)


def load_authority_index() -> dict[str, dict[str, object]]:
    """Authority and jurisdiction to the shards that contain that place."""

    payload = _read_index()
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        raise MunicipalSectionError("municipal authority index has no entries")
    return entries


def build_authority_index() -> dict[str, object]:
    """Scan the local v4 tree once and write the authority-to-shard index."""

    import pyarrow.parquet as pq

    tree = _require_tree()
    manifest = json.loads((tree / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("normalizer_version") != _NORMALIZER:
        raise MunicipalSectionError("municipal tree is not american-municipal-html/v4")
    if manifest.get("rows_kept") != _ROWS_KEPT:
        raise MunicipalSectionError("municipal tree row count does not match v4")
    if manifest.get("source_revision") != _SOURCE_REVISION:
        raise MunicipalSectionError("municipal tree source revision does not match v4")
    parts = sorted((tree / "data").glob("part-*/laws.parquet"))
    entries: dict[str, dict[str, object]] = {}
    rows = 0
    for path in parts:
        table = pq.read_table(path, columns=["authority", "jurisdiction"])
        rows += table.num_rows
        authorities = table.column("authority").to_pylist()
        jurisdictions = table.column("jurisdiction").to_pylist()
        part = path.parent.name
        for authority, jurisdiction in zip(authorities, jurisdictions):
            if not isinstance(authority, str) or not authority.strip():
                continue
            if not isinstance(jurisdiction, str) or not jurisdiction.startswith("US-"):
                continue
            key = f"{fold_place(authority)}\t{jurisdiction}"
            slot = entries.get(key)
            if slot is None:
                entries[key] = {"parts": [part], "rows": 1}
                continue
            slot["rows"] = int(slot["rows"]) + 1
            parts_for_key = slot["parts"]
            assert isinstance(parts_for_key, list)
            if part not in parts_for_key:
                parts_for_key.append(part)
    if rows != _ROWS_KEPT:
        raise MunicipalSectionError("municipal shard row count does not match the manifest")
    payload = {
        "schema": "municipal-authority-parts/v1",
        "source_revision": _SOURCE_REVISION,
        "normalizer_version": _NORMALIZER,
        "rows_kept": rows,
        "parts": len(parts),
        "entries": entries,
    }
    _INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = _INDEX_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    temporary.replace(_INDEX_PATH)
    _read_index.cache_clear()
    return payload


def _require_tree() -> Path:
    if not (_TREE / "manifest.json").is_file():
        raise MunicipalSectionError("local american municipal v4 tree is not on this machine")
    return _TREE


@lru_cache(maxsize=1)
def _read_index() -> dict[str, object]:
    if not _INDEX_PATH.is_file():
        return build_authority_index()
    payload = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MunicipalSectionError("municipal authority index is not an object")
    if payload.get("source_revision") != _SOURCE_REVISION or payload.get("rows_kept") != _ROWS_KEPT:
        return build_authority_index()
    return payload


def corpus_authority_fold(name: str, state_code: str | None) -> str:
    """Authority fold to read for this place.

    The exact fold wins when that key has rows, when the state is unknown,
    or when the index cannot be read. A unique in-state name one allowed
    prefix away is used only when the exact key has no rows.
    """

    return resolve_corpus_authority(name, state_code)[0]


def resolve_corpus_authority(name: str, state_code: str | None) -> tuple[str, str]:
    """Return ``(fold, status)``.

    ``status`` is ``exact``, ``prefix``, ``ambiguous``, ``absent``, or
    ``unindexed``. ``ambiguous`` means more than one prefix variant has
    rows, so the exact fold is kept and nothing is guessed.
    """

    folded = fold_place(name)
    if not state_code:
        return folded, "unindexed"
    try:
        index = load_authority_index()
    except MunicipalSectionError:
        return folded, "unindexed"
    if _slot_rows(index, folded, state_code) > 0:
        return folded, "exact"
    matched = [
        variant
        for variant in prefix_folds(folded)
        if _slot_rows(index, variant, state_code) > 0
    ]
    if len(matched) == 1:
        return matched[0], "prefix"
    if len(matched) > 1:
        return folded, "ambiguous"
    return folded, "absent"


def _slot_rows(index: Mapping[str, dict[str, object]], folded: str, state_code: str) -> int:
    slot = index.get(f"{folded}\tUS-{state_code}")
    rows = slot.get("rows") if isinstance(slot, dict) else 0
    return rows if isinstance(rows, int) and rows > 0 else 0


def _parts_for(index: Mapping[str, dict[str, object]], constraint: PlaceConstraint) -> tuple[str, ...]:
    folded = corpus_authority_fold(constraint.name, constraint.state_code)
    if constraint.state_code:
        slot = index.get(f"{folded}\tUS-{constraint.state_code}")
        parts = slot.get("parts") if isinstance(slot, dict) else None
        if not isinstance(parts, list):
            return ()
        return tuple(str(part) for part in parts)
    found: list[str] = []
    prefix = f"{folded}\t"
    for key, slot in index.items():
        if not key.startswith(prefix) or not isinstance(slot, dict):
            continue
        parts = slot.get("parts")
        if isinstance(parts, list):
            found.extend(str(part) for part in parts)
    return tuple(sorted(set(found)))


def _haystack(row: Mapping[str, object]) -> str:
    text = row.get("text")
    citation = row.get("citation")
    body = text if isinstance(text, str) else ""
    cite = citation if isinstance(citation, str) else ""
    return f"{body}\n{cite}"


def _bucket(token: str) -> int:
    encoded = token.encode("utf-8")
    mixed = zlib.crc32(encoded[::-1], zlib.crc32(encoded))
    return mixed % _DIMENSION


def _buckets(tokens: tuple[str, ...] | list[str]) -> dict[int, int]:
    return {_bucket(token): 1 for token in tokens}


def _inner_millionths(query: Mapping[int, int], document: Mapping[int, int]) -> int:
    if not query or not document:
        return 0
    dot = 0
    for bucket, weight in query.items():
        dot += weight * document.get(bucket, 0)
    if dot <= 0:
        return 0
    query_norm = math.isqrt(sum(weight * weight for weight in query.values()))
    if query_norm == 0:
        return 0
    return (dot * 1_000_000) // query_norm
