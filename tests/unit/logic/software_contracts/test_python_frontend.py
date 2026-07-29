"""Python semantic frontend tests for DSCON-G110."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTRecord
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.python_frontend import (
    ASTBlobRecord,
    PythonASTExtractor,
    build_python_ast_blob_record,
)


REPRESENTATIVE_SOURCE = """\
from collections import defaultdict as dd
from .helpers import helper

__all__ = ["Service"]

@decorate
class Service(Base):
    state: str = "new"

    @classmethod
    async def run(
        cls,
        value: int = 1,
        /,
        label: str = factory(),
        *items: bytes,
        enabled: bool = True,
        **options: object,
    ) -> str:
        cls.state = await client.fetch(value, label=label)
        if enabled:
            yield cls.state
        raise RuntimeError("stop")
"""


def extract(source: str | bytes = REPRESENTATIVE_SOURCE) -> ASTRecord:
    return PythonASTExtractor().extract(
        source,
        path="pkg/service.py",
        repository_id="repository:test",
        revision="0123456789abcdef",
    )


def test_python_frontend_emits_normalized_semantic_facts() -> None:
    record = extract()
    assert isinstance(record, ASTRecord)
    assert record.frontend.language == "python"
    assert record.frontend.frontend_name == "cpython-ast"
    assert record.frontend.frontend_version == "1.1.0"
    assert record.provenance.source_cid == cid_for_bytes(
        REPRESENTATIVE_SOURCE.encode()
    )
    assert record.module.name == "pkg.service"
    assert record.module.export_names == ("Service",)

    imports = {
        (item.module, item.imported_name, item.local_name)
        for item in record.imports
    }
    assert ("collections", "defaultdict", "dd") in imports
    assert (".helpers", "helper", "helper") in imports

    service = next(item for item in record.symbols if item.name == "Service")
    run = next(item for item in record.symbols if item.name == "run")
    assert service.kind == "class"
    assert run.kind == "method"
    assert run.decorator_names == ("classmethod",)
    assert set(run.flags) == {
        "async_generator",
        "classmethod",
        "coroutine",
        "generator",
    }
    assert run.signature is not None
    assert run.signature.is_async is True
    assert run.signature.is_generator is True
    assert run.signature.return_annotation == "str"
    assert [
        (item.name, item.kind, item.annotation, item.default_kind)
        for item in run.signature.parameters
    ] == [
        ("cls", "positional_only", "", "none"),
        ("value", "positional_only", "int", "literal"),
        ("label", "positional_or_named", "str", "expression"),
        ("items", "variadic_positional", "bytes", "none"),
        ("enabled", "named_only", "bool", "literal"),
        ("options", "variadic_named", "object", "none"),
    ]

    call = next(item for item in record.calls if item.callee_name == "client.fetch")
    assert call.is_awaited is True
    assert call.argument_count == 2
    assert call.named_argument_names == ("label",)
    assert call.callee_reference_id is not None
    assert {item.kind for item in record.effects} >= {
        "await",
        "exception",
        "object_state",
    }
    assert any(
        item.kind == "object_state"
        and item.operation == "write"
        and item.subject == "cls.state"
        for item in record.effects
    )


def test_duplicate_shadowed_and_unbound_facts_remain_lexical() -> None:
    source = """\
value = 1
def value():
    missing(value)
def value():
    return missing
"""
    record = extract(source)
    definitions = [item for item in record.symbols if item.name == "value"]
    assert [item.definition_ordinal for item in definitions] == [0, 1, 2]
    assert len({item.symbol_id for item in definitions}) == 3
    assert any(
        item.code == "python.duplicate_definition"
        for item in record.diagnostics
    )
    missing = [item for item in record.references if item.name == "missing"]
    assert missing
    assert all(item.context in {"call", "read"} for item in missing)
    assert any(
        item.code == "python.undefined_reference_candidate"
        and item.span == missing[0].span
        for item in record.diagnostics
    )
    for payload in [item.to_dict() for item in missing]:
        assert {
            "resolved_symbol_id",
            "target_symbol_id",
            "candidate_symbol_ids",
            "resolution_confidence",
        }.isdisjoint(payload)


def test_nested_yield_and_nested_function_are_not_attributed_to_parent_or_class() -> None:
    record = extract(
        """\
