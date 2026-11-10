"""NP: Muluki Faujdari Karyabidhi (Samhita) Ain 2074 (National Criminal Procedure Code 2017, Act No. 37 of 2074), Nepal Law Commission text as
republished on supremecourt.gov.np (Court rules/laws page). Preeti-encoded PDF text converted to Unicode with npttf2utf. One row per section (दफा);
schedules (अनुसूची, form formats) are not split into rows here."""
import json, sys, re, datetime, hashlib, os
ROOT = "/workspace/world_courts"
D = f"{ROOT}/rules/raw/np"; OUT = f"{ROOT}/data/np/np_rules.jsonl"
SRC = "https://supremecourt.gov.np/web/assets/downloads/मुलुकी_फौजदारी_देवानी_कार्यविधि_(संहिता)_ऐन,_२०७४.pdf"
sha = hashlib.sha256(open(f"{D}/crpc_2074.pdf", "rb").read()).hexdigest(); now = datetime.datetime.now(datetime.UTC).isoformat()
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
DV = str.maketrans("०१२३४५६७८९", "0123456789"); secs = []; cur = None; ch = None; expect = 0
for l in open(f"{D}/crpc_uni.txt", encoding="utf-8"):
    s = l.strip()
    if not s or s.startswith("www.") or re.fullmatch(r"[0-9]+", s): continue
    if re.fullmatch(r"[०-९]+", s) and int(s.translate(DV)) != expect + 1: continue
    if re.match(r"^अनुसूची\s*[–-]\s*१\s*$", s) and expect >= 190: break
    m = re.match(r"^परिच्छेद\s*[–-]\s*([०-९]+)\s*$", s)
    if m: ch = m.group(1).translate(DV); cur = None; continue
    m = re.match(r"^([०-९]+[क-ह]?)(\.|\s|$)\s*(.*)$", s)
    if m and ch:
        n = m.group(1).translate(DV); base = int(re.match(r"\d+", n).group())
        if (m.group(2) == "." and expect - 2 <= base <= expect + 3) or (m.group(2) != "." and base == expect + 1):
            m = type("M", (), {"group": lambda self, i, _m=m: _m.group(3) if i == 2 else _m.group(i)})()
            cur = {"n": n, "ch": ch, "t": m.group(2)}; secs.append(cur); expect = base; continue
    if cur: cur["t"] += " " + s
rows, seen = [], set()
for c in secs:
    rid = f"np-mfks-2074:s{c['n']}"
    if rid in seen or rid in old: continue
    seen.add(rid); t = re.sub(r"\s+", " ", c["t"]).strip(); m = re.match(r"^([^:।]{2,120}?)\s*:\s*(.*)$", t)
    rows.append({"rule_id": rid, "rule_set_id": "np-mfks-2074", "court_id": None, "jurisdiction": "NP",
      "rule_set": "मुलुकी फौजदारी कार्यविधि (संहिता) ऐन, २०७४ (National Criminal Procedure Code, 2017; Act No. 37 of 2074)",
      "rule_number": f"दफा {c['n']} (Chapter {c['ch']})", "title": m.group(1) if m else None, "text": m.group(2) if m else t, "effective_date": "2018-08-17",
      "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha, "source_url": SRC, "index_url": "https://supremecourt.gov.np/web/courtrules",
      "site_policy": "robots_absent_allowed;official text (Nepal Law Commission) republished by the Supreme Court of Nepal", "retrieved_at": now,
      "license": "Nepal Acts are public government works (Copyright Act 2059 s.4 excludes laws)", "language": "ne", "needs_review": True,
      "record_note": "converted from Preeti legacy font with npttf2utf; table/footnote text may be inline; verify against PDF"})
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("secs", len(secs), "added", len(rows), "last", rows[-1]["rule_number"] if rows else None)
for r in rows[:2] + rows[-2:]: print(r["rule_number"], r["title"], "|", r["text"][:100])
