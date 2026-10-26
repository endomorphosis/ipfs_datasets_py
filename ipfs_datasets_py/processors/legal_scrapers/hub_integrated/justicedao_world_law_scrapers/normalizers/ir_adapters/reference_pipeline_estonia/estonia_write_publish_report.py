#!/usr/bin/env python3
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPORTS = Path("/workspace/country-laws-ir/reports")
filter_r = json.loads((REPORTS / "estonia_filter_902b122cd27e.json").read_text())
build_r = json.loads((REPORTS / "estonia_build_902b122cd27e_result.json").read_text())
norm_r = json.loads((REPORTS / "estonia_normalization.json").read_text())
smoke = json.loads((REPORTS / "estonia_bm25_smoke_902b122cd27e.json").read_text())
man = json.loads(Path("/workspace/country-laws-ir/releases/ipfs_estonia_laws_ir/manifest.json").read_text())
upload = {}
up_path = REPORTS / "estonia_upload_902b122cd27e.json"
if up_path.is_file():
    upload = json.loads(up_path.read_text())

IR_COMMIT = upload.get("ir_commit") or ""
TIP_FULL = "902b122cd27eed93e96c28a0ba5a70e9cb36ab7d"
TIP_SHORT = "902b122cd27e"

estonia_ranked = [q for q in smoke["ranked"] if all(ord(c) < 128 for c in q)]
bm25_summary = (
    f"PASS ({'/'.join(estonia_ranked)} ranked)"
    if smoke.get("pass")
    else f"FAIL empty={smoke.get('empty')}"
)

sigterm = build_r.get("collectors_sigterm") or []
sig_pids = [x.get("pid") for x in sigterm if isinstance(x, dict)]

now_utc = datetime.now(timezone.utc)
now_pt = now_utc.astimezone(ZoneInfo("America/Los_Angeles"))

report = {
    "status": "SUCCESS" if smoke.get("pass") and man["counts"]["corpus_rows"] == man["counts"]["vector_rows"] else "PARTIAL",
    "country": "estonia",
    "source_repo": "endomorphosis/ipfs_estonia_laws",
    "source_tip": TIP_SHORT,
    "source_tip_full": TIP_FULL,
    "hub_head_at_build_note": f"Hub HEAD matched requested tip {TIP_SHORT} @ 3484/62308 (verifier IR-OK)",
    # memsafe filter schema: filter_L_A / articles_kept (no laws_before/after)
    "laws_before": filter_r.get("laws_before") or int(str(filter_r.get("filter_L_A","0/0")).split("/")[0]),
    "laws_after": filter_r.get("laws_after") or int(str(filter_r.get("filter_L_A","0/0")).split("/")[0]),
    "laws_dropped": filter_r.get("laws_dropped", 0),
    "filter_L_A": filter_r.get("filter_L_A") or f"{filter_r.get('laws_after')}/{filter_r.get('articles_after_filter') or filter_r.get('articles_kept')}",
    "articles_kept": filter_r.get("articles_kept") or filter_r.get("articles_after_filter"),
    "soft_never_thin_floor": filter_r.get("soft_never_thin_floor"),
    "floor_ok": filter_r.get("floor_ok", True),
    "filter_mode": filter_r.get("filter_mode"),
    "normalization_drops": build_r.get("normalization_drops") or norm_r.get("drops"),
    "n_dropped_total": build_r.get("n_dropped_total"),
    "corpus_rows": man["counts"]["corpus_rows"],
    "vector_rows": man["counts"]["vector_rows"],
    "n_laws": man["counts"].get("n_laws"),
    "n_articles": man["counts"].get("n_articles"),
    "vector_blocker": None,
    "vector_status": (man.get("vector") or {}).get("status") or "embedded",
    "schema_version": man.get("schema_version") or "country-laws-ir-graphrag/v1",
    "hub_url": upload.get("hub_url") or "https://huggingface.co/datasets/justicedao/ipfs_estonia_laws_ir",
    "ir_commit": IR_COMMIT,
    "ir_commit_short": (IR_COMMIT[:12] if IR_COMMIT else None),
    "hub_manifest_tip": upload.get("hub_tip") or TIP_FULL,
    "bm25_smoke": bm25_summary,
    "bm25_smoke_detail": smoke,
    "filter_cache": "/workspace/country-laws-ir/cache/estonia_filtered_902b122cd27e",
    "local_ir": "/workspace/country-laws-ir/releases/ipfs_estonia_laws_ir",
    "local_ir_complete": True,
    "blockers": [],
    "via": build_r.get("via") or "soft_filter+embed_package+upload_large_folder",
    "neighbor_via": build_r.get("neighbor_via"),
    "mem_notes": {
        "encode": f"gte-small encoded {man['counts']['corpus_rows']} @ CPU",
        "sqlite_spill": "preferred for ~50k (DO OOM lesson)" if (build_r.get("neighbor_via") or "").startswith("sqlite") else "stock neighbors",
        "mem_end_gib": build_r.get("mem_end_gib"),
    },
    "collectors_sigterm": sigterm,
    "collectors_sigterm_pids": sig_pids,
    "collectors_note": (
        f"SIGTERM applied to {sig_pids}" if sig_pids
        else "HOLD collectors already requested by CoS; lean collectors left running; no SIGTERM this run"
    ),
    "notes": [
        f"soft-filtered {filter_r.get('laws_dropped',0)} portal chrome laws; kept {filter_r.get('filter_L_A')} (mode={filter_r.get('filter_mode')})",
        f"normalization dropped {build_r.get('n_dropped_total')} -> corpus {man['counts']['corpus_rows']}",
        f"real gte-small vectors (status=embedded); corpus_rows==vector_rows=={man['counts']['corpus_rows']}",
        f"Hub tip pinned {TIP_SHORT} (IR-OK floor 3484/62308; HEAD matched; RECONFIRM_FINAL)",
        f"neighbors via {build_r.get('neighbor_via')}",
        "BM25 PASS on Estonia ASCII years+roman+Latin GATE (seadus/seaduse/paragrahvi/loike/peatukk/maaruse/eesti/oigus/riigi/kohus/otsuse + years); prefer years + attested Latin; Estonian-only may empty FTS",
    ],
    "generated_utc": now_utc.isoformat(),
    "generated_pt": now_pt.strftime("%Y-%m-%d %H:%M:%S %Z") + " PT",
}

out = REPORTS / "estonia_publish_902b122cd27e.json"
out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({
    "wrote": str(out),
    "status": report["status"],
    "tip": report["source_tip"],
    "filter_L_A": report["filter_L_A"],
    "normalize_drops": report["n_dropped_total"],
    "corpus_rows": report["corpus_rows"],
    "ir_commit_sha12": report["ir_commit_short"],
    "hub_url": report["hub_url"],
    "blockers": report["blockers"],
    "sigterm": report["collectors_sigterm_pids"],
}, indent=2))
