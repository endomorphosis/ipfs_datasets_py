import json,hashlib,os,re,sys,shutil,resource,collections
import pyarrow as pa, pyarrow.parquet as pq
BASE='/workspace/courts'; OUT=BASE+'/normalized'
SV='world-courts-raw/v1'
def gib(): return shutil.disk_usage('/workspace').free/2**30
def memok():
    m=int([l for l in open('/proc/meminfo') if l.startswith('MemAvailable')][0].split()[1])/2**20
    return m
common=[('id',pa.string(),False),('record_type',pa.string(),False),('schema_version',pa.string(),False),
 ('country_iso',pa.string(),False),('jurisdiction_level',pa.string(),False),('admin_level',pa.int64(),True),
 ('admin1',pa.string(),True),('municipality',pa.string(),True),('municipality_code',pa.string(),True),
 ('entity_key',pa.string(),False),('jurisdiction_raw',pa.string(),False),('source_name',pa.string(),True),('source_url',pa.string(),True),
 ('found_on',pa.string(),True),('fetch_mode',pa.string(),False),('retrieval_date',pa.string(),True),
 ('licence',pa.string(),True),('phase',pa.string(),False),('source_file',pa.string(),False)]
spec={'court':[('name',pa.string(),True),('address',pa.string(),True),('postcode',pa.string(),True),('court_type',pa.string(),True),('website',pa.string(),True)],
 'rule':[('title',pa.string(),True),('rule_url',pa.string(),True)],
 'form':[('title',pa.string(),True),('file_url',pa.string(),True),('file_format',pa.string(),True)],
 'judge':[('full_name',pa.string(),True),('title',pa.string(),True),('court',pa.string(),True),('court_type',pa.string(),True),('commission_date',pa.string(),True),('termination_date',pa.string(),True),('roster_url',pa.string(),True)]}
SCHEMAS={t:pa.schema([pa.field(n,ty,nullable=nl) for n,ty,nl in common+s+[('metadata_json',pa.string(),False)]],metadata={b'schema':SV.encode(),b'record_type':t.encode()}) for t,s in spec.items()}
CC={'Argentina':'AR','Australia':'AU','Austria':'AT','Bangladesh':'BD','Belgium':'BE','Brazil':'BR','Brazil (CNJ)':'BR','Canada':'CA','Chile':'CL','Czechia':'CZ','Denmark':'DK','EU':'EU','EU (e-Justice court finder)':'EU','France (annuaire)':'FR','Germany':'DE','Ghana':'GH','India':'IN','Ireland':'IE','Italy':'IT','Kenya':'KE','Mexico':'MX','Netherlands':'NL','New Zealand':'NZ','Peru':'PE','Philippines':'PH','Portugal':'PT','Singapore':'SG','South Africa':'ZA','Spain':'ES','Sri Lanka':'LK','Turkey':'TR','UK':'GB','US':'US','International':'ZZ','Council of Europe':'ZZ'}
SUB={'IN-Allahabad':'IN-UP','IN-Andhra Pradesh':'IN-AP','IN-Bombay':'IN-MH','IN-Calcutta':'IN-WB','IN-Chhattisgarh':'IN-CT','IN-Delhi':'IN-DL','IN-Gauhati':'IN-AS','IN-Gujarat':'IN-GJ','IN-Himachal Pradesh':'IN-HP','IN-Jammu & Kashmir and Ladakh':'IN-JK','IN-Jharkhand':'IN-JH','IN-Karnataka':'IN-KA','IN-Madhya Pradesh':'IN-MP','IN-Madras':'IN-TN','IN-Manipur':'IN-MN','IN-Meghalaya':'IN-ML','IN-Orissa':'IN-OR','IN-Patna':'IN-BR','IN-Rajasthan':'IN-RJ','IN-Sikkim':'IN-SK','IN-Telangana':'IN-TG','IN-Tripura':'IN-TR','IN-Uttarakhand':'IN-UT',
 'UK-England & Wales':'GB-EAW','UK-Northern Ireland':'GB-NIR','UK-Scotland':'GB-SCT',
 'AU-ACT':'AU-ACT','AU-New South Wales':'AU-NSW','AU-Queensland':'AU-QLD','AU-South Australia':'AU-SA','AU-Tasmania':'AU-TAS',
 'CA-Alberta':'CA-AB','CA-Manitoba':'CA-MB','CA-Northwest Territories':'CA-NT','CA-Nova Scotia':'CA-NS','CA-Nunavut':'CA-NU','CA-Ontario':'CA-ON','CA-Quebec':'CA-QC','CA-Saskatchewan':'CA-SK','CA-Yukon':'CA-YT'}
