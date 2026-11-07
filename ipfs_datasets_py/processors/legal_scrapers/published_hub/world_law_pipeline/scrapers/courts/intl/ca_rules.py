"""Canadian rules of procedure from official publishers (Justice Laws XML, e-Laws Ontario, BC Laws, Alberta King's Printer). Archive copies used where robots/TLS block live fetch -> data/ca/ca_rules.jsonl + crosswalk."""
import sys, hashlib, subprocess
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
from lxml import etree, html as lh
NOW_ = NOW()
def norm_ws(s): return re.sub(r"\s+", " ", s or "").strip()
def row(sid, name, jur, num, title, text, eff, src, sha, pol, lic, rid=None):
    return dict(rule_id=rid or f"{sid}:{num}", rule_set_id=sid, court_id=None, jurisdiction=jur, rule_set=name, rule_number=num, title=title, text=text, effective_date=eff, pdf_path=None, pdf_sha256=None,
                source_sha256=sha, source_url=src, site_policy=pol, retrieved_at=NOW_, license=lic, language="en")
def uniq(rows):
    seen = {}
    for r in rows:
        k = r["rule_id"]; n = seen.get(k, 0); seen[k] = n + 1
        if n: r["rule_id"] = f"{k}~{n}"
    return rows
def scc():
    b = open(f"{RAW}/intl_ca_scc_rules.xml", "rb").read(); sha = hashlib.sha256(b).hexdigest(); r = etree.fromstring(b); out = []; head = None
    body = r.find("Body")
    for e in body.iter():
        if e.tag == "Heading":
            t = e.find("TitleText"); head = norm_ws("".join(t.itertext())) if t is not None else head
        elif e.tag == "Section":
            lab = e.find("Label"); 
            if lab is None: continue
            mn = e.find("MarginalNote"); t = norm_ws(" ".join(x for x in e.itertext()))
            t = re.sub(r"^" + re.escape(lab.text or "") + r"\s*", "", t)
            out.append(row("ca-scc-rules", "Rules of the Supreme Court of Canada (SOR/2002-156)", "CA", lab.text.strip(), (norm_ws("".join(mn.itertext())) if mn is not None else head), t, e.get("{http://justice.gc.ca/lims}inforce-start-date"),
                           "https://laws-lois.justice.gc.ca/eng/regulations/SOR-2002-156/index.html", sha, "archive_wayback(live_tls_blocked_from_box)", "Reproduction of federal law (Justice Laws Website)"))
    return uniq(out)
def ontario():
    raw = open(f"{RAW}/intl_ca_on_rcp_wb.html", "rb").read(); sha = hashlib.sha256(raw).hexdigest(); d = lh.fromstring(raw.decode("utf-8", "replace")); out = []
    cur = None; grp = None; pend = None; stop = False
    for p in d.iter("p"):
        c = p.get("class") or ""; t = norm_ws(p.text_content())
        if not t: continue
        if c.startswith("Pheadingx") and re.match(r"(TARIFF|FORMS|APPENDIX)", t, re.I) and cur: stop = True
        if stop: break
        if c.startswith("Pheading1"): grp = t; continue
        if c.startswith("headnote-e"): pend = t; continue
        if c.startswith("section-e"):
            m = re.match(r"(\d+\.\d+(?:\.\d+)?)\b\s*(.*)", t)
            if m:
                if cur: out.append(cur)
                cur = row("ca-on-rcp", "Rules of Civil Procedure (R.R.O. 1990, Reg. 194)", "CA-ON", m.group(1), pend, t, None, "https://www.ontario.ca/laws/regulation/900194", sha, "archive_wayback", "Open Government Licence – Ontario"); cur["rule_group"] = grp; continue
        if cur and c and (c.startswith(("subsection", "clause", "subclause", "paragraph", "para", "section", "Pindent", "continued", "definition", "tablebody", "table"))): cur["text"] += "\n" + t
    if cur: out.append(cur)
    return uniq(out)
def bc():
    raw = open(f"{RAW}/intl_ca_bc_scr_multi.html", "rb").read(); sha = hashlib.sha256(raw).hexdigest(); d = lh.fromstring(raw); out = []; cur = None; part = None
    body = d.find(".//body")
    for e in body.iter():
        if e.tag == "p" and "part" in (e.get("class") or "").split():
            t = norm_ws(e.text_content()); m = re.match(r"Rule (\d+-\d+)\s*(?:[—-]\s*(.*))?$", t)
            if m:
                if cur: out.append(cur)
                cur = row("ca-bc-scr", "Supreme Court Civil Rules (B.C. Reg. 168/2009)", "CA-BC", f"Rule {m.group(1)}", m.group(2) or None, "", "2010-07-01", "https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/168_2009_01", sha, "archive_wayback(robots_disallowed_live)", "Queen's/King's Printer for British Columbia (Open Government Licence – BC)"); cur["rule_group"] = part
            else:
                if cur: out.append(cur); cur = None
                part = t
        elif cur is not None and e.tag == "p":
            t = norm_ws(e.text_content())
            if t: cur["text"] += (("\n" if cur["text"] else "") + t)
        elif cur is not None and e.tag == "h4":
            pass
    if cur: out.append(cur)
    return uniq([r for r in out if len(r["text"]) > 20])
