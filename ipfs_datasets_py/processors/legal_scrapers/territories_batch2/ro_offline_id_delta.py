#!/usr/bin/env python3
"""Romania offline ID-delta vs live endomorphosis/ipfs_romania_laws.

Keeps aml_ro untouched. Zero deletes. If net-new IDs with text>=50 exist,
writes additive shard laws_expand_20261105.parquet; else code-only scrapers.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MALLOC_ARENA_MAX", "2")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wave2b_common import (  # noqa: E402
    LAW_COLS,
    RAW,
    require_mem,
    utcnow,
    verify_load_dataset,
    write_json,
    write_parquet,
)

LOCAL_IDS = Path("/workspace/staging/territories_batch2_20261105/raw/ro_local_ids.txt")
INSTR = Path("/workspace/legal-corpora/ro/instruments")
OUT = Path("/workspace/staging/ro_upload_ready_20261105")


def load_live_ids() -> set[str]:
    require_mem()
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq

    path = hf_hub_download(
        repo_id="endomorphosis/ipfs_romania_laws",
        filename="data/laws.parquet",
        repo_type="dataset",
        local_dir=str(RAW / "hf_ro"),
        local_dir_use_symlinks=False,
    )
    # stream batches of id only
    pf = pq.ParquetFile(path)
    live: set[str] = set()
    if "id" not in pf.schema_arrow.names:
        raise RuntimeError(f"no id column: {pf.schema_arrow.names}")
    for batch in pf.iter_batches(columns=["id"], batch_size=8192):
        for v in batch.column(0).to_pylist():
            if v is not None:
                live.add(str(v))
    return live


def main() -> int:
    require_mem()
    local_ids = [ln.strip() for ln in LOCAL_IDS.read_text().splitlines() if ln.strip()]
    local_set = set(local_ids)
    print("local", len(local_set))
    live = load_live_ids()
    print("live", len(live))
    only_local = sorted(local_set - live)
    only_live = len(live - local_set)
    write_json(
        RAW / "ro_id_delta.json",
        {
            "local_count": len(local_set),
            "live_count": len(live),
            "only_local_count": len(only_local),
            "only_live_count": only_live,
            "only_local_sample": only_local[:50],
        },
    )
    OUT.mkdir(parents=True, exist_ok=True)
    scrapers = OUT / "scrapers_and_normalizers"
    scrapers.mkdir(parents=True, exist_ok=True)
    for name in ("ro_offline_id_delta.py", "wave2b_common.py", "collect_ro_stub_note.md"):
        src = Path(__file__).resolve().parent / name
        if src.exists():
            (scrapers / src.name).write_bytes(src.read_bytes())
    # copy collect_ro.py additively as reference (do not modify aml_ro)
    collect_ro = Path(
        "/workspace/ipfs_datasets_py_latest/ipfs_datasets_py/processors/legal_scrapers/national_collectors/collect_ro.py"
    )
    if collect_ro.exists():
        (scrapers / "collect_ro.py").write_bytes(collect_ro.read_bytes())

    new_rows = []
    for lid in only_local:
        fp = INSTR / f"{lid}.json"
        if not fp.exists():
            continue
        try:
            rec = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = str(rec.get("text") or "")
        if len(text) < 50:
            continue
        new_rows.append(
            {
                "id": rec.get("id") or lid,
                "title": rec.get("title"),
                "text": text,
                "source_url": rec.get("source_url"),
                "source_type": rec.get("source_type") or "legislatie_just",
                "jurisdiction": "RO",
                "country": "Romania",
                "language": rec.get("language") or "ro",
                "eli": rec.get("eli") if rec.get("eli") not in (None, "None") else None,
                "date": rec.get("date"),
                "date_issued": rec.get("date"),
                "retrieved_at": rec.get("retrieved_at") or utcnow(),
                "license": rec.get("license"),
                "law_status": rec.get("law_status"),
                "identifier": rec.get("identifier"),
                "official_identifier": rec.get("official_identifier"),
                "article_count": rec.get("article_count") or 0,
                "json_path": str(fp),
                "metadata_json": json.dumps({"delta": "local_minus_live_20261105"}, ensure_ascii=False),
            }
        )
    validation = {
        "local_count": len(local_set),
        "live_count": len(live),
        "only_local_ids": len(only_local),
        "net_new_text_ge_50": len(new_rows),
        "aml_ro_touched": False,
        "push": "NOT_PUSHED",
    }
    if new_rows:
        data = OUT / "data"
        data.mkdir(parents=True, exist_ok=True)
        n = write_parquet(data / "laws_expand_20261105.parquet", new_rows, LAW_COLS)
        validation["laws_expand_rows"] = n
        # minimal verify
        validation["load_dataset_verify"] = verify_load_dataset(OUT)
        (OUT / "README.md").write_text(
            f"""# Romania additive ID-delta shard

Local instruments: {len(local_set)}
Live `endomorphosis/ipfs_romania_laws` ids: {len(live)}
Net-new local IDs with text>=50: {n}

`aml_ro` untouched. Additive shard only. Push: NOT_PUSHED
""",
            encoding="utf-8",
        )
    else:
        (OUT / "README.md").write_text(
            f"""# Romania — code-only delta

Local {len(local_set)} vs live {len(live)}; net-new text>=50 rows: 0.
Scrapers bundled only. `aml_ro` untouched.
""",
            encoding="utf-8",
        )
    write_json(OUT / "validation.json", validation)
    print(json.dumps(validation, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
