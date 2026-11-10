#!/usr/bin/env python3
"""Chile Corte Suprema ministers (Presidente + Ministros only) from official pjud.cl
DOTACIÓN TITULAR. Skips Fiscal Judicial, Abogados Integrantes, Relatores, Secretarios.
Appends new judges only; dedupes against existing short-name rows. Polite 2s."""
import json, re, os, html, hashlib, datetime, time, urllib.request, unicodedata

ROOT = "/workspace/world_courts"
OUT = f"{ROOT}/data/cl/cl_judges.jsonl"
URL = "https://www.pjud.cl/tribunales/corte-suprema"
UA = {"User-Agent": "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"}
POL = "robots_allowed|pjud.cl public tribunales roster; polite 2s; public names/titles only"
COURT_ID = "cl-corte-suprema"
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()

def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")

def tokens(s):
    return [t for t in fold(s).split() if t not in ("dona", "don", "de", "del", "la", "las", "los", "y")]

time.sleep(1)
raw = urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=60).read()
sha = hashlib.sha256(raw).hexdigest()
h = raw.decode("utf-8", "replace")
m = re.search(r"DOTACIÓN\s+TITULAR(.*?)DOTACIÓN\s+REEMPLAZO", h, re.I | re.S)
section = m.group(1) if m else h

# Cut at Fiscal Judicial / Abogado Integrante / Relator / Secretario
cut = len(section)
for kw in (r"Fiscal\s+Judicial", r"Abogado\s+Integrante", r"\bRelator\b", r"\bSecretario\b"):
    mm = re.search(kw, section, re.I)
    if mm:
        cut = min(cut, mm.start())
section = section[:cut]

found = []
for mm in re.finditer(r'(Doña|Don)\s+([^"<]{5,90}?)"\s*,\s*"COSUP"', section):
    name = re.sub(r"\s+", " ", html.unescape(mm.group(2)).strip().rstrip(",").strip())
    if name and name not in found:
        found.append(name)

president = found[0] if found else None
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
old_ids = {o["judge_id"] for o in old}
old_toks = [tokens(o.get("name") or "") for o in old]

def already(name):
    jid = f"{COURT_ID}-{slug(name)}"
    if jid in old_ids:
        return True
    nt = tokens(name)
    for ot in old_toks:
        if len(ot) >= 2 and all(t in nt for t in ot):
            return True
        if len(ot) >= 2 and len(nt) >= 2 and ot[-1] in nt and ot[0] in nt:
            return True
    return False

rows = []
for i, name in enumerate(found):
    if already(name):
        continue
    jid = f"{COURT_ID}-{slug(name)}"
    if any(r["judge_id"] == jid for r in rows):
        continue
    is_pres = (i == 0 and name == president)
    rows.append({
        "judge_id": jid, "court_id": COURT_ID, "name": name,
        "title": "Presidenta (Ministra)" if is_pres else "Ministro/a",
        "position_type": "chief" if is_pres else "justice",
        "term_start": None, "term_end": None, "status": "sitting",
        "jurisdiction": "CL", "roster_url": URL, "source_url": URL,
        "source_kind": "official", "site_policy": POL, "retrieved_at": NOW,
        "needs_review": False,
        "extraction": "official pjud.cl Corte Suprema DOTACIÓN TITULAR (Presidente+Ministros only)",
        "license": "Poder Judicial de Chile official website (public facts)",
        "source_sha256": sha, "language": "es",
    })

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "a") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("found_ministers", len(found), "added", len(rows))
for r in rows:
    print(r["name"], r["title"])
