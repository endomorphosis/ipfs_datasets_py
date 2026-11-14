"""Receipt-bound, full-population catalog inference using existing owners.

The legacy owner retains custody; the extracted pure inventory performs no
model work. Native receipt consistency grants no encoder or legal authority.
"""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

from . import legal_compact_receipt_bound_source_generation_v1 as custody

SCHEMA = "legal-compact-receipt-bound-catalog-generation/v1"
PROFILE = "full-selected-native-receipt-catalog-bos-generation-384/v1"
VALIDATION_SCHEMA = "legal-compact-receipt-bound-catalog-generation-validation/v1"
MAX_REPORT_BYTES = 96 * 1024**2
MAX_NESTED_BYTES = 8 * 1024**2
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SPECS = (
    ("inventory", "logic/formalization/autoencoder/legal_compact_receipt_source_inventory_v1.py",
     "d2d7cd1f69c2f4e5ba371f7f4d141fae8a2e7c5812c6cbc3f854fc193c0af740"),
    ("custody", "logic/formalization/autoencoder/legal_compact_receipt_bound_source_generation_v1.py",
     "d91475f89dcba669ebc2a778f1dbc18f7eacbc955661f82f0a288de2bb3750f1"),
    ("generation", "logic/formalization/autoencoder/legal_compact_catalog_trained_generation_v1.py",
     "adb05b1ef30a997698aa518ef83ebda5edb483d6276192dbc7c3db1bdbc6a9e5"),
    ("catalog", "logic/formalization/autoencoder/legal_compact_catalog_tokens_v1.py",
     "bc9e425707c98db3425b5dafb1ab75e5c70002cbf6c229ef1f815eb9bb4612af"),
    ("batch", "logic/autoformal/legal_relational_catalog_batch_evaluation_v1.py",
     "96c951967f00eb202c3fc1340e29d034f7184cfeca85dcef20fb3622aeea52e6"),
)
_AUTHORITY = {**custody._AUTHORITY, "catalog_training_verified": False,
              "source_encoder_authenticated": False, "generation_comparison_qualified": False}
_DENIALS = ("encoder_executed_by_adapter", "training_executed", "compact_optimizer_executed",
            "optimizer_constructed", "optimizer_state_restored", "conditioning_producer_verified")
_PURE_FIELDS = ("population", "population_sha256", "checkpoint_sha256", "source_inventory",
                "catalog_inventory", "eligible_mapping", "settings", "pre_generation_sha256")

ReceiptBoundCatalogGenerationError = custody.ReceiptBoundTrainedSourceError
_need, _wire, _digest = custody._need, custody._wire, custody._digest


def _operation(original, source_resolver, work):
    # Reuse the existing detached-input, receipt, source and final-custody owner.
    def owned(data, loaded, outer_fence, references, checks, frozen):
        root = loaded[0]
        observed = [custody._read_identity(_SELF_PATH, _SELF_SHA)]
        observed += [custody._read_identity(root / path, sha) for _, path, sha in _SPECS]
        modules = {}
        def fence():
            outer_fence()
            for pin, witness in observed:
                _need(custody._read_identity(Path(pin["path"]), pin["sha256"], pin["bytes"])[1] == witness,
                      "catalog integration owner changed during operation")
            for name, path, _ in _SPECS:
                if name in modules:
                    _need(type(modules[name].__file__) is str and Path(modules[name].__file__).absolute() == root / path,
                          "catalog integration public owner origin changed")
        checks.append(fence)
        for name, path, _ in _SPECS:
            modules[name] = importlib.import_module("ipfs_datasets_py." + path[:-3].replace("/", "."))
        _need(modules["custody"] is custody and modules["inventory"].custody is custody,
              "existing custody owner differs")
        fence()
        result = work(data, loaded, modules, fence, references, checks, frozen,
                      [pin for pin, _ in observed])
        _wire(result, MAX_REPORT_BYTES)  # Actual aggregate serialized bound; never truncate.
        fence()
        return result
    return custody._operation(original, source_resolver, owned)


