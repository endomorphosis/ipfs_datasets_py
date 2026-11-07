"""UY: Código General del Proceso (Ley 15.982), IMPO official consolidated text (impo.com.uy/bases; robots allows /bases/codigo-general-proceso, crawl-delay 10; single page)."""
import json, sys, re, datetime, hashlib, html, os
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
P = f"{ROOT}/rules/raw/uy_rules/cgp.html"; OUT = f"{ROOT}/data/uy/uy_rules.jsonl"; SRC = "https://www.impo.com.uy/bases/codigo-general-proceso/15982-1988"
raw = open(P, "rb").read(); sha = hashlib.sha256(raw).hexdigest(); t = raw.decode("latin-1"); now = datetime.datetime.now(datetime.UTC).isoformat()
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set(); rows = []; seen = set()
for m in re.finditer(r'<h4><a href="[^"]*/(\d+(?:-\d+)?)"[^>]*>\s*Art[^<]*?(\d+[^<]*)</a></h4><pre>(.*?)</pre>(.*?)(?=<h4>|$)', t, re.S):
    num = m.group(2).strip(); body = html.unescape(re.sub(r"<[^>]+>", "", m.group(3))); notes = html.unescape(re.sub(r"<[^>]+>", " ", m.group(4)))
    rid = f"uy-cgp-15982:art-{re.sub(r'[^0-9a-z]+', '-', num.lower()).strip('-')}"
    if rid in seen or rid in old: continue
    seen.add(rid); body = re.sub(r"[ \t]+", " ", body).strip(); tm = re.match(r"^([^\n]{2,150}?)\.-\s*\n?(.*)$", body, re.S)
    red = re.search(r"Redacci[óo]n dada por:\s*([^.\n]+)", notes)
    rows.append({"rule_id": rid, "rule_set_id": "uy-cgp-15982", "court_id": None, "jurisdiction": "UY", "rule_set": "Código General del Proceso (Ley N° 15.982 de 18/10/1988), texto actualizado IMPO",
      "rule_number": f"Artículo {num}", "title": tm.group(1).strip() if tm else None, "text": re.sub(r"\s+", " ", tm.group(2) if tm else body).strip(), "effective_date": "1989-11-20",
      "pdf_path": None, "pdf_sha256": None, "source_sha256": sha, "source_url": f"{SRC}/{m.group(1)}", "site_policy": "robots_allowed(crawl-delay 10)", "retrieved_at": now,
      "license": "IMPO (Dirección Nacional de Impresiones y Publicaciones Oficiales); Uruguayan laws not protected (Ley 9.739 art. 44)", "language": "es",
      "record_note": f"Redacción dada por: {red.group(1).strip()}" if red else None})
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(rows), rows[0]["rule_number"], rows[0]["title"], "| last", rows[-1]["rule_number"])
