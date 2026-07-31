"""Tests for the CUDA-only CVEfixes embedding worker."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np
import pytest


SCRIPT = (
    Path(__file__).resolve().parents[5]
    / "scripts"
    / "ops"
    / "security_ir"
    / "embed_cvefixes_cuda.py"
)
SPEC = importlib.util.spec_from_file_location("embed_cvefixes_cuda", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
worker: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = worker
SPEC.loader.exec_module(worker)


REVISION = "1" * 40
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"


def _record(position: int, node_character: str, text: str) -> dict[str, Any]:
    return {
        "position": position,
        "node_cid": "b" + (node_character * 58),
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "text": text,
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                record,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


class _FakeCuda:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.synchronized: list[int] = []
        self.cache_cleared = False

    def is_available(self) -> bool:
        return self.available

    @staticmethod
    def current_device() -> int:
        return 0

    @staticmethod
    def get_device_name(index: int) -> str:
        assert index == 0
        return "Test CUDA GPU"

    @staticmethod
    def get_device_capability(index: int) -> tuple[int, int]:
        assert index == 0
        return (9, 0)

    def synchronize(self, index: int) -> None:
        self.synchronized.append(index)

    def empty_cache(self) -> None:
        self.cache_cleared = True


class _FakeTorch:
    __version__ = "2.9.0"
    version = SimpleNamespace(cuda="13.0")

    def __init__(self, *, cuda_available: bool = True) -> None:
        self.cuda = _FakeCuda(available=cuda_available)
        self.backends = SimpleNamespace(
            cudnn=SimpleNamespace(benchmark=True, allow_tf32=True),
            cuda=SimpleNamespace(matmul=SimpleNamespace(allow_tf32=True)),
        )
        self.deterministic = False
        self.grad_enabled = True

    def use_deterministic_algorithms(self, value: bool) -> None:
        self.deterministic = value

    def set_grad_enabled(self, value: bool) -> None:
        self.grad_enabled = value


class _FakeModel:
    device = "cuda:0"

    def __init__(self, expected_texts: list[str]) -> None:
        self.expected_texts = expected_texts
        self.evaluation = False
        self.encode_arguments: dict[str, Any] = {}

    def eval(self) -> None:
        self.evaluation = True

    @staticmethod
    def get_sentence_embedding_dimension() -> int:
        return 3

    def encode(self, texts: list[str], **kwargs: Any) -> np.ndarray:
        assert texts == self.expected_texts
        self.encode_arguments = kwargs
        return np.asarray(
            [[1.0, 0.0, 0.0], [0.0, 0.6, 0.8]], dtype=np.float32
        )


def _dependencies(
    *,
    texts: list[str],
    cuda_available: bool = True,
    model: _FakeModel | None = None,
) -> tuple[Any, _FakeTorch, _FakeModel]:
    fake_torch = _FakeTorch(cuda_available=cuda_available)
    fake_model = model or _FakeModel(texts)

    def factory(model_id: str, **kwargs: Any) -> _FakeModel:
        assert model_id == MODEL_ID
        assert kwargs == {
            "revision": REVISION,
            "device": "cuda",
            "trust_remote_code": False,
        }
        return fake_model

    dependencies = worker.EmbeddingDependencies(
        torch=fake_torch,
        sentence_transformers_version="5.4.1",
        model_factory=factory,
    )
    return dependencies, fake_torch, fake_model


def test_worker_writes_deterministic_normalized_npy_and_receipt(
    tmp_path: Path,
) -> None:
    texts = ["repair an overflow", "reject traversal"]
    records = [
        _record(0, "a", texts[0]),
        _record(1, "c", texts[1]),
    ]
    input_path = tmp_path / "input.jsonl"
    _write_jsonl(input_path, records)
    dependencies, fake_torch, fake_model = _dependencies(texts=texts)

    output = tmp_path / "embeddings.npy"
    receipt_path = tmp_path / "receipt.json"
    receipt = worker.run_worker(
        input_jsonl=input_path,
        model_id=MODEL_ID,
        model_revision=REVISION,
        output_npy=output,
        receipt_json=receipt_path,
        batch_size=64,
        dependencies=dependencies,
    )

    embeddings = np.load(output, allow_pickle=False)
    assert embeddings.dtype == np.float32
    assert embeddings.shape == (2, 3)
    assert np.allclose(np.linalg.norm(embeddings, axis=1), 1.0)
    assert receipt == json.loads(receipt_path.read_text())
    assert receipt_path.read_bytes() == worker._canonical_json(receipt) + b"\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o644
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o644
    assert receipt["cuda_required"] is True
    assert receipt["input_sha256"] == hashlib.sha256(
        input_path.read_bytes()
    ).hexdigest()
    assert receipt["output_sha256"] == hashlib.sha256(
        output.read_bytes()
    ).hexdigest()
    assert receipt["record_count"] == 2
    assert receipt["embedding_dimension"] == 3
    assert receipt["model_id"] == MODEL_ID
    assert receipt["model_revision"] == REVISION
    assert receipt["gpu_name"] == "Test CUDA GPU"
    assert receipt["compute_capability"] == {"major": 9, "minor": 0}
    assert receipt["torch_version"] == "2.9.0"
    assert receipt["cuda_version"] == "13.0"
    assert receipt["sentence_transformers_version"] == "5.4.1"
    assert fake_model.evaluation is True
    assert fake_model.encode_arguments == {
        "batch_size": 64,
        "convert_to_numpy": True,
        "device": "cuda",
        "normalize_embeddings": True,
        "show_progress_bar": False,
    }
    assert fake_torch.deterministic is True
    assert fake_torch.grad_enabled is False
    assert fake_torch.cuda.synchronized == [0]
    assert fake_torch.cuda.cache_cleared is True

    first_output = output.read_bytes()
    first_receipt = receipt_path.read_bytes()
    dependencies, _, _ = _dependencies(texts=texts)
    worker.run_worker(
        input_jsonl=input_path,
        model_id=MODEL_ID,
        model_revision=REVISION,
        output_npy=output,
        receipt_json=receipt_path,
        batch_size=64,
        dependencies=dependencies,
    )
    assert output.read_bytes() == first_output
    assert receipt_path.read_bytes() == first_receipt


def test_input_integrity_fails_before_cuda_runtime(tmp_path: Path) -> None:
    records = [_record(1, "a", "out of order")]
    input_path = tmp_path / "input.jsonl"
    _write_jsonl(input_path, records)

    with pytest.raises(
        worker.CUDAEmbeddingError,
        match="contiguous and zero based",
    ):
        worker.run_worker(
            input_jsonl=input_path,
            model_id=MODEL_ID,
            model_revision=REVISION,
            output_npy=tmp_path / "output.npy",
            receipt_json=tmp_path / "receipt.json",
            batch_size=1,
        )

    records = [_record(0, "a", "changed")]
    records[0]["text_sha256"] = "0" * 64
    _write_jsonl(input_path, records)
    with pytest.raises(worker.CUDAEmbeddingError, match="text SHA-256 differs"):
        worker._load_input(input_path)


def test_worker_forbids_cpu_fallback(tmp_path: Path) -> None:
    text = "must remain on CUDA"
    input_path = tmp_path / "input.jsonl"
    _write_jsonl(input_path, [_record(0, "a", text)])
    dependencies, _, _ = _dependencies(
        texts=[text],
        cuda_available=False,
    )

    with pytest.raises(worker.CUDAEmbeddingError, match="CPU.*forbidden"):
        worker.run_worker(
            input_jsonl=input_path,
            model_id=MODEL_ID,
            model_revision=REVISION,
            output_npy=tmp_path / "output.npy",
            receipt_json=tmp_path / "receipt.json",
            batch_size=1,
            dependencies=dependencies,
        )
    assert not (tmp_path / "output.npy").exists()
    assert not (tmp_path / "receipt.json").exists()


def test_worker_rejects_symlink_input(tmp_path: Path) -> None:
    text = "do not follow an input symlink"
    target = tmp_path / "target.jsonl"
    _write_jsonl(target, [_record(0, "a", text)])
    input_path = tmp_path / "input.jsonl"
    input_path.symlink_to(target)
    dependencies, _, _ = _dependencies(texts=[text])

    with pytest.raises(worker.CUDAEmbeddingError, match="non-symlink"):
        worker.run_worker(
            input_jsonl=input_path,
            model_id=MODEL_ID,
            model_revision=REVISION,
            output_npy=tmp_path / "output.npy",
            receipt_json=tmp_path / "receipt.json",
            batch_size=1,
            dependencies=dependencies,
        )


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            np.asarray(
                [[np.nan, 0.0, 0.0], [0.0, 0.6, 0.8]], dtype=np.float32
            ),
            "non-finite",
        ),
        (
            np.asarray(
                [[0.5, 0.0, 0.0], [0.0, 0.6, 0.8]], dtype=np.float32
            ),
            "unit normalized",
        ),
    ],
)
def test_worker_rejects_invalid_embedding_values(
    tmp_path: Path,
    values: np.ndarray,
    message: str,
) -> None:
    texts = ["one", "two"]
    input_path = tmp_path / "input.jsonl"
    _write_jsonl(
        input_path,
        [_record(0, "a", texts[0]), _record(1, "c", texts[1])],
    )
    fake_model = _FakeModel(texts)
    fake_model.encode = lambda texts, **kwargs: values  # type: ignore[method-assign]
    dependencies, _, _ = _dependencies(texts=texts, model=fake_model)

    with pytest.raises(worker.CUDAEmbeddingError, match=message):
        worker.run_worker(
            input_jsonl=input_path,
            model_id=MODEL_ID,
            model_revision=REVISION,
            output_npy=tmp_path / "output.npy",
            receipt_json=tmp_path / "receipt.json",
            batch_size=2,
            dependencies=dependencies,
        )
    assert not (tmp_path / "output.npy").exists()
    assert not (tmp_path / "receipt.json").exists()


def test_parser_requires_immutable_lowercase_revision() -> None:
    with pytest.raises(
        worker.CUDAEmbeddingError,
        match="lowercase 40-character",
    ):
        worker._validate_revision("A" * 40)
    assert worker._validate_revision(REVISION) == REVISION
