"""V6/v8 cycle assembly with synthetic vectors and no training or queue calls."""
from dataclasses import asdict, replace
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_training_worker import _campaign_job, _artifact
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_worker import _indexed_corpus_job


def _spec(path, schema="v8"):
    path.mkdir(parents=True, exist_ok=True)
    if schema == "v8":
        payload, _, _ = _campaign_job(path)
    else:
        payload, _, _ = _indexed_corpus_job(path, production=True, arrow_inputs=schema == "v7")
    return worker.TrainingJobSpec.from_dict(payload)


def _forbidden(*args, **kwargs):
    pytest.fail("unexpected native execution, queue access or pre-verification side effect")


class _ReviewedArtifactRegistry:
    """Inert filesystem byte owner; no database, model or admission substitute."""
    def __init__(self, root):
        self.root = root
        root.mkdir()
        self.stage_calls = 0
        self.staged_sizes = []

    def artifact_path(self, descriptor):
        return self.root / descriptor["sha256"]

    def stage_artifact(self, path, expected_sha256):
        import hashlib
        raw = Path(path).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected_sha256
        descriptor = {"sha256": expected_sha256, "bytes": len(raw)}
        target = self.artifact_path(descriptor)
        if target.exists():
            assert target.read_bytes() == raw
        else:
            with target.open("xb") as stream:
                stream.write(raw)
        self.stage_calls += 1
        self.staged_sizes.append(len(raw))
        return descriptor

    def read_artifact(self, descriptor, *, max_bytes):
        import hashlib
        raw = self.artifact_path(descriptor).read_bytes()
        assert len(raw) == descriptor["bytes"] <= max_bytes
        assert hashlib.sha256(raw).hexdigest() == descriptor["sha256"]
        return raw

    def __getattr__(self, name):
        raise AssertionError("forbidden registry/job/numerical operation: " + name)


def _reviewed_transition_fixture(tmp_path, *, count=3):
    from copy import deepcopy
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_span_consumer_binding as fixtures
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    helper, admission, case, rows, options = fixtures.reviewed_public_consumer_case()
    rows, exposure = rows[:count], options["exposure_records"][:count]
    cfg = splits.LegalIREvalSplitConfig()
    manifest = splits.LegalIRSplitManifest(
        examples=tuple(splits.LegalIRSplitExample.from_sample(row) for row in rows),
        assignments={row["id"]: "train" for row in rows}, config_digest=cfg.digest).to_dict()
    options.update(expected_rows_sha256=fixtures.digest(rows), split_manifest=manifest,
                   expected_split_manifest_sha256=fixtures.digest(manifest), exposure_records=exposure,
                   expected_exposure_sha256=fixtures.digest(exposure))
    history = {"schema": "reviewed-example-cycle-history/v1", "scope_id": "fixture:declared-transition-history",
        "scope_kind": "declared_genesis", "split_manifests": [], "parent_history_artifact": None,
        "records": [{"id": row["id"], "source_text": row["source_text"],
            "source_sha256": fixtures.source_digest(row["source_text"]),
            "split_example": next(item for item in manifest["examples"] if item["sample_id"] == row["id"]),
            "assignment": "train"} for row in rows]}
    return SimpleNamespace(helper=helper, admission=admission, case=case, rows=rows, options=options,
        config=cfg.to_dict(), history=history, fixtures=fixtures, deepcopy=deepcopy)


def _reviewed_stage_options(data, output):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    change = {"schema": "reviewed-example-cycle-transition/v1", "retained": [],
              "added": [row["id"] for row in data.rows], "corrected": [], "superseded": [], "revoked": []}
    lineage = {"schema": "reviewed-cycle-checkpoint-lineage/v1", "base_checkpoint": None,
               "parent_checkpoint": None, "optimizer_state": None, "weights_updated": False}
    return {"transition_kind": "bootstrap", "parent_artifact": None, "expected_parent_sha256": None,
        "successor_rows": data.rows, "expected_successor_rows_sha256": data.fixtures.digest(data.rows),
        "successor_binding": consumer.prepare_reviewed_source_span_consumer_binding_v2(data.rows, **data.options),
        "split_manifest": data.options["split_manifest"], "admission_inputs": data.options["admission_inputs"],
        "exposure_records": data.options["exposure_records"], "transition": change,
        "expected_transition_sha256": data.fixtures.digest(change), "history": data.history,
        "expected_history_sha256": data.fixtures.digest(data.history), "split_config": data.config,
        "expected_split_config_sha256": data.fixtures.digest(data.config), "checkpoint_lineage": lineage,
        "expected_checkpoint_lineage_sha256": data.fixtures.digest(lineage), "output_directory": output,
        "allow_bootstrap": True}


def _reviewed_doc(registry, reference):
    return json.loads(registry.read_artifact({key: reference[key] for key in ("sha256", "bytes")},
                                            max_bytes=inputs.MAX_REVIEWED_ARTIFACT_BYTES))


def _reviewed_reason(registry, tmp_path):
    path = tmp_path / "fictional-reason.json"
    path.write_text('{"scope":"fictional declared correction; no legal decision"}')
    import hashlib
    stored = registry.stage_artifact(path, hashlib.sha256(path.read_bytes()).hexdigest())
    return dict(stored, path=str(registry.artifact_path(stored)))


def _reviewed_successor_options(data, options, registry, parent, output):
    from copy import deepcopy
    document = _reviewed_doc(registry, parent)
    old_history = _reviewed_doc(registry, document["history_artifact"])
    history = deepcopy(old_history)
    history.update(scope_kind="complete_declared_history", parent_history_artifact=document["history_artifact"])
    options.update(transition_kind="successor", parent_artifact=parent, expected_parent_sha256=parent["sha256"],
                   history=history, expected_history_sha256=data.fixtures.digest(history), output_directory=output,
                   allow_bootstrap=False)
    change = options["transition"]
    change.update(retained=[row["id"] for row in data.rows], added=[])
    options["expected_transition_sha256"] = data.fixtures.digest(change)
    return options


def _reviewed_revise_fictional_source_revision(data):
    """Re-sign a declared fictional provenance correction with existing fixtures."""
    case, helper, admission = data.case, data.helper, data.admission
    case["declaration"]["units"][1]["document_revision"] = "fixture:act-v1/corrected-revision-2"
    helper.reviewed_refresh_manifest_v2(case)
    case["preparation"] = admission.prepare_reviewed_norm_admission_v2(
        case["declaration"], **helper.reviewed_prepare_arguments_v2(case))
    body = helper.norm._wire(case["declaration"])
    case["evidence"][case["declaration"]["component_id"]] = body
    for claim in case["reviews"]:
        claim["subject"] = data.deepcopy(case["preparation"]["subject"])
        claim["interpretation"]["reviewed_graph_sha256"] = case["preparation"]["subject"]["graph_sha256"]
        claim["interpretation"]["reviewed_ast_sha256"] = case["preparation"]["subject"]["ast_sha256"]
        for obligation in claim["context_closure"]["obligations"]:
            for reference in obligation["evidence_refs"]:
                if reference["artifact_id"] == case["declaration"]["component_id"]:
                    reference["sha256"] = helper.sha(body)
    helper.reviewed_resign_v2(case)


def test_reviewed_cycle_retains_adds_and_corrects_with_new_ids_and_complete_history(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    data = _reviewed_transition_fixture(tmp_path, count=2)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "bootstrap")
    parent = inputs.stage_reviewed_cycle_inputs(registry, **options)
    options = _reviewed_successor_options(data, options, registry, parent, tmp_path / "successor")
    prior = data.deepcopy(data.rows)
    _reviewed_revise_fictional_source_revision(data)
    rows = [{"id": "reviewed:" + unit["unit_id"], "unit_id": unit["unit_id"],
             "source_text": unit["source_text"], "canonical_ir": data.deepcopy(unit["canonical_ir"])}
            for unit in data.case["preparation"]["units"]]
    rows[1]["id"] += ":revision-2"
    assert rows[0] == prior[0]
    assert rows[1]["canonical_ir"] != prior[1]["canonical_ir"]
    historical = options["history"]["records"]
    for row in rows[1:]:
        example = splits.LegalIRSplitExample.from_sample(row)
        historical.append({"id": row["id"], "source_text": row["source_text"],
            "source_sha256": data.fixtures.source_digest(row["source_text"]),
            "split_example": example.to_dict(), "assignment": "train"})
    manifest = splits.LegalIRSplitManifest(
        examples=tuple(splits.LegalIRSplitExample.from_mapping(record["split_example"]) for record in historical),
        assignments={record["id"]: record["assignment"] for record in historical},
        config_digest=splits.LegalIREvalSplitConfig(**data.config).digest).to_dict()
    exposure = [{"id": row["id"], "source_text_sha256": data.fixtures.source_digest(row["source_text"]),
        "canonical_ir_sha256": data.fixtures.digest(row["canonical_ir"]),
        "target_exposure": "declared_supervised_training", "provenance_ref": "fixture:reviewed-revision"} for row in rows]
    replay = data.fixtures.reviewed_public_admission_inputs(data.helper, data.admission, data.case)
    prepare = dict(data.options, expected_rows_sha256=data.fixtures.digest(rows), split_manifest=manifest,
        expected_split_manifest_sha256=data.fixtures.digest(manifest), exposure_records=exposure,
        expected_exposure_sha256=data.fixtures.digest(exposure), admission_inputs=replay,
        expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(replay))
    changes = {"schema": "reviewed-example-cycle-transition/v1", "retained": [rows[0]["id"]],
        "added": [rows[2]["id"]], "corrected": [{"parent_id": prior[1]["id"], "successor_id": rows[1]["id"],
            "reason_ref": _reviewed_reason(registry, tmp_path)}], "superseded": [], "revoked": []}
    options.update(successor_rows=rows, expected_successor_rows_sha256=data.fixtures.digest(rows),
        successor_binding=consumer.prepare_reviewed_source_span_consumer_binding_v2(rows, **prepare),
        split_manifest=manifest, admission_inputs=replay, exposure_records=exposure,
        transition=changes, expected_transition_sha256=data.fixtures.digest(changes),
        expected_history_sha256=data.fixtures.digest(options["history"]))
    reference = inputs.stage_reviewed_cycle_inputs(registry, **options)
    result = _reviewed_doc(registry, reference)
    assert _reviewed_doc(registry, result["rows_artifact"]) == rows
    assert _reviewed_doc(registry, _reviewed_doc(registry, parent)["rows_artifact"]) == prior
    assert len(_reviewed_doc(registry, result["history_artifact"])["records"]) == 4
    assert result["transition"] == changes
    assert result["checkpoint_lineage"] == _reviewed_doc(registry, parent)["checkpoint_lineage"]


def test_reviewed_cycle_consumes_real_public_admission_and_stages_complete_separate_artifacts(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "staged")
    reference = inputs.stage_reviewed_cycle_inputs(registry, **options)
    document = _reviewed_doc(registry, reference)
    assert document["schema"] == inputs.REVIEWED_CYCLE_SCHEMA
    assert document["consumer_receipt"]["status"] == "ready"
    assert document["consumer_receipt"]["training_mask"] == document["consumer_receipt"]["evaluation_gold_mask"] == 0
    assert _reviewed_doc(registry, document["rows_artifact"]) == data.rows
    assessment = _reviewed_doc(registry, document["admission_assessment_artifact"])
    assert assessment["semantic_use_eligible"] is True
    assert all(unit["argument_roles"] and unit["canonical_ir"]["governing_context"]
               and unit["canonical_ir"]["definition_uses"] for unit in assessment["units"])
    assert assessment["proof_authority"] is assessment["training_executed"] is False
    transport = _reviewed_doc(registry, document["admission_transport_artifact"])
    restored = inputs._reviewed_restore_admission(registry, transport)
    assert consumer.reviewed_admission_inputs_sha256(restored) == consumer.reviewed_admission_inputs_sha256(options["admission_inputs"])
    assert all(type(value["raw_bytes"]) is bytes for value in restored["preparation_inputs"]["source_inputs"].values())
    assert document["compatibility"]["reason"] == "compatible_full_typed_training_profile_unprovided"
    assert all(value is False for key, value in document["compatibility"].items() if key != "reason")
    assert registry.stage_calls > 0


@pytest.mark.parametrize("damage", ["default_bootstrap", "omitted_member", "double_member", "same_id_changed",
                                    "wrong_parent", "lineage", "historical_reactivation"])
def test_reviewed_cycle_rejects_invalid_version_membership_before_staging(tmp_path, damage):
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "bootstrap")
    if damage == "default_bootstrap":
        options.pop("allow_bootstrap")
    else:
        parent = inputs.stage_reviewed_cycle_inputs(registry, **options)
        options = _reviewed_successor_options(data, options, registry, parent, tmp_path / "successor")
        first = data.rows[0]["id"]
        if damage == "omitted_member": options["transition"]["retained"].pop()
        elif damage == "double_member": options["transition"]["added"].append(first)
        elif damage == "same_id_changed": options["successor_rows"][0]["canonical_ir"]["interpretation_id"] += ":changed"
        elif damage == "wrong_parent": options["expected_parent_sha256"] = "0" * 64
        elif damage == "lineage": options["checkpoint_lineage"]["weights_updated"] = True
        else:
            options["transition"]["retained"].remove(first)
            options["transition"]["added"].append(first)
        options["expected_transition_sha256"] = data.fixtures.digest(options["transition"])
        options["expected_successor_rows_sha256"] = data.fixtures.digest(options["successor_rows"])
        options["expected_checkpoint_lineage_sha256"] = data.fixtures.digest(options["checkpoint_lineage"])
    registry.stage_calls = 0
    with pytest.raises(ValueError):
        inputs.stage_reviewed_cycle_inputs(registry, **options)
    assert registry.stage_calls == 0
    assert not options["output_directory"].exists()


@pytest.mark.parametrize("field", (
    "expected_successor_rows_sha256", "expected_transition_sha256", "expected_history_sha256",
    "expected_split_config_sha256", "expected_checkpoint_lineage_sha256",
))
@pytest.mark.parametrize("invalid", (None, True,
                         "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "not-a-sha256",
                         "000000000000000000000000000000000000000000000000000000000000000"),
                         ids=("missing", "boolean", "uppercase", "malformed", "short"))
