"""Source-backed evidence and immutable two-file publication; no Hub/Lake/model execution."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import span_evidence as evidence


@pytest.fixture
def cli():
    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/publish_span_evidence.py"
    spec = importlib.util.spec_from_file_location("source_batch_cli_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture(text):
    return {"decoded_text": "Decoded agency shall report.", "formulas": [
        {"op": "O", "predicate": "report", "arguments": ["actor:agency", "scope:record"]}]}


def compile_one(session, text, span_id):
    return {"compiler_status": "compiled", "decompiled": text,
            "rule": {"actor": "agency", "action": "report", "modality": "obligation", "object": "record"}}


def source_rows():
    return [{"source_span_id": "source-1", "legal_id": "usc:us:5:552",
             "source_text": "  Each agency shall report.\n", "text": "  Each agency shall report.\n",
             "source_provenance_json": '{"corpus_commit":"source-commit","offset":17}'}]


def write_input(path, rows=None):
    rows = rows if rows is not None else source_rows()
    projected = [{key: value for key, value in row.items() if key != "text"} for row in rows]
    pq.write_table(pa.Table.from_pylist(projected), path)
    return path


def generated(cli, rows=None):
    return cli.generate_batch(rows or source_rows(), compile_source=True, lake_limit=0, lake_successes=0,
                              capture=capture, compile_one=compile_one, lake_check=lambda _: {}, code_identity="fixture")


def payloads(cli, tmp_path):
    rows, execution = generated(cli)
    path = tmp_path / "rows.parquet"
    written = evidence.write_span_evidence_parquet(rows, path, exclusive=True)
    proof = {"schema_version": evidence.BATCH_PROVENANCE_SCHEMA, "batch_id": "tiny-1", "source_backed": True,
             "parquet": {key: written[key] for key in ("sha256", "bytes", "row_count")}, **execution}
    proof_path = tmp_path / "provenance.json"
    cli._save(proof_path, proof)
    return rows, path, proof_path


class FakeAPI:
    def __init__(self):
        self.calls = []; self.head = "a" * 40; self.existing = []; self.oid = "b" * 40; self.error = None

    def repo_info(self, **kwargs):
        self.calls.append(("repo_info", kwargs)); return SimpleNamespace(sha=self.head)

    def get_paths_info(self, **kwargs):
        self.calls.append(("get_paths_info", kwargs)); return self.existing

    def create_commit(self, **kwargs):
        self.calls.append(("create_commit", kwargs))
        if self.error:
            raise self.error
        return SimpleNamespace(oid=self.oid)


def test_source_mode_exact_raw_and_default_decoded_unchanged():
    seen = []
    def compiler(session, text, span_id):
        seen.append(text); return compile_one(session, text, span_id)
    args = dict(capture=capture, compile_one=compiler, lake_limit=0, lake_successes=0, code_identity="fixture")
    raw = source_rows()[0]["text"]
    rows = evidence.generate_span_evidence(source_rows(), compiler_input_mode="source", **args)
    assert seen == [raw]
    assert rows[0]["source_text"] == raw
    assert rows[0]["source_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    evidence.generate_span_evidence(source_rows(), **args)
    assert seen[-1] == "Decoded agency shall report."


def test_unknown_compiler_mode_rejected_before_callbacks():
    with pytest.raises(ValueError, match="compiler_input_mode"):
        evidence.generate_span_evidence(source_rows(), compiler_input_mode="vocabulary_fallback",
                                        capture=lambda _: pytest.fail("capture ran"))


def test_codec_absent_metrics_remain_null_and_actual_fallback_is_recorded(cli):
    full = " decoded\n" * 100
    encoded = SimpleNamespace(losses={}, modal_ir=SimpleNamespace(formulas=[], to_dict=lambda: {"formulas": [], "exception": "retained"}), decoded_text=full,
                              metadata={"spacy_model_name": "blank:en", "spacy_used_fallback_model": True,
                                        "parser_backend": "spacy", "spacy_token_count": 7})
    codec = SimpleNamespace(encode=lambda *args, **kwargs: encoded)
    result = cli.measured_codec_capture(codec, "Agency shall report.")
    assert all(result[key] is None for key in ("cosine_loss", "cosine_similarity", "cross_entropy_loss",
                                               "ir_compression_loss", "ir_compression_ratio", "reconstruction_loss"))
    assert result["codec_observation"]["full_decoded_text"] == full
    assert result["codec_observation"]["spacy_used_fallback_model"] is True
    assert result["codec_observation"]["source_embedding_kind"] == "stable_mock_embedding"
    assert result["codec_observation"]["learned_embedding"] is False
    assert result["codec_observation"]["modal_ir"]["exception"] == "retained"
    assert result["codec_observation"]["raw_losses"] == {}


def test_generation_receipt_binds_full_decoding_lake_source_and_timings(cli):
    full = "Decoded " * 80
    def measured(text):
        return {**capture(text), "decoded_text": full, "codec_observation": {"full_decoded_text": full}}
    def lake(source):
        return {"lake_ok": True, "returncode": 0, "log": "actual fixture build log"}
    rows, report = cli.generate_batch(source_rows(), compile_source=True, lake_limit=0, lake_successes=1,
                                     capture=measured, compile_one=compile_one, lake_check=lake, code_identity="fixture")
    assert len(rows[0]["decoded_text"]) <= 240
    assert report["codec_observations"][0]["full_decoded_text"] == full
    assert report["compiler_inputs"][0]["source_provenance_json"] == source_rows()[0]["source_provenance_json"]
    assert report["compiler_inputs"][0]["compiler_input"] == source_rows()[0]["source_text"]
    assert report["compiler_inputs"][0]["compiler_result"]["rule"]["actor"] == "agency"
    assert report["generation_wall_seconds"] >= report["compiler_inputs"][0]["wall_seconds"] >= 0
    assert report["codec_observations"][0]["wall_seconds"] >= 0
    receipt = report["lake_checks"][0]
    assert receipt["source_span_ids"] == ["source-1"]
    assert receipt["source_sha256"] == hashlib.sha256(receipt["source"].encode()).hexdigest()
    assert (receipt["returncode"], receipt["log"], receipt["lake_ok"]) == (0, "actual fixture build log", True)
    assert report["bridge_names"] == [] and report["workers"] == 1
    assert report["bridge_evaluate_run"] is False and report["evaluate_provers"] is False
    assert report["admitted"] is report["formalized"] is report["native_model_training"] is False


def test_source_parquet_preserves_text_and_provenance(cli, tmp_path):
    path = write_input(tmp_path / "input.parquet")
    rows, ref = cli.read_source_spans(path)
    assert rows == source_rows()
    assert ref == {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size, "row_count": 1}


@pytest.mark.parametrize("change", ["duplicate", "null", "integer", "too_many", "too_long", "bad_provenance"])
def test_bad_source_rows_are_rejected(cli, tmp_path, change):
    rows = source_rows()
    if change == "duplicate": rows *= 2
    elif change == "null": rows[0]["source_text"] = None
    elif change == "integer": rows[0]["legal_id"] = 42
    elif change == "too_many": rows = [{**rows[0], "source_span_id": str(i)} for i in range(65)]
    elif change == "too_long": rows[0]["source_text"] = "x" * 32769
    else: rows[0]["source_provenance_json"] = "[]"
    path = write_input(tmp_path / "bad.parquet", rows)
    with pytest.raises(ValueError): cli.read_source_spans(path)


def test_batch_dry_run_has_no_remote_access(cli, tmp_path):
    _, path, proof = payloads(cli, tmp_path)
    api = FakeAPI()
    result = evidence.publish_span_evidence_batch(path, proof, batch_id="tiny-1", audited_parent_commit="a" * 40, api=api)
    assert api.calls == [] and result["uploaded"] is False
    assert len(result["files"]) == 2 and result["commit_sha"] is None


def test_batch_commit_is_exact_append_only_parent_cas(cli, tmp_path):
    _, path, proof = payloads(cli, tmp_path)
    api = FakeAPI()
    result = evidence.publish_span_evidence_batch(path, proof, batch_id="tiny-1", audited_parent_commit="a" * 40,
                                                 upload=True, api=api)
    assert [name for name, _ in api.calls] == ["repo_info", "get_paths_info", "create_commit"]
    assert api.calls[1][1]["revision"] == "a" * 40
    call = api.calls[-1][1]
    assert call["parent_commit"] == "a" * 40 and call["revision"] == "main"
    assert [op.path_in_repo for op in call["operations"]] == [
        "autoformal/uscode/batches/tiny-1/span-evidence.parquet", "autoformal/uscode/batches/tiny-1/provenance.json"]
    assert [op.path_or_fileobj for op in call["operations"]] == [path.read_bytes(), proof.read_bytes()]
    assert result["commit_sha"] == "b" * 40 and result["admitted"] is False


@pytest.mark.parametrize("failure", ["stale_parent", "existing_path", "response_loss", "missing_sha"])
def test_publication_failure_never_retries_or_overwrites(cli, tmp_path, failure):
    _, path, proof = payloads(cli, tmp_path)
    api = FakeAPI()
    if failure == "stale_parent": api.head = "c" * 40
    elif failure == "existing_path": api.existing = [SimpleNamespace(path="occupied")]
    elif failure == "response_loss": api.error = RuntimeError("response lost")
    else: api.oid = ""
    with pytest.raises((ValueError, RuntimeError)):
        evidence.publish_span_evidence_batch(path, proof, batch_id="tiny-1", audited_parent_commit="a" * 40,
                                             upload=True, api=api)
    assert sum(name == "create_commit" for name, _ in api.calls) == (failure in {"response_loss", "missing_sha"})


@pytest.mark.parametrize("field,value", [("batch_id", "../escape"), ("audited_parent_commit", "main"),
                                          ("repository_id", "someone/else"), ("upload", 1)])
def test_publication_rejects_unbound_arguments(cli, tmp_path, field, value):
    _, path, proof = payloads(cli, tmp_path)
    args = {"batch_id": "tiny-1", "audited_parent_commit": "a" * 40, "api": FakeAPI(), field: value}
    with pytest.raises(ValueError): evidence.publish_span_evidence_batch(path, proof, **args)


def test_mutated_provenance_cannot_publish(cli, tmp_path):
    _, path, proof = payloads(cli, tmp_path)
    value = json.loads(proof.read_bytes()); value["admitted"] = True
    proof.write_text(json.dumps(value))
    api = FakeAPI()
    with pytest.raises(ValueError, match="provenance"):
        evidence.publish_span_evidence_batch(path, proof, batch_id="tiny-1", audited_parent_commit="a" * 40, upload=True, api=api)
    assert api.calls == []


def test_readback_uses_only_returned_immutable_commit_and_exact_rows(cli, tmp_path):
    rows, path, proof = payloads(cli, tmp_path)
    publication = evidence.publish_span_evidence_batch(path, proof, batch_id="tiny-1", audited_parent_commit="a" * 40,
                                                       upload=True, api=FakeAPI())
    requests = []
    def download(**kwargs):
        requests.append(kwargs)
        return path if kwargs["filename"].endswith(".parquet") else proof
    result = cli.verify_published_batch(publication, rows, proof.read_bytes(), download=download)
    assert result["verified"] is True and all(item["revision"] == "b" * 40 for item in requests)
    changed = [{**rows[0], "legal_id": "different"}]
    with pytest.raises(ValueError, match="exact evidence rows"):
        cli.verify_published_batch(publication, changed, proof.read_bytes(), download=download)


def test_pinned_download_corruption_rejected(cli, tmp_path):
    rows, path, proof = payloads(cli, tmp_path)
    publication = evidence.publish_span_evidence_batch(path, proof, batch_id="tiny-1", audited_parent_commit="a" * 40,
                                                       upload=True, api=FakeAPI())
    bad = tmp_path / "bad"; bad.write_bytes(b"wrong bytes")
    with pytest.raises(ValueError, match="payload differs"):
        cli.verify_published_batch(publication, rows, proof.read_bytes(), download=lambda **kw: bad)


def test_exclusive_parquet_preserves_existing_bytes(cli, tmp_path):
    rows, path, _ = payloads(cli, tmp_path)
    before = path.read_bytes()
    with pytest.raises(FileExistsError): evidence.write_span_evidence_parquet(rows, path, exclusive=True)
    assert path.read_bytes() == before


@pytest.mark.parametrize("verification_fails", [False, True])
def test_cli_source_bypasses_demo_and_retains_observed_commit(cli, tmp_path, monkeypatch, verification_fails):
    from ipfs_datasets_py.logic.autoformal import span_cache, tree_pin
    input_path = write_input(tmp_path / "input.parquet")
    output = tmp_path / "output.parquet"
    calls = []
    monkeypatch.setattr(tree_pin, "require_workspace_logic_tree", lambda: calls.append("pin") or {"compiler": "fixture"})
    monkeypatch.setattr(span_cache, "compiler_path_hashes", lambda root: {"fixture": "sha"})
    monkeypatch.setattr(span_cache, "compiler_identity", lambda paths: "fixture")
    monkeypatch.setattr(evidence, "demonstration_spans", lambda: pytest.fail("demonstrations used"))
    original = cli.generate_batch
    monkeypatch.setattr(cli, "generate_batch", lambda spans, **kw: original(
        spans, **kw, capture=capture, compile_one=compile_one, lake_check=lambda _: {}))
    api = FakeAPI()
    publisher = evidence.publish_span_evidence_batch
    monkeypatch.setattr(evidence, "publish_span_evidence_batch", lambda *a, **kw: publisher(*a, **kw, api=api))
    def verify(publication, rows, proof_raw):
        assert output.with_suffix(".publication.json").exists()
        if verification_fails: raise ValueError("verification failed")
        return {"verified": True, "commit_sha": publication["commit_sha"]}
    monkeypatch.setattr(cli, "verify_published_batch", verify)
    monkeypatch.setattr(cli, "_publish_telemetry", lambda *args, **kwargs: {
        "uploaded": True, "dry_run": False, "admitted": False, "formalized": False,
        "path_in_repo": kwargs.get("path_in_repo"), "repository_id": "justicedao/uscode-autoformal-span-cache",
    })
    monkeypatch.setattr(cli, "_publish_exchange", lambda *args, **kwargs: {
        "uploaded": True, "dry_run": False, "admitted": False, "formalized": False,
        "enqueued": False, "census_path_in_repo": kwargs.get("census_path_in_repo"),
        "goals_path_in_repo": kwargs.get("goals_path_in_repo"),
        "repository_id": "justicedao/uscode-autoformal-span-cache",
    })
    args = ["--input-parquet", str(input_path), "--compile-source", "--output", str(output),
            "--batch-id", "tiny-1", "--lake-limit", "0", "--lake-successes", "0", "--upload",
            "--audited-parent-commit", "a" * 40]
    if verification_fails:
        with pytest.raises(ValueError, match="verification failed"): cli.main(args)
    else:
        assert cli.main(args) == 0
    # Census capture now also pins its producer before and after projection.
    assert calls == ["pin"] * 6
    assert json.loads(output.with_suffix(".publication.json").read_bytes())["commit_sha"] == "b" * 40
    proof = json.loads(output.with_suffix(".provenance.json").read_bytes())
    assert proof["source_backed"] is True and proof["input_artifact"]["row_count"] == 1
    assert output.with_suffix(".receipt.json").exists() is (not verification_fails)
    if not verification_fails:
        receipt = json.loads(output.with_suffix(".receipt.json").read_bytes())
        assert receipt["exchange"]["enqueued"] is False
        assert receipt["exchange"]["admitted"] is False
        assert receipt["exchange"]["formalized"] is False
        assert receipt["exchange"]["census_rows"] == 1
        assert receipt["exchange_publication"]["enqueued"] is False
        assert output.with_name("output.ae-compiler-census.parquet").is_file()
        assert output.with_name("output.supervisor-goals.parquet").is_file()
