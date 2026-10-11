"""Independent authored fixtures for opt-in numerical source structure.

These are syntax/provenance tests, not executable NumPy or benchmark proofs.
"""
from __future__ import annotations

import copy
import hashlib

import pytest

from ipfs_datasets_py.logic.software_verification.numerical_source import (
    AUTHORITY, MAX_SOURCE_BYTES, PROFILE, adapt_numerical_source, verify_numerical_source,
)
from ipfs_datasets_py.logic.software_verification.program import ProgramIR, Purity


AUTHORED = (
    "import numpy as nx\n"
    "def spectrum_summary(matrix: nx.ndarray):\n"
    "    roots, basis = nx.linalg.eig(matrix)\n"
    "    selected = nx.argmax(nx.abs(roots))\n"
    "    return roots[selected], basis[1:, selected], roots.shape\n"
)


def _text(result, source, item):
    spans = {s.span_id: s for s in result.program.spans}
    span = spans[item.span_ids[0]]
    return source.encode("utf-8")[span.start_byte:span.end_byte].decode("utf-8")


def _calls(result):
    return [e for e in result.program.expressions if e.attributes.get("call_kind") == "python.call"]


def _commands(result):
    # Native ProgramIR collections are canonical ID-sorted; execution order is
    # the CFG's ordered command list, not collection order.
    by_id = {c.command_id: c for c in result.program.commands}
    return [by_id[key] for key in result.program.functions[0].cfg.blocks[0].command_ids]


def test_authored_numerical_structure_preserves_nested_calls_tuple_targets_and_slices():
    result = adapt_numerical_source(AUTHORED, path="src/analysis.py")
    assert result.status == "translated"
    assert result.function_coverage[0]["structurally_complete"] is True
    program = result.program
    assert program.metadata["profile"] == PROFILE
    assert ProgramIR.from_dict(program.to_dict()).to_dict() == program.to_dict()
    by_id = {e.expression_id: e for e in program.expressions}
    symbols = {s.symbol_id: s.name for s in program.symbols}
    calls = _calls(result)
    by_callee = {e.attributes["imported_callee"]: e for e in calls}
    assert set(by_callee) == {"numpy.linalg.eig", "numpy.abs", "numpy.argmax"}
    outer = by_callee["numpy.argmax"]
    assert outer.operand_ids[1] == by_callee["numpy.abs"].expression_id
    assert outer.evaluation_order == outer.operand_ids
    assert by_id[outer.operand_ids[0]].operator == "argmax"
    assignment = _commands(result)[0]
    assert assignment.expression_ids == (by_callee["numpy.linalg.eig"].expression_id,)
    pattern = assignment.attributes.to_dict()["assignment_pattern"]
    assert pattern["kind"] == "tuple"
    assert [symbols[p["symbol_id"]] for p in pattern["elements"]] == ["roots", "basis"]
    slice_expr = next(e for e in program.expressions if e.operator == "python.slice")
    assert slice_expr.attributes.to_dict()["explicit_bounds"] == [True, False, False]
    assert [by_id[e].attributes.get("value") for e in slice_expr.operand_ids] == [1, None, None]
    index = next(e for e in program.expressions if _text(result, AUTHORED, e) == "basis[1:, selected]")
    index_tuple = by_id[index.operand_ids[1]]
    assert index.kind.value == "index"
    assert index_tuple.operator == "python.tuple"
    assert index_tuple.operand_ids[0] == slice_expr.expression_id
    returned = by_id[_commands(result)[-1].expression_ids[0]]
    assert returned.operator == "python.tuple"
    assert len(returned.operand_ids) == 3
    assert all(function.purity is Purity.UNKNOWN for function in program.functions)
    assert program.functions[0].effects.raises == ("BaseException",)
    assert all(result.to_dict()[key] is False for key in AUTHORITY)
    assert all(e.attributes["runtime_identity_verified"] is False for e in calls)


