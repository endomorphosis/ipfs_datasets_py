"""CW/AW/SX/BQ: Gemeenschappelijk Hof van Justitie (ghvj.org, official; robots.txt 'Disallow:' empty = allowed). Uses the site's public
WordPress media listing (wp-json/wp/v2/media?mime_type=application/pdf) to find:
 - FORMS: model petitions (modelverzoekschriften), application forms (aanvraagformulieren, alimentatie formulieren), administrative-law
   objection/appeal templates (bezwaarschrift / beroepschrift / hoger beroepschrift), complaint form. Checklists (checklijsten) are NOT ingested.
   Island-specific files -> data/<aw|cw|sx>/..._forms.jsonl; Bonaire/St Eustatius/Saba (BES) and court-wide files -> data/cw with applies_to.
 - RULES: Procesreglement Civiele Zaken 2026, Strafprocesreglement (in force 1 Sep 2024), Procesreglement bestuursrecht, Procesregeling
   belastingrecht (GEA 2025, Hof 2022), Code zaakstoedeling, Wrakingsprotocol, Klachtenregeling, Faillissementsrichtlijnen -> data/cw/cw_rules.jsonl
   (applies_to AW/CW/SX/BQ), article-level when 'Artikel N' headings are found, otherwise one document-level row.
Polite 2 s/request; dedupe by sha256 + source_url; append-only. Usage: ghvj_forms_rules.py [--dry]"""
import json, re, os, sys, time, hashlib, datetime, subprocess, shutil, html
ROOT = "/workspace/world_courts"; DL = f"{ROOT}/rules/raw/ghvj/dl"; os.makedirs(DL, exist_ok=True)
UA = "world_courts/0.1 (open court-data research; github.com/endomorphosis)"; dry = "--dry" in sys.argv
now = datetime.datetime.now(datetime.timezone.utc).isoformat(); B = "https://ghvj.org"
POL = "robots_allowed|ghvj.org robots.txt has an empty Disallow (all allowed); official Joint Court of Justice website, no licence/terms stated"
ALL = ["AW", "CW", "SX", "BQ"]; GHVJ = "osm:way/1446424248"
def curl(u, out=None):
    r = subprocess.run(["curl", "-sk", "-L", "-m", "180", "-A", UA] + (["-o", out] if out else []) + [u], capture_output=True); time.sleep(2); return r.stdout
media = []
for p in range(1, 10):
    b = curl(f"{B}/wp-json/wp/v2/media?mime_type=application/pdf&per_page=100&page={p}&_fields=source_url,date,title")
    try: L = json.loads(b)
    except Exception: break
    if not isinstance(L, list) or not L: break
    media += L
