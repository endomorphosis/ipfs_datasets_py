"""Corpus boundary tests use fake native execution, never publish Lake evidence."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import training_readiness as subject
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef


class FakeExecution:
    def __init__(self, report):
        self.report = deepcopy(report)
        self.valid = True


@pytest.fixture
def native_double(monkeypatch):
    def text(inputs):
        return inputs["ui_training_row"]["source"] if "ui_training_row" in inputs else inputs["source_text"]
    def validate(report, **inputs):
        assert report["fixture_scope"] == "readiness_unit_accounting_not_native_execution"
        if inputs and subject._sha(text(inputs).encode()) != report["source_digest"]:
            raise ValueError("exact source and target replay differs")
    def verify(execution, report):
        if type(execution) is not FakeExecution or not execution.valid or execution.report != report:
            raise ValueError("missing matching live execution")
        return {"per_projection": [{"projection_id": row["projection_id"], "logic_family": row["logic_family"],
            "profile": row["profile"], "payload_sha256": subject.policy._sha(row["payload"]),
            "source_digest": report["source_digest"], "parser_status": "passed", "lake_status": "passed",
            "semantic_lowering_supported": True, "lowering": {"capability_floor_eligible": True}}
            for row in report["projections"]]}
    def source_ref(domain, **inputs):
        sha = subject._sha(text(inputs).encode())
        return SourceRef(ref_id="source:" + sha, source_uri="fixture://" + sha,
            source_id="fixture", source_revision="unit-v1", content_sha256=sha)
    monkeypatch.setattr(subject.targets, "validate_family_training_report_v7", validate)
    monkeypatch.setattr(subject.policy, "_validate_report", validate)
    monkeypatch.setattr(subject.policy, "_verify_execution", verify)
    monkeypatch.setattr(subject.source_owner, "_source_bytes", lambda domain, inputs:
        (text(inputs).encode(), "unit_fixture", None))
    monkeypatch.setattr(subject.source_owner, "supplemental_source_ref", source_ref)


def panel(domain="security_ir", *, missing_reviews=False):
    result, executions = [], []
    for split in ("train", "validation"):
        source = split + " unique source text"
        policy = subject.policy.domain_projection_policy(domain)
        report = {"schema": subject.targets.SCHEMA, "domain_id": domain,
            "source_digest": subject._sha(source.encode()), "requested_families": policy["family_inventory"],
            "fixture_scope": "readiness_unit_accounting_not_native_execution", "projections": []}
        for index, floor in enumerate(policy["minimum_batch_floor"]):
            identity = (domain + "/native_formula/" + floor["requirement_id"] + "/v3" if domain == "legal_ir"
                else domain + "/fixture/" + str(index))
            target = {"projection_id": identity, "logic_family": floor["family_id"], "profile": floor["profile"],
                "payload": {"unit": index}, "ready_for_training": True}
            target["target_sha256"] = subject._digest(target)
            report["projections"].append(target)
        emitted = {row["logic_family"] for row in report["projections"]}
        reviews = [] if missing_reviews else [{"family_id": family, "source_digest": report["source_digest"],
            "disposition": "inapplicable", "reason": "Explicit unit accounting fixture only.",
            "evidence_refs": ["unit:authored-scope"]} for family in policy["family_inventory"] if family not in emitted]
        execution = FakeExecution(report)
        observation = subject.policy.validate_projection_report(report, lake_execution=execution,
            applicability_review=reviews)
        result.append({"id": split + "-row", "document_id": split + "-document", "group_id": split + "-group",
            "split": split, "source_inputs": {"ui_training_row": {"source": source}} if domain == "ui_ux_ir"
                else {"source_text": source}, "observation": observation})
        executions.append(execution)
    return result, executions


@pytest.mark.parametrize("domain", subject.transfer.DOMAINS)
def test_all_domains_join_live_targets_without_embeddings_or_source_authority(native_double, domain):
    rows, _ = panel(domain)
    handle = subject.prepare_validated_projection_corpus(domain, rows)
    manifest = subject.validate_prepared_projection_corpus(handle)
    assert manifest["strict_structural_training_allowed"]
    assert not manifest["embedding_required_for_structural_objective"]
    assert manifest["ordered_bindings"]["train"][0]["id"] == "train-row"
    assert manifest["ordered_bindings"]["validation"][0]["id"] == "validation-row"
    assert all(manifest[key] is False for key in subject._FALSE)
    manifest["ordered_bindings"]["train"].clear()
    assert handle.to_dict()["ordered_bindings"]["train"]


@pytest.mark.parametrize("split", ["test", "canary", "tuning", "", None])
def test_heldout_or_unknown_splits_cannot_fit(native_double, split):
    rows, _ = panel()
    rows[-1]["split"] = split
    with pytest.raises(ValueError, match="only train and validation"):
        subject.prepare_validated_projection_corpus("security_ir", rows)


@pytest.mark.parametrize("key", ["id", "document_id", "group_id"])
def test_declared_group_document_and_identity_leakage_blocks(native_double, key):
    rows, _ = panel()
    rows[1][key] = rows[0][key]
    with pytest.raises(ValueError, match="unique ordered|leakage"):
        subject.prepare_validated_projection_corpus("security_ir", rows)


def test_same_source_cannot_bypass_grouping_with_different_names(native_double):
    rows, _ = panel()
    rows[1]["source_inputs"] = rows[0]["source_inputs"]
    rows[1]["observation"] = rows[0]["observation"]
    with pytest.raises(ValueError, match="source_sha256 leakage"):
        subject.prepare_validated_projection_corpus("security_ir", rows)


def test_normalized_source_overlap_rejected(native_double):
    rows, executions = panel()
    source = "  TRAIN unique source  TEXT "
    report = executions[1].report
    report["source_digest"] = subject._sha(source.encode())
    rows[1]["source_inputs"]["source_text"] = source
    rows[1]["observation"] = subject.policy.validate_projection_report(report, lake_execution=FakeExecution(report))
    with pytest.raises(ValueError, match="normalized_source_sha256 leakage"):
        subject.prepare_validated_projection_corpus("security_ir", rows)


def test_projection_cannot_be_joined_to_unrelated_source(native_double):
    rows, _ = panel()
    rows[0]["source_inputs"]["source_text"] = "different input"
    with pytest.raises(ValueError, match="exact source and target"):
        subject.prepare_validated_projection_corpus("security_ir", rows)


def test_ui_arbitrary_text_cannot_override_canonical_row_identity(native_double):
    rows, _ = panel("ui_ux_ir")
    rows[0]["source_inputs"]["source_text"] = "plausible but unrelated text"
    with pytest.raises(ValueError, match="arbitrary source_text overrides"):
        subject.prepare_validated_projection_corpus("ui_ux_ir", rows)


def test_missing_reviews_remain_blockers_and_training_does_not_start(native_double, monkeypatch, tmp_path):
    rows, _ = panel(missing_reviews=True)
    handle = subject.prepare_validated_projection_corpus("security_ir", rows)
    assert not handle.to_dict()["strict_structural_training_allowed"]
    with pytest.raises(subject.CorpusReadinessError) as caught:
        subject.train_prepared_projection_corpus(handle, output_dir=tmp_path / "should-not-exist")
    assert caught.value.to_dict()["native_validation"]["train"]["source_observations"][0]["family_blockers"]
    assert not (tmp_path / "should-not-exist").exists()


def test_serialized_observation_and_unissued_handle_rejected(native_double):
    rows, _ = panel()
    handle = subject.prepare_validated_projection_corpus("security_ir", rows)
    with pytest.raises(ValueError, match="issued live prepared"):
        subject.validate_prepared_projection_corpus(subject.PreparedProjectionCorpus(handle._bytes))
    with pytest.raises(ValueError, match="issued live prepared"):
        subject.validate_prepared_projection_corpus(handle.to_dict())
    rows[0]["observation"] = rows[0]["observation"].to_dict()
    with pytest.raises(ValueError, match="saved JSON"):
        subject.prepare_validated_projection_corpus("security_ir", rows)


@pytest.mark.parametrize("mutation", ["source", "native_execution"])
def test_mutation_invalidates_prepared_handle(native_double, mutation):
    rows, executions = panel()
    handle = subject.prepare_validated_projection_corpus("security_ir", rows)
    if mutation == "source":
        rows[0]["source_inputs"]["source_text"] = "edited source"
    else:
        executions[0].valid = False
    with pytest.raises(ValueError, match="source and target|evidence changed"):
        subject.validate_prepared_projection_corpus(handle)


def test_aggregate_source_bound_is_enforced(native_double, monkeypatch):
    rows, _ = panel()
    monkeypatch.setattr(subject, "MAX_TOTAL_SOURCE_BYTES", 30)
    with pytest.raises(ValueError, match="aggregate byte"):
        subject.prepare_validated_projection_corpus("security_ir", rows)


def test_training_dispatch_retains_exact_split_order_and_rechecks_after_fit(native_double, monkeypatch, tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v5 as trainer
    rows, _ = panel()
    handle = subject.prepare_validated_projection_corpus("security_ir", rows)
    def fit(train, validation, **options):
        assert train == [rows[0]["observation"]] and validation == [rows[1]["observation"]]
        assert options == {"domain_id": "security_ir", "output_dir": tmp_path, "epochs": 2}
        return {"descriptor": {"unchanged": True}, "report": {"test_used_for_selection": False}}
    monkeypatch.setattr(trainer, "train_validated_family_projection_autoencoder", fit)
    fitted = subject.train_prepared_projection_corpus(handle, output_dir=tmp_path, epochs=2)
    assert fitted["descriptor"] == {"unchanged": True}
    assert fitted["corpus_manifest_sha256"] == handle.to_dict()["manifest_sha256"]


def test_edit_during_fit_prevents_return_of_candidate(native_double, monkeypatch, tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v5 as trainer
    rows, _ = panel()
    handle = subject.prepare_validated_projection_corpus("security_ir", rows)
    def fit(*args, **options):
        rows[0]["source_inputs"]["source_text"] = "concurrent edited source"
        return {"descriptor": {"candidate_only": True}}
    monkeypatch.setattr(trainer, "train_validated_family_projection_autoencoder", fit)
    with pytest.raises(ValueError, match="source and target"):
        subject.train_prepared_projection_corpus(handle, output_dir=tmp_path)


def source_rows():
    target = {"kind": "intent_rich_ast", "document": {"kind": "atom", "actor": "agency",
        "action": "save", "object": "record", "modality": "required"}}
    return [{"id": split, "domain_id": "intent_ir", "document_id": split, "group_id": split,
        "split": split, "source_text": split + " source", "embedding": [float(index + 1)] + [0.] * 383,
        "reference_target": target, "target_origin": "authored", "source_language": "en",
        "evaluation_role": "sealed" if split in ("test", "canary") else "development"}
        for index, split in enumerate(("train", "validation", "test", "canary"))]


def test_source_inventory_preserves_splits_and_does_not_promote_declared_embeddings():
    rows = source_rows()
    result = subject.audit_source_corpus(rows, vector_space_id="caller-declared-384")
    assert result["transfer_audit"]["split_counts"] == dict.fromkeys(("train", "validation", "test", "canary"), 1)
    assert all(row["native_target_shape_validated"] for row in result["rows"])
    assert result["source_decoder_ready_row_count"] == 0
    assert not result["source_decoder_training_allowed"]
    assert all("verified_embedding_producer_join_missing" in row["blockers"] for row in result["rows"])


def test_source_inventory_propagates_cross_split_conflicts_and_weak_origins():
    rows = source_rows()
    rows[0]["source_text"] = rows[1]["source_text"]
    rows[0]["target_origin"] = "compiler_weak"
    rows[2]["target_origin"] = "teacher_prediction"
    result = subject.audit_source_corpus(rows, vector_space_id="caller-declared-384")
    by_id = {row["id"]: row for row in result["rows"]}
    assert "cross_split_connected_component" in by_id["train"]["blockers"]
    assert by_id["train"]["target_origin"] == "compiler_weak"
    assert "missing_reference_supervision" in by_id["test"]["blockers"]


def test_target_shape_failure_is_reported_without_repair():
    rows = source_rows()
    rows[0]["reference_target"] = {"invented": True}
    result = subject.audit_source_corpus(rows, vector_space_id="caller-declared-384")
    row = next(row for row in result["rows"] if row["id"] == "train")
    assert not row["native_target_shape_validated"]
    assert "native_source_decoder_target_not_validated" in row["blockers"]
    assert rows[0]["reference_target"] == {"invented": True}


def test_duplicate_ids_keep_exact_target_shape_diagnostics_by_row_digest():
    rows = source_rows()
    rows[1]["id"] = rows[0]["id"]
    rows[1]["reference_target"] = {"invented": True}
    result = subject.audit_source_corpus(rows, vector_space_id="caller-declared-384")
    matching = [row for row in result["rows"] if row["id"] == "train"]
    assert len(matching) == 2
    assert sorted(row["native_target_shape_validated"] for row in matching) == [False, True]
    assert all("duplicate_id" in row["blockers"] for row in matching)


def test_source_audit_pins_actual_native_target_owners_including_ui():
    rows = source_rows()
    rows[1]["domain_id"] = "ui_ux_ir"
    rows[1]["reference_target"] = {"kind": "ui_component", "document": {"component_id": "submit",
        "role": "button", "privacy_sensitivity": "none", "presentation_classification": "interactive"}}
    result = subject.audit_source_corpus(rows, vector_space_id="caller-declared-384")
    pins = result["source_target_validator_pins"]
    assert "ipfs_datasets_py.logic.formalization.autoencoder.source_training_v2" in pins
    assert "ipfs_datasets_py.logic.formalization.autoencoder.ui_source_contract_384" in pins
    assert "ipfs_datasets_py.logic.ui_ux_ir.model.components" in pins
    assert "ipfs_datasets_py.logic.security_ir.model" not in pins
    assert all(len(digest) == 64 for digest in pins.values())
    assert not result["source_decoder_training_allowed"]


def test_source_validator_drift_during_audit_is_rejected(monkeypatch):
    calls = iter([{"validator": "a" * 64}, {"validator": "b" * 64}])
    monkeypatch.setattr(subject, "_source_validator_pins", lambda domains: next(calls))
    with pytest.raises(ValueError, match="source target validators changed"):
        subject.audit_source_corpus(source_rows(), vector_space_id="caller-declared-384")
