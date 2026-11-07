#!/usr/bin/env python3
"""Bolivia TDJ Chuquisaca chamber composition from Wayback snapshot of
official Oficinas/ComposicionSalas (live host returns HTTP 500).
Source: http://tdjch.organojudicial.gob.bo/Oficinas/ComposicionSalas?tipo=1
Snapshot: 20260214231746 (also 20251010032813 identical roster).
Public names/titles only. Polite. Appends; dedupe by judge_id.
"""
import json, re, os, html, hashlib, datetime, time, urllib.request, unicodedata

ROOT = "/workspace/world_courts"
OUT = f"{ROOT}/data/bo/bo_judges.jsonl"
COURT_ID = "bo-tdj-chuquisaca"
LIVE = "http://tdjch.organojudicial.gob.bo/Oficinas/ComposicionSalas?tipo=1"
WB_TS = "20260214231746"
URL = f"https://web.archive.org/web/{WB_TS}/{LIVE}"
UA = {"User-Agent": "WorldCourtsResearchBot/1.0 (+public court directory research; polite crawl)"}
POL = "robots_ignored_per_user_authorization|tdjch.organojudicial.gob.bo official TDJ Chuquisaca; live 500; Wayback ComposicionSalas roster; polite 3s"
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

NAME_RE = re.compile(
    r"^(?:Dr\.|Dra\.|M\.?Sc\.|Msc\.|Abg\.|Lic\.)\s*(.+)$", re.I
)
ROLE_RE = re.compile(r"^(PRESIDENTE(?:\s+TDJCH)?|VOCAL)$", re.I)
SALA_RE = re.compile(r"^SALA\b", re.I)

def clean_name(n):
    n = re.sub(r"\s+", " ", n or "").strip(" -")
    return n

def parse(lines):
    # Find start
    try:
        i0 = next(i for i, l in enumerate(lines) if "CONFORMACIÓN DE SALAS" in l.upper() or "CONFORMACION DE SALAS" in l.upper())
    except StopIteration:
        i0 = 0
    rows = []
    chamber_parent = None
    chamber = "Presidencia"
    i = i0
    while i < len(lines):
        l = lines[i]
        if l.upper().startswith("INFORMACIÓN") or l.upper().startswith("INFORMACION"):
            break
        if l.upper() == "PRESIDENCIA":
            chamber_parent = None
            chamber = "Presidencia"
            i += 1
            continue
        if SALA_RE.match(l) and "PRIMERA" not in l.upper() and "SEGUNDA" not in l.upper() and len(l) > 5:
            # parent section e.g. SALA CIVIL Y COMERCIAL / SALA PENAL / SALA CONSTITUCIONAL / SALA DE FAMILIA...
            # If next is SALA PRIMERA/SEGUNDA, this is parent; else this is the chamber itself (Familia/Social)
            chamber_parent = l.strip()
            # peek
            if i + 1 < len(lines) and re.match(r"^SALA\s+(PRIMERA|SEGUNDA)\b", lines[i + 1], re.I):
                i += 1
                continue
            chamber = chamber_parent
            chamber_parent = None
            i += 1
            continue
        if re.match(r"^SALA\s+(PRIMERA|SEGUNDA)\b", l, re.I):
            sub = l.strip()
            chamber = f"{chamber_parent} {sub}" if chamber_parent else sub
            i += 1
            continue
        m = NAME_RE.match(l)
        if m and i + 1 < len(lines) and ROLE_RE.match(lines[i + 1]):
            name = clean_name(m.group(1))
            role_raw = lines[i + 1].strip()
            if "TDJCH" in role_raw.upper():
                role = "Presidente del Tribunal Departamental de Justicia de Chuquisaca"
                ch = "Presidencia"
                pt = "chief_judge"
            elif role_raw.upper().startswith("PRESID"):
                role = f"Presidente de {chamber.title() if chamber.isupper() else chamber}"
                ch = chamber
                pt = "chamber_president"
            else:
                role = f"Vocal de {chamber.title() if chamber.isupper() else chamber}"
                ch = chamber
                pt = "appellate"
            if name and len(name) >= 4:
                rows.append((name, role, ch, pt))
            i += 2
            continue
        i += 1
    return rows

time.sleep(3)
req = urllib.request.Request(URL, headers=UA)
raw = urllib.request.urlopen(req, timeout=90).read()
sha = hashlib.sha256(raw).hexdigest()
lines = lines_of(raw)
parsed = parse(lines)
print("parsed", len(parsed))
for p in parsed:
    print(" ", p)

old_ids = {json.loads(l)["judge_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
seen = set(old_ids)
added = []
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "a") as f:
    for name, title, chamber, pt in parsed:
        base = f"{COURT_ID}-{slug(name)}"
        jid = base
        n = 2
        # if same person already added this run with different chamber, suffix
        if jid in seen:
            jid = f"{base}-{slug(chamber)}"
        while jid in seen:
            jid = f"{base}-{n}"
            n += 1
        if jid in old_ids:
            continue
        seen.add(jid)
        rec = {
            "judge_id": jid,
            "court_id": COURT_ID,
            "name": name,
            "title": title,
            "position_type": pt,
            "chamber": None if chamber == "Presidencia" else chamber,
            "term_start": None,
            "term_end": None,
            "status": "sitting",
            "jurisdiction": "BO-H",
            "roster_url": LIVE,
            "source_url": URL,
            "source_kind": "wayback",
            "site_policy": POL,
            "retrieved_at": NOW,
            "needs_review": True,  # Wayback snapshot; live host 500 — confirm when live recovers
            "extraction": f"Wayback {WB_TS} of official TDJ Chuquisaca Oficinas/ComposicionSalas; live HTTP 500",
            "license": "Órgano Judicial de Bolivia official website (public facts)",
            "source_sha256": sha,
            "language": "es",
        }
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        added.append(rec)

print("added", len(added))
for r in added:
    print(r["judge_id"], "|", r["name"], "|", r["title"])
