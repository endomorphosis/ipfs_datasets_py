#!/usr/bin/env python3
"""Uzbekistan (UZ): national legislation from the official national legislation database LEX.UZ
(Ministry of Justice), live.  Listing: https://lex.uz/uz/search/nat?lang=4 (ASP.NET postback "Keyingisi"/next
paging, 20/page, ~28.5k docs).  Text: https://lex.uz/uz/docs/<id> (div.lx_elem > div[@id]).
robots.txt (RFC 9309; lex.uz returns 404 => allow-all per RFC 9309 §2.3.1.3) checked per request; >=3 s delay.
Dedup: skip docs whose lex.uz URL (acts/docs, any lang prefix, ONDATE variants) is in an older ipfs_*_laws repo.
Resumable: done ids + dedup log; listing is re-walked on restart (cheap), docs already done are skipped.
Usage: collect_uz_lex.py [--limit N] [--max-pages N] [--list-url URL]
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, html as _h, re, sys, time
import lxml.html
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/national/common"))
from natlib import PoliteSession, Blocked, setup_log, STAGE  # noqa
from robots import robots_for, UA  # noqa
from newcc import DedupSkip, SafeStager  # noqa

CC, NAME = "UZ", "uz_lex"
log = setup_log(CC, NAME)
S = PoliteSession(min_delay=3.0, log=log)
UZ_CYR = set("ўқғҳЎҚҒҲ")

def form(t):
    return {m[0]: _h.unescape(m[1]) for m in re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', t)}

def post(url, data):
    rb, _ = robots_for(url)
    if not (rb.can_fetch(UA, url) and rb.can_fetch("*", url)): raise Blocked("robots " + url)
    for i in range(4):
        wait = S.min_delay - (time.time() - S.last.get("lex.uz", 0))
        if wait > 0: time.sleep(wait)
        S.last["lex.uz"] = time.time()
        try:
            r = S.s.post(url, data=data, timeout=90)
            if r.status_code in (401, 403): raise Blocked(f"HTTP {r.status_code}")
            if r.status_code == 200: return r
            log.warning("post HTTP %s", r.status_code)
        except Blocked: raise
        except Exception as e: log.warning("post err %s", e)
        time.sleep(20 * (i + 1))
    raise RuntimeError("listing post failed")

def pages(list_url, max_pages):
    r = S.get(list_url); n = 1
    while True:
        t = r.text
        ids = list(dict.fromkeys(re.findall(r'href="/uz/docs/(-?\d+)"', t)))
        yield n, ids
        if not ids or (max_pages and n >= max_pages) or "ucFoundActsControl$LinkButton1" not in t: return
        f = form(t); f["__EVENTTARGET"] = "ucFoundActsControl$LinkButton1"; f["__EVENTARGUMENT"] = ""
        r = post(list_url, f); n += 1

def lang_of(text):
    s = text[:5000]
    cyr = sum("\u0400" <= c <= "\u04ff" for c in s); lat = sum("a" <= c.lower() <= "z" for c in s)
    if cyr > lat: return "uz-Cyrl" if any(c in UZ_CYR for c in s) else "ru"
    return "uz"

def parse(t):
    d = lxml.html.fromstring(t)
    parts, title = [], None
    for e in d.xpath('//div[contains(concat(" ",@class," ")," lx_elem ")]'):
        b = e.xpath('./div[@id]')
        if not b: continue
        x = re.sub(r"[ \t\xa0]+", " ", b[0].text_content()).strip()
        if not x: continue
        if title is None and "ACT_TITLE" in e.get("class", ""): title = x
        parts.append(x)
    pt = (d.xpath("//title/text()") or [""])[0].replace("\xa0", " ").strip()
    m = re.match(r"(?:\S+-сон\s+)?(\d{2})\.(\d{2})\.(\d{4})\.?\s*(.*)", pt)
    date = f"{m[3]}-{m[2]}-{m[1]}" if m else None
    return "\n\n".join(parts), (m[4].strip() if m and m[4].strip() else title or pt), title, date

def pdf_text(url, cap=40_000_000):
    import subprocess, tempfile
    try:
        r = S.get(url, stream=True)
        if r.status_code != 200 or "pdf" not in r.headers.get("content-type", ""): return ""
        buf = b""
        for ch in r.iter_content(1 << 16):
            buf += ch
            if len(buf) > cap: log.info("pdf too big %s", url); return ""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(buf); f.flush()
            out = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, timeout=300).stdout
        return re.sub(r"[ \t]+", " ", out.decode("utf-8", "replace")).strip()
    except Blocked: raise
    except Exception as e:
        log.warning("pdf fail %s %s", url, e); return ""

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-pages", type=int, default=0)
    ap.add_argument("--list-url", default="https://lex.uz/uz/search/nat?lang=4"); a = ap.parse_args()
    st = SafeStager(CC, NAME, chunk=200, log=log); dd = DedupSkip(CC, NAME)
    n = fail = short = 0
    try:
        for pno, ids in pages(a.list_url, a.max_pages):
            log.info("listing page %d: %d ids", pno, len(ids))
            for i in ids:
                if st.seen(i) or i in dd.skipped: continue
                url = f"https://lex.uz/uz/docs/{i}"
                variants = [f"https://lex.uz/{p}{k}/{i}" for p in ("", "uz/", "ru/", "en/", "oz/") for k in ("docs", "acts")]
                if dd.check(i, url, *variants, prefix=True): continue
                try: r = S.get(url)
                except Blocked as e: log.error("BLOCKED, stopping: %s", e); raise
                except Exception as e: fail += 1; log.warning("fail %s %s", i, e); continue
                if r.status_code != 200: fail += 1; log.warning("HTTP %s %s", r.status_code, i); continue
                text, name, act_title, date = parse(r.text)
                fmt = "html"
                if len(text) < 100 and f"/pdfs/{i}" in r.text:
                    text = pdf_text(f"https://lex.uz/pdffile/{i}"); fmt = "pdf_text"
                if len(text) < 100: short += 1; log.info("no text %s", i); continue
                rec = {"place_id": "iso:UZ", "country_code": "UZ", "doc_id": i, "source_platform": "uz_lex",
                       "source_url": url, "doc_type": "statute", "language": lang_of(text),
                       "title_native": name[:1000], "adopted_date": date, "consolidated": True,
                       "content_format": fmt, "text": text, "source_official": True,
                       "source_org": "LEX.UZ — National Database of Legislation of the Republic of Uzbekistan (Ministry of Justice)",
                       "source_policy": "robots_404_allow_rfc9309", "place_name": "Uzbekistan",
                       "extra_metadata": {"act_title": act_title, "listing": a.list_url, "listing_page": pno}}
                if st.add(rec): n += 1
                if a.limit and n >= a.limit: raise StopIteration
    except (StopIteration, Blocked):
        pass
    st.flush()
    log.info("DONE staged=%d dedup_skipped_now=%d fail=%d no_text=%d invalid=%d", n, dd.n, fail, short, st.bad)

if __name__ == "__main__":
    main()
