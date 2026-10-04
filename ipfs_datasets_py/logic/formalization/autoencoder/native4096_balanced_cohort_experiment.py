"""Balanced original TRAIN/development diagnostics for the native4096 head.

This remains a restricted authored rule-codec experiment. Development is an
already exposed original split, not a new holdout or an admission. Only the live
native owner authorizes public training; saved vectors cannot open that gate.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import time

from . import native4096_conditioning_experiment as conditioning

pilot = conditioning.pilot
core = conditioning.core
_require = core._require
SCHEMA = "native4096-balanced-original-development/v1"
STEPS = 200
ARMS = ("joint_unscaled", "joint_source_scaled")
FIELDS = ("actor", "action", "modality", "object")
VALUES = dict(actor=("notary", "registrar", "secretary", "treasurer", "trustee"),
              action=("approve", "deliver", "examine", "preserve", "publish"),
              modality=("F", "O", "P"), object=("archive", "notice"))
FALSE = dict(pilot.FALSE, source_encoder_trained=False, fresh_holdout_evaluated=False)


def _normalized_text(text):
    _require(type(text) is str and 0 < len(text) <= 10000, "bounded source text required")
    return " ".join(text.casefold().split())


def _rule(tokens, vocabulary):
    """Closed authored rule-codec shape; this is not a logic-family validator."""
    _require(type(tokens) is list and 1 <= len(tokens) <= 510
             and all(type(t) is int and 3 <= t < 32 for t in tokens), "bounded rule tokens required")
    def unique_object(pairs):
        _require(len({key for key, _ in pairs}) == len(pairs), "duplicate authored rule keys")
        return dict(pairs)
    value = json.loads("".join(vocabulary[token] for token in tokens), object_pairs_hook=unique_object)
    _require(type(value) is dict and set(value) == {"rules"}
             and type(value["rules"]) is list and len(value["rules"]) == 1,
             "single authored rule required")
    rule = value["rules"][0]
    _require(type(rule) is dict and set(rule) == set(FIELDS)|{"conditions", "exceptions", "temporal"}
             and all(rule.get(field) in values for field, values in VALUES.items())
             and all(rule.get(field) == [] for field in ("conditions", "exceptions", "temporal")),
             "closed authored field inventory required")
    return rule


def _target_rule(row, vocabulary):
    tokens = row.get("target_ids")
    _require(type(tokens) is list and tokens[:1] == [1] and tokens[-1:] == [2],
             "bounded BOS/EOS authored target required")
    return _rule(tokens[1:-1], vocabulary)


def cohort_statistics(rows, vocabulary):
    rules = [_target_rule(row, vocabulary) for row in rows]
    return dict(count=len(rows), fields={field: dict(sorted(Counter(r[field] for r in rules).items()))
                                        for field in FIELDS},
                actor_action_pairs=[list(pair) for pair in sorted({(r["actor"], r["action"]) for r in rules})])


def _balanced(rows, vocabulary):
    _require(type(rows) is list and 12 <= len(rows) <= 4096, "bounded original split required")
    fields = {row["id"]: _target_rule(row, vocabulary) for row in rows}
    selected, used = [], set()
    actors, actions = Counter(), Counter()
    slots = [(modality, obj) for modality in VALUES["modality"] for obj in VALUES["object"] for _ in range(2)]
    visits = 0

    def search(index):
        nonlocal visits
        visits += 1
        _require(visits <= 200000, "bounded balanced cohort search exhausted")
        if index == 12:
            return all(2 <= actors[name] <= 3 for name in VALUES["actor"]) and all(
                2 <= actions[name] <= 3 for name in VALUES["action"])
        remaining = 12-index
        if sum(max(0, 2-actors[name]) for name in VALUES["actor"]) > remaining or sum(
                max(0, 2-actions[name]) for name in VALUES["action"]) > remaining:
            return False
        candidates = [row for row in rows if row["id"] not in used
                      and (fields[row["id"]]["modality"], fields[row["id"]]["object"]) == slots[index]
                      and actors[fields[row["id"]]["actor"]] < 3 and actions[fields[row["id"]]["action"]] < 3]
        candidates.sort(key=lambda row: (
            actors[fields[row["id"]]["actor"]]+actions[fields[row["id"]]["action"]],
            max(actors[fields[row["id"]]["actor"]], actions[fields[row["id"]]["action"]]),
            hashlib.sha256(row["source_text"].encode()).hexdigest()))
        for row in candidates:
            rule = fields[row["id"]]
            selected.append(row); used.add(row["id"])
            actors[rule["actor"]] += 1; actions[rule["action"]] += 1
            if search(index+1):
                return True
            selected.pop(); used.remove(row["id"])
            actors[rule["actor"]] -= 1; actions[rule["action"]] -= 1
        return False

    _require(search(0), "original split cannot satisfy declared balancing quotas")
    return [{key: row[key] for key in ("id", "source_text", "target_ids")} for row in selected], visits


def select_original_cohort(training_bank, development_bank, source_cache, token_receipt, codec):
    """Deterministic existing-split stratification, with no model score inputs."""
    vocabulary = codec["target_vocabulary"]
    _require(len(vocabulary) == 32 and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"],
             "original complete32V codec required")
    lane = source_cache["dimensions"]["384"]["clause_cache"]
    banks = {"train": training_bank, "validation": development_bank}
    normalized = {}
    for split, bank in banks.items():
        _require(type(bank) is list and 12 <= len(bank) <= 4096, "bounded original source bank required")
        _require(all(type(row) is dict and type(row.get("id")) is str for row in bank)
                 and len({r["id"] for r in bank}) == len(bank), "unique original identities required")
        normalized[split] = {_normalized_text(row["source_text"]) for row in bank}
        _require(len(normalized[split]) == len(bank), "unique normalized source texts required")
    _require(not normalized["train"] & normalized["validation"], "original banks overlap")
    _require(not {r["id"] for r in training_bank} & {r["id"] for r in development_bank},
             "original bank identities overlap")
    tokens = token_receipt["rows"]
    _require(type(tokens) is list and len({r["source_sha256"] for r in tokens}) == len(tokens)
             and all(type(r["token_count"]) is int and 1 <= r["token_count"] <= 512 for r in tokens),
             "unique bounded native token observations required")
    counts = {row["source_sha256"]: row["token_count"] for row in tokens}
    output, stats = {}, {}
    all_pairs = {}
    for split, bank in banks.items():
        used = {row["source_text"] for row in lane[split]}
        _require(len(used) == len(lane[split]), "unique original used clause membership required")
        _require(used <= {r["source_text"] for r in bank}, "used clause lacks original split label")
        candidates = [row for row in bank if row["source_text"] in used]
        for row in candidates:
            _require(hashlib.sha256(row["source_text"].encode()).hexdigest() in counts,
                     "candidate lacks bounded native token observation")
        chosen, visits = _balanced(candidates, vocabulary)
        output[split] = chosen
        stats[split] = dict(cohort_statistics(chosen, vocabulary), eligible_count=len(candidates),
                           search_nodes=visits, token_counts=[counts[hashlib.sha256(r["source_text"].encode()).hexdigest()]
                                                            for r in chosen])
        all_pairs[split] = {tuple(pair) for pair in cohort_statistics(bank, vocabulary)["actor_action_pairs"]}
    _require(not all_pairs["train"] & all_pairs["validation"], "original actor/action split overlaps")
    return dict(schema="native4096-original-balanced-cohort/v1", training_labels=output["train"],
        development_labels=output["validation"], statistics=stats,
        selection_policy="fixed_modality_object_strata_then_actor_action_deficits_then_source_sha256",
        original_actor_action_pairs_disjoint=True, original_normalized_sources_disjoint=True,
        development_status="previously_exposed_original_development_split", **FALSE)


def _labels(torch, rows):
    length = max(len(row["target_ids"]) for row in rows)
    return torch.tensor([r["target_ids"]+[0]*(length-len(r["target_ids"])) for r in rows], dtype=torch.long)


def _fit_arm(model, training, development, *, vocabulary, arm, deadline, steps=STEPS):
    """Numerical implementation; development is observational throughout."""
    torch = core._torch()
    _require(arm in ARMS and type(steps) is int and 1 <= steps <= STEPS, "closed bounded cohort arm required")
    _require(type(deadline) in (int, float) and math.isfinite(deadline)
             and time.monotonic() < deadline <= time.monotonic()+301, "live bounded monotonic deadline required")
    sources, labels, normalization = conditioning._prepare(training)
    development_sources = torch.tensor([r["input"] for r in development], dtype=torch.float32)
    development_sources = (development_sources-torch.tensor(normalization["mean"], dtype=torch.float32))/normalization["scale"]
    development_labels = _labels(torch, development)
    optimizer = torch.optim.AdamW(conditioning._groups(model, arm, normalization["source_l1_bound"]),
                                  weight_decay=.01, foreach=False)
    parameters = list(model.parameters())
    initial = core.tensor_digest(model)

    def check(where):
        _require(time.monotonic() < deadline, "cohort deadline "+where)

    def loss(source, target):
        logits = model(source, target[:, :-1])
        return torch.nn.functional.cross_entropy(logits.flatten(0, 1), target[:, 1:].flatten(), ignore_index=0)

    def panel(source, target, rows):
        check("before observation")
        ce = float(loss(source, target))
        generated = core._greedy(torch, model, source, 512, 32, deadline)
        _require(generated is not None, "cohort deadline during generation")
        predictions, statuses = generated[1:]
        counts = Counter({field: 0 for field in FIELDS})
        parsed = 0
        for row, tokens, status in zip(rows, predictions, statuses):
            if status != "eos":
                continue
            try:
                decoded = _rule(tokens, vocabulary)
            except (ValueError, TypeError, KeyError, IndexError):
                continue
            parsed += 1
            reference = _target_rule(row, vocabulary)
            counts.update({field: int(decoded[field] == reference[field]) for field in FIELDS})
        return dict(cross_entropy=ce, sample_count=len(rows), parsed_restricted_rule_count=parsed,
            field_correct=dict(counts), field_denominator=len(rows),
            exact=sum(status == "eos" and tokens == row["target_ids"][1:-1]
                      for row, tokens, status in zip(rows, predictions, statuses)),
            predictions=[dict(id=row["id"], token_ids=tokens, status=status)
                         for row, tokens, status in zip(rows, predictions, statuses)])

    def observe(step):
        model.eval()
        result = {"step": step}
        with torch.inference_mode():
            for name, source, target, rows in (("train", sources, labels, training),
                    ("development", development_sources, development_labels, development)):
                result[name] = dict(conditioned=panel(source, target, rows),
                    zero_source=panel(torch.zeros_like(source), target, rows),
                    rotated_source=panel(source.roll(1, 0), target, rows))
            result["train_condition_preactivation_rms"] = float(model.condition(sources).square().mean().sqrt())
            result["train_source_residual_rms"] = float(model.source_to_embedding(sources).square().mean().sqrt())
        return result

    observations = [observe(0)]
    started = time.monotonic()
    updates = []
    for step in range(1, steps+1):
        check("before update")
        model.train(); optimizer.zero_grad(set_to_none=True)
        objective = loss(sources, labels)
        _require(bool(torch.isfinite(objective)), "nonfinite training objective")
        objective.backward()
        norm = float(torch.nn.utils.clip_grad_norm_(parameters, 1., error_if_nonfinite=True))
        gradients = {name: float(p.grad.norm()) if p.grad is not None else 0.
                     for name, p in model.named_parameters() if name in conditioning.SOURCE_WEIGHTS}
        check("before optimizer step"); optimizer.step()
        _require(all(bool(torch.isfinite(p).all()) for p in parameters), "nonfinite cohort parameters")
        with torch.inference_mode():
            after = float(loss(sources, labels))
        _require(math.isfinite(after), "nonfinite post-update training objective")
        updates.append(dict(step=step, training_loss_before_update=float(objective.detach()),
            training_loss_after_update=after, gradient_norm_before_clip=norm,
            source_gradient_norms_after_clip=gradients,
            learning_rates={group["name"]: group["lr"] for group in optimizer.param_groups}))
        if step in (20, 100, steps):
            observations.append(observe(step))
    seconds = time.monotonic()-started
    return dict(arm=arm, optimizer_steps=steps, row_presentations=steps*len(training),
        target_token_presentations=steps*int((labels[:, 1:] != 0).sum()), fit_seconds=seconds,
        seconds_per_training_row_presentation=seconds/(steps*len(training)),
        initial_tensor_sha256=initial, final_tensor_sha256=core.tensor_digest(model),
        normalization=normalization, observations=observations, updates=updates,
        schedule="constant_no_development_selection_or_schedule",
        source_rate_policy="base_lr" if arm == "joint_unscaled" else "base_lr/max(1,max_train_normalized_source_L1)",
        model_state={name: tensor.detach().tolist() for name, tensor in model.state_dict().items()})


def train_native_cohort(result, *, donor, codec, training_labels, development_labels, max_seconds=300):
    """Fit both fixed arms using one live native operation and TRAIN-only stats."""
    from .source_embeddings_4096_full_owner import require_live_result
    started = time.monotonic()
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds)
             and 0 < max_seconds <= 300, "bounded total cohort deadline required")
    native = require_live_result(result)
    _require(type(training_labels) is list and type(development_labels) is list
             and len(training_labels) == len(development_labels) == 12, "fixed12 TRAIN and12 development labels required")
    expected = training_labels+development_labels
    _require(len({row["id"] for row in expected}) == 24
             and len({_normalized_text(row["source_text"]) for row in expected}) == 24,
             "disjoint cohort source identities and normalized text required")
    _require(len(native["rows"]) == 25 and [r["id"] for r in native["rows"][:24]] == [r["id"] for r in expected]
             and native["rows"][-1]["id"] == "repeat:"+training_labels[0]["id"]
             and native["rows"][-1]["source_text"] == training_labels[0]["source_text"],
             "closed25-row native cohort order required")
    repeat_l2 = math.sqrt(sum((a-b)**2 for a, b in zip(native["rows"][0]["embedding"], native["rows"][-1]["embedding"])))
    _require(repeat_l2 <= 1e-6, "native cohort reset repeat differs")
    training = pilot._training_rows(native["rows"][:12], training_labels, codec)
    development = pilot._training_rows(native["rows"][12:24], development_labels, codec)
    statistics = {name: cohort_statistics(rows, codec["target_vocabulary"])
                  for name, rows in (("train", training), ("development", development))}
    for stats in statistics.values():
        _require(all(2 <= stats["fields"][field].get(value, 0) <= 3
                     for field in ("actor", "action") for value in VALUES[field])
                 and all(stats["fields"]["modality"].get(value) == 4 for value in VALUES["modality"])
                 and all(stats["fields"]["object"].get(value) == 6 for value in VALUES["object"]),
                 "declared balanced cohort quotas differ")
    _require(not {tuple(pair) for pair in statistics["train"]["actor_action_pairs"]}
             & {tuple(pair) for pair in statistics["development"]["actor_action_pairs"]},
             "cohort actor/action pairs overlap")
    digest = core.tensor_digest(donor)
    fits = []
    for arm in ARMS:
        _require(require_live_result(result) == native, "native capability changed before arm")
        model = pilot._new_body(donor, vocabulary_size=32)
        fits.append(_fit_arm(model, training, development, vocabulary=codec["target_vocabulary"],
                             arm=arm, deadline=started+max_seconds))
        _require(require_live_result(result) == native, "native capability changed during arm")
    _require(fits[0]["initial_tensor_sha256"] == fits[1]["initial_tensor_sha256"]
             and core.tensor_digest(donor) == digest, "matched initialization or donor changed")
    receipt = dict(schema=SCHEMA, dimension=4096, arms=fits, codec=deepcopy(codec),
        donor_tensor_sha256=digest, native_provenance=deepcopy(native["provenance"]),
        training_rows_sha256=core.digest(training), development_rows_sha256=core.digest(development),
        training_source_count=12, validation_count=12, native_forward_rows=25,
        cohort_statistics=statistics, development_status="previously_exposed_original_development_split",
        selection_policy="none_report_all_last_iterates", development_used_for_updates=False,
        development_used_for_normalization=False, development_used_for_learning_rates=False,
        development_used_for_selection=False, optimizer_resumable=False,
        optimizer="fresh_AdamW_default_betas_eps_weight_decay.01", max_grad_norm=1.,
        encoder_context_tokens=512, decoder_output_tokens=512, temperature=0,
        loss_scope="training_full32V_token_cross_entropy_only",
        projection_policy="identity_no_learned_embedding_reconstruction",
        bridge_names=[], legal_ir_evaluate_provers=False, metric_disk_cache_used=False,
        workers=1, elapsed_seconds=time.monotonic()-started, **FALSE)
    receipt["receipt_sha256"] = core.digest(receipt)
    return receipt
