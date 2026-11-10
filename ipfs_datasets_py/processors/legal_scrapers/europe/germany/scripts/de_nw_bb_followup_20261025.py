import json,re,pandas as pd
B='/workspace/backups/hub_ipfs_germany_laws_pre_nwbb_20261025'; S='/workspace/legal-corpora/hf-staging/de_nw_bb_followup_20261025'
L=pd.read_parquet('/tmp/de_verify_nwbb/data/laws.parquet'); A=pd.read_parquet(f'{B}/data/articles.parquet')
rep=json.load(open('/workspace/legal-corpora/hf-staging/de_nw_bb_push_20261025/REPORT.json')); NEW=[x[0] for x in rep['new']]
NEWV,OLD='de-nw-b41909efdb3b47e0','de-nw-31213'
L['effective_from']=pd.Series([None]*len(L),dtype='string')
iN=L.index[L.id==NEWV][0]; iO=L.index[L.id==OLD][0]
L.at[iN,'is_current']=False; L.at[iN,'effective_from']='2027-01-01'; L.at[iO,'is_current']=True
# lineage kept: NEWV.supersedes=OLD, OLD.superseded_by=NEWV (pending until effective_from)
for i,cur in ((iN,False),(iO,True)):
    m=json.loads(L.at[i,'metadata_json']); m['is_current']=cur
    if i==iN: m['effective_from']='2027-01-01'; m['supersession_status']='pending_until_effective_from'
    else: m['supersession_status']='pending (successor effective 2027-01-01)'
    L.at[i,'metadata_json']=json.dumps(m,ensure_ascii=False)
# (b) articles
rx=re.compile(r'(?m)^[ \t]*(§\s*\d+[a-z]?)\b[ \t]*(.*)$')
rows=[];cnt={}
for r in L[L.id.isin(NEW)].itertuples():
    t=r.text; ms=list(rx.finditer(t)); seen={}
    rows.append(dict(law_id=r.id,id=f'{r.id}:header',title='header',text=(t[:ms[0].start()] if ms else '').strip()[:20000],source_url=r.source_url,document_number=None,article_number=None,record_type='article',metadata_json=json.dumps(dict(doknr=None,enbez=None,titel=None,gliederungsbez=None,gliederungstitel=None))))
    n=0
    for k,m in enumerate(ms):
        end=ms[k+1].start() if k+1<len(ms) else len(t); en=re.sub(r'\s+',' ',m[1]); body=t[m.end():end].strip()
        aid=f'{r.id}:{en}'; seen[aid]=seen.get(aid,0)+1
        if seen[aid]>1: aid+=f'#{seen[aid]}'
        ti=(m[2] or '').strip()
        rows.append(dict(law_id=r.id,id=aid,title=en,text=body,source_url=r.source_url,document_number=None,article_number=en.replace('§','').strip(),record_type='article',metadata_json=json.dumps(dict(doknr=None,enbez=en,titel=ti or None,gliederungsbez=None,gliederungstitel=None),ensure_ascii=False))); n+=1
    if not ms: rows.append(dict(law_id=r.id,id=f'{r.id}:text',title='text',text=t,source_url=r.source_url,document_number=None,article_number=None,record_type='article',metadata_json=json.dumps(dict(doknr=None,enbez=None,titel=None,gliederungsbez=None,gliederungstitel=None))))
    cnt[r.id]=n
na=pd.DataFrame(rows,columns=A.columns); assert not na.id.isin(A.id).any() and na.id.is_unique
for k,v in cnt.items(): L.loc[L.id==k,'article_count']=v
A2=pd.concat([A,na],ignore_index=True)
L.to_parquet(f'{S}/data/laws.parquet',index=False,compression='zstd'); A2.to_parquet(f'{S}/data/articles.parquet',index=False,compression='zstd')
R=dict(laws=len(L),articles_old=len(A),articles_added=len(na),articles=len(A2),article_count=cnt,is_current_false=int((~L.is_current).sum()),swap={'current':OLD,'future':NEWV})
json.dump(R,open(f'{S}/REPORT.json','w'),indent=1);print(R)
