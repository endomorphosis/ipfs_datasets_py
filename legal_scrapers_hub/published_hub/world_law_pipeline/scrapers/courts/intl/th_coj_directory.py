"""TH: Office of the Judiciary (coj.go.th) 'หน่วยงานภายในศาลยุติธรรม' page - official list of Courts of Justice with their websites
(supreme, appeal, specialised, Bangkok first-instance, 9 regional groups). Names + official website only (court sub-sites return 403 and the
COJ open-data address XLSX has an expired TLS certificate, so no street addresses). Existing rows matched on Thai name are not duplicated."""
import json, sys, re, datetime, hashlib, os
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
SRC = "https://www.coj.go.th/th/content/category/detail/id/6/iid/121186"
RAW = f"{ROOT}/rules/raw/th_dir/coj_units_121186.html"
if not os.path.exists(RAW):
    open(RAW, "w").write(get(SRC, delay=3))
txt = open(RAW, errors="ignore").read(); sha = hashlib.sha256(txt.encode()).hexdigest()
OUT = f"{ROOT}/data/th/th_courthouses.jsonl"; old = rjl(OUT)
def tn(s): return re.sub(r"\s+|ฯ|\(.*?\)|จังหวัด|จ\.", "", s or "")
oldn = {tn(r.get("name_local") or ""): r for r in old if r.get("name_local")} | {tn(r["name"]): r for r in old}
oldid = {r["court_id"] for r in old}
GRP = {"supreme": None, "bkk": "กรุงเทพมหานคร", "special": None, "corrupt": None}
now = datetime.datetime.now(datetime.UTC).isoformat(); rows = []; skipped = 0
i = txt.find("const D = [")
for m in re.finditer(r"\{id:'([^']+)',\s*title:'([^']+)'.*?links:\[(.*?)\]\}", txt[i:], re.S):
    gid, gtitle = m.group(1), m.group(2)
    if gid in ("central", "other"): continue
    for n, u in re.findall(r"\{n:'([^']+)',u:'([^']+)'\}", m.group(3)):
        if n.startswith("สำนักศาลยุติธรรมประจำภาค"): continue  # administrative regional office, not a court
        full = n.replace("ศาลเยาวชนฯ จ.", "ศาลเยาวชนและครอบครัวจังหวัด").replace("ศาลอาญาคดีทุจริตฯ", "ศาลอาญาคดีทุจริตและประพฤติมิชอบ").replace("ศาลทรัพย์สินทางปัญญาฯ", "ศาลทรัพย์สินทางปัญญาและการค้าระหว่างประเทศกลาง")
        if n == "ศาลฎีกา": lvl, par = "supreme", "th-supreme-court"
        elif n.startswith("ศาลอุทธรณ์"): lvl, par = "appellate", "th-court-of-appeal"
        elif n.startswith("ศาลแขวง"): lvl, par = "trial_limited", "th-provincial-court"
        elif "เยาวชน" in n: lvl, par = "juvenile", "th-provincial-court"
        elif "ภาษี" in n: lvl, par = "tax", None
        elif n.startswith(("ศาลจังหวัด", "ศาลแพ่ง", "ศาลอาญา", "ศาลล้มละลาย", "ศาลแรงงาน", "ศาลทรัพย์สิน")): lvl, par = "trial_general", "th-provincial-court"
        else: lvl, par = "other", None
        if n == "ศาลฎีกา": par = None
        host = re.sub(r"^https?://|/.*$", "", u)
        cid = "th-coj-" + (host.split(".")[0] if host.endswith("coj.go.th") and not host.startswith("www.") else slug(host.replace("www.", "")))
        if cid in oldid or tn(full) in oldn or tn(n) in oldn or cid in {r["court_id"] for r in rows}: skipped += 1; continue
        prov = None
        mm = re.search(r"\(([^)]+)\)", n)
        if gid == "bkk": prov = "กรุงเทพมหานคร"
        elif mm and gid in ("supreme", "special", "corrupt"): prov = mm.group(1)
        rows.append(rec(court_id=cid, record_type="courthouse" if n != "ศาลฎีกา" else "courthouse", name=full, name_local=full, level=lvl, court_system="national",
            country_code="TH", subdivision="TH", jurisdiction=gtitle, parent_court_id=par if par != cid else None,
            address={"street": None, "city": None, "postcode": None, "region": prov, "country": "TH"}, website=u, source_url=SRC, source_kind="official",
            site_policy="robots_allowed", retrieved_at=now, license="Thai official information (Office of the Judiciary website); names/URLs are facts",
            source_sha256=sha, record_note="Official COJ directory of court websites; no street address published on this page"))
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(rows), "skipped_existing", skipped)
