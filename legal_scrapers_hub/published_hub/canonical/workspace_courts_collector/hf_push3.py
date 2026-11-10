import sys,os,hashlib,shutil,json;# sanitized: expects HF_TOKEN in environment (connector secret loader removed)
from huggingface_hub import HfApi,snapshot_download
api=HfApi();R='justicedao/ipfs_us_courts'
c=api.upload_folder(folder_path='/workspace/courts/hf_stage',repo_id=R,repo_type='dataset',allow_patterns=['README.md','ROWCOUNTS.txt','MANIFEST.sha256','data/state_rules.jsonl'],commit_message='state_rules: add 90 Common Crawl archive docs (DE 87, MI 3; source=archive, archive_source=commoncrawl); filtered+deduped; total 2803')
print('COMMIT',c.oid)
p=snapshot_download(R,repo_type='dataset',revision=c.oid,local_dir='/tmp/hfv4');ok=True
for l in open('/workspace/courts/hf_stage/MANIFEST.sha256'):
  h,f=l.split(None,1);f=f.strip()[2:];h2=hashlib.sha256()
  with open(os.path.join(p,f),'rb') as fh:
    for b in iter(lambda:fh.read(1<<20),b''):h2.update(b)
  m=h2.hexdigest()==h;ok&=m;print(f,'ok' if m else 'MISMATCH',sum(1 for _ in open(os.path.join(p,f))) if f.endswith('.jsonl') else '')
rows=[json.loads(l) for l in open(os.path.join(p,'data/state_rules.jsonl'))]
a=[r for r in rows if r.get('source_collection')=='commoncrawl_archive_20261028']
print('archive_rows',len(a),'flags_ok',all(r['record']['source']=='archive' and r['record']['archive_source']=='commoncrawl' and r['record']['warc_filename'] and r['record']['archive_timestamp'] for r in a))
print('ALL_OK',ok);shutil.rmtree('/tmp/hfv4')