def test_required_reviewed_commitments_refuse_before_copy_replay_or_staging(tmp_path, monkeypatch, field, invalid):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "never-staged")
    # Bootstrap's parent pin is intentionally optional. The five listed pins
    # independently bind real complete inputs and may never become optional.
    assert options["parent_artifact"] is options["expected_parent_sha256"] is None
    options[field] = invalid
    monkeypatch.setattr(inputs, "_reviewed_copy", _forbidden)
    monkeypatch.setattr(inputs, "_reviewed_read", _forbidden)
    monkeypatch.setattr(consumer, "validate_reviewed_source_span_consumer_binding_v2", _forbidden)
    monkeypatch.setattr(consumer, "consume_reviewed_source_span_binding_v2", _forbidden)
    monkeypatch.setattr(data.admission, "assess_reviewed_norm_admission_v2", _forbidden)
    with pytest.raises(ValueError, match="exact lowercase reviewed SHA256 required"):
        inputs.stage_reviewed_cycle_inputs(registry, **options)
    assert registry.stage_calls == 0
    assert not options["output_directory"].exists()


@pytest.mark.parametrize("retirement", ["revoked", "superseded"])
def test_reviewed_cycle_can_retire_historical_parent_without_current_positive_review(tmp_path, retirement):
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "bootstrap")
    parent = inputs.stage_reviewed_cycle_inputs(registry, **options)
    options = _reviewed_successor_options(data, options, registry, parent, tmp_path / "successor")
    retired = data.rows[-1]["id"]
    options["successor_rows"] = data.rows[:-1]
    options["exposure_records"] = options["exposure_records"][:-1]
    options["transition"]["retained"].remove(retired)
    reason = _reviewed_reason(registry, tmp_path)
    entry = {"parent_id": retired, "reason_ref": reason}
    if retirement == "superseded": entry["successor_id"] = None
    options["transition"][retirement] = [entry]
    options["expected_transition_sha256"] = data.fixtures.digest(options["transition"])
    options["expected_successor_rows_sha256"] = data.fixtures.digest(options["successor_rows"])
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    # The captured parent reviews have expired at this explicitly supplied
    # fictional clock. Fresh current reviews authorize only the successor batch;
    # the staging owner must not demand current positive review of the parent.
    current_time = "2026-10-17T12:03:00Z"
    for claim in data.case["reviews"]:
        claim["issued_at_utc"] = "2026-10-17T12:02:00Z"
        claim["expires_at_utc"] = "2026-10-18T11:00:00Z"
    data.helper.reviewed_resign_v2(data.case)
    replay = data.fixtures.reviewed_public_admission_inputs(data.helper, data.admission, data.case)
    replay["at_time_utc"] = current_time
    options["admission_inputs"] = replay
    prepare = dict(data.options, expected_rows_sha256=options["expected_successor_rows_sha256"],
                   exposure_records=options["exposure_records"], expected_exposure_sha256=data.fixtures.digest(options["exposure_records"]),
                   admission_inputs=replay, expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(replay))
    options["successor_binding"] = consumer.prepare_reviewed_source_span_consumer_binding_v2(options["successor_rows"], **prepare)
    result = _reviewed_doc(registry, inputs.stage_reviewed_cycle_inputs(registry, **options))
    assert len(_reviewed_doc(registry, result["rows_artifact"])) == 2
    assert retired in {record["id"] for record in _reviewed_doc(registry, result["history_artifact"])["records"]}
    assert result["transition"][retirement] == [entry]
    old_parent = _reviewed_doc(registry, parent)
    old_transport = _reviewed_doc(registry, old_parent["admission_transport_artifact"])
    old_inputs = inputs._reviewed_restore_admission(registry, old_transport)
    assert all(claim["expires_at_utc"] < current_time for claim in old_inputs["reviews"])


@pytest.mark.parametrize("denial", ["unreviewed", "revoked_current", "proof_cannot_override"])
def test_current_admission_failure_cannot_be_replaced_by_a_proof_or_old_ready_binding(tmp_path, denial):
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "staged")
    if denial == "unreviewed": data.case["reviews"] = []
    else:
        data.case["registry"]["keys"][0]["revoked_at_utc"] = data.helper.EVALUATED
        data.helper.reviewed_resign_v2(data.case)
    options["admission_inputs"] = data.fixtures.reviewed_public_admission_inputs(data.helper, data.admission, data.case)
    if denial == "proof_cannot_override":
        # Even an exact byte artifact saying proved cannot replace meaning review.
        data.case["evidence"]["fixture:unrelated-proof"] = b'{"proved":true,"kernel_checked":true}'
    with pytest.raises(ValueError):
        inputs.stage_reviewed_cycle_inputs(registry, **options)
    assert registry.stage_calls == 0 and not options["output_directory"].exists()


@pytest.mark.parametrize("damage", ["missing_source", "forged_fingerprint", "different_config", "capacity", "heldout_alias", "heldout_near_duplicate"])
def test_reviewed_guard_refuses_incomplete_or_leaking_historical_populations(tmp_path, damage):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "staged")
    if damage == "missing_source": options["history"]["records"][0]["source_text"] = None
    elif damage == "forged_fingerprint":
        from dataclasses import replace
        manifest = splits.LegalIRSplitManifest.from_mapping(options["split_manifest"])
        changed = (replace(manifest.examples[0], token_fingerprint=()), *manifest.examples[1:])
        frozen = splits.LegalIRSplitManifest(examples=changed, assignments=manifest.assignments,
                                            config_digest=manifest.config_digest).to_dict()
        options["split_manifest"] = frozen
        key = manifest.examples[0].sample_id
        next(record for record in options["history"]["records"] if record["id"] == key)["split_example"] = changed[0].to_dict()
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
        prepare = dict(data.options, split_manifest=frozen, expected_split_manifest_sha256=data.fixtures.digest(frozen))
        options["successor_binding"] = consumer.prepare_reviewed_source_span_consumer_binding_v2(data.rows, **prepare)
    elif damage == "different_config": options["split_config"]["seed"] = "changed-frozen-policy"
    elif damage == "capacity": options["history"]["records"] *= 172
    else:
        from copy import deepcopy
        row = data.rows[0]
        historical_text = row["source_text"] + (" Additional." if damage == "heldout_near_duplicate" else "")
        sample = splits.LegalIRSplitExample.from_sample({"id": "fictional:old-heldout", "text": historical_text})
        old = splits.LegalIRSplitManifest(examples=(sample,), assignments={sample.sample_id: "holdout"},
            config_digest=splits.LegalIREvalSplitConfig(**data.config).digest).to_dict()
        options["history"]["scope_kind"] = "complete_declared_history"
        options["history"]["split_manifests"] = [{"manifest": old, "sha256": data.fixtures.digest(old)}]
        options["history"]["records"].append({"id": sample.sample_id, "source_text": historical_text,
            "source_sha256": data.fixtures.source_digest(historical_text), "split_example": sample.to_dict(), "assignment": "holdout"})
    options["expected_history_sha256"] = data.fixtures.digest(options["history"])
    options["expected_split_config_sha256"] = data.fixtures.digest(options["split_config"])
    expected = {"missing_source": "unsupported_historical_source_replay", "forged_fingerprint": "fingerprint",
                "different_config": "frozen split policy", "capacity": "unsupported_historical_guard_capacity",
                "heldout_alias": "leakage", "heldout_near_duplicate": "leakage"}[damage]
    with pytest.raises((ValueError, splits.LegalIRSplitLeakageError), match=expected):
        inputs.stage_reviewed_cycle_inputs(registry, **options)
    assert registry.stage_calls == 0 and not options["output_directory"].exists()


@pytest.mark.parametrize("damage", ["missing_leaf", "string_placeholder", "duplicate_path"])
def test_staged_admission_transport_preserves_byte_type_and_all_exact_paths(tmp_path, damage):
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    document = _reviewed_doc(registry, inputs.stage_reviewed_cycle_inputs(
        registry, **_reviewed_stage_options(data, tmp_path / "staged")))
    transport = _reviewed_doc(registry, document["admission_transport_artifact"])
    if damage == "missing_leaf": transport["byte_leaves"].pop()
    elif damage == "duplicate_path": transport["byte_leaves"].append(data.deepcopy(transport["byte_leaves"][0]))
    else:
        path = transport["byte_leaves"][0]["path"]
        node = transport["skeleton"]
        for part in path[:-1]: node = node[part]
        node[path[-1]] = "raw bytes cannot become JSON text"
    with pytest.raises(ValueError):
        inputs._reviewed_restore_admission(registry, transport)


def test_reviewed_staging_preserves_failed_exact_readback_without_promotion(tmp_path, monkeypatch):
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "staged")
    monkeypatch.setattr(registry, "read_artifact", lambda *args, **kwargs: b"changed actual readback")
    with pytest.raises(ValueError, match="readback"):
        inputs.stage_reviewed_cycle_inputs(registry, **options)
    assert registry.stage_calls == 1 and list(options["output_directory"].iterdir())


def test_positive_reviewed_staging_refuses_an_empty_successor_without_explicit_withdrawal(tmp_path):
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "staged")
    options["successor_rows"] = []
    with pytest.raises(ValueError, match="unsupported_empty_successor_consumer"):
        inputs.stage_reviewed_cycle_inputs(registry, **options)
    assert registry.stage_calls == 0 and not options["output_directory"].exists()


def test_empty_admission_bytes_stage_no_fake_blob_and_reconstruct_exact_type(tmp_path):
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "staged")
    options["admission_inputs"]["evidence_artifacts"]["fixture:unused-empty-evidence"] = b""
    document = _reviewed_doc(registry, inputs.stage_reviewed_cycle_inputs(registry, **options))
    transport = _reviewed_doc(registry, document["admission_transport_artifact"])
    markers = [leaf for leaf in transport["byte_leaves"] if leaf["kind"] == "empty_bytes"]
    assert markers and all(set(leaf) == {"path", "kind", "bytes", "sha256"} for leaf in markers)
    restored = inputs._reviewed_restore_admission(registry, transport)
    assert restored["evidence_artifacts"]["fixture:unused-empty-evidence"] == b""
    assert min(registry.staged_sizes) > 0


@pytest.mark.parametrize("mutation", ("hash", "bool_count", "mixed_fields", "blob_zero"))
def test_empty_byte_marker_cannot_be_forged_or_confused_with_json(tmp_path, mutation):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_consumer_binding import reviewed_admission_inputs_sha256
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    marker = {"path": ["bytes"], "kind": "empty_bytes", "bytes": 0,
              "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
    transport = {"schema": "reviewed-cycle-admission-input-transport/v2", "skeleton": {"bytes": None},
                 "byte_leaves": [marker], "admission_inputs_sha256": reviewed_admission_inputs_sha256({"bytes": b""})}
    assert inputs._reviewed_restore_admission(registry, transport) == {"bytes": b""}
    assert len({reviewed_admission_inputs_sha256(value) for value in (b"", None, "", [], {})}) == 5
    if mutation == "hash": marker["sha256"] = "0" * 64
    elif mutation == "bool_count": marker["bytes"] = False
    elif mutation == "mixed_fields": marker["artifact"] = {"path": str(tmp_path / "fake"), "bytes": 0, "sha256": marker["sha256"]}
    else:
        transport["byte_leaves"] = [{"path": ["bytes"], "kind": "artifact_bytes",
            "artifact": {"path": str(tmp_path / "fake"), "bytes": 0, "sha256": marker["sha256"]}}]
    with pytest.raises(ValueError):
        inputs._reviewed_restore_admission(registry, transport)
    assert registry.stage_calls == 0


def _reviewed_withdrawal_options(data, options, registry, parent, output):
    options = _reviewed_successor_options(data, options, registry, parent, output)
    reason = _reviewed_reason(registry, output.parent)
    options.update(transition_kind="withdrawal", successor_rows=[],
        expected_successor_rows_sha256=data.fixtures.digest([]), successor_binding=None,
        admission_inputs=None, exposure_records=None)
    options["transition"].update(retained=[], added=[], corrected=[], superseded=[],
        revoked=[{"parent_id": row["id"], "reason_ref": reason} for row in data.rows])
    _repin_withdrawal(data, options)
    return options


def _repin_withdrawal(data, options):
    options["expected_transition_sha256"] = data.fixtures.digest(options["transition"])
    options["expected_history_sha256"] = data.fixtures.digest(options["history"])
    reasons = {data.fixtures.digest(entry["reason_ref"]): entry["reason_ref"]
               for kind in ("superseded", "revoked") for entry in options["transition"][kind]}
    # Sort by the existing canonical JSON recipe, matching the declared union.
    ordered = sorted(reasons.values(), key=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")))
    provenance = {"schema": "reviewed-cycle-withdrawal-provenance/v1",
        "parent_artifact_sha256": options["parent_artifact"]["sha256"],
        "transition_sha256": options["expected_transition_sha256"],
        "history_sha256": options["expected_history_sha256"],
        "checkpoint_lineage_sha256": options["expected_checkpoint_lineage_sha256"],
        "reason_refs": ordered, "declared_at_utc": "2026-10-18T12:00:00Z",
        "authority_kind": "operator_declared_retirement_only"}
    options.update(withdrawal_provenance=provenance,
                   expected_withdrawal_provenance_sha256=data.fixtures.digest(provenance))


@pytest.mark.parametrize("leaking_history", (False, True))
def test_explicit_withdrawal_removes_all_active_rows_without_positive_owner_calls(tmp_path, monkeypatch, leaking_history):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "bootstrap")
    parent = inputs.stage_reviewed_cycle_inputs(registry, **options)
    old_history = _reviewed_doc(registry, _reviewed_doc(registry, parent)["history_artifact"])
    options = _reviewed_withdrawal_options(data, options, registry, parent, tmp_path / "withdrawal")
    if leaking_history:
        row = data.rows[0]
        example = splits.LegalIRSplitExample.from_sample({"id": "fixture:discovered-heldout", "text": row["source_text"]})
        frozen = splits.LegalIRSplitManifest(examples=(example,), assignments={example.sample_id: "holdout"},
            config_digest=splits.LegalIREvalSplitConfig(**data.config).digest).to_dict()
        options["history"]["split_manifests"].append({"manifest": frozen, "sha256": data.fixtures.digest(frozen)})
        options["history"]["records"].append({"id": example.sample_id, "source_text": row["source_text"],
            "source_sha256": data.fixtures.source_digest(row["source_text"]),
            "split_example": example.to_dict(), "assignment": "holdout"})
        _repin_withdrawal(data, options)
    monkeypatch.setattr(consumer, "consume_reviewed_source_span_binding_v2", _forbidden)
    monkeypatch.setattr(consumer, "validate_reviewed_source_span_consumer_binding_v2", _forbidden)
    monkeypatch.setattr(data.admission, "assess_reviewed_norm_admission_v2", _forbidden)
    result = _reviewed_doc(registry, inputs.stage_reviewed_cycle_inputs(registry, **options))
    assert _reviewed_doc(registry, result["rows_artifact"]) == []
    assert registry.read_artifact({key: result["rows_artifact"][key] for key in ("sha256", "bytes")}, max_bytes=2) == b"[]"
    assert result["admission_assessment_artifact"] is result["admission_transport_artifact"] is None
    assert result["consumer_receipt"]["status"] == "not_applicable"
    assert result["consumer_receipt"]["positive_consumer_called"] is False
    assert result["history_guard"]["positive_use_authorized"] is False
    assert result["history_guard"]["status"] == ("violations" if leaking_history else "passed")
    assert result["history_guard"]["result"]["passed"] is (not leaking_history)
    retained = _reviewed_doc(registry, result["history_artifact"])
    assert all(record in retained["records"] for record in old_history["records"])
    assert all(value is False for key, value in result["compatibility"].items() if key != "reason")


@pytest.mark.parametrize("damage", ("missing_provenance", "missing_retirement", "double_retirement", "foreign_retirement",
                                    "nonnull_admission", "bad_history", "bad_provenance"))
def test_withdrawal_requires_complete_independent_retirement_and_guard_inputs(tmp_path, damage):
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "bootstrap")
    parent = inputs.stage_reviewed_cycle_inputs(registry, **options)
    options = _reviewed_withdrawal_options(data, options, registry, parent, tmp_path / "withdrawal")
    if damage == "missing_provenance": options["withdrawal_provenance"] = None
    elif damage == "missing_retirement": options["transition"]["revoked"].pop()
    elif damage == "double_retirement": options["transition"]["revoked"].append(data.deepcopy(options["transition"]["revoked"][0]))
    elif damage == "foreign_retirement": options["transition"]["revoked"][0]["parent_id"] = "fixture:foreign"
    elif damage == "nonnull_admission": options["admission_inputs"] = data.options["admission_inputs"]
    elif damage == "bad_history": options["history"]["records"][0]["source_text"] = None
    else: options["withdrawal_provenance"]["parent_artifact_sha256"] = "0" * 64
    if damage in {"missing_retirement", "double_retirement", "foreign_retirement", "bad_history"}:
        _repin_withdrawal(data, options)
    registry.stage_calls = 0
    with pytest.raises(ValueError):
        inputs.stage_reviewed_cycle_inputs(registry, **options)
    assert registry.stage_calls == 0 and not options["output_directory"].exists()


