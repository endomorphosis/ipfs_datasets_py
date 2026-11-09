"""Exact supervised input custody over fictional source-span examples.

No model, checkpoint, optimizer, training target producer or corpus is loaded.
Callbacks only inspect or mutate detached engineering dictionaries.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.checkpoint_content_guard import CheckpointContentGuard


def digest(value):
    return CheckpointContentGuard(value).sha256


def source_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def examples():
    return [
        {"id": "fictional-agency", "source_text": "The agency shall disclose records.",
         "canonical_ir": {"rules": [{"modality": "O", "actor": "agency", "action": "disclose",
             "object": "records", "conditions": [], "exceptions": [], "temporal": []}]}},
        {"id": "fictional-board", "source_text": "The board may retain notices.",
         "canonical_ir": {"rules": [{"modality": "P", "actor": "board", "action": "retain",
             "object": "notices", "conditions": [], "exceptions": [], "temporal": []}]}},
    ]


def manifest_for(rows, partition):
    return splits.LegalIRSplitManifest(
        examples=tuple(splits.LegalIRSplitExample.from_sample(
            {"sample_id": row["id"], "text": row["source_text"]}) for row in rows),
        assignments={row["id"]: partition for row in rows},
        config_digest=source_digest("fictional fixed consumer policy"),
    ).to_dict()


def case(*, operation="training", rows=None, partition=None):
    rows = examples() if rows is None else deepcopy(rows)
    partition = partition or ("train" if operation == "training" else "validation")
    target_exposure = ("declared_supervised_training" if operation == "training"
                       else "declared_validation_scoring")
    eligibility, exposure = [], []
    for row in rows:
        binding = {"id": row["id"], "source_text_sha256": source_digest(row["source_text"]),
                   "canonical_ir_sha256": digest(row["canonical_ir"])}
        eligibility.append({**binding, "target_origin": "authored_engineering_fixture",
            "status": "eligible", "allowed_operations": [operation],
            "reason": "Explicit fictional supervised engineering example; no legal gold."})
        exposure.append({**binding, "target_exposure": target_exposure,
            "provenance_ref": "fixture:authored-without-real-statute-review"})
    manifest = manifest_for(rows, partition)
    return rows, {
        "expected_rows_sha256": digest(rows), "split_manifest": manifest,
        "expected_split_manifest_sha256": digest(manifest),
        "eligibility_records": eligibility, "expected_eligibility_sha256": digest(eligibility),
        "exposure_records": exposure, "expected_exposure_sha256": digest(exposure),
        "operation": operation,
    }


def repin(options):
    for field, expected in (("split_manifest", "expected_split_manifest_sha256"),
                            ("eligibility_records", "expected_eligibility_sha256"),
                            ("exposure_records", "expected_exposure_sha256")):
        options[expected] = digest(options[field])


def validation_inputs(options):
    return {name: options[name] for name in ("split_manifest", "eligibility_records", "exposure_records")}


def consume(binding, rows, options, consumer):
    return owner.consume_source_span_binding(binding, rows, **validation_inputs(options), consumer=consumer)


def assert_no_callback(binding, rows, options):
    calls = []
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        consume(binding, rows, options, lambda received: calls.append(received))
    assert calls == []


@pytest.mark.parametrize("operation", ["training", "hparam_selection"])
def test_exact_training_and_validation_inputs_reach_consumer_once_in_original_order(operation):
    rows, options = case(operation=operation)
    original = deepcopy((rows, options))
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    receipt = owner.validate_source_span_consumer_binding(binding, rows, **validation_inputs(options))
    assert receipt == binding.receipt()
    assert_no_gold(receipt)
    calls = []
    consume(binding, rows, options, lambda received: calls.append(deepcopy(received)))
    assert calls == [rows]
    assert (rows, options) == original


@pytest.mark.parametrize("field", ["expected_rows_sha256", "expected_split_manifest_sha256",
                                   "expected_eligibility_sha256", "expected_exposure_sha256"])
@pytest.mark.parametrize("invalid", [None, "", "0" * 64])
def test_independent_canonical_hashes_are_required_and_exact(field, invalid):
    rows, options = case()
    options[field] = invalid
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        owner.prepare_source_span_consumer_binding(rows, **options)


def test_raw_pretty_json_hash_is_not_a_canonical_content_commitment():
    rows, options = case()
    raw = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
    options["expected_rows_sha256"] = hashlib.sha256(raw).hexdigest()
    assert options["expected_rows_sha256"] != digest(rows)
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        owner.prepare_source_span_consumer_binding(rows, **options)


@pytest.mark.parametrize("damage", ["source", "target", "order", "missing", "extra", "id"])
def test_changed_rows_cannot_reach_consumer_under_a_retained_binding(damage):
    rows, options = case()
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    if damage == "source":
        rows[0]["source_text"] += " Changed."
    elif damage == "target":
        rows[0]["canonical_ir"]["rules"][0]["modality"] = "F"
    elif damage == "order":
        rows.reverse()
    elif damage == "missing":
        rows.pop()
    elif damage == "extra":
        rows.append(deepcopy(rows[0]))
    else:
        rows[0]["id"] = "fictional-other-id"
    assert_no_callback(binding, rows, options)


@pytest.mark.parametrize("field,damage", [
    ("eligibility_records", "source_hash"), ("eligibility_records", "target_hash"),
    ("eligibility_records", "status"), ("eligibility_records", "order"),
    ("exposure_records", "source_hash"), ("exposure_records", "target_hash"),
    ("exposure_records", "exposure"), ("exposure_records", "order"),
])
def test_changed_sidecars_cannot_authorize_a_retained_batch(field, damage):
    rows, options = case()
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    records = options[field]
    if damage == "order":
        records.reverse()
    elif damage == "source_hash":
        records[0]["source_text_sha256"] = "0" * 64
    elif damage == "target_hash":
        records[0]["canonical_ir_sha256"] = "0" * 64
    elif damage == "status":
        records[0]["status"] = "ineligible"
    else:
        records[0]["target_exposure"] = "unknown"
    assert_no_callback(binding, rows, options)


@pytest.mark.parametrize("damage", ["split", "example_content", "missing_example", "extra_field"])
def test_changed_split_manifest_cannot_reach_consumer(damage):
    rows, options = case()
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    manifest = options["split_manifest"]
    if damage == "split":
        manifest["assignments"][rows[0]["id"]] = "holdout"
    elif damage == "example_content":
        manifest["examples"][0]["content_hash"] = "0" * 64
    elif damage == "missing_example":
        manifest["examples"].pop()
    else:
        manifest["weakened_profile"] = True
    assert_no_callback(binding, rows, options)


@pytest.mark.parametrize("damage", ["missing_field", "extra_field", "nonmapping_example",
    "forged_guard", "boolean_guard_alias", "forged_manifest_digest", "orphan_assignment",
    "bound_row_assignment_without_example", "weakened_protected", "weakened_partitions"])
def test_repinned_incomplete_or_weakened_manifest_profiles_are_refused(damage):
    rows, options = case()
    manifest = options["split_manifest"]
    if damage == "missing_field":
        manifest.pop("config_digest")
    elif damage == "extra_field":
        manifest["extra"] = None
    elif damage == "nonmapping_example":
        manifest["examples"].append("discarded by permissive from_mapping")
    elif damage == "forged_guard":
        manifest["legal_ir_split_guard"]["passed"] = False
    elif damage == "boolean_guard_alias":
        manifest["legal_ir_split_guard"]["passed"] = 1
    elif damage == "forged_manifest_digest":
        manifest["split_manifest_digest"] = "0" * 64
    else:
        parsed = splits.LegalIRSplitManifest.from_mapping(manifest)
        if damage == "orphan_assignment":
            parsed.assignments["not-an-example"] = "train"
        elif damage == "bound_row_assignment_without_example":
            object.__setattr__(parsed, "examples", tuple(
                example for example in parsed.examples if example.sample_id != rows[0]["id"]))
        elif damage == "weakened_protected":
            object.__setattr__(parsed, "protected_splits", ("holdout",))
        else:
            object.__setattr__(parsed, "partition_names", ("train", "validation"))
        options["split_manifest"] = parsed.to_dict()
    repin(options)
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        owner.prepare_source_span_consumer_binding(rows, **options)


@pytest.mark.parametrize("field", ["eligibility_records", "exposure_records"])
@pytest.mark.parametrize("damage", ["missing", "extra", "order", "unknown_id", "changed_source", "changed_target"])
def test_sidecars_must_cover_exact_ordered_source_target_membership(field, damage):
    rows, options = case()
    records = options[field]
    if damage == "missing":
        records.pop()
    elif damage == "extra":
        records.append(deepcopy(records[0]))
    elif damage == "order":
        records.reverse()
    elif damage == "unknown_id":
        records[0]["id"] = "fictional-unbound"
    else:
        records[0]["source_text_sha256" if damage == "changed_source" else "canonical_ir_sha256"] = "0" * 64
    repin(options)
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        owner.prepare_source_span_consumer_binding(rows, **options)


def test_callback_and_receipt_mutations_cannot_change_retained_binding_or_original_rows():
    rows, options = case()
    before = deepcopy((rows, options))
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    retained = deepcopy(binding.receipt())
    receipt = binding.receipt()
    receipt.clear()
    calls = []

    def mutating_consumer(received):
        calls.append(deepcopy(received))
        received[0]["source_text"] = "Fictional replacement"
        received[0]["canonical_ir"]["rules"][0]["conditions"].append("new condition")
        received.reverse()

    consume(binding, rows, options, mutating_consumer)
    consume(binding, rows, options, lambda received: calls.append(deepcopy(received)))
    assert calls == [rows, rows]
    assert binding.receipt() == retained
    assert (rows, options) == before
    assert owner.validate_source_span_consumer_binding(binding, rows, **validation_inputs(options)) == retained


def test_consumer_exceptions_propagate_without_retrying_callback():
    rows, options = case()
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    calls = []

    def failing_consumer(received):
        calls.append(deepcopy(received))
        raise RuntimeError("fictional consumer failure")

    with pytest.raises(RuntimeError, match="fictional consumer failure"):
        consume(binding, rows, options, failing_consumer)
    assert calls == [rows]


def test_callback_result_returns_once_without_attesting_external_callback_effects():
    rows, options = case()
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    before = deepcopy(rows)
    calls, marker = [], object()

    def consumer(received):
        calls.append(deepcopy(received))
        rows[0]["source_text"] = "External callback effect outside the bound arguments."
        return marker

    assert consume(binding, rows, options, consumer) is marker
    assert calls == [before]
    # A later use revalidates its own inputs. The already completed callback
    # receives no late exception, retry or claim that its effects were checked.
    assert_no_callback(binding, rows, options)


def assert_no_gold(receipt):
    assert receipt["semantic_authority"] is False
    assert receipt["training_gold_authority"] is False
    assert receipt["evaluation_gold_authority"] is False
    assert receipt["eligibility_declaration_only"] is True
    assert receipt["exposure_declaration_only"] is True
    assert receipt["rows_discarded"] == 0


def assert_full_blocked_batch(binding, rows, options, *, blocked_rows=None):
    receipt = binding.receipt()
    assert receipt["status"] == "blocked"
    assert receipt["row_count"] == len(rows)
    assert len(receipt["rows"]) == len(rows)
    assert receipt["ready_row_count"] + receipt["blocked_row_count"] == len(rows)
    if blocked_rows is not None:
        assert receipt["blocked_row_count"] == blocked_rows
    assert receipt["blockers"]
    assert_no_gold(receipt)
    assert_no_callback(binding, rows, options)


@pytest.mark.parametrize("damage", ["ineligible", "unknown_eligibility", "not_authorized",
    "unknown_exposure", "wrong_supervised_exposure"])
def test_mixed_batch_retains_declared_eligibility_and_exposure_failures_without_skipping(damage):
    rows, options = case()
    eligibility, exposure = options["eligibility_records"][0], options["exposure_records"][0]
    if damage == "ineligible":
        eligibility["status"] = "ineligible"
    elif damage == "unknown_eligibility":
        eligibility["status"] = "unknown"
    elif damage == "not_authorized":
        eligibility["allowed_operations"] = ["hparam_selection"]
    elif damage == "unknown_exposure":
        exposure["target_exposure"] = "unknown"
    else:
        exposure["target_exposure"] = "declared_validation_scoring"
    repin(options)
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    assert_full_blocked_batch(binding, rows, options, blocked_rows=1)


@pytest.mark.parametrize("operation", ["training", "hparam_selection"])
def test_protected_split_members_never_reach_the_consumer(operation):
    rows, options = case(operation=operation, partition="holdout")
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    assert_full_blocked_batch(binding, rows, options)


def test_unrelated_global_leakage_outside_consumed_rows_still_blocks_use():
    rows, options = case()
    parsed = splits.LegalIRSplitManifest.from_mapping(options["split_manifest"])
    shared_hash = source_digest("unrelated fictional duplicate cluster")
    extra = tuple(splits.LegalIRSplitExample(sample_id=sample_id, content_hash=shared_hash)
                  for sample_id in ("unrelated-train", "unrelated-holdout"))
    manifest = splits.LegalIRSplitManifest(
        examples=(*parsed.examples, *extra),
        assignments={**parsed.assignments, "unrelated-train": "train", "unrelated-holdout": "holdout"},
        config_digest=parsed.config_digest,
    ).to_dict()
    assert manifest["legal_ir_split_guard"]["passed"] is False
    options["split_manifest"] = manifest
    repin(options)
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    assert_full_blocked_batch(binding, rows, options)


@pytest.mark.parametrize("damage", ["atom_not_in_source", "multiple_rules", "multiple_qualifiers",
                                    "overlapping_facets", "ambiguous_span"])
def test_unsupported_targets_preserve_the_full_batch_and_are_never_repaired(damage):
    rows = examples()
    rule = rows[0]["canonical_ir"]["rules"][0]
    if damage == "atom_not_in_source":
        rule["object"] = "unwritten target"
    elif damage == "multiple_rules":
        rows[0]["canonical_ir"]["rules"].append(deepcopy(rule))
    elif damage == "multiple_qualifiers":
        rule["conditions"] = ["agency", "records"]
    elif damage == "overlapping_facets":
        rule["action"] = "agency"
    else:
        rows[0]["source_text"] = "The agency shall disclose records and records."
    rows, options = case(rows=rows)
    original = deepcopy(rows)
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    assert_full_blocked_batch(binding, rows, options, blocked_rows=1)
    assert rows == original


@pytest.mark.parametrize("operation", ["training", "hparam_selection"])
def test_disclosed_weak_targets_keep_their_origin_and_never_gain_gold_authority(operation):
    rows, options = case(operation=operation)
    for eligibility in options["eligibility_records"]:
        eligibility["target_origin"] = "model_generated_weak"
        eligibility["reason"] = "Disclosed fictional weak supervision, without legal review."
    repin(options)
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    receipt = binding.receipt()
    assert receipt["status"] == "ready"
    assert receipt["row_count"] == receipt["ready_row_count"] == 2
    assert receipt["blocked_row_count"] == 0
    assert_no_gold(receipt)
    calls = []
    marker = object()

    def consumer(received):
        calls.append(deepcopy(received))
        return marker

    assert consume(binding, rows, options, consumer) is marker
    assert calls == [rows]
    assert all(item["eligibility"]["target_origin"] == "model_generated_weak" for item in receipt["rows"])


def test_unicode_source_hashes_bind_exact_utf8_without_normalizing_copied_text():
    rows = [{"id": "fictional-unicode", "source_text": "The Łódź committee shall disclose résumé Ω-17.",
             "canonical_ir": {"rules": [{"modality": "O", "actor": "Łódź committee",
                 "action": "disclose", "object": "résumé Ω-17", "conditions": [],
                 "exceptions": [], "temporal": []}]}}]
    rows, options = case(rows=rows)
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    calls = []
    consume(binding, rows, options, lambda received: calls.append(received))
    assert calls == [rows]
    assert options["eligibility_records"][0]["source_text_sha256"] == source_digest(rows[0]["source_text"])


def test_repinned_manifest_content_hash_cannot_name_different_source_bytes():
    rows, options = case()
    parsed = splits.LegalIRSplitManifest.from_mapping(options["split_manifest"])
    examples_by_id = {example.sample_id: example for example in parsed.examples}
    old = examples_by_id[rows[0]["id"]]
    values = old.to_dict()
    values["content_hash"] = source_digest("a different fictional source")
    examples_by_id[old.sample_id] = splits.LegalIRSplitExample.from_mapping(values)
    options["split_manifest"] = splits.LegalIRSplitManifest(
        examples=tuple(examples_by_id.values()), assignments=parsed.assignments,
        config_digest=parsed.config_digest,
    ).to_dict()
    repin(options)
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        owner.prepare_source_span_consumer_binding(rows, **options)


@pytest.mark.parametrize("damage", ["empty", "duplicate_id", "duplicate_text", "blank_id",
                                    "missing_field", "extra_field", "latent"])
def test_rows_require_a_nonempty_closed_unique_zero_latent_profile(damage):
    rows, options = case()
    if damage == "empty":
        rows.clear()
    elif damage == "duplicate_id":
        rows[1]["id"] = rows[0]["id"]
    elif damage == "duplicate_text":
        rows[1]["source_text"] = rows[0]["source_text"]
    elif damage == "blank_id":
        rows[0]["id"] = " "
    elif damage == "missing_field":
        rows[0].pop("canonical_ir")
    elif damage == "extra_field":
        rows[0]["gold"] = True
    else:
        rows[0]["latent"] = [0.] * 384
    options["expected_rows_sha256"] = digest(rows)
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        owner.prepare_source_span_consumer_binding(rows, **options)


@pytest.mark.parametrize("field,key,value", [
    ("eligibility_records", "target_origin", "reviewed_legal_gold"),
    ("eligibility_records", "target_origin", None),
    ("eligibility_records", "status", True),
    ("eligibility_records", "allowed_operations", ["representation_promotion"]),
    ("eligibility_records", "reason", " "),
    ("exposure_records", "target_exposure", "independently_blinded"),
    ("exposure_records", "provenance_ref", ""),
])
def test_sidecar_declarations_cannot_invent_origins_authorities_or_policy_defaults(field, key, value):
    rows, options = case()
    options[field][0][key] = value
    repin(options)
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        owner.prepare_source_span_consumer_binding(rows, **options)


@pytest.mark.parametrize("operation", [None, "", "representation_promotion", "unrestricted_training"])
def test_only_the_declared_supervised_consumer_operations_are_supported(operation):
    rows, options = case()
    options["operation"] = operation
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        owner.prepare_source_span_consumer_binding(rows, **options)


@pytest.mark.parametrize("damage", ["nonfinite", "cycle", "custom_object", "custom_dict", "nonstring_key"])
def test_non_json_or_custom_values_are_rejected_before_any_consumption(damage):
    rows, options = case()
    if damage == "nonfinite":
        rows[0]["canonical_ir"] = {"value": float("nan")}
    elif damage == "cycle":
        rows[0]["canonical_ir"]["cycle"] = rows
    elif damage == "custom_object":
        rows[0]["canonical_ir"] = object()
    elif damage == "custom_dict":
        class CustomDict(dict):
            pass
        rows[0]["canonical_ir"] = CustomDict(rows[0]["canonical_ir"])
    else:
        rows[0]["canonical_ir"] = {1: "non-JSON object key"}
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        owner.prepare_source_span_consumer_binding(rows, **options)


@pytest.mark.parametrize("damage", ["rows", "bytes", "depth", "nodes"])
def test_complete_input_bounds_refuse_without_consuming_or_filtering_rows(damage):
    rows, options = case()
    if damage == "rows":
        rows = [{"id": str(index), "source_text": "Fictional", "canonical_ir": {}}
                for index in range(owner.MAX_ROWS + 1)]
        options["expected_rows_sha256"] = digest(rows)
    elif damage == "bytes":
        rows[0]["source_text"] = "x" * (owner.MAX_BYTES + 1)
    elif damage == "depth":
        nested = {}
        for _ in range(owner.MAX_DEPTH + 1):
            nested = {"nested": nested}
        rows[0]["canonical_ir"] = nested
    else:
        rows[0]["canonical_ir"] = [None] * (owner.MAX_NODES + 1)
    with pytest.raises(owner.SourceSpanConsumerBindingError, match="bound"):
        owner.prepare_source_span_consumer_binding(rows, **options)


def test_live_split_source_drift_invalidates_binding_before_consumer_dispatch(monkeypatch):
    rows, options = case()
    binding = owner.prepare_source_span_consumer_binding(rows, **options)
    split_path = Path(splits.__file__).resolve()
    original_read_bytes = Path.read_bytes

    def changed_split_bytes(path):
        raw = original_read_bytes(path)
        return raw + b"\n# fictional split-source drift\n" if path.resolve() == split_path else raw

    monkeypatch.setattr(Path, "read_bytes", changed_split_bytes)
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        owner.validate_source_span_consumer_binding(binding, rows, **validation_inputs(options))
    calls = []
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        consume(binding, rows, options, lambda received: calls.append(received))
    assert calls == []


# These tests isolate the consumer/admission interface with a mocked assessment.
# They do not authenticate signatures, establish statutory meaning, exercise a
# decoder, or stand in for the admission owner's end-to-end fixture tests.
def reviewed_case(monkeypatch, *, operation="training", provenance="fictional_fixture"):
    from types import SimpleNamespace
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission
    # Deliberately opaque complete-target payload: consumer preservation, not
    # constructor validity, is under test. The admission owner owns validation.
    target = {"expression": {"binder": {"name": "officer", "sort": "Officer"},
        "body": {"if": {"predicate": "Covered", "arguments": ["officer"]},
                 "then": {"modality": "O", "predicate": "Files", "arguments": ["officer", "report"]},
                 "unless": {"predicate": "Excused", "arguments": ["board", "officer"]}}},
        "argument_roles": [{"symbol": "Files", "roles": ["actor", "object"]}]}
    rows = [{"id": "fictional-reviewed", "unit_id": "fixture:provision-2",
             "source_text": "Every covered officer must file a report unless the Board excuses that officer.",
             "canonical_ir": target}]
    report = {"schema": "legal-reviewed-norm-admission-assessment/v2",
        "profile": "complete-reviewed-norm-admission/v2", "declaration_sha256": "d" * 64,
        "provenance_kind": provenance, "semantic_use_eligible": True,
        "permitted_uses": [operation], "blockers": [], "producer_pins": {"fixture:admission": "a" * 64},
        "training_mask": 0, "evaluation_gold_mask": 0,
        "units": [{"unit_id": rows[0]["unit_id"], "source_text": rows[0]["source_text"],
                   "occurrence_cid": "fixture:occurrence:provision-2", "canonical_ir": deepcopy(target),
                   "argument_roles": deepcopy(target["argument_roles"]),
                   "relational_profile": "fixture:opaque-typed-contract"}]}
    calls = []
    def assess(**inputs):
        calls.append(deepcopy(inputs))
        result = deepcopy(inputs["test_report"])
        if inputs.get("current_revoked"):
            result["semantic_use_eligible"] = False
            result["blockers"] = ["current_reviewer_key_revoked"]
        if inputs.get("current_dependency_changed"):
            raise ValueError("current dependency digest differs")
        return result
    fake = SimpleNamespace(norm=admission.norm, assess_reviewed_norm_admission_v2=assess,
                           norm_content_adjudication_sha256=admission.norm_content_adjudication_sha256)
    monkeypatch.setattr(owner, "_reviewed_admission_owner", lambda: fake)
    replay = {"expected_preparation_sha256": "e" * 64,
              "expected_registry_sha256": "b" * 64, "expected_policy_sha256": "c" * 64,
              "source_inputs": [{"raw_bytes": b"fictional exact UTF8 source\x00"}],
              "relational_inputs": [{"request_raw": b'{"complete":"typed"}'}],
              "at_time_utc": "2026-11-08T08:00:00Z", "test_report": report}
    exposure = [{"id": rows[0]["id"], "source_text_sha256": source_digest(rows[0]["source_text"]),
                 "canonical_ir_sha256": digest(target), "target_exposure":
                 "declared_supervised_training" if operation == "training" else "declared_validation_scoring",
                 "provenance_ref": "fixture:isolated-consumer-interface"}]
    manifest = manifest_for(rows, "train" if operation == "training" else "validation")
    options = {"expected_rows_sha256": digest(rows), "split_manifest": manifest,
        "expected_split_manifest_sha256": digest(manifest), "admission_inputs": replay,
        "expected_admission_inputs_sha256": owner.reviewed_admission_inputs_sha256(replay),
        "exposure_records": exposure, "expected_exposure_sha256": digest(exposure),
        "operation": operation, "allow_fictional_fixture": True}
    return rows, options, calls


def reviewed_validation_inputs(options):
    return {name: options[name] for name in ("split_manifest", "admission_inputs", "exposure_records")}


def reviewed_consume(binding, rows, options, consumer):
    return owner.consume_reviewed_source_span_binding_v2(binding, rows,
        **reviewed_validation_inputs(options), consumer=consumer)


@pytest.mark.parametrize("operation", ["training", "hparam_selection"])
def test_reviewed_complete_target_is_preserved_and_admission_replayed_at_dispatch(monkeypatch, operation):
    rows, options, replays = reviewed_case(monkeypatch, operation=operation)
    originals = deepcopy((rows, options))
    binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    assert len(replays) == 1
    receipt = binding.receipt()
    assert receipt["status"] == "ready"
    assert receipt["semantic_admission_replayed"] is True
    assert receipt["training_mask"] == receipt["evaluation_gold_mask"] == 0
    assert receipt["proof_authority"] is receipt["lean_corpus_authority"] is receipt["corpus_admitted"] is False
    received = []
    result = reviewed_consume(binding, rows, options, lambda batch: received.append(deepcopy(batch)))
    assert result is None and received == [rows] and len(replays) == 2
    assert replays[1]["source_inputs"][0]["raw_bytes"] == b"fictional exact UTF8 source\x00"
    assert (rows, options) == originals


def test_reviewed_fixture_requires_explicit_permission_and_cannot_gain_production_masks(monkeypatch):
    rows, options, _ = reviewed_case(monkeypatch)
    options.pop("allow_fictional_fixture")
    binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    assert binding.receipt()["status"] == "blocked"
    callbacks = []
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        reviewed_consume(binding, rows, options, callbacks.append)
    assert callbacks == []
    options["admission_inputs"]["test_report"]["training_mask"] = 1
    options["expected_admission_inputs_sha256"] = owner.reviewed_admission_inputs_sha256(options["admission_inputs"])
    with pytest.raises(owner.SourceSpanConsumerBindingError, match="zero production/gold"):
        owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)


@pytest.mark.parametrize("damage", ["revoked", "dependency_changed", "operation_denied"])
def test_reviewed_current_revocation_dependency_or_permission_failure_blocks_old_ready_receipt(monkeypatch, damage):
    rows, options, _ = reviewed_case(monkeypatch)
    binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    assert binding.receipt()["status"] == "ready"
    current = options["admission_inputs"]
    if damage == "revoked":
        current["current_revoked"] = True
    elif damage == "dependency_changed":
        current["current_dependency_changed"] = True
    else:
        current["test_report"]["permitted_uses"] = ["formalization"]
    callbacks = []
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        reviewed_consume(binding, rows, options, callbacks.append)
    assert callbacks == []


@pytest.mark.parametrize("damage", ["declaration", "preparation", "producer", "roles", "profile", "unit_occurrence",
                                    "trust_registry", "trust_policy"])
def test_reviewed_retained_binding_rejects_changed_stable_admission_identity(monkeypatch, damage):
    rows, options, _ = reviewed_case(monkeypatch)
    binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    current = options["admission_inputs"]
    report = current["test_report"]
    if damage == "declaration": report["declaration_sha256"] = "f" * 64
    elif damage == "preparation": current["expected_preparation_sha256"] = "f" * 64
    elif damage == "producer": report["producer_pins"]["fixture:admission"] = "f" * 64
    elif damage == "roles": report["units"][0]["argument_roles"][0]["roles"].reverse()
    elif damage == "profile": report["units"][0]["relational_profile"] = "fixture:other-profile"
    elif damage == "trust_registry": current["expected_registry_sha256"] = "f" * 64
    elif damage == "trust_policy": current["expected_policy_sha256"] = "f" * 64
    else: report["units"][0]["occurrence_cid"] = "fixture:other-occurrence"
    callbacks = []
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        reviewed_consume(binding, rows, options, callbacks.append)
    assert callbacks == []


def test_reviewed_updated_clock_can_replay_the_same_stable_admission(monkeypatch):
    rows, options, replays = reviewed_case(monkeypatch)
    binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    options["admission_inputs"]["at_time_utc"] = "2026-11-08T08:01:00Z"
    calls = []
    reviewed_consume(binding, rows, options, calls.append)
    assert calls == [rows] and len(replays) == 2
    assert replays[-1]["at_time_utc"] == "2026-11-08T08:01:00Z"


@pytest.mark.parametrize("damage", ["raw_source", "request_raw"])
def test_reviewed_admission_input_commitment_preserves_exact_bytes(monkeypatch, damage):
    rows, options, _ = reviewed_case(monkeypatch)
    if damage == "raw_source": options["admission_inputs"]["source_inputs"][0]["raw_bytes"] += b"changed"
    else: options["admission_inputs"]["relational_inputs"][0]["request_raw"] += b" "
    with pytest.raises(owner.SourceSpanConsumerBindingError, match="commitment differs"):
        owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)


@pytest.mark.parametrize("damage", ["source", "target", "missing_unit", "legacy_assessment"])
def test_reviewed_rows_cannot_launder_different_source_targets_or_legacy_assessments(monkeypatch, damage):
    rows, options, _ = reviewed_case(monkeypatch)
    if damage == "source": rows[0]["source_text"] += " Unreviewed clause."
    elif damage == "target": rows[0]["canonical_ir"]["expression"]["body"].pop("unless")
    elif damage == "missing_unit": rows[0]["unit_id"] = "fixture:unreviewed-unit"
    else: options["admission_inputs"]["test_report"]["profile"] = "unapplied-common-norm-answer-adjudication/v1"
    options["expected_rows_sha256"] = digest(rows)
    options["expected_admission_inputs_sha256"] = owner.reviewed_admission_inputs_sha256(options["admission_inputs"])
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)


def test_reviewed_compact_codec_is_blocked_without_projecting_full_target(monkeypatch):
    rows, options, _ = reviewed_case(monkeypatch)
    original = deepcopy(rows)
    options["target_codec"] = "single_canonical_deontic_rule_with_one_copied_span_per_facet"
    binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    assert binding.receipt()["status"] == "blocked"
    assert rows == original
    calls = []
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        reviewed_consume(binding, rows, options, calls.append)
    assert calls == []


def test_reviewed_protected_population_and_unknown_exposure_block_without_filtering(monkeypatch):
    rows, options, _ = reviewed_case(monkeypatch)
    options["split_manifest"] = manifest_for(rows, "holdout")
    options["expected_split_manifest_sha256"] = digest(options["split_manifest"])
    options["exposure_records"][0]["target_exposure"] = "unknown"
    options["expected_exposure_sha256"] = digest(options["exposure_records"])
    binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    receipt = binding.receipt()
    assert receipt["row_count"] == receipt["blocked_row_count"] == 1 and receipt["rows_discarded"] == 0
    assert {blocker["reason"] for blocker in receipt["blockers"]} >= {
        "split_policy_disallowed", "exposure_declaration_does_not_match_operation"}


def test_reviewed_heldout_evaluation_has_no_implicit_validation_policy(monkeypatch):
    rows, options, _ = reviewed_case(monkeypatch)
    options["operation"] = "heldout_evaluation"
    with pytest.raises(owner.SourceSpanConsumerBindingError, match="unsupported reviewed consumer operation"):
        owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)


def reviewed_public_admission_inputs(helper, admission, case):
    args, kwargs = helper.reviewed_assessment_arguments_v2(admission, case)
    return dict(zip(("preparation", "registry", "policy", "reviews"), args), **kwargs)


def reviewed_public_consumer_case():
    """Reuse the admission owner's fictional source+AST+signature fixture."""
    import importlib.util
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission
    helper_path = Path(__file__).parents[2] / "logic" / "autoformal" / "test_legal_norm_content_adjudication_v1.py"
    spec = importlib.util.spec_from_file_location("_reviewed_consumer_public_admission_fixture", helper_path)
    assert spec is not None and spec.loader is not None
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    case = helper.reviewed_norm_fixture_v2(admission)
    rows = [{"id": "reviewed:" + unit["unit_id"], "unit_id": unit["unit_id"],
             "source_text": unit["source_text"], "canonical_ir": deepcopy(unit["canonical_ir"])}
            for unit in case["preparation"]["units"]]
    exposure = [{"id": row["id"], "source_text_sha256": source_digest(row["source_text"]),
                 "canonical_ir_sha256": digest(row["canonical_ir"]),
                 "target_exposure": "declared_supervised_training",
                 "provenance_ref": "fixture:complete-reviewed-consumer-integration"} for row in rows]
    manifest = manifest_for(rows, "train")
    replay = reviewed_public_admission_inputs(helper, admission, case)
    options = {"expected_rows_sha256": digest(rows), "split_manifest": manifest,
        "expected_split_manifest_sha256": digest(manifest), "admission_inputs": replay,
        "expected_admission_inputs_sha256": owner.reviewed_admission_inputs_sha256(replay),
        "exposure_records": exposure, "expected_exposure_sha256": digest(exposure),
        "operation": "training", "allow_fictional_fixture": True}
    return helper, admission, case, rows, options


