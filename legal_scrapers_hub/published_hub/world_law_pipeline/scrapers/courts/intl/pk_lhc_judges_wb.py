"""PK: Lahore High Court sitting judges from the Wayback Machine snapshot of data.lhc.gov.pk/judges/sitting_judges
(origin lhc.gov.pk unreachable from box; lhc.gov.pk robots.txt = 'Disallow: /' so ONLY the archived copy is used, tagged in site_policy).
Names and official titles only (DOB/appointment dates NOT stored). Retirement date used solely as a filter: judges whose
listed retirement date (age 62) is before today are skipped. Snapshot is dated, so rows are needs_review."""
import json, re, html, datetime, hashlib, os, requests
ROOT = "/workspace/world_courts"; UA = "Mozilla/5.0 (world_courts research; public court data)"
BASE = "https://data.lhc.gov.pk/judges/sitting_judges"
PAGES = [("20250201175420", BASE), ("20250213180610", BASE + "/20")]  # /40 only archived 2022 => too stale, not used
OUT = f"{ROOT}/data/pk/pk_judges.jsonl"; CID = "osm:node/2953146416"  # Lahore High Court courthouse row
now = datetime.datetime.now(datetime.UTC); today = now.date()
def pd(s):
    try: return datetime.datetime.strptime(s.replace(".", ""), "%b %d, %Y").date()
    except ValueError: return None
recs = []
for TS, SRC in PAGES:
  r = requests.get(f"https://web.archive.org/web/{TS}id_/{SRC}", headers={"User-Agent": UA}, timeout=120); r.raise_for_status(); t = r.text; sha = hashlib.sha256(r.content).hexdigest()
  cells = [re.sub(r"\s+", " ", html.unescape(c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", re.sub(r"<(?!/?td)[^>]+>", " ", t), re.S)]
  i = 0
  while i < len(cells):
      m = re.match(r"^(?:(The Chief Justice|Senior Puisne Judge)\s+)?((?:Mr\.|Mrs\.|Miss|Ms\.)?\s*Justice\s+.+)$", cells[i])
      if m and i + 3 < len(cells) and pd(cells[i + 3]):
          role, nm = m.group(1), m.group(2); ret = pd(cells[i + 3])
          name = re.sub(r"^(?:Mr\.|Mrs\.|Miss|Ms\.)?\s*Justice\s+(?:Mr\.|Mrs\.|Miss|Ms\.)?\s*", "", nm).strip(" .")
          recs.append((name, role, ret, TS, SRC, sha)); i += 4; continue
      i += 1
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
have = {slug(x["name"]) for x in old}; ids = {x["judge_id"] for x in old}; n = skip_ret = 0
with open(OUT, "a") as f:
    for name, role, ret, TS, SRC, sha in recs:
        if ret < today: skip_ret += 1; continue
        jid = f"pk-lahore-high-court-{slug(name)}"
        if slug(name) in have or jid in ids: continue
        title = {"The Chief Justice": "Chief Justice, Lahore High Court", "Senior Puisne Judge": "Senior Puisne Judge, Lahore High Court"}.get(role, "Judge, Lahore High Court")
        f.write(json.dumps({"judge_id": jid, "court_id": CID, "name": name, "title": title, "position_type": "chief" if role == "The Chief Justice" else "associate",
            "term_start": None, "term_end": None, "status": "sitting", "roster_url": BASE, "source_url": f"https://web.archive.org/web/{TS}/{SRC}",
            "site_policy": f"archived_copy(wayback:{TS[:8]});origin_robots_disallow_all(lhc.gov.pk);origin_unreachable",
            "retrieved_at": now.isoformat(), "needs_review": True,
            "extraction": "LHC 'Hon'ble Sitting Judges' table as archived 2025-02-01 (names/titles only; judges with listed retirement date before retrieval skipped; later transfers/elevations not reflected)",
            "license": "Lahore High Court website (facts); site copyright notice applies to photos/material", "source_sha256": sha}, ensure_ascii=False) + "\n")
        n += 1; have.add(slug(name)); ids.add(jid)
print("parsed", len(recs), "retired_skipped", skip_ret, "added", n)
