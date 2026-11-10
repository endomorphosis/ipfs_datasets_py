#!/usr/bin/env python3
"""Official state court rules index collector (stage only). Sequential, 1 req/10s+, robots/Crawl-delay honored, HTTPS only."""
import sys,os,json,re,urllib.parse,hashlib
sys.path.insert(0,'/workspace/courts/collector')
import us_fed as U
from us_fed import log,fetch,links,sid,now
OUT='/workspace/courts/staging/state_rules/official';os.makedirs(OUT+'/files',exist_ok=True)
S=[('AK','https://courts.alaska.gov/rules/index.htm'),('AZ','https://www.azcourts.gov/rules'),('CT','https://www.jud.ct.gov/pb.htm'),('DE','https://courts.delaware.gov/rules/'),('HI','https://www.courts.state.hi.us/legal_references/rules/rulesOfCourt'),('KS','https://www.kscourts.gov/Rules-Orders/Rules'),('MI','https://www.courts.michigan.gov/rules-administrative-orders-and-jury-instructions/'),('MN','https://www.revisor.mn.gov/court_rules/'),('NV','https://www.leg.state.nv.us/CourtRules/'),('ND','https://www.ndcourts.gov/legal-resources/rules'),('OH','https://www.supremecourt.ohio.gov/laws-rules/ohio-rules-of-court/'),('OK','https://www.oscn.net/applications/oscn/index.asp?ftdb=STOKRU'),('OR','https://www.courts.oregon.gov/rules/Pages/default.aspx'),('SD','https://sdlegislature.gov/Statutes/15'),('UT','https://legacy.utcourts.gov/rules/'),('WA','https://www.courts.wa.gov/court_rules/'),('WV','https://www.courtswv.gov/legal-community/court-rules'),('LA','https://www.lasc.org/Rules'),('TN','https://www.tncourts.gov/rules'),
 ('CA','https://courts.ca.gov/forms-rules/rules-court'),('MD','https://www.mdcourts.gov/rules'),('NE','https://nebraskajudicial.gov/supreme-court-rules'),('VT','https://www.vtcourts.gov/attorneys/rules'),('MT','https://courts.mt.gov/Courts/rules/'),('RI','https://www.courts.ri.gov/Legal-Resources/Pages/court-rules.aspx'),('ME','https://www.courts.maine.gov/rules/index.html'),
 ('TX','https://www.txcourts.gov/rules-forms/rules-standards/')]
SKIP={'SC':'crawl-delay-limited: robots Disallow / + Crawl-delay 120000s; not fetched','NM':'nmonesource.com (NM Compilation Commission, official) but page 403 + robots Disallow /; skipped, no bypass','ID':'URL unresolved (rules page 404)','NY':'nycourts.gov rules page 403 on URL fix; skipped',**{s:'403 at probe; skipped per CoS' for s in 'CO DC FL KY MO NH NJ WY'.split()}}
RULE=re.compile(r'rule|court-rules|courtrules|procedure|\.pdf',re.I)
def run(st,idx,cap=None):
  done_f=f'{OUT}/{st}.jsonl'
  if os.path.exists(done_f+'.done'):return
  cap=cap or (60 if st=="TX" else 300);delay=720 if st=="TX" else 10
  r=fetch(idx,delay=delay)
  if not r:log('STATE_FAIL',st,idx);open(f'{OUT}/skips.jsonl','a').write(json.dumps(dict(state=st,url=idx,reason='index fetch fail/robots'))+'\n');return
  host=urllib.parse.urlsplit(r[0]).netloc;seen=set();n=0
  cand=[(h,t) for h,t in links(r[0],r[1]) if h.startswith('https://') and urllib.parse.urlsplit(h).netloc==host and RULE.search(h+' '+t) and h.split('#')[0]!=r[0]]
  with open(done_f,'w') as o:
    for h,t in cand:
      h=h.split('#')[0]
      if h in seen or n>=cap:continue
      seen.add(h);fn=f'{OUT}/files/{st}_{sid(h)}';g=fetch(h,delay=delay,stream_to=fn)
      if not g:continue
      fu,sha,nb=g
      o.write(json.dumps(dict(rule_id=sid(st,h),rule_set=f'{st} court rules',citation='',title=t,text=None,court_id=None,subdivision_iso='US-'+st,effective_date=None,version='',file_url=fu,file_sha256=sha,file_bytes=nb,local_path=fn,content_sha256=sha,source_url=r[0],fetched_at=now(),archive_source='live',archive_timestamp=None,license='see source terms (state-specific)',terms_note='',robots_note='robots.txt honored',transport='https'))+'\n');o.flush();n+=1
  open(done_f+'.done','w').write(now());log('STATE',st,'rows',n,'of',len(cand),'candidates')
if __name__=='__main__':
  log('STATE_RULES2 START pid',os.getpid())
  with open(f'{OUT}/skips.jsonl','a') as f:
    for k,v in SKIP.items():f.write(json.dumps(dict(state=k,reason=v))+'\n')
  for st,u in S:
    try:run(st,u)
    except SystemExit:raise
    except Exception as e:log('STATE_ERR',st,repr(e)[:200])
  log('STATE_RULES2 DONE')
