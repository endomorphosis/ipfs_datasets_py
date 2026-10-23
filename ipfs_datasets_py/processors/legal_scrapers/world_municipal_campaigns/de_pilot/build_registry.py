#!/usr/bin/env python3
"""Build the Germany Gemeinde registry from the official Destatis
Gemeindeverzeichnis quarterly extract (GV100 Auszug, Stand 31.12.2025).

Source file: raw/AuszugGV4QAktuell.xlsx (Destatis, "Alle politisch
selbständigen Gemeinden mit ausgewählten Merkmalen am 31.12.2025
(4. Quartal)"), sheet "Onlineprodukt_Gemeinden31122025".

Rows with Satzart 60 are Gemeinde-level units. Textkennzeichen (TKZ)
65/66 are gemeindefreie Bezirke/Gebiete (unincorporated areas, no
Gemeinde council, no Satzungen of their own) and are EXCLUDED, in the
count reported separately. All other TKZ are real Gemeinden
(60 Markt, 61 kreisfreie Stadt, 62 Stadtkreis, 63 Stadt, 64 Gemeinde,
67 BW Stadt).

AGS (Amtlicher Gemeindeschlüssel, 8 digits) = Land(2) + RB(1) +
Kreis(2) + Gemeinde(3). The extract's extra VB (Verband) component is
part of the 12-digit Amtlicher Regionalschlüssel, NOT of the AGS, and
is kept only as provenance.

Output: data/jurisdictions.jsonl — one JSON object per Gemeinde.
"""
import json
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent.parent
SRC = HERE / "raw" / "AuszugGV4QAktuell.xlsx"
OUT = HERE / "data" / "jurisdictions.jsonl"

LAND_NAMES = {
    "01": "Schleswig-Holstein", "02": "Hamburg", "03": "Niedersachsen",
    "04": "Bremen", "05": "Nordrhein-Westfalen", "06": "Hessen",
    "07": "Rheinland-Pfalz", "08": "Baden-Württemberg", "09": "Bayern",
    "10": "Saarland", "11": "Berlin", "12": "Brandenburg",
    "13": "Mecklenburg-Vorpommern", "14": "Sachsen",
    "15": "Sachsen-Anhalt", "16": "Thüringen",
}
TKZ_KIND = {
    "60": "markt", "61": "kreisfreie_stadt", "62": "stadtkreis",
    "63": "stadt", "64": "gemeinde", "67": "stadt",
}
EXCLUDED_TKZ = {"65", "66"}  # gemeindefreie Bezirke / Gebiete


def main():
    wb = openpyxl.load_workbook(SRC, read_only=True)
    ws = wb["Onlineprodukt_Gemeinden31122025"]
    rows, excluded = [], []
    for r in ws.iter_rows(values_only=True):
        if r[0] is None or str(r[0]) != "60":
            continue
        land, rb, kreis, vb, gem = (str(r[i]).strip() for i in (2, 3, 4, 5, 6))
        tkz = str(r[1]).strip()
        name = str(r[7]).strip()
        ags = f"{land.zfill(2)}{rb}{kreis.zfill(2)}{gem.zfill(3)}"
        assert len(ags) == 8 and ags.isdigit(), ags
        rec = {
            "code": ags,
            "name": name,
            "land": LAND_NAMES.get(land, land),
            "land_code": land,
            "kind": TKZ_KIND.get(tkz, "gemeinde"),
            "textkennzeichen": tkz,
            "verbandsschluessel": vb,
            "area_sqkm": r[8],
            "population": r[9],
            "plz": str(r[13]).strip() if r[13] is not None else "",
        }
        (excluded if tkz in EXCLUDED_TKZ else rows).append(rec)
    assert len({r["code"] for r in rows}) == len(rows), "duplicate AGS"
    rows.sort(key=lambda r: r["code"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"registry: {len(rows)} Gemeinden written to {OUT}")
    print(f"excluded unincorporated (TKZ 65/66): {len(excluded)}")
    from collections import Counter
    print("per Land:", dict(sorted(Counter(r['land_code'] for r in rows).items())))


if __name__ == "__main__":
    main()
