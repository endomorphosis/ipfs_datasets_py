"""Exact CodebaseIR feature profile, native checkpoints and durable run reload."""
from dataclasses import replace
import copy
import subprocess

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtime
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


VERSION = runtime.CODEBASE_SOURCE_FEATURE_VERSION


@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    import duckdb
    root = tmp_path_factory.mktemp("source-bound-codebase-runtime")
    repository = root / "repository"
    repository.mkdir()
    for value in range(1, 5):
        (repository / f"increment_{value}.py").write_text(
            f"def increment(n: int) -> int:\n    return n + {value}\n", encoding="utf-8")
    for arguments in (("init", "-q"), ("config", "user.name", "Feature Fixture"),
                      ("config", "user.email", "fixture@example.invalid"),
                      ("add", "."), ("commit", "-qm", "fixture")):
        subprocess.run(["git", "-C", str(repository), *arguments], check=True, capture_output=True)
    connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    artifacts = ImmutableCAS(root / "source-artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
                                   catalog=CodebaseCatalog(store, artifacts))
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=root / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8,8192,8192),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=0.005))
    head = index.prepare_current(repository, repository_id="repository:feature-runtime-fixture",
        operation_id="capture", expected_head=None, scheduler=owner).head
    targets = [runtime.prepare_targets("codebase_ir", VERSION, index=index, expected_head=head,
                                      path=f"increment_{value}.py") for value in range(1, 5)]
    yield index, head, targets[:2], targets[2:]
    assert owner.snapshot()["active_lease_count"] == 0
    connection.close()


def _model(cohort):
    return runtime.build_source_bound_codebase_runtime(cohort[2])


def _completed_child(registry, model, train, tune, directory):
    first = model.train(train, validation_samples=tune, epochs=1, learning_rate=0.002)
    parent = model.register_candidate(registry, directory / "parent")
    loaded = runtime.load_version(registry, parent["version_id"], domain="codebase_ir", version=VERSION)
    child = loaded.train(train, validation_samples=tune, epochs=1, learning_rate=0.002)
    checkpoint = {"contract": loaded.contract.to_dict(), "feature_space": loaded.feature_space,
                  "state": child["state"], "report": child["report"]}
    path = directory / "child.json"
    path.write_bytes(features._raw(checkpoint))
    artifact = registry.stage_artifact(path)
    registry.create_run("create-child", "run:child", loaded.contract.variant_id, parent["version_id"],
                        {"purpose": "authored runtime test"})
    lease = registry.claim_run("claim-child", "run:child", "worker:fixture")["lease"]
    result = {"training_purpose": "feature_pretraining", "contract_sha256": loaded.contract.sha256,
              "feature_space_sha256": features.digest(loaded.feature_space),
              "state_sha256": features.digest(child["state"]),
              "report_sha256": features.digest(child["report"]), **features.FALSE}
    receipt = registry.complete_run("complete-child", lease, artifact, result)
    return first, parent, child, receipt


def test_named_feature_profile_never_advertises_published_formula_or_384d():
    descriptor = runtime.describe_runtime("codebase_ir", VERSION)
    assert VERSION == "source_bound_feature_v1"
    assert "codebase_ir" not in runtime.NATIVE_DOMAINS
    assert descriptor["latent_width_default"] == 8
    assert descriptor["supported_latent_widths"] == {"minimum": 1, "maximum": 64}
    assert descriptor["formal_decoder"]["available"] is False
    assert "decode_formal_logic" not in descriptor["capabilities"]
    assert all(descriptor[name] is False for name in features.FALSE)
    assert all(descriptor[name] is False for name in (
        "runtime_behavior_proved", "kernel_checked", "planner_admission_eligible", "cache_authoritative"))
    requirements = descriptor["qualification_requirements"]
    assert requirements["domain"] == "codebase_ir" and requirements["contains_code"] is True
    assert len(requirements["logic_floor"]) == 8 and len(requirements["software_routes"]) == 14
    assert requirements["lake_schema_requirement"]["required"] is True
    assert requirements["qualified"] is requirements["admitted"] is False
    assert {row["runtime_version"] for row in runtime.list_runtimes() if row["domain"] == "codebase_ir"} == {
        runtime.CODEBASE_FEATURE_VERSION, VERSION}
    for version in ("native_v1", "native_v2", "native_formula_v1", "published_384_v1", "../arbitrary"):
        with pytest.raises(runtime.RuntimeVersionError, match="unknown"):
            runtime.describe_runtime("codebase_ir", version)


