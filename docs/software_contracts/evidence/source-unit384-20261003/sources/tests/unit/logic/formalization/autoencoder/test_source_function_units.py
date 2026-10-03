"""Exact unit maps reuse original bytes; no model or source execution."""
from copy import deepcopy
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import source_function_units as api


SOURCE = (b'# no imported code is executed\nraise RuntimeError("must not execute")\n'
    b'def outer(x: int) -> int:\n    def inner(y: int) -> int:\n        return y + 1\n    return inner(x)\n'
    b'class Box:\n    @staticmethod\n    def method(a: int, b: int) -> int:\n        return a + b\n')


def extract(source=SOURCE, **options):
    return api.extract_function_units(source_bytes=source,source_sha256=hashlib.sha256(source).hexdigest(),
        source_path='package/module.py',**options)


def test_complete_nested_and_decorated_functions_keep_original_maps():
    value=extract()
    assert [u['qualified_name'] for u in value['units']]==['outer','outer.inner','Box.method']
    assert [u['enclosing_scope'] for u in value['units']]==[[],['outer'],['Box']]
    assert all(u['normalized_AST_matches_source_function'] for u in value['units'])
    for unit in value['units']:
        assert SOURCE[unit['start_byte']:unit['end_byte']]
        assert unit['source_sha256']==value['source_sha256']
        api._verify_span(SOURCE,unit['normalized_source_text'].encode(),unit['source_binding'])
        assert unit['normalized_body_sha256']==hashlib.sha256(unit['normalized_source_text'].encode()).hexdigest()
        assert not unit['proof_authority'] and not unit['whole_file_semantics_verified']
    assert api.validate_function_units(value,source_bytes=SOURCE)==value
    assert not value['source_executed']


@pytest.mark.parametrize('damage',['map','range','name','scope','body','ast','omission','extra','path'])
def test_source_map_replay_rejects_resealed_or_malformed_unit_claims(damage):
    value=deepcopy(extract());unit=value['units'][1]
    if damage=='map':unit['source_binding']['line_byte_map'][0]['source_start_byte']+=1
    elif damage=='range':unit['start_byte']+=1
    elif damage=='name':unit['qualified_name']='substituted'
    elif damage=='scope':unit['enclosing_scope']=[]
    elif damage=='body':unit['normalized_source_text']='def fixture():\n    return 1'
    elif damage=='ast':unit['normalized_AST_matches_source_function']=False
    elif damage=='omission':value['units'].pop()
    elif damage=='extra':unit['target']={'operator':'+'}
    else:value['source_path']='../outside.py'
    with pytest.raises(ValueError):api.validate_function_units(value,source_bytes=SOURCE)


def test_large_original_file_is_not_silently_replaced_or_truncated():
    source=b'#'+b'x'*70000+b'\ndef calculation(a: int, b: int) -> int:\n    return a + b\n'
    value=extract(source)
    assert value['source_bytes']>65536 and len(value['units'])==1
    unit=value['units'][0]
    assert unit['start_byte']==70002 and unit['normalized_source_text']==source[70002:].decode().rstrip('\n')
    assert value['source_sha256']!=unit['normalized_body_sha256']


@pytest.mark.parametrize('source,frontier',[
    (b'def broken(:\n pass','complete_python_source_required'),
    (b'not python at all','complete_python_source_required'),
    (b'x=1\n','no_function_units'),
    (b'def f():\r\n    return 1\r\n','source_line_controls_not_mapped'),
    (b'#\n'*16385,'source_line_map_bound_exceeded'),
])
def test_file_frontiers_are_explicit_and_do_not_invent_functions(source,frontier):
    value=extract(source)
    assert value['frontier']==frontier and value['units']==[]


def test_function_bound_refuses_complete_population_instead_of_prefix():
    with pytest.raises(ValueError,match='not truncated'):extract(max_functions=2)


def test_multiline_literal_normalization_cannot_change_semantics():
    source=b'class C:\n    def f():\n        return """a\n        b"""\n'
    value=extract(source)
    assert value['units'][0]['status']=='unsupported_normalization'
    assert not value['units'][0]['normalized_AST_matches_source_function']
