"""Build add-only US shard N from raw/wayback/ocr/*.json (rapidocr of image-only Wayback PDFs made by ocr_wayback_pdfs.py). ocr=true on every row.
Mirrors build_us_shard.py schema (same laws/articles columns via packlib.write_pack) with Wayback/IA provenance (wb_url, wb_timestamp, ia_terms,
content_signal, robots_live) as in shards 00004/00005/00007/00008, plus OCR fields as in build_us_ocr_shard.py (00003).
Usage: build_us_wayback_ocr_shard.py 0000N [--dry] [--dryout=NAME]   (--dry writes to ../_state/NAME (default dry_wayback_ocr)/ instead of data/; never /tmp)
Written 2026-10-29 PDT; run only after ocr_wayback_pdfs.py has finished. Add-only: refuses to overwrite; skips ids already in any shard."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,json,re,hashlib,os,glob,urllib.parse,ast,pyarrow.parquet as pq
sys.path.insert(0,os.path.dirname(__file__)); import packlib
B=(str(_CORPORA) + '/county/US'); N=sys.argv[1]; DRY='--dry' in sys.argv
DRYNAME=next((a.split('=',1)[1] for a in sys.argv if a.startswith('--dryout=')),'dry_wayback_ocr')  # --dryout=NAME for a fresh dry dir (no deleting old dry output)
OUTD=(str(_CORPORA) + '/county/_state/')+DRYNAME if DRY else B
for k in ('laws','articles'):
    assert not os.path.exists(f'{OUTD}/data/{k}-{N}.parquet'), f'{k}-{N} exists (add-only)'
have=set(); haveart=set()
for f in glob.glob(B+'/data/laws-*.parquet'): have|=set(pq.read_table(f,columns=['id']).column('id').to_pylist())
for f in glob.glob(B+'/data/articles-*.parquet'): haveart|=set(pq.read_table(f,columns=['id']).column('id').to_pylist())
def thash(t): return hashlib.sha1(re.sub(r'\s+',' ',t).strip().lower().encode()).hexdigest()  # 2026-10-29: exact-text dedupe (same PDF at other URL / already OCR'd in 00003)
havetext=set()
for f in glob.glob(B+'/data/laws-*.parquet'): havetext|={thash(t) for t in pq.read_table(f,columns=['text']).column('text').to_pylist()}
BOTWALL=re.compile(r'request\s+is\s+being\s+verified|checking your browser|enable javascript and cookies',re.I)  # bot-challenge page OCR'd instead of the PDF
COVER=re.compile(r'^\s*(\(Space above reserved|TITLE OF DOCUMENT:)',re.I)  # blank recorder cover-sheet template
tg={c['geoid']:c for c in json.load(open(B+'/raw/targets_tx_mo_ky_wikidata.json'))}
EXCLUDE_GEOID={'21111','21067','29510'}  # city-county consolidations / independent city -> municipal bot
EXC=re.compile(r'privacy|terms of (use|service)|accessibility|sms |cookie|disclaimer',re.I)
NONCOUNTY=re.compile(r'\bISD\b|independent school|dockets?\b|order of assignment',re.I)  # archive sources: other issuers / court dockets
# 2026-11-08 (shard 00021 review): docs hosted on county sites but issued by another body (ISD/city/college/party) that the title regex misses; ids reviewed by hand from OCR text
NONCOUNTY_ID={'us-county-48037-2f160b19d3',  # DeKalb ISD order of cancellation
 'us-county-48037-48743dcbe7',  # City of Hooks order of election
 'us-county-48037-75edec9d7c',  # City of Maud resolution 24-0318
 'us-county-48037-be29a5cdac',  # Pleasant Grove ISD order of election
 'us-county-48037-e3322d0965',  # New Boston ISD amended order of election
 'us-county-48053-2f0b663fa0',  # City of Bertram ordinance 228-021120
 'us-county-48053-6320f768fd',  # Burnet County Democrats ballot order draw notice
 'us-county-48317-dea19058c6',  # City of Stanton election resolution
 'us-county-48405-fd0451e47b',  # City of Broaddus order of cancellation
 'us-county-48487-6cd1ca056c'}  # Vernon College (other political subdivision) order of election
SEC=re.compile(r'(?m)^\s*(?:Sec(?:tion|\.)|SECTION|§)\s*([0-9][0-9A-Za-z\.\-]*)\.?\s*[-–—.:]?\s*(.{0,120})$')
ENG='rapidocr-onnxruntime 1.2.3'
def truthy(v): return v is True or str(v).strip().lower() in ('true','1','yes')
def pages_text(v):
    if isinstance(v,list): return v
    try:
        x=ast.literal_eval(v)
        if isinstance(x,list): return x
    except Exception: pass
    return [str(v or '')]
def num(v):
    try: return float(v)
    except Exception: return None
laws=[];arts=[];skipped=[]
for f in sorted(glob.glob(B+'/raw/wayback/ocr/*.json')):
    try: d=json.load(open(f))
    except ValueError: skipped.append((os.path.basename(f),'corrupt json')); continue
    if not truthy(d.get('ocr')): skipped.append((d.get('pdf'),'ocr error/not done')); continue
    g=d['geoid']
    if g in EXCLUDE_GEOID: skipped.append((d['pdf'],'city-county excluded')); continue
    c=tg.get(g)
    if not c: skipped.append((d['pdf'],'geoid not in targets')); continue
    url=d['url']
    title=urllib.parse.unquote(url.split('?',1)[0].rsplit('/',1)[-1]).rsplit('.pdf',1)[0].replace('_',' ').strip() or url
    if EXC.search(title+url): skipped.append((d['pdf'],'excluded title')); continue
    if NONCOUNTY.search(urllib.parse.unquote(title+' '+url)): skipped.append((d['pdf'],'ISD/docket non-county')); continue
    text='\n\n'.join(str(p) for p in pages_text(d.get('page_text'))).strip()
    if len(text)<50: skipped.append((d['pdf'],'empty ocr text')); continue
    if len(text)<2000 and BOTWALL.search(text): skipped.append((d['pdf'],'bot-challenge page, not document')); continue
    if len(text)<300 and COVER.search(text): skipped.append((d['pdf'],'blank recorder cover sheet')); continue
    th=thash(text)
    if th in havetext: skipped.append((d['pdf'],'identical text already in pack/shard')); continue
    rid=f"us-county-{g}-{hashlib.sha256(url.encode()).hexdigest()[:10]}"  # same id rule as build_us_shard.py
    if rid in have: skipped.append((d['pdf'],'id exists in other shard')); continue
    if rid in NONCOUNTY_ID: skipped.append((d['pdf'],'non-county issuer (reviewed)')); continue
    have.add(rid); havetext.add(th)
    host=urllib.parse.urlparse(url).netloc
    cs=d.get('content_signal','') or ''
    terms=(f"Public county-government document; retrieved from the Internet Archive Wayback Machine ({d.get('wb_url')}) at <=1 req/s, not from the county site; "
           f"Internet Archive Terms of Use apply to the archive; county live robots.txt status: {d.get('robots_live')}; no explicit license reviewed (terms_reviewed=false); "
           "public-record status presumed. Text is machine OCR of an image-only PDF; expect errors.")
    if cs: terms+=f" Site robots.txt Content-Signal: {cs}."
    md=dict(admin_level='county',geoid=g,gnis=c['gnis'],state=c['state'],county=c['name'],source_site=(c.get('sites') or [host])[0],content_kind='pdf',
            ocr=True,ocr_engine=d.get('engine') or ENG,ocr_mean_conf=num(d.get('mean_conf')),ocr_pages=d.get('pages'),ocr_render_long_side_px=d.get('render_long_side_px'),
            text_source='ocr_of_wayback_image_only_pdf',local_pdf=d.get('local_pdf',''),terms=terms,content_signal=cs,fetch_via='wayback',record_type='law',
            ocr_note='machine OCR; not authoritative',wb_timestamp=d.get('wb_timestamp',''),wb_url=d.get('wb_url',''),robots_live=d.get('robots_live',''),ia_terms=d.get('ia_terms',''))
    secs=[];ms=list(SEC.finditer(text))
    for i,m in enumerate(ms):
        end=ms[i+1].start() if i+1<len(ms) else len(text); body=text[m.start():end].strip()
        if len(body)>40: secs.append((m.group(1),m.group(2).strip(),body))
    laws.append(dict(id=rid,title=title,text=text,source_url=url,source_type='county_government_site',jurisdiction='US-'+c['state'],country='United States',language='en',eli='',date='',date_issued='',
        retrieved_at=d.get('pdf_fetched',''),license=terms,law_status='unknown',identifier=g,official_identifier=c['gnis'],article_count=len(secs),json_path=f"raw/wayback/ocr/{d['pdf']}.json",
        metadata_json=json.dumps(md,ensure_ascii=False),municipality_id=f"us-county-{g}",municipality_name=c['name']+', '+c['state'],wikidata_qid=c['qid']))
    for n,h,b in secs:
        aid=f'{rid}-s{n}'; k=2
        while aid in haveart: aid=f'{rid}-s{n}-{k}'; k+=1
        haveart.add(aid)
        arts.append(dict(law_id=rid,id=aid,title=h or f'Section {n}',text=b,source_url=url,document_number=g,article_number=n,record_type='article',
            metadata_json=json.dumps(dict(admin_level='county',geoid=g,record_type='article',ocr=True,ocr_engine=d.get('engine') or ENG,ocr_mean_conf=num(d.get('mean_conf')),fetch_via='wayback')),
            municipality_id=f"us-county-{g}",municipality_name=c['name']+', '+c['state'],wikidata_qid=c['qid']))
if DRY: os.makedirs(OUTD+'/data',exist_ok=True)
if not laws: print('0 rows - no shard written','skipped',len(skipped)); sys.exit(0)
from collections import Counter
print(packlib.write_pack(OUTD,laws,arts,f'laws-{N}.parquet',f'articles-{N}.parquet'),'skipped',len(skipped),Counter(r for _,r in skipped))
