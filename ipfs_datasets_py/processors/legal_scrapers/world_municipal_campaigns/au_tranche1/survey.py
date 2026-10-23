"""AU tranche-1 survey: probe candidate councils (checkpointed).

For each candidate: robots posture, home status, sitemap scan for
law/bylaw PDF links, and one-hop local-law index pages -> law PDFs.
Hard-capped curl only. Results in survey/probe.json after each council.
"""
import json, re, subprocess, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse

HERE = Path(__file__).resolve().parent
OUT = HERE / "survey" / "probe.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 world-municipal-law-tranche1/0.1"
LAWISH = re.compile(r"local[-_ ]?law|by[-_ ]?law|bylaw", re.I)

CANDIDATES = {
    "36720": ("Sunshine Coast", "Queensland", "https://www.sunshinecoast.qld.gov.au"),
    "15900": ("Newcastle", "New South Wales", "https://www.newcastle.nsw.gov.au"),
    "18450": ("Wollongong", "New South Wales", "https://www.wollongong.nsw.gov.au"),
    "16260": ("Parramatta", "New South Wales", "https://www.cityofparramatta.nsw.gov.au"),
    "11650": ("Central Coast (NSW)", "New South Wales", "https://www.centralcoast.nsw.gov.au"),
    "14650": ("Lake Macquarie", "New South Wales", "https://www.lakemac.com.au"),
    "17750": ("Wagga Wagga", "New South Wales", "https://wagga.nsw.gov.au"),
    "10050": ("Albury", "New South Wales", "https://www.alburycity.nsw.gov.au"),
    "22750": ("Greater Geelong", "Victoria", "https://www.geelongaustralia.com.au"),
    "22620": ("Greater Bendigo", "Victoria", "https://www.bendigo.vic.gov.au"),
    "20570": ("Ballarat", "Victoria", "https://www.ballarat.vic.gov.au"),
    "21610": ("Casey", "Victoria", "https://www.casey.vic.gov.au"),
    "22170": ("Frankston", "Victoria", "https://www.frankston.vic.gov.au"),
    "23270": ("Hume", "Victoria", "https://www.hume.vic.gov.au"),
    "26980": ("Whitehorse", "Victoria", "https://www.whitehorse.vic.gov.au"),
    "27170": ("Wodonga", "Victoria", "https://www.wodonga.vic.gov.au"),
    "45340": ("Onkaparinga", "South Australia", "https://www.onkaparingacity.com"),
    "45680": ("Playford", "South Australia", "https://www.playford.sa.gov.au"),
    "47140": ("Salisbury", "South Australia", "https://www.salisbury.sa.gov.au"),
    "44620": ("Mount Gambier", "South Australia", "https://www.mountgambier.sa.gov.au"),
    "48540": ("Whyalla", "South Australia", "https://www.whyalla.com.au"),
    "57910": ("Stirling", "Western Australia", "https://www.stirling.wa.gov.au"),
    "58760": ("Wanneroo", "Western Australia", "https://www.wanneroo.wa.gov.au"),
    "51820": ("Cockburn", "Western Australia", "https://www.cockburn.wa.gov.au"),
    "55110": ("Mandurah", "Western Australia", "https://www.mandurah.wa.gov.au"),
    "50080": ("Albany", "Western Australia", "https://www.albany.wa.gov.au"),
    "51190": ("Bunbury", "Western Australia", "https://www.bunbury.wa.gov.au"),
    "57490": ("Rockingham", "Western Australia", "https://www.rockingham.wa.gov.au"),
    "58050": ("Swan", "Western Australia", "https://www.swan.wa.gov.au"),
    "62810": ("Hobart", "Tasmania", "https://www.hobartcity.com.au"),
    "64010": ("Launceston", "Tasmania", "https://www.launceston.tas.gov.au"),
    "61410": ("Clarence", "Tasmania", "https://www.ccc.tas.gov.au"),
    "62610": ("Glenorchy", "Tasmania", "https://www.gcc.tas.gov.au"),
    "71000": ("Darwin", "Northern Territory", "https://www.darwin.nt.gov.au"),
    "72800": ("Palmerston", "Northern Territory", "https://www.palmerston.nt.gov.au"),
    "33430": ("Gold Coast", "Queensland", "https://www.goldcoast.qld.gov.au"),
    "36910": ("Toowoomba", "Queensland", "https://www.tr.qld.gov.au"),
    "31820": ("Bundaberg", "Queensland", "https://www.bundaberg.qld.gov.au"),
}


