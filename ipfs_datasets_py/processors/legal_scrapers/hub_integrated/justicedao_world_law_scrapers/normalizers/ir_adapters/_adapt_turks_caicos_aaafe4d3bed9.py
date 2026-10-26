#!/usr/bin/env python3
"""Adapt saint_kitts_nevis memsafe pack → turks_caicos FIRST_IR tip aaafe4d3bed9.

Both SRC and DST use underscore slugs. Replace tip/repo/display BEFORE
blanket slug sweep so saint_kitts_nevis / turks_caicos do not get mangled.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "7debf0584c36136bf46cf788da0c18505fb34d41"
SRC_TIP_SHORT = "7debf0584c36"
DST_TIP_FULL = "aaafe4d3bed911181c42e6eec64bc350147c5c4a"
DST_TIP_SHORT = "aaafe4d3bed9"
SRC_SLUG = "saint_kitts_nevis"
DST_SLUG = "turks_caicos"
SRC_REPO = "endomorphosis/ipfs_saint_kitts_nevis_laws"
DST_REPO = "endomorphosis/ipfs_turks_caicos_laws"
SRC_TARGET = "justicedao/ipfs_saint_kitts_nevis_laws_ir"
DST_TARGET = "justicedao/ipfs_turks_caicos_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 178, 19088
SRC_FLOOR_L, SRC_FLOOR_A = 150, 25176

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("saint_kitts_nevis_soft_filter.py", "turks_caicos_soft_filter.py"),
    (f"saint_kitts_nevis_corpus_stream_{SRC_TIP_SHORT}.py", f"turks_caicos_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"saint_kitts_nevis_encode_memsafe_{SRC_TIP_SHORT}.py", f"turks_caicos_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"saint_kitts_nevis_finish_from_emb_{SRC_TIP_SHORT}.py", f"turks_caicos_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"saint_kitts_nevis_stream_graph_parts_{SRC_TIP_SHORT}.py", f"turks_caicos_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"saint_kitts_nevis_package_memsafe_{SRC_TIP_SHORT}.py", f"turks_caicos_package_memsafe_{DST_TIP_SHORT}.py"),
    ("saint_kitts_nevis_upload.py", "turks_caicos_upload.py"),
    ("saint_kitts_nevis_bm25_smoke.py", "turks_caicos_bm25_smoke.py"),
    ("saint_kitts_nevis_write_publish_report.py", "turks_caicos_write_publish_report.py"),
    (f"saint_kitts_nevis_orchestrator_{SRC_TIP_SHORT}.py", f"turks_caicos_orchestrator_{DST_TIP_SHORT}.py"),
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
    t = t.replace("English (Saint Kitts and Nevis)", "English (Turks and Caicos)")
    t = t.replace("English (KN)", "English (TC)")
    t = t.replace("English Saint Kitts and Nevis", "English Turks and Caicos")
    t = t.replace("Saint Kitts and Nevis ASCII", "Turks and Caicos ASCII")
    t = t.replace("Saint Kitts and Nevis IR", "Turks and Caicos IR")
    t = t.replace("Saint Kitts and Nevis FIRST_IR", "Turks and Caicos FIRST_IR")
    t = t.replace("Saint Kitts and Nevis filtered", "Turks and Caicos filtered")
    t = t.replace("Saint Kitts and Nevis corpus", "Turks and Caicos corpus")
    t = t.replace("BM25 smoke for Saint Kitts and Nevis", "BM25 smoke for Turks and Caicos")
    t = t.replace("Upload Saint Kitts and Nevis", "Upload Turks and Caicos")
    t = t.replace("Memory-safe Saint Kitts and Nevis", "Memory-safe Turks and Caicos")
    t = t.replace('"name": "Saint Kitts and Nevis"', '"name": "Turks and Caicos"')
    t = t.replace("# Saint Kitts and Nevis ", "# Turks and Caicos ")
    t = t.replace("Saint Kitts and Nevis-only", "Turks and Caicos-only")
    t = t.replace("Kittitian-Nevisian", "Turks and Caicos")
    t = t.replace("saint_kitts_nevis_ranked", "turks_caicos_ranked")
    t = t.replace("saint_kitts_nevis_gate", "turks_caicos_gate")
    t = t.replace("saint_kitts_nevis_pass", "turks_caicos_pass")
    t = t.replace("saint_kitts_nevis_encode_memsafe", "turks_caicos_encode_memsafe")
    t = t.replace("saint_kitts_nevis_package_memsafe", "turks_caicos_package_memsafe")
    t = t.replace("saint_kitts_nevis_corpus_stream", "turks_caicos_corpus_stream")
    t = t.replace("saint_kitts_nevis_encode_done", "turks_caicos_encode_done")
    # remaining slug tokens
    t = t.replace(f"{SRC_SLUG}_", f"{DST_SLUG}_")
    t = t.replace(f"ipfs_{SRC_SLUG}", f"ipfs_{DST_SLUG}")
    t = t.replace(SRC_SLUG, DST_SLUG)
    # country name last
    t = t.replace("Saint Kitts and Nevis", "Turks and Caicos")

    # language / CC leftovers
    t = t.replace("www/gov/kn", "www/gov/tc")
    t = t.replace('"kn"', '"tc"')
    t = t.replace("lang=en; English Turks and Caicos / Turks and Caicos",
                  "lang=en; English Turks and Caicos")

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