def _catalog_inventory(source_inventory, catalog):
    rows, outer_to_eligible, eligible_to_outer = [], [], []
    for index, (conditioning, nominated) in enumerate(zip(source_inventory["source_conditionings"],
                                                         source_inventory["source_reports"])):
        report, binding = nominated["report"], conditioning["report"]
        wrapper, raw, signature_raw, roles_raw = None, None, None, None
        # Prepare even nominated unavailable-vector contexts; their original
        # context disposition remains visible, although they never reach a model.
        if report["status"] == "nominated":
            context = report["context"]
            signature = {**context["signature"], "signature_id": "receipt-bound-catalog-inference-v1"}
            signature_raw = _wire(signature, custody.MAX_CATALOG_BYTES)
            roles_raw = _wire(context["argument_roles"], custody.MAX_CATALOG_BYTES)
            wrapper = catalog.prepare_catalog_context_v1(signature_raw, roles_raw,
                expected_signature_sha256=hashlib.sha256(signature_raw).hexdigest(),
                expected_argument_roles_sha256=hashlib.sha256(roles_raw).hexdigest())
            _need(_wire(wrapper["catalog"]) == _wire(context), "whole nominated context changed in catalog wrapper")
            raw = _wire(wrapper, custody.MAX_CATALOG_BYTES)
        eligible = binding["status"] == "embedded" and report["status"] == "nominated"
        reason = None if eligible else ("source_conditioning_" + binding["status"]
            if binding["status"] != "embedded" else "source_context_" + report["status"])
        outer_to_eligible.append(len(eligible_to_outer) if eligible else None)
        if eligible: eligible_to_outer.append(index)
        rows.append({"id": nominated["id"], "source_report_sha256": nominated["report_sha256"],
            "source_catalog_sha256": report["catalog_sha256"],
            "nominated_context_sha256": report["context_sha256"],
            "signature_utf8": signature_raw.decode("utf-8") if signature_raw is not None else None,
            "signature_sha256": hashlib.sha256(signature_raw).hexdigest() if signature_raw is not None else None,
            "argument_roles_utf8": roles_raw.decode("utf-8") if roles_raw is not None else None,
            "argument_roles_sha256": hashlib.sha256(roles_raw).hexdigest() if roles_raw is not None else None,
            "catalog_context_utf8": raw.decode("utf-8") if raw is not None else None,
            "catalog_context_sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
            "eligible": eligible, "reason": reason})
    return rows, {"outer_to_eligible": outer_to_eligible, "eligible_to_outer": eligible_to_outer}


