#!/usr/bin/env python3
"""Jordan Official Gazette (الجريدة الرسمية, www.pm.gov.jo) -> municipal regulations / instructions (أنظمة / تعليمات).

Phases (all resumable; state under $JO_STATE/gazette):
  index : GET https://www.pm.gov.jo/Ar/Pages/NewsPaperDetails/<issue> for every issue (newest first), parse the
          per-instrument items (title + the publisher's own DocuWare viewer link) -> gazette/issues/<n>.json
  scope : title classifier -> gazette/scope.jsonl (decision + reason for every item)
  fetch : in-scope items only. The publisher's viewer link (p=V) is used exactly as published, switched to DocuWare's
          documented download mode (p=D&dt=Download). PDF -> pdftotext per page + text-layer quality score; DWTiff /
          zip-of-TIFF scans and PDFs without a usable text layer -> image_only_pdfs.json (no OCR). Document bodies are
          not kept (text only) -> gazette/text/<did>.json.gz
Hosts: www.pm.gov.jo, doc.pm.gov.jo (robots.txt 404 = no rules; recorded). <= 1 request / 2 s per host, backoff.
"""
import os, re, sys, json, gzip, time, hashlib, subprocess, argparse, io, zipfile, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jo_common as C

STATE = C.STATE
G = os.path.join(STATE, "gazette")
ISS = os.path.join(G, "issues"); TXT = os.path.join(G, "text"); TMP = os.path.join(G, "tmp")
for d in (G, ISS, TXT, TMP):
    os.makedirs(d, exist_ok=True)
LOG = os.path.join(STATE, "gazette.log")
STOP = os.path.join(STATE, "STOP")
DETAIL = "https://www.pm.gov.jo/Ar/Pages/NewsPaperDetails/{}"
FIRST_ISSUE = int(os.environ.get("JO_FIRST_ISSUE", "4500"))


def log(*a):
    s = time.strftime("%Y-%m-%d %H:%M:%S %Z") + " " + " ".join(str(x) for x in a)
    print(s, flush=True)
    with open(LOG, "a") as f:
        f.write(s + "\n")


ITEM_RX = re.compile(r"href='([^']+)'>\s*<span id=\"MainContent_lvGovPaper_lblIssueNumber_(\d+)\">([^<]*)</span>")


def parse_issue(n, html):
    items = []
    for href, idx, title in ITEM_RX.findall(html):
        import html as H
        href = H.unescape(href); t = " ".join(H.unescape(title).split())
        m = re.search(r"[?&]did=(\d+)", href)
        items.append({"issue": n, "pos": int(idx), "title_raw": t, "title": t.lstrip("*").strip(),
                      "viewer_url": href, "did": m.group(1) if m else ""})
    return items


def latest_issue(P):
    r = P.get("https://www.pm.gov.jo/ar/Pages/NewsPaper", use_cache=False)
    ns = [int(x) for x in re.findall(r"NewsPaperDetails/(\d{4})", r["body"].decode("utf-8", "replace"))] if r else []
    return max(ns) if ns else 6083


def phase_index(P, args):
    hi = latest_issue(P); log(f"index: latest issue {hi}; scanning {hi}..{FIRST_ISSUE}")
    n_new = 0
    for n in range(hi, FIRST_ISSUE - 1, -1):
        if os.path.exists(STOP):
            log("STOP file -> pause"); return False
        fn = os.path.join(ISS, f"{n}.json")
        if os.path.exists(fn):
            continue
        r = P.get(DETAIL.format(n))
        if r is None:
            log(f"issue {n}: robots disallow / host blocked"); continue
        if r["status"] != 200:
            log(f"issue {n}: status {r['status']} {r.get('error','')}"); continue
        h = r["body"].decode("utf-8", "replace")
        missing = "Page not found" in h[:3000] or "Error Page" in h[:500]
        items = [] if missing else parse_issue(n, h)
        json.dump({"issue": n, "missing": missing, "retrieved_at": r.get("retrieved_at"), "url": DETAIL.format(n),
                   "items": items}, open(fn + ".tmp", "w"), ensure_ascii=False)
        os.replace(fn + ".tmp", fn); n_new += 1
        if n_new % 50 == 0:
            log(f"index: {n_new} issues fetched this run (at {n}) {C.resource_str()}")
    log(f"index done: {n_new} new issue pages"); return True


