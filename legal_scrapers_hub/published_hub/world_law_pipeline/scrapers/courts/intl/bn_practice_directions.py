"""Brunei Darussalam: Chief Justice / Chief Registrar practice directions and Chief Justice / Chief Registrar / Official Receiver /
Probate Officer / Chief Magistrate circulars, listed on judiciary.gov.bn 'Practice Directions and Circulars' (official PDFs).
One rule row per document (granularity 'document'); text via pdftotext (null where the PDF is an image scan). Circulars that are
purely administrative (practising-certificate renewals, letter-box rental, fasting-month hours, COVID, Legal Year attendance) are kept
but flagged category 'administrative_circular'. Appends to data/bn/bn_rules.jsonl, dedupe by rule_id; re-runs add 0.
robots.txt on judiciary.gov.bn returns 404 (robots_absent_allowed); site terms: gov.bn terms of use."""
import json, re, os, hashlib, datetime, subprocess, time, html, urllib.request
ROOT = "/workspace/world_courts"; RAW = f"{ROOT}/rules/raw/bn"; OUT = f"{ROOT}/data/bn/bn_rules.jsonl"
IDX = "https://www.judiciary.gov.bn/information/practice-directions-and-circulars/"; BASE = "https://www.judiciary.gov.bn"
UA = {"User-Agent": "Mozilla/5.0 (WorldCourtsResearchBot/1.0; public court data; polite)"}
now = datetime.datetime.now(datetime.UTC).isoformat(); os.makedirs(RAW, exist_ok=True)
def get(u):
    time.sleep(2); return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=180).read()
page = get(IDX).decode("utf-8", "replace")
links = [(m.group(1), html.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(2))).strip()) for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', page, re.S | re.I)]
docs = {}
for u, t in links:
    if "law_firms" in u: continue
    d = docs.setdefault(u, {"labels": []}); d["labels"].append(t)
KIND = {"chief_justice_practice_direction": ("bn-cj-pd", "Chief Justice Practice Directions", "Practice Direction"),
        "chief_registrar_practice_direction": ("bn-cr-pd", "Chief Registrar Practice Directions", "Practice Direction"),
        "chief_justice_circular": ("bn-cj-circ", "Chief Justice Circulars", "Circular"),
        "chief_registrar_circular": ("bn-cr-circ", "Chief Registrar Circulars", "Circular"), "CR-Circular": ("bn-cr-circ", "Chief Registrar Circulars", "Circular"),
        "official_receiver_circular": ("bn-or-circ", "Official Receiver Circulars", "Circular"),
        "probate_officer_circular": ("bn-po-circ", "Probate Officer Circulars", "Circular"),
        "chief_magistrate_circular": ("bn-cm-circ", "Chief Magistrate Circulars", "Circular")}
ADMIN = re.compile(r"practising cert|letter box|pigeonhole|fasting month|coronavirus|covid|opening of the legal year|downtime", re.I)
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
rows = []
for u, d in docs.items():
    fn = u.rsplit("/", 1)[1]; k = next(k for k in KIND if fn.startswith(k)); sid, sname, word = KIND[k]
    num = next((x for x in d["labels"] if re.fullmatch(r"(\d+ of )?\d{4}", x)), None)
    title = next((x for x in d["labels"] if x != num), None) or None
    if title == num: title = None
    rid = f"{sid}:{(num or fn).replace(' of ', '-').replace(' ', '')}"
    if rid in old or any(r["rule_id"] == rid for r in rows): continue
    p = f"{RAW}/{fn}"
    if not os.path.exists(p): open(p, "wb").write(get(BASE + u if u.startswith("/") else u))
    b = open(p, "rb").read(); sha = hashlib.sha256(b).hexdigest()
    txt = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout.strip()
    txt = re.sub(r"\n{3,}", "\n\n", txt.replace("\f", "\n")) if len(re.sub(r"\s", "", txt)) > 80 else None
    yr = re.search(r"(\d{4})$", num or "")
    rows.append({"rule_id": rid, "rule_set_id": sid, "court_id": None, "jurisdiction": "BN", "rule_set": sname,
        "rule_number": f"{word} No. {num}" if num and " of " in num else f"{word} {num or fn}", "title": title, "text": txt,
        "effective_date": None, "year": int(yr.group(1)) if yr else None, "category": "administrative_circular" if title and ADMIN.search(title) else ("practice_direction" if word == "Practice Direction" else "circular"),
        "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha, "source_url": BASE + u if u.startswith("/") else u, "index_url": IDX,
        "source_kind": "official", "site_policy": "robots_absent_allowed|gov.bn terms of use (https://www.gov.bn/term-of-use/)", "retrieved_at": now,
        "granularity": "document", "license": "official Brunei Judiciary publication; gov.bn terms of use", "language": "en",
        "needs_review": txt is None, "extraction": "pdftotext -layout (whole document)" if txt else "image-only PDF; no text layer"})
print("docs", len(docs), "new", len(rows), "no_text", sum(1 for r in rows if r["text"] is None))
if os.environ.get("DRY"):
    for r in rows: print(r["rule_id"], "|", r["rule_number"], "|", r["title"], "|", r["category"], "|", len(r["text"] or ""))
else:
    with open(OUT, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
