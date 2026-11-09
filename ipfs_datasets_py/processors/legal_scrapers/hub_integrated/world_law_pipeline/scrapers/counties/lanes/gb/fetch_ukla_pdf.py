"""Fetch original (image) PDFs of county-naming local Acts that have no XML text. robots: only */data.pdf disallowed; /pdfs/ path allowed. Crawl-delay 5 s. TLS verified."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,os,json,time; sys.path.insert(0,os.path.dirname(__file__))
import polite, pyarrow.parquet as pq
B=(str(_CORPORA) + '/county/GB'); CAP=1.5*2**30
rows=[]
for f in ('metadata_only_acts-00001','metadata_only_acts-00002'): rows+=pq.read_table(f'{B}/data/{f}.parquet').to_pylist()
tot=sum(os.path.getsize(f'{B}/raw/ukla_pdf/{x}') for x in os.listdir(f'{B}/raw/ukla_pdf'))
for r in rows:
    url=json.loads(r['metadata_json'])['original_pdf'].replace('http://','https://')
    fn=f"{B}/raw/ukla_pdf/{url.rsplit('/',1)[1]}"
    if os.path.exists(fn): continue
    if tot>CAP: print('CAP reached',flush=True); break
    try:
        if 'data.pdf' in url: print('skip data.pdf',url); continue
        resp=polite.get(url,min_delay=5)
        if resp.status_code==200 and resp.content[:4]==b'%PDF':
            open(fn,'wb').write(resp.content); tot+=len(resp.content); print('OK',os.path.basename(fn),len(resp.content),flush=True)
        else: print('HTTP',resp.status_code,url,flush=True)
    except PermissionError: print('ROBOTS',url,flush=True)
    except Exception as e: print('ERR',url,e,flush=True); time.sleep(10)
print('DONE',tot,flush=True)
