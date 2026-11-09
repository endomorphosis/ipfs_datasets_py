"""PK: Islamabad High Court (mis.ihc.gov.pk; robots.txt 404 => allowed). Forms from the public Downloads page's own JSON feed
(ihc.asmx/GetLatestNews pFeature=2, the same unauthenticated call the page makes); sitting judges from the site's 'Honourable Judges' menu
(names + official titles only)."""
import json, sys, re, datetime, hashlib, os, time, shutil, requests
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
B = "https://mis.ihc.gov.pk"; H = {"User-Agent": UA}
now = datetime.datetime.now(datetime.UTC).isoformat()
CID = "osm:way/780222423"  # existing Islamabad High Court courthouse row
def disk_ok(): return shutil.disk_usage("/workspace").free > 20 * 2**30
# ---- forms
OUT = f"{ROOT}/data/pk/pk_forms.jsonl"; FD = f"{ROOT}/forms/pk"; os.makedirs(FD, exist_ok=True)
old = rjl(OUT); osha = {r["pdf_sha256"] for r in old}; osrc = {r["source_url"] for r in old}
r = requests.post(f"{B}/ihc.asmx/GetLatestNews", data="{'pFeature':'2'}", headers={**H, "Content-Type": "application/json; charset=utf-8"}, timeout=60)
items = json.loads(r.json()["d"]); nf = 0; nb = 0; fail = []
for it in items:
    if not disk_ok(): print("disk < 20 GB, pausing downloads"); break
    att = it.get("Attachemnt")
    if not att: continue
    src = B + requests.utils.quote(att, safe="/")
    if src in osrc: continue
    time.sleep(2)
    try: f = requests.get(src, headers=H, timeout=120)
    except requests.RequestException as e: fail.append((att, str(e)[:60])); continue
    if f.status_code != 200 or len(f.content) < 500: fail.append((att, f.status_code)); continue
    ext = att.rsplit(".", 1)[-1].lower(); sha = hashlib.sha256(f.content).hexdigest()
    if sha in osha: continue
    open(f"{FD}/{sha}.{ext}", "wb").write(f.content)
    rev = f"{it['Year']:04d}-{it['Month']:02d}-{it['Date']:02d}" if it.get("Year") else None
    row = {"form_id": f"pk-{sha[:16]}", "court_id": CID, "jurisdiction": "PK-IS", "form_number": None, "title": it["Title"].strip(),
           "category": "ihc-judicial-forms", "language": "ur" if "Urdu" in att else "en", "revision_date": rev, "file_format": ext,
           "pdf_path": f"forms/pk/{sha}.{ext}", "pdf_sha256": sha, "file_bytes": len(f.content), "source_url": src, "index_url": f"{B}/frmDownloads.aspx",
           "description": (it.get("Description") or "").strip() or None,
           "license": "Islamabad High Court (mis.ihc.gov.pk) published forms; Pakistan government work, no licence stated",
           "site_policy": "robots_absent_allowed", "retrieved_at": now}
    with open(OUT, "a") as fo: fo.write(json.dumps(row, ensure_ascii=False) + "\n")
    osha.add(sha); nf += 1; nb += len(f.content)
print("forms added", nf, "bytes", nb, "fail", fail)
# ---- judges
JO = f"{ROOT}/data/pk/pk_judges.jsonl"; oj = {x["judge_id"] for x in rjl(JO)}
raw = open(f"{ROOT}/rules/raw/pk_ihc/frmSitting_0.html", errors="ignore").read()
blk = raw[raw.find('id="liStnJgs"'):raw.find('id="liStnFrmrCjs"')]
J = re.findall(r'href="frmJudges\.aspx\?jgs=(\d+)">([^<]+)</a>', blk); rows = []
for jid, nm in J:
    nm = re.sub(r"\s+", " ", re.sub(r"^Justice\s+", "", nm.strip()))
    chief = jid == "20"
    rid = "pk-ihc-" + slug(nm)
    if rid in oj or rid in {x["judge_id"] for x in rows}: continue
    rows.append({"judge_id": rid, "court_id": CID, "name": nm, "title": "Chief Justice, Islamabad High Court" if chief else "Judge, Islamabad High Court",
        "position_type": "chief" if chief else "puisne", "term_start": None, "term_end": None, "status": "sitting",
        "roster_url": f"{B}/frmSitting.aspx?Jgs=0", "source_url": f"{B}/frmJudges.aspx?jgs={jid}", "site_policy": "robots_absent_allowed",
        "retrieved_at": now, "needs_review": True, "extraction": "names as spelled in the official 'Honourable Judges' menu of mis.ihc.gov.pk",
        "license": "Islamabad High Court public website"})
with open(JO, "a") as fo:
    for x in rows: fo.write(json.dumps(x, ensure_ascii=False) + "\n")
print("judges added", len(rows))
