"""Harvest parked Hugging Face collectors and rewrite sandbox paths."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .helpers.paths import collectors_root, corpora_root, huggingface_token

LEGAL_SCRAPERS_REPO = "endomorphosis/legal_scrapers"
SOURCE_DATASET_PREFIX = "endomorphosis/ipfs_"
HF_DATASET_RESOLVE = "https://huggingface.co/datasets/{repo}/resolve/main/{path}"
HF_DATASET_TREE = "https://huggingface.co/api/datasets/{repo}/tree/main?recursive=1&expand=false"
USER_AGENT = "ipfs-datasets-legal-harvest/1.0"

_WORKSPACE_CORPORA_RE = re.compile(r'Path\(\s*"/workspace/legal-corpora(?:/([^"]*))?"\s*\)')
_WORKSPACE_SCRAPERS_RE = re.compile(r'Path\(\s*"/workspace/legal_scrapers/scrapers"\s*\)')
_WORKSPACE_SCRAPERS_ROOT_RE = re.compile(r'Path\(\s*"/workspace/legal_scrapers"\s*\)')
_WORKSPACE_STAGING_RE = re.compile(r'Path\(\s*f?"/workspace/legal_scrapers/staging_\{cc\}"\s*\)')
_BOX_TOKEN_RE = re.compile(r'Path\(\s*"/home/box/\.cache/huggingface/token"\s*\)')
_WORKSPACE_LITERAL_RE = re.compile(r"/workspace/legal-corpora")
_WORKSPACE_SCRAPERS_LITERAL_RE = re.compile(r"/workspace/legal_scrapers")

SHARED_HELPER_FILES = (
    "common.py",
    "world_lib.py",
    "archive_fallbacks.py",
    "pdf_extract_lib.py",
    "world_package.py",
    "collector.py",
)

PREAMBLE = '''\
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
'''


@dataclass(frozen=True)
class HarvestedFile:
    repo_id: str
    source_path: str
    local_path: str
    rewritten: bool = False
    bytes_written: int = 0


@dataclass(frozen=True)
class HarvestResult:
    collectors_root: str
    corpora_root: str
    files: list[HarvestedFile] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.files)

    @property
    def failure_count(self) -> int:
        return len(self.errors)


def rewrite_sandbox_source(source: str) -> str:
    """Replace Hugging Face parking-lot sandbox paths with env-configurable roots."""

    text = str(source or "")
    if not text:
        return text

    def _corpora_path(match: re.Match[str]) -> str:
        suffix = match.group(1) or ""
        if not suffix:
            return "_CORPORA"
        parts = " / ".join(json.dumps(part) for part in suffix.split("/") if part)
        return f"_CORPORA / {parts}" if parts else "_CORPORA"

    rewritten = _WORKSPACE_CORPORA_RE.sub(_corpora_path, text)
    rewritten = _WORKSPACE_SCRAPERS_RE.sub("_SCRAPERS", rewritten)
    rewritten = _WORKSPACE_STAGING_RE.sub('_SCRAPERS.parent / f"staging_{cc}"', rewritten)
    rewritten = _WORKSPACE_SCRAPERS_ROOT_RE.sub("_SCRAPERS.parent", rewritten)
    rewritten = _BOX_TOKEN_RE.sub("_HF_TOKEN_PATH", rewritten)
    rewritten = _WORKSPACE_LITERAL_RE.sub("{_CORPORA}", rewritten)
    rewritten = _WORKSPACE_SCRAPERS_LITERAL_RE.sub("{_SCRAPERS.parent}", rewritten)
    if rewritten == text and "/workspace/" not in text and "/home/box/" not in text:
        return text
    if "Harvested collector path injection" in rewritten:
        return rewritten
    return _insert_preamble(rewritten)


def _insert_preamble(source: str) -> str:
    lines = source.splitlines(keepends=True)
    insert_at = 0
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    while insert_at < len(lines) and lines[insert_at].strip() == "":
        insert_at += 1
    if insert_at < len(lines) and lines[insert_at].lstrip().startswith(('"""', "'''")):
        quote = '"""' if '"""' in lines[insert_at] else "'''"
        if lines[insert_at].count(quote) >= 2 and lines[insert_at].strip() != quote:
            insert_at += 1
        else:
            insert_at += 1
            while insert_at < len(lines) and quote not in lines[insert_at]:
                insert_at += 1
            if insert_at < len(lines):
                insert_at += 1
    while insert_at < len(lines) and lines[insert_at].strip() == "":
        insert_at += 1
    while insert_at < len(lines) and lines[insert_at].startswith("from __future__ import"):
        insert_at += 1
    preamble = PREAMBLE if PREAMBLE.endswith("\n") else PREAMBLE + "\n"
    return "".join(lines[:insert_at]) + preamble + "".join(lines[insert_at:])


