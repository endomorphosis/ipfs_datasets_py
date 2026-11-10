import json,glob,os,hashlib,collections,csv,random
C='/workspace/courts';ST=C+'/staging';RV=C+'/review'
def build():
  os.makedirs(RV,exist_ok=True);S=json.load(open(C+'/schema.json'))['tables']
  tmap={'judges':'judges','courts':'courts','courthouses':'courthouses','forms':'forms','rules':'rules','ncsc_state_links':None}
  counts={};val={};samp={};tr=collections.Counter();lic=collections.Counter();rob=collections.Counter()
  for f in sorted(glob.glob(ST+'/*.jsonl')):
    n=os.path.basename(f)[:-6];rows=[json.loads(l) for l in open(f) if l.strip()];counts[n]=len(rows)
    samp[n]=random.Random(0).sample(rows,min(5,len(rows)))
    for r in rows:tr[r.get('transport')]+=1;lic[r.get('license')]+=1;rob[r.get('robots_note')]+=1
    t=tmap.get(n)
    if t:
      req=[k for k in S[t] if not k.startswith('_')];miss=collections.Counter(k for r in rows for k in req if k not in r)
      val[n]=dict(required_fields=len(req),rows=len(rows),missing_field_counts=dict(miss),ok=not miss)
  sr=glob.glob(ST+'/state_rules/**/*.json*',recursive=True);counts['state_rules_files']=len(sr)
  man=open(RV+'/sha256_manifest.csv','w');w=csv.writer(man);w.writerow(['path','bytes','sha256'])
  for p in sorted(glob.glob(ST+'/**/*',recursive=True)):
    if os.path.isfile(p) and '/_home/' not in p:
      h=hashlib.sha256()
      with open(p,'rb') as fh:
        for c in iter(lambda:fh.read(1<<20),b''):h.update(c)
      w.writerow([p,os.path.getsize(p),h.hexdigest()])
  man.close()
  errs=[l for lf in glob.glob(C+'/logs/*.log') for l in open(lf,errors='ignore') if any(k in l for k in ('ERR','FAIL','DISALLOW','MEMGUARD','Traceback'))]
  open(RV+'/errors_skips.txt','w').writelines(errs+[l for l in open(ST+'/skips.jsonl')] if os.path.exists(ST+'/skips.jsonl') else errs)
  for k,v in [('row_counts',counts),('schema_validation',val),('samples',samp),('robots_terms_transport',dict(transport=dict(tr),license=dict(lic),robots=dict(rob)))]:json.dump(v,open(f'{RV}/{k}.json','w'),indent=1,default=str)
  md=['# Courts US federal review package','Staged only; nothing pushed to HF.','## Row counts']+[f'- {k}: {v}' for k,v in counts.items()]+['## Schema validation']+[f"- {k}: {'OK' if v['ok'] else 'MISSING '+str(v['missing_field_counts'])}" for k,v in val.items()]+['## Transport',str(dict(tr)),'## Licences',str(dict(lic)),f'## Errors/skips: {len(errs)} log lines (errors_skips.txt)','Files: row_counts.json, samples.json, schema_validation.json, sha256_manifest.csv, robots_terms_transport.json']
  open(RV+'/REVIEW.md','w').write('\n'.join(md)+'\n')
if __name__=='__main__':build()