def test_reviewed_public_source_ast_signature_admission_reaches_consumer_without_projection():
    _, _, case, rows, options = reviewed_public_consumer_case()
    binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    assert binding.receipt()["status"] == "ready"
    callbacks = []
    reviewed_consume(binding, rows, options, lambda received: callbacks.append(deepcopy(received)))
    assert callbacks == [rows]
    assert all(row["canonical_ir"]["typed_expression"] and row["canonical_ir"]["argument_roles"] for row in callbacks[0])
    for row in callbacks[0]:
        complete = row["canonical_ir"]
        assert {"profile", "typed_expression", "argument_roles", "assumptions", "governing_context",
                "interpretation_id", "source_binding", "definition_uses", "cross_references"} <= set(complete)
        assert complete["assumptions"] == []
        assert complete["governing_context"] and complete["interpretation_id"] and complete["source_binding"]
    assert len(case["declaration"]["definition_uses"]) == 2
    assert binding.receipt()["training_mask"] == binding.receipt()["evaluation_gold_mask"] == 0


def test_reviewed_public_current_revocation_blocks_previously_ready_consumer():
    helper, admission, case, rows, options = reviewed_public_consumer_case()
    binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    assert binding.receipt()["status"] == "ready"
    case["registry"]["keys"][0]["revoked_at_utc"] = helper.EVALUATED
    case["registry"]["revocation_generation"] += 1
    helper.reviewed_resign_v2(case)
    options["admission_inputs"] = reviewed_public_admission_inputs(helper, admission, case)
    callbacks = []
    with pytest.raises(owner.SourceSpanConsumerBindingError) as captured:
        reviewed_consume(binding, rows, options, callbacks.append)
    assert callbacks == []
    assert captured.value.receipt is not None
    assert captured.value.receipt["status"] == "blocked"
    assert any(item["reason"] == "semantic_admission_not_eligible"
               for item in captured.value.receipt["blockers"])


