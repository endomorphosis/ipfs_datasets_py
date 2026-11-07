"""VN: Quyết định 114/QĐ-TANDTC (01/7/2025) list of 34 provincial + 355 regional People's Courts, as published by Tạp chí Tòa án nhân dân (TANDTC journal, robots allow)."""
import json, sys, re, datetime, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
from bs4 import BeautifulSoup as B
P = f"{ROOT}/rules/raw/vn_dir/tct_13686.html"; U = "https://www.tapchitoaan.vn/danh-sach-dia-diem-dat-tru-so-chinh-cua-34-toa-an-nhan-dan-cap-tinh-va-355-toa-an-nhan-dan-khu-vuc13686.html"
now = datetime.datetime.now(datetime.UTC).isoformat(); OUT = f"{ROOT}/data/vn/vn_courthouses.jsonl"
old = [json.loads(l) for l in open(OUT)]; oldid = {r["court_id"] for r in old}; oldn = {norm(r["name"]) for r in old}
L = B(open(P), "html.parser").get_text("\n", strip=True).split("\n"); prov = None; rows = []; miss = 0
for i, x in enumerate(L):
    m = re.match(r"^\d+\.\s*(TỈNH|THÀNH PHỐ)\s+(.+)$", x)
    if m: prov = m.group(2).title(); continue
    if re.match(r"^(TAND|Tòa án nhân dân)\s", x) and prov and i + 1 < len(L):
        a = L[i + 1]
        if not a.startswith("Địa chỉ"): miss += 1; continue
        addr = re.sub(r"^Địa chỉ\s*:?\s*", "", a).strip()
        nm = re.sub(r"\s+", " ", x).strip(); scope = None
        mm = re.match(r"^(.*?)\s*\((.*)\)?\s*$", nm)
        if mm: nm, scope = mm.group(1).strip(), mm.group(2).rstrip(")").strip()
        full = re.sub(r"^TAND\b", "Tòa án nhân dân", nm)
        lvl = "trial" if "khu vực" in full else "appellate"
        cid = "vn-tand-" + re.sub(r"[^a-z0-9]+", "-", norm(full)).strip("-")
        if cid in oldid or norm(full) in oldn or cid in {r["court_id"] for r in rows}: continue
        rows.append({"court_id": cid, "record_type": "courthouse", "name": full, "name_local": full, "level": lvl, "court_system": "national", "country_code": "VN",
          "subdivision": "VN", "jurisdiction": scope, "parent_court_id": None, "address": {"street": addr, "city": None, "postcode": None, "region": prov, "country": "VN"},
          "geo": {"lat": None, "lon": None}, "phone": None, "website": None, "wikidata": None, "place_ids": [], "source_url": U, "source_kind": "official",
          "site_policy": "robots_allowed;official:Tạp chí Tòa án nhân dân (TANDTC) publishing QĐ 114/QĐ-TANDTC", "retrieved_at": now,
          "license": "Vietnamese official decisions are not protected (Law on IP 2005 art. 15)", "effective_date": "2025-07-01",
          "record_note": "Post-1 July 2025 court system (Nghị quyết 81/2025/UBTVQH15); district-level courts in OSM rows are pre-reform"})
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
from collections import Counter
print("added", len(rows), "miss", miss, Counter(r["level"] for r in rows), len({r["address"]["region"] for r in rows}))