US=dict(Alabama='AL',Alaska='AK',Arizona='AZ',Arkansas='AR',California='CA',Colorado='CO',Connecticut='CT',Delaware='DE',Florida='FL',Georgia='GA',Hawaii='HI',Idaho='ID',Illinois='IL',Indiana='IN',Iowa='IA',Kansas='KS',Kentucky='KY',Louisiana='LA',Maine='ME',Maryland='MD',Massachusetts='MA',Minnesota='MN',Mississippi='MS',Missouri='MO',Montana='MT',Nebraska='NE',Nevada='NV',Ohio='OH',Oregon='OR',Pennsylvania='PA',Texas='TX',Utah='UT',Vermont='VT',Virginia='VA',Wisconsin='WI',Wyoming='WY')
US.update({'New Mexico':'NM','New York':'NY','North Dakota':'ND','Rhode Island':'RI','South Carolina':'SC','South Dakota':'SD','West Virginia':'WV','District of Columbia':'DC'})
for k,v in US.items(): SUB['US-'+k]='US-'+v
# TERMS per-source rows
TERMS={}
for l in open(BASE+'/TERMS.md'):
    c=[x.strip() for x in l.strip().strip('|').split('|')]
    if len(c)==5 and c[0] not in('source','---') and not c[0].startswith('http'): TERMS.setdefault(c[0],{'robots':c[3],'terms':c[4]})
FL_NOTE='flcourts.gov robots.txt: Disallow: / for User-agent * (checked 2026-10-26); record obtained only from web.archive.org id_ replay, no live fetch; future Florida work Wayback-only (TERMS.md)'
MODE={'live':'live','wayback-cdx':'wayback','wayback':'wayback','commoncrawl':'commoncrawl'}
def geo(j):
    if j in SUB: s=SUB[j]; return s.split('-')[0],'state',4,s
    if j in CC: return CC[j],'national',2,None
    return None,None,None,None
