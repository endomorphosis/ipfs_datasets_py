#!/usr/bin/env python3
"""Build GB county pack: local Acts (legislation.gov.uk ukla XML) + county-council byelaws. Add-only; new files only."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,os,re,json,glob,subprocess,hashlib; sys.path.insert(0,os.path.dirname(__file__))
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup
import packlib as P
B=(str(_CORPORA) + '/county/GB')
L='{http://www.legislation.gov.uk/namespaces/legislation}'
M='{http://www.legislation.gov.uk/namespaces/metadata}'
DC='{http://purl.org/dc/elements/1.1/}'
OGL="Open Government Licence v3.0 (legislation.gov.uk; Crown/King's Printer copyright; https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). robots.txt: Crawl-delay 5; Disallow */data.pdf and */data.docx (not fetched); no AI content-signal. Local Acts' text is Crown copyright re-used under OGL v3."
def txt(el): return re.sub(r'\s+',' ',' '.join(t.strip() for t in el.itertext() if t.strip())).strip()
def county_of(title):
    m=re.search(r'^(?:Royal )?(?:County of )?(.+?)(?: and (.+?))? County Councils?\b',title) or re.search(r'^County of (.+?) Act',title) or re.search(r'^(.+?) County\b',title)
    n=(m.group(1) if m else title.split(' Act')[0]).strip()
    return n
def slug(s): return re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-')
import pyarrow.parquet as pq
done=set()
for f in ('laws-00001.parquet','metadata_only_acts-00001.parquet'):
    done|={r['id'] for r in pq.read_table(f'{B}/data/{f}',columns=['id']).to_pylist()}
laws=[];arts=[];nolaws=[];rt=P.now()
sel={x['id'].split('/id/')[-1]:x for x in json.load(open(f'{B}/raw/ukla_selected.json'))}
for key,x in sel.items():
    fn=f"{B}/raw/ukla/{key.replace('/','_')}.xml"
    if not os.path.exists(fn): continue
    root=ET.parse(fn).getroot()
    md=root.find(f'{M}Metadata'); title=md.find(f'{DC}title').text
    year=md.find(f'.//{M}Year').get('Value'); no=md.find(f'.//{M}Number').get('Value')
    ed=md.find(f'.//{M}EnactmentDate'); date=ed.get('Date') if ed is not None else ''
    pdfl=[a.get('href') for a in md.iter('{http://www.w3.org/2005/Atom}link') if a.get('title')=='Original PDF']
    body=root.find(f'.//{L}Body'); scheds=root.find(f'.//{L}Schedules'); prelims=root.find(f'.//{L}PrimaryPrelims')
    county=county_of(title); cslug=slug(county)
    lid=f"gb-county-ukla-{slug(key.split('ukla/')[1])}"
    if lid in done: continue
    rec=dict(id=lid,title=title,source_url=f"https://www.legislation.gov.uk/{key}",source_type='legislation_gov_uk_local_act',jurisdiction='GB',country='United Kingdom',language='en',eli=f"/{key}",
        date=date,date_issued=date,retrieved_at=rt,license=OGL,law_status='as_enacted',identifier=f"{year} c. {no} (local)" if re.fullmatch(r'\d{4}',year) else f"{year} {no} (local)",official_identifier=f"/{key}",json_path='',
        municipality_id=f"gb-county-{cslug}",municipality_name=f"{county} County Council" if 'Council' in title else f"{county}",wikidata_qid='')
    meta=dict(schema_version="collection_record.v1",record_type="law",law_identifier=lid,act_type="UnitedKingdomLocalAct",year=year,number=no,source_file=os.path.relpath(fn,B),
        source_sha256=P.sha256(fn),original_pdf=pdfl[0] if pdfl else '',terms=OGL,restricted_ai_training=False,pack="county/GB")
    secs=[]
    if body is not None:
        for g in body.iter():
            if g.tag==f'{L}P1group':
                h=g.find(f'{L}Title'); h=txt(h) if h is not None else ''
                for p1 in g.findall(f'{L}P1'):
                    n=p1.find(f'{L}Pnumber'); n=txt(n) if n is not None else str(len(secs)+1)
                    secs.append((f"section {n}",h,txt(p1)))
            elif g.tag==f'{L}P1' and False: pass
        if not secs:
            for p1 in body.iter(f'{L}P1'):
                n=p1.find(f'{L}Pnumber'); secs.append((f"section {txt(n) if n is not None else len(secs)+1}",'',txt(p1)))
    if scheds is not None:
        for i,s in enumerate(scheds.findall(f'.//{L}Schedule'),1):
            tb=s.find(f'{L}TitleBlock'); n=s.find(f'{L}Number')
            secs.append((f"schedule {txt(n) if n is not None else i}",txt(tb) if tb is not None else '',txt(s)))
    has_text=sum(len(t) for _,_,t in secs)>200
    pre=txt(prelims) if prelims is not None else ''
    full='\n\n'.join([title,pre]+[f"{('['+h+'] ') if h else ''}{t}" for _,h,t in secs]).strip()
    if not has_text:
        meta.update(text_available=False,note='legislation.gov.uk holds only an image PDF for this local Act (data.pdf is robots-disallowed; original PDF not OCR-ed in this run)')
        rec.update(text='',article_count=0,metadata_json=json.dumps(meta,ensure_ascii=False)); nolaws.append(rec); continue
    meta.update(text_available=True)
    rec.update(text=full,article_count=len(secs),metadata_json=json.dumps(meta,ensure_ascii=False)); laws.append(rec)
    for an,h,t in secs:
        arts.append(dict(law_id=lid,id=f"{lid}-{slug(an)}",title=f"{an.split()[-1]}. {h}" if h else an,text=t,source_url=rec['source_url'],document_number=an,article_number=an,record_type='article',
            metadata_json=json.dumps(dict(law_identifier=lid,kind=an.split()[0]),ensure_ascii=False),municipality_id=rec['municipality_id'],municipality_name=rec['municipality_name'],wikidata_qid=''))
nl,na=P.write_pack(B,laws,arts,'laws-00002.parquet','articles-00002.parquet')
if nolaws:
    import pyarrow as pa, pyarrow.parquet as pq
    pq.write_table(pa.Table.from_pylist([{k:(int(r[k]) if k=='article_count' else (r.get(k) or '')) for k in P.LAW_COLS} for r in nolaws],schema=pa.schema([(c,pa.int32() if c=='article_count' else pa.string()) for c in P.LAW_COLS])),f'{B}/data/metadata_only_acts-00002.parquet',compression='zstd')
print('laws',nl,'articles',na,'metadata_only',len(nolaws))