class Container:
    def outer(self):
        self.value = 1
        def inner():
            yield 1
        return self.value
"""
    )
    outer = next(item for item in record.symbols if item.name == "outer")
    inner = next(item for item in record.symbols if item.name == "inner")
    assert outer.kind == "method"
    assert outer.signature is not None and not outer.signature.is_generator
    assert inner.kind == "function"
    assert inner.signature is not None and inner.signature.is_generator
    assert not [
        item
        for item in record.symbols
        if item.kind == "variable" and item.name in {"self", "value"}
    ]


def test_scope_sensitive_bindings_and_lambda_defaults_are_preserved() -> None:
    record = extract(
        """\
module_value = 1
factory = lambda value=missing(): value
values = [item for item in source if item]

class Container:
    class_value = 2

    def read(self):
        return module_value, class_value

try:
    operation()
except Exception as error:
    handled = error

match payload:
    case {"item": captured, **rest}:
        result = captured, rest
"""
    )
    module_scope = record.module.scope_id
    comprehension_scope = next(
        item.scope_id for item in record.scopes if item.kind == "comprehension"
    )
    lambda_scope = next(
        item.scope_id for item in record.scopes if item.kind == "lambda"
    )

    missing_call = next(item for item in record.calls if item.callee_name == "missing")
    source_read = next(
        item
        for item in record.references
        if item.name == "source" and item.context == "read"
    )
    item_reads = [
        item
        for item in record.references
        if item.name == "item" and item.context == "read"
    ]
    assert missing_call.scope_id == module_scope
    assert source_read.scope_id == module_scope
    assert item_reads and {item.scope_id for item in item_reads} == {
        comprehension_scope
    }
    assert any(
        item.name == "value"
        and item.context == "read"
        and item.scope_id == lambda_scope
        for item in record.references
    )

    undefined_names = {
        item.message.split(" ", 1)[0]
        for item in record.diagnostics
        if item.code == "python.undefined_reference_candidate"
    }
    assert {"missing", "source", "class_value", "operation", "payload"} <= (
        undefined_names
    )
    assert {"module_value", "item", "value", "error", "captured", "rest"}.isdisjoint(
        undefined_names
    )


def test_explicit_exports_import_bindings_and_decorators_are_explicit() -> None:
    record = extract(
        """\
import visible_before_all
__all__ = ["kept"]

@decorate
@decorate
def kept():
    return None

class hidden_public_name:
    pass
