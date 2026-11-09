"""Select county-level local Acts from ukla_candidates.json and fetch data.xml (robots Crawl-delay 5 s; data.pdf/docx never touched)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,os,re,json,time; sys.path.insert(0,os.path.dirname(__file__))
import polite
B=(str(_CORPORA) + '/county/GB')
c=json.load(open(f'{B}/raw/ukla_candidates.json'))
EXC=re.compile(r'Electric|Railway|Tramway|Water Board|River Authority|Market|Marylebone|Eastern Counties|London|West Midlands|Greater Manchester|Merseyside|Tyne and Wear|South Yorkshire|West Yorkshire|Turnpike|Canal|Harbour',re.I)
sel=[x for x in c if re.search(r'County|Counties',x['title']) and not EXC.search(x['title'])]
json.dump(sel,open(f'{B}/raw/ukla_selected.json','w'),indent=1)
print('selected',len(sel),flush=True)
for i,x in enumerate(sel):
    key=x['id'].split('/id/')[-1]
    fn=f"{B}/raw/ukla/{key.replace('/','_')}.xml"
    if os.path.exists(fn): continue
    for attempt in range(2):
        try:
            r=polite.get(f"https://www.legislation.gov.uk/{key}/data.xml",min_delay=5)
            if r.status_code==200: open(fn,'wb').write(r.content)
            else: print('HTTP',r.status_code,key,flush=True)
            break
        except PermissionError as e: print('ROBOTS',key,flush=True); break
        except Exception as e:
            print('ERR',key,e,flush=True); time.sleep(10)
    if i%20==0: print(i,key,flush=True)
print('DONE',flush=True)
