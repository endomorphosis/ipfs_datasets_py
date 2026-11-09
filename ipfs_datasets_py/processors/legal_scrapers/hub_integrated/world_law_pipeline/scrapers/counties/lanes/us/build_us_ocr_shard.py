"""Build add-only US OCR shard N from raw/ocr/*.json (rapidocr of locally saved image-only county PDFs). ocr=true on every row.
Usage: build_us_ocr_shard.py 00003 [--dry]   (--dry writes to /tmp/us_ocr_dry instead of data/)"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,json,re,hashlib,os,glob,urllib.parse,datetime,pyarrow.parquet as pq
sys.path.insert(0,os.path.dirname(__file__)); import packlib
B=(str(_CORPORA) + '/county/US'); N=sys.argv[1]; DRY='--dry' in sys.argv
OUTD='/tmp/us_ocr_dry' if DRY else B
if not DRY: assert not os.path.exists(f'{B}/data/laws-{N}.parquet') and not os.path.exists(f'{B}/data/articles-{N}.parquet'), 'shard exists (add-only)'
have=set(); haveart=set()
for f in glob.glob(B+'/data/laws-*.parquet'): have|=set(pq.read_table(f,columns=['id']).column('id').to_pylist())
for f in glob.glob(B+'/data/articles-*.parquet'): haveart|=set(pq.read_table(f,columns=['id']).column('id').to_pylist())
tg={c['geoid']:c for c in json.load(open(B+'/raw/targets_tx_mo_ky_wikidata.json'))}
EXC=re.compile(r'privacy|terms of (use|service)|accessibility|sms |cookie|disclaimer',re.I)
SEC=re.compile(r'(?m)^\s*(?:Sec(?:tion|\.)|SECTION|§)\s*([0-9][0-9A-Za-z\.\-]*)\.?\s*[-–—.:]?\s*(.{0,120})$')
ENG='rapidocr-onnxruntime 1.2.3'
laws=[];arts=[];skipped=[]
for f in sorted(glob.glob(B+'/raw/ocr/*.json')):
    d=json.load(open(f))
    if not d.get('ocr'): skipped.append((d['pdf'],'ocr error')); continue
    c=tg[d['geoid']]; url=d['url']; pdf=f"{B}/raw/county_sites/pdf/{d['pdf']}.pdf"
    title=urllib.parse.unquote(url.rsplit('/',1)[-1]).rsplit('.pdf',1)[0].replace('_',' ').strip() or url
    if EXC.search(title+url): skipped.append((d['pdf'],'excluded title')); continue
    text='\n\n'.join(d['page_text']).strip()
    if len(text)<50: skipped.append((d['pdf'],'empty ocr text')); continue
    rid=f"us-county-{d['geoid']}-{hashlib.sha256(url.encode()).hexdigest()[:10]}"
    if rid in have: skipped.append((d['pdf'],'id exists in other shard')); continue
    have.add(rid)
    host=urllib.parse.urlparse(url).netloc
    terms="Public county-government document; fetched from county site with robots.txt honored (>=3 s/host); no explicit license reviewed (terms_reviewed=false); public-record status presumed. Text is machine OCR of an image-only PDF; expect errors."
    md=dict(admin_level='county',geoid=d['geoid'],gnis=c['gnis'],state=c['state'],county=c['name'],source_site=c['sites'][0] if c['sites'] else host,content_kind='pdf',
            ocr=True,ocr_engine=d.get('engine') or ENG,ocr_mean_conf=d.get('mean_conf'),ocr_pages=d.get('pages'),ocr_render_long_side_px=d.get('render_long_side_px'),
            text_source='ocr_of_local_image_only_pdf',local_pdf=pdf,terms=terms,fetch_via='direct_county_site',record_type='law',ocr_note='machine OCR; not authoritative')
    secs=[];ms=list(SEC.finditer(text))
    for i,m in enumerate(ms):
        end=ms[i+1].start() if i+1<len(ms) else len(text); body=text[m.start():end].strip()
        if len(body)>40: secs.append((m.group(1),m.group(2).strip(),body))
    fetched=datetime.datetime.fromtimestamp(os.path.getmtime(pdf)).astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')
    laws.append(dict(id=rid,title=title,text=text,source_url=url,source_type='county_government_site',jurisdiction='US-'+c['state'],country='United States',language='en',eli='',date='',date_issued='',
        retrieved_at=fetched,license=terms,law_status='unknown',identifier=d['geoid'],official_identifier=c['gnis'],article_count=len(secs),json_path=f"raw/ocr/{d['pdf']}.json",metadata_json=json.dumps(md,ensure_ascii=False),
        municipality_id=f"us-county-{d['geoid']}",municipality_name=c['name']+', '+c['state'],wikidata_qid=c['qid']))
    for n,h,b in secs:
        aid=f'{rid}-s{n}'; k=2
        while aid in haveart: aid=f'{rid}-s{n}-{k}'; k+=1
        haveart.add(aid)
        arts.append(dict(law_id=rid,id=aid,title=h or f'Section {n}',text=b,source_url=url,document_number=d['geoid'],article_number=n,record_type='article',
            metadata_json=json.dumps(dict(admin_level='county',geoid=d['geoid'],record_type='article',ocr=True,ocr_engine=d.get('engine') or ENG,ocr_mean_conf=d.get('mean_conf'))),
            municipality_id=f"us-county-{d['geoid']}",municipality_name=c['name']+', '+c['state'],wikidata_qid=c['qid']))
if DRY: os.makedirs(OUTD+'/data',exist_ok=True)
print(packlib.write_pack(OUTD,laws,arts,f'laws-{N}.parquet',f'articles-{N}.parquet'),'skipped',len(skipped),skipped[:20])