def curl(url, max_time=40):
    t0 = time.monotonic()
    try:
        p = subprocess.run(["curl", "-sS", "-L", "--max-time", str(max_time), "-A", UA,
                            "-w", "\n%{http_code}", url], capture_output=True, timeout=max_time + 15)
        out = p.stdout.decode("utf-8", "replace")
        body, _, code = out.rpartition("\n")
        return {"status": int(code) if code.isdigit() else 0, "body": body,
                "seconds": round(time.monotonic() - t0, 1)}
    except Exception as exc:  # noqa: BLE001
        return {"status": 0, "body": "", "seconds": round(time.monotonic() - t0, 1), "err": str(exc)[:150]}


def links(html, base):
    out = []
    for m in re.finditer(r'href="([^"#]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        href, text = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        out.append((urljoin(base, href), re.sub(r"\s+", " ", text).strip()))
    return out


def probe(code, name, state, base):
    res = {"code": code, "name": name, "state": state, "base": base}
    r = curl(base + "/robots.txt", 25)
    res["robots_status"] = r["status"]
    res["robots_disallow_all"] = bool(re.search(r"User-agent:\s*\*\s*\nDisallow:\s*/\s*(\n|$)", r["body"]))
    home = curl(base + "/", 50)
    res["home_status"] = home["status"]
    if home["status"] != 200:
        return res
    pdfs, index_pages = {}, []
    for href, text in links(home["body"], base):
        if LAWISH.search(href + " " + text) and urlparse(href).netloc == urlparse(base).netloc:
            if href.lower().split("?")[0].endswith(".pdf"):
                pdfs[href] = text[:120]
            elif href not in index_pages:
                index_pages.append(href)
    # sitemap scan for law PDFs + law index pages
    sm = curl(base + "/sitemap.xml", 40)
    if sm["status"] == 200:
        for u in re.findall(r"<loc>([^<]+)</loc>", sm["body"]):
            if LAWISH.search(u):
                if u.lower().split("?")[0].endswith(".pdf"):
                    pdfs.setdefault(u, "")
                elif u not in index_pages:
                    index_pages.append(u)
    res["index_pages"] = index_pages[:6]
    for page in index_pages[:4]:
        time.sleep(1)
        pr = curl(page, 50)
        if pr["status"] != 200:
            continue
        for href, text in links(pr["body"], page):
            if href.lower().split("?")[0].endswith(".pdf") and LAWISH.search(href + " " + text):
                pdfs[href] = text[:120]
        for u in re.findall(r'(https?://[^"\']+\.pdf)', pr["body"], re.I):
            if LAWISH.search(u):
                pdfs.setdefault(u, "")
    res["law_pdfs"] = [{"url": u, "text": t} for u, t in list(pdfs.items())[:40]]
    res["law_pdf_count"] = len(pdfs)
    return res


def main():
    only = sys.argv[1:]
    results = json.loads(OUT.read_text()) if OUT.exists() else {}
    for code, (name, state, base) in CANDIDATES.items():
        if only and code not in only:
            continue
        if code in results and results[code].get("home_status") == 200 and results[code].get("law_pdf_count"):
            continue
        print(f"probing {code} {name}", flush=True)
        results[code] = probe(code, name, state, base)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False))
        r = results[code]
        print(f"  robots={r.get('robots_status')} home={r.get('home_status')} pdfs={r.get('law_pdf_count')}", flush=True)
        time.sleep(1)


if __name__ == "__main__":
    main()
