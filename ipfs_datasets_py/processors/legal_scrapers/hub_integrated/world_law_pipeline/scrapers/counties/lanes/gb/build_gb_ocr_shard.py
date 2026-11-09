"""Build GB laws/articles shard N from raw/ukla_ocr/*.json (rapidocr) + metadata_only_acts rows. Usage: build_gb_ocr_shard.py 00003"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,json,glob,os,re,pyarrow.parquet as pq
sys.path.insert(0,os.path.dirname(__file__)); import packlib
from packlib import split_sections
B=(str(_CORPORA) + '/county/GB'); N=sys.argv[1]
meta={}
for f in sorted(glob.glob(B+'/data/metadata_only_acts-0000*.parquet')):
    for r in pq.read_table(f).to_pylist(): meta[json.loads(r['metadata_json']).get('original_pdf','').rsplit('/',1)[-1][:-4]]=r
have=set()
for f in glob.glob(B+'/data/laws-000[0-9][0-9].parquet'):
    if int(f[-13:-8])>=3 and not f.endswith(f'laws-{N}.parquet'): have|=set(pq.read_table(f,columns=['id']).column('id').to_pylist())
laws=[];arts=[];skipped=[]
for f in sorted(glob.glob(B+'/raw/ukla_ocr/*.json')):
    d=json.load(open(f)); base=d['pdf']; m=re.match(r'ukla_(\d{4})(\d{4})_en',base); yr,no=m.group(1),str(int(m.group(2)))
    r=meta.get(base); rid=r['id'] if r else f'gb-county-ukla-{yr}-{no}'
    if rid in have: continue
    if r is None: skipped.append((base,'no metadata row')); continue
    if not d.get('ocr'): skipped.append((base,'textlayer/not OCR')); continue
    text='\n\n'.join(d['page_text']); md=json.loads(r['metadata_json'])
    md.update(admin_level='county',ocr=True,ocr_engine=d.get('engine'),ocr_mean_conf=d.get('mean_conf'),ocr_pages=d.get('pages'),ocr_render_long_side_px=d.get('render_long_side_px'),
              text_source='ocr_of_robots_allowed_pdf',pdf=md.get('original_pdf'),
              terms='OGL v3.0; legislation.gov.uk robots Crawl-delay 5, */data.pdf disallowed (this PDF fetched from allowed /pdfs/ path)',
              ocr_note='machine OCR of scanned as-enacted PDF; expect errors; not authoritative')
    secs=split_sections(text)
    row=dict(r); row.update(text=text,article_count=len(secs),metadata_json=json.dumps(md,ensure_ascii=False),json_path=f'raw/ukla_ocr/{base}.json')
    laws.append(row)
    for n,h,t in secs:
        arts.append(dict(law_id=rid,id=f'{rid}-s{n}',title=h or f'Section {n}',text=t,source_url=r['source_url'],document_number=r.get('identifier',''),article_number=str(n),record_type='article',
            metadata_json=json.dumps(dict(admin_level='county',ocr=True,ocr_engine=d.get('engine'),ocr_mean_conf=d.get('mean_conf'),record_type='article')),municipality_id=r['municipality_id'],municipality_name=r['municipality_name'],wikidata_qid=r.get('wikidata_qid','')))
print(packlib.write_pack(B,laws,arts,f'laws-{N}.parquet',f'articles-{N}.parquet'),'skipped',skipped)
