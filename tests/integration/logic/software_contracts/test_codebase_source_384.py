"""Exact source corpus and opt-in actual GTE/384D numerical qualification."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as module
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


def source(name="capacity", operator="+", function="calculate"):
    sort = "int" if operator in ("+", "-", "*") else "bool"
    return f"def {function}({name}: int, threshold: int) -> {sort}:\n    return {name} {operator} threshold\n"


@pytest.fixture
def current(tmp_path):
    import duckdb
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init", "-q"), ("config", "user.name", "Fixture"), ("config", "user.email", "fixture@example.invalid")):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    selections = []
    for role, name in (("train", "capacity"), ("validation", "volume"), ("holdout", "quantity")):
        for i, op in enumerate(("+", "-", "*", "<", "<=", ">", ">=", "==", "!=")):
            path = f"{role}_{i}.py"
            (repo / path).write_text(source(name, op))
            selections.append(dict(path=path, role=role, group_id=path))
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "authored scalar fixture"], check=True)
    connection = duckdb.connect(str(tmp_path / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store, artifacts = DuckDBASTStore(connection=connection), ImmutableCAS(tmp_path / "cas")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
                                    catalog=CodebaseCatalog(store, artifacts))
    config = resources.ResourceSchedulerConfig.for_proof_host(state_path=tmp_path / "resources.json",
        proof_resource_sampler=lambda: ProofHostResources(8, 16384, 16384), lane_reservations={},
        auto_renew_leases=False, poll_interval_seconds=.005)
    scheduler = resources.GlobalResourceScheduler(config)
    head = index.prepare_current(repo, repository_id="repository:384fixture", operation_id="capture",
                                 expected_head=None, scheduler=scheduler).head
    yield index, repo, head, selections, scheduler
    connection.close()
    assert scheduler.snapshot()["active_lease_count"] == 0


def test_labels_come_from_exact_captured_source(current):
    index, repo, head, selections, _ = current
    corpus = module.prepare_corpus(index, expected_head=head, selections=selections)
    assert len(corpus["rows"]) == 27
    assert corpus["inventory_coverage"]["inventory_entries"] == 27
    for row in corpus["rows"]:
        assert row["source_sha256"] == hashlib.sha256((repo / row["path"]).read_bytes()).hexdigest()
    assert not corpus["desired_intent_used_as_label"]
    assert not corpus["proof_authority"]
    (repo / "train_0.py").write_text(source(operator="*"))
    # Historical corpus stays immutable; the live fence rejects these bytes.
    assert module.prepare_corpus(index, expected_head=head, selections=selections) == corpus
    with pytest.raises(StaleCodebaseError):
        index.observe_current(repo, expected_head=head, scheduler=current[-1])


@pytest.mark.parametrize("change", ["group", "missing_split", "duplicate_path", "extra_field"])
def test_selection_contracts(current, change):
    index, _, head, selections, _ = current
    selections = deepcopy(selections)
    if change == "group":
        selections[-1]["group_id"] = selections[0]["group_id"]
    elif change == "missing_split":
        selections = [s for s in selections if s["role"] != "holdout"]
    elif change == "duplicate_path":
        selections[-1]["path"] = selections[0]["path"]
    else:
        selections[0]["desired_intent"] = "multiply"
    with pytest.raises(ValueError):
        module.prepare_corpus(index, expected_head=head, selections=selections)


def test_clone_and_unsupported_source_controls():
    assert module._clone(source(function="a")) == module._clone("# comment\n" + source(function="b"))
    assert module._target(source(operator="+")) != module._target(source(operator="*"))
    for text in ("def f(x):\n    return x + 1\n", "print('never execute')\n", source().replace("int", "float")):
        with pytest.raises(ValueError):
            module._target(text)


def test_ancestral_roles_and_fixed_holdout(current):
    index, _, head, selections, _ = current
    corpus = module.prepare_corpus(index, expected_head=head, selections=selections)
    chain = [({}, dict(kind="repository_child", corpus=corpus))]
    module._check_successor(corpus, chain)
    changed = deepcopy(corpus)
    next(r for r in changed["rows"] if r["role"] == "holdout")["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="fixed tuning/holdout"):
        module._check_successor(changed, chain)


@pytest.mark.skipif(not os.environ.get("CODEBASE384_CHECKPOINT"), reason="explicit real pinned checkpoint required")
def test_real_fit_registry_replay_inference_and_source_fence(current, tmp_path):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    checkpoint = Path(os.environ["CODEBASE384_CHECKPOINT"])
    snapshot = os.environ["CODEBASE384_EMBEDDING_SNAPSHOT"]
    index, repo, head, selections, scheduler = current
    with AutoencoderRegistry(tmp_path / "models.duckdb", tmp_path / "models") as registry:
        parent = module.register_shared_parent(registry, checkpoint_path=checkpoint,
            expected_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest())
        arguments = dict(expected_head=head, registry=registry, parent_version_id=parent,
            selections=selections, operation_id="fit", embedding_snapshot=snapshot, scheduler=scheduler,
            timeout_seconds=240, memory_mb=4096)
        result = module.train_current_source384(index, repo, **arguments)
        assert result["training_executed"] and not result["promotion_performed"]
        assert result["evaluation"]["child_holdout"]["count"] == 9
        replay = module.train_current_source384(index, repo, **arguments)
        assert replay["version_id"] == result["version_id"] and not replay["training_executed"]
        learned = module.infer_current_source384(index, repo, expected_head=head, registry=registry,
            version_id=result["version_id"], paths=["train_0.py", "train_1.py", "train_2.py"],
            embedding_snapshot=snapshot, scheduler=scheduler, memory_mb=4096)
        assert not learned["training_executed"]
        assert all(not row["target_access"] and not row["teacher_forcing"] for row in learned["inference"]["rows"])
        assert all(row["source_contract"]["status"] == "qualified" for row in learned["inference"]["rows"])
        report = {"result": result, "replay": replay, "inference": learned}
        if os.environ.get("CODEBASE384_LAKE"):
            from ipfs_datasets_py.logic.formalization.autoencoder.source_program_runtime_384 import build_decoded_source_program_lake
            rows = [dict(id=hashlib.sha256(path.encode()).hexdigest(), source_text=(repo / path).read_text())
                    for path in ("train_0.py", "train_1.py", "train_2.py")]
            execution = build_decoded_source_program_lake(learned["inference"], rows,
                lake_executable=os.environ["CODEBASE384_LAKE"], timeout_seconds=60,
                output_directory=tmp_path / "learned-lake")
            report["lake"] = execution.to_dict()
            assert report["lake"]["status"] == "passed" and report["lake"]["backend_executed"]
            assert report["lake"]["proof_authority"] is False
        # The fitting path cannot quietly replace wrong predictions. A zero
        # head is loaded and evaluated through the same source consumer.
        zero = module.infer_current_source384(index, repo, expected_head=head, registry=registry,
            version_id=result["version_id"], paths=["train_0.py", "train_1.py", "train_2.py"],
            embedding_snapshot=snapshot, scheduler=scheduler, memory_mb=4096, weight_ablation="zero_head")
        assert all(row["source_contract"]["status"] == "mismatch" for row in zero["inference"]["rows"])
        report["zero_head_inference"] = zero
        _, envelope = module._read_generation(registry, parent)
        altered = deepcopy(envelope)
        altered["original_checkpoint_utf8"] += " "
        with pytest.raises(ValueError, match="original parent artifact"):
            module._root_view(altered)
        child_version, child = module._read_generation(registry, result["version_id"])
        child["request"]["corpus_sha256"] = "0" * 64
        changed = tmp_path / "forged-request.json"
        changed.write_bytes(module._raw(child))
        invalid = registry.register_version("forged-request-control", child_version["variant_id"],
            registry.stage_artifact(changed), parent_version_id=parent)["version_id"]
        with pytest.raises(ValueError, match="child request binding"):
            module._lineage(index, registry, invalid)
        _, unbound = module._read_generation(registry, result["version_id"])
        unbound["checkpoint"]["training_manifest"][0]["source_sha256"] = "f" * 64
        with pytest.raises(ValueError, match="checkpoint source/target manifest"):
            module._checkpoint_corpus(unbound)
        destination = os.environ.get("CODEBASE384_REPORT")
        if destination:
            Path(destination).write_text(json.dumps(report, indent=2))
        (repo / "train_0.py").write_text(source(operator="*"))
        with pytest.raises(StaleCodebaseError):
            module.infer_current_source384(index, repo, expected_head=head, registry=registry,
                version_id=result["version_id"], paths=["train_0.py"], embedding_snapshot=snapshot,
                scheduler=scheduler, memory_mb=4096)
    # No warmed registry or decoder state is needed to replay a historical
    # generation. A fresh source-owner connection is already covered by the
    # structural suite; close this one before the independent process opens it.
    index.catalog.store._connection.close()
    script = '''
import json,sys,duckdb
from pathlib import Path
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as m
root=Path(sys.argv[1])
with duckdb.connect(str(root/'source.duckdb'),config={'threads':1,'memory_limit':'64MB'}) as connection:
    store=DuckDBASTStore(connection=connection); artifacts=ImmutableCAS(root/'cas')
    index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=artifacts,catalog=CodebaseCatalog(store,artifacts))
    with AutoencoderRegistry(root/'models.duckdb',root/'models') as registry:
        def forbidden(*args,**kwargs): raise AssertionError('read path attempted fitting')
        m._worker=forbidden
        chain=m._lineage(index,registry,sys.argv[2])
        assert len(chain)==2
        print('FRESH_PROCESS_REPLAY_PASSED')
'''
    import sys
    check = subprocess.run([sys.executable, "-B", "-c", script, str(tmp_path), result["version_id"]],
        capture_output=True, text=True, timeout=60)
    assert check.returncode == 0, check.stderr
    assert check.stdout.endswith("FRESH_PROCESS_REPLAY_PASSED\n")
