import json,glob,os,hashlib,csv,collections
O='/workspace/courts/staging/state_rules_archive';RV='/workspace/courts/review_state_rules_archive';os.makedirs(RV,exist_ok=True)
S=[k for k in json.load(open('/workspace/courts/schema.json'))['tables']['rules'] if not k.startswith('_')]+['source','original_url','archive_source','archive_timestamp','file_sha256']
cnt={};rng={};miss=collections.Counter();samp={};bad=collections.Counter()
for f in sorted(glob.glob(O+'/[A-Z][A-Z].jsonl')):
  st=os.path.basename(f)[:2];ts=[];n=0
  for l in open(f):
    r=json.loads(l);n+=1;miss.update(k for k in S if k not in r);ts.append(r['archive_timestamp'])
    if r.get('source')!='archive' or r.get('archive_source')!='commoncrawl':bad[st]+=1
    if n<=2:samp.setdefault(st,[]).append(r)
  cnt[st]=n;rng[st]=[min(ts),max(ts)] if ts else None
w=csv.writer(open(RV+'/sha256_manifest.csv','w'));w.writerow(['path','bytes','sha256'])
for p in sorted(glob.glob(O+'/**/*',recursive=True)):
  if os.path.isfile(p):
    h=hashlib.sha256()
    with open(p,'rb') as fh:
      for c in iter(lambda:fh.read(1<<20),b''):h.update(c)
    w.writerow([p,os.path.getsize(p),h.hexdigest()])
sk=[json.loads(l) for l in open(O+'/skips.jsonl')] if os.path.exists(O+'/skips.jsonl') else []
ok=not miss and not bad
for k,v in [('row_counts',cnt),('capture_ranges',rng),('samples',samp),('validation',dict(missing=dict(miss),bad_flags=dict(bad),ok=ok)),('skips',sk)]:json.dump(v,open(f'{RV}/{k}.json','w'),indent=1)
open(RV+'/REVIEW.md','w').write('# State court rules: archive recovery (Common Crawl) review\nStage only, not pushed. Every row: source=archive, archive_source=commoncrawl, archive_timestamp, original_url, sha256. Licence: see source terms.\n## Rows / capture range per state\n'+'\n'.join(f'- {k}: {v} rows, {rng[k]}' for k,v in cnt.items())+f'\n## Validation: {"OK" if ok else "FAIL "+str(dict(miss))+str(dict(bad))}\n## Skips\n'+'\n'.join(f"- {s.get('state',s.get('source'))}: {s.get('reason')}" for s in sk)+'\nNote: payloads are HTTP bodies as stored in WARC (may be HTML index pages, not only rule documents).\n')
