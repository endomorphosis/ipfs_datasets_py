#!/usr/bin/env python3
"""Bolivia TDJ Santa Cruz + Cochabamba + Tarija chamber/authority rosters
from official organojudicial subdomains. Public names/titles only.
Polite ~3s. Appends; dedupe by judge_id. Skip TSJ magistrates listed on
departmental pages when already present under bo-supreme-court.
"""
import json, re, os, html, hashlib, datetime, time, urllib.request, unicodedata

ROOT = "/workspace/world_courts"
OUT = f"{ROOT}/data/bo/bo_judges.jsonl"
UA = {"User-Agent": "WorldCourtsResearchBot/1.0 (+public court directory research; polite 5s crawl)"}
POL = "robots_ignored_per_user_authorization|organojudicial.gob.bo TDJ official; public chamber roster; polite 5s"
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()

SITES = [
    {
        "court_id": "bo-tdj-santa-cruz",
        "url": "https://tdjscz.organojudicial.gob.bo/Paper/ConformacionSala",
        "jurisdiction": "BO-S",
        "style": "scz",
    },
    {
        "court_id": "bo-tdj-cochabamba",
        "url": "https://tdjcbba.organojudicial.gob.bo/Paper/ConformacionSala",
        "jurisdiction": "BO-C",
        "style": "cbba",
    },
    {
        "court_id": "bo-tdj-tarija",
        "url": "https://tarija-tdj.organojudicial.gob.bo/Paper/ConformacionSala",
        "jurisdiction": "BO-T",
        "style": "tarija",
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

NAME_ONE = re.compile(r"^(?:Dr\.|Dra\.|M\.?Sc\.|MSc\.|Lic\.)\s*(.+)$", re.I)
ROLE_LINE = re.compile(r"^(?:Vocal|Presidente|PRESIDENTE|VOCAL)\b.*$", re.I)

def clean_name(n):
    n = re.sub(r"^(?:Dr\.|Dra\.|M\.?Sc\.|MSc\.|Lic\.)\s*", "", n or "", flags=re.I)
    n = re.sub(r"\s+", " ", n).strip(" -")
    return n

def is_sala_header(l):
    if not re.match(r"^SALA\b", l, re.I):
        return False
    if "encargada" in l.lower():
        return False
    # section headers like "SALAS PENALES" / "SALA CONSTITUCIONAL" alone (parent)
    # Keep specific numbered salas; allow bare SALA X too
    return True

def parse_scz(lines):
    """SCZ: SALA header then one+ Dr./Dra. names; no explicit PRESIDENTE/VOCAL.
    First listed under a specific chamber -> Presidente (imputed); rest Vocal.
    Skip bare section headers that have no names before next SALA (e.g. SALAS PENALES).
    """
    rows = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if is_sala_header(l) and len(l) > 5:
            sala = l.strip()
            # Skip ultra-generic section titles that immediately precede a more specific SALA
            j = i + 1
            names = []
            while j < len(lines):
                if is_sala_header(lines[j]) and len(lines[j]) > 5:
                    break
                if re.match(r"^Tribunal Departamental", lines[j], re.I):
                    break
                if re.match(r"^Consejo de la Magistratura", lines[j], re.I):
                    break
                m = NAME_ONE.match(lines[j])
                if m:
                    names.append(clean_name(m.group(1)))
                j += 1
            # If this header has no names and next is also a SALA, it's a section label — skip
            if not names:
                i += 1
                continue
            for idx, name in enumerate(names):
                if not name or len(name) < 4:
                    continue
                role = "Presidente" if idx == 0 else "Vocal"
                rows.append((name, f"{role} de {sala.title() if sala.isupper() else sala}", sala, True))
            i = j
            continue
        i += 1
    return rows

def parse_cbba(lines):
    """CBBA: SALA header, optional 'Sala encargada...' blurb, then Dr./Dra. + role line pairs."""
    rows = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if is_sala_header(l) and "encargada" not in l.lower() and len(l) > 5:
            sala = l.strip()
            j = i + 1
            pending = None
            while j < len(lines):
                if is_sala_header(lines[j]) and "encargada" not in lines[j].lower() and len(lines[j]) > 5:
                    break
                if re.match(r"^Tribunal Departamental", lines[j], re.I):
                    break
                if re.match(r"^Consejo de la Magistratura", lines[j], re.I):
                    break
                if lines[j].lower().startswith("sala encargada"):
                    j += 1
                    continue
                m = NAME_ONE.match(lines[j])
                if m:
                    if pending:
                        # previous name without role — default Vocal
                        rows.append((pending, f"Vocal de {sala}", sala, True))
                    pending = clean_name(m.group(1))
                    j += 1
                    continue
                if pending and ROLE_LINE.match(lines[j]):
                    rl = lines[j]
                    if re.search(r"presid", rl, re.I):
                        role = "Presidente"
                    else:
                        role = "Vocal"
                    rows.append((pending, f"{role} de {sala}", sala, False))
                    pending = None
                    j += 1
                    continue
                j += 1
            if pending:
                rows.append((pending, f"Vocal de {sala}", sala, True))
            i = j
            continue
        i += 1
    return rows

def parse_tarija_html(raw):
    """Tarija Autoridades page: h4 name then following title paragraph.
    Skip TSJ Decana (already under bo-supreme-court) — return with court_id override None to skip.
    """
    h = raw.decode("utf-8", "replace")
    rows = []
    # Pair each h4 with the next non-empty text node that looks like a title
    parts = re.split(r"<h4>", h, flags=re.I)
    for part in parts[1:]:
        m = re.match(r"(.*?)</h4>(.*)$", part, re.S | re.I)
        if not m:
            continue
        name = clean_name(html.unescape(re.sub(r"<[^>]+>", "", m.group(1))))
        after = html.unescape(re.sub(r"<[^>]+>", "\n", m.group(2)))
        after_lines = [re.sub(r"\s+", " ", x).strip() for x in after.splitlines() if x.strip()]
        title = None
        for al in after_lines[:8]:
            if re.search(r"Presidente|Vocal|Decana|Sala|Tribunal", al, re.I) and len(al) < 200:
                title = al
                break
            # stop if we hit next bio noise without title
            if len(al) > 200:
                break
        if not name or len(name) < 4:
            continue
        # Skip TSJ Decana / supreme listings on this departmental page
        if title and re.search(r"TRIBUNAL SUPREMO|DECANA TRIBUNAL SUPREMO", title, re.I):
            continue
        if not title:
            title = "Vocal del Tribunal Departamental de Justicia de Tarija"
            imputed = True
        else:
            imputed = False
        # Normalize chamber from title if present
        sala = None
        sm = re.search(r"(Sala\s+.+)$", title, re.I)
        if sm:
            sala = sm.group(1).strip()
        rows.append((name, title, sala, imputed))
    return rows

def fetch(url):
    time.sleep(3)
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=60).read()

def main():
    old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
    old_ids = {r["judge_id"] for r in old}
    # also fold-name dedupe within BO to avoid cross-court dupes of same person when slug differs slightly
    old_names = {fold(r.get("name", "")) for r in old}
    added_all = []

    for site in SITES:
        print("===", site["court_id"], site["url"])
        try:
            raw = fetch(site["url"])
        except Exception as e:
            print("FETCH FAIL", e)
            continue
        sha = hashlib.sha256(raw).hexdigest()
        if site["style"] == "scz":
            parsed = parse_scz(lines_of(raw))
        elif site["style"] == "cbba":
            parsed = parse_cbba(lines_of(raw))
        else:
            parsed = parse_tarija_html(raw)
        print("parsed", len(parsed))
        seen = set()
        for name, title, sala, nr in parsed:
            if fold(name) in old_names:
                print("  skip existing name", name)
                continue
            base = f"{site['court_id']}-{slug(name)}"
            jid = base
            n = 2
            while jid in seen or jid in old_ids:
                jid = f"{base}-{n}"
                n += 1
            seen.add(jid)
            tl = (title or "").lower()
            if "presid" in tl and "vocal" not in tl:
                pt = "chamber_president" if "sala" in tl else "chief_judge"
            else:
                pt = "appellate"
            rec = {
                "judge_id": jid,
                "court_id": site["court_id"],
                "name": name,
                "title": title,
                "position_type": pt,
                "chamber": sala,
                "term_start": None,
                "term_end": None,
                "status": "sitting",
                "jurisdiction": site["jurisdiction"],
                "roster_url": site["url"],
                "source_url": site["url"],
                "source_kind": "official",
                "site_policy": POL,
                "retrieved_at": NOW,
                "needs_review": bool(nr) or site["style"] == "scz",
                "extraction": f"official {site['court_id']} ConformacionSala/Autoridades; style={site['style']}",
                "license": "Órgano Judicial de Bolivia official website (public facts)",
                "source_sha256": sha,
                "language": "es",
            }
            added_all.append(rec)
            old_ids.add(jid)
            old_names.add(fold(name))
            print("  +", name, "|", title)

    with open(OUT, "a") as f:
        for r in added_all:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("TOTAL_ADDED", len(added_all))

if __name__ == "__main__":
    main()
