import sys,json,os
sys.path.insert(0,'/workspace/courts/collector')
import stage2 as S, us_fed as U
st=sys.argv[1];ST='/workspace/courts/staging'
def rd(f):return [json.loads(l) for l in open(f) if l.strip()] if os.path.exists(f) else []
if st=='courthouses':
  courts=rd(ST+'/courts.jsonl') or S.courts_retry()
  done={r['court_id'] for r in rd(ST+'/courthouses.jsonl')}|{S.sid('url',r['url']) for r in rd(ST+'/skips.jsonl')}
  # resume after last court with rows (courts processed in order)
  last=max([i for i,c in enumerate(courts) if c['court_id'] in done],default=-1)
  U.log('resume courthouses from index',last+1,'of',len(courts))
  S.courthouses(courts[last+1:])
elif st=='ncsc':
  U.ncsc()
  if not rd(ST+'/ncsc_state_links.jsonl'):U.log('NCSC_EMPTY: page 301 -> /homepage (removed, not a block); archive fallback not attempted in-run (Wayback 429 earlier)')
elif st=='state_rules':S.state_rules()
elif st=='review':
  import review;review.build()
