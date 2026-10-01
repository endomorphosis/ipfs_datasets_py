"""Non-LLM derivation uses strict AST admission and never executes code."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import CodeUnit
from ipfs_datasets_py.logic.security_ir import code_program_derivation as api
from ipfs_datasets_py.logic.software_verification.source_adapters import SourceAdapterStatus


def unit(source, language="Python"):
    raw = source.encode("utf-8")
    root = canonical_identity({"fixture": "authored-code-program"}, domain="authored", schema_version="v1").cid
    body_cid = canonical_identity({"body": source}, domain="cvefixes-security-ir/code-body",
                                  schema_version="cvefixes-code-body/v1").cid
    return CodeUnit(source_cids=(root,), parent_cids=(root,), config_cid=root,
        unit_kind="symbol", language=language, path="src/f.py", polarity="fixed",
        payload={"body_cid": body_cid, "body_sha256": hashlib.sha256(raw).hexdigest()}), raw


@pytest.mark.parametrize("source", [
    "def f(x):\n    y = x + 1\n    return y * 2\n",
    "def f():\n    return 42\n",
    "def f(x, y):\n    a = -x\n    b = +y\n    return a - b\n",
    "def f(x):\n\ty = (x +\n\t     1)\n\treturn y\n",
])
def test_actual_native_derivation_rebinds_exact_source_and_spans(source):
    code_unit, raw = unit(source)
    result = api.derive_code_program(code_unit=code_unit, source_bytes=raw)
    assert result["status"] == "derived", result["unsupported"]
    target = result["projection"]["targets"][0]
    assert target["kind"] == "program" and target["family_id"] == "program"
    assert result["native_adapter"]["status"] == "success"
    remap = result["source_remapping"]
    assert remap["from_source"]["content_sha256"] == remap["to_source"]["content_sha256"] == hashlib.sha256(raw).hexdigest()
    assert remap["to_source"]["ref_id"] == code_unit.cid
    assert remap["before_program_id"] != remap["after_program_id"]
    assert remap["byte_spans"]
    for span in remap["byte_spans"]:
        assert span["span_sha256"] == hashlib.sha256(raw[span["start_byte"]:span["end_byte"]]).hexdigest()
    assert result["solver_calls"] == result["provider_calls"] == 0
    assert not result["source_semantics_verified"] and not result["proof_authority"]
    assert not result["executes_source"] and not result["security_specification_inferred"]
    assert "any" in result["assumptions"]["native_parameter_and_result_types"]
    assert api.validate_code_program_derivation(json.loads(json.dumps(result)), code_unit=code_unit, source_bytes=raw) == result


@pytest.mark.parametrize("source", [
    "def f(x):\n    return g(secret=x)\n",
    "def f(x=g()):\n    return x\n",
    "def f(x):\n    if x:\n        return x\n    return 0\n",
    "def f(x):\n    y = x + 1\n    y = y + 1\n    return y\n",
    "def f(x):\n    x = x + 1\n    return x\n",
    "def f(x):\n    while x:\n        x -= 1\n    return x\n",
    "def f(x):\n    return global_name\n",
    "def f(x):\n    return x / 2\n",
    "def f(x):\n    return x and 1\n",
    "def f(x):\n    return x.attr\n",
    "def f(x):\n    return x[0]\n",
    "def f(x):\n    y = z + 1\n    return y\n",
    "def f(x):\n    return True\n",
    "def f(x):\n    return 1.5\n",
    "def f(x):\n    return\n",
    "def f(x):\n    return x\n    return x + 1\n",
    "def f(x, x):\n    return x\n",
    "def f(x: int):\n    return x\n",
    "@decorator\ndef f(x):\n    return x\n",
    "def f(*x):\n    return 1\n",
    "import dangerous\ndef f(x):\n    return x\n",
    "def f(x):\n    return x\ndef g(x):\n    return x\n",
    "async def f(x):\n    return x\n",
    "def f(x):\n    return x # \u00e9\n",
    "def f(x):\n    \freturn x\n",
    "def f(x):\r\n    return x\r\n",
    "def f(x):\n    y = x # type: int\n    return y\n",
])
def test_unsupported_syntax_never_reaches_native_lowerer(source, monkeypatch):
    code_unit, raw = unit(source)
    monkeypatch.setattr(api, "adapt_source_to_software_verification", lambda *a, **k: pytest.fail("rejected source reached lowerer"))
    result = api.derive_code_program(code_unit=code_unit, source_bytes=raw)
    assert result["status"] == "unsupported" and result["unsupported"]
    assert result["projection"] is result["source_remapping"] is result["native_adapter"] is None


def test_native_partial_and_silent_structural_change_fail_closed(monkeypatch):
    code_unit, raw = unit("def f(x):\n    return x + 1\n")
    original = api.adapt_source_to_software_verification(raw.decode(), path=code_unit.path, language="python")
    monkeypatch.setattr(api, "adapt_source_to_software_verification", lambda *a, **k: replace(original, status=SourceAdapterStatus.PARTIAL))
    result = api.derive_code_program(code_unit=code_unit, source_bytes=raw)
    assert result["status"] == "unsupported" and result["unsupported"][0]["reason"] == "native_adapter_not_complete"
    expressions = tuple(replace(expr, operator="sub") if expr.operator == "add" else expr for expr in original.program.expressions)
    changed = replace(original.program, expressions=expressions, program_id="")
    monkeypatch.setattr(api, "adapt_source_to_software_verification", lambda *a, **k: replace(original, program=changed))
    result = api.derive_code_program(code_unit=code_unit, source_bytes=raw)
    assert result["status"] == "unsupported" and result["unsupported"][0]["reason"] == "native_expression_structure_changed"


@pytest.mark.parametrize("change", ["same_name_wrong_binding", "expression_type", "parameter_type"])
def test_native_binding_and_type_drift_fail_closed(monkeypatch, change):
    code_unit, raw = unit("def f(result):\n    return result\n")
    original = api.adapt_source_to_software_verification(raw.decode(), path=code_unit.path,
        language="python", include_supervisor_evidence=False)
    program = original.program
    if change == "same_name_wrong_binding":
        expressions = tuple(replace(expr, symbol_ids=(program.functions[0].result_symbol_id,))
            if expr.kind.value == "symbol" else expr for expr in program.expressions)
        program = replace(program, expressions=expressions, program_id="")
    elif change == "expression_type":
        program = replace(program, expressions=tuple(replace(expr, type_ref="boolean")
            for expr in program.expressions), program_id="")
    else:
        program = replace(program, symbols=tuple(replace(symbol, type_ref="integer")
            if symbol.kind.value == "parameter" else symbol for symbol in program.symbols), program_id="")
    monkeypatch.setattr(api, "adapt_source_to_software_verification", lambda *a, **k: replace(original, program=program))
    result = api.derive_code_program(code_unit=code_unit, source_bytes=raw)
    assert result["status"] == "unsupported" and result["projection"] is None
    assert result["unsupported"][0]["reason"] in {"native_expression_structure_changed",
        "native_expression_type_changed", "native_symbol_scope_changed"}


def test_missing_stale_and_resource_bounded_sources():
    code_unit, raw = unit("def f(x):\n    return x\n")
    result = api.derive_code_program(code_unit=code_unit, source_bytes=None)
    assert result["status"] == "quarantined" and result["projection"] is None
    with pytest.raises(ValueError, match="SHA differs"):
        api.derive_code_program(code_unit=code_unit, source_bytes=raw + b"\n")
    for source in ("#" * 65_537, "def f():\n    return " + str(2**65) + "\n"):
        code_unit, raw = unit(source)
        assert api.derive_code_program(code_unit=code_unit, source_bytes=raw)["status"] == "unsupported"


@pytest.mark.parametrize("change", ["authority", "span", "program", "assumption"])
def test_replay_rejects_tampered_derivation(change):
    code_unit, raw = unit("def f(x):\n    return x + 1\n")
    result = deepcopy(api.derive_code_program(code_unit=code_unit, source_bytes=raw))
    if change == "authority": result["proof_authority"] = True
    elif change == "span": result["source_remapping"]["byte_spans"][0]["start_byte"] += 1
    elif change == "program": result["projection"]["targets"][0]["native_document"]["functions"][0]["name"] = "other"
    else: result["assumptions"]["modeled_argument_type"] = "proved integers"
    with pytest.raises(api.CodeProgramDerivationError, match="identity or content"):
        api.validate_code_program_derivation(result, code_unit=code_unit, source_bytes=raw)


def test_profile_limits_apply_without_an_accelerate_provider():
    profile = api.describe_code_program_derivation_profile()
    assert profile["max_ast_nodes"] == 512 and profile["target_kind"] == "program"
    assert profile["provider_calls"] == profile["solver_calls"] == 0
    assert not profile["security_specification_inferred"] and not profile["source_semantics_verified"]


def test_native_optional_consumer_evidence_default_compatibility(monkeypatch):
    from ipfs_datasets_py.logic.software_verification import source_adapters as native
    calls = []
    monkeypatch.setattr(native, "_load_program_ast_adapter", lambda: (calls.append("loaded") or (None, None)))
    raw = "def f(x):\n    return x + 1\n"
    default = native.adapt_source_to_software_verification(raw, path="f.py")
    assert calls == ["loaded"]
    calls.clear()
    isolated = native.SourceSoftwareVerificationAdapter(include_supervisor_evidence=False).adapt(raw, path="f.py")
    assert calls == [] and isolated.program.to_dict() == default.program.to_dict()
    with pytest.raises(ValueError, match="must be a boolean"):
        native.adapt_source_to_software_verification(raw, include_supervisor_evidence=0)


def test_guarded_derivation_never_attempts_consumer_import():
    import subprocess
    import sys
    from pathlib import Path
    script = '''
import importlib.abc, sys
attempts=[]
class ConsumerBlock(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == 'ipfs_accelerate_py' or fullname.startswith('ipfs_accelerate_py.'):
            attempts.append(fullname)
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, ConsumerBlock())
from tests.unit.logic.security_ir.test_code_program_derivation import unit
from ipfs_datasets_py.logic.security_ir.code_program_derivation import derive_code_program
code_unit, raw = unit('def f(x):\\n    return x + 1\\n')
assert derive_code_program(code_unit=code_unit, source_bytes=raw)['status'] == 'derived'
assert not attempts, attempts
assert not any(name == 'ipfs_accelerate_py' or name.startswith('ipfs_accelerate_py.') for name in sys.modules)
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[4],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
