# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from huggingface_hub import HfApi
import json, re
api = HfApi(token=open("/home/USER/.cache/huggingface/token").read().strip())
ds = list(api.list_datasets(author="endomorphosis"))
have = set()
for d in ds:
    m = re.match(r"endomorphosis/ipfs_(.+)_laws$", d.id)
    if m:
        have.add(m.group(1).lower().replace("_", ""))
print("have", len(have))
targets = [
    ("is", "iceland"), ("rs", "serbia"), ("ba", "bosnia"), ("mk", "northmacedonia"), ("al", "albania"),
    ("me", "montenegro"), ("md", "moldova"), ("by", "belarus"), ("ge", "georgia"), ("am", "armenia"),
    ("az", "azerbaijan"), ("uz", "uzbekistan"), ("tm", "turkmenistan"), ("tj", "tajikistan"), ("kg", "kyrgyzstan"),
    ("mn", "mongolia"), ("np", "nepal"), ("lk", "srilanka"), ("mm", "myanmar"), ("kh", "cambodia"),
    ("la", "laos"), ("bn", "brunei"), ("af", "afghanistan"), ("iq", "iraq"), ("ir", "iran"),
    ("sy", "syria"), ("lb", "lebanon"), ("ye", "yemen"), ("et", "ethiopia"), ("tz", "tanzania"),
    ("ug", "uganda"), ("rw", "rwanda"), ("sn", "senegal"), ("ci", "cotedivoire"), ("cm", "cameroon"),
    ("ao", "angola"), ("mz", "mozambique"), ("zw", "zimbabwe"), ("dz", "algeria"), ("tn", "tunisia"),
    ("ly", "libya"), ("sd", "sudan"), ("ve", "venezuela"), ("ec", "ecuador"), ("bo", "bolivia"),
    ("py", "paraguay"), ("pa", "panama"), ("gt", "guatemala"), ("hn", "honduras"), ("sv", "elsalvador"),
    ("ni", "nicaragua"), ("do", "dominicanrepublic"), ("cu", "cuba"), ("jm", "jamaica"), ("tt", "trinidad"),
    ("ht", "haiti"), ("fj", "fiji"), ("pg", "papuanewguinea"), ("xk", "kosovo"),
    ("ps", "palestine"), ("ss", "southsudan"), ("bi", "burundi"), ("mw", "malawi"), ("zm", "zambia"),
    ("bw", "botswana"), ("na", "namibia"), ("mg", "madagascar"), ("mu", "mauritius"),
]
# skip USA explicitly
targets = [t for t in targets if t[0] != "us" and t[1] != "unitedstates"]
missing = [(c, s) for c, s in targets if s.replace("_", "") not in have]
print("missing", len(missing))
for c, s in missing:
    print(c, s)
out = {"have": sorted(have), "missing": missing, "skip": ["us", "unitedstates"]}
json.dump(out, open(str(_SCRAPERS) + "/world_gap.json", "w"), indent=2)
print("wrote world_gap.json")
