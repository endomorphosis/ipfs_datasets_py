"""Opt-in F18 four-tensor conditions full-span training profile.

Composes the unchanged F18 modality/conditions owner and the published
conditions full-span margin kernel. A caller supplies the authenticated
42-tensor F18 state. This profile copies that state, freezes the other 38
tensors including modality, and wires a fresh ordered Adam on
``start.weight``, ``start.bias``, ``end.weight`` and ``end.bias``. Only
conditions row 3 is active: 130 of 780 stored scalars. The frozen38 seal is
the digest of those 38 F18 donor tensors. F15 remains the masked-KL teacher
and is never the donor. The old F15-origin frozen36 seal is not reused.

No encoder forward, checkpoint write, historical census or optimizer step
runs here. Matched coefficient 0 and 0.25 fits stay separately admitted.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re

from ipfs_datasets_py.logic.legal_ir.conditions_fullspan_margin_v1 import (
    MAX_TOKENS as MAX_CONDITIONS_TOKENS,
    SCHEMA as MARGIN_SCHEMA,
    conditions_fullspan_margin_from_logits,
)
from . import legal_span_modality_conditions_retention as f18

SCHEMA = "conditions-fullspan-f18-four-tensor-training/v1"
CONFIG_SCHEMA = "conditions-fullspan-f18-four-tensor-configuration/v1"
PROVENANCE_SCHEMA = "conditions-fullspan-f18-donor-provenance/v1"
SCORING_SCHEMA = "conditions-fullspan-frozen-full-ir-scoring-preflight/v1"
PERMISSION_SCHEMA = "conditions-fullspan-frozen-permission-panel/v1"
PREPARATION_SCHEMA = "legal-ir-programme-engineering-preparation/v1"
TASK_ID = "LIRAE-LIR17-PROFILE-03"
PROFILE_ID = "LIR-17.conditions-fullspan-training-preparation-v1"
SELECTED = f18.ORIGINAL_POINTER_NAMES
CONDITIONS_ROW = 3
INACTIVE_ROWS = (0, 1, 2, 4, 5)
DONOR_TENSOR_COUNT = 42
FROZEN_TENSOR_COUNT = 38
STORED_SCALARS = 780
ACTIVE_SCALARS = 130
INACTIVE_SCALARS = 650
GOLD_PRESENT_TRAIN_ROWS = 72
TRAIN_INDEX_COUNT = 168
PERMISSION_COUNT = 32
BATCH_SIZE = 12
SEED = 1729
MAX_UPDATES = 32
LEARNING_RATE = 0.001
ADAM_BETAS = (0.9, 0.999)
ADAM_EPS = 1e-8
WEIGHT_DECAY = 0.0
GRADIENT_CLIP_NORM = 5.0
KL_TEMPERATURE = 1.0
KL_COEFFICIENT = 1.0
KL_BLOCKS = 6
CE_OUTER_DENOMINATOR = 8
CE_MODALITY_MULTIPLIER = 2
MARGIN_ARMS = (0.0, 0.25)
MAX_FLOAT32 = 3.4028234663852886e38
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ROOT = Path(__file__).resolve().parents[3]
FROZEN = tuple(name for name in f18.MODEL_PARAMETER_NAMES if name not in SELECTED)
REUSE_PINS = {
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_modality_conditions_retention.py": (
        "F18 model and authenticated donor state",
        "fb7449d4794ca9a279b2df2ea533b89d360344ff786edc0798395ab799db1823",
    ),
    "ipfs_datasets_py/logic/legal_ir/conditions_fullspan_margin_v1.py": (
        "published conditions full-span margin kernel",
        "e4f16146cf6f64b16e979e5ee0803a41ee41a8377bfa7833918b0a25dd7d1160",
    ),
    "ipfs_datasets_py/logic/legal_ir/structured_span_objective.py": (
        "unchanged structured-span objective",
        "68a459fe5271248ee478ae05767396842c1e1b83e33971b980c77b1afd3f8c84",
    ),
    "tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_modality_conditions_retention_contracts.py": (
        "unchanged F18 contract tests",
        "3094d9fd2bd7f409a913d4096557e9a342c8c79214c5810f7a6980b33f204c58",
    ),
    "tests/unit/logic/legal_ir/test_conditions_fullspan_margin_v1.py": (
        "unchanged margin-kernel tests",
        "461877c74b2b5661778fc853352db4e90c10f5b8127f9adb457cbf760b70bb27",
    ),
}
_PARENT_REFERENCE = {
    "repository": "ipfs_datasets_py",
    "revision": "eb023a439a23c59acdfaf485c66127f5202ecc8f",
    "path": "ipfs_datasets_py/logic/autoformal/docs/BACKLOG.json",
    "task_id": "LIR-17",
    "task_sha256": "1866c540278ad4270adc7c6b5ee938fec8128a0501cf6388161ce12a5c38a612",
}
_SOURCE_BINDING = {
    "repository": "ipfs_datasets_py",
    "public_main_commit": "eb023a439a23c59acdfaf485c66127f5202ecc8f",
    "backlog_path": "ipfs_datasets_py/logic/autoformal/docs/BACKLOG.json",
    "backlog_sha256": "d1f74b427c3a7b27988a1d174f258fa6e867b681178978b90c611f4088ff401a",
}
_IMPLEMENTATION_ROUTE = {
    "primary_provider_id": "grok_cli",
    "primary_model_id": "grok-4.7",
    "fallback_provider_id": "codex",
    "fallback_model_id": "gpt-6.1-sol",
    "fallback_trigger": "primary_quota_exhausted",
    "fallback_reasoning_effort": "high",
}
_PROVENANCE_KEYS = {
    "schema", "donor_role", "donor_schema", "donor_lineage_id", "donor_state_sha256",
    "teacher_role", "teacher_checkpoint_sha256", "teacher_model_state_sha256",
    "teacher_is_donor", "partition", "gold_present_train_indices", "gold_present_row_ids",
    "config", "old_frozen36_state_sha256",
}
_CONFIG_KEYS = {
    "hidden_size", "embedding_dim", "projection_width", "latent_dimension", "latent_enabled",
    "residual_scale", "seed", "batch_size", "learning_rate",
}
_CASE_KEYS = {
    "id", "partition", "gold_present", "training_index", "full_ir_sha256",
    "raw_output_sha256", "joint_output_sha256", "permission_ids_sha256",
}


def _require(value, message):
    if not value:
        raise ValueError(message)


def _shape_table(embedding_dim, projection_width):
    """Shapes of the live F18 42-tensor module at the fixed width-64 head."""
    width, hidden, encoded = embedding_dim, 32, 64
    feature = {
        "byte_embedding.weight": (257, width),
        "token_projection.weight": (width * 2, width * 3 + 1),
        "token_projection.bias": (width * 2,),
        "encoder.weight_ih_l0": (3 * hidden, width * 2),
        "encoder.weight_hh_l0": (3 * hidden, hidden),
        "encoder.bias_ih_l0": (3 * hidden,),
        "encoder.bias_hh_l0": (3 * hidden,),
        "encoder.weight_ih_l0_reverse": (3 * hidden, width * 2),
        "encoder.weight_hh_l0_reverse": (3 * hidden, hidden),
        "encoder.bias_ih_l0_reverse": (3 * hidden,),
        "encoder.bias_hh_l0_reverse": (3 * hidden,),
    }
    table = {
        **feature,
        "modality.weight": (3, encoded),
        "modality.bias": (3,),
        "presence.weight": (8, encoded),
        "presence.bias": (8,),
        "start.weight": (6, encoded),
        "start.bias": (6,),
        "end.weight": (6, encoded),
        "end.bias": (6,),
        "latent_down.weight": (projection_width, 384),
        "latent_down.bias": (projection_width,),
        "latent_up.weight": (encoded, projection_width),
        "latent_up.bias": (encoded,),
        "actor_start.weight": (6, encoded),
        "actor_start.bias": (6,),
        "actor_end.weight": (6, encoded),
        "actor_end.bias": (6,),
        "actor_attention.query": (encoded,),
        "actor_context.gate": (encoded,),
        "conditions_presence.weight": (8, encoded),
        "conditions_presence.bias": (8,),
    }
    for name, shape in feature.items():
        table["span_" + name] = shape
    _require(set(table) == set(f18.MODEL_PARAMETER_NAMES), "F18 42-tensor shape table differs")
    return {name: table[name] for name in f18.MODEL_PARAMETER_NAMES}


def _reuse_owners():
    owners = []
    for path, (role, digest) in REUSE_PINS.items():
        file = _ROOT / path
        _require(file.is_file() and not file.is_symlink(), "retained owner missing: " + path)
        actual = hashlib.sha256(file.read_bytes()).hexdigest()
        _require(actual == digest, "retained F18/kernel/objective bytes differ: " + path)
        owners.append({"path": path, "role": role, "sha256": actual})
    return owners


def _finite_tree(value, shape, label):
    if shape:
        _require(type(value) is list and len(value) == shape[0], "exact tensor shape required: " + label)
        for child in value:
            _finite_tree(child, shape[1:], label)
        return
    _require(type(value) in (int, float), "nonfinite control: " + label)
    _require(math.isfinite(value) and abs(value) <= MAX_FLOAT32, "nonfinite control: " + label)


def _donor_shapes(config):
    _require(type(config) is dict and set(config) == _CONFIG_KEYS, "closed F18 geometry provenance required")
    _require(config["hidden_size"] == 32 and config["latent_dimension"] == 384
             and config["latent_enabled"] is False and config["seed"] == SEED
             and config["batch_size"] == BATCH_SIZE, "fixed F18 width/latent/batch provenance required")
    _require(type(config["embedding_dim"]) is int and 4 <= config["embedding_dim"] <= 64
             and type(config["projection_width"]) is int and 4 <= config["projection_width"] <= 128,
             "exact tensor shape required: F18 feature width")
    _require(type(config["residual_scale"]) in (int, float) and math.isfinite(config["residual_scale"])
             and 0 < config["residual_scale"] <= 1 and config["learning_rate"] == LEARNING_RATE,
             "nonfinite control: F18 geometry")
    return _shape_table(config["embedding_dim"], config["projection_width"])


def _validate_state(state, shapes):
    _require(type(state) is dict and set(state) == set(f18.MODEL_PARAMETER_NAMES),
             "closed42 F18 donor state required")
    for name, shape in shapes.items():
        _finite_tree(state[name], shape, name)
    stored = sum(math.prod(shapes[name]) for name in SELECTED)
    active = sum(shapes[name][1] if name.endswith("weight") else 1 for name in SELECTED)
    _require((len(f18.MODEL_PARAMETER_NAMES), len(FROZEN), stored, active, stored - active)
             == (DONOR_TENSOR_COUNT, FROZEN_TENSOR_COUNT, STORED_SCALARS, ACTIVE_SCALARS, INACTIVE_SCALARS),
             "130/780/650 scalar count required")
    _require(all(shapes[name][0] == 6 and CONDITIONS_ROW in range(shapes[name][0]) for name in SELECTED),
             "conditions row 3 selection required")


def frozen38_seal(state):
    """Digest the 38 frozen F18 donor tensors, including modality."""
    _require(type(state) is dict and set(f18.MODEL_PARAMETER_NAMES) <= set(state),
             "closed42 F18 donor state required")
    return f18.checkpoint_digest({name: state[name] for name in FROZEN})


def frozen36_digest(state):
    """The old F15-origin/F18 frozen36 digest. It is not this profile's seal."""
    _require(type(state) is dict and set(f18.BASE_PARAMETER_NAMES) <= set(state),
             "closed42 F18 donor state required")
    return f18.checkpoint_digest({name: state[name] for name in f18.BASE_PARAMETER_NAMES})


