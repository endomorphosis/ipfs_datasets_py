#!/usr/bin/env python3
"""Adapt burkinafaso memsafe pack → saint_kitts_nevis FIRST_IR tip 7debf0584c36.

Underscore slug: replace tip/repo/display BEFORE blanket slug sweep so
saint_kitts_nevis does not get mangled. Prefer BF package_memsafe path.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "397e6ed9482ed7ce7ee7fce19f818533d35da92f"
SRC_TIP_SHORT = "397e6ed9482e"
DST_TIP_FULL = "7debf0584c36136bf46cf788da0c18505fb34d41"
DST_TIP_SHORT = "7debf0584c36"
SRC_SLUG = "burkinafaso"
DST_SLUG = "saint_kitts_nevis"
SRC_REPO = "endomorphosis/ipfs_burkinafaso_laws"
DST_REPO = "endomorphosis/ipfs_saint_kitts_nevis_laws"
SRC_TARGET = "justicedao/ipfs_burkinafaso_laws_ir"
DST_TARGET = "justicedao/ipfs_saint_kitts_nevis_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 150, 25176
SRC_FLOOR_L, SRC_FLOOR_A = 142, 28929

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("burkinafaso_soft_filter.py", "saint_kitts_nevis_soft_filter.py"),
    (f"burkinafaso_corpus_stream_{SRC_TIP_SHORT}.py", f"saint_kitts_nevis_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"burkinafaso_encode_memsafe_{SRC_TIP_SHORT}.py", f"saint_kitts_nevis_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"burkinafaso_finish_from_emb_{SRC_TIP_SHORT}.py", f"saint_kitts_nevis_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"burkinafaso_stream_graph_parts_{SRC_TIP_SHORT}.py", f"saint_kitts_nevis_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"burkinafaso_package_memsafe_{SRC_TIP_SHORT}.py", f"saint_kitts_nevis_package_memsafe_{DST_TIP_SHORT}.py"),
    ("burkinafaso_upload.py", "saint_kitts_nevis_upload.py"),
    ("burkinafaso_bm25_smoke.py", "saint_kitts_nevis_bm25_smoke.py"),
    ("burkinafaso_write_publish_report.py", "saint_kitts_nevis_write_publish_report.py"),
    (f"burkinafaso_orchestrator_{SRC_TIP_SHORT}.py", f"saint_kitts_nevis_orchestrator_{DST_TIP_SHORT}.py"),
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
    t = t.replace("French (Burkina Faso)", "English (Saint Kitts and Nevis)")
    t = t.replace("French/Latin (BF)", "English (KN)")
    t = t.replace("French Burkina Faso", "English Saint Kitts and Nevis")
    t = t.replace("Burkina Faso ASCII", "Saint Kitts and Nevis ASCII")
    t = t.replace("Burkina Faso IR", "Saint Kitts and Nevis IR")
    t = t.replace("Burkina Faso FIRST_IR", "Saint Kitts and Nevis FIRST_IR")
    t = t.replace("Burkina Faso filtered", "Saint Kitts and Nevis filtered")
    t = t.replace("Burkina Faso corpus", "Saint Kitts and Nevis corpus")
    t = t.replace("BM25 smoke for Burkina Faso", "BM25 smoke for Saint Kitts and Nevis")
    t = t.replace("Upload Burkina Faso", "Upload Saint Kitts and Nevis")
    t = t.replace("Memory-safe Burkina Faso", "Memory-safe Saint Kitts and Nevis")
    t = t.replace('"name": "Burkina Faso"', '"name": "Saint Kitts and Nevis"')
    t = t.replace("# Burkina Faso ", "# Saint Kitts and Nevis ")
    t = t.replace("Burkinabe-only", "Saint Kitts and Nevis-only")
    t = t.replace("Burkinabe", "Kittitian-Nevisian")
    t = t.replace("burkinafaso_ranked", "saint_kitts_nevis_ranked")
    t = t.replace("burkinafaso_gate", "saint_kitts_nevis_gate")
    t = t.replace("burkinafaso_pass", "saint_kitts_nevis_pass")
    t = t.replace("burkinafaso_encode_memsafe", "saint_kitts_nevis_encode_memsafe")
    t = t.replace("burkinafaso_package_memsafe", "saint_kitts_nevis_package_memsafe")
    t = t.replace("burkinafaso_corpus_stream", "saint_kitts_nevis_corpus_stream")
    t = t.replace("burkinafaso_encode_done", "saint_kitts_nevis_encode_done")
    # remaining slug tokens
    t = t.replace(f"{SRC_SLUG}_", f"{DST_SLUG}_")
    t = t.replace(f"ipfs_{SRC_SLUG}", f"ipfs_{DST_SLUG}")
    t = t.replace(SRC_SLUG, DST_SLUG)
    # country name last (after slug so "Burkina Faso" in comments not left)
    t = t.replace("Burkina Faso", "Saint Kitts and Nevis")

    # language / CC leftovers
    t = t.replace("www/gov/bf", "www/gov/kn")
    t = t.replace('"bf"', '"kn"')
    t = t.replace("lang=fr; English Saint Kitts and Nevis / Kittitian-Nevisian",
                  "lang=en; English Saint Kitts and Nevis / Kittitian-Nevisian")
    t = t.replace("lang=fr;", "lang=en;")
    t = t.replace("French/Latin", "English")
    t = t.replace("French-only", "English-only")
    t = t.replace("years + attested Latin/French stems", "years + attested English legal stems")
    t = t.replace("years+French/Latin GATE", "years+English GATE")
    t = t.replace("ASCII years+French/Latin", "ASCII years+English")

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
    return t


for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        print(f"MISSING {src}")
        continue
    (ROOT / dst_name).write_text(adapt(src.read_text()))
    print(f"wrote {dst_name}")
print("done")
