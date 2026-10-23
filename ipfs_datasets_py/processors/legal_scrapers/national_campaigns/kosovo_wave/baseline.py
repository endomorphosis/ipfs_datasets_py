# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import io, json, os, sys, urllib.request
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
os.environ["no_proxy"]="localhost,127.0.0.1"; os.environ["NO_PROXY"]="localhost,127.0.0.1"
from dynamic_credentials import add_surrogate_to_request
import pyarrow.parquet as pq
WAVE=os.path.expanduser("~/workspace/goals/global-law-scraping-coverage/hidden_files/kosovo_wave")
url="https://huggingface.co/datasets/endomorphosis/ipfs_kosovo_laws/resolve/main/data/laws.parquet"
req=urllib.request.Request(url)
add_surrogate_to_request(req,"custom.huggingface",allowed_hosts=["huggingface.co"])
with urllib.request.urlopen(req,timeout=300) as r:
    blob=r.read()
open(os.path.join(WAVE,"dedupe","xk_remote_baseline.parquet"),"wb").write(blob)
t=pq.read_table(io.BytesIO(blob))
df=t.to_pandas()
print("rows",len(df),"cols",list(df.columns))
print("unique ids",df['id'].nunique(),"empty texts",int((df['text'].fillna('').str.len()==0).sum()),"short<300",int((df['text'].fillna('').str.len()<300).sum()))
print("jurisdictions",df['jurisdiction'].value_counts().to_dict())
print("countries",df['country'].value_counts().to_dict() if 'country' in df else None)
print("languages",df['language'].value_counts().to_dict())
print("source_types",df['source_type'].value_counts().to_dict())
ids=sorted(df['id'].astype(str))
print(ids)
# dedupe file like wave7/8
import re, unicodedata
def norm(t):
    t=unicodedata.normalize('NFKD',str(t or '')).lower()
    t=re.sub(r'[^a-z0-9\u0600-\u06FF\u0400-\u04FF\u4E00-\u9FFF]+',' ',t)
    return re.sub(r'\s+',' ',t).strip()
recs=[{'id':str(r.id),'norm_title':norm(r.title)} for r in df.itertuples()]
json.dump(recs,open(os.path.join(WAVE,"dedupe","xk_dedupe.json"),"w"))
# numeric act ids
nums=sorted(int(i.split('-',1)[1]) for i in ids if i.startswith('xk-') and i.split('-',1)[1].isdigit())
print("numeric xk ids",len(nums),"min",nums[0] if nums else None,"max",nums[-1] if nums else None)
print(nums)
json.dump({"rows":len(df),"ids":ids,"numeric":nums},open(os.path.join(WAVE,"stats","baseline.json"),"w"),indent=1)
# text length stats
print(df['text'].str.len().describe())