def _sha256_text(value):
    _require(type(value) is str and _SHA.fullmatch(value), "donor provenance required")
    return value


def _gold_population(indices, row_ids):
    _require(type(indices) is list and type(row_ids) is list
             and len(indices) == len(row_ids) == GOLD_PRESENT_TRAIN_ROWS,
             "gold-present TRAIN row count required")
    _require(len(set(indices)) == GOLD_PRESENT_TRAIN_ROWS
             and all(type(index) is int and 0 <= index < TRAIN_INDEX_COUNT for index in indices)
             and indices == sorted(indices), "gold-present TRAIN row count required")
    _require(len(set(row_ids)) == GOLD_PRESENT_TRAIN_ROWS
             and all(type(row_id) is str and row_id for row_id in row_ids),
             "gold-present TRAIN row count required")
    return {index: row_id for index, row_id in zip(indices, row_ids, strict=True)}


def _validate_provenance(provenance, state):
    _require(type(provenance) is dict and set(provenance) == _PROVENANCE_KEYS, "donor provenance required")
    _require(provenance["schema"] == PROVENANCE_SCHEMA, "donor provenance required")
    _require(provenance["donor_role"] == "F18" and provenance["donor_schema"] == f18.SCHEMA
             and provenance["donor_lineage_id"] == f18.LINEAGE_ID, "F15 is the teacher, not the donor")
    _require(provenance["teacher_role"] == "F15" and provenance["teacher_is_donor"] is False
             and provenance["teacher_checkpoint_sha256"] == f18.SOURCE_ACTOR_REFINEMENT_SHA256
             and provenance["teacher_model_state_sha256"] == f18.SOURCE_ACTOR_REFINEMENT_MODEL_SHA256,
             "F15 teacher provenance required")
    _require(provenance["partition"] == "TRAIN", "TRAIN partition required")
    shapes = _donor_shapes(provenance["config"])
    _validate_state(state, shapes)
    digest = f18.checkpoint_digest({name: state[name] for name in f18.MODEL_PARAMETER_NAMES})
    _require(_sha256_text(provenance["donor_state_sha256"]) == digest, "donor state provenance differs")
    _require(digest != f18.SOURCE_ACTOR_REFINEMENT_MODEL_SHA256, "F15 is the teacher, not the donor")
    seal = frozen38_seal(state)
    old_seal = frozen36_digest(state)
    _require(_sha256_text(provenance["old_frozen36_state_sha256"]) == old_seal and seal != old_seal,
             "frozen38 seal must be derived from the F18 donor")
    population = _gold_population(provenance["gold_present_train_indices"], provenance["gold_present_row_ids"])
    return shapes, digest, seal, old_seal, population


