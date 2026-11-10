#!/usr/bin/env python3
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_it import api_post, UA, API
from common import html_to_text, get_session

row = {"dataGU":"2002-05-04","codiceRedazionale":"002G0112"}
# also a classic multi-article law: Legge 241/1990
rows = [
    row,
    {"dataGU":"1990-08-18","codiceRedazionale":"090G0294"},  # maybe
    {"dataGU":"2004-01-17","codiceRedazionale":"004G0015"},  # Legge Stanca 4/2004 from docs
]

# dettaglio-atto-multi
for r0 in rows[:1]:
    for path in ["/api/v1/atto/dettaglio-atto-multi", "/api/v1/atto/dettaglioAttoMulti", "/api/v1/atto/dettaglio-atti-multi"]:
        for payload in [
            {"dataGU": r0["dataGU"], "codiceRedazionale": r0["codiceRedazionale"], "formatoRichiesta": "V"},
            {"atti":[{"dataGU": r0["dataGU"], "codiceRedazionale": r0["codiceRedazionale"]}], "formatoRichiesta": "V"},
            {"listaAtti":[{"dataGU": r0["dataGU"], "codiceRedazionale": r0["codiceRedazionale"]}], "formatoRichiesta": "V"},
        ]:
            rr = api_post(path, payload)
            print('MULTI', path, 'keys', list(payload.keys()), 'status', rr.status_code, 'len', len(rr.content or b''), (rr.text or '')[:180].replace('\n',' '))

# Inspect HTML structure of 002G0112 for Art.2
r = api_post("/api/v1/atto/dettaglio-atto", {
    "dataGU": row["dataGU"], "codiceRedazionale": row["codiceRedazionale"], "formatoRichiesta": "V",
})
html=((r.json().get('data') or {}).get('atto') or {}).get('articoloHtml') or ''
print('\n--- Art. occurrences context ---')
for m in re.finditer(r'Art\.\s*[2-8]', html):
    snip=html[max(0,m.start()-100):m.start()+80].replace('\n',' ')
    print(snip[:200])
    if m.start()>20000: break

# Compare local stored text article heads
local=json.loads(Path('/workspace/legal-corpora/it/instruments/it-2002-05-04-002g0112.json').read_text())
print('\nlocal text Art heads', re.findall(r'(?m)^Art\.\s*\d+[^\n]{0,40}', local['text'])[:12])
print('local docs', len(local.get('documents') or []))
print('local text len', len(local['text']), 'api html_to_text len', len(html_to_text(html)))
api_text=html_to_text(html)
print('api text Art heads', re.findall(r'(?m)^Art\.\s*\d+[^\n]{0,40}', api_text)[:12])
# show if Art.2 is mid-line in api text
for m in re.finditer(r'.{0,30}Art\.\s*2.{0,40}', api_text):
    print('API Art2 context:', repr(m.group(0)))
    break

# Try legge stanca
r2 = api_post("/api/v1/atto/dettaglio-atto", {
    "dataGU":"2004-01-17","codiceRedazionale":"004G0015","formatoRichiesta":"V",
})
print('\nStanca status', r2.status_code)
if r2.status_code==200:
    h2=((r2.json().get('data') or {}).get('atto') or {}).get('articoloHtml') or ''
    print('stanca html', len(h2), 'article-num', len(re.findall('article-num-akn', h2)), 'h2arts', re.findall(r'<h2 class="article-num-akn"[^>]*>([^<]+)</h2>', h2))
    t2=html_to_text(h2)
    print('stanca text heads', re.findall(r'(?m)^Art\.\s*\d+', t2)[:20], 'len', len(t2))
