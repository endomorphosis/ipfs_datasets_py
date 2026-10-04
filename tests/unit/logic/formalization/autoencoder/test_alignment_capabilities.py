"""Inventory must preserve missing evidence and reject unsafe metadata inputs."""
import hashlib
import json
import socket
import struct
import subprocess
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_capabilities as subject


def _string(value):
    data = value.encode()
    return struct.pack("<Q", len(data)) + data


def _gguf(entries=None, tensor_bytes=b"THIS_IS_NOT_METADATA"):
    entries = entries or [
        ("general.architecture", 8, _string("deepseek2")),
        ("deepseek2.embedding_length", 4, struct.pack("<I", 4096)),
    ]
    metadata = b"GGUF" + struct.pack("<IQQ", 3, 1, len(entries))
    for key, kind, payload in entries:
        metadata += _string(key) + struct.pack("<I", kind) + payload
    return metadata, metadata + tensor_bytes


def _runner(workspace, model, embedding=False):
    path = workspace / "scripts/run_leanstral_ephemeral.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    command = '["--model", "--batch-size", "128", "--ubatch-size", "64"'
    if embedding:
        command += ', "--embeddings", "--pooling", "last"'
    command += "]"
    path.write_text("from pathlib import Path\n"
                    f"DEFAULT_MODEL = Path({str(model)!r})\n"
                    f"def server_argv(c):\n    return {command}\n"
                    "def main():\n    parser.add_argument('--context', default=4096)\n")
    return path


@pytest.fixture
def roots(tmp_path, monkeypatch):
    repository, workspace = tmp_path / "datasets", tmp_path / "workspace"
    repository.mkdir()
    workspace.mkdir()
    # Binary presence is inert discovery and must never cause an execution.
    monkeypatch.setattr(subject.shutil, "which", lambda name: "/synthetic/bin/" + name)
    def forbid(*args, **kwargs):
        raise AssertionError("capability inventory must not execute or connect")
    monkeypatch.setattr(subprocess, "Popen", forbid)
    monkeypatch.setattr(subprocess, "run", forbid)
    monkeypatch.setattr(socket, "create_connection", forbid)
    return repository, workspace


def test_discovery_and_catalog_declarations_do_not_prove_or_admit(roots):
    repository, workspace = roots
    result = subject.describe_alignment_capabilities(repository, workspace)
    assert result["canonical_catalog"]["status"] == "declared"
    assert result["canonical_catalog"]["import_matches_repository"] is False
    assert result["canonical_catalog"]["baseline_family_ids"]
    assert result["canonical_catalog"]["executable_matrix_provider_ids"]
    lean = next(row for row in result["providers"] if row["provider_id"] == "lean")
    assert lean["binary_discovery"]["status"] == "discovered"
    assert lean["binary_discovery"]["runtime_verified"] is False
    assert lean["certificate_support"]["declared_evidence_kinds"]
    assert lean["certificate_support"]["current_certificate_verified"] is False
    assert lean["recorded_execution"]["saved_receipts_present"] == 0
    symbolic = next(row for row in result["providers"] if row["provider_id"] == "symbolicai")
    assert symbolic["advisory"] is True
    assert symbolic["declared_authority_ceiling"] == "advisory"
    assert symbolic["current_proof_authority"] == "none"
    assert all(row["proof_verified"] is False for row in result["providers"])
    assert result["recorded_execution"]["status"] == "unavailable"
    assert result["leanstral"]["model_metadata"]["status"] == "unavailable"
    assert result["execution_performed"] is result["proof_verified"] is result["production_admitted"] is False
    json.dumps(result, allow_nan=False)


