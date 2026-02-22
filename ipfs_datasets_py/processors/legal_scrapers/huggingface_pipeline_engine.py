"""
HuggingFace Upload Pipeline Engine — canonical business logic.

Moved from mcp_server/tools/legal_dataset_tools/municipal_law_database_scrapers/
hugging_face_pipeline_engine.py to canonical package location.

Reusable by:
- MCP server tools (mcp_server/tools/legal_dataset_tools/)
- CLI commands
- Direct Python imports:
    from ipfs_datasets_py.processors.legal_scrapers.huggingface_pipeline_engine import (
        RateLimiter,
        UploadToHuggingFaceInParallel,
    )
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HuggingFace Hub imports (with lightweight fallback stubs)
# ---------------------------------------------------------------------------
try:
    from huggingface_hub import HfApi, CommitInfo, login  # type: ignore
    from huggingface_hub.errors import HfHubHTTPError  # type: ignore
except (ImportError, ModuleNotFoundError):

    def login(*_args: Any, **_kwargs: Any) -> None:  # type: ignore[misc]
        """No-op login stub when huggingface_hub is unavailable."""
        return None

    class CommitInfo:  # type: ignore[no-redef]
        """Stub CommitInfo when huggingface_hub is unavailable."""
        pass

    class HfHubHTTPError(Exception):  # type: ignore[no-redef]
        """Stub HfHubHTTPError when huggingface_hub is unavailable."""
        def __init__(self, *args: Any, response: Any = None, **kwargs: Any) -> None:
            super().__init__(*args)
            self.response = response

    class HfApi:  # type: ignore[no-redef]
        """Stub HfApi that returns empty/no-op results when huggingface_hub is unavailable."""
        def list_repo_files(self, *args: Any, **kwargs: Any) -> list[str]:
            """Return empty file list."""
            return []

        def upload_file(self, *args: Any, **kwargs: Any) -> cf.Future:
            """No-op upload returning an immediately resolved future."""
            fut: cf.Future = cf.Future()
            fut.set_result(None)
            return fut

        def upload_folder(self, *args: Any, **kwargs: Any) -> cf.Future:
            """No-op folder upload returning an immediately resolved future."""
            fut: cf.Future = cf.Future()
            fut.set_result(None)
            return fut

try:
    import tqdm  # type: ignore
except (ImportError, ModuleNotFoundError):

    class _TqdmNoOp:  # pragma: no cover
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "_TqdmNoOp":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def update(self, n: int = 1) -> None:
            return None

    class _TqdmModule:  # pragma: no cover
        tqdm = _TqdmNoOp

    tqdm = _TqdmModule()  # type: ignore[assignment]

try:
    from ._utils.configs import Configs  # type: ignore[import-untyped]
except (ImportError, ModuleNotFoundError, ValueError):
    # _utils.configs is optional; Configs is only needed when the full
    # municipal-law-database-scrapers package is installed.
    Configs = Any  # type: ignore[misc,assignment]


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Token bucket rate limiter for API requests.

    Implements a token bucket algorithm to limit the rate of API requests.
    Ensures that requests are made at a rate that doesn't exceed the
    specified limit.

    Attributes:
        request_limit_per_hour (int): Maximum requests allowed per hour.
        tokens (float): Current number of tokens in the bucket.
        token_rate (float): Rate at which tokens are replenished (per second).
        last_update_time (float): Timestamp of the last token update.
        mutex (threading.Lock): Lock for thread-safe operations.
    """

    def __init__(self, request_limit_per_hour: int = 300) -> None:
        """Initialize the rate limiter.

        Args:
            request_limit_per_hour: Maximum requests allowed per hour.
        """
        self.request_limit_per_hour = request_limit_per_hour
        self.tokens: float = float(request_limit_per_hour)  # Start full
        self.token_rate: float = request_limit_per_hour / 3600.0  # tokens/s
        self.last_update_time: float = time.time()
        self.mutex = threading.Lock()

    def _update_tokens(self) -> None:
        """Update token count based on elapsed time."""
        current_time = time.time()
        time_diff = current_time - self.last_update_time
        new_tokens = time_diff * self.token_rate
        with self.mutex:
            self.tokens = min(float(self.request_limit_per_hour), self.tokens + new_tokens)
            self.last_update_time = current_time

    def wait_for_token(self, tokens: int = 1) -> float:
        """Wait until the specified number of tokens are available, then consume them.

        Args:
            tokens: Number of tokens to consume.

        Returns:
            Time waited in seconds.
        """
        start_wait = time.time()
        while True:
            self._update_tokens()
            with self.mutex:
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return time.time() - start_wait
            needed_tokens = tokens - self.tokens
            if needed_tokens > 0:
                sleep_time = needed_tokens / self.token_rate
                time.sleep(min(sleep_time, 1.0))
            else:
                time.sleep(0.1)

    def get_current_rate(self) -> float:
        """Return the current token count expressed in tokens per hour."""
        with self.mutex:
            return self.tokens * (3600.0 / self.token_rate)

    def reset(self) -> None:
        """Reset the rate limiter to its initial state."""
        with self.mutex:
            self.tokens = float(self.request_limit_per_hour)
            self.last_update_time = time.time()


