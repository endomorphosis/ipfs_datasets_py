"""Colombia: Consejo de Estado magistrados (consejeros de Estado) - public names + official roles only - from the official
section pages of www.consejodeestado.gov.co (Secciones Primera-Quinta, Sala de Consulta y Servicio Civil). Secretaría/staff and
phone numbers skipped. robots.txt returns 404 (no policy). Polite 2s delay. Appends to data/co/co_judges.jsonl (dedupe by judge_id).
Sala de Consulta page lists 5 names for 4 seats (two marked president) -> those rows needs_review."""
import json, re, os, html, hashlib, datetime, time, urllib.request, unicodedata
ROOT = "/workspace/world_courts"; OUT = f"{ROOT}/data/co/co_judges.jsonl"
UA = {"User-Agent": "Mozilla/5.0 world-courts-research (public court data)"}
B = "https://www.consejodeestado.gov.co/"
SECS = {"seccion-primera": "Sección Primera", "seccion-segunda": "Sección Segunda", "seccion-tercea": "Sección Tercera",
        "seccion-cuarta": "Sección Cuarta", "seccion-quinta": "Sección Quinta", "sala-de-consulta-y-servicio-civil": "Sala de Consulta y Servicio Civil"}
def slug(s): return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip("-")
now = datetime.datetime.now(datetime.UTC).isoformat()
old = {json.loads(l)["judge_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
rows = []
for s, sec in SECS.items():
    time.sleep(2); url = f"{B}{s}/index.htm"
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
    t = re.sub(r"<(script|style).*?</\1>", "", raw.decode("utf-8", "replace"), flags=re.S)
    L = [l.strip() for l in html.unescape(re.sub(r"<[^>]+>", "\n", t)).splitlines() if l.strip()]
    i = [k for k, l in enumerate(L) if l == "Directorio"][-1]
    i = next(k for k in range(i, len(L)) if L[k] == "Magistrados")
    j = next(k for k in range(i, len(L)) if L[k].startswith("Exconsejeros") or L[k] in ("Secretaría", "-->"))
    people = []
    for l in [unicodedata.normalize("NFC", " ".join(x.split())) for x in L[i + 1:j]]:
        if l.startswith("Presidente"):
            if people: people[-1][1].append(l)
        elif re.fullmatch(r"[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñü.' -]+", l) and 2 <= len(l.split()) <= 6: people.append([l, []])
    sc = s == "sala-de-consulta-y-servicio-civil"
    for name, notes in people:
        name = re.sub(r"\bDel\b", "del", name)
        jid = f"co-consejo-de-estado-{slug(name)}"
        if jid in old or any(r["judge_id"] == jid for r in rows): continue
        title = f"Consejero(a) de Estado – {sec}" + (f" ({'; '.join(notes)})" if notes else "")
        pt = "chief" if any("del Consejo de Estado" in n for n in notes) else "presiding" if notes else "judge"
        rows.append({"judge_id": jid, "court_id": "co-consejo-de-estado", "name": name, "title": title, "position_type": pt,
            "term_start": None, "term_end": None, "status": "sitting", "jurisdiction": "CO", "chamber": sec, "roster_url": url, "source_url": url,
            "source_kind": "official", "site_policy": "no_robots_txt (robots.txt 404)", "retrieved_at": now, "needs_review": sc,
            "extraction": f"official Consejo de Estado '{sec}' page, Magistrados list", "language": "es",
            "license": "Consejo de Estado public website; Colombian official works (Ley 23/1982 art. 41)",
            "source_sha256": hashlib.sha256(raw).hexdigest()})
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(rows)); [print(r["name"], "|", r["title"], r["position_type"]) for r in rows]
