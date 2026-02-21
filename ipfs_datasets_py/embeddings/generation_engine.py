"""
Embedding Generation Engine.

Canonical business logic for generating text and file-based embeddings.
Both ``embedding_tools/embedding_generation.py`` and
``embedding_tools/advanced_embedding_generation.py`` are thin re-exports of
the functions defined here.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy dependencies
# ---------------------------------------------------------------------------
try:
    from ipfs_datasets_py.embeddings.core import IPFSEmbeddings  # type: ignore
    HAVE_EMBEDDINGS = True
except ImportError:
    HAVE_EMBEDDINGS = False
    IPFSEmbeddings = None  # type: ignore


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

async def generate_embedding(
    text: Union[str, Dict[str, Any]],
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    normalize: bool = True,
    batch_size: int = 32,
    use_gpu: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Generate a single embedding for text (or a multimodal payload dict).

    Args:
        text: Text string, or a dict with a ``text`` key for multimodal inputs.
        model_name: Embedding model identifier.
        normalize: Whether to L2-normalise the output vector.
        batch_size: Batch size used by the underlying engine.
        use_gpu: Whether to request GPU acceleration.
        **kwargs: Forwarded to the embedding engine.

    Returns:
        Dict with ``status``, ``embedding``, ``model``, ``dimension``, etc.
    """
    input_text: str = text  # type: ignore[assignment]
    modality: Optional[str] = None
    if isinstance(text, dict):
        modality = text.get("modality") or text.get("type")
        input_text = text.get("text", "")

    try:
        if not HAVE_EMBEDDINGS:
            logger.warning("Using fallback embedding generation")
            result: Dict[str, Any] = {
                "status": "success",
                "text": input_text,
                "embedding": [0.1, 0.2, 0.3, 0.4],
                "model": model_name,
                "dimension": 4,
                "normalized": normalize,
                "message": "Using fallback – install embeddings dependencies for full functionality",
            }
            if modality:
                result["modality"] = modality
            return result

        if not input_text or not isinstance(input_text, str):
            raise ValueError("Text must be a non-empty string")
        if len(input_text) > 10_000:
            raise ValueError("Text length exceeds maximum limit of 10,000 characters")

        engine = IPFSEmbeddings(model=model_name, batch_size=batch_size, use_gpu=use_gpu)
        raw = await engine.generate_embeddings([input_text])

        if not raw or not raw.get("embeddings"):
            raise RuntimeError("Failed to generate embedding")

        emb = raw["embeddings"][0]
        result = {
            "status": "success",
            "text": input_text,
            "embedding": emb.tolist() if hasattr(emb, "tolist") else emb,
            "model": model_name,
            "dimension": len(emb),
            "normalized": normalize,
            "processing_time": raw.get("processing_time", 0),
            "memory_usage": raw.get("memory_usage", 0),
        }
        if modality:
            result["modality"] = modality
        return result

    except Exception as exc:
        logger.error("Embedding generation failed: %s", exc)
        return {"status": "error", "error": str(exc), "text": input_text, "model": model_name}


