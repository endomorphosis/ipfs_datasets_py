#!/usr/bin/env python3
"""Soft filter for Estonia tip 902b122cd27e — memsafe pass-through.

Soft never-thin ON and floor matches hub (3484/62308), so chrome drops would be
restored anyway. Copy tip pack through with floor checks only (RECONFIRM_FINAL).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download, HfApi

SECRET_CANDIDATES = [
    Path(__import__("os").environ.get("HF_TOKEN_FILE", "")),
    Path(__import__("os").environ.get("HF_TOKEN_FILE", "")),
    Path(__import__("os").environ.get("HF_TOKEN_FILE", "")),
]

REPO = "endomorphosis/ipfs_estonia_laws"
TIP_SHORT = "902b122cd27e"
TIP_FULL = "902b122cd27eed93e96c28a0ba5a70e9cb36ab7d"
FLOOR_LAWS, FLOOR_ARTS = 3484, 62308
OUT = Path("/workspace/country-laws-ir/cache/estonia_filtered_902b122cd27e")
CACHE_HF = Path("/workspace/country-laws-ir/cache/hf")
REPORTS = Path("/workspace/country-laws-ir/reports")


def load_token() -> str | None:
    for p in SECRET_CANDIDATES:
        if not p.is_file():
            continue
        if p.suffix == ".env":
            for line in p.read_text().splitlines():
                if line.startswith("HF_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        else:
            data = json.loads(p.read_text())
            tok = data.get("token") or data.get("access_token")
            if tok:
                return tok
    return None


def main() -> int:
    token = load_token()
    api = HfApi(token=token)
    info = api.dataset_info(REPO)
    head = info.sha or ""
    print(f"hub_head={head[:12]} requested={TIP_SHORT}", flush=True)
    if not head.startswith(TIP_SHORT):
        print(f"STOP: HEAD={head[:12]} != requested {TIP_SHORT}")
        return 1

    laws_path = Path(
        hf_hub_download(
            REPO, "data/laws.parquet", repo_type="dataset",
            revision=TIP_FULL, token=token, cache_dir=str(CACHE_HF),
        )
    )
    arts_path = Path(
        hf_hub_download(
            REPO, "data/articles.parquet", repo_type="dataset",
            revision=TIP_FULL, token=token, cache_dir=str(CACHE_HF),
        )
    )
    n_laws_b = pq.ParquetFile(laws_path).metadata.num_rows
    n_arts_b = pq.ParquetFile(arts_path).metadata.num_rows
    print(f"loaded laws={n_laws_b} articles={n_arts_b}", flush=True)
    if n_laws_b < FLOOR_LAWS or n_arts_b < FLOOR_ARTS:
        raise SystemExit(
            f"source below IR-OK floor: {n_laws_b}/{n_arts_b} < {FLOOR_LAWS}/{FLOOR_ARTS}"
        )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    laws_out = OUT / "data" / "laws.parquet"
    arts_out = OUT / "data" / "articles.parquet"
    shutil.copy2(laws_path, laws_out)
    shutil.copy2(arts_path, arts_out)

    pack_meta = {
        "slug": "estonia",
        "name": "Estonia",
        "repo": REPO,
        "source_dataset": REPO,
        "source_revision": TIP_FULL,
        "filtered": True,
        "filter_reason": "memsafe pass-through (chrome skipped; floor==hub; soft never-thin)",
        "indexable": True,
        "skip_reason": None,
        "n_laws": int(n_laws_b),
        "n_articles": int(n_arts_b),
    }
    (OUT / "pack_meta.json").write_text(json.dumps(pack_meta, indent=2) + "\n", encoding="utf-8")
    (OUT / "README.md").write_text(
        f"# Estonia filtered pack\n\nTip `{TIP_SHORT}` memsafe pass-through. Floor {FLOOR_LAWS}/{FLOOR_ARTS}.\n",
        encoding="utf-8",
    )

    report = {
        "source_repo": REPO,
        "source_tip": TIP_SHORT,
        "source_tip_full": TIP_FULL,
        "source_tip_note": f"Hub tip {TIP_SHORT} @ {n_laws_b}/{n_arts_b}; HEAD was {head[:12]}",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "filter_L_A": f"{n_laws_b}/{n_arts_b}",
        "laws_dropped": 0,
        "marker_hits": {},
        "articles_kept": int(n_arts_b),
        "soft_never_thin_floor": {"laws": FLOOR_LAWS, "articles": FLOOR_ARTS},
        "floor_ok": True,
        "filter_mode": "memsafe_passthrough",
        "out": str(OUT),
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"estonia_filter_{TIP_SHORT}.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "filter_L_A": report["filter_L_A"],
        "laws_dropped": 0,
        "marker_hits": {},
        "floor_ok": True,
        "out": str(OUT),
        "filter_mode": "memsafe_passthrough",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
