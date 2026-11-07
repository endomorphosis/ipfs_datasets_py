import sys,os,hashlib,shutil;# sanitized: expects HF_TOKEN in environment (connector secret loader removed)
from huggingface_hub import HfApi,snapshot_download
api=HfApi();R='justicedao/ipfs_us_courts'
c=api.upload_folder(folder_path='/workspace/courts/hf_stage',repo_id=R,repo_type='dataset',allow_patterns=['README.md','ROWCOUNTS.txt','data/state_rules.jsonl'],commit_message='state_rules: merge 274 rerun docs (NE 22, DE 93, KS 159); total 2713, licence see source terms')
print('COMMIT',c.oid)
p=snapshot_download(R,repo_type='dataset',revision=c.oid,local_dir='/tmp/hfv3');ok=True
for l in open('/workspace/courts/hf_stage/MANIFEST.sha256'):
  h,f=l.split(None,1);f=f.strip()[2:];h2=hashlib.sha256()
  with open(os.path.join(p,f),'rb') as fh:
    for b in iter(lambda:fh.read(1<<20),b''):h2.update(b)
  m=h2.hexdigest()==h;ok&=m;print(f,'ok' if m else 'MISMATCH',sum(1 for _ in open(os.path.join(p,f))) if f.endswith('.jsonl') else '')
print('ALL_OK',ok);shutil.rmtree('/tmp/hfv3')
