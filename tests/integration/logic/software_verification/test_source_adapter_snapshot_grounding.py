"""Exact source identity and UTF-8 spans before repository proof admission."""

from __future__ import annotations

import ast
import hashlib

import pytest

from ipfs_datasets_py.logic.software_verification.ir import SoftwareVerificationIR
from ipfs_datasets_py.logic.software_verification.program import ProgramIR
from ipfs_datasets_py.logic.software_verification.source_adapters import (
    SourceAdapterError,
    SourceAdapterStatus,
    SourceSoftwareVerificationAdapter,
    _ast_byte_span,
    _line_byte_offsets,
    adapt_source_to_software_verification,
)


def _adapt(source, **options):
    return adapt_source_to_software_verification(
        source, include_supervisor_evidence=False, **options,
    )


@pytest.mark.parametrize("source", [
    "def identité(entrée):\n    return entrée + 1\n",
    "def sample(x):\n    y = 'é😀'; return x + 1\n",
    "# entrée 😀\r\ndef sample(x):\r\n    return 'é😀'\r\n",
    "# entrée 😀\rdef sample(x):\r    return x + 1\r",
    "def sample(x):\n    y = 'é\u0085\u2028😀'; return x\n",
    "def sample(x):\n    return '''é😀\nsecond line'''\n",
    "def sample(x):\n    return x + 1",
])
def test_ast_columns_resolve_to_exact_utf8_source_segments(source):
    raw = source.encode("utf-8")
    checked = 0
    for node in ast.walk(ast.parse(source)):
        segment = ast.get_source_segment(source, node)
        if segment is None:
            continue
        start, end, *_ = _ast_byte_span(node, source=source, offsets=_line_byte_offsets(source))
        assert raw[start:end] == segment.encode("utf-8")
        assert 0 <= start <= end <= len(raw)
        checked += 1
    assert checked >= 4


def test_emitted_python_expression_spans_preserve_unicode_identifiers_and_literals():
    source = "# café 😀\r\ndef identité(entrée):\r\n    marque = 'é😀'; return entrée\r\n"
    result = _adapt(source, path="unicode.py", revision="snapshot:captured-a")
    assert result.status is SourceAdapterStatus.SUCCESS
    program = result.program
    assert program is not None
    raw = source.encode()
    spans = {span.span_id: span for span in program.spans}
    symbols = {symbol.symbol_id: symbol for symbol in program.symbols}
    for expression in program.expressions:
        span = spans[expression.span_ids[0]]
        segment = raw[span.start_byte:span.end_byte].decode("utf-8")
        if expression.kind.value == "symbol":
            assert segment == symbols[expression.symbol_ids[0]].name
        elif expression.kind.value == "literal":
            assert segment == "'é😀'"
    assert program.sources[0].content_sha256 == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("path,language,source", [
    ("src/add.py", "python", "def add(x):\n    return x + 1\n"),
    ("src/add.js", "javascript", "function add(x) { return x + 1; }\n"),
    ("src/add.ts", "typescript", "export function add(x) { return x + 1; }\n"),
])
def test_captured_revision_binds_both_native_program_and_document(path, language, source):
    first = _adapt(source, path=path, language=language, revision="snapshot:captured-a")
    second = _adapt(source, path=path, language=language, revision="snapshot:captured-b")
    digest = hashlib.sha256(source.encode()).hexdigest()
    for result, revision in ((first, "snapshot:captured-a"), (second, "snapshot:captured-b")):
        assert result.program is not None and result.document is not None
        for owner in (result.program, result.document):
            assert len(owner.sources) == 1
            source_ref = owner.sources[0]
            assert source_ref.source_revision == revision
            assert source_ref.content_sha256 == digest
            assert source_ref.metadata["path"] == path
        assert ProgramIR.from_dict(result.program.to_dict()).to_dict() == result.program.to_dict()
        assert SoftwareVerificationIR.from_dict(result.document.to_dict()).to_dict() == result.document.to_dict()
    assert first.program.program_id != second.program.program_id


def test_opaque_javascript_signature_uses_byte_offsets_after_unicode_comment():
    source = "// café 😀\nfunction add(x) { return x + 1; }\n"
    result = _adapt(source, path="add.js", revision="snapshot:captured-a")
    assert result.status is SourceAdapterStatus.PARTIAL
    assert "javascript.opaque_function_body" in result.unsupported_constructs
    signature = result.program.spans[1]
    assert source.encode()[signature.start_byte:signature.end_byte] == b"function add(x) {"
    assert result.fake_backend_success is False


