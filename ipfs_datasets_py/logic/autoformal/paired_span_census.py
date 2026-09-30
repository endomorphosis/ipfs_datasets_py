"""Bounded, typed paired conversions and deferred work, with explicit provenance.

The legacy decoder produces vectors. Neither its source-derived bridge target
nor a compiler guided by those vectors is an independent autoencoder formula.
This module makes that distinction queryable and compares actual formal ASTs
only. Structural agreement is never proof, qualification, or Lake admission.

Three Parquet tables comprise a bundle: paired_spans, goals, and artifacts.
Large bridge documents and exact portable supervisor packets live once in the
artifact table. Historical exchange manifests remain untouched and importable.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
import math
from pathlib import Path
import re
import zlib
from typing import Any


SCHEMA = "uscode-paired-span-census/v1"
MANIFEST_SCHEMA = "uscode-paired-span-bundle/v1"
REPOSITORY = "justicedao/uscode-autoformal-span-cache"
REPO_PREFIX = "autoformal/uscode/paired-v1"
MAX_ROWS = 128
MAX_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
TABLE_NAMES = ("paired_spans", "goals", "artifacts")
FORMAL_FORMAT = "typed-deontic-rule/v1"
EXPORTER_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class PairedCensusError(ValueError):
    """Malformed, ambiguous, unbound, or oversized observation evidence."""


def _json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True,
                          separators=(",", ":"), allow_nan=False).encode("ascii")
    except (TypeError, ValueError, RecursionError) as error:
        raise PairedCensusError("evidence must be finite JSON data") from error


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise PairedCensusError("metric must be a finite number")
    try:
        result = float(value)
    except (ValueError, TypeError) as error:
        raise PairedCensusError("metric must be a finite number") from error
    if not math.isfinite(result):
        raise PairedCensusError("metric must be a finite number")
    return result


def _vector(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) > 65536:
        raise PairedCensusError("decoder vector exceeds its bounded sequence contract")
    result = [_number(item) for item in value]
    if any(item is None for item in result):
        raise PairedCensusError("decoder vector contains a missing value")
    return result


def _formal(value: Mapping, *, origin: str | None = None) -> dict:
    if not isinstance(value, Mapping) or "payload" not in value:
        raise PairedCensusError("formal outputs require an explicit AST or formula payload")
    family, format_name = value.get("family"), value.get("format")
    if not isinstance(family, str) or not family or not isinstance(format_name, str) or not format_name:
        raise PairedCensusError("formal outputs require a family and representation format")
    payload = value["payload"]
    if not isinstance(payload, (Mapping, list, str)) or not payload:
        raise PairedCensusError("empty or scalar values are not formal outputs")
    raw = _json(payload)
    if len(raw) > 1024 * 1024:
        raise PairedCensusError("formal output exceeds 1 MiB")
    return {"family": family, "format": format_name, "payload_json": raw.decode(),
            "sha256": _sha(raw), "origin": origin or str(value.get("origin") or "unspecified"),
            "independent": value.get("independent") is True,
            "target_conditioned": value.get("target_conditioned") is not False,
            "syntax_status": str(value.get("syntax_status") or "not_run")}


def compare_formal_outputs(autoencoder: Mapping, compiler: Mapping) -> dict:
    """Exact canonical AST comparison, preserving every field, order and duplicate.

    Caller must retain outputs normalized by this module. No text similarity,
    family classifier, shared target, or successful decompilation substitutes
    for independently produced formal outputs. Syntax validation is separately
    required; agreement concerns exact representation, not semantic equivalence.
    """
    ae, cc = autoencoder.get("formal_outputs") or [], compiler.get("formal_outputs") or []
    result = {"status": "both_unavailable", "comparable": False, "agrees": None,
              "independent": False, "method": "exact_canonical_ast_sequence/v1",
              "coverage_scope": "all_emitted_formulas_not_semantic_span_coverage",
              "reason": "neither_producer_emitted_formal_output", "mismatches": [],
              "autoencoder_output_count": len(ae), "compiler_output_count": len(cc)}
    if not ae or not cc:
        if cc:
            result.update(status="autoencoder_unavailable", reason="no_autoencoder_formal_output")
        elif ae:
            result.update(status="compiler_unavailable", reason="no_compiler_formal_output")
        return result
    bound = autoencoder.get("source_binding_verified") is True
    guided = bound and all(output.get("origin") == "autoencoder_guided_compiler" for output in ae)
    independent = bound and all(
        output.get("origin") == "autoencoder_decoder"
        and output.get("independent") is True and output.get("target_conditioned") is False
        for output in ae)
    result["independent"] = independent
    if not independent and not guided:
        result.update(status="incomparable", reason="autoencoder_output_not_independent_or_source_bound")
        return result
    if autoencoder.get("complete") is not True or compiler.get("complete") is not True:
        result.update(status="partial", reason="complete_span_coverage_unverified")
        return result
    if independent and any(output.get("syntax_status") not in {"passed", "compiler_accepted"} for output in [*ae, *cc]):
        result.update(status="incomparable", reason="formal_syntax_unverified")
        return result
    if {(x["family"], x["format"]) for x in ae} != {(x["family"], x["format"]) for x in cc}:
        result.update(status="incomparable", reason="formal_representations_differ")
        return result
    # Sorting JSON object keys is lossless. Lists and component multiplicity are
    # deliberately not sorted, deduplicated, or reduced to shared family labels.
    left = [(x["family"], x["format"], x["payload_json"]) for x in ae]
    right = [(x["family"], x["format"], x["payload_json"]) for x in cc]
    agrees = left == right
    prefix = "diagnostic_" if guided else ""
    result.update(status=prefix + ("agree" if agrees else "disagree"), comparable=True, agrees=agrees,
                  reason="identical_formal_representations" if agrees else "formal_output_mismatch")
    if not agrees:
        result["mismatches"] = [str(index) for index in range(max(len(left), len(right)))
                                if index >= len(left) or index >= len(right) or left[index] != right[index]]
    return result


class _Artifacts:
    def __init__(self, limit: int):
        self.limit = limit
        self.decoded_bytes = 0
        self.rows: dict[str, dict] = {}

    def add(self, value: Any, kind: str, *, exact: bytes | None = None) -> str:
        raw = _json(value) if exact is None else exact
        artifact_limit = min(self.limit, MAX_BYTES) if kind == "original_producer_receipt" else MAX_ARTIFACT_BYTES
        if len(raw) > artifact_limit:
            raise PairedCensusError("artifact exceeds decoded byte bound")
        digest = _sha(raw)
        if digest not in self.rows:
            if self.decoded_bytes + len(raw) > self.limit:
                raise PairedCensusError("bundle artifacts exceed decoded byte bound")
            self.rows[digest] = {"artifact_sha256": digest, "kind": kind,
                                 "encoding": "zlib-json/v1", "decoded_bytes": len(raw),
                                 "payload": zlib.compress(raw, level=3)}
            self.decoded_bytes += len(raw)
        return digest


def decode_artifact(artifact: Mapping, *, max_bytes: int = MAX_BYTES) -> bytes:
    """Bound decompression before allocating the decoded payload; verify its hash."""
    size = artifact.get("decoded_bytes")
    kind_limit = MAX_BYTES if artifact.get("kind") == "original_producer_receipt" else MAX_ARTIFACT_BYTES
    if type(size) is not int or size < 0 or size > min(max_bytes, kind_limit) or artifact.get("encoding") != "zlib-json/v1":
        raise PairedCensusError("unsupported artifact encoding or decoded bound")
    payload = artifact.get("payload")
    if not isinstance(payload, bytes) or len(payload) > kind_limit + 65536:
        raise PairedCensusError("artifact compressed payload exceeds bound")
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(payload, size + 1)
    except zlib.error as error:
        raise PairedCensusError("corrupt artifact compression") from error
    if len(raw) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise PairedCensusError("artifact decoded size or stream differs")
    if _sha(raw) != artifact.get("artifact_sha256"):
        raise PairedCensusError("artifact hash differs")
    return raw


def _status(compiler: Mapping) -> str:
    return str(compiler.get("compiler_status") or compiler.get("status") or "not_observed")


def _is_constitution(observation: Mapping, retained: Mapping) -> bool:
    return observation.get("constitution_source") is True or retained.get("constitution_source") is True or any(
        "constitution" in str(source.get(key, "")).lower()
        for source in (observation, retained)
        for key in ("legal_id", "corpus", "source_span_id", "source_url", "source_path", "dataset_id"))


def _goal_base(identifier: str, *, issue: str, work_kind: str, kind: str, code: str, model: str) -> dict:
    return {"goal_id": identifier, "record_kind": kind, "issue": issue, "work_kind": work_kind,
            "status": "deferred", "source_span_ids": [], "observation_ids": [],
            "packet_sha256": None, "task_sha256": None, "packet_artifact_sha256": None,
            "task_artifact_sha256": None, "packet_schema": None, "task_schema": None,
            "legacy_census_sha256": None, "code_identity": code, "model_identity": model,
            "repository_id": None, "agent_id": None, "release_id": None, "legal_id": None,
            "enqueued": False, "admitted": False}


def _portable_repairs(spans: list[dict], *, repository_id: str, agent_id: str,
                      release_id: str, code_identity: str, model_identity: str) -> list[dict]:
    """Use the existing sealed packet builder without regenerating a legacy census."""
    from .family_supervision import supervisor_repair_goals
    from .supervisor_queue import approved_edit_scope, RepairQueueError
    from .span_cache_exchange import GOAL_EXPORT_SCHEMA, _validate_goal_rows
    result = []
    for span in spans:
        if span["source"]["constitution"]:
            continue
        failed = not span["compiler"]["canonical_complete"]
        disagreement = (span["comparison"]["status"] in {"disagree", "diagnostic_disagree"}
                        or (span["autoencoder"]["status"] == "guided_no_formulas"
                            and span["compiler"]["complete"] is True
                            and bool(span["compiler"]["formal_outputs"])))
        if not failed and not disagreement:
            continue
        reason = span["compiler"]["reason"] if failed else "strict_roundtrip_failed"
        try:
            approved_edit_scope(reason)
        except RepairQueueError:
            reason = "compiler_abstain"
        source = span["source"]
        context = {"census_sha256": span["observation_id"], "source_text_sha256": source["text_sha256"],
                   "paired_schema": SCHEMA, "comparison": span["comparison"],
                   "compiler_canonical_complete": span["compiler"]["canonical_complete"],
                   "autoencoder_formal_output_hashes": [row["sha256"] for row in span["autoencoder"]["formal_outputs"]],
                   "compiler_formal_output_hashes": [row["sha256"] for row in span["compiler"]["formal_outputs"]],
                   "canonical_compiler_formal_output_hashes": [row["sha256"] for row in span["compiler"]["canonical_formal_outputs"]],
                   "source_target_artifact_sha256": span["source_target_artifact_sha256"],
                   "source_target_artifact_pointer": span["source_target_artifact_pointer"],
                   "comparison_is_not_validation": True,
                   "instruction": "Reproduce and investigate the retained discrepancy. A guided comparison is diagnostic and does not establish that either producer is correct. Preserve all existing regression and Lake admission gates."}
        observed = {"id": source["span_id"], "source_span_id": source["span_id"], "legal_id": source["legal_id"],
                    "text": source["text"], "decompiled": span["compiler"]["decompiled"], "reason": reason,
                    "agrees": False, "skipped": False, "capture": context}
        work = supervisor_repair_goals([observed], release_id=release_id, code_identity=code_identity, model_identity=model_identity)
        for entry in work["repair_packets"]:
            packet, task = entry["packet"], entry["task"]
            packet_raw, task_raw = _json(packet), _json(task)
            result.append({"schema_version": GOAL_EXPORT_SCHEMA, "record_kind": "repair_packet",
                "repository_id": repository_id, "agent_id": agent_id, "source_span_id": source["span_id"],
                "legal_id": source["legal_id"], "task_id": task["task_id"], "packet_sha256": _sha(packet_raw),
                "task_sha256": _sha(task_raw), "census_sha256": span["observation_id"],
                "packet_schema": packet["schema"], "todo_schema": task["schema"], "handoff_status": "dataset",
                "packet_json": packet_raw.decode(), "task_json": task_raw.decode(), "release_id": release_id,
                "code_identity": code_identity, "model_identity": model_identity,
                "admitted": False, "formalized": False, "wrote_compiler": False, "enqueued": False})
    _validate_goal_rows(result)
    return result


def build_paired_census(
    observations: Iterable[Mapping], *, goal_rows: Iterable[Mapping] = (),
    repository_id: str = REPOSITORY, agent_id: str = "paired-census",
    code_identity: str = "unrecorded", model_identity: str = "unrecorded",
    max_rows: int = MAX_ROWS, max_bytes: int = MAX_BYTES,
    original_receipt: Mapping | None = None, release_id: str = "ipfs-uscode-5016b86a",
) -> dict:
    """Build bounded tables from runner ``exchange_rows`` or raw legacy rows.

    Optional ``model_formal_outputs`` must be explicitly source/model bound by
    ``model_formal_output_provenance``. Each output declares its origin,
    independence, target conditioning and syntax status. Source-derived targets
    are retained only as artifacts. Existing supervisor packet/task bytes are
    preserved exactly; their import authority remains with the existing importer.
    """
    if type(max_rows) is not int or max_rows < 1 or type(max_bytes) is not int or max_bytes < 1:
        raise PairedCensusError("positive row and byte bounds required")
    if any(not isinstance(x, str) or not x.strip() for x in (repository_id, agent_id, code_identity, model_identity)):
        raise PairedCensusError("repository, agent and producer identities required")
    artifacts = _Artifacts(max_bytes)
    receipt_ref = artifacts.add(original_receipt, "original_producer_receipt") if original_receipt is not None else None
    receipt_rows = {row.get("source_span_id"): index for index, row in enumerate(original_receipt.get("rows", []))} if original_receipt is not None else {}
    paired, goals, spans = [], {}, {}
    retained_size = 0
    for original in observations:
        if len(paired) >= max_rows or not isinstance(original, Mapping):
            raise PairedCensusError("observation row count or type exceeds contract")
        observed = _mapping(original.get("autoencoder_observation")) or original
        span_id = original.get("source_span_id", observed.get("source_span_id"))
        text = original.get("text", original.get("source_text", observed.get("text")))
        if not isinstance(span_id, str) or not span_id.strip() or not isinstance(text, str) or not text.strip():
            raise PairedCensusError("full source text and span identity required")
        if span_id in spans:
            raise PairedCensusError("duplicate source span within one producer batch")
        text_hash = _sha(text.encode())
        expected_hash = original.get("source_text_sha256", original.get("source_sha256", observed.get("source_sha256")))
        if expected_hash is not None and expected_hash != text_hash:
            raise PairedCensusError("source text hash differs")
        compiler = _mapping(original.get("compiler_result")) or _mapping(observed.get("compiler"))
        rules = compiler.get("rules")
        if rules is None:
            rules = [compiler["rule"]] if isinstance(compiler.get("rule"), Mapping) else []
        if not isinstance(rules, list) or any(not isinstance(rule, Mapping) for rule in rules):
            raise PairedCensusError("compiler rules must retain their full structured list")
        canonical_formal = [_formal({"family": "typed_deontic", "format": FORMAL_FORMAT, "payload": rule,
                             "independent": True, "target_conditioned": False,
                             "syntax_status": "compiler_accepted"}, origin="deterministic_compiler") for rule in rules]
        direct = original.get("direct_formal_outputs", observed.get("direct_formal_outputs"))
        if direct is not None and not isinstance(direct, list):
            raise PairedCensusError("direct formal outputs must be a list")
        cc_formal = [_formal(output) for output in direct] if direct is not None else canonical_formal
        direct_binding = _mapping(original.get("direct_formal_output_provenance", observed.get("direct_formal_output_provenance")))
        raw, projected = _mapping(observed.get("raw_decoder")), _mapping(observed.get("safety_projected_decoder"))
        supplied_formal = original.get("model_formal_outputs", observed.get("model_formal_outputs", []))
        if not isinstance(supplied_formal, list):
            raise PairedCensusError("model formal outputs must be a list")
        ae_formal = [_formal(output) for output in supplied_formal]
        binding = _mapping(original.get("model_formal_output_provenance", observed.get("model_formal_output_provenance")))
        bound_model = binding.get("model_identity") == model_identity
        if isinstance(binding.get("model_identity"), Mapping) and original_receipt is not None:
            model = binding["model_identity"]
            checkpoint = _mapping(original_receipt.get("checkpoint"))
            bound_model = (re.fullmatch(r"[0-9a-f]{64}", str(model.get("sha256") or "")) is not None
                           and model_identity.endswith("sha256:" + model["sha256"])
                           and model.get("sha256") == checkpoint.get("sha256")
                           and model.get("bytes") == checkpoint.get("bytes"))
        bound = binding.get("source_text_sha256") == text_hash and bound_model
        ae_status = "formal_output_observed" if ae_formal else "unsupported_symbolic_decoder" if raw else "not_observed"
        guided_route = binding.get("origin") == "autoencoder_guided_compiler"
        if not ae_formal and guided_route:
            ae_status = "guided_no_formulas" if bound and binding.get("complete") is True else "guided_unavailable"
        if any(output["origin"] == "autoencoder_guided_compiler" for output in ae_formal):
            ae_status = "guided_output"
        representation = _mapping(observed.get("embedding_representation"))
        constitution = _is_constitution(original, observed)
        batch = _mapping(original.get("batch_observation"))
        campaign, timing = _mapping(batch.get("campaign")), _mapping(batch.get("timings"))
        target = original.get("logic_target_observation", observed.get("logic_target_observation"))
        receipt_index = receipt_rows.get(span_id)
        if receipt_ref is not None and receipt_index is None:
            raise PairedCensusError("original receipt is missing observed span")
        if receipt_ref is not None:
            retained_row = original_receipt["rows"][receipt_index]
            if retained_row.get("text") != text or retained_row.get("source_span_id") != span_id:
                raise PairedCensusError("original receipt source differs from paired observation")
        target_ref = (receipt_ref if receipt_ref else artifacts.add(target, "source_bridge_target")) if isinstance(target, Mapping) else None
        target_path = f"/rows/{receipt_index}/logic_target_observation" if target_ref and receipt_ref else ""
        components = compiler.get("components") or []
        if not isinstance(components, list):
            raise PairedCensusError("compiler components must be a list")
        # Components can contain large duplicated rule/text records. Keep one
        # exact artifact, while exposing the rules and count directly for queries.
        component_ref = (receipt_ref if receipt_ref else artifacts.add(components, "compiler_components")) if components else None
        row = {"schema_version": SCHEMA, "repository_id": repository_id,
               "source": {"span_id": span_id, "text": text, "text_sha256": text_hash,
                          "legal_id": str(original.get("legal_id", observed.get("legal_id", ""))),
                          "revision": str(original.get("release_id") or campaign.get("source_revision") or release_id),
                          "constitution": constitution},
               "autoencoder": {"status": ae_status, "model_identity": model_identity,
                               "embedding_model": str(representation.get("embedding_model") or ""),
                               "semantic_embeddings": representation.get("semantic_embeddings") is True,
                               "formal_outputs": ae_formal, "source_binding_verified": bound,
                               "complete": binding.get("complete") is True,
                               "raw_vector": _vector(raw.get("embedding")),
                               "cosine_similarity": _number(raw.get("cosine_similarity")),
                               "reconstruction_loss": _number(raw.get("reconstruction_loss")),
                               "projected_vector": _vector(projected.get("embedding")),
                               "projected_cosine_similarity": _number(projected.get("cosine_similarity")),
                               "projected_reconstruction_loss": _number(projected.get("reconstruction_loss")),
                               "projected_target_conditioned": bool(projected)},
               "compiler": {"status": _status(compiler), "reason": str(compiler.get("reason") or compiler.get("error_code") or ""),
                            "complete": (direct_binding.get("complete") is True
                                         and direct_binding.get("source_text_sha256") == text_hash)
                                        if direct is not None else compiler.get("compilation_complete") is True,
                            "canonical_complete": compiler.get("compilation_complete") is True,
                            "decompiled": str(compiler.get("decompiled") or original.get("decompiled") or ""),
                            "roundtrip_ok": False if constitution else compiler.get("roundtrip") is True,
                            "formal_outputs": cc_formal, "canonical_formal_outputs": canonical_formal,
                            "component_count": len(components), "components_artifact_sha256": component_ref,
                            "components_artifact_pointer": f"/rows/{receipt_index}/compiler/components" if component_ref and receipt_ref else ""},
               "provenance": {"agent_id": agent_id, "code_identity": code_identity,
                              "model_identity": model_identity, "batch_id": str(campaign.get("batch_id") or ""),
                              "elapsed_seconds": _number(timing.get("elapsed_seconds")),
                              "wall_seconds_per_span": _number(timing.get("wall_seconds_per_span")),
                              "bridge_names": [str(x) for x in _mapping(batch.get("bridges")).get("evaluation_invoked", [])],
                              "evaluate_provers": _mapping(batch.get("bridges")).get("evaluate_provers"),
                              "disk_cache": _mapping(batch.get("bridges")).get("disk_cache"),
                              "parallel_workers": _mapping(batch.get("bridges")).get("parallel_workers"),
                              "sample_count": batch.get("sample_count")},
               "lake": {"status": "not_run", "receipt_sha256": None, "admitted": False},
               "source_target_artifact_sha256": target_ref, "source_target_artifact_pointer": target_path, "goal_ids": [],
               "admitted": False, "formalized": False}
        row["comparison"] = compare_formal_outputs(row["autoencoder"], row["compiler"])
        row["observation_id"] = _sha(_json(row))
        paired.append(row)
        spans[span_id] = row
        retained_size += len(_json(row))
        if retained_size + artifacts.decoded_bytes > max_bytes:
            raise PairedCensusError("bundle decoded bytes exceed bound")
        if not ae_formal and not guided_route:
            contract = {"model_identity": model_identity, "decoder_contract": "independent_symbolic_output/v1"}
            identifier = "CAPABILITY-" + _sha(_json(contract))
            goal = goals.setdefault(identifier, _goal_base(identifier,
                issue="No independent symbolic decoder output is available for paired comparison.",
                work_kind="symbolic_decoder_capability", kind="capability_gap", code=code_identity, model=model_identity))
            goal["source_span_ids"].append(span_id)
            goal["observation_ids"].append(row["observation_id"])
            row["goal_ids"].append(identifier)
    pending_goals = []
    for goal in goal_rows:
        if len(pending_goals) >= max_rows * 2:
            raise PairedCensusError("portable goal count exceeds bound")
        pending_goals.append(goal)
    if not pending_goals:
        pending_goals = _portable_repairs(paired, repository_id=repository_id, agent_id=agent_id,
                                           release_id=release_id, code_identity=code_identity, model_identity=model_identity)
    for legacy in pending_goals:
        if not isinstance(legacy, Mapping) or legacy.get("source_span_id") not in spans:
            raise PairedCensusError("portable goal refers to an absent paired observation")
        if legacy.get("enqueued") is not False or legacy.get("admitted") is not False:
            raise PairedCensusError("portable goals must remain deferred and unadmitted")
        span = spans[legacy["source_span_id"]]
        packet_raw, task_raw = legacy.get("packet_json"), legacy.get("task_json")
        if not isinstance(packet_raw, str) or not isinstance(task_raw, str):
            raise PairedCensusError("portable goal requires exact packet/task JSON")
        packet_bytes, task_bytes = packet_raw.encode(), task_raw.encode()
        if _sha(packet_bytes) != legacy.get("packet_sha256") or _sha(task_bytes) != legacy.get("task_sha256"):
            raise PairedCensusError("portable goal hash differs")
        try:
            packet, task = json.loads(packet_raw), json.loads(task_raw)
        except (ValueError, TypeError) as error:
            raise PairedCensusError("portable goal JSON is invalid") from error
        if not isinstance(packet, dict) or not isinstance(task, dict):
            raise PairedCensusError("portable goal payloads must be objects")
        task_id = legacy.get("task_id")
        if not isinstance(task_id, str) or not task_id or task.get("task_id") != task_id:
            raise PairedCensusError("portable goal task identity differs")
        if legacy.get("code_identity") != code_identity or legacy.get("model_identity") != model_identity:
            raise PairedCensusError("portable goal producer identity differs")
        capture = _mapping(_mapping(packet.get("row")).get("capture"))
        kind = str(legacy.get("record_kind") or "")
        reason = str(_mapping(packet.get("row")).get("reason") or task.get("reason") or span["compiler"]["reason"] or span["comparison"]["reason"])
        # Existing inference-only rows repeat the same unsupported decoder issue
        # per span. Canonical output preserves one capability goal per contract;
        # original packets remain in their immutable historical exchange bundle.
        if kind == "training_goal" and not span["autoencoder"]["formal_outputs"] and not capture.get("below_threshold"):
            continue
        goal = _goal_base(task_id, issue=reason,
                          work_kind=str(task.get("work_kind") or ("compiler_decompiler_repair" if kind == "repair_packet" else "autoencoder_training")),
                          kind=kind, code=code_identity, model=model_identity)
        goal.update(source_span_ids=[span["source"]["span_id"]], observation_ids=[span["observation_id"]],
                    packet_sha256=_sha(packet_bytes), task_sha256=_sha(task_bytes),
                    packet_artifact_sha256=artifacts.add(packet, "supervisor_packet", exact=packet_bytes),
                    task_artifact_sha256=artifacts.add(task, "supervisor_task", exact=task_bytes),
                    packet_schema=str(packet.get("schema") or ""), task_schema=str(task.get("schema") or ""),
                    legacy_census_sha256=str(legacy.get("census_sha256") or ""),
                    repository_id=repository_id, agent_id=agent_id, release_id=str(legacy.get("release_id") or release_id),
                    legal_id=span["source"]["legal_id"])
        if task_id in goals and goals[task_id] != goal:
            raise PairedCensusError("conflicting goal identity")
        goals[task_id] = goal
        if task_id not in span["goal_ids"]:
            span["goal_ids"].append(task_id)
    # Even callers without a legacy packet exporter retain actionable census
    # gaps. These descriptive review goals have no native execution authority.
    for span in paired:
        status = span["comparison"]["status"]
        existing_repair = any(goals[x]["record_kind"] == "repair_packet" for x in span["goal_ids"])
        needs_review = status in {"disagree", "diagnostic_disagree"} or (span["compiler"]["canonical_complete"] is not True and not span["source"]["constitution"])
        if needs_review and not existing_repair:
            identifier = "REVIEW-" + _sha(_json({"observation_id": span["observation_id"], "kind": "paired_formal_review"}))
            goal = _goal_base(identifier, issue=span["compiler"]["reason"] or span["comparison"]["reason"],
                              work_kind="compiler_decompiler_review", kind="review_gap", code=code_identity, model=model_identity)
            goal.update(source_span_ids=[span["source"]["span_id"]], observation_ids=[span["observation_id"]])
            goals[identifier] = goal
            span["goal_ids"].append(identifier)
    if sum(len(_json(row)) for row in paired) + sum(len(_json(row)) for row in goals.values()) + artifacts.decoded_bytes > max_bytes:
        raise PairedCensusError("bundle decoded bytes exceed bound")
    return {"schema_version": SCHEMA, "repository_id": repository_id, "agent_id": agent_id,
            "paired_spans": paired, "goals": list(goals.values()), "artifacts": list(artifacts.rows.values()),
            "original_receipt_artifact_sha256": receipt_ref,
            "admitted": False, "formalized": False, "enqueued": False}


def arrow_schemas() -> dict:
    """Stable schemas, including fully typed empty tables and nested lists."""
    import pyarrow as pa
    string, boolean, floating = pa.string(), pa.bool_(), pa.float64()
    strings, vector = pa.list_(string), pa.list_(floating)
    formal = pa.list_(pa.struct([(x, string) for x in ("family", "format", "payload_json", "sha256", "origin")]
        + [("independent", boolean), ("target_conditioned", boolean), ("syntax_status", string)]))
    source = pa.struct([(x, string) for x in ("span_id", "text", "text_sha256", "legal_id", "revision")] + [("constitution", boolean)])
    ae = pa.struct([(x, string) for x in ("status", "model_identity", "embedding_model")]
        + [("semantic_embeddings", boolean), ("formal_outputs", formal), ("source_binding_verified", boolean), ("complete", boolean),
           ("raw_vector", vector), ("cosine_similarity", floating), ("reconstruction_loss", floating), ("projected_vector", vector),
           ("projected_cosine_similarity", floating), ("projected_reconstruction_loss", floating), ("projected_target_conditioned", boolean)])
    cc = pa.struct([("status", string), ("reason", string), ("complete", boolean), ("canonical_complete", boolean), ("decompiled", string),
                    ("roundtrip_ok", boolean), ("formal_outputs", formal), ("canonical_formal_outputs", formal),
                    ("component_count", pa.int64()), ("components_artifact_sha256", string), ("components_artifact_pointer", string)])
    comparison = pa.struct([("status", string), ("comparable", boolean), ("agrees", boolean), ("independent", boolean),
        ("method", string), ("coverage_scope", string), ("reason", string), ("mismatches", strings), ("autoencoder_output_count", pa.int64()), ("compiler_output_count", pa.int64())])
    provenance = pa.struct([(x, string) for x in ("agent_id", "code_identity", "model_identity", "batch_id")]
        + [("elapsed_seconds", floating), ("wall_seconds_per_span", floating), ("bridge_names", strings),
           ("evaluate_provers", boolean), ("disk_cache", boolean), ("parallel_workers", pa.int64()), ("sample_count", pa.int64())])
    lake = pa.struct([("status", string), ("receipt_sha256", string), ("admitted", boolean)])
    paired = pa.schema([("schema_version", string), ("repository_id", string), ("source", source), ("autoencoder", ae),
                        ("compiler", cc), ("provenance", provenance), ("lake", lake), ("source_target_artifact_sha256", string), ("source_target_artifact_pointer", string),
                        ("goal_ids", strings), ("admitted", boolean), ("formalized", boolean), ("comparison", comparison), ("observation_id", string)])
    goals = pa.schema([(x, string) for x in ("goal_id", "record_kind", "issue", "work_kind", "status")]
        + [("source_span_ids", strings), ("observation_ids", strings)]
        + [(x, string) for x in ("packet_sha256", "task_sha256", "packet_artifact_sha256", "task_artifact_sha256",
                                 "packet_schema", "task_schema", "legacy_census_sha256", "code_identity", "model_identity",
                                 "repository_id", "agent_id", "release_id", "legal_id")]
        + [("enqueued", boolean), ("admitted", boolean)])
    artifacts = pa.schema([("artifact_sha256", string), ("kind", string), ("encoding", string),
                           ("decoded_bytes", pa.int64()), ("payload", pa.binary())])
    return {"paired_spans": paired, "goals": goals, "artifacts": artifacts}


def _write_immutable(path: Path, raw: bytes) -> None:
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            raise PairedCensusError("immutable bundle artifact has conflicting bytes")
        return
    with path.open("xb") as handle:
        handle.write(raw)


def write_paired_census_bundle(bundle: Mapping, directory: str | Path) -> dict:
    """Write one bounded bundle; return exact local and repository paths.

    Publication is the caller's responsibility. All three tables and manifest
    should be committed atomically. This function neither downloads nor uploads.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    if bundle.get("schema_version") != SCHEMA:
        raise PairedCensusError("unsupported paired census schema")
    if _sha(Path(__file__).read_bytes()) != EXPORTER_SOURCE_SHA256:
        raise PairedCensusError("paired exporter source changed after import; reload before export")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    agent = re.sub(r"[^a-zA-Z0-9_-]", "-", str(bundle.get("agent_id") or "paired-census"))[:64]
    # A table can be byte-identical across different batches (especially empty
    # goals). Give each complete bundle its own local/remote paths so eviction
    # of one verified publication cannot remove another batch's pending table.
    bundle_key = _sha(_json({
        "schema_version": bundle["schema_version"], "repository_id": bundle["repository_id"],
        "agent_id": bundle["agent_id"], "paired_spans": bundle["paired_spans"], "goals": bundle["goals"],
        "artifacts": [{k: v for k, v in row.items() if k != "payload"} for row in bundle["artifacts"]],
        "original_receipt_artifact_sha256": bundle.get("original_receipt_artifact_sha256"),
    }))
    schemas, entries = arrow_schemas(), {}
    for name in TABLE_NAMES:
        rows = bundle[name]
        if any(set(row) != set(schemas[name].names) for row in rows):
            raise PairedCensusError("paired table fields differ from its schema")
        sink = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_pylist(rows, schema=schemas[name]), sink, compression="zstd", row_group_size=32)
        raw = sink.getvalue().to_pybytes()
        digest = _sha(raw)
        filename = f"{name}-{bundle_key}-{digest}.parquet"
        path = root / filename
        _write_immutable(path, raw)
        entries[name] = {"path": str(path), "path_in_repo": f"{REPO_PREFIX}/{name}/{agent}/{filename}",
                         "filename": filename, "sha256": digest, "bytes": len(raw), "row_count": len(rows)}
    manifest = {"schema": MANIFEST_SCHEMA, "repository_id": bundle["repository_id"], "agent_id": bundle["agent_id"],
                "exporter_sha256": EXPORTER_SOURCE_SHA256,
                "tables": {name: {k: v for k, v in entry.items() if k != "path"} for name, entry in entries.items()},
                "original_receipt_artifact_sha256": bundle.get("original_receipt_artifact_sha256"),
                "admitted": False, "formalized": False, "enqueued": False}
    fingerprint = _sha(_json(manifest))
    filename = f"manifest-{fingerprint}.json"
    manifest.update(fingerprint=fingerprint, path_in_repo=f"{REPO_PREFIX}/manifests/{agent}/{filename}")
    raw = _json(manifest)
    path = root / filename
    _write_immutable(path, raw)
    return {**entries, "fingerprint": fingerprint, "manifest": {"path": str(path),
            "path_in_repo": manifest["path_in_repo"], "sha256": _sha(raw),
            "bytes": len(raw)}, "admitted": False, "formalized": False, "enqueued": False}


