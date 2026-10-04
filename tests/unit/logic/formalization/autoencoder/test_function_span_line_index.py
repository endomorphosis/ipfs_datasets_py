"""One source-local line table preserves every independently verified span."""
import ast
from dataclasses import FrozenInstanceError
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import source_function_units as units
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formalization_evaluation as spans


SOURCES = [
    b'def one(x):\n    return x + 1\n\ndef two(x):\n    return x - 1\n',
    b'class A:\n    @staticmethod\n    def outer(x):\n        def inner(y):\n            return y\n        return inner(x)\n',
    '# unicode λ\nclass A:\n\tasync def run(self, x):\n\t\treturn "λ" + x'.encode(),
    b'class A:\n    def text(self):\n        return """line\nnot indented\n        end"""\n',
    b'@decorate(\n    "tag"\n)\ndef named(x):\n    return x',
]


def test_extraction_shares_one_source_local_index_and_still_replays_each_span(monkeypatch):
    source = SOURCES[1]
    original_span, original_verify = units._function_span, units._verify_span
    indexes, verified = [], []

    def span(*args, **kwargs):
        indexes.append(kwargs.get('_line_index'))
        return original_span(*args, **kwargs)

    def verify(*args):
        verified.append(args[2]['start_byte'])
        return original_verify(*args)

    monkeypatch.setattr(units, '_function_span', span)
    monkeypatch.setattr(units, '_verify_span', verify)
    report = units.extract_function_units(source_bytes=source, source_sha256=hashlib.sha256(source).hexdigest(),
        source_path='module.py')
    assert len(indexes) == len(verified) == len(report['units']) == 2
    assert indexes[0] is not None and all(value is indexes[0] for value in indexes)
    assert all(row['normalized_AST_matches_source_function'] for row in report['units'])


@pytest.mark.parametrize('source', SOURCES)
def test_prepared_and_independent_span_paths_match_exactly(source):
    index = spans._function_line_index(source)
    for node, _, _ in units._qualified_functions(ast.parse(source.decode(), type_comments=True)):
        expected = spans._function_span(source, node)
        actual = spans._function_span(source, node, _line_index=index)
        assert actual == expected
        units._verify_span(source, *actual)


def test_line_table_is_immutable_and_rejects_a_different_source_object():
    source = SOURCES[0]
    index = spans._function_line_index(source)
    with pytest.raises(FrozenInstanceError):
        index.offsets = ()
    assert type(index.lines) is type(index.offsets) is tuple
    copied = bytes(bytearray(source))
    assert copied == source and copied is not source
    node = ast.parse(source.decode()).body[0]
    with pytest.raises(ValueError, match='exact source-local line index'):
        spans._function_span(copied, node, _line_index=index)


def test_extraction_does_not_reuse_a_line_index_between_files(monkeypatch):
    original = units._function_span
    indexes = []

    def span(*args, **kwargs):
        indexes.append(kwargs.get('_line_index'))
        return original(*args, **kwargs)

    monkeypatch.setattr(units, '_function_span', span)
    for source in SOURCES[:2]:
        units.extract_function_units(source_bytes=source, source_sha256=hashlib.sha256(source).hexdigest(),
            source_path='module.py')
    assert len(indexes) == 4
    assert indexes[0] is indexes[1] and indexes[2] is indexes[3]
    assert indexes[0] is not None and indexes[2] is not None and indexes[0] is not indexes[2]
