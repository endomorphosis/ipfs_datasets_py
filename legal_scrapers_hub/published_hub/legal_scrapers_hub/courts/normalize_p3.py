"""Phase 3 -> world-courts-raw/v1. Uses SCHEMAS/maps from normalize.py (not modified). Applies exclusions + redactions."""
import json,hashlib,os,re,sys,shutil,resource,collections
from urllib.parse import urlparse
import pyarrow as pa, pyarrow.parquet as pq
src=open('/workspace/courts/normalized/normalize.py').read().split('def run(')[0]
exec(src)   # defines BASE,OUT,SV,SCHEMAS,CC,SUB,US,TERMS,MODE,gib,memok
phase='phase3'; d=f'{BASE}/data/{phase}'
CC.update({'NZ':'NZ','UK':'GB','IE':'IE','SG':'SG','ZA':'ZA','US':'US'})
for k,v in {'New Jersey':'NJ','New Hampshire':'NH','North Carolina':'NC','Tennessee':'TN','Washington':'WA','Oklahoma':'OK'}.items(): US[k]=v; SUB['US-'+k]='US-'+v
SUB.update({'AU-Victoria':'AU-VIC','AU-Western Australia':'AU-WA','CA-British Columbia':'CA-BC','CA-Nova Scotia':'CA-NS'})
# host-label match (phase 1/2 used a bare substring, which in phase 3 falsely hits washoecourts / darkecourts / statecourts / MagistrateCourts)
PAT=re.compile(r'((^|\.)canlii\.|(^|\.)austlii\.|law\.cornell\.edu|(^|\.)lii\.|(^|\.)ecourts[a-z]*\.)',re.I)
EM=re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'); JS=re.compile(r'(?i);jsessionid=[A-Za-z0-9._-]+')
WB={'US-Florida':('flcourts.gov','Florida'),'US-South Carolina':('sccourts.org','South Carolina')}
def wbnote(dom,name): return f'{dom} robots.txt: Disallow: / for User-agent * (checked 2026-10-26); {name} records obtained only from web.archive.org id_ replay, no live fetch; Wayback-only (TERMS.md)'
BESTEFFORT={'North Dakota trial/county court locations','Singapore State Courts','South Africa DOJ court directory'}
BE_NOTE='best-effort judge extraction: heuristic name/title parsing of general web pages (title/full_name re-cleaned by tools/p3_post.py); entries may be non-judges (news items, newsletters, staff) - verify against the roster_url before use'
def hosts(u):
    return urlparse(re.sub(r'^https?://web\.archive\.org/web/\d+[a-z_]*/','',u)).netloc if u else ''
def red(v,fx,col):
    if not isinstance(v,str): return v
    n=v
    if JS.search(n): n=JS.sub('',n); fx['jsessionid_stripped:'+col]+=1
    if EM.search(n): n=EM.sub('[email removed]',n); fx['email_redacted:'+col]+=1
    return n
# tier select
fs=[f for f in os.listdir(d) if f.endswith('.jsonl')]; tiers=collections.defaultdict(dict)
for f in fs:
    if f.endswith('_clean.jsonl'): tiers[f[:-12]]['clean']=f
    elif f.endswith('.dedup.jsonl'): tiers[f[:-12]]['dedup']=f
    else: tiers[f[:-6]]['raw']=f
sel={s:(t.get('clean') or t.get('dedup') or t['raw']) for s,t in sorted(tiers.items())}
# verify manifest
man={}
for l in open(d+'/MANIFEST.sha256'):
    if l.startswith('#') or not l.strip(): continue
    p=l.rstrip('\n').split('  ',2); man[p[2].split(' ')[0]]=(p[0],int(p[1]))
for f,(h,n) in man.items():
    hh=hashlib.sha256(); c=0
    with open(f'{d}/{f}','rb') as fh:
        for line in fh: hh.update(line); c+=line.strip()!=b''
    if hh.hexdigest()!=h or c!=n: sys.exit('MISMATCH '+f)
W={};buf=collections.defaultdict(list);infile=collections.Counter();out=collections.Counter();fx=collections.Counter()
removed=collections.Counter();ids=collections.defaultdict(collections.Counter);ents=collections.defaultdict(collections.Counter);occ=collections.Counter()
unm=[];wbrows=collections.Counter();berows=collections.Counter();bysrc=collections.Counter();modes=collections.Counter()
def flush(t):
    if not buf[t]: return
    if gib()<22 or memok()<4.5: sys.exit(f'PAUSE: disk {gib():.2f} / mem {memok():.2f}')
    if t not in W:
        os.makedirs(f'{OUT}/{phase}/{t}',exist_ok=True)
        W[t]=pq.ParquetWriter(f'{OUT}/{phase}/{t}/part-0000.parquet',SCHEMAS[t],compression='zstd')
    W[t].write_table(pa.Table.from_pylist(buf[t],schema=SCHEMAS[t])); buf[t].clear()
