"""Build US county shard N from raw/county_sites/docs.jsonl (default) or another docs.jsonl (skipping docs already built).
Usage: build_us_shard.py 00001 [SRC_DOCS_JSONL] [--dry]  (--dry writes to ../_state/dry_us_shard_N/)   e.g. raw/commoncrawl/docs.jsonl or raw/wayback/docs.jsonl (rows carry fetch_via)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,json,re,hashlib,os,glob,urllib.parse,pyarrow.parquet as pq
sys.path.insert(0,os.path.dirname(__file__)); import packlib
B=(str(_CORPORA) + '/county/US')
DRY='--dry' in sys.argv; sys.argv=[a for a in sys.argv if a!='--dry']; N=sys.argv[1]
SRC=sys.argv[2] if len(sys.argv)>2 else B+'/raw/county_sites/docs.jsonl'
if not SRC.startswith('/'): SRC=B+'/'+SRC
EXCLUDE_GEOID={'21111','21067','29510'}  # city-county consolidations / independent city -> municipal bot
NONCOUNTY=re.compile(r'\bISD\b|independent school|dockets?\b|order of assignment',re.I)  # archive sources only: other issuers / court dockets
assert (not os.path.exists(f'{B}/data/laws-{N}.parquet')) or (DRY and os.environ.get('DRY_SUFFIX')), 'shard exists (add-only; re-build only allowed as --dry with DRY_SUFFIX set, output to _state/)'
have=set()
for f in glob.glob(B+'/data/laws-*.parquet'):
    if not f.endswith(f'laws-{N}.parquet'): have|=set(pq.read_table(f,columns=['id']).column('id').to_pylist())
def thash(t): return hashlib.sha1(re.sub(r'\s+',' ',t).strip().lower().encode()).hexdigest()  # 2026-11-01: exact-text dedupe vs pack + batch (same rule as build_us_wayback_ocr_shard.py / 00010)
havetext=set()
for f in glob.glob(B+'/data/laws-*.parquet'):
    if not f.endswith(f'laws-{N}.parquet'): havetext|={thash(t or '') for t in pq.read_table(f,columns=['text']).column('text').to_pylist()}
NONGOV_HOST=re.compile(r'chamber|(^|\.)martincountykentucky\.com$|(^|\.)tourgreenupcounty\.com$',re.I)  # chambers of commerce / private marketing sites: not county government, not law (added 2026-10-31)
EXC=re.compile(r'privacy|terms of (use|service)|accessibility|sms |cookie|disclaimer',re.I)
SEC=re.compile(r'(?m)^\s*(?:Sec(?:tion|\.)|SECTION|§)\s*([0-9][0-9A-Za-z\.\-]*)\.?\s*[-–—.:]?\s*(.{0,120})$')
def empty_shell(d):  # 2026-11-01 (shard 00014): archive captures of CivicPlus nav shells with no content: empty DocumentCenter grid listings ('No records to display') and AlertCenter pages whose body never mentions the alert's own subject
    u=d['url']; t=d['text'] or ''
    if re.search(r'/DocumentCenter(/\d+)?/?(\?|$)',u) and 'No records to display' in t: return True
    if 'AlertCenter.aspx' in u:
        subj=[w for w in re.findall(r'[A-Za-z]{3,}',(d['title'] or '').split('\u2022')[-1]) if w.lower() not in ('alert','center')]
        body=t.split('\n',1)[1] if '\n' in t else ''
        if subj and not any(re.search(r'(?i)\b'+w+r'\b',body) for w in subj): return True
    return False

# --- 2026-11-02 (shard 00015 fix, Laws Normalizer request): language detection, doc_kind flag, version_date ---
_ES=set('de la el los las y en que del por para con una un se su al es como más sobre este esta están pueden público propuesta actividad notificación'.split())
_EN=set('the of and to in a for is that on be by with as or this are shall county any such'.split())
def detect_lang(t):  # stdlib-only en/es stopword heuristic on first 6000 chars; default 'en' (short/ambiguous/bilingual text stays 'en'); only returns 'en' or 'es'
    w=re.findall(r"[a-záéíóúñü]+",(t or '')[:6000].lower())
    if len(w)<30: return 'en'
    e=sum(x in _EN for x in w)/len(w); s=sum(x in _ES for x in w)/len(w)
    return 'es' if (s>2*e and s>0.15) else 'en'
STANDING_ORDER=re.compile(r'standing\s+(discovery\s+)?orders?',re.I)  # court orders (judge/JP/district court), not county law: flagged, never dropped (add-only)
_MON={m:i+1 for i,m in enumerate('january february march april may june july august september october november december'.split())}
REVISED=re.compile(r'(?m)^\s*REVISED:\s*(.+?)\s*$',re.I)
def version_info(d,title):  # real source data only: 'REVISED:' line in the document text; else (subdivision-policy titles only) the Wayback capture timestamp, labelled as such; else nothing
    m=REVISED.search(d['text'] or '')
    if m:
        raw=m.group(1).strip(); mm=re.match(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$',raw); my=re.match(r'([A-Za-z]+)\s+(?:x+|\d{0,2}x+),?\s+(\d{4})$',raw,re.I); y=re.match(r'(\d{4})$',raw)
        if mm and mm.group(1).lower() in _MON: return dict(version_date='%s-%02d-%02d'%(mm.group(3),_MON[mm.group(1).lower()],int(mm.group(2))),version_date_precision='day',version_date_source='document_text: "REVISED: '+raw+'"')
        if my and my.group(1).lower() in _MON: return dict(version_date='%s-%02d'%(my.group(2),_MON[my.group(1).lower()]),version_date_precision='month',version_date_source='document_text: "REVISED: '+raw+'" (day left blank in the document)')
        if y: return dict(version_date=y.group(1),version_date_precision='year',version_date_source='document_text: "REVISED: '+raw+'" (only the year is given)')
    ts=d.get('wb_timestamp')
    if ts and re.search(r'subdivision policy',title,re.I) and re.match(r'\d{14}$',ts):
        return dict(version_date='%s-%s-%s'%(ts[:4],ts[4:6],ts[6:8]),version_date_precision='day',version_date_source='wayback_capture_timestamp (%s); no revision date in the document text; this is the archive capture date, not the adoption/effective date'%ts)
    return {}
laws=[];arts=[];seen=set()
for i,l in enumerate(open(SRC,errors='replace')):
    if not l.strip(): continue
    try: d=json.loads(l)
    except ValueError: print('WARN corrupt line skipped',SRC,i+1); continue
    via=d.get('fetch_via','direct_county_site')
    if EXC.search(d['title']+d['url']) or d['geoid'] in EXCLUDE_GEOID: continue
    if via!='direct_county_site' and NONCOUNTY.search(urllib.parse.unquote(d['title']+' '+d['url'])): continue
    if NONGOV_HOST.search(urllib.parse.urlsplit(d['url']).hostname or ''): continue
    if via!='direct_county_site' and empty_shell(d): print('SKIP empty CivicPlus shell page (no document/alert content)',d['url']); continue
    rid=f"us-county-{d['geoid']}-{hashlib.sha256(d['url'].encode()).hexdigest()[:10]}"
    if rid in have or rid in seen: continue
    th=thash(d['text'])
    if th in havetext: print('SKIP identical text already in pack/batch',rid,d['url']); continue
    seen.add(rid); havetext.add(th)
    host=re.sub(r'^https?://([^/]+)/.*',r'\1',d['url'])
    terms=f"Public county-government document; fetched from county site with robots.txt honored (>=3 s/host); no explicit license reviewed (terms_reviewed=false); public-record status presumed."
    if via=='commoncrawl': terms=f"Public county-government document; retrieved from Common Crawl ({d.get('cc_crawl')}, WARC {d.get('warc_filename')} offset {d.get('warc_offset')}) via CDX index lookup + single ranged WARC read, not from the county site; Common Crawl Terms of Use apply to the archive; county live robots.txt status: {d.get('robots_live')}; no explicit license reviewed (terms_reviewed=false); public-record status presumed."
    elif via=='wayback': terms=f"Public county-government document; retrieved from the Internet Archive Wayback Machine ({d.get('wb_url')}) at <=1 req/s, not from the county site; Internet Archive Terms of Use apply to the archive; county live robots.txt status: {d.get('robots_live')}; no explicit license reviewed (terms_reviewed=false); public-record status presumed."
    if d.get('content_signal'): terms+=f" Site robots.txt Content-Signal: {d['content_signal']}."
    md=dict(admin_level='county',geoid=d['geoid'],gnis=d['gnis'],state=d['state'],county=d['county'],source_site=d['site'],content_kind=d['kind'],ocr=False,
            text_source='pdftotext' if d['kind']=='pdf' else 'html',local_pdf=d.get('pdf',''),terms=terms,content_signal=d.get('content_signal',''),fetch_via=via,record_type='law')
    for k in ('cc_crawl','cc_timestamp','warc_filename','warc_offset','warc_length','warc_truncated','robots_live','wb_timestamp','wb_url'):
        if k in d: md[k]=d[k]
    ttl=d['title'] or d['url']
    if STANDING_ORDER.search(urllib.parse.unquote(ttl)): md['doc_kind']='court_standing_order'
    md.update(version_info(d,ttl))
    text=d['text']; secs=[]
    ms=list(SEC.finditer(text))
    for i,m in enumerate(ms):
        end=ms[i+1].start() if i+1<len(ms) else len(text); body=text[m.start():end].strip()
        if len(body)>40: secs.append((m.group(1),m.group(2).strip(),body))
    laws.append(dict(id=rid,title=d['title'] or d['url'],text=text,source_url=d['url'],source_type='county_government_site',jurisdiction='US-'+d['state'],country='United States',language=detect_lang(d['text']),eli='',date='',date_issued='',
        retrieved_at=d['fetched'],license=terms,law_status='unknown',identifier=d['geoid'],official_identifier=d['gnis'],article_count=len(secs),json_path='',metadata_json=json.dumps(md,ensure_ascii=False),
        municipality_id=f"us-county-{d['geoid']}",municipality_name=d['county']+', '+d['state'],wikidata_qid=d['qid']))
    used=set()
    for n,h,b in secs:
        aid=f'{rid}-s{n}'; k=2
        while aid in used: aid=f'{rid}-s{n}-{k}'; k+=1
        used.add(aid)
        arts.append(dict(law_id=rid,id=aid,title=h or f'Section {n}',text=b,source_url=d['url'],document_number=d['geoid'],article_number=n,record_type='article',
            metadata_json=json.dumps(dict(admin_level='county',geoid=d['geoid'],record_type='article')),municipality_id=f"us-county-{d['geoid']}",municipality_name=d['county']+', '+d['state'],wikidata_qid=d['qid']))
OUT=B+'/../_state/dry_us_shard_'+N+os.environ.get('DRY_SUFFIX','') if DRY else B
if DRY: os.makedirs(OUT,exist_ok=True); assert not os.path.exists(f'{OUT}/data/laws-{N}.parquet'), 'dry output exists'
if not laws: print('NO QUALIFYING LAW ROWS - shard not written'); sys.exit(0)
print(packlib.write_pack(OUT,laws,arts,f'laws-{N}.parquet',f'articles-{N}.parquet'))
