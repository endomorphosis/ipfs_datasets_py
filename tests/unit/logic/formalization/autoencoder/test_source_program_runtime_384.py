"""Opt-in decoder consumption binds exact source without trusting saved checks."""
from copy import deepcopy
import hashlib
import importlib
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import source_program_runtime_384 as subject
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression, ProgramIR

PIN = "a" * 64
TEXT = "def compare(capacity: int, threshold: int) -> bool:\n    outcome = capacity < threshold\n    return outcome\n"


def candidate(operator="<"):
    refs = ("expr:capacity", "expr:threshold")
    return dict(kind="program_expression", document=ProgramExpression("expr:result", "binary", "boolean",
        operand_ids=refs, evaluation_order=refs, operator=operator, source_ref_ids=("source",)).to_dict())


def source_rows(text=TEXT):
    return [dict(id="input-0", source_text=text)]


def embedded_rows(text=TEXT):
    return [{**source_rows(text)[0], "embedding": [.125] * 384}]


def report(text=TEXT, operator="<"):
    return dict(domain_id="security_ir", rows=[dict(id="input-0", source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        candidate_ir=candidate(operator), status="unqualified_candidate", **{key: True for key in subject.FALSE})],
        **{key: True for key in subject.FALSE})


def wrapper(value, *, domain="security_ir", calls=None):
    def infer(rows, **options):
        if calls is not None:
            calls.append((deepcopy(rows), options))
        return value
    return subject.SourceProgramDecoder384(SimpleNamespace(infer=infer,
        describe=lambda: dict(domain_id=domain, **{key: True for key in subject.FALSE})), checkpoint_sha256=PIN)


def test_wrapper_qualifies_real_native_effects_and_preserves_original_candidate():
    raw, calls = report(), []
    before = deepcopy(raw)
    decoder = wrapper(raw, calls=calls)
    value = decoder.infer(embedded_rows(), weight_ablation="zero_head")
    assert raw == before
    assert calls == [(embedded_rows(), {"weight_ablation": "zero_head"})]
    assert value["checkpoint_sha256"] == PIN and value["source_contracts_checked"]
    row = value["rows"][0]
    assert row["candidate_ir"] == before["rows"][0]["candidate_ir"]
    assert row["status"] == "unqualified_candidate" and row["continue_planning"]
    checked = row["source_contract"]
    assert checked["schema"] == "security-source-program-binding-384/v2" and checked["status"] == "qualified"
    native = ProgramIR.from_dict(checked["projections"][0]["native_document"])
    assert native.functions[0].effects.reads == tuple(sorted(
        native.functions[0].parameter_symbol_ids + native.functions[0].local_symbol_ids))
    assert all(value[key] is False and row[key] is False for key in subject.FALSE)
    description = decoder.describe()
    assert description["automatic_lake_build"] is False and description["checkpoint_sha256"] == PIN
    assert all(description[key] is False for key in subject.FALSE)


@pytest.mark.parametrize("text,operator,status", [
    (TEXT, "<=", "mismatch"), (TEXT.replace(": int", ""), "<", "unsupported"),
])
def test_mismatch_or_unsupported_source_remains_fail_open_without_repair(text, operator, status):
    raw = report(text, operator)
    before = deepcopy(raw)
    value = wrapper(raw).infer(embedded_rows(text))
    row = value["rows"][0]
    assert row["status"] == "fail_open_source_contract_" + status
    assert row["continue_planning"] and row["source_contract"]["projections"] == []
    assert row["candidate_ir"] == before["rows"][0]["candidate_ir"] and raw == before


@pytest.mark.parametrize("change", ["hash", "foreign_id", "duplicate_inputs", "missing_output", "wrong_report_domain"])
def test_wrapper_rejects_changed_source_or_output_identity(change):
    raw, rows = report(), embedded_rows()
    if change == "hash":
        raw["rows"][0]["source_sha256"] = "b" * 64
    elif change == "foreign_id":
        raw["rows"][0]["id"] = "foreign"
    elif change == "duplicate_inputs":
        rows.append(deepcopy(rows[0]))
    elif change == "missing_output":
        raw["rows"] = []
    else:
        raw["domain_id"] = "legal_ir"
    with pytest.raises(ValueError, match="identity|hash|SecurityIR"):
        wrapper(raw).infer(rows)


def test_missing_candidate_preserves_decoder_abstention():
    raw = report()
    raw["rows"][0].update(candidate_ir=None, status="fail_open_decoder_abstained")
    row = wrapper(raw).infer(embedded_rows())["rows"][0]
    assert row["candidate_ir"] is None and row["status"] == "fail_open_decoder_abstained"
    assert "source_contract" not in row


@pytest.mark.parametrize("pin", [None, "main", "A" * 64, "1" * 63, "z" * 64])
def test_wrapper_requires_exact_checkpoint_identity(pin):
    runtime = SimpleNamespace(describe=lambda: dict(domain_id="security_ir"))
    with pytest.raises(ValueError, match="SHA256"):
        subject.SourceProgramDecoder384(runtime, checkpoint_sha256=pin)


