"""Authored header controls and optional exact permitted public Bottle source."""
from copy import deepcopy
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.security_ir import code_header_derivation as api
from ipfs_datasets_py.logic.security_ir import doctor_header_contracts as contracts
from ipfs_datasets_py.logic.security_ir.model import SecurityIR
from ipfs_datasets_py.logic.backends.smt.compiler import SmtObligation, SoftwareVerificationSMTCompiler

PROTOCOL = contracts.WsgiHeaderProtocolContract("authored-protocol-role-review", "respond")
PROGRAM = '''# Independently authored source; never executed by the adapter.
def convert(raw, encoding='utf8', errors='strict'):
    if isinstance(raw, (bytes, bytearray)):
        return str(raw, encoding, errors)
    return '' if raw is None else str(raw)

def clean_label(raw):
    label = convert(raw)
    return label.title().replace('_', '-')

def clean_payload(raw):
    payload = convert(raw)
    return payload

class WireResponse:
    def put(self, label, payload):
        self._values[clean_label(label)] = [clean_payload(payload)]

    @property
    def fields_for_wire(self):
        pairs = list(self._values.items())
        return [(label, value) for label, values in pairs for value in values]

def application(environ, respond):
    response = WireResponse()
    respond('200 OK', response.fields_for_wire)
'''


def derive(source=PROGRAM):
    return api.derive_header_semantics(source_bytes=source.encode(), source_path="headers.py", protocol=PROTOCOL)


def test_native_source_bound_targets_and_exact_replay():
    report = derive()
    assert report["status"] == "modeled" and not report["unsupported"]
    assert report["formula_count"] == 12 and report["smt_obligation_count"] == 6
    assert [row["symbol"] for row in report["modeled_symbols"]] == ["clean_label", "clean_payload"]
    assert [row["normalization_ops"] for row in report["modeled_symbols"]] == [["title", "replace_underscore_hyphen"], ["identity"]]
    for row in report["modeled_symbols"]:
        span = row["source_span"]
        assert hashlib.sha256(PROGRAM.encode()[span["start_byte"]:span["end_byte"]]).hexdigest() == span["sha256"]
        assert not row["guarded"]
    native = report["native_targets"]
    assert SecurityIR.from_dict(native["declaration"]).cid == native["declaration_cid"]
    for target in report["smt_targets"]:
        compiled = SoftwareVerificationSMTCompiler().compile(SmtObligation.from_dict(target["obligation"]))
        assert compiled.to_dict() == target["compilation"]
        assert "str.contains" in compiled.smtlib
    assert api.validate_header_semantics(json.loads(json.dumps(report)), source_bytes=PROGRAM.encode(),
        source_path="headers.py", protocol=PROTOCOL) == report
    assert report["provider_calls"] == report["solver_calls"] == report["learned_formula_count"] == 0
    assert not any(report[field] for field in ("proof_authority", "mutation_authority", "completion_authority",
        "source_semantics_verified", "whole_program_proved", "executes_source"))
    assert "normalization_terminates_and_preserves_NUL_LF_CR_membership" in report["assumptions"]


@pytest.mark.parametrize("mutation", ["source", "path", "protocol", "guard", "formula", "authority", "bool_alias"])
def test_stale_or_forged_derivation_rejected_before_solver(mutation, monkeypatch):
    report = derive()
    source, path, protocol = PROGRAM.encode(), "headers.py", PROTOCOL
    if mutation == "source":
        source += b"# changed bytes\n"
    elif mutation == "path":
        path = "other.py"
    elif mutation == "protocol":
        protocol = contracts.WsgiHeaderProtocolContract("different-review", "respond")
    elif mutation == "guard":
        report["modeled_symbols"][0]["guarded"] = True
    elif mutation == "formula":
        report["smt_targets"][0]["obligation"]["goal"] = {"kind": "true"}
    elif mutation == "authority":
        report["proof_authority"] = True
    else:
        report["proof_authority"] = 0
    monkeypatch.setattr(api.shutil, "which", lambda *a: pytest.fail("forged report reached solver lookup"))
    with pytest.raises(ValueError, match="current source"):
        api.check_header_semantics(report, source_bytes=source, source_path=path, protocol=protocol)


