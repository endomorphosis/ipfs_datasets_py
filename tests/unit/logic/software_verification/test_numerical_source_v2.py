"""Authored guarded-syntax fixtures; these are not Python/NumPy proofs."""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib

import pytest

from ipfs_datasets_py.logic.software_verification import numerical_source as v1
from ipfs_datasets_py.logic.software_verification.numerical_source_v2 import (
    AUTHORITY, FORMAT_POLICY, PROFILE, adapt_numerical_source,
    validate_guarded_structure, verify_numerical_source,
)


def _expressions(result):
    return {e.expression_id: e for e in result.program.expressions}


def _region(result, kind):
    return next(r for r in result.guarded_regions if r["kind"] == kind)


def _text(result, source, item):
    span = next(s for s in result.program.spans if s.span_id == item.span_ids[0])
    return source.encode()[span.start_byte:span.end_byte].decode()


def test_conditional_has_only_eager_test_and_explicit_source_bound_alternatives():
    source = "def choose(flag, left, right):\n    return left() if flag() else right()\n"
    result = adapt_numerical_source(source)
    expressions = _expressions(result)
    region = _region(result, "if_expression")
    root = expressions[region["root_expression_id"]]
    assert result.status == "translated"
    assert root.operand_ids == root.evaluation_order == (region["test_expression_id"],)
    assert [_text(result, source, expressions[region[k]]) for k in
            ("test_expression_id", "then_expression_id", "else_expression_id")] == ["flag()", "left()", "right()"]
    assert region["evaluation_policy"] == "test_once_then_truthiness_once_then_selected_branch"
    assert region["truthiness_semantics_verified"] is False
    assert set(result.program.commands[0].effects.reads) == set(result.program.functions[0].parameter_symbol_ids)
    assert validate_guarded_structure(result.program, result.guarded_regions)


@pytest.mark.parametrize("message,status", [(None, "absent"), ('"failed"', "lowered"), ('f"bad {value!r}"', "lowered")])
def test_assertion_predicate_and_message_are_both_guarded(message, status):
    source = "def check(value):\n    assert predicate(value)" + (", " + message if message else "") + "\n"
    result = adapt_numerical_source(source)
    region = _region(result, "assert_statement")
    command = result.program.commands[0]
    assert result.status == "translated"
    assert command.expression_ids == command.evaluation_order == (region["predicate_expression_id"],)
    assert region["message_expression_id"] not in command.expression_ids
    assert region["message_status"] == status
    assert region["predicate_guard"] == "assertions_enabled"
    assert region["message_guard"] == "assertions_enabled_and_predicate_false"
    assert region["exceptions_policy"] == "propagate_before_later_phase"


def test_assertion_message_reads_are_possible_not_unconditional():
    result = adapt_numerical_source("def check(condition, diagnostic):\n    assert condition, diagnostic()\n")
    command = result.program.commands[0]
    symbols = {s.symbol_id: s.name for s in result.program.symbols}
    assert {symbols[s] for s in command.effects.reads} == {"condition", "diagnostic"}
    assert command.attributes["read_scope"] == "may_read_including_guarded_regions"
    predicate = _expressions(result)[command.expression_ids[0]]
    assert {symbols[s] for s in predicate.symbol_ids} == {"condition"}


@pytest.mark.parametrize("conversion", ["", "!s", "!r", "!a"])
def test_dynamic_format_spec_precedes_conversion_and_later_fields(conversion):
    source = 'def message():\n    return f"{value()' + conversion + ':{spec()}}{later()}"\n'
    result = adapt_numerical_source(source)
    expressions = _expressions(result)
    fields = [e for e in expressions.values() if e.attributes.get("call_kind") == "python.format_value"]
    outer = next(e for e in fields if e.attributes["has_format_spec"])
    assert result.status == "translated"
    assert _text(result, source, expressions[outer.operand_ids[0]]) == "value()"
    assert expressions[outer.operand_ids[1]].attributes["call_kind"] == "python.joined_string"
    assert outer.evaluation_order == outer.operand_ids
    assert outer.attributes["evaluation_policy"] == FORMAT_POLICY
    assert outer.attributes["conversion"] == (-1 if not conversion else ord(conversion[1]))
    assert outer.attributes["exceptions_policy"] == "propagate_before_later_phase"
    returned = expressions[result.program.commands[0].expression_ids[0]]
    assert returned.attributes["evaluation_policy"] == "lexical_components_left_to_right"
    assert returned.operand_ids[0] == outer.expression_id


