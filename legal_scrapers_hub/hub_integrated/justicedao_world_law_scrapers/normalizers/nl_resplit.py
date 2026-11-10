#!/usr/bin/env python3
"""Re-split all cached KOOP toestand XML (raw/*.xml.gz) with nl_split v2 (gap fill) -> out/articles_v2/<id>.jsonl.gz.
No network. MemAvail guard 3584MB. Progress every 1000."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, json, gzip, time
sys.path.insert(0, '/workspace/scripts'); import nl_split
from nl_collect import RAW, B, version_of, memavail
O = B / 'out' / 'articles_v2'; O.mkdir(parents=True, exist_ok=True)
ids = sorted(p.name[:-7] for p in RAW.glob('*.xml.gz')); t0 = time.time()
with open(B / 'index' / 'split_summary_v2.jsonl', 'w') as summ:
    for n, lid in enumerate(ids, 1):
        m = memavail()
        if m <= 3584: print(f'MEMGUARD TERM MemAvailable={m}MB', flush=True); sys.exit(3)
        meta = json.load(open(RAW / f'{lid}.meta.json')); url = meta['url']
        try:
            rows, st = nl_split.split_xml(gzip.decompress((RAW / f'{lid}.xml.gz').read_bytes()), lid, url, version_of(url))
        except Exception as e:
            summ.write(json.dumps(dict(law_id=lid, status='parse_fail', error=repr(e)[:300])) + '\n'); continue
        tmp = O / f'{lid}.tmp'
        with gzip.open(tmp, 'wt', encoding='utf-8') as f:
            for r in rows: f.write(json.dumps(r, ensure_ascii=False) + '\n')
        os.replace(tmp, O / f'{lid}.jsonl.gz')
        summ.write(json.dumps(dict(law_id=lid, status='ok', version=version_of(url), version_note=meta.get('version_note'), rows=len(rows), **st)) + '\n')
        if n % 1000 == 0: print(time.strftime('%H:%M:%S'), 'resplit', n, '/', len(ids), f'{time.time()-t0:.0f}s', f'mem={memavail()}MB', flush=True)
print('DONE', len(ids), f'{time.time()-t0:.0f}s', flush=True)