def selection_mask_contract():
    active = {name: [CONDITIONS_ROW] for name in SELECTED}
    inactive = {name: list(INACTIVE_ROWS) for name in SELECTED}
    return {
        "schema": "conditions-fullspan-f18-row3-selection/v1",
        "optimizer_parameter_order": list(SELECTED),
        "active_rows": active,
        "inactive_rows": inactive,
        "active_scalar_count": ACTIVE_SCALARS,
        "stored_scalar_count": STORED_SCALARS,
        "inactive_scalar_count": INACTIVE_SCALARS,
        "donor_tensor_count": DONOR_TENSOR_COUNT,
        "frozen_tensor_count": FROZEN_TENSOR_COUNT,
        "frozen_parameter_names": list(FROZEN),
        "modality_frozen": True,
        "conditions_row": CONDITIONS_ROW,
    }


def donor_provenance(state, *, config, gold_present_train_indices, gold_present_row_ids):
    """Closed provenance for one caller-supplied F18 state. Does not fit."""
    shapes = _donor_shapes(config)
    _validate_state(state, shapes)
    _gold_population(gold_present_train_indices, gold_present_row_ids)
    return {
        "schema": PROVENANCE_SCHEMA,
        "donor_role": "F18",
        "donor_schema": f18.SCHEMA,
        "donor_lineage_id": f18.LINEAGE_ID,
        "donor_state_sha256": f18.checkpoint_digest({name: state[name] for name in f18.MODEL_PARAMETER_NAMES}),
        "teacher_role": "F15",
        "teacher_checkpoint_sha256": f18.SOURCE_ACTOR_REFINEMENT_SHA256,
        "teacher_model_state_sha256": f18.SOURCE_ACTOR_REFINEMENT_MODEL_SHA256,
        "teacher_is_donor": False,
        "partition": "TRAIN",
        "gold_present_train_indices": list(gold_present_train_indices),
        "gold_present_row_ids": list(gold_present_row_ids),
        "config": {key: config[key] for key in sorted(_CONFIG_KEYS)},
        "old_frozen36_state_sha256": frozen36_digest(state),
    }


