"""Suriname: Procesreglement voor Civiele Zaken bij het Hof van Justitie en de Kantongerechten, versie 2026
(vastgesteld 31 juli 2026, in werking 1 oktober 2026; replaces Procesreglement 2021). Official PDF on rechtspraak.sr (WordPress;
robots.txt allows). Article-level split at 'Artikel X-N' headings (Deel A-H); footnotes stay inline -> needs_review.
Appends to data/sr/sr_rules.jsonl, dedupe by rule_id; re-runs add 0."""
import json, re, os, hashlib, datetime, subprocess, time, urllib.request
ROOT = "/workspace/world_courts"; RAW = f"{ROOT}/rules/raw/sr"; OUT = f"{ROOT}/data/sr/sr_rules.jsonl"
URL = "https://rechtspraak.sr/wp-content/uploads/2026/10/Procesreglement-2026.pdf"; IDX = "https://rechtspraak.sr/home/protocollen/procesreglement-2026/"
UA = {"User-Agent": "Mozilla/5.0 (WorldCourtsResearchBot/1.0; public court data; polite)"}
now = datetime.datetime.now(datetime.UTC).isoformat(); os.makedirs(RAW, exist_ok=True)
p = f"{RAW}/Procesreglement-2026.pdf"
if not os.path.exists(p):
    time.sleep(2); open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=180).read())
sha = hashlib.sha256(open(p, "rb").read()).hexdigest()
L = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout.splitlines()
H = re.compile(r"^\s{0,4}Artikel\s+([A-H])\s*-\s*(\d+[a-z]?)\.?\s*(.*)$")
DEEL = re.compile(r"^\s*DEEL\s+([A-H])\s*$"); HFD = re.compile(r"^\s*(HOOFDSTUK\s+\d+|Hoofdstuk\s+\d+)\b(.*)$")
heads, deel, deeltitle, hfd = [], None, None, None
for i, l in enumerate(L):
    m = DEEL.match(l)
    if m:
        deel = m.group(1); nxt = next((x.strip() for x in L[i + 1:i + 4] if x.strip()), ""); deeltitle = f"Deel {deel} – {nxt.capitalize() if nxt.isupper() else nxt}"; hfd = None; continue
    m = HFD.match(l)
    if m and i > 150: hfd = re.sub(r"\s+", " ", (m.group(1).capitalize() + m.group(2)).strip()); continue
    m = H.match(l)
    if m and i > 100: heads.append((i, m.group(1), m.group(2), m.group(3).strip(), deeltitle, hfd))
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
rows, seen = [], set()
for j, (i, d, n, title, dt, hf) in enumerate(heads):
    e = heads[j + 1][0] if j + 1 < len(heads) else len(L)
    body = [x.rstrip() for x in L[i:e] if not re.fullmatch(r"\s*\d{1,2}\s*", x.replace("\f", ""))]
    # drop trailing DEEL/Hoofdstuk headings that belong to the next article's section
    while body and (not body[-1].strip() or DEEL.match(body[-1]) or HFD.match(body[-1]) or re.fullmatch(r"\s*[A-Z ,\-–]{6,}\s*", body[-1]) or re.fullmatch(r"\s*§\s*\d+\..*", body[-1])): body.pop()
    rid = f"sr-procesreglement-2026:art{d}-{n}"
    if rid in old or rid in seen: continue
    seen.add(rid)
    rows.append({"rule_id": rid, "rule_set_id": "sr-procesreglement-2026", "court_id": None, "jurisdiction": "SR",
        "rule_set": "Procesreglement voor Civiele Zaken bij het Hof van Justitie en de Kantongerechten (versie 2026)",
        "rule_number": f"Artikel {d}-{n}", "title": title or None, "part": " / ".join(x for x in (dt, hf) if x),
        "text": re.sub(r"\n{3,}", "\n\n", "\n".join(body)).replace("\f", "").strip(), "effective_date": "2026-10-01",
        "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha, "source_url": URL, "index_url": IDX, "source_kind": "official",
        "site_policy": "robots_allowed|rechtspraak.sr: Hof van Justitie Suriname; no licence stated", "retrieved_at": now, "granularity": "article",
        "license": "official court regulation published by the Hof van Justitie; no licence stated", "language": "nl",
        "version_note": "Vastgesteld in de algemene vergadering van het Hof van Justitie op 31 juli 2026; vervangt Procesreglement 2021",
        "needs_review": True, "extraction": "pdftotext -layout split at 'Artikel X-N' headings; footnotes inline"})
print("headings", len(heads), "new", len(rows))
if os.environ.get("DRY"):
    import collections; print(collections.Counter(r["rule_number"].split("-")[0] for r in rows))
    for r in rows[:2] + rows[-2:]: print(r["rule_id"], "|", r["title"], "|", r["part"], "|", repr(r["text"][-150:]))
else:
    with open(OUT, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
