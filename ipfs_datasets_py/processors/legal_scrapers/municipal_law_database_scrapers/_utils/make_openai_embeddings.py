# !/usr/bin/env python3
from __future__ import annotations
import argparse
import anyio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None
from pydantic import BaseModel
import hashlib

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None

try:
    from transformers import AutoTokenizer
except ImportError:  # pragma: no cover
    AutoTokenizer = None


try:
    from ipfs_datasets_py.data_transformation.ipfs_formats.ipfs_multiformats import get_cid
except Exception:  # pragma: no cover
    try:
        from ipfs_datasets_py.processors.ipfs.formats.ipfs_multiformats import get_cid
    except Exception:  # pragma: no cover
        def get_cid(file_data):
            data = file_data if isinstance(file_data, bytes) else str(file_data).encode("utf-8")
            return f"sha256-{hashlib.sha256(data).hexdigest()}"
from ipfs_datasets_py import embeddings_router
from .configs import configs


logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    # Avoid import-time side effects; configure handlers only for script execution.
    if getattr(_configure_logging, "_configured", False):
        return
    setattr(_configure_logging, "_configured", True)

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    file_handler = logging.FileHandler('embedding.log')
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def get_gnis_from_file_name(filename: str, ending: Optional[str] = None) -> str:
    """
    Extract the GNIS identifier from a filename.
    
    Args:
        filename (str): The filename to extract GNIS from
        
    Returns:
        str: The extracted GNIS identifier, or empty string if not found
    """
    if not filename:
        return ""

    if ending:
        if not filename.endswith(ending):
            logger.warning(f"Filename does not end with {ending}: {filename}")
            return ""

    try:
        # Extract GNIS from patterns like "123456.jsonl" or "123456_something.jsonl"
        return filename.split("_")[0]
    except (IndexError, AttributeError):
        logger.warning(f"Could not extract GNIS from filename: {filename}")
        return ""


def _resolve_input_dir(input_dir: Optional[str]) -> Path:
    """Resolve local or fish:// input dir into a local filesystem Path."""

    if not input_dir:
        # Keep a safe local default for CLI execution paths that do not rely on
        # the broader municipal scraper configuration bundle.
        return Path.cwd()

    value = str(input_dir).strip()
    if value.startswith("fish://"):
        parsed = urlparse(value)
        if not parsed.path:
            raise ValueError(f"Invalid fish URI (missing path): {value}")
        return Path(parsed.path)

    return Path(value).expanduser().resolve()


def _derive_output_parquet_path(input_path: Path) -> Path:
    """Derive an embeddings parquet output path from an input parquet path."""

    stem = input_path.stem
    if stem.endswith("_html"):
        out_stem = f"{stem[:-5]}_embeddings"
    elif stem.endswith("_embedding") or stem.endswith("_embeddings"):
        out_stem = stem
    else:
        out_stem = f"{stem}_embeddings"
    return input_path.with_name(f"{out_stem}.parquet")


