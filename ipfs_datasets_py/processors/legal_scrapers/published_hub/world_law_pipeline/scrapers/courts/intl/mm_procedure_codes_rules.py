"""Myanmar: Code of Civil Procedure (India Act V, 1908, as amended to 11.10.2021; sections only - the First Schedule orders are not in
this PDF) and Code of Criminal Procedure (India Act V, 1898, as amended to 20.01.2016), official English texts on the Supreme Court
of the Union website (unionsupremecourt.gov.mm 'Laws' page; robots.txt 'Disallow:' empty = allowed). Section-level split of pdftotext
output at 'N.' / 'NA.' headings in increasing order; the marginal note line before a section becomes its title. needs_review.
Appends to data/mm/mm_rules.jsonl; dedupe by rule_id; re-runs add 0."""
import json, re, os, hashlib, datetime, subprocess, time, urllib.request
ROOT = "/workspace/world_courts"; RAW = f"{ROOT}/rules/raw/mm"; OUT = f"{ROOT}/data/mm/mm_rules.jsonl"; os.makedirs(RAW, exist_ok=True)
IDX = "https://www.unionsupremecourt.gov.mm/laws"; U = "https://www.unionsupremecourt.gov.mm/uploads/legislative/"
UA = {"User-Agent": "Mozilla/5.0 (WorldCourtsResearchBot/1.0; public court data; polite)"}
now = datetime.datetime.now(datetime.UTC).isoformat()
SETS = [dict(id="mm-cpc-1908", name="The Code of Civil Procedure (India Act V, 1908) [Myanmar]", file="1783905146-mm-6a543b7ad236b-THE-CODE-OF-CIVIL-PROCEDURE.pdf",
             court="mm-supreme-court", note="As published by the Supreme Court of the Union; amendments 09.10.1956, 18.06.1989, 12.07.2000, 28.08.2008, 03.07.2014, 11.10.2021; schedules not included"),
        dict(id="mm-crpc-1898", name="The Code of Criminal Procedure (India Act V, 1898) [Myanmar]", file="1783905167-mm-6a543b8fb81bf-THE-CODE-OF-CRIMINAL-PROCEDURE.pdf",
             court="mm-supreme-court", note="As published by the Supreme Court of the Union; amendment 20.01.2016")]
SEC = re.compile(r"^\s{0,3}(\d{1,3})([A-Z]{0,2})(?:-(\d{1,3})[A-Z]?)?\.\s+(\S.*)?$")
def k(n, l): return (int(n), l)
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
rows = []
for S in SETS:
    p = f"{RAW}/{S['file']}"
    if not os.path.exists(p):
        time.sleep(2); open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(U + S["file"], headers=UA), timeout=300).read())
    sha = hashlib.sha256(open(p, "rb").read()).hexdigest()
    L = [l for l in subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout.splitlines()
         if not re.search(r"Page \d+ of \d+\s*$|^\s{40,}THE CODE OF (CIVIL|CRIMINAL) PROCEDURE\.?\s*$", l)]
    end = next((i for i, l in enumerate(L) if "[ ATTACH LIST" in l), len(L))
    heads, last = [], (0, "")
    for i in range(end):
        m = SEC.match(L[i])
        if not m: continue
        kk = k(m.group(1), m.group(2))
        if kk <= last or kk[0] > last[0] + 6: continue
        heads.append((i, m.group(1) + m.group(2), m.group(3))); last = (int(m.group(3)), "") if m.group(3) else kk
    part = chap = None; n0 = len(rows)
    for j, (i, num, rng) in enumerate(heads):
        e = heads[j + 1][0] if j + 1 < len(heads) else end
        # marginal note = last non-empty line(s) before the section that is not a PART/CHAPTER heading
        prev = [x.strip() for x in L[(heads[j - 1][0] if j else 0):i] if x.strip()]
        title = None
        if prev and not re.match(r"^(PART|CHAPTER)\b", prev[-1]) and len(prev[-1]) < 120 and not prev[-1].endswith((";", ",", ":-", "–")):
            title = prev[-1].rstrip(".")
        for x in prev:
            if re.match(r"^PART [IVXLC]+", x): part = x
            if re.match(r"^CHAPTER [IVXLC]+[A-Z]?", x): chap = x
        body = L[i:e]
        if j + 1 < len(heads):
            nprev = [x for x in L[i:e] if x.strip()]
            if nprev:
                t2 = nprev[-1].strip()
                if not re.match(r"^\d", t2) and len(t2) < 120 and not t2.endswith((";", ",", ":-", "–", ":")):
                    while body and not body[-1].strip(): body.pop()
                    if body and body[-1].strip() == t2: body.pop()
        while body and (not body[-1].strip() or re.match(r"^\s*(PART|CHAPTER)\b|^\s*[A-Z][A-Z ,]+\.?\s*$", body[-1])): body.pop()
        cut = next((n for n, x in enumerate(body) if "----- Attachment" in x or "[ ATTACH LIST" in x), None)
        if cut is not None: body = body[:cut]
        text = re.sub(r"\n{2,}", "\n", "\n".join(x.rstrip() for x in body)).strip()
        number = f"{num}-{rng}" if rng else num
        rid = f"{S['id']}:s{number}"
        if rid in old or any(r["rule_id"] == rid for r in rows): continue
        rows.append({"rule_id": rid, "rule_set_id": S["id"], "court_id": None, "jurisdiction": "MM", "rule_set": S["name"],
            "rule_number": f"Section {number}", "title": title, "part": " / ".join(x for x in (part, chap) if x) or None, "text": text,
            "effective_date": None, "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha, "source_url": U + S["file"], "index_url": IDX,
            "source_kind": "official", "site_policy": "robots_allowed|unionsupremecourt.gov.mm: no licence stated", "retrieved_at": now,
            "granularity": "section", "license": "official text published by the Supreme Court of the Union; no licence stated", "language": "en",
            "version_note": S["note"], "needs_review": True, "extraction": "pdftotext -layout split at section numbers; marginal notes as titles"})
    print(S["id"], "sections", len(heads), "new", len(rows) - n0)
if os.environ.get("DRY"):
    for r in rows[:3] + rows[200:202] + rows[-2:]: print(r["rule_id"], "|", r["title"], "|", r["part"], "|", repr(r["text"][:100]), "...", repr(r["text"][-80:]))
else:
    with open(OUT, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