def test_nested_conditionals_in_predicate_message_and_format_spec_close():
    source = '''def check(flag, value, width):
    assert value if flag else fallback(), f"bad {value!r:{width if flag else default_width()}}"
'''
    result = adapt_numerical_source(source)
    assert result.status == "translated"
    assert len(result.guarded_regions) == 3
    assert validate_guarded_structure(result.program, result.guarded_regions)
    assert all(r["function_id"] == result.program.functions[0].function_id for r in result.guarded_regions)


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_unicode_raw_bytes_and_empty_format_components_are_exact(newline):
    source = newline.join(['# λ', 'def text(value, spec):', '    return f"λ={value!r:{spec}}"', ''])
    result = adapt_numerical_source(source, path="src/format.py")
    assert result.status == "translated"
    assert result.source_sha256 == hashlib.sha256(source.encode()).hexdigest()
    for span in result.program.spans:
        span.validate()
        assert 0 <= span.start_byte <= span.end_byte <= len(source.encode())
        if span.start_byte == span.end_byte:
            assert (span.start_line, span.start_column, span.end_line, span.end_column) == (None,) * 4
    value = next(e for e in result.program.expressions if e.attributes.get("call_kind") == "python.format_value"
                 and e.attributes["has_format_spec"])
    assert _text(result, source, _expressions(result)[value.operand_ids[0]]) == "value"


@pytest.mark.parametrize("body", [
    "for value in values:\n        consume(value)",
    "if values:\n        consume(values)",
    "while values:\n        consume(values)",
])
def test_statement_control_remains_fenced_and_inner_calls_are_not_linearized(body):
    result = adapt_numerical_source("def work(values):\n    " + body + "\n")
    assert result.status == "partial"
    assert result.program.commands[0].attributes["body_not_linearized"] is True
    assert not result.program.expressions
    assert not result.guarded_regions


@pytest.mark.parametrize("source", [
    "def f(a, b):\n    return (a if b else a) + (lambda: b)\n",
    "def f(a, b):\n    obj.attr = a if b else b\n",
    "def f(a, b):\n    a = b = a if b else b\n",
])
def test_failed_outer_construct_does_not_leave_orphan_conditional_graphs(source):
    result = adapt_numerical_source(source)
    assert result.status == "partial"
    assert not result.guarded_regions
    assert not result.program.expressions


def test_unsupported_message_retains_explicit_partial_coverage():
    result = adapt_numerical_source("def f(x):\n    assert x, (lambda: x)\n")
    region = _region(result, "assert_statement")
    assert result.status == "partial"
    assert region["message_status"] == "unsupported"
    assert region["message_expression_id"] is None
    assert "python.assert.message_expression_deferred" in {d["code"] for d in result.diagnostics}
    assert result.function_coverage[0]["structurally_complete"] is False


def test_no_execution_or_authority_and_v1_contract_is_unchanged(tmp_path):
    marker = tmp_path / "must-not-exist"
    source = f'def f(x):\n    assert x, open({str(marker)!r}, "w")\n'
    before = v1.adapt_numerical_source(source).to_dict()
    result = adapt_numerical_source(source)
    assert not marker.exists()
    assert v1.adapt_numerical_source(source).to_dict() == before
    assert before["status"] == "partial"
    wire = result.to_dict()
    assert wire["profile"] == PROFILE
    assert wire["guarded_extension_required"] is True
    assert wire["standalone_program_evaluation_complete"] is False
    assert wire["structural_completeness_scope"] == "program_and_guarded_regions"
    assert all(wire[key] is False for key in AUTHORITY)
    assert wire["provider_calls"] == wire["solver_calls"] == 0


@pytest.mark.parametrize("mutation", ["dangling", "cycle", "foreign_owner", "wrong_source", "duplicate", "missing", "policy", "extra"])
def test_guarded_validator_rejects_invalid_closure(mutation):
    result = adapt_numerical_source("def f(a, b):\n    return a() if b else b()\ndef g(c):\n    return c\n")
    regions = copy.deepcopy(list(result.guarded_regions))
    region = regions[0]
    if mutation == "dangling":
        region["then_expression_id"] = "expr:missing"
    elif mutation == "cycle":
        region["then_expression_id"] = region["root_expression_id"]
    elif mutation == "foreign_owner":
        region["function_id"] = next(f.function_id for f in result.program.functions if f.name == "g")
    elif mutation == "wrong_source":
        region["span_ids"] = []
    elif mutation == "duplicate":
        regions.append(copy.deepcopy(region))
    elif mutation == "missing":
        regions.clear()
    elif mutation == "policy":
        region["evaluation_policy"] = "all_branches_eager"
    else:
        region["proof_authority"] = True
    with pytest.raises(ValueError):
        validate_guarded_structure(result.program, regions)


