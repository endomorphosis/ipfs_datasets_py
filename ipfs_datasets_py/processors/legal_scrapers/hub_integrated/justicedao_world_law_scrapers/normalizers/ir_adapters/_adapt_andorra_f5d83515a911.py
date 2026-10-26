#!/usr/bin/env python3
"""Adapt Guinea memsafe pack -> Andorra FIRST_IR tip f5d83515a911.

French (Guinea) -> Catalan (Andorra); Guinea -> Andorra; GN -> AD.
Floor 218299/16322. FIRST_IR. HOLD 0 STRICT; soft never-thin ON; SKIP_US; Italy BLOCKED.
Queue after-BT: AD->KM->CK->SM->TM->GD->MG->PS.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
SRC_TIP_FULL="c330b9fc21b5cb49b2d05ce79f6c9c1de8acb374"; SRC_TIP_SHORT="c330b9fc21b5"
DST_TIP_FULL="f5d83515a9116a27f0f46dcd86fce6a5a9e6fcb2"; DST_TIP_SHORT="f5d83515a911"
SRC_SLUG="guinea"; DST_SLUG="andorra"
SRC_REPO="endomorphosis/ipfs_guinea_laws"; DST_REPO="endomorphosis/ipfs_andorra_laws"
SRC_TARGET="justicedao/ipfs_guinea_laws_ir"; DST_TARGET="justicedao/ipfs_andorra_laws_ir"
FLOOR_LAWS,FLOOR_ARTS=218299,16322; SRC_FLOOR_L,SRC_FLOOR_A=109,16453
ROOT=Path("/workspace/do_ir_resume")
files=[
 ("guinea_soft_filter.py","andorra_soft_filter.py"),
 (f"guinea_corpus_stream_{SRC_TIP_SHORT}.py",f"andorra_corpus_stream_{DST_TIP_SHORT}.py"),
 (f"guinea_encode_memsafe_{SRC_TIP_SHORT}.py",f"andorra_encode_memsafe_{DST_TIP_SHORT}.py"),
 (f"guinea_finish_from_emb_{SRC_TIP_SHORT}.py",f"andorra_finish_from_emb_{DST_TIP_SHORT}.py"),
 (f"guinea_stream_graph_parts_{SRC_TIP_SHORT}.py",f"andorra_stream_graph_parts_{DST_TIP_SHORT}.py"),
 (f"guinea_package_memsafe_{SRC_TIP_SHORT}.py",f"andorra_package_memsafe_{DST_TIP_SHORT}.py"),
 ("guinea_upload.py","andorra_upload.py"),("guinea_bm25_smoke.py","andorra_bm25_smoke.py"),
 ("guinea_write_publish_report.py","andorra_write_publish_report.py"),
 (f"guinea_orchestrator_{SRC_TIP_SHORT}.py",f"andorra_orchestrator_{DST_TIP_SHORT}.py")]
def adapt(t):
 for a,b in [(SRC_TIP_FULL,DST_TIP_FULL),(SRC_TIP_SHORT,DST_TIP_SHORT),(SRC_REPO,DST_REPO),(SRC_TARGET,DST_TARGET),(f"ipfs_{SRC_SLUG}_laws_ir",f"ipfs_{DST_SLUG}_laws_ir"),(f"ipfs_{SRC_SLUG}_laws",f"ipfs_{DST_SLUG}_laws")]: t=t.replace(a,b)
 for kind in ["filtered_","corpus_parts_","corpus_stream_","bm25_spill_","corpus_","orchestrator_","encode_","finish_","stream_graph_","package_stream_","package_memsafe_","upload_","bm25_smoke_","publish_","filter_","build_","graph_parts_","normalization","gate_sample_","soft_filter"]: t=t.replace(f"{SRC_SLUG}_{kind}",f"{DST_SLUG}_{kind}")
 t=t.replace(f"embeddings/{SRC_SLUG}_",f"embeddings/{DST_SLUG}_").replace(f'"{SRC_SLUG}"',f'"{DST_SLUG}"')
 for a,b in [("French (Guinea)","Catalan (Andorra)"),("French/Latin (GN)","Catalan/Latin (AD)"),("French Guinea","Catalan Andorra"),("Guinean","Andorran"),("Guinea FIRST_IR","Andorra FIRST_IR"),("Guinea IR","Andorra IR"),("Guinea filtered","Andorra filtered"),("Guinea corpus","Andorra corpus"),("BM25 smoke for Guinea","BM25 smoke for Andorra"),("Upload Guinea","Upload Andorra"),("Memory-safe Guinea","Memory-safe Andorra"),("Memsafe Guinea","Memsafe Andorra"),("Soft filter for Guinea","Soft filter for Andorra"),('"name": "Guinea"','"name": "Andorra"'),("# Guinea ","# Andorra "),("guinea_ranked","andorra_ranked"),("guinea_gate","andorra_gate"),("guinea_pass","andorra_pass"),("guinea_encode_done","andorra_encode_done"),("www/gov/gn","www/gov/ad"),('"gn"','"ad"'),(" (GN)"," (AD)"),("French","Catalan"),("Guinea","Andorra"),("guinea_","andorra_"),("ipfs_guinea","ipfs_andorra")]: t=t.replace(a,b)
 t=t.replace("HOLD 0 STRICT after-TC (BT→GN→AD→KM→CK→SM→TM→GD→MG→PS)","HOLD 0 STRICT after-BT (AD→KM→CK→SM→TM→GD→MG→PS)")
 t=t.replace(f"FLOOR_LAWS, FLOOR_ARTS = {SRC_FLOOR_L}, {SRC_FLOOR_A}",f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}").replace(f"{SRC_FLOOR_L}/{SRC_FLOOR_A}",f"{FLOOR_LAWS}/{FLOOR_ARTS}").replace(f"{SRC_FLOOR_L}, {SRC_FLOOR_A}",f"{FLOOR_LAWS}, {FLOOR_ARTS}").replace(f"or {SRC_FLOOR_L}",f"or {FLOOR_LAWS}").replace(f"or {SRC_FLOOR_A}",f"or {FLOOR_ARTS}")
 t=t.replace(f'n_laws_source": int(pack.get("n_laws") or {SRC_FLOOR_L})',f'n_laws_source": int(pack.get("n_laws") or {FLOOR_LAWS})').replace(f'n_articles_source": int(pack.get("n_articles") or {SRC_FLOOR_A})',f'n_articles_source": int(pack.get("n_articles") or {FLOOR_ARTS})').replace("RECONFIRM_FINAL","FIRST_IR")
 return t
for s,d in files:
 src=ROOT/s
 if not src.is_file(): print(f"MISSING {src}"); continue
 (ROOT/d).write_text(adapt(src.read_text())); print(f"wrote {d}")
print("done")