for s,f in sel.items():
    for line in open(f'{d}/{f}'):
        if not line.strip(): continue
        r=json.loads(line); t=r.pop('type',None); infile[t]+=1
        if t not in SCHEMAS: unm.append((f,'unknown type',t)); continue
        j=r.pop('jurisdiction')
        if j in SUB: sub=SUB[j]; ci,lvl,al,a1=sub.split('-')[0],'state',4,sub
        elif j in CC: ci,lvl,al,a1=CC[j],'national',2,None
        else: unm.append((f,'unmapped jurisdiction',j)); continue
        g=lambda k: (r.pop(k,None) or None)
        sn=g('source_name'); fo=g('found_on'); lic=g('license'); rm=r.pop('retrieval_mode'); rd=g('retrieval_date')
        o={}
        if t=='court':
            o.update(name=g('name'),address=g('address'),court_type=g('court_type_hint'),website=g('website'))
            o['postcode']=r.get('zip') or (r.get('postcodes') or [None])[0]
            su=g('source_url') or o['website'] or fo
            key=(o['name'] or '')+'|'+(o['address'] or '')+'|'+(r.get('slug') or r.get('name_norm') or '')
        elif t=='rule':
            o.update(title=g('title'),rule_url=g('url')); su=o['rule_url'] or fo; key=(o['rule_url'] or '')+'|'+(o['title'] or '')
        elif t=='form':
            o.update(title=g('title'),file_url=g('file_url'),file_format=g('file_format')); su=o['file_url'] or fo; key=(o['file_url'] or '')+'|'+(o['title'] or '')
        else:
            o.update(full_name=g('full_name'),title=g('title'),court=g('court'),court_type=g('court_type'),commission_date=g('commission_date'),termination_date=g('termination_date'),roster_url=g('roster_url'))
            su=g('source_url') or o['roster_url'] or fo; key=(o['roster_url'] or '')+'|'+(o['full_name'] or '')
        # exclusion (same rule as phase1/2: host of source_url / found_on, or source name)
        hs=hosts(su)+' '+hosts(fo)
        m=PAT.search(hs) or PAT.search(sn or '')
        if m:
            removed[(t,sn,'ecourts' if 'ecourts' in m.group(0).lower() else m.group(0).lower())]+=1; continue
        extras=dict(r); tm=TERMS.get(sn)
        if tm: extras['terms_row']=tm
        if lic=='see TERMS.md' and tm: lic='see TERMS.md: '+tm['terms']
        if j in WB:
            note=wbnote(*WB[j]); lic=(lic or '')+' | '+note; extras['robots_note']=note; extras['wayback_only']=True; wbrows[(j,t,rm)]+=1
        if t=='judge' and sn in BESTEFFORT:
            extras['best_effort']=True; extras['best_effort_note']=BE_NOTE; berows[(sn,t)]+=1
        extras['retrieval_mode_raw']=rm
        ek=f'wc1e:{t}:'+hashlib.sha256(f'{t}|{j}|{sn}|{key}'.encode()).hexdigest()[:24]
        occ[(ek,fo,f)]+=1
        rid=f'wc1:{t}:'+hashlib.sha256(f'{ek}|{fo}|{f}|{occ[(ek,fo,f)]}'.encode()).hexdigest()[:24]
        o.update(id=rid,entity_key=ek,record_type=t,schema_version=SV,country_iso=ci,jurisdiction_level=lvl,admin_level=al,admin1=a1,municipality=None,municipality_code=None,
            jurisdiction_raw=j,source_name=sn,source_url=su,found_on=fo,fetch_mode=MODE.get(rm,rm),retrieval_date=rd,licence=lic,phase=phase,source_file=f)
        o['metadata_json']=json.dumps(extras,ensure_ascii=False,sort_keys=True)
        for k in list(o): o[k]=red(o[k],fx,k)
        buf[t].append(o); out[t]+=1; ids[t][rid]+=1; ents[t][ek]+=1; bysrc[(t,sn)]+=1; modes[(t,o['fetch_mode'])]+=1
        if len(buf[t])>=2000: flush(t)
for t in list(buf): flush(t)
for w in W.values(): w.close()
back={t:pq.ParquetFile(f'{OUT}/{phase}/{t}/part-0000.parquet').metadata.num_rows for t in W}
rep={'phase':phase,'schema':SV,'manifest_entries':len(man),'files_used':sel,'in_by_type':dict(infile),'in_total':sum(infile.values()),
 'removed_total':sum(removed.values()),'removed':[{'type':a,'source_name':b,'matched':c,'rows':v} for (a,b,c),v in removed.items()],
 'out_by_type':dict(out),'parquet_rows':back,'redactions':dict(fx),
 'wayback_only_rows':{f'{a}|{b}|{c}':v for (a,b,c),v in wbrows.items()},'best_effort_judge_rows':{f'{a}|{b}':v for (a,b),v in berows.items()},
 'duplicate_ids':{t:sum(1 for v in ids[t].values() if v>1) for t in out},
 'duplicate_entity_keys':{t:{'distinct':len(ents[t]),'extra_rows':sum(v-1 for v in ents[t].values() if v>1)} for t in out},
 'unmapped':unm,'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024,'free_disk_gib_end':round(gib(),2)}
json.dump(rep,open(f'{OUT}/{phase}/VALIDATION.json','w'),indent=1); print(json.dumps(rep,indent=1))
