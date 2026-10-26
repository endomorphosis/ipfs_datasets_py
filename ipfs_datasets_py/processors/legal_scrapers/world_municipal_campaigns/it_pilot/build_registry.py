#!/usr/bin/env python3
"""Build the Italy jurisdictions registry from ISTAT's official comuni list.

Source: Elenco-comuni-italiani.csv (ISTAT, www.istat.it — "Codici statistici
delle unità amministrative territoriali"). Emits jurisdictions.jsonl with
one row per comune: codice ISTAT (6-digit alphanumeric form), official
name, region, province/UTS, NUTS3, cadastral code. Also prints the set of
province prefixes (first 3 digits) for the IstatCodiceScheme validator.
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "raw"
SRC = RAW / "Elenco-comuni-italiani.csv"
OUT = HERE.parent / "out" / "jurisdictions.jsonl"


def main():
    raw = SRC.read_bytes()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            used = enc
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.DictReader(text.splitlines(), delimiter=";"))
    print(f"encoding={used} rows={len(rows)}")
    cols = rows[0].keys()
    code_col = next(c for c in cols if c.startswith("Codice Comune formato alfanumerico"))
    name_col = "Denominazione in italiano"
    full_name_col = next(c for c in cols if c.startswith("Denominazione (Italiana"))
    region_col = "Denominazione Regione"
    prov_col = next(c for c in cols if c.startswith("Denominazione dell'Unit"))
    nuts3_col = "Codice NUTS3 2021"
    cat_col = "Codice Catastale del comune"
    regcode_col = "Codice Regione"
    out_rows, provinces, regions = [], set(), {}
    for r in rows:
        code = (r[code_col] or "").strip()
        if not code:
            continue
        code = code.zfill(6)
        provinces.add(code[:3])
        regions[r[regcode_col]] = r[region_col]
        out_rows.append({
            "code": code,
            "name": (r[name_col] or r[full_name_col] or "").strip(),
            "region_code": (r[regcode_col] or "").strip(),
            "region": (r[region_col] or "").strip(),
            "province": (r[prov_col] or "").strip(),
            "nuts3": (r[nuts3_col] or "").strip(),
            "cadastral_code": (r[cat_col] or "").strip(),
            "kind": "comune",
        })
    out_rows.sort(key=lambda x: x["code"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(out_rows)} comuni -> {OUT}")
    print(f"regions ({len(regions)}): {sorted(regions.values())}")
    print(f"province prefixes ({len(provinces)}): {sorted(provinces)}")
    dupes = len(out_rows) - len({r['code'] for r in out_rows})
    print("duplicate codes:", dupes)


if __name__ == "__main__":
    sys.exit(main())
