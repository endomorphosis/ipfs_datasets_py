#!/usr/bin/env python3
"""Read-only: compare raw/ (manifest, xml, stop) against index/scan chunk rows for ids >= 725000 (scanned range 767599..725000)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, gzip, json, re, sys, collections
B = '{_CORPORA}/nl_municipal'; SCAN = f'{B}/index/scan'
LO = int(sys.argv[1]) if len(sys.argv) > 1 else 725000; HI = 767599
rows = []
for fn in sorted(os.listdir(SCAN)):
    if not fn.endswith('.jsonl.gz') or fn.startswith('tail_'): continue
    hi = int(fn.split('.')[0])
    if hi < LO or hi > HI: continue
    with gzip.open(f'{SCAN}/{fn}', 'rt') as f: rows += [json.loads(l) for l in f]
st = collections.Counter(r['s'] for r in rows)
def ids(d, pat):
    out = set()
    for e in os.scandir(f'{B}/raw/{d}'):
        m = re.match(pat, e.name)
        if m: out.add(m.groups())
    return out
man = {int(a[0]) for a in ids('manifest', r'CVDR(\d+)\.xml\.gz$')}
xml = {(int(a), b) for a, b in ids('xml', r'CVDR(\d+)_([^.]+)\.xml\.gz$')}
stop = {(int(a), b) for a, b in ids('stop', r'CVDR(\d+)_([^.]+)\.xml\.gz$')}
inr = lambda i: LO <= i <= HI
hits = [r for r in rows if r['s'] not in ('absent',) and not r['s'].startswith('fetch_fail_manifest') and not r['s'].startswith('manifest_http')]
ok = [r for r in rows if r['s'] == 'ok']; stp = [r for r in rows if r['s'] == 'stop_lvbb_xml_unsupported']
miss_man = sorted(r['id'] for r in hits if r['id'] not in man)
miss_xml = sorted(r['id'] for r in ok if (r['id'], str(r.get('expr'))) not in xml)
miss_stop = sorted(r['id'] for r in stp if (r['id'], str(r.get('expr'))) not in stop)
okset = {(r['id'], str(r.get('expr'))) for r in ok}
xml_in = {x for x in xml if inr(x[0])}
extra_xml = sorted(x for x in xml_in if x not in okset)
hitset = {r['id'] for r in hits}
extra_man = sorted(i for i in man if inr(i) and i not in hitset)
res = dict(range=f'{HI}..{LO}', scan_rows=len(rows), unique_ids=len({r['id'] for r in rows}), status=dict(st),
           raw_counts_total=dict(manifest=len(man), xml=len(xml), stop=len(stop)),
           raw_counts_in_range=dict(manifest=sum(1 for i in man if inr(i)), xml=len(xml_in), stop=sum(1 for x in stop if inr(x[0]))),
           expected=dict(manifest_hits=len(hits), ok_xml=len(ok), stop=len(stp)),
           missing=dict(manifest=len(miss_man), ok_xml=len(miss_xml), stop=len(miss_stop)),
           missing_ids=dict(manifest=miss_man[:200], ok_xml=miss_xml[:200], stop=miss_stop[:200]),
           extra_in_range=dict(xml_not_ok_chosen=len(extra_xml), xml_examples=extra_xml[:20], manifest_not_hit=len(extra_man), manifest_examples=extra_man[:20]))
print(json.dumps(res, indent=1))
