#!/usr/bin/env python3
"""2026-11-04 county lane: German Kreis Amtsblatt lister -> pdf_list_fetch.py entries JSON.
Usage: de_amtsblatt_list.py <cfg.json> <out.json> [--limit N]
cfg: {place meta..., "start_urls":[...], "follow_re": regex for same-host subpages (archive/year pages), "pdf_re"?: keep filter}
Same host only, depth<=2, <=80 pages, 2 s/request, honest WorldLawBot UA, no bypass. Spreadsheets ignored (PDF only)."""
import re, sys, json, time, html, urllib.parse as U, requests
UA = "WorldLawBot/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law; public-law research crawler; polite)"
cfg = json.load(open(sys.argv[1])); out = sys.argv[2]; lim = int(sys.argv[sys.argv.index("--limit")+1]) if "--limit" in sys.argv else 0
s = requests.Session(); s.headers["User-Agent"] = UA; s.trust_env = False
host = U.urlsplit(cfg["start_urls"][0]).netloc; fre = re.compile(cfg.get("follow_re", "amtsbl|archiv"), re.I)
max_pages = int(cfg.get("max_pages", 80)); seen, queue, items = set(), [(u, 0) for u in cfg["start_urls"]], {}
while queue and len(seen) < max_pages:
    u, d = queue.pop(0)
    if u in seen: continue
    seen.add(u); time.sleep(2)
    try: r = s.get(u, timeout=(15, 60)); r.raise_for_status()
    except Exception as e: print("ERR", u, e, flush=True); continue
    if "cf-chl" in r.text or "captcha" in r.text.lower()[:5000]: print("CHALLENGE", u); continue
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.I | re.S):
        h = U.urljoin(r.url, html.unescape(m.group(1))).split("#")[0]; t = re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", m.group(2))).strip()
        if U.urlsplit(h).netloc != host: continue
        # CommunalCMS rewrite before keep-filter so pdf_re can match /media/custom/ or titles
        mfid = re.search(r"loadDocument\.phtml\?.*FID=(\d+)\.(\d+)\.(\d+)", h, re.I)
        if mfid:
            h = U.urljoin(r.url, f"/media/custom/{mfid.group(1)}_{mfid.group(2)}_{mfid.group(3)}.PDF")
        mfile = re.search(r"download\.php\?[^#]*file=([^&]+)", h, re.I)
        if mfile:
            path = U.unquote(mfile.group(1))
            idx = path.find("/media/custom/")
            if idx >= 0:
                path = path[idx:]
                path_only, _, qs = path.partition("?")
                h = U.urljoin(r.url, path_only + (("?" + qs) if qs else ""))
        if (re.search(r"\.pdf", h, re.I) or re.search(r"download\.php\?.*(?:fid=|file=)", h, re.I)
                or re.search(r"/downloads/datei/[A-Za-z0-9+/=]+", h)
                or re.search(r"/datei/download/id/", h, re.I)
                or (re.search(r"dokument/show\.cfm\?", h, re.I) and re.search(r"pdf|amtsblatt", t + " " + h, re.I))):
            if cfg.get("pdf_re") and not re.search(cfg["pdf_re"], U.unquote(h) + " " + t, re.I): continue
            items.setdefault(h, t or U.unquote(h.rsplit("/", 1)[-1]))
        elif d < 2 and fre.search(h) and not re.search(r"\.(xlsx?|ods|csv|docx?|zip|jpg|png)($|\?)", h, re.I): queue.append((h, d + 1))
    print(f"page {u} -> {len(items)} pdfs", flush=True)
meta = {k: v for k, v in cfg.items() if k not in ("start_urls", "follow_re", "pdf_re")}
its = []
for h, t in items.items():
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", t + " " + U.unquote(h)); dt = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None
    its.append({"url": h, "title": t, "published_date": dt, "kind": "amtsblatt"})
its.sort(key=lambda x: x["published_date"] or "", reverse=True)
if lim: its = its[:lim]
meta["items"] = its; json.dump(meta, open(out, "w"), ensure_ascii=False, indent=1); print("LISTED", len(its), "pages", len(seen))