def _reviewed_readmit_options(data, registry, parent, output):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    for claim in data.case["reviews"]:
        claim["issued_at_utc"] = "2026-10-19T12:02:00Z"
        claim["expires_at_utc"] = "2026-10-20T11:00:00Z"
    data.helper.reviewed_resign_v2(data.case)
    replay = data.fixtures.reviewed_public_admission_inputs(data.helper, data.admission, data.case)
    replay["at_time_utc"] = "2026-10-19T12:03:00Z"
    data.options.update(admission_inputs=replay,
        expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(replay))
    document = _reviewed_doc(registry, parent)
    history = _reviewed_doc(registry, document["history_artifact"])
    history.update(scope_kind="complete_declared_history", parent_history_artifact=document["history_artifact"])
    rows = data.deepcopy(data.rows)
    for row in rows:
        row["id"] += ":readmitted-revision"
        example = splits.LegalIRSplitExample.from_sample(row)
        history["records"].append({"id": row["id"], "source_text": row["source_text"],
            "source_sha256": data.fixtures.source_digest(row["source_text"]),
            "split_example": example.to_dict(), "assignment": "train"})
    manifest = splits.LegalIRSplitManifest(
        examples=tuple(splits.LegalIRSplitExample.from_mapping(record["split_example"]) for record in history["records"]),
        assignments={record["id"]: record["assignment"] for record in history["records"]},
        config_digest=splits.LegalIREvalSplitConfig(**data.config).digest).to_dict()
    exposure = [dict(item, id=row["id"]) for row, item in zip(rows, data.options["exposure_records"], strict=True)]
    prepare = dict(data.options, expected_rows_sha256=data.fixtures.digest(rows), split_manifest=manifest,
        expected_split_manifest_sha256=data.fixtures.digest(manifest), exposure_records=exposure,
        expected_exposure_sha256=data.fixtures.digest(exposure))
    changes = {"schema": "reviewed-example-cycle-transition/v1", "retained": [], "added": [row["id"] for row in rows],
               "corrected": [], "superseded": [], "revoked": []}
    result = _reviewed_stage_options(data, output)
    result.update(transition_kind="successor", parent_artifact=parent, expected_parent_sha256=parent["sha256"],
        successor_rows=rows, expected_successor_rows_sha256=data.fixtures.digest(rows),
        successor_binding=consumer.prepare_reviewed_source_span_consumer_binding_v2(rows, **prepare),
        split_manifest=manifest, exposure_records=exposure, transition=changes,
        expected_transition_sha256=data.fixtures.digest(changes), history=history,
        expected_history_sha256=data.fixtures.digest(history), allow_bootstrap=False)
    return result


def test_withdrawn_parent_can_be_followed_by_genuine_new_revision_admission(tmp_path):
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "bootstrap")
    first = inputs.stage_reviewed_cycle_inputs(registry, **options)
    withdrawal = _reviewed_withdrawal_options(data, options, registry, first, tmp_path / "withdrawal")
    retired = inputs.stage_reviewed_cycle_inputs(registry, **withdrawal)
    readmit = _reviewed_readmit_options(data, registry, retired, tmp_path / "readmission")
    final = _reviewed_doc(registry, inputs.stage_reviewed_cycle_inputs(registry, **readmit))
    assert final["consumer_receipt"]["status"] == "ready"
    assert len(_reviewed_doc(registry, final["history_artifact"])["records"]) == 6
    assert all(row["id"].endswith(":readmitted-revision") for row in _reviewed_doc(registry, final["rows_artifact"]))
    assert _reviewed_doc(registry, _reviewed_doc(registry, retired)["rows_artifact"]) == []


@pytest.mark.parametrize("damage", ("fake_ready", "positive_kind", "fake_assessment", "wrong_provenance"))
def test_zero_row_parent_requires_exact_withdrawal_contract(tmp_path, damage):
    import hashlib
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "bootstrap")
    first = inputs.stage_reviewed_cycle_inputs(registry, **options)
    retired = inputs.stage_reviewed_cycle_inputs(registry, **_reviewed_withdrawal_options(
        data, options, registry, first, tmp_path / "withdrawal"))
    document = _reviewed_doc(registry, retired)
    if damage == "fake_ready": document["consumer_receipt"]["status"] = "ready"
    elif damage == "positive_kind": document["transition_kind"] = "successor"
    elif damage == "fake_assessment": document["admission_assessment_artifact"] = _reviewed_doc(registry, first)["admission_assessment_artifact"]
    else: document["withdrawal_provenance"]["reason_refs"] = []
    path = tmp_path / "explicitly-malformed-parent.json"
    path.write_bytes(inputs._reviewed_wire(document))
    descriptor = registry.stage_artifact(path, hashlib.sha256(path.read_bytes()).hexdigest())
    bad = dict(descriptor, path=str(registry.artifact_path(descriptor)))
    restart = _reviewed_stage_options(data, tmp_path / "never-staged")
    historical = _reviewed_doc(registry, document["history_artifact"])
    historical.update(scope_kind="complete_declared_history", parent_history_artifact=document["history_artifact"])
    restart.update(transition_kind="successor", parent_artifact=bad, expected_parent_sha256=bad["sha256"],
                   history=historical, expected_history_sha256=data.fixtures.digest(historical), allow_bootstrap=False)
    registry.stage_calls = 0
    with pytest.raises(ValueError, match="withdrawal|historical positive|empty parent"):
        inputs.stage_reviewed_cycle_inputs(registry, **restart)
    assert registry.stage_calls == 0 and not restart["output_directory"].exists()


def test_historical_retired_id_cannot_reactivate_with_an_untracked_target(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "bootstrap")
    first = inputs.stage_reviewed_cycle_inputs(registry, **options)
    options = _reviewed_successor_options(data, options, registry, first, tmp_path / "retirement")
    retired = data.rows[-1]["id"]
    options["successor_rows"] = data.rows[:-1]
    options["exposure_records"] = data.options["exposure_records"][:-1]
    options["transition"]["retained"].remove(retired)
    options["transition"]["revoked"] = [{"parent_id": retired, "reason_ref": _reviewed_reason(registry, tmp_path)}]
    options["expected_transition_sha256"] = data.fixtures.digest(options["transition"])
    options["expected_successor_rows_sha256"] = data.fixtures.digest(options["successor_rows"])
    prepare = dict(data.options, expected_rows_sha256=options["expected_successor_rows_sha256"],
        exposure_records=options["exposure_records"], expected_exposure_sha256=data.fixtures.digest(options["exposure_records"]))
    options["successor_binding"] = consumer.prepare_reviewed_source_span_consumer_binding_v2(options["successor_rows"], **prepare)
    second = inputs.stage_reviewed_cycle_inputs(registry, **options)
    options = _reviewed_successor_options(data, options, registry, second, tmp_path / "forbidden-reactivation")
    options.update(successor_rows=data.rows, expected_successor_rows_sha256=data.fixtures.digest(data.rows),
        exposure_records=data.options["exposure_records"],
        successor_binding=consumer.prepare_reviewed_source_span_consumer_binding_v2(data.rows, **data.options))
    options["transition"].update(retained=[row["id"] for row in data.rows[:-1]], added=[retired], revoked=[])
    options["expected_transition_sha256"] = data.fixtures.digest(options["transition"])
    registry.stage_calls = 0
    with pytest.raises(ValueError, match="unsupported_historical_id_reactivation"):
        inputs.stage_reviewed_cycle_inputs(registry, **options)
    assert registry.stage_calls == 0 and not options["output_directory"].exists()


@pytest.mark.parametrize("schema", ["v6", "v8"])
def test_exact_default_training_order_and_explicit_subset_exclude_validation(tmp_path, schema):
    spec = _spec(tmp_path, schema)
    verified = worker.verify_corpus_job_inputs(spec)
    default = inputs.verify_cycle_inputs(spec)
    expected = verified["training_record_ids"]
    assert default.verification == verified
    assert [record.record_id for record in default.training_records] == expected
    assert [asdict(record.sample) for record in default.training_records] == [asdict(row) for row in spec.samples]
    chosen = list(reversed(expected))[:1]
    subset = inputs.verify_cycle_inputs(spec, record_ids=chosen)
    assert [record.record_id for record in subset.training_records] == chosen
    assert not set(chosen).intersection(verified["validation_record_ids"])
    for selection in (verified["validation_record_ids"], ["sha256:" + "0" * 64], [], expected * 2):
        with pytest.raises(ValueError, match="training members"):
            inputs.verify_cycle_inputs(spec, record_ids=selection)


@pytest.mark.parametrize("schema", ["v6", "v8"])
def test_feedback_bound_fails_before_source_work_or_training(tmp_path, monkeypatch, schema):
    spec = _spec(tmp_path, schema)
    too_many = replace(spec, samples=tuple(spec.samples[:1]) * 129)
    monkeypatch.setattr(inputs, "verify_corpus_job_inputs", _forbidden)
    with pytest.raises(ValueError, match="128"):
        inputs.verify_cycle_inputs(too_many)
    with pytest.raises(ValueError, match="128"):
        inputs.verify_cycle_inputs(spec, record_ids=(str(number) for number in range(129)))


def test_v7_mapped_transport_is_rejected_before_verification(tmp_path, monkeypatch):
    spec = _spec(tmp_path, "v7")
    monkeypatch.setattr(inputs, "verify_corpus_job_inputs", _forbidden)
    with pytest.raises(ValueError, match="v6 or v8 inline"):
        inputs.verify_cycle_inputs(spec)
    with pytest.raises(ValueError, match="v6 or v8 inline"):
        inputs.stage_cycle_job_inputs(SimpleNamespace(stage_artifact=_forbidden), spec)


@pytest.mark.parametrize("schema", ["v6", "v8"])
def test_staging_preserves_all_declared_bytes_options_and_correct_variant(tmp_path, schema):
    spec = _spec(tmp_path / "input", schema)
    refs = [_artifact(tmp_path / f"optional-{number}", f"opaque-staging-fixture-{number}".encode()) for number in range(3)]
    spec = replace(spec, target_snapshot_id="fixture-target", target_snapshot_artifact=worker.CheckpointArtifact.from_dict(refs[0]),
        arrow_feature_weights_artifact=worker.CheckpointArtifact.from_dict(refs[1]),
        base_checkpoint_dependencies=(worker.CheckpointArtifact.from_dict(refs[2]),),
        capture_sparse_patches=True, candidate_storage="sparse")
    original = spec.to_dict()
    # These optional artifacts exercise byte staging only, not their codecs.
    inputs.verify_cycle_inputs(spec)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        payload, variant = inputs.stage_cycle_job_inputs(registry, spec)
        restored = worker.TrainingJobSpec.from_dict(payload)
        assert restored.training_config == spec.training_config
        assert restored.capture_sparse_patches and restored.candidate_storage == "sparse"
        assert restored.target_snapshot_id == "fixture-target"
        fields = ("base_checkpoint", "corpus_manifest_artifact", "target_snapshot_artifact", "arrow_feature_weights_artifact")
        fields += (worker.CAMPAIGN_ARTIFACT_FIELDS if schema == "v8" else ("corpus_index_artifact", "embedding_production_artifact"))
        arrays = ("base_checkpoint_dependencies", "corpus_source_artifacts") + (("embedding_receipt_artifacts",) if schema == "v8" else ())
        for before, after in [(original[name], payload[name]) for name in fields] + [
                pair for name in arrays for pair in zip(original[name], payload[name], strict=True)]:
            assert {key: before[key] for key in ("sha256", "bytes")} == {key: after[key] for key in ("sha256", "bytes")}
            assert Path(after["path"]) == registry.artifact_path({key: after[key] for key in ("sha256", "bytes")})
            assert Path(before["path"]).read_bytes() == Path(after["path"]).read_bytes()
        if schema == "v8":
            assert set(variant) == set(payload["variant"]) | {"source_campaign_binding"}
            assert variant["source_campaign_binding"] == {name: {key: payload[name + "_artifact"][key]
                for key in ("sha256", "bytes")} for name in ("source_inventory", "source_partitions", "embedding_receipt_set")}
            assert not {"corpus_index_binding", "embedding_production_binding"}.intersection(variant)
        else:
            assert set(variant) == set(payload["variant"]) | {"corpus_index_binding", "embedding_production_binding"}
    assert spec.to_dict() == original


def test_staging_rejects_declared_size_mismatch_and_confers_no_verification(tmp_path):
    spec = _spec(tmp_path / "input")
    changed = replace(spec, base_checkpoint=replace(spec.base_checkpoint, bytes=spec.base_checkpoint.bytes + 1))
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        with pytest.raises(ValueError, match="declared byte identity"):
            inputs.stage_cycle_job_inputs(registry, changed)


