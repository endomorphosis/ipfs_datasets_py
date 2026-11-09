'''Stream an explicit BES subset from a locally preserved official BWB snapshot.
Select official BWB -BES type or explicit BES/island/Caribisch Nederland titles.
This is all matching rows in the preserved snapshot, not current-global completeness.
'''
import pathlib,re,json,time,collections,resource
from batch2_common import ROOT,guard,install_guard,write_json
install_guard();guard(True)
import pyarrow as pa,pyarrow.parquet as pq
SRC=pathlib.Path('/workspace/legal-corpora/nl_extract/hub_verify_58982353b51d/data');ready=ROOT/'BQ/upload_ready';(ready/'data').mkdir(parents=True,exist_ok=True)
ids=set();reasons={};law_writer=None;article_writer=None;law_count=0;article_count=0;nonempty_articles=0;types=collections.Counter();pat=re.compile(r'\bBES\b|Bonaire|Sint Eustatius|\bSaba\b|Caribisch(?:e)?\s+Nederland',re.I)
for batch in pq.ParquetFile(SRC/'laws.parquet').iter_batches(batch_size=16):
 guard();rows=[]
 for row in batch.to_pylist():
  md=json.loads(row.get('metadata_json') or '{}').get('metadata',{});typ=md.get('bwb_type','');is_type='bes' in typ.lower();is_title=bool(pat.search(row.get('title') or ''))
  if not(is_type or is_title):continue
  if not(row.get('text') or '').strip():continue
  if row['id'] in ids:continue
  ids.add(row['id']);reasons[row['id']]={'bwb_type':typ,'explicit_title_match':is_title,'official_type_BES':is_type};types[typ]+=1
  row.update(jurisdiction='BQ',country='BQ',parent_country='NL',source_snapshot_hf_commit='58982353b51d',territory_selection='official BWB type -BES or explicit territory title',source_snapshot_note='Previously preserved national BWB corpus; not refreshed to current date')
  rows.append(row)
 if rows:
  table=pa.Table.from_pylist(rows)
  if law_writer is None:law_writer=pq.ParquetWriter(ready/'data/laws.parquet',table.schema,compression='zstd')
  law_writer.write_table(table);law_count+=len(rows)
if law_writer:law_writer.close()
for batch in pq.ParquetFile(SRC/'articles.parquet').iter_batches(batch_size=32):
 guard();rows=[]
 for row in batch.to_pylist():
  if row['law_id'] not in ids:continue
  if not(row.get('text') or '').strip():continue
  row.update(jurisdiction_code='BQ',parent_country='NL');rows.append(row)
 if rows:
  table=pa.Table.from_pylist(rows)
  if article_writer is None:article_writer=pq.ParquetWriter(ready/'data/articles.parquet',table.schema,compression='zstd')
  article_writer.write_table(table);article_count+=len(rows)
if article_writer:article_writer.close()
if not law_count:raise SystemExit('NO_LAWS_NO_PACKAGE')
write_json(ready/'validation.json',{'laws_rows':law_count,'articles_rows':article_count,'unique_law_ids':len(ids),'selection_types':dict(types),'source_files':[str(SRC/'laws.parquet'),str(SRC/'articles.parquet')],'source_snapshot_hf_commit':'58982353b51d','source_license':'CC0-1.0 as preserved in official KOOP BWB provenance metadata','completeness':'All matching laws/articles in local preserved BWB snapshot; NOT every currently applicable law or latest 2026-11-05 BES law','target_hf_repo':'endomorphosis/ipfs_bonairesinteustatiusandsaba_laws','push':'NOT_PUSHED','datasets_streaming_validation':'Pending central verifier'})
write_json(ready/'selection_provenance.json',reasons)
(ready/'README.md').open('x').write('''---
license: cc0-1.0
language: nl
configs:
- config_name: laws
  data_files: data/laws.parquet
- config_name: articles
  data_files: data/articles.parquet
---
# Caribbean Netherlands: official BWB BES snapshot subset

All matching nonempty laws and their existing structured articles from the locally preserved official Dutch BWB corpus at national snapshot 58982353b51d. Selection uses the official BWB regulation type containing BES, or explicit BES/Bonaire/Sint Eustatius/Saba/Caribisch Nederland in the title. This includes statutes, regulations and other official instrument types; see validation.json.

Existing article text/identifiers are preserved rather than inferred from typography. National source URLs, original retrieval dates, law status and KOOP CC0 provenance remain in each law. Parent state NL; territorial dataset BQ. Source JSON paths are historic provenance paths and may no longer exist.

This is complete for this selection within the preserved snapshot, not a certification of all currently applicable BES laws or current-through-November-2026 completeness. National general laws applicable to BES without explicit title/type indicators may be omitted. A fresh keyless SRU territorial scope reconciliation remains necessary. No uploads performed. Official texts prevail; not legal advice.
''')
for src in [pathlib.Path(__file__),ROOT/'batch2_common.py',pathlib.Path('/workspace/ipfs_datasets_py_latest/ipfs_datasets_py/processors/legal_scrapers/national_collectors/collect_bwb.py')]:
 text=src.read_text();text=re.sub(r'\bhf_[A-Za-z0-9]{16,}\b','REDACTED_HF_TOKEN',text);text=re.sub(r'/home/box/agent-data/connector-secrets/[^\s\"\'\)]+','CREDENTIAL_PATH_REMOVED',text);dest=ready/'scrapers_and_normalizers'/src.name;dest.parent.mkdir(parents=True,exist_ok=True);dest.open('x').write(text)
print('BQ_READY',law_count,article_count,'peak_rss_mb',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,flush=True)
