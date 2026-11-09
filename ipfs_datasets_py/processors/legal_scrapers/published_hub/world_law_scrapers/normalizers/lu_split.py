import re, json, collections, pyarrow as pa, pyarrow.parquet as pq
D='/workspace/packaging/out/lu_rc2_review_20261023/data/'
FR=['janvier','février','mars','avril','mai','juin','juillet','août','septembre','octobre','novembre','décembre']
DE=['januar','februar','märz','april','mai','juni','juli','august','september','oktober','november','dezember']
def pats(iso):
    y,m,d=iso.split('-'); m=int(m); d=int(d)
    dd=r'(?:1\s*(?:er|e)|1)' if d==1 else str(d)
    fr=FR[m-1].replace('é','[ée]').replace('û','[uû]')
    return re.compile(rf'(?<!\d){dd}\s*\.?\s*(?:{fr}|{DE[m-1].replace("ä","(?:ä|ae|a)")}|0?{m}\.)\s*\.?\s*{y}',re.I)
HEAD=re.compile(r'^\s*(?:[A-ZÉÈÂ][\w\s\-\'’\.]{1,60}\.\s*[-–—]\s*\S|(?:R[èe]glement|Arr[êe]t[ée]|D[ée]lib[ée]ration|Approbation|Avis|Publication|Beschluß|Verordnung|Reglement)\b)',re.M|re.I)
def clean(s): return re.sub(r'[ \t]+',' ',re.sub(r'\s*\n\s*','\n',s or '')).strip()
def despace(s): return re.sub(r'\b(?:\w ){2,}\w\b',lambda m:m.group(0).replace(' ',''),s)
SKIP=re.compile(r'version HTML|identique à la version|journal officiel|m[ée]morial|grand-duch[ée]|^\W*$|^page|^\d+$|recueil',re.I)
GEN=re.compile(r'(?:avis|bekanntmachung|r[èe]glements? communa(?:l|ux)|gemeindereglemente?|ledit .{0,40}publi[ée] en due forme|[\s.—–-])+',re.I)
def title(t):
    for ln in (t or '').split('\n'):
        ln=despace(ln.strip())
        if len(ln)<8 or (SKIP.search(ln) and len(ln)<120) or GEN.fullmatch(ln.strip(' .—-')): continue
        t0=re.split(r'(?<=[a-zé\)])\.\s',ln)[0]
        return (t0 if len(t0)>=15 else ln)[:300]
    return None
w=pq.read_table(D+'rc_works.parquet').to_pylist()
iss={r['memorial_issue_sha256']:r for r in pq.read_table(D+'memorial_issues.parquet').to_pylist()}
by=collections.defaultdict(list)
for r in w:
    if r['needs_split']: by[r['memorial_issue_sha256']].append(r)
c=collections.Counter()
for h,rows in by.items():
    t=iss[h]['text'] or ''; hit=[]; used=set()
    bd=collections.defaultdict(list)
    for r in rows: bd[r['date_document']].append(r)
    for dt,rs in bd.items():
        ms=list(pats(dt).finditer(t)) if dt else []
        for i,r in enumerate(rs):
            if i>=len(ms): r['split_status']='unmatched'; continue
            s=ms[i].start(); hs=[x.start() for x in HEAD.finditer(t,max(0,s-1500),s)]
            st=hs[-1] if hs and hs[-1] not in used else t.rfind('\n',0,s)+1
            used.add(st); hit.append((st,r))
    hit.sort(key=lambda x:x[0]); seen=set()
    for i,(s,r) in enumerate(hit):
        e=next((s2 for s2,_ in hit[i+1:] if s2>s),len(t))
        if s in seen or e-s<80: r['split_status']='unsplittable_shared_segment'; continue
        seen.add(s); r['text']=clean(t[s:e]); r['split_status']='split_from_memorial'
    if len(rows)==1 and rows[0]['split_status']!='split_from_memorial' and len(t)<20000:
        pass
for r in w:
    if r['format']=='html': r['split_status']='html'
    elif not r['needs_split']: r['split_status']=r.get('split_status','other')
    r['text']=r['text'] if r.get('split_status') in('html','split_from_memorial') else r.get('text')
    r['text_chars']=len(r['text']) if r.get('text') else None
    r['title']=title(r['text']) if r.get('text') else None
    c[r['split_status']]+=1; c['with_title']+=bool(r['title'])
c['rows']=len(w)
pq.write_table(pa.Table.from_pylist(w),D+'rc_works.parquet',compression='zstd')
s=json.load(open(D+'../summary.json')); s['split_20261023']=dict(c); json.dump(s,open(D+'../summary.json','w'),indent=1)
print(dict(c))
