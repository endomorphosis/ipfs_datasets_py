"""Additive ridge statistics for the unchanged four-domain structured decoder.

Workers transmit exact low-rank factors and sparse one-hot label indices. The
coordinator sums sufficient statistics, normalizes using training only, and fits
one ridge head. This is a full-corpus head refit over the published frozen Legal
projection and vocabulary; a head alone cannot recover historical statistics.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path
import re
import threading

from .contracts import DOMAINS, FALSE, SHA, binding, digest, raw, read_json_bound, require
from .. import grouped_source_training_384 as grouped
from .. import structured_source_384 as decoder

PLAN_SCHEMA = "distributed-structured-384-plan/v1"
UPDATE_SCHEMA = "distributed-structured-384-update/v1"
ALGORITHM = "global-centered-ridge-sufficient-statistics/v1"
_LOCK = threading.RLock()
_MANIFEST_KEYS = {"id", "source_sha256", "normalized_source_sha256", "embedding_sha256", "target_sha256"}
_BINDING_KEYS = _MANIFEST_KEYS | {"group_id", "split", "numeric_embedding_sha256"}
_SHARD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_PARENT_ROLE = "baseline evaluation; head refit from the complete declared training round"
_SELECTION = "tuning exact targets, then variable leaves, first ridge on ties"


def _sha(value, message):
    require(type(value) is str and SHA.fullmatch(value), message)


def _source_descriptor(source):
    require(type(source) is dict and source.get("schema") == "ir384-corpus-source/v1"
            and type(source.get("description")) is str and source["description"].strip()
            and len(raw(source)) <= 65536, "explicit bounded corpus source descriptor required")
    if "huggingface" in source:
        hub = source["huggingface"]
        from .contracts import COMMIT
        require(type(hub) is dict and type(hub.get("repository_id")) is str
                and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", hub["repository_id"])
                and hub.get("repo_type") in ("model", "dataset")
                and type(hub.get("revision")) is str and COMMIT.fullmatch(hub["revision"]),
                "dataset Hub source requires an immutable commit")


def _ridge_grid(options):
    require(type(options) is list and 1 <= len(options) <= 16
            and all(type(x) in (int, float) and math.isfinite(x) and 0 < x <= 100 for x in options)
            and options == sorted(set(options)), "ordered distinct bounded ridges required")


def _manifest_bindings(plan, split):
    rows, bindings = plan[split + "_manifest"], plan[split + "_bindings"]
    label = "train" if split == "training" else "validation"
    require(type(rows) is list and 1 <= len(rows) <= (2048 if label == "train" else 4096)
            and type(bindings) is list and len(rows) == len(bindings), "bounded split manifests and bindings required")
    seen, groups_by_identity, targets_by_input = set(), {}, {}
    for row, bound in zip(rows, bindings):
        require(type(row) is dict and set(row) == _MANIFEST_KEYS
                and type(bound) is dict and set(bound) == _BINDING_KEYS, "closed split row binding required")
        require(type(row["id"]) is str and 0 < len(row["id"]) <= 256 and row["id"] not in seen,
                "unique bounded split IDs required")
        seen.add(row["id"])
        require(all(row[k] == bound[k] for k in _MANIFEST_KEYS), "manifest and row binding differ")
        for key in _BINDING_KEYS - {"id", "group_id", "split"}:
            _sha(bound[key], "invalid row binding digest")
        require(type(bound["group_id"]) is str and 0 < len(bound["group_id"]) <= 512
                and bound["group_id"].strip() and bound["split"] == label, "invalid group or split binding")
        for key in ("source_sha256", "normalized_source_sha256", "numeric_embedding_sha256"):
            previous = groups_by_identity.setdefault((key, bound[key]), bound["group_id"])
            require(previous == bound["group_id"], "identical source or embedding assigned to different leakage groups")
        for key in ("source_sha256", "numeric_embedding_sha256"):
            previous = targets_by_input.setdefault((key, bound[key]), bound["target_sha256"])
            require(previous == bound["target_sha256"], "identical source or numerical input has conflicting targets")
    return {key: sorted({row[key] for row in bindings}) for key in grouped.EXCLUSION_KEYS}


def _producer():
    return {"numerics_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "grouped_recipe": grouped._pins()}


def _base(checkpoint, plan=None):
    # Runtime validation temporarily limits BLAS threads. Serialize that small
    # validation scope; the coordinator holds the outer pool-wide BLAS limit.
    with _LOCK:
        decoder.Runtime(checkpoint)
    if plan is not None:
        require(digest(checkpoint) == plan["base_json_sha256"], "base checkpoint differs")
        require(checkpoint["domain_id"] == plan["domain_id"], "base domain differs")
        require(checkpoint["projection_sha256"] == plan["projection_sha256"], "projection differs")
        require(digest(checkpoint["target_schema"]) == plan["target_schema_sha256"], "target schema differs")


def validate_plan(plan):
    keys = {"schema", "domain_id", "base_checkpoint_sha256", "base_json_sha256", "projection_sha256",
        "target_schema_sha256", "dataset", "dataset_sha256", "recipe", "recipe_sha256", "machine_count",
        "shards", "training_manifest", "validation_manifest", "training_bindings", "validation_bindings", "plan_id", *FALSE}
    require(type(plan) is dict and set(plan) == keys and plan.get("schema") == PLAN_SCHEMA,
            "closed training plan schema differs")
    require(type(plan["domain_id"]) is str and plan["domain_id"] in DOMAINS, "unsupported training domain")
    for key in ("plan_id", "base_checkpoint_sha256", "base_json_sha256", "projection_sha256",
                "target_schema_sha256", "dataset_sha256", "recipe_sha256"):
        _sha(plan[key], "invalid plan digest: " + key)
    require(plan.get("plan_id") == digest({k: v for k, v in plan.items() if k != "plan_id"}),
            "training plan identity differs")
    dataset = plan["dataset"]
    require(type(dataset) is dict and set(dataset) == {"source", "training_rows_sha256", "validation_rows_sha256"}
            and plan["dataset_sha256"] == digest(dataset), "dataset binding differs")
    _source_descriptor(dataset["source"])
    for key in ("training_rows_sha256", "validation_rows_sha256"):
        _sha(dataset[key], "invalid corpus digest")
    recipe = plan["recipe"]
    require(type(recipe) is dict and set(recipe) == {"algorithm", "producer", "ridges", "input_dimension",
        "projection_frozen", "vocabulary_frozen", "parent_head_role", "prior_training_statistics_recovered_from_weights",
        "required_families", "native_family_ids", "selection"}
        and plan["recipe_sha256"] == digest(recipe), "training recipe differs")
    require(recipe["algorithm"] == ALGORITHM and recipe["producer"] == _producer(),
            "numerical producer differs")
    _ridge_grid(recipe["ridges"])
    require(type(recipe["input_dimension"]) is int and recipe["input_dimension"] == 384
        and recipe["projection_frozen"] is True and recipe["vocabulary_frozen"] is True
        and recipe["prior_training_statistics_recovered_from_weights"] is False
        and recipe["parent_head_role"] == _PARENT_ROLE and recipe["selection"] == _SELECTION,
        "frozen projection and complete head-refit recipe required")
    from .profiles import get_profile
    available = get_profile(plan["domain_id"])["native_family_ids"]
    families = recipe["required_families"]
    require(recipe["native_family_ids"] == list(available) and type(families) is list
        and all(type(x) is str for x in families) and families == sorted(set(families))
        and set(families) <= set(available), "native family recipe differs")
    require(type(plan["machine_count"]) is int and 1 <= plan["machine_count"] <= 128,
            "bounded machine count required")
    train_inventory = _manifest_bindings(plan, "training")
    validation_inventory = _manifest_bindings(plan, "validation")
    grouped._exclude(train_inventory, validation_inventory)
    shards = plan["shards"]
    require(type(shards) is list and 1 <= len(shards) <= 2048, "bounded nonempty shards required")
    ids, seen_shards = [], set()
    by_id = {row["id"]: row for row in plan["training_bindings"]}
    group_shards = {}
    for shard in shards:
        require(type(shard) is dict and set(shard) == {"shard_id", "rows_sha256", "row_count", "row_ids", "machine_index"},
                "closed shard schema required")
        require(type(shard["shard_id"]) is str and _SHARD_ID.fullmatch(shard["shard_id"])
                and shard["shard_id"] not in seen_shards, "unique bounded shard identity required")
        seen_shards.add(shard["shard_id"])
        _sha(shard["rows_sha256"], "invalid shard digest")
        require(type(shard["row_ids"]) is list and all(type(i) is str and i in by_id for i in shard["row_ids"]),
                "shard row identity differs")
        require(type(shard["row_count"]) is int and shard["row_count"] == len(shard["row_ids"])
                and 1 <= shard["row_count"] <= 2048, "shard size differs")
        require(type(shard["machine_index"]) is int and 0 <= shard["machine_index"] < plan["machine_count"],
                "shard machine differs")
        ids.extend(shard["row_ids"])
        for row_id in shard["row_ids"]:
            group = by_id[row_id]["group_id"]
            previous = group_shards.setdefault(group, shard["shard_id"])
            require(previous == shard["shard_id"], "indivisible source group split across shards")
    require(len(ids) == len(set(ids)) == len(plan["training_manifest"]), "overlapping or missing shard rows")
    require(set(ids) == set(by_id), "shard inventory differs")
    require(all(plan.get(k) is False for k in FALSE), "training plan cannot grant authority")
    return plan


def make_plan(base_path, training_rows, validation_rows, *, source_descriptor,
              shard_size=32, machine_count=1, ridges=None, required_families=()):
    """Freeze a complete source/group-audited round before dispatching workers.

    Source descriptors record the export's actual provenance; corpus content
    hashes bind the exact typed rows regardless of a descriptive upstream URL.
    No raw CVE/SkillCenter text is silently converted into supervised IR labels.
    """
    checkpoint, base_reference = read_json_bound(base_path)
    _base(checkpoint)
    require(type(shard_size) is int and 1 <= shard_size <= 256, "bounded shard size required")
    require(type(machine_count) is int and 1 <= machine_count <= 128, "bounded machine count required")
    _source_descriptor(source_descriptor)
    domain = checkpoint["domain_id"]
    training, train_bindings, train_inventory = grouped._prepare(domain, training_rows, "train")
    validation, val_bindings, val_inventory = grouped._prepare(domain, validation_rows, "validation")
    grouped._exclude(train_inventory, val_inventory)
    from ..complete_training import _preflight_source_targets
    _preflight_source_targets(domain, training, validation)
    import numpy as np
    # Both splits must fit the published schema. Tuning never extends classes.
    decoder._targets(np, training, checkpoint["target_schema"])
    decoder._targets(np, validation, checkpoint["target_schema"])
    options = checkpoint["config"]["ridges"] if ridges is None else list(ridges)
    _ridge_grid(options)
    require(type(required_families) in (list, tuple) and all(type(x) is str for x in required_families)
            and len(set(required_families)) == len(required_families), "unique family identifiers required")
    from .profiles import get_profile
    available = get_profile(domain)["native_family_ids"]
    require(set(required_families) <= set(available), "required family lacks a domain projection route")
    groups = {}
    for row in training_rows:
        groups.setdefault(row["group_id"], []).append(row)
    batches, current = [], []
    for group in sorted(groups):
        rows = sorted(groups[group], key=lambda x: x["id"])
        if current and len(current) + len(rows) > shard_size:
            batches.append(current)
            current = []
        current.extend(rows)
    if current:
        batches.append(current)
    shards = [dict(shard_id=f"shard-{i:06d}", rows_sha256=digest(rows), row_count=len(rows),
                   row_ids=[r["id"] for r in rows], machine_index=i % machine_count)
              for i, rows in enumerate(batches)]
    recipe = dict(algorithm=ALGORITHM, producer=_producer(), ridges=options,
        input_dimension=384, projection_frozen=True, vocabulary_frozen=True,
        parent_head_role=_PARENT_ROLE,
        prior_training_statistics_recovered_from_weights=False,
        required_families=sorted(required_families), native_family_ids=list(available),
        selection=_SELECTION)
    dataset = dict(source=source_descriptor, training_rows_sha256=digest(training_rows),
                   validation_rows_sha256=digest(validation_rows))
    plan = dict(schema=PLAN_SCHEMA, domain_id=domain, base_checkpoint_sha256=base_reference["sha256"],
        base_json_sha256=digest(checkpoint), projection_sha256=checkpoint["projection_sha256"],
        target_schema_sha256=digest(checkpoint["target_schema"]), dataset=dataset,
        dataset_sha256=digest(dataset), recipe=recipe, recipe_sha256=digest(recipe),
        machine_count=machine_count, shards=shards, training_manifest=decoder._manifest(training),
        validation_manifest=decoder._manifest(validation), training_bindings=train_bindings,
        validation_bindings=val_bindings, **FALSE)
    plan["plan_id"] = digest(plan)
    return validate_plan(plan)


def shard_rows(plan, training_rows, shard_id):
    validate_plan(plan)
    require(digest(training_rows) == plan["dataset"]["training_rows_sha256"], "training corpus differs")
    shard = next((s for s in plan["shards"] if s["shard_id"] == shard_id), None)
    require(shard is not None, "unknown shard")
    by_id = {r["id"]: r for r in training_rows}
    rows = [by_id[key] for key in shard["row_ids"]]
    require(digest(rows) == shard["rows_sha256"], "shard row inventory differs")
    return rows


def compute_update(plan, checkpoint, rows, shard_id):
    """No tuning/test rows or database handle enter the numerical worker."""
    validate_plan(plan)
    _base(checkpoint, plan)
    shard = next((s for s in plan["shards"] if s["shard_id"] == shard_id), None)
    require(shard is not None and digest(rows) == shard["rows_sha256"], "shard inputs differ")
    training, row_bindings, _ = grouped._prepare(plan["domain_id"], rows, "train")
    require([row["id"] for row in training] == shard["row_ids"], "shard row identities differ")
    manifest = {row["id"]: row for row in plan["training_manifest"]}
    bindings = {row["id"]: row for row in plan["training_bindings"]}
    require(decoder._manifest(training) == [manifest[i] for i in shard["row_ids"]]
            and row_bindings == [bindings[i] for i in shard["row_ids"]], "worker rows differ from declared training manifest")
    import numpy as np
    projected = decoder._project(np, training, checkpoint["projection_state"])
    _, indices = decoder._targets(np, training, checkpoint["target_schema"])
    # A factorized update exactly represents P'P/P'Y without transmitting a
    # dense384x384 Gram matrix or a new copy of frozen model parameters.
    stats = dict(encoding="low_rank_sparse_labels/v1", projected=projected.tolist(), class_ids=indices)
    update = dict(schema=UPDATE_SCHEMA, **binding(plan), shard_id=shard_id,
        rows_sha256=shard["rows_sha256"], row_count=len(rows), statistics=stats, **FALSE)
    update["update_id"] = digest(update)
    return update


def validate_update(plan, checkpoint, update):
    validate_plan(plan)
    _base(checkpoint, plan)
    return _validate_update(plan, checkpoint, update)


def _validate_update(plan, checkpoint, update):
    require(type(update) is dict and set(update) == {"schema", *binding(plan), "shard_id",
        "rows_sha256", "row_count", "statistics", "update_id", *FALSE}, "closed update required")
    require(update["schema"] == UPDATE_SCHEMA and update["update_id"] == digest(
        {k: v for k, v in update.items() if k != "update_id"}), "update identity differs")
    require(all(update[k] == v for k, v in binding(plan).items()), "stale or foreign update binding")
    require(all(update[k] is False for k in FALSE), "update cannot grant authority")
    shard = next((s for s in plan["shards"] if s["shard_id"] == update["shard_id"]), None)
    require(shard is not None and update["rows_sha256"] == shard["rows_sha256"]
            and type(update["row_count"]) is int and update["row_count"] == shard["row_count"], "shard binding differs")
    stats = update["statistics"]
    require(type(stats) is dict and set(stats) == {"encoding", "projected", "class_ids"}
            and stats["encoding"] == "low_rank_sparse_labels/v1", "statistics encoding differs")
    import numpy as np
    projected = stats["projected"]
    require(type(projected) is list and len(projected) == update["row_count"]
        and all(type(row) is list and len(row) == 384
            and all(type(v) in (int, float) and math.isfinite(v) for v in row) for row in projected),
        "finite numerical projected statistics required")
    x = np.asarray(stats["projected"], dtype=np.float64)
    require(x.shape == (update["row_count"], 384) and np.isfinite(x).all(), "invalid projected statistics")
    classes = [len(s["classes"]) for s in checkpoint["target_schema"]["slots"]]
    indices = stats["class_ids"]
    require(type(indices) is list and len(indices) == len(x) and all(type(row) is list
        and len(row) == len(classes) and all(type(v) is int and 0 <= v < limit for v, limit in zip(row, classes))
        for row in indices), "invalid sparse target coordinates")
    y = np.zeros((len(x), sum(classes)), dtype=np.float64)
    offsets = np.cumsum([0, *classes[:-1]])
    for i, row in enumerate(indices):
        y[i, offsets + np.asarray(row)] = 1.
    return x, y


def merge_updates(plan, checkpoint, updates, validation_rows):
    """One mathematically shared fit; delivery order cannot select a winner.

    Hashes identify declared inputs and worker outputs, not proof of honest
    remote computation. Native projection and source checks remain separate.
    """
    validate_plan(plan)
    _base(checkpoint, plan)
    require(digest(validation_rows) == plan["dataset"]["validation_rows_sha256"], "tuning corpus differs")
    require(type(updates) is list and len(updates) == len(plan["shards"]), "missing or extra shard updates")
    require(len({u["shard_id"] for u in updates}) == len(updates), "duplicate shard updates")
    require({u["shard_id"] for u in updates} == {s["shard_id"] for s in plan["shards"]}, "shard coverage differs")
    validation, _, _ = grouped._prepare(plan["domain_id"], validation_rows, "validation")
    width = sum(len(s["classes"]) for s in checkpoint["target_schema"]["slots"])
    with decoder._numeric() as np:
        count = 0
        shifted_sum, sy = np.zeros(384), np.zeros(width)
        ordered = sorted(updates, key=lambda u: u["shard_id"])
        origin = None
        for update in ordered:
            x, y = _validate_update(plan, checkpoint, update)
            if origin is None:
                origin = x[0].copy()
            count += len(x)
            shifted_sum += (x - origin).sum(0)
            sy += y.sum(0)
        require(count == len(plan["training_manifest"]), "training row count differs")
        mean, bias = origin + shifted_sum / count, sy / count
        require(np.isfinite(mean).all() and np.isfinite(bias).all(), "nonfinite global means")
        centered, cross = np.zeros((384, 384)), np.zeros((384, width))
        # The transmitted factors allow a stable second pass. Forming Q minus
        # n*mean*mean.T loses all small variance when embeddings share a large
        # finite offset. Center each shard using the same global training mean
        # and then add its Gram/cross statistics; tuning never enters either.
        for update in ordered:
            x, y = _validate_update(plan, checkpoint, update)
            dx, dy = x - mean, y - bias
            centered += dx.T @ dx
            cross += dx.T @ dy
        require(np.isfinite(centered).all() and np.isfinite(cross).all(), "nonfinite centered statistics")
        trace = float(np.trace(centered) / count)
        require(np.isfinite(trace) and trace >= 0., "invalid centered variance")
        scale = max(float(np.sqrt(trace)), .01)
        gram = (centered + centered.T) / (2 * scale ** 2)
        targets = cross / scale
        require(np.isfinite(gram).all() and np.isfinite(targets).all(), "nonfinite aggregate statistics")
        values, vectors = np.linalg.eigh(gram)
        tolerance = 64 * np.finfo(np.float64).eps * 384 * max(1., float(np.max(np.abs(values))))
        require(float(values.min()) >= -tolerance, "invalid Gram spectrum")
        values = np.maximum(values, 0.)
        minimum = 16 * np.finfo(np.float64).eps * 384 * max(1., float(values.max()))
        transform = dict(mean=mean.tolist(), scale=scale, origin="training_projected_embeddings_only")
        vx, _ = decoder._normalize(np, decoder._project(np, validation, checkpoint["projection_state"]), transform)
        _, label_ids = decoder._targets(np, validation, checkpoint["target_schema"])
        history, selected, best_rank = [], None, None
        for ridge in plan["recipe"]["ridges"]:
            require(ridge > minimum, "ridge below numerical stability bound")
            weights = vectors @ ((vectors.T @ targets) / (values[:, None] + ridge))
            require(np.isfinite(weights).all(), "nonfinite fitted weights")
            observed = decoder._score(plan["domain_id"], vx @ weights + bias, validation,
                                      label_ids, checkpoint["target_schema"])
            rank = (observed["exact_targets"], observed["semantic_leaf_correct"])
            chosen = best_rank is None or rank > best_rank
            history.append(dict(ridge=ridge, **observed, selected_at_step=chosen))
            if chosen:
                selected, best_rank, best_weights, best = ridge, rank, weights.copy(), observed
        result = deepcopy(checkpoint)
        result["head_state"] = dict(weights=best_weights.tolist(), bias=bias.tolist())
        result["head_sha256"] = decoder.digest(result["head_state"])
        result["input_transform"] = transform
        result["config"]["ridges"] = list(plan["recipe"]["ridges"])
        result["training_manifest"] = deepcopy(plan["training_manifest"])
        result["validation_manifest"] = deepcopy(plan["validation_manifest"])
        result["training"] = dict(selected_ridge=selected, selected_validation=best, history=history,
            unique_training_examples=count, test_used_for_selection=False, gradient_training_used=False,
            optimizer_steps=0, trainer_id=ALGORITHM, recipe_sha256=plan["recipe_sha256"],
            plan_id=plan["plan_id"], base_checkpoint_sha256=plan["base_checkpoint_sha256"],
            statistical_merge="sum unique declared shards before global centering and solve",
            centering="two_pass_global_training_mean_then_add_centered_shard_statistics",
            head_weights_averaged=False, prior_training_statistics_recovered_from_weights=False)
    decoder.Runtime(result)
    baseline = decoder.evaluate(checkpoint, validation)
    return dict(checkpoint=result, report=dict(schema="distributed-structured-384-merge/v1",
        **binding(plan), update_ids=sorted(u["update_id"] for u in updates), shards=len(updates),
        training_rows=count, selected_validation=best,
        baseline_validation={k: baseline[k] for k in ("count", "exact_targets", "semantic_leaf_correct")},
        validation_not_regressed=(best["exact_targets"], best["semantic_leaf_correct"]) >=
            (baseline["exact_targets"], baseline["semantic_leaf_correct"]),
        frozen_legal_projection_unchanged=result["projection_state"] == checkpoint["projection_state"],
        checkpoint_bytes=len(raw(result)), update_bytes=sum(len(raw(u)) for u in updates),
        statistics_are_factored_updates=True, remote_numerical_computation_proven=False, **FALSE))
