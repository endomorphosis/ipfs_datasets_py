"""Upgrade wrapped/SHA-256 GraphRAG releases onto the thin-client contract.

Open US Law and similar Hub packages store each family as JSON blobs
(``record_json``) with SHA-256 hex ``entry_cid`` / ``node_cid`` keys.
This module unwraps those rows, rewrites identities to CIDv1
(``bafkrei…``), emits nested BM25 cells, and normalizes adjacency
``in``/``out`` directories so :func:`repair_graphrag_range_routing` and
the standalone query client can run.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifacts import ArtifactWriterConfig, write_zstd_parquet
from .engine import (
    GraphragEngineError,
    remap_sha256_identity_fields,
    sha256_key_to_cidv1,
)
from .schema import MAX_ROWS_PER_PHYSICAL_SHARD

ADJ_DIR_MAP = {
    "in": "incoming",
    "out": "outgoing",
    "incoming": "incoming",
    "outgoing": "outgoing",
}


def _unwrap_row(row: Mapping[str, Any]) -> dict[str, Any]:
    if "record_json" in row and row.get("record_json"):
        payload = json.loads(str(row["record_json"]))
        if not isinstance(payload, dict):
            raise GraphragEngineError("record_json must decode to a mapping")
        return dict(payload)
    return dict(row)


def _posting_rows(
    payload: Mapping[str, Any],
    lengths: Mapping[int, int],
    cid_to_index: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    term = str(payload.get("term") or "")
    if not term:
        raise GraphragEngineError("posting row is missing term")
    if (
        not payload.get("cells")
        and not payload.get("pointers")
        and not payload.get("document_indices")
        and payload.get("entry_cid")
    ):
        cid = sha256_key_to_cidv1(payload.get("entry_cid"))
        index = payload.get("document_index")
        if index is None and cid_to_index:
            index = cid_to_index.get(cid)
        if index is None:
            return []
        tf = int(payload.get("tf") or 1)
        return [
            {
                "body_tf": tf,
                "document_index": int(index),
                "entry_cid": cid,
                "term": term,
                "tf": tf,
                "title_tf": 0,
            }
        ]
    cells = payload.get("cells")
    if not isinstance(cells, list) or not cells:
        pointers = payload.get("pointers") or []
        cells = [{"pointers": pointers, "pointer_count": len(pointers)}]
    rows: list[dict[str, Any]] = []
    chunk_count = max(1, len(cells))
    idf = float(payload.get("idf") or 0.0)
    df = int(payload.get("document_frequency") or 0)
    for chunk_index, cell in enumerate(cells):
        pointers = list(cell.get("pointers") or ())
        indices: list[int] = []
        title_tf: list[int] = []
        body_tf: list[int] = []
        docs_len: list[int] = []
        for pointer in pointers:
            index = int(pointer.get("document_index"))
            field = pointer.get("field_tf") if isinstance(pointer.get("field_tf"), Mapping) else {}
            indices.append(index)
            title_tf.append(int(field.get("title") or field.get("heading") or 0))
            body_tf.append(int(field.get("body") or pointer.get("tf") or 0))
            docs_len.append(int(lengths.get(index, 0)))
        rows.append(
            {
                "body_frequencies": body_tf,
                "corpus_frequency": int(payload.get("pointer_count") or sum(body_tf) or len(indices)),
                "document_frequency": df or len(indices),
                "document_indices": indices,
                "document_lengths": docs_len,
                "idf": idf,
                "posting_chunk_count": chunk_count,
                "posting_chunk_index": chunk_index,
                "schema_version": str(payload.get("schema_version") or "hf-graphrag-bm25-posting/v1"),
                "term": term,
                "title_frequencies": title_tf,
            }
        )
    return rows


def _node_row(payload: Mapping[str, Any]) -> dict[str, Any]:
    node_cid = sha256_key_to_cidv1(payload.get("node_cid") or payload.get("entry_cid"))
    return {
        "label": payload.get("label"),
        "legal_id": payload.get("legal_id"),
        "node_cid": node_cid,
        "node_key": payload.get("node_key"),
        "node_type": payload.get("node_type"),
        "payload": payload.get("payload"),
        "schema_version": payload.get("schema_version"),
    }


def _edge_row(payload: Mapping[str, Any]) -> dict[str, Any]:
    src = sha256_key_to_cidv1(payload.get("source_node_cid") or payload.get("src"))
    dst = sha256_key_to_cidv1(payload.get("target_node_cid") or payload.get("dst"))
    return {
        "edge_cid": sha256_key_to_cidv1(payload.get("edge_cid")),
        "edge_type": payload.get("edge_type") or payload.get("type"),
        "src": src,
        "dst": dst,
        "source_node_cid": src,
        "target_node_cid": dst,
        "weight": payload.get("weight"),
        "schema_version": payload.get("schema_version"),
    }


def _adjacency_row(payload: Mapping[str, Any]) -> dict[str, Any]:
    remapped = remap_sha256_identity_fields(payload)
    node_cid = sha256_key_to_cidv1(remapped.get("node_cid"))
    pointers = remapped.get("pointers") or []
    return {
        "direction": "outgoing" if remapped.get("direction") in {"out", "outgoing"} else "incoming",
        "node_cid": node_cid,
        "page_index": int(remapped.get("page_index") or 0),
        "pointer_count": int(remapped.get("pointer_count") or len(pointers)),
        "pointers": pointers,
        "schema_version": remapped.get("schema_version"),
    }


def _corpus_row(payload: Mapping[str, Any]) -> dict[str, Any]:
    remapped = remap_sha256_identity_fields(payload)
    entry = sha256_key_to_cidv1(remapped.get("entry_cid"))
    remapped["entry_cid"] = entry
    return remapped


def _document_row(payload: Mapping[str, Any]) -> dict[str, Any]:
    remapped = remap_sha256_identity_fields(payload)
    remapped["entry_cid"] = sha256_key_to_cidv1(remapped.get("entry_cid"))
    return remapped


def _vector_row(payload: Mapping[str, Any]) -> dict[str, Any]:
    remapped = remap_sha256_identity_fields(payload)
    remapped["entry_cid"] = sha256_key_to_cidv1(remapped.get("entry_cid"))
    return remapped


def unwrap_sha256_family_file(
    src: str | Path,
    dest: str | Path,
    *,
    family: str,
    lengths: Mapping[int, int] | None = None,
    cid_to_index: Mapping[str, int] | None = None,
) -> dict[str, int]:
    """Unwrap one JSON-wrapped parquet and rewrite CIDv1 rows."""

    import pyarrow.parquet as pq

    table = pq.read_table(src)
    rows_in = table.to_pylist()
    out: list[dict[str, Any]] = []
    doc_lengths = lengths or {}
    for row in rows_in:
        payload = remap_sha256_identity_fields(_unwrap_row(row))
        if family == "bm25_postings":
            out.extend(_posting_rows(payload, doc_lengths, cid_to_index=cid_to_index))
        elif family == "graph_nodes":
            out.append(_node_row(payload))
        elif family == "graph_edges":
            out.append(_edge_row(payload))
        elif family in {"graph_adjacency_out", "graph_adjacency_in", "graph_outgoing_adjacency", "graph_incoming_adjacency"}:
            out.append(_adjacency_row(payload))
        elif family == "bm25_documents":
            out.append(_document_row(payload))
        elif family == "vectors":
            out.append(_vector_row(payload))
        else:
            out.append(_corpus_row(payload))
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    bound = MAX_ROWS_PER_PHYSICAL_SHARD
    config = ArtifactWriterConfig(max_rows_per_shard=bound)
    if out:
        chunks = [out[index : index + bound] for index in range(0, len(out), bound)]
        if len(chunks) == 1:
            write_zstd_parquet(dest_path, chunks[0], max_rows=bound, config=config)
        else:
            for offset, chunk in enumerate(chunks):
                write_zstd_parquet(
                    dest_path.with_name(f"{dest_path.stem}-{offset:02d}.parquet"),
                    chunk,
                    max_rows=bound,
                    config=config,
                )
    return {"rows_in": len(rows_in), "rows_out": len(out)}


def _load_document_maps(root: Path) -> tuple[dict[int, int], dict[str, int]]:
    lengths: dict[int, int] = {}
    cid_to_index: dict[str, int] = {}
    doc_dir = root / "data" / "bm25" / "documents"
    if not doc_dir.is_dir():
        return lengths, cid_to_index
    import pyarrow.parquet as pq

    for path in sorted(doc_dir.glob("*.parquet")):
        names = set(pq.ParquetFile(path).schema_arrow.names)
        if "record_json" in names:
            table = pq.read_table(path, columns=["record_json"])
            for raw in table.column("record_json").to_pylist():
                payload = json.loads(str(raw))
                index = int(payload.get("document_index") or 0)
                fields = payload.get("field_lengths") if isinstance(payload.get("field_lengths"), Mapping) else {}
                total = int(payload.get("total_length") or sum(int(v or 0) for v in fields.values()) or 0)
                lengths[index] = total
                cid = sha256_key_to_cidv1(payload.get("entry_cid"))
                if cid:
                    cid_to_index[cid] = index
            continue
        cols = [name for name in ("document_index", "total_length", "entry_cid") if name in names]
        if "document_index" not in cols:
            continue
        table = pq.read_table(path, columns=cols)
        indexes = table.column("document_index").to_pylist()
        totals = (
            table.column("total_length").to_pylist()
            if "total_length" in cols
            else [0] * len(indexes)
        )
        cids = (
            table.column("entry_cid").to_pylist()
            if "entry_cid" in cols
            else [None] * len(indexes)
        )
        for index, total, cid in zip(indexes, totals, cids):
            idx = int(index or 0)
            lengths[idx] = int(total or 0)
            mapped = sha256_key_to_cidv1(cid)
            if mapped:
                cid_to_index[mapped] = idx
    return lengths, cid_to_index


def _load_document_lengths(root: Path) -> dict[int, int]:
    lengths, _cid_to_index = _load_document_maps(root)
    return lengths


def upgrade_wrapped_graphrag_release(root: str | Path) -> dict[str, Any]:
    """Unwrap JSON-wrapped shards, rewrite SHA-256 keys to CIDv1, normalize dirs."""

    release = Path(root).expanduser().resolve()
    lengths, cid_to_index = _load_document_maps(release)
    staging = release / ".upgrade_cidv1"
    if staging.exists():
        shutil.rmtree(staging)
    adj = release / "data" / "graph" / "adjacency"
    staging_adj = staging / "data" / "graph" / "adjacency"
    mapping: list[tuple[str, Path, Path]] = [
        ("corpus", release / "data" / "corpus", staging / "data" / "corpus"),
        ("bm25_documents", release / "data" / "bm25" / "documents", staging / "data" / "bm25" / "documents"),
        ("bm25_postings", release / "data" / "bm25" / "postings", staging / "data" / "bm25" / "postings"),
        ("graph_nodes", release / "data" / "graph" / "nodes", staging / "data" / "graph" / "nodes"),
        ("graph_edges", release / "data" / "graph" / "edges", staging / "data" / "graph" / "edges"),
        ("vectors", release / "data" / "vectors", staging / "data" / "vectors"),
    ]
    if (adj / "out").is_dir():
        mapping.append(("graph_adjacency_out", adj / "out", staging_adj / "outgoing"))
    elif (adj / "outgoing").is_dir():
        mapping.append(("graph_adjacency_out", adj / "outgoing", staging_adj / "outgoing"))
    if (adj / "in").is_dir():
        mapping.append(("graph_adjacency_in", adj / "in", staging_adj / "incoming"))
    elif (adj / "incoming").is_dir():
        mapping.append(("graph_adjacency_in", adj / "incoming", staging_adj / "incoming"))
    stats: dict[str, int] = {}
    for family, src_dir, dest_dir in mapping:
        if not src_dir.is_dir():
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(p for p in src_dir.glob("*.parquet") if p.is_file())
        rows_out = 0
        for path in files:
            rec = unwrap_sha256_family_file(
                path,
                dest_dir / path.name,
                family=family,
                lengths=lengths,
                cid_to_index=cid_to_index,
            )
            rows_out += int(rec["rows_out"])
        stats[family] = rows_out
        print(f"  unwrap {family} files={len(files)} rows={rows_out}", flush=True)
    for dest_dir in (
        staging / "data" / "corpus",
        staging / "data" / "bm25" / "documents",
        staging / "data" / "bm25" / "postings",
        staging / "data" / "graph" / "nodes",
        staging / "data" / "graph" / "edges",
        staging / "data" / "graph" / "adjacency" / "outgoing",
        staging / "data" / "graph" / "adjacency" / "incoming",
        staging / "data" / "vectors",
    ):
        if not dest_dir.is_dir():
            continue
        final = release / dest_dir.relative_to(staging)
        if final.exists():
            shutil.rmtree(final)
        final.parent.mkdir(parents=True, exist_ok=True)
        dest_dir.rename(final)
    adj_root = release / "data" / "graph" / "adjacency"
    for stale_name in ("in", "out"):
        stale = adj_root / stale_name
        if stale.exists():
            shutil.rmtree(stale)
    shutil.rmtree(staging, ignore_errors=True)
    return stats


def diagnose_release_identities(
    root: str | Path, *, sample: int = 200
) -> dict[str, dict[str, int]]:
    """Count CIDv1 vs SHA-256 routing keys on a few shards per family."""

    from .engine import is_cidv1_key

    import pyarrow.parquet as pq

    release = Path(root).expanduser().resolve()
    families = {
        "corpus": release / "data" / "corpus",
        "nodes": release / "data" / "graph" / "nodes",
        "edges": release / "data" / "graph" / "edges",
        "postings": release / "data" / "bm25" / "postings",
        "outgoing": release / "data" / "graph" / "adjacency" / "outgoing",
        "incoming": release / "data" / "graph" / "adjacency" / "incoming",
        "out": release / "data" / "graph" / "adjacency" / "out",
        "in": release / "data" / "graph" / "adjacency" / "in",
    }
    report: dict[str, dict[str, int]] = {}
    for name, folder in families.items():
        files = sorted(path for path in folder.glob("*.parquet") if path.is_file())[:1]
        if not files:
            continue
        table = pq.read_table(files[0])
        wrapped = "record_json" in table.schema.names
        values: list[Any] = []
        if wrapped:
            for raw in table.column("record_json").to_pylist()[:sample]:
                payload = json.loads(str(raw))
                values.append(
                    payload.get("entry_cid")
                    or payload.get("node_cid")
                    or payload.get("edge_cid")
                    or payload.get("term")
                    or ""
                )
        else:
            col = next(
                (
                    candidate
                    for candidate in ("entry_cid", "node_cid", "edge_cid", "term")
                    if candidate in table.schema.names
                ),
                None,
            )
            values = table.column(col).to_pylist()[:sample] if col else []
        cidv1 = 0
        sha = 0
        other = 0
        for value in values:
            text = str(value or "")
            if is_cidv1_key(text):
                cidv1 += 1
            elif "sha256:" in text.lower() or (
                len(text) >= 64
                and all(char in "0123456789abcdef" for char in text[:64].lower())
            ):
                sha += 1
            else:
                other += 1
        report[name] = {
            "sampled": len(values),
            "cidv1": cidv1,
            "sha256_or_hex": sha,
            "other": other,
            "wrapped": int(wrapped),
        }
    return report


def release_needs_sha256_upgrade(root: str | Path) -> bool:
    """True when routing keys are SHA-256/hex, rows are JSON-wrapped, or dirs are ``in``/``out``."""

    release = Path(root).expanduser().resolve()
    adj = release / "data" / "graph" / "adjacency"
    if (adj / "in").is_dir() or (adj / "out").is_dir():
        return True
    report = diagnose_release_identities(release)
    return any(
        int(item.get("wrapped") or 0) or int(item.get("sha256_or_hex") or 0)
        for item in report.values()
    )


def prepare_hf_graphrag_release(
    root: str | Path,
    *,
    repo_id: str = "",
    pretty_name: str = "",
    domain_notes: str = "",
    skip_unwrap: bool = False,
    skip_repair: bool = False,
    force_repair: bool = False,
) -> dict[str, Any]:
    """Unwrap SHA-256 keys, repair range routing, write locators + Hub search pack."""

    from .engine import (
        repair_graphrag_range_routing,
        write_hub_search_pack,
        write_standard_compact_indexes,
    )

    release = Path(root).expanduser().resolve()
    before = diagnose_release_identities(release)
    unwrapped: dict[str, Any] = {}
    if not skip_unwrap and release_needs_sha256_upgrade(release):
        unwrapped = upgrade_wrapped_graphrag_release(release)
    after = diagnose_release_identities(release)
    repaired: dict[str, Any] = {}
    if not skip_repair:
        results = repair_graphrag_range_routing(release, force=force_repair)
        repaired = {
            family: {
                "rewritten": result.rewritten,
                "shard_count": result.shard_count,
                "ok": result.diagnosis_after.ok,
            }
            for family, result in results.items()
        }
    indexes = write_standard_compact_indexes(release)
    pack = write_hub_search_pack(
        release,
        repo_id=repo_id or "local/graphrag-release",
        pretty_name=pretty_name or "GraphRAG",
        domain_notes=domain_notes,
    )
    return {
        "identity_before": before,
        "identity_after": after,
        "unwrapped": unwrapped,
        "repaired": repaired,
        "indexes": {family: result.row_count for family, result in indexes.items()},
        "pack": pack,
    }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="Local GraphRAG release root")
    parser.add_argument("--repo-id", default="")
    parser.add_argument("--pretty-name", default="")
    parser.add_argument("--domain-notes", default="")
    parser.add_argument("--skip-unwrap", action="store_true")
    parser.add_argument("--skip-repair", action="store_true")
    parser.add_argument("--force-repair", action="store_true")
    parser.add_argument("--diagnose-only", action="store_true")
    args = parser.parse_args(argv)
    if args.diagnose_only:
        print(json.dumps(diagnose_release_identities(args.root), indent=2))
        return 0
    result = prepare_hf_graphrag_release(
        args.root,
        repo_id=args.repo_id,
        pretty_name=args.pretty_name,
        domain_notes=args.domain_notes,
        skip_unwrap=args.skip_unwrap,
        skip_repair=args.skip_repair,
        force_repair=args.force_repair,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
