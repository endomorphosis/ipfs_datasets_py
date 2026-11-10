#!/usr/bin/env python3
"""Bolivia Tribunal Agroambiental authorities from official
https://www.tribunalagroambiental.bo/autoridades-tribunal-agroambiental/
Public names/titles only. Site SSL chain incomplete (local issuer) — verify
disabled for fetch only (not a WAF/CF bypass). robots.txt allows all.
Also ensures court body row bo-tribunal-agroambiental exists.
Polite ~3s. Appends; dedupe by judge_id / court_id.
"""
import json, re, os, html, hashlib, datetime, time, ssl, urllib.request, unicodedata

ROOT = "/workspace/world_courts"
OUT_J = f"{ROOT}/data/bo/bo_judges.jsonl"
OUT_C = f"{ROOT}/data/bo/bo_courthouses.jsonl"
URL = "https://www.tribunalagroambiental.bo/autoridades-tribunal-agroambiental/"
COURT_ID = "bo-tribunal-agroambiental"
HOME = "https://www.tribunalagroambiental.bo/"
UA = {"User-Agent": "WorldCourtsResearchBot/1.0 (+public court directory research; polite crawl)"}
POL = "robots_allowed|tribunalagroambiental.bo Yoast allow-all; public authorities roster; polite 3s; SSL verify off (incomplete chain)"
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()
CTX = ssl._create_unverified_context()

def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")

def clean_name(n):
    n = re.sub(r"^(?:Dr\.|Dra\.|M\.?Sc\.|MSc\.|Lic\.)\s*", "", n or "", flags=re.I)
    return re.sub(r"\s+", " ", n).strip(" -")

def lines_of(raw):
    h = raw.decode("utf-8", "replace")
    t = re.sub(r"<script[^>]*>.*?</script>", "", h, flags=re.S | re.I)
    t = re.sub(r"<style[^>]*>.*?</style>", "", t, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    return [re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip()]

NAME_RE = re.compile(r"^(?:Dr\.|Dra\.)\s+(.+)$", re.I)

def parse(lines):
    """Walk text lines: optional Sala header, then Dr./Dra. name, then role lines
    (PRESIDENTE / MAGISTRADA / MAGISTRADO / DECANO / PRESIDENTE DE SALA) until next name/sala.
    """
    rows = []
    sala = None
    i = 0
    while i < len(lines):
        l = lines[i]
        if re.match(r"^Sala Especializada\b", l, re.I):
            sala = l.strip()
            i += 1
            continue
        m = NAME_RE.match(l)
        if not m:
            i += 1
            continue
        name = clean_name(m.group(1))
        roles = []
        j = i + 1
        while j < len(lines):
            if NAME_RE.match(lines[j]) or re.match(r"^Sala Especializada\b", lines[j], re.I):
                break
            if re.match(r"^(PRESIDENTE|PRESIDENTA|MAGISTRAD[OA]|DECAN[OA]|PRESIDENTE DE SALA|PRESIDENTA DE SALA)\b", lines[j], re.I):
                roles.append(lines[j].strip())
            # skip repeated "TRIBUNAL AGROAMBIENTAL" labels
            j += 1
        # Build title from roles
        role_u = " ".join(roles).upper()
        if "DECAN" in role_u and "PRESIDENTE DE SALA" not in role_u and role_u.strip() == "DECANO" or role_u.strip() == "DECANA":
            title = f"Decano del Tribunal Agroambiental"
            if sala:
                title = f"Decano — {sala}"
            pt = "associate"
        elif "PRESIDENTE DE SALA" in role_u or "PRESIDENTA DE SALA" in role_u:
            title = f"Magistrada Presidenta de {sala}" if "MAGISTRADA" in role_u else f"Magistrado Presidente de {sala}"
            if "MAGISTRADA" in role_u:
                title = f"Magistrada Presidenta de {sala}" if sala else "Magistrada Presidenta de Sala"
            else:
                title = f"Magistrado Presidente de {sala}" if sala else "Magistrado Presidente de Sala"
            pt = "chamber_president"
        elif re.search(r"\bPRESIDENTE\b|\bPRESIDENTA\b", role_u) and "SALA" not in role_u:
            title = "Presidenta del Tribunal Agroambiental" if "PRESIDENTA" in role_u or name else "Presidente del Tribunal Agroambiental"
            # gender from Dra./Dr. already stripped; use MAGISTRADA absence + original: Roxana is PRESIDENTE label on site
            if any(r.upper().startswith("PRESIDENTA") for r in roles):
                title = "Presidenta del Tribunal Agroambiental"
            else:
                # site uses PRESIDENTE even for Dra.
                title = "Presidente del Tribunal Agroambiental"
            pt = "chief_judge"
            sala_out = None
        else:
            # MAGISTRADO/MAGISTRADA alone
            fem = any(r.upper().startswith("MAGISTRADA") for r in roles)
            base = "Magistrada" if fem else "Magistrado"
            title = f"{base} del Tribunal Agroambiental" + (f" — {sala}" if sala else "")
            pt = "associate"
        sala_out = sala if "Presidente del Tribunal" not in title and "Presidenta del Tribunal" not in title else None
        # For court president, chamber None; for others keep sala if set before this person
        if pt == "chief_judge":
            sala_out = None
        rows.append((name, title, sala_out, pt, False))
        i = j
    return rows

def fetch(url):
    time.sleep(3)
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=60, context=CTX).read()

