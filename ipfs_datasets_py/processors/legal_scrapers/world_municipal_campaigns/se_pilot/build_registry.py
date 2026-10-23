"""Build jurisdictions.jsonl (290 kommuner) from scratch/scb_pairs.json."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
pairs = json.loads((OUT / "scratch" / "scb_pairs.json").read_text(encoding="utf-8"))

LAN = {
    "01": "Stockholms län", "03": "Uppsala län", "04": "Södermanlands län",
    "05": "Östergötlands län", "06": "Jönköpings län", "07": "Kronobergs län",
    "08": "Kalmar län", "09": "Gotlands län", "10": "Blekinge län",
    "12": "Skåne län", "13": "Hallands län", "14": "Västra Götalands län",
    "17": "Värmlands län", "18": "Örebro län", "19": "Västmanlands län",
    "20": "Dalarnas län", "21": "Gävleborgs län", "22": "Västernorrlands län",
    "23": "Jämtlands län", "24": "Västerbottens län", "25": "Norrbottens län",
}

rows = []
for code in sorted(pairs):
    lan = code[:2]
    assert lan in LAN, code
    rows.append({
        "jurisdiction_id": code,
        "jurisdiction_name": pairs[code],
        "country": "SE",
        "lan_code": lan,
        "lan_name": LAN[lan],
        "registry": "SCB län och kommuner i kodnummerordning",
        "registry_url": ("https://www.scb.se/hitta-statistik/regional-statistik-och-kartor/"
                         "regionala-indelningar/lan-och-kommuner/"
                         "lan-och-kommuner-i-kodnummerordning/"),
    })
assert len(rows) == 290, len(rows)
with (OUT / "jurisdictions.jsonl").open("w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("wrote", len(rows), "jurisdictions")
print("Stockholm:", [r for r in rows if r["jurisdiction_id"] == "0180"])
print("Gotland (single-kommun län):", [r for r in rows if r["lan_code"] == "09"])
