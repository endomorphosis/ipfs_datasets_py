"""Exact byte replay retains fresh owner, source body and schema authority."""
from pathlib import Path
import json
import sys
import types
import os
import subprocess

import pytest
from multiformats import multihash
from test_codebase_manifest_memo import empty_cache, specimen
from ipfs_datasets_py.logic.software_contracts import codebase_ir as owner, cache, content


def prepared(specimen, tmp_path):
    value, cid = specimen()
    cas = cache.ImmutableCAS(tmp_path/'cas')
    assert cas.put(value) == cid
    return value, cid, cas, owner.RepositoryCodebaseIndex(artifacts=cas)


def test_warm_read_hashes_fresh_bytes_without_materializing_json(specimen, tmp_path):
    value, cid, cas, index = prepared(specimen, tmp_path)
    counters = {'decode': 0, 'read': 0, 'digest': 0}
    codes = {json.loads.__code__: 'decode', cache.ImmutableCAS._read_structured_payload.__code__: 'read',
             content._cid_from_digest_bytes.__code__: 'digest'}
    def observe(frame, event, arg):
        if event == 'call' and frame.f_code in codes:counters[codes[frame.f_code]] += 1
    assert sys.getprofile() is None
    try:
        sys.setprofile(observe)
        cold = index.load(cid)
        assert counters['decode'] > 0
        counters.update(decode=0, read=0, digest=0)
        warm = index.load(cid)
    finally:sys.setprofile(None)
    assert counters == {'decode': 0, 'read': 1, 'digest': 1}
    assert warm is not cold and warm.semantic_state.symbols[0] is not cold.semantic_state.symbols[0]
    assert content.canonical_dag_json_bytes(warm.to_dict()) == content.canonical_dag_json_bytes(value)
    object.__setattr__(warm.snapshot.entries[0], 'path', 'poisoned.py')
    assert index.load(cid).to_dict() == value


@pytest.mark.parametrize('damage', ['changed_body','deleted','noncanonical','oversized','invalid_utf8','invalid_json','other_cid'])
def test_body_damage_after_warming_is_not_hidden(specimen, tmp_path, damage):
    value, cid, cas, index = prepared(specimen, tmp_path);index.load(cid)
    path = cas.path_for(cid);raw = path.read_bytes()
    if damage == 'deleted':path.unlink();error = FileNotFoundError
    else:
        error = cache.CacheIntegrityError
        if damage == 'changed_body':path.write_bytes(raw.replace(b'memo-fixture', b'evil-fixture'))
        elif damage == 'noncanonical':path.write_bytes(raw+b'\n')
        elif damage == 'oversized':cas.max_object_bytes = len(raw)-1
        elif damage == 'invalid_utf8':path.write_bytes(b'\xff')
        elif damage == 'invalid_json':path.write_bytes(b'{')
        else:
            cid = content.cid_for_structured({'different': True});path = cas.path_for(cid)
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    with pytest.raises(error):index.load(cid)


def test_mismatched_schema_cannot_reuse_valid_manifest(specimen, tmp_path):
    value, cid, cas, index = prepared(specimen, tmp_path);index.load(cid)
    value['schema'] = 'unrecognized-manifest'
    other = cas.put(value)
    with pytest.raises(cache.CacheIntegrityError, match='schema'):index.load(other)
    with pytest.raises(cache.CacheIntegrityError, match='schema'):cas.get(cid,expected_schema='different')


def test_exact_bytes_in_another_root_require_that_roots_own_read(specimen, tmp_path):
    value, cid, cas, index = prepared(specimen, tmp_path);index.load(cid)
    other = cache.ImmutableCAS(tmp_path/'other');other_index = owner.RepositoryCodebaseIndex(artifacts=other)
    with pytest.raises(FileNotFoundError):other_index.load(cid)
    other.put(value)
    assert other_index.load(cid).to_dict() == value
    other.path_for(cid).unlink()
    with pytest.raises(FileNotFoundError):other_index.load(cid)


