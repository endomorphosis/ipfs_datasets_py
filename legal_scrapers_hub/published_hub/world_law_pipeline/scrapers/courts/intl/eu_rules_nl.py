"""Dutch procedural codes from the official BWB repository (repository.officiele-overheidspublicaties.nl, toestand XML; CC0 / public domain, Auteurswet art. 11) -> data/nl/nl_rules.jsonl"""
import sys, hashlib, urllib.request
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
from lxml import etree
CODES = [("nl-rv", "Wetboek van Burgerlijke Rechtsvordering (Rv)", "BWBR0001827"), ("nl-sv", "Wetboek van Strafvordering (Sv)", "BWBR0001903"), ("nl-awb", "Algemene wet bestuursrecht (Awb)", "BWBR0005537"),
         ("nl-fw", "Faillissementswet (Fw)", "BWBR0001860")]
def ws(s): return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()
def main():
    rows = []
    for sid, name, bwb in CODES:
        p = f"{RAW}/intl_nl_{bwb}.xml"; url = f"https://repository.officiele-overheidspublicaties.nl/bwb/{bwb}/geldend/{bwb}.xml"
        if not os.path.exists(p):
            time.sleep(2.0)
            try: open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120).read())
            except Exception as e: print("miss", sid, e); continue
        raw = open(p, "rb").read()
        if len(raw) < 1000: os.remove(p); print("empty", sid); continue
        sha = hashlib.sha256(raw).hexdigest(); root = etree.fromstring(raw); n = 0; seen = {}
        eff = root.get("inwerkingtreding")
        for a in root.iter("artikel"):
            kop = a.find("kop"); lab = ws(kop.findtext("label")) if kop is not None else "Artikel"; nr = ws("".join(kop.find("nr").itertext())) if kop is not None and kop.find("nr") is not None else None
            if not nr: continue
            titel = ws("".join(kop.find("titel").itertext())) if kop is not None and kop.find("titel") is not None else None
            parts = []
            for ch in a:
                if ch.tag in ("kop", "meta-data"): continue
                t = ws(" ".join(ch.itertext()))
                if t: parts.append(t)
            text = ws(" ".join(parts))
            if len(text) < 8 or "[Vervallen]" == text or text.lower().startswith("vervallen"): continue
            num = f"{lab} {nr}"; seen[num] = seen.get(num, 0) + 1
            rows.append(dict(rule_id=f"{sid}:{num}" + (f"~{seen[num]}" if seen[num] > 1 else ""), rule_set_id=sid, court_id=None, jurisdiction="NL", rule_set=name, rule_number=num, title=titel, text=text, effective_date=eff, pdf_path=None, pdf_sha256=None,
                             source_sha256=sha, source_url=f"https://wetten.overheid.nl/{bwb}/", site_policy="robots_allowed", retrieved_at=NOW(), license="CC0-1.0 (wetten.overheid.nl; Auteurswet art. 11 public domain)", language="nl")); n += 1
        print(sid, n, flush=True)
    os.makedirs(f"{ROOT}/data/nl", exist_ok=True); wjl(f"{ROOT}/data/nl/nl_rules.jsonl", rows); print("NL rules", len(rows))
if __name__ == "__main__": main()
