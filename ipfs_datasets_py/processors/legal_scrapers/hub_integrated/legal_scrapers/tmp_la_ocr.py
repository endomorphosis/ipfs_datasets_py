# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, sys, requests
sys.path.insert(0,str(_SCRAPERS) + "/scrapers")
from pathlib import Path
from pdf_extract_lib import extract_pdf_text, honest_split, is_garbage_text
import archive_fallbacks as af
requests.packages.urllib3.disable_warnings()
instr=Path(str(_CORPORA) + '/la/instruments')
for p in instr.glob('*.json'):
  rec=json.loads(p.read_text())
  url=rec.get('source_url') or ''
  print('===', p.name)
  w=af.get_wayback_content(url)
  body=w.get('content') or b''
  if body[:4]!=b'%PDF':
    try:
      r=requests.get(url, timeout=60, verify=False)
      body=r.content or b''
    except Exception as e:
      print('fail', e); continue
  print('pdf bytes', len(body), body[:5])
  if body[:4]!=b'%PDF':
    print('not pdf'); continue
  text,how,pages=extract_pdf_text(body, enable_ocr=True, ocr_lang='eng', ocr_max_pages=20)
  print('extract', how, len(text), 'garbage', is_garbage_text(text), 'pages', pages)
  print(repr((text or '')[:200].replace('\n',' ')))
  docs,kind=honest_split('la', text, rec.get('id') or p.stem, url)
  print('arts', len(docs), kind)
  if text and len(text)>=80 and not is_garbage_text(text):
    if len(text) > len(rec.get('text') or '') * 0.8 or is_garbage_text(rec.get('text') or ''):
      rec['text']=text
      rec['documents']=docs
      rec['article_count']=len(docs)
      meta=rec.get('metadata') or {}
      meta['pdf_reextract']={'method':how,'pages':pages}
      meta['article_split']={'method':kind,'count':len(docs)}
      rec['metadata']=meta
      p.write_text(json.dumps(rec, ensure_ascii=False, indent=2)+'\n')
      print('updated')