@pytest.fixture
def runner(monkeypatch):
    scripts = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("autoformal_campaign_cycle_under_test", scripts / "run_autoformal_training_cycle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "pin_accelerate", lambda path: {})
    monkeypatch.setattr(module, "code_identity", lambda: "fixture-compiler-code")
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source",
                        SimpleNamespace(DatabaseTaskSource=_forbidden))
    return module


@pytest.mark.parametrize("schema", ["v6", "v8"])
def test_cycle_reaches_dispatch_with_owner_staged_contract_without_executing_it(tmp_path, monkeypatch, runner, schema):
    spec = _spec(tmp_path / "input", schema)
    job = tmp_path / "job.json"
    job.write_text(json.dumps(spec.to_dict()))
    seen = []

    class StopBeforeTraining(Exception):
        pass

    def stop(registry, specs, **kwargs):
        seen.extend(specs)
        assert registry.get_run(specs[0].run_id)["status"] == "queued"
        assert worker.verify_corpus_job_inputs(specs[0])["training_record_ids"] == inputs.verify_cycle_inputs(spec).verification["training_record_ids"]
        raise StopBeforeTraining

    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator
    monkeypatch.setattr(autoencoder_training_coordinator, "run_training_jobs", stop)
    with pytest.raises(StopBeforeTraining):
        runner.main(["--accelerate-root", str(tmp_path), "--job-template", str(job),
            "--database", str(tmp_path / "never-opened-queue.duckdb"), "--runtime-root", str(tmp_path / "runtime")])
    assert len(seen) == 1 and seen[0].schema_version == spec.schema_version
    assert not Path(seen[0].output_directory).exists()
    assert not (tmp_path / "never-opened-queue.duckdb").exists()


@pytest.mark.parametrize("problem", ["validation_changed", "too_many_feedback_records", "mapped_transport"])
def test_cycle_invalid_inputs_fail_before_registry_or_training(tmp_path, monkeypatch, runner, problem):
    spec = _spec(tmp_path / "input", "v7" if problem == "mapped_transport" else "v8")
    if problem == "validation_changed":
        spec = replace(spec, validation_samples=(replace(spec.validation_samples[0], text="changed held-out text"), *spec.validation_samples[1:]))
    elif problem == "too_many_feedback_records":
        spec = replace(spec, samples=spec.samples[:1] * 129)
    job = tmp_path / "job.json"
    job.write_text(json.dumps(spec.to_dict()))
    from ipfs_datasets_py.duckdb_control import autoencoder_registry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator
    monkeypatch.setattr(autoencoder_registry, "AutoencoderRegistry", _forbidden)
    monkeypatch.setattr(autoencoder_training_coordinator, "run_training_jobs", _forbidden)
    monkeypatch.setattr(inputs, "stage_cycle_job_inputs", _forbidden)
    with pytest.raises(ValueError):
        runner.main(["--accelerate-root", str(tmp_path), "--job-template", str(job),
            "--database", str(tmp_path / "queue.duckdb"), "--runtime-root", str(tmp_path / "runtime")])
    assert not (tmp_path / "runtime").exists()


def test_new_runtime_helper_and_contract_tests_are_protected(runner):
    from run_autoformal_supervisor import PROTECTED
    assert {"ipfs_datasets_py/logic/autoformal/training_cycle_inputs.py",
            "tests/unit/logic/test_autoformal_campaign_training_inputs.py",
            "tests/unit/logic/test_autoformal_campaign_learned_feedback.py"}.issubset(PROTECTED)


@pytest.mark.parametrize("problem", ["helper_before_dispatch", "compiler_after_selection", "helper_after_selection", "compiler_during_census"])
def test_cycle_source_guards_stop_dispatch_or_repair_mutation(tmp_path, monkeypatch, runner, problem):
    """Injected control-flow receipts are never native execution evidence."""
    spec = _spec(tmp_path / "input")
    job = tmp_path / "job.json"
    job.write_text(json.dumps(spec.to_dict()))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator
    from ipfs_datasets_py.logic.autoformal import learned_feedback, autoencoder_router, supervisor_queue
    stages, dispatches, queue_opens = [], [], []
    stage = inputs.stage_cycle_job_inputs
    verify = inputs.verify_cycle_inputs

    def staging(*args, **kwargs):
        result = stage(*args, **kwargs)
        stages.append(True)
        if problem == "helper_before_dispatch":
            monkeypatch.setattr(inputs, "__file__", learned_feedback.__file__)
        return result

    verification_calls = []

    def verifying(*args, **kwargs):
        result = verify(*args, **kwargs)
        verification_calls.append(True)
        if len(verification_calls) == 2:
            if problem == "compiler_after_selection":
                monkeypatch.setattr(runner, "code_identity", lambda: "changed-compiler")
            elif problem == "helper_after_selection":
                monkeypatch.setattr(inputs, "__file__", learned_feedback.__file__)
        return result

    def injected_dispatch(registry, specs, **kwargs):
        assert problem != "helper_before_dispatch", "changed helper reached dispatch"
        current = specs[0]
        dispatches.append(current)
        output = Path(current.output_directory)
        output.mkdir()
        (output / "receipt.json").write_text(json.dumps({"execution_mode": "native_training", "promotion_performed": False,
            "optimizer_accepted_epochs": 0, "training_report": {}}))
        return {"failed": [], "completed": [{"candidate": {"sha256": current.base_checkpoint.sha256,
            "bytes": current.base_checkpoint.bytes}, "version_id": "synthetic-no-training-version"}]}

    class FakeSource:
        def __init__(self, *args, **kwargs):
            queue_opens.append(True)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def census(samples, inference):
        assert problem == "compiler_during_census"
        monkeypatch.setattr(runner, "code_identity", lambda: "changed-compiler")
        return {"rows": samples}

    monkeypatch.setattr(inputs, "stage_cycle_job_inputs", staging)
    monkeypatch.setattr(inputs, "verify_cycle_inputs", verifying)
    monkeypatch.setattr(autoencoder_training_coordinator, "run_training_jobs", injected_dispatch)
    monkeypatch.setattr(learned_feedback, "observe_checkpoint", lambda *args, **kwargs: {"observation_count": 0})
    monkeypatch.setattr(learned_feedback, "attach_guidance", lambda agreement, *args: agreement)
    monkeypatch.setattr(autoencoder_router, "agreement_census", census)
    monkeypatch.setattr(supervisor_queue, "repair_packets", _forbidden)
    monkeypatch.setattr(supervisor_queue, "enqueue_repairs", _forbidden)
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source",
                        SimpleNamespace(DatabaseTaskSource=FakeSource))
    with pytest.raises(RuntimeError, match="helper changed|compiler changed"):
        runner.main(["--accelerate-root", str(tmp_path), "--job-template", str(job),
            "--database", str(tmp_path / "never-opened-queue.duckdb"), "--runtime-root", str(tmp_path / "runtime")])
    assert stages == [True]
    assert len(dispatches) == (0 if problem == "helper_before_dispatch" else 1)
    assert len(queue_opens) == (1 if problem == "compiler_during_census" else 0)
    assert not (tmp_path / "never-opened-queue.duckdb").exists()


def _reviewed_frozen_guard_fixture(data, kind):
    """Keep a genuinely ready current batch while declaring old guard metadata."""
    from dataclasses import replace
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    cfg = splits.LegalIREvalSplitConfig(**data.config)
    current = splits.LegalIRSplitManifest.from_mapping(data.options["split_manifest"])
    examples = list(current.examples)
    if kind == "narrowed_policy":
        cfg = replace(cfg, protected_splits=("canary",))
    if kind == "frozen_group":
        examples[0] = examples[0].with_near_duplicate_key("fixture:committed-protective-group")
    manifest = splits.LegalIRSplitManifest(examples=tuple(examples), assignments=current.assignments,
        config_digest=cfg.digest, protected_splits=splits.PROTECTED_LEGAL_IR_SPLITS).to_dict()
    data.config = cfg.to_dict()
    data.options.update(split_manifest=manifest, expected_split_manifest_sha256=data.fixtures.digest(manifest))
    by_id = {example.sample_id: example for example in examples}
    for record in data.history["records"]:
        record["split_example"] = by_id[record["id"]].to_dict()


def _append_reviewed_historical_guard(data, options, kind, *, conflicts=None):
    """Append an independently committed historical manifest, preserving prefix."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    current = splits.LegalIRSplitManifest.from_mapping(options["split_manifest"])
    first = current.examples[0]
    texts = {row["id"]: row["source_text"] for row in data.rows}
    if kind == "narrowed_policy":
        text = texts[first.sample_id]
    elif kind == "recomputed_near":
        text = texts[first.sample_id] + " Additional."
    elif kind == "assignment_conflict":
        text = "Amber turbines rotate beside distant cobalt dunes."
    else:
        text = "Violet minerals rest beneath quiet silver mountains."
    sample = splits.LegalIRSplitExample.from_sample({"id": "fixture:historical-" + kind, "text": text})
    if kind == "frozen_group":
        sample = sample.with_near_duplicate_key(first.near_duplicate_key)
        assert sample.near_duplicate_key == "fixture:committed-protective-group"
    assignment = "train" if kind == "assignment_conflict" else "holdout"
    declared_conflicts = {sample.sample_id: conflicts or ("train", "holdout")} if kind == "assignment_conflict" else {}
    historic = splits.LegalIRSplitManifest(examples=(sample,), assignments={sample.sample_id: assignment},
        config_digest=splits.LegalIREvalSplitConfig(**data.config).digest,
        protected_splits=splits.PROTECTED_LEGAL_IR_SPLITS, assignment_conflicts=declared_conflicts)
    payload = historic.to_dict()
    history = options["history"]
    history["scope_kind"] = "complete_declared_history"
    history["split_manifests"].append({"manifest": payload, "sha256": data.fixtures.digest(payload)})
    record = {"id": sample.sample_id, "source_text": text,
        "source_sha256": data.fixtures.source_digest(text), "split_example": sample.to_dict(), "assignment": assignment}
    existing = next((item for item in history["records"] if item["id"] == sample.sample_id), None)
    if existing is None:
        history["records"].append(record)
    else:
        assert existing == record
    options["expected_history_sha256"] = data.fixtures.digest(history)
    return current, historic


def _canonical_reviewed_guard_views(data, current, historic):
    """Observe actual canonical guard behavior for one crafted historical edge."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    cfg = splits.LegalIREvalSplitConfig(**data.config)
    examples = current.examples + historic.examples
    assignments = dict(current.assignments, **historic.assignments)
    conflicts = dict(historic.assignment_conflicts)
    frozen = splits.LegalIRSplitManifest(examples=examples, assignments=assignments,
        config_digest=cfg.digest, protected_splits=splits.PROTECTED_LEGAL_IR_SPLITS,
        assignment_conflicts=conflicts)
    clusters = splits._near_duplicate_clusters(examples, cfg.near_duplicate_jaccard_threshold)
    recomputed = splits.LegalIRSplitManifest(
        examples=tuple(example.with_near_duplicate_key(clusters[example.sample_id]) for example in examples),
        assignments=assignments, config_digest=cfg.digest, protected_splits=splits.PROTECTED_LEGAL_IR_SPLITS,
        assignment_conflicts=conflicts)
    lossy_old_shape = splits.LegalIRSplitManifest(examples=recomputed.examples, assignments=assignments,
        config_digest=cfg.digest, protected_splits=cfg.protected_splits)
    return (splits.validate_legal_ir_eval_splits(frozen), splits.validate_legal_ir_eval_splits(recomputed),
            splits.validate_legal_ir_eval_splits(lossy_old_shape), clusters)


@pytest.mark.parametrize("kind", ("narrowed_policy", "assignment_conflict", "frozen_group"))
def test_reviewed_positive_history_cannot_lose_frozen_guard_protections(tmp_path, kind):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    data = _reviewed_transition_fixture(tmp_path)
    _reviewed_frozen_guard_fixture(data, kind)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "never-staged")
    current, historic = _append_reviewed_historical_guard(data, options, kind)
    frozen, recomputed, lossy, clusters = _canonical_reviewed_guard_views(data, current, historic)
    # The current public consumer remains genuinely ready, and the exact
    # lossy old guard construction misses the independently observed violation.
    assert options["successor_binding"].receipt()["status"] == "ready"
    assert splits.validate_legal_ir_eval_splits(current).passed
    assert not frozen.passed and lossy.passed
    if kind == "frozen_group":
        assert recomputed.passed
        assert clusters[current.examples[0].sample_id] != clusters[historic.examples[0].sample_id]
        assert current.examples[0].near_duplicate_key == historic.examples[0].near_duplicate_key
    if kind == "narrowed_policy":
        assert current.protected_splits == historic.protected_splits == splits.PROTECTED_LEGAL_IR_SPLITS
        assert tuple(data.config["protected_splits"]) == ("canary",)
        with pytest.raises(ValueError, match="configuration and frozen protected profile must agree"):
            inputs.stage_reviewed_cycle_inputs(registry, **options)
    else:
        with pytest.raises(splits.LegalIRSplitLeakageError) as refused:
            inputs.stage_reviewed_cycle_inputs(registry, **options)
        assert type(refused.value.result) is splits.LegalIRSplitGuardResult
        expected = [item.to_dict() for item in frozen.violations]
        actual = [item.to_dict() for item in refused.value.result.violations]
        assert all(item in actual for item in expected)
    assert registry.stage_calls == 0 and not options["output_directory"].exists()


@pytest.mark.parametrize("kind", ("assignment_conflict", "frozen_group"))
def test_withdrawal_retains_actual_frozen_guard_violations_without_rewriting_parent(tmp_path, kind):
    data = _reviewed_transition_fixture(tmp_path)
    _reviewed_frozen_guard_fixture(data, kind)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "bootstrap")
    parent = inputs.stage_reviewed_cycle_inputs(registry, **options)
    original_parent = _reviewed_doc(registry, parent)
    original_history = _reviewed_doc(registry, original_parent["history_artifact"])
    options = _reviewed_withdrawal_options(data, options, registry, parent, tmp_path / "withdrawal")
    current, historic = _append_reviewed_historical_guard(data, options, kind)
    frozen, _, lossy, _ = _canonical_reviewed_guard_views(data, current, historic)
    assert not frozen.passed and lossy.passed
    _repin_withdrawal(data, options)
    result = _reviewed_doc(registry, inputs.stage_reviewed_cycle_inputs(registry, **options))
    guard = result["history_guard"]
    assert guard["status"] == "violations" and guard["result"]["passed"] is False
    assert guard["positive_use_authorized"] is False
    assert all(item.to_dict() in guard["result"]["violations"] for item in frozen.violations)
    history = _reviewed_doc(registry, result["history_artifact"])
    assert history["split_manifests"][:len(original_history["split_manifests"])] == original_history["split_manifests"]
    assert all(record in history["records"] for record in original_history["records"])
    assert _reviewed_doc(registry, parent) == original_parent


