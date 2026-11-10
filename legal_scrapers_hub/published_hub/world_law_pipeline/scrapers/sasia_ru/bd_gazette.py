"""BD gap work (2026-10-31): Bangladesh Gazette extraordinary issues (www.dpp.gov.bd/bgpress, official, live, robots 404 ->
allow per RFC 9309). Walks get_extraordinary/<id> newest-first, indexes every row (date, title, ministry, pdf) to
_bd/bg_index.jsonl, and for local-body items (পৌরসভা / সিটি কর্পোরেশন / ইউনিয়ন পরিষদ / জেলা পরিষদ / উপজেলা পরিষদ named in the
title) maps the title to a BD Wikidata place via its Bengali label (unique match only), downloads the PDF, extracts text
(pdftotext if it is real Unicode Bengali, else tesseract 'ben' OCR if installed, else queued in _bd/bg_ocr_pending.jsonl)
and stages validated per-place batches to staging/sasia_ru/BD/. Resumable via _bd/bg_done.txt.
Usage: bd_gazette.py [--start-id N] [--min-id N] [--limit N] [--stage]"""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, re, json, time, shutil, argparse, resource, subprocess, tempfile, html as H
from datetime import datetime, timezone
for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','all_proxy'): os.environ.pop(k, None)
os.environ['ARCHIVE_LANE'] = 'sasia_ru'
import requests, pandas as pd
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/web"))
from schema import validate_record, validate_file, place_key
from rfc9309 import Robots
resource.setrlimit(resource.RLIMIT_AS, (2_000_000_000, 2_000_000_000))
UA = "Mozilla/5.0 (compatible; WorldLawMunicipalResearch/1.0)"
BASE = "https://www.dpp.gov.bd"
D = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/sasia_ru/_bd"); RAW = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/sasia_ru/_raw/bd_gazette")
DELAY = 1.5
S = requests.Session(); S.headers["User-Agent"] = UA; S.verify = False
requests.packages.urllib3.disable_warnings()
LOCAL = re.compile(r"পৌরসভা|সিটি\s*কর্পোরেশন|সিটি\s*কর্পোরেশনের|ইউনিয়ন\s*পরিষদ|জেলা\s*পরিষদ|উপজেলা\s*পরিষদ|পৌর\s")
TYPEWORDS = [("municipality", r"পৌরসভা"), ("municipality", r"সিটি\s*কর্পোরেশন"), ("union", r"ইউনিয়ন(?:\s*পরিষদ)?"),
             ("district", r"জেলা(?:\s*পরিষদ)?")]
STRIP = re.compile(r"\s*(পৌরসভা|সিটি কর্পোরেশন|ইউনিয়ন পরিষদ|ইউনিয়ন|জেলা|উপজেলা|সদর|বিভাগ)\s*$")
BN_DIG = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
MON = dict(Jan=1, Feb=2, Mar=3, Apr=4, May=5, Jun=6, Jul=7, Aug=8, Sep=9, Oct=10, Nov=11, Dec=12)
_rb = None
RESPECT_ROBOTS = os.environ.get('RESPECT_ROBOTS', '0') != '0'  # 2026-11-01: default off (user decision; set RESPECT_ROBOTS=1 to restore)
def robots():
    global _rb
    if _rb is None and not RESPECT_ROBOTS: _rb = (Robots(allow_all=True), "robots_not_consulted")
    if _rb is None:
        r = S.get(BASE + "/robots.txt", timeout=(10, 30))
        if r.status_code == 200: _rb = (Robots(r.text), "robots_allowed_rfc9309")
        elif 400 <= r.status_code < 500: _rb = (Robots(allow_all=True), "robots_404_allow_rfc9309")
        else: raise SystemExit(f"robots unreachable {r.status_code}")
    return _rb
def get(url, **kw):
    rb, _ = robots()
    if RESPECT_ROBOTS and not rb.can_fetch(UA, url): return None
    time.sleep(DELAY)
    for i in range(3):
        try: return S.get(url, timeout=(15, 120), **kw)
        except Exception: time.sleep(30 * (i + 1))
    return None
