#!/usr/bin/env python3
"""Probe official Normattiva dettaglio-atto / caricaAKN for multi-article structure."""
import json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_it import api_post, UA, API, HDR
from common import get_session, http_get, html_to_text, xml_to_text

# Known multi-article law that already has 8 docs
row = {"dataGU":"2002-05-04","codiceRedazionale":"002G0112"}
# And a long one with only Art.1 locally
row2 = {"dataGU":"2026-01-08","codiceRedazionale":"26G00007"}
# And a mid one
row3 = {"dataGU":"2003-05-30","codiceRedazionale":"003G0142"}

def probe(row):
    print('\n====', row)
    r = api_post("/api/v1/atto/dettaglio-atto", {
        "dataGU": row["dataGU"], "codiceRedazionale": row["codiceRedazionale"], "formatoRichiesta": "V",
    })
    print('dettaglio status', r.status_code, 'len', len(r.content or b''))
    data = r.json() if r.status_code==200 else {}
    # show top keys
    print('top keys', list(data.keys())[:20])
    atto = ((data.get('data') or {}).get('atto')) or data.get('atto') or {}
    print('atto keys', sorted(atto.keys())[:40])
    for k in ['articoloHtml','html','testo','articoli','listaArticoli','numeroArticoli','elencoArticoli']:
        v=atto.get(k)
        if v is None: continue
        if isinstance(v,str):
            print(k, 'str', len(v), repr(v[:120]))
        elif isinstance(v,list):
            print(k, 'list', len(v), type(v[0]) if v else None)
            if v and isinstance(v[0], dict):
                print('  item0 keys', sorted(v[0].keys())[:20])
        else:
            print(k, type(v), v)
    # nested data keys
    if 'data' in data and isinstance(data['data'], dict):
        print('data keys', sorted(data['data'].keys())[:40])
        for k,v in data['data'].items():
            if k=='atto': continue
            if isinstance(v, list):
                print(' data.',k,'list',len(v))
                if v and isinstance(v[0], dict):
                    print('  keys', sorted(v[0].keys())[:25])
            elif isinstance(v, dict):
                print(' data.',k,'dict', sorted(v.keys())[:20])
            elif isinstance(v, str) and len(v)>80:
                print(' data.',k,'str', len(v))
            else:
                print(' data.',k, type(v).__name__, v)
    # dump small json structure summary
    def summarize(obj, prefix='', depth=0):
        if depth>3: return
        if isinstance(obj, dict):
            for k,v in list(obj.items())[:30]:
                if isinstance(v,(dict,list)):
                    print(f'{prefix}{k}: {type(v).__name__} len={len(v)}')
                    if depth<2: summarize(v, prefix+k+'.', depth+1)
                elif isinstance(v,str) and len(v)>60:
                    print(f'{prefix}{k}: str[{len(v)}]')
                else:
                    print(f'{prefix}{k}: {v!r}'[:120])
        elif isinstance(obj, list) and obj:
            print(f'{prefix}[0]:', type(obj[0]).__name__)
            if isinstance(obj[0], dict):
                summarize(obj[0], prefix+'[0].', depth+1)
    print('--- structure ---')
    summarize(data)

    # AKN
    dgu = row['dataGU'].replace('-','')
    akn = f"https://www.normattiva.it/do/atto/caricaAKN?dataGU={dgu}&codiceRedaz={row['codiceRedazionale']}&dataVigenza=20260902"
    rr = http_get(akn, ua=UA, sleep=0.4)
    print('AKN', rr.status_code, len(rr.content or b''), (rr.content or b'')[:80])
    if rr.status_code==200 and rr.content:
        txt = rr.text
        print('akn has article tags', txt.lower().count('<article'), 'akn:article', txt.count('akn:article'), 'eId=', len(re.findall(r'eId="[^"]*art', txt, re.I)))
        # count article elements
        arts = re.findall(r'<(?:akn:)?article\b[^>]*>', txt, re.I)
        print('article open tags', len(arts), arts[:5])
        body = xml_to_text(txt)
        print('akn text len', len(body), 'Art. heads', len(re.findall(r'(?m)^Art\.\s*\d+', body)))
        print(repr(body[:300]))

for row in (row, row2, row3):
    probe(row)
    time.sleep(0.5)
