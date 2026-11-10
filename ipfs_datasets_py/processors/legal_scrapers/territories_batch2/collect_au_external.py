'''Bounded official AU external-territory foundation-law PDF collection.'''
import pathlib,json,sys,time,subprocess,resource,re
from bs4 import BeautifulSoup
from batch2_common import ROOT,Polite,guard,install_guard,write_json
install_guard();guard(True)
client=Polite(['www.legislation.gov.au']);rob=client.setup('https://www.legislation.gov.au/');body,terms=client.get('https://www.legislation.gov.au/terms-of-use');text=BeautifulSoup(body,'html.parser').get_text(' ',strip=True);write_json(ROOT/'AU_terms_review.json',{'robots':rob,'terms':terms,'terms_text':text,'scope':'Foundation acts/applied laws ordinances; not all applied WA/ACT law'})
print('AU_TERMS',terms['status'],text[:3500],flush=True)
if terms['status']!=200:raise SystemExit('LICENSING_REVIEW_HOLD')
if re.search(r'(prohibit|not permit|must not).{0,120}(scrap|crawl|automat)',text,re.I):raise SystemExit('TERMS_HOLD')
import pyarrow as pa,pyarrow.parquet as pq
seeds=[('CX','C1958A00041','Christmas Island Act 1958'),('CX','F2006B00507','Christmas Island Applied Laws Ordinance 1992'),('CC','C1955A00034','Cocos (Keeling) Islands Act 1955'),('CC','F2006B01318','Cocos (Keeling) Islands Applied Laws Ordinance 1992'),('HM','C1953A00007','Heard Island and McDonald Islands Act 1953')]
rows={};events=[]
def child_limit():resource.setrlimit(resource.RLIMIT_AS,(270*1024**2,270*1024**2))
for code,identifier,title in seeds:
 guard();url='https://www.legislation.gov.au/'+identifier+'/latest/text/original/pdf'
 try:
  body,meta=client.get(url);event=dict(code=code,title=title,response=meta)
  if meta['status']!=200 or meta.get('challenge'):events.append(event);break
  if not body.startswith(b'%PDF'):event['error']='not_pdf';events.append(event);continue
  result=subprocess.run(['pdftotext','-layout',meta['raw_path'],'-'],capture_output=True,timeout=40,preexec_fn=child_limit);content=result.stdout.decode(errors='replace').strip()
  if result.returncode or len(content)<200:event['error']='missing_pdf_text';events.append(event);continue
  rows.setdefault(code,[]).append({'id':code+'-'+identifier,'title':title,'text':content,'source_url':meta['requested_url'],'source_sha256':meta['sha256'],'jurisdiction_code':code,'parent_country':'AU','language':'en','retrieved_at':meta['observed_local'],'official_identifier':identifier,'source_type':'official_Federal_Register_PDF','license':'See official Federal Register terms-of-use and preserved evidence','law_status':'latest endpoint at retrieval; compilation details preserved in text','coverage':'bounded foundation act and applied-laws ordinance seed set; NOT all territorial/applied laws'})
  events.append(event);print('AU_COLLECTED',code,identifier,len(content),flush=True)
 except Exception as e:events.append({'code':code,'error':type(e).__name__+':'+str(e)[:200]});break
write_json(ROOT/'AU_collection_events.json',events)
for code,data in rows.items():
 ready=ROOT/code/'upload_ready';(ready/'data').mkdir(parents=True,exist_ok=True);target=ready/'data/laws.parquet';pq.write_table(pa.Table.from_pylist(data),target,compression='zstd');n=pq.read_metadata(target).num_rows
 write_json(ready/'validation.json',{'laws_rows':n,'articles_rows':0,'articles_file_created':False,'source':'official Federal Register PDFs','scope':'Foundation act + applied-laws ordinance seed set, not complete territory corpus','robots_crawl_delay_seconds':client.delay['www.legislation.gov.au'],'copyright_terms':terms,'push':'NOT_PUSHED','datasets_streaming_validation':'Pending central verifier'})
 (ready/'README.md').open('x').write('''---
configs:
- config_name: laws
  data_files: data/laws.parquet
---
# Official Australian external-territory foundation laws

Verified-TLS official Federal Register latest PDF snapshot. This is a bounded seed package, NOT every territory ordinance or all WA/ACT laws applied in the territory. Compilation dates and amendment notes are preserved in text. No speculative article splitting, no empty articles.parquet. Official sources prevail; not legal advice. See validation.json and preserved official terms-of-use evidence. No uploads performed.
''')
 for src in [pathlib.Path(__file__),ROOT/'batch2_common.py']:
  dest=ready/'scrapers_and_normalizers'/src.name;dest.parent.mkdir(parents=True,exist_ok=True);dest.open('xb').write(src.read_bytes())
 print('AU_READY',code,n,flush=True)
print('AU_DONE peak_rss_mb',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,flush=True)