def alberta():
    subprocess.run(["pdftotext", "-layout", f"{RAW}/intl_ca_ab_roc.pdf", "/tmp/ab.txt"], check=True)
    sha = hashlib.sha256(open(f"{RAW}/intl_ca_ab_roc.pdf", "rb").read()).hexdigest()
    ls = open("/tmp/ab.txt", encoding="utf-8", errors="replace").read().split("\n")
    start = next(i for i, l in enumerate(ls) if re.search(r"^\W*Rule 1\.1\s+ALBERTA RULES OF COURT", l) or (i > 600 and re.match(r"^\s+1\.1\s+", l)))
    pat = re.compile(r"^\s{6,18}(\d{1,2}\.\d{1,3})(?:\(\d+\))?\s+(\S.*)$")
    hdr = re.compile(r"(ALBERTA RULES OF COURT|^\s*\d+\s*$|^\s*(Division|Subdivision|Part|Schedule) [\dA-Z]+\s*$)")
    starts = []; lastn = (0, 0)
    def key(n): a, b = n.split("."); return (int(a), int(b))
    for i in range(start, len(ls)):
        m = pat.match(ls[i])
        if not m: continue
        k = key(m.group(1))
        if k <= lastn or k[0] > lastn[0] + 1 or (k[0] == lastn[0] and k[1] > lastn[1] + 60): continue
        # title = nearest previous non-blank line that is not a header
        j = i - 1
        while j > start and (not ls[j].strip() or hdr.search(ls[j])): j -= 1
        starts.append((i, j, m.group(1), ls[j].strip())); lastn = k
    end = next((i for i, l in enumerate(ls) if i > starts[-1][0] and re.match(r"^\s*Schedule A\s*$", l)), len(ls))
    out = []
    for k, (i, j, n, t) in enumerate(starts):
        nxt = starts[k + 1][1] if k + 1 < len(starts) else end
        body = [x.strip() for x in ls[i:nxt] if x.strip() and not hdr.search(x)]
        text = norm_ws(" ".join(body)); text = re.sub(r"^" + re.escape(n) + r"\s*", "", text)
        if len(text) < 15: continue
        out.append(row("ca-ab-roc", "Alberta Rules of Court (Alta Reg 124/2010)", "CA-AB", n, t, text, "2010-11-01", "https://kings-printer.alberta.ca/documents/Regs/2010_124.pdf", sha, "archive_wayback(robots_disallowed_live)", "Alberta King's Printer (OGL-Alberta)"))
    return uniq(out)
def build():
    rows = []; xw = []
    SETS = [(scc, "ca-scc-rules", ["ca-scc"]), (ontario, "ca-on-rcp", ["ca-on-superior-court", "ca-on-court-of-appeal"]), (bc, "ca-bc-scr", ["ca-bc-superior-court"]), (alberta, "ca-ab-roc", ["ca-ab-superior-court", "ca-ab-court-of-appeal"])]
    for fn, sid, courts in SETS:
        try: r = fn()
        except Exception as e: print("ERR", sid, repr(e)); continue
        rows += r; print(sid, len(r), flush=True)
        if r:
            for c in courts: xw.append(dict(rule_set_id=sid, rule_set=r[0]["rule_set"], court_id=c, jurisdiction=r[0]["jurisdiction"], basis="rule set applies to this court (per rule set scope)", source_url=r[0]["source_url"], linked_rows="new"))
    for c in ("ca-fc", "ca-fca"): xw.append(dict(rule_set_id="ca-fcr", rule_set="Federal Courts Rules (SOR/98-106)", court_id=c, jurisdiction="CA", basis="existing upstream rule set (endomorphosis/ipfs_canada_courts); text not duplicated here", source_url="https://huggingface.co/datasets/endomorphosis/ipfs_canada_courts", linked_rows="upstream"))
    wjl(f"{ROOT}/data/ca/ca_rules.jsonl", rows); wjl(f"{ROOT}/data/ca/ca_rules_crosswalk.jsonl", xw); print("CA rules", len(rows), "crosswalk", len(xw))
if __name__ == "__main__": build()
