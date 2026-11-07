#!/usr/bin/env python3
"""Greater Amman Municipality (media.ammancity.gov.jo, 'التشريعات') and Ministry of Local Administration
(www.mola.gov.jo, 'الانظمة' / 'التعليمات') document lists -> items NOT already on the Hub
(endomorphosis/ipfs_jordan_municipal_laws@1a7f5872 seeds/listing.json) -> PDF text (no OCR) -> $JO_STATE/lists/.
Listing pages via GET and the ASP.NET pager POST-back; robots.txt 404 on both hosts (no rules); >= 2 s per request."""
import os, re, sys, json, html, hashlib, collections
from urllib.parse import quote, urljoin
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jo_common as C
import collect_jo_gazette as G

OUT = os.path.join(C.STATE, "lists"); TXT = os.path.join(OUT, "text"); os.makedirs(TXT, exist_ok=True)
HUB_LISTING = os.path.join(C.STATE, "hub", "mun", "scrapers", "seeds", "listing.json")
SOURCES = [("gam", "media.ammancity.gov.jo", "/AR/List/التشريعات", "التشريعات", False),
           ("mola", "www.mola.gov.jo", "/Ar/List/الانظمة", "الانظمة", False),
           ("mola", "www.mola.gov.jo", "/Ar/List/التعليمات", "التعليمات", False),
           ("mola", "www.mola.gov.jo", "/AR/Pages/التعليمات", "التعليمات (صفحة)", True)]
ROW_RX = re.compile(r"lvDocumentLibraryView_RowItem_(\d+)\".*?<label>(.*?)</label>.*?lblFileSize_\d+\"[^>]*>(.*?)</span>.*?href='([^']+)'", re.S)
PAGER_RX = re.compile(r"<a class=\"(NumericClass|nextPreviousButtonCSS)\" href=\"javascript:__doPostBack\(&#39;([^&]+?pagerList\$[^&]+?)&#39;,&#39;&#39;\)\">([^<]+)</a>")
CUR_RX = re.compile(r"CurrentPageClass[^>]*>(\d+)<")
OF_RX = re.compile(r"صفحة\s*(\d+)\s*من\s*(\d+)")


def enc(host, href):
    u = urljoin(f"https://{host}/", href)
    return quote(u, safe=":/?&=%#+,;@!$'()*~-._")


def form_fields(t):
    f = {}
    form = re.search(r"<form[^>]*id=\"ctl01\"[^>]*>(.*)</form>", t, re.S)
    for inp in re.findall(r"<input\b[^>]*>", form.group(1) if form else t):
        typ = (re.search(r'type="([^"]+)"', inp) or [None, "text"])[1].lower()
        nm = re.search(r'name="([^"]+)"', inp)
        if not nm or typ in ("submit", "image", "button", "checkbox", "radio", "file"):
            continue
        val = re.search(r'value="([^"]*)"', inp)
        f[html.unescape(nm.group(1))] = html.unescape(val.group(1)) if val else ""
    return f


def list_source(P, code, host, path, lname, static):
    url = enc(host, path); items = []
    r = P.get(url, use_cache=False)
    if not r or r["status"] != 200:
        G.log(f"lists {code}/{lname}: {r and r['status']}"); return items
    if static:
        t = r["body"].decode("utf-8", "replace")
        main = t[t.find("ContentDetails"):] if "ContentDetails" in t else t
        for href, txt in re.findall(r"<a\b[^>]*href=['\"]([^'\"]+\.pdf)['\"][^>]*>(.*?)</a>", main, re.S | re.I):
            title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", txt))).strip()
            items.append({"source": code, "list": lname, "host": host, "title": title, "url": enc(host, html.unescape(href)),
                          "listing_page": 1})
        return items
    seen = set()
    while r is not None and r["status"] == 200:
        t = r["body"].decode("utf-8", "replace")
        cur = int(CUR_RX.search(t).group(1)) if CUR_RX.search(t) else 1
        m = OF_RX.search(re.sub(r"<[^>]+>|&nbsp;", " ", t)); total = int(m.group(2)) if m else 1
        if cur in seen:
            break
        seen.add(cur)
        for idx, label, size, href in ROW_RX.findall(t):
            title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", label))).strip()
            items.append({"source": code, "list": lname, "host": host, "title": title, "url": enc(host, html.unescape(href)),
                          "listing_page": cur, "row": int(idx), "size_label": html.unescape(size).strip()})
        G.log(f"lists {code}/{lname} page {cur}/{total}: {len(items)} rows so far")
        if cur >= total:
            break
        nxt = next((tg for cls, tg, txt in PAGER_RX.findall(t) if txt.strip() == str(cur + 1)), None)
        if not nxt:
            break
        data = form_fields(t); data["__EVENTTARGET"] = nxt; data["__EVENTARGUMENT"] = ""
        r = P.post(url, data)
    return items