def free_gb(): return shutil.disk_usage('/workspace').free / 1e9
def load_places():
    """Bengali labels for BD candidate places (cached _bd/wd_bd_bn.jsonl from the Wikidata API)."""
    c = pd.read_csv((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + '/global_municipalities_candidate.csv'), low_memory=False)
    c = c[c.country_code == 'BD'][['qid', 'place_name', 'admin_level']]
    cf = f"{D}/wd_bd_bn.jsonl"; have = {}
    if os.path.exists(cf): have = {json.loads(l)['qid']: json.loads(l) for l in open(cf)}
    need = [q for q in c.qid if q not in have]
    with open(cf, 'a') as f:
        for i in range(0, len(need), 50):
            ids = "|".join(need[i:i + 50]); time.sleep(1)
            r = {}
            for t in range(6):
                try: r = requests.get("https://www.wikidata.org/w/api.php", params=dict(action="wbgetentities", ids=ids, props="labels|aliases", languages="bn", format="json", maxlag=5), headers={"User-Agent": UA}, timeout=60).json(); break
                except Exception: time.sleep(20 * (t + 1))
            for q, e in r.get("entities", {}).items():
                rec = {"qid": q, "bn": [e.get("labels", {}).get("bn", {}).get("value")] + [a["value"] for a in e.get("aliases", {}).get("bn", [])]}
                rec["bn"] = [x for x in rec["bn"] if x]; have[q] = rec; f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    anc = parents([q for q, lvl in zip(c.qid, c.admin_level) if lvl in ("municipality", "union", "district")])  # 2026-11-04: district-level (upazila) parents too, for rematch
    P = []
    for q, nm, lvl in c.itertuples(index=False):
        cores = {STRIP.sub("", x).strip() for x in have.get(q, {}).get("bn", [])}
        P.append({"qid": q, "name": nm, "level": lvl, "cores": [x for x in cores if len(x) >= 2], "anc": anc.get(q, [])})
    return P
def wbget(ids, props):
    for t in range(12):  # 2026-11-04: retry on maxlag/API error JSON (previously returned {} silently -> empty caches)
        try:
            time.sleep(1)
            j = requests.get("https://www.wikidata.org/w/api.php", params=dict(action="wbgetentities", ids="|".join(ids), props=props, languages="bn", format="json", **({"maxlag": 5} if t < 3 else {})), headers={"User-Agent": UA}, timeout=60).json()  # WDQS lag can pin maxlag for hours; low-rate reads drop it after 3 tries
            if "error" in j: time.sleep(min(60, 10 * (t + 1))); continue
            return j.get("entities", {})
        except Exception: time.sleep(20 * (t + 1))
    raise RuntimeError("wikidata wbgetentities failed after retries")
def parents(qids, force=False):
    """Bengali labels (core names) of P131 parents up to 2 levels, cached in _bd/wd_bd_anc.jsonl."""
    cf = f"{D}/wd_bd_anc.jsonl"; have = {}
    if os.path.exists(cf): have = {json.loads(l)["qid"]: json.loads(l)["anc"] for l in open(cf)}
    need = [q for q in qids if q not in have or (force and not have[q])]
    if not need: return have
    p131 = {}
    def claims(ids):
        out = {}
        for i in range(0, len(ids), 50):
            for q, e in wbget(ids[i:i + 50], "claims").items():
                out[q] = [c["mainsnak"].get("datavalue", {}).get("value", {}).get("id") for c in e.get("claims", {}).get("P131", [])]
                out[q] = [x for x in out[q] if x]
        return out
    p1 = claims(need); lv2 = sorted({x for v in p1.values() for x in v}); p2 = claims(lv2)
    allp = sorted(set(lv2) | {x for v in p2.values() for x in v}); lab = {}
    for i in range(0, len(allp), 50):
        for q, e in wbget(allp[i:i + 50], "labels").items(): lab[q] = e.get("labels", {}).get("bn", {}).get("value")
    with open(cf, "a") as f:
        for q in need:
            a = [lab.get(x) for x in p1.get(q, [])] + [lab.get(y) for x in p1.get(q, []) for y in p2.get(x, [])]
            a = sorted({STRIP.sub("", x).strip() for x in a if x})
            have[q] = a; f.write(json.dumps({"qid": q, "anc": a}, ensure_ascii=False) + "\n")
    return have