def ensure_court(sha_home=None):
    old_ids = set()
    if os.path.exists(OUT_C):
        for l in open(OUT_C):
            try:
                old_ids.add(json.loads(l).get("court_id"))
            except Exception:
                pass
    if COURT_ID in old_ids:
        print("court exists", COURT_ID)
        return 0
    rec = {
        "court_id": COURT_ID,
        "record_type": "courthouse",
        "name": "Tribunal Agroambiental",
        "name_local": "Tribunal Agroambiental",
        "level": "national_specialized",
        "court_system": "national",
        "country_code": "BO",
        "subdivision": "BO",
        "jurisdiction": "Bolivia — jurisdicción agroambiental",
        "parent_court_id": "bo-supreme-court",
        "address": {"street": None, "city": "Sucre", "postcode": None, "region": "Chuquisaca", "country": "BO"},
        "geo": {"lat": None, "lon": None},
        "phone": None,
        "website": HOME,
        "wikidata": None,
        "place_ids": [],
        "source_url": HOME,
        "source_kind": "official",
        "site_policy": POL,
        "retrieved_at": NOW,
        "needs_review": False,
        "extraction": "official tribunalagroambiental.bo homepage card + autoridades page",
        "license": "Tribunal Agroambiental official website (public facts)",
        "language": "es",
    }
    with open(OUT_C, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("court +", COURT_ID)
    return 1

def main():
    added_c = ensure_court()
    raw = fetch(URL)
    sha = hashlib.sha256(raw).hexdigest()
    parsed = parse(lines_of(raw))
    print("parsed", len(parsed))
    for p in parsed:
        print(" ", p)

    old = [json.loads(l) for l in open(OUT_J)] if os.path.exists(OUT_J) else []
    old_ids = {r["judge_id"] for r in old}
    old_names = {fold(r.get("name", "")) for r in old}
    added = []
    seen = set()
    for name, title, sala, pt, nr in parsed:
        if not name or len(name) < 4:
            continue
        if fold(name) in old_names:
            print("skip existing", name)
            continue
        base = f"{COURT_ID}-{slug(name)}"
        jid = base
        n = 2
        while jid in seen or jid in old_ids:
            jid = f"{base}-{n}"
            n += 1
        seen.add(jid)
        rec = {
            "judge_id": jid,
            "court_id": COURT_ID,
            "name": name,
            "title": title,
            "position_type": pt,
            "chamber": sala,
            "term_start": None,
            "term_end": None,
            "status": "sitting",
            "jurisdiction": "BO",
            "roster_url": URL,
            "source_url": URL,
            "source_kind": "official",
            "site_policy": POL,
            "retrieved_at": NOW,
            "needs_review": bool(nr),
            "extraction": "official tribunalagroambiental.bo Autoridades page (names/titles only)",
            "license": "Tribunal Agroambiental official website (public facts)",
            "source_sha256": sha,
            "language": "es",
        }
        added.append(rec)
        old_ids.add(jid)
        old_names.add(fold(name))
        print("+", name, "|", title, "|", sala, "|", pt)

    with open(OUT_J, "a") as f:
        for r in added:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("COURTS_ADDED", added_c)
    print("JUDGES_ADDED", len(added))

if __name__ == "__main__":
    main()