"""
    )
    kept = next(item for item in record.symbols if item.name == "kept")
    assert record.module.export_names == ("kept",)
    assert kept.decorator_names == ("decorate",)
    assert any(
        item.code == "python.repeated_decorator"
        for item in record.unsupported
    )

    implicit = extract("import public_module as imported\n_private = 1\n")
    assert implicit.module.export_names == ("imported",)

    dynamic = extract("__all__ = exported_names\npublic_name = 1\n")
    assert dynamic.module.export_names == ()
    assert any(
        item.code == "python.dynamic_exports"
        for item in dynamic.unsupported
    )


def test_malformed_dynamic_and_wildcard_constructs_fail_explicitly() -> None:
    malformed = extract("def broken(:\n")
    assert {item.code for item in malformed.diagnostics} == {
        "python.parse_error"
    }
    assert {item.code for item in malformed.unsupported} == {
        "python.parse_error"
    }
    assert not malformed.symbols

    dynamic = extract(
        "from plugin import *\n"
        "exec(payload)\n"
        "module = __import__(name)\n"
    )
    codes = {item.code for item in dynamic.unsupported}
    assert "python.wildcard_import" in codes
    assert "python.dynamic_execution" in codes


def test_resource_and_encoding_failures_are_durable_unsupported_records() -> None:
    bounded = PythonASTExtractor(max_source_bytes=4).extract(
        "value = 1\n",
        path="value.py",
    )
    assert [item.code for item in bounded.unsupported] == [
        "python.resource_limit"
    ]
    assert not bounded.symbols

    invalid = PythonASTExtractor().extract(
        b"# \xff\n",
        path="invalid.py",
    )
    assert invalid.provenance.source_cid == cid_for_bytes(b"# \xff\n")
    assert [item.code for item in invalid.unsupported] == [
        "python.invalid_encoding"
    ]

    deeply_nested = PythonASTExtractor().extract(
        "value = " + "+".join(["1"] * 500) + "\n",
        path="deep.py",
    )
    assert [item.construct for item in deeply_nested.unsupported] == [
        "frontend_traversal"
    ]
    assert [item.code for item in deeply_nested.diagnostics] == [
        "python.resource_limit"
    ]


def test_utf8_byte_spans_are_exact_across_unicode_and_crlf() -> None:
    source = "café = 1\r\nprint(café)\r\n"
    record = extract(source)
    source_bytes = source.encode("utf-8")
    read = next(
        item
        for item in record.references
        if item.name == "café" and item.context == "read"
    )
    assert source_bytes[read.span.start_byte : read.span.end_byte] == "café".encode(
        "utf-8"
    )
    assert read.span.start_line == 2
    assert read.span.start_column == len("print(".encode("utf-8"))


def test_analyzed_source_is_never_imported_or_executed(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    source = (
        "from definitely_missing_side_effect_module import value\n"
        f"open({str(marker)!r}, 'w').write('executed')\n"
        "raise SystemExit(99)\n"
    )
    record = extract(source)
    assert record.calls
    assert not marker.exists()
    assert record.imports[0].module == "definitely_missing_side_effect_module"


def test_monolith_duplicate_definitions_are_reproduced() -> None:
    monolith = (
        Path(__file__).resolve().parents[4]
        / "ipfs_datasets_py"
        / "ipfs_datasets.py"
    )
    record = PythonASTExtractor().extract(
        monolith.read_bytes(),
        path="ipfs_datasets_py/ipfs_datasets.py",
    )
    for name in (
        "combine_checkpoints",
        "generate_clusters",
        "load_checkpoints",
        "load_clusters",
    ):
        definitions = [item for item in record.symbols if item.name == name]
        assert len(definitions) == 2
        assert [item.definition_ordinal for item in definitions] == [0, 1]
        assert len({item.symbol_id for item in definitions}) == 2


def test_compatibility_constructor_round_trip_and_golden_root() -> None:
    record = build_python_ast_blob_record(
        REPRESENTATIVE_SOURCE,
        path="pkg/service.py",
        repository_id="repository:test",
        revision="0123456789abcdef",
    )
    assert isinstance(record, ASTBlobRecord)
    assert ASTRecord.from_json(record.to_json()) == record
    assert record.verify_cid(record.cid) == record.cid
    # Golden identity binds source, frontend/toolchain, normalized facts and
    # the shared AST schema.  Update only with an explicit compatibility review.
    assert (
        record.cid
        == "baguqeeraqqnuh7keo2od4wafzpc6cuvkkbzm3rcktff2e7axrsauwkinfhrq"
    )


def test_frontend_is_deterministic_across_fresh_processes() -> None:
    script = (
        "from ipfs_datasets_py.logic.software_contracts.python_frontend "
        "import build_python_ast_blob_record;"
        f"source={REPRESENTATIVE_SOURCE!r};"
        "r=build_python_ast_blob_record(source,path='pkg/service.py',"
        "repository_id='repository:test',revision='0123456789abcdef');"
        "print(r.cid);print(r.to_json())"
    )
    outputs = []
    for seed in ("1", "8675309"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
            timeout=20,
        )
        outputs.append(completed.stdout)
    assert outputs[0] == outputs[1]
    cid, payload = outputs[0].splitlines()
    assert json.loads(payload)["schema"].endswith("@1.0.0")
    assert cid == extract().cid


@pytest.mark.parametrize("bad_value", [None, 1, bytearray(b"x")])
def test_source_input_type_is_closed(bad_value: object) -> None:
    with pytest.raises(TypeError, match="exact str or bytes"):
        PythonASTExtractor().extract(bad_value)  # type: ignore[arg-type]
