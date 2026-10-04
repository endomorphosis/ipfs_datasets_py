from copy import deepcopy
import hashlib
import pytest

from scripts.ops.legal_ir import summarize_legal_open_vocabulary_experiment as subject


def source(identity, text, family="a"):
    return {"id": identity, "source_text": text, "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "family_group": family}


def abstention(s, vector):
    return {"source_sha256": s["source_sha256"], "status": "abstained", "canonical_ir": None,
            "formal_outputs": [], "target_access": False, "teacher_forcing": False,
            "latent_sha256": subject.digest(vector)}


def generation(s, context, control="source"):
    vector = context["context"]
    effective = [0.] * len(vector) if control == "zero" else vector
    row = abstention(s, effective)
    receipt = {"id": s["id"], "source_sha256": s["source_sha256"], "supplied_context_sha256": subject.digest(vector),
        "effective_context_sha256": subject.digest(effective), "context_disabled": control == "disabled",
        "donor_id": None, "donor_source_sha256": None, "target_access": False}
    return {"reports": [{"rows": [row]}], "rows": [row], "control": control, "dimension": len(vector),
            "control_receipts": [receipt], "generation_inputs_contained_references": False}


def context(s, value):
    return {"id": s["id"], "source_sha256": s["source_sha256"], "context": [value],
            "context_sha256": subject.digest([value]), "native_stage_receipt": {"id": s["id"]}}


def inventory():
    items = [{"name": f"{arm}-{seed}", "arm": arm, "latent_enabled": arm != "source_only"}
             for arm in subject.ARMS for seed in subject.SEEDS]
    items += [{"name": f"parent_source-{seed}", "arm": "parent_source", "latent_enabled": False} for seed in subject.SEEDS]
    normal = {r["name"]: {panel: {"path": r["name"] + panel} for panel in ("tuning", "challenge", "oov")} for r in items}
    files = deepcopy(normal)
    for item in items:
        if item["latent_enabled"]:
            files[item["name"]].update({f"challenge_{c}_context": {"path": c} for c in subject.CONTROLS})
    frozen = {"schema": "legal-open-vocabulary-generation-freeze/v1", "all_generation_complete": True,
        "challenge_targets_read_in_this_execution": False, "independent_holdout": False, "files": files}
    return frozen, normal, items


def test_complete_inventory_is_7452_including_all_controls_and_parents():
    assert subject.generation_inventory(*inventory()) == 7452


@pytest.mark.parametrize("mutation", ["model", "control", "normal", "reference_access"])
def test_inventory_rejects_dropped_panel_or_model_and_replaced_normal(mutation):
    frozen, normal, items = inventory()
    if mutation == "model":
        frozen["files"].pop("parent_source-1731")
    elif mutation == "control":
        frozen["files"]["native768-1729"].pop("challenge_zero_context")
    elif mutation == "normal":
        normal["source_only-1729"]["oov"] = {"path": "replacement"}
    else:
        frozen["challenge_targets_read_in_this_execution"] = True
    with pytest.raises(ValueError):
        subject.generation_inventory(frozen, normal, items)


@pytest.mark.parametrize("control", ["source", "zero", "disabled"])
def test_control_receipt_distinguishes_zero_from_disabled_and_rejects_mutation(control):
    s = source("a", "one")
    ctx = context(s, 2.)
    value = generation(s, ctx, control)
    assert subject.verify_generation(value, [s], [ctx], dimension=1, control=control) == 0
    value["control_receipts"][0]["context_disabled"] = not value["control_receipts"][0]["context_disabled"]
    with pytest.raises(ValueError, match="control receipt"):
        subject.verify_generation(value, [s], [ctx], dimension=1, control=control)


def test_generation_rejects_rehashed_donor_vector_mismatch():
    s = source("a", "one")
    ctx = context(s, 2.)
    value = generation(s, ctx)
    changed = context(s, 3.)
    with pytest.raises(ValueError, match="effective context"):
        subject.verify_generation(value, [s], [changed], dimension=1, control="source")


def test_generation_rejects_report_rows_disagreeing_with_top_level():
    s = source("a", "one")
    ctx = context(s, 2.)
    value = generation(s, ctx)
    value["reports"] = [{"rows": []}]
    with pytest.raises(ValueError, match="inference reports"):
        subject.verify_generation(value, [s], [ctx], dimension=1, control="source")


def test_generation_rejects_source_change_even_if_source_record_is_rehashed():
    s = source("a", "one")
    ctx = context(s, 2.)
    value = generation(s, ctx)
    changed = source("a", "two")
    with pytest.raises(ValueError, match="source binding"):
        subject.verify_generation(value, [changed], [ctx], dimension=1, control="source")


def test_cross_family_donor_join_rejects_changed_native_receipt():
    sources = [source("a", "one", "x"), source("b", "two", "y")]
    contexts = [context(sources[0], 1.), context(sources[1], 2.)]
    swapped = subject.runner.cross_family_contexts(sources, contexts)
    subject.verify_swap(sources, contexts, swapped)
    swapped[0]["donor_native_stage_receipt"] = {"id": "different"}
    with pytest.raises(ValueError, match="producer donor"):
        subject.verify_swap(sources, contexts, swapped)


def test_reference_rejects_same_length_changed_bytes_and_unknown_keys(tmp_path):
    path = tmp_path / "record.json"
    ref = subject.write(path, {"x": 1})
    assert subject.reference(ref) == {"x": 1}
    with pytest.raises(ValueError, match="closed"):
        subject.reference({**ref, "authority": True})
    path.write_text(path.read_text().replace("1", "2"))
    with pytest.raises(ValueError, match="hash differs"):
        subject.reference(ref)


def selection():
    return {"rows": [{"candidate": {"candidate_id": "a"}}, {"candidate": {"candidate_id": "b"}}],
        "excluded": [{"candidate_id": "c", "reason": "decoder_abstained"}], "source_count": 3,
        "decoded_count": 2, "supported_count": 2, "exclusion_counts": {"decoder_abstained": 1}}


def test_build_accounting_retains_abstention_and_compiled_wrong():
    receipts = [{"candidate_ids": ["a", "b"], "build_passed": True, "backend_executed": True}]
    result = subject.build_accounting(selection(), receipts, {"a": True, "b": False, "c": False})
    assert result["count"] == 3 and result["abstained"] == 1
    assert result["built"] == 2 and result["built_exact"] == result["built_reference_mismatch"] == 1


def test_failed_backend_still_reports_actual_execution():
    receipts = [{"candidate_ids": ["a", "b"], "build_passed": False, "backend_executed": True}]
    result = subject.build_accounting(selection(), receipts, {"a": True, "b": False, "c": False})
    assert result["built"] == 0 and result["actual_lake_build_executed"] is True
    assert result["build_invocations"] == 1


@pytest.mark.parametrize("ids", [["a"], ["b", "a"], ["a", "b", "b"]])
def test_build_accounting_rejects_dropped_reordered_duplicate_batches(ids):
    with pytest.raises(ValueError, match="batch coverage"):
        subject.build_accounting(selection(), [{"candidate_ids": ids, "build_passed": True, "backend_executed": True}],
                                 {"a": True, "b": False, "c": False})


def test_build_accounting_rejects_dropped_abstention_and_duplicate_selection():
    selected = selection()
    selected["excluded"].append(selected["excluded"][0])
    with pytest.raises(ValueError, match="duplicate"):
        subject.build_accounting(selected, [], {"a": True, "b": False, "c": False})
    with pytest.raises(ValueError, match="denominator"):
        subject.build_accounting(selection(), [], {"a": True, "b": False})
