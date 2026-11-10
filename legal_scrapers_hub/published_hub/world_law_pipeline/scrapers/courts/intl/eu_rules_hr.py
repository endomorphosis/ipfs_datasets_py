"""Croatian procedural statutes from the official Narodne novine (narodne-novine.nn.hr): ZPP official consolidated text NN 148/2011 and ZKP as published NN 152/2008. The official NN texts are OUTDATED
(ZPP lacks NN 70/2019, 80/2022, 114/2022, 155/2023, 146/2025; ZKP lacks all amendments); current consolidations exist only as unofficial private texts, which are not used. -> data/hr/hr_rules.jsonl"""
import sys, hashlib, urllib.request
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
from bs4 import BeautifulSoup
DOCS = [("hr-zpp", "Zakon o parničnom postupku (NN 148/2011 pročišćeni tekst; later amendments NOT applied)", "2011_12_148_2993", "2011-12-23"),
        ("hr-zkp", "Zakon o kaznenom postupku (NN 152/2008 as published; amendments NOT applied)", "2008_12_152_4149", "2008-12-24")]
def tx(e): return re.sub(r"\s+", " ", e.get_text(" ")).strip()
def main():
    rows = []
    for sid, name, pid, eff in DOCS:
        p = f"{RAW}/intl_hr_{pid}.html"
        if not os.path.exists(p): time.sleep(2.0); open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(f"https://narodne-novine.nn.hr/clanci/sluzbeni/full/{pid}.html", headers={"User-Agent": UA}), timeout=120).read())
        raw = open(p, "rb").read(); sha = hashlib.sha256(raw).hexdigest(); s = BeautifulSoup(raw.decode("utf8", "replace"), "lxml"); cur = None; n = 0; seen = {}; part = None
        def flush():
            nonlocal cur, n
            if cur and len(cur["t"].strip()) > 8:
                num = cur["n"]; seen[num] = seen.get(num, 0) + 1
                rows.append(dict(rule_id=f"{sid}:{num}" + (f"~{seen[num]}" if seen[num] > 1 else ""), rule_set_id=sid, court_id=None, jurisdiction="HR", rule_set=name, rule_number=num, title=cur["h"], text=re.sub(r"\s+", " ", cur["t"]).strip(),
                                 effective_date=eff, pdf_path=None, pdf_sha256=None, source_sha256=sha, source_url=f"https://narodne-novine.nn.hr/clanci/sluzbeni/{pid}.html", site_policy="robots_allowed", retrieved_at=NOW(),
                                 license="Croatian official legislation (Zakon o autorskom pravu čl. 8: not protected); Narodne novine", language="hr")); n += 1
            cur = None
        head = None
        for el in s.find_all("p"):
            c = " ".join(el.get("class") or []); t = tx(el)
            if c == "clanak" and t.startswith("Članak"): flush(); cur = dict(n=t.rstrip("."), t="", h=head); continue
            if c in ("t-12-9-sred", "t-11-9-sred") or c.startswith("t-11-9-sred"): head = t; flush(); continue
            if cur is not None and not c.startswith("clanak-kurziv") and t: cur["t"] += " " + t
        flush(); print(sid, n, flush=True)
    os.makedirs(f"{ROOT}/data/hr", exist_ok=True); wjl(f"{ROOT}/data/hr/hr_rules.jsonl", rows); print("HR rules", len(rows))
if __name__ == "__main__": main()