@pytest.mark.parametrize('kind', ['subclass_get','subclass_read','instance_get','instance_path','class_get','class_read','class_path','class_decode'])
def test_custom_readers_execute_original_get_path(specimen, tmp_path, monkeypatch, kind):
    value, cid, cas, index = prepared(specimen, tmp_path);index.load(cid)
    class Expected(RuntimeError):pass
    def refuse(*args, **kwargs):raise Expected('custom owner called')
    if kind.startswith('subclass'):
        name = 'get' if kind == 'subclass_get' else '_read_structured_payload'
        custom = type('CustomCAS', (cache.ImmutableCAS,), {name:refuse})(cas.root)
        index.artifacts = custom
    elif kind.startswith('instance'):
        setattr(cas, 'get' if kind == 'instance_get' else 'path_for', refuse)
    else:
        name = {'class_get':'get','class_read':'_read_structured_payload',
                'class_path':'path_for','class_decode':'_decode_structured_payload'}[kind]
        monkeypatch.setattr(cache.ImmutableCAS, name, refuse)
    with pytest.raises(Expected, match='custom owner called'):index.load(cid)


@pytest.mark.parametrize('mutation', ['code','defaults','json_loads','json_decoder','json_encoder'])
def test_native_function_or_decoder_changes_bypass_prior_byte_replay(specimen, tmp_path, monkeypatch, mutation):
    value, cid, cas, index = prepared(specimen, tmp_path);index.load(cid)
    calls=[]
    if mutation == 'code':
        original = cache.ImmutableCAS.get
        def replacement(self,cid,*,expected_schema=None):raise RuntimeError('changed native code')
        monkeypatch.setattr(original, '__code__', replacement.__code__)
        with pytest.raises(RuntimeError, match='changed native code'):index.load(cid)
    elif mutation == 'defaults':
        method = cache.ImmutableCAS.get
        monkeypatch.setattr(method, '__kwdefaults__', {'expected_schema': 'different-default'})
        assert index.load(cid).to_dict() == value
    elif mutation == 'json_loads':
        original = json.loads
        def changed(*args, **kwargs):calls.append(True);return original(*args, **kwargs)
        monkeypatch.setattr(json,'loads',changed)
        assert index.load(cid).to_dict() == value
        assert calls
    elif mutation == 'json_decoder':
        obj = json._default_decoder;original = obj.decode
        def changed(*args, **kwargs):calls.append(True);return original(*args, **kwargs)
        monkeypatch.setitem(vars(obj),'decode',changed)
        assert index.load(cid).to_dict() == value
        assert calls
    else:
        original = json.JSONEncoder.encode
        def changed(*args, **kwargs):calls.append(True);return original(*args, **kwargs)
        monkeypatch.setattr(json.JSONEncoder,'encode',changed)
        assert index.load(cid).to_dict() == value
        assert calls
    assert owner._manifest_producer_key() is None
    assert owner._MANIFEST_MEMO_STATS['hits'] == 0


@pytest.mark.parametrize('warm', [False,True])
@pytest.mark.parametrize('drift', ['producer','registry','owner','cache_json','content_json'])
def test_drift_during_actual_read_refuses_even_exact_body(specimen, tmp_path, monkeypatch, warm, drift):
    value,cid,cas,index = prepared(specimen,tmp_path)
    if warm:index.load(cid)
    target = cas.path_for(cid);original = Path.open;implementation,size = multihash.raw.get('sha2-256')
    class Stream:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):self.stream.__enter__();return self
        def __exit__(self,*args):return self.stream.__exit__(*args)
        def read(self,*args):
            raw=self.stream.read(*args)
            if drift == 'producer':monkeypatch.setattr(owner,'CODEBASE_IR_SCHEMA','changed')
            elif drift == 'registry':multihash.raw.register('sha2-256',implementation,16,overwrite=True)
            elif drift == 'owner':cas.max_object_bytes += 1
            else:
                module = cache if drift == 'cache_json' else content
                monkeypatch.setattr(module,'json',types.SimpleNamespace(loads=json.loads,dumps=json.dumps))
            return raw
    def opened(path,*args,**kwargs):
        stream=original(path,*args,**kwargs)
        return Stream(stream) if path == target else stream
    monkeypatch.setattr(Path,'open',opened)
    try:
        with pytest.raises(owner.CodebaseIRError, match='producer, registry or owner changed'):index.load(cid)
        assert owner._MANIFEST_MEMO_STATS['hits'] == 0
    finally:multihash.raw.register('sha2-256',implementation,size,overwrite=True)


