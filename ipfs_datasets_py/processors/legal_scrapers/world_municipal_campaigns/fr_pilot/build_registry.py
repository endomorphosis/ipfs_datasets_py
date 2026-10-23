"""France pilot — build the jurisdiction registry from the INSEE COG.

Source (official): INSEE Code Officiel Géographique (COG), millésime 2026
(au 01/01/2026), as listed on data.gouv.fr dataset
"code-officiel-geographique-cog" (publisher: Insee):
  v_commune_2026.csv      — communes, arrondissements municipaux (ARM),
                            communes associées/déléguées (COMA/COMD)
  v_departement_2026.csv  — département names
  v_region_2026.csv       — région names

Only TYPECOM == "COM" rows are communes; ARM rows (Paris/Lyon/Marseille
arrondissements) and COMA/COMD rows (sub-communal) are excluded. Every
code is validated against world_municipal's CodeInseeScheme before it
enters the registry. Output: data/jurisdictions.jsonl.
"""
import csv
import io
import json
import sys
from pathlib import Path

import requests

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.jurisdiction import get_scheme  # noqa: E402

OUT = Path(__file__).resolve().parent.parent
DATA = OUT / "data"
SCRATCH = OUT / "scratch"
BASE = "https://www.insee.fr/fr/statistiques/fichier/8740222"
FILES = {
    "v_commune_2026.csv": f"{BASE}/v_commune_2026.csv",
    "v_departement_2026.csv": f"{BASE}/v_departement_2026.csv",
    "v_region_2026.csv": f"{BASE}/v_region_2026.csv",
}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 world-municipal-law-pilot/0.1"
FR = get_scheme("FR")


def fetch(name):
    path = SCRATCH / name
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()
    r = requests.get(FILES[name], headers={"User-Agent": UA}, timeout=120)
    r.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    return r.content


def read_csv(name):
    raw = fetch(name)
    text = raw.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def main():
    deps = {r["DEP"]: r["LIBELLE"] for r in read_csv("v_departement_2026.csv")}
    regs = {r["REG"]: r["LIBELLE"] for r in read_csv("v_region_2026.csv")}
    rows = read_csv("v_commune_2026.csv")
    kinds = {}
    out = []
    bad = []
    for r in rows:
        kind = (r.get("TYPECOM") or "").strip()
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind != "COM":
            continue
        code_raw = (r.get("COM") or "").strip()
        try:
            code = FR.normalize(code_raw)
        except ValueError:
            bad.append(code_raw)
            continue
        dep = (r.get("DEP") or "").strip()
        reg = (r.get("REG") or "").strip()
        out.append({
            "jurisdiction_id": code,
            "jurisdiction_name": (r.get("LIBELLE") or "").strip(),
            "country": "FR",
            "scheme": "INSEE COG commune",
            "departement_code": dep,
            "departement_name": deps.get(dep, ""),
            "region_code": reg,
            "region_name": regs.get(reg, ""),
            "kind": "commune",
        })
    out.sort(key=lambda j: j["jurisdiction_id"])
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "jurisdictions.jsonl").open("w", encoding="utf-8") as f:
        for j in out:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")
    print("TYPECOM counts in v_commune_2026:", kinds)
    print("communes (TYPECOM=COM) in registry:", len(out))
    print("codes failing CodeInseeScheme:", len(bad), bad[:10])
    print("régions represented:", len({j['region_code'] for j in out}))
    for probe in ("75056", "69123", "13055", "35238", "2A004", "2B033", "97101", "97411"):
        hit = [j for j in out if j["jurisdiction_id"] == probe]
        print(probe, "->", hit[0]["jurisdiction_name"] if hit else "MISSING")


if __name__ == "__main__":
    main()
