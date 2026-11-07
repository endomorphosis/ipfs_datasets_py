"""Verifier FIX pass (audit 2026-10-18) on the built ZA supplement. Usage: ZA_STATE PACK_DIR VERIFIER_HUB_DIR
Drops/flags rows in place of the pack parquet files (backups written to ZA_STATE/verifier_fix first)."""
import sys,os,json,re,glob,hashlib,collections,shutil
import pyarrow as pa,pyarrow.parquet as pq
ST,PK,HUBD=sys.argv[1:4]; OUT=os.path.join(ST,'verifier_fix'); os.makedirs(OUT,exist_ok=True)
LP,AP=PK+'/data/laws.parquet',PK+'/data/articles.parquet'
for p,n in [(LP,'laws.parquet.pre_verifier_fix_20261023.bak'),(AP,'articles.parquet.pre_verifier_fix_20261023.bak')]:
    b=os.path.join(OUT,n)
    if not os.path.exists(b): shutil.copy2(p,b)
LT=pq.read_table(os.path.join(OUT,'laws.parquet.pre_verifier_fix_20261023.bak')); AT=pq.read_table(os.path.join(OUT,'articles.parquet.pre_verifier_fix_20261023.bak'))
L=LT.to_pylist(); byid={r['id']:r for r in L}
drop={}; flags=collections.defaultdict(dict)
def D(i,item,reason):
    if i in byid and i not in drop: drop[i]={'fix_item':item,'reason':reason,'title':byid[i]['title'],'source_url':byid[i]['source_url']}
def find(sub): return [i for i in byid if sub in i]
# FIX 1 non-by-laws
for r in L:
    if r['municipality_code']=='LIM344' and re.match(r'\s*MAKHADO\s+MUNICIPALITY\s+DETERMINATION\s+OF\s+CHARGES',r['text']): D(r['id'],1,'s75A tariff/charges determination notice, not a by-law')
for s,why in [('lim472-documents-by_law-by-laws','public-participation meeting schedule'),('lim472-documents-by_law-notice-on-emlm-by-laws','notice inviting public comment'),
  ('by-law-register-2025','by-law register (list), not a by-law'),('index-of-by-laws','index of by-laws, not a by-law'),('municipal-code-of-by-laws_musina','municipal code list of by-laws, not a by-law'),
  ('indeks.bundels','alphabetical index of by-laws, not a by-law'),('tsh-wp-admin-admin-ajax.php-cf4f4691','gazette correction notice'),('tsh-wp-admin-admin-ajax.php-f20f1037','gazette correction notice'),
  ('eth-uploads-0000-6-2025-08-08-public-health-by-law-final-april-2022-for-pp','public-participation draft; final text is on the Hub'),('eth-uploads-0000-6-2025-08-08-health-food-and-milk-products-by-law-april-2022-for-pp','public-participation draft; final text is on the Hub'),('business-licence-registration-by-laws','unadopted DRAFT business licensing by-law')]:
    for i in find(s): D(i,1,why)
# FIX 2 truncated / no body text
for s in ['gazetted-outdoor-advertising-by-laws','gazetted-property-encroachment-by-laws','gazetted-public-roads-by-laws','gazetted-stormwater-management-by-laws',
          'musina-bylaw-for-advertsing_billboard','property-rates-by-laws_2008']:
    for i in find(s): D(i,2,'body pages have no text layer (only gazette cover/index text extracted); treated as image-only, no OCR')
for i in find('ward-committee-by-law-under-rev'): D(i,2,'not the by-law text: the extracted text is a Polokwane gazette notice that the ward-committee by-law was adopted ("copy available on request"); the by-law body itself is not in the PDF')
for i in find('10-grondgebruikbeplanning_land_use_planning__gewysig'): D(i,2,'single gazette page of unrelated land-use notices, not the by-law text')
for i in find('liquor-trading-days-and-hours-by-law'): D(i,5,'compilation, not a single adopted WC031 by-law: Western Cape Provincial Gazette 8695 (9 Dec 2022) containing (a) the George Problem Premises By-law (LAN 074/2022), already in the pack as the WC044 problem-premises row (0.82 contained in this gazette), and (b) a Theewaterskloof notice of proposed adoption of a Liquor Trading Days and Hours By-law (proposed, not adopted). Not Matzikama text; the Matzikama liquor by-law is the kept row wc011-akn-by-law-2014-liquor-trading-days-hours')
for i in find('nc071-index.php-documents-category-32-by-laws-e4d3e3fd')+find('nc071-index.php-documents-category-32-by-laws-e94c0000'):
    flags[i]['verifier_review']='Ubuntu Local Municipality (NC071) row; audit flagged as a fragment; checked 2026-10-23: text runs to the short-title section, so it is a complete short by-law; kept'
