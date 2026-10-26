#!/usr/bin/env python3
"""Adapt chad memsafe pack → niger FIRST_IR tip e27a3d51e154.

French → French; Chad → Niger; TD → NE. Floor 102/17498. FIRST_IR.
justicedao/ipfs_niger_laws_ir does NOT exist yet.
HOLD 0 STRICT; soft never-thin ON; SKIP_US; Italy BLOCKED.
Queue after: BT→GN→AD→KM→CK→SM→TM→GD→MG→PS.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "cfef0584fb76ace64f7b1fd9121caaf9aba2e4ec"
SRC_TIP_SHORT = "cfef0584fb76"
DST_TIP_FULL = "e27a3d51e1542a49a580bd3a793f402ccce53002"
DST_TIP_SHORT = "e27a3d51e154"
SRC_SLUG = "chad"
DST_SLUG = "niger"
SRC_REPO = "endomorphosis/ipfs_chad_laws"
DST_REPO = "endomorphosis/ipfs_niger_laws"
SRC_TARGET = "justicedao/ipfs_chad_laws_ir"
DST_TARGET = "justicedao/ipfs_niger_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 102, 17498
SRC_FLOOR_L, SRC_FLOOR_A = 99, 19425

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("chad_soft_filter.py", "niger_soft_filter.py"),
    (f"chad_corpus_stream_{SRC_TIP_SHORT}.py", f"niger_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"chad_encode_memsafe_{SRC_TIP_SHORT}.py", f"niger_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"chad_finish_from_emb_{SRC_TIP_SHORT}.py", f"niger_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"chad_stream_graph_parts_{SRC_TIP_SHORT}.py", f"niger_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"chad_package_memsafe_{SRC_TIP_SHORT}.py", f"niger_package_memsafe_{DST_TIP_SHORT}.py"),
    ("chad_upload.py", "niger_upload.py"),
    ("chad_bm25_smoke.py", "niger_bm25_smoke.py"),
    ("chad_write_publish_report.py", "niger_write_publish_report.py"),
    (f"chad_orchestrator_{SRC_TIP_SHORT}.py", f"niger_orchestrator_{DST_TIP_SHORT}.py"),
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

    # Display / language before blanket
    t = t.replace("French (Chad)", "French (Niger)")
    t = t.replace("French/Latin (TD)", "French/Latin (NE)")
    t = t.replace("French Chad", "French Niger")
    t = t.replace("Chad FIRST_IR", "Niger FIRST_IR")
    t = t.replace("Chad IR", "Niger IR")
    t = t.replace("Chad filtered", "Niger filtered")
    t = t.replace("Chad corpus", "Niger corpus")
    t = t.replace("BM25 smoke for Chad", "BM25 smoke for Niger")
    t = t.replace("Upload Chad", "Upload Niger")
    t = t.replace("Memory-safe Chad", "Memory-safe Niger")
    t = t.replace("Memsafe Chad", "Memsafe Niger")
    t = t.replace("Soft filter for Chad", "Soft filter for Niger")
    t = t.replace('"name": "Chad"', '"name": "Niger"')
    t = t.replace("# Chad ", "# Niger ")
    t = t.replace("Chadian", "Nigerien")
    t = t.replace("chad_ranked", "niger_ranked")
    t = t.replace("chad_gate", "niger_gate")
    t = t.replace("chad_pass", "niger_pass")
    t = t.replace("chad_encode_done", "niger_encode_done")
    t = t.replace("www/gov/td", "www/gov/ne")
    t = t.replace('"td"', '"ne"')
    t = t.replace(" (TD)", " (NE)")
    t = t.replace("WAVE END after-ME (EE→…→TL→TD)", "HOLD 0 STRICT after-TC (BT→GN→AD→KM→CK→SM→TM→GD→MG→PS)")
    t = t.replace("Chad", "Niger")
    t = t.replace("chad_", "niger_")
    t = t.replace("ipfs_chad", "ipfs_niger")

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
