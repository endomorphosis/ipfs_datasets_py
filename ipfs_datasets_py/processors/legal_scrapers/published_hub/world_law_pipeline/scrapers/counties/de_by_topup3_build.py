#!/usr/bin/env python3
"""2026-11-02 de_by_topup3_build.py: list-only builder for Bavarian Landkreise that were robots-blocked (archive-only) or got tiny
yields before Benjamin's 2026-11-01 "ignore robots.txt" decision. Per target: live crawl of the index page(s) + same-host law-ish
sub-pages (depth<=2, <=60 pages, 2 s/req, honest UA; no WAF/captcha bypass) UNION the original URLs listed in the earlier archive
cfg (de_by_kreisrecht_<slug>_archive.json), minus anything already staged/processed/provenance (by source_url or de_by_kreisrecht
doc_id = sha1(url)[:16], same as pdf_list_fetch.py). Spreadsheets dropped. Writes entries/de_by_wd_<Q>.json for pdf_list_fetch.py.
Usage: de_by_topup3_build.py <targets.json> [parallel=5]"""
import re, sys, json, time, html, gzip, hashlib, itertools, urllib.request, urllib.parse
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from multiprocessing import Pool
HERE = Path(__file__).resolve().parent
UA = "WorldLawBot/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law; public-law research crawler; polite)"
LAWY = re.compile(r"(kreisrecht|satzung|verordnung|ortsrecht|recht|bekanntmach|amtsbl|gebühr|gebuehr|abfall|archiv|20[0-2]\d)", re.I)
DEFLINK = r"\.pdf|download|loadDocument\.phtml\?[^\"]*Ext=PDF|/output/download\.php\?"
JUNK = re.compile(r"abfuhrkalender|antragsformular|formular|flyer|brosch|ratgeber|sortierhinweis|stellenaus|stellenang|speiseplan|veranstaltungskalender|wahlvorschlag_muster", re.I)  # obvious non-law PDFs
SHEET = re.compile(r"\.(xlsx?|ods|csv)(\?|$)", re.I)
def get(u):
    time.sleep(2)
    r = urllib.request.urlopen(urllib.request.Request(urllib.parse.quote(u, safe=":/?&=%#;+,@!$~*()'{}"), headers={"User-Agent": UA}), timeout=60)
    return r.geturl(), r.read(5_000_000).decode("utf-8", "replace")
def links(page, base, e):
    lre = re.compile(e.get("link_re") or DEFLINK, re.I); out = {}
    for h, t in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S | re.I):
        if not lre.search(h): continue
        u = urllib.parse.quote(urljoin(base, html.unescape(h)), safe=":/?&=%#;+,@!$~*()'[]{}")
        for a, b in e.get("norm", []): u = re.sub(a, b, u)
        if re.search(r"\.vcf(\?|$)|/visitenkarte/|readspeaker|docreader|\.(jpe?g|png|gif|docx?|zip)(\?|$)", u, re.I) or SHEET.search(u): continue
        if e.get("exclude_re") and re.search(e["exclude_re"], u, re.I): continue
        if JUNK.search(urllib.parse.unquote(u)) or JUNK.search(t): continue
        t = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", t))).strip(); t = re.sub(r"\(?\s*PDF[^)]*\)?\s*$", "", t, flags=re.I).strip(" -")
        if e.get("pdf_re") and not re.search(e["pdf_re"], urllib.parse.unquote(u) + " " + t, re.I): continue
        if len(re.sub(r"\W", "", t)) < 3: t = ""
        out.setdefault(u, t or urllib.parse.unquote(u.split("?")[0].rsplit("/", 1)[-1]))
    return out
