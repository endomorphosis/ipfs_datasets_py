"""Synthetic controls for the opt-in F18 four-tensor full-span profile.

No historical checkpoint, external encoder, or real-input fit is opened.
The numerical controls instantiate the actual retained F18 architecture with
synthetic state, and require a new original-owned numerical admission to run.
The published margin kernel and F18 CE/KL owners stay the implementations.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.legal_ir import conditions_fullspan_margin_v1 as margin
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_modality_conditions_retention as f18
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_conditions_fullspan_training_v1 as subject

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = ROOT / "docs/autoformalization/evidence/legal-ir-conditions-fullspan-owner-adoption-20261027.json"
CONFIG = {
    "hidden_size": 32,
    "embedding_dim": 8,
    "projection_width": 8,
    "latent_dimension": 384,
    "latent_enabled": False,
    "residual_scale": 0.25,
    "seed": 1729,
    "batch_size": 12,
    "learning_rate": 0.001,
}


def _zeros(shape):
    if len(shape) == 1:
        return [0.0] * shape[0]
    return [_zeros(shape[1:]) for _ in range(shape[0])]


def _state():
    shapes = subject._shape_table(CONFIG["embedding_dim"], CONFIG["projection_width"])
    state = {name: _zeros(shape) for name, shape in shapes.items()}
    state["modality.bias"][0] = 0.25
    state["modality.weight"][0][0] = 0.5
    state["presence.bias"][1] = 0.125
    return state


def _population():
    indices = list(range(subject.GOLD_PRESENT_TRAIN_ROWS))
    row_ids = ["synthetic-gold-%03d" % index for index in indices]
    return indices, row_ids


def _provenance(state=None, **overrides):
    indices, row_ids = _population()
    arguments = {
        "config": copy.deepcopy(CONFIG),
        "gold_present_train_indices": indices,
        "gold_present_row_ids": row_ids,
    }
    arguments.update(overrides)
    return subject.donor_provenance(state if state is not None else _state(), **arguments)


def _blocks(mask_modality, token_count=2):
    known = [math.log(0.5), math.log(0.25), math.log(0.25)]
    return {
        "actor_start": {"logits": [0.0] * token_count, "gold_index": None, "teacher_argmax": 0, "mask": False},
        "actor_end": {"logits": [0.0] * token_count, "gold_index": None, "teacher_argmax": 0, "mask": False},
        "modality": {
            "logits": known if mask_modality else [0.0, 0.0, 0.0],
            "gold_index": 0 if mask_modality else None,
            "teacher_argmax": 0,
            "mask": mask_modality,
        },
        "conditions_start": {"logits": [0.0] * token_count, "gold_index": None, "teacher_argmax": 0, "mask": False},
        "conditions_end": {"logits": [0.0] * token_count, "gold_index": None, "teacher_argmax": 0, "mask": False},
        "exceptions_presence": {"logits": [0.0, 0.0], "gold_index": None, "teacher_argmax": 0, "mask": False},
    }


def _records(provenance, indices, *, original_shape=False):
    population = dict(zip(provenance["gold_present_train_indices"], provenance["gold_present_row_ids"], strict=True))
    records = []
    for index in indices:
        text = "actor%d acts when ready" % index if original_shape else "aa%d bb" % index
        tokens = span.tokenize_source(text)
        present = index in population
        labels = {
            "modality": 0,
            "presence": [True, True, False, present, False, False],
            "spans": [(0, 0), (1, 1) if original_shape else (0, 0), (-100, -100),
                      ((2, 3) if original_shape else (0, 1)) if present else (-100, -100),
                      (-100, -100), (-100, -100)],
        }
        records.append({
            "id": population[index] if present else "synthetic-absent-%03d" % index,
            "source_text": text,
            "tokens": tokens,
            "labels": labels,
            "latent": [0.0] * CONFIG["latent_dimension"],
        })
    return records


def _batch(provenance, indices=None, *, original_shape=False):
    import torch
    indices = (list(provenance["gold_present_train_indices"][:subject.BATCH_SIZE])
               if indices is None else list(indices))
    records = _records(provenance, indices, original_shape=original_shape)
    teacher_rows = []
    weight_rows = []
    record_by_index = dict(zip(indices, records, strict=True))
    for index in range(subject.TRAIN_INDEX_COUNT):
        record = record_by_index.get(index)
        if record is None:
            teacher_rows.append({
                "id": "stored-only-%03d" % index,
                "training_index": index,
                "source_sha256": "ab" * 32,
                "token_count": 1,
                "blocks": _blocks(False),
            })
            weight_rows.append({
                "id": "stored-only-%03d" % index,
                "training_index": index,
                "conditions_only_mask": False,
                "conditions_facet_weight": 1,
                "raw_status": "abstained",
                "error_fields": ["actor"],
            })
            continue
        source_sha = hashlib.sha256(record["source_text"].encode()).hexdigest()
        token_count = len(span.tokenize_source(record["source_text"]))
        teacher_rows.append({
            "id": record["id"],
            "training_index": index,
            "source_sha256": source_sha,
            "token_count": token_count,
            "blocks": _blocks(True, token_count),
        })
        projected = [{key: token[key] for key in ("text", "start", "end")} for token in record["tokens"]]
        selected = index == indices[0]
        weight_rows.append({
            "id": record["id"],
            "training_index": index,
            "source_sha256": source_sha,
            "tokens_sha256": f18.checkpoint_digest(projected),
            "labels_sha256": f18.checkpoint_digest(record["labels"]),
            "raw_output_sha256": "0" * 64,
            "raw_status": "decoded",
            "raw_reason": None,
            "error_fields": ["conditions"] if selected else [],
            "conditions_only_mask": selected,
            "conditions_facet_weight": 2 if selected else 1,
        })
    teacher = {"rows": teacher_rows, "rows_sha256": f18.checkpoint_digest(teacher_rows)}
    weights = {
        "rows": weight_rows,
        "rows_sha256": f18.checkpoint_digest(weight_rows),
        "near_complete_mask_sha256": "0" * 64,
    }
    output = {
        "modality": torch.zeros((subject.BATCH_SIZE, 3), dtype=torch.float32, requires_grad=True),
        "presence": torch.zeros((subject.BATCH_SIZE, 4, 2), dtype=torch.float32, requires_grad=True),
        "start": torch.zeros((subject.BATCH_SIZE, 6, 2), dtype=torch.float32, requires_grad=True),
        "end": torch.zeros((subject.BATCH_SIZE, 6, 2), dtype=torch.float32, requires_grad=True),
    }
    return records, indices, teacher, weights, output


def _permissions():
    return {
        "schema": subject.PERMISSION_SCHEMA,
        "count": subject.PERMISSION_COUNT,
        "ids": ["synthetic-permission-%02d" % index for index in range(subject.PERMISSION_COUNT)],
        "frozen": True,
        "scored": False,
    }


def _cases(provenance, permissions):
    digest = f18.checkpoint_digest(permissions["ids"])
    cases = []
    for index, row_id in zip(provenance["gold_present_train_indices"], provenance["gold_present_row_ids"], strict=True):
        cases.append({
            "id": row_id,
            "partition": "TRAIN",
            "gold_present": True,
            "training_index": index,
            "full_ir_sha256": hashlib.sha256(("ir-%d" % index).encode()).hexdigest(),
            "raw_output_sha256": hashlib.sha256(("raw-%d" % index).encode()).hexdigest(),
            "joint_output_sha256": hashlib.sha256(("joint-%d" % index).encode()).hexdigest(),
            "permission_ids_sha256": digest,
        })
    return cases


def _raises(message, function, *args, **kwargs):
    with pytest.raises(ValueError, match=message):
        function(*args, **kwargs)


def test_retained_owners_and_published_kernel_identity_stay_pinned():
    owners = subject.engineering_preparation()["result"]["reuse_owners"]
    assert [(row["path"], row["sha256"]) for row in owners] == [
        (path, digest) for path, (_role, digest) in subject.REUSE_PINS.items()
    ]
    for path, (_role, digest) in subject.REUSE_PINS.items():
        file = ROOT / path
        assert file.is_file() and not file.is_symlink()
        assert hashlib.sha256(file.read_bytes()).hexdigest() == digest
    assert subject.conditions_fullspan_margin_from_logits is margin.conditions_fullspan_margin_from_logits
    assert subject.MARGIN_SCHEMA == margin.SCHEMA == "conditions-fullspan-margin/v1"
    source = Path(subject.__file__).read_text()
    assert "import structured_span_objective" not in source
    assert "def conditions_fullspan_margin" not in source
    retained = json.loads(EVIDENCE.read_text())["retained_preparation"]
    current = subject.engineering_preparation()
    # The immutable receipt is the original dfd generation. These four explicit
    # additive metadata changes document the separately qualified correction;
    # every other preparation field must still match that retained oracle.
    wiring = current["result"]["model_optimizer_wiring"]
    assert {key: wiring.pop(key) for key in (
        "training_row_count", "batch_order_owner", "absent_conditions_margin")} == {
            "training_row_count": 168,
            "batch_order_owner": "legal_span_targeted_loss._batch_indices(168, progress, 12, 1729)",
            "absent_conditions_margin": "connected_zero_in_full_batch_mean",
        }
    assert current["result"]["unresolved_questions"].pop(0) == (
        "Caller-state self-hashes do not independently authenticate the retained final F18 donor or its source/teacher/mask artifact roots; original-owned admission must bind them.")
    assert current == retained


def test_preparation_document_is_closed_and_claims_no_fit():
    prepared = subject.engineering_preparation()
    assert set(prepared) == {
        "schema", "task_id", "parent_reference", "source_binding", "admitted", "formalized",
        "semantic_review_performed", "model_gain_claimed", "training_executed", "result",
    }
    assert prepared["schema"] == "legal-ir-programme-engineering-preparation/v1"
    assert prepared["task_id"] == "LIRAE-LIR17-PROFILE-03"
    for key in ("admitted", "formalized", "semantic_review_performed", "model_gain_claimed", "training_executed"):
        assert prepared[key] is False
    result = prepared["result"]
    assert set(result) == {
        "state_provenance", "model_optimizer_wiring", "selection_mask_contract", "acceptance_controls",
        "frozen_full_ir_casewise_scoring", "unresolved_questions", "reuse_owners",
    }
    assert all(result[key] not in (None, "", [], {}) for key in result)
    wiring = result["model_optimizer_wiring"]
    assert wiring["ce_batch_denominator"] == 12 and wiring["ce_outer_denominator"] == 8
    assert wiring["kl_temperature"] == 1 and wiring["kl_coefficient"] == 1 and wiring["kl_denominator"] == 72
    assert wiring["margin_arms"] == [0.0, 0.25] and wiring["optimizer_steps_executed"] == 0
    assert wiring["structured_objective_invoked"] is False and wiring["latent_enabled"] is False
    assert result["state_provenance"]["frozen36_reused_as_seal"] is False
    assert result["state_provenance"]["teacher_is_donor"] is False
    assert result["state_provenance"]["gold_present_train_rows"] == 72
    contract = result["selection_mask_contract"]
    assert contract["active_scalar_count"] == 130
    assert contract["stored_scalar_count"] == 780
    assert contract["inactive_scalar_count"] == 650
    assert contract["frozen_tensor_count"] == 38 and contract["donor_tensor_count"] == 42
    assert contract["modality_frozen"] is True
    assert "modality.weight" in contract["frozen_parameter_names"]
    assert set(subject.SELECTED).isdisjoint(contract["frozen_parameter_names"])
    assert result["acceptance_controls"]["fits_real_inputs"] is False
    assert result["frozen_full_ir_casewise_scoring"]["scoring_executed"] is False


def test_frozen38_seal_comes_from_the_f18_donor_and_includes_modality():
    state = _state()
    provenance = _provenance(state)
    seal = subject.frozen38_seal(state)
    old = subject.frozen36_digest(state)
    assert seal != old
    assert provenance["old_frozen36_state_sha256"] == old
    assert provenance["donor_state_sha256"] != f18.SOURCE_ACTOR_REFINEMENT_MODEL_SHA256
    assert provenance["teacher_is_donor"] is False
    assert provenance["teacher_role"] == "F15" and provenance["donor_role"] == "F18"
    assert provenance["donor_schema"] == f18.SCHEMA
    assert provenance["donor_lineage_id"] == f18.LINEAGE_ID
    modality = copy.deepcopy(state)
    modality["modality.weight"][1][1] = 1.0
    assert subject.frozen38_seal(modality) != seal
    assert subject.frozen36_digest(modality) == old
    pointer = copy.deepcopy(state)
    pointer["start.weight"][3][0] = 1.0
    assert subject.frozen38_seal(pointer) == seal
    assert subject.frozen36_digest(pointer) == old
    assert f18.checkpoint_digest({name: pointer[name] for name in f18.MODEL_PARAMETER_NAMES}) != provenance["donor_state_sha256"]
    base = copy.deepcopy(state)
    base["presence.bias"][0] = 1.0
    assert subject.frozen38_seal(base) != seal and subject.frozen36_digest(base) != old
    configured = subject.configuration(state, provenance, selection=subject.selection_mask_contract(), margin_weight=0.25)
    assert configured["state_provenance"]["frozen38_state_sha256"] == seal
    assert configured["state_provenance"]["old_frozen36_state_sha256"] == old
    assert configured["state_provenance"]["frozen36_reused_as_seal"] is False
    assert configured["state_provenance"]["frozen38_derived_from_f18_donor"] is True
    assert configured["training_executed"] is False and configured["encoder_executed"] is False
    assert configured["model_optimizer_wiring"]["optimizer_steps"] == 0
    assert configured["model_optimizer_wiring"]["kl"]["denominator"] == 72
    assert configured["model_optimizer_wiring"]["ce"]["batch_denominator"] == 12
    assert subject.GOLD_PRESENT_TRAIN_ROWS == 72
    assert subject.KL_BLOCKS * subject.BATCH_SIZE == 72


def test_rejects_wrong_shapes_rows_counts_partition_provenance_and_nonfinite_controls():
    state = _state()
    provenance = _provenance(state)
    short = copy.deepcopy(state)
    short["start.weight"] = _zeros((5, 64))
    _raises("exact tensor shape required", subject.donor_provenance, short, config=CONFIG,
            gold_present_train_indices=provenance["gold_present_train_indices"],
            gold_present_row_ids=provenance["gold_present_row_ids"])
    ranked = copy.deepcopy(state)
    ranked["end.bias"] = [[0.0]]
    _raises("exact tensor shape required", subject.donor_provenance, ranked, config=CONFIG,
            gold_present_train_indices=provenance["gold_present_train_indices"],
            gold_present_row_ids=provenance["gold_present_row_ids"])
    narrow = copy.deepcopy(state)
    narrow["end.weight"] = _zeros((6, 63))
    _raises("exact tensor shape required", subject.donor_provenance, narrow, config=CONFIG,
            gold_present_train_indices=provenance["gold_present_train_indices"],
            gold_present_row_ids=provenance["gold_present_row_ids"])
    missing_tensor = copy.deepcopy(state)
    missing_tensor.pop("modality.bias")
    _raises("closed42 F18 donor state required", subject.configuration, missing_tensor, provenance)
    bad_row = subject.selection_mask_contract()
    bad_row["active_rows"] = dict(bad_row["active_rows"])
    bad_row["active_rows"]["start.weight"] = [2]
    _raises("conditions row 3 selection required", subject.configuration, state, provenance, selection=bad_row)
    bad_count = subject.selection_mask_contract()
    bad_count["active_scalar_count"] = 129
    _raises("conditions row 3 selection required", subject.configuration, state, provenance, selection=bad_count)
    bad_inactive = subject.selection_mask_contract()
    bad_inactive["inactive_scalar_count"] = 649
    _raises("conditions row 3 selection required", subject.configuration, state, provenance, selection=bad_inactive)
    indices, row_ids = _population()
    _raises("gold-present TRAIN row count required", subject.donor_provenance, state, config=CONFIG,
            gold_present_train_indices=indices[:-1], gold_present_row_ids=row_ids[:-1])
    unsorted = list(indices)
    unsorted[0], unsorted[1] = unsorted[1], unsorted[0]
    _raises("gold-present TRAIN row count required", subject.donor_provenance, state, config=CONFIG,
            gold_present_train_indices=unsorted, gold_present_row_ids=row_ids)
    _raises("gold-present TRAIN row count required", subject.donor_provenance, state, config=CONFIG,
            gold_present_train_indices=indices, gold_present_row_ids=row_ids[:-1] + [row_ids[0]])
    nonfinite = copy.deepcopy(state)
    nonfinite["modality.bias"][0] = float("nan")
    _raises("nonfinite control", subject.donor_provenance, nonfinite, config=CONFIG,
            gold_present_train_indices=indices, gold_present_row_ids=row_ids)
    infinite = copy.deepcopy(state)
    infinite["start.bias"][3] = float("inf")
    _raises("nonfinite control", subject.configuration, infinite, provenance)
    boolean = copy.deepcopy(state)
    boolean["end.bias"][3] = True
    _raises("nonfinite control", subject.configuration, boolean, provenance)
    bad_geometry = copy.deepcopy(provenance)
    bad_geometry["config"] = dict(provenance["config"])
    bad_geometry["config"]["residual_scale"] = float("nan")
    _raises("nonfinite control", subject.configuration, state, bad_geometry)
    bad_rate = copy.deepcopy(provenance)
    bad_rate["config"] = dict(provenance["config"])
    bad_rate["config"]["learning_rate"] = float("nan")
    _raises("nonfinite control", subject.configuration, state, bad_rate)
    _raises("nonfinite control", subject.configuration, state, provenance, margin_weight=float("nan"))
    _raises("matched margin arm required", subject.configuration, state, provenance, margin_weight=0.1)
    _raises("matched margin arm required", subject.configuration, state, provenance, margin_weight=True)
    incomplete = copy.deepcopy(provenance)
    incomplete.pop("donor_state_sha256")
    _raises("donor provenance required", subject.configuration, state, incomplete)
    extra = copy.deepcopy(provenance)
    extra["note"] = "missing-closed-provenance"
    _raises("donor provenance required", subject.configuration, state, extra)
    stale = copy.deepcopy(provenance)
    stale["donor_state_sha256"] = "0" * 64
    _raises("donor state provenance differs", subject.configuration, state, stale)
    donor = copy.deepcopy(provenance)
    donor["donor_role"] = "F15"
    _raises("F15 is the teacher, not the donor", subject.configuration, state, donor)
    teacher = copy.deepcopy(provenance)
    teacher["teacher_is_donor"] = True
    _raises("F15 teacher provenance required", subject.configuration, state, teacher)
    teacher_hash = copy.deepcopy(provenance)
    teacher_hash["teacher_model_state_sha256"] = "1" * 64
    _raises("F15 teacher provenance required", subject.configuration, state, teacher_hash)
    reused = copy.deepcopy(provenance)
    reused["old_frozen36_state_sha256"] = subject.frozen38_seal(state)
    _raises("frozen38 seal must be derived from the F18 donor", subject.configuration, state, reused)
    dev = copy.deepcopy(provenance)
    dev["partition"] = "DEV"
    _raises("TRAIN partition required", subject.configuration, state, dev)
    test_partition = copy.deepcopy(provenance)
    test_partition["partition"] = "TEST"
    _raises("TRAIN partition required", subject.scoring_preflight, _cases(provenance, _permissions()), _permissions(), test_partition, state)
    permissions = _permissions()
    permissions["count"] = 31
    permissions["ids"] = permissions["ids"][:-1]
    _raises("32 permission decisions required", subject.scoring_preflight, _cases(provenance, _permissions()), permissions, provenance, state)
    permissions = _permissions()
    permissions["scored"] = True
    _raises("32 permission decisions required", subject.scoring_preflight, _cases(provenance, permissions), permissions, provenance, state)
    short_cases = _cases(provenance, _permissions())[:-1]
    _raises("gold-present TRAIN row count required", subject.scoring_preflight, short_cases, _permissions(), provenance, state)
    swapped = _cases(provenance, _permissions())
    swapped[0], swapped[1] = swapped[1], swapped[0]
    _raises("gold-present TRAIN row count required", subject.scoring_preflight, swapped, _permissions(), provenance, state)
    dirty = _cases(provenance, _permissions())
    dirty[0] = dict(dirty[0])
    dirty[0]["extra"] = "not-closed"
    _raises("scoring provenance required", subject.scoring_preflight, dirty, _permissions(), provenance, state)
    bad_hex = _cases(provenance, _permissions())
    bad_hex[0] = dict(bad_hex[0])
    bad_hex[0]["full_ir_sha256"] = "zz" + "ab" * 31
    _raises("provenance required", subject.scoring_preflight, bad_hex, _permissions(), provenance, state)
    dev_case = _cases(provenance, _permissions())
    dev_case[3] = dict(dev_case[3])
    dev_case[3]["partition"] = "DEV"
    _raises("TRAIN partition required", subject.scoring_preflight, dev_case, _permissions(), provenance, state)


def test_scoring_preflight_freezes_caller_ids_and_does_not_score():
    state = _state()
    provenance = _provenance(state)
    permissions = _permissions()
    report = subject.scoring_preflight(_cases(provenance, permissions), permissions, provenance, state)
    assert report["schema"] == subject.SCORING_SCHEMA
    assert report["case_count"] == 72 and report["permission_count"] == 32
    assert report["partition"] == "TRAIN" and report["gold_present"] is True
    assert report["scoring_executed"] is False and report["casewise_retention_computed"] is False
    assert report["raw_and_joint_outputs_frozen_before_scoring"] is True
    assert report["training_executed"] is False and report["admitted"] is False and report["formalized"] is False
    assert report["permission_ids_sha256"] == f18.checkpoint_digest(permissions["ids"])
    _raises("executes no updates", subject.run_admitted_updates, state, provenance)
    _raises("does not score", subject.score_frozen_cases, _cases(provenance, permissions))


def test_zero_and_quarter_arms_keep_full_batch_ce_and_kl():
    import torch
    state = _state()
    provenance = copy.deepcopy(_provenance(state))
    records, indices, teacher, weights, output = _batch(provenance)
    assert len(indices) == 12 and len(provenance["gold_present_train_indices"]) == 72
    assert len(teacher["rows"]) == 168 and len(weights["rows"]) == 168
    zero = subject.compose_objective_for_state(
        torch, output, records, indices, teacher, weights, state, provenance, margin_weight=0.0)
    quarter = subject.compose_objective_for_state(
        torch, output, records, indices, teacher, weights, state, provenance, margin_weight=0.25)
    assert "_state" not in provenance
    assert zero["ce_batch_denominator"] == zero["weighted_CE"]["batch_denominator"] == 12
    assert zero["ce_outer_denominator"] == zero["weighted_CE"]["outer_denominator"] == 8
    assert zero["weighted_CE"]["modality_multiplier"] == 2
    assert zero["weighted_CE"]["actor_hinge_omitted"] is True
    assert zero["kl_temperature"] == 1 and zero["kl_coefficient"] == 1
    assert zero["kl_denominator"] == zero["retention"]["denominator"] == 72
    assert [row["conditions_facet_weight"] for row in zero["weighted_CE"]["rows"]] == [2, *([1] * 11)]
    expected_kl = 0.5 * math.log(1.5) + 0.5 * math.log(0.75)
    assert abs(zero["retention"]["value"] - expected_kl / 6) < 1e-5
    assert quarter["retention"]["denominator"] == 72
    assert quarter["weighted_CE"]["weighted_main_loss"] == zero["weighted_CE"]["weighted_main_loss"]
    assert quarter["retention"]["value"] == zero["retention"]["value"]
    assert torch.equal(zero["f18_ce_plus_kl"].detach(), quarter["f18_ce_plus_kl"].detach())
    assert float(zero["margin"]["weighted_loss"].detach()) == 0.0
    assert zero["margin"]["margin_computed"] is False and zero["margin"]["schema"] == margin.SCHEMA
    assert quarter["margin"]["weight"] == 0.25 and quarter["margin"]["margin_computed"] is True
    assert quarter["margin"]["batch_size"] == 12
    direct = margin.conditions_fullspan_margin_from_logits(
        torch, output["start"][:, 3, :], output["end"][:, 3, :],
        [{"token_count": 2, "present": True, "span": (0, 1)} for _ in records], weight=0.25)
    assert torch.allclose(quarter["margin"]["weighted_loss"], direct["weighted_loss"])
    assert torch.allclose(quarter["loss"].detach(), (quarter["f18_ce_plus_kl"] + quarter["margin"]["weighted_loss"]).detach())
    assert torch.allclose((quarter["loss"] - zero["loss"]).detach(), quarter["margin"]["weighted_loss"].detach())
    assert zero["optimizer_steps"] == 0 and zero["training_executed"] is False
    assert zero["model_execution_performed"] is False and quarter["model_execution_performed"] is False
    assert zero["margin"]["weighted_loss"].requires_grad and quarter["loss"].requires_grad
    dev = copy.deepcopy(records)
    dev[4] = dict(dev[4])
    dev[4]["partition"] = "DEV"
    _raises("TRAIN partition required", subject.compose_objective_for_state,
            torch, output, dev, indices, teacher, weights, state, provenance, margin_weight=0.0)
    short = records[:-1]
    _raises("full TRAIN batch row count required", subject.compose_objective_for_state,
            torch, output, short, indices[:-1], teacher, weights, state, provenance, margin_weight=0.25)
    _raises("nonfinite control", subject.compose_objective_for_state,
            torch, output, records, indices, teacher, weights, state, provenance, margin_weight=float("nan"))
    poisoned = {key: value for key, value in output.items()}
    poisoned["modality"] = torch.full((12, 3), float("nan"))
    _raises("finite", subject.compose_objective_for_state,
            torch, poisoned, records, indices, teacher, weights, state, provenance, margin_weight=0.0)


def test_original_f18_record_shape_and_mixed_168_schedule_preserve_all_72_present_rows():
    provenance = _provenance()
    population = dict(zip(*_population(), strict=True))
    seen, present_indices = [], []
    mixed_batches = 0
    for step in range(subject.TRAIN_INDEX_COUNT // subject.BATCH_SIZE):
        progress = {"epochs_completed": 0, "optimizer_steps": step, "row_cursor": step * subject.BATCH_SIZE}
        indices = f18.targeted._batch_indices(168, progress, 12, 1729)
        records = _records(provenance, indices, original_shape=True)
        assert all(set(row) == {"id", "source_text", "tokens", "labels", "latent"} for row in records)
        # The retained F18 source validator accepts the actual unsidecarred shape.
        for record in records:
            f18.targeted._actor_record(record)
        assert subject._bind_batch(records, indices, population) == records
        targets = subject._conditions_targets(records)
        assert len(targets) == 12
        present_count = sum(target["present"] for target in targets)
        mixed_batches += 0 < present_count < 12
        present_indices.extend(index for index, target in zip(indices, targets, strict=True) if target["present"])
        seen.extend(indices)
    assert sorted(seen) == list(range(168)) and len(set(seen)) == 168
    assert sorted(present_indices) == list(range(72))
    assert mixed_batches > 0


@pytest.mark.parametrize("bad_index", [True, 0.5, "0", -1, 168])
def test_batch_indices_and_optional_sidecars_are_typed(bad_index):
    provenance = _provenance()
    population = dict(zip(*_population(), strict=True))
    indices = list(range(12))
    records = _records(provenance, indices, original_shape=True)
    bad = list(indices)
    bad[0] = bad_index
    _raises("typed full TRAIN batch indices", subject._bind_batch, records, bad, population)
    duplicate = [0, *indices[:-1]]
    _raises("typed full TRAIN batch indices", subject._bind_batch, records, duplicate, population)
    for key, value, message in (
        ("partition", "DEV", "TRAIN partition"),
        ("training_index", True, "TRAIN index annotation"),
        ("training_index", 1, "TRAIN index annotation"),
        ("gold_present", 1, "TRAIN presence annotation"),
        ("gold_present", False, "TRAIN presence annotation"),
    ):
        tagged = copy.deepcopy(records)
        tagged[0][key] = value
        _raises(message, subject._bind_batch, tagged, indices, population)
    mislabeled = copy.deepcopy(records)
    mislabeled[0]["labels"]["presence"][3] = False
    _raises("gold-present TRAIN membership", subject._bind_batch, mislabeled, indices, population)
    wrong_id = copy.deepcopy(records)
    wrong_id[0]["id"] = "unbound-present-id"
    _raises("gold-present TRAIN membership", subject._bind_batch, wrong_id, indices, population)


@pytest.mark.parametrize("coordinates", [(True, 1), (0, 1.5), ("0", 1), (0,), None])
def test_conditions_targets_reject_boolean_fractional_and_malformed_coordinates(coordinates):
    record = _records(_provenance(), [0], original_shape=True)[0]
    record["labels"]["spans"][3] = coordinates
    _raises("integer conditions target geometry", subject._conditions_targets, [record])


@pytest.mark.parametrize("coordinates", [(-100, -100), (-1, 1), (3, 2), (0, 4)])
def test_present_conditions_targets_reject_sentinel_reversed_and_outside_spans(coordinates):
    record = _records(_provenance(), [0], original_shape=True)[0]
    record["labels"]["spans"][3] = coordinates
    _raises("present conditions span or absent sentinel", subject._conditions_targets, [record])


def test_absent_conditions_require_exact_sentinel_and_bounded_token_geometry():
    record = _records(_provenance(), [72], original_shape=True)[0]
    assert subject._conditions_targets([record]) == [{"token_count": 4, "present": False, "span": (-100, -100)}]
    for span_value in ((0, 1), (-100, 0), (-100.0, -100), (False, -100)):
        bad = copy.deepcopy(record)
        bad["labels"]["spans"][3] = span_value
        _raises("conditions", subject._conditions_targets, [bad])
    for count in (0, subject.MAX_CONDITIONS_TOKENS + 1):
        bad = copy.deepcopy(record)
        bad["tokens"] = [record["tokens"][0]] * count
        _raises("integer conditions target geometry", subject._conditions_targets, [bad])
    bad = copy.deepcopy(record)
    bad["labels"]["presence"][3] = 0
    _raises("conditions row 3", subject._conditions_targets, [bad])


def _synthetic_architecture_state():
    """Actual F18 architecture initialization; no checkpoint or donor payload."""
    import torch
    model = f18._model(torch, CONFIG)
    return {name: value.detach().tolist() for name, value in model.state_dict().items()}


def _same_bytes(left, right):
    import torch
    return torch.equal(left.detach().contiguous().reshape(-1).view(torch.uint8),
                       right.detach().contiguous().reshape(-1).view(torch.uint8))


def _assert_frozen_and_inactive(wired, before, *, steps):
    import torch
    named, optimizer = wired["named"], wired["optimizer"]
    assert len(subject.FROZEN) == 38 and len(subject.SELECTED) == 4
    inactive = [0, 1, 2, 4, 5]
    for name in subject.FROZEN:
        assert named[name].grad is None
        assert _same_bytes(named[name], before[name])
        assert named[name] not in optimizer.state
    for name in subject.SELECTED:
        parameter = named[name]
        assert _same_bytes(parameter[inactive], before[name][inactive])
        if parameter.grad is not None:
            assert torch.count_nonzero(parameter.grad[inactive]) == 0
        if steps:
            moments = optimizer.state[parameter]
            assert int(moments["step"]) == steps
            for key in ("exp_avg", "exp_avg_sq"):
                assert torch.count_nonzero(moments[key][inactive]) == 0


def test_actual_f18_forward_mixed_batch_preserves_ce_kl_and_row3_optimizer_partition():
    import torch
    state = _synthetic_architecture_state()
    provenance = _provenance(state)
    wired = subject.wire_optimizer(torch, state, provenance, margin_weight=0.25)
    before = {name: parameter.detach().clone() for name, parameter in wired["named"].items()}
    indices = [0, 73, 2, 75, 4, 77, 6, 79, 8, 81, 10, 83]
    records, indices, teacher, weights, _ = _batch(provenance, indices, original_shape=True)
    output = wired["model"](*span._batch(torch, records))
    zero = subject.compose_objective_for_state(
        torch, output, records, indices, teacher, weights, state, provenance, margin_weight=0.0)
    quarter = subject.compose_objective_for_state(
        torch, output, records, indices, teacher, weights, state, provenance, margin_weight=0.25)
    original, details = f18._loss(torch, output, records, indices,
                                 f18._policy("modality-conditions-retention-ce"), teacher, weights)
    assert _same_bytes(original, zero["f18_ce_plus_kl"])
    assert _same_bytes(original, quarter["f18_ce_plus_kl"])
    assert zero["weighted_CE"] == quarter["weighted_CE"] == details["weighted_CE"]
    assert zero["retention"] == quarter["retention"] == details["retention"]
    assert quarter["ce_batch_denominator"] == 12 and quarter["ce_outer_denominator"] == 8
    assert quarter["kl_denominator"] == 72 and quarter["margin"]["batch_size"] == 12
    assert quarter["margin"]["present_count"] == 6
    diagnostics = quarter["margin"]["row_diagnostics"]
    assert all(row["hinge"] == 0.0 and row["wrong_domain_count"] == 0
               for row in diagnostics if not row["present"])
    targets = subject._conditions_targets(records)
    present_rows = [index for index, target in enumerate(targets) if target["present"]]
    only_present = margin.conditions_fullspan_margin_from_logits(
        torch, output["start"][present_rows, 3, :], output["end"][present_rows, 3, :],
        [targets[index] for index in present_rows], weight=0.25)
    assert torch.allclose(quarter["margin"]["weighted_loss"], only_present["weighted_loss"] * 0.5)
    margin_gradients = torch.autograd.grad(quarter["margin"]["weighted_loss"],
                                         (output["start"], output["end"]), retain_graph=True)
    # Independently differentiate the detached wrong/gold boundary witnesses.
    # Shared endpoints cancel; only the endpoint pair must be nonzero jointly.
    expected_gradients = [torch.zeros_like(output[key]) for key in ("start", "end")]
    for index, row in enumerate(diagnostics):
        wrong = row["wrong_span"]
        if not row["present"] or wrong is None:
            assert row["hinge"] == 0.0
            continue
        gold = targets[index]["span"]
        starts, ends = output["start"].detach()[index, 3], output["end"].detach()[index, 3]
        hinge = float((1.0 + (starts[wrong[0]] + ends[wrong[1]]))
                      - (starts[gold[0]] + ends[gold[1]]))
        assert row["hinge"] == max(hinge, 0.0)
        if hinge > 0.0:  # ReLU's zero/negative branch contributes no derivative.
            for endpoint, expected in enumerate(expected_gradients):
                expected[index, 3, wrong[endpoint]] += 0.25 / 12
                expected[index, 3, gold[endpoint]] -= 0.25 / 12
    for gradient, expected in zip(margin_gradients, expected_gradients, strict=True):
        assert torch.equal(gradient, expected)
        assert torch.count_nonzero(gradient[:, [0, 1, 2, 4, 5], :]) == 0
        assert torch.count_nonzero(gradient[[1, 3, 5, 7, 9, 11], 3, :]) == 0
    assert sum(int(torch.count_nonzero(gradient[present_rows, 3, :])) for gradient in margin_gradients) > 0
    quarter["loss"].backward()
    assert any(torch.count_nonzero(parameter.grad[3]) > 0 for parameter in wired["selected"])
    _assert_frozen_and_inactive(wired, before, steps=0)
    subject.clip_selected_gradients(torch, wired["selected"])
    wired["optimizer"].step()
    _assert_frozen_and_inactive(wired, before, steps=1)
    assert any(not _same_bytes(wired["named"][name][3], before[name][3]) for name in subject.SELECTED)
    assert all(value == 1 for value in wired["model"]._actor_forward_accounting.values())
    assert all(value == 1 for value in wired["model"]._conditions_forward_accounting.values())


def test_actual_f18_all_absent_margin_is_connected_zero_with_full_batch_denominators():
    import torch
    state = _synthetic_architecture_state()
    provenance = _provenance(state)
    wired = subject.wire_optimizer(torch, state, provenance)
    records, indices, teacher, weights, _ = _batch(provenance, range(72, 84), original_shape=True)
    output = wired["model"](*span._batch(torch, records))
    result = subject.compose_objective_for_state(
        torch, output, records, indices, teacher, weights, state, provenance, margin_weight=0.25)
    term = result["margin"]["weighted_loss"]
    assert term.requires_grad and float(term.detach()) == 0.0
    assert result["margin"]["present_count"] == 0 and result["margin"]["batch_size"] == 12
    assert result["weighted_CE"]["batch_denominator"] == 12 and result["retention"]["denominator"] == 72
    gradients = torch.autograd.grad(term, wired["selected"], retain_graph=True)
    assert all(torch.count_nonzero(gradient) == 0 for gradient in gradients)
    result["loss"].backward()
    assert all(parameter.grad is not None and torch.count_nonzero(parameter.grad) == 0
               for parameter in wired["selected"])
    assert all(wired["named"][name].grad is None for name in subject.FROZEN)
    assert wired["optimizer"].state == {}


def test_synthetic_in_memory_adam_resume_matches_uninterrupted_actual_f18_updates():
    import torch
    state = _synthetic_architecture_state()
    provenance = _provenance(state)
    uninterrupted = subject.wire_optimizer(torch, state, provenance)
    interrupted = subject.wire_optimizer(torch, state, provenance)
    before = {name: parameter.detach().clone() for name, parameter in uninterrupted["named"].items()}

    def step(wired, cursor):
        progress = {"epochs_completed": 0, "optimizer_steps": cursor // 12, "row_cursor": cursor}
        indices = f18.targeted._batch_indices(168, progress, 12, 1729)
        records, indices, teacher, weights, _ = _batch(provenance, indices, original_shape=True)
        wired["optimizer"].zero_grad(set_to_none=True)
        output = wired["model"](*span._batch(torch, records))
        result = subject.compose_objective_for_state(
            torch, output, records, indices, teacher, weights, state, provenance, margin_weight=0.25)
        result["loss"].backward()
        subject.clip_selected_gradients(torch, wired["selected"])
        wired["optimizer"].step()

    step(uninterrupted, 0)
    step(uninterrupted, 12)
    step(interrupted, 0)
    # Only in-memory synthetic state is restored: no checkpoint I/O or claim
    # about the product's still-unadmitted fit/resume runner is made here.
    saved_model = copy.deepcopy(interrupted["model"].state_dict())
    saved_adam = copy.deepcopy(interrupted["optimizer"].state_dict())
    resumed = subject.wire_optimizer(torch, state, provenance)
    resumed["model"].load_state_dict(saved_model, strict=True)
    resumed["optimizer"].load_state_dict(saved_adam)
    step(resumed, 12)
    for name in f18.MODEL_PARAMETER_NAMES:
        assert _same_bytes(uninterrupted["named"][name], resumed["named"][name])
    for left, right in zip(uninterrupted["selected"], resumed["selected"], strict=True):
        for key in ("step", "exp_avg", "exp_avg_sq"):
            assert _same_bytes(uninterrupted["optimizer"].state[left][key], resumed["optimizer"].state[right][key])
    _assert_frozen_and_inactive(uninterrupted, before, steps=2)
    _assert_frozen_and_inactive(resumed, before, steps=2)
    final_state = {name: value.detach().tolist() for name, value in resumed["model"].state_dict().items()}
    assert subject.frozen38_seal(final_state) == subject.frozen38_seal(state)


def test_fresh_adam_updates_only_conditions_row_of_the_four_tensors():
    import torch
    parameter = torch.nn.Parameter(torch.zeros(6, dtype=torch.float32))
    parameter.grad = torch.full((6,), float("nan"))
    _raises("nonfinite control", subject.clip_selected_gradients, torch, [parameter])

    state = _state()
    original_pointer = copy.deepcopy(state["start.weight"])
    original_modality = copy.deepcopy(state["modality.weight"])
    provenance = _provenance(state)
    ambient = torch.get_rng_state().clone()
    wired = subject.wire_optimizer(torch, state, provenance, selection=subject.selection_mask_contract(), margin_weight=0.0)
    assert torch.equal(ambient, torch.get_rng_state())
    assert state["start.weight"] == original_pointer and state["modality.weight"] == original_modality
    model, optimizer, selected = wired["model"], wired["optimizer"], wired["selected"]
    assert wired["optimizer_steps"] == 0 and wired["model_forwards"] == 0 and wired["training_executed"] is False
    assert model.training is False
    assert sum(model._actor_forward_accounting.values()) == 0
    assert sum(model._conditions_forward_accounting.values()) == 0
    named = wired["named"]
    assert tuple(parameter for parameter in named if named[parameter].requires_grad) == subject.SELECTED
    assert [tuple(parameter.shape) for parameter in selected] == [(6, 64), (6,), (6, 64), (6,)]
    assert [parameter is named[name] for parameter, name in zip(selected, subject.SELECTED, strict=True)] == [True, True, True, True]
    optimized = [parameter for group in optimizer.param_groups for parameter in group["params"]]
    assert [id(parameter) for parameter in optimized] == [id(parameter) for parameter in selected]
    defaults = optimizer.defaults
    assert defaults["lr"] == 0.001 and defaults["betas"] == (0.9, 0.999)
    assert defaults["eps"] == 1e-8 and defaults["weight_decay"] == 0.0 and defaults["foreach"] is False
    assert optimizer.state == {}
    optimized_ids = {id(parameter) for parameter in optimized}
    for name in subject.FROZEN:
        assert named[name].requires_grad is False and named[name].grad is None
        assert id(named[name]) not in optimized_ids
    assert named["modality.weight"].requires_grad is False and named["modality.bias"].requires_grad is False
    before = {name: parameter.detach().clone() for name, parameter in named.items()}
    loss = sum(parameter.sum() for parameter in selected)
    loss.backward()
    for parameter in selected:
        assert parameter.grad is not None and bool(torch.isfinite(parameter.grad).all())
        assert torch.equal(parameter.grad[3], torch.ones_like(parameter.grad[3]))
        for row in (0, 1, 2, 4, 5):
            assert torch.count_nonzero(parameter.grad[row]) == 0
    for name in subject.FROZEN:
        assert named[name].grad is None
    norm = subject.clip_selected_gradients(torch, selected)
    assert bool(torch.isfinite(norm))
    optimizer.step()
    for name in subject.FROZEN:
        assert torch.equal(named[name].detach(), before[name])
    for parameter, name in zip(selected, subject.SELECTED, strict=True):
        assert torch.equal(parameter.detach()[:3], before[name][:3])
        assert torch.equal(parameter.detach()[4:], before[name][4:])
        assert not torch.equal(parameter.detach()[3], before[name][3])
        moment = optimizer.state[parameter]
        assert int(moment["step"]) == 1
        for key in ("exp_avg", "exp_avg_sq"):
            assert torch.count_nonzero(moment[key][3]) > 0
            for row in (0, 1, 2, 4, 5):
                assert torch.count_nonzero(moment[key][row]) == 0
    assert sum(model._actor_forward_accounting.values()) == 0
    assert sum(model._conditions_forward_accounting.values()) == 0
    assert state["start.weight"] == original_pointer
    assert wired["configuration"]["model_optimizer_wiring"]["optimizer"]["max_updates"] == 32
    assert wired["configuration"]["model_optimizer_wiring"]["optimizer"]["inherited_moments"] is False
    assert wired["configuration"]["model_optimizer_wiring"]["margin_arms"] == [0.0, 0.25]
    assert wired["configuration"]["model_optimizer_wiring"]["margin_weight"] == 0.0
