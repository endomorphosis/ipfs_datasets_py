"""VE: Tribunal Supremo de Justicia 'Magistradas y Magistrados' page (tsj.gob.ve/magistrados): principal magistrates of all six Salas.
Public names + Sala only. Dedupes on name slug against existing rows (Sala Constitucional + president were already present).
Usage: ve_tsj_magistrados.py [--dry]"""
import json, re, sys, time, hashlib, html, datetime, os, unicodedata, requests
UA = "WorldCourtsResearchBot/1.0 (+https://huggingface.co/datasets/endomorphosis/world_courts; polite research crawl)"
SRC = "https://www.tsj.gob.ve/magistrados"; OUT = "/workspace/world_courts/data/ve/ve_judges.jsonl"; COURT = "ve-tribunal-supremo-de-justicia"
def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower(); return re.sub(r"[^a-z0-9]+", "-", s).strip("-")
def main():
    dry = "--dry" in sys.argv; now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in range(4):
        try: r = requests.get(SRC, headers={"User-Agent": UA}, timeout=60); r.raise_for_status(); break
        except Exception as e: print("retry", str(e)[:60]); time.sleep(10 * (k + 1))
    else: raise SystemExit("fetch failed")
    sha = hashlib.sha256(r.content).hexdigest(); t = re.sub(r"<(script|style).*?</\1>", "", r.text, flags=re.S)
    toks = [x.strip() for x in html.unescape(re.sub(r"<[^>]+>", "\n", t)).split("\n") if x.strip()]
    rows, sala = [], None
    for x in toks:
        m = re.match(r"^Magistrados\(as\) de la (Sala .+)$", x)
        if m: sala = m.group(1); continue
        if x.startswith("Salas del Tribunal"): break
        if sala and re.match(r"^[A-ZÁÉÍÓÚÑ][\w'ÁÉÍÓÚÑáéíóúñ]+( [\w'ÁÉÍÓÚÑáéíóúñ]+){1,5}$", x):
            rows.append({"judge_id": f"{COURT}-{slug(x)}", "court_id": COURT, "name": x, "title": f"Magistrado/a de la {sala}", "position_type": "judge",
                "term_start": None, "term_end": None, "status": "sitting", "jurisdiction": "VE", "roster_url": SRC, "source_url": SRC, "source_kind": "official",
                "site_policy": "robots_allowed(only one decision URL disallowed)|tsj.gob.ve: official TSJ portal, no licence stated", "retrieved_at": now,
                "needs_review": False, "extraction": "official TSJ 'Magistradas y Magistrados' page, list by Sala", "license": "official public information; no licence stated",
                "source_sha256": sha, "language": "es"})
    have = set()
    if os.path.exists(OUT):
        for l in open(OUT):
            if l.strip(): have.add(slug(json.loads(l)["name"]))
    new = [x for x in rows if slug(x["name"]) not in have]
    print("parsed", len(rows), "new", len(new))
    if not dry and new:
        with open(OUT, "a") as f:
            for x in new: f.write(json.dumps(x, ensure_ascii=False) + "\n")
main()