def _http_bytes(url: str, *, token: str = "", retries: int = 4) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=60) as response:
                return response.read()
        except HTTPError as exc:
            last_error = exc
            if exc.code in {404, 410, 401, 403}:
                raise
            time.sleep(min(20, 1.5 * attempt))
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(min(20, 1.5 * attempt))
    raise RuntimeError(f"GET failed {url}: {last_error}")


def _http_json(url: str, *, token: str = "") -> Any:
    payload = json.loads(_http_bytes(url, token=token).decode("utf-8"))
    return payload


def list_repo_files(repo_id: str, *, token: str = "") -> list[str]:
    payload = _http_json(HF_DATASET_TREE.format(repo=repo_id), token=token)
    if not isinstance(payload, list):
        raise ValueError(f"Unexpected tree payload for {repo_id}")
    return [str(item.get("path") or "") for item in payload if item.get("type") == "file" and item.get("path")]


def download_repo_file(
    repo_id: str,
    path: str,
    dest: Path,
    *,
    token: str = "",
    rewrite: bool = True,
    skip_existing: bool = False,
) -> HarvestedFile:
    if skip_existing and dest.is_file() and dest.stat().st_size > 0:
        return HarvestedFile(
            repo_id=repo_id,
            source_path=path,
            local_path=str(dest),
            rewritten=False,
            bytes_written=dest.stat().st_size,
        )
    url = HF_DATASET_RESOLVE.format(repo=repo_id, path=quote(path, safe="/"))
    raw = _http_bytes(url, token=token)
    dest.parent.mkdir(parents=True, exist_ok=True)
    rewritten = False
    if rewrite and dest.suffix == ".py":
        text = raw.decode("utf-8", errors="replace")
        updated = rewrite_sandbox_source(text)
        dest.write_text(updated, encoding="utf-8")
        rewritten = updated != text
        size = dest.stat().st_size
    else:
        dest.write_bytes(raw)
        size = dest.stat().st_size
    return HarvestedFile(
        repo_id=repo_id,
        source_path=path,
        local_path=str(dest),
        rewritten=rewritten,
        bytes_written=size,
    )


def harvest_legal_scrapers_repo(
    *,
    dest_root: Path | None = None,
    token: Optional[str] = None,
    rewrite: bool = True,
) -> HarvestResult:
    root = collectors_root(dest_root)
    shared = root / "shared"
    raw = root / "legal_scrapers"
    token_value = token if token is not None else huggingface_token()
    result_files: list[HarvestedFile] = []
    errors: list[dict[str, Any]] = []
    try:
        files = list_repo_files(LEGAL_SCRAPERS_REPO, token=token_value)
    except Exception as exc:
        return HarvestResult(
            collectors_root=str(root),
            corpora_root=str(corpora_root()),
            errors=[{"repo_id": LEGAL_SCRAPERS_REPO, "error": str(exc)}],
        )
    for path in files:
        name = Path(path).name
        targets: list[Path] = [raw / path]
        if name in SHARED_HELPER_FILES or path.startswith("scrapers/"):
            if path.startswith("scrapers/"):
                targets.append(shared / name)
            elif name in SHARED_HELPER_FILES:
                targets.append(shared / name)
        try:
            downloaded = None
            for target in targets:
                downloaded = download_repo_file(
                    LEGAL_SCRAPERS_REPO,
                    path,
                    target,
                    token=token_value,
                    rewrite=rewrite and target.suffix == ".py",
                )
                result_files.append(downloaded)
        except Exception as exc:
            errors.append({"repo_id": LEGAL_SCRAPERS_REPO, "path": path, "error": str(exc)})
    return HarvestResult(
        collectors_root=str(root),
        corpora_root=str(corpora_root()),
        files=result_files,
        errors=errors,
    )