@pytest.mark.parametrize('alias', ['get','get_structured','read'])
def test_public_cas_get_aliases_still_decode_and_validate(specimen, tmp_path, alias):
    value,cid,cas,index=prepared(specimen,tmp_path);index.load(cid)
    assert getattr(cas,alias)(cid,expected_schema=owner.CODEBASE_IR_SCHEMA) == value
    cas.path_for(cid).write_bytes(cas.path_for(cid).read_bytes()+b'\n')
    with pytest.raises(cache.CacheIntegrityError,match='not canonical'):
        getattr(cas,alias)(cid,expected_schema=owner.CODEBASE_IR_SCHEMA)


@pytest.mark.parametrize('warm', [False, True])
@pytest.mark.parametrize('module', ['cache','content','owner'])
def test_replaced_json_module_alias_cannot_bypass_original_semantics(specimen,tmp_path,monkeypatch,warm,module):
    value,cid,cas,index=prepared(specimen,tmp_path)
    if warm:index.load(cid)
    target={'cache':cache,'content':content,'owner':owner}[module]
    calls=[]
    def loads(*args,**kwargs):calls.append('loads');return json.loads(*args,**kwargs)
    def dumps(*args,**kwargs):calls.append('dumps');return json.dumps(*args,**kwargs)
    # Other module attributes remain compatible; identity still marks this
    # custom alias unsupported before any private-byte replay is considered.
    replacement=types.SimpleNamespace(**vars(json))
    replacement.loads=loads;replacement.dumps=dumps
    monkeypatch.setattr(target,'json',replacement)
    assert owner._manifest_producer_key() is None
    assert index.load(cid).to_dict() == value
    if module != 'owner':assert calls
    assert owner._MANIFEST_MEMO_STATS['hits'] == 0


@pytest.mark.parametrize('attempts', [1,2])
@pytest.mark.parametrize('mode', ['get','read','decode','path','code','defaults',
                                'json_alias','json_decoder','prior_json_loads','prior_json_defaults',
                                'prior_json_scan','prior_json_constant','canonical_alias','cid_alias','prior_json_decode_default'])
def test_customizations_before_manifest_import_keep_original_get(specimen,tmp_path,mode,attempts):
    value,_=specimen();fixture=tmp_path/'fixture.json';fixture.write_text(json.dumps(value))
    result=subprocess.run([sys.executable,'-B','-c',IMPORT_ORDER_SCRIPT,str(fixture),mode,str(attempts)],
        capture_output=True,text=True,env=dict(os.environ),timeout=30)
    assert result.returncode==0,result.stderr
    record=json.loads(result.stdout.splitlines()[-1])
    assert record['exact_output'] and not record['native_reader_eligible']
    assert record['byte_replay_hits']==0


