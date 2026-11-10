import sys,os,hashlib,shutil,json;# sanitized: expects HF_TOKEN in environment (connector secret loader removed)
from huggingface_hub import HfApi,snapshot_download
api=HfApi();R='justicedao/ipfs_us_courts'
c=api.upload_folder(folder_path='/workspace/courts/hf_stage',repo_id=R,repo_type='dataset',allow_patterns=['README.md','ROWCOUNTS.txt','MANIFEST.sha256','schema.json','data/courts.jsonl','data/courthouses.jsonl','data/judges.jsonl','data/forms.jsonl'],commit_message='state/county judiciary Phase 1: +71 courts, +413 courthouses, +860 judges, +2300 forms (coverage field; gaps DE MT CT VA KS WA WI ND listed on card)')
print('COMMIT',c.oid,flush=True)
p=snapshot_download(R,repo_type='dataset',revision=c.oid,local_dir='/tmp/hfv5');ok=True
for l in open('/workspace/courts/hf_stage/MANIFEST.sha256'):
  h,f=l.split(None,1);f=f.strip()[2:];h2=hashlib.sha256()
  with open(os.path.join(p,f),'rb') as fh:
    for b in iter(lambda:fh.read(1<<20),b''):h2.update(b)
  m=h2.hexdigest()==h;ok&=m;print(f,'ok' if m else 'MISMATCH',sum(1 for _ in open(os.path.join(p,f))) if f.endswith('.jsonl') else '')
print('ALL_OK',ok,flush=True);shutil.rmtree('/tmp/hfv5')
from datasets import load_dataset
for cfg in ['courts','courthouses','judges','forms']:
  d=load_dataset(R,cfg,split='train',revision=c.oid,cache_dir='/tmp/hfds5')
  n=[r for r in d if r.get('coverage')][:2]
  print('SMOKE',cfg,len(d),[(r.get('name') or r.get('full_name') or r.get('title'),r['subdivision_iso'],r['coverage']) for r in n])
shutil.rmtree('/tmp/hfds5',ignore_errors=True)
