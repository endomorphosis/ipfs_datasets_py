import json,re,collections,urllib.parse,csv
R='raw/'
tab=json.load(open(R+'covered_table.json'))
cw=[json.loads(l) for l in open(R+'crosswalk.jsonl')]
g2cw={c['gnis']:c for c in cw}
for c in cw:
    for a in c.get('gnis_alt') or []: g2cw.setdefault(a,c)
qid2gnis=collections.defaultdict(set)
for c in cw:
    for q in [c.get('qid')]+(c.get('qids') or []):
        if q: qid2gnis[q].add(c['gnis']); qid2gnis[q].update(c.get('gnis_alt') or [])
covg={t['gnis'] for t in tab}
for t in tab:
    c=g2cw.get(t['gnis'])
    if c:
        t['name']=t['name'] or c['name']; t['state']=t['state'] or c.get('state_code','')
print('covered w/o state',sum(1 for t in tab if not t['state']),'w/o name',sum(1 for t in tab if not t['name']))
gaz={}
import csv as _c
for fn in ['raw/census/2023_Gaz_place_national.txt','raw/census/2023_Gaz_cousubs_national.txt']:
    for r in _c.DictReader(open(fn,encoding='utf-8',errors='ignore'),delimiter='\t'):
        r={k.strip():(v or '').strip() for k,v in r.items() if k}
        gaz.setdefault(r['ANSICODE'].lstrip('0'),(r['USPS'],r['FUNCSTAT'],r['NAME']))
print('gaz',len(gaz))
def norm(n):
    n=(n or '').lower()
    n=re.sub(r'\b(city and borough|city and county|city|town|village|borough|township|municipality|of|the|charter|metro|government)\b','',n)
    return re.sub(r'[^a-z]','',n)
covname={(norm(t['name']),t['state']) for t in tab if t['name'] and t['state']}
covname_nostate=collections.Counter(norm(t['name']) for t in tab if t['name'])
cty=json.load(open(R+'county/county_covered.json'))
# county FIPS pack
countyfips={k.replace('us-county-','') for k in cty}
def tld_state(u):
    h=urllib.parse.urlparse(u).netloc.lower()
    m=re.search(r'\.([a-z]{2})\.us$',h)
    if m: return m.group(1).upper()
    return ''
def host_platform(u):
    h=urllib.parse.urlparse(u).netloc.lower()
    for k,v in [('municode.com','municode'),('amlegal.com','amlegal'),('ecode360.com','ecode360'),('municipal.codes','municipal.codes (Code Publishing/General Code)'),('codepublishing.com','codepublishing'),('municipalcodeonline.com','civicplus_municipalcodeonline'),('encodeplus.com','encodeplus'),('qcode.us','qcode.us'),('sterlingcodifiers.com','sterling_codifiers'),('franklinlegal.net','franklin_legal'),('citycode.net','citycode.net'),('civicplus.com','civicplus'),('revize.com','revize'),('.pdf','official_pdf')]:
        if k in h or k in u.lower(): return v
    return 'official_site'
GATED={'municode':'yes: Cloudflare/bot challenge possible; robots Content-Signal ai-train=no','amlegal':'yes: bot challenge possible; robots ai-train=no','ecode360':'yes: ToS personal-use; robots ai-train=no','qcode.us':'yes: Cloudflare 301 on robots','franklin_legal':'yes: Cloudflare 301 on robots','municipal.codes (Code Publishing/General Code)':'partial: ai-train=no; migrating to eCode360','codepublishing':'partial: robots disallows search/PDF'}
out=[];stats=collections.Counter()
seen=set()
def add(src,r,kind):
    q=r.get('qid'); gn=str(r.get('gnis') or ''); name=r.get('name') or r.get('place_name') or r.get('wikidata_label') or ''
    urls=r.get('source_urls') or []
    st=r.get('state_code') or ''
    alt=set([gn]+list(r.get('gnis_alt') or []))|qid2gnis.get(q,set())
    alt.discard('')
    c=None
    for a in alt:
        if a in g2cw: c=g2cw[a]; break
    if c:
        name=name or c['name']; st=st or c.get('state_code','')
    isCDP=False
    for a in [gn]+list(alt):
        if a and a.lstrip('0') in gaz:
            gs=gaz[a.lstrip('0')]; st=st or gs[0]; isCDP=(gs[1]=='S'); name=name or gs[2]; break
    if not st and urls: st=tld_state(urls[0])
    covered=False; why=''
    if alt & covg: covered=True; why='gnis/qid match'
    elif name and st and (norm(name),st) in covname: covered=True; why='name+state match'
    key=(q or gn or name, )
    if key in seen: stats['dup_within']+=1; return
    seen.add(key)
    u=urls[0] if urls else ''
    plat=host_platform(u) if u else ''
    if kind=='county':
        fips=str(r.get('census_geoid') or '')
        cc=fips in countyfips
        covered=covered or cc
        why=why or ('county pack FIPS' if cc else '')
    note=[]
    if not st: note.append('state unresolved')
    if not name: note.append('name unresolved (qid only)')
    if kind=='ambiguous': note.append('ambiguous place name; needs disambiguation via GNIS/qid')
    if not u: note.append('no official URL in seed; needs discovery')
    if r.get('gap_reason')=='ready_unscraped': note.append('code host known (%s)'%r.get('publisher'))
    if r.get('population'): note.append('pop %s'%r['population'])
    if why: note.append(why)
    if kind=='county': note.append('county')
    gated=GATED.get(plat,'no (check site robots.txt)') if u else 'n/a'
    if isCDP: note.append('Census CDP (statistical, likely no municipal code)')
    typ={'gaps':'municipality','ambiguous':'municipality','ready':'municipality','county':'county'}[kind]
    out.append(dict(qid=q or '',gnis=gn,census_geoid=str(r.get('census_geoid') or ''),jurisdiction=name or ('wikidata:'+(q or '')),state=st,type=('cdp_statistical' if isCDP else typ),source_url=u,platform=plat or 'unknown',already_covered='yes' if covered else 'no',gated=gated,notes='; '.join(note)))
    stats[(kind,'covered' if covered else 'new')]+=1
for kind,fn in [('ready','gh_US_municipality_ready_unscraped'),('gaps','gh_US_municipality_gaps'),('ambiguous','gh_US_municipality_ambiguous'),('county','gh_US_county_gaps')]:
    for l in open(R+fn+'.jsonl'): add(fn,json.loads(l),kind)
print(stats)
json.dump(out,open(R+'cand_seed.json','w'))
json.dump(tab,open(R+'covered_table2.json','w'))
new=[o for o in out if o['already_covered']=='no']
print('new total',len(new))
new=[o for o in new if o['type']!='cdp_statistical']
print('cdp excluded',sum(1 for o in out if o['type']=='cdp_statistical'))
print('new by type',collections.Counter(o['type'] for o in new))
print('new w/ url',sum(1 for o in new if o['source_url']),'w/ state',sum(1 for o in new if o['state']),'w/ name',sum(1 for o in new if not o['jurisdiction'].startswith('wikidata:')))
print('new platform',collections.Counter(o['platform'] for o in new).most_common(15))
print('new state',collections.Counter(o['state'] for o in new).most_common(15))