def test_real_train_registry_restart_and_durable_completed_child(cohort, tmp_path, monkeypatch):
    _, _, train, tune = cohort
    model = _model(cohort)
    assert model.contract.state_codec.version == "1:latent-8"
    with pytest.raises(runtime.RuntimeVersionError, match="requires a trained"):
        model.infer(tune)
    database, artifacts = tmp_path / "models.duckdb", tmp_path / "models"
    with AutoencoderRegistry(database, artifacts) as registry:
        first, parent, child, receipt = _completed_child(registry, model, train, tune, tmp_path)
    with AutoencoderRegistry(database, artifacts) as registry:
        loaded = runtime.load_version(registry, receipt["version_id"], domain="codebase_ir", version=VERSION)
        assert loaded.state == child["state"] and loaded.training_report == child["report"]
        assert loaded.parent_version_id == receipt["version_id"]
        assert registry.get_version(receipt["version_id"])["parent_version_id"] == parent["version_id"]
        uninterrupted = features.train_projection_features(model.contract, model.feature_space, train, tune,
                                                            epochs=2, latent_width=8, learning_rate=0.002)
        assert loaded.state == uninterrupted["state"]
        with monkeypatch.context() as patch:
            patch.setattr(features, "train_projection_features", lambda *a, **k: pytest.fail("inference trained"))
            observed = loaded.infer(tune)
        assert observed["training_executed"] is False and observed["decoded_formulas_generated"] is False
        assert all(observed[name] is False for name in features.FALSE)
        assert first["state"]["completed_epochs"] == 1 and loaded.state["completed_epochs"] == 2
        assert first["state"]["parameters"] != loaded.state["parameters"]
        assert all(moment["step"] == 2 for moment in loaded.state["adam"])


@pytest.mark.parametrize("width", [True, 0, 65, 384])
def test_named_profile_rejects_unsupported_latent_width(cohort, width):
    with pytest.raises(features.ProjectionFeatureError, match="latent width"):
        runtime.build_source_bound_codebase_runtime(cohort[2], latent_width=width)


@pytest.mark.parametrize("width", [1, 64])
def test_native_feature_backend_width_limits_remain_explicit(cohort, width):
    model = runtime.build_source_bound_codebase_runtime(cohort[2], latent_width=width)
    assert model.contract.state_codec.version == f"1:latent-{width}"


def test_no_decoder_training_overrides_or_adapter_substitution(cohort):
    model = _model(cohort)
    for operation in (lambda: model.decode_formal_logic(cohort[3]),
                      lambda: runtime.open_formal_decoder("codebase_ir", VERSION),
                      lambda: runtime.open_runtime("codebase_ir", VERSION, contract=model.contract,
                          feature_space=model.feature_space, decoder_head={})):
        with pytest.raises(runtime.RuntimeVersionError, match="no formal decoder"):
            operation()
    with pytest.raises(runtime.RuntimeVersionError, match="resume state is bound"):
        model.train(cohort[2], validation_samples=cohort[3], base_state={})
    changed = replace(model.contract, adapter=replace(model.contract.adapter, sha256="0" * 64))
    with pytest.raises(runtime.RuntimeVersionError, match="adapter differs"):
        runtime.open_runtime("codebase_ir", VERSION, contract=changed, feature_space=model.feature_space)
    changed = replace(model.contract, ir_schema="security_ir/another-profile")
    with pytest.raises(runtime.RuntimeVersionError, match="target schema"):
        runtime.open_runtime("codebase_ir", VERSION, contract=changed, feature_space=model.feature_space)


