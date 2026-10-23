#!/usr/bin/env python3
"""Local-only batch builder: skip existing releases, no HF upload, skip vectors for large corpora."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/workspace/country-laws-ir")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# Never upload; never rely on HF token
os.environ.pop("HF_TOKEN", None)
os.environ.pop("HUGGING_FACE_HUB_TOKEN", None)

from country_laws_ir.build import build_country, record_progress, _log  # noqa: E402
from country_laws_ir.catalog import EXCLUDED_SLUGS, indexable_countries  # noqa: E402

RELEASES = ROOT / "releases"
REPORTS = ROOT / "reports"
BATCH_LOG = REPORTS / "batch_local.log"
SUMMARY = REPORTS / "batch_summary.jsonl"

# Soft threshold: above this article/law count, skip vectors (embeddings bottleneck)
LARGE_DOC_HINT = 25000

# Prefer finishing medium/small first; known-large deferred toward end
DEFER_LARGE = {
    "australia", "argentina", "brazil", "canada", "china", "eu", "france",
    "india", "indonesia", "japan", "korea", "mexico", "russia", "spain",
    "uk", "usa", "ukraine", "italy", "poland", "turkey", "netherlands",
}


def has_release(slug: str) -> bool:
    man = RELEASES / slug / "manifest.json"
    return man.is_file()


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    done = {c["slug"] for c in indexable_countries() if has_release(c["slug"])}
    # Always treat malta/germany as done if present
    targets = [c["slug"] for c in indexable_countries() if c["slug"] not in EXCLUDED_SLUGS]
    # Order: non-deferred first (alpha), then deferred large
    small = [s for s in targets if s not in DEFER_LARGE]
    large = [s for s in targets if s in DEFER_LARGE]
    ordered = small + large

    with BATCH_LOG.open("a", encoding="utf-8") as blog:
        def blog_write(msg: str) -> None:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            line = f"[{ts}] {msg}"
            print(line, flush=True)
            blog.write(line + "\n")
            blog.flush()

        blog_write(f"batch start remaining={len([s for s in ordered if s not in done])} done={sorted(done)}")
        for slug in ordered:
            if slug in done:
                blog_write(f"skip existing release {slug}")
                continue
            out = RELEASES / slug
            skip_vectors = True  # wall-time pass: corpus+BM25+graph for all; vectors deferred
            # Also skip vectors for everyone by default to maximize coverage;
            # small ones can still embed if under threshold after a cheap probe — keep simple: embed only if not deferred
            try:
                blog_write(f"build start {slug} skip_vectors={skip_vectors}")
                result = build_country(
                    slug,
                    out=out,
                    upload=False,
                    device="cpu",
                    skip_vectors=skip_vectors,
                )
                n_out = result["normalization"]["n_out"]
                # If we embedded a "small" country that turned out huge, note it
                rec = {
                    "event": "batch_ok",
                    "country": slug,
                    "docs": n_out,
                    "unit": result["normalization"]["unit"],
                    "drops": result["normalization"]["drops"],
                    "vector_blocker": result.get("vector_blocker"),
                    "out": str(out),
                    "counts": result["counts"],
                }
                with SUMMARY.open("a", encoding="utf-8") as sf:
                    sf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                blog_write(f"OK {slug} docs={n_out} vectors={result.get('vector_blocker') or 'embedded'}")
            except Exception as exc:
                blog_write(f"FAILED {slug}: {exc}")
                record_progress({
                    "event": "failed",
                    "country": slug,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                })
                with SUMMARY.open("a", encoding="utf-8") as sf:
                    sf.write(json.dumps({
                        "event": "batch_failed",
                        "country": slug,
                        "error": str(exc),
                    }, ensure_ascii=False) + "\n")
                continue
        blog_write("batch finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