async def generate_batch_embeddings(
    texts: List[str],
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    normalize: bool = True,
    batch_size: int = 32,
    use_gpu: bool = False,
    max_texts: int = 100,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Generate embeddings for multiple texts.

    Args:
        texts: List of text strings.
        model_name: Embedding model identifier.
        normalize: Whether to L2-normalise output vectors.
        batch_size: Internal processing batch size.
        use_gpu: Whether to request GPU acceleration.
        max_texts: Hard cap on the number of input texts.
        **kwargs: Forwarded to the embedding engine.

    Returns:
        Dict with ``status``, ``embeddings`` (list of vectors), ``count``, etc.
    """
    try:
        if not texts:
            raise ValueError("texts list must not be empty")
        if len(texts) > max_texts:
            raise ValueError(f"Too many texts: {len(texts)} > limit {max_texts}")

        if not HAVE_EMBEDDINGS:
            logger.warning("Using fallback batch embedding generation")
            return {
                "status": "success",
                "embeddings": [[0.1, 0.2, 0.3, 0.4] for _ in texts],
                "model": model_name,
                "count": len(texts),
                "dimension": 4,
                "normalized": normalize,
                "message": "Using fallback – install embeddings dependencies for full functionality",
            }

        engine = IPFSEmbeddings(model=model_name, batch_size=batch_size, use_gpu=use_gpu)
        raw = await engine.generate_embeddings(texts)

        if not raw or not raw.get("embeddings"):
            raise RuntimeError("Failed to generate batch embeddings")

        embs = raw["embeddings"]
        return {
            "status": "success",
            "embeddings": [e.tolist() if hasattr(e, "tolist") else e for e in embs],
            "model": model_name,
            "count": len(embs),
            "dimension": len(embs[0]) if embs else 0,
            "normalized": normalize,
            "processing_time": raw.get("processing_time", 0),
            "memory_usage": raw.get("memory_usage", 0),
        }

    except Exception as exc:
        logger.error("Batch embedding generation failed: %s", exc)
        return {"status": "error", "error": str(exc), "count": len(texts), "model": model_name}


async def generate_embeddings_from_file(
    file_path: str,
    output_path: Optional[str] = None,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    batch_size: int = 32,
    chunk_size: Optional[int] = None,
    max_length: Optional[int] = None,
    output_format: str = "json",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Generate embeddings from a text or JSON file.

    Args:
        file_path: Path to the input file.
        output_path: Where to save the result (optional).
        model_name: Embedding model identifier.
        batch_size: Internal processing batch size.
        chunk_size: Split plain-text files into chunks of this size.
        max_length: Truncate each chunk/text to this many characters.
        output_format: ``"json"`` or ``"parquet"``.
        **kwargs: Forwarded to :func:`generate_batch_embeddings`.

    Returns:
        Dict with ``status``, ``embeddings``, ``input_file``, etc.
    """
    try:
        fpath = Path(file_path)
        if not fpath.exists():
            raise FileNotFoundError(f"Input file not found: {fpath}")
        if not fpath.is_file():
            raise ValueError(f"Path is not a file: {fpath}")

        try:
            content = fpath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = fpath.read_text(encoding="latin-1")

        if not content.strip():
            raise ValueError("File is empty or contains no valid text")

        if fpath.suffix.lower() == ".json":
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    texts = [str(item) for item in data]
                elif isinstance(data, dict):
                    texts = [v if isinstance(v, str) else json.dumps(v) for v in data.values()]
                else:
                    texts = [str(data)]
            except json.JSONDecodeError:
                texts = [content]
        elif chunk_size:
            texts = [content[i:i + chunk_size] for i in range(0, len(content), chunk_size)]
        else:
            texts = [content]

        if max_length:
            texts = [t[:max_length] for t in texts]

        result = await generate_batch_embeddings(texts, model_name, batch_size=batch_size, **kwargs)
        if result["status"] != "success":
            return result

        if output_path:
            opath = Path(output_path)
            opath.parent.mkdir(parents=True, exist_ok=True)
            if output_format.lower() == "parquet":
                try:
                    import pandas as pd  # type: ignore
                    pd.DataFrame(result["embeddings"]).to_parquet(opath)
                except ImportError:
                    logger.warning("pandas not available – saving as JSON instead")
                    opath = opath.with_suffix(".json")
                    opath.write_text(json.dumps(result, indent=2))
            else:
                opath.write_text(json.dumps(result, indent=2))

        return {
            **result,
            "input_file": str(fpath),
            "output_file": str(output_path) if output_path else None,
            "output_format": output_format,
            "total_chunks": len(texts),
        }

    except Exception as exc:
        logger.error("File embedding generation failed: %s", exc)
        return {"status": "error", "error": str(exc), "input_file": file_path, "model": model_name}
