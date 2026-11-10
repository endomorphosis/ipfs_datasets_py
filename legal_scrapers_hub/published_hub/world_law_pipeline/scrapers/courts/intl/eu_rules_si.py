"""Slovenian procedural statutes from the official Uradni list RS (uradni-list.si, official consolidated texts adopted by Drzavni zbor): ZPP-UPB3 (UL RS 73/07; later amendments NOT applied) and
ZKP-UPB16 (UL RS 176/2021; later amendments NOT applied). Current unofficial consolidations (PISRS) are a JS app and not used. -> data/si/si_rules.jsonl"""
import sys, hashlib, urllib.request
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
from bs4 import BeautifulSoup
DOCS = [("si-zpp", "Zakon o pravdnem postopku (ZPP-UPB3, Uradni list RS 73/07; later amendments not applied)", "2007-01-3965", "https://www.uradni-list.si/glasilo-uradni-list-rs/vsebina/2007-01-3965", "2007-08-13"),
        ("si-zkp", "Zakon o kazenskem postopku (ZKP-UPB16, Uradni list RS 176/21; later amendments not applied)", "2021-01-3462", "https://www.uradni-list.si/glasilo-uradni-list-rs/vsebina/2021-01-3462", "2021-11-12")]
ART = re.compile(r"^(\d+(?:\.[a-z]+)?)\. člen$")
def tx(e): return re.sub(r"\s+", " ", e.get_text(" ")).strip()
def main():
    rows = []
    for sid, name, pid, src, eff in DOCS:
        p = f"{RAW}/intl_si_{pid}.html"
        if not os.path.exists(p): time.sleep(2.0); open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": UA}), timeout=120).read())
        raw = open(p, "rb").read(); sha = hashlib.sha256(raw).hexdigest(); s = BeautifulSoup(raw.decode("utf8", "replace"), "lxml"); box = s.find("div", class_="content-segments") or s
        cur = None; n = 0; seen = {}; head = None
        def flush():
            nonlocal cur, n
            if cur and len(cur["t"].strip()) > 8:
                num = cur["n"]; seen[num] = seen.get(num, 0) + 1
                rows.append(dict(rule_id=f"{sid}:{num}" + (f"~{seen[num]}" if seen[num] > 1 else ""), rule_set_id=sid, court_id=None, jurisdiction="SI", rule_set=name, rule_number=num, title=cur["h"], text=re.sub(r"\s+", " ", cur["t"]).strip(),
                                 effective_date=eff, pdf_path=None, pdf_sha256=None, source_sha256=sha, source_url=src, site_policy="robots_allowed", retrieved_at=NOW(), license="Slovenian official legislation (ZASP čl. 9: not protected); Uradni list RS", language="sl")); n += 1
            cur = None
        for d in box.find_all("div", class_=re.compile(r"^esegment")):
            c = " ".join(d.get("class") or []); t = tx(d)
            if not t: continue
            m = ART.match(t)
            if m: flush(); cur = dict(n=f"{m.group(1)}. člen", t="", h=head); continue
            if c.startswith("esegment_h") and len(t) < 160:
                head = t; 
                if cur is not None and not re.match(r"^\(", t): flush()
                elif cur is not None: cur["t"] += " " + t
                continue
            if cur is not None: cur["t"] += " " + t
        flush(); print(sid, n, flush=True)
    os.makedirs(f"{ROOT}/data/si", exist_ok=True); wjl(f"{ROOT}/data/si/si_rules.jsonl", rows); print("SI rules", len(rows))
if __name__ == "__main__": main()
