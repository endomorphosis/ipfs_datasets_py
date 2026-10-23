# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
src = Path("/workspace/do_ir_resume/tunisia_soft_filter.py").read_text()
text = src
text = text.replace("Tunisia tip 6178f00710c3; floor >= 1326/49830", "Angola tip 545eacccc162; floor >= 825/17084")
text = text.replace("endomorphosis/ipfs_tunisia_laws", "endomorphosis/ipfs_angola_laws")
text = text.replace("6178f00710c3749e5064c5ffea58c2d7c63b4a43", "545eacccc1627f3355d3435d30731207de91d69e")
text = text.replace("6178f00710c3", "545eacccc162")
text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 1326, 49830", "FLOOR_LAWS, FLOOR_ARTS = 825, 17084")
text = text.replace("tunisia_filtered_", "angola_filtered_")
text = text.replace("tunisia_filter_", "angola_filter_")
text = text.replace("\"slug\": \"tunisia\"", "\"slug\": \"angola\"")
text = text.replace("\"name\": \"Tunisia\"", "\"name\": \"Angola\"")
text = text.replace("Tunisia filtered pack", "Angola filtered pack")
text = text.replace("# Tunisia filtered", "# Angola filtered")
Path("/workspace/do_ir_resume/angola_soft_filter.py").write_text(text)
print("ok", len(text))