def test_reviewed_public_replaced_supporting_trust_cannot_reuse_old_consumer_binding():
    from cryptography.hazmat.primitives import serialization
    from ipfs_datasets_py.logic.profile_g import Ed25519Signer
    helper, admission, case, rows, options = reviewed_public_consumer_case()
    binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    assert binding.receipt()["status"] == "ready"
    case["registry"]["generation"] += 1
    case["registry"]["process_id"] = "fixture:different-supporting-trust"
    case["policy"]["process_id"] = case["registry"]["process_id"]
    case["policy"]["policy_id"] = "fixture:different-supporting-policy"
    case["signers"] = [Ed25519Signer.generate("did:example:replacement-reviewer:" + str(index))
                       for index in range(len(case["registry"]["keys"]))]
    for index, (key, signer, review) in enumerate(zip(case["registry"]["keys"], case["signers"], case["reviews"])):
        key["key_id"] = "fixture:replacement-key:" + str(index)
        key["principal_id"] = "fixture:replacement-principal:" + str(index)
        key["signer_did"] = signer.did
        key["public_key_hex"] = signer.public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        review["key_id"] = key["key_id"]
        review["principal_id"] = key["principal_id"]
    helper.reviewed_resign_v2(case)
    current = reviewed_public_admission_inputs(helper, admission, case)
    assert admission.assess_reviewed_norm_admission_v2(**current)["semantic_use_eligible"] is True
    options["admission_inputs"] = current
    callbacks = []
    with pytest.raises(owner.SourceSpanConsumerBindingError, match="trust identity changed") as captured:
        reviewed_consume(binding, rows, options, callbacks.append)
    assert callbacks == []
    assert captured.value.receipt["status"] == "blocked"
    assert any(item["reason"] == "reviewed_admission_identity_changed"
               for item in captured.value.receipt["blockers"])


