"""Retained exports preserve original observations without executing a model."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.fixture
def cli():
    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/publish_span_cache_exchange.py"
    spec = importlib.util.spec_from_file_location("retained_exchange_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def retained(tmp_path):
    text = "The agency shall submit a report unless an emergency occurs."
    decoded = "reconstructed text with complete exception evidence\n" * 200
    sha = hashlib.sha256(text.encode()).hexdigest()
    row = {"source_span_id": "span-retained-1", "legal_id": "usc:5:552",
           "source_text": text, "source_sha256": sha, "compiler_status": "abstained",
           "reason": "UNSUPPORTED_SEMANTICS:exception", "decompiled_text": "",
           "agrees": False, "admitted": False, "formalized": False,
           "formulas_json": "[]", "rule_json": "{}"}
    path = tmp_path / "evidence.parquet"
    pq.write_table(pa.Table.from_pylist([row]), path)
    raw = path.read_bytes()
    proof = {"parquet": {"bytes": len(raw), "row_count": 1, "sha256": hashlib.sha256(raw).hexdigest()},
             "admitted": False, "formalized": False, "source_backed": True,
             "codec_kind": "DeterministicModalLogicCodec",
             "learned_autoencoder_execution": False, "compiler_input_mode": "source",
             "compiler_path_hashes": {"parser.py": "a" * 64},
             "compiler_inputs": [{"source_span_id": row["source_span_id"],
                                  "original_source_text": text, "original_source_sha256": sha,
                                  "compiler_input": text, "compiler_input_sha256": sha,
                                  "compiler_result": {"status": "abstained", "reason": row["reason"]}}],
             "codec_observations": [{"source_span_id": row["source_span_id"],
                                     "injected_capture": False,
                                     "codec_input_sha256": sha, "full_decoded_text": decoded,
                                     "observation": {"modal_ir": {"exception": "emergency"},
                                                     "raw_losses": {"cross_entropy_loss": 0.125}}}]}
    proof_path = tmp_path / "evidence.provenance.json"
    proof_path.write_text(json.dumps(proof))
    return path, proof_path, proof


def test_complete_historical_capture_preserved(cli, tmp_path):
    path, proof_path, proof = retained(tmp_path)
    rows, identity, binding = cli.retained_exchange_inputs(path, proof_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["autoencoder_text"] == proof["codec_observations"][0]["full_decoded_text"]
    assert row["autoencoder_capture"] == proof["codec_observations"][0]
    assert row["compiler_result"] == proof["compiler_inputs"][0]["compiler_result"]
    assert row["compiler_path_hashes"] == proof["compiler_path_hashes"]
    assert row["learned_autoencoder_execution"] is False
    assert row["retained_producer_binding"] == binding
    assert binding["historical_producer"] is True and binding["codec_rerun"] is False
    assert identity


@pytest.mark.parametrize("fault", ["hash", "source", "codec_source", "compiler_input", "coverage", "learned", "admitted", "producer", "synthetic", "injected"])
def test_inconsistent_retained_provenance_rejected(cli, tmp_path, fault):
    path, proof_path, proof = retained(tmp_path)
    if fault == "hash":
        proof["parquet"]["sha256"] = "0" * 64
    elif fault == "source":
        proof["compiler_inputs"][0]["original_source_text"] = "different law"
    elif fault == "codec_source":
        proof["codec_observations"][0]["codec_input_sha256"] = "0" * 64
    elif fault == "compiler_input":
        proof["compiler_inputs"][0]["compiler_input"] += " different input"
    elif fault == "coverage":
        proof["codec_observations"] = []
    elif fault == "learned":
        proof["learned_autoencoder_execution"] = True
    elif fault == "admitted":
        proof["admitted"] = True
    elif fault == "synthetic":
        proof["source_backed"] = False
    elif fault == "injected":
        proof["codec_observations"][0]["injected_capture"] = True
    else:
        proof["compiler_path_hashes"] = {"parser.py": "not-a-digest"}
    proof_path.write_text(json.dumps(proof))
    with pytest.raises(ValueError):
        cli.retained_exchange_inputs(path, proof_path)


def test_snapshot_rejects_symlink(cli, tmp_path):
    path, _, _ = retained(tmp_path)
    link = tmp_path / "linked.parquet"
    link.symlink_to(path)
    with pytest.raises(OSError):
        cli._snapshot(link)
