# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import json,os,glob,hashlib,re,datetime
import pyarrow.parquet as pq
R=(str(_CORPORA) + '/county/KE')
def sha(p):
    h=hashlib.sha256(); h.update(open(p,'rb').read()); return h.hexdigest()
L=pq.read_table(f'{R}/data/laws-00005.parquet').to_pylist(); A=pq.read_table(f'{R}/data/articles-00005.parquet')
files=[]
for p in sorted(glob.glob(f'{R}/data/*.parquet')): files.append(dict(path=os.path.relpath(p,R),bytes=os.path.getsize(p),sha256=sha(p)))
raw=[dict(path='raw/'+os.path.basename(p),bytes=os.path.getsize(p),sha256=sha(p)) for p in sorted(glob.glob(f'{R}/raw/*.pdf'))]
per={}
for r in L:
    m=json.loads(r['metadata_json']); per.setdefault(r['municipality_name'],[]).append(dict(id=r['id'],title=r['title'],date=r['date'],articles=r['article_count'],ocr=m['ocr'],ocr_mean_conf=m.get('ocr_mean_conf'),source_url=r['source_url']))
man=dict(pack='county/KE (batch 5, add-only supplement to endomorphosis/ipfs_kenya_municipal_laws)',built=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),upload=False,
  counts=dict(laws=len(L),articles=A.num_rows,by_county={k:len(v) for k,v in per.items()}),files=files,raw_sources=raw,records=per,
  terms=dict(kenya_law="robots.txt Content-Signal ai-train=no, ai-input=no (EU DSM Art.4 reservation); not used as a source (WAF challenge)",caf_repository="no robots.txt (404), no terms page; third-party mirror",samburu_go_ke="robots allows /download/; footer © 2024; no terms page; bot-check pages skipped"),
  restricted_ai_training=True,
  notes=["Premise correction: HF repo already had Samburu (19 acts). Only Kirinyaga was absent. This pack adds Kirinyaga (5) and the 4 Samburu Acts not in the HF repo (Livestock Sale Yards 2018, Community Conservancies Fund 2019, Finance 2023, Finance 2025).",
         "OCR (tesseract, ocr=true): Samburu Livestock Sale Yards 2018 (conf 92.6), Community Conservancies Fund 2019 (conf 93.5), Finance 2023 (conf 67.2: tables)",
         "Section splitting is best-effort; the law-level text field is always complete. Samburu Sale Yards Act has no Act number on the copy so its FRBR key is constructed.",
         "kirinyaga.go.ke and kirinyagaassembly.go.ke fail TLS verification, samburuassembly.go.ke robots.txt returns 500, Wayback/Common Crawl were unavailable, Kenya Gazette via gazettes.africa carries ai-train=no - none used."])
json.dump(man,open(f'{R}/MANIFEST.json','w'),indent=1,ensure_ascii=False)
