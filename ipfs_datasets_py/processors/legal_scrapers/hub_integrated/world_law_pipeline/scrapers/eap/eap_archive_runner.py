"""eap archive runner (rebuilt 2026-10-18 after instance move). Stages: elis, tw, nz, pac, mo, th.
usage: eap_archive_runner.py <stage>[,<stage>...]
Code: pipeline/scrapers/eap/ (durable). Work/checkpoints: staging/eap/_eap_work/ (uploader ignores _dirs).
Archive-only via ArchiveFetcher (shared rate limiter, ARCHIVE_LANE=eap). Validated chunks via StagedWriter ->
staging/eap/<CC>/<place_key>.archive-eap-<stage>-<UTC>pNNNN.jsonl. Checkpoint arch_ckpt/<stage>.done: a key is
written only after its doc's chunk is flushed. Scanned PDFs: content_complete=false row (no OCR), PDF kept in
_eap_work/_pdf/, line appended to the scanned-PDF manifest (skipped if already in state/pdf_ledger.jsonl).
Exit 6 = only deferred items left (429/5xx cool-down): retry at min(not_before) in arch_ckpt/<stage>.retry_at;
Exit 3 = archives unavailable (waiter retries in 30 min); 4 = disk < 35 GB; 5 = RSS > 480 MB."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, re, json, time, html as H, hashlib, subprocess, tempfile, shutil, resource, csv, datetime
os.environ.setdefault("ARCHIVE_LANE", "eap")
if os.environ["ARCHIVE_LANE"] != "eap": os.environ["ARCHIVE_LANE"] = "eap"
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from archive import ArchiveFetcher, StagedWriter, provenance_fields
from archive.core import Capture, ArchiveError, ArchiveDeferred, ArchiveTransient
from schema import place_key
STAGE = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eap"); W = f"{STAGE}/_eap_work"; CK = f"{W}/arch_ckpt"
MANS = [(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/eap/_scanned_pdfs_manifest.jsonl"), f"{W}/_scanned_pdfs_manifest.jsonl"]
CAND = (_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv")
os.makedirs(CK, exist_ok=True)
fx = ArchiveFetcher(lane="eap")
def log(*a): print(time.strftime("%F %T"), *a, flush=True)
def guard():
    free = shutil.disk_usage("/workspace").free / 2**30
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    if free < 35: log("STOP disk", round(free, 1), "GB"); sys.exit(4)
    if rss > 480: log("STOP rss", round(rss), "MB"); sys.exit(5)
LED = None
def ledger():
    global LED
    if LED is None:
        LED = (set(), set())
        for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/state/pdf_ledger.jsonl")):
            try: r = json.loads(l)
            except Exception: continue
            LED[0].add((r.get("place_key"), r.get("doc_id"))); LED[1].add(r.get("sha256"))
    return LED
def keep_pdf(cc, pid, doc_id, url, body, policy):
    pk = place_key(pid); sha = hashlib.sha256(body).hexdigest(); led = ledger()
    if (pk, doc_id) in led[0] or sha in led[1]: return None
    d = f"{W}/_pdf/{cc}/{pk}"; os.makedirs(d, exist_ok=True)
    p = f"{d}/{re.sub(r'[:/\\\\]', '_', doc_id)}.pdf"
    with open(p + ".tmp", "wb") as f: f.write(body)
    os.rename(p + ".tmp", p)
    rec = {"doc_id": doc_id, "place_key": pk, "country_code": cc, "source_url": url, "local_path": p, "ocr_done": False,
           "source_policy": policy, "law_file": None, "sha256": sha, "bytes": len(body),
           "fetched_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    for m in MANS:
        os.makedirs(os.path.dirname(m), exist_ok=True)
        with open(m, "a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return p
def pdf_text(body):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(body); f.flush()
        try: return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True, timeout=120).stdout
        except Exception: return ""
def strip(h):
    h = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", h)
    t = H.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", h)))
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t\xa0]+", " ", t)).strip()
class Run:
    def __init__(s, name):
        s.name = name; s.ckf = f"{CK}/{name}.done"
        s.done = set(open(s.ckf).read().split("\n")) if os.path.exists(s.ckf) else set()
        s.dff = f"{CK}/{name}.deferred.json"
        s.deferred = json.load(open(s.dff)) if os.path.exists(s.dff) else {}
        s.ck = open(s.ckf, "a"); s.writers = {}; s.n = 0; s.scan = 0; s.fails = 0; s.pending = []; s.since = 0
    def due(s, k):
        """False if k is deferred and its not_before is still in the future (skip this pass)."""
        nb = s.deferred.get(k)
        return nb is None or nb <= time.time()
    def defer(s, k, nb):
        s.deferred[k] = max(float(nb or 0), time.time() + 5); s.save_deferred()
    def save_deferred(s):
        with open(s.dff + ".tmp", "w") as f: json.dump(s.deferred, f)
        os.replace(s.dff + ".tmp", s.dff)
    def mark(s, k):
        if k in s.deferred: s.deferred.pop(k); s.save_deferred()
        s.done.add(k); s.pending.append(k)
        if s.since >= 25 or not any(w.buf for w in s.writers.values()): s.commit()
    def commit(s):
        for w in s.writers.values():
            if w.buf: guard(); w.flush()
        for k in s.pending: s.ck.write(k + "\n")
        s.ck.flush(); os.fsync(s.ck.fileno()); s.pending = []; s.since = 0
    def add(s, cc, rec):
        w = s.writers.get(rec["place_id"])
        if not w: w = s.writers[rec["place_id"]] = StagedWriter(STAGE, cc, rec["place_id"], batch_prefix=f"archive-eap-{s.name}-", chunk=50)
        guard(); e = w.add(rec)
        if e: log("invalid", rec.get("doc_id"), e); return False
        s.n += 1; s.since += 1; return True
    def close(s):
        s.commit(); s.save_deferred()
        live = {k: v for k, v in s.deferred.items() if k not in s.done}
        if live:
            nb = min(live.values()); open(f"{CK}/{s.name}.retry_at", "w").write(str(nb))
            log(s.name, "deferred items left", len(live), "retry at", time.strftime("%F %T", time.localtime(nb)))
        json.dump({"stage": s.name, "deferred": len(live), "docs": s.n, "scanned": s.scan, "places": len(s.writers), "updated": time.strftime("%F %T")},
                  open(f"{CK}/{s.name}.status.json", "w"))
RUNSTATE = {"down": 0}
class Deferred(Exception):
    def __init__(s, nb): s.nb = nb
def fetch(cap, validator=None):
    """One capture. Returns doc, or None = genuine miss (caller records it, no retry).
    ArchiveDeferred (429/5xx cool-down) -> Deferred(not_before); other ArchiveTransient (timeout/breaker) ->
    Deferred(now+600) so the item is requeued; 5 transients in a row -> exit 3 (breaker/archives down)."""
    try:
        d = fx.fetch_capture(cap)
    except ArchiveDeferred as e: raise Deferred(e.not_before)
    except ArchiveTransient as e:
        RUNSTATE["down"] += 1
        if RUNSTATE["down"] >= 5: log("archives unavailable; exit 3", e); sys.exit(3)
        raise Deferred(time.time() + 600)
    except ArchiveError: return None
    except Exception: return None
    RUNSTATE["down"] = 0
    return d if d is not None and (validator is None or validator(d)) else None
def miss(r, key, why="miss"):
    """record a genuine miss (never retried)"""
    r.fails += 1
    with open(f"{CK}/{r.name}.miss", "a") as f: f.write(f"{key}\t{why}\n")
    r.mark(key)
def exit_deferred(stage, nb, why=""):
    for f in {stage, "run"}: open(f"{CK}/{f}.retry_at", "w").write(str(nb))
    log(stage, "deferred", why, "retry at", time.strftime("%F %T", time.localtime(nb))); sys.exit(6)
def capobj(c): return c if isinstance(c, Capture) else Capture(**c)
# ---------- place data (candidate CSV + Wikidata labels/P131 cache) ----------
def wd_cache():
    p = f"{W}/wd_kr_tw_nz.json"
    if not os.path.exists(p): subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "wd_labels.py")], check=True)
    return json.load(open(p))
# ---------- ELIS ----------
CTPV_ISO = {"41": "KR-41", "42": "KR-42", "51": "KR-42", "43": "KR-43", "44": "KR-44", "45": "KR-45", "52": "KR-45",
            "46": "KR-46", "47": "KR-47", "48": "KR-48", "50": "KR-49", "49": "KR-49"}
METRO = {"11": "서울특별시", "26": "부산광역시", "27": "대구광역시", "28": "인천광역시", "29": "광주광역시", "30": "대전광역시", "31": "울산광역시", "36": "세종특별자치시"}
PROV = {"41": "경기도", "42": "강원", "51": "강원", "43": "충청북도", "44": "충청남도", "45": "전라북도", "52": "전북", "46": "전라남도", "47": "경상북도", "48": "경상남도", "50": "제주", "49": "제주"}
CTPV_PAR = {"11": {"Q8684"}, "26": {"Q16520"}, "27": {"Q20927"}, "28": {"Q20934"}, "29": {"Q41283", "Q138870299"}, "30": {"Q20921"},
            "31": {"Q41278"}, "41": {"Q20937"}, "42": {"Q41071"}, "51": {"Q41071"}, "43": {"Q41066"}, "44": {"Q41070"}, "45": {"Q41157"},
            "52": {"Q41157"}, "46": {"Q41161", "Q138870299"}, "47": {"Q41154"}, "48": {"Q41151"}, "49": {"Q41164"}, "50": {"Q41164"}}
def kr_index():
    wd = wd_cache(); idx = {}
    for q, v in wd.items():
        if v["cc"] != "KR": continue
        for l in v["labels"]:
            if re.search(r"[가-힣]", l): idx.setdefault(l.replace(" ", ""), set()).add(q)
    return wd, idx
def elis_place(title, ctpv, sgg, wd, idx):
    if not sgg or sgg == "000":
        if ctpv in METRO:
            nm = METRO[ctpv]; qs = idx.get(nm, set()) | idx.get(nm[:2], set())
            qs = {q for q in qs if wd[q]["admin_level"] == "municipality"}
            if len(qs) == 1: q = qs.pop(); return wd[q]["place_id"], wd[q]["place_name"], q
        if ctpv in CTPV_ISO: return "iso:" + CTPV_ISO[ctpv], PROV.get(ctpv), None
        return None
    toks = title.split()
    prov = METRO.get(ctpv) or PROV.get(ctpv) or ""
    labs = sorted((l for l in idx if l.endswith(("시", "군", "구"))), key=len, reverse=True)
    cands = []
    for i in range(min(3, len(toks))):
        t = toks[i]
        if i == 0 and prov and t.startswith(prov[:2]): continue
        if t in idx: cands = list(idx[t]); break
        hit = next((l for l in labs if t.startswith(l) and len(l) >= 2), None)
        if hit: cands = list(idx[hit]); break
    if len(cands) > 1:
        par = CTPV_PAR.get(ctpv, set())
        cands = [q for q in cands if set(wd[q].get("p131", [])) & par]
    if len(cands) == 1: q = cands[0]; return wd[q]["place_id"], wd[q]["place_name"], q
    return None
def elis_caps():
    p = f"{W}/elis_wb_html_caps.json"
    if os.path.exists(p): return json.load(open(p))
    caps = []
    for h in ["www.elis.go.kr/allalr/selectAlrBdtOne", "elis.go.kr/allalr/selectAlrBdtOne"]:
        try: got = fx.wb_captures(h, "prefix", filters=["mimetype:text/html"])
        except ArchiveDeferred as e: exit_deferred("elis", e.not_before, "cdx listing")
        except ArchiveError as e: log("elis cdx fail", e); sys.exit(3)
        if getattr(got, "truncated", False): exit_deferred("elis", got.deferral.not_before if got.deferral else time.time() + 600, "cdx listing truncated")
        caps += got
    out = [c.to_dict() for c in caps]
    json.dump(out, open(p, "w")); return out
def stage_elis():
    r = Run("elis"); wd, idx = kr_index()
    uf = f"{CK}/elis.unmapped"
    if os.path.exists(uf):
        retry = set(open(uf).read().split()); r.done -= retry; os.rename(uf, uf + ".retried." + time.strftime("%Y%m%dT%H%M%S"))
        log("elis retrying unmapped", len(retry))
    caps = [c for c in elis_caps() if "/allalr/selectAlrBdtOne" in c["original_url"] and "alrNo=" in c["original_url"]]
    best = {}
    for c in caps:
        a = re.search(r"alrNo=(\d+)", c["original_url"])[1]; h = (re.search(r"histNo=(\d+)", c["original_url"]) or [None, "000"])[1]
        k = (h, c["timestamp"])
        if a not in best or k > best[a][0]: best[a] = (k, c)
    log("elis alrNo", len(best), "caps", len(caps), "already done", len(set(best) & r.done))
    pol = "archived_robots_disallowed"; basis = "elis.go.kr robots.txt unreachable from box (connect timeout, 2026-10-16) => disallow-all"
    unm = 0
    for a, (k, c) in sorted(best.items()):
        if a in r.done or not r.due(a): continue
        try: d = fetch(capobj(c), validator=lambda d: b"policy-detail" in d.body)
        except Deferred as e: r.defer(a, e.nb); continue
        if not d: miss(r, a); continue
        t = d.text()
        title = H.unescape((re.search(r'<strong class="tit">(.*?)</strong>', t, re.S) or [None, ""])[1]).strip()
        ctpv = (re.search(r'id="ctpvCd"[^>]*value="(\d*)"', t) or [None, ""])[1] or (re.search(r"ctpvCd=(\d+)", c["original_url"]) or [None, ""])[1]
        sgg = (re.search(r'id="sggCd"[^>]*value="(\d*)"', t) or [None, ""])[1] or (re.search(r"sggCd=(\d+)", c["original_url"]) or [None, ""])[1]
        if not ctpv: ctpv = a[:2]
        if not sgg: sgg = a[2:5]
        pl = elis_place(title, ctpv, sgg, wd, idx) if title else None
        if not pl: unm += 1; log("unmapped", a, ctpv, sgg, title[:40]); open(uf, "a").write(a + "\n"); r.mark(a); continue
        pid, pname, q = pl
        m = re.search(r'<div class="policy-detail">(.*?)<!-- ', t, re.S) or re.search(r'<div class="policy-detail">(.*)', t, re.S)
        body = m[1] if m else t
        meta = strip((re.search(r'<p class="txt">(.*?)</p>', body, re.S) or [None, ""])[1])
        eff = re.search(r"시행\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", meta)
        num = re.search(r"((?:조례|규칙|훈령|예규)\s*제\s*\d+호)", meta)
        rec = {"place_id": pid, "country_code": "KR", "doc_id": f"elis:{a}", "source_platform": "kr_elis",
               "source_url": d.provenance().get("original_url") or c["original_url"], "doc_type": "regulation" if title.endswith("규칙") else "ordinance",
               "language": "ko", "title_native": title, "consolidated": True, "content_format": "html",
               "html": body[:2_000_000], "text": strip(body)[:1_000_000], "in_force": None, "hist_no": k[0], "elis_alr_no": a,
               "retrieved_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "source_official": True,
               "place_name": pname, "platform": "kr_elis", "platform_place_id": f"{ctpv}{sgg}", "text_source": "html",
               **provenance_fields(d, pol, basis)}
        if q: rec["qid"] = q
        if pid.startswith("iso:"): rec["iso_3166_2"] = pid[4:]; rec["admin_level"] = "adm1"
        else: rec["admin_level"] = "municipality"
        if eff: rec["effective_date"] = f"{eff[1]}-{int(eff[2]):02d}-{int(eff[3]):02d}"
        if num: rec["number"] = re.sub(r"\s+", " ", num[1])
        r.add("KR", rec); r.mark(a)
        if r.n % 25 == 0: log("elis progress new docs", r.n, "unmapped", unm, "fails", r.fails, "done total", len(set(best) & r.done))
    r.close(); log("ELIS DONE new docs", r.n, "unmapped", unm, "fails", r.fails, "done total", len(set(best) & r.done), "of", len(best))
# ---------- generic ----------
def caps_for(prefix, match="prefix", filters=None, cache=None):
    """Wayback (+ CC) listing. Cached only when complete. Deferred/truncated/transient -> raise Deferred (requeue)."""
    if cache and os.path.exists(cache): return json.load(open(cache))
    try: cs = fx.wb_captures(prefix, match, filters=filters or [])
    except ArchiveDeferred as e: raise Deferred(e.not_before)
    except ArchiveTransient as e:
        RUNSTATE["down"] += 1
        if RUNSTATE["down"] >= 5: log("archives unavailable; exit 3", e); sys.exit(3)
        raise Deferred(time.time() + 600)
    except ArchiveError as e: log("wb cdx error (treated as empty)", prefix, e); cs = []
    if getattr(cs, "truncated", False): raise Deferred(cs.deferral.not_before if cs.deferral else time.time() + 600)
    try:
        cc = fx.cc_captures(prefix, match, on_deferred="flag")
        if getattr(cc, "truncated", False): raise Deferred(cc.deferral.not_before if cc.deferral else time.time() + 600)
        cs = list(cs) + list(cc)
    except Deferred: raise
    except ArchiveDeferred as e: raise Deferred(e.not_before)
    except Exception as e: log("cc listing failed (wayback-only)", prefix, type(e).__name__)
    RUNSTATE["down"] = 0
    seen = {}
    for c in sorted(cs, key=lambda c: c.timestamp, reverse=True): seen.setdefault(c.original_url, c)
    out = [c.to_dict() for c in seen.values() if c.status in (200, None)]
    if cache: json.dump(out, open(cache, "w"))
    return out
def emit_doc(r, cc, pid, pname, q, c, d, pol, basis, platform, doc_type="ordinance", lang="en", title=None, extra=None):
    body = d.body; url = d.provenance().get("original_url") or c["original_url"]
    doc_id = f"{platform}:" + hashlib.sha1(url.lower().encode()).hexdigest()[:16]
    rec = {"place_id": pid, "country_code": cc, "doc_id": doc_id, "source_platform": platform, "source_url": url,
           "doc_type": doc_type, "language": lang, "consolidated": False, "in_force": None, "source_official": True,
           "retrieved_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "place_name": pname,
           "platform": platform, "admin_level": "municipality",
           **(provenance_fields(d, pol, basis) if pol.startswith("archived_") else provenance_fields(d))}
    rec["source_policy"] = pol
    if basis: rec["robots_basis"] = basis
    if q: rec["qid"] = q
    if body[:5] == b"%PDF-":
        txt = pdf_text(body); rec["content_format"] = "pdf_text"
        if len(txt.strip()) < 200:
            rec["content_complete"] = False; rec["text_source"] = "none"; rec["incomplete_reason"] = "scanned PDF, no text layer; OCR deferred to OCR bot"
            rec["text"] = txt.strip() or "(scanned PDF; no text layer)"
            lp = keep_pdf(cc, pid, doc_id, url, body, pol)
            if lp: rec["scanned_pdf_local"] = lp
            r.scan += 1
        else: rec["text"] = txt; rec["text_source"] = "pdf_text"
        rec["title_native"] = title or (next((l.strip() for l in txt.splitlines() if len(l.strip()) > 8), None) or url.rsplit("/", 1)[-1])[:300]
    else:
        t = d.text(); rec["content_format"] = "html"; rec["html"] = t[:2_000_000]; rec["text"] = strip(t)[:1_000_000]; rec["text_source"] = "html"
        rec["title_native"] = title or strip((re.search(r"(?is)<title>(.*?)</title>", t) or [None, url])[1])[:300]
    if extra: rec.update(extra)
    return r.add(cc, rec)
# ---------- TW county GLRS ----------
TW_HOSTS = {"law.chiayi.gov.tw": "嘉義市", "law.hccg.gov.tw": "新竹市", "law.kinmen.gov.tw": "金門縣", "law.matsu.gov.tw": "連江縣",
            "lawsearch.chcg.gov.tw": "彰化縣", "outlaw.kcg.gov.tw": "高雄市"}
TW_POL = {"lawsearch.chcg.gov.tw": ("archived_robots_disallowed", "robots.txt Disallow: / (parsed live 2026-10-16)")}
def tw_key(url):
    from urllib.parse import urlparse
    k = (re.search(r"id=([A-Za-z0-9]+)", url) or [None, url])[1].upper()
    return f"{urlparse(url).netloc.lower().split(':')[0]}|{k}"
def stage_tw():
    r = Run("tw"); wd = wd_cache()
    for host, zh in TW_HOSTS.items():
        qs = [q for q, v in wd.items() if v["cc"] == "TW" and zh in v["labels"]]
        if len(qs) != 1: log("tw no unique qid", host, zh, qs); continue
        q = qs[0]; pid = wd[q]["place_id"]; pname = wd[q]["place_name"]
        pol, basis = TW_POL.get(host, ("robots_404_allow_rfc9309_archive_fallback", None))
        if not r.due(f"list|{host}"): continue
        try: allc = caps_for(host + "/", cache=f"{CK}/tw_{host}.caps.json")
        except Deferred as e: r.defer(f"list|{host}", e.nb); continue
        r.deferred.pop(f"list|{host}", None)
        caps = [c for c in allc if re.search(r"LawContent\.aspx\?id=|LawAll\.aspx|\.pdf$", c["original_url"], re.I)]
        best = {}
        for c in caps:
            k = tw_key(c["original_url"]).split("|", 1)[1]
            if k not in best or c["timestamp"] > best[k]["timestamp"]: best[k] = c
        log("tw", host, "caps", len(caps), "docs", len(best), "done", sum(f"{host}|{k}" in r.done for k in best))
        for k, c in best.items():
            key = f"{host}|{k}"
            if key in r.done or not r.due(key): continue
            try: d = fetch(capobj(c))
            except Deferred as e: r.defer(key, e.nb); continue
            if not d: miss(r, key); continue
            if d.body[:5] == b"%PDF-" or len(d.body) > 1500:
                t = d.text() if d.body[:5] != b"%PDF-" else ""
                title = strip((re.search(r'(?is)id="[^"]*(?:LawName|lawname|hlLawName)[^"]*"[^>]*>(.*?)</', t) or [None, ""])[1]) or None
                emit_doc(r, "TW", pid, pname, q, c, d, pol, basis, "tw_glrs_" + host.split(".")[1], lang="zh-TW", title=title, extra={"glrs_id": k})
            r.mark(key)
            if r.n and r.n % 50 == 0: log("tw progress", r.n)
    r.close(); log("TW DONE docs", r.n, "scanned", r.scan)
# ---------- NZ ----------
def nz_robots(host):
    import requests
    try:
        x = requests.get(f"https://{host}/robots.txt", timeout=20, headers={"User-Agent": "Mozilla/5.0 (compatible; world-law-research-bot; eap lane)"})
        if x.status_code in (404, 410): return "robots_404_allow_rfc9309_archive_fallback", None
        if x.status_code == 200 and "<html" not in x.text[:200].lower(): return "robots_allowed_rfc9309_archive_fallback", None
        return "archived_robots_disallowed", f"robots.txt HTTP {x.status_code} => disallow-all"
    except Exception as e: return "archived_robots_disallowed", f"robots.txt unreachable ({type(e).__name__}) => disallow-all"
def stage_nz():
    r = Run("nz"); wd = wd_cache(); done_hub = set(json.load(open(f"{W}/hub_places_NZ.json")))
    from urllib.parse import urlparse
    for q, v in sorted(wd.items()):
        if v["cc"] != "NZ" or not v.get("source_url"): continue
        if place_key(v["place_id"]) in done_hub: continue
        host = urlparse(v["source_url"]).netloc.lower()
        if not host: continue
        dom = host[4:] if host.startswith("www.") else host
        if f"host|{dom}" in r.done or not r.due(f"list|{dom}"): continue
        try: allc = caps_for(dom, "domain", filters=["original:.*[Bb]ylaw.*\\.[Pp][Dd][Ff].*"], cache=f"{CK}/nz_{dom}.caps.json")
        except Deferred as e: r.defer(f"list|{dom}", e.nb); continue
        r.deferred.pop(f"list|{dom}", None)
        caps = [c for c in allc if re.search(r"bylaw", c["original_url"], re.I) and re.search(r"\.pdf", c["original_url"], re.I)]
        if not caps: r.mark(f"host|{dom}"); continue
        pol, basis = nz_robots(host); log("nz", dom, "pdfs", len(caps), pol)
        held = False
        for c in caps[:400]:
            key = c["original_url"]
            if key in r.done: continue
            if not r.due(key): held = True; continue
            try: d = fetch(capobj(c), validator=lambda d: d.body[:5] == b"%PDF-")
            except Deferred as e: r.defer(key, e.nb); held = True; continue
            if not d: miss(r, key); continue
            emit_doc(r, "NZ", v["place_id"], v["place_name"], q, c, d, pol, basis, "nz_council_bylaws_archive")
            r.mark(key)
        if not held: r.mark(f"host|{dom}")
    r.close(); log("NZ DONE docs", r.n, "scanned", r.scan, "places", len(r.writers))
# ---------- PacLII ----------
PAC_POL = "robots_allowed_rfc9309_archive_fallback;content_signal_ai_train_no"
LOCAL_RE = re.compile(r"by-?law|ordinance|provincial|province|municipal|city council|town council|local government|local-level|council\b", re.I)
def pac_places():
    rows = [x for x in csv.DictReader(open(CAND)) if x["country_code"] in ("PG", "SB", "VU", "WS", "TO")]
    extra = {"PG": [("National Capital District", "Q1378310")], "SB": [("Honiara", "Q1178")], "VU": [("Port Vila", "Q36126"), ("Luganville", "Q645520")]}
    out = {}
    for x in rows:
        nm = re.sub(r"\s+(Province|District|region)$", "", x["place_name"]).strip()
        out.setdefault(x["country_code"], []).append((nm, x["place_id"], x["place_name"], x["qid"]))
    for cc, l in extra.items():
        for nm, q in l: out.setdefault(cc, []).append((nm, "wd:" + q, nm, q))
    return out
def stage_pac():
    r = Run("pac"); P = pac_places()
    for cc in ["pg", "sb", "vu", "ws", "to"]:
        if not r.due(f"list|{cc}"): continue
        try: allc = caps_for(f"www.paclii.org/{cc}/legis/", cache=f"{CK}/pac_{cc}.caps.json")
        except Deferred as e: r.defer(f"list|{cc}", e.nb); continue
        r.deferred.pop(f"list|{cc}", None)
        caps = [c for c in allc if re.search(r"/legis/[^/]+/[^/]+/(index\.html)?$|\.html$|\.pdf$|\.rtf$", c["original_url"])]
        log("pac", cc, "caps", len(caps))
        for c in caps:
            key = c["original_url"]
            if key in r.done or not r.due(key): continue
            slug = key.split("/legis/", 1)[1]
            if not LOCAL_RE.search(slug.replace("_", " ")) and "provincial" not in slug and "pl/" not in slug: r.mark(key); continue
            try: d = fetch(capobj(c))
            except Deferred as e: r.defer(key, e.nb); continue
            if not d: miss(r, key); continue
            t = d.text() if d.body[:5] != b"%PDF-" else ""
            title = strip((re.search(r"(?is)<title>(.*?)</title>", t) or [None, ""])[1]) if t else ""
            hay = title + " " + slug.replace("_", " ")
            if not LOCAL_RE.search(hay): r.mark(key); continue
            pl = next(((pid, pn, q) for nm, pid, pn, q in sorted(P.get(cc.upper(), []), key=lambda z: -len(z[0])) if re.search(r"\b" + re.escape(nm) + r"\b", hay, re.I)), None)
            if not pl: log("pac unmapped", cc, hay[:90]); r.mark(key); continue
            emit_doc(r, cc.upper(), pl[0], pl[1], pl[2], c, d, PAC_POL, None, "paclii_archive", title=title or None)
            r.mark(key)
    r.close(); log("PAC DONE docs", r.n, "scanned", r.scan, "places", len(r.writers))
def stage_disc(name, prefixes):
    stp = f"{CK}/{name}.status.json"
    tot = json.load(open(stp)) if os.path.exists(stp) else {}
    nbs = []
    for p in prefixes:
        if p in tot: continue
        try: cs = caps_for(p, cache=f"{CK}/{name}_{re.sub(r'[^a-z0-9]+', '_', p)}.caps.json")
        except Deferred as e: nbs.append(e.nb); log(name, p, "deferred"); continue
        tot[p] = len(cs); log(name, p, "captures", len(cs))
    json.dump(tot, open(stp, "w"))
    if nbs: exit_deferred(name, min(nbs), "listing")
STAGES = {"elis": stage_elis, "tw": stage_tw, "nz": stage_nz, "pac": stage_pac,
          "mo": lambda: stage_disc("mo", ["bo.io.gov.mo/bo/", "www.io.gov.mo/pt/legis/"]),
          "th": lambda: stage_disc("th", ["ratchakitcha.soc.go.th/DATA/PDF/"])}
def live_deferred(stage):
    p = f"{CK}/{stage}.deferred.json"; d = f"{CK}/{stage}.done"
    if not os.path.exists(p): return {}
    done = set(open(d).read().split("\n")) if os.path.exists(d) else set()
    return {k: v for k, v in json.load(open(p)).items() if k not in done}
if __name__ == "__main__":
    nbs = []
    for s in sys.argv[1].split(","):
        if os.path.exists(f"{CK}/{s}.FINISHED"): log("skip finished", s); continue
        log("START", s); STAGES[s]()
        left = live_deferred(s)
        if left: nbs.append(min(left.values())); log(s, "not finished:", len(left), "deferred"); continue
        open(f"{CK}/{s}.FINISHED", "w").write(time.strftime("%F %T"))
    if nbs: exit_deferred("run", min(nbs), "items")
    log("ALL DONE")
