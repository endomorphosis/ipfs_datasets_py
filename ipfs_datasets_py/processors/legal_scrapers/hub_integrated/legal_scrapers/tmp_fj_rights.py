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
t = json.loads(p.read_text())['text']
for pat in [r'(?m)^\s*(\d+)\.—', r'(?m)^\s*(\d+)\.\s+[A-Z]', r'(?m)^\s*Section\s+(\d+)']:
    ms=list(re.finditer(pat, t))
    print(pat, 'count', len(ms))
    for m in ms[:5]:
        print(' ', repr(t[m.start():m.start()+80].replace('\n',' | ')))
idx=t.find('CHAPTER 2')
print('idx', idx)
if idx>=0:
    print(t[idx:idx+1800])