@pytest.mark.parametrize("source,options,status,unsupported", [
    ("fn main() {}\n", {"path": "main.rs", "language": "rust"},
     SourceAdapterStatus.UNSUPPORTED, "language.rust"),
    ("def sample(x):\n    return x\n", {"path": "sample.py", "max_source_bytes": 8},
     SourceAdapterStatus.UNSUPPORTED, "source.size_bound"),
    ("def sample(:\n", {"path": "sample.py"}, SourceAdapterStatus.MALFORMED, None),
])
def test_rejected_source_retains_exact_snapshot_identity_without_proof_requests(source, options, status, unsupported):
    result = _adapt(source, revision="snapshot:rejected-source", **options)
    assert result.status is status
    assert result.program is None and result.document is not None
    source_ref = result.document.sources[0]
    assert source_ref.source_revision == "snapshot:rejected-source"
    assert source_ref.content_sha256 == hashlib.sha256(source.encode()).hexdigest()
    assert not result.backend_requests
    assert not result.document.properties and not result.document.assumptions
    if unsupported is not None:
        assert unsupported in result.unsupported_constructs
    assert SoftwareVerificationIR.from_dict(result.document.to_dict()).to_dict() == result.document.to_dict()


def test_default_workspace_and_legacy_annotation_profile_remain_available():
    result = _adapt("def add(x: int) -> int:\n    value: int = x + 1\n    return value\n", path="add.py")
    assert result.program.sources[0].source_revision == "workspace:local"
    assert {symbol.type_ref for symbol in result.program.symbols} == {"any"}
    assert result.program.functions[0].return_type == "any"


@pytest.mark.parametrize("annotation", ["int", "bool", "float", "CustomType", "'int'", "'bool'", "'float'"])
def test_explicit_annotation_profile_retains_declared_parameter_local_and_result_types(annotation):
    source = f"def identity(x: {annotation}) -> {annotation}:\n    value: {annotation} = x\n    return value\n"
    result = _adapt(source, path="typed.py", preserve_type_annotations=True)
    assert result.status is SourceAdapterStatus.SUCCESS
    expected_type = annotation.strip("'")
    assert {symbol.type_ref for symbol in result.program.symbols} == {expected_type}
    assert result.program.functions[0].return_type == expected_type
    assert result.document.declarations[0].payload["return_type"] == expected_type


@pytest.mark.parametrize("annotation", ["list[int]", "'list[int]'", "builtins.int"])
def test_complex_annotations_remain_explicit_unsupported_frontiers(annotation):
    source = f"def identity(x: {annotation}) -> {annotation}:\n    return x\n"
    result = _adapt(source, path="typed.py", preserve_type_annotations=True)
    assert result.status is SourceAdapterStatus.PARTIAL
    assert "python.annotation.complex" in result.unsupported_constructs
    assert result.program.symbols[0].type_ref == annotation.strip("'")
    assert result.program.functions[0].return_type == annotation.strip("'")


def test_opt_in_keeps_unannotated_inputs_unknown():
    result = _adapt("def add(x):\n    return x + 1\n", path="add.py", preserve_type_annotations=True)
    assert {symbol.type_ref for symbol in result.program.symbols} == {"any"}
    assert result.program.functions[0].return_type == "any"


def test_late_local_annotation_is_retained_and_conflicting_redeclaration_is_unsupported():
    result = _adapt("def identity(x: int):\n    value = x\n    value: int = x\n    value: bool = x\n    return value\n",
                    path="typed.py", preserve_type_annotations=True)
    assert next(symbol for symbol in result.program.symbols if symbol.name == "value").type_ref == "int"
    assert "python.annotation.conflicting_redeclaration" in result.unsupported_constructs
    assert result.status is SourceAdapterStatus.PARTIAL


def test_class_adapter_forwards_revision_and_annotation_profile():
    result = SourceSoftwareVerificationAdapter(include_supervisor_evidence=False,
                                               preserve_type_annotations=True).adapt(
        "def identity(x: bool) -> bool:\n    return x\n", path="typed.py", revision="snapshot:class-adapter")
    assert result.program.sources[0].source_revision == "snapshot:class-adapter"
    assert {symbol.type_ref for symbol in result.program.symbols} == {"bool"}


@pytest.mark.parametrize("revision", [None, 1, "", " revision ", "bad\x00revision"])
def test_invalid_revision_is_rejected_before_source_lowering(revision):
    with pytest.raises(SourceAdapterError, match="revision"):
        _adapt("def identity(x):\n    return x\n", path="sample.py", revision=revision)


@pytest.mark.parametrize("enabled", [None, 0, 1, "true"])
def test_annotation_profile_requires_an_exact_boolean(enabled):
    with pytest.raises(SourceAdapterError, match="preserve_type_annotations"):
        _adapt("def identity(x):\n    return x\n", path="sample.py", preserve_type_annotations=enabled)