def reviewed_public_heldout_case():
    """Existing signed fictional component; no real statutory review or model."""
    helper, admission, current, rows, options = reviewed_public_consumer_case()
    options.update(operation="heldout_evaluation", allow_heldout_evaluation=True,
                   heldout_evaluation_purpose=owner.REVIEWED_HELDOUT_PURPOSE)
    options["split_manifest"] = manifest_for(rows, "holdout")
    options["expected_split_manifest_sha256"] = digest(options["split_manifest"])
    for exposure in options["exposure_records"]:
        exposure["target_exposure"] = owner.REVIEWED_HELDOUT_EXPOSURE
    options["expected_exposure_sha256"] = digest(options["exposure_records"])
    return helper, admission, current, rows, options


def test_reviewed_explicit_heldout_complete_component_retains_actual_dependency_closure():
    _, _, current, rows, options = reviewed_public_heldout_case()
    binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    receipt = binding.receipt()
    assert receipt["status"] == "ready"
    heldout = receipt["heldout_evaluation"]
    group = heldout["dependency_group"]
    assert group["required_dependency_ids"] == current["preparation"]["subject"]["required_dependency_ids"]
    assert group["dependency_manifest_sha256"] == current["manifest"]["manifest_sha256"]
    assert group["dependencies"] == [{"artifact_id": row["artifact_id"],
        "artifact_sha256": row["artifact_sha256"]} for row in current["manifest"]["artifacts"]]
    assert heldout["dependency_group_sha256"] == digest(group)
    assert {row["unit_id"] for row in group["source_units"]} == {row["unit_id"] for row in rows}
    assert heldout["split_manifest_sha256"] == options["expected_split_manifest_sha256"]
    assert heldout["partition"] == "holdout"
    assert heldout["purpose"] == owner.REVIEWED_HELDOUT_PURPOSE
    assert heldout["training_example_ids"] == heldout["retrieved_example_ids"] == []
    for flag in ("external_training_exposure_verified", "model_pretraining_exposure_verified",
                 "external_retrieval_exclusion_verified", "global_dependency_grouping_verified",
                 "preregistration_time_authenticated", "producer_authenticity_verified",
                 "inference_context_enforced", "generalization_established", "proof_authority"):
        assert heldout[flag] is False
    assert receipt["training_mask"] == receipt["evaluation_gold_mask"] == 0
    calls = []
    reviewed_consume(binding, rows, options, lambda received: calls.append(deepcopy(received)))
    assert calls == [rows]


