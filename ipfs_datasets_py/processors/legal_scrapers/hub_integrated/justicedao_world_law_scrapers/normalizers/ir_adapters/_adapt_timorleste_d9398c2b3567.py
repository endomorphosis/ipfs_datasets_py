#!/usr/bin/env python3
"""Adapt cayman memsafe pack → timorleste FIRST_IR tip d9398c2b3567.

Both SRC and DST are plain single-token slugs (no underscores).
Replace tip/repo/kind-prefixed paths BEFORE blanket slug sweep.
Display: Cayman Islands → Timor-Leste; English → Portuguese.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "27056e52499065e8791fc6617835dd9abe565c5c"
SRC_TIP_SHORT = "27056e524990"
DST_TIP_FULL = "d9398c2b3567e13e63a3c2001cc8e188d926c95a"
DST_TIP_SHORT = "d9398c2b3567"
SRC_SLUG = "cayman"
DST_SLUG = "timorleste"
SRC_REPO = "endomorphosis/ipfs_cayman_laws"
DST_REPO = "endomorphosis/ipfs_timorleste_laws"
SRC_TARGET = "justicedao/ipfs_cayman_laws_ir"
DST_TARGET = "justicedao/ipfs_timorleste_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 226, 19779
SRC_FLOOR_L, SRC_FLOOR_A = 175, 20203

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("cayman_soft_filter.py", "timorleste_soft_filter.py"),
    (f"cayman_corpus_stream_{SRC_TIP_SHORT}.py", f"timorleste_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"cayman_encode_memsafe_{SRC_TIP_SHORT}.py", f"timorleste_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"cayman_finish_from_emb_{SRC_TIP_SHORT}.py", f"timorleste_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"cayman_stream_graph_parts_{SRC_TIP_SHORT}.py", f"timorleste_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"cayman_package_memsafe_{SRC_TIP_SHORT}.py", f"timorleste_package_memsafe_{DST_TIP_SHORT}.py"),
    ("cayman_upload.py", "timorleste_upload.py"),
    ("cayman_bm25_smoke.py", "timorleste_bm25_smoke.py"),
    ("cayman_write_publish_report.py", "timorleste_write_publish_report.py"),
    (f"cayman_orchestrator_{SRC_TIP_SHORT}.py", f"timorleste_orchestrator_{DST_TIP_SHORT}.py"),
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
    t = t.replace("English (Cayman Islands)", "Portuguese (Timor-Leste)")
    t = t.replace("English (KY)", "Portuguese (TL)")
    t = t.replace("English Cayman Islands", "Portuguese Timor-Leste")
    t = t.replace("Cayman Islands ASCII", "Timor-Leste ASCII")
    t = t.replace("Cayman Islands IR", "Timor-Leste IR")
    t = t.replace("Cayman Islands FIRST_IR", "Timor-Leste FIRST_IR")
    t = t.replace("Cayman Islands filtered", "Timor-Leste filtered")
    t = t.replace("Cayman Islands corpus", "Timor-Leste corpus")
    t = t.replace("BM25 smoke for Cayman Islands", "BM25 smoke for Timor-Leste")
    t = t.replace("Upload Cayman Islands", "Upload Timor-Leste")
    t = t.replace("Memory-safe Cayman Islands", "Memory-safe Timor-Leste")
    t = t.replace('"name": "Cayman Islands"', '"name": "Timor-Leste"')
    t = t.replace("# Cayman Islands ", "# Timor-Leste ")
    t = t.replace("Cayman Islands-only", "Timor-Leste-only")
    t = t.replace("Caymanian", "Timorese")
    t = t.replace("cayman_ranked", "timorleste_ranked")
    t = t.replace("cayman_gate", "timorleste_gate")
    t = t.replace("cayman_pass", "timorleste_pass")
    t = t.replace("cayman_encode_memsafe", "timorleste_encode_memsafe")
    t = t.replace("cayman_package_memsafe", "timorleste_package_memsafe")
    t = t.replace("cayman_corpus_stream", "timorleste_corpus_stream")
    t = t.replace("cayman_encode_done", "timorleste_encode_done")
    # remaining slug tokens
    t = t.replace(f"{SRC_SLUG}_", f"{DST_SLUG}_")
    t = t.replace(f"ipfs_{SRC_SLUG}", f"ipfs_{DST_SLUG}")
    t = t.replace(SRC_SLUG, DST_SLUG)
    # country name last
    t = t.replace("Cayman Islands", "Timor-Leste")

    # language / CC leftovers
    t = t.replace("www/gov/ky", "www/gov/tl")
    t = t.replace('"ky"', '"tl"')
    t = t.replace("lang=en", "lang=pt")
    t = t.replace("English legal corpus", "Portuguese legal corpus")
    t = t.replace("English legal stems", "Portuguese legal stems")
    t = t.replace("English stems ARE GATE", "Portuguese stems ARE GATE")
    t = t.replace("EN corpus", "PT corpus")
    t = t.replace("company-law heavy", "Portuguese legal corpus (ASCII after diacritic fold)")

    # floors
    t = t.replace(
        f"FLOOR_LAWS, FLOOR_ARTS = {SRC_FLOOR_L}, {SRC_FLOOR_A}",
        f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}",
    )
    t = t.replace(f"{SRC_FLOOR_L}/{SRC_FLOOR_A}", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}, {SRC_FLOOR_A}", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(f"or {SRC_FLOOR_L}", f"or {FLOOR_LAWS}")
    t = t.replace(f"or {SRC_FLOOR_A}", f"or {FLOOR_ARTS}")
    t = t.replace(
        f'n_laws_source\": int(pack.get(\"n_laws\") or {SRC_FLOOR_L})',
        f'n_laws_source\": int(pack.get(\"n_laws\") or {FLOOR_LAWS})',
    )
    t = t.replace(
        f'n_articles_source\": int(pack.get(\"n_articles\") or {SRC_FLOOR_A})',
        f'n_articles_source\": int(pack.get(\"n_articles\") or {FLOOR_ARTS})',
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
