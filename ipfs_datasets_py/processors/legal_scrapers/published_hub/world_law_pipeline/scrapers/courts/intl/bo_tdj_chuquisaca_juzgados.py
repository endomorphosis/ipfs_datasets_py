#!/usr/bin/env python3
"""Bolivia TDJ Chuquisaca capital trial-court roster from Wayback snapshot of
official Oficinas/ComposicionJuzgados (live host HTTP 500).
Source: http://tdjch.organojudicial.gob.bo/Oficinas/ComposicionJuzgados?tipo=1
Snapshot: 20260308011130. Public names/titles only. Appends; dedupe by judge_id.
"""
import json, re, os, html, hashlib, datetime, time, urllib.request, unicodedata

ROOT = "/workspace/world_courts"
OUT = f"{ROOT}/data/bo/bo_judges.jsonl"
COURT_ID = "bo-tdj-chuquisaca"
LIVE = "http://tdjch.organojudicial.gob.bo/Oficinas/ComposicionJuzgados?tipo=1"
WB_TS = "20260308011130"
URL = f"https://web.archive.org/web/{WB_TS}/{LIVE}"
UA = {"User-Agent": "WorldCourtsResearchBot/1.0 (+public court directory research; polite crawl)"}
POL = "robots_ignored_per_user_authorization|tdjch.organojudicial.gob.bo official TDJ Chuquisaca; live 500; Wayback ComposicionJuzgados Capital; polite 3s"
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

NAME_RE = re.compile(r"^(?:Dr\.|Dra\.|M\.?Sc\.|Msc\.|Abg\.|Lic\.)\s*(.+)$", re.I)
NUM_RE = re.compile(r"^(?:JUZGADO|TRIBUNAL)\s+(\d+|1º|2º|3º|4º|5º|6º|7º|8º|9º|10º|11º|12º|13º|14º)\b", re.I)
CAT_RE = re.compile(r"^(?:JUZGADO|TRIBUNAL)\b", re.I)

def clean_name(n):
    return re.sub(r"\s+", " ", n or "").strip(" -")

def parse(lines):
    try:
        i0 = next(i for i, l in enumerate(lines) if "CONFORMACIÓN DE JUZGADOS" in l.upper() or "CONFORMACION DE JUZGADOS" in l.upper())
    except StopIteration:
        i0 = 0
    rows = []
    category = None
    unit = None
    i = i0 + 1
    while i < len(lines):
        l = lines[i]
        if l.upper().startswith("INFORMACIÓN") or l.upper().startswith("INFORMACION"):
            break
        # Numbered unit under a category
        if NUM_RE.match(l):
            unit = l.strip()
            i += 1
            continue
        # Category header (not a numbered unit): long JUZGADO DE ... / TRIBUNAL DE ...
        if CAT_RE.match(l) and not NUM_RE.match(l) and len(l) > 12:
            category = l.strip()
            unit = None
            i += 1
            continue
        m = NAME_RE.match(l)
        if m:
            name = clean_name(m.group(1))
            if name and len(name) >= 4:
                if category and unit:
                    chamber = f"{category} {unit}"
                elif category:
                    chamber = category
                elif unit:
                    chamber = unit
                else:
                    chamber = "Juzgado Capital"
                title = f"Juez de {chamber.title() if chamber.isupper() else chamber}"
                rows.append((name, title, chamber))
            i += 1
            continue
        i += 1
    return rows

time.sleep(3)
raw = urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=90).read()
sha = hashlib.sha256(raw).hexdigest()
parsed = parse(lines_of(raw))
print("parsed", len(parsed))
for p in parsed:
    print(" ", p[0], "|", p[2][:70])

old_ids = {json.loads(l)["judge_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
seen = set(old_ids)
added = []
with open(OUT, "a") as f:
    for name, title, chamber in parsed:
        base = f"{COURT_ID}-{slug(name)}"
        jid = base
        n = 2
        if jid in seen:
            jid = f"{base}-{slug(chamber)[:40]}"
        while jid in seen:
            jid = f"{base}-{n}"; n += 1
        if jid in old_ids:
            continue
        seen.add(jid)
        rec = {
            "judge_id": jid, "court_id": COURT_ID, "name": name, "title": title,
            "position_type": "trial", "chamber": chamber,
            "term_start": None, "term_end": None, "status": "sitting",
            "jurisdiction": "BO-H", "roster_url": LIVE, "source_url": URL,
            "source_kind": "wayback", "site_policy": POL, "retrieved_at": NOW,
            "needs_review": True,
            "extraction": f"Wayback {WB_TS} of official TDJ Chuquisaca Oficinas/ComposicionJuzgados Capital; live HTTP 500",
            "license": "Órgano Judicial de Bolivia official website (public facts)",
            "source_sha256": sha, "language": "es",
        }
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        added.append(rec)
print("added", len(added))
