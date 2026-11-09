"""Opt-in custody of source-span batches and retained native conditioning.

This additive engineering profile reuses the zero-latent eligibility, exposure
and split owner without widening its accepted target origins. Original producer
artifacts are reopened before dispatch; caller-written verification flags are
not an input. Derived 384D projections retain saved-output custody only, never
a claim that their numerical computation was replayed or legal meaning proved.
The callback boundary binds arguments, not all process reads or callback effects.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import math
from pathlib import Path

from . import legal_span_consumer_binding as base

SCHEMA = "source-span-context-binding/v1"
PROFILE = "native-context-declared-engineering-supervision/v1"
STAGES = ("raw384", "core384", "trained384", "native768")
SourceSpanContextBindingError = base.SourceSpanConsumerBindingError
_SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LABELS = ("contexts", "context evidence")


def _owner(stage):
    base._require(type(stage) is str and stage in STAGES, "unsupported native context stage")
    name = "legal_native768_contexts" if stage == "native768" else "legal_native384_contexts"
    return importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder." + name)


def _implementation(stage):
    base._require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_SHA,
                  "context binding source changed since import")
    owner = _owner(stage)
    return {"binding_sha256": _SELF_SHA,
            "context_owner_sha256": hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest()}


def _verify(stage, sources, evidence, resolver):
    owner = _owner(stage)
    try:
        if stage == "native768":
            result = owner.verify_native768_contexts(evidence, sources=sources)
        else:
            base._require(evidence.get("stage") == stage, "requested and evidenced context stage differ")
            result = owner.verify_native384_contexts(evidence, sources=sources, source_resolver=resolver)
        # Finite, bounded, detached output even if a delegated validator changes.
        return json.loads(base._preflight(result))
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError) as error:
        raise SourceSpanContextBindingError("native context verification failed: " + str(error)) from error


def _contexts(rows, contexts, dimension):
    base._require(type(contexts) is list and len(contexts) == len(rows),
                  "complete ordered context population required")
    for row, context in zip(rows, contexts):
        base._closed(context, {"id", "source_sha256", "context"}, "native context")
        base._require(type(context["id"]) is str and context["id"] == row["id"]
            and context["source_sha256"] == hashlib.sha256(row["source_text"].encode("utf-8")).hexdigest(),
            "context must bind exact ordered source identity and bytes")
        vector = context["context"]
        base._require(type(vector) is list and len(vector) == dimension,
                      "native context dimension differs")
        base._require(all(type(v) in (int, float) and abs(v) <= 3.4028234e38 and math.isfinite(v)
                          for v in vector), "native context must contain finite float32 numbers")


def _verification_contexts(result):
    # The 768D producer also retains the complete original stage receipt. Those
    # sidecars remain in the verification receipt, never in numerical labels.
    return [{key: row[key] for key in ("id", "source_sha256", "context")}
            for row in result["contexts"]]


def _representation(result, stage):
    representation = result["representation"]
    base._require(type(representation) is dict and
                  {"dimension", "representation_id", "producer_sha256"} <= set(representation),
                  "native representation metadata missing")
    base._require(type(representation["dimension"]) is int and
                  representation["dimension"] == (768 if stage == "native768" else 384),
                  "native representation dimension differs")
    base._text(representation["representation_id"], "representation identity", 512)
    base._sha256(representation["producer_sha256"], "representation producer SHA256")
    return {key: representation[key] for key in ("dimension", "representation_id", "producer_sha256")}


def _retained_split_policy(receipt, verification, stage, contexts, operation):
    """Keep original native768 cohort roles, including duplicate-source roles."""
    if stage != "native768":
        return  # Native384 production receipts have no split assignments.
    memberships = verification.get("provenance", {}).get("selected_source_splits")
    base._require(type(memberships) is list and len(memberships) == len(contexts),
                  "complete original native768 source split membership required")
    wanted = "train" if operation == "training" else "tuning"
    for record, context, member in zip(receipt["rows"], contexts, memberships):
        base._closed(member, {"id", "source_sha256", "splits"}, "native768 source membership")
        base._require(member["id"] == context["id"] and member["source_sha256"] == context["source_sha256"]
            and type(member["splits"]) is list and bool(member["splits"])
            and all(type(s) is str and s in ("train", "tuning", "challenge", "oov") for s in member["splits"])
            and len(member["splits"]) == len(set(member["splits"])), "native768 source membership differs")
        record["original_context_source_splits"] = member["splits"]
        if member["splits"] != [wanted]:
            blocker = {"reason": "original_native_source_split_disallows_operation",
                       "original_splits": member["splits"], "operation": operation}
            record["blockers"].append(blocker)
            record["status"] = "blocked"
            receipt["blockers"].append({"row_index": record["row_index"], "id": record["id"], **blocker})
    receipt["blocked_row_count"] = sum(r["status"] == "blocked" for r in receipt["rows"])
    receipt["ready_row_count"] = receipt["row_count"] - receipt["blocked_row_count"]
    receipt["status"] = "blocked" if receipt["blockers"] else "ready"


@dataclass(frozen=True, slots=True, init=False)
class SourceSpanContextBinding:
    _base_binding: base.SourceSpanConsumerBinding
    _stage: str
    _guards: tuple
    _verification_guard: object
    _implementation_guard: object
    _numerical_guard: object
    _numerical_json: bytes
    _receipt_json: bytes

    def __init__(self):
        raise TypeError("use prepare_source_span_context_binding")

    def receipt(self):
        """Detached complete-denominator input receipt; no execution authority."""
        return json.loads(self._receipt_json)


def prepare_source_span_context_binding(rows, *, expected_rows_sha256, split_manifest,
        expected_split_manifest_sha256, eligibility_records, expected_eligibility_sha256,
        exposure_records, expected_exposure_sha256, operation, stage, contexts,
        expected_contexts_sha256, context_evidence, expected_context_evidence_sha256,
        source_resolver=None):
    """Bind the entire declared batch to its independently pinned context records.

    ``contexts`` is ordered {id, source_sha256, context}. For 384D,
    ``context_evidence`` is the native384 verifier's closed stage/receipt/bundle
    mapping. For 768D it is the original manifest's path/bytes/SHA256 reference.
    All expected content hashes use the existing canonical content-guard recipe.
    """
    _owner(stage)
    for label, digest in zip(_LABELS, (expected_contexts_sha256, expected_context_evidence_sha256)):
        base._sha256(digest, "expected " + label + " SHA256")
    copied_contexts, copied_evidence = json.loads(base._preflight([contexts, context_evidence]))
    base._require(type(copied_evidence) is dict, "context evidence mapping required")
    guards = tuple(base._guard(v, h) for v, h in zip((copied_contexts, copied_evidence),
        (expected_contexts_sha256, expected_context_evidence_sha256)))
    arguments = dict(split_manifest=split_manifest, eligibility_records=eligibility_records,
                     exposure_records=exposure_records)
    original = base.prepare_source_span_consumer_binding(rows,
        expected_rows_sha256=expected_rows_sha256,
        expected_split_manifest_sha256=expected_split_manifest_sha256,
        expected_eligibility_sha256=expected_eligibility_sha256,
        expected_exposure_sha256=expected_exposure_sha256, operation=operation, **arguments)
    receipt = original.receipt()
    detached_rows = json.loads(original._rows_json)
    dimension = 768 if stage == "native768" else 384
    _contexts(detached_rows, copied_contexts, dimension)
    implementation = base._guard(_implementation(stage))
    sources = [{"id": row["id"], "source_text": row["source_text"]} for row in detached_rows]
    verification = _verify(stage, sources, copied_evidence, source_resolver)
    representation = _representation(verification, stage)
    base._check(guards[0], _verification_contexts(verification), "original producer contexts")
    _retained_split_policy(receipt, verification, stage, copied_contexts, operation)
    numerical = [{**row, "latent": context["context"]} for row, context in zip(detached_rows, copied_contexts)]
    # Reuse the dimensional trainer's exact current row grammar, without models.
    if receipt["status"] == "ready":
        from . import legal_span_formula as span
        span._records(numerical, dimension)
    receipt.update(schema=SCHEMA, profile=PROFILE, latent_dimension=dimension,
        context_stage=stage, source_binding_schema=base.SCHEMA,
        context_input_sha256s={"contexts": expected_contexts_sha256,
                              "evidence": expected_context_evidence_sha256},
        context_verification=verification,
        context_contract={**representation, "training_index_sha256": expected_contexts_sha256},
        context_contract_scope="this_batch_only_not_an_automatically_selected_training_lineage",
        strict_dimensional_records_check_passed=receipt["status"] == "ready",
        numerical_rows_sha256=base._guard(numerical).sha256,
        context_implementation=_implementation(stage),
        receipt_scope="source_target_split_custody_and_retained_context_artifact_consistency",
        context_computation_reexecuted=False, runtime_cryptographically_attested=False)
    # Delegated validators and resolvers cannot mutate an original argument and
    # still dispatch under the previously inspected batch.
    base.validate_source_span_consumer_binding(original, rows, **arguments)
    for guard, value, copied, label in zip(guards, (contexts, context_evidence),
                                         (copied_contexts, copied_evidence), _LABELS):
        base._check(guard, value, label)
        base._check(guard, copied, "prepared " + label)
    base._check(implementation, _implementation(stage), "context implementation")
    binding = object.__new__(SourceSpanContextBinding)
    for key, value in {
        "_base_binding": original, "_stage": stage, "_guards": guards,
        "_implementation_guard": implementation, "_verification_guard": base._guard(verification),
        "_numerical_guard": base._guard(numerical), "_numerical_json": base._wire(numerical),
        "_receipt_json": base._preflight(receipt),
    }.items():
        object.__setattr__(binding, key, value)
    return binding


def validate_source_span_context_binding(binding, rows, *, split_manifest, eligibility_records,
        exposure_records, contexts, context_evidence, source_resolver=None):
    """Reopen producer evidence and check unchanged arguments before consumption."""
    base._require(type(binding) is SourceSpanContextBinding, "prepared SourceSpanContextBinding required")
    arguments = dict(split_manifest=split_manifest, eligibility_records=eligibility_records,
                     exposure_records=exposure_records)
    base.validate_source_span_consumer_binding(binding._base_binding, rows, **arguments)
    copies = json.loads(base._preflight([contexts, context_evidence]))
    for guard, value, label in zip(binding._guards, copies, _LABELS):
        base._check(guard, value, label)
    base._check(binding._implementation_guard, _implementation(binding._stage), "context implementation")
    sources = [{"id": row["id"], "source_text": row["source_text"]}
               for row in json.loads(binding._base_binding._rows_json)]
    verification = _verify(binding._stage, sources, copies[1], source_resolver)
    base._check(binding._verification_guard, verification, "retained context verification")
    base.validate_source_span_consumer_binding(binding._base_binding, rows, **arguments)
    for guard, original, copied, label in zip(binding._guards, (contexts, context_evidence), copies, _LABELS):
        base._check(guard, original, label)
        base._check(guard, copied, "validated " + label)
    base._check(binding._implementation_guard, _implementation(binding._stage), "context implementation")
    return binding.receipt()


def consume_source_span_context_binding(binding, rows, *, split_manifest, eligibility_records,
        exposure_records, contexts, context_evidence, consumer, source_resolver=None):
    """One call on detached exact numerical rows per invocation; no automatic retry."""
    receipt = validate_source_span_context_binding(binding, rows, split_manifest=split_manifest,
        eligibility_records=eligibility_records, exposure_records=exposure_records,
        contexts=contexts, context_evidence=context_evidence, source_resolver=source_resolver)
    if receipt["status"] != "ready":
        raise SourceSpanContextBindingError("source-span context batch is blocked", receipt=receipt)
    base._require(callable(consumer), "explicit callable consumer required")
    numerical = json.loads(binding._numerical_json)
    base._check(binding._numerical_guard, numerical, "detached numerical rows")
    return consumer(numerical)


__all__ = ["SourceSpanContextBinding", "SourceSpanContextBindingError",
    "prepare_source_span_context_binding", "validate_source_span_context_binding",
    "consume_source_span_context_binding", "SCHEMA", "PROFILE", "STAGES"]
