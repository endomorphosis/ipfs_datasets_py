"""2026-10-23: Build a us_pdf_list config of Dâmbovița County council decisions (HCJ main PDFs) from hotariri.cjd.ro's wpDataTables
server-side endpoint (admin-ajax.php is explicitly Allowed by robots.txt); PDFs live on sinteserv.cjd.ro (robots: only /wp-admin/ disallowed).
Usage: ro_cjd_list.py <years comma list, e.g. 2024,2025,2026> <out.json> [max_urls]"""
import re, sys, json, time, html, urllib.request, urllib.parse
UA = "Mozilla/5.0 (world_law county lane)"; years = set(sys.argv[1].split(",")); out = sys.argv[2]; maxu = int(sys.argv[3]) if len(sys.argv) > 3 else 10**6
pg = urllib.request.urlopen(urllib.request.Request("https://hotariri.cjd.ro/hotaririle-consiliului-judetean-dambovita/", headers={"User-Agent": UA}), timeout=60).read().decode("utf-8", "replace")
nonce = re.search(r'wdtNonceFrontendServerSide_1" value="([^"]+)"', pg).group(1)
def fix(t):  # titles are ISO-8859-2 bytes mis-decoded as Latin-1 (ã=ă, º=ş, þ=ţ) plus HTML entities
    try: t = t.encode("latin-1").decode("iso-8859-2")
    except Exception: pass
    return re.sub(r"\s+", " ", html.unescape(t)).strip()
urls, titles, start, total = [], {}, 0, None
while total is None or start < total:
    d = urllib.parse.urlencode({"draw": 1, "start": start, "length": 500, "wdtNonce": nonce}).encode()
    j = json.loads(urllib.request.urlopen(urllib.request.Request("https://hotariri.cjd.ro/wp-admin/admin-ajax.php?action=get_wdtable&table_id=1", data=d, headers={"User-Agent": UA}), timeout=120).read().decode("utf-8", "replace"))
    total = int(j["recordsTotal"]); start += 500
    for row in j["data"]:
        nr, date, title, yr = row[0], row[1], row[2], row[5]
        m = re.search(r"href='(https://sinteserv\.cjd\.ro/[^']+\.pdf)'", row[-1]) or re.search(r"href='(/bld/[^']+\.pdf)'", row[-2])
        if yr not in years or not m: continue
        u = urllib.parse.urljoin("https://sinteserv.cjd.ro/", m.group(1)); u = urllib.parse.quote(u, safe=":/?&=%#;+,@!$~*()'[]")
        if re.search(r"anex", u, re.I) or u in titles: continue
        urls.append(u); titles[u] = f"Hotărârea nr. {nr}/{yr} ({date}): {fix(title)}"[:500]
    print("fetched", start, "of", total, "kept", len(urls), flush=True); time.sleep(2)
urls.sort(key=lambda u: u, reverse=True)
json.dump(dict(country_code="RO", place_id="wd:Q188797", qid="Q188797", place_name="Județul Dâmbovița", iso_3166_2="RO-DB", admin_level="judet",
               language="ro", doc_type="decision", consolidated=False, platform="ro_cj_hcj", source_org="Județul Dâmbovița",
               index_url="https://hotariri.cjd.ro/hotaririle-consiliului-judetean-dambovita/", max_bytes=50 * 1024 * 1024, urls=urls[:maxu], titles={u: titles[u] for u in urls[:maxu]}),
          open(out, "w"), ensure_ascii=False, indent=1)
print("wrote", out, len(urls[:maxu]))