def _prepare(data, loaded, modules, fence, references, checks, frozen, pins, source_resolver, offered=None):
    source_inventory, _, _ = modules["inventory"]._prepare_inventory(
        data, loaded, fence, references, checks, frozen, source_resolver)
    catalog_inventory, mapping = _catalog_inventory(source_inventory, modules["catalog"])
    settings = dict(max_new_tokens=data["max_new_tokens"], max_total_ids=512,
                    prefix_origin="bos_seed", catalog_context_origin="caller_supplied_unverified")
    pure = {"population": source_inventory["population"], "population_sha256": data["expected_population_sha256"],
        "checkpoint_sha256": data["expected_checkpoint_sha256"], "source_inventory": source_inventory,
        "catalog_inventory": catalog_inventory, "eligible_mapping": mapping, "settings": settings}
    pure["pre_generation_sha256"] = _digest(pure, MAX_REPORT_BYTES)
    frozen.append((pure, _wire(pure, MAX_REPORT_BYTES)))
    if offered is not None:
        _need(all(key in offered and _wire(offered[key], MAX_REPORT_BYTES) == _wire(pure[key], MAX_REPORT_BYTES)
                  for key in _PURE_FIELDS), "offered report differs from frozen catalog pre-generation inventory")
    fence()
    generation, slots, observations = modules["generation"], [], []
    original_count, replay_count = 0, 0
    codec = modules["catalog"].build_compact_catalog_token_codec_v1()
    for index, (occurrence, context) in enumerate(zip(pure["population"]["rows"], catalog_inventory)):
        binding = source_inventory["source_conditionings"][index]["report"]
        nominated = source_inventory["source_reports"][index]["report"]
        trajectory, adapter = None, None
        if context["eligible"]:
            kwargs = dict(expected_checkpoint_sha256=data["expected_checkpoint_sha256"],
                expected_catalog_context_sha256=context["catalog_context_sha256"],
                max_new_tokens=data["max_new_tokens"], prefix_origin="bos_seed",
                catalog_context_origin="caller_supplied_unverified")
            raw = context["catalog_context_utf8"].encode("utf-8")
            trajectory = generation.generate_compact_catalog_trained_v1(
                data["checkpoint"], binding["conditioning"], [1], raw, **kwargs)
            frozen.append((trajectory, _wire(trajectory, MAX_NESTED_BYTES)))
            fence()
            trajectory_sha = generation.compact_catalog_trained_generation_sha256(trajectory)
            adapter = generation.prepare_compact_catalog_trained_batch_prediction_v1(
                trajectory, data["checkpoint"], binding["conditioning"], [1], raw, data["population_raw"],
                expected_generation_sha256=trajectory_sha, expected_population_sha256=data["expected_population_sha256"],
                occurrence_id=occurrence["id"], **kwargs)
            frozen.append((adapter, _wire(adapter, MAX_NESTED_BYTES)))
            _need(adapter["population_raw_utf8"].encode("utf-8") == data["population_raw"]
                  and adapter["source_context_sha256"] == occurrence["context_sha256"]
                  and adapter["encoder_sha256"] is None and adapter["generation_comparison_qualified"] is False
                  and adapter["generation_validation"]["generation_report"] == trajectory,
                  "whole original population/replay binding differs")
            count = trajectory["numerical_forward_count"]
            _need(type(count) is int and 0 <= count <= data["max_new_tokens"]
                  and adapter["replay_forward_count"] == adapter["numerical_forward_count"] == count
                  and adapter["original_forward_count"] == 0, "catalog adapter replay accounting differs")
            original_count += count
            replay_count += count
            observation = adapter["prediction_row"]
        else:
            observation = {**occurrence, "status": "abstained", "teacher_forcing": False, "target_access": False,
                "generated_ids": None, "generated_ids_sha256": None, "reason": context["reason"],
                "catalog_context_utf8": None, "catalog_context_sha256": None,
                "catalog_context_origin": None}
        observations.append(observation)
        slots.append({"index": index, "id": occurrence["id"], "embedding_status": binding["status"],
            "source_context_status": nominated["status"], "status": observation["status"], "reason": observation["reason"],
            "generation": trajectory, "adapter": adapter})
        fence()
    predictions = {"schema": generation.PREDICTIONS_SCHEMA, "codec": codec, "codec_sha256": _digest(codec),
        "generation": {"kind": "decoder_declared", "population_sha256": data["expected_population_sha256"],
            "latent_dimension": 384, "checkpoint_sha256": data["expected_checkpoint_sha256"], "encoder_sha256": None,
            "settings_sha256": _digest(settings), "teacher_forcing": False, "target_access": False}, "rows": observations}
    # No target/reference enters inference. Explicit unavailable reference rows
    # permit full-denominator diagnostic accounting without inventing gold.
    reference_rows = {"schema": "legal-relational-batch-references/v1", "population_sha256": data["expected_population_sha256"],
        "rows": [{"id": row["id"], "status": "unavailable", "request_utf8": None, "request_sha256": None,
                  "report": None, "report_sha256": None, "reason": "No reviewed reference supplied"}
                 for row in pure["population"]["rows"]]}
    reference_raw, prediction_raw = _wire(reference_rows), _wire(predictions)
    evaluation = modules["batch"].prepare_relational_catalog_batch_evaluation_v1(
        data["population_raw"], reference_raw, prediction_raw,
        expected_population_sha256=data["expected_population_sha256"],
        expected_references_sha256=hashlib.sha256(reference_raw).hexdigest(),
        expected_predictions_sha256=hashlib.sha256(prediction_raw).hexdigest())
    _wire(evaluation, MAX_NESTED_BYTES)
    counts = {"selected": len(slots), "eligible": len(mapping["eligible_to_outer"]),
        "generated": sum(slot["status"] == "generated" for slot in slots),
        "abstained": sum(slot["status"] == "abstained" for slot in slots),
        "complete": sum(slot["generation"] is not None and slot["generation"]["status"] == "complete" for slot in slots),
        "conditioning_unavailable": sum(slot["embedding_status"] != "embedded" for slot in slots),
        "producer_receipt_inputs": sum(row["input_count"] for row in source_inventory["receipt_inventory"]),
        "original_numerical_forward_count": original_count, "adapter_replay_numerical_forward_count": replay_count,
        "total_numerical_forward_count": original_count + replay_count, "comparison_eligible": 0, "comparison_credit": 0}
    result = {"schema": SCHEMA, "profile": PROFILE, "status": "complete_outer_population", **pure,
        "slots": slots, "counts": counts, "predictions": predictions, "predictions_sha256": _digest(predictions),
        "references": reference_rows, "batch_evaluation": evaluation,
        "model_executed": bool(original_count + replay_count), **dict.fromkeys(_DENIALS, False),
        "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        "owner_pins": pins, "limitations": [
            "Receipt/source consistency does not authenticate an encoder, runtime, legal semantics, context permission or conditioning-space compatibility.",
            "The original selected population and complete producer inputs remain distinct from the eligible map; declared abstentions remain visible even under provenance precedence.",
            "The entire nominated catalog is fixed before BOS inference; generated-expression selection cannot shrink the inference catalog.",
            "Nested original counters are historical during validation; adapter and validation replay counters overlap and must not be summed twice.",
            "Failure or cancellation can follow numerical work; absence of a successful report is not zero cost. The admitted enclosing observer retains attempts.",
            "This profile permits 16 rows and 12 new tokens: at most 384 forwards per preparation including mandatory replay, without truncating a report that exceeds its aggregate bound."]}
    _wire(result, MAX_REPORT_BYTES)
    fence()
    return result


