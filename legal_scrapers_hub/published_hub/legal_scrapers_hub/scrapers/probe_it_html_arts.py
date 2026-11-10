#!/usr/bin/env python3
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_it import api_post, UA
from common import html_to_text, ARTICLE_SPLIT

row = {"dataGU":"2026-01-08","codiceRedazionale":"26G00007"}
r = api_post("/api/v1/atto/dettaglio-atto", {
    "dataGU": row["dataGU"], "codiceRedazionale": row["codiceRedazionale"], "formatoRichiesta": "V",
})
data=r.json()
atto=((data.get('data') or {}).get('atto')) or {}
html=atto.get('articoloHtml') or ''
Path('/tmp/it_sample.html').write_text(html, encoding='utf-8')
print('html len', len(html))
# class names related to articles
classes=sorted(set(re.findall(r'class="([^"]+)"', html)))
print('classes sample', [c for c in classes if re.search(r'art|akn|titol|head|body|comma', c, re.I)][:40])
# look for article markers in raw html
for pat in [r'Art\.\s*\d+', r'articolo-num', r'article-num', r'art-?num', r'h2[^>]*>', r'data-id="[^"]*"', r'eId="[^"]*"', r'class="[^"]*art[^"]*"']:
    ms=re.findall(pat, html, re.I)
    print(pat, 'count', len(ms), 'first5', ms[:5])

# show snippets around Art.
for m in re.finditer(r'.{0,80}Art\.\s*\d+.{0,80}', html):
    print('SNIP', m.group(0).replace('\n',' ')[:200])
    if m.start()>50000: break

text=html_to_text(html)
Path('/tmp/it_sample.txt').write_text(text, encoding='utf-8')
print('text len', len(text))
print('ARTICLE_SPLIT matches', len(list(ARTICLE_SPLIT.finditer(text))))
print(ARTICLE_SPLIT.pattern)
# show unique line prefixes that look structural
lines=[ln.strip() for ln in text.splitlines() if ln.strip()]
artish=[ln for ln in lines if re.match(r'(?i)^(art|capo|titolo|sezione|libro|parte|allegato)\b', ln)]
print('structural lines', len(artish))
print('\n'.join(artish[:40]))
# also look for numbered headings like "1." at start after blank? 
nums=[ln for ln in lines if re.match(r'^\d+\.\s+\S', ln)]
print('num.paragraph lines', len(nums), 'first', nums[:5])
