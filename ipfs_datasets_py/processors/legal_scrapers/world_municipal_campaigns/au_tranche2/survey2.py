"""AU tranche-2 survey: probe candidate councils (checkpointed).

For each candidate: robots posture, home status, sitemap scan for
law/bylaw PDF links, and one-hop local-law index pages -> law PDFs.
Hard-capped curl only. Results in survey/probe.json after each council.
"""
import json, re, subprocess, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse

HERE = Path(__file__).resolve().parent
OUT = HERE / "survey" / "probe.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 world-municipal-law-tranche2/0.1"
LAWISH = re.compile(r"local[-_ ]?law|by[-_ ]?law|bylaw", re.I)

CANDIDATES = {
    # New South Wales
    "17150": ("Sutherland", "New South Wales", "https://www.sutherlandshire.nsw.gov.au"),
    "10750": ("Blacktown", "New South Wales", "https://www.blacktown.nsw.gov.au"),
    "16550": ("Randwick", "New South Wales", "https://www.randwick.nsw.gov.au"),
    "14170": ("Inner West", "New South Wales", "https://www.innerwest.nsw.gov.au"),
    "15990": ("Northern Beaches", "New South Wales", "https://www.northernbeaches.nsw.gov.au"),
    "14000": ("Hornsby", "New South Wales", "https://www.hornsby.nsw.gov.au"),
    "16350": ("Penrith", "New South Wales", "https://www.penrithcity.nsw.gov.au"),
    "12850": ("Fairfield", "New South Wales", "https://www.fairfieldcity.nsw.gov.au"),
    "14900": ("Liverpool", "New South Wales", "https://www.liverpool.nsw.gov.au"),
    "11500": ("Campbelltown (NSW)", "New South Wales", "https://www.campbelltown.nsw.gov.au"),
    "10500": ("Bayside (NSW)", "New South Wales", "https://www.bayside.nsw.gov.au"),
    "12380": ("Cumberland", "New South Wales", "https://www.cumberland.nsw.gov.au"),
    "11570": ("Canterbury-Bankstown", "New South Wales", "https://www.cbcity.nsw.gov.au"),
    "12930": ("Georges River", "New South Wales", "https://www.georgesriver.nsw.gov.au"),
    "14500": ("Ku-ring-gai", "New South Wales", "https://www.krg.nsw.gov.au"),
    "18250": ("Willoughby", "New South Wales", "https://www.willoughby.nsw.gov.au"),
    "15950": ("North Sydney", "New South Wales", "https://www.northsydney.nsw.gov.au"),
    "18050": ("Waverley", "New South Wales", "https://www.waverley.nsw.gov.au"),
    "17550": ("Tweed", "New South Wales", "https://www.tweed.nsw.gov.au"),
    "16380": ("Port Macquarie-Hastings", "New South Wales", "https://www.pmhc.nsw.gov.au"),
    "17310": ("Tamworth", "New South Wales", "https://www.tamworth.nsw.gov.au"),
    "12390": ("Dubbo", "New South Wales", "https://www.dubbo.nsw.gov.au"),
    "16950": ("Shoalhaven", "New South Wales", "https://www.shoalhaven.nsw.gov.au"),
    "11800": ("Coffs Harbour", "New South Wales", "https://www.coffsharbour.nsw.gov.au"),
    # Victoria
    "25340": ("Mornington Peninsula", "Victoria", "https://www.mornpen.vic.gov.au"),
    "22670": ("Greater Dandenong", "Victoria", "https://www.greaterdandenong.vic.gov.au"),
    "21180": ("Brimbank", "Victoria", "https://www.brimbank.vic.gov.au"),
    "24970": ("Monash", "Victoria", "https://www.monash.vic.gov.au"),
    "21110": ("Boroondara", "Victoria", "https://www.boroondara.vic.gov.au"),
    "22310": ("Glen Eira", "Victoria", "https://www.gleneira.vic.gov.au"),
    "24330": ("Maribyrnong", "Victoria", "https://www.maribyrnong.vic.gov.au"),
    "21890": ("Darebin", "Victoria", "https://www.darebin.vic.gov.au"),
    "27350": ("Yarra", "Victoria", "https://www.yarracity.vic.gov.au"),
    "26350": ("Stonnington", "Victoria", "https://www.stonnington.vic.gov.au"),
    "25900": ("Port Phillip", "Victoria", "https://www.portphillip.vic.gov.au"),
    "25060": ("Moonee Valley", "Victoria", "https://www.mvcc.vic.gov.au"),
    "27260": ("Wyndham", "Victoria", "https://www.wyndham.vic.gov.au"),
    "27070": ("Whittlesea", "Victoria", "https://www.whittlesea.vic.gov.au"),
    "24650": ("Melton", "Victoria", "https://www.melton.vic.gov.au"),
    "27450": ("Yarra Ranges", "Victoria", "https://www.yarraranges.vic.gov.au"),
    "21450": ("Cardinia", "Victoria", "https://www.cardinia.vic.gov.au"),
    "22830": ("Greater Shepparton", "Victoria", "https://www.greatershepparton.com.au"),
    "23810": ("Latrobe (Vic.)", "Victoria", "https://www.latrobe.vic.gov.au"),
    # Queensland (non-LGAQ hosts hoped; walled ones get documented)
    "33220": ("Fraser Coast", "Queensland", "https://www.frasercoast.qld.gov.au"),
    "34770": ("Mackay", "Queensland", "https://www.mackay.qld.gov.au"),
    "36370": ("Rockhampton", "Queensland", "https://www.rockhamptonregion.qld.gov.au"),
    "33360": ("Gladstone", "Queensland", "https://www.gladstone.qld.gov.au"),
    "35740": ("Noosa", "Queensland", "https://www.noosa.qld.gov.au"),
    "37310": ("Western Downs", "Queensland", "https://www.wdrc.qld.gov.au"),
    "36510": ("Scenic Rim", "Queensland", "https://www.scenicrim.qld.gov.au"),
    "33620": ("Gympie", "Queensland", "https://www.gympie.qld.gov.au"),
    # South Australia
    "41060": ("Charles Sturt", "South Australia", "https://www.charlessturt.sa.gov.au"),
    "45890": ("Port Adelaide Enfield", "South Australia", "https://www.cityofpae.sa.gov.au"),
    "47700": ("Tea Tree Gully", "South Australia", "https://www.ttg.sa.gov.au"),
    "44340": ("Mitcham", "South Australia", "https://www.mitchamcouncil.sa.gov.au"),
    "40700": ("Burnside", "South Australia", "https://www.burnside.sa.gov.au"),
    "45290": ("Norwood Payneham and St Peters", "South Australia", "https://www.npsp.sa.gov.au"),
    "47980": ("Unley", "South Australia", "https://www.unley.sa.gov.au"),
    "42600": ("Holdfast Bay", "South Australia", "https://www.holdfast.sa.gov.au"),
    "44550": ("Mount Barker", "South Australia", "https://www.mountbarker.sa.gov.au"),
    "45040": ("Murray Bridge", "South Australia", "https://www.murraybridge.sa.gov.au"),
    # Western Australia
    "53780": ("Gosnells", "Western Australia", "https://www.gosnells.wa.gov.au"),
    "50210": ("Armadale", "Western Australia", "https://www.armadale.wa.gov.au"),
    "50420": ("Bayswater", "Western Australia", "https://www.bayswater.wa.gov.au"),
    "51330": ("Canning", "Western Australia", "https://www.canning.wa.gov.au"),
    "55320": ("Melville", "Western Australia", "https://www.melvillecity.com.au"),
    "57840": ("South Perth", "Western Australia", "https://www.southperth.wa.gov.au"),
    "58570": ("Vincent", "Western Australia", "https://www.vincent.wa.gov.au"),
    "51310": ("Cambridge", "Western Australia", "https://www.cambridge.wa.gov.au"),
    "56580": ("Nedlands", "Western Australia", "https://www.nedlands.wa.gov.au"),
    "50490": ("Belmont", "Western Australia", "https://www.belmont.wa.gov.au"),
    "54830": ("Kwinana", "Western Australia", "https://www.kwinana.wa.gov.au"),
    "51260": ("Busselton", "Western Australia", "https://www.busselton.wa.gov.au"),
    # Tasmania
    "63610": ("Kingborough", "Tasmania", "https://www.kingborough.tas.gov.au"),
    "61610": ("Devonport", "Tasmania", "https://www.devonport.tas.gov.au"),
    "60610": ("Burnie", "Tasmania", "https://www.burnie.tas.gov.au"),
    "63010": ("Huon Valley", "Tasmania", "https://www.huonvalley.tas.gov.au"),
    # Northern Territory
    "70200": ("Alice Springs", "Northern Territory", "https://www.alicesprings.nt.gov.au"),
    "72300": ("Litchfield", "Northern Territory", "https://www.litchfield.nt.gov.au"),
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