def crawl(e):
    starts = e.get("index_urls") or [e["url"]]; host = urlsplit(starts[0]).netloc
    seen, queue, found, fails = set(), [(u, 0) for u in starts], {}, []
    while queue and len(seen) < e.get("max_pages", 60):
        u, d = queue.pop(0)
        if u in seen: continue
        seen.add(u)
        try: fu, page = get(u)
        except Exception as ex: fails.append(f"{u} {str(ex)[:120]}"); continue
        m = re.search(r'<base[^>]+href="([^"]+)"', page, re.I); b = urljoin(fu, m.group(1)) if m else fu
        for k, v in links(page, b, e).items(): found.setdefault(k, v)
        if d < 2:
            for h, t in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', page, re.S):
                s = urljoin(b, html.unescape(h))
                if urlsplit(s).netloc == host and s not in seen and not re.search(r"\.(pdf|jpe?g|png|docx?|zip|xlsx?)$|loadDocument\.phtml|download\.php|mailto:", s, re.I) \
                   and (LAWY.search(s) or LAWY.search(re.sub("<[^>]+>", "", t))): queue.append((s, d + 1))
    return seen, found, fails
def staged():
    urls, ids = set(), set()
    base = Path("/workspace/world_law")
    for f in itertools.chain((base / "staging/counties").rglob("*.jsonl"), (base / "processed/counties/DE").glob("*.jsonl*")):
        if "de_by_kreisrecht" not in f.name: continue
        for l in (gzip.open(f, "rt", errors="replace") if f.name.endswith(".gz") else open(f, errors="replace")):
            m = re.search(r'"source_url": ?"([^"]+)"', l); m2 = re.search(r'"doc_id": ?"([^"]+)"', l)
            if m: urls.add(m.group(1))
            if m2: ids.add(m2.group(1))
    for l in open(HERE / "published_skip.jsonl"):
        try: d = json.loads(l); urls.add(d.get("source_url")); ids.add(d.get("doc_id"))
        except Exception: pass
    return urls, ids
def one(e):
    t0 = time.time(); seen, found, fails = crawl(e); live = len(found)
    arch = HERE / f"de_by_kreisrecht_{re.sub(chr(92)+'W+', '_', e['name'].lower()).strip('_')}_archive.json"
    na = 0
    if arch.exists() and not e.get("no_archive_list"):
        c = json.load(open(arch))
        for u in c.get("urls", []):
            for a, b in e.get("norm", []): u = re.sub(a, b, u)
            if SHEET.search(u) or JUNK.search(urllib.parse.unquote(u)): continue
            if e.get("exclude_re") and re.search(e["exclude_re"], u, re.I): continue
            if u not in found: found[u] = c.get("titles", {}).get(u) or urllib.parse.unquote(u.split("?")[0].rsplit("/", 1)[-1]); na += 1
    return e, len(seen), live, na, found, fails[:5], round(time.time() - t0)
if __name__ == "__main__":
    T = json.load(open(sys.argv[1])); par = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    SU, SI = staged(); print("already staged de_by_kreisrecht urls", len(SU), "ids", len(SI), flush=True)
    with Pool(par) as p:
        for e, np_, live, na, found, fails, dt in p.imap_unordered(one, T):
            new = {u: t for u, t in found.items() if u not in SU and urllib.parse.unquote(u) not in SU
                   and "de_by_kreisrecht:" + hashlib.sha1(u.encode()).hexdigest()[:16] not in SI}
            print(json.dumps(dict(name=e["name"], qid=e["qid"], pages=np_, live_links=live, archive_list_added=na, total=len(found), new=len(new), secs=dt, fails=fails), ensure_ascii=False), flush=True)
            if not new: continue
            out = dict(place_id="wd:" + e["qid"], country_code="DE", source_platform="de_by_kreisrecht", source_org=e["name"], doc_id_prefix="",
                       language="de", doc_type="ordinance", place_name=e["name"], admin_level="landkreis", qid=e["qid"],
                       items=[{"url": u, "title": t} for u, t in new.items()])
            pth = HERE / "entries" / f"de_by_wd_{e['qid']}.json"
            if pth.exists(): pth.rename(pth.with_suffix(".json.prev_" + time.strftime("%Y%m%d%H%M")))
            json.dump(out, open(pth, "w"), ensure_ascii=False); print("ENTRIES", pth, e["name"], len(new), flush=True)