# ---------------------------------------------------------------------------
# UploadToHuggingFaceInParallel
# ---------------------------------------------------------------------------

class UploadToHuggingFaceInParallel:
    """Upload files to HuggingFace in parallel with rate limiting.

    Handles uploading files to HuggingFace repositories while respecting
    API rate limits. Uses :class:`RateLimiter` to enforce the limit.

    Attributes:
        configs: Configuration object.
        resources (Optional[dict]): Additional resources.
        repo_id (str): HuggingFace repository ID.
        sql_input (Path): Input path for SQL data.
        rate_limiter (RateLimiter): Rate limiter for API requests.
        upload_count (int): Count of successful uploads.
        failed_count (int): Count of failed uploads.
        retry_count (int): Count of retried uploads.
        repo_type (str): Repository type (dataset, model, space).
        api (HfApi): HuggingFace API client.
    """

    def __init__(
        self,
        configs: Any = None,
        resources: Optional[dict] = None,
        meta: Optional[dict] = None,
    ) -> None:
        """Initialize the uploader.

        Args:
            configs: Configuration object with REPO_ID, token path, etc.
            resources: Optional extra resources dict.
            meta: Optional metadata dict.
        """
        self.configs = configs
        self.resources = resources if resources is not None else {}
        self.meta = meta if meta is not None else {}
        self.upload_count = 0
        self.failed_count = 0
        self.retry_count = 0
        self.repo_type = "dataset"

        if configs is not None:
            self.repo_id: str = getattr(configs, "REPO_ID", "")
            self.sql_input = Path(getattr(getattr(configs, "paths", None), "INPUT_FROM_SQL", ".") or ".")
            token_path = getattr(configs, "HUGGING_FACE_USER_ACCESS_TOKEN", None)
            try:
                login(token=token_path)
            except Exception:  # noqa: BLE001
                pass
            rate_limit = getattr(configs, "REQUEST_LIMIT_PER_HOUR", 300)
            self.rate_limiter = RateLimiter(request_limit_per_hour=rate_limit)
            self.api = HfApi()
        else:
            self.repo_id = ""
            self.sql_input = Path(".")
            self.rate_limiter = RateLimiter()
            self.api = HfApi()

    def _get_processed_file_info(self) -> set[str]:
        """Return the set of file names already present in the remote repo."""
        try:
            file_info_set: set[str] = set()
            for file_path_str in self.api.list_repo_files(
                repo_id=self.repo_id, repo_type=self.repo_type
            ):
                file_info_set.add(Path(file_path_str).name)
            logger.info("Found %d files in the repository %s.", len(file_info_set), self.repo_id)
            return file_info_set
        except Exception as e:
            logger.error("Error getting processed files: %s", e)
            raise

    def _get_folders_to_upload(self, data_dir: Path, file_info_set: set[str]) -> list[Path]:
        """Return the list of local folders that still need to be uploaded.

        Args:
            data_dir: Directory containing the data.
            file_info_set: Set of file names already in the repository.

        Returns:
            Folders whose parquet files have not yet been uploaded.
        """
        folders_to_upload: list[Path] = []
        for dir_path in data_dir.iterdir():
            if not dir_path.is_dir():
                continue
            all_files_exist = all(
                f.name in file_info_set for f in dir_path.glob("**/*.parquet")
            )
            if not all_files_exist:
                folders_to_upload.append(dir_path)
        return folders_to_upload

    def _upload_file(self, *, file_path: Path, path_in_repo: str) -> cf.Future:
        """Upload a single file to HuggingFace."""
        _path_in_repo = Path(path_in_repo) / file_path.name
        return self.api.upload_file(  # type: ignore[call-arg]
            path_or_fileobj=file_path,
            path_in_repo=str(_path_in_repo),
            repo_id=self.repo_id,
            repo_type=self.repo_type,
        )

    def _upload_folder(self, *, folder_path: Path, path_in_repo: str) -> cf.Future:
        """Upload an entire folder to HuggingFace."""
        return self.api.upload_folder(  # type: ignore[call-arg]
            folder_path=str(folder_path),
            path_in_repo=path_in_repo,
            repo_id=self.repo_id,
            repo_type=self.repo_type,
        )

    async def upload_to_hugging_face_in_parallel(
        self,
        output_dir: Optional[Path] = None,
        target_dir_name: str = "data",
        max_concurrency: int = 5,
        retry_limit: int = 3,
    ) -> dict:
        """Upload parquet files from *output_dir* to HuggingFace in parallel.

        Args:
            output_dir: Local directory containing the data folders to upload.
            target_dir_name: Name of the target directory in the HF repository.
            max_concurrency: Maximum number of concurrent uploads.
            retry_limit: Maximum number of retries per failed upload.

        Returns:
            Dict with keys ``uploaded``, ``failed``, ``retried``.
        """
        if output_dir is None:
            output_dir = self.sql_input

        try:
            file_info_set = self._get_processed_file_info()
        except Exception as e:
            logger.error("Failed to retrieve file info from repo: %s", e)
            return {"uploaded": 0, "failed": 1, "retried": 0}

        folders_to_upload = self._get_folders_to_upload(output_dir, file_info_set)
        if not folders_to_upload:
            logger.info("All folders already uploaded to %s.", self.repo_id)
            return {"uploaded": 0, "failed": 0, "retried": 0}

        logger.info("Uploading %d folders to %s.", len(folders_to_upload), self.repo_id)

        sem = None
        try:
            import anyio  # type: ignore
            sem = anyio.Semaphore(max_concurrency)
        except (ImportError, ModuleNotFoundError):
            sem = None

        with cf.ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            futures: list[tuple[Path, cf.Future]] = []
            for folder in folders_to_upload:
                self.rate_limiter.wait_for_token()
                path_in_repo = f"{target_dir_name}/{folder.name}"
                fut = executor.submit(
                    self._upload_folder_sync,
                    folder_path=folder,
                    path_in_repo=path_in_repo,
                    retry_limit=retry_limit,
                )
                futures.append((folder, fut))

            for folder, fut in futures:
                try:
                    result = fut.result()
                    if result:
                        self.upload_count += 1
                    else:
                        self.failed_count += 1
                except Exception as e:
                    logger.error("Upload failed for %s: %s", folder.name, e)
                    self.failed_count += 1

        if self.failed_count > 0:
            logger.error(
                "Failed to upload %d folders to %s. Check logs for details.",
                self.failed_count, self.repo_id,
            )
        return {"uploaded": self.upload_count, "failed": self.failed_count, "retried": self.retry_count}

    def _upload_folder_sync(
        self,
        *,
        folder_path: Path,
        path_in_repo: str,
        retry_limit: int = 3,
    ) -> bool:
        """Synchronously upload a folder with retry logic.

        Args:
            folder_path: Local folder to upload.
            path_in_repo: Target path in the HF repository.
            retry_limit: Maximum retries on transient errors.

        Returns:
            ``True`` on success, ``False`` on exhausted retries.
        """
        for attempt in range(retry_limit + 1):
            try:
                fut = self._upload_folder(folder_path=folder_path, path_in_repo=path_in_repo)
                if isinstance(fut, cf.Future):
                    fut.result()
                return True
            except HfHubHTTPError as e:
                # Rate limit (429) or server error (5xx) — retry with back-off
                status = getattr(getattr(e, "response", None), "status_code", 0)
                if status in (429, 500, 502, 503) and attempt < retry_limit:
                    wait = 2 ** attempt
                    logger.warning(
                        "HTTP %s uploading %s, retrying in %ss (attempt %d/%d).",
                        status, folder_path.name, wait, attempt + 1, retry_limit,
                    )
                    time.sleep(wait)
                    self.retry_count += 1
                else:
                    logger.error("Upload failed for %s after %d attempt(s): %s", folder_path.name, attempt + 1, e)
                    return False
            except Exception as e:
                logger.error("Unexpected error uploading %s: %s", folder_path.name, e)
                return False
        return False


__all__ = [
    "RateLimiter",
    "UploadToHuggingFaceInParallel",
    "HfApi",
    "CommitInfo",
    "HfHubHTTPError",
    "login",
]
