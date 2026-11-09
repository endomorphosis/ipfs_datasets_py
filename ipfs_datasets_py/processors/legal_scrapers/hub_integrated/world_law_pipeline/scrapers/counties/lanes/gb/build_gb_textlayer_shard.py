"""Build GB shard N from text-layer (non-OCR) local-Act PDFs marked textlayer=true in raw/ukla_ocr. Add-only; skips ids in shards >=00003. Usage: build_gb_textlayer_shard.py 00008"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,json,glob,os,subprocess,pyarrow.parquet as pq
sys.path.insert(0,os.path.dirname(__file__)); import packlib
from packlib import split_sections
B=(str(_CORPORA) + '/county/GB'); N=sys.argv[1]
assert not os.path.exists(f'{B}/data/laws-{N}.parquet'), 'shard exists (add-only)'
meta={}
for f in sorted(glob.glob(B+'/data/metadata_only_acts-0000*.parquet')):
    for r in pq.read_table(f).to_pylist(): meta[json.loads(r['metadata_json']).get('original_pdf','').rsplit('/',1)[-1][:-4]]=r
have=set()
for f in glob.glob(B+'/data/laws-000[0-9][0-9].parquet'):
    if int(f[-13:-8])>=3: have|=set(pq.read_table(f,columns=['id']).column('id').to_pylist())
laws=[];arts=[]
for f in sorted(glob.glob(B+'/raw/ukla_ocr/*.json')):
    d=json.load(open(f)); base=d['pdf']
    if not d.get('textlayer'): continue
    r=meta.get(base)
    if r is None or r['id'] in have: continue
    rid=r['id']; text=subprocess.run(['pdftotext','-layout' if False else '-raw',f'{B}/raw/ukla_pdf/{base}.pdf','-'],capture_output=True,text=True).stdout.replace('\f','\n\n')
    md=json.loads(r['metadata_json'])
    md.update(admin_level='county',ocr=False,text_source='pdf_text_layer (pdftotext -raw) of robots-allowed PDF',pdf=md.get('original_pdf'),
              terms='OGL v3.0; legislation.gov.uk robots Crawl-delay 5, */data.pdf disallowed (this PDF fetched from allowed /pdfs/ path)',
              note='embedded text layer of scanned as-enacted PDF (provider OCR); may contain errors; not authoritative')
    secs=split_sections(text)
    row=dict(r); row.update(text=text,article_count=len(secs),metadata_json=json.dumps(md,ensure_ascii=False),json_path=f'raw/ukla_pdf/{base}.pdf')
    laws.append(row)
    for n,h,t in secs:
        arts.append(dict(law_id=rid,id=f'{rid}-s{n}',title=h or f'Section {n}',text=t,source_url=r['source_url'],document_number=r.get('identifier',''),article_number=str(n),record_type='article',
            metadata_json=json.dumps(dict(admin_level='county',ocr=False,text_source='pdf_text_layer',record_type='article')),municipality_id=r['municipality_id'],municipality_name=r['municipality_name'],wikidata_qid=r.get('wikidata_qid','')))
print(packlib.write_pack(B,laws,arts,f'laws-{N}.parquet',f'articles-{N}.parquet'))