def _is_harvestable_scraper_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/")
    if not normalized.startswith("scrapers/") or not normalized.endswith(".py"):
        return False
    if "/__pycache__/" in normalized or normalized.endswith(".pyc"):
        return False
    return True


def harvest_dataset_collectors(
    dataset_id: str,
    *,
    dest_root: Path | None = None,
    token: Optional[str] = None,
    rewrite: bool = True,
    skip_existing: bool = False,
) -> HarvestResult:
    root = collectors_root(dest_root)
    shared = root / "shared"
    dataset_dir = root / "datasets" / dataset_id.replace("/", "__")
    token_value = token if token is not None else huggingface_token()
    files: list[HarvestedFile] = []
    errors: list[dict[str, Any]] = []
    try:
        repo_files = list_repo_files(dataset_id, token=token_value)
    except Exception as exc:
        return HarvestResult(
            collectors_root=str(root),
            corpora_root=str(corpora_root()),
            errors=[{"repo_id": dataset_id, "error": str(exc)}],
        )
    for path in repo_files:
        if not _is_harvestable_scraper_path(path):
            continue
        name = Path(path).name
        targets = [dataset_dir / path]
        if name in SHARED_HELPER_FILES or name.startswith("collect_") or name.startswith("_"):
            targets.append(shared / name)
        try:
            for target in targets:
                files.append(
                    download_repo_file(
                        dataset_id,
                        path,
                        target,
                        token=token_value,
                        rewrite=rewrite,
                        skip_existing=skip_existing,
                    )
                )
        except Exception as exc:
            errors.append({"repo_id": dataset_id, "path": path, "error": str(exc)})
    return HarvestResult(
        collectors_root=str(root),
        corpora_root=str(corpora_root()),
        files=files,
        errors=errors,
    )


def list_harvested_collector_names(dest_root: Path | None = None) -> set[str]:
    root = collectors_root(dest_root)
    names: set[str] = set()
    for folder in (
        root / "shared",
        root / "legal_scrapers" / "scrapers",
        root / "legal_scrapers",
    ):
        if folder.is_dir():
            names.update(path.name for path in folder.glob("collect_*.py"))
    datasets = root / "datasets"
    if datasets.is_dir():
        names.update(path.name for path in datasets.glob("**/collect_*.py"))
    return names


def missing_catalog_collectors(
    entries: Iterable[Mapping[str, Any]] | None = None,
    *,
    dest_root: Path | None = None,
) -> list[dict[str, str]]:
    if entries is None:
        from .catalog import list_snapshot_corpora

        selected = [
            {
                "slug": item.slug,
                "collector": item.collector,
                "source_dataset_id": item.source_dataset_id,
            }
            for item in list_snapshot_corpora(include_aliases=False)
        ]
    else:
        selected = list(entries)
    present = list_harvested_collector_names(dest_root)
    missing: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in selected:
        collector = str(entry.get("collector") or "").strip()
        dataset_id = str(entry.get("source_dataset_id") or "").strip()
        slug = str(entry.get("slug") or "").strip()
        if not collector or collector in present or collector in seen:
            continue
        seen.add(collector)
        missing.append({"slug": slug, "collector": collector, "source_dataset_id": dataset_id})
    return missing


