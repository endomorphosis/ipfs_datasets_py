#!/usr/bin/env python3
"""Generate out/coverage_report.md + out/README.md from the pilot
summary and the registry (surveyed-vs-covered, honestly named)."""
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "out"
DATA = HERE / "data"

LANDS = {
    "01": "Schleswig-Holstein", "02": "Hamburg", "03": "Niedersachsen",
    "04": "Bremen", "05": "Nordrhein-Westfalen", "06": "Hessen",
    "07": "Rheinland-Pfalz", "08": "Baden-Württemberg", "09": "Bayern",
    "10": "Saarland", "11": "Berlin", "12": "Brandenburg",
    "13": "Mecklenburg-Vorpommern", "14": "Sachsen",
    "15": "Sachsen-Anhalt", "16": "Thüringen",
}


def main():
    summary = json.loads((OUT / "pilot_summary.json").read_text(encoding="utf-8"))
    registry = [json.loads(ln) for ln in
                (DATA / "jurisdictions.jsonl").read_text(encoding="utf-8").splitlines()]
    per_land = Counter(r["land_code"] for r in registry)
    total_rows = sum(s["rows"] for s in summary)
    total_docs = sum(s["extracted"] for s in summary)

    lines = [
        "# Coverage report — Germany municipal laws (PILOT SEED)",
        "",
        "This dataset is a **pilot seed**, not a complete collection of",
        "German municipal law. It covers the Gemeinden listed below out of",
        f"**{len(registry)} Gemeinden** in the official Destatis",
        "Gemeindeverzeichnis registry (Stand 31.12.2025) shipped in",
        "`data/jurisdictions.jsonl`.",
        "",
        "## Covered in this seed",
        "",
        "| AGS | Gemeinde | Land | Docs | Article rows |",
        "|---|---|---|---:|---:|",
    ]
    for s in sorted(summary, key=lambda x: x["ags"]):
        land = LANDS.get(s["ags"][:2], s["ags"][:2])
        lines.append(f"| {s['ags']} | {s['name']} | {land} | "
                     f"{s['extracted']} | {s['rows']} |")
    lines += [
        f"| | **Total** | | **{total_docs}** | **{total_rows}** |",
        "",
        "Sources: each Gemeinde's own official Ortsrecht/Satzungen PDF",
        "collection on its municipal website. Documents were fetched from",
        "the live official URL where reachable, else from the Wayback",
        "Machine's snapshot of that same official URL (per-document route",
        "recorded in the `source_route` column). Texts are split into",
        "article (§) rows in the shared world_municipal 19-column schema.",
        "",
        "## Surveyed but NOT covered",
        "",
        f"All other {len(registry) - len(summary)} Gemeinden in the registry.",
        "Route survey (2026-10-14): own-site CMS Ortsrecht trees are the",
        "workable route found so far; Ratsinformationssysteme (SessionNet/",
        "ALLRIS, SD.NET) did not connect from the harvesting network and",
        "remain unsurveyed at scale. Several candidate town sites have no",
        "usable web archive coverage either (e.g. Marne, Berchtesgaden,",
        "Böblingen, Celle at survey time).",
        "",
        "## Registry size by Land (Gemeinden)",
        "",
    ]
    for code in sorted(per_land):
        lines.append(f"- {LANDS[code]}: {per_land[code]}")
    cov = "\n".join(lines) + "\n"
    (OUT / "coverage_report.md").write_text(cov, encoding="utf-8")

    readme = f"""# ipfs_germany_municipal_laws — pilot seed

German municipal ordinances (Satzungen/Verordnungen) normalized into
the world municipal-law program's shared 19-column schema, built with
`ipfs_datasets_py`'s `world_municipal` library.

**Status: pilot seed.** {len(summary)} Gemeinden of {len(registry)} in
the official Destatis Gemeindeverzeichnis (Stand 31.12.2025),
{total_docs} documents, {total_rows} article rows. See
`coverage_report.md` for exactly what is and is not covered.

## Layout

- `data/{{ags}}_html.parquet` — one file per Gemeinde (AGS =
  Amtlicher Gemeindeschlüssel, 8 digits), article-level rows
- `data/{{ags}}_validation.json` — fail-closed validation sidecar
- `data/jurisdictions.jsonl` — the full official registry
  (10,751 Gemeinden; 202 unincorporated gemeindefreie Gebiete excluded)
- `scrapers/` — the pilot's registry builder, harvester and publisher

Registry source: Statistisches Bundesamt (Destatis),
Gemeindeverzeichnis quarterly extract, Stand 31.12.2025.
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    print(f"wrote coverage_report.md + README.md ({len(summary)} Gemeinden, "
          f"{total_docs} docs, {total_rows} rows)")


if __name__ == "__main__":
    main()
