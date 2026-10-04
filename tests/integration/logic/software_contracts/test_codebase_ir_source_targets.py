"""Native captured-source target replay; structural learning has no proof authority."""
import copy
import json
import subprocess

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_ir_targets as module
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers


@pytest.fixture
def prepared(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "increment.py").write_text("# café λ\ndef increment(n: int) -> int:\n    return n + 1\n", encoding="utf-8")
    for arguments in (("init", "-q"), ("config", "user.name", "Target Fixture"),
                      ("config", "user.email", "fixture@example.invalid"),
                      ("add", "."), ("commit", "-qm", "fixture")):
        subprocess.run(["git", "-C", str(repository), *arguments], check=True, capture_output=True)
    connection = duckdb.connect(str(tmp_path / "catalog.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    artifacts = ImmutableCAS(tmp_path / "artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
                                   catalog=CodebaseCatalog(store, artifacts))
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8,8192,8192),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=0.005))
    receipt = index.prepare_current(repository, repository_id="repository:source-target-fixture",
        operation_id="initial", expected_head=None, scheduler=owner)
    yield index, repository, receipt.head, owner, connection
    assert owner.snapshot()["active_lease_count"] == 0
    connection.close()


def target(prepared, **kwargs):
    index, _, head, _, _ = prepared
    options = dict(expected_head=head, path="increment.py")
    options.update(kwargs)
    return module.prepare_codebase_targets(index, **options)


def update(prepared, source):
    index, repository, head, owner, _ = prepared
    (repository / "increment.py").write_text(source, encoding="utf-8")
    return index.prepare_current(repository, repository_id=head.repository_id,
        operation_id="updated", expected_head=head, scheduler=owner).head


def details(value):
    return value.to_dict()["validation"][0]["details"]


def test_exact_native_targets_have_fixed_inventory_and_detached_complete_replay(prepared, monkeypatch):
    # None of source execution, solver/version probes, or live Git reads can
    # occur while making or replaying a historical target.
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("target preparation launched a process"))
    specs = [ContractSpec("increment", preconditions=("n > 0",), postconditions=("result == n + 1",))]
    result = target(prepared, contracts=specs)
    assert result.ready_for_training
    assert module.validate_codebase_targets(result).canonical_bytes == result.canonical_bytes
    payload = result.to_dict()
    assert [row["projection_id"] for row in payload["projections"]] == [
        module.CODEBASE_PROGRAM_PROJECTION, module.CODEBASE_CONTRACTS_PROJECTION]
    assert all(payload[name] is False for name in ("qualified", "admitted", "formalized"))
    assert details(result)["source_semantics_verified"] is False
    assert details(result)["proof_authority"] is False
    assert details(result)["semantic_formula_decoder"] is False
    assert details(result)["native_adapter"]["evidence"] is None
    assert details(result)["native_adapter"]["fake_backend_success"] is False
    assert len(details(result)["native_contracts"]) == 1
    binding = module.source_binding_from_target(result)
    assert binding["head"] == prepared[2].to_dict()
    assert binding["repository_id"] == prepared[2].repository_id
    assert binding["source_revision"] == "snapshot:" + prepared[2].snapshot_cid
    assert binding["authored_contracts"] == [item.to_dict() for item in specs]
    assert binding["ast_cid"] and binding["source_cid"]
    binding["head"]["generation"] = 999
    assert module.source_binding_from_target(result)["head"]["generation"] == 1
    raw = bytes.fromhex(details(result)["source_bytes_hex"])
    for span in details(result)["correspondence"]["spans"]:
        assert raw[span["start_byte"]:span["end_byte"]].decode("utf-8") == span["source_text"]
    assert prepared[4].execute("SELECT generation FROM codebase_control.heads").fetchall() == [(1,)]


def test_historical_targets_do_not_claim_a_current_checkout(prepared):
    first = target(prepared)
    (prepared[1] / "increment.py").write_text("def increment(n: int) -> int:\n    return n + 99\n")
    assert target(prepared).canonical_bytes == first.canonical_bytes
    assert module.validate_codebase_targets(first).canonical_bytes == first.canonical_bytes


def test_provenance_changes_are_outside_learned_features(prepared):
    first = target(prepared)
    index, repository, head, owner, _ = prepared
    second_head = index.prepare_current(repository, repository_id=head.repository_id,
        operation_id="same_source_new_generation", expected_head=head, scheduler=owner).head
    second = target(prepared, expected_head=second_head)
    assert first.digest != second.digest
    assert first.source_digest != second.source_digest
    assert [row["expression"] for row in first.to_dict()["projections"]] == [
        row["expression"] for row in second.to_dict()["projections"]]
    learned = json.dumps([row["expression"] for row in first.to_dict()["projections"]])
    assert head.snapshot_cid not in learned and head.manifest_cid not in learned
    assert "source_ref_ids" not in learned and "span_ids" not in learned
    assert "program_id" not in learned and "contract_id" not in learned


