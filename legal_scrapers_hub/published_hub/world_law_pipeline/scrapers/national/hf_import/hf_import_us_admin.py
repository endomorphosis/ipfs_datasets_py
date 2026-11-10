#!/usr/bin/env python3
"""READ-ONLY import of US state administrative rules from HF into staging/national/US/ (sibling of hf_import_us.py).
  admin  justicedao/ipfs_state_admin_rules
         releases/canonical_merged_daemon_cycle_0999_20260325_234135_cleaned/state_admin_rules_cid/STATE-XX.parquet
         -> iso:US-XX (adm1), doc_type "regulation" (rows the source itself tags legislation_type=statute -> "code_section").
Skips *_embeddings.parquet, the all_states aggregates (per-state files exist for every state), anything else in the repo
(OR/ jsonld/knowledge-graph dumps, US_ADMINISTRATIVE_RULES/ mirror) and any Federal Register files.
doc_id = ipfs_cid. Dedupe: within this import by doc_id, source_url and (place_id, sha1(text)); against the earlier
US statute/USC imports by reading state/US.done_ids READ-ONLY (matched on ipfs_cid/source_id). Empty-text rows skipped.
Resumable per file: state/US_admin.json + state/US_admin.done_ids (US.done_ids is never written).
Usage: hf_import_us_admin.py [--source release|parsed] [XX ...]
  --source release (default, unchanged): the releases/canonical_merged_daemon_cycle_0999_.../ set above.
  --source parsed: the larger/newer US_ADMINISTRATIVE_RULES/parsed/parquet/state_admin_rules_cid/STATE-XX.parquet set
                   (same skips; stats under stats["admin_parsed"]; same US_admin.json/US_admin.done_ids/text_hashes so
                   anything staged by the release pass is deduped by ipfs_cid and by (place_id, normalized-text sha1)).
"""
import hashlib, json, os, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hf_import as H
from hf_import import log, check_disk, STATE, CACHE
import hf_import_us as U
from hf_import_us import nn
import pyarrow.parquet as pq
from huggingface_hub import HfApi, hf_hub_download

DS = "justicedao/ipfs_state_admin_rules"
REL = "releases/canonical_merged_daemon_cycle_0999_20260325_234135_cleaned/state_admin_rules_cid/"
REL_PARSED = "US_ADMINISTRATIVE_RULES/parsed/parquet/state_admin_rules_cid/"
SOURCES = {"release": (REL, "admin"), "parsed": (REL_PARSED, "admin_parsed")}
FILE_RE = re.compile(re.escape(REL) + r"STATE-[A-Z]{2}\.parquet$")
WB_RE = re.compile(r"^https?://web\.archive\.org/web/(\d{14})[a-z_]*/(https?://.+)$")

class WA(U.W):
    """U.W writer with its own done_ids file; US.done_ids only read for cross-import dedupe."""
    def __init__(self):
        super().__init__("admin")
        prior = self.done; prior.discard("")
        self.prior = prior
        self.idf = STATE / "US_admin.done_ids"
        self.done = set(self.idf.read_text().split("\n")) - {""} if self.idf.exists() else set()
        self.texts = set(self.st.get("text_hashes", []))
    def save(self):
        self.st["text_hashes"] = sorted(self.texts); super().save()
    def add_admin(self, rec, keys, th, stats):  # th = "place_id|sha1(normalized text)"
        if any(k and k in self.prior for k in keys):
            stats["dupes_prior_us_import"] = stats.get("dupes_prior_us_import", 0) + 1; return
        if th in self.texts:
            stats["dupes"] = stats.get("dupes", 0) + 1; stats["dupes_text"] = stats.get("dupes_text", 0) + 1; return
        before = stats.get("dupes", 0)
        r = self.add(rec, stats)          # doc_id / source_url / existing-staged dedupe + buffered flush
        if stats.get("dupes", 0) == before: self.texts.add(th)
        return r

def first_line(t):
    for ln in t.splitlines():
        ln = ln.strip()
        if len(ln) >= 4 and ln.lower() not in ("message", "loading..", "×"): return ln[:300]
    return None