@pytest.mark.parametrize("damage", ["no_opt_in", "integer_opt_in", "missing_purpose", "wrong_purpose",
                                    "purpose_for_training", "opt_in_for_training"])
def test_reviewed_heldout_requires_distinct_opt_in_and_purpose(damage):
    _, _, _, rows, options = reviewed_public_heldout_case()
    if damage == "no_opt_in":
        options["allow_heldout_evaluation"] = False
    elif damage == "integer_opt_in":
        options["allow_heldout_evaluation"] = 1
    elif damage == "missing_purpose":
        options["heldout_evaluation_purpose"] = None
    elif damage == "wrong_purpose":
        options["heldout_evaluation_purpose"] = "hparam_selection"
    elif damage == "purpose_for_training":
        options.update(operation="training", allow_heldout_evaluation=False)
    else:
        options["operation"] = "training"
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)


@pytest.mark.parametrize("partition", ["train", "validation", "canary", "external_test"])
def test_reviewed_explicit_heldout_does_not_authorize_other_partitions(partition):
    _, _, _, rows, options = reviewed_public_heldout_case()
    options["split_manifest"] = manifest_for(rows, partition)
    options["expected_split_manifest_sha256"] = digest(options["split_manifest"])
    with pytest.raises(owner.SourceSpanConsumerBindingError, match="must remain in holdout"):
        owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)


