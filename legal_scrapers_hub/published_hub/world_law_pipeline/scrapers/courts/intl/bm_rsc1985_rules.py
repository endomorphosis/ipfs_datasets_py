"""BM: Rules of the Supreme Court 1985 (GN 470/1985, consolidated to BR 13/2026) from Bermuda Laws Online (official, Attorney-General's
Chambers; bermudalaws.bm robots.txt 404). Rule-level rows (Order/rule), text from the PDF text layer. Appendix A/B (forms) not split.
Usage: bm_rsc1985_rules.py [--dry]"""
import json, re, sys, hashlib, subprocess, datetime, os, time, requests
ROOT = "/workspace/world_courts"; OUT = f"{ROOT}/data/bm/bm_rules.jsonl"; RAW = f"{ROOT}/rules/raw/bm/rsc1985.pdf"
UA = "world_courts/0.1 (open court-data research; github.com/endomorphosis)"
SRC = "https://www.bermudalaws.bm/Laws/Consolidated%20Law/1985/Rules%20of%20the%20Supreme%20Court%201985"
if not os.path.exists(RAW):
    os.makedirs(os.path.dirname(RAW), exist_ok=True); r = requests.get(SRC, headers={"User-Agent": UA}, timeout=180); r.raise_for_status()
    open(RAW, "wb").write(r.content); time.sleep(3)
pdf = open(RAW, "rb").read(); sha = hashlib.sha256(pdf).hexdigest()
L = subprocess.run(["pdftotext", RAW, "-"], capture_output=True, text=True).stdout.splitlines()
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
start = [i for i, l in enumerate(L) if l.strip() == "ORDER 1"][1]  # second occurrence = body (first is table of contents)
end = next(i for i in range(start, len(L)) if L[i].strip() == "APPENDIX A")
L = [l for l in L[start:end] if l.strip() != "RULES OF THE SUPREME COURT 1985" and not re.fullmatch(r"\s*\d{1,3}\s*", l)]
order = None; otitle = ""; cur = None; rows = []
def flush():
    if cur: rows.append(cur)
i = 0
while i < len(L):
    l = L[i].strip(); m = re.fullmatch(r"ORDER (\d+[A-Z]?)", l)
    if m:
        order = m.group(1); t = []; j = i + 1
        while j < len(L) and L[j].strip() and L[j].strip().upper() == L[j].strip() and not re.match(r"\d+[A-Z]?/", L[j].strip()): t.append(L[j].strip()); j += 1
        otitle = " ".join(t); i = j; continue
    m = re.match(r"^(\d+[A-Z]?)/(\d+[A-Z]?)\s+(\S.*)$", l)
    if m and order and m.group(1) == order:
        flush(); rn = f"{order}/{m.group(2)}"
        cur = {"rule_id": f"bm-rsc1985:o{order}r{m.group(2)}".lower(), "rule_set_id": "bm-rsc1985", "court_id": "bm-supreme-court", "jurisdiction": "BM",
               "rule_set": "Rules of the Supreme Court 1985 (Bermuda)", "rule_number": f"Order {order} rule {m.group(2)}", "title": m.group(3).strip(),
               "part": f"Order {order}: {otitle.title()}" if otitle else f"Order {order}", "text": "", "effective_date": "1988-01-04",
               "pdf_path": "rules/raw/bm/rsc1985.pdf", "pdf_sha256": sha, "source_sha256": sha, "source_url": SRC, "index_url": "https://www.bermudalaws.bm/LawIndex",
               "source_kind": "official", "site_policy": "robots_absent_allowed|bermudalaws.bm robots.txt 404; Bermuda Laws Online (Government of Bermuda) - see site disclaimer",
               "license": "Bermuda Government legislation (Bermuda Laws Online); no open licence stated", "retrieved_at": now, "language": "en",
               "needs_review": False, "version_note": "Consolidated text as published on Bermuda Laws Online (amendments to BR 13/2026; PDF generated 2026-03-11)"}
        i += 1; continue
    if cur is not None: cur["text"] += L[i] + "\n"
    i += 1
flush()
for r in rows: r["text"] = re.sub(r"\n{3,}", "\n\n", r["text"]).strip()[:150000]
rows = [r for r in rows if not (len(r["text"]) < 20 and r["title"] in ("to", "[blank]"))]  # unused rule ranges
seen = set(); rows = [r for r in rows if not (r["rule_id"] in seen or seen.add(r["rule_id"]))]
have = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
new = [r for r in rows if r["rule_id"] not in have]
print("orders", len({r['part'] for r in rows}), "rules", len(rows), "new", len(new), "empty", sum(1 for r in rows if len(r["text"]) < 20))
for r in rows[:3] + rows[-2:]: print(r["rule_id"], r["part"][:40], "|", r["title"][:60], len(r["text"]))
if "--dry" not in sys.argv:
    with open(OUT, "a") as f:
        for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("wrote", len(new))
