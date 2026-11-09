"""South Africa procedural rules from official justice.gov.za PDFs (Uniform Rules, Magistrates' Courts, SCA, Labour, Labour Appeal). Rule-level sequential split (heuristic, see rule_set)."""
import sys, hashlib, subprocess
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from row_rules_in import seq, clean, sha
RAWD = f"{ROOT}/rules/raw/za"; B = "https://www.justice.gov.za/legislation/rules/"
LIC = "Department of Justice and Constitutional Development (South Africa) published rules; public legislation, reuse per site terms"
def txt(n): return subprocess.run(["pdftotext", "-layout", f"{RAWD}/{n}.pdf", "-"], capture_output=True, text=True).stdout.replace("\x0c", "\n")
def toc_split(t, i0):
    """TOC-guided: rule numbers/titles from the arrangement list before i0, then each heading located sequentially in the body"""
    toc = []; seen = set()
    for m in re.finditer(r"^[ \t]*(\d{1,3}[A-Z]{0,2})\.?[ \t]+(?!…)([A-Za-z\u2019'][^\n]{3,})$", t[max(0, i0 - 9000):i0], re.M):
        if m.group(1) not in seen: seen.add(m.group(1)); toc.append((m.group(1), clean(m.group(2))))
    pos = []; cur = i0
    for num, ti in toc:
        m = re.compile(r"^[ \t]*" + num + r"\.?[ \t]+" + re.escape(ti[:14]).replace(r"\ ", r"\s+"), re.M).search(t, cur)
        if m: pos.append((num, ti, m.start(), m.end())); cur = m.end()
    out = []
    for i, (num, ti, a, b) in enumerate(pos):
        e = pos[i + 1][2] if i + 1 < len(pos) else min(len(t), b + 20000); out.append((num, ti, t[b:e]))
    return out
def nth(pat, t, k):
    ms = list(re.finditer(pat, t, re.M)); return ms[min(k, len(ms) - 1)].start() if ms else 0
def title_first(b):
    b = b.strip(); l = b.split("\n")[0]; return clean(l)[:150] if l and len(l) < 150 else None
SETS = [
 ("za-uniform-rules", "Uniform Rules of Court (High Court), GNR 48 of 1965 as amended (justice.gov.za PDF; heuristic rule split)", "uniform", "Uniform-Rules-of-Court-GG999-GNR48-19650112-SAFLII.pdf", ["za-high-court"], r"^\s*1\.\s+Definitions", 1, r"^\s*(?:ANNEXURE|Annexure)\s+[A-Z0-9]|^\s*FORM\s+1\b", 90),
 ("za-sca-rules", "Rules of the Supreme Court of Appeal, GNR 1523 of 1998 as amended (justice.gov.za PDF; heuristic rule split)", "sca", "Rules-SupremeCourtOfAppeal-GG19507-GNR1523-19981127-SAFLII.pdf", ["za-supreme-court-of-appeal"], r"^\s*1\.\s+Definitions", 1, None, 0),
 ("za-labour-rules", "Rules for the Conduct of Proceedings in the Labour Court, GN 4775 of 2024 (justice.gov.za PDF; heuristic rule split)", "labour", "Rules-LabourCourt-GG50608-GN4775-20240503-SAFLII.pdf", ["za-labour-court"], r"^\s*1\.\s+Definitions", 1, None, 0),
 ("za-lac-rules", "Rules of the Labour Appeal Court, GN 4775 of 2024 (justice.gov.za PDF; heuristic rule split)", "lac", "Rules-LabourAppealCourt-GG50608-GN4775-20240503-SAFLII.pdf", ["za-labour-appeal-court"], r"^\s*1\.\s+Definitions", 1, None, 0),
 ("za-magistrates-rules", "Rules Regulating the Conduct of the Proceedings of the Magistrates' Courts of South Africa, GNR 740 of 2010 as amended (justice.gov.za PDF; heuristic rule split)", "magistrate", "Rules-MagistrateCourts-GG33487-GNR740-20100823.pdf", ["za-magistrates-courts"], r"^\s*1\.\s+\(1\)|^\s*Definitions\s*$", 0, None, 0),
]
def build():
    rows = []; xw = []
    for sid, name, n, fn, courts, start, k, end, _ in SETS:
        t = txt(n); pdf = f"{RAWD}/{n}.pdf"
        i0 = nth(start, t, k) if n != "magistrate" else (t.find("\n   Definitions\n") + 1)
        i1 = len(t)
        if n == "magistrate": i1 = t.find("Short title and commencement\n", i0) + 3000
        if end:
            m = re.search(end, t[i0 + 5000:], re.M); i1 = i0 + 5000 + m.start() if m else len(t)
        reg = t[i0:i1]
        if n == "magistrate": reg = re.sub(r"^\s*Definitions\s*\n", "1. Definitions\n", reg, 1, re.M)
        pat = r"^[ \t]*(\d{1,3})([A-Z]{0,2})\.?[ \t]+(?=[A-Z(“\"])" if n != "magistrate" else r"^[ \t]*(\d{1,3})([A-Z]{0,2})\.[ \t]+(?=\S)"
        out = []
        it = [(a, b, c) for a, b, c in toc_split(t, i0)] if n != "magistrate" else [(a, None, b) for a, b in seq(reg, pat=pat)]
        for tok, ttl, body in it:
            if len(clean(body)) < 12: continue
            out.append(dict(rule_id=f"{sid}:{tok}", rule_set_id=sid, court_id=None, jurisdiction="ZA", rule_set=name, rule_number=f"r.{tok}", title=ttl or title_first(body), text=clean(body)[:12000], effective_date=None, pdf_path=None, pdf_sha256=None,
                            source_sha256=sha(pdf), source_url=B + fn, site_policy="robots_unknown:fetched_ok", retrieved_at=NOW(), license=LIC, language="en"))
        # dedupe ids
        seen = set(); out = [r for r in out if not (r["rule_id"] in seen or seen.add(r["rule_id"]))]
        print(sid, len(out), flush=True); rows += out
        for c in courts: xw.append(dict(rule_set_id=sid, rule_set=name, court_id=c, jurisdiction="ZA", basis="rule set applies to this court (per rule set scope)", source_url=B + fn, linked_rows="new"))
    os.makedirs(f"{ROOT}/data/za", exist_ok=True); wjl(f"{ROOT}/data/za/za_rules.jsonl", rows); wjl(f"{ROOT}/data/za/za_rules_crosswalk.jsonl", xw); print("ZA rules", len(rows))
if __name__ == "__main__": build()
