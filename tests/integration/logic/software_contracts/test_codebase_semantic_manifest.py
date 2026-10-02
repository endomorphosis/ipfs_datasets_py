"""Whole-inventory semantics compose the native typed owners without execution."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.integration.logic.software_contracts.test_codebase_scan_policy import current
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.logic.software_contracts import codebase_integer_profile as integer
from ipfs_datasets_py.logic.software_contracts import codebase_semantic_manifest as module
from ipfs_datasets_py.logic.software_contracts.codebase_resources import acquire_codebase_resources
from ipfs_datasets_py.logic.software_verification.program import ProgramIR
from ipfs_datasets_py.logic.software_verification.contracts import ProgramContract


@pytest.fixture
def prepared(current):
    root, index, prepare, _, _ = current
    (root / "main.py").write_text("def increment(n: int) -> int:\n    return n + 1\n")
    (root / "missing.py").write_text("def missing(n: int) -> int:\n    return n + 2\n")
    contracts = (
        integer.IntegerOffsetContract("main.py", "increment", "n", 1),
        integer.IntegerOffsetContract("do_not_execute.py", "forbidden", "n", 1),
        integer.IntegerOffsetContract("broken.py", "bad", "n", 1),
    )
    policy = prepare()
    request = dict(policy_receipt_cid=policy["receipt_cid"], contracts=contracts)
    return current, policy, request


def build(prepared, **kwargs):
    return module.build_codebase_semantic_manifest(prepared[0][1], **{**prepared[2], **kwargs})


def load(prepared, result):
    return module.load_codebase_semantic_manifest(prepared[0][1], result["manifest_cid"])


def test_complete_semantic_manifest_reuses_typed_native_owners_and_all_denominators(prepared):
    result = build(prepared)
    value = load(prepared, result)
    index = prepared[0][1]
    assert value["schema"] == "codebase-ir-manifest@1"
    assert len(value["units"]) == value["coverage"]["inventory_entries"] == 8
    statuses = {row["path"]: row["model_status"] for row in value["units"]}
    assert statuses == {"main.py": "source_bound_model", "missing.py": "missing_contract",
        "do_not_execute.py": "unsupported_source", "broken.py": "unsupported_parse",
        "README.txt": "unsupported_language", "binary.dat": "opaque", "large.py": "opaque", "link.py": "opaque"}
    assert value["coverage"]["source_bound_models"] == value["coverage"]["formalized_properties"] == 1
    assert value["coverage"]["unmodeled_inventory_units"] == 7
    assert value["coverage"]["declared_contracts"] == 3
    assert value["coverage"]["unmodeled_contracts"] == 2
    assert value["coverage"]["checked_properties"] == 0
    row = next(row for row in value["units"] if row["path"] == "main.py")
    program = ProgramIR.from_dict(index.artifacts.get(row["native_artifacts"]["program"]))
    contracts = [ProgramContract.from_dict(v) for v in index.artifacts.get(row["native_artifacts"]["contracts"])]
    assert len(program.functions) == len(contracts) == 1
    assert program.functions[0].name == "increment"
    assert contracts[0].function_id == program.functions[0].function_id
    correspondence = index.artifacts.get(row["native_artifacts"]["source_correspondence"])
    assert correspondence["source"]["source_revision"] == "snapshot:" + prepared[1]["head"]["snapshot_cid"]
    assert set(row["native_artifacts"]) == {"program", "contracts", "source_correspondence", "effects", "vc_sets", "compilation"}
    assert row["assumptions"] == list(integer.ASSUMPTIONS)
    assert row["dependency_frontier"]["status"] == "closed_local_expression_under_declared_runtime_assumptions"
    assert row["checked_evidence_references"] == []
    assert all(not value["authority"][key] for key in
        ("proof_authority", "source_runtime_semantics_verified", "execution_authority", "solver_executed", "training_executed", "learned_latents_as_predicates"))


def test_missing_contracts_are_not_silently_synthesized_or_satisfied(prepared):
    value = load(prepared, build(prepared, contracts=()))
    assert value["coverage"]["source_bound_models"] == value["coverage"]["formalized_properties"] == 0
    assert value["coverage"]["inventory_entries"] == 8
    assert next(v for v in value["units"] if v["path"] == "main.py")["model_status"] == "missing_contract"


def test_changed_literals_keep_logical_ids_but_change_exact_versions_and_native_artifacts(prepared):
    current, policy, request = prepared
    root, index, prepare, _, _ = current
    original = build(prepared)
    first = load(prepared, original)
    (root / "main.py").write_text("def increment(n: int) -> int:\n    return n + 2\n")
    successor = prepare("successor", CodebaseHead.from_dict(policy["head"]))
    second = load(prepared, module.build_codebase_semantic_manifest(index,
        policy_receipt_cid=successor["receipt_cid"], contracts=request["contracts"]))
    a = next(row for row in first["units"] if row["path"] == "main.py")
    b = next(row for row in second["units"] if row["path"] == "main.py")
    assert a["logical_unit_id"] == b["logical_unit_id"]
    assert {s["stable_id"] for s in a["symbols"]} == {s["stable_id"] for s in b["symbols"]}
    assert {s["version_cid"] for s in a["symbols"]} != {s["version_cid"] for s in b["symbols"]}
    assert a["version_cid"] != b["version_cid"] and a["source_cid"] != b["source_cid"]
    assert a["native_artifacts"]["program"] != b["native_artifacts"]["program"]
    assert a["declared_contract_cid"] == b["declared_contract_cid"]
    assert load(prepared, original) == first


def test_rename_creates_new_logical_identity_without_inferred_equivalence(prepared):
    root, index, prepare, _, _ = prepared[0]
    first = load(prepared, build(prepared))
    (root / "main.py").rename(root / "renamed.py")
    policy = prepare("rename", CodebaseHead.from_dict(prepared[1]["head"]))
    contract = integer.IntegerOffsetContract("renamed.py", "increment", "n", 1)
    second = load(prepared, module.build_codebase_semantic_manifest(index,
        policy_receipt_cid=policy["receipt_cid"], contracts=(contract,)))
    old = next(row for row in first["units"] if row["path"] == "main.py")
    new = next(row for row in second["units"] if row["path"] == "renamed.py")
    assert old["logical_unit_id"] != new["logical_unit_id"]
    assert "no_equivalence_inference" in second["identity_policy"]["rename"]


@pytest.mark.parametrize("damage", ["latent", "program_ref", "source_ref", "contract_ref", "frontier", "coverage", "omit_unit", "logical_id", "authority", "version"])
def test_resealed_semantic_claims_cannot_replace_native_source_owners(prepared, damage):
    index = prepared[0][1]
    value = deepcopy(load(prepared, build(prepared)))
    row = next(row for row in value["units"] if row["path"] == "main.py")
    if damage == "latent": row["semantic_predicate"] = {"latent": [1] * 384}
    elif damage == "program_ref": row["native_artifacts"]["program"] = row["native_artifacts"]["contracts"]
    elif damage == "source_ref": row["source_cid"] = value["structural_manifest_cid"]
    elif damage == "contract_ref": row["declared_contract_cid"] = row["entry_cid"]
    elif damage == "frontier": row["dependency_frontier"]["whole_program_closed"] = True
    elif damage == "coverage": value["coverage"]["checked_properties"] = 1
    elif damage == "omit_unit": value["units"].pop()
    elif damage == "logical_id": row["logical_unit_id"] = row["entry_cid"]
    elif damage == "authority": value["authority"]["proof_authority"] = True
    else: row["version_cid"] = row["entry_cid"]
    with pytest.raises(module.CodebaseSemanticManifestError, match="does not reconstruct"):
        module.load_codebase_semantic_manifest(index, index.artifacts.put(value))


@pytest.mark.parametrize("kind", ["latent_contract", "dictionary_contract", "duplicate", "outside_inventory", "missing_evidence"])
def test_arbitrary_predicates_and_out_of_scope_requests_are_refused(prepared, kind):
    contract = prepared[2]["contracts"][0]
    if kind == "latent_contract": args = {"contracts": ([0.1] * 384,)}
    elif kind == "dictionary_contract": args = {"contracts": (contract.to_dict(),)}
    elif kind == "duplicate": args = {"contracts": (contract, contract)}
    elif kind == "outside_inventory": args = {"contracts": (integer.IntegerOffsetContract("absent.py", "f", "n", 1),)}
    else: args = {"evidence_refs": ({"kind": "conditional_smt_record", "path": "missing.py", "artifact_cid": prepared[1]["receipt_cid"]},)}
    with pytest.raises(module.CodebaseSemanticManifestError): build(prepared, **args)


def test_replay_never_executes_checker_or_target_or_publishes_replacements(prepared, monkeypatch):
    result = build(prepared)
    def forbidden(*args, **kwargs): raise AssertionError("historical replay started a mutation or execution")
    monkeypatch.setattr(integer, "execute_integer_offset", forbidden)
    monkeypatch.setattr(prepared[0][1].artifacts, "put", forbidden)
    assert load(prepared, result)["coverage"]["source_bound_models"] == 1


@pytest.mark.parametrize("artifact", ["program", "contracts", "source_correspondence", "effects", "vc_sets", "compilation"])
def test_missing_native_artifact_refuses_historical_replay(prepared, artifact):
    result = build(prepared)
    value = load(prepared, result)
    row = next(row for row in value["units"] if row["path"] == "main.py")
    prepared[0][1].artifacts.path_for(row["native_artifacts"][artifact]).unlink()
    with pytest.raises(FileNotFoundError): load(prepared, result)


def test_fresh_process_reconstructs_semantic_manifest_from_native_cas_history(prepared, tmp_path):
    result = build(prepared)
    expected = load(prepared, result)
    prepared[0][4].close()
    (prepared[0][0] / "main.py").unlink()
    script = """
