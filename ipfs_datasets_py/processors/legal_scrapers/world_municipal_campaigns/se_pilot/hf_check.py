import os, sys
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

entry = dynamic_credential_entry("custom.huggingface")
tok = entry["surrogate"]
if not tok:
    raise RuntimeError("no surrogate")

from huggingface_hub import HfApi  # noqa: E402
api = HfApi(token=tok)
ds = [d.id for d in api.list_datasets(author="endomorphosis", limit=1000)]
print(len(ds), "datasets total")
for d in sorted(ds):
    if "swed" in d.lower() or "sverige" in d.lower():
        print("SWEDEN-MATCH:", d)
try:
    info = api.dataset_info("endomorphosis/ipfs_sweden_municipal_laws")
    print("TARGET EXISTS:", [s.rfilename for s in info.siblings or []])
except Exception as e:  # noqa: BLE001
    print("target missing:", type(e).__name__, str(e)[:120])