def configuration(state, provenance, *, selection=None, margin_weight=0.25):
    """Versioned model/optimizer configuration. Does not construct Torch or step."""
    if selection is not None:
        _require(selection == selection_mask_contract(), "conditions row 3 selection required")
    _require(type(margin_weight) in (int, float) and margin_weight in MARGIN_ARMS,
             "nonfinite control: matched margin arm required" if type(margin_weight) is float
             and not math.isfinite(margin_weight) else "matched margin arm required")
    owners = _reuse_owners()
    _, digest, seal, old_seal, population = _validate_provenance(provenance, state)
    contract = selection_mask_contract()
    return {
        "schema": CONFIG_SCHEMA,
        "profile_id": PROFILE_ID,
        "profile_schema": SCHEMA,
        "state_provenance": {
            "donor_role": "F18",
            "donor_schema": f18.SCHEMA,
            "donor_lineage_id": f18.LINEAGE_ID,
            "donor_tensor_count": DONOR_TENSOR_COUNT,
            "donor_state_sha256": digest,
            "teacher_role": "F15",
            "teacher_is_donor": False,
            "teacher_checkpoint_sha256": f18.SOURCE_ACTOR_REFINEMENT_SHA256,
            "teacher_model_state_sha256": f18.SOURCE_ACTOR_REFINEMENT_MODEL_SHA256,
            "partition": "TRAIN",
            "gold_present_train_rows": GOLD_PRESENT_TRAIN_ROWS,
            "gold_present_index_sha256": f18.checkpoint_digest(provenance["gold_present_train_indices"]),
            "frozen38_state_sha256": seal,
            "old_frozen36_state_sha256": old_seal,
            "frozen38_derived_from_f18_donor": True,
            "frozen36_reused_as_seal": False,
            "population_ids": population,
        },
        "model_optimizer_wiring": {
            "model_owner": "legal_span_modality_conditions_retention._model",
            "state_owner": "caller-supplied authenticated F18 42-tensor state",
            "optimizer": {
                "name": "Adam",
                "parameter_order": list(SELECTED),
                "learning_rate": LEARNING_RATE,
                "betas": list(ADAM_BETAS),
                "eps": ADAM_EPS,
                "weight_decay": WEIGHT_DECAY,
                "foreach": False,
                "gradient_clip_norm": GRADIENT_CLIP_NORM,
                "inherited_moments": False,
                "max_updates": MAX_UPDATES,
            },
            "seed": SEED,
            "batch_size": BATCH_SIZE,
            "training_row_count": TRAIN_INDEX_COUNT,
            "batch_order_owner": "legal_span_targeted_loss._batch_indices(168, progress, 12, 1729)",
            "absent_conditions_margin": "connected_zero_in_full_batch_mean",
            "latent_enabled": False,
            "margin_arms": list(MARGIN_ARMS),
            "margin_schema": MARGIN_SCHEMA,
            "margin_weight": float(margin_weight),
            "ce": {
                "owner": "legal_span_modality_conditions_retention._loss",
                "association": "(2*mean_modality_CE+sum_of_six_facet_means_with_existing_conditions_row_weight)/8",
                "batch_denominator": BATCH_SIZE,
                "outer_denominator": CE_OUTER_DENOMINATOR,
                "modality_multiplier": CE_MODALITY_MULTIPLIER,
                "full_batch_mean": True,
                "actor_hinge_omitted": True,
            },
            "kl": {
                "owner": "legal_span_modality_conditions_retention._retention_loss",
                "teacher_role": "F15",
                "temperature": KL_TEMPERATURE,
                "coefficient": KL_COEFFICIENT,
                "blocks": KL_BLOCKS,
                "denominator": KL_BLOCKS * BATCH_SIZE,
                "normalization": "sum_masked_row_block_KL_divide_6_times_full_batch",
            },
            "optimizer_steps": 0,
            "model_forwards": 0,
        },
        "selection_mask_contract": contract,
        "reuse_owners": owners,
        "training_executed": False,
        "model_execution_performed": False,
        "encoder_executed": False,
        "checkpoint_mutated": False,
        "admitted": False,
        "formalized": False,
        "semantic_review_performed": False,
        "model_gain_claimed": False,
        "qualified": False,
    }