def main():
    P = C.Polite()
    hub = json.load(open(HUB_LISTING))["items"]
    hub_urls = {x["url"]: x for x in hub}
    tkey = lambda t: re.sub(r"[^\u0621-\u064a0-9]", "", C.norm_ar(t).replace("أ", "ا").replace("إ", "ا"))
    hub_titles = {tkey(x["title"]): x for x in hub if x.get("in_scope")}
    allitems = []
    for s in SOURCES:
        allitems += list_source(P, *s)
    seen, rows, cnt = set(), [], collections.Counter()
    for it in allitems:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        h = hub_urls.get(it["url"])
        if h is None and tkey(it["title"]) in hub_titles:
            it["decision"], it["reason"] = "hub", "already on the Hub (same title, different URL)"
        elif h is not None and h.get("in_scope"):
            it["decision"], it["reason"] = "hub", "already on the Hub (in scope there)"
        else:
            t = C.norm_ar(it["title"])
            if not it["url"].lower().endswith(".pdf"):
                it["decision"], it["reason"] = "out", "not a PDF"
            elif re.match(r"^(?:ال)?(?:قانون|دستور)", t):
                it["decision"], it["reason"] = "out", "national law (قانون)"
            elif G.CENTRAL_RX.search(t) and not re.search(r"أمانة\s*عمان|امانة\s*عمان|بلدية", t):
                it["decision"], it["reason"] = "out", "central-government rule (procurement / ministry organisation), not a local regulation"
            elif re.search(r"تعليمات|نظام|أنظمة|انظمة", t) or it["list"] == "الانظمة":
                it["decision"], it["reason"] = "in", ("new since the Hub listing" if h is None else
                                                      "Hub listed it as out of scope; re-checked by title")
            else:
                it["decision"], it["reason"] = "out", "title is not a نظام / تعليمات"
        cnt[it["decision"]] += 1; rows.append(it)
    json.dump({"listed_at": C.now_utc(), "items": rows, "counts": cnt}, open(os.path.join(OUT, "listing.json"), "w"),
              ensure_ascii=False, indent=1)
    G.log(f"lists: {len(rows)} unique items {dict(cnt)}")
    for it in rows:
        if it["decision"] != "in":
            continue
        key = hashlib.sha1(it["url"].encode()).hexdigest()[:16]
        fn = os.path.join(TXT, key + ".json.gz")
        if os.path.exists(fn):
            continue
        r = P.get(it["url"], doc=True, timeout=300)
        if not r or r["status"] != 200:
            G.log(f"lists fetch {it['url']}: {r and r['status']}"); continue
        ex = G.extract(r["body"], key)
        rec = {"key": key, "item": it, "status": 200, "download_url": it["url"], "final_url": r["url"],
               "content_type": r["ctype"], "last_modified": r.get("last_modified", ""), "retrieved_at": r["retrieved_at"],
               "bytes": len(r["body"]), "sha256": hashlib.sha256(r["body"]).hexdigest(), **ex}
        C._gz_w(fn, json.dumps(rec, ensure_ascii=False).encode())
        G.log(f"lists fetched {key} {ex['kind']} pages={ex.get('npages')} {it['title'][:60]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except C.ResourcePause as e:
        G.log(f"PAUSE {e}"); sys.exit(4)
