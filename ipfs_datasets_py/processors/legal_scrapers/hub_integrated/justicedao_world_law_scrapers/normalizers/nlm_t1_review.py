# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, json, gzip, random, os, glob, time, collections
import pyarrow.parquet as pq, pyarrow.compute as pc
S=sys.argv[1]; B='{_CORPORA}/nl_municipal'; R=json.load(open(f'{S}/build_report.json'))
L=pq.ParquetFile(f'{S}/data/laws.parquet'); A=pq.ParquetFile(f'{S}/data/articles.parquet')
ids=pq.read_table(f'{S}/data/laws.parquet',columns=['id'])['id'].to_pylist()
V=dict(laws_rows=L.metadata.num_rows, articles_rows=A.metadata.num_rows, unique_law_ids=len(set(ids)),
  laws_bytes=os.path.getsize(f'{S}/data/laws.parquet'), articles_bytes=os.path.getsize(f'{S}/data/articles.parquet'))
aids=set(); dup=0; orphan=0; idset=set(ids)
for b in A.iter_batches(batch_size=50000,columns=['law_id','id']):
    for l,a in zip(b.column('law_id').to_pylist(), b.column('id').to_pylist()):
        if a in aids: dup+=1
        aids.add(a)
        if l not in idset: orphan+=1
V.update(dup_article_ids=dup, orphan_articles=orphan); del aids
st=pq.read_table(f'{S}/data/laws.parquet',columns=['law_status'])['law_status'].value_counts().to_pylist(); V['law_status']={d['values']:d['counts'] for d in st}
random.seed(20261015); samp=sorted(random.sample(ids,20),reverse=True)
t=pq.read_table(f'{S}/data/laws.parquet',columns=['id','title','jurisdiction','date','law_status','source_url','article_count','official_identifier'],filters=[('id','in',samp)]).to_pylist()
at=pq.read_table(f'{S}/data/articles.parquet',columns=['law_id','title','text','record_type'],filters=[('law_id','in',samp)]).to_pylist()
first={}; 
for a in at: first.setdefault(a['law_id'],a)
nart=collections.Counter(a['law_id'] for a in at); H=[]
for r in sorted(t,key=lambda r:-int(r['id'][4:])):
    oid=r['official_identifier']; px=f"{B}/raw/xml/{oid}.xml.gz"; chk=None
    if os.path.exists(px):
        raw=gzip.decompress(open(px,'rb').read()).decode('utf-8','ignore'); w=[x for x in (r['title'] or '').split() if len(x)>4][:4]
        chk=all(x in raw for x in w)
    fa=first.get(r['id'],{})
    H.append(dict(id=r['id'],title=(r['title'] or '')[:110],jurisdiction=r['jurisdiction'],date=r['date'],status=r['law_status'],article_count=r['article_count'],
      articles_in_parquet=nart[r['id']],count_match=nart[r['id']]==r['article_count'],raw_xml_cached=os.path.exists(px),title_words_in_raw=chk,
      first_unit=f"{fa.get('record_type')}: {(fa.get('title') or '')[:60]}",source_url=r['source_url']))
R['verify']=V; R['handcheck']=H; R['handcheck_summary']=dict(n=len(H),count_match=sum(h['count_match'] for h in H),raw_cached=sum(h['raw_xml_cached'] for h in H),title_in_raw=sum(1 for h in H if h['title_words_in_raw']))
ts=os.path.basename(S).rsplit('_',1)[1]; out=f'/workspace/country-law-triage/nlm_t1_review_{ts}.json'; json.dump(R,open(out,'w'),indent=1,default=str)
print(out); print(json.dumps(V)); print(json.dumps(R['handcheck_summary']))
for h in H: print(h['id'],h['jurisdiction'],h['date'],h['status'],h['article_count'],h['count_match'],h['title_words_in_raw'],'|',h['title'][:70],'|',h['first_unit'])