def _mask_gradient(gradient, active_row):
    # The loss may touch every stored coordinate. Adam must still see exact
    # zero on the 650 inactive scalars so those rows stay byte-identical.
    masked = gradient.clone()
    _require(masked.ndim >= 1 and masked.shape[0] == 6 and active_row == CONDITIONS_ROW,
             "conditions row 3 selection required")
    for index in range(masked.shape[0]):
        if index != active_row:
            masked[index] = 0
    return masked


def wire_optimizer(torch, state, provenance, *, selection=None, margin_weight=0.25):
    """Load the caller-supplied F18 state and wire a fresh four-tensor Adam.

    The F18 module builds the architecture. This function copies tensors into
    that module, freezes 38 parameters, and does not forward or step.
    """
    prepared = configuration(state, provenance, selection=selection, margin_weight=margin_weight)
    config = provenance["config"]
    model = f18._model(torch, config)
    template = model.state_dict()
    expected = _donor_shapes(config)
    _require(set(template) == set(f18.MODEL_PARAMETER_NAMES), "closed42 F18 donor state required")
    for name, shape in expected.items():
        _require(tuple(template[name].shape) == shape, "exact tensor shape required: " + name)
    loaded = {name: torch.tensor(state[name], dtype=torch.float32) for name in f18.MODEL_PARAMETER_NAMES}
    model.load_state_dict(loaded, strict=True)
    named = dict(model.named_parameters())
    _require(tuple(named) == f18.MODEL_PARAMETER_NAMES and len({id(parameter) for parameter in named.values()}) == 42,
             "closed42 F18 donor state required")
    for name, parameter in named.items():
        parameter.requires_grad_(name in SELECTED)
        parameter.grad = None
        if name in SELECTED:
            parameter.register_hook(lambda gradient, row=CONDITIONS_ROW: _mask_gradient(gradient, row))
    selected = [named[name] for name in SELECTED]
    optimizer = torch.optim.Adam(selected, lr=LEARNING_RATE, betas=ADAM_BETAS, eps=ADAM_EPS,
                                  weight_decay=WEIGHT_DECAY, foreach=False)
    _require(optimizer.state == {} and optimizer.defaults["lr"] == LEARNING_RATE
             and optimizer.defaults["betas"] == ADAM_BETAS and optimizer.defaults["eps"] == ADAM_EPS
             and optimizer.defaults["weight_decay"] == WEIGHT_DECAY and optimizer.defaults["foreach"] is False,
             "fresh ordered four-tensor Adam required")
    model.eval()
    forwards = 0
    for accounting in (getattr(model, "_actor_forward_accounting", {}), getattr(model, "_conditions_forward_accounting", {})):
        forwards += sum(accounting.values())
    _require(forwards == 0, "encoder execution is outside this profile")
    return {
        "configuration": prepared,
        "model": model,
        "optimizer": optimizer,
        "named": named,
        "selected": selected,
        "optimizer_steps": 0,
        "model_forwards": 0,
        "training_executed": False,
    }


def clip_selected_gradients(torch, selected):
    try:
        norm = torch.nn.utils.clip_grad_norm_(selected, GRADIENT_CLIP_NORM, error_if_nonfinite=True)
    except RuntimeError as error:
        raise ValueError("nonfinite control") from error
    _require(bool(torch.isfinite(norm)), "nonfinite control")
    return norm