@pytest.mark.parametrize("damage", ["partial_component", "missing_manifest_member", "extra_manifest_member"])
def test_reviewed_heldout_manifest_cannot_drop_or_add_component_members(damage):
    _, _, _, rows, options = reviewed_public_heldout_case()
    if damage == "partial_component":
        rows.pop()
        options["exposure_records"].pop()
        options["expected_rows_sha256"] = digest(rows)
        options["expected_exposure_sha256"] = digest(options["exposure_records"])
        options["split_manifest"] = manifest_for(rows, "holdout")
    elif damage == "missing_manifest_member":
        options["split_manifest"] = manifest_for(rows[:-1], "holdout")
    else:
        unrelated = {"id": "fictional-unrelated-component", "source_text": "A distinct fictional matter."}
        options["split_manifest"] = manifest_for([*rows, unrelated], "holdout")
    options["expected_split_manifest_sha256"] = digest(options["split_manifest"])
    with pytest.raises(owner.SourceSpanConsumerBindingError, match="complete admitted component"):
        owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)


@pytest.mark.parametrize("exposure", ["unknown", "declared_supervised_training", "declared_validation_scoring"])
def test_reviewed_heldout_cannot_reuse_supervision_or_validation_exposure(exposure):
    _, _, _, rows, options = reviewed_public_heldout_case()
    for record in options["exposure_records"]:
        record["target_exposure"] = exposure
    options["expected_exposure_sha256"] = digest(options["exposure_records"])
    if exposure != "unknown":
        with pytest.raises(owner.SourceSpanConsumerBindingError, match="explicit target_exposure"):
            owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    else:
        binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
        assert binding.receipt()["blocked_row_count"] == len(rows)
        calls = []
        with pytest.raises(owner.SourceSpanConsumerBindingError, match="batch is blocked"):
            reviewed_consume(binding, rows, options, calls.append)
        assert calls == []


