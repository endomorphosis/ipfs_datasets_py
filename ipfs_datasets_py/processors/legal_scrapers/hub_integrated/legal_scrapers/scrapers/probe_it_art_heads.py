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
# several patterns
pats = {
 'line_Art': re.compile(r'(?m)^Art\.\s*\d+', re.I),
 'line_Articolo': re.compile(r'(?m)^Articolo\s+\d+', re.I),
 'any_Art_num': re.compile(r'(?m)(?:^|\n)\s*Art\.\s*\d+[\.\-:]?', re.I),
 'ART_upper': re.compile(r'(?m)^ART(?:ICOLO)?\.\s*\d+', re.I),
 'art_htmlish': re.compile(r'(?m)^Art(?:icolo)?\s*\d+\s*[-–.]', re.I),
}
# sample a long law
for name in ['it-2026-01-08-26g00007.json','it-2003-05-30-003g0142.json','it-1995-05-17-095g0222.json','it-2002-05-04-002g0112.json']:
    p=inst/name
    if not p.exists():
        continue
    d=json.loads(p.read_text())
    text=d.get('text') or ''
    print('\n====', name, 'len', len(text), 'docs', len(d.get('documents') or []))
    for k,pat in pats.items():
        ms=list(pat.finditer(text))
        print(k, len(ms), 'first3', [m.group(0).replace('\n','\\n') for m in ms[:3]])
    # show lines that look like article heads
    lines=[ln for ln in text.splitlines() if re.match(r'(?i)^\s*art', ln)][:15]
    print('art-ish lines:', lines)

# aggregate potential split counts across corpus (sample 1500 ok texts)
c=Counter(); potential=0; already=0
pat=re.compile(r'(?m)^(?:Art\.|Articolo|ART\.)\s*\d+', re.I)
for i,p in enumerate(inst.glob('*.json')):
    d=json.loads(p.read_text())
    text=str(d.get('text') or '')
    if len(text)<200: continue
    n=len(pat.findall(text))
    docs=len(d.get('documents') or [])
    if docs: already+=1
    elif n>=2:
        potential+=1
        c['heads_'+str(min(n,20))]+=1
    elif n==1:
        c['single_head']+=1
    else:
        c['no_head']+=1
    if i>3000 and potential>200: break
print('potential multi-head laws (partial scan)', potential, 'already_docs', already, c)
