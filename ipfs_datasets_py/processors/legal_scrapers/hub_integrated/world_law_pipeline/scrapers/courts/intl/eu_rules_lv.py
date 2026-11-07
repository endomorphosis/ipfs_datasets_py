"""Latvian procedural laws from the official likumi.lv (Latvijas Vestnesis). likumi.lv is unreachable directly from the box, so pages come from the Internet Archive (web.archive.org/web/2026id_/https://likumi.lv/ta/id/<id>, gzip):
Civilprocesa likums (50500), Kriminalprocesa likums (107820), Administrativa procesa likums (55567). Snapshot date may predate latest amendments. -> data/lv/lv_rules.jsonl"""
import sys, hashlib, urllib.request, gzip
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
from bs4 import BeautifulSoup
DOCS = [("lv-cpl", "Civilprocesa likums", 50500), ("lv-kpl", "Kriminālprocesa likums", 107820), ("lv-apl", "Administratīvā procesa likums", 55567)]
def tx(e): return re.sub(r"\s+", " ", e.get_text(" ")).strip()
def main():
    rows = []
    for sid, name, did in DOCS:
        p = f"{RAW}/intl_lv_{did}.html"
        if not os.path.exists(p):
            time.sleep(2.0); b = urllib.request.urlopen(urllib.request.Request(f"https://web.archive.org/web/2026id_/https://likumi.lv/ta/id/{did}", headers={"User-Agent": UA}), timeout=120).read()
            open(p, "wb").write(gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b)
        raw = open(p, "rb").read(); sha = hashlib.sha256(raw).hexdigest(); s = BeautifulSoup(raw.decode("utf8", "replace"), "lxml"); head = None; n = 0; seen = {}
        for d in s.find_all("div", class_=re.compile(r"^TV21[2-3]")):
            c = " ".join(d.get("class") or [])
            if "TV212" in c: head = tx(d); continue
            if d.get("data-pfx") != "p": continue
            hp = d.find("p", class_="TVP"); 
            if not hp: continue
            ht = tx(hp); m = re.match(r"^(\d+(?:\.\d+)?)\.\s?pants\.?\s*(.*)$", ht)
            if not m: continue
            body = " ".join(tx(x) for x in d.find_all("p") if x is not hp)
            if len(body) < 8 or re.search(r"^\(?(Izslēgts|izslēgts)", body): continue
            num = f"{m.group(1)}. pants"; seen[num] = seen.get(num, 0) + 1
            rows.append(dict(rule_id=f"{sid}:{num}" + (f"~{seen[num]}" if seen[num] > 1 else ""), rule_set_id=sid, court_id=None, jurisdiction="LV", rule_set=name, rule_number=num, title=" — ".join(x for x in (head, m.group(2)) if x) or None, text=body,
                             effective_date=None, pdf_path=None, pdf_sha256=None, source_sha256=sha, source_url=f"https://likumi.lv/ta/id/{did}", site_policy="archive:wayback (likumi.lv unreachable from box)", retrieved_at=NOW(),
                             license="Latvian official legislation (Autortiesību likums 6. pants: not protected); likumi.lv", language="lv")); n += 1
        print(sid, n, flush=True)
    os.makedirs(f"{ROOT}/data/lv", exist_ok=True); wjl(f"{ROOT}/data/lv/lv_rules.jsonl", rows); print("LV rules", len(rows))
if __name__ == "__main__": main()