def _bind_batch(records, indices, population):
    _require(type(records) is list and type(indices) is list and len(records) == len(indices) == BATCH_SIZE,
             "full TRAIN batch row count required")
    _require(all(type(index) is int and 0 <= index < TRAIN_INDEX_COUNT for index in indices)
             and len(set(indices)) == BATCH_SIZE, "typed full TRAIN batch indices required")
    bound = []
    for record, index in zip(records, indices, strict=True):
        _require(type(record) is dict and type(record.get("id")) is str and record["id"],
                 "TRAIN record identity required")
        labels = record.get("labels")
        presence = labels.get("presence") if type(labels) is dict else None
        _require(type(presence) in (list, tuple) and len(presence) == 6
                 and all(type(value) is bool for value in presence), "typed TRAIN presence labels required")
        present = presence[CONDITIONS_ROW]
        _require((present and population.get(index) == record["id"])
                 or (not present and index not in population and record["id"] not in population.values()),
                 "gold-present TRAIN membership differs")
        # Original F18 records have no partition/gold_present/training_index
        # sidecars: indices travel separately, and its immutable teacher/weight
        # tables bind each selected record. Reject conflicting optional tags.
        if "partition" in record:
            _require(record["partition"] == "TRAIN", "TRAIN partition required")
        if "training_index" in record:
            _require(type(record["training_index"]) is int and record["training_index"] == index,
                     "TRAIN index annotation differs")
        if "gold_present" in record:
            _require(type(record["gold_present"]) is bool and record["gold_present"] is present,
                     "TRAIN presence annotation differs")
        bound.append(record)
    return bound


def _conditions_targets(records):
    targets = []
    for record in records:
        _require(type(record) is dict and type(record.get("tokens")) in (list, tuple),
                 "conditions token geometry required")
        labels = record.get("labels")
        presence = labels.get("presence") if type(labels) is dict else None
        spans = labels.get("spans") if type(labels) is dict else None
        _require(type(presence) in (list, tuple) and len(presence) == 6
                 and all(type(value) is bool for value in presence)
                 and type(spans) in (list, tuple) and len(spans) == 6,
                 "conditions row 3 selection required")
        count, present, span = len(record["tokens"]), presence[CONDITIONS_ROW], spans[CONDITIONS_ROW]
        _require(1 <= count <= MAX_CONDITIONS_TOKENS and type(span) in (list, tuple) and len(span) == 2
                 and all(type(value) is int for value in span), "integer conditions target geometry required")
        left, right = span
        _require((0 <= left <= right < count) if present else (left, right) == (-100, -100),
                 "present conditions span or absent sentinel required")
        targets.append({"token_count": count, "present": present, "span": (left, right)})
    return targets


def compose_objective(torch, output, records, indices, teacher, weights, state, provenance, *, margin_weight=0.25):
    """Add the published margin on conditions row 3 to unchanged F18 CE and F15 KL.

    ``legal_span_modality_conditions_retention._loss`` remains the CE/KL
    implementation. The donor state authenticates provenance and is not stored
    inside that document. This function does not renormalize CE/KL and does not step.
    """
    _require(type(margin_weight) in (int, float) and math.isfinite(margin_weight) and margin_weight in MARGIN_ARMS,
             "nonfinite control: matched margin arm required")
    _require(type(provenance) is dict and "_state" not in provenance, "donor provenance required")
    _, _, _, _, population = _validate_provenance(provenance, state)
    _bind_batch(records, indices, population)
    targets = _conditions_targets(records)
    policy = f18._policy("modality-conditions-retention-ce")
    total, details = f18._loss(torch, output, records, indices, policy, teacher, weights)
    _require(details["weighted_CE"]["batch_denominator"] == BATCH_SIZE
             and details["weighted_CE"]["outer_denominator"] == CE_OUTER_DENOMINATOR
             and details["weighted_CE"]["modality_multiplier"] == CE_MODALITY_MULTIPLIER
             and details["weighted_CE"]["actor_hinge_omitted"] is True
             and details["retention"]["denominator"] == KL_BLOCKS * BATCH_SIZE,
             "unchanged CE/KL full-batch wiring required")
    start, end = output["start"], output["end"]
    _require(start.ndim == 3 and tuple(start.shape) == tuple(end.shape) and start.shape[1] == 6
             and start.shape[0] == BATCH_SIZE, "conditions row 3 selection required")
    margin = conditions_fullspan_margin_from_logits(
        torch, start[:, CONDITIONS_ROW, :], end[:, CONDITIONS_ROW, :],
        targets, weight=margin_weight)
    combined = total + margin["weighted_loss"]
    _require(bool(torch.isfinite(combined)), "nonfinite control")
    return {
        "schema": SCHEMA,
        "loss": combined,
        "f18_ce_plus_kl": total,
        "weighted_CE": details["weighted_CE"],
        "retention": details["retention"],
        "margin": margin,
        "margin_weight": float(margin_weight),
        "ce_batch_denominator": BATCH_SIZE,
        "ce_outer_denominator": CE_OUTER_DENOMINATOR,
        "kl_temperature": KL_TEMPERATURE,
        "kl_coefficient": KL_COEFFICIENT,
        "kl_denominator": KL_BLOCKS * BATCH_SIZE,
        "optimizer_steps": 0,
        "training_executed": False,
        "model_execution_performed": False,
    }


