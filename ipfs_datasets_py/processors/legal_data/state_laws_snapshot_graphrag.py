"""Snapshot/research sparse GraphRAG helpers for all 51 state laws.

This lane indexes locally available statute text with the existing Open US
Law GraphRAG stack (term-range BM25, pinned gte-small, centroid vectors,
legal graph). Build-time tokenization, graph extraction, and adjacency
invert share :mod:`ipfs_datasets_py.processors.legal_data.graphrag_parallel`.
It does not authorize Hub publication or a current-bundle.

NY, WI, TN, AR, NH, MS, and GA must come from the operator dumps under
``/tmp/tmp_laws`` (durable ingest: ``vaquill-snapshot-normalized-v2026.08.31``).
The other 44 continue from local LCR JSON-LD when that file is usable.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

from ipfs_datasets_py.processors.legal_data.open_us_law_corpus import (
    default_code_family_for,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    EXACT_51_JURISDICTION_CODES,
    ReleaseConfiguration,
    StatuteStatus,
)

SCHEMA = "ipfs_datasets_py.state_laws.snapshot_graphrag.v1"
MODE = "snapshot_research"
EDITION = "snapshot-research-v2026.08.31"
LIVE_FETCH_BLOCKED_REASON = "residential_proxy_not_used"
REFUSAL = (
    "Release policy requires official_source_receipt_required_per_jurisdiction "
    "and closed_frontier_required_per_jurisdiction. Snapshot dumps and LCR "
    "JSON-LD stubs cannot authorize Hub publication or a current-bundle."
)
FORBIDDEN_DEST_TOKENS = (
    "acquisition-evidence",
    "live-v",
    "current-live",
    "permanently-nonauthorizing",
)
PROTECTED_OFFICIAL_HUB_REPOS = (
    "justicedao/ipfs_state_laws",
    "justicedao/ipfs_federal_register",
)
DEFAULT_SNAPSHOT_HUB_REPO_ID = "Publicus/state-laws-snapshot-graphrag"
REMAINING_TMP_LAWS_STATES = ("AR", "GA", "MS", "NH", "NY", "TN", "WI")
TMP_LAWS_DUMPS = {
    "AR": "Arkansas_Law_v2026-08.cleaned.jsonl.gz",
    "GA": "Georgia_Laws_FRESH_2026-08-31.jsonl.gz",
    "MS": "Mississippi_Laws_2026-08-31.jsonl.gz",
    "NH": "New_Hampshire_Revised_Statutes_v2026-08.jsonl.gz",
    "NY": "New_York_Laws_2026-08-31.jsonl.gz",
    "TN": "Tennessee_Laws_Complete_Collection_REISSUED_2026-08.zip",
    "WI": "Wisconsin_Legal_Corpus_2026-08-31_bundle.zip",
}
JSONLD_USABLE_MIN_RECORDS = 200
JSONLD_STUB_MAX_BYTES = 200_000

DEFAULT_TMP_LAWS = Path("/tmp/tmp_laws")
DEFAULT_STATE_LAWS_ROOT = Path.home() / ".ipfs_datasets" / "state_laws"
DEFAULT_VAQUILL_ROOT = (
    DEFAULT_STATE_LAWS_ROOT / "vaquill-snapshot-normalized-v2026.08.31"
)
DEFAULT_JSONLD_ROOT = DEFAULT_STATE_LAWS_ROOT / "state_laws_jsonld"
DEFAULT_INVENTORY_PATH = (
    DEFAULT_STATE_LAWS_ROOT / "snapshot-graphrag-v2026.08.31.inventory.json"
)
DEFAULT_CORPUS_ROOT = (
    DEFAULT_STATE_LAWS_ROOT / "snapshot-graphrag-corpus-v2026.08.31"
)
DEFAULT_RELEASE_ROOT = DEFAULT_STATE_LAWS_ROOT / "snapshot-graphrag-v2026.08.31"


class SnapshotGraphragError(RuntimeError):
    """Fail-closed snapshot GraphRAG error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def refuse_authorizing_for_publication(flag: bool) -> None:
    if flag:
        raise SystemExit(f"REFUSING Hub authorization: {REFUSAL}")