@pytest.mark.parametrize("source,reason", [
    (PROGRAM.replace("label.title()", "label.strip()"), "unsupported_normalizer_or_conversion_shape"),
    (PROGRAM.replace("convert(raw)", "convert(raw=raw)"), "unsupported_normalizer_or_conversion_shape"),
    (PROGRAM.replace("def clean_payload(raw):", "def clean_payload(raw='default'):"), "unsupported_normalizer_or_conversion_shape"),
    (PROGRAM.replace("def clean_payload(raw):", "def clean_payload(raw: str):"), "normalizer_annotations_not_modeled"),
    (PROGRAM.replace("def clean_payload(raw):", "@decorate\ndef clean_payload(raw):"), "unsupported_normalizer_or_conversion_shape"),
    ("str = dangerous\n" + PROGRAM, "unsupported_normalizer_or_conversion_shape"),
    (PROGRAM.replace("return payload\n", "payload = other\n    return payload\n"), "unsupported_normalizer_or_conversion_shape"),
    (PROGRAM.replace("\n", "\r\n"), "unsupported_source_line_control"),
])
def test_unsupported_shapes_do_not_emit_formal_targets(source, reason):
    report = derive(source)
    assert report["status"] == "unsupported" and report["unsupported"] == [reason]
    assert report["native_targets"] is None and not report["smt_targets"]
    assert report["formula_count"] == report["smt_obligation_count"] == 0


def test_solver_optional_and_protocol_required():
    report = derive()
    check = api.check_header_semantics(report, source_bytes=PROGRAM.encode(), source_path="headers.py",
        protocol=PROTOCOL, z3_executable="this-header-solver-is-not-installed")
    assert check["status"] == "solver_unavailable" and check["solver_calls"] == 0
    with pytest.raises(TypeError):
        api.derive_header_semantics(source_bytes=PROGRAM.encode(), source_path="headers.py", protocol=None)
    with pytest.raises(ValueError):
        api.derive_header_semantics(source_bytes=PROGRAM.encode(), source_path="../headers.py", protocol=PROTOCOL)


@pytest.mark.parametrize("kind", ["admission_timeout", "query_timeout", "cancelled", "os_error", "missing_executable"])
def test_leased_checker_preserves_native_failure_cause_without_fallback_probe(monkeypatch, kind):
    from ipfs_datasets_py.logic.security_ir import bounded_header_checker as bounded
    from ipfs_datasets_py.logic.backends.smt import differential

    failure = (bounded.LeaseCancelledError("authored cancellation") if kind == "cancelled"
        else OSError("authored process failure") if kind == "os_error"
        else FileNotFoundError("authored removed executable") if kind == "missing_executable"
        else bounded.LeaseTimeoutError("authored deadline"))
    diagnostic = dict(schema="bounded-header-checker-failure@1",
        phase="child_admission" if kind == "admission_timeout" else "query",
        reason=kind if kind != "query_timeout" else "deadline")
    failure.header_checker_diagnostic = diagnostic
    if kind == "admission_timeout":
        failure.admission_observation = {"schema": "resource-admission-observation@1", "primary_gate": "memory_pressure"}
    calls = []

    def run(*args):
        calls.append(args)
        raise failure

    def forbidden_probe(*args, **kwargs):
        pytest.fail("leased failure attempted an unowned version subprocess")

    monkeypatch.setattr(api.shutil, "which", lambda value: "/usr/bin/true")
    monkeypatch.setattr(bounded, "bounded_header_runner", lambda *args, **kwargs: run)
    monkeypatch.setattr(differential.subprocess, "run", forbidden_probe)
    with pytest.raises(bounded.BoundedHeaderCheckerError) as error:
        api.check_header_semantics(derive(), source_bytes=PROGRAM.encode(), source_path="headers.py",
            protocol=PROTOCOL, timeout_seconds=20., parent_lease=object())
    assert len(calls) == 1
    assert error.value.__cause__ is failure
    assert error.value.header_checker_diagnostic == diagnostic
    if kind == "admission_timeout":
        assert error.value.__cause__.admission_observation is failure.admission_observation


