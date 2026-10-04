"""Route exact source units to the existing domain-specific learned decoders.

Embedding windows are retrieval slices, not automatically complete modeling
inputs. Callers may supply an entire original document plus a selection; any
additional context use is explicit. Unsupported regions are never formalized
by assigning them an empty or unconditional proposition.
"""
from __future__ import annotations

import hashlib
import json
import re

SCHEMA = "source-document-autoencoder/v1"
MAX_BYTES = 1_048_576


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _security_family_views(projection):
    """Name canonical logic families separately from representation backends."""
    from ...families.registry import DEFAULT_REGISTRY
    if projection["status"] != "candidate":
        return []
    views = []
    for index, item in enumerate(projection.get("projections", [])):
        backend = "smt" if item["family_id"] == "smt" else None
        family = "first_order" if backend else item["family_id"]
        if family not in DEFAULT_REGISTRY.families:
            raise ValueError("security projection has no canonical logic family")
        views.append({"family_id":family,"backend":backend,
            "representation_profile":item["profile_id"],"projection_index":index,
            "projection_sha256":projection["projection_sha256"],
            "semantics":"typed_scalar_model_equality" if backend else "typed_pure_program_declaration",
            "proof_authority":False,"source_semantics_verified":False})
    if projection.get("lean_source"):
        views.append({"family_id":"higher_order","backend":"lean4",
            "representation_profile":"pure_model_equations","projection_index":None,
            "projection_sha256":projection["projection_sha256"],
            "semantics":"pure_model_equality_under_declared_input_sorts",
            "proof_authority":False,"source_semantics_verified":False})
    return views