def refuse_live_dest(path: Path) -> None:
    rendered = str(path)
    for token in FORBIDDEN_DEST_TOKENS:
        if token in rendered:
            raise SnapshotGraphragError(
                f"REFUSING dest looks like a live acquisition root: {path}"
            )


def refuse_official_current_bundle_repo(repo_id: str) -> str:
    """R&D snapshot upload is allowed; official current-bundle repos are not."""

    ident = str(repo_id or "").strip()
    if "/" not in ident or ident.startswith("/") or ident.endswith("/"):
        raise SnapshotGraphragError(
            "dataset_repo_id must have the form namespace/repository"
        )
    if ident.lower() in {item.lower() for item in PROTECTED_OFFICIAL_HUB_REPOS}:
        raise SnapshotGraphragError(
            f"REFUSING official current-bundle Hub target {ident}; "
            "snapshot research must use a non-current-bundle repository"
        )
    return ident


def publish_snapshot_research_hf(
    hf_release_dir: Path,
    *,
    repo_id: str = DEFAULT_SNAPSHOT_HUB_REPO_ID,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Upload the SkillCenter-layout snapshot as research context, not a current-bundle."""

    repo = refuse_official_current_bundle_repo(repo_id)
    root = Path(hf_release_dir)
    manifest = root / "manifest.json"
    if not manifest.is_file():
        raise SnapshotGraphragError(f"HF release manifest missing: {manifest}")
    receipt = {
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "current_bundle": False,
        "dataset_repo_id": repo,
        "dry_run": bool(dry_run),
        "hf_release_dir": str(root),
        "mode": MODE,
        "schema": SCHEMA,
    }
    if dry_run:
        receipt["status"] = "dry_run"
        return receipt
    try:
        from huggingface_hub import HfApi
        from huggingface_hub.utils import get_token
    except ImportError as exc:
        raise SnapshotGraphragError("huggingface_hub is required to publish") from exc
    if not get_token():
        raise SnapshotGraphragError("Hugging Face token is missing")
    api = HfApi()
    api.create_repo(repo_id=repo, repo_type="dataset", exist_ok=True, private=False)
    info = api.upload_folder(
        folder_path=str(root),
        repo_id=repo,
        repo_type="dataset",
        commit_message="Add 51-jurisdiction snapshot/research sparse GraphRAG (not a current-bundle)",
    )
    receipt["commit"] = str(getattr(info, "oid", "") or getattr(info, "commit_url", "") or info)
    receipt["status"] = "uploaded"
    return receipt


def nonauthorizing_receipt(**extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema": SCHEMA,
        "mode": MODE,
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "current_bundle": False,
        "official_source_receipt": False,
        "closed_frontier": False,
        "satisfies_exact_51_gate": False,
        "hub_authorization_refused": REFUSAL,
        "live_official_fetch_blocked_reason": LIVE_FETCH_BLOCKED_REASON,
    }
    payload.update(extra)
    return payload


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def slug_hierarchy_token(value: Any) -> Optional[str]:
    """Make hierarchy tokens legal_id-safe (no ':' or ';' path/qualifier breaks)."""

    text = _as_str(value)
    if not text:
        return None
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    if not text:
        return None
    return text[:128]


def sanitize_hierarchy(hierarchy: Mapping[str, Any] | None) -> Optional[Dict[str, Optional[str]]]:
    raw = dict(hierarchy or {})
    cleaned: Dict[str, Optional[str]] = {}
    for key in ("title", "chapter", "part", "article", "section", "subsection"):
        cleaned[key] = slug_hierarchy_token(raw.get(key))
    if not cleaned.get("section"):
        return None
    return cleaned


def _hierarchy_from_normalized(record: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    title = _as_str(record.get("title_number")) or None
    chapter = _as_str(record.get("chapter_number")) or None
    section = (
        _as_str(record.get("section_number"))
        or _as_str(record.get("statute_id"))
        or None
    )
    return {"title": title, "chapter": chapter, "section": section, "subsection": None}


def _hierarchy_from_jsonld(record: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    chapter = record.get("chapter")
    chapter_number = _as_str(record.get("chapterNumber"))
    if not chapter_number and isinstance(chapter, Mapping):
        chapter_number = _as_str(chapter.get("chapter_label") or chapter.get("chapter_name"))
    section = _as_str(record.get("sectionNumber")) or None
    return {
        "title": _as_str(record.get("titleNumber")) or None,
        "chapter": chapter_number or None,
        "section": section,
        "subsection": None,
    }


def map_normalized_statute_to_oul_row(record: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Map one Vaquill NormalizedStatute object onto an OUL corpus row."""

    code = _as_str(record.get("state_code") or record.get("jurisdiction_code")).upper()
    if code not in EXACT_51_JURISDICTION_CODES:
        return None
    text = _as_str(record.get("full_text") or record.get("text"))
    if not text:
        return None
    metadata = record.get("metadata") if isinstance(record.get("metadata"), Mapping) else {}
    structured = (
        record.get("structured_data")
        if isinstance(record.get("structured_data"), Mapping)
        else {}
    )
    if bool(metadata.get("repealed")) or str(structured.get("status") or "") == "repealed":
        return None
    hierarchy = sanitize_hierarchy(_hierarchy_from_normalized(record))
    if hierarchy is None:
        return None
    family = default_code_family_for(code, ReleaseConfiguration.STATE_STATUTES_EXACT_51)
    source_url = _as_str(record.get("source_url") or record.get("official_source_url"))
    heading = _as_str(record.get("section_name") or record.get("short_title"))
    return {
        "admission_status": "admitted",
        "code_family": family,
        "configuration": ReleaseConfiguration.STATE_STATUTES_EXACT_51.value,
        "document_kind": "statute",
        "edition": EDITION,
        "heading": heading,
        "hierarchy": hierarchy,
        "jurisdiction_code": code,
        "official_source_url": source_url,
        "snapshot_source_kind": "tmp_laws",
        "status": StatuteStatus.CURRENT.value,
        "text": text,
    }


def map_jsonld_to_oul_row(record: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Map one LCR JSON-LD Legislation object onto an OUL corpus row."""

    code = _as_str(record.get("stateCode") or record.get("jurisdiction_code")).upper()
    if code not in EXACT_51_JURISDICTION_CODES:
        return None
    if code in REMAINING_TMP_LAWS_STATES:
        raise SnapshotGraphragError(
            f"REFUSING JSON-LD for remaining-state {code}; "
            "use /tmp/tmp_laws ingest only"
        )
    text = _as_str(record.get("text"))
    if not text:
        return None
    hierarchy = sanitize_hierarchy(_hierarchy_from_jsonld(record))
    if hierarchy is None:
        return None
    family = default_code_family_for(code, ReleaseConfiguration.STATE_STATUTES_EXACT_51)
    return {
        "admission_status": "admitted",
        "code_family": family,
        "configuration": ReleaseConfiguration.STATE_STATUTES_EXACT_51.value,
        "document_kind": "statute",
        "edition": EDITION,
        "heading": _as_str(record.get("sectionName") or record.get("name")),
        "hierarchy": hierarchy,
        "jurisdiction_code": code,
        "official_source_url": _as_str(record.get("sourceUrl")),
        "snapshot_source_kind": "lcr_jsonld",
        "status": StatuteStatus.CURRENT.value,
        "text": text,
    }


def _iter_json_lines(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                yield payload


def _count_json_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def load_ingest_manifest(vaquill_root: Path) -> Dict[str, Any]:
    path = vaquill_root / "ingest_manifest.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def dump_digest_from_manifest(manifest: Mapping[str, Any], code: str) -> Optional[str]:
    for state in manifest.get("states") or []:
        if isinstance(state, Mapping) and state.get("state_code") == code:
            digest = state.get("source_sha256")
            return str(digest) if digest else None
    return None


def inventory_jurisdiction(
    code: str,
    *,
    tmp_laws: Path = DEFAULT_TMP_LAWS,
    vaquill_root: Path = DEFAULT_VAQUILL_ROOT,
    jsonld_root: Path = DEFAULT_JSONLD_ROOT,
    ingest_manifest: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    manifest = ingest_manifest if ingest_manifest is not None else load_ingest_manifest(vaquill_root)
    jsonld_path = jsonld_root / f"STATE-{code}.jsonld"
    jsonld_bytes = jsonld_path.stat().st_size if jsonld_path.is_file() else 0
    jsonld_records = _count_json_lines(jsonld_path) if jsonld_path.is_file() else 0
    jsonld_usable = jsonld_path.is_file() and jsonld_records >= JSONLD_USABLE_MIN_RECORDS

    record: Dict[str, Any] = {
        "jurisdiction_code": code,
        "jsonld_path": str(jsonld_path) if jsonld_path.is_file() else None,
        "jsonld_bytes": jsonld_bytes,
        "jsonld_record_count": jsonld_records,
        "jsonld_usable": jsonld_usable,
        "authorizing_for_publication": False,
        "current_bundle": False,
    }

    if code in REMAINING_TMP_LAWS_STATES:
        dump_name = TMP_LAWS_DUMPS[code]
        dump_path = tmp_laws / dump_name
        jsonl_path = vaquill_root / code / "statutes.jsonl"
        dump_sha = None
        if dump_path.is_file():
            dump_sha = sha256_file(dump_path)
        else:
            dump_sha = dump_digest_from_manifest(manifest, code)
        if not jsonl_path.is_file():
            record.update(
                {
                    "chosen_source": "gap",
                    "gap_reason": f"missing {code} ingest at {jsonl_path}",
                    "tmp_laws_dump": str(dump_path),
                    "tmp_laws_dump_present": dump_path.is_file(),
                    "source_sha256": dump_sha,
                }
            )
            return record
        record.update(
            {
                "chosen_source": "tmp_laws",
                "source_kind": "vaquill_jsonl",
                "source_path": str(jsonl_path),
                "source_sha256": sha256_file(jsonl_path),
                "dump_name": dump_name,
                "tmp_laws_dump": str(dump_path),
                "tmp_laws_dump_present": dump_path.is_file(),
                "dump_sha256": dump_sha,
                "statute_count": _count_json_lines(jsonl_path),
                "coverage": "full",
            }
        )
        return record

    if jsonld_path.is_file() and jsonld_records >= 1:
        record.update(
            {
                "chosen_source": "lcr_jsonld",
                "source_kind": "lcr_jsonld",
                "source_path": str(jsonld_path),
                "source_sha256": sha256_file(jsonld_path),
                "statute_count": jsonld_records,
                "coverage": "full" if jsonld_usable else "partial",
            }
        )
        return record

    record.update(
        {
            "chosen_source": "gap",
            "gap_reason": (
                "jsonld missing or empty "
                f"(bytes={jsonld_bytes}, records={jsonld_records})"
            ),
        }
    )
    return record


def inventory_all(
    *,
    tmp_laws: Path = DEFAULT_TMP_LAWS,
    vaquill_root: Path = DEFAULT_VAQUILL_ROOT,
    jsonld_root: Path = DEFAULT_JSONLD_ROOT,
) -> Dict[str, Any]:
    manifest = load_ingest_manifest(vaquill_root)
    states = [
        inventory_jurisdiction(
            code,
            tmp_laws=tmp_laws,
            vaquill_root=vaquill_root,
            jsonld_root=jsonld_root,
            ingest_manifest=manifest,
        )
        for code in EXACT_51_JURISDICTION_CODES
    ]
    chosen = {row["jurisdiction_code"]: row["chosen_source"] for row in states}
    return nonauthorizing_receipt(
        inventoried_at=utc_now(),
        remaining_tmp_laws_states=list(REMAINING_TMP_LAWS_STATES),
        jurisdiction_count=len(states),
        chosen_source_counts={
            "tmp_laws": sum(1 for row in states if row["chosen_source"] == "tmp_laws"),
            "lcr_jsonld": sum(1 for row in states if row["chosen_source"] == "lcr_jsonld"),
            "gap": sum(1 for row in states if row["chosen_source"] == "gap"),
        },
        remaining_seven_all_tmp_laws=all(
            chosen.get(code) == "tmp_laws" for code in REMAINING_TMP_LAWS_STATES
        ),
        all_51_have_source=all(src != "gap" for src in chosen.values()),
        states=states,
    )


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def assemble_jurisdiction(
    inventory_row: Mapping[str, Any],
    *,
    dest_root: Path,
) -> Dict[str, Any]:
    code = str(inventory_row["jurisdiction_code"])
    refuse_live_dest(dest_root)
    if code in REMAINING_TMP_LAWS_STATES and inventory_row.get("chosen_source") != "tmp_laws":
        raise SnapshotGraphragError(
            f"REFUSING to assemble {code} from {inventory_row.get('chosen_source')!r}; "
            "remaining states must use /tmp/tmp_laws"
        )
    if inventory_row.get("source_kind") == "lcr_jsonld" and code in REMAINING_TMP_LAWS_STATES:
        raise SnapshotGraphragError(
            f"REFUSING JSON-LD for remaining-state {code}"
        )
    chosen = inventory_row.get("chosen_source")
    dest_dir = dest_root / code
    rows_path = dest_dir / "rows.jsonl"
    if chosen == "gap":
        return nonauthorizing_receipt(
            jurisdiction_code=code,
            chosen_source="gap",
            gap_reason=inventory_row.get("gap_reason"),
            row_count=0,
            output_path=None,
        )
    source_path = Path(str(inventory_row["source_path"]))
    if not source_path.is_file():
        raise SnapshotGraphragError(f"missing source for {code}: {source_path}")
    mapper = (
        map_normalized_statute_to_oul_row
        if inventory_row.get("source_kind") == "vaquill_jsonl"
        else map_jsonld_to_oul_row
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    mapped = (row for record in _iter_json_lines(source_path) if (row := mapper(record)))
    count = _write_jsonl(rows_path, mapped)
    receipt_path = dest_dir / "assembly_receipt.json"
    receipt = nonauthorizing_receipt(
        jurisdiction_code=code,
        chosen_source=inventory_row.get("chosen_source"),
        source_kind=inventory_row.get("source_kind"),
        source_path=str(source_path),
        source_sha256=inventory_row.get("source_sha256"),
        dump_sha256=inventory_row.get("dump_sha256"),
        row_count=count,
        output_path=str(rows_path),
        output_sha256=sha256_file(rows_path),
        assembled_at=utc_now(),
    )
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def assemble_corpus(
    inventory: Mapping[str, Any],
    *,
    dest_root: Path,
) -> Dict[str, Any]:
    refuse_live_dest(dest_root)
    if dest_root.exists() and any(dest_root.iterdir()):
        raise SnapshotGraphragError(f"REFUSING dest already exists: {dest_root}")
    dest_root.mkdir(parents=True, exist_ok=True)
    assembled: List[Dict[str, Any]] = []
    for row in inventory.get("states") or []:
        assembled.append(assemble_jurisdiction(row, dest_root=dest_root))
    summary = nonauthorizing_receipt(
        assembled_at=utc_now(),
        dest_root=str(dest_root),
        jurisdiction_count=len(assembled),
        assembled_row_count=sum(int(item.get("row_count") or 0) for item in assembled),
        remaining_tmp_laws_states=list(REMAINING_TMP_LAWS_STATES),
        states=assembled,
    )
    (dest_root / "corpus_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def assembled_jurisdiction_codes(
    dest_root: Path,
    *,
    codes: Optional[Sequence[str]] = None,
) -> List[str]:
    """Return assembled jurisdiction codes that have a rows.jsonl file."""

    selected = list(codes) if codes else list(EXACT_51_JURISDICTION_CODES)
    return [
        code
        for code in selected
        if (Path(dest_root) / code / "rows.jsonl").is_file()
    ]


def load_assembled_rows(
    dest_root: Path,
    *,
    codes: Optional[Sequence[str]] = None,
    limit_per_state: int = 0,
) -> List[Dict[str, Any]]:
    selected = assembled_jurisdiction_codes(dest_root, codes=codes)
    rows: List[Dict[str, Any]] = []
    for code in selected:
        path = dest_root / code / "rows.jsonl"
        if not path.is_file():
            continue
        taken = 0
        for record in _iter_json_lines(path):
            hierarchy = sanitize_hierarchy(record.get("hierarchy"))
            if hierarchy is None:
                continue
            payload = dict(record)
            payload["hierarchy"] = hierarchy
            rows.append(payload)
            taken += 1
            if limit_per_state and taken >= limit_per_state:
                break
    return rows


# SkillCenter-style Hub layout (Publicus/skillcenter-ir). Family configs and
# compact routing indexes are first-class Viewer subsets. Retrieval is
# context-only and never a current-bundle.
SKILLCENTER_SNAPSHOT_CONFIGS: tuple[dict[str, str], ...] = (
    {"config_name": "corpus", "path": "data/corpus/*.parquet", "primary_key": "entry_cid"},
    {"config_name": "bm25_documents", "path": "data/bm25/documents/*.parquet", "primary_key": "entry_cid"},
    {"config_name": "bm25_postings", "path": "data/bm25/postings/*.parquet", "primary_key": "term"},
    {"config_name": "graph_nodes", "path": "data/graph/nodes/*.parquet", "primary_key": "node_cid"},
    {"config_name": "graph_edges", "path": "data/graph/edges/*.parquet", "primary_key": "edge_cid"},
    {
        "config_name": "graph_outgoing_adjacency",
        "path": "data/graph/adjacency/out/*.parquet",
        "primary_key": "node_cid",
    },
    {
        "config_name": "graph_incoming_adjacency",
        "path": "data/graph/adjacency/in/*.parquet",
        "primary_key": "node_cid",
    },
    {"config_name": "vectors", "path": "data/vectors/*.parquet", "primary_key": "chunk_cid"},
    {"config_name": "centroids", "path": "data/vectors/centroids/*.parquet", "primary_key": "centroid_id"},
    {"config_name": "vector_locator", "path": "data/vectors/locator/*.parquet", "primary_key": "entry_cid"},
    {"config_name": "corpus_chunk_index", "path": "indexes/corpus_chunks*.parquet", "primary_key": "first_key"},
    {
        "config_name": "bm25_keyword_index",
        "path": "indexes/bm25_postings_chunks*.parquet",
        "primary_key": "first_key",
    },
    {"config_name": "vector_meta_index", "path": "indexes/vectors_chunks*.parquet", "primary_key": "first_key"},
    {
        "config_name": "graph_outgoing_adjacency_index",
        "path": "indexes/graph_adjacency_out_chunks*.parquet",
        "primary_key": "first_key",
    },
    {
        "config_name": "graph_incoming_adjacency_index",
        "path": "indexes/graph_adjacency_in_chunks*.parquet",
        "primary_key": "first_key",
    },
)


def skillcenter_snapshot_dataset_configs() -> dict[str, Any]:
    configs = []
    for item in SKILLCENTER_SNAPSHOT_CONFIGS:
        configs.append(
            {
                "config_name": item["config_name"],
                "data_files": [{"split": "train", "path": item["path"]}],
                "is_default": item["config_name"] == "corpus",
                "primary_key": item["primary_key"],
                "satisfies_exact_51_gate": False,
                "viewer_visible": True,
            }
        )
    return {
        "default_config": "corpus",
        "layout": "publicus-skillcenter-ir",
        "schema_version": "state-laws-snapshot-skillcenter-layout/v1",
        "viewer_safe_default_exact_51": False,
        "authorizing_for_publication": False,
        "configs": configs,
    }


def _skillcenter_readme_frontmatter() -> str:
    lines = [
        "---",
        "pretty_name: State Laws Snapshot Sparse GraphRAG",
        "license: other",
        "language:",
        "- en",
        "task_categories:",
        "- text-retrieval",
        "- feature-extraction",
        "- sentence-similarity",
        "size_categories:",
        "- 100K<n<1M",
        "tags:",
        "- legal",
        "- state-statutes",
        "- bm25",
        "- embeddings",
        "- graphrag",
        "- parquet",
        "configs:",
    ]
    for item in SKILLCENTER_SNAPSHOT_CONFIGS:
        lines.extend(
            [
                f"- config_name: {item['config_name']}",
                "  data_files:",
                "  - split: train",
                f"    path: {item['path']}",
            ]
        )
    lines.append("---")
    return "\n".join(lines) + "\n"


def _skillcenter_readme_body() -> str:
    return """
# State laws snapshot sparse GraphRAG

CID-keyed retrieval release in the same thin-client layout as
[`Publicus/skillcenter-ir`](https://huggingface.co/datasets/Publicus/skillcenter-ir):

- Zstandard Parquet shards of at most 4,096 rows
- `entry_cid` as the canonical content identity; `document_index` is a compact pointer
- compact BM25 term-range, vector-centroid, corpus, and adjacency routing indexes
- `thenlper/gte-small` 384-d L2 vectors, cosine-sorted inside centroid shards
- queries fetch the manifest, routing indexes, and only the routed shards

This is a **snapshot/research** retrieval aid. It is not a current-bundle, does
not close LCR-084, and does not authorize Hub publication of
`justicedao/ipfs_state_laws`. Official state publications remain the authority.

## Remote retrieval without a full download

```bash
python scripts/query_open_us_law_hf.py \\
  --local-root . --fixture-mode --json --trace \\
  bm25 "public records" --top-k 10
```

Vector retrieval probes compact centroids and exact-scores only selected shards.

NY, WI, TN, AR, NH, MS, and GA come from local `/tmp/tmp_laws` dumps. Other
jurisdictions use the best local LCR JSON-LD available. Partial JSON-LD coverage
is recorded; it does not become an official source receipt.
"""


def apply_skillcenter_snapshot_release(
    hf_release_dir: Path,
    *,
    query_script: Path | None = None,
) -> dict[str, Any]:
    """Overlay SkillCenter family Viewer configs and bundle the query client."""

    root = Path(hf_release_dir)
    if not root.is_dir():
        raise SnapshotGraphragError(f"HF release dir does not exist: {root}")
    configs = skillcenter_snapshot_dataset_configs()
    (root / "dataset_configs.json").write_text(
        json.dumps(configs, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readme_path = root / "README.md"
    existing = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    body = existing
    if existing.startswith("---"):
        rest = existing.split("---", 2)
        body = rest[2] if len(rest) == 3 else existing
    readme_path.write_text(
        _skillcenter_readme_frontmatter() + _skillcenter_readme_body() + body,
        encoding="utf-8",
    )
    copied = None
    if query_script is not None and query_script.is_file():
        dest = root / "scripts"
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / "query_open_us_law_hf.py"
        shutil.copy2(query_script, target)
        copied = str(target.relative_to(root))
    return {
        "authorizing_for_publication": False,
        "default_config": "corpus",
        "layout": "publicus-skillcenter-ir",
        "query_script": copied,
        "viewer_config_count": len(configs["configs"]),
        "viewer_safe_default_exact_51": False,
    }