def load_paired_census_bundle(manifest_path: str | Path, *, max_bytes: int = MAX_BYTES, max_rows: int = MAX_ROWS) -> dict:
    """Verify a local immutable bundle and every referenced artifact before use."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    path = Path(manifest_path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise PairedCensusError("manifest must be a bounded regular file")
    manifest_raw = path.read_bytes()
    manifest = json.loads(manifest_raw)
    if manifest.get("schema") != MANIFEST_SCHEMA or set(manifest.get("tables", {})) != set(TABLE_NAMES):
        raise PairedCensusError("unsupported manifest schema or tables")
    if "exporter_sha256" in manifest and re.fullmatch(r"[0-9a-f]{64}", str(manifest["exporter_sha256"])) is None:
        raise PairedCensusError("invalid exporter source identity")
    if manifest.get("fingerprint") != _sha(_json({k: v for k, v in manifest.items() if k not in {"fingerprint", "path_in_repo"}})):
        raise PairedCensusError("manifest content identity differs")
    if any(manifest.get(name) is not False for name in ("admitted", "formalized", "enqueued")):
        raise PairedCensusError("bundle cannot grant authority")
    schemas, tables, used, table_paths = arrow_schemas(), {}, 0, {}
    for name in TABLE_NAMES:
        entry = manifest["tables"][name]
        relative = entry.get("path_in_repo", "")
        if (not isinstance(relative, str) or not relative.startswith(REPO_PREFIX + "/") or ".." in Path(relative).parts
                or "\\" in relative or Path(relative).name != entry.get("filename")):
            raise PairedCensusError("invalid bundle repository path")
        table_path = path.parent / Path(relative).name
        if not table_path.exists():
            # Downloaders may preserve repository directories instead of placing
            # the four immutable bundle files beside each other.
            manifest_relative = manifest.get("path_in_repo", "")
            relative_parts = Path(manifest_relative).parts
            absolute_parts = path.absolute().parts
            if (not manifest_relative.startswith(REPO_PREFIX + "/") or ".." in relative_parts
                    or "\\" in manifest_relative or len(relative_parts) >= len(absolute_parts)
                    or tuple(absolute_parts[-len(relative_parts):]) != relative_parts):
                raise PairedCensusError("bundle tables missing from local or repository layout")
            repository_root = path.absolute().parents[len(relative_parts) - 1]
            table_path = repository_root / relative
            if any(parent.is_symlink() for parent in (table_path, *table_path.parents) if parent != repository_root and repository_root in parent.parents):
                raise PairedCensusError("bundle repository layout cannot contain symlinks")
            if repository_root.resolve() not in table_path.resolve().parents:
                raise PairedCensusError("bundle table escaped staging root")
        if table_path.is_symlink() or not table_path.is_file() or table_path.stat().st_size != entry.get("bytes"):
            raise PairedCensusError("bundle table file differs")
        used += table_path.stat().st_size
        if used > max_bytes:
            raise PairedCensusError("bundle compressed size exceeds bound")
        raw = table_path.read_bytes()
        if _sha(raw) != entry.get("sha256"):
            raise PairedCensusError("bundle table hash differs")
        parquet = pq.ParquetFile(pa.BufferReader(raw))
        if parquet.schema_arrow != schemas[name] or parquet.metadata.num_rows != entry.get("row_count"):
            raise PairedCensusError("bundle table schema or row count differs")
        if parquet.metadata.num_rows > max_rows * (8 if name != "paired_spans" else 1):
            raise PairedCensusError("bundle row count exceeds bound")
        decoded = sum(parquet.metadata.row_group(i).total_byte_size for i in range(parquet.metadata.num_row_groups))
        if decoded > max_bytes:
            raise PairedCensusError("bundle Arrow allocation exceeds bound")
        tables[name] = parquet.read().to_pylist()
        table_paths[name] = str(table_path)
    artifacts = {}
    decoded = 0
    for artifact in tables["artifacts"]:
        raw = decode_artifact(artifact, max_bytes=max_bytes - decoded)
        decoded += len(raw)
        if artifact["artifact_sha256"] in artifacts:
            raise PairedCensusError("duplicate artifact identity")
        artifacts[artifact["artifact_sha256"]] = artifact
    spans = {span["observation_id"]: span for span in tables["paired_spans"]}
    goals = {goal["goal_id"]: goal for goal in tables["goals"]}
    if len(spans) != len(tables["paired_spans"]) or len(goals) != len(tables["goals"]):
        raise PairedCensusError("duplicate observation or goal identity")
    for span in spans.values():
        checked = {key: value for key, value in span.items() if key != "observation_id"}
        checked["goal_ids"] = []
        if _sha(_json(checked)) != span["observation_id"] or _sha(span["source"]["text"].encode()) != span["source"]["text_sha256"]:
            raise PairedCensusError("paired observation identity differs")
        if span["comparison"] != compare_formal_outputs(span["autoencoder"], span["compiler"]):
            raise PairedCensusError("paired comparison differs from retained formal outputs")
        if span["admitted"] is not False or span["formalized"] is not False or span["lake"]["admitted"] is not False:
            raise PairedCensusError("paired observation cannot grant authority")
        if span["source"]["constitution"] and span["compiler"]["roundtrip_ok"]:
            raise PairedCensusError("Constitution cannot be marked roundtrip_ok")
        for reference in (span["source_target_artifact_sha256"], span["compiler"]["components_artifact_sha256"]):
            if reference is not None and reference not in artifacts:
                raise PairedCensusError("missing paired artifact reference")
        if any(goal_id not in goals for goal_id in span["goal_ids"]):
            raise PairedCensusError("missing paired goal reference")
    portable_goals = []
    for goal in goals.values():
        if any(identity not in spans for identity in goal["observation_ids"]) or goal["enqueued"] is not False or goal["admitted"] is not False:
            raise PairedCensusError("goal binding or authority differs")
        if goal["source_span_ids"] != [spans[identity]["source"]["span_id"] for identity in goal["observation_ids"]]:
            raise PairedCensusError("goal source identities differ from observations")
        if any(goal["goal_id"] not in spans[identity]["goal_ids"] for identity in goal["observation_ids"]):
            raise PairedCensusError("goal observation links are not reciprocal")
        for kind in ("packet", "task"):
            reference = goal[kind + "_artifact_sha256"]
            if reference is not None and (reference not in artifacts or reference != goal[kind + "_sha256"]):
                raise PairedCensusError("missing portable goal artifact reference")
        if goal["packet_artifact_sha256"] is not None:
            packet_raw = decode_artifact(artifacts[goal["packet_artifact_sha256"]])
            task_raw = decode_artifact(artifacts[goal["task_artifact_sha256"]])
            packet = json.loads(packet_raw)
            source = _mapping(packet.get("row"))
            capture = _mapping(source.get("capture"))
            if len(goal["observation_ids"]) != 1:
                raise PairedCensusError("portable goal must bind one paired observation")
            span = spans[goal["observation_ids"][0]]
            if (source.get("text") != span["source"]["text"] or source.get("source_span_id") != span["source"]["span_id"]
                    or capture.get("census_sha256") != span["observation_id"]
                    or capture.get("source_text_sha256") != span["source"]["text_sha256"]
                    or goal["code_identity"] != span["provenance"]["code_identity"]
                    or goal["model_identity"] != span["provenance"]["model_identity"]):
                raise PairedCensusError("portable goal differs from paired source or producer")
            from .span_cache_exchange import GOAL_EXPORT_SCHEMA
            portable_goals.append({"schema_version": GOAL_EXPORT_SCHEMA, "record_kind": goal["record_kind"],
                "repository_id": goal["repository_id"], "agent_id": goal["agent_id"],
                "source_span_id": span["source"]["span_id"], "legal_id": goal["legal_id"], "task_id": goal["goal_id"],
                "packet_sha256": goal["packet_sha256"], "task_sha256": goal["task_sha256"],
                "census_sha256": goal["legacy_census_sha256"], "packet_schema": goal["packet_schema"],
                "todo_schema": goal["task_schema"], "handoff_status": "dataset", "packet_json": packet_raw.decode(),
                "task_json": task_raw.decode(), "release_id": goal["release_id"], "code_identity": goal["code_identity"],
                "model_identity": goal["model_identity"], "admitted": False, "formalized": False,
                "wrote_compiler": False, "enqueued": False})
    from .span_cache_exchange import _validate_goal_rows
    _validate_goal_rows(portable_goals)
    original_receipt = None
    receipt_ref = manifest.get("original_receipt_artifact_sha256")
    if receipt_ref is not None:
        if receipt_ref not in artifacts or artifacts[receipt_ref]["kind"] != "original_producer_receipt":
            raise PairedCensusError("missing original producer receipt")
        original_receipt = json.loads(decode_artifact(artifacts[receipt_ref]))
        retained = original_receipt.get("rows", [])
        identities = {row.get("source_span_id"): row for row in retained}
        if len(identities) != len(retained) or set(identities) != {row["source"]["span_id"] for row in spans.values()}:
            raise PairedCensusError("original receipt span coverage differs")
        for span in spans.values():
            observed = identities[span["source"]["span_id"]]
            if observed.get("text") != span["source"]["text"]:
                raise PairedCensusError("original receipt source text differs")
    return {"schema_version": SCHEMA, "repository_id": manifest["repository_id"], "agent_id": manifest["agent_id"],
            **tables, "manifest": manifest, "original_receipt": original_receipt, "portable_goal_rows": portable_goals,
            "table_paths": table_paths, "manifest_sha256": _sha(manifest_raw),
            "admitted": False, "formalized": False, "enqueued": False}
