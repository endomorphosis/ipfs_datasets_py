'''Normalize already-captured official Tokelau Statistics Rules HTML; no network.'''
import pathlib,json,resource
from bs4 import BeautifulSoup
from batch2_common import ROOT,guard,install_guard,write_json
install_guard();guard(True)
import pyarrow as pa,pyarrow.parquet as pq
source=json.load((ROOT/'TK_portal.json').open());soup=BeautifulSoup(pathlib.Path(source['page']['raw_path']).read_bytes(),'html.parser');content=soup.select_one('#c1204.component_ContentDisplay_Content')
if content is None:raise SystemExit('NO_VERIFIED_CONTENT_CONTAINER')
for n in content(['script','style']):n.extract()
text=content.get_text('\n',strip=True)
if len(text)<10000:raise SystemExit('LAW_BODY_SHORT')
ready=ROOT/'TK/upload_ready';(ready/'data').mkdir(parents=True,exist_ok=True);row={'id':'TK-statistics-rules-2013','title':'Tokelau Statistics Rules 2013 / Tulafono mo Fuainumela Fakamaumau 2013','text':text,'jurisdiction_code':'TK','language':'en,tkl','source_url':source['page']['requested_url'],'source_sha256':source['page']['sha256'],'retrieved_at':source['page']['observed_local'],'source_type':'official_Tokelau_government_rule_HTML','license':'Rights review required: government website footer says all rights reserved; no explicit open reuse licence located','coverage':'One rule only, not the complete Tokelau rules corpus'};p=ready/'data/laws.parquet';pq.write_table(pa.Table.from_pylist([row]),p,compression='zstd')
write_json(ready/'validation.json',{'laws_rows':pq.read_metadata(p).num_rows,'articles_rows':0,'articles_file_created':False,'rights_review_required':True,'publication_hold':'Do not upload until copyright/licensing reviewed and explicit HF GO received','scope':'One official bilingual rule; not all Tokelau legislation','datasets_streaming_validation':'Pending central verifier','push':'NOT_PUSHED'})
(ready/'README.md').open('x').write('''---
configs:
- config_name: laws
  data_files: data/laws.parquet
---
# Tokelau Statistics Rules 2013 — local review copy

One official bilingual English/Tokelauan rule copied from the substantive official government HTML content container, excluding site navigation/footer. Source URL, SHA-256 and retrieval time accompany the record. Not all Tokelau law and not legal advice. No guessed article splits or empty article file.

PUBLICATION HOLD: the government website footer says all rights reserved; no explicit open reuse licence was located. This is a local review artifact, not cleared for redistribution. Obtain rights review and explicit publication GO before any external upload. No uploads performed.
''')
for src in [pathlib.Path(__file__),ROOT/'batch2_common.py']:
 p=ready/'scrapers_and_normalizers'/src.name;p.parent.mkdir(parents=True,exist_ok=True);p.open('xb').write(src.read_bytes())
print('TK_READY_LOCAL_RIGHTS_HOLD',1,'rss_mb',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)