# shingles
W=lambda t:re.findall(r'\w+',(t or '').lower())
def sh(t,k=8):
    w=W(t); return {hash(' '.join(w[i:i+k])) for i in range(max(0,len(w)-k+1))}
H=[]
for f in glob.glob(HUBD+'/data/laws-*.parquet'):
    for r in pq.read_table(f,columns=['id','text']).to_pylist(): H.append((r['id'],r['text'] or ''))
g=collections.defaultdict(list)
for f in glob.glob(HUBD+'/data/*_html.parquet'):
    for r in pq.read_table(f,columns=['regeling_id','text','doc_order']).to_pylist(): g[r['regeling_id']].append((int(r['doc_order'] or 0),r['text'] or ''))
for k,v in g.items(): H.append((k,'\n'.join(t for _,t in sorted(v))))
HS=[(h,sh(t)) for h,t in H]
ALIAS={'buf':'bcm'}
def hubmuni(h):
    m=re.match(r'/akn/za-([a-z0-9]+)/',h) or re.match(r'za-muni-([a-z0-9]+)-',h)
    return m.group(1) if m else None
inv=collections.defaultdict(set)
for j,(h,s) in enumerate(HS):
    for x in s: inv[x].add(j)
NS={r['id']:sh(r['text']) for r in L}
# FIX 3 vs Hub
SAMEVER=['cpt-media-zqnpllim-nature_reserve_by-law','jhb-documents_-documents-by-laws-prom-encoachment-by-laws','jhb-documents_-documents-by-laws-prom-parking-ground-by-laws']  # re-verify 2026-10-23: same instrument+version as the Hub doc
for r in L:
    i=r['id']; S=NS[i]
    if not S: continue
    c=collections.Counter(j for x in S for j in inv.get(x,()))
    hits=[]
    for j,n in c.most_common(5):
        if hubmuni(HS[j][0])!=ALIAS.get(r['municipality_code'].lower(),r['municipality_code'].lower()): continue
        a=n/len(S); b=n/max(1,len(HS[j][1])); hits.append((HS[j][0],round(a,3),round(b,3)))
    both=[h for h in hits if h[1]>=0.8 and h[2]>=0.8]; newin=[h for h in hits if h[1]>=0.8]; hubin=[h for h in hits if h[2]>=0.8]
    if both: D(i,3,f'near-duplicate of Hub document {both[0][0]} (8-word shingle containment new-in-hub {both[0][1]}, hub-in-new {both[0][2]})'); (drop[i].__setitem__('hub_id',both[0][0]) if drop[i]['fix_item']==3 else None)
    elif newin: D(i,3,f'>=80% contained in Hub document {newin[0][0]} (containment {newin[0][1]})'); (drop[i].__setitem__('hub_id',newin[0][0]) if drop[i]['fix_item']==3 else None)
    elif hubin and any(x in i for x in SAMEVER): D(i,3,f'same-version gazette/PDF copy of Hub document {hubin[0][0]} (only gazette headers/approval lines differ; hub-in-row {hubin[0][2]}, row-in-hub {hubin[0][1]})'); drop[i]['hub_id']=hubin[0][0]
    elif hubin: flags[i]['hub_near_duplicate']={'decision':'kept: bilingual/trilingual gazette copy that fully contains the Hub (English) text; the other-language text is not on the Hub','hub_ids':[h[0] for h in hubin],'containment_hub_in_row':[h[2] for h in hubin],'containment_row_in_hub':[h[1] for h in hubin]}
# FIX 4 within pack (compilations are excluded from version pairs; containment in a compilation is flagged under FIX 5)
COMPSET={r['id'] for r in L if json.loads(r['metadata_json'])['extras'].get('multi_instrument_document')}|set(find('3070_6-3_limpopo_extract'))|set(find('town-planning-docs-8226-swartland_2020'))
keep=[r for r in L if r['id'] not in drop]; ids=[r['id'] for r in keep]; inv2=collections.defaultdict(set)
for k,i in enumerate(ids):
    for x in NS[i]: inv2[x].add(k)
def yr(r):
    y=re.findall(r'(?:19|20)\d\d',r['title']+' '+r['id']); return max(y) if y else ''
