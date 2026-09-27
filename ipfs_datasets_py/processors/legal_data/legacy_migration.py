"""Plan and stage legacy JusticeDAO corpora into the IR search schema.

Dry-run is the only default. Staging writes compact indexes (CIDs, term
ranges, centroids, BWBR aliases). It does not copy HTML, opinion text, or
embedding floats, and it does not upload or open ``control.duckdb``.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from ipfs_datasets_py.retrieval.hf_graphrag.engine import is_cidv1_key

_FORBIDDEN_READ = frozenset({"html", "text", "embedding", "vector", "path", "relative_path"})
_CASELAW_SPACES = (
    "thenlper/gte-small:384",
    "Alibaba-NLP/gte-large-en-v1.5:1024",
    "Alibaba-NLP/gte-Qwen2-1.5B-instruct:1536",
)
_SPACE_BY_TOKEN = (
    ("gte-qwen2", _CASELAW_SPACES[2]),
    ("gte-large", _CASELAW_SPACES[1]),
    ("gte-small", _CASELAW_SPACES[0]),
)


class LegacyMigrationError(ValueError):
    """The migration planner refused to stage a corpus."""


def _parquet_files(root: Path) -> tuple[Path, ...]:
    if not root.is_dir():
        return ()
    return tuple(sorted(path for path in root.rglob("*.parquet") if path.is_file()))


def _schema_names(path: Path) -> tuple[str, ...]:
    import pyarrow.parquet as pq

    return tuple(pq.read_schema(path).names)


def _column(path: Path, name: str) -> list[object]:
    import pyarrow.parquet as pq

    names = set(_schema_names(path))
    if name not in names:
        raise LegacyMigrationError(f"{path.name} has no {name} column")
    if name in _FORBIDDEN_READ:
        raise LegacyMigrationError(f"refusing to read {name}")
    return list(pq.read_table(path, columns=[name]).column(name).to_pylist())


def _file_kind(path: Path) -> str:
    stem = path.name.lower()
    if stem.endswith("_html.parquet") or "_html" in stem:
        return "html"
    if stem.endswith("_citation.parquet") or "citation" in stem:
        return "citation"
    if stem.endswith("_embeddings.parquet") or "embedding" in stem:
        return "embeddings"
    return "other"


def _space_for_name(name: str) -> str | None:
    lowered = name.lower()
    for token, space in _SPACE_BY_TOKEN:
        if token in lowered:
            return space
    return None


def inventory_parquet(root: Path) -> tuple[dict[str, object], ...]:
    """Column names and row counts. Body and embedding columns are not read."""

    import pyarrow.parquet as pq

    files: list[dict[str, object]] = []
    for path in _parquet_files(root):
        schema = _schema_names(path)
        files.append(
            {
                "name": str(path.relative_to(root)),
                "kind": _file_kind(path),
                "columns": list(schema),
                "rows": int(pq.ParquetFile(path).metadata.num_rows),
                "reads_body": False,
            }
        )
    return tuple(files)


def _cids(paths: Iterable[Path]) -> tuple[list[str], int]:
    kept: list[str] = []
    needs = 0
    for path in paths:
        if "cid" not in set(_schema_names(path)):
            continue
        for raw in _column(path, "cid"):
            cid = str(raw or "").strip()
            if is_cidv1_key(cid):
                kept.append(cid)
            elif cid:
                needs += 1
    return kept, needs


def plan_legacy_migration(checkout_root: str | Path) -> dict[str, object]:
    """Inventory local checkouts. Does not stage files or contact Hugging Face."""

    root = Path(checkout_root).expanduser().resolve()
    if not root.is_dir():
        raise LegacyMigrationError("checkout root must be a directory")
    municipal = root / "american_municipal_law"
    text = root / "ipfs_caselaw_access_project"
    dedup = root / "dedup_ipfs_caselaw_access_project"
    embeddings = root / "Caselaw_Access_Project_embeddings"
    netherlands = root / "ipfs_netherlands_laws"
    files = inventory_parquet(municipal) if municipal.is_dir() else ()
    html = [item for item in files if item["kind"] == "html"]
    citation = [item for item in files if item["kind"] == "citation"]
    embedded = [item for item in files if item["kind"] == "embeddings"]
    html_paths = [municipal / str(item["name"]) for item in html]
    cids, needs_cid = _cids(html_paths) if municipal.is_dir() else ([], 0)
    citation_cids = set()
    if municipal.is_dir():
        for item in citation:
            path = municipal / str(item["name"])
            if "cid" in set(_schema_names(path)):
                citation_cids.update(str(value or "").strip() for value in _column(path, "cid"))
    html_cids = set(cids)
    citation_without = sorted(cid for cid in citation_cids if cid and cid not in html_cids)
    if not municipal.is_dir():
        municipal_decision = "missing"
    elif not html or citation_without:
        municipal_decision = "blocked"
    else:
        municipal_decision = "ready_to_stage"
    text_present = text.is_dir()
    dedup_present = dedup.is_dir()
    if text_present and dedup_present:
        caselaw_decision = "unresolved_duplicate"
    elif text_present or dedup_present:
        caselaw_decision = "ready_to_stage"
    else:
        caselaw_decision = "missing"
    spaces: list[str] = []
    unknown: list[str] = []
    if embeddings.is_dir():
        for path in _parquet_files(embeddings):
            space = _space_for_name(path.name)
            if space is None:
                unknown.append(path.name)
            elif space not in spaces:
                spaces.append(space)
    if not embeddings.is_dir():
        embedding_decision = "missing"
    elif unknown or not spaces:
        embedding_decision = "blocked"
    else:
        embedding_decision = "ready_to_stage"
    bwbr_count = 0
    if netherlands.is_dir():
        for path in _parquet_files(netherlands):
            names = set(_schema_names(path))
            if "bwbr_id" in names:
                bwbr_count += sum(1 for value in _column(path, "bwbr_id") if str(value or "").strip())
    return {
        "research_only": True,
        "authoritative": False,
        "ducklake_authoritative": False,
        "executed_migration": False,
        "municipal": {
            "decision": municipal_decision,
            "html_files": len(html),
            "citation_files": len(citation),
            "embedding_files": len(embedded),
            "cid_count": len(cids),
            "needs_cid": needs_cid,
            "citation_without_html_cid": len(citation_without),
            "vector_space_id": "openai:text-embedding-3-small:1536",
            "fuse_with_bm25": False,
            "coverage": "snapshot",
        },
        "caselaw_text": {
            "decision": caselaw_decision,
            "repos_present": [
                name
                for name, present in (
                    ("ipfs_caselaw_access_project", text_present),
                    ("dedup_ipfs_caselaw_access_project", dedup_present),
                )
                if present
            ],
        },
        "caselaw_embeddings": {
            "decision": embedding_decision,
            "spaces": spaces,
            "unknown_files": unknown,
            "fuse_with_bm25": False,
        },
        "netherlands": {
            "decision": "ready_to_stage" if netherlands.is_dir() else "missing",
            "bwbr_count": bwbr_count,
            "published_cap": "5000 of 42956 BWBR identifiers",
            "coverage": "capped",
        },
    }


def _write_table(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([dict(row) for row in rows]), path)


def _digest(values: Iterable[str]) -> str:
    return sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()


def stage_municipal(source: str | Path, output: str | Path, *, apply: bool) -> dict[str, object]:
    """Stage municipal CIDs and one citation term range. HTML is not read."""

    root = Path(source).expanduser().resolve()
    html_paths = [path for path in _parquet_files(root) if _file_kind(path) == "html"]
    citation_paths = [path for path in _parquet_files(root) if _file_kind(path) == "citation"]
    cids, needs_cid = _cids(html_paths)
    terms: list[str] = []
    for path in citation_paths:
        names = set(_schema_names(path))
        if "bluebook_citation" not in names or "cid" not in names:
            continue
        paired = zip(_column(path, "cid"), _column(path, "bluebook_citation"))
        for cid, citation in paired:
            if is_cidv1_key(str(cid or "").strip()) and str(citation or "").strip():
                terms.append(str(citation).strip())
    report: dict[str, object] = {
        "corpus_id": "us:municipal",
        "apply": apply,
        "bodies_written": False,
        "cid_count": len(cids),
        "needs_cid": needs_cid,
        "term_count": len(terms),
        "research_only": True,
        "authoritative": False,
        "fuse_with_bm25": False,
        "coverage": "snapshot",
    }
    if not apply:
        report["output"] = None
        return report
    if not cids:
        raise LegacyMigrationError("municipal stage has no CIDv1 rows")
    destination = Path(output).expanduser().resolve() / "american_municipal_law"
    _write_table(
        destination / "indexes" / "subsection_cids.parquet",
        [{"cid": cid} for cid in cids],
    )
    if terms:
        ordered = sorted(terms)
        _write_table(
            destination / "indexes" / "bm25_keyword_shards.parquet",
            [
                {
                    "first_key": ordered[0],
                    "last_key": ordered[-1],
                    "sha256": _digest(cids),
                    "row_count": len(cids),
                    "shard_id": 0,
                    "kind": "bm25_postings",
                }
            ],
        )
    report["output"] = str(destination.parent)
    return report


def stage_caselaw(
    checkout_root: str | Path,
    output: str | Path,
    *,
    apply: bool,
    text_pin: str = "",
) -> dict[str, object]:
    """Stage Caselaw centroids. Refuse text apply until the pin is resolved."""

    root = Path(checkout_root).expanduser().resolve()
    plan = plan_legacy_migration(root)
    text_decision = str(plan["caselaw_text"]["decision"])  # type: ignore[index]
    if apply and text_decision == "unresolved_duplicate" and not text_pin:
        raise LegacyMigrationError(
            "caselaw text pin is unresolved; refusing to apply"
        )
    embeddings = root / "Caselaw_Access_Project_embeddings"
    centroids: list[dict[str, object]] = []
    unknown: list[str] = []
    if embeddings.is_dir():
        for path in _parquet_files(embeddings):
            space = _space_for_name(path.name)
            if space is None:
                unknown.append(path.name)
                continue
            names = set(_schema_names(path))
            if "centroid_id" not in names or "shard_id" not in names:
                unknown.append(path.name)
                continue
            for centroid_id, shard_id in zip(_column(path, "centroid_id"), _column(path, "shard_id")):
                centroids.append(
                    {
                        "vector_space_id": space,
                        "centroid_id": str(centroid_id),
                        "shard_id": int(shard_id),
                    }
                )
    if unknown:
        raise LegacyMigrationError("caselaw embedding file is not one of the three closed spaces")
    report: dict[str, object] = {
        "caselaw_text_decision": text_decision,
        "text_pin": text_pin,
        "apply": apply,
        "bodies_written": False,
        "centroid_count": len(centroids),
        "fuse_with_bm25": False,
        "research_only": True,
        "authoritative": False,
    }
    if not apply:
        report["output"] = None
        return report
    destination = Path(output).expanduser().resolve()
    if centroids:
        _write_table(
            destination / "Caselaw_Access_Project_embeddings" / "indexes" / "centroids.parquet",
            centroids,
        )
    if text_pin:
        text_root = root / text_pin.split("/", 1)[-1]
        opinion_paths = _parquet_files(text_root)
        cids, needs_cid = _cids(opinion_paths)
        report["opinion_cid_count"] = len(cids)
        report["needs_cid"] = needs_cid
        if cids:
            _write_table(
                destination / text_root.name / "indexes" / "opinion_cids.parquet",
                [{"cid": cid} for cid in cids],
            )
    report["output"] = str(destination)
    return report


def stage_netherlands(
    legacy_root: str | Path,
    ir_cids: Iterable[str],
    output: str | Path,
    *,
    apply: bool,
) -> dict[str, object]:
    """Write BWBR aliases. Unmatched identifiers stay capped and unsearchable."""

    root = Path(legacy_root).expanduser().resolve()
    known = {cid for cid in (str(item).strip() for item in ir_cids) if is_cidv1_key(cid)}
    rows: list[dict[str, object]] = []
    linked = 0
    capped = 0
    for path in _parquet_files(root):
        names = set(_schema_names(path))
        if "bwbr_id" not in names:
            continue
        cid_column = "entry_cid" if "entry_cid" in names else "cid" if "cid" in names else ""
        identifiers = _column(path, "bwbr_id")
        cids = _column(path, cid_column) if cid_column else [""] * len(identifiers)
        for identifier, raw_cid in zip(identifiers, cids):
            alias = str(identifier or "").strip()
            if not alias:
                continue
            cid = str(raw_cid or "").strip()
            if is_cidv1_key(cid) and cid in known:
                rows.append({"bwbr_id": alias, "entry_cid": cid, "searchable": True})
                linked += 1
            else:
                rows.append({"bwbr_id": alias, "entry_cid": "", "searchable": False})
                capped += 1
    report: dict[str, object] = {
        "corpus_id": "country:netherlands",
        "apply": apply,
        "linked": linked,
        "capped": capped,
        "published_cap": "5000 of 42956 BWBR identifiers",
        "bodies_written": False,
        "research_only": True,
        "authoritative": False,
        "coverage": "capped",
    }
    if not apply:
        report["output"] = None
        return report
    destination = Path(output).expanduser().resolve() / "ipfs_netherlands_laws"
    _write_table(destination / "indexes" / "bwbr_alias.parquet", rows)
    report["output"] = str(destination.parent)
    return report


def write_report(path: str | Path, payload: Mapping[str, object]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