def harvest_all_dataset_collectors(
    entries: Iterable[Mapping[str, Any]] | None = None,
    *,
    dest_root: Path | None = None,
    token: Optional[str] = None,
    rewrite: bool = True,
    skip_existing: bool = True,
    missing_only: bool = True,
    max_workers: int = 8,
) -> HarvestResult:
    if entries is None:
        from .catalog import list_snapshot_corpora

        selected = [
            {
                "slug": item.slug,
                "collector": item.collector,
                "source_dataset_id": item.source_dataset_id,
            }
            for item in list_snapshot_corpora(include_aliases=False)
        ]
    else:
        selected = list(entries)
    if missing_only:
        needed = {item["source_dataset_id"] for item in missing_catalog_collectors(selected, dest_root=dest_root)}
        selected = [item for item in selected if item.get("source_dataset_id") in needed]
    files: list[HarvestedFile] = []
    errors: list[dict[str, Any]] = []
    if not selected:
        root = collectors_root(dest_root)
        return HarvestResult(collectors_root=str(root), corpora_root=str(corpora_root()), files=files, errors=errors)

    def _one(dataset_id: str) -> HarvestResult:
        return harvest_dataset_collectors(
            dataset_id,
            dest_root=dest_root,
            token=token,
            rewrite=rewrite,
            skip_existing=skip_existing,
        )

    dataset_ids = list(dict.fromkeys(str(item.get("source_dataset_id") or "") for item in selected if item.get("source_dataset_id")))
    workers = max(1, min(int(max_workers or 1), len(dataset_ids)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_one, dataset_id): dataset_id for dataset_id in dataset_ids}
        for fut in as_completed(futs):
            dataset_id = futs[fut]
            try:
                part = fut.result()
            except Exception as exc:
                errors.append({"repo_id": dataset_id, "error": str(exc)})
                continue
            files.extend(part.files)
            errors.extend(part.errors)
    root = collectors_root(dest_root)
    return HarvestResult(
        collectors_root=str(root),
        corpora_root=str(corpora_root()),
        files=files,
        errors=errors,
    )


def harvest_catalog_collectors(
    entries: Iterable[Mapping[str, Any]],
    *,
    dest_root: Path | None = None,
    token: Optional[str] = None,
    include_legal_scrapers: bool = True,
    limit: Optional[int] = None,
) -> HarvestResult:
    files: list[HarvestedFile] = []
    errors: list[dict[str, Any]] = []
    if include_legal_scrapers:
        base = harvest_legal_scrapers_repo(dest_root=dest_root, token=token)
        files.extend(base.files)
        errors.extend(base.errors)
    selected = list(entries)
    if limit is not None:
        selected = selected[: max(0, int(limit))]
    part = harvest_all_dataset_collectors(
        selected,
        dest_root=dest_root,
        token=token,
        skip_existing=True,
        missing_only=True,
    )
    files.extend(part.files)
    errors.extend(part.errors)
    root = collectors_root(dest_root)
    return HarvestResult(
        collectors_root=str(root),
        corpora_root=str(corpora_root()),
        files=files,
        errors=errors,
    )


def harvest_result_to_dict(result: HarvestResult) -> dict[str, Any]:
    return {
        "collectors_root": result.collectors_root,
        "corpora_root": result.corpora_root,
        "success_count": result.success_count,
        "failure_count": result.failure_count,
        "files": [asdict(item) for item in result.files],
        "errors": list(result.errors),
    }


__all__ = [
    "HarvestResult",
    "HarvestedFile",
    "LEGAL_SCRAPERS_REPO",
    "download_repo_file",
    "harvest_all_dataset_collectors",
    "harvest_catalog_collectors",
    "harvest_dataset_collectors",
    "harvest_legal_scrapers_repo",
    "harvest_result_to_dict",
    "list_harvested_collector_names",
    "list_repo_files",
    "missing_catalog_collectors",
    "rewrite_sandbox_source",
]
