"""Finnish procedural statutes from Finlex open data (opendata.finlex.fi AKN XML, CC BY 4.0): Oikeudenkaari 4/1734 and Laki oikeudenkaynnista hallintoasioissa 808/2019 (consolidated 'ajantasa'),
plus Laki oikeudenkaynnista rikosasioissa 689/1997 and Ulosottokaari 705/2007 (only the as-published `statute` text is open; later amendments NOT applied -- tagged in rule_set). -> data/fi/fi_rules.jsonl"""
import sys, hashlib, urllib.request
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
from lxml import etree
B = "https://opendata.finlex.fi/finlex/avoindata/v1/akn/fi/act"; A = "{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}"
DOCS = [("fi-ok", "Oikeudenkäymiskaari (4/1734), ajantasainen", "statute-consolidated/1734/4-000/fin@20260885", "https://finlex.fi/fi/lainsaadanto/saadoskokoelma/1734/4"),
        ("fi-halpl", "Laki oikeudenkäynnistä hallintoasioissa (808/2019), ajantasainen", "statute-consolidated/2019/808/fin@", "https://finlex.fi/fi/lainsaadanto/saadoskokoelma/2019/808"),
        ("fi-ork", "Laki oikeudenkäynnistä rikosasioissa (689/1997), as published (amendments not applied)", "statute/1997/689/fin@", "https://finlex.fi/fi/lainsaadanto/saadoskokoelma/1997/689"),
        ("fi-ulosotto", "Ulosottokaari (705/2007), as published (amendments not applied)", "statute/2007/705/fin@", "https://finlex.fi/fi/lainsaadanto/saadoskokoelma/2007/705")]
def tx(e): return re.sub(r"\s+", " ", " ".join(e.itertext())).strip()
def main():
    rows = []
    for sid, name, path, src in DOCS:
        p = f"{RAW}/intl_fi_{sid}.xml"
        if not os.path.exists(p):
            time.sleep(2.0)
            try: open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(f"{B}/{path}", headers={"User-Agent": UA, "Accept": "application/xml"}), timeout=120).read())
            except Exception as e: print("miss", sid, e); continue
        raw = open(p, "rb").read(); sha = hashlib.sha256(raw).hexdigest(); root = etree.fromstring(raw); n = 0; seen = {}
        for s in root.iter(A + "section"):
            num = s.findtext(A + "num"); 
            if not num: continue
            ch = next((a for a in s.iterancestors(A + "chapter")), None); chn = (ch.findtext(A + "num") or "").strip() if ch is not None else ""
            cht = tx(ch.find(A + "heading")) if ch is not None and ch.find(A + "heading") is not None else None
            sh = s.find(A + "heading"); sht = tx(sh) if sh is not None else None
            body = " ".join(tx(c) for c in s if c.tag not in (A + "num", A + "heading"))
            if len(body) < 8 or re.fullmatch(r"\(?\s*kumottu.*", body, re.I) or body.lower().startswith(("(kumottu", "kumottu")): continue
            rn = (chn + " " if chn else "") + num.strip(); seen[rn] = seen.get(rn, 0) + 1
            rows.append(dict(rule_id=f"{sid}:{rn}" + (f"~{seen[rn]}" if seen[rn] > 1 else ""), rule_set_id=sid, court_id=None, jurisdiction="FI", rule_set=name, rule_number=rn, title=" — ".join(x for x in (cht, sht) if x) or None, text=body,
                             effective_date=None, pdf_path=None, pdf_sha256=None, source_sha256=sha, source_url=src, site_policy="robots_allowed:open_data_api", retrieved_at=NOW(), license="CC BY 4.0 (Finlex open data, Oikeusministeriö)", language="fi")); n += 1
        print(sid, n, flush=True)
    os.makedirs(f"{ROOT}/data/fi", exist_ok=True); wjl(f"{ROOT}/data/fi/fi_rules.jsonl", rows); print("FI rules", len(rows))
if __name__ == "__main__": main()
