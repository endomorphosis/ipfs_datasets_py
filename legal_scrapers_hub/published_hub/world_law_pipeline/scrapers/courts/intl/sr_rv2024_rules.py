"""SR: Wetboek van Burgerlijke Rechtsvordering (S.B. 2024 no. 170, Wet van 5 december 2024, published 13/15 January 2025),
article-level rows from the official PDF on De Nationale Assemblée site (dna.sr; robots.txt 404 -> robots_absent_allowed).
pdftotext (non-layout) output; Boek/Titel/Afdeling headings carried; text cut before the Memorie van Toelichting."""
import json, os, re, hashlib, datetime, subprocess, requests
ROOT = "/workspace/world_courts"
SRC = "https://www.dna.sr/media/xqmmsvva/s-b-_2024_no-_170__wet_van_5_december_2024__houdende_vaststelling_van_het_nieuwe_wetboek_van_burgerlijke_rechtsvordering.pdf"
IDX = "https://www.dna.sr/wetgeving/surinaamse-wetten/wetten-na-2005/nieuw-burgerlijk-wetboek/wet-burgerlijke-rechtsvordering/"
RAW = f"{ROOT}/rules/raw/sr/rv2024_dna.pdf"; OUT = f"{ROOT}/data/sr/sr_rules.jsonl"
now = datetime.datetime.now(datetime.UTC).isoformat()
if not os.path.exists(RAW):
    r = requests.get(SRC, headers={"User-Agent": "WorldCourtsResearchBot/1.0"}, timeout=180); r.raise_for_status(); open(RAW, "wb").write(r.content)
sha = hashlib.sha256(open(RAW, "rb").read()).hexdigest()
L = subprocess.run(["pdftotext", RAW, "-"], capture_output=True, text=True).stdout.replace("\f", "\n").splitlines()
for k, l in enumerate(L):
    if l.strip() == "MEMORIE VAN TOELICHTING": L = L[:k]; break
for k, l in enumerate(L):
    if l.strip().startswith("Paramaribo, de 5e december 2024"): L = L[:k]; break
noise = re.compile(r"^(No\. 170|\d{1,3}|STAATSBLAD.*)$")
hd = {"BOEK": None, "TITEL": None, "AFDELING": None}
def nxt(i):
    for j in range(i + 1, min(i + 4, len(L))):
        s = L[j].strip()
        if s and not noise.match(s): return s
    return ""
arts = []; cur = None
for i, l in enumerate(L):
    s = l.strip()
    m = re.fullmatch(r"(BOEK|TITEL|AFDELING) (\d+[A-Za-z]?)", s)
    if m:
        k = m.group(1); hd[k] = f"{k.title()} {m.group(2)} – {nxt(i)}"
        if k == "BOEK": hd["TITEL"] = hd["AFDELING"] = None
        if k == "TITEL": hd["AFDELING"] = None
        if cur: cur["stop"] = True
        continue
    m = re.fullmatch(r"Artikel (\d+[a-z]{0,2}|[A-Z])", s)
    if m:
        cur = {"n": m.group(1), "part": " / ".join(v for v in hd.values() if v), "lines": [], "stop": False}; arts.append(cur); continue
    if cur and not cur["stop"] and s and not noise.match(s):
        # heading-title line right after a BOEK/TITEL/AFDELING header is captured by nxt(); skip while stopped
        cur["lines"].append(s)
rows = []; seen = set()
for a in arts:
    rid = f"sr-rv-2024:art{a['n']}"
    if rid in seen: continue
    seen.add(rid)
    text = re.sub(r"\s+", " ", " ".join(a["lines"])).strip()
    text = re.sub(r"(?<=\w)- (?=[a-z])", "", text)
    if not text: continue
    rows.append({"rule_id": rid, "rule_set_id": "sr-rv-2024", "court_id": None, "jurisdiction": "SR",
        "rule_set": "Wetboek van Burgerlijke Rechtsvordering (S.B. 2024 no. 170)", "rule_number": f"Artikel {a['n']}", "title": None,
        "part": a["part"] or None, "text": text, "effective_date": None, "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha,
        "source_url": SRC, "index_url": IDX, "site_policy": "robots_absent_allowed", "retrieved_at": now,
        "license": "Wet of the Republic of Suriname (Staatsblad 2024 no. 170); official text published by De Nationale Assemblée, no licence stated",
        "language": "nl", "version_note": "new Code of Civil Procedure, Wet van 5 december 2024, uitgegeven 13 januari 2025; entry into force set separately (not verified here)",
        "needs_review": True})
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
new = [x for x in rows if x["rule_id"] not in old]
with open(OUT, "a") as f:
    for x in new: f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("parsed", len(rows), "added", len(new))
