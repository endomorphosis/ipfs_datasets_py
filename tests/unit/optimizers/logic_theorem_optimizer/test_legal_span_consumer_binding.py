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