def admin_rec(r, sha, sc, rel=REL):
    text = nn(r.get("text"))
    if not text or not text.strip(): return None
    j = {}
    try: j = json.loads(r.get("jsonld") or "{}") or {}
    except Exception: pass
    lt_raw = nn(r.get("legislation_type"))
    lt = (lt_raw or "StateAdministrativeRule").strip()
    is_statute = lt.lower() == "statute"
    url = nn(r.get("source_url"))
    if not (url and url.startswith("http")): url = f"https://huggingface.co/datasets/{DS}"
    num = nn(r.get("identifier")) or nn(j.get("official_cite"))
    title = " ".join(x for x in (nn(r.get("identifier")), nn(r.get("name"))) if x) or nn(j.get("title")) \
        or nn(j.get("description")) or nn(j.get("official_cite")) or first_line(text)
    desc = nn(j.get("description")) if isinstance(j.get("description"), str) else None
    rec = {"place_id": f"iso:US-{sc}", "country_code": "US", "doc_id": r.get("ipfs_cid"),
           "source_platform": f"us_{sc.lower()}_admin_rules", "source_url": url,
           "doc_type": "code_section" if is_statute else "regulation", "language": "en",
           "title_native": title[:1000] if title else None, "number": num,
           "in_force": None, "consolidated": True, "content_format": "html", "text": text,
           "place_name": sc, "iso_3166_2": f"US-{sc}", "state_code": sc, "admin_level": "adm1",
           "platform": f"us_{sc.lower()}_admin_rules",
           "source": f"hf:{DS}", "source_revision": sha, "hf_dataset": DS, "hf_path": f"{rel}STATE-{sc}.parquet",
           "hf_ipfs_cid": r.get("ipfs_cid"), "hf_source_id": nn(r.get("source_id")),
           "legislation_type": lt if lt_raw else "untyped_agentic_web_capture",
           "legal_category": "statute" if is_statute else "administrative_rule",
           "hf_description": desc[:1000] if desc else None,
           "hf_fetched_at": nn(j.get("fetched_at")), "hf_capture_source": nn(j.get("source")),
           "source_official": None}
    m = WB_RE.match(url)
    if m:
        rec.update({"archive_source": "wayback", "archive_url": url, "archive_timestamp": m.group(1), "original_url": m.group(2)})
    return {k: v for k, v in rec.items() if v is not None}

def run(only, source="release"):
    rel, skey = SOURCES[source]; file_re = re.compile(re.escape(rel) + r"STATE-[A-Z]{2}\.parquet$")
    api = HfApi(); info = api.dataset_info(DS, files_metadata=True); sha = info.sha
    allf = [s.rfilename for s in info.siblings]
    files = sorted(f for f in allf if file_re.match(f))
    assert not any(re.search(r"embedding|all_states|feder", f, re.I) for f in files)
    if only: files = [f for f in files if f[-10:-8] in only]
    log("US admin", source, DS, sha, len(files), "per-state files")
    w = WA(); w.st["dataset"] = DS; w.st["sha"] = sha
    stats = w.st["stats"].setdefault(skey, {})
    for f in files:
        fs = w.st["files"].setdefault(f, {"done": False, "rows": 0})
        if fs["done"]: continue
        check_disk(); p = hf_hub_download(DS, f, repo_type="dataset", revision=sha, cache_dir=str(CACHE))
        pf = pq.ParquetFile(p); sc = f[-10:-8]; n = 0
        log("US admin", f, pf.metadata.num_rows, "rows")
        for b in pf.iter_batches(batch_size=200):
            for r in b.to_pylist():
                n += 1
                if n <= fs["rows"]: continue
                stats["rows_read"] = stats.get("rows_read", 0) + 1
                if nn(r.get("state_code")) and r["state_code"] != sc: log("US admin state_code mismatch", f, r["state_code"])
                rec = admin_rec(r, sha, sc, rel)
                if rec is None: stats["empty"] = stats.get("empty", 0) + 1; continue
                th = hashlib.sha1(re.sub(r"\s+", " ", rec["text"]).strip().encode()).hexdigest()
                if w.add_admin(rec, (r["ipfs_cid"], nn(r.get("source_id"))), f"{rec['place_id']}|{th}", stats):
                    fs["rows"] = n; w.save()
        fs["done"] = True; fs["rows"] = n; w.flush(stats); w.save(); del pf
        try:  # delete this parquet's cached blob (symlink target) + link
            real = os.path.realpath(p); os.remove(p); os.remove(real)
        except OSError as e: log("US admin cache cleanup", e)
    w.flush(stats); w.save()
    log("US admin DONE", source, json.dumps(stats)[:3000])

if __name__ == "__main__":
    a = sys.argv[1:]; source = "release"
    if "--source" in a:
        i = a.index("--source"); source = a[i + 1]; del a[i:i + 2]
    if source not in SOURCES: sys.exit(f"unknown --source {source!r}; choose from {sorted(SOURCES)}")
    run(set(x.upper() for x in a), source)