def test_leased_inconclusive_result_cannot_trigger_unowned_version_probe(monkeypatch):
    from ipfs_datasets_py.logic.security_ir import bounded_header_checker as bounded
    from ipfs_datasets_py.logic.backends.smt import differential

    monkeypatch.setattr(api.shutil, "which", lambda value: "/usr/bin/true")
    monkeypatch.setattr(bounded, "bounded_header_runner", lambda *args, **kwargs:
        lambda *args: differential.SmtRawSolverOutput(timed_out=True, returncode=None))
    monkeypatch.setattr(differential.subprocess, "run", lambda *args, **kwargs:
        pytest.fail("leased inconclusive result attempted an unowned version subprocess"))
    result = api.check_header_semantics(derive(), source_bytes=PROGRAM.encode(), source_path="headers.py",
        protocol=PROTOCOL, timeout_seconds=20., parent_lease=object())
    assert result["status"] == "model_check_inconclusive_or_mismatch"
    assert all(row["solver_answer"] == "unknown" and row["solver_version"] == ""
        for row in result["results"])
    assert not result["proof_authority"] and not result["completion_authority"]


@pytest.mark.parametrize("timeout", [True, 0, -1, float("inf"), float("nan"), 301, "1"])
def test_invalid_deadline_cannot_reach_derivation_or_solver(monkeypatch, timeout):
    monkeypatch.setattr(api, "validate_header_semantics", lambda *a, **k:
        pytest.fail("invalid budget reached source derivation"))
    with pytest.raises(ValueError, match="deadline"):
        api.check_header_semantics({}, source_bytes=PROGRAM.encode(), source_path="headers.py",
            protocol=PROTOCOL, timeout_seconds=timeout)


def test_lease_requires_deadline_and_native_lease_type(monkeypatch):
    from ipfs_datasets_py.logic.security_ir import bounded_header_checker as bounded
    with pytest.raises(ValueError, match="aggregate deadline"):
        api.check_header_semantics({}, source_bytes=PROGRAM.encode(), source_path="headers.py",
            protocol=PROTOCOL, parent_lease=object())
    monkeypatch.setattr(api.shutil, "which", lambda value: "/usr/bin/true")
    with pytest.raises(TypeError, match="native datasets parent lease"):
        api.check_header_semantics(derive(), source_bytes=PROGRAM.encode(), source_path="headers.py",
            protocol=PROTOCOL, timeout_seconds=10, parent_lease=object())


def test_precancelled_check_never_rebuilds_or_dispatches(monkeypatch):
    import threading
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(api, "validate_header_semantics", lambda *a, **k:
        pytest.fail("cancelled request reached source derivation"))
    with pytest.raises(InterruptedError, match="cancelled"):
        api.check_header_semantics({}, source_bytes=PROGRAM.encode(), source_path="headers.py",
            protocol=PROTOCOL, timeout_seconds=10, cancel_event=cancel)


