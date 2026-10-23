# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, json, gzip, re, os
sys.path.insert(0, '/workspace/scripts')
import au_parse as P
BASE = '{_CORPORA}/au_subnational'
def raw(st, sid):
    for ext in ('html', 'txt'):
        p = f'{BASE}/raw/{st}/{re.sub(r"[^A-Za-z0-9._-]", "_", sid)}.{ext}.gz'
        if os.path.exists(p): return ext, gzip.open(p).read()
    return None, None
def parse(st, ext, b):
    if ext == 'txt': return P.parse_nt_text(b.decode('utf-8', 'replace'))
    if st in ('NSW', 'QLD'): return P.parse_pco(b)
    if st == 'TAS': return P.parse_pco(b, tas=True)
    if st == 'WA': return P.parse_wa(b)
res = []
for st in ['NSW', 'QLD', 'TAS', 'WA', 'NT']:
    for l in open(f'{BASE}/index/{st}_fetch_sample.jsonl'):
        it = json.loads(l); ext, b = raw(st, it['src_id'])
        if b is None: res.append(dict(st=st, id=it['src_id'], ok=False, why=it.get('fetch_status'))); continue
        t, u = parse(st, ext, b)
        nc = P.numbering_check(u)
        # in-force/version evidence
        s = b.decode('utf-8', 'replace')
        ev = None
        for pat in [r'(?i)(in force (?:from|at|on)[^<\n]{0,40})', r'(?i)(current version for[^<\n]{0,60})', r'(?i)(as at [0-9][^<\n]{0,30})', r'(?i)(Compiled[^<\n]{0,60})', r'(?i)(Version:[^<\n]{0,40})', r'(?i)(Republication[^<\n]{0,40})', r'(?i)(As in force at[^<\n]{0,30})']:
            m = re.search(pat, s)
            if m: ev = re.sub(r'\s+', ' ', m.group(1)).strip(); break
        r = dict(st=st, id=it['src_id'], list_title=it.get('title'), parsed_title=t, number=it.get('no') or it.get('number'), year=it.get('year'),
                 in_force_evidence=ev, sections=nc['n_sections'], schedules=nc['n_schedules'], first=nc['first'], last=nc['last'],
                 nonmono=nc['nonmonotonic'], dups=nc['duplicates'], first_text=(u[0]['text'][:90] if u else None))
        r['ok'] = bool(u) and nc['nonmonotonic'] <= max(1, nc['n_sections'] // 20)
        res.append(r)
for r in res: print(json.dumps(r, ensure_ascii=False))
json.dump(res, open(f'{BASE}/handcheck_20.json', 'w'), indent=1, ensure_ascii=False)
print('OK', sum(r['ok'] for r in res), '/', len(res))
