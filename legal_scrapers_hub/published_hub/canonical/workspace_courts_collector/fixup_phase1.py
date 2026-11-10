import json,re,collections,shutil,os,hashlib,random
SRC='hf_stage';DST='hf_stage_fixup';REV='review_state_county/phase1_fixup'
if os.path.exists(DST): shutil.rmtree(DST)
shutil.copytree(SRC,DST)
log=open(f'{REV}/rules_applied.log','w')
RULES=[ # (name, field, regex, role_type) first match wins; applied to court_id-null rows
 ('R0_ut_senior_board','court_name',r'^board of senior judges$','senior_judge'),
 ('R1_committee','court_name',r'committee|association|education|bench book|legislat|technology|probate|juvenile services|criminal procedure|waivers|caseload|ethics|personnel|salary|pension|board of','committee_member'),
 ('R2_nav_heading','court_name',r'responsibilities of','other'),
 ('R3_justice','title',r'justice','justice'),
 ('R4_magistrate','title',r'magistrate|commissioner|referee','magistrate'),
 ('R5_staff','title',r'clerk|administrator|staff|secretary|director','staff'),
 ('R6_judge_seat','court_name',r'^district \d+$|circuit judges|presiding judges','judge'),
]
def classify_null(x):
  for n,f,rx,rt in RULES:
    if re.search(rx,(x.get(f) or ''),re.I): return rt,n
  return 'other','R9_default'
def classify_linked(x):
  t=(x.get('title') or '').lower()
  if 'justice' in t: return 'justice','L1_title_justice'
  if re.search('magistrate|commissioner|referee',t): return 'magistrate','L2_title_magistrate'
  return 'judge','L3_linked_seat'
before={}
# (1) AL coverage
al=collections.Counter()
for f in ['courts','courthouses','forms','judges']:
  p=f'{DST}/data/{f}.jsonl';rows=[json.loads(l) for l in open(p)];before[f]=len(rows)
  for r in rows:
    if r.get('subdivision_iso')=='US-AL':
      if r.get('coverage')=='complete': r['coverage']='partial_guard_stop';al[f]+=1
      else: al[f+'_untouched_cov_'+str(r.get('coverage'))]+=1
  if f!='judges': open(p,'w').write(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
# (2) judges
p=f'{DST}/data/judges.jsonl';rows=[json.loads(l) for l in open(p)]
cnt=collections.Counter();bystate=collections.Counter();rulec=collections.Counter()
for r in rows:
  if r.get('court_id'): rt,n=classify_linked(r)
  else:
    rt,n=classify_null(r);bystate[(r['subdivision_iso'],rt)]+=1
    log.write(f"{r['judge_id']}\t{r['subdivision_iso']}\t{r['court_name']!r}\t{r['title']!r}\t{n}\t{rt}\n")
  r['role_type']=rt;rulec[n]+=1;cnt[(bool(r.get('court_id')),rt)]+=1
REMOVE={'committee_member','staff','other'}
keep=[r for r in rows if not (not r.get('court_id') and r['role_type'] in REMOVE)]
removed=[r for r in rows if r not in keep]
# names removed that also survive as a seat in same state
seat={(r['subdivision_iso'],' '.join(r['full_name'].split()).lower()) for r in keep}
dup=sum(((r['subdivision_iso'],' '.join(r['full_name'].split()).lower()) in seat) for r in removed)
open(p,'w').write(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in keep))
open(f'{REV}/removed_judges.jsonl','w').write(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in removed))
after={f:sum(1 for _ in open(f'{DST}/data/{f}.jsonl')) for f in before}
# card
card=open(f'{DST}/README.md').read()
card+=f"""

## Fix-up (staged 2026-10-28, on top of f12c757)
- Alabama state/county rows: coverage changed `complete` -> `partial_guard_stop` (the AL collection was cut by the memory guard).
- `judges` now has a `role_type` field on every row (judge, justice, magistrate, senior_judge; for unlinked rows also committee_member, other). `senior_judge` = 7 Utah Board of Senior Judges members, kept, assigned by explicit logged rules.
- **Removed** {len(removed)} unlinked rows (court_id null) whose role_type was committee_member/staff/other: these were committee, association or board memberships (mostly Nebraska Judicial Branch committee pages), not judicial seats. Removed rows are saved for audit (removed_judges.jsonl, not published). {dup} of them name a person who still appears in this state as a seat row. Kept unlinked rows with role_type judge/justice/senior_judge ({sum(1 for r in keep if not r.get('court_id'))}) remain without a court_id.
"""
open(f'{DST}/README.md','w').write(card)
open(f'{DST}/ROWCOUNTS.txt','w').write(''.join(f'data/{f}.jsonl {sum(1 for _ in open(f"{DST}/data/{f}.jsonl"))}\n' for f in sorted(os.listdir(f'{DST}/data')) for f in [f[:-6]]))
man=''
for root,_,fs in os.walk(DST):
  for f in sorted(fs):
    if f=='MANIFEST.sha256':continue
    q=os.path.join(root,f);man+=hashlib.sha256(open(q,'rb').read()).hexdigest()+'  '+os.path.relpath(q,DST)+'\n'
