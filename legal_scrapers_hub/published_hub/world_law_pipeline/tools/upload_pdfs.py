#!/usr/bin/env python3
"""Upload staged image-only scanned PDFs to endomorphosis/world_law_scanned_pdfs (contract: PDF_STAGING.md).

    staging/pdf/<CC>/<place_key>/<sanitized doc_id>.pdf
    staging/pdf/_manifest/batch_<NNNN>.jsonl   one JSON object per PDF (doc_id, place_id, place_key, country_code,
                                               source_url, sha256, bytes, fetched_at, source_policy, lane)
    staging/pdf/_manifest/batch_<NNNN>.ready   written LAST by the OCR bot: the batch is complete

Per ready batch (oldest first, skipped when batch_<NNNN>.pushed exists):
  1. validate each record, hash the PDF (streaming), apply the source policy (schema.hold_reason: robots_unreachable /
     robots_disallowed live fetches are HELD -> moved to held/pdf/, never published);
  2. upload the rest in a few large commits (xet; files are streamed from disk, never loaded into memory):
     --shard-mode tar (DEFAULT since 2026-10-18; env WORLD_LAW_PDF_SHARD_MODE): per-country uncompressed tar shards
       shards/<CC>/<YYYY>/<MM>/<CC>_<seq>.tar, members <place_key>/<sha256>.pdf (tools/pdf_shards.py); pdf_ref =
       "<repo>:<shard>#member=..&offset=..&size=..&sha256=.." (one PDF = one HTTP byte range). A PDF whose sha256 is
       already published (loose or in a shard) is not re-uploaded: its rows reuse the existing ref.
     --shard-mode loose (fallback, and the default for programmatic callers without args.shard_mode):
       pdfs/<CC>/[<b>/]<place_key>/<sha256>.pdf;
     A record whose local PDF is gone but whose sha256 is already verified on the Hub counts as done (not
     missing_file) - the retry case after a partially verified batch.
  3. verify every file's sha256 on the Hub (get_paths_info), ledger state/pdf_ledger.jsonl;
  4. update manifest.parquet (+ README) on the Hub, state/pdf_refs/<CC>/<place_key>.json ({doc_id: pdf_ref}) and the
     backfill queue state/pdf_backfill_pending.txt (places already published in the law repos);
  5. delete the batch's PDFs locally, write batch_<NNNN>.pushed (JSON); the manifest jsonl is kept.
Idempotent: a verified (sha256, path) in the ledger is never re-uploaded; a crash at any step is resumed on rerun.
Never writes to the law repos (the pdf_ref backfill goes through run_loop.py, see tools/pdf_step.py)."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import schema as S  # noqa: E402

BASE = Path(os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law"))
PDF_REPO = S.PDF_REPO_ID
FORBIDDEN = {"endomorphosis/american_municipal_law", "justicedao/american_municipal_law",
             S.REPO_ID, S.NATIONAL_REPO_ID}
REQUIRED = ["doc_id", "place_id", "place_key", "country_code", "source_url", "sha256", "bytes", "fetched_at",
            "source_policy", "lane"]
MANIFEST_COLUMNS = ["doc_id", "place_id", "place_key", "country_code", "source_url", "sha256", "bytes",
                    "fetched_at", "source_policy", "lane", "law_repo", "law_path", "pdf_path", "pdf_ref",
                    "batch", "uploaded_at", "shard_path", "member", "offset", "size"]
MANIFEST_INT_COLUMNS = {"bytes", "offset", "size"}
SHARD_MODES = ("tar", "loose")
DEFAULT_SHARD_MODE = os.environ.get("WORLD_LAW_PDF_SHARD_MODE", "tar")   # CLI default; set "loose" to fall back
COMMIT_MAX_BYTES = 3 * 1024 ** 3   # ~2 GB batch -> 1 data commit (+1 manifest commit)
COMMIT_MAX_FILES = 6_000
COMMIT_TIMEOUT_S = 25 * 60       # one create_commit (~1.7 GB batch) is abandoned after this; retried, then Hub-verified
MEM_LOW_GB = 1.5                 # same floor as run_loop.MEM_LOW_GB: no new batch is started below this MemAvailable
_BATCH_RE = re.compile(r"^batch_(\d{4,})\.ready$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] upload_pdfs: {msg}", flush=True)


def mem_available_gb() -> float:
    """MemAvailable from /proc/meminfo in GB (inf if unreadable); mirrors run_loop.mem_available_gb."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024 / 1e9
    except OSError:
        pass
    return float("inf")


def timed_commit(api, timeout_s: float, **kw):
    """api.create_commit in a daemon thread; raises TimeoutError after timeout_s (the abandoned commit may still
    land: callers verify every file by Hub sha256 afterwards, so a late landing is harmless and a retry is idempotent)."""
    import threading
    box: Dict[str, Any] = {}

    def work():
        try:
            box["ci"] = api.create_commit(**kw)
        except BaseException as e:  # noqa: BLE001
            box["err"] = e

    th = threading.Thread(target=work, name="pdf-commit", daemon=True)
    th.start()
    th.join(timeout_s if timeout_s and timeout_s > 0 else None)
    if th.is_alive():
        raise TimeoutError(f"create_commit exceeded {timeout_s:.0f}s")
    if "err" in box:
        raise box["err"]
    return box.get("ci")