IMPORT_ORDER_SCRIPT = '"""Fresh-process reader customization probe; only synthetic fixture input."""\nfrom pathlib import Path\nimport json,sys,types\n\nfixture=Path(sys.argv[1]);mode=sys.argv[2];attempts=int(sys.argv[3]);value=json.loads(fixture.read_text())\nassert attempts in (1,2)\ncalls=[]\nif mode.startswith(\'prior_json\'):\n    original=json.loads\n    if mode == \'prior_json_defaults\':\n        json.loads.__kwdefaults__={**json.loads.__kwdefaults__,\'parse_int\':lambda v:(calls.append(\'parse_int\'),int(v))[1]}\n    elif mode==\'prior_json_decode_default\':\n        original=json.JSONDecoder.decode.__defaults__[0]\n        def changed(*args,**kwargs):calls.append(\'decode_default\');return original(*args,**kwargs)\n        json.JSONDecoder.decode.__defaults__=(changed,)\n    elif mode==\'prior_json_scan\':\n        original=json._default_decoder.scan_once\n        def changed(*args,**kwargs):calls.append(\'scan_once\');return original(*args,**kwargs)\n        json._default_decoder.scan_once=changed\n    elif mode==\'prior_json_constant\':\n        original=json._default_decoder.parse_constant\n        def changed(*args,**kwargs):calls.append(\'parse_constant\');return original(*args,**kwargs)\n        json._default_decoder.parse_constant=changed\n    else:\n        def changed(*args,**kwargs):calls.append(\'loads\');return original(*args,**kwargs)\n        json.loads=changed\n\nfrom ipfs_datasets_py.logic.software_contracts import cache,content\nassert \'ipfs_datasets_py.logic.software_contracts.codebase_ir\' not in sys.modules\ncas=cache.ImmutableCAS(fixture.parent/\'cas\');cid=cas.put(value)\nif mode in (\'get\',\'read\',\'decode\',\'path\'):\n    name={\'get\':\'get\',\'read\':\'_read_structured_payload\',\'decode\':\'_decode_structured_payload\',\'path\':\'path_for\'}[mode]\n    original=getattr(cache.ImmutableCAS,name)\n    def changed(*args,**kwargs):calls.append(mode);return original(*args,**kwargs)\n    setattr(cache.ImmutableCAS,name,staticmethod(changed) if mode==\'decode\' else changed)\nelif mode==\'code\':\n    original=cache.ImmutableCAS.get\n    saved=types.FunctionType(original.__code__,original.__globals__,original.__name__,original.__defaults__)\n    saved.__kwdefaults__=dict(original.__kwdefaults__)\n    cache._probe_saved_get=saved;cache._probe_calls=calls\n    def replacement(self,cid,*,expected_schema=None):\n        _probe_calls.append(\'code\')\n        return _probe_saved_get(self,cid,expected_schema=expected_schema)\n    original.__code__=replacement.__code__\nelif mode==\'defaults\':\n    cache.ImmutableCAS.get.__kwdefaults__={\'expected_schema\':\'different-default\'}\nelif mode==\'json_alias\':\n    replacement=types.SimpleNamespace(**vars(json));original=json.loads\n    def changed(*args,**kwargs):calls.append(\'json_alias\');return original(*args,**kwargs)\n    replacement.loads=changed;cache.json=replacement\nelif mode==\'json_decoder\':\n    original=json._default_decoder.decode\n    def changed(*args,**kwargs):calls.append(\'decode\');return original(*args,**kwargs)\n    vars(json._default_decoder)[\'decode\']=changed\nelif mode in (\'canonical_alias\',\'cid_alias\'):\n    name=\'canonical_dag_json_bytes\' if mode==\'canonical_alias\' else \'decode_and_recompute_structured\'\n    original=getattr(cache,name)\n    def changed(*args,**kwargs):calls.append(mode);return original(*args,**kwargs)\n    setattr(cache,name,changed)\nelif not mode.startswith(\'prior_json\'):\n    raise ValueError(\'unsupported probe mode\')\n\nfrom ipfs_datasets_py.logic.software_contracts import codebase_ir as owner\nassert cache._structured_reader_is_native() is False\nassert owner._manifest_producer_key() is None\nindex=owner.RepositoryCodebaseIndex(artifacts=cas);calls.clear()\nfor _ in range(attempts):assert index.load(cid).to_dict()==value\nassert owner._MANIFEST_MEMO_STATS[\'hits\']==0\nassert owner._MANIFEST_MEMO_STATS[\'bypasses\']==attempts\nif mode not in (\'defaults\',\'prior_json_constant\'):assert len(calls)>=attempts\nprint(json.dumps(dict(mode=mode,attempts=attempts,custom_calls=len(calls),byte_replay_hits=0,\n    native_reader_eligible=False,exact_output=True)))\n'
