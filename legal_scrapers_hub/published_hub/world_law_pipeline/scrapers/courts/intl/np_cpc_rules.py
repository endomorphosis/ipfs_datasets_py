"""NP: Muluki Dewani Karyabidhi Samhita 2074 (National Civil Procedure Code 2017), Nepal Law Commission text (as amended to 2080), PDF via giwmscdnone.gov.np
(GoN CDN, linked from policynepal.org/MoLJPA). Preeti-encoded text converted to Unicode with npttf2utf. One row per section (दफा)."""
import json, sys, re, datetime, hashlib, os
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
D = f"{ROOT}/rules/raw/np_rules"; OUT = f"{ROOT}/data/np/np_rules.jsonl"
SRC = "https://giwmscdnone.gov.np/media/pdf_upload/%E0%A4%AE%E0%A5%81%E0%A4%B2%E0%A5%81%E0%A4%95%E0%A5%80-%E0%A4%A6%E0%A5%87%E0%A4%B5%E0%A4%BE%E0%A4%A8%E0%A5%80-%E0%A4%95%E0%A4%BE%E0%A4%B0%E0%A5%8D%E0%A4%AF%E0%A4%B5%E0%A4%BF%E0%A4%A7%E0%A4%BF-%E0%A4%90%E0%A4%A8-%E0%A5%A8%E0%A5%A6%E0%A5%AD%E0%A5%AA_01adtvr.pdf"
sha = hashlib.sha256(open(f"{D}/cpc_ne.pdf", "rb").read()).hexdigest(); now = datetime.datetime.now(datetime.UTC).isoformat()
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
DV = str.maketrans("०१२३४५६७८९", "0123456789"); secs = []; cur = None; ch = None; expect = 0
for l in open(f"{D}/cpc_ne_uni.txt", encoding="utf-8"):
    s = l.strip()
    if not s or s.startswith("www.") or re.fullmatch(r"[०-९0-9]+", s): continue
    m = re.match(r"^परिच्छेद\s*[–-]\s*([०-९]+)", s)
    if m: ch = m.group(1).translate(DV); continue
    m = re.match(r"^([०-९]+[क-ह]?)\.\s*(.*)$", s)
    if m and ch:
        n = m.group(1).translate(DV); base = int(re.match(r"\d+", n).group())
        if base >= expect - 2:
            cur = {"n": n, "ch": ch, "t": m.group(2)}; secs.append(cur); expect = base; continue
    if cur: cur["t"] += " " + s
rows, seen = [], set()
for c in secs:
    rid = f"np-mdks-2074:s{c['n']}"
    if rid in seen or rid in old: continue
    seen.add(rid); t = re.sub(r"\s+", " ", c["t"]).strip(); m = re.match(r"^([^:।]{2,120}?)\s*:\s*(.*)$", t)
    rows.append({"rule_id": rid, "rule_set_id": "np-mdks-2074", "court_id": None, "jurisdiction": "NP", "rule_set": "मुलुकी देवानी कार्यविधि संहिता, २०७४ (National Civil Procedure Code, 2017; as amended 2075, 2080)",
      "rule_number": f"दफा {c['n']} (Chapter {c['ch']})", "title": m.group(1) if m else None, "text": m.group(2) if m else t, "effective_date": "2018-08-17", "pdf_path": None, "pdf_sha256": sha,
      "source_sha256": sha, "source_url": SRC, "site_policy": "robots_none(gov CDN);official text from Nepal Law Commission", "retrieved_at": now,
      "license": "Nepal Acts are public government works (Copyright Act 2059 s.4 excludes laws)", "language": "ne", "record_note": "converted from Preeti legacy font with npttf2utf; verify against PDF"})
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("secs", len(secs), "added", len(rows), "last", rows[-1]["rule_number"]); print(rows[1]["title"], "|", rows[1]["text"][:120])