@pytest.mark.parametrize("literal", [2, -1, 0])
def test_literal_values_do_not_collapse_into_same_feature_target(prepared, literal):
    first = target(prepared)
    head = update(prepared, f"# café λ\ndef increment(n: int) -> int:\n    return n + {literal}\n")
    second = target(prepared, expected_head=head)
    assert second.ready_for_training
    assert first.to_dict()["projections"][0]["expression"] != second.to_dict()["projections"][0]["expression"]


def test_bool_and_int_literals_remain_distinct(prepared):
    head = update(prepared, "def increment(n: bool) -> bool:\n    return True\n")
    result = target(prepared, expected_head=head)
    assert result.ready_for_training
    values = [row["attributes"].get("value") for row in details(result)["native_program"]["expressions"]]
    assert any(type(value) is bool and value is True for value in values)
    assert "bool" in json.dumps(result.to_dict()["projections"][0]["expression"])


def test_multiple_authored_contracts_keep_one_fixed_native_projection(prepared):
    specs = [ContractSpec("increment", postconditions=("result == n + 1",), contract_id="first"),
             ContractSpec("increment", postconditions=("result > n",), contract_id="second")]
    result = target(prepared, contracts=specs)
    assert result.ready_for_training
    assert len(result.to_dict()["projections"]) == 2
    assert len(result.to_dict()["projections"][1]["expression"]["documents"]) == 2
    assert details(result)["authored_contracts"] == [item.to_dict() for item in specs]
    assert len(set(details(result)["authored_contract_cids"])) == 2
    assert len(details(result)["lowered_contract_sha256"]) == 2


@pytest.mark.parametrize("source, expected", [
    ("def increment(n: int) -> int:\n    if n > 0:\n        return n + 1\n    return n - 1\n", "python.if.path_sensitive_cfg"),
    ("def increment(n: int = 1) -> int:\n    return n + 1\n", "function_signature_or_decorator_unsupported"),
    ("@cached\ndef increment(n: int) -> int:\n    return n + 1\n", "function_signature_or_decorator_unsupported"),
    ("def increment(n: int) -> int:\n    return abs(n)\n", "expression_outside_native_feature_profile"),
    ("def increment(n: float) -> float:\n    return n + 1.5\n", "annotation_outside_int_bool_feature_profile"),
    ("def increment(n: int) -> int:\n    return outside + n\n", "global_or_unbound_name"),
    ("def increment(n: int) -> int:\n    return int\n", "global_or_unbound_name"),
    ("def increment(n: int) -> int:\n    while n > 0:\n        n = n - 1\n    return n\n", "statement_outside_native_feature_profile"),
    ("def increment(n: int) -> int:\n    return b'bytes'\n", "literal_outside_int_bool_feature_profile"),
    ("import os\ndef increment(n: int) -> int:\n    return n + 1\n", "plain_function_module_required"),
    ("def increment(n: list[int]) -> int:\n    return 1\n", "annotation_outside_int_bool_feature_profile"),
])
def test_unsupported_inventory_is_source_bound_and_refuses_readiness(prepared, source, expected):
    head = update(prepared, source)
    result = target(prepared, expected_head=head)
    assert not result.ready_for_training
    assert expected in {row["reason"] for row in result.to_dict()["unsupported"]}
    assert module.validate_codebase_targets(result).canonical_bytes == result.canonical_bytes


def test_guard_polarity_is_preserved_even_when_native_branch_semantics_are_unsupported(prepared):
    first_head = update(prepared, "def increment(n: int) -> int:\n    if n > 0:\n        return n + 1\n    return n - 1\n")
    first = target(prepared, expected_head=first_head)
    index, repository, _, owner, _ = prepared
    (repository / "increment.py").write_text("def increment(n: int) -> int:\n    if n < 0:\n        return n + 1\n    return n - 1\n")
    second_head = index.prepare_current(repository, repository_id=first_head.repository_id,
        operation_id="changed_guard", expected_head=first_head, scheduler=owner).head
    second = target(prepared, expected_head=second_head)
    assert not first.ready_for_training and not second.ready_for_training
    first_expression = first.to_dict()["projections"][0]["expression"]
    second_expression = second.to_dict()["projections"][0]["expression"]
    assert first_expression != second_expression
    assert "branch_condition" in json.dumps(first_expression)
    assert "gt" in json.dumps(first_expression) and "lt" in json.dumps(second_expression)