@pytest.mark.parametrize("damage", ["split_manifest", "dependency_manifest"])
def test_reviewed_heldout_rechecks_frozen_split_and_actual_dependencies_at_dispatch(damage):
    _, _, _, rows, options = reviewed_public_heldout_case()
    binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    if damage == "split_manifest":
        options["split_manifest"]["config_digest"] = "0" * 64
    else:
        options["admission_inputs"]["preparation_inputs"]["dependency_manifest"]["artifacts"][0]["artifact_sha256"] = "0" * 64
    calls = []
    with pytest.raises(owner.SourceSpanConsumerBindingError):
        reviewed_consume(binding, rows, options, calls.append)
    assert calls == []


def test_reviewed_heldout_current_revocation_blocks_old_ready_binding():
    helper, admission, current, rows, options = reviewed_public_heldout_case()
    binding = owner.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    current["registry"]["keys"][0]["revoked_at_utc"] = helper.EVALUATED
    current["registry"]["revocation_generation"] += 1
    helper.reviewed_resign_v2(current)
    options["admission_inputs"] = reviewed_public_admission_inputs(helper, admission, current)
    calls = []
    with pytest.raises(owner.SourceSpanConsumerBindingError) as captured:
        reviewed_consume(binding, rows, options, calls.append)
    assert calls == []
    assert captured.value.receipt["status"] == "blocked"
    assert any(item["reason"] == "semantic_admission_not_eligible"
               for item in captured.value.receipt["blockers"])


