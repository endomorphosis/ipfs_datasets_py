"""Australian rules of procedure from official state legislation sites (Qld UCPR 1999 live; NSW UCPR 2005 via Wayback copy because live site returns 403 to the box) -> data/au/au_rules.jsonl + crosswalk."""
import sys, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
from lxml import html as lh
def ws(s): return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()
def row(sid, name, jur, num, title, text, src, sha, pol, lic):
    return dict(rule_id=f"{sid}:{num}", rule_set_id=sid, court_id=None, jurisdiction=jur, rule_set=name, rule_number=num, title=title, text=text, effective_date=None, pdf_path=None, pdf_sha256=None, source_sha256=sha,
                source_url=src, site_policy=pol, retrieved_at=NOW(), license=lic, language="en")
def qld():
    raw = open(f"{RAW}/intl_au_qld_ucpr_whole.html", "rb").read(); sha = hashlib.sha256(raw).hexdigest(); d = lh.fromstring(raw); out = []
    heads = [p for p in d.iter("p") if (p.get("class") or "") == "HeadingParagraph" and p.find(".//a[@name]") is not None and (p.find(".//a").get("name") or "").startswith("sec.")]
    for p in heads:
        num = ws(p.find(".//b").text_content() if p.find(".//b") is not None else ""); ti = p.find(".//span[@class='HeadingName']"); title = ws(ti.text_content()) if ti is not None else None
        parts = []
        for s in p.itersiblings():
            c = s.get("class") or ""
            if s.tag == "p" and "Heading" in c: break
            if "history-note" in c and s.tag == "blockquote": continue
            parts.append(ws(s.text_content()))
        text = ws(" ".join(x for x in parts if x))
        if num and len(text) > 10: out.append(row("au-qld-ucpr", "Uniform Civil Procedure Rules 1999 (Qld)", "AU-QLD", num, title, text, "https://www.legislation.qld.gov.au/view/html/inforce/current/sl-1999-0111", sha, "robots_allowed", "CC-BY-4.0 (State of Queensland)"))
    return out
def nsw():
    raw = open(f"{RAW}/intl_au_nsw_ucpr_whole.html", "rb").read(); sha = hashlib.sha256(raw).hexdigest(); d = lh.fromstring(raw); out = []
    for e in d.iter("div", "blockquote"):
        i = e.get("id") or ""
        if re.fullmatch(r"sec\.[\dA-Z]+(?:\.[\dA-Z]+)?", i) and "frag-clause" in (e.get("class") or ""):
            h = e.find(".//span[@class='frag-heading']"); title = ws(h.text_content()) if h is not None else None
            text = ws(e.text_content()); text = text[len(title):].strip() if title and text.startswith(title) else text
            if len(text) > 10 and not any(x["rule_number"] == i[4:] for x in out): out.append(row("au-nsw-ucpr", "Uniform Civil Procedure Rules 2005 (NSW)", "AU-NSW", i[4:], title, text, "https://legislation.nsw.gov.au/view/html/inforce/current/sl-2005-0418", sha, "archive_wayback(live_403_to_box)", "CC-BY-4.0 (NSW Parliamentary Counsel)"))
    return out
def build():
    rows = []; xw = []
    for fn, sid, courts in ((qld, "au-qld-ucpr", ["au-qld-supreme-court", "au-qld-intermediate-court", "au-qld-lower-court"]), (nsw, "au-nsw-ucpr", ["au-nsw-supreme-court", "au-nsw-intermediate-court", "au-nsw-lower-court"])):
        r = fn(); rows += r; print(sid, len(r), flush=True)
        for c in courts: xw.append(dict(rule_set_id=sid, rule_set=r[0]["rule_set"] if r else sid, court_id=c, jurisdiction=r[0]["jurisdiction"] if r else None, basis="rule set applies to this court (per rule set scope)", source_url=r[0]["source_url"] if r else None, linked_rows="new"))
    wjl(f"{ROOT}/data/au/au_rules.jsonl", rows); wjl(f"{ROOT}/data/au/au_rules_crosswalk.jsonl", xw); print("AU rules", len(rows))
if __name__ == "__main__": build()