class RouterEmbedding:
    """Embeddings pipeline backed by `ipfs_datasets_py.embeddings_router`.

    This replaces the previous OpenAI Files/Batches workflow. It reads parquet inputs,
    prepares text, chunks overly large inputs, and generates embeddings in batches via
    `embeddings_router.embed_texts_batched`.
    """

    def __init__(
        self,
        *,
        model: str = "thenlper/gte-small",
        device: str = "cuda",
        provider: Optional[str] = "local_adapter",
        batch_size: int = 128,
        max_tokens_per_chunk: int = 480,
    ) -> None:
        self.model = model
        self.device = str(device or "cuda")
        self.provider = provider
        self.batch_size = int(batch_size)
        self.max_tokens_per_chunk = int(max_tokens_per_chunk)

        self.total_token_count = 0

        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.max_tokens_per_chunk <= 0:
            raise ValueError("max_tokens_per_chunk must be positive")

        # Exclude identifier-like fields from embedding text to improve retrieval quality.
        self._excluded_text_columns = {
            "cid",
            "embedding_cid",
            "id",
            "_id",
            "uuid",
            "gnis",
            "text_chunk_order",
            "chunk_id",
            "row_id",
        }

        self._encoding = None
        self._hf_tokenizer = None
        if tiktoken is not None:
            try:
                self._encoding = tiktoken.encoding_for_model(self.model)
            except Exception:
                self._encoding = None

        if self._encoding is None and AutoTokenizer is not None:
            try:
                self._hf_tokenizer = AutoTokenizer.from_pretrained(self.model)
            except Exception:
                self._hf_tokenizer = None

    def get_token_count(self, text: str) -> int:
        if self._encoding is None:
            if self._hf_tokenizer is not None:
                return len(self._hf_tokenizer.encode(text, add_special_tokens=False))
            # Approximate tokens by whitespace pieces when tokenizer is unavailable.
            return len(text.split())
        return len(self._encoding.encode(text, allowed_special="all"))

    def chunk_text_by_tokens(self, text: str) -> list[str]:
        if self._encoding is None:
            if self._hf_tokenizer is not None:
                token_ids = self._hf_tokenizer.encode(text, add_special_tokens=False)
                chunks: list[str] = []
                for start in range(0, len(token_ids), self.max_tokens_per_chunk):
                    chunk_ids = token_ids[start : start + self.max_tokens_per_chunk]
                    chunks.append(self._hf_tokenizer.decode(chunk_ids, skip_special_tokens=True))
                return chunks
            # Conservative fallback: chunk by whitespace-delimited tokens.
            words = text.split()
            step = max(1, self.max_tokens_per_chunk)
            return [" ".join(words[i : i + step]) for i in range(0, len(words), step)]

        token_ids = self._encoding.encode(text, allowed_special="all")
        chunks: list[str] = []
        for start in range(0, len(token_ids), self.max_tokens_per_chunk):
            chunk_ids = token_ids[start : start + self.max_tokens_per_chunk]
            chunks.append(self._encoding.decode(chunk_ids))
        return chunks

    @staticmethod
    def _prepare_html_for_embedding(html_title: str, html: str) -> str:
        """
        Prepare HTML content for embedding by extracting text and removing tags.
        
        Args:
            html_title (str): The title of the HTML content.
            html (str): The HTML content to process.
            
        Returns:
            str: The text content extracted from the HTML.
        """
        raw_text_list = []
        for _html in [html_title, html]:
            if BeautifulSoup is None:
                text = re.sub(r"<[^>]+>", " ", str(_html))
            else:
                soup = BeautifulSoup(_html, "html.parser")
                # Find elements with either chunk-content or chunk-title class
                element = soup.find(class_="chunk-content")
                if not element:
                    element = soup.find(class_="chunk-title")

                # If no specific elements found, use the whole soup
                if element:
                    text = element.get_text(separator=" ")
                else:
                    text = soup.get_text(separator=" ")

            raw_text_list.append(text)

        # Make sure the raw text in the raw_text_list is not empty
        if not raw_text_list:
            raw_text = ""
        else:
            raw_text = " ".join(raw_text_list)

        # Clean the text by removing extra spaces and newlines

        # Remove newlines
        text = raw_text.replace('\n', ' ')
        # Remove extra spaces
        text = re.sub(r'\s+', ' ', text)
        # Strip leading and trailing spaces
        text = text.strip()

        return text

    def _prepare_row_for_embedding(self, row: dict) -> str:
        """Create embedding text from semantic content fields only.

        This intentionally excludes IDs, URLs, JSON blobs, and provenance fields
        to avoid polluting embeddings with non-semantic metadata.
        """

        html_title = str(row.get("html_title", "") or "")
        html = str(row.get("html", "") or "")
        if html_title or html:
            return self._prepare_html_for_embedding(html_title, html)

        preferred_fields = [
            "text",
            "content",
            "body",
            "section_text",
            "law_text",
            "full_text",
            "excerpt",
            "clause_text",
            "provision_text",
        ]

        context_fields = [
            "law_name",
            "title_name",
            "title",
            "heading",
            "description",
            "summary",
            "name",
        ]

        non_semantic_key_markers = {
            "cid",
            "id",
            "url",
            "json",
            "source",
            "file",
            "path",
            "date",
            "time",
            "timestamp",
            "number",
            "index",
            "warning",
            "hash",
            "uuid",
            "checksum",
        }

        semantic_key_markers = {
            "text",
            "content",
            "body",
            "summary",
            "description",
            "title",
            "heading",
            "name",
            "clause",
            "provision",
            "section",
            "law",
        }

        def _looks_semantic_value(value: object) -> bool:
            s = str(value).strip()
            if len(s) < 20:
                return False
            if s.startswith("{") or s.startswith("["):
                return False
            words = s.split()
            if len(words) < 3:
                return False
            letters = sum(ch.isalpha() for ch in s)
            ratio = letters / max(1, len(s))
            return ratio >= 0.35

        parts: list[str] = []
        for field in preferred_fields:
            value = row.get(field)
            if value is None:
                continue
            value_s = str(value).strip()
            if value_s:
                parts.append(value_s)

        for field in context_fields:
            value = row.get(field)
            if value is None:
                continue
            value_s = str(value).strip()
            if value_s:
                parts.append(value_s)

        if not parts:
            for key, value in row.items():
                key_l = str(key).strip().lower()
                if key_l in self._excluded_text_columns:
                    continue
                if any(marker in key_l for marker in non_semantic_key_markers):
                    continue
                if not any(marker in key_l for marker in semantic_key_markers):
                    continue
                if value is None:
                    continue
                if not _looks_semantic_value(value):
                    continue
                parts.append(str(value).strip())

        text = " ".join(parts)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    async def embed_parquet_to_parquet(
        self,
        *,
        html_parquet_path: Path,
        output_parquet_path: Path,
        max_rows: Optional[int] = None,
    ) -> None:
        if pd is None:
            raise RuntimeError("pandas is required for parquet embedding. Install pandas/pyarrow first.")

        gnis = str(html_parquet_path.stem.split("_")[0])
        if not gnis.isdigit():
            logger.warning(f"GNIS '{gnis}' does not contain only numeric values; proceeding with best-effort row IDs.")

        df = pd.read_parquet(html_parquet_path)

        pending_records: list[tuple[str, str, int, str]] = []
        pending_texts: list[str] = []
        out_rows: list[dict] = []

        def _flush_pending() -> None:
            if not pending_texts:
                return

            embeddings = embeddings_router.embed_texts_batched(
                pending_texts,
                batch_size=self.batch_size,
                model_name=self.model,
                device=self.device,
                provider=self.provider,
            )
            if len(embeddings) != len(pending_records):
                raise RuntimeError(f"Embedding count mismatch: {len(embeddings)} != {len(pending_records)}")

            for (gnis_val, cid_val, chunk_order, _), vec in zip(pending_records, embeddings):
                embedding_cid = get_cid(f"{json.dumps(vec)}{cid_val}")
                out_rows.append(
                    {
                        "embedding_cid": embedding_cid,
                        "gnis": gnis_val,
                        "cid": cid_val,
                        "text_chunk_order": int(chunk_order),
                        "embedding": vec,
                    }
                )

            pending_records.clear()
            pending_texts.clear()

        for idx, row in enumerate(df.to_dict(orient="records")):
            if max_rows is not None and idx >= max_rows:
                break
            text = self._prepare_row_for_embedding(row)
            cid = str(row.get("cid", "") or "").strip()
            if not cid:
                cid = f"row-{idx + 1}"
            if not text:
                continue

            likely_long = len(text) > (self.max_tokens_per_chunk * 6)
            token_count = self.get_token_count(text) if likely_long else max(1, len(text.split()))
            self.total_token_count += token_count

            if likely_long and token_count > self.max_tokens_per_chunk:
                chunks = self.chunk_text_by_tokens(text)
                for idx, chunk in enumerate(chunks, start=1):
                    pending_records.append((gnis, cid, idx, chunk))
                    pending_texts.append(chunk)
            else:
                pending_records.append((gnis, cid, 1, text))
                pending_texts.append(text)

            if len(pending_texts) >= self.batch_size:
                _flush_pending()

        _flush_pending()

        if not out_rows:
            logger.info(f"No embeddable rows found for {html_parquet_path.name}")
            return

        logger.info(
            f"Embedded {len(out_rows)} text chunks for GNIS {gnis} "
            f"(provider={self.provider or 'default'}, model={self.model}, device={self.device})"
        )

        out_df = pd.DataFrame(out_rows, columns=["embedding_cid", "gnis", "cid", "text_chunk_order", "embedding"])
        out_df.to_parquet(output_parquet_path, compression="gzip")
        logger.info(f"Wrote embeddings parquet: {output_parquet_path}")


