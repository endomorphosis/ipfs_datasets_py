#!/usr/bin/env python3
"""Build add-only KE supplement (batch 5): Kirinyaga (5 Acts) + Samburu (Acts missing from batch 1-4)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,os,re,json,subprocess,glob; sys.path.insert(0,os.path.dirname(__file__))
import packlib as P
ROOT=(str(_CORPORA) + '/county/KE')
TERMS_KL=("Kenya Law (new.kenyalaw.org) robots.txt content signals: ai-train=no, ai-input=no, search=yes, with an express EU DSM Art.4 rights reservation; "
          "site contents described as public domain except CC-marked material (https://new.kenyalaw.org/terms-of-use/). Kenya Law document pages returned an AWS WAF challenge, so the PDFs were NOT taken from Kenya Law.")
TERMS_CAF=("Copy fetched from the County Assemblies Forum Knowledge Repository (repository.org.countyassembliesforum.org), a third-party mirror of Kirinyaga County Assembly PDFs: "
           "no robots.txt (404), no terms-of-use page found. County Acts are written law (Constitution of Kenya Art.260; Copyright Act Cap.130 s.2 excludes written law). "
           "Kenya Law lists the same Acts under ai-train=no / ai-input=no content signals - treat as restricted for AI training until cleared. Not legal advice.")
TERMS_SB=("County Government of Samburu website (samburu.go.ke): robots.txt allows /download/ (only /wp-admin/ and /imunify-bot-check disallowed); footer 'Copyright © 2024', no terms-of-use. "
          "Enacted county Acts are written law (Constitution Art.260). Pages intermittently served an 'imunify-bot-check' challenge; those were skipped, not bypassed.")
KIR=dict(mid='ke-020',mname='Kirinyaga County',qid='Q2230311')
SAM=dict(mid='ke-025',mname='Samburu County',qid='Q2096419')
DOCS=[
 dict(c=KIR,file='kirinyaga-county-supplementary-appropriation-act-2015-2015-20.pdf',year=2015,no=1,date='2015-01-26',title='Kirinyaga County Supplementary Appropriation Act, 2015',
      src='https://repository.org.countyassembliesforum.org/repository/documents/kirinyaga-county-supplementary-appropriation-act-2015-2015-20/download/',official='https://new.kenyalaw.org/akn/ke-020/act/2015/1/eng@2015-01-26',stype='caf_repository_kirinyaga_assembly',terms=TERMS_CAF+' '+TERMS_KL),
 dict(c=KIR,file='kirinyaga-county-revenue-administration-act-2015-2015-20.pdf',year=2015,no=3,date='2015-10-27',title='Kirinyaga County Revenue Administration Act, 2015',
      src='https://repository.org.countyassembliesforum.org/repository/documents/kirinyaga-county-revenue-administration-act-2015-2015-20/download/',official='https://new.kenyalaw.org/akn/ke-020/act/2015/3/eng@2015-10-27',stype='caf_repository_kirinyaga_assembly',terms=TERMS_CAF+' '+TERMS_KL),
 dict(c=KIR,file='kirinyaga-county-emergency-fund-act-2015-2015-20.pdf',year=2015,no=4,date='2015-10-27',title='Kirinyaga County Emergency Fund Act, 2015',
      src='https://repository.org.countyassembliesforum.org/repository/documents/kirinyaga-county-emergency-fund-act-2015-2015-20/download/',official='https://new.kenyalaw.org/akn/ke-020/act/2015/4/eng@2015-10-27',stype='caf_repository_kirinyaga_assembly',terms=TERMS_CAF+' '+TERMS_KL),
 dict(c=KIR,file='kirinyaga-county-education-act-2016-2016-20.pdf',year=2016,no=1,date='2016-02-19',title='Kirinyaga County Education Act, 2016',
      src='https://repository.org.countyassembliesforum.org/repository/documents/kirinyaga-county-education-act-2016-2016-20/download/',official='https://new.kenyalaw.org/akn/ke-020/act/2016/1/eng@2016-02-19',stype='caf_repository_kirinyaga_assembly',terms=TERMS_CAF+' '+TERMS_KL),
 dict(c=KIR,file='kirinyaga-county-appropriation-act-2016-2016-20.pdf',year=2016,no=2,date='2016-07-01',title='Kirinyaga County Appropriation Act, 2016',
      src='https://repository.org.countyassembliesforum.org/repository/documents/kirinyaga-county-appropriation-act-2016-2016-20/download/',official='https://new.kenyalaw.org/akn/ke-020/act/2016/2/eng@2016-07-01',stype='caf_repository_kirinyaga_assembly',terms=TERMS_CAF+' '+TERMS_KL),
 dict(c=SAM,file='samburu-sc-livestock-saleyards-act-2018.pdf',year=2018,no=None,date='2018-01-04',title='Samburu County Livestock Sale Yards Act, 2018',
      src='https://www.samburu.go.ke/download/sc-livestock-saleyards-act-2018/',official='',stype='samburu_county_government_downloads',terms=TERMS_SB,ocr=True,ocrtxt='scratch/ocr_saleyards'),
 dict(c=SAM,file='samburu-sc-community-conservancies-fund-act-2019.pdf',year=2019,no=5,date='2020-02-11',title='Samburu County Community Conservancies Fund Act, 2019',
      src='https://www.samburu.go.ke/download/sc-community-conservances-fund-act-2019/',official='https://new.kenyalaw.org/akn/ke-025/act/2019/5',stype='samburu_county_government_downloads',terms=TERMS_SB+' '+TERMS_KL,ocr=True,ocrtxt='scratch/ocr_conserv2019',marker='Kenya Gazette Supplement'),
 dict(c=SAM,file='samburu-sc-finance-act-2023.pdf',year=2023,no=4,date='2024-02-06',title='Samburu County Finance Act, 2023',
      src='https://www.samburu.go.ke/download/sc-finance-act-2023/',official='https://new.kenyalaw.org/akn/ke-025/act/2023/4',stype='samburu_county_government_downloads',terms=TERMS_SB+' '+TERMS_KL,ocr=True,ocrtxt='scratch/ocr_fin2023',marker='Kenya Gazette Supplement'),
 dict(c=SAM,file='samburu-county-finance-act-2025.pdf',year=2025,no=4,date='2025-12-22',title='Samburu County Finance Act, 2025',
      src='https://www.samburu.go.ke/download/the-samburu-county-finance-act-2025/',official='',stype='samburu_county_government_downloads',terms=TERMS_SB,note='Kenya Gazette Supplement No. 10 (Samburu County Acts No. 4), Nairobi 22 Dec 2025; assent 15 Dec 2025; text layer present'),
]
laws=[];arts=[];rt=P.now();stats=[]
for d in DOCS:
    path=f"{ROOT}/raw/{d['file']}"
    if d.get('ocr'):
        txt='\n'.join(open(f).read() for f in sorted(glob.glob(f"{ROOT}/{d['ocrtxt']}/p-*.txt")))
        i=txt.find(d.get('marker','SAMBURU COUNTY LIVESTO')); txt=txt[i:] if i>=0 else txt
        import csv,statistics
        cs=[]
        for f in glob.glob(f"{ROOT}/{d['ocrtxt']}/p-*.tsv"):
            for r in csv.DictReader(open(f),delimiter='\t',quoting=csv.QUOTE_NONE):
                try:
                    if (r['text'] or '').strip() and float(r['conf'])>=0: cs.append(float(r['conf']))
                except Exception: pass
        d['conf']=round(statistics.mean(cs),1)
    else:
        txt=subprocess.run(['pdftotext',path,'-'],capture_output=True,text=True).stdout
    txt=re.sub(r'\n{3,}','\n\n',txt).strip()
    c=d['c']; key=f"{d['year']}-{d['no']}" if d['no'] else f"{d['year']}-{re.sub(r'[^a-z0-9]+','-',d['title'].lower()).strip('-')[:40]}"
    lid=f"ke-muni-{c['mid']}-act-{key}"
    eli=f"/akn/{c['mid']}/act/{d['year']}/{d['no']}" if d['no'] else f"/akn/{c['mid']}/act/{d['year']}/{key.split('-',1)[1]}"
    secs=P.split_sections(txt)
    ident=f"Act No. {d['no']} of {d['year']}" if d['no'] else f"Act of {d['year']} (number not stated on copy)"
    meta=dict(note=d.get('note',''),schema_version="collection_record.v1",record_type="law",law_identifier=lid,frbr_work=eli,citation=ident,display_type="pdf",
              source_file=d['file'],source_sha256=P.sha256(path),source_bytes=os.path.getsize(path),ocr=bool(d.get('ocr')),
              text_backend='tesseract-5 psm6 300dpi' if d.get('ocr') else 'pdftotext',official_source_url=d['official'],
              terms=d['terms'],restricted_ai_training=True,pack="county/KE batch5 add-only supplement",
              frbr_key_constructed=not bool(d['no']) )
    if d.get('ocr'): meta['ocr_mean_conf']=d['conf']; meta['note']='image-only scanned PDF; OCR text contains errors; stamp noise on cover removed from start of text'
    laws.append(dict(id=lid,title=d['title'],text=txt,source_url=d['src'],source_type=d['stype'],jurisdiction='KE',country='Kenya',language='en',eli=eli,date=d['date'],date_issued=d['date'],
        retrieved_at=rt,license=d['terms'],law_status='current',identifier=ident,official_identifier=eli,article_count=len(secs),json_path='',metadata_json=json.dumps(meta,ensure_ascii=False),
        municipality_id=c['mid'],municipality_name=c['mname'],wikidata_qid=c['qid']))
    for n,h,t in secs:
        title=f"{n}. {h}" if (h and not d.get("ocr")) else f"{n}."
        arts.append(dict(law_id=lid,id=f"{lid}-s-{n}",title=title,text=t,source_url=d['src'],document_number=f"section {n}",article_number=f"section {n}",record_type='article',
            metadata_json=json.dumps(dict(law_identifier=lid,kind='section',ocr=bool(d.get('ocr'))),ensure_ascii=False),municipality_id=c['mid'],municipality_name=c['mname'],wikidata_qid=c['qid']))
    stats.append((d['title'],len(txt),len(secs)))
nl,na=P.write_pack(ROOT,laws,arts,'laws-00005.parquet','articles-00005.parquet')
for s in stats: print(s)
print('laws',nl,'articles',na)
