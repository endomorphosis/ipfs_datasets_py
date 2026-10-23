"""Thin, stdlib-only reader for the shared place-code crosswalk (world_law/pipeline/codes/place_codes.csv).
code_to_place(system, cc) -> {code: place_id} for current codes that map to exactly one place_id (ambiguous codes dropped).
Official name lists live in pipeline/codes/cache/ (IBGE json, INE diccionario xlsx, INEI UBIGEO csv)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv
from functools import lru_cache
from pathlib import Path

CODES = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes"))
CACHE = CODES / "cache"


@lru_cache(maxsize=None)
def code_to_place(system, cc):
    m = {}
    with open(CODES / "place_codes.csv", newline="", encoding="utf8") as fh:
        for r in csv.DictReader(fh):
            if r["country_code"] != cc or r["code_system"] != system or r["is_current"] == "False":
                continue
            if r["official_check"] == "not_municipal_level":
                continue
            m.setdefault(r["code"], set()).add(r["place_id"])
    return {k: next(iter(v)) for k, v in m.items() if len(v) == 1}
