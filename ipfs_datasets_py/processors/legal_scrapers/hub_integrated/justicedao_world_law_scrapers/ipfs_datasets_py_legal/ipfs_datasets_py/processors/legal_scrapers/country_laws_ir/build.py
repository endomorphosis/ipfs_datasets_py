"""End-to-end build: normalize → incremental vectors → BM25 → graph → package.

Default mode is ``auto``: skip when the endomorphosis source revision is
unchanged, otherwise delta-refresh embeddings by ``entry_cid`` and rebuild
BM25/graph from the current corpus. Publication to ``justicedao/*`` is opt-in
via ``upload=True``.
"""

from __future__ import annotations

import os

import json

import pandas as pd
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .sparse import export_sparse_graphrag
from .mem import MemAbort, checkpoint, log_mem
from .spill import spill_dir_for, spill_pickle
from .package import package_from_spill, package_release
from .catalog import get_country, indexable_countries, target_repo

from .incremental import (
    fetch_hub_prior,
    load_embedding_cache,
    load_prior_release,
    load_release_vectors_by_cid,
    merge_embedding_maps,
    plan_rebuild,
    save_embedding_cache,
)
from .normalize import build_corpus, load_source
from .auth import configure_hf
from .vectors import (
    DIMENSION,
    MODEL_NAME,
    assemble_embeddings,
    embeddings_by_cid,
    layout_stub_vectors,
    layout_vectors,
    select_device,
)

ROOT = Path(os.environ.get("COUNTRY_LAWS_IR_ROOT", str(Path.home() / ".ipfs_datasets" / "country-laws-ir")))
CACHE = ROOT / "cache"
RELEASES = ROOT / "releases"
REPORTS = ROOT / "reports"
PROGRESS = ROOT / "progress.jsonl"


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


def record_progress(event: dict[str, Any]) -> None:
    event = dict(event)
    event.setdefault("ts", datetime.now(timezone.utc).isoformat())
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    lock_path = PROGRESS.with_suffix(".lock")
    with lock_path.open("a", encoding="utf-8") as lock_fh:
        try:
            import fcntl

            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        with PROGRESS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _prior_dir_for(
    slug: str,
    out: Path,
    prior_dir: Path | None,
    *,
    fetch_hub: bool = True,
) -> Path | None:
    if prior_dir is not None:
        return Path(prior_dir)
    if out.is_dir() and (out / "manifest.json").is_file():
        return out
    default = RELEASES / f"ipfs_{slug}_laws_ir"
    if default.is_dir() and (default / "manifest.json").is_file() and default.resolve() != out.resolve():
        return default
    if not fetch_hub:
        return None
    hub = fetch_hub_prior(slug, cache_root=CACHE / "hub-ir")
    if hub is not None:
        _log(f"using justicedao prior {hub}")
    return hub


def _encode_vectors(
    *,
    corpus: pd.DataFrame,
    country_slug: str,
    prior,
    plan,
    skip_vectors: bool,
    device: str,
) -> tuple[dict[str, Any], str | None, dict[str, Any]]:
    import gc

    vector_report: dict[str, Any] = {"status": "stub"}
    vector_blocker = None
    if skip_vectors:
        vectors = layout_stub_vectors(corpus, reason="skip_vectors flag")
        return vectors, "skip_vectors", {"status": "stub", "reason": "skip_vectors"}

    cid_cache_path = CACHE / "embeddings" / f"{country_slug}_by_cid.parquet"
    prior_by_cid = {}
    if plan.reuse_embeddings:
        prior_by_cid = merge_embedding_maps(
            load_embedding_cache(cid_cache_path),
            None if prior is None else load_release_vectors_by_cid(prior.directory),
        )
        _log(f"embedding cache reused_cids={len(prior_by_cid)}")
    try:
        positional = CACHE / "embeddings" / f"{country_slug}.npy"
        resolved, fallback = select_device(device)
        if fallback:
            _log(f"embedding device fallback requested={device} using={resolved}")
        embeddings, vector_report = assemble_embeddings(
            corpus,
            prior_by_cid,
            encode_missing=True,
            device=resolved,
            checkpoint_path=str(positional),
        )
        if (
            vector_report.get("status") in {"stub_missing_encoder", "incomplete"}
            and not int(vector_report.get("n_reused") or 0)
        ):
            vector_blocker = vector_report.get("reason") or vector_report.get("status")
            vectors = layout_stub_vectors(corpus, reason=str(vector_blocker))
            return vectors, vector_blocker, vector_report
        vectors = layout_vectors(corpus, embeddings)
        if int(vector_report.get("n_reused") or 0) and vector_report.get("status") != "reused":
            vectors["stats"]["status"] = "partial"
            vectors["stats"]["n_reused"] = int(vector_report.get("n_reused") or 0)
            vectors["stats"]["n_missing"] = int(vector_report.get("n_missing") or 0)
            vector_blocker = vector_report.get("reason") or vector_report.get("status")
        save_embedding_cache(
            cid_cache_path,
            merge_embedding_maps(prior_by_cid, embeddings_by_cid(corpus, embeddings)),
            model_name=MODEL_NAME,
            dimension=DIMENSION,
        )
        del embeddings
        gc.collect()
        _log(
            f"vectors n={vectors['stats']['n_vectors']} shards={vectors['stats']['shard_count']} "
            f"reused={vector_report.get('n_reused')} encoded={vector_report.get('n_encoded')}"
        )
        return vectors, None, vector_report
    except Exception as exc:
        vector_blocker = f"embedding_failed: {exc}"
        _log(f"vector embedding failed; writing stub ({exc})")
        vectors = layout_stub_vectors(corpus, reason=vector_blocker)
        return vectors, vector_blocker, {"status": "failed", "reason": str(exc)}


