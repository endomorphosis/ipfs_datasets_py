"""TH: Civil Procedure Code B.E. 2477 — Office of the Council of State (Krisdika) unofficial English translation, PDF hosted by JPO Global IP DB,
retrieved via Wayback (origin 403). One row per section. Never overwrites existing rows."""
import json, sys, re, datetime, hashlib, os
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
P = f"{ROOT}/rules/raw/th_rules/cpc_en.pdf"; T = P[:-3] + "txt"; OUT = f"{ROOT}/data/th/th_rules.jsonl"
SRC = "https://www.globalipdb.inpit.go.jp/jpowp/wp-content/uploads/2023/04/486b089864af8d307e61cd3442cc72da.pdf"
sha = hashlib.sha256(open(P, "rb").read()).hexdigest(); now = datetime.datetime.now(datetime.UTC).isoformat()
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
SUF = r"(?:/\d+)?(?:\s(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies|undecies|duodecies))?"
rx = re.compile(r"^\s*Section (\d+" + SUF + r")\.(\d{0,3})\s+(.*)")
secs = []; cur = None; part = "act"
for l in open(T, encoding="utf-8"):
    if "DISCLAIMER" in l or re.match(r"^\s*\d+\s*$", l) or re.match(r"^\s{8,}\d{1,3}\s*$", l): continue
    m = rx.match(l)
    if m:
        if m.group(1) == "1" and secs: part = "code"
        cur = [part, m.group(1), m.group(3).strip()]; secs.append(cur); continue
    if re.match(r"^\s*\*?\s*\d{1,3}\s{0,2}[A-Z][a-z]+.*(Act|Gazette|amended|added|repealed)", l): continue  # footnote
    if cur and l.strip() and not re.match(r"^\s*(BOOK|TITLE|CHAPTER|PART)\b", l): cur[2] += " " + l.strip()
rows, seen = [], set()
for part, num, txt in secs:
    sid = "th-cpc-1934" if part == "code" else "th-cpc-1934-promulgation"
    rid = f"{sid}:s{re.sub(r'[^0-9a-z]+', '-', num.lower())}"
    if rid in seen or rid in old: continue
    seen.add(rid)
    rows.append({"rule_id": rid, "rule_set_id": sid, "court_id": None, "jurisdiction": "TH",
      "rule_set": "Civil Procedure Code B.E. 2477 (1934), as amended — unofficial English translation (Office of the Council of State)" if part == "code" else "Act Promulgating the Civil Procedure Code B.E. 2477 (1934) — unofficial English translation",
      "rule_number": f"Section {num}", "title": None, "text": re.sub(r"\s+", " ", txt).strip(), "effective_date": "1935-10-01", "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha,
      "source_url": SRC, "site_policy": "archived_copy(wayback:20230521140446);origin_403", "retrieved_at": now,
      "license": "Thai statutes are not copyrightable (Copyright Act B.E. 2537 s.7); translation by Office of the Council of State, informational use, no legal force", "language": "en"})
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("sections", len(secs), "added", len(rows)); print(rows[5]["rule_number"], rows[5]["text"][:200]); print(rows[-1]["rule_number"], rows[-1]["text"][:150])
