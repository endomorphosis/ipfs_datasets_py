"""Actual structural Lake checks do not establish source semantic admission."""
import copy
from dataclasses import FrozenInstanceError
import importlib.util
import os
from pathlib import Path
import struct
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import native_formal_decoder

PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
ROOT = Path(native_formal_decoder.__file__).resolve().parents[3]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if os.environ.get("DECODER_COMPLETION_STAGING"):
    q = _load(Path(os.environ["DECODER_COMPLETION_STAGING"]) / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_schema_lake.py", PREFIX + ".autoencoder_schema_lake")
else:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_schema_lake as q
fixtures = _load(ROOT / "tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_projection_features.py", "_schema_lake_native_fixtures")
SOURCE = 'Authored schema fixture: preserve "quotes", backslash \\, newline\n and Unicode λ.'
CHECKPOINT = "a" * 64


def _output(domain):
    if domain == "legal_ir":
        return {"rules": [{"modality": "O", "actor": "Agency", "action": "retain", "object": "file",
                           "conditions": [], "exceptions": ["emergency"], "temporal": ["at least 20 days"]}]}
    target = {"security_ir": fixtures._security, "intent_ir": fixtures._intent, "ui_ux_ir": fixtures._ui}[domain](1).to_dict()
    selected = {"security_ir": "program.program_ir/v1", "intent_ir": "intent-route/norms/v1", "ui_ux_ir": "ui_ux_ir:flogic"}[domain]
    row = next(row for row in target["projections"] if row["projection_id"] == selected)
    return {key: row[key] for key in ("projection_id", "expression", *q.DESCRIPTOR_FIELDS)}


@pytest.mark.parametrize("domain", ("legal_ir", "security_ir", "intent_ir", "ui_ux_ir"))
def test_artifacts_are_typed_deterministic_and_do_not_claim_semantics(domain):
    output = _output(domain)
    artifact = q.build_schema_artifact(domain, output, source_text=SOURCE, checkpoint_sha256=CHECKPOINT)
    assert artifact == q.build_schema_artifact(domain, output, source_text=SOURCE, checkpoint_sha256=CHECKPOINT)
    assert "structure Record" in artifact["lean_source"]
    assert "def decodedInstance :" in artifact["lean_source"]
    assert "theorem" not in artifact["lean_source"] and "import " not in artifact["lean_source"]
    assert "Char.ofNat" in artifact["lean_source"]
    assert all(artifact[key] is False for key in q.FALSE)
    assert artifact["shape"]["scalar_encoding"]["float"] == "exact_ieee754_binary64_bits"
    assert artifact["source_binding_scope"].endswith("not_native_source_digest_or_semantic_fidelity")


@pytest.fixture(scope="module", params=("legal_ir", "security_ir", "intent_ir", "ui_ux_ir"))
def real_execution(request, tmp_path_factory):
    binary = Path.home() / ".elan/toolchains/leanprover--lean4---v4.26.0/bin/lake"
    if not binary.is_file():
        pytest.skip("required toolchain is not installed; no downloads")
    domain = request.param
    output = _output(domain)
    directory = tmp_path_factory.mktemp("schema-lake") / domain
    execution = q.validate_schema_output(domain, output, source_text=SOURCE, checkpoint_sha256=CHECKPOINT,
                                         output_directory=directory, timeout_seconds=60)
    return domain, output, execution


def test_actual_lake_build_each_domain_and_verify_exact_receipt(real_execution):
    domain, output, execution = real_execution
    result = q.verify_schema_execution(execution, domain, output, source_text=SOURCE, checkpoint_sha256=CHECKPOINT)
    assert result["schema_instance_typecheck_passed"], result
    assert result["backend_executed"] and result["command"][-2:] == ["build", "DecoderSchema"]
    assert result["returncode"] == 0 and not result["output_truncated"]
    assert all(result[key] is False for key in q.FALSE)
    assert "Built DecoderSchema" in (Path(result["directory"]) / "lake.log").read_text()
    assert "Lean version 4.26.0" in result["toolchain"]["version_output"]


def test_receipt_cannot_be_forged_rebound_or_mutated(real_execution):
    domain, output, execution = real_execution
    record = execution.to_dict()
    with pytest.raises(q.SchemaLakeError, match="actual in-process"):
        q.verify_schema_execution(record, domain, output, source_text=SOURCE, checkpoint_sha256=CHECKPOINT)
    constructed = q.SchemaLakeExecution(execution._bytes)
    with pytest.raises(q.SchemaLakeError, match="actual in-process"):
        q.verify_schema_execution(constructed, domain, output, source_text=SOURCE, checkpoint_sha256=CHECKPOINT)
    with pytest.raises(FrozenInstanceError):
        execution._bytes = b"{}"
    with pytest.raises(q.SchemaLakeError, match="different artifact"):
        q.verify_schema_execution(execution, domain, output, source_text=SOURCE + " changed", checkpoint_sha256=CHECKPOINT)
    with pytest.raises(q.SchemaLakeError, match="different artifact"):
        q.verify_schema_execution(execution, domain, output, source_text=SOURCE, checkpoint_sha256="b" * 64)
    record["schema_instance_typecheck_passed"] = False
    assert execution.to_dict()["schema_instance_typecheck_passed"]


def test_retained_source_and_missing_log_are_not_accepted(real_execution):
    domain, output, execution = real_execution
    directory = Path(execution.to_dict()["directory"])
    source = directory / "DecoderSchema.lean"
    original = source.read_bytes()
    try:
        source.write_bytes(original + b"\n-- tampered\n")
        with pytest.raises(q.SchemaLakeError, match="file changed"):
            q.verify_schema_execution(execution, domain, output, source_text=SOURCE, checkpoint_sha256=CHECKPOINT)
    finally:
        source.write_bytes(original)
    log = directory / "lake.log"
    data = log.read_bytes()
    try:
        log.unlink()
        with pytest.raises(q.SchemaLakeError, match="missing or invalid"):
            q.verify_schema_execution(execution, domain, output, source_text=SOURCE, checkpoint_sha256=CHECKPOINT)
    finally:
        log.write_bytes(data)


@pytest.mark.parametrize("domain", ("legal_ir", "security_ir", "intent_ir", "ui_ux_ir"))
def test_supplied_lean_and_extra_fields_reject_before_file_creation(domain, tmp_path):
    output = _output(domain)
    output["lean_source"] = "theorem fake : True := by trivial"
    directory = tmp_path / "must-not-exist"
    with pytest.raises(q.SchemaLakeError):
        q.validate_schema_output(domain, output, source_text=SOURCE, checkpoint_sha256=CHECKPOINT, output_directory=directory)
    assert not directory.exists()


@pytest.mark.parametrize("domain", ("security_ir", "intent_ir", "ui_ux_ir"))
def test_unknown_family_projection_or_producer_rejects(domain):
    for key, value in (("logic_family", "not-a-family"), ("projection_id", "unimplemented/v1"), ("producer_id", "unverified")):
        output = _output(domain)
        output[key] = value
        with pytest.raises(q.SchemaLakeError):
            q.build_schema_artifact(domain, output, source_text=SOURCE, checkpoint_sha256=CHECKPOINT)


@pytest.mark.parametrize("change", ["missing", "unknown", "wrong_type", "unsorted"])
def test_legal_facets_never_normalize_or_disappear(change):
    output = _output("legal_ir")
    rule = output["rules"][0]
    if change == "missing":
        del rule["exceptions"]
    elif change == "unknown":
        rule["invented"] = "x"
    elif change == "wrong_type":
        rule["actor"] = False
    else:
        rule["conditions"] = ["z", "a"]
    with pytest.raises(q.SchemaLakeError):
        q.build_schema_artifact("legal_ir", output, source_text=SOURCE, checkpoint_sha256=CHECKPOINT)


def test_native_record_types_null_missing_and_arrays_are_explicit():
    renderer = q._Renderer()
    kind, value = renderer.render({"array": [1, True, None, "x", -0.0], "empty": [], "null": None})
    declarations = "\n".join(renderer.declarations)
    assert "inductive Choice" in declarations
    assert "Int" in declarations and "Bool" in declarations and "AbsentValue" in declarations
    assert str(struct.unpack(">Q", struct.pack(">d", -0.0))[0]) in value
    record = next(row for row in renderer.schemas if row["lean_type"] == kind)
    assert [row["source_field"] for row in record["fields"]] == ["array", "empty", "null"]
    assert record["missing_fields"] == "not_materialized_or_defaulted"


def test_legal_qualifier_types_do_not_depend_on_empty_lists():
    first = _output("legal_ir")
    second = copy.deepcopy(first)
    second["rules"][0]["conditions"] = ["authorized"]
    second["rules"][0]["exceptions"] = []
    a = q.build_schema_artifact("legal_ir", first, source_text=SOURCE, checkpoint_sha256=CHECKPOINT)
    b = q.build_schema_artifact("legal_ir", second, source_text=SOURCE, checkpoint_sha256=CHECKPOINT)
    assert a["shape_sha256"] == b["shape_sha256"]
    assert a["input_sha256"] != b["input_sha256"]


def test_checkpoint_digest_is_inert_and_cannot_load_a_path(tmp_path):
    with pytest.raises(q.SchemaLakeError, match="paths are not accepted"):
        q.build_schema_artifact("legal_ir", _output("legal_ir"), source_text=SOURCE, checkpoint_sha256=str(tmp_path / "model.json"))
    with pytest.raises(TypeError):
        q.validate_schema_output("legal_ir", _output("legal_ir"), source_text=SOURCE,
            checkpoint_sha256=CHECKPOINT, output_directory=tmp_path / "x", passed=True)


def test_imported_producer_source_drift_rejects_without_editing_live_files(monkeypatch):
    original = Path.read_bytes
    target = Path(native_formal_decoder.__file__).resolve()
    def changed(path):
        raw = original(path)
        return raw + b"\n# simulated concurrent source edit\n" if path.resolve() == target else raw
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(q.SchemaLakeError, match="source or executed code changed"):
        q.build_schema_artifact("legal_ir", _output("legal_ir"), source_text=SOURCE, checkpoint_sha256=CHECKPOINT)


def test_wrong_import_tree_cannot_nominate_itself_as_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(q.tree_pin, "workspace_root", lambda: tmp_path)
    with pytest.raises(q.SchemaLakeError, match="outside canonical workspace"):
        q.build_schema_artifact("legal_ir", _output("legal_ir"), source_text=SOURCE, checkpoint_sha256=CHECKPOINT)


def test_first_observation_rejects_already_imported_stale_function(tmp_path, monkeypatch):
    source = tmp_path / "owned.py"
    source.write_text("def own():\n    return 1\n")
    module = _load(source, "_schema_lake_stale_import_fixture")
    source.write_text("def own():\n    return 2\n")
    monkeypatch.setattr(q, "_workspace", lambda: tmp_path)
    with pytest.raises(q.SchemaLakeError, match="loaded producer code differs"):
        q._pin_imported_module(module)
