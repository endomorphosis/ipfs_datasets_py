import json,os,glob,collections,time
R='/workspace/courts/intl'; out={'generated':time.strftime('%Y-%m-%d %H:%M %Z'),'counts':{},'coverage':{},'validation':{}}
for cc in ('IE','EU'):
    d=f'{R}/staging/{cc}'
    if os.path.exists(d+'/ckpt.json'): out['coverage'][cc]=json.load(open(d+'/ckpt.json')).get('coverage')
    for f in glob.glob(d+'/*.jsonl'):
        rows=[json.loads(l) for l in open(f)]; k=f'{cc}/{os.path.basename(f)[:-6]}'; out['counts'][k]=len(rows)
        pk={'courts':'court_id','courthouses':'courthouse_id','forms':'form_id','rules':'url','judges':'name'}.get(os.path.basename(f)[:-6])
        c=collections.Counter(r.get(pk) for r in rows)
        out['validation'][k]={'dup_ids':sum(v-1 for v in c.values() if v>1),'missing_source':sum(1 for r in rows if not r.get('source_url')),'non_https':sum(1 for r in rows if r.get('transport')!='https')}
os.makedirs(R+'/review_intl/intl2',exist_ok=True); json.dump(out,open(R+'/review_intl/intl2/summary.json','w'),indent=1); open(R+'/review_intl/intl2/REVIEW_READY','w').write(out['generated'])
