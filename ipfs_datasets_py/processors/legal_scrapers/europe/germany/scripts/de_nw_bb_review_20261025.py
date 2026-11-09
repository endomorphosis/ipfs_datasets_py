import json,gzip,hashlib,re,os,urllib.parse,pandas as pd
from bs4 import BeautifulSoup
D='/workspace/legal-corpora/de_subnational'; O='/workspace/packaging/out/de_nw_bb_review_20261025'
hub=pd.read_parquet(f'{O}/hub_ref/data/laws.parquet',columns=['id','title','text','source_url','jurisdiction'])
nu=lambda u:re.sub(r'^https?://(www\.)?','',(u or '').lower()).rstrip('/')
nt=lambda t:re.sub(r'\s+',' ',(t or '').lower()).strip()
hub_u=set(hub.source_url.map(nu)); hub_tj=set(zip(hub.title.map(nt),hub.jurisdiction)); hub_sha=set(hub.text.fillna('').map(lambda t:hashlib.sha256(t.encode()).hexdigest()))
jur_vals=hub.jurisdiction.value_counts().to_dict()
def idx(L):
    m={}
    for l in open(f'{D}/raw/{L}/index.jsonl'):
        r=json.loads(l)
        if r['kind']=='law': m[r['url'].rstrip('/')]=r
    return m
targets=[('NW','DE-NW',u.strip()) for u in open(f'{D}/probe/nw_urls_new_disc_20261025.txt') if u.strip()]
targets+=[('BB','DE-BB','https://bravors.brandenburg.de'+p) for p in json.load(open(f'{D}/raw/BB/bb_links_new_disc_20261025.json'))]
I={'NW':idx('NW'),'BB':idx('BB')}; rows=[]
jurmap={L:next((j for j in jur_vals if L in j or {'NW':'Nordrhein','BB':'Brandenburg'}[L] in j),f'DE-{L}') for L in ('NW','BB')}
for L,J,u in targets:
    r=I[L][u.rstrip('/')]; p=f'{D}/raw/{L}/law/{r["key"]}.html.gz'
    raw=gzip.open(p).read(); html=raw.decode('utf-8','replace'); s=BeautifulSoup(html,'lxml')
    for x in s(['script','style','nav','header','footer']): x.decompose()
    main=s.find('main') or s.find(id=re.compile('content|main',re.I)) or s.body
    h=s.find('h1'); title=re.sub(r'\s+',' ',(h.get_text(' ') if h else (s.title.string or ''))).strip()
    flags=''
    if L=='BB':
        kopf=s.select_one('.reiterbox_innen_kopf'); kt=kopf.get_text('\n').strip() if kopf else ''
        if not title or 'Vorschriftensystem' in title: title=re.sub(r'\s+',' ',kt.split('\n')[0]).strip() if kt else r['key']
        box=s.select_one('.reiterbox_innen_text') or main; main=box
        if re.search(r'außer Kraft getreten|aufgehoben durch',kt[:600],re.I): flags='not_in_force'
        if re.search(r'(Änderung|ändern)',title) and re.match(r'(Gesetz|Verordnung) zur Änderung',title): flags='amending'
    text=((kt+'\n\n') if L=='BB' and kt else '')+re.sub(r'\n\s*\n+','\n\n',main.get_text('\n')).strip()
    sha=hashlib.sha256(text.encode()).hexdigest()
    rows.append(dict(id=f'de-{L.lower()}-{r["key"]}',land=L,jurisdiction=jurmap[L],title=title,text=text,html=html,source_url=u,final_url=r['final_url'],http_status=r['status'],retrieved_at=r['ts'],raw_path=p,raw_sha256=hashlib.sha256(raw).hexdigest(),text_sha256=sha,discovery_run='fresh_discovery_20261025T102144',discovery_method={'NW':'sitemap','BB':'year_index'}[L],scraper='scripts/de_fresh_discovery.py + de_sub_collect.Site',license='§5 UrhG amtliche Werke',
        dup_url=nu(u) in hub_u or nu(r['final_url']) in hub_u,dup_title_jur=(nt(title),jurmap[L]) in hub_tj,dup_sha=sha in hub_sha,text_chars=len(text),flags=flags))
df=pd.DataFrame(rows); df['dup_any']=df.dup_url|df.dup_title_jur|df.dup_sha
in_dup=int(df.duplicated('source_url').sum()+df.duplicated('text_sha256').sum())
new=df[~df.dup_any]
df.to_parquet(f'{O}/de_nw_bb_all_candidates.parquet',index=False); new.to_parquet(f'{O}/de_nw_bb_new_laws.parquet',index=False)
smp=df.drop(columns=['html']).assign(text=lambda d:d.text.str[:600]).to_dict('records')
json.dump(smp,open(f'{O}/sample.json','w'),indent=1,ensure_ascii=False)
S=dict(stage_only=True,pushed=False,hub_ref=dict(repo='endomorphosis/ipfs_germany_laws',laws_rows=len(hub),jurisdictions=jur_vals),rows=len(df),per_land=df.land.value_counts().to_dict(),
 overlap=dict(url=int(df.dup_url.sum()),title_jur=int(df.dup_title_jur.sum()),sha256=int(df.dup_sha.sum()),any=int(df.dup_any.sum())),intra_batch_dups=in_dup,new_rows=len(new),new_per_land=new.land.value_counts().to_dict(),
 min_text_chars=int(df.text_chars.min()),titles=df[['land','title','dup_any']].values.tolist())
json.dump(S,open(f'{O}/summary.json','w'),indent=1,ensure_ascii=False); print(json.dumps({k:v for k,v in S.items()},ensure_ascii=False,indent=0)[:3000])
