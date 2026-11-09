import json,requests,time,os,re,sys
UA='world-laws-municipal-collector/0.1 (research on open US municipal codes; contact via benjamin barber)'
c=json.load(open('raw/cand_seed.json'))
q=sorted({o['qid'] for o in c if o['already_covered']=='no' and o['qid'] and re.match(r'Q\d+$',o['qid'])})
outf='out/wikidata_resolved.jsonl'
done=set()
if os.path.exists(outf):
    for l in open(outf): done.add(json.loads(l)['qid'])
todo=[x for x in q if x not in done]
print(len(q),len(todo),flush=True)
S=requests.Session(); S.headers.update({'User-Agent':UA,'Accept':'application/sparql-results+json'})
B=80
for i in range(0,len(todo),B):
    b=todo[i:i+B]
    qs='SELECT ?q ?iso ?gnis ?site WHERE { VALUES ?q { %s } OPTIONAL { ?q wdt:P131* ?s . ?s wdt:P300 ?iso . FILTER(STRSTARTS(?iso,"US-")) } OPTIONAL{?q wdt:P590 ?gnis} OPTIONAL{?q wdt:P856 ?site} }'%' '.join('wd:'+x for x in b)
    for att in range(4):
        r=S.post('https://query.wikidata.org/sparql',data={'query':qs},timeout=90)
        if r.status_code==200: break
        time.sleep(10*(att+1))
    else:
        print('fail batch',i,r.status_code,flush=True); continue
    res={}
    for row in r.json()['results']['bindings']:
        qq=row['q']['value'].rsplit('/',1)[1]
        d=res.setdefault(qq,{'qid':qq,'state':'','gnis':set(),'site':set()})
        if 'iso' in row and not d['state']: d['state']=row['iso']['value'][3:5] if len(row['iso']['value'])>=5 else ''
        if 'gnis' in row: d['gnis'].add(row['gnis']['value'].lstrip('0'))
        if 'site' in row: d['site'].add(row['site']['value'])
    with open(outf,'a') as f:
        for x in b:
            d=res.get(x,{'qid':x,'state':'','gnis':set(),'site':set()})
            f.write(json.dumps({'qid':x,'state':d['state'],'gnis':sorted(d['gnis']),'site':sorted(d['site'])})+'\n')
    if (i//B)%10==0: print(i,flush=True)
    time.sleep(2)
print('done')
