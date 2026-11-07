#!/usr/bin/env python3
"""Haiti Cour de cassation sitting members from English Wikipedia 'Supreme Court of Haiti'
(Current members section). Official courdecassation.ht / cspj.ht unreachable from box.
Names + titles only; needs_review=True; CC BY-SA 4.0. Append-only by judge_id / name slug."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_COURTS = _ipfs_Path(_ipfs_os.environ.get("WORLD_COURTS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_courts")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, re, os, datetime, urllib.request, hashlib

W = str(_COURTS)
OUT = f"{W}/data/ht/ht_judges.jsonl"
PAGE = "Supreme_Court_of_Haiti"
UA = "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
CID = "ht-supreme-court"
POL = "robots_allowed|en.wikipedia.org: CC BY-SA 4.0, attribution required (Wikimedia Terms of Use)"
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()

def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s

u = f"https://en.wikipedia.org/w/api.php?action=parse&page={PAGE}&prop=text|revid&format=json&formatversion=2"
d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60))["parse"]
rev = d["revid"]
src = f"https://en.wikipedia.org/w/index.php?title={PAGE}&oldid={rev}"
html = d["text"]
# Extract Current members block until next h2
m = re.search(r'(?is)<h2[^>]*>\s*Current members.*?</h2>(.*)(<h2|$)', html)
block = m.group(1) if m else ""
plain = re.sub(r"<[^>]+>", "\n", block)
plain = re.sub(r"\[edit[^\]]*\]", "", plain)
lines = [re.sub(r"\s+", " ", l).strip(" ,") for l in plain.splitlines() if l.strip()]
# Parse pairs: Name / , role (since YEAR)
members = []
i = 0
while i < len(lines):
    l = lines[i]
    if l.startswith("References") or l.startswith("^"):
        break
    # "Name" then next line ", President (since 2022)" OR "Name (since 2019)"
    m2 = re.match(r"^([A-ZÀÂÄÆÇÉÈÊËÎÏÔŒÙÛÜŸ][\wÀ-ÿ'.\-]+(?:\s+[A-ZÀÂÄÆÇÉÈÊËÎÏÔŒÙÛÜŸ][\wÀ-ÿ'.\-]+)+)(?:\s*\((since\s+\d{4})\))?$", l)
    if m2 and not l.lower().startswith("current"):
        name = m2.group(1).strip()
        since = m2.group(2)
        title = "Juge à la Cour de cassation"
        pt = "associate"
        # peek next line for role
        if i + 1 < len(lines) and re.match(r"^,?\s*(President|vice-president|Vice-president)", lines[i + 1], re.I):
            role = lines[i + 1].lstrip(", ").strip()
            if re.search(r"President", role, re.I) and not re.search(r"vice", role, re.I):
                title = f"Président de la Cour de cassation ({role})"
                pt = "chief"
            elif re.search(r"vice-president", role, re.I):
                title = f"Vice-président de la Cour de cassation ({role})"
                pt = "deputy_chief"
            since_m = re.search(r"since\s+(\d{4})", role, re.I)
            if since_m:
                since = since_m.group(0)
            i += 1
        elif since:
            title = f"Juge à la Cour de cassation ({since})"
        members.append((name, title, pt, since))
    i += 1

# Deduplicate by slug, prefer chief title
by = {}
for name, title, pt, since in members:
    k = slug(name)
    if k not in by or pt == "chief":
        by[k] = (name, title, pt, since)

old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
have = {slug(r["name"]) for r in old} | {r["judge_id"] for r in old}
rows = []
for k, (name, title, pt, since) in by.items():
    jid = f"{CID}-{k}"
    if k in have or jid in have:
        continue
    rows.append({
        "judge_id": jid, "court_id": CID, "name": name, "title": title, "position_type": pt,
        "term_start": None, "term_end": None, "status": "sitting", "jurisdiction": "HT",
        "roster_url": src, "source_url": src, "source_kind": "secondary",
        "site_policy": POL, "retrieved_at": NOW, "needs_review": True,
        "extraction": f"Wikipedia rev {rev}, 'Current members' section; official Haitian court sites unreachable from box",
        "license": "CC BY-SA 4.0 (Wikipedia contributors)",
        "source_sha256": hashlib.sha256(html.encode()).hexdigest(),
    })

with open(OUT, "a") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print("HT cassation wiki judges parsed", len(by), "new", len(rows), [r["name"] for r in rows])