# ---------------------------------------------------------------- scope
LAWTYPE_RX = re.compile(r"(?:^|[\s\-–(])(?:ال)?(?:نظام|أنظمة|انظمة|تعليمات|التعليمات)(?:$|[\s\-–)])")
MUN_RX = re.compile(r"أمانة\s*عمان|امانة\s*عمان|بلدي|البلديات|بلديات|المجالس\s+المحلية|المجلس\s+المحلي|مجالس\s+المحافظات|"
                    r"مجلس\s+المحافظة|الإدارة\s+المحلية|الادارة\s+المحلية|الخدمات\s+المشتركة|تنظيم\s+المدن\s+والقرى|"
                    r"الأبنية\s+والتنظيم|الابنية\s+والتنظيم|التنظيم\s+والأبنية|التنظيم\s+والابنية|مدينة\s+عمان|اللامركزية|"
                    r"الشؤون\s+البلدية|الأسواق\s+الشعبية|المسالخ|الأرصفة|اللوحات\s+الإعلانية|اللوحات\s+الاعلانية|"
                    r"المهن\s+(?:في|ضمن)|رخص\s+المهن|ترخيص\s+المهن")
ZONE_RX = re.compile(r"منطقة\s+العقبة\s+الاقتصادية|سلطة\s+منطقة\s+العقبة|إقليم\s+البترا|اقليم\s+البترا|منطقة\s+البحر\s+الميت|"
                     r"المناطق\s+التنموية|منطقة\s+تنموية|المنطقة\s+التنموية")
CENTRAL_RX = re.compile(r"التنظيم\s+الإداري\s+لوزارة|التنظيم\s+الاداري\s+لوزارة|المشتريات\s+الحكومية|المشرتيات\s+الحكومية|الخدمة\s+المدنية|"
                        r"الموارد\s+البشرية\s+في\s+القطاع\s+العام")


def classify(it):
    t = C.norm_ar(it["title"]); t = re.sub(r"\s+", " ", t).strip()
    if not it.get("did"):
        return "out", "no document link"
    if re.match(r"^(?:ال)?فهرس", t):
        return "out", "issue index (الفهرس), not a law"
    if re.match(r"^(?:ال)?شؤون\s+البلدي", t):
        return "out", "non-law: 'الشؤون البلدية' section (planning / zoning / expropriation notices)"
    if re.match(r"^(?:ال)?(?:قانون|دستور)", t):
        return "out", "national law (قانون) - national corpus"
    if re.search(r"تصحيح\s+خطأ|تصويب|استدراك", t):
        return "out", "non-law: correction notice"
    if re.search(r"(?:^|\s)(?:مشروع|مسودة)(?:\s|$)", t):
        return "out", "non-law: draft"
    if re.match(r"^(?:إعلان|اعلان|إعلانات|اعلانات|بلاغ|بيان|قرارات?\s+(?:تنظيم|استملاك))", t):
        return "out", "non-law: notice / decision"
    if not LAWTYPE_RX.search(" " + t + " "):
        return "out", "not a نظام / تعليمات"
    if re.search(r"^(?:قرار|إرادة|ارادة)", t) and not re.search(r"بإصدار\s+(?:ال)?(?:تعليمات|نظام)|باصدار\s+(?:ال)?(?:تعليمات|نظام)", t):
        return "out", "decision, not a regulation / instruction"
    mun = MUN_RX.search(t)
    if not mun:
        if ZONE_RX.search(t):
            return "zone", "special zone / development authority (ASEZA, Petra, Dead Sea, development zones) - not municipal; not collected"
        return "out", "not municipal (no local-government subject in title)"
    if CENTRAL_RX.search(t) and not re.search(r"أمانة\s*عمان|امانة\s*عمان|بلدية\s+\S+", t):
        return "out", "central-government organisation / HR rule"
    return "in", f"title: law type + municipal subject ({mun.group(0)})"


