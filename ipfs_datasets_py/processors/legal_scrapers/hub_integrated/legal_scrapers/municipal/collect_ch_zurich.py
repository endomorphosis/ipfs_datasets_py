#!/usr/bin/env python3
"""Stadt Zuerich (BFS 261) Amtliche Sammlung collector - polite live fetches, official PDFs, pdftotext (no OCR).
Index page -> systematic group pages -> act pages -> current 'Rechtstexte (pdf)' link.
Common Crawl was tried first (zh_pointers.py) but only had 5 AS PDFs captured, so live fetch is used.
Usage: python3 collect_ch_zurich.py OUTDIR [--limit N]  -> OUTDIR/raw/docs_zh.jsonl (same record shape as collect_ch_municipal)"""
import html, json, os, re, sys, datetime
from urllib.parse import urljoin, unquote
from collect_ch_municipal import get, pdf_text, now
BASE = "https://www.stadt-zuerich.ch"
IDX = BASE + "/de/politik-und-verwaltung/politik-und-recht/amtliche-sammlung.html"

def links(page, rx):
    t = html.unescape(page).replace("\\/", "/").replace('\\"', '"')
    return list(dict.fromkeys(re.findall(rx, t)))

def main():
    out = sys.argv[1]; limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10**9
    os.makedirs(f"{out}/raw", exist_ok=True)
    groups = links(get(IDX).text, r'href="(/de/politik-und-verwaltung/politik-und-recht/amtliche-sammlung/\d+/\d+\.html)"')
    acts = []
    for g in groups:
        r = get(BASE + g)
        if not r: continue
        stem = g[:-5]
        acts += [a for a in links(r.text, rf'href="((?:/web)?{re.escape(stem)}/[^"/]+\.html)"') if a not in acts]
    print("groups", len(groups), "acts", len(acts), flush=True)
    n = 0
    with open(f"{out}/raw/docs_zh.jsonl", "w") as f:
        for a in acts[:limit]:
            r = get(BASE + a.replace("/web/de/", "/de/"))
            if not r: continue
            pdfs = links(r.text, r'href="(/dam/web/de/politik-verwaltung/politik-recht/amtliche-sammlung/[^"]+?\.pdf)"')
            if not pdfs: continue
            pu = BASE + pdfs[0]; p = get(pu)
            if not p or not p.content.startswith(b"%PDF"): continue
            text = pdf_text(p.content)
            m = re.search(r"amtliche-sammlung/\d+/\d+/(\d{3}\.\d{3}(?:\.\d+)?)", pdfs[0])
            num = m.group(1) if m else unquote(pdfs[0].rsplit("/", 1)[1])[:-4]
            tm = re.search(r"<title>([^<|]+)", r.text)
            title = html.unescape(tm.group(1)).strip() if tm else num
            f.write(json.dumps(dict(native_id=num, title=title, text=text, source_url=pu, municipality="Zürich", municipality_code="261",
                admin1="CH-ZH", language="de", date=None, source_body="Stadt Zürich", retrieved_at=now(),
                extras={"act_page": BASE + a, "pdf_file": unquote(pdfs[0].rsplit("/", 1)[1]), "source": "stadt-zuerich.ch amtliche-sammlung"}),
                ensure_ascii=False) + "\n"); n += 1
            if n % 25 == 0: print("docs", n, flush=True)
    print("done", n)
if __name__ == "__main__": main()
