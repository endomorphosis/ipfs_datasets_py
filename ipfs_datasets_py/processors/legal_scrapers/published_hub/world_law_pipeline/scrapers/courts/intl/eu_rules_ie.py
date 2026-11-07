"""Irish court rules as MADE (Irish Statute Book print versions, irishstatutebook.ie/eli/<yr>/si/<n>/made/en/print): RSC S.I. 15/1986, District Court Rules S.I. 93/1997, Circuit Court Rules S.I. 510/2001.
These are the original as-made texts; later amending S.I.s are NOT applied (consolidated versions are at courts.ie /docs/, which robots.txt disallows). -> data/ie/ie_rules.jsonl"""
import sys, hashlib, html as H
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
SETS = [("ie-rsc", "Rules of the Superior Courts (S.I. 15/1986, as made)", "1986/si/15", "1986-02-01"), ("ie-dcr", "District Court Rules (S.I. 93/1997, as made)", "1997/si/93", "1997-04-01"),
        ("ie-ccr", "Circuit Court Rules (S.I. 510/2001, as made)", "2001/si/510", "2002-01-01")]
RULE = re.compile(r"^(\d+[A-Za-z]?)\.\s+(\S.*)$"); ORD = re.compile(r"^ORDER\s+(\d+[A-Z]{0,2})\.?\s*(.*)$")
def lines(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h); h = re.sub(r"(?i)</?(p|br|div|tr|li|h\d|table)[^>]*>", "\n", h)
    t = H.unescape(re.sub(r"<[^>]+>", "", h)); t = re.sub(r"[ \t\xa0]+", " ", t); return [l.strip() for l in t.split("\n") if l.strip()]
def main():
    rows = []
    for sid, name, path, eff in SETS:
        p = f"{RAW}/intl_ie_{path.replace('/', '_')}.html"; raw = open(p, "rb").read(); sha = hashlib.sha256(raw).hexdigest(); ls = lines(raw.decode("utf8", "replace"))
        start = next(i for i, l in enumerate(ls) if ORD.match(l) and any(RULE.match(x) and RULE.match(x).group(1) == "1" for x in ls[i + 1:i + 4]))
        order = None; otitle = None; cur = None; n = 0; seen = {}
        def flush():
            nonlocal cur, n
            if cur and len(cur["t"]) > 8:
                num = f"Order {cur['o']}, r. {cur['r']}"; seen[num] = seen.get(num, 0) + 1
                rows.append(dict(rule_id=f"{sid}:{num}" + (f"~{seen[num]}" if seen[num] > 1 else ""), rule_set_id=sid, court_id=None, jurisdiction="IE", rule_set=name, rule_number=num, title=cur["ot"], text=re.sub(r"\s+", " ", cur["t"]).strip(),
                                 effective_date=eff, pdf_path=None, pdf_sha256=None, source_sha256=sha, source_url=f"https://www.irishstatutebook.ie/eli/{path}/made/en/print", site_policy="robots_allowed:irishstatutebook",
                                 retrieved_at=NOW(), license="Irish Statute Book statutory instrument (Government of Ireland open data / PSI re-use, CC-BY 4.0); as made", language="en")); n += 1
            cur = None
        i = start
        while i < len(ls):
            l = ls[i]; m = ORD.match(l)
            if m and any(RULE.match(x) and RULE.match(x).group(1) == "1" for x in ls[i + 1:i + 4]):
                flush(); order = m.group(1); otitle = m.group(2) or (ls[i + 1] if not RULE.match(ls[i + 1]) else None); i += 1; continue
            if re.match(r"^(APPENDIX|SCHEDULE OF COSTS|SCHEDULE|FORMS?)\b", l) and l.upper() == l and len(l) < 40 and n > 20:
                flush(); break
            mr = RULE.match(l)
            if mr and order:
                flush(); cur = dict(o=order, ot=otitle, r=mr.group(1), t=mr.group(2))
            elif cur is not None:
                nxt = ls[i + 1] if i + 1 < len(ls) else ""
                if RULE.match(nxt) and len(l) < 120 and not l.endswith((".", ";", ":")) and not l.startswith("("): pass
                elif not (otitle and l == otitle and cur["t"] == ""): cur["t"] += " " + l
            i += 1
        flush(); print(sid, n, flush=True)
    os.makedirs(f"{ROOT}/data/ie", exist_ok=True); wjl(f"{ROOT}/data/ie/ie_rules.jsonl", rows); print("IE rules", len(rows))
if __name__ == "__main__": main()
