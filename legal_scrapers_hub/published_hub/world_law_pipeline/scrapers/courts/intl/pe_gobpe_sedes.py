"""PE: official Poder Judicial sedes (Sede Central + Cortes Superiores) with street addresses and switchboard numbers from
gob.pe/institucion/pj/sedes (pj.gob.pe now redirects to gob.pe). Adds courthouse rows; skips ids already present."""
import json, re, html, datetime, hashlib, os, unicodedata, time, requests
ROOT = "/workspace/world_courts"; UA = "Mozilla/5.0 (world_courts research; public court data)"
BASE = "https://www.gob.pe/institucion/pj/sedes"; OUT = f"{ROOT}/data/pe/pe_courthouses.jsonl"
now = datetime.datetime.now(datetime.UTC).isoformat()
def slug(s): return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip("-")
rows = []
for sheet in range(1, 6):
    u = BASE if sheet == 1 else f"{BASE}?sheet={sheet}"
    r = requests.get(u, headers={"User-Agent": UA}, timeout=60); r.raise_for_status(); time.sleep(3)
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", r.text, flags=re.S)
    x = [y for y in (re.sub(r"\s+", " ", html.unescape(z)).strip() for z in re.sub(r"<[^>]+>", "\n", t).split("\n")) if y]
    k = max(i for i, y in enumerate(x) if y == "Sedes"); got = 0
    for i in range(k, len(x) - 1):
        if (x[i] == "Sede Central" or x[i].startswith("Corte Superior de Justicia")) and x[i + 1].endswith("Perú"):
            phone = None
            for j in range(i + 2, min(i + 6, len(x) - 1)):
                if x[j] == "Central telefónica": phone = x[j + 1]
                if x[j].startswith("Corte Superior"): break
            rows.append((x[i], x[i + 1], phone, u, hashlib.sha256(r.content).hexdigest())); got += 1
    if not got or "Siguiente" not in x or f"sheet={sheet + 1}" not in r.text: break
have = {json.loads(l)["court_id"] for l in open(OUT)}; n = 0
with open(OUT, "a") as f:
    for name, addr, phone, u, sha in rows:
        parts = [p.strip() for p in addr.split(" - ")]
        street, city, region = parts[0], (parts[1] if len(parts) > 1 else None), (parts[-2] if len(parts) > 2 else None)
        nm = "Poder Judicial - Sede Central (Palacio de Justicia)" if name == "Sede Central" else name
        cid = "pe-pj-sede-central" if name == "Sede Central" else "pe-" + slug(name).replace("corte-superior-de-justicia-de-l-", "csj-").replace("corte-superior-de-justicia-del-", "csj-").replace("corte-superior-de-justicia-de-", "csj-")
        cid += "-sede"
        if cid in have: continue
        f.write(json.dumps({"court_id": cid, "record_type": "courthouse", "name": nm, "name_local": nm,
            "level": "supreme" if name == "Sede Central" else "appellate", "court_system": "national", "country_code": "PE", "subdivision": None,
            "jurisdiction": None, "parent_court_id": "pe-corte-suprema" if name == "Sede Central" else "pe-corte-superior",
            "address": {"street": street, "city": city, "postcode": None, "region": region, "country": "PE"}, "geo": {"lat": None, "lon": None},
            "phone": (("+51 1 " + phone) if phone else None), "website": u, "wikidata": None, "place_ids": [], "source_url": u, "source_kind": "official_page",
            "site_policy": ("robots_disallowed_user_authorized" if "sheet=" in u else "robots_allowed") + "|gob.pe terminos y condiciones", "retrieved_at": now, "license": "official public information (gob.pe); no licence stated",
            "sources": [{"source_url": u, "site_policy": ("robots_disallowed_user_authorized" if "sheet=" in u else "robots_allowed") + "|gob.pe terminos y condiciones", "source_kind": "official_page", "source_sha256": sha}],
            "needs_review": False, "record_note": f"Official address as listed on gob.pe: {addr}"}, ensure_ascii=False) + "\n"); n += 1; have.add(cid)
print("parsed", len(rows), "added", n)