import json,sys,duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.codebase_semantic_manifest import load_codebase_semantic_manifest
cx=duckdb.connect(sys.argv[1],config={'threads':1,'memory_limit':'64MB'})
store=DuckDBASTStore(connection=cx);cas=ImmutableCAS(sys.argv[2])
index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
print(json.dumps(load_codebase_semantic_manifest(index,sys.argv[3]),sort_keys=True))
cx.close()
"""
    process = subprocess.run([sys.executable, "-c", script, str(tmp_path / "catalog.duckdb"),
        str(tmp_path / "cas"), result["manifest_cid"]], capture_output=True, text=True, timeout=30, env=dict(os.environ))
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout.splitlines()[-1]) == expected


@pytest.mark.skipif(not (shutil.which("z3") and shutil.which("cvc5")), reason="real native checker executables required")
def test_actual_native_smt_record_is_bound_but_does_not_grant_cache_or_behavior_authority(prepared):
    root, index, _, scheduler, _ = prepared[0]
    contract = prepared[2]["contracts"][0]
    compiled = integer.compile_integer_offset((root / "main.py").read_bytes(), contract,
        revision="snapshot:" + prepared[1]["head"]["snapshot_cid"])
    with acquire_codebase_resources(scheduler=scheduler) as lease:
        record = integer.execute_integer_offset(compiled, parent_lease=lease)
    assert record["status"] == "proved"
    reference = dict(kind="conditional_smt_record", path="main.py", artifact_cid=index.artifacts.put(record))
    value = load(prepared, build(prepared, evidence_refs=(reference,)))
    row = next(row for row in value["units"] if row["path"] == "main.py")
    assert row["declared_execution_records"][0]["recorded_status"] == "proved"
    assert row["declared_execution_records"][0]["trusted_execution"] is False
    assert row["checked_evidence_references"] == []
    assert value["coverage"]["checked_properties"] == 0
    for field in ("source_cid", "contract_cid", "compiled_cid", "query_cid"):
        wrong = dict(record, **{field: prepared[1]["receipt_cid"]})
        forged = dict(reference, artifact_cid=index.artifacts.put(wrong))
        with pytest.raises(module.CodebaseSemanticManifestError, match="binding differs"):
            build(prepared, evidence_refs=(forged,))
    forged = dict(reference, artifact_cid=index.artifacts.put(dict(record, kernel_checked=True)))
    with pytest.raises(module.CodebaseSemanticManifestError, match="binding differs"):
        build(prepared, evidence_refs=(forged,))
