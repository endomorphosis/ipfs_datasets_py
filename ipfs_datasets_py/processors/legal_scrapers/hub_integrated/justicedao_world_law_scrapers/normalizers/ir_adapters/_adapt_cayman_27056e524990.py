#!/usr/bin/env python3
"""Adapt samoa memsafe pack → cayman FIRST_IR tip 27056e524990.

Both SRC and DST are plain single-token slugs (no underscores).
Replace tip/repo/kind-prefixed paths BEFORE blanket slug sweep.
Display: Samoa → Cayman Islands.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "1db7f49bfb36de97ff6503587ebff3ef22328ee7"
SRC_TIP_SHORT = "1db7f49bfb36"
DST_TIP_FULL = "27056e52499065e8791fc6617835dd9abe565c5c"
DST_TIP_SHORT = "27056e524990"
SRC_SLUG = "samoa"
DST_SLUG = "cayman"
SRC_REPO = "endomorphosis/ipfs_samoa_laws"
DST_REPO = "endomorphosis/ipfs_cayman_laws"
SRC_TARGET = "justicedao/ipfs_samoa_laws_ir"
DST_TARGET = "justicedao/ipfs_cayman_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 175, 20203
SRC_FLOOR_L, SRC_FLOOR_A = 267, 21509

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("samoa_soft_filter.py", "cayman_soft_filter.py"),
    (f"samoa_corpus_stream_{SRC_TIP_SHORT}.py", f"cayman_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"samoa_encode_memsafe_{SRC_TIP_SHORT}.py", f"cayman_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"samoa_finish_from_emb_{SRC_TIP_SHORT}.py", f"cayman_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"samoa_stream_graph_parts_{SRC_TIP_SHORT}.py", f"cayman_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"samoa_package_memsafe_{SRC_TIP_SHORT}.py", f"cayman_package_memsafe_{DST_TIP_SHORT}.py"),
    ("samoa_upload.py", "cayman_upload.py"),
    ("samoa_bm25_smoke.py", "cayman_bm25_smoke.py"),
    ("samoa_write_publish_report.py", "cayman_write_publish_report.py"),
    (f"samoa_orchestrator_{SRC_TIP_SHORT}.py", f"cayman_orchestrator_{DST_TIP_SHORT}.py"),
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
    t = t.replace("English (Samoa)", "English (Cayman Islands)")
    t = t.replace("English (WS)", "English (KY)")
    t = t.replace("English Samoa", "English Cayman Islands")
    t = t.replace("Samoa ASCII", "Cayman Islands ASCII")
    t = t.replace("Samoa IR", "Cayman Islands IR")
    t = t.replace("Samoa FIRST_IR", "Cayman Islands FIRST_IR")
    t = t.replace("Samoa filtered", "Cayman Islands filtered")
    t = t.replace("Samoa corpus", "Cayman Islands corpus")
    t = t.replace("BM25 smoke for Samoa", "BM25 smoke for Cayman Islands")
    t = t.replace("Upload Samoa", "Upload Cayman Islands")
    t = t.replace("Memory-safe Samoa", "Memory-safe Cayman Islands")
    t = t.replace('"name": "Samoa"', '"name": "Cayman Islands"')
    t = t.replace("# Samoa ", "# Cayman Islands ")
    t = t.replace("Samoa-only", "Cayman Islands-only")
    t = t.replace("Samoan", "Caymanian")
    t = t.replace("samoa_ranked", "cayman_ranked")
    t = t.replace("samoa_gate", "cayman_gate")
    t = t.replace("samoa_pass", "cayman_pass")
    t = t.replace("samoa_encode_memsafe", "cayman_encode_memsafe")
    t = t.replace("samoa_package_memsafe", "cayman_package_memsafe")
    t = t.replace("samoa_corpus_stream", "cayman_corpus_stream")
    t = t.replace("samoa_encode_done", "cayman_encode_done")
    # remaining slug tokens
    t = t.replace(f"{SRC_SLUG}_", f"{DST_SLUG}_")
    t = t.replace(f"ipfs_{SRC_SLUG}", f"ipfs_{DST_SLUG}")
    t = t.replace(SRC_SLUG, DST_SLUG)
    # country name last
    t = t.replace("Samoa", "Cayman Islands")

    # language / CC leftovers
    t = t.replace("www/gov/ws", "www/gov/ky")
    t = t.replace('"ws"', '"ky"')

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
    t = t.replace(f"or {SRC_FLOOR_L}", f"or {FLOOR_LAWS}")
    t = t.replace(f"or {SRC_FLOOR_A}", f"or {FLOOR_ARTS}")
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