def match(title, P):
    # 2026-11-04 fix: "X জেলার Y পৌরসভা/উপজেলা/ইউনিয়ন" used to map to district X; resolve Y within X (bd_rematch), else unmatched.
    from bd_rematch import rematch
    r = rematch(title, P)
    if r is not None: return {r} if r else set()
    hits = {}
    for lvl, tw in TYPEWORDS:
        for m in re.finditer(r"([\u0980-\u09FF]+(?:[\s\-][\u0980-\u09FF]+)?)\s*" + tw, title):
            pre = m.group(1)
            for p in P:
                if p["level"] != lvl and not (lvl == "municipality" and p["level"] == "municipality"): continue
                for core in p["cores"]:
                    if pre == core or pre.endswith(" " + core) or pre.endswith(core) and len(core) >= 3 and pre[-len(core) - 1:-len(core)] in ("", " ", "-"):
                        hits.setdefault((lvl, m.start()), set()).add(p["qid"])
    PL = {p["qid"]: p for p in P}
    for k, v in list(hits.items()):
        if len(v) > 1:
            f = {q for q in v if any(a and a in title for a in PL[q]["anc"])}
            if len(f) == 1: hits[k] = f
    uniq = {next(iter(v)) for v in hits.values() if len(v) == 1}
    return uniq if len(uniq) == 1 else (set() if not uniq else {"AMBIG"})
def bn_ratio(t):
    t = re.sub(r"\s", "", t); return (sum(1 for ch in t if "\u0980" <= ch <= "\u09FF") / len(t)) if t else 0
def extract(pdf):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f.pdf"); open(p, "wb").write(pdf)
        t = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True, timeout=120).stdout
        if bn_ratio(t) > 0.5 or (re.search(r"[A-Za-z]{4}", t) and len(t) > 800 and not re.search(r"[†‡©¨]", t)): return t, "pdf_text"
        if not shutil.which("tesseract"): return None, "ocr_pending"
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-l", "30", "-png", p, os.path.join(d, "pg")], capture_output=True, timeout=600)
        out = []
        for im in sorted(x for x in os.listdir(d) if x.startswith("pg")):
            out.append(subprocess.run(["tesseract", os.path.join(d, im), "-", "-l", "ben+eng"], capture_output=True, text=True, timeout=300).stdout)
        return "\n".join(out), "pdf_text_ocr"
def doc_type(title):
    if re.search(r"উপ-?আইন|by-?law", title, re.I): return "ordinance"
    if re.search(r"প্রবিধানমালা|বিধিমালা|regulation|rules", title, re.I): return "regulation"
    return "gazette_act" if re.search(r"আইন", title) else "decision"