def test_all_obligations_share_one_decreasing_deadline(monkeypatch):
    from types import SimpleNamespace
    from ipfs_datasets_py.logic.security_ir import bounded_header_checker as bounded
    from ipfs_datasets_py.logic.backends.smt.differential import SmtRawSolverOutput
    clock = SimpleNamespace(now=100.)
    monkeypatch.setattr(api, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(api.shutil, "which", lambda value: "/usr/bin/true")
    limits = []
    def run(script, bounds):
        limits.append(bounds.timeout_ms)
        clock.now += 1
        return SmtRawSolverOutput(stdout="unknown\n", solver_version="authored clock control")
    monkeypatch.setattr(bounded, "bounded_header_runner", lambda *a, **k: run)
    with pytest.raises(TimeoutError, match="deadline expired"):
        api.check_header_semantics(derive(), source_bytes=PROGRAM.encode(), source_path="headers.py",
            protocol=PROTOCOL, timeout_seconds=2.5, parent_lease=object())
    assert limits == [2500, 1500, 500]


@pytest.mark.parametrize("drift", ["bytes", "selected_path"])
def test_leased_executable_drift_cannot_produce_checked_receipt(monkeypatch, tmp_path, drift):
    from ipfs_datasets_py.logic.security_ir import bounded_header_checker as bounded
    from ipfs_datasets_py.logic.backends.smt.differential import SmtRawSolverOutput
    selected = [tmp_path / "solver"]
    selected[0].write_bytes(b"authored solver identity")
    monkeypatch.setattr(api.shutil, "which", lambda value: str(selected[0]))
    def run(*args):
        if drift == "bytes":
            selected[0].write_bytes(b"changed solver identity")
        else:
            replacement = tmp_path / "other-solver"
            replacement.write_bytes(selected[0].read_bytes())
            selected[0] = replacement
        return SmtRawSolverOutput(stdout="unknown\n", solver_version="authored drift control")
    monkeypatch.setattr(bounded, "bounded_header_runner", lambda *a, **k: run)
    with pytest.raises(bounded.BoundedHeaderCheckerError, match="executable changed"):
        api.check_header_semantics(derive(), source_bytes=PROGRAM.encode(), source_path="headers.py",
            protocol=PROTOCOL, timeout_seconds=10, parent_lease=object())


@pytest.mark.parametrize("guarded", [False, True])
def test_real_leased_z3_checks_all_source_bound_obligations(guarded):
    from tests.unit.logic.security_ir.test_bounded_header_checker_native import AuthoredParent
    from ipfs_datasets_py.logic.security_ir.bounded_header_checker import HEADER_EXECUTION_PROFILE
    z3 = shutil.which("z3")
    assert z3 is not None, "native bounded integration qualification requires installed Z3"
    source = PROGRAM
    if guarded:
        source = contracts.analyze_http_header_contracts(source, protocol=PROTOCOL).candidate.source
    parent = AuthoredParent()
    report = derive(source)
    check = api.check_header_semantics(report, source_bytes=source.encode(), source_path="headers.py",
        protocol=PROTOCOL, z3_executable=z3, timeout_seconds=30, parent_lease=parent)
    assert check["execution_profile"] == HEADER_EXECUTION_PROFILE
    assert check["solver_executable_sha256"] == hashlib.sha256(Path(z3).read_bytes()).hexdigest()
    assert check["status"] == "checked_local_model"
    assert check["solver_calls"] == parent.release_count == len(report["smt_targets"]) == 6
    assert all(row["matches_model_expectation"] and row["solver_version"] for row in check["results"])
    assert not any(check[key] for key in ("proof_authority", "completion_authority",
        "mutation_authority", "source_semantics_verified", "whole_program_proved"))


def test_unicode_comment_does_not_change_byte_span_geometry():
    source = "# é\u2028line\u2029not-an-AST-line\n" + PROGRAM
    report = derive(source)
    assert report["status"] == "modeled"
    for row in report["modeled_symbols"]:
        span = row["source_span"]
        body = source.encode()[span["start_byte"]:span["end_byte"]]
        assert body.startswith(("def " + row["symbol"]).encode())
        assert hashlib.sha256(body).hexdigest() == span["sha256"]


@pytest.mark.skipif(shutil.which("z3") is None, reason="real optional Z3 unavailable")
@pytest.mark.parametrize("guarded", [False, True])
def test_real_z3_distinguishes_original_and_guarded_local_behavior(guarded):
    source = PROGRAM
    if guarded:
        candidate = contracts.analyze_http_header_contracts(source, protocol=PROTOCOL).candidate
        assert contracts.verify_header_candidate(source, candidate)
        source = candidate.source
    report = derive(source)
    assert all(row["guarded"] is guarded for row in report["modeled_symbols"])
    check = api.check_header_semantics(report, source_bytes=source.encode(), source_path="headers.py", protocol=PROTOCOL)
    assert check["status"] == "checked_local_model" and check["solver_calls"] == 6
    for result in check["results"]:
        expected = "unsat" if guarded or result["kind"] == "safe_normalization_preserved" else "sat"
        assert result["solver_answer"] == expected
        assert result["solver_version"] and result["script_sha256"]
        assert result["unsat_core"] if expected == "unsat" else result["model_text"]
    assert not check["source_semantics_verified"] and not check["whole_program_proved"]


def test_datasets_only_imports_without_accelerate_attempts():
    script = '''import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, *args):
        if name.startswith('ipfs_accelerate_py'):
            raise AssertionError('consumer import attempted: '+name)
sys.meta_path.insert(0, Block())
from ipfs_datasets_py.logic.security_ir.code_header_derivation import derive_header_semantics, WsgiHeaderProtocolContract
r=derive_header_semantics(source_bytes=SOURCE.encode(),source_path='headers.py',protocol=WsgiHeaderProtocolContract('authored','respond'))
assert r['status']=='modeled'
'''.replace("SOURCE", repr(PROGRAM))
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)


