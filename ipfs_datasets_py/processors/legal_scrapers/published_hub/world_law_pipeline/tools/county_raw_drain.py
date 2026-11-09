"""Drain staging/counties/_raw: scans -> staging/pdf/<CC>/<pkey>/ + manifest; text raws verified vs JSONL; delete verified.
Usage: county_raw_drain.py [--limit N] [--dry]"""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, re, json, gzip, hashlib, shutil, subprocess, argparse, datetime
from pathlib import Path
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from schema import place_key
from archive import StagedWriter
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/tools"))
import batch_alloc as BA
ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--dry", action="store_true"); a = ap.parse_args()
W = Path(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law")); RAW = W / "staging/counties/_raw"; PDF = W / "staging/pdf"; MAN = PDF / "_manifest"
LOG = open(W / ("staging/counties/_logs/raw_drain_%s.log" % datetime.datetime.now().strftime("%Y%m%dT%H%M%S")), "w")
def log(*x): print(*x, file=LOG, flush=True)
def free(): return shutil.disk_usage("/workspace").free / 1e9
# index: raw_path -> row meta ; (platform, urlhash10) -> row meta
by_path, by_uh = {}, {}
def files():
    for root in (W / "staging/counties", W / "processed/counties"):
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in ("_raw",)]
            for f in fn:
                if f.endswith(".jsonl") or f.endswith(".jsonl.gz"): yield Path(dp) / f
for f in files():
    if "_archive_provenance" in str(f) or "_archive_rejects" in str(f): continue
    op = gzip.open if f.suffix == ".gz" else open
    with op(f, "rt", errors="replace") as fh:
        for l in fh:
            try: r = json.loads(l)
            except Exception: continue
            m = {k: r.get(k) for k in ("doc_id", "place_id", "country_code", "source_url", "source_policy", "retrieved_at", "gnis", "platform", "source_platform")}
            m["has_text"] = bool((r.get("text") or "").strip() or (r.get("html") or "").strip()); m["file"] = str(f)
            if r.get("raw_path"): by_path[r["raw_path"]] = m
            u = r.get("source_url")
            if u: by_uh[hashlib.sha1(u.encode()).hexdigest()[:10]] = m
from collections import defaultdict
_du = defaultdict(set)
for _m in list(by_path.values()) + list(by_uh.values()): _du[_m["doc_id"]].add(_m["source_url"])
def pdf_doc_id(m):  # scrapers derive doc_id from the URL minus query -> distinct ?did= downloads collide; disambiguate
    return m["doc_id"] + "~" + hashlib.sha1(m["source_url"].encode()).hexdigest()[:8] if len(_du[m["doc_id"]]) > 1 else m["doc_id"]
log("index rows by_path", len(by_path), "by_uh", len(by_uh))
def next_batch():
    n = 272
    for p in MAN.iterdir():
        mm = re.match(r"batch_(\d{4})\.", p.name)
        if mm: n = max(n, int(mm.group(1)))
    return n + 1