def test_withdrawal_aggregates_real_frozen_and_recomputed_guard_evidence(tmp_path):
    data = _reviewed_transition_fixture(tmp_path)
    _reviewed_frozen_guard_fixture(data, "frozen_group")
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "bootstrap")
    parent = inputs.stage_reviewed_cycle_inputs(registry, **options)
    options = _reviewed_withdrawal_options(data, options, registry, parent, tmp_path / "withdrawal")
    expected = []
    for kind in ("assignment_conflict", "frozen_group", "recomputed_near"):
        current, historic = _append_reviewed_historical_guard(data, options, kind)
        frozen, recomputed, _, _ = _canonical_reviewed_guard_views(data, current, historic)
        if kind == "recomputed_near":
            assert frozen.passed and not recomputed.passed
            expected.extend(item.to_dict() for item in recomputed.violations)
        else:
            assert not frozen.passed
            expected.extend(item.to_dict() for item in frozen.violations)
    _repin_withdrawal(data, options)
    result = _reviewed_doc(registry, inputs.stage_reviewed_cycle_inputs(registry, **options))
    actual = result["history_guard"]["result"]
    assert actual["passed"] is False and actual["blocked_operations"]
    assert all(item in actual["violations"] for item in expected)
    assert _reviewed_doc(registry, result["rows_artifact"]) == []


def test_withdrawal_merges_every_committed_assignment_conflict_for_the_same_example(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "bootstrap")
    parent = inputs.stage_reviewed_cycle_inputs(registry, **options)
    options = _reviewed_withdrawal_options(data, options, registry, parent, tmp_path / "withdrawal")
    current, first = _append_reviewed_historical_guard(data, options, "assignment_conflict",
                                                      conflicts=("train", "validation"))
    _, second = _append_reviewed_historical_guard(data, options, "assignment_conflict",
                                                 conflicts=("train", "holdout"))
    assert not splits.validate_legal_ir_eval_splits(first).passed
    assert not splits.validate_legal_ir_eval_splits(second).passed
    sample_id = first.examples[0].sample_id
    merged = splits.LegalIRSplitManifest(examples=current.examples + first.examples,
        assignments=dict(current.assignments, **first.assignments), config_digest=current.config_digest,
        protected_splits=splits.PROTECTED_LEGAL_IR_SPLITS,
        assignment_conflicts={sample_id: ("train", "validation", "holdout")})
    expected = splits.validate_legal_ir_eval_splits(merged)
    _repin_withdrawal(data, options)
    result = _reviewed_doc(registry, inputs.stage_reviewed_cycle_inputs(registry, **options))
    assert all(item.to_dict() in result["history_guard"]["result"]["violations"] for item in expected.violations)
    conflict = next(item for item in result["history_guard"]["result"]["violations"]
                    if item["kind"] == "example" and item["key"] == sample_id)
    assert set(conflict["splits"]) == {"train", "validation", "holdout"}


def test_withdrawal_refuses_a_configuration_that_narrows_fixed_parent_protections(tmp_path):
    from dataclasses import replace
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    data = _reviewed_transition_fixture(tmp_path)
    registry = _ReviewedArtifactRegistry(tmp_path / "registry")
    options = _reviewed_stage_options(data, tmp_path / "bootstrap")
    parent = inputs.stage_reviewed_cycle_inputs(registry, **options)
    options = _reviewed_withdrawal_options(data, options, registry, parent, tmp_path / "withdrawal")
    options["split_config"] = replace(splits.LegalIREvalSplitConfig(**data.config), protected_splits=("canary",)).to_dict()
    options["expected_split_config_sha256"] = data.fixtures.digest(options["split_config"])
    registry.stage_calls = 0
    with pytest.raises(ValueError, match="configuration and frozen protected profile must agree"):
        inputs.stage_reviewed_cycle_inputs(registry, **options)
    assert registry.stage_calls == 0 and not options["output_directory"].exists()


class _ReviewedDecoderByteTokenizer:
    """Explicit fictional byte transport, with non-attested observation state."""
    bos_token_id = 1
    eos_token_id = 2
    vocab_size = 259

    def __init__(self):
        self.byte_to_id = list(range(3, 259))
        self.frontend_config = {"normalizer": "identity", "cleanup": False}
        self.text_encoding = "utf-8"
        self.observation_state = {}

    @property
    def byte_token_ids(self):
        return self.byte_to_id

    def encode(self, text):
        if self.frontend_config["normalizer"] == "lowercase":
            text = text.lower()
        return [self.byte_to_id[value] for value in text.encode(self.text_encoding)]

    def decode(self, values):
        inverse = {token: value for value, token in enumerate(self.byte_to_id)}
        return bytes(inverse[value] for value in values).decode(self.text_encoding)

    def pipeline_serialization(self):
        return inputs._reviewed_decoder_fixed_byte_pipeline(self)


class _ReviewedDecoderLoadedByteTokenizer(_ReviewedDecoderByteTokenizer):
    """The maintained wrapper's kwargs transport, without importing a model."""
    def encode(self, text, *, add_special_tokens, truncation):
        assert add_special_tokens is False and truncation is False
        return _ReviewedDecoderByteTokenizer.encode(self, text)

    def decode(self, values, *, skip_special_tokens, clean_up_tokenization_spaces):
        assert skip_special_tokens is False and clean_up_tokenization_spaces is False
        return _ReviewedDecoderByteTokenizer.decode(self, values)


def _reviewed_decoder_add_unmapped_external_reference(data, unit_index):
    """Build a currently admitted fictional dependency, without inventing a fold map.

    Re-prepare the real admission declaration and re-sign its changed complete
    review subject. Staged target/exposure seals must include the external ref;
    a malformed or stale declaration would test a different, earlier refusal.
    """
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    case, helper, admission = data.case, data.helper, data.admission
    dependency_raw = b"Fictional versioned external dependency; no external unit/source/fold mapping."
    dependency_id = "fixture:unmapped-external-law"
    dependency_sha = helper.sha(dependency_raw)
    process_ref = {"artifact_id": helper.REVIEWED_PROCESS_ID,
                   "sha256": helper.sha(case["evidence"][helper.REVIEWED_PROCESS_ID])}
    reference = {"from_unit_id": case["declaration"]["units"][unit_index]["unit_id"],
        "dependency_artifact_id": dependency_id, "dependency_sha256": dependency_sha,
        "version": "fixture:unmapped-external-v1", "evidence_refs": [process_ref]}
    case["declaration"]["cross_references"] = [reference]
    case["evidence"][dependency_id] = dependency_raw
    helper.reviewed_refresh_manifest_v2(case)
    case["preparation"] = admission.prepare_reviewed_norm_admission_v2(
        case["declaration"], **helper.reviewed_prepare_arguments_v2(case))
    body = helper.norm._wire(case["declaration"])
    case["evidence"][case["declaration"]["component_id"]] = body
    for claim in case["reviews"]:
        claim["subject"] = data.deepcopy(case["preparation"]["subject"])
        claim["interpretation"]["reviewed_graph_sha256"] = case["preparation"]["subject"]["graph_sha256"]
        claim["interpretation"]["reviewed_ast_sha256"] = case["preparation"]["subject"]["ast_sha256"]
        for obligation in claim["context_closure"]["obligations"]:
            for evidence in obligation["evidence_refs"]:
                if evidence["artifact_id"] == case["declaration"]["component_id"]:
                    evidence["sha256"] = helper.sha(body)
    helper.reviewed_resign_v2(case)
    prepared = {unit["unit_id"]: unit for unit in case["preparation"]["units"]}
    for row in data.rows:
        row["canonical_ir"] = data.deepcopy(prepared[row["unit_id"]]["canonical_ir"])
    exposure = data.deepcopy(data.options["exposure_records"])
    for row, record in zip(data.rows, exposure, strict=True):
        assert record["id"] == row["id"]
        record["canonical_ir_sha256"] = data.fixtures.digest(row["canonical_ir"])
    current = data.fixtures.reviewed_public_admission_inputs(helper, admission, case)
    data.options.update(expected_rows_sha256=data.fixtures.digest(data.rows), admission_inputs=current,
        expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(current),
        exposure_records=exposure, expected_exposure_sha256=data.fixtures.digest(exposure))


def _reviewed_decoder_fixture(tmp_path, *, definition_only=False, third_component_assignment="train",
                              external_reference_unit_index=None,
                              known_interpretation_id="fixture:act-v1/selected-interpretation"):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    data = _reviewed_transition_fixture(tmp_path)
    if external_reference_unit_index is not None:
        _reviewed_decoder_add_unmapped_external_reference(data, external_reference_unit_index)
    if definition_only:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
        component = list(data.rows)
        included = component[:2] if third_component_assignment == "missing" else component
        # Deliberately no citation, lineage, dependency or source-span groups.
        # Distinct linked norm text must still be grouped by the new component
        # guard, rather than being treated as an unrelated held-out source.
        examples = tuple(splits.LegalIRSplitExample.from_sample({"id": row["id"], "text": row["source_text"]})
                         for row in included)
        assignments = {row["id"]: (third_component_assignment if index == 2 else "train")
                       for index, row in enumerate(included)}
        manifest = splits.LegalIRSplitManifest(examples=examples, assignments=assignments,
            config_digest=splits.LegalIREvalSplitConfig(**data.config).digest).to_dict()
        data.rows = component[:1]
        exposure = data.options["exposure_records"][:1]
        data.options.update(expected_rows_sha256=data.fixtures.digest(data.rows), split_manifest=manifest,
            expected_split_manifest_sha256=data.fixtures.digest(manifest), exposure_records=exposure,
            expected_exposure_sha256=data.fixtures.digest(exposure))
        data.history["records"] = [{"id": row["id"], "source_text": row["source_text"],
            "source_sha256": data.fixtures.source_digest(row["source_text"]),
            "split_example": example.to_dict(), "assignment": assignments[row["id"]]}
            for row, example in zip(included, examples, strict=True)]
    registry = _ReviewedArtifactRegistry(tmp_path / "decoder-registry")
    options = _reviewed_stage_options(data, tmp_path / "decoder-stage")
    artifact = inputs.stage_reviewed_cycle_inputs(registry, **options)
    # Author-selected caller input, not a default inferred from targets or reviews.
    contexts = {"profile": "reviewed-source-selection-context/v2",
        "selection_context": {"schema": "caller-known-interpretation-selection/v1",
            "interpretation_id": known_interpretation_id, "selection_mode": "identifier_only"}, "rows": [
        {"id": row["id"], "unit_id": row["unit_id"],
         "governing_context": data.deepcopy(row["canonical_ir"]["governing_context"]),
         "source_binding": data.deepcopy(row["canonical_ir"]["source_binding"])} for row in data.rows]}
    kwargs = dict(stage_artifact=artifact, expected_stage_sha256=artifact["sha256"],
        current_admission_inputs=options["admission_inputs"],
        expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(options["admission_inputs"]),
        exposure_records=options["exposure_records"], expected_exposure_sha256=data.fixtures.digest(options["exposure_records"]),
        source_contexts=contexts, expected_source_contexts_sha256=data.fixtures.digest(contexts),
        split_config=data.config, expected_split_config_sha256=data.fixtures.digest(data.config),
        tokenizer=_ReviewedDecoderByteTokenizer(), max_source_tokens=65536, max_target_tokens=65536,
        allow_fictional_fixture=True)
    return data, registry, artifact, kwargs


def _reviewed_decoder_put_json(registry, path, value):
    import hashlib
    raw = inputs._reviewed_wire(value)
    path.write_bytes(raw)
    stored = registry.stage_artifact(path, hashlib.sha256(raw).hexdigest())
    return dict(stored, path=str(registry.artifact_path(stored)))


def _reviewed_decoder_repin_stage(registry, tmp_path, kwargs, document):
    artifact = _reviewed_decoder_put_json(registry, tmp_path / "decoder-mutated-stage.json", document)
    kwargs.update(stage_artifact=artifact, expected_stage_sha256=artifact["sha256"])


def test_full_reviewed_decoder_preparation_retains_all_nine_fields_without_fitting_or_target_input(tmp_path):
    data, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    before = registry.stage_calls

    class ReadOnlyRegistry:
        def artifact_path(self, descriptor):
            return registry.artifact_path(descriptor)

        def read_artifact(self, descriptor, *, max_bytes):
            return registry.read_artifact(descriptor, max_bytes=max_bytes)

        def __getattr__(self, name):
            raise AssertionError("decoder input preparation attempted registry mutation: " + name)

    result = inputs.prepare_reviewed_decoder_training_inputs(ReadOnlyRegistry(), **kwargs)
    assert registry.stage_calls == before
    assert result["schema"] == "reviewed-decoder-training-inputs/v2"
    assert len(result["records"]) == len(data.rows)
    for row, record in zip(data.rows, result["records"], strict=True):
        assert set(record) == {"id", "unit_id", "source_wire", "target_json", "source_token_ids", "target_token_ids"}
        assert json.loads(record["target_json"]) == row["canonical_ir"]
        assert len(json.loads(record["target_json"])) == 9
        source = json.loads(record["source_wire"])
        assert set(source) == {"profile", "source_text", "governing_context", "source_binding", "selection_context"}
        assert source["selection_context"] == kwargs["source_contexts"]["selection_context"]
        assert result["receipt"]["semantic_selection_supported"] is False
        assert source["source_text"] == row["source_text"]
        assert not {"typed_expression", "argument_roles", "definition_uses", "target_json"}.intersection(source)
        for key, wire in (("source_token_ids", "source_wire"), ("target_token_ids", "target_json")):
            assert record[key][0] == 1 and record[key][-1] == 2
            assert kwargs["tokenizer"].decode(record[key][1:-1]) == record[wire]
    receipt = result["receipt"]
    assert receipt["target_codec"] == "complete-reviewed-norm-json/v1"
    assert receipt["training_record_ids"] == [row["id"] for row in data.rows]
    assert receipt["fixture_only"] is True and receipt["training_mask"] == 0
    assert receipt["production_training_eligible"] is False
    assert all(receipt[key] is False for key in ("backend_execution_authorized", "training_executed",
        "weights_updated", "proof_authority", "Lean_admitted", "corpus_admitted"))
    payload = {key: result[key] for key in ("schema", "records", "receipt")}
    import hashlib
    assert result["prepared_sha256"] == hashlib.sha256(inputs._reviewed_wire(payload)).hexdigest()


