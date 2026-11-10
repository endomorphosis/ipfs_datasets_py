"""Maldives: all sitting judges from the Judicial Service Commission 'Judges' list export (https://jsc.gov.mv/judges/ ->
'Export List' https://jsc.gov.mv/export/JudgeList/, xlsx with court / post / full name in Dhivehi). Official source.
Honorifics (އަލްއުސްތާޛު / އަލްއުސްތާޛާ) are stripped into name_honorific; names are kept in Thaana only (no transliteration);
English post titles are our translations -> needs_review. Supreme Court rows already present from supremecourt.mv are skipped
(matched on Thaana name). judge_id = mv-jsc-<sha1(court|post|name)[:12]>; re-runs add 0. robots.txt: only content-signal comments, no
Disallow (robots_allowed)."""
import json, os, re, io, hashlib, datetime, time, urllib.request, collections, openpyxl
ROOT = "/workspace/world_courts"; OUT = f"{ROOT}/data/mv/mv_judges.jsonl"; RAWD = f"{ROOT}/state/raw_mv"; os.makedirs(RAWD, exist_ok=True)
URL = "https://jsc.gov.mv/export/JudgeList/"; ROSTER = "https://jsc.gov.mv/judges/"
UA = {"User-Agent": "Mozilla/5.0 (WorldCourtsResearchBot/1.0; public court data; polite)"}
now = datetime.datetime.now(datetime.UTC).isoformat()
b = urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=120).read(); time.sleep(2)
sha = hashlib.sha256(b).hexdigest(); open(f"{RAWD}/jsc_judgelist_{datetime.date.today():%Y%m%d}.xlsx", "wb").write(b)
rows = list(openpyxl.load_workbook(io.BytesIO(b)).active.iter_rows(values_only=True))
hdr = next(i for i, r in enumerate(rows) if r and r[0] == "ކޯޓު")
COURT = {"ދިވެހިރާއްޖޭގެ ސުޕްރީމް ކޯޓު": ("mv-supreme-court", "Supreme Court of the Maldives"),
         "ދިވެހިރާއްޖޭގެ ހައިކޯޓު": ("mv-high-court-of-maldives", "High Court of the Maldives"),
         "ސިވިލް ކޯޓު": ("mv-civil-court", "Civil Court"), "ކްރިމިނަލް ކޯޓު": ("mv-criminal-court", "Criminal Court"),
         "ފެމިލީ ކޯޓު": ("mv-family-court", "Family Court"), "ޖުވެނައިލް ކޯޓު": ("mv-juvenile-court", "Juvenile Court"),
         "ޑްރަގް ކޯޓު": ("mv-drug-court", "Drug Court")}
POST = {"އުއްތަމަފަނޑިޔާރު": ("Chief Justice", "chief"), "ފަނޑިޔާރު": ("Judge", "judge"), "އިސްފަނޑިޔާރު": ("Chief Judge", "chief"),
        "އިސް ފަނޑިޔާރު": ("Chief Judge", "chief"), "ޤާޟީ": ("Judge (Qazi)", "judge"), "އިސް ޤާޟީ": ("Chief Judge (Qazi)", "chief"),
        "އިސް ގާޞީ": ("Chief Judge (Qazi)", "chief"), "މެޖިސްޓްރޭޓް": ("Magistrate", "magistrate"),
        "އިސްމެޖިސްޓްރޭޓް": ("Chief Magistrate", "magistrate"), "އިސް މެޖިސްޓްރޭޓް": ("Chief Magistrate", "magistrate"),
        "ދާއިރާ އިސްމެޖިސްޓްރޭޓް": ("Circuit Chief Magistrate", "magistrate"), "ދާއިރާ އިސް މެޖިސްޓްރޭޓް": ("Circuit Chief Magistrate", "magistrate"),
        "ދާއިރާގެ އިސްމެޖިސްޓްރޭޓް": ("Circuit Chief Magistrate", "magistrate"), "މެޖިސްޓްރޭޓް (މ.ޖުޑީޝަލް ދާއިރާ)": ("Magistrate (M. judicial circuit)", "magistrate")}
HON = re.compile(r"^(އަލްއުސްތާޛު|އަލްއުސްތާޛާ|އަލްއުސްތާޛް)\s+")
def norm(s): return re.sub(r"\s+", " ", (s or "").replace("ﷲ", "އްލާހު")).strip()
existing = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
old_ids = {r["judge_id"] for r in existing}; sc_names = {norm(r.get("name_local")) for r in existing if r["court_id"] == "mv-supreme-court"}
new, skipped_sc, seen = [], 0, collections.Counter()
for r in rows[hdr + 1:]:
    if not r or not r[2]: continue
    court_l, post_l, full = norm(r[0]), norm(r[1]), norm(r[2])
    m = HON.match(full); hon = m.group(1) if m else None; name = HON.sub("", full)
    cid, cname = COURT.get(court_l, ("mv-magistrate-courts", None))
    if cid == "mv-supreme-court" and (name in sc_names or full in sc_names or norm(name.replace("ޑޮކްޓަރ ", "")) in {norm(x.replace("ޑޮކްޓަރ ", "")) for x in sc_names}):
        skipped_sc += 1; continue
    t, pos = POST.get(post_l, (None, None))
    if cid == "mv-supreme-court" and t == "Judge": t, pos = "Justice of the Supreme Court", "associate"
    key = f"{court_l}|{post_l}|{name}"; seen[key] += 1
    jid = "mv-jsc-" + hashlib.sha1(f"{key}|{seen[key]}".encode()).hexdigest()[:12]
    if jid in old_ids: continue
    new.append({"judge_id": jid, "court_id": cid, "court_name": cname, "court_name_local": court_l, "name": name, "name_local": name,
        "name_honorific": hon, "name_as_listed": full, "title": t, "title_local": post_l, "position_type": pos, "term_start": None, "term_end": None,
        "status": "sitting", "jurisdiction": "MV", "roster_url": ROSTER, "source_url": URL, "source_kind": "official",
        "site_policy": "robots_allowed|jsc.gov.mv: robots.txt content-signal preamble only (no signals set); no licence stated",
        "retrieved_at": now, "needs_review": True, "extraction": "JSC judge list xlsx export (court, post, full name); English titles translated by us",
        "license": "official public register; no licence stated", "source_sha256": sha, "language": "dv"})
print("listed", len(rows) - hdr - 1, "skipped_existing_sc", skipped_sc, "new", len(new), "unmapped_posts", sorted({x["title_local"] for x in new if not x["title"]}))
if os.environ.get("DRY"):
    print(collections.Counter(x["court_id"] for x in new)); print(collections.Counter(x["title"] for x in new))
else:
    with open(OUT, "a") as f:
        for x in new: f.write(json.dumps(x, ensure_ascii=False) + "\n")