st = dict(scan=0, text_ok=0, deleted=0, kept=0, freed=0, staged_new=0); manifest = []; kept = []; todel = []
cnt = 0
for d in sorted(RAW.iterdir()):
    if not d.is_dir(): continue
    for p in sorted(d.iterdir()):
        if not p.is_file() or p.name.endswith(".tmp"): continue
        if a.limit and cnt >= a.limit: break
        if free() < 45: log("STOP disk", free()); break
        cnt += 1
        m = by_path.get(str(p)) or by_uh.get(p.name.split("_", 1)[0])
        if not m: kept.append((str(p), "no_jsonl_row")); continue
        with open(p, "rb") as fh: head = fh.read(1024)
        ispdf = head.lstrip()[:5].startswith(b"%PDF")
        txt = subprocess.run(["pdftotext", "-l", "3", str(p), "-"], capture_output=True).stdout if ispdf else b""
        if ispdf and len(txt.strip()) < 200 and not m["has_text"]:
            txt = subprocess.run(["pdftotext", str(p), "-"], capture_output=True).stdout
        scanned = ispdf and len(txt.strip()) < 200 and not m["has_text"]
        if scanned:
            cc = m["country_code"]; pk = place_key(m["place_id"], m.get("gnis"), cc)
            od = PDF / cc / pk; out = od / (re.sub(r"[:/\\]", "_", pdf_doc_id(m)) + ".pdf")
            h = hashlib.sha256(); n = 0
            if out.exists() or any(x["_out"] == str(out) for x in manifest[-50:]): kept.append((str(p), "pdf_target_exists")); continue
            if not a.dry:
                od.mkdir(parents=True, exist_ok=True); tmp = out.with_name(out.name + ".tmp")
                with open(p, "rb") as src, open(tmp, "wb") as dst:
                    first = True
                    for ch in iter(lambda: src.read(1 << 20), b""):
                        if first: ch = ch.lstrip() if not ch.startswith(b"%PDF-") else ch; first = False
                        h.update(ch); n += len(ch); dst.write(ch)
                    dst.flush(); os.fsync(dst.fileno())
                with open(tmp, "rb") as t:
                    if t.read(5) != b"%PDF-": kept.append((str(p), "bad_magic")); tmp.unlink(); continue
                os.rename(tmp, out)
            manifest.append(dict(doc_id=pdf_doc_id(m), jsonl_doc_id=m["doc_id"], place_id=m["place_id"], place_key=pk, country_code=cc, source_url=m["source_url"],
                                 sha256=h.hexdigest(), bytes=n, fetched_at=m["retrieved_at"],
                                 source_policy=m["source_policy"] if isinstance(m["source_policy"], str) else ";".join(m["source_policy"] or []),
                                 lane="counties", _out=str(out), _raw=str(p)))
            st["scan"] += 1
        elif m["has_text"]:
            st["text_ok"] += 1; todel.append(str(p))
        elif ispdf:
            kept.append((str(p), "text_layer_but_row_has_no_text:" + m["file"]))  # handled below by staging
            m2 = dict(m); m2["_txt_path"] = str(p); m2["_needs_stage"] = True; kept[-1] = (str(p), m2)
        else:
            kept.append((str(p), "not_pdf_no_text"))
# stage rows for text-layer raws whose row lacks text
need = [(k, v) for k, v in kept if isinstance(v, dict)]; kept = [(k, v) for k, v in kept if not isinstance(v, dict)]
for k, m in need:
    src = None
    with (gzip.open if m["file"].endswith(".gz") else open)(m["file"], "rt", errors="replace") as fh:
        for l in fh:
            r = json.loads(l)
            if r.get("doc_id") == m["doc_id"]: src = r; break
    if not src: kept.append((k, "row_vanished")); continue
    src["text"] = subprocess.run(["pdftotext", "-layout", k, "-"], capture_output=True, text=True).stdout
    src.pop("scanned_pdf", None); src.pop("content_complete", None)
    if a.dry: st["staged_new"] += 1; continue
    w = StagedWriter(W / "staging/counties", src["country_code"], src["place_id"], batch_prefix=(src.get("platform") or "county") + "-rawdrain", chunk=500)
    e = w.add(src)
    if e: kept.append((k, "invalid:" + e)); continue
    w.flush(); st["staged_new"] += 1; todel.append(k)
# manifests (500 per batch), collision check right before each write
mfiles = []
for i in range(0, len(manifest), 500):
    if a.dry: break
    chunk = []
    for r in manifest[i:i + 500]:  # verify BEFORE .ready: pdf uploader consumes and deletes local pdfs within seconds
        o = Path(r["_out"])
        if o.exists() and o.stat().st_size == r["bytes"] and open(o, "rb").read(5) == b"%PDF-": chunk.append(r); todel.append(r["_raw"])
        else: kept.append((r["_raw"], "staged_pdf_verify_failed"))
    if not chunk: continue
    n = BA.write_batch(MAN, [{k: v for k, v in r.items() if not k.startswith("_")} for r in chunk], floor=272)  # atomic (batch_alloc)
    mfiles.append(n); log("manifest", n, len(chunk))
for k in todel:
    if a.dry: break
    sz = os.path.getsize(k); os.unlink(k); st["deleted"] += 1; st["freed"] += sz
st["kept"] = len(kept); st["freed_gb"] = round(st.pop("freed") / 1e9, 3); st["batches"] = mfiles; st["examined"] = cnt; st["free_gb_end"] = round(free(), 1)
for k, v in kept: log("KEPT", k, v)
log("SUMMARY", json.dumps(st)); print(json.dumps(st)); print("log:", LOG.name)
