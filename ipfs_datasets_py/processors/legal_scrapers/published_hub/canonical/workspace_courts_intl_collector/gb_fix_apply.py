#!/usr/bin/env python3
"""Apply GB fix: offline postcode relabel for all rows; refetched structured addresses where available. Validates and writes review."""
import sys,os,json,time,shutil,collections
sys.path.insert(0,'/workspace/courts/intl/collector')
from gb_geo import sub_from,WTOWN
R='/workspace/courts/intl'; D=R+'/staging/GB'; RV=R+'/review_intl'
src=D+'/courts.orig_20261103.jsonl'
if not os.path.exists(src): shutil.copy(D+'/courts.jsonl',src); shutil.copy(D+'/courthouses.jsonl',D+'/courthouses.orig_20261103.jsonl')
courts=[json.loads(l) for l in open(src)]; chs=[json.loads(l) for l in open(D+'/courthouses.orig_20261103.jsonl')]
fx={}
if os.path.exists(D+'/gb_fix_ckpt.jsonl'):
    for l in open(D+'/gb_fix_ckpt.jsonl'):
        x=json.loads(l)
        if x.get('ok'): fx[x['old_id']]=x
oldpc={h['court_id']:h.get('postal_code') for h in chs}
outc=[];outh=[];stats=collections.Counter()
for c in courts:
    oid=c['court_id']; slug=c['source_url'].rsplit('/',1)[1]; f=fx.get(oid)
    if f: sub,how=f['sub'],f['how']
    else: sub,how=sub_from(oldpc.get(oid),c['name']+' '+slug.replace('-',' ').title())
    if how=='default_no_postcode' and not f: how='unverified_no_postcode'
    nid=f'GB-{sub[3:]}-{slug}'; stats[f'{c["subdivision_iso"]}->{sub}']+=1; stats['sub_method:'+how]+=1
    c2={**c,'subdivision_iso':sub,'court_id':nid,'subdivision_method':how}
    if f: c2['sha256']=f['sha']
    outc.append(c2)
    if f:
        for i,a in enumerate(f['addrs']):
            outh.append({**c2,'courthouse_id':nid+('-visit' if i==0 else f'-addr{i+1}'),'court_id':nid,'street':a['street'],'locality':a['locality'],'postal_code':a['postal_code'],
                'region':sub,'lat':f['ll'][0] if i==0 else None,'lon':f['ll'][1] if i==0 else None,'phone':None,'email':None,'address_source':a['kind']})
            for k in ('level','jurisdiction_type','parent_court_id','name_en','subdivision_method'): outh[-1].pop(k,None)
    else:
        for h in chs:
            if h['court_id']==oid: outh.append({**h,'court_id':nid,'courthouse_id':nid+'-visit','subdivision_iso':sub,'region':sub,'address_source':'legacy_text_unverified'})
ids=collections.Counter(x['court_id'] for x in outc); hids=collections.Counter(x['courthouse_id'] for x in outh); cset=set(ids)
val=dict(courts=len(outc),courthouses=len(outh),dup_court_ids=sum(v-1 for v in ids.values() if v>1),dup_courthouse_ids=sum(v-1 for v in hids.values() if v>1),
  bad_fk=sum(1 for h in outh if h['court_id'] not in cset),courthouses_missing_postcode=sum(1 for h in outh if not h.get('postal_code')),
  sct_with_nonsct_postcode=sum(1 for h in outh if h['subdivision_iso']!='GB-SCT' and sub_from(h.get('postal_code'))[0]=='GB-SCT' and h.get('postal_code')),
  refetched=len(fx),courts_without_address=len(cset-{h['court_id'] for h in outh}))
for n,rows in (('courts',outc),('courthouses',outh)):
    with open(f'{D}/{n}.jsonl','w') as fo:
        for x in rows: fo.write(json.dumps(x,ensure_ascii=False)+'\n')
rep={'generated':time.strftime('%Y-%m-%d %H:%M %Z'),'validation':val,'relabel':dict(stats),'backups':['GB/courts.orig_20261103.jsonl','GB/courthouses.orig_20261103.jsonl']}
json.dump(rep,open(RV+'/gb_fix_report.json','w'),indent=1); print(json.dumps(rep,indent=1))
