# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,re,json,urllib.parse; sys.path.insert(0, _ipfs_os.path.dirname(_ipfs_os.path.abspath(__file__)))
import polite
from xml.etree import ElementTree as ET
NS={'a':'http://www.w3.org/2005/Atom','leg':'http://www.legislation.gov.uk/namespaces/legislation','ukm':'http://www.legislation.gov.uk/namespaces/metadata'}
counties=["Bedfordshire","Berkshire","Buckinghamshire","Cambridgeshire","Cheshire","Cleveland","Cornwall","Cumbria","Cumberland","Derbyshire","Devon","Dorset","Durham","East Sussex","Essex","Gloucestershire","Hampshire","Hertfordshire","Humberside","Isle of Wight","Kent","Lancashire","Leicestershire","Lincolnshire","Norfolk","Northamptonshire","Northumberland","North Yorkshire","Nottinghamshire","Oxfordshire","Rutland","Shropshire","Somerset","Staffordshire","Suffolk","Surrey","Warwickshire","West Sussex","Wiltshire","Worcestershire","Herefordshire","Avon","East Riding","Dyfed","Gwent","Clwyd","Gwynedd","Powys","Glamorgan","Pembrokeshire","Carmarthenshire","Ceredigion","Monmouthshire","Denbighshire","Flintshire","Anglesey","Conwy","Wrexham","Merioneth","Huntingdon","Peterborough","Middlesex","Yorkshire","Lindsey","Kesteven","Holland","Westmorland","Hereford and Worcester","Lothian","Fife"]
queries=["County Council"]+counties
seen={}
def run(q):
    p=1
    while True:
        u="https://www.legislation.gov.uk/search/data.feed?type=ukla&title="+urllib.parse.quote(q)+f"&page={p}"
        r=polite.get(u,min_delay=5)
        if r.status_code!=200: print('ERR',q,p,r.status_code); break
        root=ET.fromstring(r.content)
        for e in root.findall('a:entry',NS):
            idl=e.find('a:id',NS).text; t=e.find('a:title',NS).text
            seen.setdefault(idl,{'id':idl,'title':t,'queries':[]})['queries'].append(q)
        more=root.find('leg:morePages',NS)
        if more is not None and int(more.text)>0 and p<20: p+=1
        else: break
for q in queries:
    run(q); print(q,len(seen),flush=True)
json.dump(list(seen.values()),open((str(_CORPORA) + '/county/GB/raw/ukla_candidates.json'),'w'),indent=1)