def test_non_security_runtime_is_not_accepted():
    with pytest.raises(ValueError, match="SecurityIR"):
        wrapper(report(), domain="intent_ir")


@pytest.mark.parametrize("name,module_name", [("structured", "structured_source_384"), ("sequence_v2", "source_training_v2")])
def test_loader_passes_independent_hash_pin_and_security_domain(monkeypatch, name, module_name):
    module = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder." + module_name)
    runtime = SimpleNamespace(describe=lambda: dict(domain_id="security_ir"))
    calls = []

    def load(path, **options):
        calls.append((path, options))
        return runtime

    monkeypatch.setattr(module, "load_checkpoint", load)
    loaded = subject.load_source_program_decoder_384("weights.json", expected_sha256=PIN, decoder=name)
    assert loaded.runtime is runtime
    assert calls == [("weights.json", dict(expected_sha256=PIN, expected_domain="security_ir"))]
    assert loaded.describe()["checkpoint_sha256"] == PIN


def test_loader_does_not_accept_unknown_decoder():
    with pytest.raises(ValueError, match="unsupported"):
        subject.load_source_program_decoder_384("weights.json", expected_sha256=PIN, decoder="untrusted")


def test_infer_texts_forwards_only_verified_embeddings_and_source(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384
    calls = []

    def embed(texts, **options):
        assert texts == [TEXT] and options == {"snapshot_path": "verified-snapshot"}
        return [[.125] * 384]

    monkeypatch.setattr(source_embeddings_384, "embed_texts", embed)
    result = wrapper(report(), calls=calls).infer_texts([TEXT], snapshot_path="verified-snapshot",
        weight_ablation="zero_head")
    assert calls == [(embedded_rows(), {"weight_ablation": "zero_head"})]
    assert result["rows"][0]["source_contract"]["status"] == "qualified"


@pytest.mark.parametrize("extra", ["target", "embedding", "source_contract"])
def test_build_helper_rejects_target_or_context_fields_in_source_rows(extra):
    rows = source_rows()
    rows[0][extra] = candidate()
    with pytest.raises(ValueError, match="closed source rows"):
        subject.build_decoded_source_program_lake(report(), rows, lake_executable="unused")


@pytest.mark.parametrize("change", ["wrong_source", "wrong_hash", "foreign_id", "duplicate_id", "wrong_domain"])
def test_build_helper_rejects_incorrect_source_identity_before_gate(monkeypatch, change):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_program_lake_384 as gate
    monkeypatch.setattr(gate, "build_source_program_lake", lambda *a, **k: pytest.fail("invalid identity reached gate"))
    raw, rows = report(), source_rows()
    if change == "wrong_source":
        rows[0]["source_text"] += "# changed\n"
    elif change == "wrong_hash":
        raw["rows"][0]["source_sha256"] = "0" * 64
    elif change == "foreign_id":
        rows[0]["id"] = "foreign"
    elif change == "duplicate_id":
        rows.append(deepcopy(rows[0]))
    else:
        raw["domain_id"] = "ui_ux_ir"
    with pytest.raises(ValueError, match="identity|hash|SecurityIR"):
        subject.build_decoded_source_program_lake(raw, rows, lake_executable="unused")


def test_build_helper_sends_fresh_closed_candidates_without_trusting_attached_evidence(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_program_lake_384 as gate
    raw = report()
    raw["rows"][0]["source_contract"] = {"qualified": True, "proof_authority": True, "projections": ["forged"]}
    before = deepcopy(raw)
    sentinel = object()

    def build(rows, **options):
        assert rows == [dict(id="input-0", source_text=TEXT, candidate_ir=candidate())]
        assert options == dict(lake_executable="native-lake", timeout_seconds=23, output_directory="fresh-output")
        rows[0]["candidate_ir"]["document"]["operator"] = "!="
        return sentinel

    monkeypatch.setattr(gate, "build_source_program_lake", build)
    result = subject.build_decoded_source_program_lake(raw, source_rows(), lake_executable="native-lake",
        timeout_seconds=23, output_directory="fresh-output")
    assert result is sentinel and raw == before


def test_forged_success_contract_cannot_make_mismatched_prediction_reach_lake(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_program_lake_384 as gate
    raw = report(operator="<=")
    raw["rows"][0]["source_contract"] = {"status": "qualified", "proof_authority": True}
    # This unit check deliberately installs an executor tripwire. It does not
    # claim real execution evidence; production loaded-code guards stay active
    # everywhere outside this narrowly scoped mock.
    monkeypatch.setattr(gate, "_guard", lambda: None)
    monkeypatch.setattr(gate.executor, "_execute", lambda *a, **k: pytest.fail("mismatched prediction reached Lake"))
    execution = subject.build_decoded_source_program_lake(raw, source_rows(), lake_executable="unused")
    receipt = execution.to_dict()
    assert receipt["status"] == "blocked" and receipt["backend_executed"] is False
    assert receipt["rows"][0]["source_qualification"]["status"] == "mismatch"
    assert receipt["proof_authority"] is False
