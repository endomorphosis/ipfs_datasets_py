#!/usr/bin/env python3
"""Adapt barbados memsafe pack → samoa FIRST_IR tip 1db7f49bfb36.

Both SRC and DST are plain single-token slugs (no underscores).
Replace tip/repo/kind-prefixed paths BEFORE blanket slug sweep.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "22af9b2e03459035d9000b959d6a63ee0289a5b8"
SRC_TIP_SHORT = "22af9b2e0345"
DST_TIP_FULL = "1db7f49bfb36de97ff6503587ebff3ef22328ee7"
DST_TIP_SHORT = "1db7f49bfb36"
SRC_SLUG = "barbados"
DST_SLUG = "samoa"
SRC_REPO = "endomorphosis/ipfs_barbados_laws"
DST_REPO = "endomorphosis/ipfs_samoa_laws"
SRC_TARGET = "justicedao/ipfs_barbados_laws_ir"
DST_TARGET = "justicedao/ipfs_samoa_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 267, 21509
SRC_FLOOR_L, SRC_FLOOR_A = 150, 23296

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("barbados_soft_filter.py", "samoa_soft_filter.py"),
    (f"barbados_corpus_stream_{SRC_TIP_SHORT}.py", f"samoa_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"barbados_encode_memsafe_{SRC_TIP_SHORT}.py", f"samoa_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"barbados_finish_from_emb_{SRC_TIP_SHORT}.py", f"samoa_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"barbados_stream_graph_parts_{SRC_TIP_SHORT}.py", f"samoa_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"barbados_package_memsafe_{SRC_TIP_SHORT}.py", f"samoa_package_memsafe_{DST_TIP_SHORT}.py"),
    ("barbados_upload.py", "samoa_upload.py"),
    ("barbados_bm25_smoke.py", "samoa_bm25_smoke.py"),
    ("barbados_write_publish_report.py", "samoa_write_publish_report.py"),
    (f"barbados_orchestrator_{SRC_TIP_SHORT}.py", f"samoa_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str) -> str:
    t = text
    # tips: full before short
    t = t.replace(SRC_TIP_FULL, DST_TIP_FULL)
    t = t.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    # repos before slug
    t = t.replace(SRC_REPO, DST_REPO)
    t = t.replace(SRC_TARGET, DST_TARGET)
    t = t.replace(f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir")
    t = t.replace(f"ipfs_{SRC_SLUG}_laws", f"ipfs_{DST_SLUG}_laws")

    # kind-prefixed paths (slug_kind) — longest/kind tokens first
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

    # Display / language before blanket country name
    t = t.replace("English (Barbados)", "English (Samoa)")
    t = t.replace("English (BB)", "English (WS)")
    t = t.replace("English Barbados", "English Samoa")
    t = t.replace("Barbados ASCII", "Samoa ASCII")
    t = t.replace("Barbados IR", "Samoa IR")
    t = t.replace("Barbados FIRST_IR", "Samoa FIRST_IR")
    t = t.replace("Barbados filtered", "Samoa filtered")
    t = t.replace("Barbados corpus", "Samoa corpus")
    t = t.replace("BM25 smoke for Barbados", "BM25 smoke for Samoa")
    t = t.replace("Upload Barbados", "Upload Samoa")
    t = t.replace("Memory-safe Barbados", "Memory-safe Samoa")
    t = t.replace('"name": "Barbados"', '"name": "Samoa"')
    t = t.replace("# Barbados ", "# Samoa ")
    t = t.replace("Barbados-only", "Samoa-only")
    t = t.replace("Barbadian", "Samoan")
    t = t.replace("barbados_ranked", "samoa_ranked")
    t = t.replace("barbados_gate", "samoa_gate")
    t = t.replace("barbados_pass", "samoa_pass")
    t = t.replace("barbados_encode_memsafe", "samoa_encode_memsafe")
    t = t.replace("barbados_package_memsafe", "samoa_package_memsafe")
    t = t.replace("barbados_corpus_stream", "samoa_corpus_stream")
    t = t.replace("barbados_encode_done", "samoa_encode_done")
    # remaining slug tokens
    t = t.replace(f"{SRC_SLUG}_", f"{DST_SLUG}_")
    t = t.replace(f"ipfs_{SRC_SLUG}", f"ipfs_{DST_SLUG}")
    t = t.replace(SRC_SLUG, DST_SLUG)
    # country name last
    t = t.replace("Barbados", "Samoa")

    # language / CC leftovers
    t = t.replace("www/gov/bb", "www/gov/ws")
    t = t.replace('"bb"', '"ws"')

    # floors
    t = t.replace(
        f"FLOOR_LAWS, FLOOR_ARTS = {SRC_FLOOR_L}, {SRC_FLOOR_A}",
        f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}",
    )
    t = t.replace(f"{SRC_FLOOR_L}/{SRC_FLOOR_A}", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}, {SRC_FLOOR_A}", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(
        f'n_articles_source\": int(pack.get(\"n_articles\") or {SRC_FLOOR_A})',
        f'n_articles_source\": int(pack.get(\"n_articles\") or {FLOOR_ARTS})',
    )
    t = t.replace(
        f'n_laws_source\": int(pack.get(\"n_laws\") or {SRC_FLOOR_L})',
        f'n_laws_source\": int(pack.get(\"n_laws\") or {FLOOR_LAWS})',
    )
    t = t.replace(str(SRC_FLOOR_A), str(FLOOR_ARTS))
    t = t.replace(str(SRC_FLOOR_L), str(FLOOR_LAWS))
    return t


for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        print(f"MISSING {src}")
        continue
    (ROOT / dst_name).write_text(adapt(src.read_text()))
    print(f"wrote {dst_name}")
print("done")
