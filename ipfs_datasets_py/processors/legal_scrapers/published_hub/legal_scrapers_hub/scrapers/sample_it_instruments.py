#!/usr/bin/env python3
import json, statistics
from pathlib import Path
inst = Path('/workspace/legal-corpora/it/instruments')
files = list(inst.glob('*.json'))
print('n_files', len(files))
empty=short=ok=0
has_docs=has_arts=0
text_lens=[]
doc_counts=[]; art_counts=[]
samples_empty=[]; samples_ok=[]; samples_arts=[]
for i,p in enumerate(files):
    try:
        d=json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        continue
    text=(d.get('text') or d.get('body') or '')
    if isinstance(text, list):
        text='\n'.join(str(x) for x in text)
    text=str(text)
    tl=len(text.strip())
    text_lens.append(tl)
    docs=d.get('documents') or []
    arts=d.get('articles') or []
    if isinstance(docs, dict): docs=[docs]
    if isinstance(arts, dict): arts=[arts]
    nd=len(docs) if isinstance(docs, list) else 0
    na=len(arts) if isinstance(arts, list) else 0
    if nd: has_docs+=1
    if na: has_arts+=1
    doc_counts.append(nd); art_counts.append(na)
    if tl<40:
        empty+=1
        if len(samples_empty)<3:
            samples_empty.append((p.name, tl, sorted(d.keys())[:15], (d.get('title') or '')[:80]))
    elif tl<200:
        short+=1
    else:
        ok+=1
        if len(samples_ok)<2:
            samples_ok.append((p.name, tl, na, nd))
    if na and len(samples_arts)<2:
        a0=arts[0] if arts else {}
        at = a0.get('text') or a0.get('body') or '' if isinstance(a0, dict) else str(a0)
        samples_arts.append((p.name, na, list(a0.keys())[:10] if isinstance(a0,dict) else type(a0).__name__, str(at)[:120]))
    if i and i%2000==0:
        print('...', i, flush=True)

print('empty(<40)', empty, 'short(40-199)', short, 'ok(>=200)', ok)
print('has_documents', has_docs, 'has_articles', has_arts)
print('text_len min/med/mean/max', min(text_lens), statistics.median(text_lens), round(statistics.mean(text_lens)), max(text_lens))
print('art_count sum', sum(art_counts), 'nonzero', sum(1 for x in art_counts if x), 'max', max(art_counts) if art_counts else 0)
print('doc_count sum', sum(doc_counts), 'nonzero', sum(1 for x in doc_counts if x))
print('samples_empty', samples_empty)
print('samples_ok', samples_ok)
print('samples_arts', samples_arts)
d=json.loads(files[0].read_text())
print('schema keys', sorted(d.keys()))
print('title', (d.get('title') or '')[:100])
print('text[:200]', repr((d.get('text') or '')[:200]))
print('meta', {k:d.get(k) for k in ('id','source_url','collector','document_type') if k in d or True})
