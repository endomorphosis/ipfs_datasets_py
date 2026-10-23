#!/usr/bin/env python3
"""Adapt the Andorra memsafe FIRST_IR pack to Comoros tip bf29adc28297.

French Comoros; FIRST_IR; HOLD 0 STRICT; soft never-thin ON; SKIP_US; Italy BLOCKED.
Queue after-AD: KM -> CK -> SM -> TM -> GD -> MG -> PS.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "f5d83515a9116a27f0f46dcd86fce6a5a9e6fcb2"
SRC_TIP_SHORT = "f5d83515a911"
DST_TIP_FULL = "bf29adc2829759e4b1edf73f0ca0d6059aa2daf1"
DST_TIP_SHORT = "bf29adc28297"
SRC_SLUG = "andorra"
DST_SLUG = "comoros"
SRC_REPO = "endomorphosis/ipfs_andorra_laws"
DST_REPO = "endomorphosis/ipfs_comoros_laws"
SRC_TARGET = "justicedao/ipfs_andorra_laws_ir"
DST_TARGET = "justicedao/ipfs_comoros_laws_ir"
SRC_FLOOR_L, SRC_FLOOR_A = 218299, 16322
FLOOR_LAWS, FLOOR_ARTS = 117, 15155
ROOT = Path("/workspace/do_ir_resume")

files = [
    ("andorra_soft_filter.py", "comoros_soft_filter.py"),
    (f"andorra_corpus_stream_{SRC_TIP_SHORT}.py", f"comoros_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"andorra_encode_memsafe_{SRC_TIP_SHORT}.py", f"comoros_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"andorra_finish_from_emb_{SRC_TIP_SHORT}.py", f"comoros_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"andorra_stream_graph_parts_{SRC_TIP_SHORT}.py", f"comoros_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"andorra_package_memsafe_{SRC_TIP_SHORT}.py", f"comoros_package_memsafe_{DST_TIP_SHORT}.py"),
    ("andorra_upload.py", "comoros_upload.py"),
    ("andorra_bm25_smoke.py", "comoros_bm25_smoke.py"),
    ("andorra_write_publish_report.py", "comoros_write_publish_report.py"),
    (f"andorra_orchestrator_{SRC_TIP_SHORT}.py", f"comoros_orchestrator_{DST_TIP_SHORT}.py"),
]

def adapt(text: str) -> str:
    replacements = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        (SRC_REPO, DST_REPO),
        (SRC_TARGET, DST_TARGET),
        (f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir"),
        (f"ipfs_{SRC_SLUG}_laws", f"ipfs_{DST_SLUG}_laws"),
        ("HOLD 0 STRICT after-BT (AD→KM→CK→SM→TM→GD→MG→PS)", "HOLD 0 STRICT after-AD (KM→CK→SM→TM→GD→MG→PS)"),
        ("www/gov/ad", "www/gov/km"),
        ("/ad", "/km"),
        ("\"ad\"", "\"km\""),
        ("AD-attested", "KM-attested"),
        ("(AD)", "(KM)"),
        ("Catalan (Andorra)", "French (Comoros)"),
        ("Catalan/Latin (AD)", "French/Latin (KM)"),
        ("Catalan Andorra", "French Comoros"),
        ("Andorran", "Comorian"),
        ("Andorra", "Comoros"),
        ("andorra", "comoros"),
        ("Catalan", "French"),
        ("ca;", "fr;"),
        ("ca)", "fr)"),
        ("after-BT (KM→CK→SM→TM→GD→MG→PS)", "after-AD (KM→CK→SM→TM→GD→MG→PS)"),
        ("after-BT (AD→KM→CK→SM→TM→GD→MG→PS)", "after-AD (KM→CK→SM→TM→GD→MG→PS)"),
        ("after-BT", "after-AD"),
        ("218299/16322", "117/15155"),
        ("218299 / 16322", "117 / 15155"),
        ("218299, 16322", "117, 15155"),
        ("218299", "117"),
        ("16322", "15155"),
    ]
    for a, b in replacements:
        text = text.replace(a, b)
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 109, 16453", "FLOOR_LAWS, FLOOR_ARTS = 117, 15155")
    text = text.replace("RECONFIRM_FINAL", "FIRST_IR")
    return text

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"wrote {dst_name}")
print("done")
