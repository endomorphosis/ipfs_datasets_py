# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, pathlib, re
p=next(pathlib.Path(str(_CORPORA) + "/fj/instruments").glob("*Constitution*English*.json"), None)
print("path", p)
if not p:
  for x in pathlib.Path(str(_CORPORA) + "/fj/instruments").glob("*"):
    if "english" in x.name.lower() or "Constitution" in x.name: print(x.name)
else:
  t=json.loads(p.read_text())["text"]
  print("len", len(t))
  # show lines that look like headings
  for i,line in enumerate(t.splitlines()):
    if re.search(r"^(Chapter|CHAPTER|Part|PART|Article|ARTICLE|Section|SECTION)\b", line.strip()):
      print(i, repr(line[:100]))
      if i>80: break
