"""Build the verified SGC jurisdiction registry for the Canada pilot.

Source: Statistics Canada table 17-10-0155 ("Population estimates, July 1,
by census subdivision, 2021 boundaries"), full-download CSV, retrieved
2026-10-13 from https://www150.statcan.gc.ca/n1/tbl/csv/17100155-eng.zip
(CKAN package b3e6fb57-8016-4af6-a54c-70108052c6bf on open.canada.ca).

Every census subdivision (CSD) row carries DGUID "2021A0005" + the
7-digit SGC code and GEO "Name (TYPE), Province". We extract the unique
CSD set, count-verify it in code, and assert the pilot municipalities
resolve to the right names/provinces. Output: sgc_registry_2021.jsonl
(full CSD list) + registry_stats.json.
"""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

OUT = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/ca_pilot"
CSV_PATH = OUT / "data" / "statcan" / "17100155.csv"

PROV_TAIL_RE = re.compile(
    r",\s*(Newfoundland and Labrador|Prince Edward Island|Nova Scotia|"
    r"New Brunswick|Quebec|Ontario|Manitoba|Saskatchewan|Alberta|"
    r"British Columbia|Yukon|Northwest Territories|Nunavut)$")
PAREN_RE = re.compile(r"\(([^()]*)\)")


def parse_geo(geo: str):
    """GEO = 'Name (TYPE), [County, ]Province' — take the province from the
    tail and the CSD type as the LAST parenthesized group before it."""
    pm = PROV_TAIL_RE.search(geo)
    assert pm, geo
    prov = pm.group(1)
    head = geo[:pm.start()]
    groups = list(PAREN_RE.finditer(head))
    assert groups, geo
    g = groups[-1]
    name = (head[:g.start()] + head[g.end():]).strip(" ,")
    return name, g.group(1), prov
PROV_BY_PR = {"10": "Newfoundland and Labrador", "11": "Prince Edward Island",
              "12": "Nova Scotia", "13": "New Brunswick", "24": "Quebec",
              "35": "Ontario", "46": "Manitoba", "47": "Saskatchewan",
              "48": "Alberta", "59": "British Columbia", "60": "Yukon",
              "61": "Northwest Territories", "62": "Nunavut"}

# CSD types that are NOT municipal governments, classified by inspecting
# the actual records (name + province) for every ambiguous type:
#   IRI/S-É/TC/TK/TI/TAL/TL/NL  Indigenous reserves, settlements, treaty or
#                               self-government lands (incl. QC terres
#                               réservées / inuites doublings of VC/VN/VK)
#   NO/SNO/SET/SÉ               unorganized territories, subdivisions of
#                               unorganized, unincorporated settlements
#   RDA                         BC regional-district electoral areas
#   SC                          NS subdivisions of county municipalities
#   FD                          PEI fire districts
#   P                           New Brunswick parishes (service geography)
#   ID/SA                       AB improvement districts / special areas
#                               (provincially administered, no council)
#   IGD                         Sechelt Indian Government District (x2 CSDs)
# Everything else is an incorporated municipality or municipal-type
# government (incl. QC paroisses/cantons/villages nordiques & cris, NT
# charter communities & Tlicho community governments, AB summer villages,
# SK resort villages, MB local government districts, Eeyou Istchee
# Baie-James regional government).
NON_MUNICIPAL_TYPES = {"IRI", "S-É", "SÉ", "TC", "TK", "TI", "TAL", "TL",
                       "NL", "NO", "SNO", "SET", "RDA", "SC", "FD", "P",
                       "ID", "SA", "IGD"}

csds = {}
with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        dguid = row["DGUID"]
        if not (dguid.startswith("2021A0005") and len(dguid) == 16):
            continue
        sgc = dguid[-7:]
        name, ctype, prov = parse_geo(row["GEO"])
        prev = csds.get(sgc)
        rec = {"sgc": sgc, "name": name, "csd_type": ctype,
               "province": prov, "pr": sgc[:2], "cd": sgc[2:4]}
        if prev is not None:
            assert prev == rec, f"conflicting records for {sgc}: {prev} vs {rec}"
        csds[sgc] = rec

assert len(csds) > 4000, len(csds)
# every province prefix must resolve and agree with the GEO province label
for rec in csds.values():
    assert PROV_BY_PR[rec["pr"]] == rec["province"], rec

types = Counter(r["csd_type"] for r in csds.values())
municipal = {s: r for s, r in csds.items() if r["csd_type"] not in NON_MUNICIPAL_TYPES}
non_muni = {s: r for s, r in csds.items() if r["csd_type"] in NON_MUNICIPAL_TYPES}

PILOT = {"3520005": ("Toronto", "Ontario"), "5915004": ("Surrey", "British Columbia"),
         "1209034": ("Halifax", "Nova Scotia"), "2481017": ("Gatineau", "Quebec")}
for sgc, (name, prov) in PILOT.items():
    rec = csds.get(sgc)
    assert rec is not None, f"pilot code {sgc} missing from registry"
    assert rec["name"] == name and rec["province"] == prov, (sgc, rec)
    print(f"pilot {sgc}: {rec['name']} ({rec['csd_type']}), {rec['province']}  OK")

with (OUT / "sgc_registry_2021.jsonl").open("w", encoding="utf-8") as f:
    for sgc in sorted(csds):
        r = csds[sgc]
        f.write(json.dumps({**r, "municipal_government": r["csd_type"] not in NON_MUNICIPAL_TYPES},
                           ensure_ascii=False) + "\n")

stats = {
    "source": "Statistics Canada table 17-10-0155 (2021 boundaries), CSV retrieved 2026-10-13",
    "source_url": "https://www150.statcan.gc.ca/n1/tbl/csv/17100155-eng.zip",
    "total_csds": len(csds),
    "municipal_government_csds": len(municipal),
    "non_municipal_csds": len(non_muni),
    "type_counts": dict(sorted(types.items(), key=lambda kv: -kv[1])),
    "municipal_by_province": dict(sorted(Counter(r["pr"] for r in municipal.values()).items())),
    "non_municipal_types_excluded": sorted(NON_MUNICIPAL_TYPES),
}
(OUT / "registry_stats.json").write_text(json.dumps(stats, indent=1))
print(json.dumps(stats, indent=1))
