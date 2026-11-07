import json,glob,collections,os,hashlib,random
B='/workspace/courts';O=f'{B}/staging/state_county_cc';R=f'{B}/review_state_county/cc_gapfill';os.makedirs(R,exist_ok=True)
c=collections.Counter();bad=collections.Counter();samp={}
REQ=['source','archive_source','archive_timestamp','original_url','sha256','warc_filename','warc_offset','warc_length']
for f in sorted(glob.glob(f'{O}/[A-Z][A-Z]_*.jsonl')):
  st,t=os.path.basename(f)[:-6].split('_',1);rows=[json.loads(l) for l in open(f)];c[(st,t)]=len(rows)
  for r in rows:
    for k in REQ:
      if r.get(k) in (None,''): bad[(st,t,k)]+=1
    if r.get('source')!='archive' or r.get('archive_source')!='commoncrawl': bad[(st,t,'flag')]+=1
  if rows: samp[f'{st}_{t}']=random.sample(rows,min(2,len(rows)))
pf=collections.Counter()
if os.path.exists(f'{O}/page_filter_log.jsonl'):
  for l in open(f'{O}/page_filter_log.jsonl'): d=json.loads(l);pf[(d['state'],d['reason'])]+=1
md=['# CC gap-fill review (AL ND WV PA CO MS MN NM FL — 9 states) — STAGED, NOT PUSHED','','## Rows by state x table']+[f'- {s} {t}: {n}' for (s,t),n in sorted(c.items())]+['','## Page filter (index/nav heuristic) by state x reason']+[f'- {s} {r}: {n}' for (s,r),n in sorted(pf.items())]+['','Heuristic: drop HTML page if <80 words (scripts/nav/header/footer stripped), or no judge/courthouse rows extracted, or link_density>0.5 with <3 rows. Forms: archived file URLs with form in path and doc extension, sha256 of WARC payload only, not stored.','','## Validation (missing required archive fields)',str(dict(bad)) or 'none','','## Samples']+[f'- {k}: '+json.dumps(v,ensure_ascii=False)[:1500] for k,v in samp.items()]
open(f'{R}/REVIEW.md','w').write('\n'.join(md)+'\n')
json.dump(dict(rows={f'{s}_{t}':n for (s,t),n in c.items()},filter={f'{s}|{r}':n for (s,r),n in pf.items()},invalid={'|'.join(k):v for k,v in bad.items()}),open(f'{R}/report.json','w'),indent=1)
open(f'{R}/MANIFEST.sha256','w').write(''.join(hashlib.sha256(open(p,'rb').read()).hexdigest()+'  '+p+'\n' for p in sorted(glob.glob(f'{O}/*.jsonl'))+[f'{R}/REVIEW.md',f'{R}/report.json']))
print(md[:20])