def compose_objective_for_state(torch, output, records, indices, teacher, weights, state, provenance, *, margin_weight=0.25):
    """Public loss wiring. The donor state stays outside the provenance document and the F15 teacher."""
    return compose_objective(
        torch, output, records, indices, teacher, weights, state, provenance, margin_weight=margin_weight)


def scoring_preflight(cases, permissions, provenance, state):
    """Validate frozen full-IR casewise scoring inputs. Does not score or forward."""
    _validate_provenance(provenance, state)
    population = _gold_population(provenance["gold_present_train_indices"], provenance["gold_present_row_ids"])
    _require(type(cases) is list and len(cases) == GOLD_PRESENT_TRAIN_ROWS, "gold-present TRAIN row count required")
    _require(type(permissions) is dict and set(permissions) == {"schema", "count", "ids", "frozen", "scored"}
             and permissions["schema"] == PERMISSION_SCHEMA and permissions["count"] == PERMISSION_COUNT
             and permissions["frozen"] is True and permissions["scored"] is False,
             "32 permission decisions required")
    ids = permissions["ids"]
    _require(type(ids) is list and len(ids) == PERMISSION_COUNT and len(set(ids)) == PERMISSION_COUNT
             and all(type(item) is str and item for item in ids), "32 permission decisions required")
    permission_digest = f18.checkpoint_digest(ids)
    seen = []
    frozen_cases = []
    for case, (index, row_id) in zip(cases, population.items(), strict=True):
        _require(type(case) is dict and set(case) == _CASE_KEYS, "scoring provenance required")
        _require(case["partition"] == "TRAIN" and case["gold_present"] is True, "TRAIN partition required")
        _require(case["id"] == row_id and case["training_index"] == index, "gold-present TRAIN row count required")
        for key in ("full_ir_sha256", "raw_output_sha256", "joint_output_sha256", "permission_ids_sha256"):
            _sha256_text(case[key])
        _require(case["permission_ids_sha256"] == permission_digest, "32 permission decisions required")
        seen.append(case["id"])
        frozen_cases.append({key: case[key] for key in sorted(_CASE_KEYS)})
    _require(seen == list(population.values()), "gold-present TRAIN row count required")
    return {
        "schema": SCORING_SCHEMA,
        "case_count": GOLD_PRESENT_TRAIN_ROWS,
        "partition": "TRAIN",
        "gold_present": True,
        "permission_count": PERMISSION_COUNT,
        "permission_ids_sha256": permission_digest,
        "cases_sha256": f18.checkpoint_digest(frozen_cases),
        "raw_and_joint_outputs_frozen_before_scoring": True,
        "casewise_retention_computed": False,
        "scoring_executed": False,
        "model_execution_performed": False,
        "training_executed": False,
        "admitted": False,
        "formalized": False,
    }


def run_admitted_updates(*_args, **_kwargs):
    raise ValueError("resource and model fitting admission is separate; this profile executes no updates")


def score_frozen_cases(*_args, **_kwargs):
    raise ValueError("frozen full-IR scoring is preflight only; this profile does not score")


