import sys
sys.path.insert(0, "/workspace")
from package_hf_release import package
info = package("de", coverage="full Bundesrecht via gesetze-im-internet.de TOC", notes="EXPAND above hub floor 6124/129926 (tip ab9708b5c7cc). Official GII/BMJ texts prevail; amtliche Werke. Not legal advice.")
print("DONE", info["path"], info["laws_rows"], info["articles_rows"], flush=True)
