#!/usr/bin/env python3
"""Bolivia TDJ Pando chamber composition from official
https://pando.organojudicial.gob.bo/Paper/ConformacionSala
Public names/titles only. Polite 2s. Appends; dedupe by judge_id."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_COURTS = _ipfs_Path(_ipfs_os.environ.get("WORLD_COURTS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_courts")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, re, os, html, hashlib, datetime, time, urllib.request, unicodedata

ROOT = str(_COURTS)
OUT = f"{ROOT}/data/bo/bo_judges.jsonl"
URL = "https://pando.organojudicial.gob.bo/Paper/ConformacionSala"
COURT_ID = "bo-tdj-pando"
UA = {"User-Agent": "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"}
POL = "robots_ignored_per_user_authorization|pando.organojudicial.gob.bo official TDJ Pando; public chamber roster; polite 2s"
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()

def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")

def lines_of(raw):
    h = raw.decode("utf-8", "replace")
    t = re.sub(r"<script[^>]*>.*?</script>", "", h, flags=re.S | re.I)
    t = re.sub(r"<style[^>]*>.*?</style>", "", t, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    return [re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip()]

NAME_ONE = re.compile(r"^(?:Dr\.|Dra\.|M\.?Sc\.|MSc\.|Lic\.)\s*(.+)$", re.I)

def parse_pando(lines):
    """Pando lists one multi-matter Sala then Dr./Dra. names; role lines
    (PRESIDENTE/VOCAL) appear only for some. First named without role
    treated as Presidente de Sala; others without role as Vocal; needs_review."""
    rows = []
    i = 0
    while i < len(lines):
        l = lines[i]
        # Sala header: starts with "Sala " (not "Salas" nav) and long enough
        if re.match(r"^Sala\b", l, re.I) and "encargada" not in l.lower() and "plena" not in l.lower() and len(l) > 10:
            sala = l.strip().rstrip(".")
            j = i + 1
            pending = None
            names_in_sala = []
            while j < len(lines):
                if re.match(r"^Sala\b", lines[j], re.I) and "encargada" not in lines[j].lower():
                    break
                if re.match(r"^Tribunal (Departamental|Supremo|Agroambiental)", lines[j], re.I):
                    break
                if re.match(r"^Consejo de la Magistratura", lines[j], re.I):
                    break
                if re.match(r"^Autoridades", lines[j], re.I):
                    break
                if lines[j].lower().startswith("sala encargada"):
                    j += 1
                    continue
                m = NAME_ONE.match(lines[j])
                if m:
                    if pending:
                        names_in_sala.append((pending, None))
                    pending = re.sub(r"\s+", " ", m.group(1)).strip(" -")
                    j += 1
                    continue
                if pending and re.match(r"^(PRESIDENTE|VOCAL)$", lines[j], re.I):
                    role = "Presidente" if lines[j].upper().startswith("PRESID") else "Vocal"
                    names_in_sala.append((pending, role))
                    pending = None
                    j += 1
                    continue
                j += 1
            if pending:
                names_in_sala.append((pending, None))
            # Assign default roles when missing: first -> Presidente, rest -> Vocal
            for idx, (name, role) in enumerate(names_in_sala):
                if not role:
                    role = "Presidente" if idx == 0 else "Vocal"
                rows.append((name, f"{role} de {sala}", sala, role is None or True))
                # needs_review always True for imputed roles; mark via 4th tuple always True for pando
            # Fix: track which roles were imputed
            rows = []
            for idx, (name, role) in enumerate(names_in_sala):
                imputed = role is None
                if not role:
                    role = "Presidente" if idx == 0 else "Vocal"
                rows.append((name, f"{role} de {sala}", sala, imputed or True))  # always needs_review (messy page)
        i += 1
    return rows

time.sleep(2)
raw = urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=60).read()
sha = hashlib.sha256(raw).hexdigest()
lines = lines_of(raw)
parsed = parse_pando(lines)
print("parsed", len(parsed))
for p in parsed:
    print(" ", p)

old_ids = {json.loads(l)["judge_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
added = []
seen = set()
for name, title, sala, _nr in parsed:
    if not name or len(name) < 4:
        continue
    base = f"{COURT_ID}-{slug(name)}"
    jid = base
    n = 2
    while jid in seen:
        jid = f"{base}-{n}"; n += 1
    seen.add(jid)
    if jid in old_ids:
        continue
    pt = "chamber_president" if title.lower().startswith("presidente") else "appellate"
    rec = {
        "judge_id": jid, "court_id": COURT_ID, "name": name, "title": title,
        "position_type": pt, "chamber": sala, "term_start": None, "term_end": None,
        "status": "sitting", "jurisdiction": "BO-N",
        "roster_url": URL, "source_url": URL,
        "source_kind": "official", "site_policy": POL, "retrieved_at": NOW,
        "needs_review": True,
        "extraction": "official TDJ Pando Paper/ConformacionSala; roles imputed when page omits PRESIDENTE/VOCAL label (first listed=Presidente, others=Vocal)",
        "license": "Órgano Judicial de Bolivia official website (public facts)",
        "source_sha256": sha, "language": "es",
    }
    added.append(rec)
    old_ids.add(jid)

with open(OUT, "a") as f:
    for r in added:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(added))
for r in added:
    print(r["name"], "|", r["title"])
