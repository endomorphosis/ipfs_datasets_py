"""Japan: Supreme Court rules (最高裁判所規則) from the official courts.go.jp 規則集 PDFs (not in the e-Gov API). Appends rows/crosswalk to data/jp/jp_rules*.jsonl (replacing earlier rows of the same sets)."""
import sys, hashlib, subprocess
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import polite_get
RAWD = f"{ROOT}/rules/raw/jp"
B = "https://www.courts.go.jp/assets/"
SETS = [("民事訴訟規則", "jp-rcp", "080521minnsokisoku.pdf", "civil"), ("民事執行規則", "jp-rce", "minjisikkoukisoku.pdf", "civil"), ("民事保全規則", "jp-rcpm", "080521minjihozenkisoku.pdf", "civil"),
        ("刑事訴訟規則", "jp-rcrp", "keijisosyoukisoku_20261020.pdf", "criminal"), ("家事事件手続規則", "jp-family-rules", "20260521kajikisoku.pdf", "family"), ("人事訴訟規則", "jp-personal-status-rules", "20260521jinsokisoku.pdf", "family"),
        ("少年審判規則", "jp-juvenile-rules", "20260521shounenshinpankisoku.pdf", "family")]
KN = "〇一二三四五六七八九十百千"
HEAD = re.compile(r"^\s*(第[%s]+条(?:の[%s]+)*)\s*(.*)$" % (KN, KN), re.M)
def build():
    rows = []; xw = []
    for title, sid, fn, grp in SETS:
        p = f"{RAWD}/{sid}.pdf"
        if not os.path.exists(p):
            b, u, pol = polite_get(B + fn, delay=2.0, binary=True)
            if not b or b[:4] != b"%PDF": print("MISSING", title); continue
            open(p, "wb").write(b)
        sh = hashlib.sha256(open(p, "rb").read()).hexdigest()
        txt = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout
        ms = list(HEAD.finditer(txt)); seen = set(); n = 0
        # skip TOC: keep the last occurrence of each article heading
        last = {}
        for m in ms: last[m.group(1)] = m
        order = sorted(last.values(), key=lambda m: m.start())
        for i, m in enumerate(order):
            e = order[i + 1].start() if i + 1 < len(order) else len(txt)
            body = re.sub(r"\s+", " ", (m.group(2) + " " + txt[m.end():e])).strip()
            capm = re.search(r"（([^）]{1,40})）\s*$", txt[max(0, m.start() - 80):m.start()].strip().split("\n")[-1] if txt[:m.start()].strip() else "")
            if len(body) < 8: continue
            rows.append(dict(rule_id=f"{sid}:{m.group(1)}", rule_set_id=sid, court_id=None, jurisdiction="JP", rule_set=f"{title} (最高裁判所規則)", rule_number=m.group(1), title=capm.group(1) if capm else None, text=body[:12000],
                             effective_date=None, pdf_path=f"rules/raw/jp/{sid}.pdf", pdf_sha256=sh, source_sha256=sh, source_url=B + fn, site_policy="robots_allowed", retrieved_at=NOW(),
                             license="Supreme Court of Japan (courts.go.jp) published rules; official text, reuse per site terms", language="ja")); n += 1
        print(sid, title, n, flush=True)
        tiers = {"civil": ["jp-supreme-court", "jp-high", "jp-district", "jp-summary"], "criminal": ["jp-supreme-court", "jp-high", "jp-district", "jp-summary"], "family": ["jp-supreme-court", "jp-high", "jp-family"]}[grp]
        for c in tiers: xw.append(dict(rule_set_id=sid, rule_set=f"{title} (最高裁判所規則)", court_id=c, jurisdiction="JP", basis="rule set applies to this court tier (per rule set scope)", source_url=B + fn, linked_rows="new"))
    sids = {s[1] for s in SETS}
    old = [r for r in rjl(f"{ROOT}/data/jp/jp_rules.jsonl") if r["rule_set_id"] not in sids]; oldx = [r for r in rjl(f"{ROOT}/data/jp/jp_rules_crosswalk.jsonl") if r["rule_set_id"] not in sids]
    wjl(f"{ROOT}/data/jp/jp_rules.jsonl", old + rows); wjl(f"{ROOT}/data/jp/jp_rules_crosswalk.jsonl", oldx + xw); print("JP rules total", len(old) + len(rows))
if __name__ == "__main__": build()
