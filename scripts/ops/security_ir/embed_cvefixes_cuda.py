#!/usr/bin/env python3
"""Build normalized CVEfixes retrieval embeddings on CUDA only.

The input is UTF-8 JSON Lines with one object per retrieval document::

    {"position":0,"node_cid":"b...","text_sha256":"...","text":"..."}

Positions must be contiguous and zero based, node CIDs must be unique, and
``text_sha256`` must commit to the exact UTF-8 encoding of ``text``.  The
worker never falls back to CPU inference.  It writes an NPY matrix followed
by a canonical JSON runtime receipt; both files are replaced atomically.

The receipt intentionally contains neither timestamps nor filesystem paths.
This keeps it deterministic for a fixed input, model, runtime, and output.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Callable, Final, Mapping, Sequence

import numpy as np


RECEIPT_SCHEMA_VERSION: Final = "cvefixes-cuda-embedding-receipt/v1"
INPUT_SCHEMA_VERSION: Final = "cvefixes-cuda-embedding-input/v1"
OUTPUT_FORMAT: Final = "numpy-npy/v1"
MAX_BATCH_SIZE: Final = 4096
UNIT_NORM_ATOL: Final = 5e-4

_INPUT_FIELDS: Final = frozenset(
    {"position", "node_cid", "text_sha256", "text"}
)
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
_CID_RE: Final = re.compile(r"b[a-z2-7]{58}")
_REVISION_RE: Final = re.compile(r"[0-9a-f]{40}")
_MODEL_ID_RE: Final = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}"
)


class CUDAEmbeddingError(RuntimeError):
    """Raised when input, CUDA execution, or output validation fails."""


@dataclass(frozen=True)
class InputRecord:
    """One validated, ordered embedding input."""

    position: int
    node_cid: str
    text_sha256: str
    text: str


@dataclass(frozen=True)
class LoadedInput:
    """Validated input records and their byte/semantic commitments."""

    records: tuple[InputRecord, ...]
    input_sha256: str
    ordered_records_sha256: str


@dataclass(frozen=True)
class EmbeddingDependencies:
    """Lazy runtime dependencies, injectable for CPU-hosted unit tests."""

    torch: Any
    sentence_transformers_version: str
    model_factory: Callable[..., Any]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _absolute_path(path: Path) -> Path:
    """Make a path absolute without following a final symlink."""

    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _paths_alias(left: Path, right: Path) -> bool:
    if left == right:
        return True
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError as exc:
        raise CUDAEmbeddingError("cannot compare input and output paths") from exc


def _reject_duplicate_keys(
    pairs: Sequence[tuple[str, Any]],
) -> Mapping[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CUDAEmbeddingError("duplicate JSON keys are forbidden")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    del value
    raise CUDAEmbeddingError("non-finite JSON constants are forbidden")


def _validate_model_id(value: str) -> str:
    model_id = str(value or "")
    if _MODEL_ID_RE.fullmatch(model_id) is None:
        raise CUDAEmbeddingError(
            "model-id must be a Hugging Face namespace/repository identifier"
        )
    return model_id


def _validate_revision(value: str) -> str:
    revision = str(value or "")
    if _REVISION_RE.fullmatch(revision) is None:
        raise CUDAEmbeddingError(
            "model-revision must be an exact lowercase 40-character commit SHA"
        )
    return revision


def _validate_batch_size(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_BATCH_SIZE:
        raise CUDAEmbeddingError(
            f"batch-size must be between 1 and {MAX_BATCH_SIZE}"
        )
    return value


def _load_input(path: Path) -> LoadedInput:
    """Read and validate the ordered JSONL input without importing Torch."""

    try:
        stat = path.stat()
    except OSError as exc:
        raise CUDAEmbeddingError("cannot inspect input JSONL") from exc
    if not path.is_file() or path.is_symlink():
        raise CUDAEmbeddingError("input JSONL must be a regular, non-symlink file")
    if stat.st_size <= 0:
        raise CUDAEmbeddingError("input JSONL is empty")

    raw_digest = hashlib.sha256()
    order_digest = hashlib.sha256()
    records: list[InputRecord] = []
    seen_node_cids: set[str] = set()
    try:
        with path.open("rb") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                raw_digest.update(raw_line)
                if not raw_line.strip():
                    raise CUDAEmbeddingError(
                        f"input line {line_number} is blank"
                    )
                try:
                    decoded = raw_line.decode("utf-8")
                    value = json.loads(
                        decoded,
                        object_pairs_hook=_reject_duplicate_keys,
                        parse_constant=_reject_json_constant,
                    )
                except CUDAEmbeddingError:
                    raise
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise CUDAEmbeddingError(
                        f"input line {line_number} is not valid UTF-8 JSON"
                    ) from exc
                if not isinstance(value, Mapping):
                    raise CUDAEmbeddingError(
                        f"input line {line_number} must be a JSON object"
                    )
                if frozenset(value) != _INPUT_FIELDS:
                    raise CUDAEmbeddingError(
                        f"input line {line_number} has unexpected fields"
                    )

                position = value["position"]
                node_cid = value["node_cid"]
                text_sha256 = value["text_sha256"]
                text = value["text"]
                expected_position = line_number - 1
                if type(position) is not int or position != expected_position:
                    raise CUDAEmbeddingError(
                        "input positions must be contiguous and zero based; "
                        f"line {line_number} expected {expected_position}"
                    )
                if (
                    not isinstance(node_cid, str)
                    or _CID_RE.fullmatch(node_cid) is None
                ):
                    raise CUDAEmbeddingError(
                        f"input line {line_number} has an invalid node CID"
                    )
                if node_cid in seen_node_cids:
                    raise CUDAEmbeddingError(
                        f"input line {line_number} repeats a node CID"
                    )
                if (
                    not isinstance(text_sha256, str)
                    or _SHA256_RE.fullmatch(text_sha256) is None
                ):
                    raise CUDAEmbeddingError(
                        f"input line {line_number} has an invalid text SHA-256"
                    )
                if not isinstance(text, str):
                    raise CUDAEmbeddingError(
                        f"input line {line_number} text must be a string"
                    )
                try:
                    text_bytes = text.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise CUDAEmbeddingError(
                        f"input line {line_number} text is not valid Unicode"
                    ) from exc
                if hashlib.sha256(text_bytes).hexdigest() != text_sha256:
                    raise CUDAEmbeddingError(
                        f"input line {line_number} text SHA-256 differs"
                    )

                record = InputRecord(
                    position=position,
                    node_cid=node_cid,
                    text_sha256=text_sha256,
                    text=text,
                )
                records.append(record)
                seen_node_cids.add(node_cid)
                order_digest.update(
                    _canonical_json(
                        {
                            "node_cid": node_cid,
                            "position": position,
                            "text_sha256": text_sha256,
                        }
                    )
                    + b"\n"
                )
    except CUDAEmbeddingError:
        raise
    except OSError as exc:
        raise CUDAEmbeddingError("cannot read input JSONL") from exc

    if not records:
        raise CUDAEmbeddingError("input JSONL contains no records")
    return LoadedInput(
        records=tuple(records),
        input_sha256=raw_digest.hexdigest(),
        ordered_records_sha256=order_digest.hexdigest(),
    )


def _load_dependencies() -> EmbeddingDependencies:
    try:
        import sentence_transformers
        import torch
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise CUDAEmbeddingError(
            "torch and sentence-transformers are required"
        ) from exc
    return EmbeddingDependencies(
        torch=torch,
        sentence_transformers_version=str(
            getattr(sentence_transformers, "__version__", "")
        ),
        model_factory=SentenceTransformer,
    )


def _configure_cuda(torch: Any) -> tuple[int, str, int, int]:
    """Fail closed unless a concrete CUDA device and runtime are available."""

    try:
        available = bool(torch.cuda.is_available())
    except Exception as exc:
        raise CUDAEmbeddingError("cannot query CUDA availability") from exc
    if not available:
        raise CUDAEmbeddingError(
            "CUDA is required; CPU embedding fallback is forbidden"
        )

    try:
        device_index = int(torch.cuda.current_device())
        gpu_name = str(torch.cuda.get_device_name(device_index)).strip()
        capability = torch.cuda.get_device_capability(device_index)
        major, minor = int(capability[0]), int(capability[1])
    except Exception as exc:
        raise CUDAEmbeddingError("cannot identify the active CUDA device") from exc
    if not gpu_name or major < 1 or minor < 0:
        raise CUDAEmbeddingError("active CUDA device metadata is invalid")

    try:
        torch.use_deterministic_algorithms(True)
        torch.set_grad_enabled(False)
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.allow_tf32 = False
        if hasattr(torch.backends, "cuda") and hasattr(
            torch.backends.cuda, "matmul"
        ):
            torch.backends.cuda.matmul.allow_tf32 = False
    except Exception as exc:
        raise CUDAEmbeddingError(
            "cannot enable deterministic CUDA execution"
        ) from exc
    return device_index, gpu_name, major, minor


def _validate_embeddings(
    value: Any,
    *,
    expected_count: int,
    expected_dimension: int | None,
) -> np.ndarray:
    try:
        embeddings = np.asarray(value)
    except Exception as exc:
        raise CUDAEmbeddingError(
            "embedding output cannot be converted to an array"
        ) from exc
    if embeddings.ndim != 2:
        raise CUDAEmbeddingError("embedding output must be a rank-two matrix")
    count, dimension = embeddings.shape
    if count != expected_count:
        raise CUDAEmbeddingError(
            "embedding output row count differs from ordered input"
        )
    if dimension <= 0:
        raise CUDAEmbeddingError("embedding output dimension must be positive")
    if expected_dimension is not None and dimension != expected_dimension:
        raise CUDAEmbeddingError(
            "embedding output dimension differs from the model contract"
        )
    if not np.issubdtype(embeddings.dtype, np.floating):
        raise CUDAEmbeddingError("embedding output must have a floating dtype")

    embeddings = np.ascontiguousarray(embeddings, dtype=np.float32)
    if not np.isfinite(embeddings).all():
        raise CUDAEmbeddingError("embedding output contains non-finite values")
    norms = np.linalg.norm(embeddings.astype(np.float64), axis=1)
    if not np.allclose(
        norms,
        np.ones(expected_count, dtype=np.float64),
        rtol=0.0,
        atol=UNIT_NORM_ATOL,
    ):
        raise CUDAEmbeddingError(
            "embedding output rows are not unit normalized"
        )
    return embeddings


def _atomic_write_npy(path: Path, embeddings: np.ndarray) -> tuple[str, int]:
    path = _absolute_path(path)
    if path.suffix != ".npy":
        raise CUDAEmbeddingError("output-npy must end in .npy")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            np.save(handle, embeddings, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())

        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        with temporary.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk)
        size_bytes = temporary.stat().st_size
        check = np.load(temporary, mmap_mode="r", allow_pickle=False)
        try:
            if check.shape != embeddings.shape or check.dtype != np.float32:
                raise CUDAEmbeddingError("serialized NPY output differs")
            if not np.array_equal(check, embeddings):
                raise CUDAEmbeddingError("serialized NPY values differ")
        finally:
            del check
            gc.collect()
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        temporary_name = None
        _fsync_directory(path.parent)
        return digest.hexdigest(), size_bytes
    except CUDAEmbeddingError:
        raise
    except (OSError, ValueError) as exc:
        raise CUDAEmbeddingError("cannot atomically write NPY output") from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path = _absolute_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
        temporary_name = None
        _fsync_directory(path.parent)
    except OSError as exc:
        raise CUDAEmbeddingError(
            "cannot atomically write embedding receipt"
        ) from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CUDAEmbeddingError("cannot open output directory for sync") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise CUDAEmbeddingError("cannot sync output directory") from exc
    finally:
        os.close(descriptor)


def run_worker(
    *,
    input_jsonl: Path,
    model_id: str,
    model_revision: str,
    output_npy: Path,
    receipt_json: Path,
    batch_size: int,
    dependencies: EmbeddingDependencies | None = None,
) -> Mapping[str, Any]:
    """Validate input, embed it on CUDA, and atomically persist the result."""

    model_id = _validate_model_id(model_id)
    model_revision = _validate_revision(model_revision)
    batch_size = _validate_batch_size(batch_size)

    input_path = _absolute_path(input_jsonl)
    output_path = _absolute_path(output_npy)
    receipt_path = _absolute_path(receipt_json)
    if (
        _paths_alias(output_path, receipt_path)
        or _paths_alias(input_path, output_path)
        or _paths_alias(input_path, receipt_path)
    ):
        raise CUDAEmbeddingError(
            "input-jsonl, output-npy, and receipt-json must differ"
        )
    if receipt_path.suffix != ".json":
        raise CUDAEmbeddingError("receipt-json must end in .json")

    loaded = _load_input(input_path)
    runtime = dependencies or _load_dependencies()
    torch = runtime.torch
    device_index, gpu_name, capability_major, capability_minor = (
        _configure_cuda(torch)
    )
    torch_version = str(getattr(torch, "__version__", "")).strip()
    cuda_version = str(
        getattr(getattr(torch, "version", None), "cuda", "") or ""
    ).strip()
    sentence_transformers_version = str(
        runtime.sentence_transformers_version
    ).strip()
    if not torch_version or not cuda_version or not sentence_transformers_version:
        raise CUDAEmbeddingError("embedding runtime versions are incomplete")

    model: Any = None
    try:
        try:
            model = runtime.model_factory(
                model_id,
                revision=model_revision,
                device="cuda",
                trust_remote_code=False,
            )
            model_device = str(model.device)
            if not model_device.startswith("cuda"):
                raise CUDAEmbeddingError(
                    "embedding model was not materialized on CUDA"
                )
            model.eval()
            declared_dimension = model.get_sentence_embedding_dimension()
            if declared_dimension is not None:
                declared_dimension = int(declared_dimension)
                if declared_dimension <= 0:
                    raise CUDAEmbeddingError(
                        "model reports an invalid embedding dimension"
                    )
            encoded = model.encode(
                [record.text for record in loaded.records],
                batch_size=batch_size,
                convert_to_numpy=True,
                device="cuda",
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            torch.cuda.synchronize(device_index)
        except CUDAEmbeddingError:
            raise
        except Exception as exc:
            # Library exceptions may include URLs, credentials, or host paths.
            raise CUDAEmbeddingError(
                f"CUDA embedding failed ({type(exc).__name__})"
            ) from None
        embeddings = _validate_embeddings(
            encoded,
            expected_count=len(loaded.records),
            expected_dimension=declared_dimension,
        )
    finally:
        del model
        gc.collect()
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass

    output_sha256, output_size_bytes = _atomic_write_npy(
        output_path, embeddings
    )

    receipt: dict[str, Any] = {
        "batch_size": batch_size,
        "compute_capability": {
            "major": capability_major,
            "minor": capability_minor,
        },
        "cuda_required": True,
        "cuda_version": cuda_version,
        "deterministic_algorithms": True,
        "embedding_dimension": int(embeddings.shape[1]),
        "embedding_dtype": "float32",
        "gpu_device_index": device_index,
        "gpu_name": gpu_name,
        "input_schema_version": INPUT_SCHEMA_VERSION,
        "input_sha256": loaded.input_sha256,
        "model_id": model_id,
        "model_revision": model_revision,
        "normalized": True,
        "numpy_version": str(np.__version__),
        "ordered_records_sha256": loaded.ordered_records_sha256,
        "output_format": OUTPUT_FORMAT,
        "output_sha256": output_sha256,
        "output_size_bytes": output_size_bytes,
        "record_count": len(loaded.records),
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "sentence_transformers_version": sentence_transformers_version,
        "torch_version": torch_version,
    }
    _atomic_write_bytes(receipt_path, _canonical_json(receipt) + b"\n")
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build normalized CVEfixes retrieval embeddings with a pinned "
            "SentenceTransformer revision on CUDA; CPU fallback is forbidden."
        ),
        allow_abbrev=False,
    )
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument(
        "--model-revision",
        "--revision",
        dest="model_revision",
        required=True,
        help="Exact lowercase 40-character Hugging Face model commit SHA.",
    )
    parser.add_argument("--output-npy", type=Path, required=True)
    parser.add_argument("--receipt-json", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=128)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = run_worker(
            input_jsonl=args.input_jsonl,
            model_id=args.model_id,
            model_revision=args.model_revision,
            output_npy=args.output_npy,
            receipt_json=args.receipt_json,
            batch_size=args.batch_size,
        )
    except CUDAEmbeddingError as exc:
        error = {
            "error": str(exc),
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "success": False,
        }
        sys.stderr.write(_canonical_json(error).decode("ascii") + "\n")
        return 2
    sys.stdout.write(_canonical_json(receipt).decode("ascii") + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
