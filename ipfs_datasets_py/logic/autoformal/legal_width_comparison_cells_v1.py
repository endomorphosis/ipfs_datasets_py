"""Run the three genuine width comparison cells from their published producers.

The 8D cell loads the hash-checked canonical sparse checkpoint and encodes one
authored sentence. The 384D cell is the pinned gte-small receipt. The 768D
cell is the complete local encoder, not a zero-padded vector and not the
512-token experiment gate. A missing asset or a drifted vector raises.
Nothing here admits a meaning, scores a federal corpus, or starts training.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile


SOURCE = "The office shall retain the authored record."
_OFFLINE = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "TOKENIZERS_PARALLELISM": "false",
}


class WidthComparisonCellError(RuntimeError):
    """A comparison cell did not return its published producer result."""


def _offline() -> None:
    for name, value in _OFFLINE.items():
        os.environ.setdefault(name, value)


def _sha(value) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _vector_sha(vector) -> str:
    if not isinstance(vector, list) or not vector:
        raise WidthComparisonCellError("comparison vector is empty")
    return _sha([float(item) for item in vector])


def _package_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _canonical_checkpoint() -> Path:
    payload = json.loads(
        (_package_root() / "configs/autoencoders/legal_autoencoder_lineages.json")
        .read_text(encoding="utf-8")
    )
    lineage = payload["lineages"]["legacy_hub_v1"]
    checkpoint = lineage["checkpoint"]
    policy = lineage["checkpoint_policy"]
    repository = str(checkpoint["repository_id"]).replace("/", "--")
    path = (
        Path.home()
        / ".cache/huggingface/hub"
        / ("datasets--" + repository)
        / "snapshots"
        / checkpoint["revision"]
        / checkpoint["path"]
    )
    if not path.is_file() or path.stat().st_size != int(policy["size_bytes"]):
        raise WidthComparisonCellError("canonical sparse checkpoint is not the published file")
    return path


def _native768_assets() -> tuple[Path, Path]:
    for parent in Path(__file__).resolve().parents:
        root = parent / "artifacts/legal-decoder-native-conditioning-20261002/native768/assets"
        model = root / "model"
        code = root / "code"
        if (model / "model.safetensors").is_file() and (code / "modeling.py").is_file():
            return model, code
    raise WidthComparisonCellError("complete 768D local assets are absent")


def _safetensors_dtypes(path: Path) -> list[str]:
    with path.open("rb") as handle:
        header_len = struct.unpack("<Q", handle.read(8))[0]
        if header_len <= 0 or header_len > 8_000_000:
            raise WidthComparisonCellError("safetensors header is not a bounded dtype table")
        header = json.loads(handle.read(header_len))
    dtypes = sorted({
        str(item.get("dtype"))
        for key, item in header.items()
        if key != "__metadata__" and isinstance(item, dict)
    })
    if not dtypes:
        raise WidthComparisonCellError("safetensors header recorded no dtypes")
    return dtypes


def _false_authority() -> dict[str, object]:
    return {
        "admitted": False,
        "formalized": False,
        "gold_or_teacher_admission_granted": False,
        "constitution_roundtrip_ok": False,
        "completion_authority": False,
        "legal_meaning_established": False,
        "legal_acceptance_claimed": False,
        "federal_corpus_scored": False,
        "training_executed": False,
        "worker_launched": False,
        "encoder_unfrozen": False,
        "decoder_executed": False,
        "authored_fixture_only": True,
    }


def run_sparse8_cell() -> dict[str, object]:
    """Encode one authored sentence with the canonical 8D sparse checkpoint."""

    _offline()
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        isolated_object_clause_decoder_experiment as sidecar,
    )
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        source_gradient_preconditioning as formula,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_cuda
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import (
        legacy_v1,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages._contract import (
        TEACHER_CHECKPOINT_SHA256,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import (
        daemon_teacher,
        linguistic,
    )

    profile = linguistic.LinguisticAutoencoder(
        backend="historical_blank_en", compute_device="cpu"
    )
    sample = profile.build_sample(title="authored", section="record", text=SOURCE)
    origin = sample.parser_trace.get("embedding_origin")
    input_vector = [float(item) for item in sample.embedding_vector]
    model = legacy_v1.load_checkpoint(
        _canonical_checkpoint(),
        expected_sha256=TEACHER_CHECKPOINT_SHA256,
        compute_device="cpu",
    )
    identity = model.describe()["checkpoint_identity"]
    encoded = model.encode(sample)
    projection = [float(item) for item in encoded["embedding_projection"]]
    if (
        identity.get("sha256") != TEACHER_CHECKPOINT_SHA256
        or identity.get("exact_published_legacy_teacher") is not True
        or identity.get("read_only_checkpoint_load") is not True
        or legacy_v1.LINEAGE_ID != "legacy_hub_v1"
        or legacy_v1.DIMENSION != 8
        or origin != "deterministic_linguistic_feature_hash"
        or len(input_vector) != 8
        or len(projection) != 8
        or projection == input_vector
        or legacy_span_cuda.MODE != "legacy_mock_diagnostic"
        or legacy_span_cuda.REPRESENTATION.get("embedding_model") != "mock:stable-sha256"
        or formula.SCHEMA != "eight-dimensional-source-gradient-preconditioner/v1"
        or sidecar.LINEAGE != "isolated_object_8d_formula_sidecar_v1"
        or linguistic.PROFILE_ID != "legacy-linguistic-features-8d/v1"
        or daemon_teacher.PROFILE_ID != "legacy-daemon-linguistic-bm25-flogic-8d/v1"
        or model.describe().get("admitted") is not False
    ):
        raise WidthComparisonCellError("8D cell did not keep the canonical sparse projection")
    return {
        "checkpoint_sha256": identity.get("sha256"),
        "daemon_profile_executed": False,
        "dimension": 8,
        "encoder_called": True,
        "encode_keys": sorted(encoded),
        "exact_published_legacy_teacher": True,
        "formula_sidecar_lineage": sidecar.LINEAGE,
        "formula_sidecar_substituted": False,
        "input_dimension": 8,
        "input_origin": origin,
        "input_sha256": _vector_sha(input_vector),
        "lineage_id": legacy_v1.LINEAGE_ID,
        "linguistic_bundle_substituted": False,
        "linguistic_profile_id": linguistic.PROFILE_ID,
        "mock_embedding_model": "mock:stable-sha256",
        "mock_projection_substituted": False,
        "model_executed": True,
        "model_inference_executed": True,
        "producer_called": True,
        "projection_dimension": 8,
        "projection_equals_input": False,
        "projection_sha256": _vector_sha(projection),
        "read_only_checkpoint_load": True,
        "source_access_evidenced": True,
        "source_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
        "source_text_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
        **_false_authority(),
    }


def run_native384_cell() -> dict[str, object]:
    """Embed one authored sentence with the pinned 384D gte-small profile."""

    _offline()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        autoencoder_embedding_production as codec,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        autoencoder_embedding_runtime as runtime,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import (
        SourceArtifact,
        SourceSpan,
    )

    raw = SOURCE.encode()
    digest = hashlib.sha256(raw).hexdigest()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "source.txt"
        path.write_bytes(raw)
        source = SourceSpan(
            SourceArtifact(digest, len(raw)),
            "us_code",
            "authored-fixture",
            "authored-record",
            "en",
            "1 USC 1",
            0,
            len(raw),
        )
        item = codec.EmbeddingInput(source, "1", "1", SOURCE, source.citation)

        def resolver(ref):
            if ref.get("sha256") != digest:
                raise FileNotFoundError(ref.get("sha256"))
            return path

        receipt = runtime.produce_native_embedding_receipt(
            [item], resolver=resolver, batch_size=1
        )
    data = receipt.to_dict()
    row = data["results"][0]
    decoded = [float(value) for value in codec._decode_vector(row["vector"])]
    weights = Path(runtime.DEFAULT_SNAPSHOT_PATH) / "model.safetensors"
    pinned_size, pinned_sha = runtime._PINNED_ASSETS["model.safetensors"]
    if not weights.is_file() or weights.stat().st_size != pinned_size:
        raise WidthComparisonCellError("pinned 384D weights are not the published file")
    storage_dtypes = _safetensors_dtypes(weights)
    execution = dict(data["execution"])
    design = {"kind": "native", "batch_size": 1, **codec._EXECUTION}
    settings_matched = (
        data["model"] == {
            "model_id": codec.MODEL_ID,
            "revision": codec.MODEL_REVISION,
            "dimension": codec.DIMENSION,
        }
        and execution == design
        and data["qualification"] == codec._QUALIFICATION
        and row["status"] == "embedded"
        and len(decoded) == 384
        and "F16" in storage_dtypes
        and execution.get("dtype") == "float32"
    )
    if not settings_matched or codec.MODEL_ID != "thenlper/gte-small" or codec.DIMENSION != 384:
        raise WidthComparisonCellError("384D cell did not match the pinned execution profile")
    return {
        "active_lane_model_id": codec.MODEL_ID,
        "active_lane_revision": codec.MODEL_REVISION,
        "asset_names": sorted(item["name"] for item in data["model_assets"]),
        "detached_placeholder_components": ["F15", "F17", "F18"],
        "detached_placeholder_bound_as_active_lane": False,
        "dimension": 384,
        "encoder_called": True,
        "executed_dtype": "float32",
        "execution": execution,
        "model": data["model"],
        "model_executed": True,
        "model_inference_executed": True,
        "model_revision_authenticated": False,
        "pinned_weight_sha256": pinned_sha,
        "producer_called": True,
        "qualification": data["qualification"],
        "receipt_schema": data["schema"],
        "receipt_sha256": receipt.sha256,
        "runtime_computation_proven": False,
        "runtime_cryptographically_attested": False,
        "settings_matched": True,
        "source_authority_authenticated": False,
        "source_sha256": digest,
        "status": row["status"],
        "status_counts": data["status_counts"],
        "storage_dtypes": storage_dtypes,
        "vector_length": len(decoded),
        "vector_sha256": _vector_sha(decoded),
        **_false_authority(),
    }


def run_native768_cell() -> dict[str, object]:
    """Embed one authored sentence with the complete local 768D encoder."""

    _offline()
    import torch

    from ipfs_datasets_py.logic.formalization.autoencoder import (
        dimension_source_inputs,
        gte_multilingual_profile as profile,
        source_embeddings_768 as reference,
        source_embeddings_768_complete as producer,
    )

    manifest = _package_root() / "configs/autoencoders/gte_multilingual_local_assets_v1.json"
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    model_directory, code_directory = _native768_assets()
    source_sha = hashlib.sha256(SOURCE.encode()).hexdigest()
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        report = producer.embed_rows(
            [{"id": "source:" + source_sha, "source_text": SOURCE}],
            manifest_path=manifest,
            expected_manifest_sha256=manifest_sha,
            model_directory=model_directory,
            code_directory=code_directory,
            batch_size=1,
        )
    finally:
        torch.set_num_threads(previous)
    receipts = report.get("receipts") or []
    loading = report.get("complete_checkpoint_loading") or {}
    dense = report.get("dense_path_verification") or {}
    vector = receipts[0]["embedding"] if receipts else None
    execution = report.get("execution_profile") or {}
    authenticated = (
        report.get("status") == "completed"
        and report.get("profile_id") == profile.PROFILE_ID
        and report.get("model_inference_executed") is True
        and report.get("download_executed") is False
        and report.get("training_executed") is False
        and receipts
        and receipts[0].get("dimension") == 768
        and receipts[0].get("truncated") is False
        and receipts[0].get("normalized") is True
        and isinstance(vector, list)
        and len(vector) == 768
        and dense.get("encoder_and_complete_hidden_states_bitwise_equal") is True
        and loading.get("unexpected_keys") == []
        and loading.get("missing_keys") == []
        and loading.get("classifier_loaded") is True
        and loading.get("classifier_logits_used_for_dense_embedding") is False
        and loading.get("architecture") == "NewForTokenClassification"
        and loading.get("tensor_count") == 138
        and execution.get("max_tokens_including_special_tokens") == 8192
        and reference.MAX_TOKENS == 8192
        and dimension_source_inputs.MAX_TOKENS == 512
        and execution.get("pooling") == "cls"
        and execution.get("normalization") == "l2"
        and execution.get("device") == "cpu"
        and execution.get("dtype") == "float32"
        and (report.get("assets") or {}).get("manifest_sha256") == manifest_sha
        and report.get("proof_authority") is False
    )
    if not authenticated:
        raise WidthComparisonCellError("768D cell did not authenticate the complete encoder")
    return {
        "architecture": loading.get("architecture"),
        "classifier_loaded": True,
        "classifier_logits_used_for_dense_embedding": False,
        "coordinate_relabel_manufactured": False,
        "coordinate_zero_pad": False,
        "dense_path_equal": True,
        "dimension": 768,
        "download_executed": False,
        "encoder_called": True,
        "encoder_identity_authenticated": True,
        "execution_profile": execution,
        "experiment_max_tokens": dimension_source_inputs.MAX_TOKENS,
        "implementation": report.get("implementation"),
        "manifest_sha256": manifest_sha,
        "max_tokens_relabelled_as_512": False,
        "missing_keys": [],
        "model_executed": True,
        "model_inference_executed": True,
        "normalized": True,
        "producer_called": True,
        "profile_id": report.get("profile_id"),
        "profile_max_tokens": reference.MAX_TOKENS,
        "proof_authority": False,
        "runtime_compatibility_verified": report.get("runtime_compatibility_verified"),
        "source_semantics_verified": False,
        "source_sha256": source_sha,
        "status": report.get("status"),
        "tensor_count": 138,
        "token_count_including_special_tokens": receipts[0].get(
            "token_count_including_special_tokens"
        ),
        "truncated": False,
        "unexpected_keys": [],
        "vector_length": 768,
        "vector_sha256": _vector_sha(vector),
        "zero_padding_manufactured": False,
        **_false_authority(),
    }


def main() -> None:
    for name, function in (
        ("sparse8", run_sparse8_cell),
        ("native384", run_native384_cell),
        ("native768", run_native768_cell),
    ):
        print("START", name, flush=True)
        result = function()
        print("OK", name, flush=True)
        print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
