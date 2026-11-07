#!/usr/bin/env python3
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, re
from pathlib import Path
from collections import Counter
inst = Path(str(_CORPORA) + '/it/instruments')
art_pat = re.compile(r'(?m)^(Art\.|Articolo)\s+\d+', re.I)
short=[]; medium=[]; long_no_docs=[]; with_docs=[]
heading_hits=0
for p in inst.glob('*.json'):
    d=json.loads(p.read_text(encoding='utf-8'))
    text=str(d.get('text') or '')
    tl=len(text.strip())
    docs=d.get('documents') or []
    n_heads=len(art_pat.findall(text))
    if n_heads: heading_hits+=1
    row=(p.name, tl, len(docs), n_heads, (d.get('title') or '')[:70], text[:120].replace('\n',' | '))
    if tl<80: short.append(row)
    elif tl<200: medium.append(row)
    elif not docs: long_no_docs.append(row)
    else: with_docs.append(row)

print('tl<80', len(short), '80-199', len(medium), '>=200 no docs', len(long_no_docs), 'with docs', len(with_docs))
print('laws with Art./Articolo headings', heading_hits)
print('--- short samples ---')
for r in short[:5]: print(r)
print('--- medium ---')
for r in medium[:5]: print(r)
print('--- long no docs with headings ---')
long_heads=[r for r in long_no_docs if r[3]>0]
print('count long_no_docs with heads', len(long_heads))
for r in sorted(long_heads, key=lambda x:-x[3])[:5]: print(r)
print('--- with docs sample ---')
for r in with_docs[:3]: print(r)
# look at one with docs structure
for p in inst.glob('*.json'):
    d=json.loads(p.read_text())
    if d.get('documents'):
        print('DOC EXAMPLE', p.name, 'n=', len(d['documents']))
        print(json.dumps(d['documents'][0], ensure_ascii=False)[:500])
        if len(d['documents'])>1:
            print(json.dumps(d['documents'][1], ensure_ascii=False)[:300])
        break
# bucket short text content types
c=Counter()
for r in short[:200]:
    t=r[5]
    if 'Art.' in t or 'Articolo' in t: c['has_art']=c['has_art']+1
    elif len(r[5])<60: c['tiny']=c['tiny']+1
    else: c['other']=c['other']+1
print('short content buckets sample200', c)