def prepare_receipt_bound_catalog_generation_v1(population_raw, rows, checkpoint, *,
        expected_population_sha256, expected_checkpoint_sha256, max_new_tokens, source_resolver):
    original = custody._inputs(population_raw, rows, checkpoint, expected_population_sha256,
                               expected_checkpoint_sha256, max_new_tokens)
    return _operation(original, source_resolver, lambda *args: _prepare(*args, source_resolver))


def receipt_bound_catalog_generation_sha256(report):
    def work(data, *args):
        _need(type(data["report"]) is dict and data["report"].get("schema") == SCHEMA
              and data["report"].get("profile") == PROFILE, "versioned receipt-bound catalog report required")
        return {"sha256": _digest(data["report"], MAX_REPORT_BYTES)}
    return _operation({"report": report}, None, work)["sha256"]


def validate_receipt_bound_catalog_generation_v1(report, population_raw, rows, checkpoint, *,
        expected_report_sha256, expected_population_sha256, expected_checkpoint_sha256,
        max_new_tokens, source_resolver):
    original = custody._inputs(population_raw, rows, checkpoint, expected_population_sha256,
                               expected_checkpoint_sha256, max_new_tokens)
    original.update(report=report, expected_report_sha256=expected_report_sha256)
    def work(data, *args):
        custody._hash(data["expected_report_sha256"], "original catalog report")
        offered = data["report"]
        _need(type(offered) is dict and _digest(offered, MAX_REPORT_BYTES) == data["expected_report_sha256"],
              "original catalog report commitment differs")
        _need(offered.get("schema") == SCHEMA and offered.get("profile") == PROFILE
              and offered.get("status") == "complete_outer_population"
              and type(offered.get("authority")) is dict and set(offered["authority"]) == set(_AUTHORITY)
              and all(value is False for value in offered["authority"].values())
              and all(offered.get(name) is False for name in _DENIALS)
              and all(type(offered.get(name)) is int and offered[name] == 0
                      for name in ("training_mask", "evaluation_gold_mask")), "fixed authority/mask/execution denials differ")
        regenerated = _prepare(data, *args, source_resolver, offered=offered)
        _need(_wire(regenerated, MAX_REPORT_BYTES) == _wire(offered, MAX_REPORT_BYTES),
              "catalog report differs from complete original-bound replay")
        count = regenerated["counts"]["total_numerical_forward_count"]
        return {"schema": VALIDATION_SCHEMA, "generation_report": regenerated,
            "generation_sha256": data["expected_report_sha256"], "generation_regenerated": True,
            "original_generation_forward_count": count, "original_forward_count": 0,
            "replay_forward_count": count, "numerical_forward_count": count, "reference_forward_count": 0,
            "count_categories_overlap": True, "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0}
    return _operation(original, source_resolver, work)


__all__ = ["ReceiptBoundCatalogGenerationError", "prepare_receipt_bound_catalog_generation_v1",
           "receipt_bound_catalog_generation_sha256", "validate_receipt_bound_catalog_generation_v1"]
