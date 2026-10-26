import io, os, sys, urllib.request
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
os.environ["no_proxy"] = "localhost,127.0.0.1"; os.environ["NO_PROXY"] = "localhost,127.0.0.1"
from dynamic_credentials import add_surrogate_to_request
import pyarrow.parquet as pq
url = "https://huggingface.co/datasets/endomorphosis/ipfs_kosovo_laws/resolve/main/data/laws.parquet"
req = urllib.request.Request(url)
add_surrogate_to_request(req, "custom.huggingface", allowed_hosts=["huggingface.co"])
with urllib.request.urlopen(req, timeout=60) as r:
    blob = r.read()
t = pq.read_table(io.BytesIO(blob))
ids = t.column("id").to_pylist()
texts = t.column("text").to_pylist()
empty = sum(1 for x in texts if x is None or not str(x).strip())
print(f"rows={t.num_rows} unique={len(set(ids))} empty={empty} "
      f"has_123033={'xk-123033' in set(ids)} has_122635={'xk-122635' in set(ids)} "
      f"has_122698={'xk-122698' in set(ids)}")
