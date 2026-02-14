# !/usr/bin/env python3
from __future__ import annotations
import anyio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional


from bs4 import BeautifulSoup
import pandas as pd
from pydantic import BaseModel

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None


from ipfs_datasets_py.data_transformation.ipfs_formats.ipfs_multiformats import get_cid
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


class RouterEmbedding:
    """Embeddings pipeline backed by `ipfs_datasets_py.embeddings_router`.

    This replaces the previous OpenAI Files/Batches workflow. It reads parquet inputs,
    prepares text, chunks overly large inputs, and generates embeddings in batches via
    `embeddings_router.embed_texts_batched`.
    """

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        provider: Optional[str] = None,
        batch_size: int = 128,
        max_tokens_per_chunk: int = 8192,
    ) -> None:
        self.model = model
        self.provider = provider
        self.batch_size = int(batch_size)
        self.max_tokens_per_chunk = int(max_tokens_per_chunk)

        self.total_token_count = 0

        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.max_tokens_per_chunk <= 0:
            raise ValueError("max_tokens_per_chunk must be positive")

        self._encoding = None
        if tiktoken is not None:
            try:
                self._encoding = tiktoken.encoding_for_model(self.model)
            except Exception:
                self._encoding = None

    def get_token_count(self, text: str) -> int:
        if self._encoding is None:
            return len(text)
        return len(self._encoding.encode(text, allowed_special="all"))

    def chunk_text_by_tokens(self, text: str) -> list[str]:
        if self._encoding is None:
            # Conservative fallback: chunk by characters.
            step = max(1, self.max_tokens_per_chunk)
            return [text[i : i + step] for i in range(0, len(text), step)]

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
    async def embed_parquet_to_parquet(self, *, html_parquet_path: Path, output_parquet_path: Path) -> None:
        gnis = str(html_parquet_path.stem.split("_")[0])
        if not gnis.isdigit():
            logger.warning(f"GNIS '{gnis}' does not contain only numeric values.")
            return

        df = pd.read_parquet(html_parquet_path)

        records: list[tuple[str, str, int, str]] = []
        texts: list[str] = []

        for row in df.itertuples():
            text = self._prepare_html_for_embedding(getattr(row, "html_title", ""), getattr(row, "html", ""))
            cid = str(getattr(row, "cid", ""))
            if not cid or not text:
                continue

            token_count = self.get_token_count(text)
            self.total_token_count += token_count

            if token_count > self.max_tokens_per_chunk:
                chunks = self.chunk_text_by_tokens(text)
                for idx, chunk in enumerate(chunks, start=1):
                    records.append((gnis, cid, idx, chunk))
                    texts.append(chunk)
            else:
                records.append((gnis, cid, 1, text))
                texts.append(text)

        if not texts:
            logger.info(f"No embeddable rows found for {html_parquet_path.name}")
            return

        logger.info(
            f"Embedding {len(texts)} text chunks for GNIS {gnis} "
            f"(provider={self.provider or 'default'}, model={self.model})"
        )

        def _run_embed() -> list[list[float]]:
            return embeddings_router.embed_texts_batched(
                texts,
                batch_size=self.batch_size,
                model_name=self.model,
                provider=self.provider,
            )

        embeddings = await anyio.to_thread.run_sync(_run_embed)
        if len(embeddings) != len(records):
            raise RuntimeError(f"Embedding count mismatch: {len(embeddings)} != {len(records)}")

        out_rows: list[dict] = []
        for (gnis_val, cid_val, chunk_order, _), vec in zip(records, embeddings):
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

        out_df = pd.DataFrame(out_rows, columns=["embedding_cid", "gnis", "cid", "text_chunk_order", "embedding"])
        out_df.to_parquet(output_parquet_path, compression="gzip")
        logger.info(f"Wrote embeddings parquet: {output_parquet_path}")


# Backwards-compatible alias: older utilities import `OpenAIEmbedding`.
# The implementation is now router-backed and does not depend on the OpenAI SDK.
OpenAIEmbedding = RouterEmbedding

async def main(input_files: Optional[list[Path]] = None) -> int:
    logger = logging.getLogger(__name__)

    # Update to include the "american_law" subdirectory
    _configure_logging()
    input_dir = configs.paths.ROOT_DIR / "input_from_sql" / "american_law" / "data"
    logger.info(f"Looking for files in: {input_dir}")
    
    # Check if directory exists
    if not input_dir.exists():
        logger.error(f"Directory does not exist: {input_dir}")
        return 1

    # Make one iteration through the loop to see what files are found
    html_files = list(input_dir.glob("*_html.parquet")) if input_files is None else input_files

    # Exit if no files found
    if not html_files:
        logger.info("No HTML parquet files found. Exiting.")
        return 1
    logger.info(f"Found {len(html_files)} HTML parquet files.")

    embedder = RouterEmbedding(model="text-embedding-3-small")
    logger.info("Starting embedding generation via embeddings_router.")
    
    try:
        processed_count = 0
        error_count = 0

        # Process all files
        for html_parquet_path in html_files:
            try:
                gnis_str = html_parquet_path.stem.split("_")[0]
                embedding_path = input_dir / f"{gnis_str}_embeddings.parquet"

                if embedding_path.exists():
                    logger.info(f"Embeddings already exist for {gnis_str}.")
                    continue

                logger.info(f"Embedding {html_parquet_path.name}")
                await embedder.embed_parquet_to_parquet(
                    html_parquet_path=html_parquet_path,
                    output_parquet_path=embedding_path,
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

if __name__ == "__main__":
    sys.exit(anyio.run(main()))
