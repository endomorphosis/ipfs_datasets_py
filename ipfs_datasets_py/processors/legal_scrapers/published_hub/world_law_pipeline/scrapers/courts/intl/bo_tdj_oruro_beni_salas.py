#!/usr/bin/env python3
"""Bolivia TDJ Oruro + Beni chamber composition from official
/Paper/ConformacionSala pages. Public names/titles only. Polite 2s.
Appends new judges; dedupe by judge_id."""
import json, re, os, html, hashlib, datetime, time, urllib.request, unicodedata

ROOT = "/workspace/world_courts"
OUT = f"{ROOT}/data/bo/bo_judges.jsonl"
UA = {"User-Agent": "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"}
POL = "robots_ignored_per_user_authorization|organojudicial.gob.bo TDJ official; public chamber roster; polite 2s"
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()

SITES = [
    {
        "court_id": "bo-tdj-oruro",
        "url": "https://oruro.organojudicial.gob.bo/Paper/ConformacionSala",
        "jurisdiction": "BO-O",
        "style": "oruro",  # "Dr. A-Dr. B" with Vocal-Presidente labels
    },
    {
        "court_id": "bo-tdj-beni",
        "url": "https://beni.organojudicial.gob.bo/Paper/ConformacionSala",
        "jurisdiction": "BO-B",
        "style": "beni",  # Dr. Name / PRESIDENTE|VOCAL alternating
    },
]

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

NAME_ONE = re.compile(
    r"^(?:Dr\.|Dra\.|M\.?Sc\.|MSc\.|Lic\.)\s*(.+)$", re.I
)

def clean_name(n):
    n = re.sub(r"\s+", " ", n).strip()
    n = re.sub(r"\s*\((?:Presidente|Vocal)\)\s*$", "", n, flags=re.I)
    return n.strip(" -")

def parse_oruro(lines, court_id):
    rows = []
    # Find sala blocks: line starting with SALA / Sala
    i = 0
    while i < len(lines):
        l = lines[i]
        if re.match(r"^SALA\b|^Sala\b", l) and "encargada" not in l.lower():
            sala = l.strip()
            # look ahead for name line and role line
            names_line = roles_line = None
            for j in range(i + 1, min(i + 8, len(lines))):
                if re.match(r"^SALA\b|^Sala\b", lines[j]) and "encargada" not in lines[j].lower() and j > i:
                    break
                if re.search(r"Dr\.|Dra\.", lines[j]) and "encargada" not in lines[j].lower():
                    names_line = lines[j]
                if re.search(r"Vocal|Presidente", lines[j], re.I) and not re.search(r"Dr\.|Dra\.", lines[j]):
                    roles_line = lines[j]
                # combined: Dr. A (Presidente)- Dr. B (Vocal)
                if names_line and "(" in names_line and re.search(r"Presidente|Vocal", names_line, re.I):
                    parts = re.split(r"\s*-\s*", names_line)
                    for p in parts:
                        rm = re.search(r"\((Presidente|Vocal)\)", p, re.I)
                        nm = re.sub(r"\((?:Presidente|Vocal)\)", "", p, flags=re.I)
                        nm = re.sub(r"^(?:Dr\.|Dra\.)\s*", "", nm.strip(), flags=re.I)
                        nm = clean_name(nm)
                        if nm and rm:
                            role = rm.group(1).title()
                            rows.append((nm, f"{role} de {sala}", sala))
                    names_line = None
                    roles_line = None
                    break
            if names_line and roles_line:
                # Split names on - ; roles on -
                nparts = re.split(r"\s*-\s*", names_line)
                rparts = re.split(r"\s*-\s*", roles_line)
                nparts = [clean_name(re.sub(r"^(?:Dr\.|Dra\.)\s*", "", p, flags=re.I)) for p in nparts]
                rparts = [p.strip().title() for p in rparts]
                # Oruro often lists Vocal-Presidente meaning first is Vocal, second Presidente
                for ni, name in enumerate(nparts):
                    if not name:
                        continue
                    role = rparts[ni] if ni < len(rparts) else ("Presidente" if ni == 0 else "Vocal")
                    # normalize
                    if "presid" in role.lower():
                        role = "Presidente"
                    elif "vocal" in role.lower():
                        role = "Vocal"
                    rows.append((name, f"{role} de {sala}", sala))
            elif names_line and not roles_line:
                # single name with role on same or next
                m = NAME_ONE.match(names_line)
                if m:
                    name = clean_name(m.group(1))
                    role = "Presidente"
                    rows.append((name, f"{role} de {sala}", sala))
        i += 1
    return rows

def parse_beni(lines, court_id):
    rows = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if re.match(r"^SALA\b", l, re.I) and "encargada" not in l.lower():
            sala = l.strip()
            # subsequent Dr. / PRESIDENTE|VOCAL pairs until next SALA
            j = i + 1
            pending_name = None
            while j < len(lines):
                if re.match(r"^SALA\b", lines[j], re.I) and "encargada" not in lines[j].lower():
                    break
                if re.match(r"^Tribunal Departamental", lines[j], re.I):
                    break
                m = NAME_ONE.match(lines[j])
                if m:
                    pending_name = clean_name(m.group(1))
                    j += 1
                    continue
                if pending_name and re.match(r"^(PRESIDENTE|VOCAL)$", lines[j], re.I):
                    role = lines[j].title()
                    if role.upper() == "PRESIDENTE":
                        role = "Presidente"
                    else:
                        role = "Vocal"
                    rows.append((pending_name, f"{role} de {sala}", sala))
                    pending_name = None
                j += 1
            # if name without role at end of sala (some Beni entries)
            if pending_name:
                rows.append((pending_name, f"Integrante de {sala}", sala))
        i += 1
    return rows

old_ids = {json.loads(l)["judge_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
added = []
for site in SITES:
    time.sleep(2)
    raw = urllib.request.urlopen(urllib.request.Request(site["url"], headers=UA), timeout=60).read()
    sha = hashlib.sha256(raw).hexdigest()
    lines = lines_of(raw)
    if site["style"] == "oruro":
        parsed = parse_oruro(lines, site["court_id"])
    else:
        parsed = parse_beni(lines, site["court_id"])
    print(site["court_id"], "parsed", len(parsed))
    seen = set()
    for name, title, sala in parsed:
        if not name or len(name) < 4:
            continue
        base = f"{site['court_id']}-{slug(name)}"
        jid = base if base not in seen else f"{base}-{slug(sala)}"
        n = 2
        while jid in seen:
            jid = f"{base}-{n}"; n += 1
        seen.add(jid)
        if jid in old_ids:
            continue
        pt = "chamber_president" if title.lower().startswith("presidente") else "appellate"
        rec = {
            "judge_id": jid, "court_id": site["court_id"], "name": name, "title": title,
            "position_type": pt, "chamber": sala, "term_start": None, "term_end": None,
            "status": "sitting", "jurisdiction": site["jurisdiction"],
            "roster_url": site["url"], "source_url": site["url"],
            "source_kind": "official", "site_policy": POL, "retrieved_at": NOW,
            "needs_review": True,  # Oruro name strings sometimes messy
            "extraction": f"official TDJ {site['court_id']} Paper/ConformacionSala",
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
    print(r["court_id"], "|", r["name"], "|", r["title"])
