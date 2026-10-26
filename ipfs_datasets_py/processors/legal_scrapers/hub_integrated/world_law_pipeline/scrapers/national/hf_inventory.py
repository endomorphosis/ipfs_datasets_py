# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
# Read-only HF inventory of national-law datasets. No uploads.
import json, re, sys, time
from huggingface_hub import HfApi
api=HfApi()
out=open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/national/hf_national_datasets.jsonl'),'w')
for author in ['endomorphosis','justicedao']:
    for d in api.list_datasets(author=author, full=True):
        if not re.search(r'_laws|uk_local_acts|uscode|state_laws|federal_register|eu_laws|state_admin', d.id): continue
        rec={'id':d.id,'last_modified':str(d.last_modified),'size_tag':[t for t in (d.tags or []) if t.startswith('size_categories')]}
        try:
            info=api.dataset_info(d.id, files_metadata=True)
            files=info.siblings or []
            rec['n_files']=len(files)
            rec['bytes']=sum((f.size or 0) for f in files)
            rec['parquet_bytes']=sum((f.size or 0) for f in files if f.rfilename.endswith('.parquet'))
            rec['files_sample']=[f.rfilename for f in files[:8]]
            cd=info.card_data.to_dict() if info.card_data else {}
            rows=0
            for c in (cd.get('dataset_info') or []) if isinstance(cd.get('dataset_info'),list) else [cd.get('dataset_info') or {}]:
                for s in (c.get('splits') or []): rows+=s.get('num_examples',0) or 0
            rec['rows_card']=rows or None
        except Exception as e:
            rec['err']=str(e)[:200]
        out.write(json.dumps(rec)+'\n'); out.flush()
        time.sleep(0.2)
print('done')
