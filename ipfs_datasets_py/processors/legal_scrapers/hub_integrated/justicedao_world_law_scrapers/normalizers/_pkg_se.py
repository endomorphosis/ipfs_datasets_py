import sys
sys.path.insert(0, "/workspace")
from package_hf_release import package
info = package("se", coverage="full SFS via Riksdagen öppna data dokumentlista", notes="EXPAND above hub floor 9973/16526 (tip eeb006dd12d7). CC0 as stated by Riksdagen. Official source prevails. Not legal advice.")
print("DONE", info["path"], info["laws_rows"], info["articles_rows"], flush=True)
