#!/usr/bin/env python3
"""ONE commit publish of the AU subnational pack (parent_commit pinned), then Hub never-thin verify. Phases: upload | verify."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, json, time, hashlib, threading
from pathlib import Path
sys.path.insert(0, '/workspace/scripts')
from huggingface_hub import HfApi, CommitOperationAdd, hf_hub_download
REPO = 'endomorphosis/ipfs_australia_laws'; TIP = 'c72ad1989fc8d4f4858ea8e2944c77f08406a6dd'
STAGE = Path('{_CORPORA}/hf-staging/ipfs_australia_laws_subnational_20260928T015251')
SNAP = Path(f'/workspace/country-laws-ir/cache/hf/hub/datasets--endomorphosis--ipfs_australia_laws/snapshots/{TIP}')
UP = Path('{_CORPORA}/au_subnational/hub_upload_result.json')
OUT = Path('/workspace/country-law-triage/australia_subnational_hub_republish_result.json')
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
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
api = HfApi(token=os.environ['HF_TOKEN'])

def upload():
    info = api.dataset_info(REPO); log('hub tip', info.sha)
    if info.sha != TIP: log('ABORT: tip moved', info.sha); json.dump({'aborted': 'tip_moved', 'tip': info.sha}, open(UP, 'w')); sys.exit(2)
    live = {s.rfilename for s in info.siblings}
    ops = []; plan = []
    for p in sorted(STAGE.rglob('*')):
        if not p.is_file(): continue
        rel = str(p.relative_to(STAGE)); old = SNAP / rel
        if old.exists() and sha(old) == sha(p): continue
        ops.append(CommitOperationAdd(path_in_repo=rel, path_or_fileobj=str(p))); plan.append(dict(path=rel, new=rel not in live, bytes=p.stat().st_size))
    log('ops', json.dumps(plan))
    assert all(x['path'] in {str(q.relative_to(STAGE)) for q in STAGE.rglob('*') if q.is_file()} for x in plan)
    ci = api.create_commit(repo_id=REPO, repo_type='dataset', operations=ops, parent_commit=TIP,
                           commit_message='Append Australian state/territory in-force laws (NSW, QLD, TAS, WA, NT): 36,214 laws / 680,077 articles; Commonwealth rows unchanged',
                           commit_description='Append-only. Commonwealth rows (29,084 laws / 309,135 articles at c72ad1989fc8) unchanged and first; AU-NSW/QLD/TAS/WA/NT rows appended from official state/territory legislation sites. VIC/ACT blocked by robots.txt, SA BLOCKED_SOURCE (403). See README Known limitations and PACK_META.json.')
    res = dict(commit_oid=ci.oid, commit_url=ci.commit_url, parent_commit=TIP, files=plan, ts=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
    json.dump(res, open(UP, 'w'), indent=1); log('COMMIT', ci.oid, ci.commit_url)
    import pa_exit_guard as _EG; _EG.release()  # exit guard (pa_exit_guard): gc before returning

def verify():
    import au_fix_mixedcase as F
    up = json.load(open(UP)); new = up['commit_oid']
    info = api.dataset_info(REPO, revision=new, files_metadata=True); tipnow = api.dataset_info(REPO).sha
    d = Path(f'{_CORPORA}/hub_verify_{new[:12]}'); d.mkdir(exist_ok=True)
    for f in ('data/laws.parquet', 'data/articles.parquet'):
        hf_hub_download(REPO, f, repo_type='dataset', revision=new, local_dir=str(d), token=os.environ['HF_TOKEN']); log('downloaded', f)
    r = {'repo': REPO, 'old_tip': TIP, 'new_tip': new, 'hub_tip_at_verify': tipnow, 'commit_url': up['commit_url'], 'files_in_commit': up['files'],
         'parent_commit_used': TIP, 'verified_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    r['hub_files_old'] = sorted(str(p.relative_to(SNAP)) for p in SNAP.rglob('*') if p.is_file())
    r['hub_files_new'] = sorted(s.rfilename for s in info.siblings)
    r['files_removed'] = sorted(set(r['hub_files_old']) - set(r['hub_files_new']))
    r['laws_vs_old_tip'] = F.compare_prefix(str(SNAP / 'data/laws.parquet'), str(d / 'data/laws.parquet')); log('laws', r['laws_vs_old_tip'])
    r['articles_vs_old_tip'] = F.compare_prefix(str(SNAP / 'data/articles.parquet'), str(d / 'data/articles.parquet')); log('articles', r['articles_vs_old_tip'])
    r['sha256_hub_equals_staged'] = {f: sha(d / f) == sha(STAGE / f) for f in ('data/laws.parquet', 'data/articles.parquet')}
    r['article_count_check'] = F.ac_check(str(d / 'data/laws.parquet'), str(d / 'data/articles.parquet')); log('ac', r['article_count_check'])
    meta = json.load(open(STAGE / 'PACK_META.json'))
    r['fix12'] = meta['follow_up_20260930']
    ok = lambda x: x['old_row_field_mismatches'] == 0 and x['old_ids_missing'] == 0 and x['schema_equal'] and x['old_rows_compared'] == x['old_rows']
    r['hub_never_thin_PASS'] = bool(ok(r['laws_vs_old_tip']) and ok(r['articles_vs_old_tip']) and not r['files_removed'] and all(r['sha256_hub_equals_staged'].values())
                                    and r['article_count_check']['mismatches'] == 0 and r['article_count_check']['orphan_article_rows_nonAU_scope'] == 0)
    r['totals'] = {'laws': r['laws_vs_old_tip']['new_rows'], 'articles': r['articles_vs_old_tip']['new_rows']}
    r['skipped_or_blocked'] = {'AU-VIC': 'BLOCKED (robots.txt)', 'AU-SA': 'BLOCKED_SOURCE (403)', 'AU-ACT': 'BLOCKED (robots.txt)'}
    json.dump(r, open(OUT, 'w'), indent=1, ensure_ascii=False); log('VERIFY', 'PASS' if r['hub_never_thin_PASS'] else 'FAIL')
    import pa_exit_guard as _EG; _EG.release()  # exit guard (pa_exit_guard): gc before returning

if __name__ == '__main__':
    import pa_exit_guard as _EG  # exit guard (pa_exit_guard)
    log('START', sys.argv[1], 'pid', os.getpid(), 'mem', memavail())
    def _main(): {'upload': upload, 'verify': verify}[sys.argv[1]](); log('END', sys.argv[1])
    _EG.run_guarded(_main)