def run(phase):
    d=f'{BASE}/data/{phase}'; man=[l.split() for l in open(d+'/MANIFEST.sha256') if l.strip() and not l.startswith('#')]
    for h,n,f,*_ in man:   # re-verify
        hh=hashlib.sha256(); c=0
        with open(f'{d}/{f}','rb') as fh:
            for line in fh: hh.update(line); c+=line.strip()!=b''
        if hh.hexdigest()!=h or c!=int(n): sys.exit(f'MISMATCH {phase}/{f}')
    W={};buf=collections.defaultdict(list);st=collections.Counter();nulls=collections.defaultdict(collections.Counter)
    ids=collections.defaultdict(collections.Counter);unm=[];occ=collections.Counter();ents=collections.defaultdict(collections.Counter);infile=collections.Counter()
    def flush(t):
        if not buf[t]: return
        if gib()<20 or memok()<4.5: sys.exit(f'PAUSE: disk {gib():.2f} GiB / mem {memok():.2f}')
        if t not in W:
            os.makedirs(f'{OUT}/{phase}/{t}',exist_ok=True)
            W[t]=pq.ParquetWriter(f'{OUT}/{phase}/{t}/part-0000.parquet',SCHEMAS[t],compression='zstd')
        W[t].write_table(pa.Table.from_pylist(buf[t],schema=SCHEMAS[t])); buf[t].clear()
    for h,n,f,*_ in man:
        for line in open(f'{d}/{f}'):
            if not line.strip(): continue
            r=json.loads(line); t=r.pop('type',None); infile[t]+=1
            if t not in SCHEMAS: unm.append((f,'unknown type',t)); continue
            j=r.pop('jurisdiction'); ci,lvl,al,a1=geo(j)
            if ci is None: unm.append((f,'unmapped jurisdiction',j)); continue
            g=lambda k: (r.pop(k,None) or None)
            src=g('source_name'); fo=g('found_on'); lic=g('license'); rm=r.pop('retrieval_mode'); rd=g('retrieval_date')
            o={}
            if t=='court':
                o.update(name=g('name'),address=g('address'),court_type=g('court_type_hint'),website=g('website'))
                pc=r.get('zip') or (r.get('postcodes') or [None])[0]; o['postcode']=pc
                su=g('source_url') or o['website'] or fo
                key=(o['name'] or '')+'|'+(o['address'] or '')+'|'+(r.get('slug') or r.get('name_norm') or '')
            elif t=='rule':
                o.update(title=g('title'),rule_url=g('url')); su=o['rule_url'] or fo; key=(o['rule_url'] or '')+'|'+(o['title'] or '')
            elif t=='form':
                o.update(title=g('title'),file_url=g('file_url'),file_format=g('file_format')); su=o['file_url'] or fo; key=(o['file_url'] or '')+'|'+(o['title'] or '')
            else:
                o.update(full_name=g('full_name'),title=g('title'),court=g('court'),court_type=g('court_type'),commission_date=g('commission_date'),termination_date=g('termination_date'),roster_url=g('roster_url'))
                su=g('source_url') or o['roster_url'] or fo
                key=(r.get('fjc_nid') and 'fjc:'+r['fjc_nid']) or ((o['roster_url'] or '')+'|'+(o['full_name'] or ''))
            extras=dict(r); tm=TERMS.get(src)
            if tm: extras['terms_row']=tm
            if lic=='see TERMS.md' and tm: lic='see TERMS.md: '+tm['terms']
            if j=='US-Florida': lic=(lic or '')+' | '+FL_NOTE; extras['robots_note']=FL_NOTE
            extras['retrieval_mode_raw']=rm
            ek=f'wc1e:{t}:'+hashlib.sha256(f'{t}|{j}|{src}|{key}'.encode()).hexdigest()[:24]
            occ[(ek,fo,f)]+=1
            rid=f'wc1:{t}:'+hashlib.sha256(f'{ek}|{fo}|{f}|{occ[(ek,fo,f)]}'.encode()).hexdigest()[:24]
            ents[t][ek]+=1
            o.update(id=rid,entity_key=ek,record_type=t,schema_version=SV,country_iso=ci,jurisdiction_level=lvl,admin_level=al,admin1=a1,municipality=None,municipality_code=None,
                jurisdiction_raw=j,source_name=src,source_url=su,found_on=fo,fetch_mode=MODE.get(rm,rm),retrieval_date=rd,licence=lic,phase=phase,source_file=f,
                metadata_json=json.dumps(extras,ensure_ascii=False,sort_keys=True))
            buf[t].append(o); st[t]+=1; ids[t][rid]+=1
            for k in ('source_url','retrieval_date','licence','admin1','name','title','full_name','file_url','rule_url'):
                if k in o: nulls[t][k]+= o[k] is None
            if o['country_iso']=='ZZ': nulls[t]['country_iso=ZZ']+=1
            if len(buf[t])>=2000: flush(t)
    for t in list(buf): flush(t)
    for w in W.values(): w.close()
    # read back counts
    back={t:pq.ParquetFile(f'{OUT}/{phase}/{t}/part-0000.parquet').metadata.num_rows for t in W}
    rep={'phase':phase,'schema':SV,'manifest_entries':len(man),'manifest_records':sum(int(x[1]) for x in man),'in_by_type':dict(infile),'out_by_type':dict(st),'parquet_rows':back,
      'null_rates':{t:{k:round(v/st[t],4) for k,v in nulls[t].items()} for t in st},
      'duplicate_ids':{t:{'ids_with_dupes':sum(1 for v in ids[t].values() if v>1),'extra_rows':sum(v-1 for v in ids[t].values() if v>1)} for t in st},
      'duplicate_entity_keys':{t:{'keys_with_dupes':sum(1 for v in ents[t].values() if v>1),'extra_rows':sum(v-1 for v in ents[t].values() if v>1),'distinct':len(ents[t])} for t in st},
      'exact_repeat_rows_same_page':sum(v-1 for v in occ.values() if v>1),
      'unmapped':unm,'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024,'free_disk_gib_end':round(gib(),2)}
    if gib()<20: sys.exit('PAUSE before report')
    json.dump(rep,open(f'{OUT}/{phase}/VALIDATION.json','w'),indent=1); print(json.dumps(rep,indent=1))
run(sys.argv[1])
