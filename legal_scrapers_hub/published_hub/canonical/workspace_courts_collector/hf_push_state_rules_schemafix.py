import sys,os,hashlib,shutil;# sanitized: expects HF_TOKEN in environment (connector secret loader removed)
from huggingface_hub import HfApi,snapshot_download
api=HfApi();R='justicedao/ipfs_us_courts';S='/workspace/courts/hf_stage_phase2';PARENT='dca3bf749a865c39badc4fe186608200f6fc29f4'
head=api.dataset_info(R).sha;print('HEAD',head,flush=True)
assert head==PARENT,'head moved'
c=api.upload_folder(folder_path=S,repo_id=R,repo_type='dataset',parent_commit=PARENT,allow_patterns=['README.md','MANIFEST.sha256','data/state_rules.jsonl'],commit_message='state_rules schema fix: record as JSON string + explicit features; values unchanged (2803 rows)')
print('COMMIT',c.oid,flush=True)
p=snapshot_download(R,repo_type='dataset',revision=c.oid,local_dir='/tmp/hfv7');ok=True
for l in open(S+'/MANIFEST.sha256'):
  h,f=l.split(None,1);f=f.strip();h2=hashlib.sha256()
  with open(os.path.join(p,f),'rb') as fh:
    for b in iter(lambda:fh.read(1<<20),b''):h2.update(b)
  m=h2.hexdigest()==h;ok&=m;print(f,'ok' if m else 'MISMATCH',sum(1 for _ in open(os.path.join(p,f))) if f.endswith('.jsonl') else '')
rc=open(os.path.join(p,'ROWCOUNTS.txt')).read()
for l in rc.split('\n'):
  if l: f,n=l.split();a=sum(1 for _ in open(os.path.join(p,f)));ok&=a==int(n);print('ROWCOUNT',f,n,a)
print('ALL_OK',ok,flush=True);shutil.rmtree('/tmp/hfv7')
