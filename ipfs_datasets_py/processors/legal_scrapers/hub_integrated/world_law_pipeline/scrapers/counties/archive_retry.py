"""Retry archive-only fetches for robots-disallowed PDFs, honoring ArchiveDeferred.not_before.
Usage: archive_retry.py <config.json> [max_minutes]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, json, time, re, hashlib, datetime, subprocess, os
from pathlib import Path
from urllib.parse import unquote
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline"))
from archive import ArchiveFetcher, ArchiveDeferred, ArchiveError, StagedWriter, provenance_fields
_H = Path(__file__).parent; _argv = sys.argv[:]; sys.argv = ["x", str(_H / "_dummy_cfg.json")]
_ns = {}; exec(open(_H / "us_pdf_list.py").read().split("w = StagedWriter")[0], _ns); sys.argv = _argv
live_robots = _ns["robots"]   # RFC 9309 status for the live URL
cfg = json.load(open(sys.argv[1])); deadline = time.time() + 60 * float(sys.argv[2] if len(sys.argv) > 2 else 30)
sys.path.insert(0, str(_H)); from county_pdfstage import text_of, ScanStager; from schema import validate_record; ss = ScanStager()  # 2026-10-21: no _raw
import glob
_pk = cfg["place_id"].replace(":", "_"); _got = set()
import gzip  # 2026-10-27: also dedupe against processed/*.jsonl.gz (emit_staged moves flushed batches there; the plain-.jsonl glob made pass 5 redo everything)
for _f in glob.glob(f'~/.ipfs_datasets/world_law/*/counties/{cfg.get("country_code","US")}/*{_pk.split("_",1)[1]}.*.jsonl') + glob.glob(f'~/.ipfs_datasets/world_law/*/counties/{cfg.get("country_code","US")}/*{_pk.split("_",1)[1]}.*.jsonl.gz'):
    try:
        for l in (gzip.open(_f, "rt", encoding="utf-8") if _f.endswith(".gz") else open(_f)):
            try: _got.add(json.loads(l).get("source_url"))
            except Exception: pass
    except Exception: pass
fx = ArchiveFetcher(cc_crawls=8); todo = [u for u in cfg["urls"] if u not in _got]; print("todo", len(todo), "already", len(cfg["urls"]) - len(todo), flush=True); done = {}; miss = {}
w = StagedWriter((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/counties"), cfg.get("country_code", "US"), cfg["place_id"], batch_prefix=cfg["platform"] + "-archive", chunk=500)
now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
_stop = os.environ.get('ARCHIVE_RETRY_STOPFILE')  # 2026-10-26: chain disk guard touches this file -> finish current URL, flush, exit
import signal as _sig; _term = []  # 2026-11-03: SIGTERM (e.g. `timeout 3300`) -> finish current URL, then the normal flush below seals
_sig.signal(_sig.SIGTERM, lambda *_: _term.append(1))  # the scan manifest (batch_NNNN.jsonl + .ready); before, a kill left PDFs with no .ready
while todo and time.time() < deadline and not _term and not (_stop and os.path.exists(_stop)):
    u = todo.pop(0)
    try:
        d = fx.fetch_newest(u)
        if d is None: raise ArchiveError("no capture in CC or Wayback")
        data = d.body
    except ArchiveDeferred as e:
        todo.append(u); time.sleep(max(5, min(300, e.retry_in or 60))); continue
    except ArchiveError as e:
        miss[u] = str(e)[:200]; print("MISS", u, miss[u], flush=True); continue
    from county_pdfstage import sniff as _sniff  # 2026-10-21 followup
    if _sniff(data, u) != "pdf": miss[u] = "not_pdf:" + _sniff(data, u); print("SKIP_NOTPDF", miss[u], u, flush=True); continue
    _rb = live_robots(u)
    _pol = "archived_robots_disallowed" if _rb == "robots_disallowed" else ("archived_robots_unreachable" if _rb == "robots_unreachable" else cfg.get("archive_policy", "archived_live_fetch_failed"))
    name = unquote(u.split("/")[-1].split("?")[0])
    txt = text_of(data)
    rec = {"place_id": cfg["place_id"], "country_code": cfg.get("country_code", "US"), "gnis": cfg.get("gnis"),
           "doc_id": cfg["platform"] + ":" + hashlib.sha1(u.split("?")[0].encode()).hexdigest()[:16] + (("~" + hashlib.sha1(u.encode()).hexdigest()[:8]) if "?" in u else ""),  # 2026-10-23: URL-hash suffix for query-string URLs (same rule as us_pdf_list/county_pdfstage; WUG timm/download.php?file=)
           "source_platform": cfg["platform"], "source_url": u, "doc_type": cfg.get("doc_type", "regulation"), "language": cfg.get("language", "en"),
           "title_native": cfg.get("titles", {}).get(u) or re.sub(r"[_-]+", " ", name[:-4]).strip(), "consolidated": cfg.get("consolidated", True), "content_format": "pdf_text", "retrieved_at": now,
           "source_policy": _pol, "source_official": True, "source_org": cfg["source_org"],
           "place_name": cfg["place_name"], "qid": cfg.get("qid"), "admin_level": cfg.get("admin_level", "county"), "iso_3166_2": cfg.get("iso_3166_2"), "state_code": cfg.get("state_code"), **provenance_fields(d)}
    if len(txt.strip()) < 200:
        rec.update(content_complete=False, scanned_pdf=True)
        if not validate_record(rec): rec["pdf_path"] = ss.add(data, rec, now)
    else: rec["text"] = txt
    e = w.add(rec); print("OK" if not e else "INVALID " + e, d.provenance().get("archive_source"), u, flush=True)
print("written:", w.flush(), "scan_batches", [ss.flush()] + ss.batches, "staged", len(cfg["urls"]) - len(todo) - len(miss), "miss", len(miss), "still_deferred", len(todo))
