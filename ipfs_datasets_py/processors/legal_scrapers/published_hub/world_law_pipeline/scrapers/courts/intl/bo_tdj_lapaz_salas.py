#!/usr/bin/env python3
"""Bolivia: Tribunal Departamental de Justicia de La Paz — chamber composition
(Presidente TDJ + Sala presidentes/vocales) from official
https://lapaz.organojudicial.gob.bo/Home/ComposicionSalas
Public names/titles only. Polite 2s. Appends new judges; dedupe by judge_id."""
import json, re, os, html, hashlib, datetime, time, urllib.request, unicodedata

ROOT = "/workspace/world_courts"
OUT = f"{ROOT}/data/bo/bo_judges.jsonl"
URL = "https://lapaz.organojudicial.gob.bo/Home/ComposicionSalas"
UA = {"User-Agent": "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"}
POL = "robots_ignored_per_user_authorization|lapaz.organojudicial.gob.bo official TDJ La Paz; public chamber roster; polite 2s"
COURT_ID = "bo-tdj-la-paz"
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()

def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")

time.sleep(2)
raw = urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=60).read()
sha = hashlib.sha256(raw).hexdigest()
h = raw.decode("utf-8", "replace")
t = re.sub(r"<script[^>]*>.*?</script>", "", h, flags=re.S | re.I)
t = re.sub(r"<style[^>]*>.*?</style>", "", t, flags=re.S | re.I)
text = html.unescape(re.sub(r"<[^>]+>", "\n", t))
lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines()]
lines = [l for l in lines if l]

# Find start
try:
    start = next(i for i, l in enumerate(lines) if re.search(r"Conformación\s+Salas|Composición\s+de\s+Salas", l, re.I))
except StopIteration:
    start = 0
try:
    end = next(i for i, l in enumerate(lines) if i > start and re.search(r"Gracias por su visita|Enlaces de Interes", l, re.I))
except StopIteration:
    end = len(lines)
block = lines[start:end]

NAME_RE = re.compile(
    r"^(?:Dr\.|Dra\.|M\.?Sc\.|MSc\.|Lic\.)\s+(.+)$", re.I
)

rows = []
seen = set()
# Presidente TDJ special
for i, l in enumerate(block):
    if re.search(r"Presidente\s+Tribunal\s+Departamental", l, re.I):
        # next name-like line
        for j in range(i + 1, min(i + 5, len(block))):
            m = NAME_RE.match(block[j])
            if m:
                name = m.group(1).strip()
                jid = f"{COURT_ID}-{slug(name)}"
                if jid not in seen:
                    seen.add(jid)
                    rows.append((name, "Presidente del Tribunal Departamental de Justicia de La Paz", "chief", "Tribunal Departamental de Justicia de La Paz"))
                break
        break

# Pattern: Sala NAME / Presidente|Vocal / Dr. Name  (sala line may repeat)
i = 0
while i < len(block):
    l = block[i]
    sm = re.match(r"^(Sala\s+.+)$", l, re.I)
    if sm:
        sala = sm.group(1).strip()
        # look ahead for Presidente/Vocal + name
        role = None
        for j in range(i + 1, min(i + 6, len(block))):
            if re.match(r"^(Presidente|Vocal)$", block[j], re.I):
                role = block[j]
                continue
            if role:
                m = NAME_RE.match(block[j])
                if m:
                    name = m.group(1).strip()
                    title = f"{role} de {sala}"
                    jid = f"{COURT_ID}-{slug(name)}"
                    # same person can appear in multiple salas (e.g. Vargas as TDJ pres + Penal 3 vocal)
                    # use sala in id if duplicate name
                    if jid in seen:
                        jid = f"{COURT_ID}-{slug(name)}-{slug(sala)}"
                    if jid not in seen:
                        seen.add(jid)
                        pt = "chamber_president" if role.lower() == "presidente" else "appellate"
                        rows.append((name, title, pt, sala))
                    role = None
                    # don't break — sala block may list presidente then vocal with sala repeated
            if re.match(r"^Sala\s+", block[j], re.I) and j > i:
                break
        i += 1
        continue
    i += 1

old_ids = set()
if os.path.exists(OUT):
    old_ids = {json.loads(l)["judge_id"] for l in open(OUT)}

added = []
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "a") as f:
    for name, title, pt, chamber in rows:
        jid = f"{COURT_ID}-{slug(name)}"
        # recover the id we used (may include sala suffix)
        # recompute same logic
        pass

# Rebuild with stable ids matching seen logic
seen2 = set()
final = []
# presidente first
for name, title, pt, chamber in rows:
    base = f"{COURT_ID}-{slug(name)}"
    jid = base if base not in seen2 else f"{base}-{slug(chamber)}"
    # if still collision rare
    n = 2
    while jid in seen2:
        jid = f"{base}-{n}"; n += 1
    seen2.add(jid)
    if jid in old_ids:
        continue
    rec = {
        "judge_id": jid, "court_id": COURT_ID, "name": name, "title": title,
        "position_type": pt, "chamber": chamber if chamber != "Tribunal Departamental de Justicia de La Paz" else None,
        "term_start": None, "term_end": None, "status": "sitting",
        "jurisdiction": "BO-L", "roster_url": URL, "source_url": URL,
        "source_kind": "official", "site_policy": POL, "retrieved_at": NOW,
        "needs_review": False,
        "extraction": "official TDJ La Paz Home/ComposicionSalas chamber roster",
        "license": "Órgano Judicial de Bolivia official website (public facts)",
        "source_sha256": sha, "language": "es",
    }
    final.append(rec)

with open(OUT, "a") as f:
    for r in final:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("parsed", len(rows), "added", len(final))
for r in final:
    print(r["judge_id"], "|", r["name"], "|", r["title"])
