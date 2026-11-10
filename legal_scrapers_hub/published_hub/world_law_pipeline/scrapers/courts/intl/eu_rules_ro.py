"""Romanian codes from the official Portal Legislativ (legislatie.just.ro, Ministry of Justice). The portal is unreachable directly from the box (connection failure), so the pages are read from the
Internet Archive snapshot web.archive.org/web/2026id_/https://legislatie.just.ro/Public/DetaliiDocument/<id> (CPP snapshot 2026-06-26): CPP (Legea 135/2010, id 120611), CPC (Legea 134/2010 R, id 140271). -> data/ro/ro_rules.jsonl"""
import sys, hashlib, urllib.request
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
from bs4 import BeautifulSoup
DOCS = [("ro-cpp", "Codul de procedură penală (Legea 135/2010), consolidated, Portal Legislativ via Wayback", 120611), ("ro-cpc", "Codul de procedură civilă (Legea 134/2010, republicată), consolidated, Portal Legislativ via Wayback", 140271)]
def tx(e): return re.sub(r"\s+", " ", e.get_text(" ")).strip()
def main():
    rows = []
    for sid, name, did in DOCS:
        p = f"{RAW}/intl_ro_{did}.html"
        if not os.path.exists(p):
            time.sleep(2.0); open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(f"https://web.archive.org/web/2026id_/https://legislatie.just.ro/Public/DetaliiDocument/{did}", headers={"User-Agent": UA}), timeout=120).read())
        raw = open(p, "rb").read(); sha = hashlib.sha256(raw).hexdigest(); s = BeautifulSoup(raw.decode("utf8", "replace"), "lxml"); n = 0; seen = {}
        for a in s.find_all("span", id=re.compile(r"^id_art[A-Z]\d+$")):
            t = a.find("span", class_="S_ART_TTL"); b = a.find("span", class_="S_ART_BDY")
            if not t or not b: continue
            num = tx(t); den = a.find("span", class_="S_ART_DEN"); den = tx(den) if den else None
            body = tx(b)
            if len(body) < 8 or re.fullmatch(r"\(?(abrogat|Abrogat)[^)]*\)?\.?", body): continue
            seen[num] = seen.get(num, 0) + 1
            rows.append(dict(rule_id=f"{sid}:{num}" + (f"~{seen[num]}" if seen[num] > 1 else ""), rule_set_id=sid, court_id=None, jurisdiction="RO", rule_set=name, rule_number=num, title=den or None, text=body, effective_date=None, pdf_path=None, pdf_sha256=None,
                             source_sha256=sha, source_url=f"https://legislatie.just.ro/Public/DetaliiDocument/{did}", site_policy="archive:wayback (portal unreachable from box)", retrieved_at=NOW(),
                             license="Romanian official legislation (Legea 8/1996 art. 9: legal acts not protected)", language="ro")); n += 1
        print(sid, n, flush=True)
    os.makedirs(f"{ROOT}/data/ro", exist_ok=True); wjl(f"{ROOT}/data/ro/ro_rules.jsonl", rows); print("RO rules", len(rows))
if __name__ == "__main__": main()
