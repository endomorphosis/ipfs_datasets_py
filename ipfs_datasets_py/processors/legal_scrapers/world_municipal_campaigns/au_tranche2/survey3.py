"""AU tranche-2 survey: probe candidate councils (checkpointed).

For each candidate: robots posture, home status, sitemap scan for
law/bylaw PDF links, and one-hop local-law index pages -> law PDFs.
Hard-capped curl only. Results in survey/probe.json after each council.
"""
import json, re, subprocess, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse

HERE = Path(__file__).resolve().parent
OUT = HERE / "survey" / "probe2.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 world-municipal-law-tranche2/0.1"
LAWISH = re.compile(r"local[-_ ]?law|by[-_ ]?law|bylaw", re.I)

CANDIDATES = {
    "16150": ("Orange", "New South Wales", "https://www.orange.nsw.gov.au"),
    "10470": ("Bathurst", "New South Wales", "https://www.bathurst.nsw.gov.au"),
    "16900": ("Shellharbour", "New South Wales", "https://www.shellharbour.nsw.gov.au"),
    "16490": ("Queanbeyan-Palerang", "New South Wales", "https://www.qprc.nsw.gov.au"),
    "15240": ("Mid-Coast", "New South Wales", "https://www.midcoast.nsw.gov.au"),
    "14850": ("Lismore", "New South Wales", "https://www.lismore.nsw.gov.au"),
    "10180": ("Armidale", "New South Wales", "https://www.armidaleregional.nsw.gov.au"),
    "13450": ("Griffith", "New South Wales", "https://www.griffith.nsw.gov.au"),
    "11250": ("Broken Hill", "New South Wales", "https://www.brokenhill.nsw.gov.au"),
    "11350": ("Byron", "New South Wales", "https://www.byron.nsw.gov.au"),
    "24130": ("Macedon Ranges", "Victoria", "https://www.mrsc.vic.gov.au"),
    "26490": ("Surf Coast", "Victoria", "https://www.surfcoast.vic.gov.au"),
    "26700": ("Wangaratta", "Victoria", "https://www.wangaratta.vic.gov.au"),
    "24780": ("Mildura", "Victoria", "https://www.mildura.vic.gov.au"),
    "20830": ("Baw Baw", "Victoria", "https://www.bawbawshire.com.au"),
    "22110": ("East Gippsland", "Victoria", "https://www.eastgippsland.vic.gov.au"),
    "26810": ("Wellington", "Victoria", "https://www.wellington.vic.gov.au"),
    "25710": ("Nillumbik", "Victoria", "https://www.nillumbik.vic.gov.au"),
    "34530": ("Livingstone", "Queensland", "https://www.livingstone.qld.gov.au"),
    "33980": ("Isaac", "Queensland", "https://www.isaacrc.qld.gov.au"),
    "37340": ("Whitsunday", "Queensland", "https://www.whitsundayrc.qld.gov.au"),
    "34860": ("Maranoa", "Queensland", "https://www.maranoa.qld.gov.au"),
    "36660": ("Southern Downs", "Queensland", "https://www.sdrc.qld.gov.au"),
    "34580": ("Lockyer Valley", "Queensland", "https://www.lockyer.qld.gov.au"),
    "36580": ("Somerset", "Queensland", "https://www.somerset.qld.gov.au"),
    "32810": ("Douglas", "Queensland", "https://www.douglas.qld.gov.au"),
    "32260": ("Cassowary Coast", "Queensland", "https://www.cassowarycoast.qld.gov.au"),
    "36820": ("Tablelands", "Queensland", "https://www.trc.qld.gov.au"),
    "34880": ("Mareeba", "Queensland", "https://www.msc.qld.gov.au"),
    "31900": ("Burdekin", "Queensland", "https://www.burdekin.qld.gov.au"),
    "35300": ("Mount Isa", "Queensland", "https://www.mountisa.qld.gov.au"),
    "32310": ("Charters Towers", "Queensland", "https://www.charterstowers.qld.gov.au"),
    "48050": ("Victor Harbor", "South Australia", "https://www.victor.sa.gov.au"),
    "46300": ("Port Lincoln", "South Australia", "https://www.portlincoln.sa.gov.au"),
    "46090": ("Port Augusta", "South Australia", "https://www.portaugusta.sa.gov.au"),
    "40220": ("Alexandrina", "South Australia", "https://www.alexandrina.sa.gov.au"),
    "40310": ("Barossa", "South Australia", "https://www.barossa.sa.gov.au"),
    "40120": ("Adelaide Hills", "South Australia", "https://www.ahc.sa.gov.au"),
    "42030": ("Gawler", "South Australia", "https://www.gawler.sa.gov.au"),
    "46510": ("Prospect", "South Australia", "https://www.prospect.com.au"),
    "53800": ("Greater Geraldton", "Western Australia", "https://www.cgg.wa.gov.au"),
    "54280": ("Kalgoorlie-Boulder", "Western Australia", "https://www.ckb.wa.gov.au"),
    "50980": ("Broome", "Western Australia", "https://www.broome.wa.gov.au"),
    "54310": ("Karratha", "Western Australia", "https://www.karratha.wa.gov.au"),
    "57280": ("Port Hedland", "Western Australia", "https://www.porthedland.wa.gov.au"),
    "53290": ("Esperance", "Western Australia", "https://www.esperance.wa.gov.au"),
    "57700": ("Serpentine-Jarrahdale", "Western Australia", "https://www.sjshire.wa.gov.au"),
    "54200": ("Kalamunda", "Western Australia", "https://www.kalamunda.wa.gov.au"),
    "56090": ("Mundaring", "Western Australia", "https://www.mundaring.wa.gov.au"),
    "64810": ("Sorell", "Tasmania", "https://www.sorell.tas.gov.au"),
    "60410": ("Brighton", "Tasmania", "https://www.brighton.tas.gov.au"),
    "60810": ("Central Coast (Tas.)", "Tasmania", "https://www.centralcoast.tas.gov.au"),
    "65410": ("Waratah-Wynyard", "Tasmania", "https://www.warwyn.tas.gov.au"),
    "65810": ("West Tamar", "Tasmania", "https://www.wtc.tas.gov.au"),
    "64210": ("Meander Valley", "Tasmania", "https://www.meander.tas.gov.au"),
    "64610": ("Northern Midlands", "Tasmania", "https://www.northernmidlands.tas.gov.au"),
    "72200": ("Katherine", "Northern Territory", "https://www.katherine.nt.gov.au"),
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
