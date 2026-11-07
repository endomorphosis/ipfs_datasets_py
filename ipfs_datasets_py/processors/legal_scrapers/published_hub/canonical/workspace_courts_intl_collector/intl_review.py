import json,os,glob,collections,time
R='/workspace/courts/intl'; O=R+'/review_intl'; os.makedirs(O,exist_ok=True)
cnt={};bad=collections.Counter();ids=collections.Counter()
req={'courts':['court_id','name'],'courthouses':['courthouse_id','court_id'],'judges':['name','court_id','title'],'forms':['url','sha256'],'rules':['rule_set','section','url']}
cov={}
for d in sorted(glob.glob(R+'/staging/*/')):
    cc=d.rstrip('/').rsplit('/',1)[1]; ck=d+'ckpt.json'
    cov[cc]=json.load(open(ck)).get('coverage',{}) if os.path.exists(ck) else {}
    for f in glob.glob(d+'*.jsonl'):
        cfg=os.path.basename(f)[:-6]; n=0
        for l in open(f):
            r=json.loads(l); n+=1
            for k in req.get(cfg,[]):
                if not r.get(k): bad[f'{cc}/{cfg}/missing_{k}']+=1
            if r.get('source')!='live': bad[f'{cc}/{cfg}/nonlive']+=1
            for pk in ('court_id','courthouse_id'):
                if cfg==pk.split('_')[0]+'s': ids[(cfg,r.get(pk))]+=1
        cnt[f'{cc}/{cfg}']=n
dups={f'{k[0]}:{k[1]}':v for k,v in ids.items() if v>1}
json.dump({'generated':time.strftime('%Y-%m-%d %H:%M %Z'),'counts':cnt,'coverage':cov,'validation':{'missing_or_nonlive':dict(bad),'duplicate_ids':dups},
 'skips':'see TERMS_REVIEW.md + dead targets (Legifrance 403, judiciary.uk 202, UKSC 404, justiz.de forms 404, bccourts)'},open(O+'/summary.json','w'),indent=1)
open(O+'/REVIEW_READY','w').write(time.strftime('%Y-%m-%dT%H:%M:%S%z')+'\n')
