"""NZ court rules from legislation.govt.nz (live site answers the box with an AWS-WAF challenge, so the Wayback copy of the PCO 'whole' page is read; CC-BY 4.0 / NZ Govt open licence).
-> data/nz/nz_rules.jsonl"""
import sys, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW, cached
from lxml import html as lh
SETS = [  # id, name, path, courts
 ("nz-hcr-2016", "High Court Rules 2016 (LI 2016/225)", "regulation/public/2016/0225", ["nz-high-court"]),
 ("nz-dcr-2014", "District Court Rules 2014 (LI 2014/179)", "regulation/public/2014/0179", ["nz-district-court"]),
 ("nz-scr-2004", "Supreme Court Rules 2004 (SR 2004/199)", "regulation/public/2004/0199", ["nz-supreme-court"]),
 ("nz-coa-civil-2005", "Court of Appeal (Civil) Rules 2005 (SR 2005/69)", "regulation/public/2005/0069", ["nz-court-of-appeal"]),
 ("nz-cpr-2012", "Criminal Procedure Rules 2012 (SR 2012/415)", "regulation/public/2012/0415", ["nz-high-court", "nz-district-court", "nz-court-of-appeal", "nz-supreme-court"]),
 ("nz-fcr-2002", "Family Court Rules 2002 (SR 2002/261)", "regulation/public/2002/0261", ["nz-family-court"]),
]
def ws(s): return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()
def get_set(path, key):
    for pre in ("https://www.legislation.govt.nz/", "https://legislation.govt.nz/"):
        url = f"https://web.archive.org/web/2026id_/{pre}{path}/latest/whole.html"
        b, u, pol = cached(url, key, delay=3.0)
        if b and len(b) > 20000 and b"<html" in b[:2000].lower() + b: return b, u, pol
    return None, None, None
def parse(b, sid, name, src, pol):
    sha = hashlib.sha256(b).hexdigest(); d = lh.fromstring(b); out = {}; eff = None
    m = re.search(rb"\(as at (\d{1,2} \w+ \d{4})\)", b)
    if m:
        import datetime
        try: eff = datetime.datetime.strptime(m.group(1).decode(), "%d %B %Y").date().isoformat()
        except Exception: pass
    for p in d.iter("div"):
        if p.get("class") != "prov": continue
        h = p.find("h5")
        if h is None: continue
        lab = h.find("span"); num = ws(lab.text_content()) if lab is not None else None
        title = ws(h.text_content()); title = title[len(num):].strip() if num and title.startswith(num) else title
        body = p.find("div[@class='prov-body']")
        if body is None or not num: continue
        for x in body.xpath(".//div[@class='history']|.//p[@class='cf']"): x.getparent().remove(x)
        parts = []
        for e in body.iter("p", "td"):
            t = ws(e.text_content())
            if t: parts.append(t)
        text = ws(" ".join(parts))
        if len(text) < 15 or num in out: continue
        out[num] = dict(rule_id=f"{sid}:{num}", rule_set_id=sid, court_id=None, jurisdiction="NZ", rule_set=name, rule_number=num, title=title, text=text, effective_date=eff, pdf_path=None, pdf_sha256=None,
                        source_sha256=sha, source_url=src, site_policy=pol, retrieved_at=NOW(), license="CC-BY-4.0 (NZ Parliamentary Counsel Office)", language="en")
    return list(out.values())
def build():
    rows = []; xw = []
    for sid, name, path, courts in SETS:
        b, u, pol = get_set(path, f"intl_nz_{sid}.html")
        if not b: print(sid, "UNAVAILABLE"); continue
        r = parse(b, sid, name, u, pol); rows += r; print(sid, len(r), u, flush=True)
        for c in courts: xw.append(dict(rule_set_id=sid, rule_set=name, court_id=c, jurisdiction="NZ", basis="rule set applies to this court (per rule set scope)", source_url=u, linked_rows="new"))
    os.makedirs(f"{ROOT}/data/nz", exist_ok=True)
    wjl(f"{ROOT}/data/nz/nz_rules.jsonl", rows); wjl(f"{ROOT}/data/nz/nz_rules_crosswalk.jsonl", xw); print("NZ rules", len(rows))
if __name__ == "__main__": build()
