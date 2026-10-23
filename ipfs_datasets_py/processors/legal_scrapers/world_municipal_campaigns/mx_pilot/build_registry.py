"""Mexico pilot — derive the municipio registry from INEGI's official
Catálogo Único de Claves de Áreas Geoestadísticas (AGEEML export API).

Source (fetched 2026-10-14):
  https://www.inegi.org.mx/app/api/ageeml/Catuni/ObtenerExpLOC/
      ?fecha=01/09/2026&tipo=2&union=0&formato=03&cod=1
(localidades-level CSV, UTF-8; the municipio registry is the distinct
(Cve_Ent, Cve_Mun) projection — the AGEEML API has no MUN export endpoint).

jurisdiction_id = Cve_Ent (2) + Cve_Mun (3), the 5-digit clave
geoestadística ("01001" = Aguascalientes, Ags.). Cabecera = the localidad
with Cve_Loc 0001 in each municipio.
"""
import csv
import json
import sys
from pathlib import Path

PILOT = Path(__file__).resolve().parent.parent
SRC = PILOT / "scratch" / "inegi_catalogo_unico_localidades_2026-09.csv"
OUT = PILOT / "data" / "jurisdictions.jsonl"


def main() -> int:
    muns: dict[str, dict] = {}
    with SRC.open(encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        nloc = 0
        skipped = 0
        for row in rdr:
            if not (row.get("Cve_Ent") or "").strip() or not (row.get("Cve_Mun") or "").strip():
                skipped += 1
                continue
            nloc += 1
            ent, mun = row["Cve_Ent"].strip(), row["Cve_Mun"].strip()
            jid = f"{ent}{mun}"
            m = muns.get(jid)
            if m is None:
                m = muns[jid] = {
                    "jurisdiction_id": jid,
                    "jurisdiction_name": row["Nom_Mun"].strip(),
                    "country": "MX",
                    "scheme": "INEGI clave geoestadistica",
                    "state_code": ent,
                    "state_name": row["Nom_Ent"].strip(),
                    "state_abbr": row["Nom_Abr"].strip(),
                    "cabecera": "",
                    "localidades": 0,
                }
            m["localidades"] += 1
            if row["Cve_Loc"].strip() == "0001":
                m["cabecera"] = row["Nom_Loc"].strip()
    rows = [muns[k] for k in sorted(muns)]
    with OUT.open("w", encoding="utf-8") as f:
        for m in rows:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    states = sorted({m["state_code"] for m in rows})
    print(f"localidades rows read: {nloc} (skipped blank-key rows: {skipped})")
    print(f"municipios derived: {len(rows)} across {len(states)} states")
    no_cab = [m["jurisdiction_id"] for m in rows if not m["cabecera"]]
    print(f"municipios without Cve_Loc 0001 cabecera row: {len(no_cab)} {no_cab[:5]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
