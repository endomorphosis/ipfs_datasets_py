"""Wave 16 fresh remote verification: download each repo's
data/laws.parquet fresh (common13 machinery), check row counts,
ID uniqueness, empty texts, and presence of the two tail
instruments closed by the watchdog (ge-faolex-geo200876,
sv-faolex-els166336) plus pw RPPL-No.-10-47.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, sys

sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
sys.path.insert(0, os.path.expanduser(
    "~/workspace/goals/global-law-scraping-coverage/hidden_files/wave13/scripts"))

from common13 import TARGETS, download_remote_parquet  # noqa: E402

EXPECT = {"ba": 1427, "sv": 991, "sz": 273, "pw": 147,
          "ci": 190, "by": 1294, "ge": 640, "ne": 458}
WANT_IDS = {"ge": ["ge-faolex-geo200876"],
            "sv": ["sv-faolex-els166336"]}

results = {}
for cc in ["ba", "sv", "sz", "pw", "ci", "by", "ge", "ne"]:
    repo = TARGETS[cc][0]
    try:
        table, blob = download_remote_parquet(repo)
        df = table.to_pandas()
        ids = [str(i) for i in df["id"]]
        texts = [str(t or "") for t in df["text"]]
        entry = {
            "repo": repo,
            "rows": int(table.num_rows),
            "expected": EXPECT[cc],
            "rows_match": int(table.num_rows) == EXPECT[cc],
            "ids_unique": len(ids) == len(set(ids)),
            "empty_texts": sum(1 for t in texts if not t.strip()),
            "parquet_bytes": len(blob),
        }
        for wid in WANT_IDS.get(cc, []):
            if wid in ids:
                i = ids.index(wid)
                entry[wid] = {"present": True,
                              "text_chars": len(texts[i]),
                              "title": str(df["title"][i])[:120]}
            else:
                entry[wid] = {"present": False}
        if cc == "pw":
            hits = [i for i in ids if "10-47" in i or "1047" in i]
            entry["rppl_10_47_ids"] = hits
            for h in hits:
                i = ids.index(h)
                entry[h] = {"text_chars": len(texts[i]),
                            "title": str(df["title"][i])[:120]}
        results[cc] = entry
        print(json.dumps({cc: entry}, ensure_ascii=False))
    except Exception as e:
        results[cc] = {"repo": repo, "error": f"{type(e).__name__}: {e}"}
        print(json.dumps({cc: results[cc]}, ensure_ascii=False))

out = os.path.expanduser(
    "~/workspace/goals/global-law-scraping-coverage/hidden_files/wave16/stats/verify16.json")
json.dump(results, open(out, "w"), indent=1, ensure_ascii=False)
print("wrote", out)