def engineering_preparation():
    """Preparation document for LIRAE-LIR17-PROFILE-03. It records no fit."""
    owners = _reuse_owners()
    contract = selection_mask_contract()
    result = {
        "state_provenance": {
            "donor": "authenticated 42-tensor F18 state",
            "donor_schema": f18.SCHEMA,
            "donor_lineage_id": f18.LINEAGE_ID,
            "donor_tensor_count": DONOR_TENSOR_COUNT,
            "teacher": "F15 masked retention; not a donor",
            "teacher_checkpoint_sha256": f18.SOURCE_ACTOR_REFINEMENT_SHA256,
            "teacher_model_state_sha256": f18.SOURCE_ACTOR_REFINEMENT_MODEL_SHA256,
            "teacher_is_donor": False,
            "partition": "TRAIN",
            "gold_present_train_rows": GOLD_PRESENT_TRAIN_ROWS,
            "frozen38_seal": "sha256 of the 38 F18 donor tensors outside start/end weight and bias, including modality",
            "frozen36_reused_as_seal": False,
            "old_frozen36_identity": "F15-origin BASE_PARAMETER_NAMES digest recorded only to prove it is not the seal",
        },
        "model_optimizer_wiring": {
            "model_owner": "legal_span_modality_conditions_retention._model",
            "loss_owner": "legal_span_modality_conditions_retention._loss",
            "margin_owner": "conditions_fullspan_margin_from_logits",
            "margin_schema": MARGIN_SCHEMA,
            "margin_arms": list(MARGIN_ARMS),
            "optimizer": {
                "name": "Adam",
                "parameter_order": list(SELECTED),
                "learning_rate": LEARNING_RATE,
                "betas": list(ADAM_BETAS),
                "eps": ADAM_EPS,
                "weight_decay": WEIGHT_DECAY,
                "foreach": False,
                "gradient_clip_norm": GRADIENT_CLIP_NORM,
                "inherited_moments": False,
                "max_updates": MAX_UPDATES,
            },
            "seed": SEED,
            "batch_size": BATCH_SIZE,
            "latent_enabled": False,
            "ce_batch_denominator": BATCH_SIZE,
            "ce_outer_denominator": CE_OUTER_DENOMINATOR,
            "kl_temperature": KL_TEMPERATURE,
            "kl_coefficient": KL_COEFFICIENT,
            "kl_denominator": KL_BLOCKS * BATCH_SIZE,
            "optimizer_steps_executed": 0,
            "structured_objective_invoked": False,
            "training_row_count": TRAIN_INDEX_COUNT,
            "batch_order_owner": "legal_span_targeted_loss._batch_indices(168, progress, 12, 1729)",
            "absent_conditions_margin": "connected_zero_in_full_batch_mean",
        },
        "selection_mask_contract": contract,
        "acceptance_controls": {
            "rejects_wrong_tensor_shapes": True,
            "rejects_wrong_conditions_row": True,
            "rejects_wrong_tensor_and_row_counts": True,
            "rejects_nonfinite_controls": True,
            "rejects_missing_provenance": True,
            "rejects_non_TRAIN_partition": True,
            "rejects_f15_as_donor": True,
            "verifies_unchanged_ce_kl_full_batch": True,
            "verifies_margin_arms": list(MARGIN_ARMS),
            "fits_real_inputs": False,
            "training_executed": False,
            "encoder_executed": False,
            "checkpoint_mutated": False,
        },
        "frozen_full_ir_casewise_scoring": {
            "schema": SCORING_SCHEMA,
            "population": "all 72 gold-present TRAIN rows",
            "permission_decisions": PERMISSION_COUNT,
            "raw_and_joint_outputs_frozen_before_scoring": True,
            "casewise_retention_computed_by_this_profile": False,
            "scoring_executed": False,
            "comparators_not_rerun": ["F18", "F15", "N11", "F16", "F17", "F19"],
        },
        "unresolved_questions": [
            "Caller-state self-hashes do not independently authenticate the retained final F18 donor or its source/teacher/mask artifact roots; original-owned admission must bind them.",
            "Matched coefficient 0 and 0.25 arms still need separate resource admission before the 32-update fit.",
            "Frozen raw and joint complete-IR scoring against retained comparators, casewise retention and the 32 permission decisions is preflight only.",
            "Statutory gold, governing meaning, latent-width comparison and parent LIR-17 semantic dependencies remain unresolved.",
            "Historical F17, F18 and F19 checkpoints are not opened or rewritten by this preparation.",
        ],
        "reuse_owners": owners,
    }
    return {
        "schema": PREPARATION_SCHEMA,
        "task_id": TASK_ID,
        "parent_reference": dict(_PARENT_REFERENCE),
        "source_binding": dict(_SOURCE_BINDING),
        "admitted": False,
        "formalized": False,
        "semantic_review_performed": False,
        "model_gain_claimed": False,
        "training_executed": False,
        "result": result,
    }


_require(SELECTED == ("start.weight", "start.bias", "end.weight", "end.bias"), "ordered four-tensor selection differs")
_require(len(FROZEN) == FROZEN_TENSOR_COUNT and set(f18.MODALITY_NAMES) <= set(FROZEN), "modality must stay inside frozen38")
_require(set(FROZEN) - set(f18.BASE_PARAMETER_NAMES) == set(f18.MODALITY_NAMES), "frozen38 must extend frozen36 by modality only")
_require(f18._active_rows("start.weight") == (CONDITIONS_ROW,) and f18._inactive_rows("start.bias") == INACTIVE_ROWS,
         "F18 conditions row contract differs")
_stored = sum(math.prod(_shape_table(8, 8)[name]) for name in SELECTED)
_active = sum(_shape_table(8, 8)[name][1] if name.endswith("weight") else 1 for name in SELECTED)
_require((_stored, _active, _stored - _active) == (STORED_SCALARS, ACTIVE_SCALARS, INACTIVE_SCALARS),
         "130/780/650 scalar count required")
_require(KL_BLOCKS * BATCH_SIZE == 72, "KL full-batch denominator differs")


__all__ = [
    "SCHEMA", "CONFIG_SCHEMA", "SELECTED", "FROZEN", "MARGIN_SCHEMA",
    "conditions_fullspan_margin_from_logits", "configuration", "donor_provenance",
    "wire_optimizer", "compose_objective_for_state", "clip_selected_gradients",
    "scoring_preflight", "frozen38_seal", "frozen36_digest", "selection_mask_contract",
    "engineering_preparation", "run_admitted_updates", "score_frozen_cases",
]
