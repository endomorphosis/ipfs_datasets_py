"""BZ: Senior Courts of Belize (belizejudiciary.org, WordPress; robots.txt 404 => allowed). The site is a JS front-end; page data is read from
the site's public WP REST page objects (wp-json/wp/v2/pages/<id>, ACF 'profile_grid' / 'list' blocks), the same JSON the front-end renders.
Judges: High Court (page 906) + Court of Appeal (page 885) - names and official titles only (no bios/photos). Forms: 'court-forms' (1026) and
'rules-of-the-court-forms' (865) file attachments."""
import json, sys, re, datetime, hashlib, os, time, shutil, requests
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
BASE = "https://www.belizejudiciary.org"; H = {"User-Agent": UA}; RAW = f"{ROOT}/rules/raw/bz"; os.makedirs(RAW, exist_ok=True)
now = datetime.datetime.now(datetime.UTC).isoformat()
def page(i):
    p = f"{RAW}/page_{i}.json"
    if not os.path.exists(p):
        open(p, "w").write(requests.get(f"{BASE}/wp-json/wp/v2/pages/{i}?_fields=id,slug,link,acf,modified", headers=H, timeout=60).text); time.sleep(2)
    return json.load(open(p))
def clean(lbl):
    x = re.sub(r"\s+", " ", lbl).strip()
    x = re.sub(r"^Chief Justice,\s*", "", x)
    x = re.sub(r"^(Hon\.?|Mde\.?|Madame|Madam|Mme\.?|Mr\.?|Mrs\.?|Ms\.?|Justice)\s+", "", x); x = re.sub(r"^(Hon\.?|Mde\.?|Madame|Madam|Mme\.?|Mr\.?|Justice)\s+", "", x)
    x = re.sub(r"^(Madame|Madam|Mr\.?|Justice)\s+", "", x); x = re.sub(r"^Justice\s+", "", x)
    x = re.sub(r",?\s*(KC|OBE|JA|SC)(\s*,?\s*(KC|OBE|JA|SC))*\s*$", "", x).strip(" ,")
    return x
# ---- judges
JO = f"{ROOT}/data/bz/bz_judges.jsonl"; oj = {x["judge_id"] for x in rjl(JO)}; rows = []; seen_names = set()
for pid, court, cname in [(906, "bz-high-court", "High Court"), (885, "bz-court-of-appeal", "Court of Appeal")]:
    d = page(pid)
    for b in (d.get("acf") or {}).get("blocks") or []:
        if b.get("acf_fc_layout") != "profile_grid": continue
        for it in b.get("item") or []:
            lbl = (it.get("label") or "").strip(); tag = (it.get("tag") or "").strip()
            nm = clean(lbl)
            if not nm or nm in seen_names: continue  # Chief Justice listed on both pages -> one row
            seen_names.add(nm)
            if lbl.startswith("Chief Justice") or tag == "Chief Justice": title, pt = "Chief Justice of Belize", "chief"
            elif tag == "President": title, pt = "President of the Court of Appeal", "president"
            else: title, pt = ("Justice of Appeal" if court == "bz-court-of-appeal" else "Judge of the High Court"), "puisne"
            jid = f"bz-{'ca' if court == 'bz-court-of-appeal' else 'hc'}-{slug(nm)}"
            if jid in oj: continue
            rows.append({"judge_id": jid, "court_id": court, "name": nm, "title": title, "position_type": pt, "term_start": None, "term_end": None,
                "status": "sitting", "roster_url": d["link"], "source_url": f"{BASE}/wp-json/wp/v2/pages/{pid}", "site_policy": "robots_absent_allowed",
                "retrieved_at": now, "needs_review": True, "label_as_published": lbl, "extraction": f"{cname} judges page (ACF profile_grid labels)",
                "license": "Belize Judiciary public website"})
with open(JO, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("judges added", len(rows))
# ---- forms
FO = f"{ROOT}/data/bz/bz_forms.jsonl"; FD = f"{ROOT}/forms/bz"; os.makedirs(FD, exist_ok=True)
old = rjl(FO); osha = {r["pdf_sha256"] for r in old}; osrc = {r["source_url"] for r in old}; n = nb = 0; fail = []
for pid, cat in [(1026, "court-forms"), (865, "rules-of-the-court-forms")]:
    d = page(pid)
    for b in (d.get("acf") or {}).get("blocks") or []:
        for it in b.get("label") or [] if isinstance(b.get("label"), list) else []:
            fobj = it.get("file") or {}; src = fobj.get("url")
            if not src or src in osrc: continue
            if shutil.disk_usage("/workspace").free < 20 * 2**30: print("disk < 20 GB, pausing"); break
            time.sleep(2)
            try: r = requests.get(src, headers=H, timeout=120)
            except requests.RequestException as e: fail.append((src, str(e)[:50])); continue
            if r.status_code != 200 or len(r.content) < 500: fail.append((src, r.status_code)); continue
            ext = src.rsplit(".", 1)[-1].lower(); sha = hashlib.sha256(r.content).hexdigest()
            if sha in osha: continue
            open(f"{FD}/{sha}.{ext}", "wb").write(r.content)
            title = re.sub(r"\s+", " ", (it.get("label") or fobj.get("title") or "")).strip()
            row = {"form_id": f"bz-{sha[:16]}", "court_id": None, "jurisdiction": "BZ", "form_number": None, "title": title,
                   "category": cat + (f": {b.get('title').strip()}" if (b.get("title") or "").strip() and b.get("title").strip() != title else ""),
                   "language": "en", "revision_date": None, "file_format": ext, "pdf_path": f"forms/bz/{sha}.{ext}", "pdf_sha256": sha,
                   "file_bytes": len(r.content), "source_url": src, "index_url": d["link"], "license": "Belize Judiciary published forms; no licence stated",
                   "site_policy": "robots_absent_allowed", "retrieved_at": now}
            with open(FO, "a") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
            osha.add(sha); osrc.add(src); n += 1; nb += len(r.content)
print("forms added", n, "bytes", nb, "fail", fail)