pairs=[]
for k,i in enumerate(ids):
    S=NS[i]
    if not S: continue
    c=collections.Counter(j for x in S for j in inv2[x] if j!=k)
    for j,n in c.items():
        if j<=k: continue
        o=ids[j]
        if byid[o]['municipality_code']!=byid[i]['municipality_code'] or i in COMPSET or o in COMPSET: continue
        a=n/len(S); b=n/max(1,len(NS[o]))
        if a>=0.8 and b>=0.8: pairs.append((i,o,round(a,3),round(b,3)))
groups={}
def root(x):
    while groups.get(x,x)!=x: x=groups[x]
    return x
for i,o,a,b in pairs:
    ra,rb=root(i),root(o)
    if ra!=rb: groups[rb]=ra
    groups.setdefault(ra,ra)
comp=collections.defaultdict(set)
for i,o,a,b in pairs: comp[root(i)]|={i,o}
for i,o,a,b in pairs:
    if a>=0.98 and b>=0.98 and i not in drop and o not in drop:
        ri,ro=byid[i],byid[o]
        k,d=sorted([ri,ro],key=lambda r:(yr(r),len(r['text']),r['id']),reverse=True)
        D(d['id'],4,f'>=0.98 identical (8-word shingles {a}/{b}) to pack row {k["id"]}; kept that one')
        flags[k['id']].setdefault('dropped_identical_copies',[]).append({'id':d['id'],'source_url':d['source_url']})
for g_,mem in comp.items():
    live=sorted(m for m in mem if m not in drop)
    if len(live)<2: continue
    gid='vg-'+hashlib.sha1('|'.join(sorted(mem)).encode()).hexdigest()[:10]
    for m in live: flags[m]['version_group']={'id':gid,'members':live,'rule':'same-municipality rows with >=0.80 8-word-shingle containment both ways (annual re-adoptions/versions); all kept as distinct versions'}
# FIX 5 compilations
HEAD=re.compile(r"(?m)^[ \t]*[A-Z][A-Z ,:\-']{3,80}(?:BY-?LAWS?|VERORDENING)[ ,0-9]*$")
for s,ttl in [('3070_6-3_limpopo_extract','Limpopo Provincial Gazette 3070 extract (multiple notices, incl. Makhuduthamaga Spatial Planning and Land Use Management By-law)'),
              ('town-planning-docs-8226-swartland_2020','Western Cape Provincial Gazette Extraordinary 8226 (Swartland Municipal Land Use Planning By-law and other by-laws incl. Filming By-law)')]:
    for i in find(s):
        if i in drop: continue
        e=json.loads(byid[i]['metadata_json'])['extras']
        flags[i]['multi_instrument_document']=True; flags[i]['contained_bylaw_headings']=sorted(set(h.strip() for h in HEAD.findall(byid[i]['text'])))[:40]
        flags[i]['new_title']=ttl
comps=[r['id'] for r in L if r['id'] not in drop and (json.loads(r['metadata_json'])['extras'].get('multi_instrument_document') or flags[r['id']].get('multi_instrument_document'))]
for r in L:
    i=r['id']
    if i in drop or i in comps or not NS[i]: continue
    for c_ in comps:
        if c_[:12]!=i[:12] and byid[c_]['municipality_code']!=r['municipality_code']: continue
        n=len(NS[i]&NS[c_])/len(NS[i])
        if n>=0.8: flags[i].setdefault('contained_in_compilation',[]).append({'id':c_,'containment':round(n,3)})
# explicit containment (re-verify 2026-10-23): WC015 water amendment is fully inside the WC015 telecom gazette row
for i in find('4ee8ce33'):
    for c_ in find('39_telekommunikasie-infrastruktuur'):
        if i not in drop and c_ not in drop and NS[i]: flags[i].setdefault('contained_in_compilation',[]).append({'id':c_,'containment':round(len(NS[i]&NS[c_])/len(NS[i]),3),'note':'gazette row that also prints this amendment'})
# FIX 6 language
AF=set('die en van in is dat te nie met vir op word deur aan sal of moet enige hierdie wat ingevolge munisipaliteit verordening artikel persoon raad'.split())
EN=set('the and of to in is that for by with shall be any this or as municipality by-law section person council'.split())
for r in L:
    i=r['id']
    if i in drop: continue
    w=W(r['text']); a=sum(x in AF-EN for x in w); e=sum(x in EN-AF for x in w); t=a+e
    if t<50: continue
    fa=a/t
    if 0.15<=fa<=0.85:
        flags[i]['language_detail']={'languages':['af','en'],'af_share_of_marker_words':round(fa,2),'primary':r['language']}
        flags[i]['new_language']='af;en'
