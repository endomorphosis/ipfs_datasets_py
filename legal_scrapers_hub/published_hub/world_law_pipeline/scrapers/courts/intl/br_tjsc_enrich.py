"""Enrich existing OSM rows that duplicate TJSC comarca fóruns (same name+city): fill missing street/postcode/phone,
set level trial_general, parent TJSC, append official source. No new rows."""
import json, sys, re, html, glob, os
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
RAW = f"{ROOT}/rules/raw/br_tjsc"; OUT = f"{ROOT}/data/br/br_courthouses.jsonl"
rows = [json.loads(l) for l in open(OUT)]; by = {}
for r in rows:
    if r["court_id"].startswith("osm:") and r.get("subdivision") == "BR-SC": by.setdefault(norm(r["name"]), r)
n = 0
for f in glob.glob(f"{RAW}/*.html"):
    slug = os.path.basename(f)[:-5]
    if slug == "list": continue
    s = re.sub(r"\n\s*\n+", "\n", re.sub(r"<[^>]+>", "\n", html.unescape(open(f, encoding="utf-8", errors="ignore").read())))
    m = re.search(r"Comarca de ([^\n]+)\n(.*?)\nAbrir todos", s, re.S)
    if not m: continue
    r = by.get(norm(f"Fórum da Comarca de {m.group(1).strip()}"))
    if not r: continue
    block = [x.strip() for x in m.group(2).split("\n") if x.strip()]
    tel = next((x for x in block if re.fullmatch(r"\(\d{2}\)\s*[\d -]+", x)), None)
    adr = next((x for x in block if re.search(r"- SC,?\s*\d{5}-?\d{3}", x)), None); a = r.setdefault("address", {})
    if adr:
        mm = re.match(r"(.*),\s*([^,]+?)\s*-\s*SC,?\s*(\d{5}-?\d{3})", adr)
        if mm:
            a["street"] = a.get("street") or mm.group(1); a["city"] = a.get("city") or mm.group(2); a["postcode"] = a.get("postcode") or mm.group(3)
    r["phone"] = r.get("phone") or tel; r["level"] = "trial_general" if r.get("level") == "other" else r["level"]
    r["parent_court_id"] = r.get("parent_court_id") or "br-sc-appellate-tjsc"; src = f"https://www.tjsc.jus.br/comarcas/{slug}"
    if not any(x.get("source_url") == src for x in r.setdefault("sources", [])):
        r["sources"].append({"source_url": src, "site_policy": "robots_unknown:official", "source_kind": "official"}); n += 1
open(OUT, "w").write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)); print("enriched", n)
