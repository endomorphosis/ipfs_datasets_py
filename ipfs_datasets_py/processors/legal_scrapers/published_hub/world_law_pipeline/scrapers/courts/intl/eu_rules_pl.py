"""Polish procedural codes: consolidated texts (tekst jednolity) from the Sejm ELI API (api.sejm.gov.pl/eli; Dziennik Ustaw, official, public domain art. 4 Pr.aut.)
-> data/pl/pl_rules.jsonl. PDFs kept under rules/pdf-style cache in rules/raw (not uploaded)."""
import sys, hashlib, json, subprocess, urllib.request
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW, split_rules, norm as tnorm
CODES = [("pl-kpc", "Kodeks postępowania cywilnego (KPC)", "DU/2026/468"), ("pl-kpk", "Kodeks postępowania karnego (KPK)", "DU/2026/490"), ("pl-kpa", "Kodeks postępowania administracyjnego (KPA)", "DU/2025/1691"),
         ("pl-ppsa", "Prawo o postępowaniu przed sądami administracyjnymi (PPSA)", "DU/2026/143"), ("pl-kpw", "Kodeks postępowania w sprawach o wykroczenia (KPW)", "DU/2026/1336")]
def fetch(url, p, binary=True):
    if os.path.exists(p): return open(p, "rb").read()
    time.sleep(2.0); b = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120).read(); open(p, "wb").write(b); return b
def build():
    rows = []; xw = []
    for sid, name, eli in CODES:
        meta = json.loads(fetch(f"https://api.sejm.gov.pl/eli/acts/{eli}", f"{RAW}/intl_pl_{eli.replace('/', '_')}.json"))
        pdf_name = next((t["fileName"] for t in meta.get("texts", []) if t["type"] in ("T", "O")), None)
        pdfb = fetch(f"https://api.sejm.gov.pl/eli/acts/{eli}/text.pdf", f"{RAW}/intl_pl_{eli.replace('/', '_')}.pdf")
        if pdfb[:4] != b"%PDF": print("bad pdf", sid); continue
        sha = hashlib.sha256(pdfb).hexdigest(); txt = tnorm(subprocess.run(["pdftotext", f"{RAW}/intl_pl_{eli.replace('/', '_')}.pdf", "-"], capture_output=True, text=True).stdout)
        txt = re.sub(r"(?m)^©Kancelaria Sejmu.*$|^\d{4}-\d{2}-\d{2}\s*$|^s\. \d+/\d+\s*$", "", txt)
        rs = split_rules(txt, r"^Art\.\s*(?P<num>\d+[a-zA-Z]*(?:\s?[¹²³⁴⁵⁶⁷⁸⁹⁰]+)?)\.\s*", min_len=0)
        i1 = [i for i, r in enumerate(rs[:25]) if re.fullmatch(r'1', r['num'])]
        rs = rs[i1[-1]:] if i1 else rs  # drop the announcement (Obwieszczenie) preamble
        seen = {}; n = 0
        for r in rs:
            body = re.sub(r"\s+", " ", r["text"]).strip()
            if len(body) < 8: continue
            num = "Art. " + re.sub(r"\s+", "", r["num"]); seen[num] = seen.get(num, 0) + 1
            rid = f"{sid}:{num}" + (f"~{seen[num]}" if seen[num] > 1 else "")
            rows.append(dict(rule_id=rid, rule_set_id=sid, court_id=None, jurisdiction="PL", rule_set=name, rule_number=num, title=None, text=body, effective_date=(meta.get("announcementDate")), pdf_path=None, pdf_sha256=sha, source_sha256=sha,
                             source_url=f"https://api.sejm.gov.pl/eli/acts/{eli}/text.pdf", site_policy="robots_unknown:api_documented", retrieved_at=NOW(), license="public domain (art. 4 pkt 2 Prawa autorskiego: texts of official acts)", language="pl")); n += 1
        print(sid, eli, n, flush=True)
    wjl(f"{ROOT}/data/pl/pl_rules.jsonl", rows); print("PL rules", len(rows))
if __name__ == "__main__":
    os.makedirs(f"{ROOT}/data/pl", exist_ok=True); build()
