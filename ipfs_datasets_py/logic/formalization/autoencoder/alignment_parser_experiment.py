"""Compare an opt-in complete qualifier grammar with frozen richer evidence.

The default compiler, parser, benchmark identities, panel, and formal features
stay unchanged. This composition explicitly invokes the new compiler, the
existing source-withheld renderer, and the new compiler again. It does not
claim admission to the frozen canonical round-trip composition.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from .alignment_baseline import _digest
from .alignment_experiment import _write_json
from .alignment_retrieval_experiment import _read_bound_json, _verify_origins
from .alignment_richer_evaluation import (
    _ir_diagnostics,
    _native_projection,
    score_authored_reference,
)
from .alignment_richer_experiment import _summarize_rows, construct_panel_sources
from .alignment_richer_panel import (
    richer_row_input,
    richer_training_vocabulary,
    validate_alignment_richer_panel,
)
from .alignment_study import (
    _bounded_bytes,
    _executing_repository_root,
    _observed_binding,
    _reject_constant,
    _strict_object,
)

CONFIG_SCHEMA = "alignment-parser-experiment-config/v1"
REPORT_SCHEMA = "alignment-parser-experiment-report/v1"
CONSTRUCTION_SCHEMA = "alignment-explicit-qualifier-construction/v1"
_CONSTRUCTION_FIELDS = {"schema", "composition", "request", "source_sha256", "vocabulary_sha256", "context",
                        "compiler_result", "construction_status", "admission_outcome", "canonical_ir", "schema_acceptance",
                        "roundtrip", "native_projection", "proof_scopes", "authored_target_supplied", "model_call_count",
                        "source_fidelity_established", "qualified", "content_sha256"}
_ROUNDTRIP_FIELDS = {"renderer_request", "renderer_result", "reparse_request", "reparse_result", "rendered_text", "reparsed_ir",
                     "exact_ir", "generated_vs_reparsed", "frozen_roundtrip_orchestrator_used", "source_fidelity_established"}
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/legal_ir/canonical_explicit_qualifiers.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_source_guards.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_parser_experiment.py",
    "scripts/ops/legal_ir/run_alignment_parser_experiment.py",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def load_parser_config(path):
    raw = _bounded_bytes(Path(path), 262_144)
    settings = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    _require(type(settings) is dict and set(settings) == {"schema", "study_id", "richer_report", "max_seconds"}
             and settings["schema"] == CONFIG_SCHEMA, "closed parser experiment config required")
    _require(settings["study_id"] == "autoformalization-parser-development-v1", "exposed development identity required")
    binding = settings["richer_report"]
    _require(type(binding) is dict and set(binding) == {"path", "sha256"}
             and type(binding["path"]) is str and 0 < len(binding["path"]) <= 4096
             and type(binding["sha256"]) is str and len(binding["sha256"]) == 64
             and all(char in "0123456789abcdef" for char in binding["sha256"]), "bound richer report required")
    seconds = settings["max_seconds"]
    _require(type(seconds) in (int, float) and 1 <= seconds <= 120 and math.isfinite(seconds), "invalid max_seconds")
    return settings, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _composition():
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
        SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
    )
    from ipfs_datasets_py.logic.legal_ir.canonical_explicit_qualifiers import (
        EXPLICIT_QUALIFIER_CONFIG_CID,
    )

    body = {"profile": "explicit-qualifier-source-withheld-diagnostic/v1",
            "compiler_config_cid": EXPLICIT_QUALIFIER_CONFIG_CID,
            "decompiler_config_cid": SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
            "frozen_roundtrip_composition_admitted": False, "source_withheld": True, "model_calls": 0}
    from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json

    return {**body, "composition_cid": cid_for_dag_json(body)}


def construct_explicit_source(source_text, vocabulary, *, request_id, requires_context_resolution=False, context_text=""):
    """Target-free construction, with explicit unavailable context resolution."""
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
        CompilerRequest,
        DecompilerRequest,
        OperationStatus,
    )
    from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import (
        SourceWithheldCanonicalDecompiler,
    )
    from ipfs_datasets_py.logic.legal_ir.canonical_explicit_qualifiers import (
        ExplicitQualifierCanonicalCompiler,
    )

    _require(type(requires_context_resolution) is bool and type(context_text) is str and len(context_text) <= 2000,
             "bounded explicit context declaration required")
    _require(requires_context_resolution is bool(context_text.strip()), "context role and supplied text differ")
    request = CompilerRequest(source_text, request_id, vocabulary, allow_explicit_partial=False, config={})
    compiler = ExplicitQualifierCanonicalCompiler()
    l1 = None if requires_context_resolution else compiler.compile(request)
    render_request, render, reparse_request, l2 = None, None, None, None
    if l1 is not None and l1.status is OperationStatus.SUCCESS:
        render_request = DecompilerRequest(l1.canonical_ir, request_id + ":source-withheld-render")
        render = SourceWithheldCanonicalDecompiler().decompile(render_request)
        if render.status is OperationStatus.SUCCESS:
            reparse_request = CompilerRequest(render.text, request_id + ":explicit-reparse", vocabulary,
                                             allow_explicit_partial=False, config={})
            l2 = compiler.compile(reparse_request)
    candidate = None if l1 is None or l1.canonical_ir is None else l1.canonical_ir.to_dict()
    reparsed = None if l2 is None or l2.canonical_ir is None else l2.canonical_ir.to_dict()
    clarify = l1 is not None and any(item.code == "source.unresolved_actor_pronoun" for item in l1.diagnostics)
    record = {"schema": CONSTRUCTION_SCHEMA, "composition": _composition(), "request": request.to_dict(),
              "source_sha256": hashlib.sha256(source_text.encode()).hexdigest(),
              "vocabulary_sha256": _digest(vocabulary.to_dict()),
              "context": {"text": context_text, "sha256": hashlib.sha256(context_text.encode()).hexdigest(),
                          "requires_resolution": requires_context_resolution, "applied_to_query": False},
              "compiler_result": None if l1 is None else l1.to_dict(),
              "construction_status": "unavailable" if l1 is None else l1.status.value,
              "admission_outcome": "context_resolution_unavailable" if requires_context_resolution else
                                   "clarification_required" if clarify else "candidate_generated" if candidate is not None else "no_candidate_generated",
              "canonical_ir": candidate, "schema_acceptance": candidate is not None,
              "roundtrip": {"renderer_request": None if render_request is None else render_request.to_dict(),
                            "renderer_result": None if render is None else render.to_dict(),
                            "reparse_request": None if reparse_request is None else reparse_request.to_dict(),
                            "reparse_result": None if l2 is None else l2.to_dict(),
                            "rendered_text": None if render is None else render.text,
                            "reparsed_ir": reparsed,
                            "exact_ir": None if l1 is None else candidate is not None and reparsed == candidate,
                            "generated_vs_reparsed": None if candidate is None else _ir_diagnostics(reparsed, candidate),
                            "frozen_roundtrip_orchestrator_used": False, "source_fidelity_established": False},
              "native_projection": _native_projection(l1, source_text),
              "proof_scopes": {scope: {"status": "unrun"} for scope in ("native_proof", "kernel_proof", "useful_proof_coverage")},
              "authored_target_supplied": False, "model_call_count": 0,
              "source_fidelity_established": False, "qualified": False}
    record["content_sha256"] = _digest(record)
    return record


def validate_explicit_construction(record):
    """Recompute persisted source, stage, content, and transport identities."""
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
        CanonicalTypedBridge,
        CompilerRequest,
        CompilerResult,
        DecompilerRequest,
        DecompilerResult,
        OperationStatus,
    )
    from ipfs_datasets_py.logic.legal_ir.canonical_explicit_qualifiers import (
        EXPLICIT_QUALIFIER_CONFIG_CID,
    )

    _require(type(record) is dict and set(record) == _CONSTRUCTION_FIELDS and record.get("schema") == CONSTRUCTION_SCHEMA,
             "closed explicit construction schema required")
    _require(record["content_sha256"] == _digest({key: value for key, value in record.items() if key != "content_sha256"}),
             "construction digest differs")
    _require(record["composition"] == _composition() and record["qualified"] is False
             and record["authored_target_supplied"] is False and record["source_fidelity_established"] is False
             and type(record["model_call_count"]) is int and record["model_call_count"] == 0, "construction scope differs")
    request = CompilerRequest.from_dict(record["request"])
    _require(request.allow_explicit_partial is False and dict(request.config) == {}, "constructor request profile differs")
    _require(record["source_sha256"] == hashlib.sha256(request.source_text.encode()).hexdigest()
             and record["vocabulary_sha256"] == _digest(request.atom_vocabulary.to_dict()), "source or vocabulary differs")
    context = record["context"]
    _require(type(context) is dict and set(context) == {"text", "sha256", "requires_resolution", "applied_to_query"}
             and type(context["text"]) is str and len(context["text"]) <= 2000
             and type(context["requires_resolution"]) is bool and context["requires_resolution"] is bool(context["text"].strip())
             and context["sha256"] == hashlib.sha256(context["text"].encode()).hexdigest()
             and context["applied_to_query"] is False, "context role or binding differs")
    l1 = None if record["compiler_result"] is None else CompilerResult.from_dict(record["compiler_result"])
    if l1 is None:
        _require(context["requires_resolution"] is True and record["canonical_ir"] is None
                 and record["construction_status"] == "unavailable", "missing compiler must disclose context unavailability")
    else:
        _require(context["requires_resolution"] is False and l1.request_cid == request.request_cid
                 and l1.provenance["compiler_config_cid"] == EXPLICIT_QUALIFIER_CONFIG_CID
                 and record["construction_status"] == l1.status.value, "compiler stage differs")
    candidate = None if l1 is None or l1.canonical_ir is None else l1.canonical_ir.to_dict()
    _require(record["canonical_ir"] == candidate and record["schema_acceptance"] is (candidate is not None), "candidate differs")
    clarify = l1 is not None and any(item.code == "source.unresolved_actor_pronoun" for item in l1.diagnostics)
    expected_outcome = ("context_resolution_unavailable" if l1 is None else "clarification_required" if clarify
                        else "candidate_generated" if candidate is not None else "no_candidate_generated")
    _require(record["admission_outcome"] == expected_outcome, "admission outcome differs from stages")
    roundtrip = record["roundtrip"]
    _require(type(roundtrip) is dict and set(roundtrip) == _ROUNDTRIP_FIELDS, "closed roundtrip diagnostics required")
    render_request = None if roundtrip["renderer_request"] is None else DecompilerRequest.from_dict(roundtrip["renderer_request"])
    render = None if roundtrip["renderer_result"] is None else DecompilerResult.from_dict(roundtrip["renderer_result"])
    reparse_request = None if roundtrip["reparse_request"] is None else CompilerRequest.from_dict(roundtrip["reparse_request"])
    l2 = None if roundtrip["reparse_result"] is None else CompilerResult.from_dict(roundtrip["reparse_result"])
    _require((render_request is None) is (render is None), "renderer request/result accounting differs")
    _require((reparse_request is None) is (l2 is None), "reparse request/result accounting differs")
    if candidate is None:
        _require(render is None and l2 is None, "absent candidate cannot enter rendering")
    else:
        _require(render_request is not None and render_request.canonical_ir.to_dict() == candidate
                 and render.request_cid == render_request.request_cid, "source-withheld render binding differs")
        _require((l2 is not None) is (render.status is OperationStatus.SUCCESS), "reparse execution differs from render status")
    if l2 is not None:
        _require(reparse_request.source_text == render.text and l2.request_cid == reparse_request.request_cid
                 and reparse_request.atom_vocabulary == request.atom_vocabulary
                 and reparse_request.allow_explicit_partial is False and dict(reparse_request.config) == {}
                 and l2.provenance["compiler_config_cid"] == EXPLICIT_QUALIFIER_CONFIG_CID, "reparse binding or vocabulary differs")
    reparsed = None if l2 is None or l2.canonical_ir is None else l2.canonical_ir.to_dict()
    _require(roundtrip["rendered_text"] == (None if render is None else render.text)
             and roundtrip["reparsed_ir"] == reparsed
             and roundtrip["exact_ir"] is (None if l1 is None else candidate is not None and reparsed == candidate)
             and roundtrip["generated_vs_reparsed"] == (None if candidate is None else _ir_diagnostics(reparsed, candidate)),
             "roundtrip diagnostics differ from stages")
    _require(roundtrip["frozen_roundtrip_orchestrator_used"] is False and roundtrip["source_fidelity_established"] is False,
             "custom composition cannot claim frozen roundtrip admission")
    projection = record["native_projection"]
    _require(type(projection) is dict and projection.get("status") in ("executed", "unavailable", "unrun")
             and projection["proofs_executed"] is False, "bridge projection cannot become a proof")
    if projection["status"] == "executed":
        bridge = CanonicalTypedBridge.from_dict(projection["artifact"])
        _require(candidate is not None and bridge.bridge_cid == projection["bridge_cid"]
                 and projection.get("scope") == "typed_bridge_transport_with_disclosed_gaps"
                 and _digest(projection["artifact"]) == projection["artifact_sha256"]
                 and bridge.family_identity.to_dict() == projection["family_identity"]
                 and bridge.views["canonical_roundtrip_ir"].to_dict()["payload"] == candidate
                 and bridge.views["source_text"].to_dict()["payload"]["source_text"] == request.source_text,
                 "native bridge artifact identity differs")
    _require(set(record["proof_scopes"]) == {"native_proof", "kernel_proof", "useful_proof_coverage"}
             and all(value["status"] == "unrun" for value in record["proof_scopes"].values()), "proof scope differs")
    return record


def score_explicit_reference(construction, authored_target):
    validate_explicit_construction(construction)
    score = {"construction_sha256": construction["content_sha256"], "reference_read_after_construction": True,
             "source_fidelity_established": False, "qualified": False}
    if authored_target is None:
        score.update(exact_ir=False, candidate_absent=construction["canonical_ir"] is None,
                     negative_semantics_certified=False, reference_kind="authored_expected_abstention")
    else:
        score.update(**_ir_diagnostics(construction["canonical_ir"], authored_target),
                     reference_kind="synthetic_authored_unreviewed", reference_sha256=_digest(authored_target))
    return score


def _observed_sources(repository, prior_bindings):
    bindings = [_observed_binding(repository, {"path": binding["path"], "sha256": binding["sha256"]})
                for binding in prior_bindings]
    for relative in _SOURCE_FILES:
        raw = _bounded_bytes(repository / relative, 1_000_000)
        bindings.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    _verify_origins(repository, bindings)
    return bindings


def _deadline(deadline):
    _require(time.perf_counter() <= deadline, "cooperative parser experiment deadline exceeded")


def run_parser_experiment(config_path, repository_root, workspace_root, output_directory):
    started = time.perf_counter()
    repository, workspace, output = Path(repository_root).resolve(), Path(workspace_root).resolve(), Path(output_directory)
    _require(repository == _executing_repository_root(), "repository must match executing study package")
    _require(not output.exists() and not output.is_symlink(), "fresh output directory required")
    settings, config_binding = load_parser_config(config_path)
    deadline = started + settings["max_seconds"]
    _, prior = _read_bound_json(workspace, settings["richer_report"])
    _require(prior.get("schema") == "alignment-richer-experiment-report/v1" and prior.get("status") == "completed"
             and prior["report_sha256"] == _digest({key: value for key, value in prior.items() if key != "report_sha256"}),
             "completed content-bound richer report required")
    _require(prior["evaluation_role"] == "exposed_development" and prior["target_origin"] == "synthetic_authored_unreviewed"
             and all(prior[name] is False for name in ("qualified", "production_admitted", "sealed_final_test_accessed",
                 "original_validation_accessed", "development_used_in_fit", "query_targets_used_in_construction")),
             "predecessor scope differs")
    bindings = _observed_sources(repository, prior["source_bindings"])
    protocols = [_observed_binding(workspace, {"path": binding["path"], "sha256": binding["sha256"]})
                 for binding in prior["protected_protocol_bindings"]]
    _, panel = _read_bound_json(workspace, prior["panel_binding"])
    _, saved = _read_bound_json(workspace, prior["construction_binding"])
    _read_bound_json(workspace, prior["representation_assay_binding"])
    panel_validation = validate_alignment_richer_panel(panel)
    _require(panel_validation == prior["panel_validation"], "panel validation differs from prior")
    vocabulary = richer_training_vocabulary(panel)
    _require(vocabulary.to_dict() == prior["training_vocabulary"] and _digest(vocabulary.to_dict()) == prior["training_vocabulary_sha256"],
             "frozen training vocabulary differs")
    replay = construct_panel_sources(panel, vocabulary, deadline)
    _require(len(replay) == len(saved["rows"]) == len(panel["rows"]), "baseline row accounting differs")
    for authored, current, old in zip(panel["rows"], replay, saved["rows"], strict=True):
        _require(authored["id"] == current["id"] == old["id"] and authored["input_sha256"] == current["input_sha256"] == old["input_sha256"]
                 and current["construction"] == old["construction"] and authored["target"] == old["authored_target"], "frozen baseline replay differs")
        _require(score_authored_reference(current["construction"], authored["target"]) == old["posthoc_authored_score"], "baseline authored score differs")
    improved = []
    for authored, old in zip(panel["rows"], saved["rows"], strict=True):
        _deadline(deadline)
        contextual = authored["context"]["role"] != "none_required"
        source_input = richer_row_input(authored, mode="source_with_context" if contextual else "source_only")
        construction = construct_explicit_source(source_input["source_text"], vocabulary, request_id=authored["id"],
                                                requires_context_resolution=contextual,
                                                context_text=authored["context"]["text"] if contextual else "")
        score = score_explicit_reference(construction, authored["target"])
        improved.append({"id": authored["id"], "input_sha256": authored["input_sha256"], "group_id": authored["group_id"],
                         "split": authored["split"], "row_kind": authored["row_kind"], "authored_target": authored["target"],
                         "baseline_construction_sha256": old["construction"]["content_sha256"],
                         "construction": construction, "posthoc_authored_score": score,
                         "exact_authored_gain": score["exact_ir"] and not old["posthoc_authored_score"]["exact_ir"],
                         "exact_authored_regression": old["posthoc_authored_score"]["exact_ir"] and not score["exact_ir"]})
    _deadline(deadline)
    _require(bindings == _observed_sources(repository, prior["source_bindings"]), "executing source bytes changed during run")
    _require(config_binding["sha256"] == load_parser_config(config_path)[1]["sha256"], "configuration changed during run")
    _read_bound_json(workspace, settings["richer_report"])
    for key in ("panel_binding", "construction_binding", "representation_assay_binding"):
        _read_bound_json(workspace, prior[key])
    for binding in prior["protected_protocol_bindings"]:
        _observed_binding(workspace, {"path": binding["path"], "sha256": binding["sha256"]})
    output.mkdir(parents=True, exist_ok=False)
    construction_binding = _write_json(output / "constructions.json", {"schema": "alignment-parser-comparisons/v1", "rows": improved})
    report = {"schema": REPORT_SCHEMA, "study_id": settings["study_id"], "status": "completed",
              "configuration": settings, "configuration_binding": config_binding, "predecessor_binding": settings["richer_report"],
              "source_bindings": bindings, "protected_protocol_bindings": protocols,
              "panel_binding": prior["panel_binding"], "baseline_construction_binding": prior["construction_binding"],
              "representation_assay_binding": prior["representation_assay_binding"], "construction_binding": construction_binding,
              "training_vocabulary": vocabulary.to_dict(), "training_vocabulary_sha256": _digest(vocabulary.to_dict()),
              "composition": _composition(), "baseline_exact_replay_records": len(replay),
              "baseline_summaries": prior["summaries"],
              "summaries": {"all": _summarize_rows(improved),
                            "train": _summarize_rows([row for row in improved if row["split"] == "train"]),
                            "development": _summarize_rows([row for row in improved if row["split"] == "validation"])},
              "exact_authored_gains": sum(row["exact_authored_gain"] for row in improved),
              "exact_authored_regressions": sum(row["exact_authored_regression"] for row in improved),
              "clarification_pattern_rows": [row["id"] for row in improved if row["construction"]["admission_outcome"] == "clarification_required"],
              "evaluation_role": "exposed_development", "target_origin": "synthetic_authored_unreviewed",
              "development_used_to_design_grammar": True, "development_used_in_vocabulary_fit": False,
              "query_targets_used_in_construction": False, "sealed_final_test_accessed": False,
              "original_validation_accessed": False, "frozen_baseline_sources_changed": False,
              "default_compiler_replaced": False, "frozen_roundtrip_composition_admitted": False,
              "complete_dependency_manifest": False, "dependency_binding_scope": "listed_study_and_core_source_files_only",
              "qualified": False, "production_admitted": False,
              "primary_fidelity": {"status": "unavailable_independent_review", "value": None},
              "native_useful_proof_coverage": {"status": "unrun", "value": None},
              "resource_scope": {"model_loads": 0, "provider_calls": 0, "prover_calls": 0, "optimizer_steps": 0,
                                 "model_embeddings_computed": 0, "deadline_kind": "cooperative_between_rows_no_preemption"},
              "limitations": ["The grammar was designed after viewing exposed development diagnostics; gains are exploratory regression evidence.",
                              "Exact caller atom surfaces and declared connectives restrict this profile to controlled single-rule English.",
                              "Candidate preservation does not certify source fidelity or interpretation of flat qualifier atoms.",
                              "Absent negative candidates do not certify general unsupported-semantic recognition or clarification.",
                              "Explicit context resolution, native proof and kernel checking remain unrun or unavailable.",
                              "Independent 8D, 384D, 768D and Leanstral model lanes were not exercised."],
              "elapsed_seconds": time.perf_counter() - started}
    report["report_sha256"] = _digest(report)
    _write_json(output / "report.json", report)
    persisted = json.loads(_bounded_bytes(output / "report.json", 32_000_000),
                           object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    _require(persisted == report, "persisted parser report differs")
    return report