def build_country(
    source: str,
    out: Path | None = None,
    upload: bool = False,
    device: str = "cuda",
    neighbor_k: int = 8,
    skip_vectors: bool = False,
    mode: str = "auto",
    force: bool = False,
    prior_dir: Path | None = None,
    fetch_hub_prior_ir: bool = True,
    renormalize: bool = False,
) -> dict[str, Any]:
    country = get_country(source)
    if not country.get("indexable", True):
        raise RuntimeError(f"{country['repo']} is excluded: {country.get('skip_reason')}")
    repo = country["repo"]
    out = Path(out) if out else RELEASES / f"ipfs_{country['slug']}_laws_ir"
    local_dir = country.get("local_source_dir") or (
        str(Path(source).resolve())
        if Path(source).is_dir()
        and (
            (Path(source) / "data" / "laws.parquet").is_file()
            or (Path(source) / "laws.parquet").is_file()
        )
        else None
    )
    _log(
        f"build start {repo} -> {out} "
        f"(upload={upload} mode={mode} force={force} renormalize={renormalize}) local={local_dir}"
    )
    configure_hf()
    CACHE.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    laws, articles, source_meta = load_source(local_dir or repo, CACHE)
    _log(
        f"source loaded laws={source_meta['n_laws_source']} "
        f"articles={source_meta['n_articles_source']} rev={source_meta['source_revision']}"
    )
    prior = load_prior_release(
        _prior_dir_for(
            country["slug"],
            out,
            prior_dir,
            fetch_hub=fetch_hub_prior_ir,
        )
    )
    plan = plan_rebuild(
        mode=mode,
        source_meta=source_meta,
        prior=prior,
        force=force,
        rebuild_stub_vectors=not skip_vectors,
    )
    if plan.skip_build and not renormalize:
        _log(f"skip unchanged {country['slug']} rev={plan.source_revision}")
        result = {
            "country": country["slug"],
            "source": repo,
            "source_revision": source_meta["source_revision"],
            "out": str(out),
            "target_hub_id": target_repo(country["slug"]),
            "skipped": True,
            "incremental": plan.to_dict(),
            "normalization": {"n_out": plan.delta.current_count if plan.delta else 0},
            "vector_blocker": None,
            "neighbor_via": None,
            "schema_version": "country-laws-ir-graphrag/v1",
        }
        record_progress({"event": "skipped_unchanged", **{k: v for k, v in result.items() if k != "normalization"}})
        return result

    corpus, norm_report = build_corpus(laws, articles, source_meta)
    report_path = REPORTS / f"{country['slug']}_normalization.json"
    report_path.write_text(json.dumps(norm_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPORTS / "normalization.json").write_text(
        json.dumps(norm_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _log(
        f"normalized docs={len(corpus)} unit={norm_report['unit']} "
        f"dropped={norm_report['n_dropped_total']} report={report_path}"
    )
    if corpus.empty:
        raise RuntimeError("Normalized corpus is empty; refusing to package")
    verdict = (norm_report or {}).get("verification") or {}
    if verdict.get("blocks_graphrag") and not force:
        from .verify import NormalizationAdmissionError

        raise NormalizationAdmissionError(
            f"{country['slug']} failed normalization verifiers: {verdict.get('failed_ids')}"
        )

    import gc

    plan = plan_rebuild(
        mode=mode,
        source_meta=source_meta,
        prior=prior,
        current_corpus=corpus,
        force=force,
        rebuild_stub_vectors=not skip_vectors,
        compare_normalized=renormalize and not force,
    )
    _log(
        f"rebuild kind={plan.kind.value} reuse_embeddings={plan.reuse_embeddings} "
        f"added={0 if plan.delta is None else plan.delta.n_added} "
        f"removed={0 if plan.delta is None else plan.delta.n_removed}"
    )
    if plan.skip_build:
        _log(f"skip unchanged after normalize {country['slug']}")
        result = {
            "country": country["slug"],
            "source": repo,
            "source_revision": source_meta["source_revision"],
            "out": str(out),
            "target_hub_id": target_repo(country["slug"]),
            "skipped": True,
            "incremental": plan.to_dict(),
            "normalization": {
                "n_out": norm_report.get("n_out"),
                "unit": norm_report.get("unit"),
                "n_law_rows": norm_report.get("n_law_rows"),
                "n_child_rows": norm_report.get("n_child_rows"),
            },
            "vector_blocker": None,
            "neighbor_via": None,
            "schema_version": "country-laws-ir-graphrag/v1",
        }
        record_progress({"event": "skipped_unchanged", **{k: v for k, v in result.items() if k != "normalization"}})
        return result

    n_docs = len(corpus)
    spill = spill_dir_for(country["slug"], CACHE)
    spill.mkdir(parents=True, exist_ok=True)
    corpus_ckpt = CACHE / f"{country['slug']}_corpus.parquet"
    corpus.to_parquet(corpus_ckpt, index=False)
    checkpoint("after_normalize", log=_log)

    vectors, vector_blocker, vector_report = _encode_vectors(
        corpus=corpus,
        country_slug=country["slug"],
        prior=prior,
        plan=plan,
        skip_vectors=skip_vectors,
        device=device,
    )
    spill_pickle(spill / "vectors.pkl", vectors)
    del vectors
    gc.collect()
    checkpoint("vectors_spilled", log=_log)
    extra_manifest = {"incremental": {**plan.to_dict(), "vectors": vector_report}}

    neighbor_via = "hf_graphrag"
    if out.exists():
        import shutil as _shutil

        _shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    _log(f"sparse GraphRAG via hf_graphrag.bm25/graph parquet builders n={n_docs}")
    sparse_report = export_sparse_graphrag(corpus, out)
    extra_manifest["sparse"] = sparse_report
    with open(spill / "vectors.pkl", "rb") as _vf:
        import pickle as _pickle

        vectors = _pickle.load(_vf)
    dummy_bm25 = {
        "documents": pd.DataFrame(),
        "postings": pd.DataFrame(),
        "stats": (sparse_report.get("bm25") or {}).get("bm25")
        or (sparse_report.get("bm25") or {}),
    }
    dummy_graph = {
        "nodes": pd.DataFrame(),
        "edges": pd.DataFrame(),
        "incoming": pd.DataFrame(),
        "outgoing": pd.DataFrame(),
        "stats": sparse_report.get("graph") or {},
    }
    code_root = Path(__file__).resolve().parent.parent
    manifest = package_release(
        out,
        corpus,
        dummy_bm25,
        dummy_graph,
        vectors,
        source_meta,
        country,
        code_root,
        normalization_report=norm_report,
        extra_manifest=extra_manifest,
        wipe=False,
        skip_bm25_graph=True,
    )
    del corpus, vectors
    gc.collect()
    _log(f"packaged {out}")
    result = {
        "country": country["slug"],
        "source": repo,
        "source_revision": source_meta["source_revision"],
        "out": str(out),
        "target_hub_id": target_repo(country["slug"]),
        "counts": manifest["counts"],
        "normalization": norm_report,
        "vector_blocker": vector_blocker,
        "neighbor_via": neighbor_via,
        "schema_version": manifest["schema_version"],
        "skipped": False,
        "incremental": extra_manifest["incremental"],
    }
    if upload:
        from .upload import upload_release

        hub = upload_release(out, target_repo(country["slug"]))
        result["hub"] = hub
        _log(f"uploaded {hub['url']} rev={hub['revision']}")
        record_progress({"event": "uploaded", **result})
    else:
        record_progress({"event": "built_local", **{k: v for k, v in result.items() if k != "normalization"}})
    return result


def batch(
    slugs: list[str] | None = None,
    upload: bool = False,
    skip_done: bool = True,
    mode: str = "auto",
    force: bool = False,
    skip_vectors: bool = False,
) -> list[dict[str, Any]]:
    """Build every indexable country. Unchanged Hub revisions are skipped in auto mode.

    ``skip_done`` is kept for compatibility: it no longer skips a country whose
    source revision changed. Pass ``force=True`` (or ``--no-skip-done``) to
    rebuild regardless of CID overlap.
    """
    targets = slugs or [c["slug"] for c in indexable_countries()]
    if "malta" in targets:
        targets = ["malta"] + [s for s in targets if s != "malta"]
    results = []
    rebuild_force = force or not skip_done
    for slug in targets:
        try:
            results.append(
                build_country(
                    slug,
                    upload=upload,
                    mode=mode,
                    force=rebuild_force,
                    skip_vectors=skip_vectors,
                )
            )
        except Exception as exc:
            _log(f"FAILED {slug}: {exc}")
            record_progress(
                {
                    "event": "failed",
                    "country": slug,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            continue
    return results


def reindex_from_gaps(
    *,
    upload: bool = False,
    slugs: list[str] | None = None,
    limit: int | None = None,
    max_corpus_rows: int | None = 20_000,
    skip_vectors: bool = False,
    workers: int = 4,
    mode: str = "auto",
    force: bool = False,
    all_indexable: bool = False,
    device: str = "cuda",
    renormalize: bool = False,
) -> list[dict[str, Any]]:
    """Rebuild country IR. Default is Hub gaps; ``all_indexable`` processes every catalog country.

    Default cap skips huge corpora (Finland, Dominican Republic). Pass
    ``max_corpus_rows=None`` to include them.
    """
    from .catalog import indexable_countries
    from .coverage import gap_report

    if slugs is None:
        if all_indexable:
            rows = [{"slug": c["slug"], "corpus_rows": 0} for c in indexable_countries()]
            _log(f"reindex all indexable n={len(rows)}")
        else:
            report = gap_report(workers=workers)
            rows = [c for c in report["countries"] if c.get("rebuild")]
            _log(
                f"reindex targets n={len(rows)} "
                f"(from scan rebuild={len(report.get('rebuild') or [])})"
            )
        rows.sort(key=lambda r: int(r.get("corpus_rows") or 0))
        if max_corpus_rows is not None:
            rows = [
                r
                for r in rows
                if int(r.get("corpus_rows") or 0) <= int(max_corpus_rows)
            ]
        if limit is not None:
            rows = rows[: int(limit)]
        slugs = [str(r["slug"]) for r in rows]
    kwargs = {
        "upload": upload,
        "mode": mode,
        "force": force,
        "skip_vectors": skip_vectors,
        "fetch_hub_prior_ir": True,
        "device": device,
        "renormalize": renormalize,
    }
    n_workers = max(1, int(workers or 1))
    _log(f"reindex parallel workers={n_workers} countries={len(slugs)} device=cuda")
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor, as_completed

    try:
        mp.set_start_method("spawn", force=False)
    except RuntimeError:
        pass

    results = [None] * len(slugs)
    with ProcessPoolExecutor(max_workers=n_workers, max_tasks_per_child=1) as pool:
        futs = {
            pool.submit(_reindex_one_country, (slug, kwargs)): i
            for i, slug in enumerate(slugs)
        }
        for fut in as_completed(futs):
            idx = futs[fut]
            slug = slugs[idx]
            try:
                results[idx] = fut.result()
            except Exception as exc:
                _log(f"FAILED {slug}: {exc}")
                results[idx] = {"country": slug, "skipped": False, "error": str(exc)}
    return [r for r in results if r is not None]


def _reindex_one_country(item: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    slug, kwargs = item
    _log(f"reindex start {slug}")
    try:
        return build_country(slug, **kwargs)
    except Exception as exc:
        _log(f"FAILED {slug}: {exc}")
        record_progress(
            {
                "event": "failed",
                "country": slug,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        return {"country": slug, "skipped": False, "error": str(exc)}
