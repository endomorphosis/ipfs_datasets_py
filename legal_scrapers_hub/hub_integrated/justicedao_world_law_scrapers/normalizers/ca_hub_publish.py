#!/usr/bin/env python3
"""ONE commit publish of the CA subnational append (parent_commit pinned), then Hub never-thin verify. Phases: upload | verify. No legal-source fetching."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, json, time, hashlib, threading, collections
from pathlib import Path
import pyarrow.parquet as pq
from huggingface_hub import HfApi, CommitOperationAdd, hf_hub_download
REPO = 'endomorphosis/ipfs_canada_laws'; TIP = '7e8066f09c8cdef1fbadad34ea8e35585828e8a0'
STAGE = Path('{_CORPORA}/hf-staging/ipfs_canada_laws_subnational_20261001T145527')
SNAP = Path(f'/workspace/country-laws-ir/cache/hf/hub/datasets--endomorphosis--ipfs_canada_laws/snapshots/{TIP}')
UP = Path('{_CORPORA}/ca_subnational/hub_upload_result.json')
OUT = Path('/workspace/country-law-triage/canada_subnational_hub_republish_result.json')
PIN = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'
EXPECT = {'laws': 19208, 'articles': 442911, 'per': {'CA': 11676, 'CA-ON': 3073, 'CA-NS': 1934, 'CA-NB': 1098, 'CA-NT': 808, 'CA-NU': 619}}
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
def set_pin(**u):
    kv = dict(l.rstrip('\n').split('=', 1) for l in open(PIN) if '=' in l); kv.update({k: str(v) for k, v in u.items()})
    open(PIN + '.tmp', 'w').write(''.join(f'{k}={v}\n' for k, v in kv.items())); os.replace(PIN + '.tmp', PIN)
def _mg():
    while True:
        m = memavail()
        if m <= 3584:
            log(f'MEMGUARD TERM MemAvailable={m}MB')
            set_pin(mode='HOLD_0_CA_MEMSHED', collectors=0, phase=f'CA publish {sys.argv[1]} self-TERM at MemAvail={m}MB; not restarted', ts=time.strftime('%Y-%m-%dT%H:%MPT'))
            os._exit(3)
        time.sleep(5)
threading.Thread(target=_mg, daemon=True).start()
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
api = HfApi(token=os.environ['HF_TOKEN'])

def upload():
    info = api.dataset_info(REPO); log('hub tip', info.sha)
    if info.sha != TIP:
        log('ABORT: tip moved', info.sha); json.dump({'aborted': 'tip_moved', 'tip': info.sha}, open(UP, 'w')); sys.exit(2)
    live = {s.rfilename for s in info.siblings}
    mp = STAGE / 'PACK_META.json'; meta = json.loads(mp.read_text())
    assert meta['never_thin']['PASS'] is True and meta['base_tip'] == TIP
    meta['uploaded'] = True; meta['uploaded_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z'); meta['upload_parent_commit'] = TIP
    mp.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    ops = []; plan = []
    for p in sorted(STAGE.rglob('*')):
        if not p.is_file(): continue
        rel = str(p.relative_to(STAGE)); old = SNAP / rel
        if old.exists() and sha(old) == sha(p): continue
        ops.append(CommitOperationAdd(path_in_repo=rel, path_or_fileobj=str(p))); plan.append(dict(path=rel, new=rel not in live, bytes=p.stat().st_size, sha256=sha(p)))
    log('ops', json.dumps(plan))
    ci = api.create_commit(repo_id=REPO, repo_type='dataset', operations=ops, parent_commit=TIP,
        commit_message='Append provincial/territorial consolidated laws (ON, NS, NB, NT, NU): 19,208 laws / 442,911 articles; federal rows unchanged',
        commit_description='Append-only. Federal rows (11,676 laws / 267,570 articles at 7e8066f09c8c) unchanged and first; CA-ON (3,073), CA-NS (1,934), CA-NB (1,098), CA-NT (808), CA-NU (619) appended from official provincial/territorial sites (English). MB and SK held out pending licence decision. QC/PE/YT BLOCKED_SOURCE, BC/AB BLOCKED (robots.txt), NL UNAVAILABLE. Licences differ per jurisdiction (NS/NB/NT non-commercial; NU personal use); see README Known limitations and PACK_META.json.')
    res = dict(commit_oid=ci.oid, commit_url=ci.commit_url, parent_commit=TIP, files=plan, ts=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
    json.dump(res, open(UP, 'w'), indent=1); log('COMMIT', ci.oid, ci.commit_url)
    import pa_exit_guard as _EG; _EG.release()  # exit guard (pa_exit_guard): gc before returning

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
        ids.update(ob.column('id').to_pylist()); rows += ob.num_rows
    allnew = set()
    for nb in new.iter_batches(batch_size=20000, columns=['id']): allnew.update(nb.column('id').to_pylist())
    res = {'old_rows': old.metadata.num_rows, 'new_rows': new.metadata.num_rows, 'old_rows_compared': rows, 'old_row_field_mismatches': mism, 'mismatch_columns': dict(mc),
            'old_ids_missing': len(ids - allnew), 'duplicate_ids_before': old.metadata.num_rows - len(ids), 'duplicate_ids_after': new.metadata.num_rows - len(allnew),
            'new_duplicate_ids': (new.metadata.num_rows - len(allnew)) - (old.metadata.num_rows - len(ids)), 'schema_equal': old.schema_arrow.equals(new.schema_arrow)}
    import pa_exit_guard as _EG; _EG.release(it, old, new); del it, old, new, buf; ob = nb = parts = None; _EG.release()  # exit guard (pa_exit_guard): close readers, drop them + gc
    return res

def post(laws_p, arts_p):
    jur = {}; ac = {}; kind = {}
    for b in pq.ParquetFile(laws_p).iter_batches(batch_size=1000, columns=['id', 'jurisdiction', 'article_count', 'metadata_json']):
        for i, j, c, m in zip(*[b.column(k).to_pylist() for k in ['id', 'jurisdiction', 'article_count', 'metadata_json']]):
            jur[i] = j; ac[i] = c
            if j != 'CA': kind[i] = json.loads(m).get('document_type')
    rows = collections.Counter(); orphan = 0
    for b in pq.ParquetFile(arts_p).iter_batches(batch_size=50000, columns=['law_id']):
        for lid in b.column('law_id').to_pylist():
            if lid not in jur: orphan += 1
            rows[lid] += 1
    per = collections.defaultdict(collections.Counter)
    for i, j in jur.items():
        k = kind.get(i, 'federal'); per[j]['laws'] += 1; per[j]['articles'] += rows.get(i, 0); per[j][f'{k}_laws'] += 1; per[j][f'{k}_articles'] += rows.get(i, 0)
    return {'article_count_mismatch_laws': sum(1 for i in ac if ac[i] != rows.get(i, 0)), 'orphan_articles': orphan, 'per_jurisdiction': {j: dict(v) for j, v in sorted(per.items())}}

def verify():
    up = json.load(open(UP)); new = up['commit_oid']
    info = api.dataset_info(REPO, revision=new, files_metadata=True); tipnow = api.dataset_info(REPO).sha
    parents = [p for p in (api.list_repo_commits(REPO, repo_type='dataset')[:3])]
    d = Path(f'{_CORPORA}/hub_verify_ca_{new[:12]}'); d.mkdir(exist_ok=True)
    for f in ('data/laws.parquet', 'data/articles.parquet'):
        hf_hub_download(REPO, f, repo_type='dataset', revision=new, local_dir=str(d), token=os.environ['HF_TOKEN']); log('downloaded', f)
    r = {'repo': REPO, 'old_tip': TIP, 'new_tip': new, 'hub_tip_at_verify': tipnow, 'commit_url': up['commit_url'], 'parent_commit_used': TIP,
         'recent_commits': [dict(id=c.commit_id, title=c.title) for c in parents], 'files_in_commit': up['files'], 'verified_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    r['hub_files_old'] = sorted(str(p.relative_to(SNAP)) for p in SNAP.rglob('*') if p.is_file())
    r['hub_files_new'] = sorted(s.rfilename for s in info.siblings)
    r['files_removed'] = sorted(set(r['hub_files_old']) - set(r['hub_files_new']))
    r['laws_vs_old_tip'] = compare_prefix(SNAP / 'data/laws.parquet', d / 'data/laws.parquet'); log('laws', r['laws_vs_old_tip'])
    r['articles_vs_old_tip'] = compare_prefix(SNAP / 'data/articles.parquet', d / 'data/articles.parquet'); log('articles', r['articles_vs_old_tip'])
    r['sha256_hub_equals_staged'] = {f: sha(d / f) == sha(STAGE / f) for f in ('data/laws.parquet', 'data/articles.parquet')}
    lf = {s.rfilename: s for s in info.siblings}
    r['hub_lfs_sha256'] = {f: (lf[f].lfs.sha256 if lf.get(f) and lf[f].lfs else None) for f in ('data/laws.parquet', 'data/articles.parquet')}
    r['post'] = post(d / 'data/laws.parquet', d / 'data/articles.parquet'); log('post', r['post'])
    pj = r['post']['per_jurisdiction']
    r['expected_counts_match'] = (r['laws_vs_old_tip']['new_rows'] == EXPECT['laws'] and r['articles_vs_old_tip']['new_rows'] == EXPECT['articles']
                                  and all(pj.get(j, {}).get('laws') == n for j, n in EXPECT['per'].items()) and set(pj) == set(EXPECT['per']))
    r['federal_after'] = {'laws': pj['CA']['laws'], 'articles': pj['CA']['articles']}
    ok = lambda x: x['old_row_field_mismatches'] == 0 and x['old_ids_missing'] == 0 and x['schema_equal'] and x['old_rows_compared'] == x['old_rows'] and x['new_duplicate_ids'] == 0
    r['hub_never_thin_PASS'] = bool(ok(r['laws_vs_old_tip']) and ok(r['articles_vs_old_tip']) and not r['files_removed'] and all(r['sha256_hub_equals_staged'].values())
                                    and r['post']['article_count_mismatch_laws'] == 0 and r['post']['orphan_articles'] == 0 and r['expected_counts_match']
                                    and r['federal_after'] == {'laws': 11676, 'articles': 267570})
    r['totals'] = {'laws': r['laws_vs_old_tip']['new_rows'], 'articles': r['articles_vs_old_tip']['new_rows']}
    r['held_out_local_only'] = ['CA-MB', 'CA-SK']
    r['skipped_or_blocked'] = {'CA-QC': 'BLOCKED_SOURCE (CloudFront 403 x3)', 'CA-BC': 'BLOCKED (robots.txt Disallow / for *)', 'CA-AB': 'BLOCKED (robots.txt Disallow /)',
                               'CA-PE': 'BLOCKED_SOURCE (Radware challenge)', 'CA-YT': 'BLOCKED_SOURCE (Cloudflare/sgcaptcha 202)', 'CA-NL': 'UNAVAILABLE (robots.txt HTTP 500)'}
    json.dump(r, open(OUT, 'w'), indent=1, ensure_ascii=False); log('VERIFY', 'PASS' if r['hub_never_thin_PASS'] else 'FAIL')
    import pa_exit_guard as _EG; _EG.release()  # exit guard (pa_exit_guard): gc before returning

if __name__ == '__main__':
    import pa_exit_guard as _EG  # exit guard (pa_exit_guard)
    log('START', sys.argv[1], 'pid', os.getpid(), 'mem', memavail())
    def _main(): {'upload': upload, 'verify': verify}[sys.argv[1]](); log('END', sys.argv[1])
    _EG.run_guarded(_main)
