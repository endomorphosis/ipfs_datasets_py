"""Slovak procedural codes from the binding Slov-Lex PDFs (static.slov-lex.sk/pdf/SK/ZZ/<yr>/<n>/ZZ_<yr>_<n>_<effective>.pdf; official Zbierka zakonov SR, public domain Autorsky zakon s.5):
CSP 160/2015 (eff. 2026-07-15), Trestny poriadok 301/2005 (eff. 2026-08-18), SSP 162/2015 (eff. 2026-06-12). -> data/sk/sk_rules.jsonl; PDFs cached in rules/raw."""
import sys, hashlib, subprocess, urllib.request
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
DOCS = [("sk-csp", "Civilný sporový poriadok (160/2015 Z. z.)", 2015, 160, "20260715"), ("sk-tp", "Trestný poriadok (301/2005 Z. z.)", 2005, 301, "20260818"), ("sk-ssp", "Správny súdny poriadok (162/2015 Z. z.)", 2015, 162, "20260612")]
SEC = re.compile(r"^(§ \d+[a-z]{0,2}|Čl\. \d+)\s*$")
FOOT = re.compile(r"^(Strana \d+|Zbierka zákonov Slovenskej republiky|\d+/\d{4} Z\. z\.|Vydavate.* Zbierky.*|správca obsahu.*|helpdesk@slov-lex.*|Račianska.*|Ministerstvo spravodlivosti.*|tel\.:.*)\s*$")
def main():
    rows = []
    for sid, name, yr, no, eff in DOCS:
        pdf = f"{RAW}/intl_sk_{yr}_{no}_{eff}.pdf"; url = f"https://static.slov-lex.sk/pdf/SK/ZZ/{yr}/{no}/ZZ_{yr}_{no}_{eff}.pdf"
        if not os.path.exists(pdf):
            time.sleep(2.0)
            try: open(pdf, "wb").write(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120).read())
            except Exception as e: print("miss", sid, e); continue
        raw = open(pdf, "rb").read(); sha = hashlib.sha256(raw).hexdigest()
        txt = subprocess.run(["pdftotext", pdf, "-"], capture_output=True, text=True).stdout.replace("\x0c", "\n")
        lines = [l.rstrip() for l in txt.split("\n") if not FOOT.match(l.strip())]; idx = [i for i, l in enumerate(lines) if SEC.match(l)]; n = 0; seen = {}
        for k, i in enumerate(idx):
            end = idx[k + 1] if k + 1 < len(idx) else len(lines); seg = [l for l in lines[i + 1:end]]
            while seg and (not seg[-1].strip() or (len(seg[-1]) < 90 and not seg[-1].rstrip().endswith((".", ";", ":", ",", ")", "—")) and k + 1 < len(idx)) or re.match(r"^(\S+ )?(ČASŤ|HLAVA|DIEL|ODDIEL|Čl\.)", seg[-1].strip())): seg.pop()
            title = None
            if len(seg) > 1 and 3 < len(seg[0]) < 90 and not seg[0].lstrip().startswith("(") and not seg[0].rstrip().endswith((".", ";", ":", ",")) and re.match(r"^\(?\d", seg[1].strip()): title = seg.pop(0).strip()
            body = re.sub(r"\s+", " ", " ".join(seg)).strip(); num = SEC.match(lines[i]).group(1)
            if len(body) < 8 or re.fullmatch(r"\(?(Zrušený|zrušený)[^)]*\)?\.?", body): continue
            seen[num] = seen.get(num, 0) + 1
            rows.append(dict(rule_id=f"{sid}:{num}" + (f"~{seen[num]}" if seen[num] > 1 else ""), rule_set_id=sid, court_id=None, jurisdiction="SK", rule_set=name, rule_number=num, title=title, text=body,
                             effective_date=f"{eff[:4]}-{eff[4:6]}-{eff[6:]}", pdf_path=None, pdf_sha256=sha, source_sha256=sha, source_url=url, site_policy="robots_allowed:static_pdf", retrieved_at=NOW(),
                             license="Slovak official legislation (Zákon 185/2015 Z. z. §5: legal acts not protected); Slov-Lex binding PDF", language="sk")); n += 1
        print(sid, n, flush=True)
    os.makedirs(f"{ROOT}/data/sk", exist_ok=True); wjl(f"{ROOT}/data/sk/sk_rules.jsonl", rows); print("SK rules", len(rows))
if __name__ == "__main__": main()