for i in find('rules-and-orders-by-laws_2007'):
    if i in flags and 'new_language' in flags[i]:
        flags[i]['new_language']='en'; flags[i]['language_detail']['primary']='en'; flags[i]['language_detail']['languages']=['en']
        flags[i]['language_detail']['note']='the Rules and Orders text is English; the Afrikaans marker share comes from unrelated township notices printed in the same gazette'
for i in find('eth-uploads-0000-6-2025-08-10-parks-and-recreational-grounds'):
    flags[i]['new_language']='en;zu'; flags[i]['language_detail']={'languages':['en','zu'],'primary':'en','note':'English/isiZulu gazette (Notice 197/2015); the isiZulu text is what is not matched by the Hub English text'}
# FIX 7 terms
ov=json.load(open(os.path.join(ST,'terms/terms_overrides.json')))
SAB='The source PDF carries a "Reproduced by Sabinet Online in terms of Government Printer\'s Copyright Authority" header/notice; the by-law text itself is excluded from copyright under s12(8)(a), Sabinet\'s presentation is not reproduced as such.'
for r in L:
    i=r['id']
    if i in drop: continue
    if re.search(r'(?i)sabinet',r['text'][:3000]) and not json.loads(r['metadata_json'])['extras'].get('sabinet_reproduction'): flags[i]['sabinet_reproduction']=True
# apply
fixed=[]
for r in L:
    i=r['id']
    if i in drop: continue
    m=json.loads(r['metadata_json']); e=m['extras']; f=flags.get(i,{})
    for k in ['hub_near_duplicate','version_group','contained_in_compilation','dropped_identical_copies','language_detail','verifier_review','multi_instrument_document','contained_bylaw_headings','sabinet_reproduction']:
        if k in f: e[k]=f[k]
    if 'new_title' in f: e.setdefault('original_title',r['title']); r['title']=f['new_title']
    if 'new_language' in f: r['language']=f['new_language']
    host=e.get('host','')
    o=ov.get(host) or ov.get(host.replace('www.','')) or {}
    if o.get('apply_to_rows_verifier') and o.get('row_terms'): e['source_terms']=o['row_terms']
    if e.get('sabinet_reproduction') and 'Sabinet' not in (e.get('source_terms') or ''): e['source_terms']=(e.get('source_terms') or '').rstrip()+' '+SAB
    if r['source_type'].startswith('za_openbylaws'):
        e['source_terms_decision_pending']='Laws.Africa states CC BY-NC-SA 4.0 for its consolidated legislation; these rows ARE Laws.Africa AKN consolidations, so NC-SA may attach to the consolidation/markup. Pending CoS decision; kept for translation/research use only, not for training.'
    if e.get('source_terms'): r['license']=e['source_terms']
    r['metadata_json']=json.dumps(m,ensure_ascii=False); fixed.append(r)
newL=pa.Table.from_pylist(fixed,schema=LT.schema)
keepids=set(r['id'] for r in fixed)
mask=pa.array([x in keepids for x in AT.column('law_id').to_pylist()])
newA=AT.filter(mask)
pq.write_table(newL,LP); pq.write_table(newA,AP)
rep={'dropped':drop,'flag_counts':{k:sum(1 for f in flags.values() if k in f and f.get('_')!=1) for k in ['hub_near_duplicate','version_group','contained_in_compilation','dropped_identical_copies','language_detail','verifier_review','multi_instrument_document','sabinet_reproduction','new_title']},
     'within_pack_pairs_ge_0.80':len(pairs),'within_pack_pairs_ge_0.98':sum(1 for p in pairs if p[2]>=.98 and p[3]>=.98),
     'flags':{k:{kk:vv for kk,vv in v.items() if kk!='contained_bylaw_headings'} for k,v in flags.items() if k in keepids},'laws':newL.num_rows,'articles':newA.num_rows}
json.dump(rep,open(os.path.join(OUT,'verifier_fix_report.json'),'w'),indent=1,ensure_ascii=False)
print(json.dumps({'laws':newL.num_rows,'articles':newA.num_rows,'dropped_by_item':collections.Counter(v['fix_item'] for v in drop.values()),'flag_counts':rep['flag_counts'],'pairs':rep['within_pack_pairs_ge_0.80'],'p98':rep['within_pack_pairs_ge_0.98']},indent=1))