def test_split_explicit_heldout_policy_preserves_existing_supervised_permissions():
    rows = examples()
    manifest = manifest_for(rows, "holdout")
    assert splits.authorize_legal_ir_split_use(manifest, operation="heldout_evaluation",
                                              items=[{"sample_id": rows[0]["id"]}]).passed is True
    for operation in ("training", "hparam_selection", "representation_promotion", "codex_todo_projection"):
        with pytest.raises(splits.LegalIRSplitPolicyError):
            splits.authorize_legal_ir_split_use(manifest, operation=operation,
                                               items=[{"sample_id": rows[0]["id"]}])
    assert owner.OPERATIONS == ("training", "hparam_selection")
    assert splits.LEGAL_IR_SPLIT_OPERATION_ALLOWED_SPLITS["training"] == frozenset({"train"})
    assert splits.LEGAL_IR_SPLIT_OPERATION_ALLOWED_SPLITS["hparam_selection"] == frozenset({"validation"})


@pytest.mark.parametrize("overlap", ["source_span", "lineage_group", "citation_cluster"])
def test_split_known_cross_partition_leakage_lists_and_blocks_heldout_evaluation(overlap):
    left = {"sample_id": "fictional-exposed", "text": "A hypothetical agency releases notices."}
    right = {"sample_id": "fictional-heldout", "text": "An imagined council retains permits."}
    if overlap == "source_span":
        left.update(source_document_id="fictional:shared-document", char_start=0, char_end=30)
        right.update(source_document_id="fictional:shared-document", char_start=10, char_end=40)
    elif overlap == "lineage_group":
        left["lineage_group_id"] = right["lineage_group_id"] = "fictional:shared-component"
    else:
        left["citation"] = right["citation"] = "10 USC 101"
    manifest = splits.LegalIRSplitManifest(
        examples=tuple(splits.LegalIRSplitExample.from_sample(item) for item in (left, right)),
        assignments={left["sample_id"]: "train", right["sample_id"]: "holdout"},
        config_digest=source_digest("fictional intentionally contaminated heldout manifest"))
    guard = splits.validate_legal_ir_eval_splits(manifest)
    assert guard.passed is False
    assert "heldout_evaluation" in guard.blocked_operations
    assert overlap in {item.kind for item in guard.violations}
    assert splits.split_guard_blocks_operation(guard.to_dict(), "heldout_evaluation") is True
    assert splits.split_guard_blocks_operation({"legal_ir_split_guard": guard.to_dict()},
                                              "heldout_evaluation") is True
    with pytest.raises(splits.LegalIRSplitLeakageError):
        splits.authorize_legal_ir_split_use(manifest, operation="heldout_evaluation",
                                          items=[{"sample_id": right["sample_id"]}])