def test_source_bound_targets_and_inference_options_stay_closed(cohort):
    model = _model(cohort)
    target = cohort[2][0].to_dict()
    target["qualified"] = True
    with pytest.raises(ValueError, match="cannot establish qualification"):
        runtime.build_source_bound_codebase_runtime([target])
    model.train(cohort[2], validation_samples=cohort[3], epochs=1)
    with pytest.raises(runtime.RuntimeVersionError, match="does not accept"):
        model.infer(cohort[3], epochs=10)
    with pytest.raises(runtime.RuntimeVersionError, match="pending candidate"):
        model.train(cohort[2], validation_samples=cohort[3], epochs=1)


def test_completed_run_flags_cannot_replace_actual_native_completion(cohort, tmp_path, monkeypatch):
    model = _model(cohort)
    with AutoencoderRegistry(tmp_path / "models.duckdb", tmp_path / "models") as registry:
        _, _, _, receipt = _completed_child(registry, model, cohort[2], cohort[3], tmp_path)
        with monkeypatch.context() as patch:
            patch.setattr(registry, "get_run_completion", lambda _: None)
            with pytest.raises(runtime.RuntimeVersionError, match="lacks a native completed run"):
                runtime.load_version(registry, receipt["version_id"], domain="codebase_ir", version=VERSION)
        completion = registry.get_run_completion("run:child")
        changed = copy.deepcopy(completion)
        changed["completion_receipt"]["version_id"] = "0" * 64
        with monkeypatch.context() as patch:
            patch.setattr(registry, "get_run_completion", lambda _: changed)
            with pytest.raises(runtime.RuntimeVersionError, match="producer binding"):
                runtime.load_version(registry, receipt["version_id"], domain="codebase_ir", version=VERSION)


@pytest.mark.parametrize("change", ["state_sha256", "qualified", "authority_integer", "extra", "attempt_boolean"])
def test_completed_candidate_exact_result_and_metadata_reject_forgery(cohort, tmp_path, change):
    model = _model(cohort)
    with AutoencoderRegistry(tmp_path / "models.duckdb", tmp_path / "models") as registry:
        _, _, _, receipt = _completed_child(registry, model, cohort[2], cohort[3], tmp_path)
        row = registry.get_version(receipt["version_id"])
        metadata = copy.deepcopy(row["metadata"])
        if change == "state_sha256":
            metadata["result"][change] = "0" * 64
        elif change == "qualified":
            metadata["result"][change] = True
        elif change == "authority_integer":
            metadata["result"]["qualified"] = 0
        elif change == "extra":
            metadata["result"]["caller_passed"] = True
        else:
            metadata["attempt"] = True
        forged = registry.register_version("forge:" + change, row["variant_id"], row["artifact"], metadata,
                                           parent_version_id=row["parent_version_id"])
        with pytest.raises(runtime.RuntimeVersionError, match="metadata differs|identity or authority"):
            runtime.load_version(registry, forged["version_id"], domain="codebase_ir", version=VERSION)


def test_completed_run_metadata_is_not_accepted_by_other_feature_profile(cohort, tmp_path):
    model = _model(cohort)
    with AutoencoderRegistry(tmp_path / "models.duckdb", tmp_path / "models") as registry:
        _, _, _, receipt = _completed_child(registry, model, cohort[2], cohort[3], tmp_path)
        with pytest.raises(runtime.RuntimeVersionError, match="metadata differs"):
            runtime.load_version(registry, receipt["version_id"], domain="codebase_ir",
                                 version=runtime.CODEBASE_FEATURE_VERSION)