# Backwards-compatible alias: older utilities import `OpenAIEmbedding`.
# The implementation is now router-backed and does not depend on the OpenAI SDK.
OpenAIEmbedding = RouterEmbedding

async def main(input_files: Optional[list[Path]] = None) -> int:
    return await run_embedding_pipeline(input_files=input_files)


async def run_embedding_pipeline(
    input_files: Optional[list[Path]] = None,
    *,
    input_dir: Optional[Path] = None,
    file_glob: str = "*_html.parquet",
    recursive: bool = False,
    model: str = "thenlper/gte-small",
    device: str = "cuda",
    provider: Optional[str] = "local_adapter",
    skip_existing: bool = True,
    max_rows: Optional[int] = None,
    max_tokens_per_chunk: int = 480,
) -> int:
    logger = logging.getLogger(__name__)

    # Update to include the "american_law" subdirectory by default.
    _configure_logging()
    if input_dir is not None:
        resolved_input_dir = input_dir
    elif input_files is None:
        resolved_input_dir = configs.paths.ROOT_DIR / "input_from_sql" / "american_law" / "data"
    else:
        # Explicit input files do not require default directory configuration.
        resolved_input_dir = Path.cwd()

    logger.info(f"Looking for files in: {resolved_input_dir}")
    
    # Check if directory exists
    if not resolved_input_dir.exists():
        logger.error(f"Directory does not exist: {resolved_input_dir}")
        return 1

    # Discover input parquet files if none were explicitly provided.
    if input_files is None:
        globber = resolved_input_dir.rglob if recursive else resolved_input_dir.glob
        html_files = [p for p in globber(file_glob) if p.is_file()]

        # Backward-compatible fallback for non-HTML parquet datasets.
        if not html_files and file_glob == "*_html.parquet":
            html_files = [
                p
                for p in globber("*.parquet")
                if p.is_file() and not p.stem.endswith("_embedding") and not p.stem.endswith("_embeddings")
            ]
    else:
        html_files = input_files

    # Exit if no files found
    if not html_files:
        logger.info("No HTML parquet files found. Exiting.")
        return 1
    logger.info(f"Found {len(html_files)} HTML parquet files.")

    embedder = RouterEmbedding(
        model=model,
        device=device,
        provider=provider,
        max_tokens_per_chunk=max_tokens_per_chunk,
    )
    logger.info("Starting embedding generation via embeddings_router.")
    
    try:
        processed_count = 0
        error_count = 0

        # Process all files
        for html_parquet_path in html_files:
            try:
                embedding_path = _derive_output_parquet_path(html_parquet_path)

                if skip_existing and embedding_path.exists():
                    logger.info(f"Embeddings already exist for {html_parquet_path.name}; skipping.")
                    continue

                logger.info(f"Embedding {html_parquet_path.name}")
                await embedder.embed_parquet_to_parquet(
                    html_parquet_path=html_parquet_path,
                    output_parquet_path=embedding_path,
                    max_rows=max_rows,
                )
                processed_count += 1
            except Exception as e:
                logger.error(f"Error processing {html_parquet_path}: {e}")
                error_count += 1
                continue
        logger.info(f"Embedding process completed. Processed: {processed_count}, Errors: {error_count}")

    except Exception as e:
        logger.error(f"Error in main processing loop: {e}")
        return 1

    logger.info("Embedding processing finished")
    return 0


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate parquet embeddings via embeddings_router")
    parser.add_argument(
        "--input-dir",
        help="Input parquet directory (supports local paths and fish://user@host/path URIs)",
    )
    parser.add_argument(
        "--glob",
        default="*_html.parquet",
        help="Glob pattern for input parquet files (default: *_html.parquet)",
    )
    parser.add_argument("--recursive", action="store_true", help="Recursively search for parquet files")
    parser.add_argument(
        "--model",
        default="thenlper/gte-small",
        help="Embedding model passed to embeddings_router",
    )
    parser.add_argument(
        "--device",
        default="cuda",
        help="Embedding device (default: cuda)",
    )
    parser.add_argument(
        "--max-tokens-per-chunk",
        type=int,
        default=480,
        help="Maximum token-length per text chunk before splitting",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Optional cap on number of parquet rows to process per file",
    )
    parser.add_argument(
        "--provider",
        default="local_adapter",
        help="Embeddings provider (default: local_adapter for local CUDA/HF)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Recompute embeddings even when output parquet already exists",
    )
    parser.add_argument(
        "--input-file",
        action="append",
        default=[],
        help="Specific parquet file(s) to process; can be used multiple times",
    )
    return parser.parse_args(argv)


async def _run_from_cli(args: argparse.Namespace) -> int:
    input_files = [Path(p).expanduser().resolve() for p in (args.input_file or [])]
    input_dir = _resolve_input_dir(args.input_dir) if args.input_dir or not input_files else None
    return await run_embedding_pipeline(
        input_files=input_files or None,
        input_dir=input_dir,
        file_glob=args.glob,
        recursive=bool(args.recursive),
        model=str(args.model),
        device=str(args.device),
        provider=args.provider,
        skip_existing=not bool(args.overwrite),
        max_rows=args.max_rows,
        max_tokens_per_chunk=int(args.max_tokens_per_chunk),
    )

if __name__ == "__main__":
    cli_args = _parse_args()
    sys.exit(anyio.run(_run_from_cli, cli_args))
