#!/usr/bin/env python3
"""Adapt niger memsafe pack → guinea FIRST_IR tip c330b9fc21b5.

French → French; Niger → Guinea; NE → GN. Floor 109/16453. FIRST_IR.
justicedao/ipfs_guinea_laws_ir does NOT exist yet.
HOLD 0 STRICT; soft never-thin ON; SKIP_US; Italy BLOCKED.
Queue after: AD→KM→CK→SM→TM→GD→MG→PS.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "e27a3d51e1542a49a580bd3a793f402ccce53002"
SRC_TIP_SHORT = "e27a3d51e154"
DST_TIP_FULL = "c330b9fc21b5cb49b2d05ce79f6c9c1de8acb374"
DST_TIP_SHORT = "c330b9fc21b5"
SRC_SLUG = "niger"
DST_SLUG = "guinea"
SRC_REPO = "endomorphosis/ipfs_niger_laws"
DST_REPO = "endomorphosis/ipfs_guinea_laws"
SRC_TARGET = "justicedao/ipfs_niger_laws_ir"
DST_TARGET = "justicedao/ipfs_guinea_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 109, 16453
SRC_FLOOR_L, SRC_FLOOR_A = 102, 17498

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("niger_soft_filter.py", "guinea_soft_filter.py"),
    (f"niger_corpus_stream_{SRC_TIP_SHORT}.py", f"guinea_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"niger_encode_memsafe_{SRC_TIP_SHORT}.py", f"guinea_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"niger_finish_from_emb_{SRC_TIP_SHORT}.py", f"guinea_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"niger_stream_graph_parts_{SRC_TIP_SHORT}.py", f"guinea_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"niger_package_memsafe_{SRC_TIP_SHORT}.py", f"guinea_package_memsafe_{DST_TIP_SHORT}.py"),
    ("niger_upload.py", "guinea_upload.py"),
    ("niger_bm25_smoke.py", "guinea_bm25_smoke.py"),
    ("niger_write_publish_report.py", "guinea_write_publish_report.py"),
    (f"niger_orchestrator_{SRC_TIP_SHORT}.py", f"guinea_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str) -> str:
    t = text
    t = t.replace(SRC_TIP_FULL, DST_TIP_FULL)
    t = t.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    t = t.replace(SRC_REPO, DST_REPO)
    t = t.replace(SRC_TARGET, DST_TARGET)
    t = t.replace(f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir")
    t = t.replace(f"ipfs_{SRC_SLUG}_laws", f"ipfs_{DST_SLUG}_laws")

    for kind in [
        "filtered_", "corpus_parts_", "corpus_stream_", "bm25_spill_", "corpus_",
        "orchestrator_", "encode_", "finish_", "stream_graph_", "package_stream_",
        "package_memsafe_", "upload_", "bm25_smoke_", "publish_", "filter_",
        "build_", "graph_parts_", "normalization", "gate_sample_", "soft_filter",
    ]:
        t = t.replace(f"{SRC_SLUG}_{kind}", f"{DST_SLUG}_{kind}")

    t = t.replace(f"embeddings/{SRC_SLUG}_", f"embeddings/{DST_SLUG}_")
    t = t.replace(chr(34) + SRC_SLUG + chr(34), chr(34) + DST_SLUG + chr(34))
    t = t.replace("SLUG = " + chr(34) + SRC_SLUG + chr(34), "SLUG = " + chr(34) + DST_SLUG + chr(34))

    t = t.replace("French (Niger)", "French (Guinea)")
    t = t.replace("French/Latin (NE)", "French/Latin (GN)")
    t = t.replace("French Niger", "French Guinea")
    t = t.replace("Niger FIRST_IR", "Guinea FIRST_IR")
    t = t.replace("Niger IR", "Guinea IR")
    t = t.replace("Niger filtered", "Guinea filtered")
    t = t.replace("Niger corpus", "Guinea corpus")
    t = t.replace("BM25 smoke for Niger", "BM25 smoke for Guinea")
    t = t.replace("Upload Niger", "Upload Guinea")
    t = t.replace("Memory-safe Niger", "Memory-safe Guinea")
    t = t.replace("Memsafe Niger", "Memsafe Guinea")
    t = t.replace("Soft filter for Niger", "Soft filter for Guinea")
    t = t.replace('"name": "Niger"', '"name": "Guinea"')
    t = t.replace("# Niger ", "# Guinea ")
    t = t.replace("Nigerien", "Guinean")
    t = t.replace("niger_ranked", "guinea_ranked")
    t = t.replace("niger_gate", "guinea_gate")
    t = t.replace("niger_pass", "guinea_pass")
    t = t.replace("niger_encode_done", "guinea_encode_done")
    t = t.replace("www/gov/ne", "www/gov/gn")
    t = t.replace('"ne"', '"gn"')
    t = t.replace(" (NE)", " (GN)")
    t = t.replace(
        "HOLD 0 STRICT after-TC (BT\u2192GN\u2192AD\u2192KM\u2192CK\u2192SM\u2192TM\u2192GD\u2192MG\u2192PS)",
        "HOLD 0 STRICT after-BT (AD\u2192KM\u2192CK\u2192SM\u2192TM\u2192GD\u2192MG\u2192PS)",
    )
    t = t.replace("Niger", "Guinea")
    t = t.replace("niger_", "guinea_")
    t = t.replace("ipfs_niger", "ipfs_guinea")

    t = t.replace(
        f"FLOOR_LAWS, FLOOR_ARTS = {SRC_FLOOR_L}, {SRC_FLOOR_A}",
        f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}",
    )
    t = t.replace(f"{SRC_FLOOR_L}/{SRC_FLOOR_A}", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}, {SRC_FLOOR_A}", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(f"or {SRC_FLOOR_L}", f"or {FLOOR_LAWS}")
    t = t.replace(f"or {SRC_FLOOR_A}", f"or {FLOOR_ARTS}")
    t = t.replace(
        f'n_laws_source": int(pack.get("n_laws") or {SRC_FLOOR_L})',
        f'n_laws_source": int(pack.get("n_laws") or {FLOOR_LAWS})',
    )
    t = t.replace(
        f'n_articles_source": int(pack.get("n_articles") or {SRC_FLOOR_A})',
        f'n_articles_source": int(pack.get("n_articles") or {FLOOR_ARTS})',
    )
    t = t.replace("RECONFIRM_FINAL", "FIRST_IR")
    return t


for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        print(f"MISSING {src}")
        continue
    (ROOT / dst_name).write_text(adapt(src.read_text()))
    print(f"wrote {dst_name}")
print("done")
