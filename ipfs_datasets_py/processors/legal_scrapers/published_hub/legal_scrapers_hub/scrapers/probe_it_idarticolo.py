#!/usr/bin/env python3
import json, re, sys, time
sys.path.insert(0, "/workspace/legal_scrapers/scrapers")
from collect_it import api_post, UA, API, HDR
from common import html_to_text, get_session

# Multi-article law already known locally
row = {"dataGU": "2002-05-04", "codiceRedazionale": "002G0112"}

print("=== idArticolo int walk ===")
for i in range(0, 12):
    payload = {**row, "formatoRichiesta": "V", "idArticolo": i}
    r = api_post("/api/v1/atto/dettaglio-atto", payload)
    if r.status_code != 200:
        print(i, "HTTP", r.status_code, (r.text or "")[:100]); continue
    atto = ((r.json().get("data") or {}).get("atto")) or {}
    html = atto.get("articoloHtml") or ""
    arts = re.findall(r'<h2 class="article-num-akn"[^>]*>([^<]+)</h2>', html)
    text = html_to_text(html)
    print(f"id={i} html={len(html)} arts={arts[:3]} text_head={repr(text[:80])} tlen={len(text)}")

print("\n=== progressivo walk ===")
for i in range(0, 10):
    payload = {**row, "formatoRichiesta": "V", "progressivo": i}
    r = api_post("/api/v1/atto/dettaglio-atto", payload)
    if r.status_code != 200:
        print("prog", i, "HTTP", r.status_code); continue
    atto = ((r.json().get("data") or {}).get("atto")) or {}
    html = atto.get("articoloHtml") or ""
    arts = re.findall(r'<h2 class="article-num-akn"[^>]*>([^<]+)</h2>', html)
    print(f"prog={i} html={len(html)} arts={arts[:3]}")

print("\n=== dettaglio-atto-urn ===")
# try common URN forms
urns = [
    "urn:nir:stato:decreto:2002-03-29;80",
    "urn:nir:stato:decreto.ministeriale:2002-03-29;80",
    f"nir:stato:{row['codiceRedazionale']}",
]
# also get from ricerca
rs = api_post("/api/v1/ricerca/avanzata", {
    "dataInizioEmanazione": "2002-03-01",
    "dataFineEmanazione": "2002-03-31",
    "numeroProvvedimento": 80,
    "orderType": "vecchio",
    "paginazione": {"paginaCorrente": 1, "numeroElementiPerPagina": 20},
})
print("search80", rs.status_code)
acts = (rs.json() or {}).get("listaAtti") or []
for a in acts[:5]:
    print(" act", a.get("dataGU"), a.get("codiceRedazionale"), (a.get("titoloAtto") or "")[:70], "urn?", a.get("urn") or a.get("eli") or list(a.keys())[:12])

# dump first act keys fully
if acts:
    print("act0 keys", sorted(acts[0].keys()))
    print(json.dumps(acts[0], ensure_ascii=False)[:600])

for urn in urns:
    r = api_post("/api/v1/atto/dettaglio-atto-urn", {"urn": urn})
    print("URN", urn, r.status_code, len(r.content or b''), (r.text or "")[:160].replace("\n"," "))

# tipoDettaglio guesses
print("\n=== tipoDettaglio ===")
for td in ["T", "A", "L", "I", "S", "P", "FULL", "ALL", "lista", "TREE"]:
    payload = {**row, "formatoRichiesta": "V", "tipoDettaglio": td}
    r = api_post("/api/v1/atto/dettaglio-atto", payload)
    if r.status_code != 200:
        print(td, "HTTP", r.status_code); continue
    data = r.json().get("data") or {}
    atto = data.get("atto") or {}
    html = atto.get("articoloHtml") or ""
    lista = data.get("lista")
    arts = re.findall(r'<h2 class="article-num-akn"[^>]*>([^<]+)</h2>', html)
    print(f"td={td} html={len(html)} arts={len(arts)} lista={type(lista).__name__}:{len(lista) if isinstance(lista,list) else lista} data_keys={list(data.keys())}")
