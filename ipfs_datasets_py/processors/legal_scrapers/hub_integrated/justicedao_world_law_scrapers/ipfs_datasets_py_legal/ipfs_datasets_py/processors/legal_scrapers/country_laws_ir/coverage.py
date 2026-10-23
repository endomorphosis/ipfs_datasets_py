"""Compare endomorphosis raw sources against justicedao GraphRAG releases.

Gap kinds
---------
* missing — no JusticeDAO IR (and no local pack)
* unpublished — local IR exists, Hub IR does not
* stale — Hub/local IR source revision does not match current endomorphosis SHA
* incomplete — missing corpus/BM25/graph, empty corpus, or source has no laws
* stub_vectors — IR is otherwise current but embeddings were stubbed
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping

from .catalog import EXCLUDED_SLUGS, all_countries, target_repo

ALIAS_TO_CANONICAL = {
    "dominican_republic": "dominicanrepublic",
    "el_salvador": "elsalvador",
    "north_korea": "northkorea",
    "papua_new_guinea": "papuanewguinea",
    "san_marino": "sanmarino",
    "trinidad_and_tobago": "trinidad",
}


def _slug_from_source(dataset_id: str) -> str | None:
    if not dataset_id.startswith("endomorphosis/ipfs_") or not dataset_id.endswith("_laws"):
        return None
    return dataset_id.split("ipfs_", 1)[1].removesuffix("_laws")


def _slug_from_ir(dataset_id: str) -> str | None:
    if not dataset_id.startswith("justicedao/ipfs_") or not dataset_id.endswith("_laws_ir"):
        return None
    return dataset_id.split("ipfs_", 1)[1].removesuffix("_laws_ir")


def canonical_slug(slug: str) -> str:
    return ALIAS_TO_CANONICAL.get(slug, slug)


def list_hub_slugs(*, author: str, kind: str) -> list[str]:
    from huggingface_hub import HfApi

    from .auth import configure_hf, operator_token, public_token

    configure_hf()
    token = operator_token() or public_token()
    api = HfApi(token=token)
    out: list[str] = []
    for ds in api.list_datasets(author=author):
        slug = _slug_from_source(ds.id) if kind == "source" else _slug_from_ir(ds.id)
        if slug:
            out.append(slug)
    return sorted(set(out))


def local_release_slugs(releases_dir: Path) -> list[str]:
    if not releases_dir.is_dir():
        return []
    found: list[str] = []
    for path in sorted(releases_dir.glob("ipfs_*_laws_ir")):
        if (path / "manifest.json").is_file():
            slug = path.name.removeprefix("ipfs_").removesuffix("_laws_ir")
            found.append(slug)
    return found


IR_FAMILY_PREFIXES = (
    ("data/corpus/", "ir_missing_corpus"),
    ("data/bm25/", "ir_missing_bm25"),
    ("data/graph/", "ir_missing_graph"),
)
STUB_VECTOR_STATUSES = {"stub", "stub_missing_encoder", "incomplete"}
TINY_LAWS_BYTES = 1024


def classify_gap(
    *,
    excluded: bool = False,
    alias: bool = False,
    source_has_laws: bool = True,
    source_laws_bytes: int | None = None,
    source_revision: str | None = None,
    ir_files: list[str] | None = None,
    ir_source_revision: str | None = None,
    ir_corpus_rows: int | None = None,
    vector_status: str | None = None,
    local_only: bool = False,
    local_source_revision: str | None = None,
) -> dict[str, Any]:
    """Pure classifier for missing / stale / incomplete country IR."""
    issues: list[str] = []
    if alias:
        return {"status": "alias", "issues": issues, "rebuild": False, "publish": False}
    if excluded:
        return {"status": "excluded", "issues": issues, "rebuild": False, "publish": False}

    if not source_has_laws:
        issues.append("source_missing_laws")
    if (
        source_laws_bytes is not None
        and source_laws_bytes >= 0
        and source_laws_bytes < TINY_LAWS_BYTES
    ):
        issues.append("source_laws_tiny")

    if ir_files is None:
        issues.append("missing_ir")
    else:
        names = set(ir_files)
        if "manifest.json" not in names:
            issues.append("ir_missing_manifest")
        for prefix, issue in IR_FAMILY_PREFIXES:
            if not any(name.startswith(prefix) for name in names):
                issues.append(issue)
        if ir_corpus_rows is not None and int(ir_corpus_rows) <= 0:
            issues.append("ir_empty_corpus")
        if (
            source_revision
            and ir_source_revision
            and str(source_revision) != str(ir_source_revision)
        ):
            issues.append("stale_source_revision")
        if vector_status in STUB_VECTOR_STATUSES:
            issues.append("ir_stub_vectors")

    structural = {
        "source_missing_laws",
        "source_laws_tiny",
        "ir_missing_manifest",
        "ir_missing_corpus",
        "ir_missing_bm25",
        "ir_missing_graph",
        "ir_empty_corpus",
    }
    issue_set = set(issues)
    if "missing_ir" in issue_set:
        status = "unpublished" if local_only else "missing"
    elif "stale_source_revision" in issue_set:
        status = "stale"
    elif issue_set & structural:
        status = "incomplete"
    elif issue_set == {"ir_stub_vectors"}:
        status = "stub_vectors"
    elif not issues:
        status = "current"
    else:
        status = "incomplete"

    local_current = bool(
        source_revision
        and local_source_revision
        and str(source_revision) == str(local_source_revision)
    )
    rebuild = (
        status in {"missing", "unpublished", "stale", "incomplete", "stub_vectors"}
        and (not local_current or status == "stub_vectors")
    )
    publish = status in {"missing", "unpublished", "stale", "incomplete", "stub_vectors"} and (
        "source_missing_laws" not in issues
    )
    return {
        "status": status,
        "issues": issues,
        "rebuild": rebuild,
        "publish": publish,
    }


def _ir_source_revision(manifest: Mapping[str, Any] | None) -> str | None:
    if not manifest:
        return None
    pinned = manifest.get("dataset_revision") or (manifest.get("source") or {}).get(
        "source_revision"
    )
    text = str(pinned or "").strip()
    return text or None


def _vector_status(manifest: Mapping[str, Any] | None) -> str | None:
    if not manifest:
        return None
    vector = manifest.get("vector") or {}
    if isinstance(vector, dict) and vector.get("status"):
        return str(vector.get("status"))
    incremental = manifest.get("incremental") or {}
    nested = incremental.get("vectors") if isinstance(incremental, dict) else None
    if isinstance(nested, dict) and nested.get("status"):
        return str(nested.get("status"))
    if isinstance(vector, dict) and vector.get("stub"):
        return "stub"
    return None


def load_local_manifest(release_dir: Path) -> dict[str, Any]:
    path = Path(release_dir) / "manifest.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _sibling_map(info: Any) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for sib in getattr(info, "siblings", None) or []:
        name = str(getattr(sib, "rfilename", "") or "")
        if not name:
            continue
        size = getattr(sib, "size", None)
        try:
            out[name] = int(size) if size is not None else None  # type: ignore[assignment]
        except (TypeError, ValueError):
            out[name] = None  # type: ignore[assignment]
    return out


def _inspect_source(slug: str, cache_dir: Path | None = None) -> dict[str, Any]:
    from huggingface_hub import dataset_info

    from .auth import configure_hf, operator_token, public_token

    repo = f"endomorphosis/ipfs_{slug}_laws"
    configure_hf()
    info = dataset_info(repo, token=operator_token() or public_token())
    files = _sibling_map(info)
    laws_file = next(
        (name for name in ("data/laws.parquet", "laws.parquet") if name in files),
        None,
    )
    arts_file = next(
        (name for name in ("data/articles.parquet", "articles.parquet") if name in files),
        None,
    )
    return {
        "repo": repo,
        "revision": getattr(info, "sha", None),
        "files": sorted(files),
        "has_laws": laws_file is not None,
        "has_articles": arts_file is not None,
        "laws_bytes": files.get(laws_file) if laws_file else None,
        "articles_bytes": files.get(arts_file) if arts_file else None,
    }


def _inspect_ir(slug: str, cache_dir: Path) -> dict[str, Any] | None:
    from huggingface_hub import HfApi, dataset_info, hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError

    from .auth import configure_hf, operator_token, public_token

    repo = target_repo(slug)
    configure_hf()
    token = operator_token() or public_token()
    try:
        info = dataset_info(repo, token=token)
    except RepositoryNotFoundError:
        return None
    files = _sibling_map(info)
    if len(files) < 8:
        try:
            listed = HfApi(token=token).list_repo_files(repo_id=repo, repo_type="dataset")
            for name in listed:
                files.setdefault(str(name), None)
        except Exception:
            pass
    manifest: dict[str, Any] = {}
    if "manifest.json" in files:
        try:
            path = hf_hub_download(
                repo_id=repo,
                filename="manifest.json",
                repo_type="dataset",
                token=token,
                cache_dir=str(cache_dir / "hf"),
            )
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                manifest = payload
        except (EntryNotFoundError, OSError, json.JSONDecodeError):
            manifest = {}
    counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    return {
        "repo": repo,
        "hub_revision": getattr(info, "sha", None),
        "files": sorted(files),
        "manifest": manifest,
        "source_revision": _ir_source_revision(manifest),
        "corpus_rows": counts.get("corpus_rows"),
        "vector_status": _vector_status(manifest),
    }


def gap_report(
    releases_dir: Path | None = None,
    *,
    slugs: list[str] | None = None,
    workers: int = 8,
) -> dict[str, Any]:
    """Live Hub scan: missing, stale, incomplete, and unpublished country IR."""
    from .build import CACHE, RELEASES

    sources = slugs or [
        s
        for s in list_hub_slugs(author="endomorphosis", kind="source")
        if s not in ALIAS_TO_CANONICAL
    ]
    hub_ir = set(list_hub_slugs(author="justicedao", kind="ir"))
    local_dir = Path(releases_dir) if releases_dir else RELEASES
    local_ir = set(local_release_slugs(local_dir))
    cache_dir = CACHE
    cache_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []

    def _one(slug: str) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                source = _inspect_source(slug)
                ir = _inspect_ir(slug, cache_dir) if slug in hub_ir else None
                break
            except Exception as exc:
                last_exc = exc
                name = type(exc).__name__
                msg = str(exc)
                if "429" in msg or "rate limit" in msg.lower():
                    time.sleep(min(45, 3 ** attempt * 2))
                    continue
                raise
        else:
            raise last_exc or RuntimeError(f"scan failed for {slug}")
        local_manifest = load_local_manifest(local_dir / f"ipfs_{slug}_laws_ir")
        local_rev = _ir_source_revision(local_manifest) if local_manifest else None
        classified = classify_gap(
            excluded=slug in EXCLUDED_SLUGS,
            alias=False,
            source_has_laws=bool(source.get("has_laws")),
            source_laws_bytes=source.get("laws_bytes"),
            source_revision=source.get("revision"),
            ir_files=None if ir is None else ir.get("files"),
            ir_source_revision=(ir or {}).get("source_revision") or local_rev,
            ir_corpus_rows=(ir or {}).get("corpus_rows")
            if ir is not None
            else (local_manifest.get("counts") or {}).get("corpus_rows")
            if local_manifest
            else None,
            vector_status=(ir or {}).get("vector_status")
            or _vector_status(local_manifest),
            local_only=slug in local_ir and slug not in hub_ir,
            local_source_revision=local_rev,
        )
        return {
            "slug": slug,
            "source": source.get("repo"),
            "target": target_repo(slug),
            "source_revision": source.get("revision"),
            "ir_source_revision": (ir or {}).get("source_revision"),
            "local_source_revision": local_rev,
            "has_hub_ir": ir is not None,
            "has_local_ir": slug in local_ir,
            "source_has_articles": source.get("has_articles"),
            "source_laws_bytes": source.get("laws_bytes"),
            "corpus_rows": (ir or {}).get("corpus_rows")
            if ir is not None
            else (local_manifest.get("counts") or {}).get("corpus_rows")
            if local_manifest
            else None,
            "vector_status": (ir or {}).get("vector_status")
            or _vector_status(local_manifest),
            **classified,
        }

    workers = max(1, min(int(workers), 16))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_one, slug): slug for slug in sources}
        for fut in as_completed(futs):
            slug = futs[fut]
            try:
                rows.append(fut.result())
            except Exception as exc:
                rows.append(
                    {
                        "slug": slug,
                        "source": f"endomorphosis/ipfs_{slug}_laws",
                        "target": target_repo(slug),
                        "status": "incomplete",
                        "issues": [f"scan_error:{type(exc).__name__}"],
                        "rebuild": False,
                        "publish": False,
                        "error": str(exc),
                    }
                )
    rows.sort(key=lambda r: str(r.get("slug")))
    by_status: dict[str, list[str]] = {}
    for row in rows:
        by_status.setdefault(str(row.get("status")), []).append(str(row.get("slug")))
    return {
        "n": len(rows),
        "by_status": {k: sorted(v) for k, v in sorted(by_status.items())},
        "counts": {k: len(v) for k, v in sorted(by_status.items())},
        "rebuild": [r["slug"] for r in rows if r.get("rebuild")],
        "publish": [r["slug"] for r in rows if r.get("publish")],
        "countries": rows,
    }


def coverage_report(releases_dir: Path | None = None) -> dict[str, Any]:
    from .build import RELEASES

    sources = list_hub_slugs(author="endomorphosis", kind="source")
    hub_ir = list_hub_slugs(author="justicedao", kind="ir")
    local_ir = local_release_slugs(Path(releases_dir) if releases_dir else RELEASES)
    hub_ir_canon = {canonical_slug(s) for s in hub_ir}
    local_ir_canon = {canonical_slug(s) for s in local_ir}
    missing_hub: list[dict[str, Any]] = []
    missing_local: list[dict[str, Any]] = []
    excluded: list[str] = []
    aliases: list[str] = []
    for slug in sources:
        if slug in ALIAS_TO_CANONICAL:
            aliases.append(slug)
            continue
        if slug in EXCLUDED_SLUGS:
            excluded.append(slug)
            continue
        row = {
            "slug": slug,
            "source": f"endomorphosis/ipfs_{slug}_laws",
            "target": target_repo(slug),
        }
        if slug not in hub_ir_canon:
            missing_hub.append(row)
        if slug not in local_ir_canon and slug not in hub_ir_canon:
            missing_local.append(row)
    return {
        "n_sources": len(sources),
        "n_hub_ir": len(hub_ir),
        "n_local_ir": len(local_ir),
        "n_catalog": len(all_countries()),
        "excluded": excluded,
        "alias_sources": aliases,
        "missing_justicedao": missing_hub,
        "missing_local_and_hub": missing_local,
        "local_only": sorted(local_ir_canon - hub_ir_canon),
    }