def stage(recs, pid):
    # 2026-11-04: NOT '.full' any more -- a .full batch replaces the whole place (SCHEMA.md 1.4), so one-row .full files wiped every earlier doc.
    d = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/sasia_ru/BD"); os.makedirs(d, exist_ok=True)
    final = f"{d}/{place_key(pid)}.bdgazette{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}p0001.jsonl"; tmp = final + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in recs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    chk = f"{d}/.{os.path.basename(final)}.check.jsonl"; os.link(tmp, chk)
    try: res = validate_file(chk, expect_place_key=place_key(pid))
    finally: os.unlink(chk)
    if not res["ok"]:
        os.makedirs((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/sasia_ru/_rejects"), exist_ok=True)
        os.replace(tmp, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/sasia_ru/_rejects/") + os.path.basename(final)); return None
    os.rename(tmp, final); time.sleep(1.1); return final
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--start-id", type=int, default=0); ap.add_argument("--min-id", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0); ap.add_argument("--stage", action="store_true"); a = ap.parse_args()
    P = load_places(); PL = {p["qid"]: p for p in P}
    print(json.dumps({"places": len(P), "with_bn": sum(1 for p in P if p["cores"])}), flush=True)
    start = a.start_id
    if not start:
        r = get(BASE + "/bgpress/index.php/document/gazettes/140")
        start = max(int(x) for x in re.findall(r"get_extraordinary/(\d+)", r.text)) + 50
    donef = f"{D}/bg_done.txt"; done = set(open(donef).read().split()) if os.path.exists(donef) else set()
    fi = open(f"{D}/bg_index.jsonl", "a"); fd = open(donef, "a"); fm = open(f"{D}/bg_local.jsonl", "a"); fo = open(f"{D}/bg_ocr_pending.jsonl", "a")
    _, pol = robots(); n = 0; staged = 0; miss_run = 0
    for gid in range(start, a.min_id - 1, -1):
        if str(gid) in done: continue
        if a.limit and n >= a.limit: break
        n += 1
        r = get(f"{BASE}/bgpress/index.php/document/get_extraordinary/{gid}")
        if r is None or r.status_code != 200: continue   # not marked done -> retried next run
        rows = []
        for m in re.finditer(r"<tr.*?</tr>", r.text, re.S):
            u = re.findall(r'href="([^"]+\.pdf)"', m.group(0))
            if not u: continue
            cells = [re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", c))).strip() for c in re.findall(r"<td.*?</td>", m.group(0), re.S)]
            cells = [c for c in cells if c]
            if len(cells) < 3: continue
            rows.append({"gid": gid, "date": cells[0], "title": cells[1], "ministry": cells[2], "pages": cells[3] if len(cells) > 3 else None,
                         "pdf": u[0].replace("http://", "https://")})
        for x in rows: fi.write(json.dumps(x, ensure_ascii=False) + "\n")
        fi.flush()
        for x in rows:
            if not (LOCAL.search(x["title"]) or "Local Government" in x["ministry"]): continue
            q = match(x["title"], P); x["match"] = sorted(q)
            fm.write(json.dumps(x, ensure_ascii=False) + "\n"); fm.flush()
            if len(q) != 1 or "AMBIG" in q: continue
            q = next(iter(q)); pdfp = f"{RAW}/{os.path.basename(x['pdf'])}"
            if not os.path.exists(pdfp):
                rp = get(x["pdf"])
                if not rp or rp.status_code != 200 or rp.content[:4] != b"%PDF": continue
                open(pdfp, "wb").write(rp.content)
            text, fmt = extract(open(pdfp, "rb").read())
            if fmt == "ocr_pending": fo.write(json.dumps({**x, "qid": q, "pdf_path": pdfp}, ensure_ascii=False) + "\n"); fo.flush(); continue
            if not text or len(text.strip()) < 200: continue
            dm = re.match(r"(\d{2})-(\w{3})-(\d{4})", x["date"])
            p = PL[q]; num = re.search(r"(?:নং|S\.?\s*R\.?\s*O\.?[^০-৯0-9]*)\s*([০-৯0-9][^\s।,]*)", x["title"])
            rec = {"place_id": "wd:" + q, "country_code": "BD", "doc_id": f"bdgazette:{gid}:{os.path.basename(x['pdf'])[:-4]}", "source_platform": "bd_gazette",
                   "source_url": f"{BASE}/bgpress/index.php/document/get_extraordinary/{gid}", "doc_type": doc_type(x["title"]), "language": "bn",
                   "title_native": x["title"][:1000], "number": num.group(1).translate(BN_DIG) if num else None, "adopted_date": None,
                   "published_date": f"{dm.group(3)}-{MON.get(dm.group(2), 1):02d}-{dm.group(1)}" if dm else None, "in_force": None,
                   "consolidated": False, "content_format": "pdf_text", "text": text, "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "source_policy": pol, "source_official": True, "source_org": "Bangladesh Government Press (DPP)", "file_url": x["pdf"],
                   "place_name": p["name"], "qid": q, "admin_level": p["level"], "platform": "bd_gazette", "platform_place_id": str(gid),
                   "extra_metadata": {"ministry": x["ministry"], "gazette_pages": x["pages"], "text_method": fmt}}
            if validate_record(rec): continue
            if a.stage:
                while free_gb() < 10: print(json.dumps({"disk_low_gb": round(free_gb(), 1), "sleep": 3600}), flush=True); time.sleep(3600)
                out = stage([rec], "wd:" + q); staged += bool(out)
                print(json.dumps({"gid": gid, "qid": q, "title": x["title"][:120], "staged": out}, ensure_ascii=False), flush=True)
        fd.write(f"{gid}\n"); fd.flush()
        if n % 200 == 0: print(json.dumps({"progress_gid": gid, "n": n, "staged": staged, "ts": datetime.now().isoformat(timespec="seconds")}), flush=True)
    print(json.dumps({"end": datetime.now(timezone.utc).isoformat(timespec="seconds"), "n": n, "staged": staged}), flush=True)
if __name__ == "__main__": main()