def test_independent_candidate_ast_admission_and_deterministic_compiler_attribution():
    node = next(node for node in ast.parse(PROGRAM).body if isinstance(node, ast.FunctionDef) and node.name == "clean_label")
    candidate = ast.unparse(node)
    receipt = api.validate_header_candidate_function(source_bytes=PROGRAM.encode(), source_path="headers.py",
        protocol=PROTOCOL, symbol="clean_label", candidate_function_source=candidate)
    assert receipt["candidate_ast_matches_source"] and not receipt["candidate_producer_verified"]
    assert receipt["native_derivation"] == derive()
    assert receipt["compiler_attribution"] == "deterministic native header model"
    for altered in (candidate.replace(".title()", ".lower()"), candidate + "\nraise RuntimeError()",
                    candidate.replace("clean_label", "other"), candidate.replace("convert(raw)", "convert(secret=raw)")):
        with pytest.raises(ValueError, match="candidate"):
            api.validate_header_candidate_function(source_bytes=PROGRAM.encode(), source_path="headers.py",
                protocol=PROTOCOL, symbol="clean_label", candidate_function_source=altered)


PUBLIC_BOTTLE_PATH = os.environ.get("IPFS_DATASETS_PUBLIC_BOTTLE_FIXTURE", "").strip()
PUBLIC_BOTTLE = Path(PUBLIC_BOTTLE_PATH) if PUBLIC_BOTTLE_PATH else None


@pytest.mark.skipif(
    PUBLIC_BOTTLE is None or not PUBLIC_BOTTLE.is_file(),
    reason="set IPFS_DATASETS_PUBLIC_BOTTLE_FIXTURE to the exact permitted public input",
)
def test_exact_permitted_public_bottle_header_symbols_are_modeled():
    raw = PUBLIC_BOTTLE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "761756ce31753e526c48d28ccbca13a5d2493b16fe37aff3e1e4d2efaf3a2bba"
    protocol = contracts.WsgiHeaderProtocolContract("benchmark public WSGI source review")
    report = api.derive_header_semantics(source_bytes=raw, source_path="bottle.py", protocol=protocol)
    assert report["status"] == "modeled"
    assert [(r["symbol"], r["line"]) for r in report["modeled_symbols"]] == [("_hkey", 1560), ("_hval", 1565)]
    assert report["formula_count"] == 12 and report["learned_formula_count"] == 0
