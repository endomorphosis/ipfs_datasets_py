#!/usr/bin/env python3
import json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_it import api_post, UA, API, HDR
from common import get_session, html_to_text

# Law that already has 8 article docs
row = {"dataGU":"2002-05-04","codiceRedazionale":"002G0112"}
r = api_post("/api/v1/atto/dettaglio-atto", {
    "dataGU": row["dataGU"], "codiceRedazionale": row["codiceRedazionale"], "formatoRichiesta": "V",
})
atto=((r.json().get('data') or {}).get('atto')) or {}
html=atto.get('articoloHtml') or ''
print('html len', len(html))
print('article-num-akn count', len(re.findall(r'article-num-akn', html)))
print('ids', re.findall(r'id="art_\d+"', html)[:20])
print('h2 arts', re.findall(r'<h2 class="article-num-akn"[^>]*>([^<]+)</h2>', html)[:20])

# Try payloads with articolo / progressivo
payloads = [
    {"dataGU": row["dataGU"], "codiceRedazionale": row["codiceRedazionale"], "formatoRichiesta": "V", "articolo": "2"},
    {"dataGU": row["dataGU"], "codiceRedazionale": row["codiceRedazionale"], "formatoRichiesta": "V", "numeroArticolo": 2},
    {"dataGU": row["dataGU"], "codiceRedazionale": row["codiceRedazionale"], "formatoRichiesta": "V", "idArticolo": "art_2"},
    {"dataGU": row["dataGU"], "codiceRedazionale": row["codiceRedazionale"], "formatoRichiesta": "T"},  # testo?
    {"dataGU": row["dataGU"], "codiceRedazionale": row["codiceRedazionale"], "formatoRichiesta": "A"},
    {"dataGU": row["dataGU"], "codiceRedazionale": row["codiceRedazionale"], "formatoRichiesta": "V", "tipoRicerca": "tutti"},
]
for p in payloads:
    rr = api_post("/api/v1/atto/dettaglio-atto", p)
    try:
        d=rr.json()
        a=((d.get('data') or {}).get('atto')) or {}
        h=a.get('articoloHtml') or ''
        arts=re.findall(r'<h2 class="article-num-akn"[^>]*>([^<]+)</h2>', h)
        print('payload', {k:v for k,v in p.items() if k not in ('dataGU','codiceRedazionale')}, 'status', rr.status_code, 'html', len(h), 'arts', arts[:8], 'title', (a.get('titolo') or '')[:50])
    except Exception as e:
        print('payload err', p, e, rr.text[:120])

# Try other API paths
paths = [
    "/api/v1/atto/elenco-articoli",
    "/api/v1/atto/articoli",
    "/api/v1/atto/albero-atto",
    "/api/v1/atto/struttura",
    "/api/v1/atto/carica-akn",
    "/api/v1/atto/testo-atto",
    "/api/v1/atto/dettaglio",
]
base_payload = {"dataGU": row["dataGU"], "codiceRedazionale": row["codiceRedazionale"]}
for path in paths:
    try:
        rr = api_post(path, base_payload)
        print('PATH', path, rr.status_code, len(rr.content or b''), (rr.text or '')[:120].replace('\n',' '))
    except Exception as e:
        print('PATH', path, 'ERR', e)

# GET variants?
sess=get_session(UA)
for url in [
    f"{API}/api/v1/atto/dettaglio-atto?dataGU={row['dataGU']}&codiceRedazionale={row['codiceRedazionale']}",
    f"https://www.normattiva.it/atto/caricaDettaglioAtto?dataGU={row['dataGU']}&codiceRedazionale={row['codiceRedazionale']}",
    f"https://www.normattiva.it/eli/id/{row['dataGU'][:4]}/{row['codiceRedazionale']}",
]:
    try:
        rr=sess.get(url, timeout=(15,40), headers={"User-Agent":UA,"Accept":"application/json,text/html"})
        print('GET', rr.status_code, rr.headers.get('content-type'), len(rr.content), url[-80:], (rr.content[:60]))
    except Exception as e:
        print('GET ERR', url, e)
