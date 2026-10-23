"""Staging helpers for archived documents (SCHEMA.md §1 contract + archive provenance).

SCHEMA.md v1.0.0 has no archive fields and no extra-metadata column, so provenance is carried as
extra top-level keys on each staged record (validate_record ignores unknown keys):

    archive_source       "commoncrawl" | "wayback"
    archive_crawl_id     "CC-MAIN-2026-39" | "wayback"
    archive_timestamp    ISO 8601 UTC of the capture
    archive_url          WARC locator / web.archive.org/web/<ts>id_/<url>
    original_url         URL as captured (also used as source_url)
    content_complete     false if WARC-truncated / partial / body shorter than declared
    possibly_stale       true if capture older than 2 years (vs 2026-10-10)

and the same object is duplicated under "extra_metadata": {"archive": {...}}. run_loop.py drops
unknown keys when building the 22-column parquet, so StagedWriter ALSO writes an uploader-ignored
sidecar  <stage_dir>/_archive_provenance/<CC>/<final file name>  (one {doc_id, ...provenance} per
line) that survives the move of the staged file to processed/.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from schema import place_key, validate_file, validate_record  # noqa: E402

PROV_KEYS = ("archive_source", "archive_crawl_id", "archive_timestamp", "archive_url",
             "original_url", "content_complete", "possibly_stale")


POLICY_KEYS = ("source_policy", "robots_basis")   # optional, e.g. source_policy="archived_robots_disallowed"


def provenance_fields(doc, source_policy: Optional[str] = None, robots_basis: Optional[str] = None) -> Dict[str, Any]:
    """Flat provenance keys + extra_metadata.archive. With source_policy (e.g. 'archived_robots_disallowed'
    for hosts whose robots.txt disallows live crawling) it is added top level, in extra_metadata.archive
    and (via StagedWriter) in the provenance sidecar."""
    p = doc.provenance() if hasattr(doc, "provenance") else {k: doc.get(k) for k in PROV_KEYS}
    p = dict(p)
    if source_policy:
        p["source_policy"] = source_policy
        if robots_basis:
            p["robots_basis"] = robots_basis
    out = dict(p)
    out["extra_metadata"] = {"archive": dict(p)}
    return out


def utc_batch() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class StagedWriter:
    """Buffer records for ONE place and flush them as immutable chunk files.

    final name: <stage_dir>/<CC>/<place_key>.<batch_prefix><UTC>p<NNNN>.jsonl
    (batch_prefix should contain 'archive', e.g. 'archive-').
    """

    def __init__(self, stage_dir: Path | str, cc: str, place_id: str, batch_prefix: str = "archive",
                 chunk: int = 500, max_bytes: int = 200 * 1024 * 1024):
        self.stage = Path(stage_dir)
        self.cc = cc
        self.place_id = place_id
        self.pkey = place_key(place_id)
        self.prefix = batch_prefix
        self.chunk = chunk
        self.max_bytes = max_bytes
        self.buf: List[Dict[str, Any]] = []
        self.bytes = 0
        self.part = 0
        self.written: List[str] = []
        self.rejected = 0

    def add(self, rec: Dict[str, Any]) -> Optional[str]:
        errs = validate_record(rec)
        if errs:
            self.rejected += 1
            return ";".join(errs)
        self.buf.append(rec)
        self.bytes += len(json.dumps(rec, ensure_ascii=False))
        if len(self.buf) >= self.chunk or self.bytes >= self.max_bytes:
            self.flush()
        return None

    def flush(self) -> Optional[Path]:
        if not self.buf:
            return None
        self.part += 1
        d = self.stage / self.cc
        d.mkdir(parents=True, exist_ok=True)
        batch = f"{self.prefix}{utc_batch()}p{self.part:04d}"
        final = d / f"{self.pkey}.{batch}.jsonl"
        while final.exists():
            self.part += 1
            final = d / f"{self.pkey}.{self.prefix}{utc_batch()}p{self.part:04d}.jsonl"
        tmp = final.with_name(final.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for r in self.buf:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush(); os.fsync(f.fileno())
        # validate_file needs a .jsonl suffix -> validate a hard link with the final-ish name
        chk = d / f".{final.name}.check.jsonl"
        os.link(tmp, chk)
        try:
            res = validate_file(chk, expect_place_key=self.pkey)
        finally:
            chk.unlink()
        if not res["ok"]:
            bad = d.parent / "_archive_rejects"
            bad.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, bad / (final.name + ".invalid"))
            raise RuntimeError(f"staged chunk failed validation: {res['errors'][:3]}")
        # provenance sidecar (uploader ignores _-prefixed dirs)
        sd = self.stage / "_archive_provenance" / self.cc
        sd.mkdir(parents=True, exist_ok=True)
        stmp = sd / (final.name + ".tmp")
        with stmp.open("w", encoding="utf-8") as f:
            for r in self.buf:
                f.write(json.dumps({"doc_id": r["doc_id"], "place_id": r["place_id"],
                                    **{k: r.get(k) for k in PROV_KEYS},
                                    **{k: r[k] for k in POLICY_KEYS if r.get(k)}}, ensure_ascii=False) + "\n")
            f.flush(); os.fsync(f.fileno())
        os.rename(stmp, sd / final.name)
        os.rename(tmp, final)
        self.written.append(str(final))
        self.buf, self.bytes = [], 0
        return final
