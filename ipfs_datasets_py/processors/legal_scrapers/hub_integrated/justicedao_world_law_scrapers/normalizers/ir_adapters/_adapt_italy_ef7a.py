# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import re

OLD_FULL = "6ba4c0218006d4c216a1e1a99ca4e233f30ac47a"
OLD_SHORT = "6ba4c0218006"
NEW_FULL = "dda3ced5edf17a97163e0f28364649f2d223ad6b"
NEW_SHORT = "dda3ced5edf1"
OLD_FLOOR = "951, 224298"
NEW_FLOOR = "1011, 224377"
OLD_FLOOR_SL = "951/224298"
NEW_FLOOR_SL = "1011/224377"

# --- soft filter ---
p = Path("/workspace/do_ir_resume/dominicanrepublic_soft_filter.py")
t = p.read_text()
t = t.replace(OLD_FULL, NEW_FULL)
t = t.replace(OLD_SHORT, NEW_SHORT)
t = t.replace(f"FLOOR_LAWS, FLOOR_ARTS = {OLD_FLOOR}", f"FLOOR_LAWS, FLOOR_ARTS = {NEW_FLOOR}")
t = t.replace(OLD_FLOOR_SL, NEW_FLOOR_SL)
t = t.replace(f"floor >= {OLD_FLOOR_SL}", f"floor >= {NEW_FLOOR_SL}")
t = t.replace(f"tip {OLD_SHORT}", f"tip {NEW_SHORT}")
t = re.sub(r'TIP_FULL = "[^"]+"', f'TIP_FULL = "{NEW_FULL}"', t)
t = re.sub(r'TIP_SHORT = "[^"]+"', f'TIP_SHORT = "{NEW_SHORT}"', t)
t = t.replace(
    f"dominicanrepublic_filtered_{OLD_SHORT}",
    f"dominicanrepublic_filtered_{NEW_SHORT}",
)
t = t.replace(
    f"dominicanrepublic_filter_{OLD_SHORT}.json",
    f"dominicanrepublic_filter_{NEW_SHORT}.json",
)
p.write_text(t)
print("soft_filter OK")

# --- build ---
p = Path("/workspace/do_ir_resume/dominicanrepublic_build.py")
t = p.read_text()
t = t.replace(OLD_FULL, NEW_FULL)
t = t.replace(OLD_SHORT, NEW_SHORT)
t = t.replace("do_bm25_spill_6ba4", "do_bm25_spill_dda3")
t = re.sub(r'TIP = "[^"]+"', f'TIP = "{NEW_FULL}"', t)
t = re.sub(r'TIP_SHORT = "[^"]+"', f'TIP_SHORT = "{NEW_SHORT}"', t)
t = t.replace(f"tip {OLD_SHORT}", f"tip {NEW_SHORT}")
t = t.replace(
    f"dominicanrepublic_filtered_{OLD_SHORT}",
    f"dominicanrepublic_filtered_{NEW_SHORT}",
)
for old_s in [OLD_SHORT, "6ba4c0218006"]:
    t = t.replace(f"dominicanrepublic_{old_s}", f"dominicanrepublic_{NEW_SHORT}")
    t = t.replace(f"dominicanrepublic_build_{old_s}", f"dominicanrepublic_build_{NEW_SHORT}")
    t = t.replace(f"dominicanrepublic_corpus_{old_s}", f"dominicanrepublic_corpus_{NEW_SHORT}")

new_order = """COLLECTOR_SHED_ORDER = [
    # refresh PIDs at kickoff; mm/th/is-reg/LT first; protect at_deepen + it last
    ("mm", [398730, 398765]),
    ("th", [398732, 398764]),
    ("is-reg", [399712, 399719]),
    ("lt", []),
    ("dk", [398729, 398758]),
    ("at_deepen", [398728]),
    ("it_deepen", [398734]),
]"""
t = re.sub(r"COLLECTOR_SHED_ORDER = \[.*?\]", new_order, t, count=1, flags=re.S)

if '"dk":' not in t or '"at_deepen":' not in t:
    t = t.replace(
        '"mt": ("collect_mt", "run_collector_cc.sh collect_mt"),\n    }',
        '"mt": ("collect_mt", "run_collector_cc.sh collect_mt"),\n'
        '        "dk": ("collect_dk", "run_collector_cc.sh collect_dk"),\n'
        '        "at_deepen": ("at_deepen_articles",),\n'
        '        "it_deepen": ("it_article_body_deepen",),\n'
        "    }",
    )

t = re.sub(
    r"dominicanrepublic_build_[a-f0-9]+_result\.json",
    f"dominicanrepublic_build_{NEW_SHORT}_result.json",
    t,
)
p.write_text(t)
print("build OK")

# --- upload ---
src = Path("/workspace/do_ir_resume/dominicanrepublic_upload_6ba4.py")
t = src.read_text()
t = t.replace(OLD_SHORT, NEW_SHORT)
t = t.replace(OLD_FULL, NEW_FULL)
t = re.sub(r'TIP_SHORT = "[^"]+"', f'TIP_SHORT = "{NEW_SHORT}"', t)
t = re.sub(
    r"dominicanrepublic_upload_[a-f0-9]+\.json",
    f"dominicanrepublic_upload_{NEW_SHORT}.json",
    t,
)
out = Path("/workspace/do_ir_resume/dominicanrepublic_upload_dda3.py")
out.write_text(t)
print("upload OK ->", out)

# --- smoke ---
p = Path("/workspace/do_ir_resume/dominicanrepublic_bm25_smoke.py")
t = p.read_text()
t = t.replace(OLD_SHORT, NEW_SHORT)
t = re.sub(
    r"dominicanrepublic_bm25_smoke_[a-f0-9]+\.json",
    f"dominicanrepublic_bm25_smoke_{NEW_SHORT}.json",
    t,
)
p.write_text(t)
print("smoke OK")

# --- publish report ---
p = Path("/workspace/do_ir_resume/dominicanrepublic_write_publish_report.py")
t = p.read_text()
t = t.replace(OLD_FULL, NEW_FULL)
t = t.replace(OLD_SHORT, NEW_SHORT)
t = t.replace(OLD_FLOOR_SL, NEW_FLOOR_SL)
t = re.sub(r'TIP_FULL = "[^"]+"', f'TIP_FULL = "{NEW_FULL}"', t)
t = re.sub(r'TIP_SHORT = "[^"]+"', f'TIP_SHORT = "{NEW_SHORT}"', t)
for old in [OLD_SHORT, "6ba4c0218006"]:
    t = t.replace(old, NEW_SHORT)
t = t.replace("951/224298", NEW_FLOOR_SL)
p.write_text(t)
print("publish_report OK")

for label, path in [
    ("soft", "/workspace/do_ir_resume/dominicanrepublic_soft_filter.py"),
    ("build", "/workspace/do_ir_resume/dominicanrepublic_build.py"),
    ("upload", "/workspace/do_ir_resume/dominicanrepublic_upload_dda3.py"),
    ("smoke", "/workspace/do_ir_resume/dominicanrepublic_bm25_smoke.py"),
    ("report", "/workspace/do_ir_resume/dominicanrepublic_write_publish_report.py"),
]:
    tt = Path(path).read_text()
    assert NEW_SHORT in tt, label
    assert OLD_SHORT not in tt, (label, "still has old short")
    print(label, "verified")
print("DONE retarget dda3")
