"""Direct official court-form PDFs (EC Consejo de la Judicatura; UY Ventanilla Judicial). Append-per-row, sha dedup."""
import json, sys, datetime, hashlib, os, time, requests
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
now = datetime.datetime.now(datetime.UTC).isoformat(); H = {"User-Agent": "world-courts-research/0.3"}
EC = "https://www.funcionjudicial.gob.ec/resources/pdf/"
ITEMS = [
 ("ec", EC + "consejo/formulariodemanda_de_pension.pdf", "Formulario único para demanda de pensión alimenticia", "Res. 052-2020 CJ", "robots_none(404);official:Consejo de la Judicatura", "Ecuadorian official texts are not protected (COESCCI art. 132)"),
 ("ec", EC + "consejo/formularioaumento_pension.pdf", "Formulario único para demanda de aumento de pensión alimenticia", "Res. 052-2020 CJ", "robots_none(404);official:Consejo de la Judicatura", "Ecuadorian official texts are not protected (COESCCI art. 132)"),
 ("ec", EC + "consejo/formulariodisminucion_pension.pdf", "Formulario único para demanda de disminución de pensión alimenticia", "Res. 052-2020 CJ", "robots_none(404);official:Consejo de la Judicatura", "Ecuadorian official texts are not protected (COESCCI art. 132)"),
 ("ec", EC + "Formulario%20%C3%BAnico%20para%20la%20demanda%20de%20declaratoria%20de%20paternidad%20y%20fijaci%C3%B3n%20de%20pensi%C3%B3n%20alimenticia.pdf", "Formulario único para la demanda de declaratoria de paternidad y fijación de pensión alimenticia", None, "robots_none(404);official:Consejo de la Judicatura", "Ecuadorian official texts are not protected (COESCCI art. 132)"),
] + [("uy", "https://ventanilla.poderjudicial.gub.uy/" + p, t, None, "robots_allowed;official:Poder Judicial Ventanilla Judicial", "Uruguayan official texts are not protected (Ley 9.739 art. 44)") for p, t in json.loads(sys.argv[1])]
for cc, u, title, num, pol, lic in ITEMS:
    OUT = f"{ROOT}/data/{cc}/{cc}_forms.jsonl"; FD = f"{ROOT}/forms/{cc}"; os.makedirs(FD, exist_ok=True)
    old = {json.loads(l)["pdf_sha256"] for l in open(OUT)} if os.path.exists(OUT) else set()
    try: r = requests.get(u, headers=H, timeout=90)
    except Exception as e: print("fail", u, type(e).__name__); continue
    time.sleep(3)
    if r.status_code != 200 or r.content[:4] != b"%PDF": print("fail", u, r.status_code); continue
    sha = hashlib.sha256(r.content).hexdigest()
    if sha in old: print("dup", title); continue
    open(f"{FD}/{sha}.pdf", "wb").write(r.content)
    row = {"form_id": f"{cc}-{sha[:16]}", "court_id": None, "jurisdiction": cc.upper(), "form_number": num, "title": title, "category": "official-court-forms", "language": "es",
      "file_format": "pdf", "pdf_path": f"forms/{cc}/{sha}.pdf", "pdf_sha256": sha, "file_bytes": len(r.content), "source_url": u, "index_url": None, "license": lic, "site_policy": pol, "retrieved_at": now}
    open(OUT, "a").write(json.dumps(row, ensure_ascii=False) + "\n"); print("added", cc, title)
