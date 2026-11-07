"""India procedural rules: Supreme Court Rules 2013 (official sci.gov.in PDF, scanned/OCR text), Code of Civil Procedure 1908 (India Code PDF via Wayback; live India Code is a JS app),
Bharatiya Nagarik Suraksha Sanhita 2023 (MHA official PDF via Wayback; live URL 404). Heuristic sequential-number parse (see rule_set text). -> data/in/in_rules.jsonl + crosswalk"""
import sys, hashlib, subprocess
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
RAWD = f"{ROOT}/rules/raw/in"
def ws(s): return re.sub(r"\s+", " ", s or "").strip()
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def seq(text, pat=r"^[ \t]*(\d{1,3})([A-Z]{0,2})\.[ \t]+(?=\S)"):
    """sequential section/rule splitter: accept 'N.' only when N == previous+1 (or letter-suffixed insert / gap<=2)"""
    out = []; cur = 0
    for m in re.finditer(pat, text, re.M):
        n = int(m.group(1)); let = m.group(2)
        if let and n == cur and f"{n}{let}" not in {o[0] for o in out}: ok = True
        elif not let and (n == cur + 1 or (cur >= 1 and n in (cur + 2, cur + 3) and n < 600)): ok = True
        else: ok = False
        if ok:
            out.append((f"{n}{let}", m.start(), m.end()))
            if not let: cur = n
    res = []
    for i, (tok, s0, e0) in enumerate(out):
        end = out[i + 1][1] if i + 1 < len(out) else len(text)
        res.append((tok, text[e0:end]))
    return res
def clean(t): return ws(re.sub(r"\n+", " ", t))
def row(sid, name, num, title, text, src, pol, shaf, eff, lic, jur="IN"):
    text = clean(text)
    return dict(rule_id=f"{sid}:{num}", rule_set_id=sid, court_id=None, jurisdiction=jur, rule_set=name, rule_number=num, title=title, text=text[:12000], effective_date=eff, pdf_path=None, pdf_sha256=None,
                source_sha256=shaf, source_url=src, site_policy=pol, retrieved_at=NOW(), license=lic, language="en")
def title_of(t):
    t = clean(t[:300]); m = re.match(r"(.{3,150}?)\.\s*[—-]", t)
    return m.group(1) if m else None
def orders(text, start_pat=None):
    """split into Order segments: ^ORDER <roman>"""
    ms = list(re.finditer(r"^[ \t]*ORDER\s+([IVXLC]+[A-Z]?)[ \t]*$", text, re.M)); segs = {}
    for i, m in enumerate(ms):
        e = ms[i + 1].start() if i + 1 < len(ms) else len(text); seg = text[m.end():e]
        if m.group(1) not in segs or len(seg) > len(segs[m.group(1)]): segs[m.group(1)] = seg
    return segs
def sc_rules():
    pdf = f"{RAWD}/sc2013.pdf"; txt = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True).stdout
    src = "https://www.sci.gov.in/supreme-court-rules/"; sh = sha(pdf); out = []; name = "Supreme Court Rules, 2013 (scanned official PDF; OCR text, heuristic rule split)"
    txt = re.sub(r"(?m)^([ \t]*)[Il1]\.", r"\g<1>1.", txt)
    for o, seg in orders(txt).items():
        for tok, body in seq(seg, pat=r"^[ \t]*(\d{1,3})([A-Z]{0,2})(?:\.|(?<=\d)[ \t])[ \t]*(?=\S)"):
            if len(clean(body)) < 20: continue
            out.append(row("in-scr-2013", name, f"O{o} r{tok}", title_of(body), body, src, "robots_allowed", sh, "2025-06-14", "Supreme Court of India public website; official rules, reuse per site terms"))
    return out
def cpc():
    pdf = f"{RAWD}/cpc.pdf"; txt = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True).stdout
    src = "https://web.archive.org/web/20251206201807/https://www.indiacode.nic.in/bitstream/123456789/2191/1/A1908-05.pdf"; sh = sha(pdf); name = "Code of Civil Procedure, 1908 (India Code PDF; heuristic section/rule split)"
    ms = [m.start() for m in re.finditer(r"1\.\s+Short title, commencement and extent", txt)]; i0 = ms[1] if len(ms) > 1 else ms[0]
    fs = [m.start() for m in re.finditer(r"THE FIRST SCHEDULE", txt)]; i1 = fs[1] if len(fs) > 1 else fs[0]
    out = []; pol = "archive_wayback(live_indiacode_js_app)"; lic = "Government of India (India Code) public legislation; Government Open Data License - India"
    for tok, body in seq(txt[i0:i1]):
        if len(clean(body)) < 15: continue
        out.append(row("in-cpc-1908", name, f"s.{tok}", title_of(body), body, src, pol, sh, None, lic))
    for o, seg in orders(txt[i1:]).items():
        for tok, body in seq(seg):
            if len(clean(body)) < 15: continue
            out.append(row("in-cpc-1908", name, f"O{o} r{tok}", title_of(body), body, src, pol, sh, None, lic))
    return out
def bnss():
    pdf = f"{RAWD}/bnss.pdf"; txt = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True).stdout
    src = "https://web.archive.org/web/20251204193526/https://www.mha.gov.in/sites/default/files/2024-04/250884_2_english_01042024.pdf"; sh = sha(pdf); name = "Bharatiya Nagarik Suraksha Sanhita, 2023 (MHA official PDF; heuristic section split)"
    m = re.search(r"1\.\s*\(1\)\s*This Act may be called", txt); i0 = m.start() if m else 0
    j = re.search(r"THE FIRST SCHEDULE", txt[i0:]); i1 = i0 + j.start() if j else len(txt)
    out = []
    for tok, body in seq(txt[i0:i1], pat=r"^[ \t]*(?:[A-Za-z ,\-\.']{0,40}?[ \t]{2,})?(\d{1,3})([A-Z]{0,2})\.[ \t]+(?=\S)"):
        if len(clean(body)) < 15: continue
        out.append(row("in-bnss-2023", name, f"s.{tok}", None, body, src, "archive_wayback(live_url_404)", sh, "2024-07-01", "Government of India (MHA) published Act; Government Open Data License - India"))
    return out
CW = {"in-scr-2013": ["in-supreme-court"], "in-cpc-1908": ["in-supreme-court", "in-high-courts", "in-district-courts"], "in-bnss-2023": ["in-supreme-court", "in-high-courts", "in-district-courts"]}
def build():
    rows = []; xw = []
    for fn in (sc_rules, cpc, bnss):
        r = fn(); rows += r; print(fn.__name__, len(r), flush=True)
        if r:
            sid = r[0]["rule_set_id"]
            for c in CW[sid]: xw.append(dict(rule_set_id=sid, rule_set=r[0]["rule_set"], court_id=c, jurisdiction="IN", basis="rule set applies to this court tier (per rule set scope)", source_url=r[0]["source_url"], linked_rows="new"))
    os.makedirs(f"{ROOT}/data/in", exist_ok=True); wjl(f"{ROOT}/data/in/in_rules.jsonl", rows); wjl(f"{ROOT}/data/in/in_rules_crosswalk.jsonl", xw); print("IN rules", len(rows))
if __name__ == "__main__": build()