@pytest.mark.parametrize("field", ("profile", "typed_expression", "argument_roles", "assumptions",
    "governing_context", "interpretation_id", "source_binding", "definition_uses", "cross_references", "unknown"))
def test_full_reviewed_decoder_refuses_lossy_or_extended_target_even_if_artifacts_are_resealed(tmp_path, field):
    _, registry, artifact, kwargs = _reviewed_decoder_fixture(tmp_path)
    document = _reviewed_doc(registry, artifact)
    rows = _reviewed_doc(registry, document["rows_artifact"])
    if field == "unknown":
        rows[0]["canonical_ir"]["unsupported_extra"] = "not silently ignored"
    else:
        rows[0]["canonical_ir"].pop(field)
    document["rows_artifact"] = _reviewed_decoder_put_json(registry, tmp_path / "lossy-target-rows.json", rows)
    _reviewed_decoder_repin_stage(registry, tmp_path, kwargs, document)
    with pytest.raises(ValueError, match="full nine-field"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)


@pytest.mark.parametrize("field", ("typed_expression", "assumptions", "interpretation_id", "definition_uses"))
def test_full_reviewed_decoder_current_review_rejects_changed_values_in_a_complete_resealed_target(tmp_path, field):
    _, registry, artifact, kwargs = _reviewed_decoder_fixture(tmp_path)
    document = _reviewed_doc(registry, artifact)
    rows = _reviewed_doc(registry, document["rows_artifact"])
    target = rows[0]["canonical_ir"]
    if field == "typed_expression":
        target[field]["root"]["node_id"] = "changed-reference-node"
    elif field == "assumptions":
        target[field] = ["unreviewed premise"]
    elif field == "interpretation_id":
        target[field] += ":unreviewed"
    else:
        assert target[field]
        target[field] = []
    document["rows_artifact"] = _reviewed_decoder_put_json(registry, tmp_path / "changed-complete-target.json", rows)
    _reviewed_decoder_repin_stage(registry, tmp_path, kwargs, document)
    with pytest.raises(ValueError, match="complete row target differs"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)


@pytest.mark.parametrize("damage", ("formula", "roles", "definition_labels", "hidden_context", "wrong_edition", "wrong_profile"))
def test_full_reviewed_decoder_source_context_cannot_hide_reference_target_or_change_admitted_facts(tmp_path, damage):
    data, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    contexts = kwargs["source_contexts"]
    row = contexts["rows"][0]
    if damage in ("formula", "roles", "definition_labels"):
        key = {"formula": "typed_expression", "roles": "argument_roles", "definition_labels": "definition_uses"}[damage]
        row[key] = data.deepcopy(data.rows[0]["canonical_ir"][key])
    elif damage == "hidden_context":
        row["governing_context"]["reference_formula"] = data.rows[0]["canonical_ir"]["typed_expression"]
    elif damage == "wrong_edition":
        row["governing_context"]["governing_edition"] = "wrong-source-edition"
    else:
        contexts["profile"] = "implicit-rich-context"
    kwargs["expected_source_contexts_sha256"] = data.fixtures.digest(contexts)
    with pytest.raises(ValueError, match="source-known|source context"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)


@pytest.mark.parametrize("budget", ("max_source_tokens", "max_target_tokens"))
def test_full_reviewed_decoder_checks_entire_input_and_target_budgets_without_truncating(tmp_path, budget):
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    kwargs[budget] = 2
    with pytest.raises(ValueError, match="token budget exceeded; truncation forbidden"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)


@pytest.mark.parametrize("damage", ("truncated", "normalized", "special_body", "bool_token"))
def test_full_reviewed_decoder_rejects_lossy_or_ambiguous_tokenizer_transport(tmp_path, damage):
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)

    class DamagedTokenizer(_ReviewedDecoderByteTokenizer):
        def encode(self, text):
            body = super().encode(text)
            return body[:-1] if damage == "truncated" else [1, *body] if damage == "special_body" else [True, *body] if damage == "bool_token" else body

        def decode(self, values):
            value = super().decode(values)
            return value.replace('"profile"', '"PROFILE"') if damage == "normalized" else value

    kwargs["tokenizer"] = DamagedTokenizer()
    with pytest.raises(ValueError, match="roundtrip|body-only"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)


@pytest.mark.parametrize("phase", ("source", "target"))
def test_full_reviewed_decoder_snapshots_cached_token_list_before_decode_can_mutate_it(tmp_path, phase):
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)

    class CachedListMutationTokenizer(_ReviewedDecoderByteTokenizer):

        def encode(self, text):
            self.observation_state["cached_body"] = super().encode(text)
            self.observation_state["phase"] = "source" if "source_text" in json.loads(text) else "target"
            return self.observation_state["cached_body"]

        def decode(self, values):
            text = super().decode(values)
            if self.observation_state["phase"] == phase and self.observation_state.get("mutated_body") is None:
                self.observation_state["mutated_body"] = self.observation_state["cached_body"]
                self.observation_state["cached_body"][:] = [True, self.bos_token_id, -1, self.vocab_size]
            return text

    tokenizer = CachedListMutationTokenizer()
    kwargs["tokenizer"] = tokenizer
    result = inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert tokenizer.observation_state["mutated_body"] == [True, 1, -1, 259]
    independent_transport = _ReviewedDecoderByteTokenizer()
    for record in result["records"]:
        for key, wire, limit in (("source_token_ids", "source_wire", kwargs["max_source_tokens"]),
                                 ("target_token_ids", "target_json", kwargs["max_target_tokens"])):
            ids = record[key]
            assert ids[0] == 1 and ids[-1] == 2 and len(ids) <= limit
            assert all(type(value) is int and 3 <= value < 259 for value in ids[1:-1])
            assert independent_transport.decode(ids[1:-1]) == record[wire]


@pytest.mark.parametrize("assignment", ("holdout", "validation", "canary", "missing"))
def test_full_reviewed_decoder_groups_distinct_definition_and_linked_norm_component_before_tokenization(tmp_path, assignment):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    data, registry, artifact, kwargs = _reviewed_decoder_fixture(
        tmp_path, definition_only=True, third_component_assignment=assignment)
    document = _reviewed_doc(registry, artifact)
    assert document["consumer_receipt"]["status"] == "ready"
    manifest = splits.LegalIRSplitManifest.from_mapping(_reviewed_doc(registry, document["split_manifest_artifact"]))
    assert splits.validate_legal_ir_eval_splits(manifest).passed
    assert all(not item.citation_clusters and not item.source_span_key and not item.amendment_key
               and not item.lineage_group_id and not item.sibling_keys for item in manifest.examples)
    units = data.case["preparation"]["units"]
    assert len({unit["source_text"] for unit in units}) == 3
    assert any(use["use_unit_id"] == units[2]["unit_id"]
               for use in data.rows[0]["canonical_ir"]["definition_uses"])
    calls = []

    class MustNotTokenize(_ReviewedDecoderByteTokenizer):
        def encode(self, text):
            calls.append(text)
            pytest.fail("linked held-out or missing component reached tokenizer")

    kwargs["tokenizer"] = MustNotTokenize()
    with pytest.raises(ValueError, match="reviewed component"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert calls == []


def test_full_reviewed_decoder_can_train_definition_only_when_entire_linked_component_is_frozen_train(tmp_path):
    data, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path, definition_only=True)
    result = inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert len(result["records"]) == 1
    assert json.loads(result["records"][0]["target_json"]) == data.rows[0]["canonical_ir"]
    guard = result["receipt"]["component_split_guard"]
    assert guard["passed"] is True and guard["component_unit_count"] == 3
    assert all(unit["assignment"] == "train" for unit in guard["units"])
    assert guard["assignments_recomputed"] is guard["target_fields_discarded"] is False


@pytest.mark.parametrize("denial", ("unreviewed", "revoked", "fixture_not_allowed"))
def test_full_reviewed_decoder_replays_current_admission_instead_of_historical_ready_receipt(tmp_path, denial):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    data, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    if denial == "fixture_not_allowed":
        kwargs["allow_fictional_fixture"] = False
    else:
        if denial == "unreviewed":
            data.case["reviews"] = []
        else:
            data.case["registry"]["keys"][0]["revoked_at_utc"] = data.helper.EVALUATED
            data.helper.reviewed_resign_v2(data.case)
        current = data.fixtures.reviewed_public_admission_inputs(data.helper, data.admission, data.case)
        kwargs.update(current_admission_inputs=current,
            expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(current))
    with pytest.raises(ValueError):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)


@pytest.mark.parametrize("damage", ("missing_config", "narrowed_policy", "heldout_alias", "frozen_assignment_conflict"))
def test_full_reviewed_decoder_recomputes_fixed_cumulative_split_guards(tmp_path, damage):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    data, registry, artifact, kwargs = _reviewed_decoder_fixture(tmp_path)
    if damage == "missing_config":
        kwargs["split_config"] = None
        kwargs["expected_split_config_sha256"] = data.fixtures.digest(None)
        with pytest.raises(ValueError, match="complete split_config required"):
            inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
        return
    if damage == "narrowed_policy":
        kwargs["split_config"]["protected_splits"] = ["canary"]
        kwargs["expected_split_config_sha256"] = data.fixtures.digest(kwargs["split_config"])
        with pytest.raises(ValueError, match="protected profile"):
            inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
        return
    document = _reviewed_doc(registry, artifact)
    history = _reviewed_doc(registry, document["history_artifact"])
    options = {"split_manifest": _reviewed_doc(registry, document["split_manifest_artifact"]), "history": history}
    kind = "narrowed_policy" if damage == "heldout_alias" else "assignment_conflict"
    _append_reviewed_historical_guard(data, options, kind)
    document["history_artifact"] = _reviewed_decoder_put_json(registry, tmp_path / "leaking-decoder-history.json", history)
    _reviewed_decoder_repin_stage(registry, tmp_path, kwargs, document)
    with pytest.raises(splits.LegalIRSplitLeakageError):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)


def test_full_reviewed_decoder_does_not_pass_unrelated_heldout_history_to_tokenizer_or_records(tmp_path):
    data, registry, artifact, kwargs = _reviewed_decoder_fixture(tmp_path)
    document = _reviewed_doc(registry, artifact)
    history = _reviewed_doc(registry, document["history_artifact"])
    options = {"split_manifest": _reviewed_doc(registry, document["split_manifest_artifact"]), "history": history}
    _append_reviewed_historical_guard(data, options, "heldout_unrelated")
    heldout = next(row for row in history["records"] if row["assignment"] == "holdout")
    document["history_artifact"] = _reviewed_decoder_put_json(registry, tmp_path / "heldout-decoder-history.json", history)
    _reviewed_decoder_repin_stage(registry, tmp_path, kwargs, document)
    seen = []

    class ObservedTokenizer(_ReviewedDecoderByteTokenizer):
        def encode(self, text):
            seen.append(text)
            return super().encode(text)

    kwargs["tokenizer"] = ObservedTokenizer()
    result = inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert heldout["id"] not in result["receipt"]["training_record_ids"]
    assert not any(heldout["source_text"] in text for text in seen)
    assert len(seen) == 2 * len(data.rows)


def test_full_reviewed_decoder_replays_a_retained_successor_and_refuses_withdrawal_as_training(tmp_path):
    data, registry, artifact, kwargs = _reviewed_decoder_fixture(tmp_path)
    original = inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    options = _reviewed_stage_options(data, tmp_path / "decoder-successor")
    options = _reviewed_successor_options(data, options, registry, artifact, tmp_path / "decoder-successor")
    successor = inputs.stage_reviewed_cycle_inputs(registry, **options)
    kwargs.update(stage_artifact=successor, expected_stage_sha256=successor["sha256"])
    retained = inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert retained["records"] == original["records"]
    assert retained["receipt"]["stage_artifact_sha256"] != original["receipt"]["stage_artifact_sha256"]
    withdrawal = _reviewed_withdrawal_options(data, options, registry, successor, tmp_path / "decoder-withdrawal")
    withdrawn = inputs.stage_reviewed_cycle_inputs(registry, **withdrawal)
    kwargs.update(stage_artifact=withdrawn, expected_stage_sha256=withdrawn["sha256"])
    with pytest.raises(ValueError, match="positive complete reviewed stage profile required"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)


@pytest.mark.parametrize("mutation", ("context", "admission", "tokenizer", "artifact"))
def test_full_reviewed_decoder_refuses_inputs_or_registry_bytes_changed_during_tokenization(tmp_path, mutation):
    _, registry, artifact, kwargs = _reviewed_decoder_fixture(tmp_path)
    original_rows_ref = _reviewed_doc(registry, artifact)["rows_artifact"]

    class MutatingTokenizer(_ReviewedDecoderByteTokenizer):

        def encode(self, text):
            if not self.observation_state.get("changed"):
                self.observation_state["changed"] = True
                if mutation == "context":
                    kwargs["source_contexts"]["rows"][0]["source_binding"]["document_revision"] = "changed-during-tokenization"
                elif mutation == "admission":
                    kwargs["current_admission_inputs"]["reviews"].clear()
                elif mutation == "tokenizer":
                    self.vocab_size = 260
                else:
                    Path(original_rows_ref["path"]).write_bytes(b"changed registry body")
            return super().encode(text)

    kwargs["tokenizer"] = MutatingTokenizer()
    with pytest.raises((ValueError, AssertionError)):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)