def test_unknown_native_types_are_retained_without_silent_integer_refinement(prepared):
    head = update(prepared, "def increment(n):\n    return n + 1\n")
    result = target(prepared, expected_head=head)
    assert result.ready_for_training
    observations = details(result)["unknown_inventory"]
    assert any(row["native_kind"] == "symbols" and row["value"] == "any" for row in observations)
    assert any(row["native_kind"] == "expressions" and row["value"] == "any" for row in observations)
    assert details(result)["source_semantics_verified"] is False


def test_only_integer_literal_feature_value_changes_when_authored_contract_id_changes(prepared):
    first = target(prepared, contracts=[ContractSpec("increment", postconditions=("result == n + 1",), contract_id="first")])
    second = target(prepared, contracts=[ContractSpec("increment", postconditions=("result == n + 1",), contract_id="second")])
    assert first.digest != second.digest
    assert [row["expression"] for row in first.to_dict()["projections"]] == [
        row["expression"] for row in second.to_dict()["projections"]]


def test_historical_receipts_are_replayed_from_native_sql_owner(prepared):
    result = target(prepared)
    prepared[4].execute("UPDATE codebase_control.operations SET receipt='{}'")
    with pytest.raises(ValueError, match="receipt"):
        target(prepared)
    # Already detached target replay has no dependency on mutable SQL history.
    assert module.validate_codebase_targets(result).digest == result.digest


@pytest.mark.parametrize("mutation", [
    lambda p: p["projections"][0]["expression"]["document"]["expressions"][1]["attributes"].update(value=999),
    lambda p: p["validation"][0]["details"]["source_binding"].update(content_sha256="0" * 64),
    lambda p: p["validation"][0]["details"]["source_binding"]["head"].update(generation=2),
    lambda p: p["validation"][0]["details"].update(source_bytes_hex="00"),
    lambda p: p["validation"][0]["details"]["correspondence"]["spans"][0].update(source_text="different"),
    lambda p: p["validation"][0]["details"].update(proof_authority=True),
    lambda p: p["validation"][0]["details"]["native_program"]["expressions"][0].update(operator="fake"),
    lambda p: p["validation"][0]["details"]["profile"].update(executes_source=True),
    lambda p: p["projections"][0].update(producer_id="caller"),
    lambda p: p["validation"][0]["details"].update(authored_contracts=[]),
    lambda p: p["validation"][0]["details"].update(captured_ast=None),
])
def test_native_replay_rejects_modified_feature_source_contract_and_authority(prepared, mutation):
    result = target(prepared, contracts=[ContractSpec("increment", postconditions=("result == n + 1",))])
    payload = copy.deepcopy(result.to_dict())
    mutation(payload)
    with pytest.raises(module.CodebaseTargetError):
        module.validate_codebase_targets(DomainTargetEnvelope.from_dict(payload))


@pytest.mark.parametrize("limits", [
    {"max_source_bytes": True}, {"max_ast_nodes": 0}, {"max_ast_depth": 49},
    {"max_target_bytes": 4 * 1024 * 1024 + 1}, {"max_contracts": 9},
])
def test_caps_are_exact_and_cannot_expand_the_native_profile(limits):
    with pytest.raises(module.CodebaseTargetError):
        module.CodebaseTargetLimits(**limits)


def test_source_contract_and_target_byte_bounds_are_checked(prepared):
    with pytest.raises(module.CodebaseTargetError, match="source exceeds"):
        target(prepared, limits=module.CodebaseTargetLimits(max_source_bytes=8))
    with pytest.raises(module.CodebaseTargetError, match="AST exceeds"):
        target(prepared, limits=module.CodebaseTargetLimits(max_ast_nodes=8))
    with pytest.raises(module.CodebaseTargetError, match="byte bound"):
        target(prepared, limits=module.CodebaseTargetLimits(max_target_bytes=512))
    with pytest.raises(module.CodebaseTargetError, match="condition inventory"):
        target(prepared, contracts=[ContractSpec("increment", postconditions=("True",) * 33)])


def test_native_inputs_and_unique_contracts_required(prepared):
    with pytest.raises(module.CodebaseTargetError, match="native ContractSpec"):
        target(prepared, contracts=[{"function_name": "increment"}])
    with pytest.raises(module.CodebaseTargetError, match="duplicate contract"):
        target(prepared, contracts=[ContractSpec("increment", postconditions=("True",))] * 2)
    with pytest.raises(module.CodebaseTargetError, match="captured nonopaque"):
        target(prepared, path="missing.py")
    with pytest.raises(module.CodebaseTargetError, match="immutable"):
        module.validate_codebase_targets(target(prepared).to_dict())
