#!/usr/bin/env python3
"""Spain: BOE datos abiertos API, legislación consolidada (estatal -> iso:ES, autonómico -> iso:ES-XX).
robots.txt of www.boe.es allows /datosabiertos/. 1 req/s. Resumable (done ids)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, re, sys
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/common"))
from natlib import PoliteSession, Stager, setup_log, norm_date, html_to_text, Blocked

API = "https://www.boe.es/datosabiertos/api/legislacion-consolidada"
CCAA_BY_NAME = {"andaluc": "AN", "arag": "AR", "asturias": "AS", "balears": "IB", "baleares": "IB", "canarias": "CN",
    "cantabria": "CB", "castilla y le": "CL", "castilla-la mancha": "CM", "catalu": "CT", "extremadura": "EX", "galicia": "GA",
    "madrid": "MD", "murcia": "MC", "navarra": "NC", "vasco": "PV", "euskadi": "PV", "rioja": "RI", "valencia": "VC",
    "ceuta": "CE", "melilla": "ML"}
log = setup_log("ES", "boe")
S = PoliteSession(min_delay=1.0, log=log)
st = Stager("ES", "boe", chunk=300, log=log)

def region(item):
    m = re.search(r"/eli/es-([a-z]{2})/", item.get("url_eli") or "")
    if m: return m[1].upper()
    name = ((item.get("departamento") or {}).get("texto") or "").lower()
    for k, v in CCAA_BY_NAME.items():
        if k in name: return v
    return None

def listing():
    off = 0
    while True:
        r = S.get(API, params={"limit": 500, "offset": off}, headers={"Accept": "application/json"})
        data = r.json().get("data") or []
        if not data: return
        yield from data
        off += len(data)
        log.info("listed %d", off)

def main():
    n = 0
    for it in listing():
        did = it["identificador"]
        if st.seen(did): continue
        amb = (it.get("ambito") or {}).get("codigo")
        if amb == "2":
            reg = region(it)
            if not reg: log.warning("no region for %s", did); continue
            pid, admin, iso2 = f"iso:ES-{reg}", "adm1", f"ES-{reg}"
        else:
            pid, admin, iso2 = "iso:ES", "country", None
        try:
            x = S.get(f"{API}/id/{did}/texto", headers={"Accept": "application/xml"}).text
        except Blocked as e:
            log.error("blocked %s", e); continue
        except Exception as e:
            log.warning("fail %s %s", did, e); continue
        text = html_to_text(x)
        rango = ((it.get("rango") or {}).get("texto") or "").lower()
        dt = "statute" if re.search(r"^(ley|real decreto[- ]ley|real decreto legislativo|decreto[- ]ley|decreto legislativo|constituci|estatuto)", rango) else "regulation"
        st.add({"place_id": pid, "country_code": "ES", "doc_id": did, "source_platform": "es_boe_consolidada",
                "source_url": it.get("url_html_consolidada") or f"https://www.boe.es/buscar/act.php?id={did}",
                "doc_type": dt, "language": "es", "title_native": it.get("titulo"), "number": it.get("numero_oficial"),
                "adopted_date": norm_date(it.get("fecha_disposicion")), "published_date": norm_date(it.get("fecha_publicacion")),
                "effective_date": norm_date(it.get("fecha_vigencia")),
                "in_force": {"N": True, "S": False}.get(it.get("vigencia_agotada")), "consolidated": True,
                "content_format": "xml", "text": text, "admin_level": admin, "iso_3166_2": iso2,
                "place_name": (it.get("departamento") or {}).get("texto") if admin == "adm1" else "Spain",
                "platform": "es_boe_consolidada"})
        n += 1
    st.flush(); log.info("FINISHED staged=%d invalid=%d", st.n, st.bad)

if __name__ == "__main__":
    try: main()
    finally: st.flush()
