# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, pathlib, re
p = pathlib.Path(str(_CORPORA) + '/fj/instruments/fj--filename-2013-20constitution-20of-20fiji-20-english-.pdf.json')
rec = json.loads(p.read_text())
t = rec['text']
print('len', len(t), 'docs', len(rec.get('documents') or []))
shown=0
for i,line in enumerate(t.splitlines()):
    s=line.strip()
    if re.match(r'(Chapter|CHAPTER|Part|PART|Article|ARTICLE|Section|SECTION)\b', s):
        print(i, repr(s[:120])); shown+=1
        if shown>=40: break
print('Article line', len(re.findall(r'(?m)^\s*Article\s+\d+', t)))
print('CHAPTER', len(re.findall(r'(?m)^\s*CHAPTER\s+', t, re.I)))
print('sample', [repr(t[m.start():m.start()+80].replace('\n',' ')) for m in list(re.finditer(r'Article\s+\d+', t))[:8]])