def write_lock_info(lock, **extra) -> None:
    """Holder JSON (pid, started_at, heartbeat_at) in the flock'd file, for stale-lock checks by pdf_loop."""
    try:
        info = {"pid": os.getpid(), "started_at": extra.pop("started_at", None) or utc_now(),
                "heartbeat_at": utc_now(), **extra}
        lock.seek(0)
        lock.truncate()
        lock.write(json.dumps(info) + "\n")
        lock.flush()
    except OSError:
        pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_doc_id(doc_id: str) -> str:
    """File stem for a doc_id (PDF_STAGING.md §2): ':' '/' '\\' -> '_' ; nothing else changes."""
    return re.sub(r"[:/\\]", "_", str(doc_id))


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_ignored(name: str) -> bool:
    return name.startswith(("_", ".")) or name.endswith(".tmp")


def iter_jsonl(p: Path) -> Iterator[Tuple[int, Any]]:
    with open(p, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if line.strip():
                try:
                    yield i, json.loads(line)
                except ValueError as e:
                    yield i, f"bad_json:{e}"


def append_jsonl(p: Path, rec: Dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def atomic_write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("." + p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------
def ledger_key(path_in_repo: str, member: Optional[str] = None) -> str:
    return f"{path_in_repo}#{member}" if member else path_in_repo


def load_ledger(path: Path) -> Dict[str, Dict[str, Any]]:
    """{key: last verified entry} (streamed; one small dict per published PDF). key = path_in_repo for loose PDFs,
    '<shard>.tar#<member>' for shard members (entry also has shard/member/offset/size)."""
    out: Dict[str, Dict[str, Any]] = {}
    if path.exists():
        for _, r in iter_jsonl(path):
            if isinstance(r, dict) and r.get("verified") and r.get("path_in_repo"):
                e = {"sha256": r["sha256"], "commit": r.get("commit")}
                if r.get("member"):
                    e.update(shard=r["path_in_repo"], member=r["member"], offset=int(r["offset"]), size=int(r["size"]))
                out[ledger_key(r["path_in_repo"], r.get("member"))] = e
    return out


def sha_index(ledger: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """{sha256: ledger key}, preferring a loose file over a shard member (existing loose refs stay in use)."""
    idx: Dict[str, str] = {}
    for k, e in ledger.items():
        cur = idx.get(e["sha256"])
        if cur is None or ("#" in cur and "#" not in k):
            idx[e["sha256"]] = k
    return idx


def attach_ref(item: Dict[str, Any], key: str, ledger: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Point an item at an already published PDF (loose path or shard member)."""
    e = ledger[key]
    item["ledger_key"] = key
    if e.get("member"):
        item.update(path_in_repo=e["shard"], member=e["member"], offset=e["offset"], size=e["size"])
    else:
        item["path_in_repo"] = key
        for k in ("member", "offset", "size"):
            item.pop(k, None)
    return item


def place_counts(ledger: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    c: Dict[str, int] = {}
    for p in ledger:
        if "#" in p:
            continue
        d = p.rsplit("/", 1)[0]
        c[d] = c.get(d, 0) + 1
    return c


# ---------------------------------------------------------------------------
# law repo crosswalk
# ---------------------------------------------------------------------------
def law_location(base: Path, cc: str, pkey: str, doc_id: str, check_doc: bool = True
                 ) -> Tuple[Optional[str], Optional[str]]:
    """(law_repo, law_path) when the place is published (local metadata of out/ or out_national/) and, if the
    local parquet is present, the doc_id is in it. law_path = data parquet path, or the shard glob."""
    nat = S.is_national_key(pkey)
    repo = S.NATIONAL_REPO_ID if nat else S.REPO_ID
    out = base / ("out_national" if nat else "out")
    meta = None
    for rel in [S.metadata_path(cc, pkey)] + S.legacy_metadata_paths(cc, pkey):
        q = out / rel
        if q.exists():
            try:
                meta = json.loads(q.read_text())
            except ValueError:
                meta = None
            break
    if not meta or not meta.get("html_files"):
        return None, None
    files = list(meta["html_files"])
    if check_doc:
        local = [out / f for f in files if (out / f).exists()]
        if local and len(local) == len(files):
            import pyarrow.parquet as pq
            found = None
            for lp in local:
                ids = pq.read_table(str(lp), columns=["doc_id"]).column("doc_id").to_pylist()
                if str(doc_id) in ids:
                    found = lp.relative_to(out).as_posix()
                    break
            if found is None:
                return None, None
            return repo, found
    return repo, files[0] if len(files) == 1 else S.shard_glob(cc, pkey)


# ---------------------------------------------------------------------------
# batch processing
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
import batch_alloc as BA  # noqa: E402

def ready_batches(stage: Path) -> List[str]:
    md = stage / "_manifest"
    if not md.is_dir():
        return []
    out = []
    for f in sorted(md.iterdir()):
        m = _BATCH_RE.match(f.name)
        if m and (md / f"batch_{m.group(1)}.jsonl").exists() and not (md / f"batch_{m.group(1)}.pushed").exists():
            out.append(f"batch_{m.group(1)}")
    # batch-number collisions: .jsonl/.ready rewritten after .pushed, or row count != pushed count -> re-push
    # (idempotent by path: verified files are skipped via the ledger)
    out.extend(b for b in BA.stale_batches(md) if b not in out)
    return sorted(out)


def check_record(rec: Any) -> List[str]:
    if not isinstance(rec, dict):
        return [str(rec)]
    errs = [f"missing:{k}" for k in REQUIRED if k not in rec or (rec[k] in (None, "") and k != "source_policy")]
    if errs:
        return errs
    cc = str(rec["country_code"]).upper()
    if not re.match(r"^[A-Z]{2}$", cc):
        errs.append("bad_country_code")
    try:
        pk = S.place_key(rec["place_id"], None, cc)
        if pk != rec["place_key"]:
            errs.append(f"place_key_mismatch:{pk}!={rec['place_key']}")
    except ValueError as e:
        errs.append(str(e))
    if not _SHA_RE.match(str(rec["sha256"]).lower()):
        errs.append("bad_sha256")
    try:
        int(rec["bytes"])
    except (TypeError, ValueError):
        errs.append("bad_bytes")
    return errs


def published_key(ledger: Dict[str, Dict[str, Any]], idx: Dict[str, str], cc: str, pk: str, sha: str,
                  any_place: bool = True) -> Optional[str]:
    """Ledger key of a verified copy of this PDF: the place's own loose path (flat or split) first, else (any_place)
    any verified copy with the same sha256 (loose preferred over shard)."""
    for split in (False, True):
        k = S.pdf_path(cc, pk, sha, split=split)
        if k in ledger and ledger[k]["sha256"] == sha:
            return k
    return idx.get(sha) if any_place else None


def plan_batch(stage: Path, batch: str, ledger: Dict[str, Dict[str, Any]], split_places: set,
               shard_mode: str = "loose") -> Dict[str, Any]:
    """Classify every record of a batch: upload / already (verified in ledger) / held / skipped (reasons)."""
    plan: Dict[str, Any] = {"upload": [], "already": [], "held": [], "skipped": [], "records": 0}
    counts = place_counts(ledger)
    idx = sha_index(ledger)
    seen_paths: Dict[str, str] = {}
    seen_sha: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for line, rec in iter_jsonl(stage / "_manifest" / f"{batch}.jsonl"):
        plan["records"] += 1
        errs = check_record(rec)
        did = rec.get("doc_id") if isinstance(rec, dict) else None
        if errs:
            plan["skipped"].append({"line": line, "doc_id": did, "reason": ";".join(errs)})
            continue
        cc, pk = str(rec["country_code"]).upper(), rec["place_key"]
        rel = rec.get("pdf_file") or f"{cc}/{pk}/{sanitize_doc_id(did)}.pdf"
        local = stage / rel
        item = {"line": line, "rec": rec, "local": local, "rel": rel}
        hr = S.hold_reason(rec)
        if hr:
            plan["held"].append({**item, "reason": hr})
            continue
        if not local.is_file():
            # retry case: the PDF was verified on the Hub and deleted locally by an earlier (partial) run -> done
            sha = str(rec["sha256"]).lower()
            key = published_key(ledger, idx, cc, pk, sha)
            if key:
                item.update(sha256=sha, bytes=int(rec["bytes"]), commit=ledger[key].get("commit"),
                            recovered_missing=True)
                plan["already"].append(attach_ref(item, key, ledger))
                continue
            plan["skipped"].append({"line": line, "doc_id": did, "reason": f"missing_file:{rel}"})
            continue
        size = local.stat().st_size
        if size != int(rec["bytes"]):
            plan["skipped"].append({"line": line, "doc_id": did, "reason": f"bytes_mismatch:{size}!={rec['bytes']}"})
            continue
        with open(local, "rb") as f:
            if f.read(5) != b"%PDF-":
                plan["skipped"].append({"line": line, "doc_id": did, "reason": "not_a_pdf"})
                continue
        digest = sha256_file(local)
        if digest != str(rec["sha256"]).lower():
            plan["skipped"].append({"line": line, "doc_id": did, "reason": f"sha256_mismatch:{digest}"})
            continue
        pdir = S.pdf_path(cc, pk, digest).rsplit("/", 1)[0]
        if pk in split_places or counts.get(pdir, 0) >= S.PDF_PLACE_MAX:
            split_places.add(pk)
        pir = S.pdf_path(cc, pk, digest, split=pk in split_places)
        item.update(sha256=digest, path_in_repo=pir, bytes=size)
        if shard_mode == "tar":
            key = published_key(ledger, idx, cc, pk, digest)
            if key:      # already on the Hub (loose or shard): keep that ref, never re-upload
                plan["already"].append(attach_ref({**item, "commit": ledger[key]["commit"]}, key, ledger))
            elif (cc, digest) in seen_sha:   # same PDF twice in one batch: packed once, both rows reference it
                plan["already"].append({**item, "commit": None, "dup_in_batch": True, "twin": seen_sha[(cc, digest)]})
            else:
                item.update(cc=cc, place_key=pk)
                seen_sha[(cc, digest)] = item
                plan["upload"].append(item)
            continue
        if pir in ledger and ledger[pir]["sha256"] == digest:
            plan["already"].append({**item, "commit": ledger[pir]["commit"]})
        elif pir in seen_paths:  # same PDF twice in one batch (two doc_ids): upload once, both rows reference it
            plan["already"].append({**item, "commit": None, "dup_in_batch": True})
        else:
            seen_paths[pir] = did
            counts[pdir] = counts.get(pdir, 0) + 1
            plan["upload"].append(item)
    return plan


def chunk(items: List[Dict[str, Any]], max_bytes: int, max_files: int) -> List[List[Dict[str, Any]]]:
    out, cur, b = [], [], 0
    for it in items:
        if cur and (b + it["bytes"] > max_bytes or len(cur) >= max_files):
            out.append(cur)
            cur, b = [], 0
        cur.append(it)
        b += it["bytes"]
    if cur:
        out.append(cur)
    return out


def git_blob_sha1(data: bytes) -> str:
    """git blob id of a file stored as a plain (non-LFS) git object."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


SMALL_DOWNLOAD_MAX = 2_000_000  # non-LFS files up to this size are re-downloaded and sha256-checked


def _download_sha256(api, repo: str, path: str) -> Optional[str]:
    try:
        from huggingface_hub import hf_hub_download
        with tempfile.TemporaryDirectory() as td:
            f = hf_hub_download(repo, path, repo_type="dataset", local_dir=td, token=getattr(api, "token", None))
            return hashlib.sha256(Path(f).read_bytes()).hexdigest()
    except Exception as e:  # noqa: BLE001
        log(f"download verify failed for {path}: {e!r}")
        return None


def hub_sha256(api, repo: str, paths: List[str], local: Optional[Dict[str, Any]] = None,
               download_small: bool = True) -> Dict[str, Optional[str]]:
    """{path: sha256 of the file on the Hub}, 200 paths per call.

    LFS/xet files: the LFS sha256. Small files stored as plain git blobs have no LFS info: then, given the
    local file (local[path]), the Hub's blob_id must equal the local git blob sha1 and the size must match;
    if so (and, when download_small, the downloaded file's sha256 also matches) the local sha256 is returned.
    """
    local = local or {}
    out: Dict[str, Optional[str]] = {}
    for i in range(0, len(paths), 200):
        part = paths[i:i + 200]
        for info in api.get_paths_info(repo, part, repo_type="dataset", expand=True):
            lfs = getattr(info, "lfs", None)
            sha = getattr(lfs, "sha256", None) if lfs is not None else None
            if sha is None and isinstance(lfs, dict):
                sha = lfs.get("sha256")
            if sha is None and lfs is None and info.path in local:
                lp = Path(local[info.path])
                try:
                    data = lp.read_bytes()
                except OSError:
                    data = None
                blob, size = getattr(info, "blob_id", None), getattr(info, "size", None)
                if data is not None and blob and blob == git_blob_sha1(data) and (size is None or size == len(data)):
                    lsha = hashlib.sha256(data).hexdigest()
                    if download_small and len(data) <= SMALL_DOWNLOAD_MAX:
                        sha = lsha if _download_sha256(api, repo, info.path) == lsha else None
                    else:
                        sha = lsha
            out[info.path] = sha
    return out


GITATTR_MAX_BYTES = 1024 ** 2  # warn + compact when the Hub .gitattributes grows past 1 MiB (Hub hard limit: 10 MiB)
LFS_RULES = ["*.pdf filter=lfs diff=lfs merge=lfs -text", "*.parquet filter=lfs diff=lfs merge=lfs -text",
             "*.tar filter=lfs diff=lfs merge=lfs -text"]


def _rule_is_per_file(line: str) -> bool:
    """A .gitattributes rule naming one concrete .pdf/.parquet path (what the Hub appends for each LFS upload that
    no pattern covers) - redundant once the *.pdf / *.parquet rules exist."""
    pat = line.split(None, 1)[0] if line.strip() and not line.lstrip().startswith("#") else ""
    return bool(pat) and not any(c in pat for c in "*?[") and pat.lower().endswith((".pdf", ".parquet", ".tar"))


def compact_gitattributes(text: str) -> str:
    """Drop per-file .pdf/.parquet rules, keep every other line (default HF patterns, comments, custom rules) and
    make sure the *.pdf and *.parquet LFS rules are present."""
    keep = [ln for ln in text.splitlines() if not _rule_is_per_file(ln)]
    while keep and not keep[-1].strip():
        keep.pop()
    for r in LFS_RULES:
        if r not in (k.strip() for k in keep):
            keep.append(r)
    return "\n".join(keep) + "\n"


def ensure_gitattributes(api, repo: str, max_bytes: int = GITATTR_MAX_BYTES) -> Optional[str]:
    """Pre-commit guard. If the Hub .gitattributes lacks the *.pdf rule (the Hub would then append one line per
    uploaded PDF) or is over max_bytes, log a warning and commit the compacted file. Returns the commit oid or None."""
    from huggingface_hub import CommitOperationAdd
    try:
        info = api.get_paths_info(repo, [".gitattributes"], repo_type="dataset", expand=False)
        size = info[0].size if info else 0
        with tempfile.TemporaryDirectory() as td:
            f = api.hf_hub_download(repo_id=repo, filename=".gitattributes", repo_type="dataset",
                                    local_dir=td) if info else None
            text = Path(f).read_text() if f else ""
    except Exception as e:  # noqa: BLE001
        log(f"gitattributes guard: check failed ({e!r}); continuing")
        return None
    new = compact_gitattributes(text)
    if size <= max_bytes and all(r in text.splitlines() for r in LFS_RULES):
        return None
    log(f"WARNING gitattributes guard: .gitattributes is {size} bytes ({len(text.splitlines())} lines); "
        f"compacting to {len(new)} bytes")
    try:
        ci = api.create_commit(repo_id=repo, repo_type="dataset", commit_message="Compact .gitattributes (guard)",
                               operations=[CommitOperationAdd(".gitattributes", new.encode())])
    except Exception as e:  # noqa: BLE001  (e.g. storage quota): not fatal, the batch commit decides
        log(f"gitattributes guard: commit failed ({e!r}); continuing")
        return None
    return getattr(ci, "oid", None)


def upload_and_verify(api, repo: str, batch: str, items: List[Dict[str, Any]], ledger_path: Path,
                      ledger: Dict[str, Dict[str, Any]], max_bytes: int, max_files: int,
                      commit_timeout: float = COMMIT_TIMEOUT_S) -> Dict[str, Any]:
    from huggingface_hub import CommitOperationAdd
    res: Dict[str, Any] = {"commits": [], "verified": 0, "failed": []}
    chunks = chunk(items, max_bytes, max_files)
    for n, ch in enumerate(chunks, 1):
        ops = [CommitOperationAdd(path_in_repo=it["path_in_repo"], path_or_fileobj=str(it["local"])) for it in ch]
        msg = f"pdfs {batch} part {n}/{len(chunks)}: {len(ch)} files, {sum(i['bytes'] for i in ch) / 1e9:.2f} GB"
        log(msg)
        ci = None
        for attempt in range(3):
            try:
                ci = timed_commit(api, commit_timeout, repo_id=repo, repo_type="dataset", operations=ops,
                                  commit_message=msg)
                break
            except Exception as e:  # noqa: BLE001
                log(f"commit attempt {attempt + 1} failed: {e!r}")
                time.sleep(30 * (attempt + 1))
        oid = getattr(ci, "oid", None) if ci is not None else None
        hub = hub_sha256(api, repo, [it["path_in_repo"] for it in ch],
                         local={it["path_in_repo"]: it["local"] for it in ch})
        if oid:
            res["commits"].append(oid)
        for it in ch:
            ok = hub.get(it["path_in_repo"]) == it["sha256"]
            append_jsonl(ledger_path, {"ts": utc_now(), "batch": batch, "doc_id": it["rec"]["doc_id"],
                                       "place_key": it["rec"]["place_key"], "country_code": it["rec"]["country_code"],
                                       "sha256": it["sha256"], "bytes": it["bytes"],
                                       "path_in_repo": it["path_in_repo"], "commit": oid, "verified": ok,
                                       "hub_sha256": hub.get(it["path_in_repo"])})
            if ok:
                ledger[it["path_in_repo"]] = {"sha256": it["sha256"], "commit": oid}
                it["commit"] = oid
                res["verified"] += 1
            else:
                res["failed"].append(it)
    return res


def _commit_with_retries(api, repo: str, ops, msg: str, commit_timeout: float):
    for attempt in range(3):
        try:
            return timed_commit(api, commit_timeout, repo_id=repo, repo_type="dataset", operations=ops,
                                commit_message=msg)
        except Exception as e:  # noqa: BLE001
            log(f"commit attempt {attempt + 1} failed: {e!r}")
            time.sleep(30 * (attempt + 1))
    return None


def upload_shards(api, repo: str, batch: str, items: List[Dict[str, Any]], stage: Path, state: Path,
                  ledger_path: Path, ledger: Dict[str, Dict[str, Any]], max_bytes: int,
                  commit_timeout: float = COMMIT_TIMEOUT_S, ym: Optional[str] = None) -> Dict[str, Any]:
    """Tar-shard mode: reserve per-country shard names (stable across retries), build the tars under
    staging/pdf/_shards/<batch>/ one commit-chunk at a time, commit, verify each shard's sha256 on the Hub, ledger
    one row per member. Shards that already landed (a commit that timed out client-side but completed) are
    accepted from the recorded build index without re-uploading. Local tars are always removed afterwards."""
    from huggingface_hub import CommitOperationAdd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pdf_shards as PS  # noqa: E402
    res: Dict[str, Any] = {"commits": [], "verified": 0, "failed": [], "shards": []}
    ym = ym or datetime.now(timezone.utc).strftime("%Y/%m")
    plans = PS.reserve(state, batch, items, ym)
    by_key = {(str(i["cc"]).upper(), i["sha256"]): i for i in items}

    def finalize(p, info, oid):
        for e in info["index"]:
            it = by_key.get((p["cc"], e["sha256"]))
            pk = e["member"].split("/", 1)[0]
            append_jsonl(ledger_path, {"ts": utc_now(), "batch": batch, "doc_id": it["rec"]["doc_id"] if it else None,
                                       "place_key": pk, "country_code": p["cc"], "sha256": e["sha256"],
                                       "bytes": e["size"], "path_in_repo": p["shard_path"], "member": e["member"],
                                       "offset": e["offset"], "size": e["size"], "shard_sha256": info["sha256"],
                                       "commit": oid, "verified": True})
            key = ledger_key(p["shard_path"], e["member"])
            ledger[key] = {"sha256": e["sha256"], "commit": oid, "shard": p["shard_path"], "member": e["member"],
                           "offset": e["offset"], "size": e["size"]}
            if it is not None:
                attach_ref(it, key, ledger)
                it["commit"] = oid
                res["verified"] += 1
        res["shards"].append(p["shard_path"])

    work = []
    for p in plans:
        mem = [m for m in p["members"] if (p["cc"], m["sha256"]) in by_key]
        if mem:
            work.append((p, mem))
    landed = [p for p, _ in work if p.get("built")]
    if landed:
        hub = hub_sha256(api, repo, [p["shard_path"] for p in landed])
        for p in landed:
            if hub.get(p["shard_path"]) == p["built"]["sha256"]:
                log(f"{p['shard_path']} already on the Hub (earlier commit landed late): accepted")
                finalize(p, p["built"], p["built"].get("commit"))
        work = [(p, m) for p, m in work if p["shard_path"] not in res["shards"]]
    groups, cur, b = [], [], 0
    for p, mem in work:
        sz = sum(int(by_key[(p["cc"], m["sha256"])]["bytes"]) for m in mem)
        if cur and b + sz > max_bytes:
            groups.append(cur)
            cur, b = [], 0
        cur.append((p, mem))
        b += sz
    if cur:
        groups.append(cur)
    tmpdir = stage / "_shards" / batch
    try:
        for n, grp in enumerate(groups, 1):
            built = []
            for p, mem in grp:
                dest = tmpdir / p["shard_path"]
                info = PS.write_shard(dest, [{**m, "local": by_key[(p["cc"], m["sha256"])]["local"]} for m in mem])
                PS.record_build(state, batch, p["shard_path"], info)
                built.append((p, mem, dest, info))
            ops = [CommitOperationAdd(path_in_repo=p["shard_path"], path_or_fileobj=str(dest)) for p, _, dest, _ in built]
            msg = (f"pdf shards {batch} part {n}/{len(groups)}: {len(built)} shards, "
                   f"{sum(len(m) for _, m, _, _ in built)} PDFs, {sum(i['bytes'] for *_, i in built) / 1e9:.2f} GB")
            log(msg)
            ci = _commit_with_retries(api, repo, ops, msg, commit_timeout)
            oid = getattr(ci, "oid", None) if ci is not None else None
            hub = hub_sha256(api, repo, [p["shard_path"] for p, *_ in built],
                             local={p["shard_path"]: dest for p, _, dest, _ in built})
            if oid:
                res["commits"].append(oid)
            for p, mem, dest, info in built:
                if hub.get(p["shard_path"]) == info["sha256"]:
                    info = {**info, "commit": oid}
                    PS.record_build(state, batch, p["shard_path"], info)
                    finalize(p, info, oid)
                else:
                    for m in mem:
                        it = by_key[(p["cc"], m["sha256"])]
                        append_jsonl(ledger_path, {"ts": utc_now(), "batch": batch, "doc_id": it["rec"]["doc_id"],
                                                   "place_key": it["place_key"], "country_code": p["cc"],
                                                   "sha256": it["sha256"], "bytes": it["bytes"],
                                                   "path_in_repo": p["shard_path"], "member": m["member"],
                                                   "commit": oid, "verified": False,
                                                   "hub_sha256": hub.get(p["shard_path"])})
                        res["failed"].append(it)
                dest.unlink(missing_ok=True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        with __import__("contextlib").suppress(OSError):
            (stage / "_shards").rmdir()
    return res


# ---------------------------------------------------------------------------
# manifest.parquet + pdf_refs
# ---------------------------------------------------------------------------
def manifest_schema():
    import pyarrow as pa
    s = pa.string()
    return pa.schema([(c, pa.int64() if c in MANIFEST_INT_COLUMNS else s) for c in MANIFEST_COLUMNS],
                     metadata={b"schema": b"world_law_scanned_pdfs", b"schema_version": b"1.1.0"})  # 1.1.0: shard_*


def manifest_row(it: Dict[str, Any], batch: str, base: Path) -> Dict[str, Any]:
    r = it["rec"]
    cc, pk = str(r["country_code"]).upper(), r["place_key"]
    pol = ";".join(S.source_policies(r)) or None  # all tags (incl. content_signal*) kept, lower-case
    law_repo, law_path = law_location(base, cc, pk, str(r["doc_id"]))
    return {"doc_id": str(r["doc_id"]), "place_id": r["place_id"], "place_key": pk, "country_code": cc,
            "source_url": r["source_url"], "sha256": it["sha256"], "bytes": int(it["bytes"]),
            "fetched_at": str(r["fetched_at"]), "source_policy": pol, "lane": str(r["lane"]),
            "law_repo": law_repo, "law_path": law_path, "pdf_path": it["path_in_repo"],
            "pdf_ref": item_pdf_ref(it), "batch": batch, "uploaded_at": utc_now(),
            "shard_path": it["path_in_repo"] if it.get("member") else None, "member": it.get("member"),
            "offset": int(it["offset"]) if it.get("member") else None,
            "size": int(it["size"]) if it.get("member") else None}


def item_pdf_ref(it: Dict[str, Any], repo: str = S.PDF_REPO_ID) -> str:
    """Loose: '<repo>:pdfs/...pdf' (unchanged). Shard member: '<repo>:<shard>#member=..&offset=..&size=..&sha256=..'."""
    if it.get("member"):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import pdf_shards as PS  # noqa: E402
        return PS.shard_ref(repo, it["path_in_repo"], it["member"], it["offset"], it["size"], it["sha256"])
    return S.pdf_ref(it["path_in_repo"], repo)


def merge_manifest(local_manifest: Path, new_rows: List[Dict[str, Any]], base: Path, refresh_law: bool = True) -> int:
    """Upsert new rows by (place_id, doc_id) into the local copy of manifest.parquet; rows whose law_repo is null get
    their law_* columns re-resolved (the text row may have been published since)."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if local_manifest.exists():
        t = pq.read_table(str(local_manifest))
        for r in t.to_pylist():
            rows[(r["place_id"], r["doc_id"])] = {c: r.get(c) for c in MANIFEST_COLUMNS}
    for r in new_rows:
        rows[(r["place_id"], r["doc_id"])] = r
    if refresh_law:
        for r in rows.values():
            if r.get("law_repo") is None:
                r["law_repo"], r["law_path"] = law_location(base, r["country_code"], r["place_key"], r["doc_id"])
    out = sorted(rows.values(), key=lambda r: (r["country_code"], r["place_key"], r["doc_id"]))
    t = pa.Table.from_pylist(out, schema=manifest_schema())
    local_manifest.parent.mkdir(parents=True, exist_ok=True)
    tmp = local_manifest.with_name("." + local_manifest.name + ".tmp")
    pq.write_table(t, str(tmp), compression="zstd")
    tmp.replace(local_manifest)
    return t.num_rows


def write_pdf_refs(state: Path, rows: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """state/pdf_refs/<CC>/<place_key>.json {doc_id: pdf_ref}; returns the (cc, place_key) touched."""
    by: Dict[Tuple[str, str], Dict[str, str]] = {}
    for r in rows:
        by.setdefault((r["country_code"], r["place_key"]), {})[r["doc_id"]] = r["pdf_ref"]
    for (cc, pk), refs in by.items():
        p = state / "pdf_refs" / cc / f"{pk}.json"
        cur = json.loads(p.read_text()) if p.exists() else {}
        cur.update(refs)
        atomic_write(p, json.dumps(cur, ensure_ascii=False, sort_keys=True, indent=0) + "\n")
    return sorted(by)


def queue_backfill(state: Path, rows: List[Dict[str, Any]]) -> int:
    """Places whose text rows are already published get queued for a run_loop rebuild (pdf_ref backfill)."""
    q = state / "pdf_backfill_pending.txt"
    have = set(q.read_text().split()) if q.exists() else set()
    new = sorted({f'{r["country_code"]}/{r["place_key"]}' for r in rows if r.get("law_repo")} - have)
    if new:
        with open(q, "a") as f:
            f.write("".join(k + "\n" for k in new))
    return len(new)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def remove_file(p: Path, stage: Path) -> None:
    p.unlink(missing_ok=True)
    d = p.parent
    while d != stage and d.is_dir() and not any(d.iterdir()):
        d.rmdir()
        d = d.parent


def process_batch(api, args, batch: str, ledger: Dict[str, Dict[str, Any]], split_places: set) -> Dict[str, Any]:
    stage, state, base = Path(args.staging), Path(args.state), Path(args.base)
    ledger_path = state / "pdf_ledger.jsonl"
    mode = getattr(args, "shard_mode", None) or "loose"
    if mode not in SHARD_MODES:
        raise SystemExit(f"bad shard mode {mode!r}")
    plan = plan_batch(stage, batch, ledger, split_places, shard_mode=mode)
    log(f"{batch}: {plan['records']} records, upload {len(plan['upload'])}, already {len(plan['already'])}, "
        f"held {len(plan['held'])}, skipped {len(plan['skipped'])}")
    rep: Dict[str, Any] = {"batch": batch, "started_at": utc_now(), "repo": args.repo, "records": plan["records"],
                           "commits": [], "manifest_commit": None, "shard_mode": mode}
    if not args.dry_run and plan["upload"]:
        g = ensure_gitattributes(api, args.repo)
        if g:
            rep["gitattributes_commit"] = g
    if args.dry_run:
        rep.update(dry_run=True, would_upload=len(plan["upload"]),
                   would_upload_bytes=sum(i["bytes"] for i in plan["upload"]))
        return rep
    if not plan["upload"]:
        up = {"commits": [], "verified": 0, "failed": []}
    elif mode == "tar":
        up = upload_shards(api, args.repo, batch, plan["upload"], stage, state, ledger_path, ledger,
                           args.commit_max_bytes, getattr(args, "commit_timeout", COMMIT_TIMEOUT_S))
        rep["shards"] = up.get("shards", [])
    else:
        up = upload_and_verify(api, args.repo, batch, plan["upload"], ledger_path, ledger,
                               args.commit_max_bytes, args.commit_max_files,
                               getattr(args, "commit_timeout", COMMIT_TIMEOUT_S))
    rep["commits"] = up["commits"]
    for i in plan["already"]:            # tar-mode in-batch duplicates follow their twin's shard member
        tw = i.pop("twin", None)
        if tw is not None and tw.get("ledger_key"):
            attach_ref(i, tw["ledger_key"], ledger)
    ok_items = [i for i in plan["upload"] if i not in up["failed"]] + plan["already"]
    # 'already' items need a verified ledger entry (dup_in_batch ones only if their twin verified)
    ok_items = [i for i in ok_items if i.get("ledger_key", i["path_in_repo"]) in ledger]
    rows = [manifest_row(i, batch, base) for i in ok_items]
    local_manifest = state / "pdf_manifest.parquet"
    n_manifest = merge_manifest(local_manifest, rows, base)
    write_pdf_refs(state, rows)
    n_q = queue_backfill(state, rows)
    from huggingface_hub import CommitOperationAdd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pdf_card  # noqa: E402
    ci = api.create_commit(repo_id=args.repo, repo_type="dataset", commit_message=
                           f"manifest: {batch} (+{len(rows)} docs, {n_manifest} total)",
                           operations=[CommitOperationAdd("manifest.parquet", str(local_manifest)),
                                       CommitOperationAdd("README.md", pdf_card.card(local_manifest).encode())])
    rep["manifest_commit"] = getattr(ci, "oid", None)
    # held PDFs: kept locally under held/pdf/ (like held rows), never published
    held_dir = Path(args.held) / "pdf"
    for h in plan["held"]:
        if h["local"].is_file():
            dst = held_dir / h["rel"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(h["local"]), str(dst))
            remove_file(h["local"], stage)
    append_jsonl(held_dir / "_held.jsonl", {"batch": batch, "held": [
        {"doc_id": h["rec"].get("doc_id"), "place_key": h["rec"].get("place_key"), "reason": h["reason"],
         "file": h["rel"]} for h in plan["held"]]}) if plan["held"] else None
    deleted = 0
    rep["recovered_missing"] = sum(1 for i in plan["already"] if i.get("recovered_missing"))
    for i in ok_items:  # only PDFs whose sha256 was verified on the Hub
        if i["local"].exists():
            remove_file(i["local"], stage)
            deleted += 1
    rep.update(finished_at=utc_now(), uploaded=up["verified"], already_on_hub=len(plan["already"]),
               verified=len(ok_items), deleted_local=deleted, manifest_rows_total=n_manifest,
               backfill_queued_places=n_q,
               held=[{"doc_id": h["rec"].get("doc_id"), "reason": h["reason"]} for h in plan["held"]],
               skipped=[{"doc_id": s["doc_id"], "reason": s["reason"]} for s in plan["skipped"]]
               + [{"doc_id": i["rec"]["doc_id"], "reason": "hub_sha256_verify_failed"} for i in up["failed"]])
    if up["failed"]:
        rep["incomplete"] = True  # not marked pushed: retried next run (verified files are skipped)
        atomic_write(stage / "_manifest" / f"{batch}.retry.json", json.dumps(rep, indent=1) + "\n")
    else:
        atomic_write(stage / "_manifest" / f"{batch}.pushed", json.dumps(rep, indent=1) + "\n")
        stale = stage / "_manifest" / f"{batch}.retry.json"
        if stale.exists():
            stale.unlink()  # retry succeeded: drop the old incomplete report
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=str(BASE))
    ap.add_argument("--staging", default=str(BASE / "staging" / "pdf"))
    ap.add_argument("--state", default=str(BASE / "state"))
    ap.add_argument("--held", default=str(BASE / "held"))
    ap.add_argument("--repo", default=PDF_REPO)
    ap.add_argument("--max-batches", type=int, default=0, help="0 = all ready batches")
    ap.add_argument("--commit-max-bytes", type=int, default=COMMIT_MAX_BYTES)
    ap.add_argument("--commit-max-files", type=int, default=COMMIT_MAX_FILES)
    ap.add_argument("--dry-run", action="store_true", help="plan + hash only; no upload, no deletes")
    ap.add_argument("--shard-mode", choices=SHARD_MODES, default=DEFAULT_SHARD_MODE,
                    help="tar (default; env WORLD_LAW_PDF_SHARD_MODE): per-country tar shards; loose: one file per PDF")
    ap.add_argument("--commit-timeout", type=float, default=COMMIT_TIMEOUT_S,
                    help="seconds before one create_commit attempt is abandoned (0 = no timeout)")
    ap.add_argument("--min-mem-gb", type=float, default=MEM_LOW_GB,
                    help="do not start a batch while MemAvailable is below this (exit 3; retried later)")
    ap.add_argument("--refresh-manifest", action="store_true",
                    help="re-resolve law_repo/law_path for unpublished docs and push manifest.parquet + README")
    args = ap.parse_args(argv)
    if args.repo in FORBIDDEN:
        raise SystemExit(f"refusing to write PDFs to {args.repo}")
    state = Path(args.state)
    state.mkdir(parents=True, exist_ok=True)
    lock = open(state / "pdf_upload.lock", "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("another upload_pdfs holds state/pdf_upload.lock; exiting")
        return 0
    started = utc_now()
    write_lock_info(lock, started_at=started, phase="start", argv=list(argv or sys.argv[1:]))
    from huggingface_hub import HfApi
    api = HfApi()
    stage = Path(args.staging)
    batches = ready_batches(stage)
    if args.max_batches:
        batches = batches[: args.max_batches]
    log(f"{len(batches)} ready batch(es) in {stage}")
    ledger = load_ledger(state / "pdf_ledger.jsonl")
    sp_path = state / "pdf_split_places.txt"
    split_places = set(sp_path.read_text().split()) if sp_path.exists() else set()
    reports = []
    mem_low = False
    for b in batches:
        avail = mem_available_gb()
        if avail < args.min_mem_gb:
            log(f"MEM_LOW MemAvailable={avail:.2f}GB < {args.min_mem_gb:g}GB: not starting {b}; retried next run")
            mem_low = True
            break
        write_lock_info(lock, started_at=started, phase="batch", batch=b)
        why = BA.stale_pushed(stage / "_manifest", b)
        if why and not args.dry_run:
            dst = BA.supersede_pushed(stage / "_manifest", b)
            log(f"BATCH_COLLISION {b}: {', '.join(why)}; old .pushed moved to {dst}; re-pushing")
        reports.append(process_batch(api, args, b, ledger, split_places))
        if split_places:
            atomic_write(sp_path, "".join(k + "\n" for k in sorted(split_places)))
        log(json.dumps({k: v for k, v in reports[-1].items() if k not in ("held", "skipped")}))
    if args.refresh_manifest and not args.dry_run and (state / "pdf_manifest.parquet").exists():
        from huggingface_hub import CommitOperationAdd
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import pdf_card  # noqa: E402
        mp = state / "pdf_manifest.parquet"
        before = sha256_file(mp)
        n = merge_manifest(mp, [], Path(args.base))
        if before == sha256_file(mp):
            log("manifest refresh: no change")
        else:
          api.create_commit(repo_id=args.repo, repo_type="dataset", commit_message=f"manifest refresh ({n} docs)",
                          operations=[CommitOperationAdd("manifest.parquet", str(mp)),
                                      CommitOperationAdd("README.md", pdf_card.card(mp).encode())])
    print(json.dumps({"batches": len(reports), "reports": [{k: v for k, v in r.items() if k not in ("held", "skipped")}
                                                           for r in reports]}, indent=1))
    return 3 if mem_low else 0


if __name__ == "__main__":
    sys.exit(main())
