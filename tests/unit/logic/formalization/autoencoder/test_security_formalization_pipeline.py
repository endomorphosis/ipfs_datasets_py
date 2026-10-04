"""Actual learned predictions joined to independently checked source models."""
import hashlib
import json

import pytest

from tests.unit.logic.formalization.autoencoder.test_security_formula_decoder import formula_checkpoint
from tests.unit.logic.security_ir.test_code_header_derivation import PROGRAM
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formalization_pipeline as api

PROTOCOL = {"review_ref": "authored-protocol-role-review", "callback_parameter": "respond"}


def inputs(tmp_path, source=PROGRAM):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "headers.py").write_text(source)
    ledger = {"headers.py": hashlib.sha256((repository / "headers.py").read_bytes()).hexdigest()}
    return repository, ledger


def test_real_learned_headers_need_source_binding_and_disappear_in_model_off(tmp_path, formula_checkpoint):
    repository, ledger = inputs(tmp_path)
    enabled = api.run_security_formalization_pipeline(repository=repository, source_hashes=ledger,
        decoder=formula_checkpoint, protocol=PROTOCOL, output=tmp_path / "enabled")
    report = api.validate_security_formalization_pipeline(repository=repository, receipt=enabled)
    assert report["summary"]["learned_accepted_functions"] == 2
    assert report["summary"]["learned_formula_count"] == 6
    assert report["summary"]["deterministic_header_formula_count"] == 12
    assert report["summary"]["all_functions_retained"]
    assert report["summary"]["learned_abstained_functions"] > 0
    assert not report["summary"]["whole_program_semantics_verified"]
    for row in report["function_results"]:
        if row.get("learned_header"):
            assert row["learned"]["validation"]["source_AST_equivalent"]
            assert row["learned"]["learned_formula_count"] == 0
            assert len(row["learned_header"]["targets"]) == 3
    disabled = api.run_security_formalization_pipeline(repository=repository, source_hashes=ledger,
        decoder=formula_checkpoint, protocol=PROTOCOL, output=tmp_path / "disabled", model_enabled=False)
    control = api.validate_security_formalization_pipeline(repository=repository, receipt=disabled)
    assert control["header_models"] == report["header_models"]
    assert [row["derivation"] for row in control["function_results"]] == [row["derivation"] for row in report["function_results"]]
    assert control["summary"]["learned_formula_count"] == 0
    assert not control["summary"]["learned_formula_generation_passed"]


def test_missing_protocol_keeps_source_candidates_out_of_formula_totals(tmp_path, formula_checkpoint):
    repository, ledger = inputs(tmp_path)
    result = api.run_security_formalization_pipeline(repository=repository, source_hashes=ledger,
        decoder=formula_checkpoint, output=tmp_path / "unreviewed")
    assert result["summary"]["learned_formula_count"] == 0
    assert not result["summary"]["learned_formula_generation_passed"]


@pytest.mark.parametrize("damage", ["count", "omit", "source"])
def test_replay_rejects_stale_source_or_rehashed_fabricated_coverage(tmp_path, formula_checkpoint, damage):
    repository, ledger = inputs(tmp_path, "def transform(value):\n    return (value - 4) * (value + 3)\n")
    receipt = api.run_security_formalization_pipeline(repository=repository, source_hashes=ledger,
        decoder=formula_checkpoint, output=tmp_path / "observations")
    path = tmp_path / "observations/formalization.json"
    report = json.loads(path.read_bytes())
    if damage == "source":
        (repository / "headers.py").write_text("def transform(value):\n    return value + 3\n")
    else:
        if damage == "count":
            report["summary"]["learned_formula_count"] += 1
        else:
            report["function_results"] = []
        value = {key: item for key, item in report.items() if key != "report_cid"}
        report["report_cid"] = api._cid(value)
        raw = api.portable._json(report)
        path.chmod(0o600)
        path.write_bytes(raw)
        receipt.update(report_sha256=hashlib.sha256(raw).hexdigest(), report_cid=report["report_cid"], summary=report["summary"])
    with pytest.raises(ValueError):
        api.validate_security_formalization_pipeline(repository=repository, receipt=receipt)


def test_unsupported_source_file_is_a_coverage_gap(tmp_path, formula_checkpoint):
    repository, ledger = inputs(tmp_path, "def f(x):\r\n    return x\r\n")
    result = api.run_security_formalization_pipeline(repository=repository, source_hashes=ledger,
        decoder=formula_checkpoint, output=tmp_path / "unsupported")
    assert result["summary"]["unsupported_file_count"] == 1
    assert not result["summary"]["all_functions_retained"]
    assert not result["summary"]["all_functions_have_learned_candidates"]
