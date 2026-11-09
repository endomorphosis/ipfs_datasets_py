'''Bounded one-rowgroup-per-process BES extraction; original incomplete attempt retained.'''
import pathlib,json,re,subprocess,sys,resource
from batch2_common import ROOT,guard,install_guard,write_json
install_guard();guard(True)
import pyarrow as pa,pyarrow.parquet as pq
SRC=pathlib.Path('/workspace/legal-corpora/nl_extract/hub_verify_58982353b51d/data');pat=re.compile(r'\bBES\b|Bonaire|Sint Eustatius|\bSaba\b|Caribisch(?:e)?\s+Nederland',re.I);selection={}
for b in pq.ParquetFile(SRC/'laws.parquet').iter_batches(batch_size=64,columns=['id','title','metadata_json'],use_threads=False):
 for row in b.to_pylist():
  md=json.loads(row['metadata_json'] or '{}').get('metadata',{});typ=md.get('bwb_type','');title=bool(pat.search(row['title'] or ''))
  if 'bes' in typ.lower() or title:selection[row['id']]={'title':row['title'],'bwb_type':typ,'explicit_title':title}
write_json(ROOT/'BQ_candidate_ids.json',sorted(selection));ready=ROOT/'BQ/upload_ready_v2';(ready/'data').mkdir(parents=True,exist_ok=True);counts={}
for kind in ['laws','articles']:
 for g in range(pq.ParquetFile(SRC/(kind+'.parquet')).metadata.num_row_groups):
  guard(True);p=ROOT/'BQ/rowgroup_shards_v2'/kind/f'{g:03}.parquet'
  result=subprocess.run([sys.executable,str(ROOT/'bq_rowgroup_worker_v2.py'),kind,str(g)],env=__import__('os').environ.copy())
  if result.returncode:raise SystemExit('BQ_ROWGROUP_HOLD '+kind+' '+str(g))
 shards=sorted((ROOT/'BQ/rowgroup_shards_v2'/kind).glob('*.parquet'));writer=None;count=0;verified_ids=set()
 for p in shards:
  for b in pq.ParquetFile(p).iter_batches(batch_size=16,use_threads=False):
   guard();t=pa.Table.from_batches([b])
   if writer is None:writer=pq.ParquetWriter(ready/'data'/(kind+'.parquet'),t.schema,compression='zstd')
   writer.write_table(t);count+=len(t)
   if kind=='laws':verified_ids.update(t['id'].to_pylist())
 if writer:writer.close()
 counts[kind]=count
 if kind=='laws':write_json(ROOT/'BQ_verified_law_ids.json',sorted(verified_ids))
write_json(ready/'selection_provenance.json',selection);write_json(ready/'validation.json',{'laws_rows':counts['laws'],'articles_rows':counts['articles'],'target_hf_repo':'endomorphosis/ipfs_bonairesinteustatiusandsaba_laws','source_files':[str(SRC/'laws.parquet'),str(SRC/'articles.parquet')],'source_snapshot':'58982353b51d','license':'CC0-1.0 per preserved KOOP BWB provenance','selection':'Official BWB type -BES or explicit BES/island/Caribisch Nederland title; nonempty texts; articles join on selected law IDs','scope':'All matching rows in preserved snapshot, not every currently applicable/current BES law','datasets_streaming_validation':'Pending central verifier','push':'NOT_PUSHED'})
(ready/'README.md').open('x').write('''---
license: cc0-1.0
language: nl
configs:
- config_name: laws
  data_files: data/laws.parquet
- config_name: articles
  data_files: data/articles.parquet
---
# Caribbean Netherlands official BWB snapshot subset

Official BWB BES-type instruments and laws explicitly naming BES/Bonaire/Sint Eustatius/Saba/Caribisch Nederland, extracted from locally preserved Dutch national release 58982353b51d. All nonempty matching laws and existing structured articles are retained, with source URLs, original retrieval dates and CC0 provenance. Source JSON paths may be historical and absent. BQ is the territorial jurisdiction; NL is parent state.

This is not a claim of current-through-November-2026 or all applicable-law completeness. Generally applicable Dutch laws without explicit BES title/type may be omitted. Fresh SRU scope reconciliation remains open. No speculative article splitting. Original source files and initial memory-held attempt remain untouched. No upload performed.
''')
for src in [pathlib.Path(__file__),ROOT/'bq_rowgroup_worker_v2.py',ROOT/'batch2_common.py',pathlib.Path('/workspace/ipfs_datasets_py_latest/ipfs_datasets_py/processors/legal_scrapers/national_collectors/collect_bwb.py')]:
 text=src.read_text();text=re.sub(r'\bhf_[A-Za-z0-9]{16,}\b','REDACTED_HF_TOKEN',text);text=re.sub(r'/home/box/agent-data/connector-secrets/[^\s\"\'\)]+','CREDENTIAL_PATH_REMOVED',text);dest=ready/'scrapers_and_normalizers'/src.name;dest.parent.mkdir(parents=True,exist_ok=True);dest.open('x').write(text)
print('BQ_V2_READY',counts,'parent_peak_rss_mb',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,flush=True)
