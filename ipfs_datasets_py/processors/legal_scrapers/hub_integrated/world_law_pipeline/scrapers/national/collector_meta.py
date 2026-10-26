# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import ast, json, re
from pathlib import Path
from collections import Counter
HERE=Path(__file__).parent
ents=[e for e in json.load(open(HERE/'snapshot_catalog.json'))['entries'] if not e.get('alias_of')]
out={}
for e in ents:
    src=(HERE/'shared'/e['collector']).read_text(errors='ignore')
    try: doc=ast.get_docstring(ast.parse(src)) or ''
    except Exception: doc=''
    hosts=Counter(h.lower() for h in re.findall(r'https?://([a-zA-Z0-9.-]+\.[a-z]{2,})', src))
    for bad in ['web.archive.org','index.commoncrawl.org','archive.org','data.commoncrawl.org','archive.ph','archive.is','www.w3.org','schema.org','creativecommons.org','purl.org','json-schema.org','huggingface.co']:
        hosts.pop(bad,None)
    lic=re.search(r'robots|Crawl-delay',src,re.I) is not None
    out[e['country_code']]=dict(cc=e['country_code'],country=e['display_name'],collector=e['collector'],quality=e['quality'],
        source_dataset=e['source_dataset_id'],ir_dataset=e['ir_dataset_id'],doc=' '.join(doc.split())[:400],hosts=[h for h,_ in hosts.most_common(4)],
        wayback=('archive_fallbacks' in src or 'web.archive.org' in src),pdf=('pdf' in src.lower()),robots_mentioned=lic)
json.dump(out,open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/national/_collector_meta.json'),'w'),indent=1,ensure_ascii=False)
print(len(out))
