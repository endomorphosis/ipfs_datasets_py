"""Authored review custody survives native-project transport without a build.

The existing fixture supplies synthetic legal/formal signatures, not actual
statutory reviews. Fresh child interpreters only replay and load candidate text;
no Lean toolchain, proof kernel, model or target program is executed.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_definition_use_review_v2 as review
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as owner
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import scoped_definition_resolution as resolver
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


_BYTES = "__native_project_test_bytes_base64__"
_MAX_HANDOFF_BYTES = 64 * 1024 * 1024


@lru_cache(maxsize=1)
def authored_fixtures():
    modules = []
    for filename, name in (
        ("test_legal_corpus_definition_use_lake_v2.py", "native_project_authored_review"),
        ("test_definition_use_review_v2_graph_exchange.py", "native_project_table_controls"),
    ):
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return tuple(modules)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def packed(value, depth=0):
    """Encode only ordinary controlled JSON and exact bytes; never key objects."""
    assert depth <= 64
    if type(value) is bytes:
        return {_BYTES: base64.b64encode(value).decode("ascii")}
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        assert math.isfinite(value)
        return value
    if type(value) is list:
        return [packed(item, depth + 1) for item in value]
    assert type(value) is dict and _BYTES not in value
    assert all(type(key) is str for key in value)
    return {key: packed(item, depth + 1) for key, item in value.items()}


def original_inputs(data, alias_fixture):
    originals = alias_fixture.original_bytes(data["signed"]["component"]["case"])
    fields = {
        "candidate_raw", "report_raw", "request_raw", "raw_html",
        "sampling_report_raw", "descriptor_raw",
    }
    assert set(originals) == {
        role + "/" + field + ".bin"
        for role in ("donor", "consumer") for field in fields
    }
    assert all(type(raw) is bytes for raw in originals.values())
    return originals


def retain_originals(directory, originals):
    directory.mkdir(mode=0o700)
    for role in ("donor", "consumer"):
        (directory / role).mkdir(mode=0o700)
    for name, raw in originals.items():
        (directory / name).write_bytes(raw)


def retained_files(directory):
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*") if path.is_file()
    }


def assert_preparation(prepared, data):
    assert type(prepared) is owner.DefinitionUseCorpusPreparation
    manifest, files = prepared.to_dict(), dict(prepared.files)
    assert len(files) == len(prepared.files) == 9
    assert len(manifest["expected_modules"]) == 6
    lean_paths = {module.replace(".", "/") + ".lean" for module in manifest["expected_modules"]}
    assert {name for name in files if name.endswith(".lean")} == lean_paths
    assert manifest["file_sha256"] == {name: sha(text.encode("utf-8")) for name, text in files.items()}
    record = data["signed"]["component"]["record"]
    fragments = {row["role"]: row for row in manifest["native_fragments"]}
    assert list(fragments) == ["donor", "consumer", "alias", "joint"]
    for role in ("donor", "consumer"):
        candidate = data["signed"]["component"]["case"][role]["candidate"]
        assert fragments[role]["native"]["native_ast"] == candidate["definition_record"]["native_ast"]
    assert fragments["alias"]["native"]["native_ast"] == record["alias_native"]["native_ast"]
    assert fragments["joint"]["native"]["native_ast"] == record["joint_native"]["native_ast"]
    assert manifest["review_dependency_manifest"] == data["signed"]["manifest"]
    assert manifest["review_evidence_status"] == data["assessment"]["evidence_assessment_status"]
    assert manifest["review_blockers"] == data["assessment"]["blockers"]
    assert manifest["preparation_only"] is True
    assert manifest["lean_compilation_status"] == "not_run" and manifest["proof_status"] == "pending"
    assert all(manifest[flag] is False for flag in owner.FALSE_FLAGS)
    assert all(row["native"]["backend_executed"] is False for row in fragments.values())
    handoff = manifest["execution_handoff"]
    assert handoff["processes_executed"] == 0 and handoff["build_eligible"] is False
    assert handoff["installed_binary_pins"] is None
    assert handoff["observed_theorem_axiom_dependencies"] is None
    return manifest


_COLD_LOAD = r'''
import base64,hashlib,json,math,pathlib,subprocess,sys
def forbidden(*args,**kwargs):
    raise AssertionError('native project replay must not execute a process or toolchain')
subprocess.Popen=forbidden
tag='__native_project_test_bytes_base64__'
def pairs(items):
    result={}
    for key,value in items:
        assert key not in result
        result[key]=value
    return result
def unpack(value,depth=0):
    assert depth<=64
    if value is None or type(value) in (str,bool,int): return value
    if type(value) is float:
        assert math.isfinite(value)
        return value
    if type(value) is list: return [unpack(item,depth+1) for item in value]
    assert type(value) is dict
    if tag in value:
        assert set(value)=={tag} and type(value[tag]) is str
        raw=base64.b64decode(value[tag],validate=True)
        assert base64.b64encode(raw).decode('ascii')==value[tag]
        return raw
    return {key:unpack(item,depth+1) for key,item in value.items()}
path=pathlib.Path(sys.argv[1])
assert 0<path.stat().st_size<=64*1024*1024
raw=path.read_bytes()
assert hashlib.sha256(raw).hexdigest()==sys.argv[2]
arguments=unpack(json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON'))))
assert set(arguments)=={'assessment_raw','expected_assessment_file_sha256','review_inputs','toolchain'}
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as owner
assert pathlib.Path(owner.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[5]))
assert len(arguments['review_inputs'])==17 and set(arguments['review_inputs'])==owner.REVIEW_INPUT_FIELDS
loaded=owner.load_definition_use_corpus_v2(sys.argv[3],expected_manifest_sha256=sys.argv[4],**arguments)
assert type(loaded) is owner.DefinitionUseCorpusPreparation
manifest=loaded.to_dict()
assert all(manifest[flag] is False for flag in owner.FALSE_FLAGS)
assert manifest['execution_handoff']['processes_executed']==0
assert manifest['lean_compilation_status']=='not_run'
hashes={}
for role in ('donor','consumer'):
    inputs=arguments['review_inputs']['use_inputs'][role+'_evidence_inputs']['candidate_inputs']
    for name,body in inputs.items():
        assert type(body) is bytes
        hashes[role+'/'+name+'.bin']=hashlib.sha256(body).hexdigest()
assert len(hashes)==12
for prefix in ('torch','transformers','tensorflow'):
    assert not any(name==prefix or name.startswith(prefix+'.') for name in sys.modules)
sys.stdout.write(json.dumps({'manifest':manifest,'manifest_json':loaded.manifest_json,'files':loaded.files,'original_sha256s':hashes},sort_keys=True,ensure_ascii=False,allow_nan=False))
'''


def cold_load(tmp_path, directory, prepared, data, originals, fixture):
    arguments = fixture.arguments(data)
    assert len(arguments["review_inputs"]) == 17
    assert set(arguments["review_inputs"]) == owner.REVIEW_INPUT_FIELDS
    # Only public review inputs travel: never the fixture, signers or private keys.
    raw = json.dumps(packed(arguments), sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    assert 0 < len(raw) <= _MAX_HANDOFF_BYTES
    handoff = tmp_path / (directory.name + "-review-handoff.json")
    with handoff.open("xb") as stream:
        stream.write(raw)
    manifest_raw = (directory / "corpus-manifest.json").read_bytes()
    assert manifest_raw == prepared.manifest_json.encode("utf-8")
    expected_manifest_sha256 = sha(prepared.manifest_json.encode("utf-8"))
    root = Path(__file__).resolve().parents[4]
    completed = subprocess.run(
        [sys.executable, "-c", _COLD_LOAD, str(handoff), sha(raw), str(directory), expected_manifest_sha256, str(root)],
        cwd=tmp_path,
        env=dict(
            os.environ,
            PYTHONPATH=os.pathsep.join([str(root), *filter(None, os.environ.get("PYTHONPATH", "").split(os.pathsep))]),
            PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
            IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0",
        ),
        capture_output=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    loaded = json.loads(completed.stdout)
    assert loaded["manifest"] == prepared.to_dict()
    assert loaded["manifest_json"] == prepared.manifest_json
    assert tuple(tuple(row) for row in loaded["files"]) == prepared.files
    assert loaded["original_sha256s"] == {name: sha(body) for name, body in originals.items()}
    assert handoff.read_bytes() == raw


def write_and_check(directory, prepared, data, fixture):
    assert owner.write_definition_use_corpus_v2(prepared, directory, **fixture.arguments(data)) == prepared.to_dict()
    assert retained_files(directory) == {
        "corpus-manifest.json": prepared.manifest_json.encode("utf-8"),
        **{name: text.encode("utf-8") for name, text in prepared.files},
    }


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_public_native_project_fresh_process_load_preserves_exact_review_and_sources(tmp_path, family):
    fixture, graph_fixture = authored_fixtures()
    _, alias_fixture = graph_fixture.authored_fixtures()
    data = fixture.assessment_data(family)
    component = data["signed"]["component"]
    component_before = canonical_dag_json_bytes(component["record"])
    dependency_before = canonical_dag_json_bytes(data["signed"]["manifest"])
    originals = original_inputs(data, alias_fixture)
    retained = tmp_path / "original-inputs"
    retain_originals(retained, originals)
    graph_fixture.assert_authenticated_pair(data["assessment"])
    assert data["assessment"]["review_prerequisites_satisfied_under_selected_trust"] is True
    prepared = fixture.prepare(owner, data)
    assert_preparation(prepared, data)
    directory = tmp_path / "candidate-project"
    write_and_check(directory, prepared, data, fixture)
    cold_load(tmp_path, directory, prepared, data, originals, fixture)
    assert canonical_dag_json_bytes(component["record"]) == component_before
    assert canonical_dag_json_bytes(data["signed"]["manifest"]) == dependency_before
    assert original_inputs(data, alias_fixture) == originals == retained_files(retained)


def test_real_competing_table_invalidates_old_assessment_and_replays_blocked_project(tmp_path):
    fixture, graph_fixture = authored_fixtures()
    _, alias_fixture = graph_fixture.authored_fixtures()
    data = fixture.assessment_data()
    signed, component = data["signed"], data["signed"]["component"]
    originals = original_inputs(data, alias_fixture)
    component_before = canonical_dag_json_bytes(component["record"])
    graph_before = {role: canonical_dag_json_bytes(component["case"][role]["candidate"]["graph"]) for role in ("donor", "consumer")}
    dependency_before = canonical_dag_json_bytes(signed["manifest"])
    reviews_before = canonical_dag_json_bytes(signed["reviews"])
    stable = data["assessment"]
    graph_fixture.assert_authenticated_pair(stable)
    assert stable["review_prerequisites_satisfied_under_selected_trust"] is True
    prepared = fixture.prepare(owner, data)
    directory = tmp_path / "original-project"
    write_and_check(directory, prepared, data, fixture)
    original_project = retained_files(directory)
    manifest_sha = sha(original_project["corpus-manifest.json"])

    # Rebuild the existing real registry/table fixture, retaining both source documents.
    changed = deepcopy(component["case"])
    changed["lookup_inputs"] = fixture._COMBINED._USE.lookup_inputs(changed, status="ambiguous")
    old_registry = json.loads(component["case"]["lookup_inputs"]["registry_raw"])
    new_registry = json.loads(changed["lookup_inputs"]["registry_raw"])
    old_parts = {row["partition_id"]: row for row in old_registry["partitions"]}
    new_parts = {row["partition_id"]: row for row in new_registry["partitions"]}
    assert old_parts["local"] == new_parts["local"]
    old_donor, new_donor = old_parts["donor"], new_parts["donor"]
    old_rows = json.loads(old_donor["table_json"])["definitions"]
    new_rows = json.loads(new_donor["table_json"])["definitions"]
    assert len(old_rows) == 1 and len(new_rows) == 2 and all(row in new_rows for row in old_rows)
    assert old_donor["table_sha256"] == sha(old_donor["table_json"].encode())
    assert new_donor["table_sha256"] == sha(new_donor["table_json"].encode()) != old_donor["table_sha256"]
    current = alias_fixture.observations(signed["manifest"])
    donor_id = "definition-partition:donor"
    assert current["observed_artifact_sha256s"][donor_id] == sha(canonical_dag_json_bytes(old_donor))
    current["observed_artifact_sha256s"][donor_id] = sha(canonical_dag_json_bytes(new_donor))
    current["observed_pins"]["definition"]["definition-table:donor"] = new_donor["table_sha256"]
    invalidation = dependencies.invalidate_dependencies(signed["manifest"], **current)
    assert invalidation["seed_artifact_ids"] == [donor_id]
    assert {row["code"] for row in invalidation["seed_reasons"][donor_id]} == {"artifact_changed", "dependency_pin_changed"}
    lookup_id = "definition-lookup:" + component["case"]["lookup_inputs"]["expected_lookup_cid"]
    assert {donor_id, lookup_id, component["record"]["graph"]["record_cid"]} <= set(invalidation["stale_artifact_ids"])
    assert dependencies.validate_invalidation(invalidation, signed["manifest"], **current) == invalidation
    query_raw = component["case"]["lookup_inputs"]["query_raw"]
    lookup = resolver.resolve_definition_lookup(new_registry, query_raw, sha(query_raw))
    assert lookup == json.loads(changed["lookup_inputs"]["lookup_raw"])
    assert lookup["status"] == "ambiguous" and lookup["selected_symbol_id"] is None

    signed["observed_artifact_sha256s"] = current["observed_artifact_sha256s"]
    signed["observed_pins"] = current["observed_pins"]
    blocked_data = fixture.refresh_assessment(signed)
    blocked = blocked_data["assessment"]
    graph_fixture.assert_authenticated_pair(blocked)
    assert blocked["dependency_invalidation_sha256"] == invalidation["invalidation_sha256"]
    assert "required_dependency_closure_not_current" in blocked["blockers"]
    assert blocked["review_prerequisites_satisfied_under_selected_trust"] is False
    with pytest.raises(ValueError):
        review.validate_definition_use_review_assessment_v2(stable, **blocked_data["review_inputs"])
    with pytest.raises(ValueError):
        owner.load_definition_use_corpus_v2(directory, expected_manifest_sha256=manifest_sha, **fixture.arguments(blocked_data))
    blocked_prepared = fixture.prepare(owner, blocked_data)
    blocked_manifest = assert_preparation(blocked_prepared, blocked_data)
    assert blocked_manifest["review_prerequisites_satisfied_under_selected_trust"] is False
    assert blocked_prepared != prepared
    assert blocked_prepared == fixture.prepare(owner, blocked_data)
    blocked_directory = tmp_path / "blocked-project"
    write_and_check(blocked_directory, blocked_prepared, blocked_data, fixture)
    cold_load(tmp_path, blocked_directory, blocked_prepared, blocked_data, originals, fixture)
    assert owner.load_definition_use_corpus_v2(directory, expected_manifest_sha256=manifest_sha, **fixture.arguments(data)) == prepared
    assert retained_files(directory) == original_project
    assert canonical_dag_json_bytes(component["record"]) == component_before
    assert canonical_dag_json_bytes(signed["manifest"]) == dependency_before
    assert canonical_dag_json_bytes(signed["reviews"]) == reviews_before
    assert original_inputs(blocked_data, alias_fixture) == originals == alias_fixture.original_bytes(changed)
    for role in ("donor", "consumer"):
        assert canonical_dag_json_bytes(component["case"][role]["candidate"]["graph"]) == graph_before[role]
