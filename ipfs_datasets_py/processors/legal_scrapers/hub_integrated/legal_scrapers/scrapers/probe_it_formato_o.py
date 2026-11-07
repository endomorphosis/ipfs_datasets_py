#!/usr/bin/env python3
import json, re, sys
from pathlib import Path
sys.path.insert(0,'.')
from collect_it import api_post, UA
from common import html_to_text, http_get

# Legge with many articles - Codice civile? or known multi-art legge
# Try Costituzione or a known law with many articles via search
r = api_post('/api/v1/ricerca/semplice', {
    'testoRicerca': 'legge 241 1990',
    'orderType': 'recente',
    'paginazione': {'paginaCorrente':1,'numeroElementiPerPagina':5},
})
print('search', r.status_code)
acts=(r.json() or {}).get('listaAtti') or []
for a in acts[:3]:
    print(' ', a.get('dataGU'), a.get('codiceRedazionale'), a.get('descrizioneAtto') or a.get('titoloAtto'))

if not acts:
    acts=[{'dataGU':'1990-08-18','codiceRedazionale':'090G0294'}]

for fmt in ['V','O','M']:
    a=acts[0]
    rr=api_post('/api/v1/atto/dettaglio-atto', {
        'dataGU':a['dataGU'],'codiceRedazionale':a['codiceRedazionale'],'formatoRichiesta':fmt,
    })
    atto=((rr.json().get('data') or {}).get('atto') or {})
    html=atto.get('articoloHtml') or ''
    arts=re.findall(r'<h2 class="article-num-akn"[^>]*>([^<]+)</h2>', html)
    text=html_to_text(html)
    line_arts=re.findall(r'(?m)^Art\.\s*\d+', text)
    print(f'fmt={fmt} html={len(html)} h2arts={len(arts)} {arts[:8]} line_arts={len(line_arts)} textlen={len(text)}')

# caricaAKN variants
a=acts[0]
dgu=a['dataGU'].replace('-','')
cod=a['codiceRedazionale']
for url in [
    f'https://www.normattiva.it/do/atto/caricaAKN?dataGU={dgu}&codiceRedaz={cod}',
    f'https://www.normattiva.it/do/atto/caricaAKN?dataGU={dgu}&codiceRedaz={cod}&dataVigenza=',
    f'https://www.normattiva.it/do/atto/caricaAKN?dataGU={dgu}&codiceRedaz={cod}&dataVigenza=20260101',
    f'https://www.normattiva.it/atto/caricaDettaglioAtto?dataGU={a["dataGU"]}&codiceRedazionale={cod}',
]:
    rr=http_get(url, ua=UA, sleep=0.3)
    ct=rr.headers.get('content-type','')
    body=rr.content or b''
    print('AKN/URL', rr.status_code, ct, len(body), url.split('?')[0][-30:], body[:40])
    if b'<akoma' in body[:1000].lower() or b'<?xml' in body[:50]:
        print('  XML OK articles', len(re.findall(rb'<(?:akn:)?article\b', body, re.I)))
