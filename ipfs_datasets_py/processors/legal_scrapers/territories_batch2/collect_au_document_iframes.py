'''Collect visible official full-text EPUB HTML documents linked by title pages.
No API reverse engineering; no front-page navigation/TOC masquerading as law text.
'''
import pathlib,json,resource
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from batch2_common import ROOT,Polite,guard,install_guard,write_json,UA
install_guard();guard(True)
import pyarrow as pa,pyarrow.parquet as pq
terms=json.load((ROOT/'AU_terms_review.json').open());client=Polite(['www.legislation.gov.au']);rp=RobotFileParser();rp.parse(pathlib.Path(terms['robots']['raw_path']).read_text().splitlines());client.policies['www.legislation.gov.au']=rp;client.delay['www.legislation.gov.au']=max(2,rp.crawl_delay(UA) or rp.crawl_delay('*') or 0)
rows={};events=[]
for old in json.load((ROOT/'AU_collection_events.json').open()):
 guard();soup=BeautifulSoup(pathlib.Path(old['response']['raw_path']).read_bytes(),'html.parser');iframe=soup.find('iframe',id='epubFrame')
 if not iframe or not iframe.get('src'):continue
 url=iframe['src'];body,meta=client.get(url);event={'code':old['code'],'title':old['title'],'response':meta};events.append(event)
 if meta['status']!=200 or meta.get('challenge'):break
 doc=BeautifulSoup(body,'html.parser')
 for n in doc(['script','style']):n.extract()
 text=(doc.body or doc).get_text('\n',strip=True)
 if len(text)<1000:event['error']='body_too_short';continue
 identifier=old['response']['requested_url'].split('/')[3];code=old['code'];rows.setdefault(code,[]).append({'id':code+'-'+identifier,'official_identifier':identifier,'title':old['title'],'text':text,'source_url':meta['requested_url'],'source_sha256':meta['sha256'],'jurisdiction_code':code,'parent_country':'AU','language':'en','source_type':'official_Federal_Register_EPUB_HTML','retrieved_at':meta['observed_local'],'license':'CC-BY-4.0, Federal Register of Legislation attribution; exceptions as official terms','normalization':'Based on content from the Federal Register of Legislation at '+meta['requested_url']+' on retrieval date; HTML markup removed, text order retained. https://creativecommons.org/licenses/by/4.0/','coverage':'Foundation act / Applied Laws Ordinance seed set, not all applied WA/ACT laws'})
 print('AU_HTML',code,identifier,len(text),flush=True)
write_json(ROOT/'AU_iframe_collection_events.json',events)
for code,data in rows.items():
 ready=ROOT/code/'upload_ready';(ready/'data').mkdir(parents=True,exist_ok=True);p=ready/'data/laws.parquet';pq.write_table(pa.Table.from_pylist(data),p,compression='zstd');n=pq.read_metadata(p).num_rows
 write_json(ready/'validation.json',{'laws_rows':n,'articles_rows':0,'articles_file_created':False,'source':'Official full-text document iframe linked visibly by Register page','scope':'Foundation acts and applied-laws ordinances only, not entire territorial law corpus','robots_crawl_delay_seconds':client.delay['www.legislation.gov.au'],'license':'CC-BY-4.0; see AU_terms_review.json','datasets_streaming_validation':'Pending central verifier','push':'NOT_PUSHED'})
 (ready/'README.md').open('x').write('''---
license: cc-by-4.0
language: en
configs:
- config_name: laws
  data_files: data/laws.parquet
---
# Australian external territory: official foundation laws

Based on content from the Federal Register of Legislation, https://www.legislation.gov.au/ . Source URLs and retrieval times accompany each record. Licensed CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), with exceptions in official terms. Changes: HTML markup removed, source text order retained; no speculative article splitting.

Complete for the documented small foundation-act/applied-laws-ordinance seed list only. NOT all territory ordinances, all applied Western Australian/ACT legislation, or a claim that old compilation dates are current legal advice. The official latest title pages supplied visible full-text document iframe URLs; those full texts, not navigation summaries, are preserved here. No empty articles.parquet created. Official text prevails; not legal advice. No upload performed.
''')
 for src in [pathlib.Path(__file__),ROOT/'batch2_common.py']:
  dest=ready/'scrapers_and_normalizers'/src.name;dest.parent.mkdir(parents=True,exist_ok=True);dest.open('xb').write(src.read_bytes())
 print('AU_READY',code,n,flush=True)
print('AU_HTML_DONE peak_rss_mb',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,flush=True)