def test_dynamic_receiver_and_keyword_evaluation_order_is_not_sorted():
    source = "def visit():\n    return maker().run(first(), z=second(), a=third())\n"
    result = adapt_numerical_source(source)
    by_id = {e.expression_id: e for e in result.program.expressions}
    outer = by_id[_commands(result)[-1].expression_ids[0]]
    assert outer.attributes["callee_resolution"] == "dynamic_receiver"
    assert outer.attributes["imported_callee"] is None
    assert outer.attributes.to_dict()["keyword_names"] == ["z", "a"]
    assert outer.attributes["positional_count"] == 1
    assert [_text(result, source, by_id[i]) for i in outer.evaluation_order] == [
        "maker().run", "first()", "second()", "third()"]
    assert _text(result, source, by_id[by_id[outer.operand_ids[0]].operand_ids[0]]) == "maker()"


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_exact_raw_byte_spans_after_unicode_comments_and_with_inline_comment(newline):
    # U+2028 remains inside a comment: Python physical lines are CR/LF only.
    source = newline.join([
        "# π 🍋\u2028 not a Python line break",
        "import numpy as nx",
        "def measure(a):",
        "    values, vectors = nx.linalg.eig(a)  # café",
        "    return values[0], vectors[:, 0]", ""])
    result = adapt_numerical_source(source, path="unicode.py")
    raw = source.encode("utf-8")
    assert result.status == "translated"
    assert result.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.program.sources[0].content_sha256 == hashlib.sha256(raw).hexdigest()
    spans = {s.span_id: s for s in result.program.spans}
    call = _calls(result)[0]
    span = spans[call.span_ids[0]]
    expected = b"nx.linalg.eig(a)"
    expected_start = raw.index(expected)  # Independent bytes, not shared AST helpers.
    assert (span.start_byte, span.end_byte) == (expected_start, expected_start + len(expected))
    assert raw[span.start_byte:span.end_byte] == expected
    assert span.start_line == span.end_line == 4
    assignment = spans[_commands(result)[0].span_ids[0]]
    expected_assignment = b"values, vectors = nx.linalg.eig(a)"
    assert raw[assignment.start_byte:assignment.end_byte] == expected_assignment
    function = spans[result.program.functions[0].span_ids[0]]
    start = raw.index(b"def measure")
    end = raw.index(b"vectors[:, 0]") + len(b"vectors[:, 0]")
    assert (function.start_byte, function.end_byte) == (start, end)
    for item in result.program.spans:
        assert 0 <= item.start_byte <= item.end_byte <= len(raw)
        raw[item.start_byte:item.end_byte].decode("utf-8")


@pytest.mark.parametrize(("imports", "expression", "canonical"), [
    ("import numpy as nx", "nx.linalg.eig(a)", "numpy.linalg.eig"),
    ("from numpy.linalg import eig as decompose", "decompose(a)", "numpy.linalg.eig"),
    ("import numpy.linalg", "numpy.linalg.eig(a)", "numpy.linalg.eig"),
])
def test_declared_import_resolution_is_explicit_not_runtime_authority(imports, expression, canonical):
    source = f"{imports}\ndef spectrum(a):\n    return {expression}\n"
    result = adapt_numerical_source(source)
    call = _calls(result)[0]
    assert call.attributes["imported_callee"] == canonical
    assert call.attributes["callee_resolution"] == "declared_import"
    assert call.attributes["runtime_identity_verified"] is False


@pytest.mark.parametrize("source", [
    "import numpy as nx\nnx = replacement\ndef f(a):\n    return nx.linalg.eig(a)\n",
    "import numpy as nx\ndef f(a, nx):\n    return nx.linalg.eig(a)\n",
    "import numpy as nx\ndef f(a):\n    value = nx.linalg.eig(a)\n    nx = other\n    return value\n",
    "import numpy as nx\ndef f(a):\n    import other as nx\n    return nx.linalg.eig(a)\n",
    "import numpy as nx\ndef f(a):\n    def nx():\n        pass\n    return nx.linalg.eig(a)\n",
    "import numpy as nx\ndef f(a):\n    nx.linalg.eig = other\n    return nx.linalg.eig(a)\n",
    "import numpy as nx\ndef f(a):\n    global nx\n    return nx.linalg.eig(a)\n",
    "import numpy as nx\nfrom other import *\ndef f(a):\n    return nx.linalg.eig(a)\n",
    "import numpy as nx\nfrom .other import nx\ndef f(a):\n    return nx.linalg.eig(a)\n",
    "import numpy as nx\nif condition:\n    import other as nx\ndef f(a):\n    return nx.linalg.eig(a)\n",
    "import numpy as nx\nnx.linalg.eig = other\ndef f(a):\n    return nx.linalg.eig(a)\n",
])
def test_rebinding_never_promotes_apparent_imported_callee(source):
    result = adapt_numerical_source(source)
    call = next(c for c in _calls(result) if c.attributes["qualified_callee"] == "nx.linalg.eig")
    assert call.attributes["imported_callee"] is None
    assert call.attributes["callee_resolution"] == "unresolved_or_shadowed"


@pytest.mark.parametrize("expression", ["f(*a)", "f(**a)", "f(x=1, x=2)"])
def test_argument_expansion_and_duplicate_keywords_fail_closed(expression):
    result = adapt_numerical_source(f"def compute(a):\n    return {expression}\n")
    assert result.status in ("partial", "unsupported")
    assert not result.to_dict()["source_translation_complete"]
    assert not _calls(result) if result.program else True
    assert any(row["code"] in ("python.syntax", "python.call.argument_expansion_or_duplicate_keyword")
               for row in result.diagnostics)


def test_tuple_pattern_keeps_repeated_target_order_and_rhs_occurs_once():
    result = adapt_numerical_source("def select(a):\n    x, (y, x) = acquire(a)\n    return x, y\n")
    command = _commands(result)[0]
    pattern = command.attributes.to_dict()["assignment_pattern"]
    assert pattern["elements"][0]["symbol_id"] == pattern["elements"][1]["elements"][1]["symbol_id"]
    assert len(command.target_symbol_ids) == 2
    assert len(command.expression_ids) == 1
    assert len(_calls(result)) == 1


