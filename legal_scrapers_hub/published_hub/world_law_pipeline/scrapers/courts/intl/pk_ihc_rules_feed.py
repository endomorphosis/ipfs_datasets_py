"""PK: Islamabad High Court 'IHC Rules' list (mis.ihc.gov.pk ihc.asmx/GetLatestNews pFeature=10, the page's own unauthenticated feed).
Ingests new feed items that carry the rule text in the feed's Description field (e.g. S.R.O. 1341(I)/2026 amending rule 24 of the
Islamabad Judicial Service Rules, 2011, notified with a scanned gazette JPG). Items already covered by pk_ihc_rules2025.py, scanned PDFs
without text, and non-rule documents (Gender Fair Language Framework, President's Order No. 3 of 1997 on judges' pensions) are skipped.
Append-only; dedupe by rule_id and source_url. Usage: pk_ihc_rules_feed.py [--dry]"""
import json, re, sys, time, datetime, hashlib, requests
ROOT = "/workspace/world_courts"; UA = "world_courts/0.1 (open court-data research; github.com/endomorphosis)"; B = "https://mis.ihc.gov.pk"
POL = "robots_absent_allowed|mis.ihc.gov.pk robots.txt 404 (no restrictions); official Islamabad High Court website, no terms of use stated"
OUT = f"{ROOT}/data/pk/pk_rules.jsonl"; now = datetime.datetime.now(datetime.timezone.utc).isoformat()
old = [json.loads(l) for l in open(OUT) if l.strip()]; ids = {r["rule_id"] for r in old}; srcs = {r.get("source_url") for r in old}
r = requests.post(f"{B}/ihc.asmx/GetLatestNews", data="{'pFeature':'10'}", headers={"User-Agent": UA, "Content-Type": "application/json; charset=utf-8"}, timeout=60)
d = r.json()["d"]; items = json.loads(d) if isinstance(d, str) else d; rows = []
for it in items:
    t, desc, att = it["Title"].strip(), (it.get("Description") or "").strip(), it.get("Attachemnt") or ""
    m = re.search(r"S\.\s*R\.\s*O\.\s*(\d+)\(I\)/(\d{4})", t + " " + desc)
    if not m or "AMENDMENT" not in t.upper() or len(desc) < 200: continue
    src = B + att; rid = f"pk-ihc-sro-{m.group(1)}-{m.group(2)}"
    if rid in ids or src in srcs: continue
    time.sleep(2); img = requests.get(src, headers={"User-Agent": UA}, timeout=60).content; sha = hashlib.sha256(img).hexdigest()
    text = re.sub(r"\r\n", "\n", desc).lstrip(" .-")
    rows.append({"rule_id": rid, "rule_set_id": "pk-islamabad-judicial-service-rules-2011", "court_id": "osm:way/780222423", "jurisdiction": "PK-IS",
        "rule_set": "Islamabad Judicial Service Rules, 2011 (amendments)", "rule_number": "Rule 24(a) (amended)", "title": t.title().replace("S.R.O.", " S.R.O."),
        "part": None, "text": text, "effective_date": f"{it['Year']:04d}-{it['Month']:02d}-{it['Date']:02d}", "pdf_path": None, "pdf_sha256": None,
        "source_sha256": sha, "source_url": src, "index_url": f"{B}/frmDetails.aspx?Type=10", "source_kind": "official", "site_policy": POL,
        "license": "Rules made by the Chief Justice, Islamabad High Court (Gazette of Pakistan); no open licence stated", "retrieved_at": now,
        "language": "en", "needs_review": True,
        "version_note": "text from the IHC feed's Description field (official transcription of the gazette notice); source_url is the gazette scan (JPG); date = IHC listing date"})
if "--dry" not in sys.argv and rows:
    with open(OUT, "a") as f:
        for x in rows: f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("rules new", len(rows), [x["rule_id"] for x in rows])
