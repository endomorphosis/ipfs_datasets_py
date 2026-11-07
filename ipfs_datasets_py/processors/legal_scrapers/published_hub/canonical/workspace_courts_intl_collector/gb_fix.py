#!/usr/bin/env python3
"""GB fix: re-fetch HMCTS court pages (live, polite) -> correct subdivision (postcode) + structured address. Writes *.v2 then swaps with backup. Stage only."""
import sys,os,json,re,time,shutil
sys.path.insert(0,'/workspace/courts/intl/collector')
import intl_collect as ic
from gb_geo import sub_from,parse_addresses
ic.LOG=ic.ROOT+'/logs/gb_fix.log'
D=ic.ST+'/GB'; RV=ic.ROOT+'/review_intl'
def fin(marker,why):
    marker={'STOPPED_INTL':'STOPPED_GB_FIX'}.get(marker,marker)
    open(f'{ic.ROOT}/{marker}','w').write(time.strftime('%Y-%m-%dT%H:%M:%S%z')+' '+why+'\n'); ic.log('FINISH',marker,why); sys.exit(0 if 'DONE' in marker else 3)
ic.finish=fin
old=[json.loads(l) for l in open(f'{D}/courts.orig_20261103.jsonl')]
ck=f'{D}/gb_fix_ckpt.jsonl'; done={json.loads(l)['old_id'] for l in open(ck)} if os.path.exists(ck) else set()
ic.log('GB_FIX START pid',os.getpid(),'courts',len(old),'done',len(done))
for c in old:
    if c['court_id'] in done: continue
    try: r=ic.fetch(c['source_url'])
    except ic.HostStop as h: ic.log('HOSTSTOP',h); break
    rec={'old_id':c['court_id'],'ok':False}
    if r:
        b=r[0].decode('utf-8','ignore'); addrs,ll=parse_addresses(b)
        pc=next((a['postal_code'] for a in addrs if a.get('postal_code')),None)
        sub,how=sub_from(pc,ic.txt(b)); slug=c['source_url'].rsplit('/',1)[1]
        rec.update(ok=True,sub=sub,how=how,court_id=f'GB-{sub[3:]}-{slug}',sha=ic.sha(r[0]),addrs=addrs,ll=ll)
    open(ck,'a').write(json.dumps(rec)+'\n')
ic.log('GB_FIX fetch loop end')
