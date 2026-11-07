"""Build a us_pdf_list config of Cluj County council decisions (main PDF, no annexes) for given year/months."""
import re, sys, json, time, html, urllib.request
UA = "Mozilla/5.0 (world_law county lane)"; year = sys.argv[1]; months = sys.argv[2].split(","); out = sys.argv[3]
urls, titles = [], {}
for m in months:
    for pg in range(1, 20):
        u = f"https://cjcluj.ro/hotarare-cjc/{year}/{m}/" + (f"page/{pg}/" if pg > 1 else "")
        try: p = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8", "replace")
        except Exception: break
        n = 0
        for b in re.split(r"<h2", p):
            t = re.search(r">\s*(Hotărârea nr\.[^<]+)", b); pdf = [x for x in re.findall(r'href="(https://storage[^"]+\.pdf)"', b) if "anexa" not in x.lower()]
            if t and pdf and pdf[0] not in titles: urls.append(pdf[0]); titles[pdf[0]] = html.unescape(t.group(1).strip()); n += 1
        time.sleep(2)
        if n == 0 or f"page/{pg+1}/" not in p: break
    print(m, len(urls), flush=True)
json.dump(dict(country_code="RO", place_id="iso:RO-CJ", qid="Q182624", place_name="Județul Cluj", iso_3166_2="RO-CJ", admin_level="judet",
               language="ro", doc_type="decision", consolidated=False, platform="ro_cjcluj_hcj", source_org="Consiliul Județean Cluj",
               urls=urls, titles=titles), open(out, "w"), ensure_ascii=False, indent=1)
