import json,glob,os,re,collections,urllib.parse
R='raw/'
# covered AML gnis
aml=json.load(open(R+'aml.json'))['siblings']
cov=set()
for s in aml:
    m=re.match(r'american_law/data(_\d+)?/(\d+)_html\.parquet$',s['rfilename'])
    if m: cov.add(m.group(2))
print('aml gnis',len(cov))
meta={}
for f in glob.glob(R+'meta/*.json'):
    g=os.path.basename(f)[:-5].split('__')[-1]
    try: meta[g]=json.load(open(f))
    except Exception: pass
print('meta',len(meta))
# manifests -> origin/platform
origin={}
mrow={}
for f in sorted(glob.glob(R+'man/*.jsonl')):
    k=os.path.basename(f).replace('_manifest.jsonl','')
    for l in open(f):
        if not l.strip(): continue
        r=json.loads(l); g=str(r.get('gnis'))
        if k=='justicedao_merge': origin.setdefault(g,('legacy_justicedao','municode/amlegal/ecode360 (legacy, per-place platform not recorded)'))
        else:
            origin[g]=(k,r.get('publisher') or 'unknown'); mrow[g]=r
for g in cov:
    m=mrow.get(g)
    if m:
        meta.setdefault(g,{}); 
        meta[g].setdefault('place_name',m.get('place_name')); meta[g].setdefault('state_code',m.get('state_code'))
def typ(n):
    n=n or ''
    if re.search(r'\b(County|Parish)\b',n) and not re.search(r'City and County|City-County',n): return 'county'
    if re.search(r'City and County|City-County|Consolidated|Metro|Unified Government|Borough|Municipality of Anchorage|Urban County|Lexington-Fayette|Louisville|Nashville',n): return 'consolidated_or_borough'
    if re.search(r'\bTownship\b',n): return 'township'
    if re.search(r'\bTown\b|\bTown of\b',n): return 'town'
    if re.search(r'\bVillage\b',n): return 'village'
    if re.search(r'\bCity\b',n): return 'city'
    return 'other'
tab=[]
for g in sorted(cov):
    m=meta.get(g,{}); o=origin.get(g,('unknown',''))
    tab.append(dict(gnis=g,name=m.get('place_name',''),state=m.get('state_code',''),type=typ(m.get('place_name')),origin=o[0],publisher=o[1],sections=m.get('total_sections')))
json.dump(tab,open(R+'covered_table.json','w'))
print('no name',sum(1 for t in tab if not t['name']))
print('type',collections.Counter(t['type'] for t in tab))
print('origin',collections.Counter(t['origin'] for t in tab).most_common(30))
print('publisher',collections.Counter(t['publisher'] for t in tab).most_common(20))
print('states',len({t['state'] for t in tab}),collections.Counter(t['state'] for t in tab).most_common(60))
