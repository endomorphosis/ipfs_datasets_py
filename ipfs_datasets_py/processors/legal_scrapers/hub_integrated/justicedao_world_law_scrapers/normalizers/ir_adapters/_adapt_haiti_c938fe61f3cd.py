#!/usr/bin/env python3
"""Adapt the Togo French memsafe FIRST_IR pack to Haiti HT."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import json, re

ROOT = Path("/workspace/do_ir_resume")
SRC_TIP_FULL = "5d6406438adc379a3db1a2102b30c3f49e313443"
SRC_TIP_SHORT = "5d6406438adc"
DST_TIP_FULL = "c938fe61f3cdacaa2dd646563c2ebf975d03b26a"
DST_TIP_SHORT = "c938fe61f3cd"
SRC_REPO = "endomorphosis/ipfs_togo_laws"
DST_REPO = "endomorphosis/ipfs_haiti_laws"
SRC_TARGET = "justicedao/ipfs_togo_laws_ir"
DST_TARGET = "justicedao/ipfs_haiti_laws_ir"
SRC_FLOOR_LAWS, SRC_FLOOR_ARTS = 170, 10915
DST_FLOOR_LAWS, DST_FLOOR_ARTS = 150, 9518
FILES = [
    ("togo_soft_filter.py", "haiti_soft_filter.py"),
    (f"togo_corpus_stream_{SRC_TIP_SHORT}.py", f"haiti_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"togo_encode_memsafe_{SRC_TIP_SHORT}.py", f"haiti_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"togo_finish_from_emb_{SRC_TIP_SHORT}.py", f"haiti_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"togo_stream_graph_parts_{SRC_TIP_SHORT}.py", f"haiti_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"togo_package_memsafe_{SRC_TIP_SHORT}.py", f"haiti_package_memsafe_{DST_TIP_SHORT}.py"),
    ("togo_upload.py", "haiti_upload.py"),
    ("togo_bm25_smoke.py", "haiti_bm25_smoke.py"),
    ("togo_write_publish_report.py", "haiti_write_publish_report.py"),
    (f"togo_orchestrator_{SRC_TIP_SHORT}.py", f"haiti_orchestrator_{DST_TIP_SHORT}.py"),
]

GATE_YEARS = ["2002", "2007", "2008", "2009", "2010", "2011", "2012", "2014", "2015", "2016"]
GATE_STEMS = ["etat", "titre", "services", "personnel", "ministere", "ministre", "ecole", "direction", "instituteur", "agent", "lycee"]

def adapt(text: str, dst_name: str) -> str:
    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL), (SRC_TIP_SHORT, DST_TIP_SHORT),
        (SRC_REPO, DST_REPO), (SRC_TARGET, DST_TARGET),
        ("ipfs_togo_laws_ir", "ipfs_haiti_laws_ir"), ("ipfs_togo_laws", "ipfs_haiti_laws"),
        ("HOLD 0 STRICT after-NR (MS→HT→VG→SX→CD→BM)", "HOLD 0 STRICT after-MS (VG→SX→CD→BM)"),
        ("after-NR (MS→HT→VG→SX→CD→BM)", "after-MS (VG→SX→CD→BM)"), ("after-NR", "after-MS"),
        ("www/gov/tg", "www/gov/ht"), ("/tg", "/ht"), ('"tg"', '"ht"'), ("(TG)", "(HT)"),
        ("French (Togo)", "French (Haiti)"), ("French Togo", "French Haiti"),
        ("Togo", "Haiti"), ("togo", "haiti"),
        ("170/10915", "150/9518"), ("170 / 10915", "150 / 9518"), ("170, 10915", "150, 9518"),
        ("or 170", "or 150"), ("or 10915", "or 9518"), ("170", "150"), ("10915", "9518"),
    ]
    for a, b in reps:
        text = text.replace(a, b)
    if dst_name == "haiti_bm25_smoke.py":
        text = re.sub(r"GATE_YEARS = \[[^\n]+\]", f"GATE_YEARS = {GATE_YEARS!r}", text)
        text = re.sub(r"GATE_FRENCH = \[.*?\n\]", "GATE_FRENCH = [\n" + "    " + ", ".join(repr(x) for x in GATE_STEMS) + ",\n]", text, flags=re.S)
        text = text.replace('detail["togo_pass"]', 'detail["haiti_pass"]').replace('detail["togo_gate"]', 'detail["haiti_gate"]')
        text = text.replace("Togo", "Haiti").replace("togo", "haiti")
    if dst_name == "haiti_write_publish_report.py":
        text = text.replace("togo_ranked", "haiti_ranked")
        text = text.replace("Togo", "Haiti").replace("togo", "haiti")
        text = text.replace(
            "BM25 PASS on Haiti ASCII-fold French GATE (2007/2011/2012/2015/2017/2018/2019/2020/2022/2024 + article/loi/republique/president/etat/nationale/assemblee/cour/autorite/decret/ministre/togolaise); URL www/gov/ht is query-only, not GATE",
            "BM25 PASS on Haiti ASCII-fold French GATE (2002/2007/2008/2009/2010/2011/2012/2014/2015/2016 + etat/titre/services/personnel/ministere/ministre/ecole/direction/instituteur/agent/lycee); URL www/gov/ht is query-only, not GATE",
        )
    return text

for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")

wave = Path("/workspace/country-law-triage/next_ir_ok_wave_after_ps.json")
data = json.loads(wave.read_text(encoding="utf-8"))
for entry in data["queue"]:
    if entry.get("slug") == "haiti":
        entry.update({
            "tip": DST_TIP_SHORT, "tip_full": DST_TIP_FULL,
            "laws": DST_FLOOR_LAWS, "articles": DST_FLOOR_ARTS,
            "floor_laws": DST_FLOOR_LAWS, "floor_articles": DST_FLOOR_ARTS,
            "claim_tip": DST_TIP_SHORT, "match_claim": True,
            "ir_hub_head": None, "true_first_ir": True, "thin": False,
            "label": "EXPAND", "soft_never_thin": True, "skip_us": True,
            "italy_blocked": True, "language": "French",
            "years_attested": [2016, 2014, 2015, 2012, 2017, 2009, 2011, 2010, 2007, 2008, 2013, 2002],
            "gate_years": [int(x) for x in GATE_YEARS], "gate_stems": GATE_STEMS,
            "note": "HT FIRST_IR scaffold; tip MATCH c938fe61f3cd@150/9518; HOLD 0 STRICT; queue VG→SX→CD→BM",
        })
        break
else:
    raise RuntimeError("Haiti entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Haiti entry")
