"""Normalize the municipal-laws corpus into canonical CID-keyed parquet artifacts."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import hashlib
from html import unescape
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence

from ..legal_data.canonical_legal_corpora import get_canonical_legal_corpus
from ..legal_data.legal_source_recovery_promotion import _resolve_hf_token
from .justicedao_dataset_inventory import (
    build_canonical_corpus_artifacts,
    canonical_corpus_artifact_build_result_to_dict,
)
from ...utils.cid_utils import canonical_json_bytes
from ...utils.cid_utils import cid_for_obj


_CORPUS = get_canonical_legal_corpus("municipal_laws")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_MOJIBAKE_MARKERS = ("\u00c2", "\u00c3", "\u00e2\u20ac", "\ufffd")
_MOJIBAKE_REPLACEMENTS = {
    "\u00c2\u00a7": "\u00a7",
    "\u00c2\u00b6": "\u00b6",
    "\u00c2\u00a0": " ",
    "\u00e2\u20ac\u201d": "\u2014",
    "\u00e2\u20ac\u201c": "\u201c",
    "\u00e2\u20ac\u009d": "\u201d",
    "\u00e2\u20ac\u2122": "\u2019",
    "\u00e2\u20ac\u02dc": "\u2018",
    "\u00e2\u20ac\u00a6": "\u2026",
}


@dataclass(frozen=True)
class MunicipalCorpusRebuildResult:
    input_root: str
    output_root: str
    combined_parquet_path: str
    state_parquet_paths: Dict[str, str]
    source_row_count: int
    row_count: int
    state_row_counts: Dict[str, int]
    artifact_results: List[Dict[str, Any]]


def municipal_corpus_rebuild_result_to_dict(result: MunicipalCorpusRebuildResult) -> Dict[str, Any]:
    return asdict(result)


def _normalize_state_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _safe_cid_for_obj(payload: Mapping[str, Any]) -> str:
    try:
        return cid_for_obj(dict(payload))
    except Exception:
        digest = hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()
        return f"sha256:{digest}"


def _read_parquet_rows(path: Path) -> List[Dict[str, Any]]:
    import pyarrow.parquet as pq

    if not path.exists():
        return []
    return [dict(row) for row in pq.read_table(path).to_pylist()]


def _write_parquet_rows(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_rows = _normalize_rows_for_parquet(rows)
    pq.write_table(pa.Table.from_pylist(normalized_rows), path, compression="snappy")


def _default_embeddings_path(canonical_parquet_path: str | Path) -> str:
    path = Path(canonical_parquet_path)
    return str(path.with_name(f"{path.stem}_embeddings.parquet"))


def _default_faiss_path(canonical_parquet_path: str | Path) -> str:
    return str(Path(canonical_parquet_path).with_suffix(".faiss"))


def _default_faiss_metadata_path(canonical_parquet_path: str | Path) -> str:
    path = Path(canonical_parquet_path)
    return str(path.with_name(f"{path.stem}_faiss_metadata.parquet"))


def _normalize_rows_for_parquet(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    if not rows:
        return [{"_empty": True}]
    ordered_fields: List[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            text = str(key)
            if text not in seen:
                seen.add(text)
                ordered_fields.append(text)
    return [{field: row.get(field) for field in ordered_fields} for row in rows]


def _first_text(payload: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _repair_text_encoding(value.strip())
        if value is not None and str(value).strip():
            return _repair_text_encoding(str(value).strip())
    return ""


def _repair_text_encoding(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    for bad, replacement in _MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(bad, replacement)
    original_score = sum(text.count(marker) for marker in _MOJIBAKE_MARKERS)
    if original_score <= 0:
        return text
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return text
    repaired_score = sum(repaired.count(marker) for marker in _MOJIBAKE_MARKERS)
    return repaired if repaired_score < original_score else text


def _clean_html_to_text(value: Any) -> str:
    html = str(value or "").strip()
    if not html:
        return ""
    text = _HTML_TAG_RE.sub(" ", html)
    text = unescape(text)
    return _repair_text_encoding(_WHITESPACE_RE.sub(" ", text).strip())


def _clean_inline_html(value: Any) -> str:
    return _clean_html_to_text(value)


def _municipal_source_id(citation_row: Mapping[str, Any], html_row: Mapping[str, Any]) -> str:
    return _first_text(
        {**dict(html_row), **dict(citation_row)},
        ("bluebook_cid", "doc_id", "source_id", "identifier", "bluebook_citation", "cid", "gnis"),
    )


def _municipal_identifier(citation_row: Mapping[str, Any], html_row: Mapping[str, Any]) -> str:
    direct = _first_text(
        {**dict(html_row), **dict(citation_row)},
        ("bluebook_citation", "identifier", "title", "html_title"),
    )
    if direct:
        return direct
    title = _first_text(citation_row, ("title",))
    chapter = _first_text(citation_row, ("chapter",))
    if title and chapter:
        return f"{title} {chapter}".strip()
    return title or chapter


def _municipal_name(citation_row: Mapping[str, Any], html_row: Mapping[str, Any]) -> str:
    title = _first_text(citation_row, ("title",))
    if title:
        return title
    html_title = _clean_inline_html(html_row.get("html_title"))
    if html_title:
        return html_title
    return _first_text({**dict(html_row), **dict(citation_row)}, ("chapter", "identifier"))


def _municipal_source_url(citation_row: Mapping[str, Any], html_row: Mapping[str, Any]) -> str:
    return _first_text({**dict(html_row), **dict(citation_row)}, ("source_url", "url", "sourceUrl"))


def _municipal_text(citation_row: Mapping[str, Any], html_row: Mapping[str, Any]) -> str:
    html_text = _clean_html_to_text(html_row.get("html"))
    if html_text:
        return html_text
    return _first_text(
        {**dict(html_row), **dict(citation_row)},
        ("text", "html_title", "title", "history_note", "bluebook_citation"),
    )


def _build_jsonld_payload(citation_row: Mapping[str, Any], html_row: Mapping[str, Any], *, ipfs_cid: str) -> Dict[str, Any]:
    state_code = _normalize_state_code(_first_text(citation_row, ("state_code",)))
    identifier = _municipal_identifier(citation_row, html_row)
    name = _municipal_name(citation_row, html_row)
    text = _municipal_text(citation_row, html_row)
    source_url = _municipal_source_url(citation_row, html_row)
    gnis = _first_text({**dict(html_row), **dict(citation_row)}, ("gnis",))
    bluebook_citation = _first_text(citation_row, ("bluebook_citation",))
    chapter = _first_text(citation_row, ("chapter",))
    title = _first_text(citation_row, ("title", "html_title"))

    payload: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Legislation",
        "@id": f"ipfs://{ipfs_cid}",
        "identifier": identifier,
        "name": name,
        "text": text,
        "citation": bluebook_citation,
        "legislationJurisdiction": state_code,
        "isPartOf": {
            "@type": "CreativeWork",
            "name": chapter,
        } if chapter else None,
        "legislationType": "municipal_code",
        "url": source_url,
        "sameAs": source_url,
        "alternateName": title if title and title != name else None,
        "spatialCoverage": {
            "@type": "Place",
            "identifier": gnis,
            "addressRegion": state_code,
        } if gnis or state_code else None,
        "raw_source": {
            "citation": dict(citation_row),
            "html": dict(html_row),
        },
    }
    return {key: value for key, value in payload.items() if value not in (None, "", {}, [])}


def municipal_rows_to_canonical_row(
    citation_row: Mapping[str, Any],
    html_row: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    html_payload = dict(html_row or {})
    citation_payload = dict(citation_row)
    state_code = _normalize_state_code(_first_text(citation_payload, ("state_code",)))
    raw_cid = _first_text(citation_payload, ("cid",)) or _first_text(html_payload, ("cid",))
    identifier = _municipal_identifier(citation_payload, html_payload)
    name = _municipal_name(citation_payload, html_payload)
    text = _municipal_text(citation_payload, html_payload)
    source_url = _municipal_source_url(citation_payload, html_payload)
    source_id = _municipal_source_id(citation_payload, html_payload)

    row_without_cid: Dict[str, Any] = {
        "state_code": state_code,
        "source_id": source_id,
        "source_cid": raw_cid,
        "identifier": identifier,
        "name": name,
        "text": text,
        "source_url": source_url,
        "official_cite": _first_text(citation_payload, ("bluebook_citation",)),
        "bluebook_citation": _first_text(citation_payload, ("bluebook_citation",)),
        "html_title": _clean_inline_html(html_payload.get("html_title")),
        "title": _first_text(citation_payload, ("title",)),
        "chapter": _first_text(citation_payload, ("chapter",)),
        "gnis": _first_text({**html_payload, **citation_payload}, ("gnis",)),
        "doc_id": _first_text(html_payload, ("doc_id",)),
        "doc_order": _first_text(html_payload, ("doc_order",)),
    }
    ipfs_cid = raw_cid or _safe_cid_for_obj(row_without_cid)
    jsonld_payload = _build_jsonld_payload(citation_payload, html_payload, ipfs_cid=ipfs_cid)
    return {
        "ipfs_cid": ipfs_cid,
        **row_without_cid,
        "jsonld": json.dumps(jsonld_payload, ensure_ascii=False, sort_keys=True),
    }


def _group_raw_dataset_files(input_root: Path) -> Dict[str, Dict[str, Path]]:
    grouped: Dict[str, Dict[str, Path]] = defaultdict(dict)
    for path in input_root.rglob("*.parquet"):
        name = path.name
        if name.endswith("_citation.parquet"):
            grouped[name[:-len("_citation.parquet")]]["citation"] = path
        elif name.endswith("_html.parquet"):
            grouped[name[:-len("_html.parquet")]]["html"] = path
        elif name.endswith("_embeddings.parquet"):
            grouped[name[:-len("_embeddings.parquet")]]["embeddings"] = path
    return dict(grouped)


def load_municipal_canonical_rows(
    input_root: str | Path,
    *,
    states: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    root = Path(input_root).expanduser().resolve()
    grouped = _group_raw_dataset_files(root)
    selected_states = {_normalize_state_code(item) for item in list(states or []) if _normalize_state_code(item)}
    rows: List[Dict[str, Any]] = []

    for file_set in grouped.values():
        citation_path = file_set.get("citation")
        if citation_path is None:
            continue
        html_path = file_set.get("html")
        html_rows = _read_parquet_rows(html_path) if html_path is not None else []
        html_by_cid: Dict[str, Dict[str, Any]] = {}
        for row in html_rows:
            cid = _first_text(row, ("cid",))
            if cid and cid not in html_by_cid:
                html_by_cid[cid] = row

        for citation_row in _read_parquet_rows(citation_path):
            state_code = _normalize_state_code(_first_text(citation_row, ("state_code",)))
            if selected_states and state_code not in selected_states:
                continue
            html_row = html_by_cid.get(_first_text(citation_row, ("cid",))) or {}
            rows.append(municipal_rows_to_canonical_row(citation_row, html_row))
    return rows


def _row_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    for field in ("ipfs_cid", "source_id", "identifier", "source_url"):
        value = str(row.get(field) or "").strip()
        if value:
            return field, value
    return "row", json.dumps(dict(row), ensure_ascii=True, sort_keys=True, default=str)


def _dedupe_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    merged: MutableMapping[tuple[str, str], Dict[str, Any]] = {}
    order: List[tuple[str, str]] = []
    for row in rows:
        normalized = dict(row)
        key = _row_identity(normalized)
        if key not in merged:
            order.append(key)
        merged[key] = normalized
    return [merged[key] for key in order]


def _coerce_embedding_vector(value: Any) -> List[float]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    return []


def _metadata_rows_for_embeddings(rows: Sequence[Mapping[str, Any]], *, vector_id_start: int) -> List[Dict[str, Any]]:
    metadata_rows: List[Dict[str, Any]] = []
    for offset, row in enumerate(rows):
        metadata_row = {
            "vector_id": vector_id_start + offset,
            "ipfs_cid": row.get("ipfs_cid"),
            "semantic_text": row.get("semantic_text"),
        }
        for field in ("identifier", "name", "source_id", "state_code"):
            if field in row:
                metadata_row[field] = row.get(field)
        metadata_rows.append(metadata_row)
    return metadata_rows


def _combine_state_semantic_artifacts(
    state_artifact_results: Sequence[Mapping[str, Any]],
    *,
    combined_parquet_path: str,
    build_faiss: bool,
) -> Dict[str, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    semantic_indexes = [
        dict(result.get("semantic_index") or {})
        for result in state_artifact_results
        if result.get("state_code") and result.get("semantic_index")
    ]
    if not semantic_indexes:
        raise ValueError("No state semantic indexes were available to combine")

    embeddings_output = _default_embeddings_path(combined_parquet_path)
    faiss_index_output = _default_faiss_path(combined_parquet_path)
    faiss_metadata_output = _default_faiss_metadata_path(combined_parquet_path)
    Path(embeddings_output).parent.mkdir(parents=True, exist_ok=True)
    Path(faiss_metadata_output).parent.mkdir(parents=True, exist_ok=True)

    embeddings_writer: Any = None
    metadata_writer: Any = None
    faiss_index: Any = None
    row_count = 0
    vector_dimension = 0
    backend = ""
    provider = ""
    model_name = ""
    join_field = "ipfs_cid"

    try:
        if build_faiss:
            import faiss
        else:
            faiss = None  # type: ignore[assignment]
        import numpy as np

        for semantic_index in sorted(semantic_indexes, key=lambda item: str(item.get("state_code") or "")):
            embeddings_path = Path(str(semantic_index.get("embeddings_parquet_path") or ""))
            if not embeddings_path.exists():
                continue
            embeddings_table = pq.read_table(embeddings_path)
            if embeddings_writer is None:
                embeddings_writer = pq.ParquetWriter(embeddings_output, embeddings_table.schema, compression="snappy")
            embeddings_writer.write_table(embeddings_table)

            if not backend:
                backend = str(semantic_index.get("backend") or "")
                provider = str(semantic_index.get("provider") or "")
                model_name = str(semantic_index.get("model_name") or "")
                join_field = str(semantic_index.get("join_field") or "ipfs_cid")

            embedding_rows = embeddings_table.to_pylist()
            vectors = [_coerce_embedding_vector(row.get("embedding")) for row in embedding_rows]
            vectors = [vector for vector in vectors if vector]
            if vectors and vector_dimension <= 0:
                vector_dimension = len(vectors[0])
            if vectors and build_faiss and faiss is not None:
                if faiss_index is None:
                    if hasattr(faiss, "IndexFlatIP"):
                        faiss_index = faiss.IndexFlatIP(len(vectors[0]))
                    elif hasattr(faiss, "IndexFlatL2"):
                        faiss_index = faiss.IndexFlatL2(len(vectors[0]))
                    else:
                        faiss_index = faiss.index_factory(len(vectors[0]), "Flat", getattr(faiss, "METRIC_INNER_PRODUCT", 0))
                faiss_index.add(np.asarray(vectors, dtype="float32"))

            metadata_path = Path(str(semantic_index.get("faiss_metadata_path") or ""))
            if metadata_path.exists():
                metadata_rows = pq.read_table(metadata_path).to_pylist()
                for offset, row in enumerate(metadata_rows):
                    row["vector_id"] = row_count + offset
            else:
                metadata_rows = _metadata_rows_for_embeddings(embedding_rows, vector_id_start=row_count)
            metadata_rows = _normalize_rows_for_parquet(metadata_rows)
            metadata_table = pa.Table.from_pylist(metadata_rows)
            if metadata_writer is None:
                metadata_writer = pq.ParquetWriter(faiss_metadata_output, metadata_table.schema, compression="snappy")
            else:
                metadata_table = metadata_table.cast(metadata_writer.schema)
            metadata_writer.write_table(metadata_table)
            row_count += len(embedding_rows)
    finally:
        if embeddings_writer is not None:
            embeddings_writer.close()
        if metadata_writer is not None:
            metadata_writer.close()

    faiss_index_written: Optional[str] = None
    faiss_metadata_written: Optional[str] = None
    if build_faiss and faiss_index is not None:
        import faiss

        Path(faiss_index_output).parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(faiss_index, faiss_index_output)
        faiss_index_written = faiss_index_output
        faiss_metadata_written = faiss_metadata_output

    return {
        "corpus_key": _CORPUS.key,
        "dataset_id": _CORPUS.hf_dataset_id,
        "canonical_parquet_path": str(combined_parquet_path),
        "embeddings_parquet_path": str(embeddings_output),
        "faiss_index_path": faiss_index_written,
        "faiss_metadata_path": faiss_metadata_written,
        "row_count": row_count,
        "vector_dimension": vector_dimension,
        "backend": backend,
        "provider": provider,
        "model_name": model_name,
        "join_field": join_field,
        "state_code": "",
    }


def write_municipal_canonical_parquets(
    rows: Sequence[Mapping[str, Any]],
    *,
    output_root: str | Path,
) -> tuple[Dict[str, str], str, Dict[str, int], int]:
    root = Path(output_root).expanduser().resolve()
    parquet_dir = root / _CORPUS.parquet_dir_name
    parquet_dir.mkdir(parents=True, exist_ok=True)

    deduped_rows = _dedupe_rows(rows)
    rows_by_state: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in deduped_rows:
        state_code = _normalize_state_code(row.get("state_code"))
        if not state_code:
            continue
        rows_by_state[state_code].append(dict(row))

    state_paths: Dict[str, str] = {}
    state_counts: Dict[str, int] = {}
    for state_code in sorted(rows_by_state):
        state_path = parquet_dir / _CORPUS.state_parquet_filename(state_code)
        _write_parquet_rows(rows_by_state[state_code], state_path)
        state_paths[state_code] = str(state_path)
        state_counts[state_code] = len(rows_by_state[state_code])

    combined_path = parquet_dir / _CORPUS.combined_parquet_filename
    _write_parquet_rows(deduped_rows, combined_path)
    return state_paths, str(combined_path), state_counts, len(deduped_rows)


def rebuild_municipal_laws_corpus(
    *,
    input_root: str | Path,
    output_root: str | Path | None = None,
    states: Optional[Sequence[str]] = None,
    provider: Optional[str] = None,
    model_name: str = "thenlper/gte-small",
    device: Optional[str] = None,
    build_faiss: bool = True,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    repo_id: Optional[str] = None,
    include_canonical_parquet: bool = True,
) -> MunicipalCorpusRebuildResult:
    source_root = Path(input_root).expanduser().resolve()
    target_root = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else _CORPUS.default_local_root()
    )
    rows = load_municipal_canonical_rows(source_root, states=states)
    state_paths, combined_path, state_counts, canonical_row_count = write_municipal_canonical_parquets(
        rows,
        output_root=target_root,
    )

    artifact_results: List[Dict[str, Any]] = []
    resolved_repo_id = str(repo_id or _CORPUS.hf_dataset_id)
    resolved_hf_token = _resolve_hf_token(hf_token)
    if publish_to_hf:
        raise ValueError(
            "Publishing municipal artifacts after combined semantic reuse is not enabled yet; "
            "rerun without --publish-to-hf and upload the generated artifacts after validation."
        )
    for state_code in sorted(state_paths):
        artifact_results.append(
            canonical_corpus_artifact_build_result_to_dict(
                build_canonical_corpus_artifacts(
                    "municipal_laws",
                    canonical_parquet_path=state_paths[state_code],
                    state_code=state_code,
                    output_root=str(Path(state_paths[state_code]).parent),
                    provider=provider,
                    model_name=model_name,
                    device=device,
                    build_faiss=build_faiss,
                    publish_to_hf=publish_to_hf,
                    hf_token=resolved_hf_token,
                    repo_id=resolved_repo_id,
                    include_canonical_parquet=include_canonical_parquet,
                )
            )
        )
    combined_artifact = canonical_corpus_artifact_build_result_to_dict(
        build_canonical_corpus_artifacts(
            "municipal_laws",
            canonical_parquet_path=combined_path,
            output_root=str(Path(combined_path).parent),
            provider=provider,
            model_name=model_name,
            device=device,
            build_faiss=build_faiss,
            build_semantic_index=False,
            publish_to_hf=False,
            hf_token=resolved_hf_token,
            repo_id=resolved_repo_id,
            include_canonical_parquet=include_canonical_parquet,
        )
    )
    if any(result.get("semantic_index") for result in artifact_results):
        combined_artifact["semantic_index"] = _combine_state_semantic_artifacts(
            artifact_results,
            combined_parquet_path=combined_path,
            build_faiss=build_faiss,
        )
    artifact_results.append(combined_artifact)

    return MunicipalCorpusRebuildResult(
        input_root=str(source_root),
        output_root=str(target_root),
        combined_parquet_path=str(combined_path),
        state_parquet_paths=state_paths,
        source_row_count=len(rows),
        row_count=canonical_row_count,
        state_row_counts=state_counts,
        artifact_results=artifact_results,
    )


__all__ = [
    "MunicipalCorpusRebuildResult",
    "load_municipal_canonical_rows",
    "municipal_corpus_rebuild_result_to_dict",
    "municipal_rows_to_canonical_row",
    "rebuild_municipal_laws_corpus",
    "write_municipal_canonical_parquets",
]