open(f'{DST}/MANIFEST.sha256','w').write(man)
random.seed(7)
samp={rt:random.sample([r for r in rows if r['role_type']==rt and not r.get('court_id')],min(3,sum(1 for r in rows if r['role_type']==rt and not r.get('court_id')))) for rt in set(r['role_type'] for r in rows if not r.get('court_id'))}
nl=collections.Counter(r['role_type'] for r in rows if not r.get('court_id'))
md=["# Phase 1 fix-up review (STAGED, NOT PUSHED)","Base: justicedao/ipfs_us_courts f12c75717a852dc2d81f1f293a7005251c52dd5f. Staged copy: hf_stage_fixup/","",
"## (1) AL coverage", f"Changed complete->partial_guard_stop: {dict(al)}. AL rows with coverage null are pre-existing non-state-county rows and were left unchanged.","",
"## (2) role_type rules (first match wins, unlinked rows)"]+[f"- {n}: `{f}` ~ /{rx}/i -> {rt}" for n,f,rx,rt in RULES]+["- R9_default -> other","Linked rows (court_id set): title~justice->justice; magistrate|commissioner|referee->magistrate; else judge.","",
"## Counts: unlinked (court_id null, n=%d) by role_type"%sum(nl.values())]+[f"- {k}: {v}" for k,v in nl.most_common()]+["","## Unlinked by state x role_type"]+[f"- {s} {rt}: {v}" for (s,rt),v in sorted(bystate.items())]+["","## All judges by (linked, role_type)"]+[f"- linked={a} {rt}: {v}" for (a,rt),v in sorted(cnt.items())]+["","## Rule hits"]+[f"- {k}: {v}" for k,v in sorted(rulec.items())]+["",
"## Recommendation / action","Flag every judge row with role_type AND remove unlinked committee_member/staff/other rows from `judges` (they are memberships, not seats; %d of %d removed duplicate a person kept as a seat). Removed rows saved in removed_judges.jsonl for audit."%(dup,len(removed)),"",
"## Row counts before -> after"]+[f"- {f}: {before[f]} -> {after[f]}" for f in before]+["","## Samples (unlinked)"]+[f"- {rt}: "+json.dumps([{k:r[k] for k in ('full_name','subdivision_iso','court_name','title','source_url')} for r in v],ensure_ascii=False) for rt,v in samp.items()]+["","Rule log: rules_applied.log. Card text appended in hf_stage_fixup/README.md."]
open(f'{REV}/REVIEW.md','w').write('\n'.join(md)+'\n')
m=''.join(hashlib.sha256(open(f'{REV}/{f}','rb').read()).hexdigest()+'  '+f+'\n' for f in sorted(os.listdir(REV)) if f!='MANIFEST.sha256')
open(f'{REV}/MANIFEST.sha256','w').write(m)
print('\n'.join(md))