def prepare_source_document(source_text, *, source_path, source_format,
        language=None, intent_checkpoint=None, security_checkpoint=None,
        start_char=0, end_char=None, recover_context=False, lake_executable=None,
        project_logic_families=False, intent_family_context=None, requested_intent_families=None):
    """Prepare typed clauses/functions without guessing a missing source language.

    Formats: ``intent``/``markdown`` route prose clauses to IntentIR and declared
    Python fences to SecurityIR; ``code`` requires an explicit Python language.
    Security prose and diffs remain unsupported until an appropriate decoder or
    a verified complete source is supplied. A supplied native Lake executable
    opts into actual builds. No source code is executed or repaired.
    """
    if (type(source_text) is not str or not source_text or len(source_text.encode()) > MAX_BYTES
            or type(source_path) is not str or not source_path or len(source_path) > 512
            or source_format not in {"intent","markdown","code","security_prose","diff"}
            or type(recover_context) is not bool or type(project_logic_families) is not bool):
        raise ValueError("bounded source, explicit format and context policy required")
    if (intent_family_context is not None or requested_intent_families is not None) and (
            not project_logic_families or source_format not in {"intent", "markdown"}):
        raise ValueError("Intent family context/selection requires enabled Intent family projection")
    end_char = len(source_text) if end_char is None else end_char
    if type(start_char) is not int or type(end_char) is not int or not 0 <= start_char < end_char <= len(source_text):
        raise ValueError("exact nonempty character selection required")
    raw = source_text.encode()
    start_byte, end_byte = len(source_text[:start_char].encode()), len(source_text[:end_char].encode())
    report = {"schema":SCHEMA,"source_path":source_path,"source_format":source_format,
        "language":language,"source_sha256":_sha(raw),"source_bytes":len(raw),
        "selection":{"start_char":start_char,"end_char":end_char,"start_byte":start_byte,
                     "end_byte":end_byte,"sha256":_sha(raw[start_byte:end_byte])},
        "whole_source_context_supplied":start_char!=0 or end_char!=len(source_text),
        "recover_context":recover_context,"intent":None,"security_regions":[],
        "project_logic_families":project_logic_families,"intent_family_projection":None,
        "routing_frontiers":[],"candidates":[],"lake_checks":[],
        "counts":{"intent_candidates":0,"security_program_candidates":0,
                  "security_equation_candidates":0,"equation_candidates_using_recovered_context":0,
                  "security_typed_ir_candidates":0,"security_logic_projections":0,
                  "security_decoder_calls":0,"security_neural_forwards":0,
                  "lake_attempts":0,"lake_passes":0},
        "whole_document_formalized":False,"source_semantics_verified":False,
        "proof_authority":False,"execution_authority":False,"training_steps":0,
        "llm_calls":0,"download_calls":0}
    if source_format in {"intent","markdown"} and any(c in source_text for c in "\v\f\x1c\x1d\x1e\x85\u2028\u2029"):
        report["status"] = "unsupported"
        report["routing_frontiers"].append({"reason":"nonphysical_markdown_line_separator_requires_parser_support"})
        report["report_sha256"] = _sha(json.dumps(report,sort_keys=True,separators=(",",":"),allow_nan=False).encode())
        return report

    def security_region(text, left, right, path):
        byte_base = len(source_text[:left].encode())
        region_raw = text.encode()
        local_start = max(start_byte-byte_base,0)
        local_end = min(end_byte-byte_base,len(region_raw))
        if local_start >= local_end:
            return
        region = {"start_char":left,"end_char":right,"start_byte":byte_base,
                  "end_byte":byte_base+len(region_raw),"source_sha256":_sha(region_raw),
                  "report":None,"equations":[]}
        report["security_regions"].append(region)
        if security_checkpoint is None:
            region["frontier"] = "security_checkpoint_not_selected"
            return
        from .security.security_formula_source_units import decode_security_source_units
        if security_checkpoint.get("schema") == "security-formula-production-decoder@2":
            from .security.security_formula_logic_v2 import (
                project_security_formula_logic_v2 as project_security_formula_lean,
                validate_security_formula_logic_v2 as validate_security_formula_lean)
        else:
            from .security.security_formula_lean import project_security_formula_lean, validate_security_formula_lean
        units = decode_security_source_units(source_bytes=region_raw,source_sha256=_sha(region_raw),
            source_path=path,checkpoint=security_checkpoint,window_start_byte=local_start,
            window_end_byte=local_end,recover_context=recover_context,language="python")
        region["report"] = units
        # v2 uses candidate status for independently AST-agreed programs.
        # The legacy accepted-only counter otherwise hides real v2 coverage.
        report["counts"]["security_program_candidates"] += units["counts"]["source_AST_equivalent_functions"]
        report["counts"]["security_decoder_calls"] += sum(u["decode"] is not None for u in units["units"])
        report["counts"]["security_neural_forwards"] += units["counts"]["learned_inference_functions"]
        for unit in units["units"]:
            decoded = unit["decode"]
            if not decoded or not decoded["validation"]["source_AST_equivalent"]:
                continue
            # Reconstruct the exact documented modeling input from verified
            # original-source maps; never use the model's candidate as input.
            body = b"".join(region_raw[m["source_start_byte"]:m["source_end_byte"]]
                            for m in unit["source_binding"]["line_byte_map"])
            assert _sha(body) == unit["normalized_body_sha256"]
            equations = project_security_formula_lean(source_bytes=body,
                checkpoint=security_checkpoint,source_path=path)
            report["counts"]["security_decoder_calls"] += 1
            report["counts"]["security_neural_forwards"] += bool(equations["decode"]["predicted_productions"])
            region["equations"].append({"unit_id":unit["unit_id"],"projection":equations,
                                       "context_recovered":unit["context_recovered"]})
            if project_logic_families:
                region["equations"][-1]["family_views"] = _security_family_views(equations)
            if equations["status"] != "candidate":
                continue
            report["counts"]["security_equation_candidates"] += 1
            report["counts"]["security_typed_ir_candidates"] += bool(equations.get("typed_ir"))
            report["counts"]["security_logic_projections"] += len(equations.get("projections", []))
            report["counts"]["equation_candidates_using_recovered_context"] += unit["context_recovered"]
            report["candidates"].append({"domain":"security_ir","unit_id":unit["unit_id"],
                "region_start_byte":byte_base,"start_byte":byte_base+unit["start_byte"],
                "end_byte":byte_base+unit["end_byte"],"context_recovered":unit["context_recovered"],
                "projection_sha256":equations["projection_sha256"],
                "meaning":"pure_function_model_equations_under_declared_assumptions",
                "typed_ir_available":bool(equations.get("typed_ir")),
                "logic_projection_count":len(equations.get("projections", []))})
            if lake_executable:
                checked = validate_security_formula_lean(equations,source_bytes=body,
                    checkpoint=security_checkpoint,lake_executable=lake_executable)
                report["counts"]["security_decoder_calls"] += checked["validation_decoder_replays"]
                report["counts"]["security_neural_forwards"] += checked["validation_decoder_replays"]
                report["lake_checks"].append({"domain":"security_ir","unit_id":unit["unit_id"],"receipt":checked})

    if source_format in {"intent","markdown"}:
        from ...intent_ir.formalize.document_roundtrip import prepare_intent_document
        from ...intent_ir.formalize.skillcenter_spans import _markdown_blocks
        if intent_checkpoint is not None and intent_checkpoint.get("schema") == "intent-rich-copy-checkpoint/v1":
            from ...intent_ir.formalize.rich_document import prepare_rich_intent_document
            rich = prepare_rich_intent_document(source_text,intent_checkpoint,
                start_char=start_char,end_char=end_char,context=intent_family_context,
                requested_families=requested_intent_families,lake_executable=lake_executable)
            report["rich_intent"] = rich
            # The rich checkpoint's codec intrinsically emits its scoped
            # typed views, as the older codec emits native views internally.
            # The legacy family flag still gates explicit context/selection.
            report["rich_projection_enabled_by_checkpoint"] = True
            report["counts"]["intent_candidates"] = len(rich["candidates"])
            report["counts"]["intent_logic_families"] = sum(p["status"]=="available_views" for p in rich["family_inventory"])
            report["counts"]["intent_encoder_executions"] = rich["counts"]["encoder_executions"]
            report["counts"]["intent_decoder_executions"] = rich["counts"]["decoder_executions"]
            report["candidates"].extend({"domain":"intent_ir","unit_id":c["unit_id"],
                "start_char":c["start_char"],"end_char":c["end_char"],"context_recovered":False,
                "meaning":"source_supported_rich_candidate","rich_ir":c["rich_ir"]} for c in rich["candidates"])
            report["lake_checks"].extend({"domain":"intent_ir",**check} for check in rich["lake_checks"])
        else:
            if project_logic_families:
                from ...intent_ir.formalize.source_family_bridge import project_source_intent_families
                family_report = project_source_intent_families(source_text,intent_checkpoint,
                    start_char=start_char,end_char=end_char,context=intent_family_context,
                    requested_families=requested_intent_families)
                intent = family_report["document_report"]
                # Retain one copy of the numerical inference trace. The family
                # validator explicitly supports this stripped, source-bound bundle.
                report["intent_family_projection"] = {k:v for k,v in family_report.items() if k != "document_report"}
                report["counts"]["intent_logic_families"] = family_report["counts"]["families_with_available_views"]
                report["counts"]["intent_typed_fixtures"] = family_report["counts"]["typed_fixtures"]
            else:
                intent = prepare_intent_document(source_text,intent_checkpoint,start_char=start_char,end_char=end_char)
            report["intent"] = intent
            for candidate in intent["candidates"]:
                report["candidates"].append({"domain":"intent_ir","unit_id":candidate["unit_id"],
                    "start_char":candidate["start_char"],"end_char":candidate["end_char"],
                    "context_recovered":False,"meaning":"source_supported_single_clause_candidate"})
                if lake_executable and not project_logic_families:
                    from ...intent_ir.formalize.lean_projection import project_lean_family, validate_lean_projection
                    ir = candidate["candidate_intent_ir"]
                    checked = validate_lean_projection(project_lean_family(ir),ir,lake_executable=lake_executable)
                    report["lake_checks"].append({"domain":"intent_ir","unit_id":candidate["unit_id"],"receipt":checked})
            report["counts"]["intent_candidates"] = len(intent["candidates"])
            if lake_executable and project_logic_families:
                from ...intent_ir.formalize.source_family_bridge import validate_source_family_lean
                checked = validate_source_family_lean(report["intent_family_projection"],
                    source_text=source_text,checkpoint_descriptor=intent_checkpoint,lake_executable=lake_executable)
                report["intent_family_validation"] = checked
                report["counts"]["intent_validation_inference_replays"] = checked["validation_inference_replays"]
                report["counts"]["intent_validation_encoder_executions"] = checked["validation_encoder_executions"]
                report["counts"]["intent_validation_decoder_executions"] = checked["validation_decoder_executions"]
                report["lake_checks"].extend({"domain":"intent_ir","unit_id":r["unit_id"],
                    "receipt":r["receipt"]} for r in checked["receipts"])
        for block in _markdown_blocks(source_text):
            if block["kind"] != "fenced_code" or not (block["start_char"] < end_char and start_char < block["end_char"]):
                continue
            lines = block["text"].splitlines(keepends=True)
            opening = re.fullmatch(r"[ \t]*(`{3,}|~{3,})[ \t]*(python|py|python3)[ \t]*(?:\r?\n)?",lines[0])
            closing = lines[-1].strip() if len(lines)>1 else ""
            if not opening or len(closing)<len(opening[1]) or set(closing)!={opening[1][0]}:
                report["routing_frontiers"].append({"kind":"fenced_code","start_char":block["start_char"],
                    "reason":"closed_explicit_python_fence_required"})
                continue
            left = block["start_char"]+len(lines[0])
            right = block["end_char"]-len(lines[-1])
            security_region(source_text[left:right],left,right,"fence_"+str(block["start_byte"])+".py")
    elif source_format == "code" and language in {"python","py","python3"}:
        security_region(source_text,0,len(source_text),source_path)
    else:
        report["routing_frontiers"].append({"kind":source_format,"language":language,
            "reason":"decoder_for_this_source_kind_unavailable; complete supported source required"})
    for checked in report["lake_checks"]:
        receipt = checked["receipt"]
        report["counts"]["lake_attempts"] += bool(receipt.get("backend_executed"))
        report["counts"]["lake_passes"] += receipt["status"] == "passed"
    report["status"] = "partial_candidates" if report["candidates"] else "unsupported"
    report["limitations"] = ["No whole-document or program-correctness claim.",
        "A source unit may exceed an embedding window; recovered context is reported separately.",
        "Intent Lake checks only the generated Lean declarations or parameterized fixture, not every projected family backend; Security Lake checks explicit pure model equations.",
        "Fixture and knowledge-graph slots are explicit modeling premises, not established facts or referent existence.",
        "Unsupported languages, effects, dependencies and scope remain unresolved."]
    report["report_sha256"] = _sha(json.dumps(report,sort_keys=True,separators=(",",":"),allow_nan=False).encode())
    return report