def phase_scope(args):
    out, cnt = [], collections.Counter()
    for fn in sorted(os.listdir(ISS), key=lambda x: -int(x.split(".")[0])):
        d = json.load(open(os.path.join(ISS, fn)))
        for it in d["items"]:
            dec, why = classify(it)
            cnt[dec] += 1
            out.append(dict(it, decision=dec, reason=why))
    with open(os.path.join(G, "scope.jsonl.tmp"), "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(os.path.join(G, "scope.jsonl.tmp"), os.path.join(G, "scope.jsonl"))
    log(f"scope: {len(out)} items {dict(cnt)}")


# ---------------------------------------------------------------- fetch + text
VOCAB = None


def vocab():
    global VOCAB
    if VOCAB is None:
        fn = os.path.join(STATE, "ar_vocab.json")
        if not os.path.exists(fn):
            import pyarrow.parquet as pq
            t = pq.read_table(os.path.join(STATE, "hub", "nat", "data", "laws.parquet"), columns=["text"])
            c = collections.Counter()
            for x in t.column("text").to_pylist():
                c.update(re.findall(r"[\u0621-\u064a]+", C.norm_ar(x or "")))
            json.dump(sorted(w for w, k in c.items() if k >= 3), open(fn, "w"), ensure_ascii=False)
        VOCAB = set(json.load(open(fn)))
    return VOCAB


def page_quality(t):
    toks = re.findall(r"[\u0621-\u064a]+", C.norm_ar(t))
    toks = [w for w in toks if len(w) >= 2]
    if not toks:
        return {"words": 0, "in_vocab": 0.0}
    v = vocab()
    return {"words": len(toks), "in_vocab": round(sum(1 for w in toks if w in v) / len(toks), 3)}


def extract(body, did):
    """-> dict(kind, pages[{text, words, in_vocab}], ...)"""
    if body[:2] == b"PK":
        try:
            names = zipfile.ZipFile(io.BytesIO(body)).namelist()
        except Exception:
            names = []
        return {"kind": "zip", "members": names[:50],
                "image_only": all(n.lower().endswith((".dwtiff", ".tif", ".tiff", ".jpg", ".png")) for n in names) and bool(names)}
    if body[:4] in (b"II*\x00", b"MM\x00*"):
        return {"kind": "tiff", "image_only": True}
    if body[:5] != b"%PDF-":
        return {"kind": "unknown", "head": body[:16].hex(), "image_only": False}
    pdf = os.path.join(TMP, f"{did}.pdf")
    open(pdf, "wb").write(body)
    try:
        raw = subprocess.run(["pdftotext", "-enc", "UTF-8", pdf, "-"], capture_output=True, timeout=600).stdout.decode("utf-8", "replace")
        info = subprocess.run(["pdfinfo", pdf], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
        fonts = subprocess.run(["pdffonts", pdf], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
    finally:
        os.remove(pdf)
    pages = raw.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    m = re.search(r"^Pages:\s+(\d+)", info, re.M); npages = int(m.group(1)) if m else len(pages)
    pages += [""] * (npages - len(pages))
    P = []
    for t in pages:
        q = page_quality(t); P.append(dict(q, text=t))
    meta = {k: v.strip() for k, v in re.findall(r"^(Producer|Creator|CreationDate|ModDate|Title):\s*(.*)$", info, re.M)}
    fnames = sorted({l.split()[0] for l in fonts.splitlines()[2:] if l.strip()})
    return {"kind": "pdf", "npages": npages, "pdfinfo": meta, "fonts": fnames[:40], "pages": P,
            "image_only": all(p["words"] < 10 for p in P)}


def phase_fetch(P, args):
    rows = [json.loads(l) for l in open(os.path.join(G, "scope.jsonl"))]
    todo = [r for r in rows if r["decision"] == "in" and not os.path.exists(os.path.join(TXT, r["did"] + ".json.gz"))]
    log(f"fetch: {len(todo)} in-scope documents to fetch")
    done = 0
    for r in todo:
        if os.path.exists(STOP):
            log("STOP file -> pause"); return False
        url = r["viewer_url"].replace("p=V&", "p=D&dt=Download&")
        if "p=D&dt=Download" not in url:
            log(f"skip {r['did']}: viewer url without p=V"); continue
        res = P.get(url, doc=True, timeout=300)
        if res is None:
            log(f"did {r['did']}: robots disallow"); continue
        if res["status"] != 200:
            log(f"did {r['did']}: status {res['status']} {res.get('error','')[:120]}")
            if res["status"] in (404, 410):
                rec = {"did": r["did"], "item": r, "status": res["status"], "retrieved_at": res["retrieved_at"]}
                C._gz_w(os.path.join(TXT, r["did"] + ".json.gz"), json.dumps(rec, ensure_ascii=False).encode())
            continue
        body = res["body"]
        ex = extract(body, r["did"])
        rec = {"did": r["did"], "item": r, "status": 200, "download_url": url, "final_url": res["url"],
               "content_type": res["ctype"], "content_disposition": res.get("cdisp", ""),
               "last_modified": res.get("last_modified", ""), "retrieved_at": res["retrieved_at"],
               "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), **ex}
        C._gz_w(os.path.join(TXT, r["did"] + ".json.gz"), json.dumps(rec, ensure_ascii=False).encode())
        done += 1
        if done % 25 == 0:
            log(f"fetch: {done}/{len(todo)} {C.resource_str()}")
    log(f"fetch done: {done} documents"); return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["index", "scope", "fetch", "all"])
    ap.add_argument("--limit-issues", type=int, default=0)
    args = ap.parse_args()
    P = C.Polite()
    try:
        if args.phase in ("index", "all"):
            if not phase_index(P, args):
                return 3
        if args.phase in ("scope", "all", "fetch"):
            phase_scope(args)
        if args.phase in ("fetch", "all"):
            if not phase_fetch(P, args):
                return 3
    except C.ResourcePause as e:
        log(f"PAUSE resources {e}"); return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
