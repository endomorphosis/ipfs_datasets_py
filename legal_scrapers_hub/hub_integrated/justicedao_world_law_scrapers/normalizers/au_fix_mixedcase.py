#!/usr/bin/env python3
"""Follow-up for AU subnational pack: fetch the 12 in-force QLD/TAS items whose mixed-case ids (act-1994-84A, SL-1879-qcipa)
were dropped by the old lowercase-only id filter, parse them with the same au_build code, append them to the staging parquets
(append-only), and re-run never-thin + article_count checks. Phases: fetch | build | append | check. ONE process; memguard 3584MB."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, json, re, gzip, time, threading, shutil, collections
sys.path.insert(0, '/workspace/scripts')
BASE = '{_CORPORA}/au_subnational'
STAGE = '{_CORPORA}/hf-staging/ipfs_australia_laws_subnational_20260928T015251'
BACKUP = '{_CORPORA}/hf-staging/backup_pre_fix12_20260930'
SNAP = '/workspace/country-laws-ir/cache/hf/hub/datasets--endomorphosis--ipfs_australia_laws/snapshots/c72ad1989fc8d4f4858ea8e2944c77f08406a6dd'
TMPB = f'{BASE}/fix12_tmp'
GAPS = '/workspace/country-law-triage/australia_subnational_gap_list.json'
RES = f'{BASE}/fix12_result.json'
JURS = ['QLD', 'TAS']
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
def _mg():
    while True:
        m = memavail()
        if m <= 3584: log(f'MEMGUARD TERM MemAvailable={m}MB'); os._exit(3)
        time.sleep(10)
threading.Thread(target=_mg, daemon=True).start()
def res_load(): return json.load(open(RES)) if os.path.exists(RES) else {}
def res_save(d): json.dump(d, open(RES + '.tmp', 'w'), indent=1, ensure_ascii=False); os.replace(RES + '.tmp', RES)
def gap12():
    g = json.load(open(GAPS))['gaps']
    return {(x['jurisdiction'][3:], x['src_id']) for x in g if 'lowercase-only id filter' in x['reason']}

def fetch():
    import au_collect as C
    C.STATE = f'{BASE}/collector_state_fix12.json'   # never touch the original collector_state.json
    C.state.update(status='running', jur={}, blocked={})
    want = gap12(); assert len(want) == 12, want
    out = {}
    for st in JURS:
        listed = {json.loads(l)['src_id'] for l in open(f'{BASE}/index/{st}_list.jsonl')}
        items = [it for it in C.list_pco(st) if it['src_id'] not in listed]   # list_pco regex is ^[A-Za-z]+-\d{4}-[0-9A-Za-z]+$
        ids = {(st, it['src_id']) for it in items}
        assert ids == {w for w in want if w[0] == st}, (st, ids)
        with open(f'{BASE}/index/{st}_fix12_fetch.jsonl', 'w') as rf:
            for it in items:
                try: s = C.fetch_one(st, it)
                except C.Blocked as b: log(st, 'BLOCKED', b); s = 'blocked'
                it['fetch_status'] = s; it['fetched_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
                rf.write(json.dumps(it) + '\n'); rf.flush()
                log(st, it['src_id'], s, it.get('final_url'), f'mem={memavail()}MB')
                out[f'{st}:{it["src_id"]}'] = s
                if s == 'blocked': break
    C.state['status'] = 'finished'; C.save_state()
    r = res_load(); r['fetch'] = out; res_save(r); log('FETCH DONE', out)

def build():
    import au_build as B
    if os.path.exists(TMPB): shutil.rmtree(TMPB)
    os.makedirs(f'{TMPB}/index'); os.makedirs(f'{TMPB}/parsed'); os.symlink(f'{BASE}/raw', f'{TMPB}/raw')
    for st in JURS: shutil.copy(f'{BASE}/index/{st}_fix12_fetch.jsonl', f'{TMPB}/index/{st}_fetch.jsonl')
    B.BASE = TMPB; B.OUT = f'{TMPB}/parsed'
    built = {}
    for st in JURS:
        B.build(st)
        for kind in ('laws', 'articles'):
            src = f'{TMPB}/parsed/{st}_{kind}.jsonl.gz'; dst = f'{BASE}/parsed/{st}_fix12_{kind}.jsonl.gz'
            with gzip.open(src, 'rt') as f, gzip.open(dst, 'wt') as g:
                for l in f:
                    row = json.loads(l)
                    if kind == 'laws': row['json_path'] = row['json_path'].replace(TMPB, BASE)  # same path form as the other rows
                    g.write(json.dumps(row, ensure_ascii=False) + '\n')
        shutil.copy(f'{TMPB}/parsed/{st}_stats.json', f'{BASE}/parsed/{st}_fix12_stats.json')
        built[st] = json.load(open(f'{BASE}/parsed/{st}_fix12_stats.json'))
    r = res_load(); r['build'] = built; res_save(r); log('BUILD DONE', json.dumps({k: v['stats'] for k, v in built.items()}))

def append():
    import pyarrow as pa, pyarrow.parquet as pq
    r = res_load(); added = {}
    for kind in ('laws', 'articles'):
        cur = f'{STAGE}/data/{kind}.parquet'; bk = f'{BACKUP}/{kind}.parquet'
        if not os.path.exists(bk): shutil.copy2(cur, bk)          # pre-fix12 staged file (36,202 / 680,057 rows)
        pf = pq.ParquetFile(bk); schema = pf.schema_arrow
        ids = set()
        for b in pf.iter_batches(batch_size=50000, columns=['id']): ids.update(b.column('id').to_pylist())
        rows = []; coll = []
        for st in JURS:
            n = 0
            for l in gzip.open(f'{BASE}/parsed/{st}_fix12_{kind}.jsonl.gz', 'rt'):
                x = json.loads(l)
                if x['id'] in ids: coll.append(x['id']); continue
                ids.add(x['id']); rows.append(x); n += 1
            added.setdefault(kind, {})[st] = n
        tmp = f'{STAGE}/data/.{kind}.parquet.tmp'
        w = pq.ParquetWriter(tmp, schema, compression='zstd')
        for i in range(pf.metadata.num_row_groups): w.write_table(pf.read_row_group(i))
        if rows: w.write_table(pa.Table.from_pylist(rows, schema=schema), row_group_size=2000)
        w.close(); os.replace(tmp, cur)
        added[kind + '_collisions_skipped'] = coll
        log('APPEND', kind, 'old', pf.metadata.num_rows, 'added', len(rows), 'new', pq.ParquetFile(cur).metadata.num_rows, 'collisions', len(coll))
    r['append'] = added; res_save(r)

def compare_prefix(old_path, new_path):
    import pyarrow.parquet as pq
    old = pq.ParquetFile(old_path); new = pq.ParquetFile(new_path)
    it = new.iter_batches(batch_size=1000); buf = None; mism = 0; rows = 0; ids = set()
    for ob in old.iter_batches(batch_size=1000):
        need = ob.num_rows; parts = []
        while need > 0:
            if buf is None or buf.num_rows == 0: buf = next(it)
            t = min(need, buf.num_rows); parts.append(buf.slice(0, t)); buf = buf.slice(t); need -= t
        for col in ob.schema.names:
            a = ob.column(col).to_pylist(); b = [x for p in parts for x in p.column(col).to_pylist()]
            mism += sum(1 for x, y in zip(a, b) if x != y)
        ids.update(ob.column('id').to_pylist()); rows += ob.num_rows
    allnew = set()
    for nb in new.iter_batches(batch_size=20000, columns=['id']): allnew.update(nb.column('id').to_pylist())
    return {'old_rows': old.metadata.num_rows, 'new_rows': new.metadata.num_rows, 'old_rows_compared': rows,
            'old_row_field_mismatches': mism, 'old_ids_missing': len(ids - allnew), 'unique_ids_before': len(ids),
            'unique_ids_after': len(allnew), 'schema_equal': old.schema_arrow.equals(new.schema_arrow)}

def ac_check(laws_path, arts_path):
    import pyarrow.parquet as pq
    ac = {}; jl = collections.Counter(); ja = collections.Counter(); law_j = {}
    for b in pq.ParquetFile(laws_path).iter_batches(batch_size=20000, columns=['id', 'jurisdiction', 'article_count']):
        for i, j, c in zip(*(b.column(k).to_pylist() for k in ('id', 'jurisdiction', 'article_count'))):
            jl[j] += 1; law_j[i] = j
            if j != 'AU': ac[i] = c
    real = collections.Counter(); orphan = 0
    for b in pq.ParquetFile(arts_path).iter_batches(batch_size=50000, columns=['law_id']):
        for lid in b.column('law_id').to_pylist():
            j = law_j.get(lid)
            if j is None:
                j = 'ORPHAN'
                if re.match(r'^au-(nsw|qld|tas|wa|nt)-', lid or ''): orphan += 1
            ja[j] += 1
            if j not in ('AU', 'ORPHAN'): real[lid] += 1
    mm = [i for i, c in ac.items() if real.get(i, 0) != c]
    return dict(new_laws_checked=len(ac), mismatches=len(mm), mismatch_sample=mm[:10], orphan_article_rows_nonAU_scope=orphan,
                laws_by_jurisdiction=dict(jl), articles_by_jurisdiction=dict(ja))

def check(stage_dir=None, tag='check'):
    stage_dir = stage_dir or STAGE
    r = res_load(); c = {}
    for kind in ('laws', 'articles'):
        c[kind + '_vs_tip_c72ad1989fc8'] = compare_prefix(f'{SNAP}/data/{kind}.parquet', f'{stage_dir}/data/{kind}.parquet'); log(kind, 'vs tip', c[kind + '_vs_tip_c72ad1989fc8'])
        if os.path.exists(f'{BACKUP}/{kind}.parquet'):
            c[kind + '_vs_prefix12_staged'] = compare_prefix(f'{BACKUP}/{kind}.parquet', f'{stage_dir}/data/{kind}.parquet'); log(kind, 'vs pre-fix12 staged', c[kind + '_vs_prefix12_staged'])
    c['article_count_check'] = ac_check(f'{stage_dir}/data/laws.parquet', f'{stage_dir}/data/articles.parquet'); log('ac', c['article_count_check'])
    tipfiles = {str(p.relative_to(SNAP)) for p in __import__('pathlib').Path(SNAP).rglob('*') if p.is_file()}
    stfiles = {str(p.relative_to(stage_dir)) for p in __import__('pathlib').Path(stage_dir).rglob('*') if p.is_file()}
    c['files_removed_vs_tip'] = sorted(tipfiles - stfiles); c['files_added_vs_tip'] = sorted(stfiles - tipfiles)
    ok = lambda d: d['old_row_field_mismatches'] == 0 and d['old_ids_missing'] == 0 and d['schema_equal'] and d['old_rows_compared'] == d['old_rows'] and d['new_rows'] >= d['old_rows'] and d['unique_ids_after'] == d['new_rows'] - (d['old_rows'] - d['unique_ids_before'])
    c['PASS'] = bool(all(ok(v) for k, v in c.items() if k.endswith(('_vs_tip_c72ad1989fc8', '_vs_prefix12_staged'))) and not c['files_removed_vs_tip']
                     and c['article_count_check']['mismatches'] == 0 and c['article_count_check']['orphan_article_rows_nonAU_scope'] == 0)
    r[tag] = c; res_save(r); log(tag.upper(), 'PASS' if c['PASS'] else 'FAIL')

if __name__ == '__main__':
    log('START', sys.argv[1:], 'pid', os.getpid(), 'mem', memavail())
    ph = sys.argv[1]
    if ph == 'check' and len(sys.argv) > 2: check(sys.argv[2], sys.argv[3])
    else: {'fetch': fetch, 'build': build, 'append': append, 'check': check}[ph]()
    log('END', ph)
