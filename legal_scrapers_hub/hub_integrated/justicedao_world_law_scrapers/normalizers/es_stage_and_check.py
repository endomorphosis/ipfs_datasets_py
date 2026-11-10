#!/usr/bin/env python3
"""Stage ipfs_spain_laws + ES-<CCAA> append (NO upload) and never-thin pre-check vs hub tip. Streamed.
Offline except one Hub metadata call (tip / LFS sha check)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gzip, hashlib, json, os, shutil, sys, time, collections
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq
from huggingface_hub import HfApi
REPO = 'endomorphosis/ipfs_spain_laws'; TIP = '98f411da9ac98fe9a28ceac10641dd5295ed436c'
B = Path('{_CORPORA}/es_subnational'); SNAP = B / 'es_tip'; PARSED = B / 'parsed'
TS = time.strftime('%Y%m%dT%H%M%S'); STAGE = Path(f'{_CORPORA}/hf-staging/ipfs_spain_laws_subnational_{TS}')
ORDER = ['ES-AN', 'ES-AR', 'ES-AS', 'ES-IB', 'ES-CN', 'ES-CB', 'ES-CL', 'ES-CM', 'ES-CT', 'ES-EX', 'ES-GA', 'ES-MD', 'ES-MC', 'ES-NC', 'ES-PV', 'ES-RI', 'ES-VC', 'ES-CE', 'ES-ML']
NOTICE = ('Texto consolidado de carácter meramente informativo, sin valor oficial. Únicamente tienen carácter oficial y auténtico los textos publicados en '
          'el Boletín Oficial del Estado.')
PIN = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def _avail():
    for ln in open('/proc/meminfo'):
        if ln.startswith('MemAvailable'): return int(ln.split()[1]) // 1024
def set_pin(**upd):
    kv = dict(l.rstrip('\n').split('=', 1) for l in open(PIN) if '=' in l); kv.update({k: str(v) for k, v in upd.items()})
    open(PIN + '.tmp', 'w').write(''.join(f'{k}={v}\n' for k, v in kv.items())); os.replace(PIN + '.tmp', PIN)
def mem_ok():
    m = _avail()
    while m < 4600:
        if m <= 3584:
            print(f'MEMGUARD TERM MemAvailable={m}MB', flush=True)
            set_pin(mode='HOLD_0_ES_MEMSHED', collectors=0, phase=f'ES stage self-TERM at MemAvail={m}MB; not restarted', ts=time.strftime('%Y-%m-%dT%H:%MPT'), MemAvail_MB=m)
            os._exit(3)
        print(f'MEM PAUSE MemAvailable={m}MB; sleeping 20s', flush=True); time.sleep(20); m = _avail()
def jsonl(p):
    with gzip.open(p, 'rt') as f:
        for ln in f: yield json.loads(ln)
def ordered_law_ids():
    laws = [(r['jurisdiction'], r['date_issued'] or '', r['official_identifier'], r['id']) for r in jsonl(PARSED / 'laws_all.jsonl.gz')]
    laws.sort(key=lambda x: (ORDER.index(x[0]), x[1], x[2])); return [x[3] for x in laws]
def merge(old_path, new_path, kind, old_ids, order):
    pf = pq.ParquetFile(old_path); schema = pf.schema_arrow
    w = pq.ParquetWriter(new_path, schema, compression='zstd')
    for i in range(pf.metadata.num_row_groups): w.write_table(pf.read_row_group(i)); mem_ok()
    rank = {lid: n for n, lid in enumerate(order)}; key = 'id' if kind == 'laws' else 'law_id'
    # bucket by law rank so append order is deterministic (jurisdiction, date_issued, BOE id); spill to per-1000-rank temp files to stay lean
    tmpd = new_path.parent / f'.tmp_{kind}'; tmpd.mkdir(exist_ok=True); fh = {}
    for r in jsonl(PARSED / f'{kind}_all.jsonl.gz'):
        k = rank[r[key]] // 200
        if k not in fh: fh[k] = gzip.open(tmpd / f'{k:05d}.jsonl.gz', 'wt')
        fh[k].write(json.dumps(r, ensure_ascii=False) + '\n')
    for f in fh.values(): f.close()
    added = collections.Counter(); coll = 0; new_ids = set(); buf = []
    def flush():
        if buf: w.write_table(pa.Table.from_pylist(buf, schema=schema), row_group_size=2000); buf.clear(); mem_ok()
    for k in sorted(fh):
        rows = list(jsonl(tmpd / f'{k:05d}.jsonl.gz')); rows.sort(key=lambda r: rank[r[key]])   # stable: keeps block order within a law
        for r in rows:
            r = {c: r.get(c) for c in schema.names}
            if r['id'] in old_ids or r['id'] in new_ids: coll += 1; continue
            new_ids.add(r['id']); buf.append(r); added[r['law_id'][:5] if kind == 'articles' else r['jurisdiction']] += 1
            if len(buf) >= (300 if kind == 'laws' else 5000): flush()
    flush(); w.close(); shutil.rmtree(tmpd)
    return dict(added), coll
def compare_prefix(old_path, new_path):
    old = pq.ParquetFile(old_path); new = pq.ParquetFile(new_path)
    it = new.iter_batches(batch_size=1000); buf = None; mism = 0; rows = 0; ids = set(); mc = collections.Counter()
    for ob in old.iter_batches(batch_size=1000):
        need = ob.num_rows; parts = []
        while need > 0:
            if buf is None or buf.num_rows == 0: buf = next(it)
            t = min(need, buf.num_rows); parts.append(buf.slice(0, t)); buf = buf.slice(t); need -= t
        for col in ob.schema.names:
            a = ob.column(col).to_pylist(); b = [x for p in parts for x in p.column(col).to_pylist()]
            m = sum(1 for x, y in zip(a, b) if x != y); mism += m
            if m: mc[col] += m
        ids.update(ob.column('id').to_pylist()); rows += ob.num_rows; mem_ok()
    allnew = set()
    for nb in new.iter_batches(batch_size=20000, columns=['id']): allnew.update(nb.column('id').to_pylist())
    return {'old_rows': old.metadata.num_rows, 'new_rows': new.metadata.num_rows, 'old_rows_compared': rows, 'old_row_field_mismatches': mism, 'mismatch_columns': dict(mc),
            'old_ids_missing': len(ids - allnew), 'unique_ids_before': len(ids), 'unique_ids_after': len(allnew),
            'duplicate_ids_before': old.metadata.num_rows - len(ids), 'duplicate_ids_after': new.metadata.num_rows - len(allnew),
            'new_duplicate_ids': (new.metadata.num_rows - len(allnew)) - (old.metadata.num_rows - len(ids)), 'schema_equal': old.schema_arrow.equals(new.schema_arrow)}
def post_checks(stage):
    jur = {}; ac = {}; st = {}; rk = {}; zero = collections.Counter(); short = collections.Counter(); shortb = collections.Counter()
    for b in pq.ParquetFile(stage / 'data/laws.parquet').iter_batches(batch_size=500, columns=['id', 'jurisdiction', 'article_count', 'metadata_json', 'text', 'law_status']):
        for i, j, c, m, t, s in zip(*[b.column(k).to_pylist() for k in ['id', 'jurisdiction', 'article_count', 'metadata_json', 'text', 'law_status']]):
            jur[i] = j; ac[i] = c; st[i] = s; rk[i] = json.loads(m)['metadata'].get('rango')
            if c == 0: zero[j] += 1
            if len(t or '') < 200: short[j] += 1
            if len((t or '').replace(NOTICE, '').strip()) < 200: shortb[j] += 1
        mem_ok()
    rows = collections.Counter(); orphan = 0; empty = collections.Counter()
    for b in pq.ParquetFile(stage / 'data/articles.parquet').iter_batches(batch_size=50000, columns=['law_id', 'text']):
        for lid, t in zip(b.column('law_id').to_pylist(), b.column('text').to_pylist()):
            if lid not in jur: orphan += 1
            rows[lid] += 1
            if not t: empty[jur.get(lid)] += 1
    mism = [i for i in ac if ac[i] != rows.get(i, 0)]
    per = collections.defaultdict(collections.Counter); rango = collections.defaultdict(collections.Counter)
    for i, j in jur.items():
        per[j]['laws'] += 1; per[j]['articles'] += rows.get(i, 0); per[j][f'{st[i]}_laws'] += 1; rango[j][rk[i]] += 1
    for j in per:
        per[j]['zero_article_laws'] = zero[j]; per[j]['text_under_200_chars'] = short[j]; per[j]['body_under_200_chars_excl_notice'] = shortb[j]; per[j]['empty_article_texts'] = empty[j]
    return {'article_count_mismatch_laws': len(mism), 'article_count_mismatch_sample': mism[:10], 'orphan_articles': orphan,
            'per_jurisdiction': {j: dict(v) for j, v in sorted(per.items())}, 'rango_per_jurisdiction': {j: dict(v) for j, v in sorted(rango.items())}}
def main():
    mem_ok()
    api = HfApi(token=os.environ.get('HF_TOKEN')); info = api.dataset_info(REPO, files_metadata=True)
    live_files = {s.rfilename: s for s in info.siblings}
    if info.sha != TIP: print('ABORT tip moved', info.sha); sys.exit(2)
    shutil.copytree(SNAP, STAGE, symlinks=False, ignore=shutil.ignore_patterns('.cache'))
    for q in STAGE.rglob('*'): q.chmod(0o755 if q.is_dir() else 0o644)
    old_law_ids = set(pq.read_table(SNAP / 'data/laws.parquet', columns=['id']).column('id').to_pylist())
    old_art_ids = set(pq.read_table(SNAP / 'data/articles.parquet', columns=['id']).column('id').to_pylist())
    order = ordered_law_ids()
    la, lc = merge(SNAP / 'data/laws.parquet', STAGE / 'data/laws.parquet', 'laws', old_law_ids, order)
    aa, ac = merge(SNAP / 'data/articles.parquet', STAGE / 'data/articles.parquet', 'articles', old_art_ids, order)
    for f in ['es_collect.py', 'es_build.py', 'es_stage_and_check.py']: shutil.copy2(f'/workspace/scripts/{f}', STAGE / 'scrapers' / f)
    chk = {'live_tip': info.sha, 'tip_unchanged': info.sha == TIP}
    for nm, key in (('laws', 'data/laws.parquet'), ('articles', 'data/articles.parquet')):
        lf = live_files.get(key); chk[f'{nm}_sha256_live'] = lf.lfs.sha256 if lf and lf.lfs else None
        chk[f'{nm}_sha256_snapshot'] = sha(SNAP / key); chk[f'{nm}_snapshot_matches_live'] = chk[f'{nm}_sha256_snapshot'] == chk[f'{nm}_sha256_live']
        chk[f'{nm}_sha256_staged'] = sha(STAGE / key)
    staged = {str(p.relative_to(STAGE)) for p in STAGE.rglob('*') if p.is_file()}
    chk['files_removed'] = sorted(set(live_files) - staged); chk['files_added'] = sorted(staged - set(live_files))
    chk['laws'] = compare_prefix(SNAP / 'data/laws.parquet', STAGE / 'data/laws.parquet')
    chk['articles'] = compare_prefix(SNAP / 'data/articles.parquet', STAGE / 'data/articles.parquet')
    chk['id_collisions_skipped'] = {'laws': lc, 'articles': ac}
    pc = post_checks(STAGE); chk['post'] = pc
    ok = lambda d: d['old_rows_compared'] == d['old_rows'] and d['old_row_field_mismatches'] == 0 and d['old_ids_missing'] == 0 and d['schema_equal'] and d['new_duplicate_ids'] == 0
    chk['PASS'] = bool(chk['tip_unchanged'] and chk['laws_snapshot_matches_live'] and chk['articles_snapshot_matches_live'] and not chk['files_removed']
                       and ok(chk['laws']) and ok(chk['articles']) and lc == 0 and ac == 0 and pc['article_count_mismatch_laws'] == 0 and pc['orphan_articles'] == 0)
    meta = {'repo': REPO, 'base_tip': TIP, 'staged_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'uploaded': False,
            'method': 'append-only: BOE estatal rows first and unchanged; ES-<CCAA> rows (BOE legislacion-consolidada, ambito Autonomico) appended in jurisdiction order, then date_issued, then BOE id',
            'source': 'https://www.boe.es/datosabiertos/api/legislacion-consolidada (query ambito@codigo:2)', 'append_order': ORDER,
            'subnational_laws_added': la, 'subnational_articles_added': aa, 'never_thin': chk}
    open(B / 'last_stage_path.txt', 'w').write(str(STAGE))
    (STAGE / 'PACK_META.json').write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(json.dumps({'stage': str(STAGE), 'PASS': chk['PASS'], 'laws': chk['laws'], 'articles': chk['articles'], 'post': pc}, indent=1, ensure_ascii=False)[:6000])
if __name__ == '__main__': main()