print("media pdfs", len(media))
def fname(u): return u.rsplit("/", 1)[-1]
FORM_RE = re.compile(r"(model|formulier|aanvraagform|beroepschrift|bezwaarschrift|verzoek-kinderalimentatie|MODE\d|^ENG-MO1|^PAP[OU](MO|AA)1|klachtformulier|gevolg-geven)", re.I)
RULES = [  # (filename regex, rule_set_id, rule_set title)
 (r"^Procesreglement-Civiele-Zaken-2026", "ghvj-procesreglement-civiel-2026", "Procesreglement Civiele Zaken 2026 (Gemeenschappelijk Hof van Justitie en Gerechten in eerste aanleg)"),
 (r"^Strafprocesreglement-inwerkingtreding-1-september-2024", "ghvj-strafprocesreglement-2024", "Strafprocesreglement (in werking 1 september 2024)"),
 (r"^DEF-Procesreglement-bestuursrecht", "ghvj-procesreglement-bestuursrecht", "Procesreglement bestuursrecht"),
 (r"^Procesregeling-belastingrecht-GEA-2025", "ghvj-procesregeling-belastingrecht-gea-2025", "Procesregeling belastingrecht Gerecht in eerste aanleg 2025"),
 (r"^Procesregeling-belastingrecht-Hof-2022", "ghvj-procesregeling-belastingrecht-hof-2022", "Procesregeling belastingrecht Hof 2022"),
 (r"^20250508_Code-zaakstoedeling", "ghvj-code-zaakstoedeling-2025", "Code zaakstoedeling GHvJ (vastgesteld 8 mei 2025)"),
 (r"^230309-DEFINITIEF-Wrakingsprotocol", "ghvj-wrakingsprotocol-2023", "Wrakingsprotocol (9 maart 2023)"),
 (r"^GHvJ_Klachtenregeling", "ghvj-klachtenregeling", "Klachtenregeling Gemeenschappelijk Hof van Justitie"),
 (r"^Faillissementsrichtlijnen-2012-versie-2023", "ghvj-faillissementsrichtlijnen-2023", "Faillissementsrichtlijnen 2012 (versie 2023)"),
]
def island(fn):
    f = fn.upper()
    if re.search(r"(^|[_-])(AW|AUA)([_-]|\.PDF)", f) or "ARUBA" in f: return "aw", ["AW"]
    if re.search(r"(^|[_-])(SXM)([_-]|\.PDF)", f) or "SINT-MAARTEN" in f: return "sx", ["SX"]
    if re.search(r"(^|[_-])(BES|BON|EUX|SABA)([_-]|\.PDF)", f) or re.search(r"BONAIRE|EUSTATIUS|-SABA-", f): return "cw", ["BQ"]
    if re.search(r"(^|[_-])CW([_-]|\.PDF)", f) or "CURACAO" in f: return "cw", ["CW"]
    return "cw", ALL
def rjl(p): return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []
def get_pdf(u):
    p = f"{DL}/{fname(u)}"
    if not os.path.exists(p):
        if shutil.disk_usage("/workspace").free < 20 * 2**30: raise SystemExit("disk < 20 GB, pausing downloads")
        curl(u, p)
    b = open(p, "rb").read() if os.path.exists(p) else b""
    return (p, b) if b.startswith(b"%PDF") else (None, None)
# ---------------- forms
seen = {}; nf = {}
for cc in ("aw", "cw", "sx"):
    seen[cc] = rjl(f"{ROOT}/data/{cc}/{cc}_forms.jsonl")
shas = {r["pdf_sha256"] for v in seen.values() for r in v}; srcs = {r["source_url"] for v in seen.values() for r in v}
for m in sorted(media, key=lambda x: x["date"], reverse=True):
    u = m["source_url"]; fn = fname(u)
    if not FORM_RE.search(fn) or re.search(r"checkl", fn, re.I) or u in srcs: continue
    p, b = get_pdf(u)
    if not b: continue
    sha = hashlib.sha256(b).hexdigest()
    if sha in shas: continue
    cc, app = island(fn); title = html.unescape(m["title"]["rendered"]).strip() or fn
    lang = "pap" if re.search(r"PAP", fn) else "en" if re.search(r"(^|[_-])(EN|ENG)[_-]|english|engels", fn, re.I) else "nl"
    cat = "family" if re.search(r"alimentatie|gezag|echtscheiding|curatele", fn, re.I) else "administrative" if re.search(r"beroepschrift|bezwaarschrift|gevolg-geven", fn, re.I) \
          else "estates" if re.search(r"boedel|vereffenaar|nalatenschap|tegeldemaking", fn, re.I) else "complaint" if "klacht" in fn.lower() else "civil"
    os.makedirs(f"{ROOT}/forms/{cc}", exist_ok=True)
    row = {"form_id": f"{cc}-{sha[:16]}", "court_id": GHVJ if cc == "cw" else f"{cc}-lower-court", "jurisdiction": "GHvJ" if app == ALL else app[0], "applies_to": app,
           "form_number": None, "title": title, "category": cat, "language": lang, "revision_date": m["date"][:10], "file_format": "pdf",
           "pdf_path": f"forms/{cc}/{sha}.pdf", "pdf_sha256": sha, "file_bytes": len(b), "source_url": u, "index_url": f"{B}/alle-onderwerpen/",
           "source_kind": "official", "site_policy": POL, "license": "Gemeenschappelijk Hof van Justitie official form/model; no licence stated",
           "retrieved_at": now, "needs_review": app == ["BQ"] or None,
           "description": "found via ghvj.org WordPress media listing; revision_date = upload date" + ("; Caribbean Netherlands (BES) form stored under data/cw (no data/bq)" if app == ["BQ"] else "")}
    if not dry:
        shutil.copy(p, f"{ROOT}/forms/{cc}/{sha}.pdf")
        with open(f"{ROOT}/data/{cc}/{cc}_forms.jsonl", "a") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
    shas.add(sha); srcs.add(u); nf[cc] = nf.get(cc, 0) + 1
