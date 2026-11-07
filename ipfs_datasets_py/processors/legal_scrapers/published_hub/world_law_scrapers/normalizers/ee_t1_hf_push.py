#!/usr/bin/env python3
"""Push the EE T1 staging folder to the HF dataset endomorphosis/ipfs_estonia_municipal_laws as status EXPAND (single commit), then verify
(remote file list, row counts vs local, load one shard back) and set state.json status T1_PUSHED with the tip sha.
Auth: ONLY an existing env token (HF_TOKEN / HUGGING_FACE_HUB_TOKEN) or the huggingface-cli / `hf auth login` login on the box (huggingface_hub.get_token()).
No other credential source is used; the token is never printed. No auth -> exit 4 without any network write.
Gate: the latest review/ee_t1_review_strip_*.json must have push_gate.passes == true and match the current shard manifest sha256.
Usage: nice -n 19 /workspace/venv/bin/python /workspace/scripts/ee_t1_hf_push.py STAGING_DIR [--check]"""
import os, sys, json, glob, time, tempfile
sys.path.insert(0, '/workspace/scripts')
import ee_t1_fix as F
REPO = 'endomorphosis/ipfs_estonia_municipal_laws'
FILES = ['README.md', 'data/laws.parquet', 'data/articles.parquet', 'manifest.json']
import pa_exit_guard as _EG  # exit guard (pa_exit_guard)
def log(*a):
    s = time.strftime('%Y-%m-%d %H:%M:%S') + ' ' + ' '.join(str(x) for x in a); print(s, flush=True)
    with open(LOGF, 'a') as f: f.write(s + '\n')
def main():
    global LOGF
    a = sys.argv[1:]; check = '--check' in a; stg = [x for x in a if not x.startswith('--')][0]
    LOGF = f"/workspace/logs/ee_t1_hf_push_{time.strftime('%Y%m%dT%H%M%S')}{'_check' if check else ''}.log"
    rv = sorted(glob.glob(f'{F.ROOT}/review/ee_t1_review_strip_*.json'))[-1]; R = json.load(open(rv)); msha = F.sha_file(F.MAN)
    g = R['push_gate']; log('gate', rv, {k: v for k, v in g.items() if k != 'article_delta_explanation'})
    if not g['passes']: log('GATE FAILED -> no push'); sys.exit(2)
    if R['manifest_sha256'] != msha: log('review does not match current manifest -> no push'); sys.exit(2)
    mf = json.load(open(f'{stg}/manifest.json'))
    if mf['source_manifest_sha256'] != msha: log('staging built from another manifest -> no push'); sys.exit(2)
    for p in FILES[:3]:
        if F.sha_file(f'{stg}/{p}') != mf['files'][p]['sha256']: log('staging file changed', p); sys.exit(2)
    from huggingface_hub import HfApi, get_token, CommitOperationAdd, hf_hub_download
    tok = os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN') or get_token()
    src = 'env' if (os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN')) else 'cli_login' if tok else None
    if not tok: log('NO HF AUTH: no HF_TOKEN / HUGGING_FACE_HUB_TOKEN in env and no huggingface-cli login on the box -> stop, nothing pushed'); sys.exit(4)
    api = HfApi(token=tok); who = api.whoami(); log('auth ok via', src, 'user', who.get('name'))
    if check: log('CHECK ONLY: gate + auth ok; not pushing'); return
    api.create_repo(REPO, repo_type='dataset', exist_ok=True, private=False)
    ops = [CommitOperationAdd(path_in_repo=p, path_or_fileobj=f'{stg}/{p}') for p in FILES]
    c = api.create_commit(REPO, repo_type='dataset', operations=ops,
                          commit_message=f"EE municipal laws tranche 1 (Riigi Teataja IV xml.2024, as of 2024-11-01): {mf['validation']['laws']:,} laws, {mf['validation']['articles']:,} articles; status EXPAND")
    tip = c.oid; log('pushed', REPO, 'commit', tip, c.commit_url)
    files = sorted(api.list_repo_files(REPO, repo_type='dataset', revision=tip)); log('remote files', files)
    tmp = tempfile.mkdtemp(prefix='ee_hf_verify_', dir='/workspace/legal-corpora/ee_municipal/build')
    for p in ('data/laws.parquet', 'data/articles.parquet'):
        hf_hub_download(REPO, p, repo_type='dataset', revision=tip, local_dir=tmp, token=tok)
    ver = verify_local(tmp, files, mf)
    log('verify', ver)
    st = json.load(open(f'{F.ROOT}/state.json'))
    st['t1_push'] = dict(repo=REPO, url=f'https://huggingface.co/datasets/{REPO}', tip_sha=tip, tip_short=tip[:12], commit_url=c.commit_url, pushed=F.now(), status='EXPAND',
                         staging=stg, manifest_sha256=msha, review=rv, auth_source=src, verify=ver, log=LOGF)
    if ver['all_files_present'] and ver['rows_match']: st['status'] = 'T1_PUSHED'
    st['ts'] = F.now(); F.atomic_json(f'{F.ROOT}/state.json', st); log('state.json status', st['status'])
def verify_local(tmp, files, mf):
    """offline part of the post-push verify (row counts + load one shard back) on a local dir laid out like the repo (tmp/data/*.parquet); no network"""
    import pyarrow.parquet as pq
    rows = {}
    for p in ('data/laws.parquet', 'data/articles.parquet'):
        pf = pq.ParquetFile(f'{tmp}/{p}'); rows[p] = pf.metadata.num_rows; _EG.release(pf); del pf  # exit guard (pa_exit_guard)
    t = pq.read_table(f'{tmp}/data/laws.parquet'); ids = t.column('id').to_pylist(); n = t.num_rows
    del t; _EG.release()  # exit guard (pa_exit_guard): drop the Table + gc before returning
    return dict(remote_files=files, all_files_present=all(p in files for p in FILES), rows_remote=rows,
                rows_local=dict(laws=mf['validation']['laws'], articles=mf['validation']['articles']),
                rows_match=rows == {'data/laws.parquet': mf['validation']['laws'], 'data/articles.parquet': mf['validation']['articles']},
                shard_loaded=dict(file='data/laws.parquet', rows=n, unique_ids=len(set(ids)), first_id=ids[0]))
if __name__ == '__main__': _EG.run_guarded(main)  # exit guard (pa_exit_guard)