@pytest.mark.parametrize("unit_index", (0, 2), ids=("selected-definition", "unselected-linked-norm"))
def test_full_reviewed_decoder_refuses_current_admitted_external_dependencies_before_tokenization(tmp_path, unit_index):
    data, registry, artifact, kwargs = _reviewed_decoder_fixture(
        tmp_path, definition_only=True, external_reference_unit_index=unit_index)
    document = _reviewed_doc(registry, artifact)
    assert document["consumer_receipt"]["status"] == "ready"
    assessment = data.admission.assess_reviewed_norm_admission_v2(**kwargs["current_admission_inputs"])
    assert assessment["semantic_use_eligible"] is True and assessment["blockers"] == []
    assert assessment["provenance_kind"] == "fictional_fixture"
    assert assessment["training_mask"] == assessment["evaluation_gold_mask"] == 0
    assert all(record["assignment"] == "train" for record in data.history["records"])
    units = assessment["units"]
    assert len(units) == 3 and len(data.rows) == 1
    assert units[unit_index]["canonical_ir"]["cross_references"] == data.case["declaration"]["cross_references"]
    if unit_index == 2:
        assert units[unit_index]["unit_id"] != data.rows[0]["unit_id"]
    staged_rows = _reviewed_doc(registry, document["rows_artifact"])
    assert staged_rows == data.rows
    assert len(staged_rows[0]["canonical_ir"]) == 9
    assert staged_rows[0]["canonical_ir"]["definition_uses"]
    # On the unselected unit, the active target has no external ref at all.
    # Dropping that unit from this batch must not bypass the component refusal.
    assert bool(staged_rows[0]["canonical_ir"]["cross_references"]) is (unit_index == 0)
    assert data.case["observed_artifacts"]["fixture:unmapped-external-law"] == (
        data.case["declaration"]["cross_references"][0]["dependency_sha256"])
    calls = []

    class MustNotTokenize(_ReviewedDecoderByteTokenizer):
        def encode(self, text):
            calls.append(text)
            pytest.fail("unsupported external dependency reached tokenizer")

    kwargs["tokenizer"] = MustNotTokenize()
    with pytest.raises(ValueError, match="unsupported external cross-reference source/frozen-split mapping"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert calls == []
    # Refusal preserves the complete target and the signed declaration.
    assert _reviewed_doc(registry, document["rows_artifact"]) == staged_rows
    assert data.case["declaration"]["cross_references"]


def test_full_reviewed_decoder_internal_definition_uses_remain_complete_without_external_scope_claim(tmp_path):
    data, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path, definition_only=True)
    assert all(not unit["canonical_ir"]["cross_references"] for unit in data.case["preparation"]["units"])
    result = inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert len(result["records"]) == 1
    target = json.loads(result["records"][0]["target_json"])
    assert target == data.rows[0]["canonical_ir"] and len(target) == 9
    assert len(target["definition_uses"]) == 2 and target["cross_references"] == []
    guard = result["receipt"]["component_split_guard"]
    assert guard["passed"] is True and guard["component_unit_count"] == 3
    assert guard["external_cross_reference_count"] == 0
    assert guard["external_cross_reference_mapping_supported"] is False
    assert guard["corpus_wide_dependency_isolation_proved"] is False
    assert guard["assignments_recomputed"] is guard["target_fields_discarded"] is False



def test_full_reviewed_decoder_binds_complete_live_tokenizer_pipeline_and_actual_implementation_files(tmp_path):
    import hashlib
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    tokenizer = kwargs["tokenizer"]
    raw = tokenizer.pipeline_serialization()
    pipeline = json.loads(raw)
    assert len(pipeline["backend"]["byte_to_id"]) == 256
    assert pipeline["backend"]["byte_to_id"] == list(range(3, 259))
    assert pipeline["frontend"]["encoding"] == "utf-8"
    for descriptor in pipeline["implementation"]:
        actual = Path(descriptor["path"]).read_bytes()
        assert descriptor["bytes"] == len(actual)
        assert descriptor["sha256"] == hashlib.sha256(actual).hexdigest()
    result = inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    contract = result["receipt"]["tokenizer_contract"]
    assert contract == {"schema": "reviewed-decoder-tokenizer-contract/v2", "bos_token_id": 1,
        "eos_token_id": 2, "vocab_size": 259, "pipeline_kind": "fictional_fixed_byte",
        "pipeline_sha256": hashlib.sha256(raw).hexdigest(), "pipeline_bytes": len(raw)}
    assert result["receipt"]["tokenizer_pipeline_identity_authenticated"] is False
    assert result["receipt"]["tokenizer_pipeline_serialization_verified"] is True
    assert result["receipt"]["tokenizer_implementation_file_pins_verified"] is True
    assert result["receipt"]["tokenizer_behavior_independently_attested"] is False
    assert result["receipt"]["fixture_only"] is True
    assert result["receipt"]["training_mask"] == 0
    assert result["receipt"]["tokenizer_assets_authenticated"] is False
    changed = _ReviewedDecoderByteTokenizer()
    changed.byte_token_ids[65], changed.byte_token_ids[66] = changed.byte_token_ids[66], changed.byte_token_ids[65]
    assert (changed.bos_token_id, changed.eos_token_id, changed.vocab_size) == (1, 2, 259)
    assert inputs._reviewed_decoder_tokenizer_contract(changed)["pipeline_sha256"] != contract["pipeline_sha256"]
    changed = _ReviewedDecoderByteTokenizer()
    changed.text_encoding = "utf8"
    assert inputs._reviewed_decoder_tokenizer_contract(changed)["pipeline_sha256"] != contract["pipeline_sha256"]