print("forms new", nf)
# ---------------- rules
RO = f"{ROOT}/data/cw/cw_rules.jsonl"; ids = {r["rule_id"] for r in rjl(RO)}; rows = []; rep = []
LIC = "Gemeenschappelijk Hof van Justitie procedural regulation (procesreglement/regeling); no licence stated"
for rx, sid, title in RULES:
    cand = sorted([m for m in media if re.search(rx, fname(m["source_url"]))], key=lambda x: x["date"], reverse=True)
    if not cand: rep.append((sid, "not listed")); continue
    m = cand[0]; u = m["source_url"]; p, b = get_pdf(u)
    if not b: rep.append((sid, "fetch failed")); continue
    sha = hashlib.sha256(b).hexdigest()
    txt = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout.replace("\f", "\n")
    if len(txt.strip()) < 300: rep.append((sid, "no text")); continue
    hs = [(mm.start(), mm.group(1)) for mm in re.finditer(r"(?m)^\s*(?:Artikel|Art\.)\s+(\d+[a-z]?(?:\.\d+)?)\b", txt)]
    seq = []; last = 0
    for pos, n in hs:
        k = int(re.match(r"\d+", n).group(0))
        if (not seq and k == 1) or (seq and last <= k <= last + 3 and n != seq[-1][1]): seq.append((pos, n)); last = k
    base = {"rule_set_id": sid, "court_id": GHVJ, "jurisdiction": "GHvJ", "applies_to": ALL, "rule_set": title, "part": None, "effective_date": None,
            "pdf_path": f"rules/raw/ghvj/dl/{fname(u)}", "pdf_sha256": sha, "source_sha256": sha, "source_url": u, "index_url": f"{B}/professionals/",
            "source_kind": "official", "site_policy": POL, "license": LIC, "retrieved_at": now, "language": "nl", "needs_review": True}
    def clean(s): s = re.sub(r"[ \t]+", " ", s); return re.sub(r"\n\s*\n+", "\n", s).strip()
    if len(seq) >= 5:
        pre = clean(txt[:seq[0][0]])
        if len(pre) > 200 and f"{sid}:preamble" not in ids:
            rows.append({"rule_id": f"{sid}:preamble", "rule_number": "Preamble", "title": "Inleiding / considerans", "text": pre[:150000], **base, "version_note": f"pdftotext; upload {m['date'][:10]}"})
        for i, (pos, n) in enumerate(seq):
            body = clean(txt[pos:seq[i + 1][0] if i + 1 < len(seq) else len(txt)]); rid = f"{sid}:art-{n.lower()}"
            if rid in ids: continue
            ids.add(rid); first = body.split("\n", 1)[0]; tt = re.sub(r"^\s*(Artikel|Art\.)\s+\S+\s*[\.:-]?\s*", "", first)[:150] or None
            rows.append({"rule_id": rid, "rule_number": f"Artikel {n}", "title": tt, "text": body[:150000], **base, "version_note": f"pdftotext article split; upload {m['date'][:10]}"})
        rep.append((sid, "articles", len(seq)))
    else:
        rid = f"{sid}:doc"
        if rid not in ids:
            rows.append({"rule_id": rid, "rule_number": None, "title": title, "text": clean(txt)[:150000], **base, "version_note": f"document-level row (no 'Artikel' structure found); upload {m['date'][:10]}"})
        rep.append((sid, "doc"))
if not dry and rows:
    with open(RO, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("rules new", len(rows)); [print(x) for x in rep]