def test_guarded_validator_rejects_cross_function_side_root():
    result = adapt_numerical_source("def f(a, b):\n    return a if b else b\ndef g(c):\n    return c\n")
    regions = copy.deepcopy(list(result.guarded_regions))
    commands = {c.command_id: c for c in result.program.commands}
    other = next(f for f in result.program.functions if f.name == "g")
    regions[0]["then_expression_id"] = commands[other.cfg.blocks[0].command_ids[0]].expression_ids[0]
    with pytest.raises(ValueError):
        validate_guarded_structure(result.program, regions)


def test_guarded_validator_rejects_other_statement_side_root_in_same_function():
    result = adapt_numerical_source("def f(a, b):\n    earlier = a()\n    return a if b else b\n")
    regions = copy.deepcopy(list(result.guarded_regions))
    first = next(c for c in result.program.commands if c.kind.value == "assign")
    regions[0]["then_expression_id"] = first.expression_ids[0]
    with pytest.raises(ValueError, match="source span"):
        validate_guarded_structure(result.program, regions)


@pytest.mark.parametrize("field", ["region_id", "function_id", "then_expression_id"])
def test_guarded_validator_rejects_non_scalar_ids(field):
    result = adapt_numerical_source("def f(a, b):\n    return a if b else b\n")
    regions = copy.deepcopy(list(result.guarded_regions))
    regions[0][field] = ["invalid"]
    with pytest.raises(ValueError, match="IDs"):
        validate_guarded_structure(result.program, regions)


def test_guarded_validator_rejects_missing_message_may_reads():
    result = adapt_numerical_source("def f(predicate, message):\n    assert predicate, message()\n")
    predicate = _expressions(result)[result.program.commands[0].expression_ids[0]]
    command = result.program.commands[0]
    command = replace(command, effects=replace(command.effects, reads=predicate.symbol_ids))
    program = replace(result.program, program_id="", commands=(command,))
    with pytest.raises(ValueError, match="MAY-read"):
        validate_guarded_structure(program, result.guarded_regions)


@pytest.mark.parametrize("change", ["guard", "conversion", "source", "profile", "authority"])
def test_exact_replay_rejects_any_changed_claim(change):
    source = 'def f(x):\n    assert x, f"bad {x!r}"\n'
    result = adapt_numerical_source(source, path="src/f.py")
    wire = result.to_dict()
    if change == "guard":
        wire["guarded_regions"][0]["message_guard"] = "always"
    elif change == "conversion":
        next(e for e in wire["program"]["expressions"] if e["attributes"].get("call_kind") == "python.format_value")["attributes"]["conversion"] = ord("s")
    elif change == "source":
        source += "# changed\n"
    elif change == "profile":
        wire["profile"] = v1.PROFILE
    else:
        wire["proof_authority"] = True
    with pytest.raises(ValueError, match="exact replay"):
        verify_numerical_source(wire, source, path="src/f.py")


def test_replay_success_detaches_nested_wire_data():
    source = "def f(x):\n    return x if x else 0\n"
    result = adapt_numerical_source(source)
    assert verify_numerical_source(result, source).to_dict() == result.to_dict()
    wire = result.to_dict()
    wire["guarded_regions"].clear()
    assert result.guarded_regions


@pytest.mark.parametrize("path", ["/abs.py", "a/../b.py", "./a.py", "a\\b.py", "a//b.py"])
def test_path_bounds_are_preserved(path):
    with pytest.raises(ValueError):
        adapt_numerical_source("def f(): pass\n", path=path)


def test_syntax_and_resource_limits_remain_explicit():
    result = adapt_numerical_source("def :")
    assert result.status == "unsupported" and not result.guarded_regions
    for source in ("", " " * (v1.MAX_SOURCE_BYTES + 1), "\ud800"):
        with pytest.raises(ValueError):
            adapt_numerical_source(source)