@pytest.mark.parametrize("mutation", ("mapping", "frontend"))
def test_full_reviewed_decoder_refuses_changed_pipeline_even_with_identical_three_token_ids(tmp_path, mutation):
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)

    class ChangedPipelineTokenizer(_ReviewedDecoderByteTokenizer):

        def decode(self, values):
            text = super().decode(values)
            if not self.observation_state.get("changed"):
                self.observation_state["changed"] = True
                if mutation == "mapping":
                    self.byte_token_ids[65], self.byte_token_ids[66] = self.byte_token_ids[66], self.byte_token_ids[65]
                else:
                    self.text_encoding = "utf8"
            return text

    tokenizer = ChangedPipelineTokenizer()
    kwargs["tokenizer"] = tokenizer
    with pytest.raises(ValueError, match="tokenizer contract changed"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert (tokenizer.bos_token_id, tokenizer.eos_token_id, tokenizer.vocab_size) == (1, 2, 259)


@pytest.mark.parametrize("field", ("bos_token_id", "eos_token_id", "vocab_size"))
def test_full_reviewed_decoder_rechecks_three_token_ids_after_pipeline_getter(tmp_path, field):
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    encoded = []

    class GetterMutatesIds(_ReviewedDecoderByteTokenizer):
        def pipeline_serialization(self):
            raw = super().pipeline_serialization()
            setattr(self, field, 260 if field == "vocab_size" else 0)
            return raw

        def encode(self, text):
            encoded.append(text)
            pytest.fail("pipeline getter changed token IDs before tokenization")

    kwargs["tokenizer"] = GetterMutatesIds()
    with pytest.raises(ValueError, match="IDs changed during pipeline serialization"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert encoded == []


@pytest.mark.parametrize("damage", ("missing", "opaque_hash", "mutable_bytes", "noncanonical", "duplicate_key",
                                    "empty_implementation", "transport_truncation", "unknown_field"))
def test_full_reviewed_decoder_refuses_opaque_or_incomplete_tokenizer_pipeline_before_encoding(tmp_path, damage):
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    encoded = []

    class UnsupportedPipelineTokenizer(_ReviewedDecoderByteTokenizer):
        def pipeline_serialization(self):
            raw = super().pipeline_serialization()
            if damage == "opaque_hash":
                return {"pipeline_sha256": "a" * 64}
            if damage == "mutable_bytes":
                return bytearray(raw)
            if damage == "noncanonical":
                return raw + b" "
            if damage == "duplicate_key":
                return b'{"schema":"reviewed-decoder-tokenizer-pipeline/v1",' + raw[1:]
            pipeline = json.loads(raw)
            if damage == "empty_implementation":
                pipeline["implementation"] = []
            elif damage == "transport_truncation":
                pipeline["transport"]["truncation"] = True
            elif damage == "unknown_field":
                pipeline["opaque_commitment"] = "not a complete actual pipeline"
            return inputs._reviewed_wire(pipeline)

        def encode(self, text):
            encoded.append(text)
            pytest.fail("unsupported tokenizer pipeline reached encode")

    tokenizer = UnsupportedPipelineTokenizer()
    if damage == "missing":
        tokenizer.pipeline_serialization = None
    kwargs["tokenizer"] = tokenizer
    with pytest.raises(ValueError):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert encoded == []


def test_full_reviewed_decoder_refuses_pipeline_serialization_changed_between_contract_checks(tmp_path):
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)

    class ChangingSerializationTokenizer(_ReviewedDecoderByteTokenizer):

        def pipeline_serialization(self):
            self.observation_state["serializations"] = self.observation_state.get("serializations", 0) + 1
            self.text_encoding = "utf-8" if self.observation_state["serializations"] % 2 else "utf8"
            return super().pipeline_serialization()

    tokenizer = ChangingSerializationTokenizer()
    kwargs["tokenizer"] = tokenizer
    with pytest.raises(ValueError, match="tokenizer contract changed"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert tokenizer.observation_state["serializations"] >= 2


def test_full_reviewed_decoder_rechecks_pipeline_after_real_current_admission_replay(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)

    class ObservedTokenizer(_ReviewedDecoderByteTokenizer):

        def decode(self, values):
            self.observation_state["tokenization_entered"] = True
            return super().decode(values)

    tokenizer = ObservedTokenizer()
    actual_validate = consumer.validate_reviewed_source_span_consumer_binding_v2

    def validate_then_change_frontend(*args, **options):
        receipt = actual_validate(*args, **options)
        if tokenizer.observation_state.get("tokenization_entered"):
            tokenizer.text_encoding = "utf8"
        return receipt

    monkeypatch.setattr(consumer, "validate_reviewed_source_span_consumer_binding_v2", validate_then_change_frontend)
    kwargs["tokenizer"] = tokenizer
    with pytest.raises(ValueError, match="tokenizer contract changed after current admission replay"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)


def test_full_reviewed_decoder_refuses_actual_implementation_source_changed_after_serialization(tmp_path):
    import hashlib
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    source = tmp_path / "untrusted-extra-tokenizer-implementation.py"
    source.write_bytes(b"def declared_implementation(): return 1\n")
    encoded = []

    class StaleImplementationTokenizer(_ReviewedDecoderByteTokenizer):
        def pipeline_serialization(self):
            pipeline = json.loads(super().pipeline_serialization())
            raw = source.read_bytes()
            # An offered extra implementation descriptor cannot authorize even
            # its own now-changed bytes; it is not canonical product code.
            pipeline["implementation"].append({"path": str(source), "bytes": len(raw),
                                                "sha256": hashlib.sha256(raw).hexdigest()})
            source.write_bytes(b"def declared_implementation(): return 2\n")
            return inputs._reviewed_wire(pipeline)

        def encode(self, text):
            encoded.append(text)
            pytest.fail("changed implementation source reached tokenizer encode")

    kwargs["tokenizer"] = StaleImplementationTokenizer()
    with pytest.raises(ValueError, match="tokenizer implementation SourceChanged"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert encoded == []


def test_full_reviewed_decoder_refuses_huggingface_pipeline_without_exact_maintained_wrapper(tmp_path):
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    encoded = []

    class OpaqueProductionTokenizer(_ReviewedDecoderByteTokenizer):
        def pipeline_serialization(self):
            pipeline = json.loads(super().pipeline_serialization())
            pipeline["kind"] = "huggingface_fast"
            return inputs._reviewed_wire(pipeline)

        def encode(self, text):
            encoded.append(text)
            pytest.fail("opaque production tokenizer reached encode")

    kwargs["tokenizer"] = OpaqueProductionTokenizer()
    with pytest.raises(ValueError, match="exact maintained ReviewedPretrainedTokenizer"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert encoded == []


@pytest.mark.parametrize("damage", ("missing_selection", "missing_id", "wrong_caller_id", "empty_id",
                                    "meaning_policy_mode", "reference_label_field", "historical_v1"))
def test_full_reviewed_decoder_requires_caller_known_v2_selector_without_filling_from_reference(tmp_path, damage):
    data, registry, artifact, kwargs = _reviewed_decoder_fixture(tmp_path)
    assert _reviewed_doc(registry, artifact)["consumer_receipt"]["status"] == "ready"
    original_targets = data.deepcopy(data.rows)
    context = kwargs["source_contexts"]
    if damage == "missing_selection":
        context.pop("selection_context")
    elif damage == "missing_id":
        context["selection_context"].pop("interpretation_id")
    elif damage == "wrong_caller_id":
        context["selection_context"]["interpretation_id"] = "fixture:caller-known-other-interpretation"
    elif damage == "empty_id":
        context["selection_context"]["interpretation_id"] = ""
    elif damage == "meaning_policy_mode":
        context["selection_context"]["selection_mode"] = "automatic_meaning_resolution"
    elif damage == "reference_label_field":
        context["selection_context"]["reference_target"] = data.deepcopy(data.rows[0]["canonical_ir"])
    else:
        context["profile"] = "reviewed-source-known-context/v1"
        context.pop("selection_context")
    kwargs["expected_source_contexts_sha256"] = data.fixtures.digest(context)
    serializations = []

    class MustNotSerialize(_ReviewedDecoderByteTokenizer):
        def pipeline_serialization(self):
            serializations.append(True)
            pytest.fail("missing/wrong/unprovided selection reached tokenizer identity or encoding")

    kwargs["tokenizer"] = MustNotSerialize()
    with pytest.raises(ValueError, match="selection|source-known"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert serializations == []
    assert data.rows == original_targets
    if damage == "wrong_caller_id":
        assert context["selection_context"]["interpretation_id"] == "fixture:caller-known-other-interpretation"


@pytest.mark.parametrize("damage", ("target_id", "definition_use_id", "missing_definition_use_id"))
def test_full_reviewed_decoder_rejects_reference_interpretation_mismatch_without_rekeying_caller(tmp_path, damage):
    data, registry, artifact, kwargs = _reviewed_decoder_fixture(tmp_path)
    document = _reviewed_doc(registry, artifact)
    rows = _reviewed_doc(registry, document["rows_artifact"])
    if damage == "target_id":
        rows[0]["canonical_ir"]["interpretation_id"] = "fixture:changed-reference-interpretation"
    elif damage == "definition_use_id":
        rows[0]["canonical_ir"]["definition_uses"][0]["interpretation_id"] = "fixture:changed-reference-interpretation"
    else:
        rows[0]["canonical_ir"]["definition_uses"][0].pop("interpretation_id")
    selection = data.deepcopy(kwargs["source_contexts"]["selection_context"])
    with pytest.raises(ValueError, match="interpretation"):
        inputs._reviewed_decoder_source_target_wires(rows, kwargs["source_contexts"]["rows"], selection)
    # A fresh transport seal is not a fresh complete reviewed meaning target.
    document["rows_artifact"] = _reviewed_decoder_put_json(registry, tmp_path / "changed-interpretation-rows.json", rows)
    _reviewed_decoder_repin_stage(registry, tmp_path, kwargs, document)
    kwargs["exposure_records"][0]["canonical_ir_sha256"] = data.fixtures.digest(rows[0]["canonical_ir"])
    kwargs["expected_exposure_sha256"] = data.fixtures.digest(kwargs["exposure_records"])
    serialized = []

    class MustNotSerialize(_ReviewedDecoderByteTokenizer):
        def pipeline_serialization(self):
            serialized.append(True)
            pytest.fail("changed reference target reached tokenizer")

    kwargs["tokenizer"] = MustNotSerialize()
    with pytest.raises(ValueError):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert serialized == []
    assert kwargs["source_contexts"]["selection_context"] == selection
    assert selection["interpretation_id"] == "fixture:act-v1/selected-interpretation"


def test_full_reviewed_decoder_caller_rekey_is_an_independent_input_and_never_gold_fill(tmp_path):
    known = "fixture:caller-explicitly-selected-unavailable-interpretation"
    data, registry, artifact, kwargs = _reviewed_decoder_fixture(tmp_path, known_interpretation_id=known)
    assert _reviewed_doc(registry, artifact)["consumer_receipt"]["status"] == "ready"
    assert kwargs["source_contexts"]["selection_context"]["interpretation_id"] == known
    targets = data.deepcopy(data.rows)
    assert targets[0]["canonical_ir"]["interpretation_id"] == "fixture:act-v1/selected-interpretation"
    with pytest.raises(ValueError, match="caller-known interpretation selection differs"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert data.rows == targets
    assert kwargs["source_contexts"]["selection_context"]["interpretation_id"] == known


def test_full_reviewed_decoder_identifier_only_context_is_explicitly_not_meaning_resolution(tmp_path):
    data, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    result = inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert result["schema"] == "reviewed-decoder-training-inputs/v2"
    receipt = result["receipt"]
    assert receipt["schema"] == "reviewed-decoder-training-input-receipt/v2"
    assert receipt["target_codec"] == "complete-reviewed-norm-json/v2"
    assert receipt["source_profile"] == "reviewed-source-selection-context/v2"
    assert receipt["semantic_selection_supported"] is False
    assert receipt["identifier_equality_is_meaning_resolution"] is False
    assert receipt["meaning_policy_route"] == "UNPROVIDED/unsupported"
    assert receipt["admitted_multi_target_relation"] is False
    assert receipt["historical_complete_input_target_relation_proved"] is False
    assert receipt["custody_hash_difference_is_semantic_incompatibility"] is False
    custody = receipt["current_admission_custody"]
    assert custody["review_subject_full_unit_records_sha256"] == data.case["preparation"]["subject"]["ast_sha256"]
    assert custody["review_subject_ast_label_is_pure_typed_expression"] is False
    for record, row, commitment in zip(result["records"], data.rows, receipt["row_commitments"], strict=True):
        source = json.loads(record["source_wire"])
        assert set(source) == {"profile", "source_text", "governing_context", "source_binding", "selection_context"}
        assert source["selection_context"] == kwargs["source_contexts"]["selection_context"]
        assert json.loads(record["target_json"]) == row["canonical_ir"]
        assert commitment["target_identities"]["full_nine_field_target_sha256"] == commitment["canonical_ir_sha256"]
    assert inputs.REVIEWED_DECODER_SOURCE_PROFILE_V1 == "reviewed-source-known-context/v1"
    assert inputs.REVIEWED_DECODER_TARGET_CODEC_V1 == "complete-reviewed-norm-json/v1"


@pytest.mark.parametrize("facet", ("interpretation", "source_binding", "governing_context", "definition_evidence"))
def test_full_reviewed_decoder_typed_ast_identity_stays_separate_from_full_record_custody_drift(tmp_path, facet):
    data, _, _, _ = _reviewed_decoder_fixture(tmp_path)
    original = data.rows[0]["canonical_ir"]
    changed = data.deepcopy(original)
    if facet == "interpretation":
        changed["interpretation_id"] += ":different-id"
    elif facet == "source_binding":
        changed["source_binding"]["document_revision"] += ":new-custody"
    elif facet == "governing_context":
        changed["governing_context"]["governing_edition"] += ":different-context"
    else:
        changed["definition_uses"][0]["evidence_refs"][0]["sha256"] = "0" * 64
    before = inputs._reviewed_decoder_target_identities(original)
    after = inputs._reviewed_decoder_target_identities(changed)
    assert before["pure_typed_expression_sha256"] == after["pure_typed_expression_sha256"]
    assert before["ordered_argument_roles_sha256"] == after["ordered_argument_roles_sha256"]
    assert before["assumptions_sha256"] == after["assumptions_sha256"]
    assert before["local_facets_sha256"] == after["local_facets_sha256"]
    assert before["full_nine_field_target_sha256"] != after["full_nine_field_target_sha256"]
    assert before["semantic_equivalence_or_incompatibility_proved"] is after["semantic_equivalence_or_incompatibility_proved"] is False
    if facet == "definition_evidence":
        assert before["dependency_custody_sha256"] != after["dependency_custody_sha256"]


def test_full_reviewed_decoder_refuses_one_complete_input_with_different_full_targets_without_semantic_claim(tmp_path):
    data, _, _, kwargs = _reviewed_decoder_fixture(tmp_path, definition_only=True)
    row = data.deepcopy(data.rows[0])
    different = data.deepcopy(row)
    different["id"] += ":untrusted-second-record"
    different["canonical_ir"]["definition_uses"][0]["evidence_refs"][0]["sha256"] = "0" * 64
    contexts = [kwargs["source_contexts"]["rows"][0]] * 2
    selection = kwargs["source_contexts"]["selection_context"]
    assert inputs._reviewed_decoder_target_identities(row["canonical_ir"])["pure_typed_expression_sha256"] == (
        inputs._reviewed_decoder_target_identities(different["canonical_ir"])["pure_typed_expression_sha256"])
    with pytest.raises(ValueError, match="unsupported conflicting full-target relation.*no admitted multi-target policy"):
        inputs._reviewed_decoder_source_target_wires([row, different], contexts, selection)
    # Predicate-only control: identical full target is functional. This confers
    # no admission on a duplicate row or on the changed custody record above.
    same = data.deepcopy(row)
    same["id"] += ":same-target-control"
    wires = inputs._reviewed_decoder_source_target_wires([row, same], contexts, selection)
    assert len(wires) == 2 and wires[0] == wires[1]
    assert len(json.loads(wires[0][1])) == 9


@pytest.mark.parametrize("mutation", ("none", "source_contexts", "admission", "registry"))
def test_full_reviewed_decoder_closes_all_inputs_after_identical_third_serialization_callback(tmp_path, mutation):
    data, registry, artifact, kwargs = _reviewed_decoder_fixture(tmp_path)
    rows_reference = _reviewed_doc(registry, artifact)["rows_artifact"]
    serialized = []

    class ThirdSerializationMutation(_ReviewedDecoderByteTokenizer):
        def pipeline_serialization(self):
            self.observation_state["serializations"] = self.observation_state.get("serializations", 0) + 1
            raw = super().pipeline_serialization()
            serialized.append(raw)
            if self.observation_state["serializations"] == 3:
                if mutation == "source_contexts":
                    kwargs["source_contexts"]["selection_context"]["interpretation_id"] = "fixture:changed-after-all-tokenization"
                elif mutation == "admission":
                    kwargs["current_admission_inputs"]["reviews"].clear()
                elif mutation == "registry":
                    Path(rows_reference["path"]).write_bytes(b"changed-on-third-serializer")
            return raw

    tokenizer = ThirdSerializationMutation()
    kwargs["tokenizer"] = tokenizer
    if mutation == "none":
        result = inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
        assert result["receipt"]["record_count"] == len(data.rows)
        assert result["receipt"]["tokenizer_behavior_independently_attested"] is False
    else:
        with pytest.raises((ValueError, AssertionError)):
            inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert tokenizer.observation_state["serializations"] == 3
    assert len(serialized) == 3 and serialized[0] == serialized[1] == serialized[2]


@pytest.mark.parametrize("damage", ("opaque_backend", "partial_mapping", "duplicate_mapping", "bos_mapping",
                                    "eos_mapping", "out_of_range_mapping", "bool_mapping", "opaque_frontend",
                                    "missing_config", "forged_method", "unencoded_instance_setting", "unencoded_class_setting"))
def test_full_reviewed_decoder_refuses_incomplete_fixed_byte_mapping_or_unencoded_config_before_encoding(tmp_path, damage):
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    entered = []

    class InvalidFixedBytePipeline(_ReviewedDecoderByteTokenizer):
        def pipeline_serialization(self):
            pipeline = json.loads(super().pipeline_serialization())
            if damage == "opaque_backend":
                pipeline["backend"] = {"opaque_sha256": "a" * 64}
            elif damage == "partial_mapping":
                pipeline["backend"]["byte_to_id"].pop()
            elif damage == "duplicate_mapping":
                pipeline["backend"]["byte_to_id"][-1] = pipeline["backend"]["byte_to_id"][0]
            elif damage in {"bos_mapping", "eos_mapping", "out_of_range_mapping", "bool_mapping"}:
                pipeline["backend"]["byte_to_id"][0] = (
                    self.bos_token_id if damage == "bos_mapping" else self.eos_token_id if damage == "eos_mapping"
                    else self.vocab_size if damage == "out_of_range_mapping" else True)
            elif damage == "opaque_frontend":
                pipeline["frontend"] = {"opaque_sha256": "b" * 64}
            elif damage == "missing_config":
                pipeline["frontend"].pop("configuration")
            elif damage == "forged_method":
                pipeline["frontend"]["methods"]["encode"]["code_sha256"] = "0" * 64
            return inputs._reviewed_wire(pipeline)

        def encode(self, text):
            entered.append(text)
            pytest.fail("incomplete/unencoded fictional pipeline reached encode")

    tokenizer = InvalidFixedBytePipeline()
    if damage == "unencoded_instance_setting":
        tokenizer.unencoded_normalizer = "lowercase"
    elif damage == "unencoded_class_setting":
        InvalidFixedBytePipeline.unencoded_normalizer = "lowercase"
    kwargs["tokenizer"] = tokenizer
    with pytest.raises(ValueError):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert entered == []


@pytest.mark.parametrize("transport", ("direct_worker_fixture", "maintained_wrapped_fixture"))
def test_full_reviewed_decoder_accepts_both_maintained_complete_fixed_byte_fixture_envelopes(tmp_path, transport):
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_worker import _CompleteReviewedByteTokenizer
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    if transport == "direct_worker_fixture":
        tokenizer = _CompleteReviewedByteTokenizer()
    else:
        delegate = _ReviewedDecoderLoadedByteTokenizer()
        tokenizer = worker.ReviewedPretrainedTokenizer(delegate, bos_token_id=delegate.bos_token_id,
            eos_token_id=delegate.eos_token_id, vocab_size=delegate.vocab_size, allow_fictional_fixture=True)
    kwargs["tokenizer"] = tokenizer
    result = inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    receipt = result["receipt"]
    assert receipt["tokenizer_contract"]["pipeline_kind"] == "fictional_fixed_byte"
    assert receipt["tokenizer_pipeline_serialization_verified"] is True
    assert receipt["tokenizer_implementation_file_pins_verified"] is True
    assert receipt["tokenizer_pipeline_identity_authenticated"] is False
    assert receipt["tokenizer_behavior_independently_attested"] is False
    assert receipt["fixture_only"] is True and receipt["training_mask"] == 0
    for record in result["records"]:
        for tokens, text in (("source_token_ids", "source_wire"), ("target_token_ids", "target_json")):
            assert tokenizer.decode(record[tokens][1:-1]) == record[text]


@pytest.mark.parametrize("fictional_wrapper", (False, True), ids=("opaque-production-wrapper", "opaque-fictional-wrapper"))
def test_full_reviewed_decoder_refuses_instance_shadow_before_opaque_wrapper_getter_or_encoding(tmp_path, fictional_wrapper):
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    delegate = _ReviewedDecoderLoadedByteTokenizer()
    if fictional_wrapper:
        tokenizer = worker.ReviewedPretrainedTokenizer(delegate, bos_token_id=delegate.bos_token_id,
            eos_token_id=delegate.eos_token_id, vocab_size=delegate.vocab_size, allow_fictional_fixture=True)
    else:
        # An invalid object may bypass its constructor. Its nominal exact class
        # must not make a shadow getter an actual maintained production pipeline.
        tokenizer = object.__new__(worker.ReviewedPretrainedTokenizer)
        tokenizer.tokenizer = object()
        tokenizer.bos_token_id, tokenizer.eos_token_id, tokenizer.vocab_size = 1, 2, 259
        tokenizer.allow_fictional_fixture = False
    opaque = json.loads(delegate.pipeline_serialization())
    opaque["kind"] = "huggingface_fast"
    opaque["backend"] = {"opaque_sha256": "a" * 64}
    opaque["frontend"] = {"opaque_sha256": "b" * 64}
    raw = inputs._reviewed_wire(opaque)
    entered = []

    def shadowed_getter():
        entered.append("opaque_getter")
        return raw

    def shadowed_encode(text):
        entered.append("encode")
        pytest.fail("shadowed wrapper reached encode")

    tokenizer.pipeline_serialization = shadowed_getter
    tokenizer.encode = shadowed_encode
    kwargs["tokenizer"] = tokenizer
    with pytest.raises(worker.TrainingJobValidationError, match="exact unshadowed reviewed tokenizer wrapper"):
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert entered == []



def test_full_reviewed_decoder_known_configuration_validation_has_explicit_typed_boundary(tmp_path):
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    kwargs["tokenizer"].frontend_config["cleanup"] = True
    with pytest.raises(inputs.ReviewedDecoderInputValidationError,
                       match="supported explicit fixed-byte normalization/cleanup options required") as caught:
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert type(caught.value) is inputs.ReviewedDecoderInputValidationError
    assert isinstance(caught.value, ValueError)
    # The original staging helper remains a different, unchanged boundary.
    with pytest.raises(ValueError) as legacy:
        inputs._reviewed_need(False, "unchanged legacy staging validation")
    assert type(legacy.value) is ValueError


@pytest.mark.parametrize("callback", ("serializer", "registry", "current_admission"))
def test_full_reviewed_decoder_foreign_callback_valueerror_keeps_original_identity(tmp_path, monkeypatch, callback):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    _, registry, _, kwargs = _reviewed_decoder_fixture(tmp_path)
    foreign = ValueError("operational callback error; not a decoder validation")

    if callback == "serializer":
        class ForeignSerializer(_ReviewedDecoderByteTokenizer):
            def pipeline_serialization(self):
                raise foreign
        kwargs["tokenizer"] = ForeignSerializer()
    elif callback == "registry":
        actual_registry = registry
        class ForeignRegistry:
            def artifact_path(self, descriptor):
                return actual_registry.artifact_path(descriptor)
            def read_artifact(self, descriptor, *, max_bytes):
                raise foreign
        registry = ForeignRegistry()
    else:
        def foreign_current_admission(*args, **options):
            raise foreign
        monkeypatch.setattr(consumer, "validate_reviewed_source_span_consumer_binding_v2", foreign_current_admission)
    with pytest.raises(ValueError) as caught:
        inputs.prepare_reviewed_decoder_training_inputs(registry, **kwargs)
    assert caught.value is foreign
    assert type(caught.value) is ValueError
    assert not isinstance(caught.value, inputs.ReviewedDecoderInputValidationError)
