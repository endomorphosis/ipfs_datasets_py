# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "79ff4e94267ed0f56550b06053fdf8e6b530afec"
SRC_TIP_SHORT = "79ff4e94267e"
DST_TIP_FULL = "fa649d0d49be2a91909810dfa9ba31039020966f"
DST_TIP_SHORT = "fa649d0d49be"
SRC_SLUG = "srilanka"
DST_SLUG = "brunei"
SRC_REPO = "endomorphosis/ipfs_srilanka_laws"
DST_REPO = "endomorphosis/ipfs_brunei_laws"
SRC_TARGET = "justicedao/ipfs_srilanka_laws_ir"
DST_TARGET = "justicedao/ipfs_brunei_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 238, 21383
SRC_FLOOR_L, SRC_FLOOR_A = 4620, 1523

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("srilanka_soft_filter.py", "brunei_soft_filter.py"),
    (f"srilanka_corpus_stream_{SRC_TIP_SHORT}.py", f"brunei_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"srilanka_encode_memsafe_{SRC_TIP_SHORT}.py", f"brunei_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"srilanka_finish_from_emb_{SRC_TIP_SHORT}.py", f"brunei_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"srilanka_stream_graph_parts_{SRC_TIP_SHORT}.py", f"brunei_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"srilanka_package_memsafe_{SRC_TIP_SHORT}.py", f"brunei_package_memsafe_{DST_TIP_SHORT}.py"),
    ("srilanka_upload.py", "brunei_upload.py"),
    ("srilanka_bm25_smoke.py", "brunei_bm25_smoke.py"),
    ("srilanka_write_publish_report.py", "brunei_write_publish_report.py"),
    (f"srilanka_orchestrator_{SRC_TIP_SHORT}.py", f"brunei_orchestrator_{DST_TIP_SHORT}.py"),
]

def adapt(text: str) -> str:
    t = text
    t = t.replace(SRC_TIP_FULL, DST_TIP_FULL)
    t = t.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    t = t.replace(SRC_REPO, DST_REPO)
    t = t.replace(SRC_TARGET, DST_TARGET)
    t = t.replace(f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir")
    for kind in [
        "filtered_", "corpus_", "bm25_spill_", "corpus_parts_", "orchestrator_",
        "encode_", "finish_", "stream_graph_", "package_stream_", "package_memsafe_",
        "upload_", "bm25_smoke_", "publish_", "filter_", "build_", "graph_parts_",
        "corpus_stream_",
    ]:
        t = t.replace(f"{SRC_SLUG}_{kind}", f"{DST_SLUG}_{kind}")
    t = t.replace(f"embeddings/{SRC_SLUG}_", f"embeddings/{DST_SLUG}_")
    t = t.replace(f"{SRC_SLUG}_normalization", f"{DST_SLUG}_normalization")
    t = t.replace(chr(34) + SRC_SLUG + chr(34), chr(34) + DST_SLUG + chr(34))
    t = t.replace("SLUG = " + chr(34) + SRC_SLUG + chr(34), "SLUG = " + chr(34) + DST_SLUG + chr(34))
    t = t.replace("Sri Lanka", "Brunei")
    t = t.replace("Sinhala/Tamil", "English/Malay")
    t = t.replace("Sinhala", "Malay")
    t = t.replace("Tamil", "Malay")
    t = t.replace("srilanka_", "brunei_")
    t = t.replace("ipfs_srilanka", "ipfs_brunei")
    t = t.replace(f"FLOOR_LAWS, FLOOR_ARTS = {SRC_FLOOR_L}, {SRC_FLOOR_A}", f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}/{SRC_FLOOR_A}", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}, {SRC_FLOOR_A}", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(f"or {SRC_FLOOR_L}", f"or {FLOOR_LAWS}")
    t = t.replace(f"or {SRC_FLOOR_A}", f"or {FLOOR_ARTS}")
    t = t.replace(f"n_laws_source\": int(pack.get(\"n_laws\") or {SRC_FLOOR_L})", f"n_laws_source\": int(pack.get(\"n_laws\") or {FLOOR_LAWS})")
    t = t.replace(f"n_articles_source\": int(pack.get(\"n_articles\") or {SRC_FLOOR_A})", f"n_articles_source\": int(pack.get(\"n_articles\") or {FLOOR_ARTS})")
    t = t.replace("RECONFIRM_DRIFT_UP", "FIRST_IR")
    t = t.replace("DRIFT_UP RECONFIRM", "FIRST_IR")
    t = t.replace("FIRST-IR", "FIRST_IR")
    return t

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        print(f"MISSING {src}")
        continue
    (ROOT / dst_name).write_text(adapt(src.read_text()))
    print(f"wrote {dst_name}")
print("done")
