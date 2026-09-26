"""Typed page closure over synthetic declarations, without runtime training."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_detached_inputs as detached
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_package_inputs as inputs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_plan as plans
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_checkpoint as compact
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_sparse_checkpoint as sparse
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import encode_patch
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_batches import (
    _from_case, _generate, _template,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_detached_inputs import _Store, _bare
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_plan import _register
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_shared_sparse_arrow import _forbid_native
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_produced_record_projection import _prepared


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    _forbid_native(monkeypatch)


def _raw(value):
    return worker._json_bytes(value)


def _stage(registry, root, name, raw):
    path = root / name
    path.write_bytes(raw)
    ref = registry.stage_artifact(path)
    return {**ref, "path": str(registry.artifact_path(ref))}


@dataclass
class Page:
    template: object
    report: dict
    fixture: object
    generation_artifact: dict
    plan_artifact: dict
    variant_record: dict
    version_records: list
    run_records: list
    store: object

    def kwargs(self, *, artifact_resolver=None):
        return {"variant_record": self.variant_record, "version_records": self.version_records,
                "run_records": self.run_records, "artifact_resolver": artifact_resolver or self.store.resolve}

    def generation(self):
        return json.loads(self.store.paths[self.generation_artifact["sha256"]].read_bytes())

    def plan(self):
        return json.loads(self.store.paths[self.plan_artifact["sha256"]].read_bytes())


def _page(registry, root, *, start_batch=1, max_batches=2,
          shared_artifacts=False, base_kind="full", sparse_parent_override=None,
          alias=False, training_batch_size=2, validation_batch_size=2):
    """Reusable real generated page; all vectors and state changes are fixtures.

    Canonical template prefix guarantees template-only training sources on a
    later page. Sparse patches are direct scalar fixture transactions, not
    optimizer updates. Optional target/Arrow bytes deliberately stay unqualified.
    """
    root.mkdir(parents=True, exist_ok=True)
    fixture = _from_case(_prepared(root / "sources", alias=alias).case)
    updates = {}
    if shared_artifacts:
        target = _stage(registry, root, "target.fixture", b"unqualified complete-target placeholder")
        arrow = _stage(registry, root, "arrow.fixture", b"unqualified Arrow-feature placeholder")
        updates.update(target_snapshot_id="sha256:" + target["sha256"],
                       target_snapshot_artifact=target, arrow_feature_weights_artifact=arrow)
    template, fixture = _template(registry, root / "inputs", fixture=fixture, updates=updates)
    if base_kind != "full":
        original_base = template.base_version_id
        base_ref = {"sha256": template.base_checkpoint.sha256, "bytes": template.base_checkpoint.bytes}
        state = modal.ModalAutoencoderTrainingState.from_dict(
            json.loads(Path(template.base_checkpoint.path).read_bytes()))
        if base_kind == "sparse":
            declared_parent = sparse_parent_override or original_base
            before = state.state_identity()
            with state.transaction(label="package-fixture-scalar-change") as transaction:
                state.feature_embedding_weights["padding"][0] = 0.375
            patch = _stage(registry, root, "accepted.fixture.patch", encode_patch(transaction.patch,
                base_state_identity=before, result_state_identity=state.state_identity(),
                base_version_id=declared_parent, sequence=0, provenance={"run_id": "fixture-only"}))
            manifest = sparse.encode_manifest(parent=base_ref, base_version_id=declared_parent,
                patches=[_bare(patch)], materialized_checkpoint=sparse.checkpoint_identity(state),
                state_identity=state.state_identity(), result_revision=state.state_revision,
                provenance={"run_id": "fixture-only"})
            new_artifact = _stage(registry, root, "sparse.fixture.json", manifest)
            base = registry.register_version("package-register-sparse", "english-0", _bare(new_artifact),
                {"fixture_only": True}, parent_version_id=original_base)
        elif base_kind in {"compact_ancestor", "compact_corrupt"}:
            raw = compact.serialize_checkpoint(state)
            if base_kind == "compact_corrupt":
                raw = raw[:-1] + bytes([raw[-1] ^ 1])
            ancestor = _stage(registry, root, "compact.fixture.bin", raw)
            compact_version = registry.register_version("package-register-compact", "english-0", _bare(ancestor),
                {"fixture_only": True}, parent_version_id=original_base)
            base = registry.register_version("package-register-full-descendant", "english-0", base_ref,
                {"fixture_only": "full descendant"}, parent_version_id=compact_version["version_id"])
        else:
            raise ValueError("unsupported package fixture base kind")
        bound = coordinator.registered_checkpoint_inputs(registry, base["version_id"])
        template = _register(registry, root, {**template.to_dict(), **bound,
            "base_version_id": base["version_id"]}, "package-template")
    report = _generate(registry, template, fixture, root, start_batch=start_batch, max_batches=max_batches,
                       training_batch_size=training_batch_size, validation_batch_size=validation_batch_size)
    variants = registry.get_variant("english-0")
    versions = []
    version_id = template.base_version_id
    while version_id is not None:
        record = registry.get_version(version_id)
        versions.append(record)
        version_id = record["parent_version_id"]
    versions.reverse()
    runs = [registry.get_run(template.run_id), *(registry.get_run(key) for key in report["run_ids"])]
    store = _Store(root / "detached-blobs")
    for path in sorted(registry.artifact_root.glob("*/*")):
        if path.is_file():
            store.add(path.read_bytes())
    return Page(template, report, fixture, report["generation_artifact"], report["plan_artifact"],
                variants, versions, runs, store)


def _inspect(page, **kwargs):
    return inputs.inspect_campaign_inputs(page.generation_artifact, page.plan_artifact,
        **{**page.kwargs(), **kwargs})


def _no_weights(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("detached inventory must not construct/replay model weights")
    monkeypatch.setattr(modal.ModalAutoencoderTrainingState, "__init__", forbidden)
    monkeypatch.setattr(compact, "_state_from_data", forbidden)
    monkeypatch.setattr(sparse, "resolve_checkpoint", forbidden)


def _replace_generation(page, data):
    page.generation_artifact = page.store.add(_raw(data))


def _rewrite_job(page, index, change):
    generation, plan = page.generation(), page.plan()
    row = generation["jobs"][index]
    payload = json.loads(page.store.paths[row["job_spec_artifact"]["sha256"]].read_bytes())
    change(payload)
    spec = worker.TrainingJobSpec.from_dict(payload)
    row["job_spec_artifact"] = page.store.add(_raw(spec.to_dict()))
    row["job_spec_sha256"] = spec.canonical_sha256
    generation["total_job_bytes"] = sum(item["job_spec_artifact"]["bytes"] for item in generation["jobs"])
    page.run_records[index + 1]["spec"] = {name: row[name] for name in ("job_spec_artifact", "job_spec_sha256")}
    batch = plan["batches"][index]
    batch.update(job_spec_artifact=row["job_spec_artifact"], job_spec_sha256=spec.canonical_sha256,
        training_config_sha256=hashlib.sha256(_raw(spec.to_dict()["training_config"])).hexdigest(),
        autoencoder_config_sha256=hashlib.sha256(_raw(spec.to_dict()["autoencoder_config"])).hexdigest())
    batch["batch_id"] = plans._batch_id(batch)
    _replace_generation(page, generation)
    page.plan_artifact = page.store.add(plans.encode_campaign_plan(plan))


def test_later_page_uses_global_generation_and_local_plan_ordinals_without_historical_paths(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        page = _page(registry, tmp_path / "page")
        assert [row["ordinal"] for row in page.generation()["jobs"]] == [1, 2]
        assert [row["ordinal"] for row in page.plan()["batches"]] == [0, 1]
        captured = deepcopy((page.variant_record, page.version_records, page.run_records))
        # This page now has only detached byte locators. Original CAS payloads
        # disappear, but historical paths and job canonical identities remain.
        for path in registry.artifact_root.glob("*/*"):
            if path.is_file():
                path.unlink()
        _no_weights(monkeypatch)
        first = _inspect(page)
        second = _inspect(page)
        assert first == second
        assert captured == (page.variant_record, page.version_records, page.run_records)
        assert first["coverage"] == page.report["coverage"]
        qualification = first["qualification"]
        assert qualification["corpus_membership_verified"] is True
        assert qualification["checkpoint_inventory_verified"] is True
        for name in ("checkpoint_semantic_replay_verified", "weights_constructed", "execution_authorized",
                     "execution_source_manifest_verified", "historical_absolute_paths_used", "full_source_payload_closure",
                     "completion_history_exported", "source_authority_authenticated", "global_holdout_verified",
                     "full_federal_corpus_complete", "constitution_formalized", "formalized", "admitted",
                     "publication_performed", "training_performed"):
            assert qualification[name] is False


@pytest.mark.parametrize("change", ["coverage", "count_type", "disposition", "selected_sources", "ordinal", "qualification"])
def test_generation_is_rederived_instead_of_trusting_an_individually_valid_hash(tmp_path, change):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        page = _page(registry, tmp_path / "page", max_batches=1)
        generation = page.generation()
        if change == "coverage":
            generation["coverage"]["deferred_training_input_count"] += 1
        elif change == "count_type":
            generation["coverage"]["selected_training_input_count"] = float(generation["coverage"]["selected_training_input_count"])
        elif change == "disposition":
            generation["input_dispositions"][0]["disposition"] = "invented"
        elif change == "selected_sources":
            generation["selected_source_artifacts"].pop()
        elif change == "ordinal":
            generation["jobs"][0]["ordinal"] = 0
        else:
            generation["admitted"] = True
        _replace_generation(page, generation)
        with pytest.raises(inputs.CampaignPackageInputError):
            _inspect(page)


@pytest.mark.parametrize("field", ["corpus_manifest_artifact", "produced_record_projection_artifact"])
def test_generation_row_descriptors_reject_float_byte_counts_before_template_reads(tmp_path, field):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        page = _page(registry, tmp_path / "page", max_batches=1)
        generation = page.generation()
        generation["jobs"][0][field]["bytes"] = float(generation["jobs"][0][field]["bytes"])
        _replace_generation(page, generation)
        template_digest = generation["recipe"]["template_job_spec_artifact"]["sha256"]
        def resolve(ref):
            assert ref["sha256"] != template_digest, "invalid row descriptor reached template verification"
            return page.store.resolve(ref)
        with pytest.raises(inputs.CampaignPackageInputError):
            _inspect(page, artifact_resolver=resolve)


@pytest.mark.parametrize("change", ["training_config", "model_config", "code_identity", "source_pins", "training_order"])
def test_coherently_rehashed_generated_job_cannot_escape_template_contract(tmp_path, change):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        page = _page(registry, tmp_path / "page", max_batches=1)
        def mutate(payload):
            if change == "training_config":
                payload["training_config"]["learning_rate"] *= 2
            elif change == "model_config":
                payload["autoencoder_config"]["changed"] = 1
            elif change == "code_identity":
                payload["code_identity"] = "other-producer"
            elif change == "source_pins":
                payload["expected_source_sha256"] = {name: "3" * 64 for name in worker.SOURCE_MODULE_NAMES}
            else:
                payload["samples"].reverse()
        _rewrite_job(page, 0, mutate)
        with pytest.raises(inputs.CampaignPackageInputError):
            _inspect(page)


def test_template_only_sources_are_required_even_when_absent_from_generated_page(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        page = _page(registry, tmp_path / "page", max_batches=1)
        generated = {row["sha256"] for row in page.generation()["selected_source_artifacts"]}
        only_template = {row.sha256 for row in page.template.corpus_source_artifacts} - generated
        assert len(only_template) == 2
        page.store.paths[sorted(only_template)[0]].unlink()
        with pytest.raises(inputs.CampaignPackageInputError):
            _inspect(page)


def test_valid_alternate_source_alias_cannot_impersonate_canonical_generation_selection(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        page = _page(registry, tmp_path / "page", start_batch=0, max_batches=1,
                     alias=True, training_batch_size=128, validation_batch_size=32)
        generation, plan = page.generation(), page.plan()
        row = generation["jobs"][0]
        payload = json.loads(page.store.paths[row["job_spec_artifact"]["sha256"]].read_bytes())
        projection = json.loads(page.store.paths[row["produced_record_projection_artifact"]["sha256"]].read_bytes())
        alternatives = {page.fixture.case.rows[0]["entry_cid"], page.fixture.case.rows[-1]["entry_cid"]}
        selected = next(item for item in projection["records"] if item["entry_cid"] in alternatives)
        assert selected["entry_cid"] == min(alternatives)
        selected.update(page.fixture.receipt_set.binding_for(max(alternatives)))
        projection_ref = page.store.add(_raw(projection))
        row["produced_record_projection_artifact"] = projection_ref
        payload["produced_record_projection_artifact"] = {**projection_ref,
            "path": str(Path(generation["recipe"]["artifact_root"]) / projection_ref["sha256"][:2] / projection_ref["sha256"])}
        digest = hashlib.sha256(_raw({"recipe_id": generation["recipe_id"], "ordinal": row["ordinal"],
            "corpus_manifest_artifact": row["corpus_manifest_artifact"],
            "produced_record_projection_artifact": projection_ref})).hexdigest()
        row["job_id"], row["run_id"] = "campaign-job:" + digest, "campaign-run:" + digest
        payload.update(job_id=row["job_id"], run_id=row["run_id"])
        spec = worker.TrainingJobSpec.from_dict(payload)
        row["job_spec_artifact"] = page.store.add(_raw(spec.to_dict()))
        row["job_spec_sha256"] = spec.canonical_sha256
        generation["total_job_bytes"] = row["job_spec_artifact"]["bytes"]
        page.run_records[1].update(run_id=spec.run_id,
            spec={key: row[key] for key in ("job_spec_artifact", "job_spec_sha256")})
        plan["batches"][0].update({key: row[key] for key in ("job_id", "run_id", "job_spec_artifact", "job_spec_sha256")})
        plan["batches"][0]["batch_id"] = plans._batch_id(plan["batches"][0])
        _replace_generation(page, generation)
        page.plan_artifact = page.store.add(plans.encode_campaign_plan(plan))
        # Both aliases are valid source occurrences; only the original generator
        # contract requires the canonical representative. A generic job check
        # alone therefore cannot establish exact generated-page provenance.
        valid_job = detached.verify_detached_campaign_job(row["job_spec_artifact"], resolver=page.store.resolve,
            expected_job_spec_sha256=spec.canonical_sha256, variant_manifest=page.variant_record["manifest"])
        assert valid_job["corpus_verification"]["produced_record_projection_verified"] is True
        with pytest.raises(inputs.CampaignPackageInputError):
            _inspect(page)


@pytest.mark.parametrize("change", ["ordered_roles", "configuration"])
def test_sealed_plan_cannot_describe_other_order_or_configuration(tmp_path, change):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        page = _page(registry, tmp_path / "page", max_batches=1)
        plan = page.plan()
        if change == "ordered_roles":
            plan["batches"][0]["validation_record_ids"].reverse()
        else:
            plan["batches"][0]["training_config_sha256"] = "4" * 64
        plan["batches"][0]["batch_id"] = plans._batch_id(plan["batches"][0])
        page.plan_artifact = page.store.add(plans.encode_campaign_plan(plan))
        with pytest.raises(inputs.CampaignPackageInputError):
            _inspect(page)


@pytest.mark.parametrize("change", ["variant", "unrelated_version", "missing_version", "version_identity"])
def test_variant_and_complete_registered_version_ancestry_are_exact(tmp_path, change):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        page = _page(registry, tmp_path / "page", max_batches=1)
        if change == "variant":
            page.variant_record["manifest"]["model_variant"] = "foreign"
        elif change == "unrelated_version":
            registered = registry.register_version("unrelated-version", "english-0", page.version_records[0]["artifact"],
                                                  {"unrelated": True})
            page.version_records.insert(0, registry.get_version(registered["version_id"]))
        elif change == "missing_version":
            page.version_records.clear()
        else:
            page.version_records[0]["metadata"]["forged"] = True
        with pytest.raises(inputs.CampaignPackageInputError):
            _inspect(page)


@pytest.mark.parametrize("base_kind", ["sparse", "compact_ancestor"])
def test_checkpoint_ancestry_inventory_never_constructs_weights_or_claims_replay(tmp_path, monkeypatch, base_kind):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        page = _page(registry, tmp_path / "page", max_batches=1, base_kind=base_kind)
        _no_weights(monkeypatch)
        checked = _inspect(page)
        artifacts = {row["sha256"]: row for row in checked["artifacts"]}
        assert all(version["artifact"]["sha256"] in artifacts for version in page.version_records)
        assert all(ref.sha256 in artifacts for ref in page.template.base_checkpoint_dependencies)
        assert checked["qualification"]["checkpoint_inventory_verified"] is True
        assert checked["qualification"]["checkpoint_semantic_replay_verified"] is False
        assert checked["qualification"]["weights_constructed"] is False


def test_sparse_physical_parent_cannot_claim_another_registered_parent(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        page = _page(registry, tmp_path / "page", max_batches=1, base_kind="sparse",
                     sparse_parent_override="different-declared-parent")
        with pytest.raises(inputs.CampaignPackageInputError, match="registered parent"):
            _inspect(page)


def test_compact_registry_ancestor_requires_valid_framing_without_state_construction(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        page = _page(registry, tmp_path / "page", max_batches=1, base_kind="compact_corrupt")
        _no_weights(monkeypatch)
        with pytest.raises(inputs.CampaignPackageInputError):
            _inspect(page)


@pytest.mark.parametrize("missing", [None, "target_snapshot_artifact", "arrow_feature_weights_artifact"])
def test_shared_bytes_are_required_but_runtime_compatibility_stays_deferred(tmp_path, missing):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        page = _page(registry, tmp_path / "page", max_batches=1, shared_artifacts=True)
        if missing:
            page.store.paths[getattr(page.template, missing).sha256].unlink()
            with pytest.raises(inputs.CampaignPackageInputError):
                _inspect(page)
        else:
            checked = _inspect(page)
            assert checked["qualification"]["target_membership_verified"] is False
            assert checked["qualification"]["target_membership_qualification"] == "deferred_to_worker"
            assert checked["qualification"]["arrow_runtime_compatibility_verified"] is False
            roles = {row["sha256"]: row["roles"] for row in checked["artifacts"]}
            assert "target_snapshot" in roles[page.template.target_snapshot_artifact.sha256]
            assert "arrow_feature_weights" in roles[page.template.arrow_feature_weights_artifact.sha256]
