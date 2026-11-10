"""SV: Corte Suprema de Justicia de El Salvador - 'Magistrados - Corte Suprema de Justicia' page (csj.gob.sv), 15 magistrates by Sala.
csj.gob.sv answers 403 to the box (not bypassed), so the official page is read from its Wayback Machine capture (20250907191639).
Roster as of Sept 2025 -> needs_review. Public names/titles only. Usage: sv_csj_magistrados_wb.py [--dry]"""
import json, re, sys, time, hashlib, html, datetime, os, unicodedata, gzip, subprocess, tempfile, requests
UA = "WorldCourtsResearchBot/1.0 (+https://huggingface.co/datasets/endomorphosis/world_courts; polite research crawl)"
TS = "20250907191639"; SRC = "https://www.csj.gob.sv/magistrados-corte-suprema-de-justicia/"; WB = f"https://web.archive.org/web/{TS}id_/{SRC}"
OUT = "/workspace/world_courts/data/sv/sv_judges.jsonl"; COURT = "sv-supreme-court"
SALAS = ["SALA DE LO CONSTITUCIONAL", "SALA DE LO CIVIL", "SALA DE LO PENAL", "SALA DE LO CONTENCIOSO ADMINISTRATIVO"]
def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower(); return re.sub(r"[^a-z0-9]+", "-", s).strip("-")
def fetch():
    for k in range(4):
        try:
            r = requests.get(WB, headers={"User-Agent": UA}, timeout=120)
            if r.status_code == 200: return r.content
        except requests.exceptions.SSLError:
            with tempfile.NamedTemporaryFile() as f:
                subprocess.run(["curl", "-s", "--compressed", "-m", "120", "-A", UA, "-o", f.name, WB]); c = open(f.name, "rb").read()
                if c: return c
        time.sleep(15 * (k + 1))
    raise SystemExit("wayback fetch failed")
def main():
    dry = "--dry" in sys.argv; now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    b = fetch()
    if b[:2] == b"\x1f\x8b": b = gzip.decompress(b)
    sha = hashlib.sha256(b).hexdigest(); t = b.decode("utf-8", "replace")
    t = re.sub(r"<(script|style).*?</\1>", "", t, flags=re.S)
    toks = [x.strip() for x in html.unescape(re.sub(r"<[^>]+>", "\n", t)).split("\n") if x.strip()]
    rows, sala = [], None
    for i, x in enumerate(toks):
        if x in SALAS: sala = x.title().replace(" De Lo ", " de lo "); continue
        if x.startswith(("SALA ", "Compartir")) and sala: 
            if x.startswith("Compartir"): break
        if sala and i + 1 < len(toks) and toks[i + 1] in ("Magistrado Presidente", "Magistrada Presidenta", "Vocal") and re.match(r"^(Lic|Licda|Dr|Dra|Ing)\.\s", x):
            name = re.sub(r"^(Lic|Licda|Dr|Dra|Ing)\.\s+", "", x); role = toks[i + 1]
            pres = role != "Vocal"
            title = f"{role}, {sala}" + (" (Presidente de la Corte Suprema de Justicia y del Órgano Judicial)" if pres and "Constitucional" in sala else "")
            rows.append({"judge_id": f"{COURT}-{slug(name)}", "court_id": COURT, "name": name, "title": title, "honorific": x.split()[0],
                "position_type": "chief" if pres and "Constitucional" in sala else ("presiding" if pres else "judge"), "term_start": None, "term_end": None,
                "status": "sitting", "jurisdiction": "SV", "roster_url": SRC, "source_url": SRC, "source_kind": "official",
                "site_policy": f"archived_copy(wayback:{TS[:8]});origin_403|csj.gob.sv: Corte Suprema de Justicia, todos los derechos reservados",
                "retrieved_at": now, "needs_review": True, "extraction": f"official CSJ magistrates page, Wayback capture {TS[:8]} (roster as of Sept 2025)",
                "license": "Corte Suprema de Justicia de El Salvador official website (facts)", "source_sha256": sha, "language": "es"})
    have = set()
    if os.path.exists(OUT):
        for l in open(OUT):
            if l.strip(): r = json.loads(l); have.add(r["judge_id"]); have.add(slug(r["name"]))
    new = [r for r in rows if r["judge_id"] not in have and slug(r["name"]) not in have]
    print("parsed", len(rows), "new", len(new))
    if not dry and new:
        with open(OUT, "a") as f:
            for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
main()
