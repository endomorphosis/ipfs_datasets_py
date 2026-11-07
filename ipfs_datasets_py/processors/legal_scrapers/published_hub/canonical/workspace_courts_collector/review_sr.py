import json,glob,os,hashlib,csv,collections
O=os.environ.get('SR_OUT','/workspace/courts/staging/state_rules/official');RV=os.environ.get('SR_RV','/workspace/courts/review_state_rules');os.makedirs(RV,exist_ok=True)
S=[k for k in json.load(open('/workspace/courts/schema.json'))['tables']['rules'] if not k.startswith('_')]
cnt={};miss=collections.Counter();samp={}
for f in sorted(glob.glob(O+'/[A-Z][A-Z].jsonl')):
  st=os.path.basename(f)[:2];n=0
  for l in open(f):
    r=json.loads(l);n+=1;miss.update(k for k in S if k not in r)
    if n<=2:samp.setdefault(st,[]).append(r)
  cnt[st]=n
w=csv.writer(open(RV+'/sha256_manifest.csv','w'));w.writerow(['path','bytes','sha256'])
for p in sorted(glob.glob(O+'/**/*',recursive=True)):
  if os.path.isfile(p):
    h=hashlib.sha256()
    with open(p,'rb') as fh:
      for c in iter(lambda:fh.read(1<<20),b''):h.update(c)
    w.writerow([p,os.path.getsize(p),h.hexdigest()])
sk=[json.loads(l) for l in open(O+'/skips.jsonl')] if os.path.exists(O+'/skips.jsonl') else []
errs=[l for lf in glob.glob('/workspace/courts/logs/'+os.environ.get('SR_LOG','state_rules2_')+'*.log') for l in open(lf,errors='ignore') if any(k in l for k in('ERR','FAIL','DISALLOW','MEMGUARD'))]
for k,v in [('row_counts',cnt),('samples',samp),('schema_validation',dict(required=S,missing=dict(miss),ok=not miss)),('skips',sk)]:json.dump(v,open(f'{RV}/{k}.json','w'),indent=1)
open(RV+'/errors.txt','w').writelines(errs)
open(RV+'/REVIEW.md','w').write('# State court rules (official sites) review\nStage only, not pushed. Licence: see source terms (per state).\n## Rows per state\n'+'\n'.join(f'- {k}: {v}' for k,v in cnt.items())+f'\n## Schema: {"OK" if not miss else "MISSING "+str(dict(miss))}\n## Skipped\n'+'\n'.join(f"- {s.get('state')}: {s.get('reason')}" for s in sk)+f'\n## Errors: {len(errs)} lines (errors.txt)\nTransport: https only; robots.txt + Crawl-delay honored; TX at 720s/request capped at 60 docs.\n')
