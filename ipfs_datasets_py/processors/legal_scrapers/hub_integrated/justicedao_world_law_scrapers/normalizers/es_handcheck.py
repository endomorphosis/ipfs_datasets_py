#!/usr/bin/env python3
"""20-law hand check. Usage: es_handcheck.py pre  (parsed/handcheck jsonl)  |  es_handcheck.py staged STAGE_DIR IDS_FILE"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, json, gzip, re, collections
from pathlib import Path
import pyarrow.parquet as pq
B = Path('{_CORPORA}/es_subnational')
NUM = re.compile(r'^Art[íi]culo\s+(\d+)(?:\s*(bis|ter|quater|quinquies|sexies|septies))?\b', re.I)
def load(mode):
    cat = {x['identificador']: x for x in json.load(open(B / 'catalog_autonomico.json'))['data']}
    if mode == 'pre':
        laws = [json.loads(l) for l in gzip.open(B / 'parsed/laws_handcheck.jsonl.gz', 'rt')]
        arts = collections.defaultdict(list)
        for l in gzip.open(B / 'parsed/articles_handcheck.jsonl.gz', 'rt'): a = json.loads(l); arts[a['law_id']].append(a)
        return cat, laws, arts, B / 'handcheck_20_pre.json'
    st = Path(sys.argv[2]); want = open(sys.argv[3]).read().strip().split(',')
    t = pq.read_table(st / 'data/laws.parquet', filters=[('official_identifier', 'in', want), ('jurisdiction', '!=', 'ES')])
    laws = t.to_pylist(); lids = [l['id'] for l in laws]
    a = pq.read_table(st / 'data/articles.parquet', filters=[('law_id', 'in', lids)]).to_pylist()
    arts = collections.defaultdict(list); [arts[x['law_id']].append(x) for x in a]
    return cat, laws, arts, B / 'handcheck_20_staged.json'
def check(L, A, c):
    md = json.loads(L['metadata_json'])['metadata']; ident = L['official_identifier']
    nums = []; unico = 0; prec = 0; vers_multi = 0; vers_ok = 0
    for a in A:
        m = json.loads(a['metadata_json'])['metadata']
        if m['block_type'] == 'precepto':
            prec += 1; mm = NUM.match(a['title'] or '')
            if mm: nums.append(int(mm.group(1)))
            elif re.match(r'^Art[íi]culo\s+[úu]nico', a['title'] or '', re.I): unico += 1
        if m['n_versions_in_block'] > 1:
            vers_multi += 1; fv = (m['fecha_vigencia'] or m['fecha_publicacion'] or '').replace('-', '')
            vers_ok += fv <= '20261002'
    ints = sorted(set(nums)); gaps = [i for i in range(1, (max(ints) if ints else 0) + 1) if i not in set(ints)]
    regress = sum(1 for x, y in zip(nums, nums[1:]) if y < x)
    no = (c.get('numero_oficial') or '').strip()
    r = dict(id=L['id'], jurisdiction=L['jurisdiction'], title=L['title'][:140], title_matches_catalog=L['title'] == c['titulo'],
             numero_oficial=no or None, number_in_title=(not no) or no.split('/')[0] in L['title'],
             rango=md['rango'], law_status=L['law_status'], estado_consolidacion=md['estado_consolidacion'], fecha_actualizacion=md['fecha_actualizacion'],
             eli=L['eli'], source_url=L['source_url'], article_count=L['article_count'], article_rows=len(A), article_count_ok=L['article_count'] == len(A),
             precepto_blocks=prec, numbered_articles=len(nums), articulo_unico=unico, max_article=max(ints) if ints else None, article_number_gaps=gaps[:20], n_gaps=len(gaps),
             numbering_regressions=regress, multi_version_blocks=vers_multi, current_version_in_force=vers_ok == vers_multi,
             text_chars=len(L['text']), empty_article_texts=sum(1 for a in A if not a['text']),
             sample_article=next((a['text'][:240] for a in A if NUM.match(a['title'] or '')), None))
    r['PASS'] = bool(r['title_matches_catalog'] and r['number_in_title'] and r['article_count_ok'] and r['current_version_in_force'] and r['text_chars'] > 400
                     and (r['numbered_articles'] > 0 or r['articulo_unico'] > 0 or r['rango'] not in ('Ley', 'Ley Foral')) and r['numbering_regressions'] <= 3)
    return r
def main():
    cat, laws, arts, out = load(sys.argv[1])
    res = [check(L, arts[L['id']], cat[L['official_identifier']]) for L in laws]
    s = dict(n=len(res), passed=sum(r['PASS'] for r in res), jurisdictions=sorted({r['jurisdiction'] for r in res}), results=res)
    json.dump(s, open(out, 'w'), indent=1, ensure_ascii=False)
    for r in res: print(r['PASS'], r['jurisdiction'], r['id'], r['rango'], r['law_status'], 'arts', r['article_rows'], 'num', r['numbered_articles'], 'max', r['max_article'], 'gaps', r['n_gaps'], 'regr', r['numbering_regressions'], 'mv', r['multi_version_blocks'], r['title'][:60])
    print('PASSED', s['passed'], '/', s['n'])
if __name__ == '__main__': main()
