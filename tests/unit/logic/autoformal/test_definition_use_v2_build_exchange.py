"""Cold readback of authored build observations; no compiler runs in these cases.

The existing author's simulated runner supplies clearly marked fake artifacts.
These checks exercise public transport and reconstruction, not native proof.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_build_v2 as owner


@lru_cache(maxsize=1)
def fixtures():
    result = []
    for filename, name in (
        ("test_legal_corpus_definition_use_build_v2.py", "joined_authored_build"),
        ("test_definition_use_v2_native_project_exchange.py", "joined_project_handoff"),
    ):
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result.append(module)
    return tuple(result)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


COLD = r'''
import base64,hashlib,json,math,pathlib,subprocess,sys
def forbidden(*args,**kwargs):
    raise AssertionError('historical build loading must not run a compiler or probe')
subprocess.Popen=forbidden
tag='__native_project_test_bytes_base64__'
def pairs(items):
    value={}
    for key,item in items:
        assert key not in value
        value[key]=item
    return value
def unpack(value,depth=0):
    assert depth<=64
    if value is None or type(value) in (str,int,bool):return value
    if type(value) is float:
        assert math.isfinite(value)
        return value
    if type(value) is list:return [unpack(item,depth+1) for item in value]
    assert type(value) is dict
    if tag in value:
        assert set(value)=={tag}
        raw=base64.b64decode(value[tag],validate=True)
        assert base64.b64encode(raw).decode('ascii')==value[tag]
        return raw
    return {key:unpack(item,depth+1) for key,item in value.items()}
handoff=pathlib.Path(sys.argv[1]);raw=handoff.read_bytes()
assert 0<len(raw)<=64*1024*1024
assert hashlib.sha256(raw).hexdigest()==sys.argv[2]
value=unpack(json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite'))))
assert set(value)=={'arguments','expected_binary_sha256','expected_manifest_sha256'}
arguments=value['arguments']
assert set(arguments)=={'assessment_raw','expected_assessment_file_sha256','review_inputs','toolchain'}
assert len(arguments['review_inputs'])==17
assert all(not pathlib.Path(name).exists() for name in value['expected_binary_sha256'])
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_build_v2 as build
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as prep
assert pathlib.Path(build.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[5]))
prepared=prep.load_definition_use_corpus_v2(pathlib.Path(sys.argv[3])/'project',expected_manifest_sha256=value['expected_manifest_sha256'],**arguments)
receipt=build.load_definition_use_build_v2(sys.argv[3],prepared,expected_receipt_sha256=sys.argv[4],expected_binary_sha256=value['expected_binary_sha256'],**arguments)
assert all(receipt[name] is False for name in build.FALSE_FLAGS)
assert receipt['engineering_build_only'] is True
assert receipt['admission_build_eligible'] is False
assert prepared.to_dict()['build_eligible'] is False
for prefix in ('symai','torch','transformers','tensorflow'):
    assert not any(name==prefix or name.startswith(prefix+'.') for name in sys.modules)
sys.stdout.write(json.dumps(receipt,sort_keys=True,ensure_ascii=False,allow_nan=False))
'''


@pytest.mark.parametrize("family,failure", [("fol", None), ("tdfol", None), ("fol", "missing_output")])
def test_cold_build_readback_preserves_authored_observation_without_live_toolchain(
    tmp_path, monkeypatch, family, failure
):
    authored, exchange = fixtures()
    case = authored.prepared_case(family)
    original_preparation = deepcopy(case["preparation"])
    original_arguments = authored._PREP.arguments(case["data"])
    captured = authored.install_runner(owner, monkeypatch, tmp_path, case, failure=failure)
    directory = tmp_path / "saved-authored-build"
    receipt = authored.build(owner, case, captured, directory)
    assert len(captured["run_calls"]) == len(captured["probe_calls"]) == 1
    assert all(body.startswith(b"AUTHORED-FAKE-OLEAN-NOT-COMPILER-OUTPUT:") for body in captured["outputs"].values())
    assert receipt["build_passed"] is (failure is None)
    assert receipt["manifest_coverage_passed"] is (failure is None)
    assert receipt["kernel_proofs_checked"] is (failure is None)
    assert len(receipt["compiled_modules"]) == (6 if failure is None else 5)
    assert all(receipt[name] is False for name in owner.FALSE_FLAGS)
    assert case["preparation"] == original_preparation
    before = exchange.retained_files(directory)
    original_receipt_raw = before["build-receipt.json"]
    # The original external receipt commitment is retained before later loading.
    expected_receipt_sha256 = sha(original_receipt_raw)
    for path in captured["files"].values():
        path.unlink()
    payload = {
        "arguments": original_arguments,
        "expected_binary_sha256": captured["pins"],
        "expected_manifest_sha256": sha(original_preparation.manifest_json.encode()),
    }
    raw = json.dumps(exchange.packed(payload), sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    handoff = tmp_path / "public-build-handoff.json"
    handoff.write_bytes(raw)
    root = Path(__file__).resolve().parents[4]
    completed = subprocess.run(
        [sys.executable, "-B", "-c", COLD, str(handoff), sha(raw), str(directory), expected_receipt_sha256, str(root)],
        cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=os.pathsep.join([str(root), *filter(None, os.environ.get("PYTHONPATH", "").split(os.pathsep))]), PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0"),
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert json.loads(completed.stdout) == receipt
    assert exchange.retained_files(directory) == before
    assert authored._PREP.arguments(case["data"]) == original_arguments
    # A current dependency change must not be confused with historical custody.
    changed = deepcopy(case)
    observations = changed["data"]["review_inputs"]["observed_artifact_sha256s"]
    observations[next(iter(observations))] = "0" * 64
    with pytest.raises(ValueError):
        authored.load(owner, changed, captured, directory, expected_receipt_sha256)
    with pytest.raises(ValueError):
        authored.load(owner, case, captured, directory, "0" * 64)
    assert exchange.retained_files(directory) == before
    assert (directory / "build-receipt.json").read_bytes() == original_receipt_raw