@pytest.mark.parametrize("control", [
    "for item in data:\n        hidden_call(item)",
    "while condition:\n        hidden_call(data)",
    "if condition:\n        hidden_call(data)",
    "try:\n        hidden_call(data)\n    except Exception:\n        pass",
])
def test_unsupported_control_flow_is_a_fence_not_linearized(control):
    result = adapt_numerical_source(f"def compute(data):\n    {control}\n    return data\n")
    assert result.status == "partial"
    assert result.function_coverage[0]["structurally_complete"] is False
    assert not _calls(result)
    assert _commands(result)[0].attributes["body_not_linearized"] is True
    assert _commands(result)[0].kind.value == "skip"


def test_structural_assert_predicate_retains_residual_but_defers_fstring_message():
    source = ("def residual(matrix, vector, root):\n"
        "    error = matrix @ vector - root * vector\n"
        "    assert accepted(error), f'bad: {error}'\n"
        "    return error\n")
    result = adapt_numerical_source(source)
    assert result.status == "partial"
    assert any(row["code"] == "python.assert.message_expression_deferred" for row in result.diagnostics)
    assert {e.operator for e in result.program.expressions} >= {"matmul", "mul", "sub"}
    command = _commands(result)[1]
    assert command.kind.value == "assert"
    assert command.attributes["assertion_message_source"] == "f'bad: {error}'"
    assert command.attributes["message_evaluated_only_on_failure"] is True
    assert command.attributes["assertion_semantics_verified"] is False


def test_float_literal_is_lossless_without_claiming_real_number_semantics():
    source = "def fraction(a):\n    return a[1.5], 1e-3, -0.0\n"
    result = adapt_numerical_source(source)
    literals = [e for e in result.program.expressions if e.type_ref == "python.literal.float"]
    observed = {e.attributes["source_spelling"]: float.fromhex(e.attributes["value_hex"]) for e in literals}
    assert observed == {"1.5": 1.5, "1e-3": 0.001, "0.0": 0.0}
    assert all("value" not in e.attributes for e in literals)
    assert all(e.attributes["literal_encoding"] == "python.float.hex" for e in literals)
    assert any(e.operator == "neg" for e in result.program.expressions)


def test_numerical_structure_never_enters_the_scalar_source_proof_profile():
    from ipfs_datasets_py.logic.formalization.autoencoder.native_program_lean import emit_program
    from ipfs_datasets_py.logic.formalization.autoencoder.security.source_program_binding_384 import (
        qualify_source_candidate,
    )
    result = adapt_numerical_source(AUTHORED)
    with pytest.raises(ValueError, match="program_metadata_requires_explicit_semantics_review"):
        emit_program(result.program.to_dict())
    qualification = qualify_source_candidate(AUTHORED, {})
    assert qualification["qualified"] is False
    assert qualification["projections"] == []
    assert result.program.metadata["scalar_source384_profile_widened"] is False


def test_replay_rejects_source_path_claim_and_structural_tampering():
    result = adapt_numerical_source(AUTHORED, path="src/a.py")
    assert verify_numerical_source(result, AUTHORED, path="src/a.py").to_dict() == result.to_dict()
    for source, path in [(AUTHORED + "# changed\n", "src/a.py"), (AUTHORED, "src/b.py")]:
        with pytest.raises(ValueError, match="exact replay"):
            verify_numerical_source(result, source, path=path)
    for mutate in [
        lambda row: row.update(proof_authority=True),
        lambda row: row["function_coverage"][0].update(structurally_complete=False),
        lambda row: row["program"]["expressions"][-1].update(operator="invented"),
        lambda row: row["program"]["spans"][0].update(start_byte=1),
    ]:
        wire = copy.deepcopy(result.to_dict())
        mutate(wire)
        with pytest.raises(ValueError, match="exact replay"):
            verify_numerical_source(wire, AUTHORED, path="src/a.py")


def test_never_executes_source_and_records_top_level_effect_gap(tmp_path):
    marker = tmp_path / "must-not-exist"
    source = f"open({str(marker)!r}, 'w').write('executed')\ndef answer():\n    return 1\n"
    result = adapt_numerical_source(source)
    assert not marker.exists()
    assert result.status == "partial"
    assert result.to_dict()["source_executed"] is False
    assert any(d["code"] == "python.module.Expr" for d in result.diagnostics)


@pytest.mark.parametrize("path", ["/tmp/a.py", "../a.py", "a/./b.py", "a//b.py", "a\\b.py", ""])
def test_path_requires_canonical_relative_identity(path):
    with pytest.raises(ValueError, match="relative"):
        adapt_numerical_source(AUTHORED, path=path)


def test_resource_bounds_and_invalid_source_are_explicit():
    with pytest.raises(ValueError, match="byte bound"):
        adapt_numerical_source("#" * (MAX_SOURCE_BYTES + 1))
    with pytest.raises(ValueError, match="AST resource"):
        adapt_numerical_source("\n".join(f"def f{i}():\n    return 0" for i in range(33)))
    invalid = adapt_numerical_source("def broken(:\n")
    assert invalid.status == "unsupported"
    assert invalid.program is None
    assert invalid.diagnostics[0]["code"] == "python.syntax"
    assert adapt_numerical_source("import numpy\n").status == "unsupported"
