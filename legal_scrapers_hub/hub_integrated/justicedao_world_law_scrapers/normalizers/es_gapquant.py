#!/usr/bin/env python3
"""Offline estimate of autonomic laws WITHOUT a BOE consolidated version: per CCAA and year, Ley / Ley Foral numbers are sequential
(N/YYYY), so missing numbers in 1..max(N) among BOE-consolidated laws approximate non-consolidated laws (lower bound: laws after the
last consolidated number in a year, and years with no consolidated law at all, are not counted)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, re, collections
from pathlib import Path
B = Path('{_CORPORA}/es_subnational')
DEP = {'8010': 'ES-AN', '8020': 'ES-AR', '8150': 'ES-AS', '8121': 'ES-IB', '8120': 'ES-IB', '8030': 'ES-CN', '8040': 'ES-CB', '9531': 'ES-CL', '8060': 'ES-CM', '8070': 'ES-CT',
       '8080': 'ES-EX', '8090': 'ES-GA', '8131': 'ES-MD', '8100': 'ES-MC', '8170': 'ES-NC', '8140': 'ES-PV', '8110': 'ES-RI', '8162': 'ES-VC', '8161': 'ES-VC'}
cat = json.load(open(B / 'catalog_autonomico.json'))['data']
nums = collections.defaultdict(set); unparsed = 0
for x in cat:
    if x['rango']['texto'] not in ('Ley', 'Ley Foral'): continue
    m = re.search(r'(\d+)\s*/\s*(\d{4})', x.get('numero_oficial') or '') or re.search(r'\b(\d+)/(\d{4})\b', x['titulo'])
    if not m: unparsed += 1; continue
    nums[(DEP[x['departamento']['codigo']], int(m.group(2)))].add(int(m.group(1)))
per = collections.defaultdict(lambda: dict(consolidated_laws=0, est_missing_in_sequence=0, max_numbers_sum=0, years=0))
for (j, y), s in nums.items():
    p = per[j]; p['consolidated_laws'] += len(s); p['max_numbers_sum'] += max(s); p['est_missing_in_sequence'] += max(s) - len(s); p['years'] += 1
tot_c = sum(p['consolidated_laws'] for p in per.values()); tot_m = sum(p['est_missing_in_sequence'] for p in per.values())
out = dict(method=__doc__.strip(), per_jurisdiction={k: dict(v, est_coverage_pct=round(100 * v['consolidated_laws'] / max(1, v['max_numbers_sum']), 1)) for k, v in sorted(per.items())},
           totals=dict(consolidated_numbered_laws=tot_c, est_missing_in_sequence=tot_m, est_coverage_pct=round(100 * tot_c / max(1, tot_c + tot_m), 1)), unparsed_numbers=unparsed,
           desactualizado=sum(1 for x in cat if x['estado_consolidacion']['texto'] == 'Desactualizado'))
out['summary'] = (f"by Ley/Ley Foral numbering, BOE consolidates ~{out['totals']['est_coverage_pct']}% of numbered regional laws in the years it covers "
                  f"(~{tot_m:,} numbered laws missing from sequences; lower-bound estimate)")
json.dump(out, open(B / 'gap_quant.json', 'w'), indent=1, ensure_ascii=False); print(json.dumps(out['totals']), out['summary'])
for k, v in out['per_jurisdiction'].items(): print(k, v)