def test_saved_success_without_receipts_remains_historical_not_verified(roots):
    repository, workspace = roots
    folder = repository / subject._QUALIFICATION / "native-final"
    folder.mkdir(parents=True)
    path = folder / "result.json"
    path.write_text(json.dumps({"schema": "generic-prover-admission-benchmark@1", "status": "passed",
        "runs": [{"cases": [{"kind": "lean", "outcome": {"result": {"status": "proved"}}}]}],
        "secret": "NEVER_INCLUDE_RAW_RECORD_FIELDS"}))
    result = subject.describe_alignment_capabilities(repository, workspace)
    record = result["recorded_execution"]
    assert record["status"] == "hash_bound_historical_record"
    assert record["result"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert record["reported_status"] == "passed"
    assert record["provider_summaries"]["lean"] == {"reported_cases": 1, "saved_receipts_present": 0}
    assert record["current_proof_authority"] == "none"
    assert record["receipts_verified"] is False
    assert "NEVER_INCLUDE_RAW_RECORD_FIELDS" not in json.dumps(result)


@pytest.mark.parametrize("payload", [[], {"status": "passed"},
    {"schema": "generic-prover-admission-benchmark@1", "runs": [{"cases": "malformed"}]}])
def test_malformed_saved_records_do_not_create_capability(roots, payload):
    repository, workspace = roots
    folder = repository / subject._QUALIFICATION / "native-final"
    folder.mkdir(parents=True)
    (folder / "result.json").write_text(json.dumps(payload))
    result = subject.describe_alignment_capabilities(repository, workspace)
    assert result["recorded_execution"]["status"] in {"invalid", "unavailable"}
    assert all(row["recorded_execution"]["saved_receipts_present"] == 0 for row in result["providers"])
    assert result["proof_verified"] is False


@pytest.mark.parametrize("embedding", [False, True])
def test_runner_mode_and_gguf_dimension_are_bound_without_loading(roots, embedding):
    repository, workspace = roots
    model = workspace / "model.gguf"
    prefix, data = _gguf()
    model.write_bytes(data)
    runner = _runner(workspace, model, embedding)
    Path(str(model) + ".json").write_text(json.dumps({"content_sha256": "a" * 64,
        "filename": model.name, "secret": "MANIFEST_FIELDS_MUST_BE_ALLOWLISTED"}))
    result = subject.describe_alignment_capabilities(repository, workspace)["leanstral"]
    assert result["runner"]["mode"] == ("embedding" if embedding else "chat")
    assert result["runner"]["embedding_endpoint_configured"] is embedding
    assert result["runner"]["source"]["sha256"] == hashlib.sha256(runner.read_bytes()).hexdigest()
    assert result["runner"]["declared_resource_defaults"]["--ubatch-size"] == 64
    metadata = result["model_metadata"]
    assert metadata["native_hidden_dimension"] == metadata["native_output_dimension"] == 4096
    assert metadata["metadata_bytes"] == len(prefix)
    assert metadata["metadata_prefix_sha256"] == hashlib.sha256(prefix).hexdigest()
    assert metadata["tensors_loaded"] is metadata["full_model_hash_verified"] is False
    assert result["cache_manifest"]["declared_model_sha256"] == "a" * 64
    assert result["cache_manifest"]["full_model_hash_verified"] is False
    assert result["embedding_runtime_verified"] is result["retrieval_quality_verified"] is False
    assert "MANIFEST_FIELDS_MUST_BE_ALLOWLISTED" not in json.dumps(result)


@pytest.mark.parametrize("case", ["truncated", "unknown_version", "oversized_string", "oversized_array", "duplicate_key", "invalid_width"])
def test_gguf_metadata_is_bounded_and_rejects_malformed_inputs(tmp_path, case):
    prefix, data = _gguf()
    if case == "truncated":
        data = prefix[:-1]
    elif case == "unknown_version":
        data = b"GGUF" + struct.pack("<IQQ", 99, 1, 0)
    elif case == "oversized_string":
        data = b"GGUF" + struct.pack("<IQQQ", 3, 1, 1, 2**40)
    elif case == "oversized_array":
        _, data = _gguf([("tokenizer.ggml.tokens", 9, struct.pack("<IQ", 8, 2**40))])
    elif case == "duplicate_key":
        _, data = _gguf([("general.architecture", 8, _string("deepseek2")),
                        ("general.architecture", 8, _string("other"))])
    elif case == "invalid_width":
        _, data = _gguf([("general.architecture", 8, _string("deepseek2")),
                        ("deepseek2.embedding_length", 7, struct.pack("<?", True))])
    path = tmp_path / "model.gguf"
    path.write_bytes(data)
    result = subject._gguf_metadata(path)
    assert result["status"] == "invalid"
    assert "native_hidden_dimension" not in result
    assert result["tensors_loaded"] is False


def test_nonregular_files_are_rejected_without_blocking(tmp_path):
    import os
    path = tmp_path / "metadata.fifo"
    os.mkfifo(path)
    assert subject._binding(path)["reason"] == "not_regular_file"
    assert subject._gguf_metadata(path)["reason"] == "not_regular_file"


def test_json_limits_and_duplicate_keys_do_not_create_records(tmp_path):
    path = tmp_path / "record.json"
    path.write_text('{"status":"failed","status":"passed"}')
    binding, record = subject._json_record(path)
    assert binding["status"] == "invalid"
    assert record is None
    with path.open("wb") as stream:
        stream.truncate(subject.MAX_JSON_BYTES + 1)
    binding, record = subject._json_record(path)
    assert binding["reason"] == "file_size_limit"
    assert record is None


def test_trust_policy_uses_hashed_source_without_importing_router(roots):
    repository, workspace = roots
    path = repository / "ipfs_datasets_py/logic/integration/reasoning/legal_ir_proof_router.py"
    path.parent.mkdir(parents=True)
    path.write_text("raise RuntimeError('source must not execute')\n"
                    "class ProofTrustLevel:\n    NONE = 0\n    BACKEND = 10\n    KERNEL = 40\n"
                    "class ProofRoutingPolicy:\n    required_trust: str = ProofTrustLevel.BACKEND\n")
    result = subject.describe_alignment_capabilities(repository, workspace)["trust_policy"]
    assert result["default_required_trust"] == "backend"
    assert result["declared_tiers"]["KERNEL"] == 40
    assert result["source"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["inventory_authority"] == "none"
    assert result["policy_executed"] is False
