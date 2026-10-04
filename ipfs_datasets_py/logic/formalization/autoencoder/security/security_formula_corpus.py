"""Local, source-bound decoder examples from verified complete CVE files.

This bridge preserves repository splits, explicit unsupported functions and
cross-split collisions. Corpus security labels are provenance only; teacher
productions come from the admitted source grammar, never from CWE labels.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import warnings

from . import security_cve_source_context as context_api
from . import security_formula_grammar as grammar
from .security_formalization_evaluation import _function_span
from ....ir_core.identity import canonical_identity
from ....security_ir.cvefixes.schemas import CodeUnit

SCHEMA = "security-source-formula-corpus@1"
SPLITS = ("train", "validation", "test")
MAX_FUNCTIONS = 4096


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _cid(value):
    return canonical_identity(value, domain="security-source-formula-corpus", schema_version=SCHEMA).cid


def _qualified_functions(tree):
    found = []
    def walk(node, parents):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = ".".join((*parents, child.name))
                found.append((child, qualified, list(parents)))
                walk(child, (*parents, child.name))
            elif isinstance(child, ast.ClassDef):
                walk(child, (*parents, child.name))
            else:
                walk(child, parents)
    walk(tree, ())
    return sorted(found, key=lambda item: (item[0].lineno, item[0].col_offset, item[1]))


def _verify_span(raw, body, binding):
    """Independently check every normalized byte against exact source offsets."""
    start, end = binding["start_byte"], binding["end_byte"]
    if (not 0 <= start < end <= len(raw) or _sha(raw[start:end]) != binding["span_sha256"]
            or _sha(body) != binding["normalized_body_sha256"]):
        raise ValueError("function source span digest differs")
    cursor, source_cursor = 0, start
    for row in binding["line_byte_map"]:
        a, b = row["source_start_byte"], row["source_end_byte"]
        c, d = row["normalized_start_byte"], row["normalized_end_byte"]
        if (not source_cursor <= a <= b <= end or c != cursor or not c <= d <= len(body)
                or raw[a:b] != body[c:d] or any(byte not in (9, 32) for byte in raw[source_cursor:a])):
            raise ValueError("function normalization byte map differs")
        cursor, source_cursor = d, b
    if cursor != len(body) or source_cursor != end:
        raise ValueError("function normalization map is incomplete")


def build_security_formula_corpus(*, context: Path, expected_manifest_sha256: str,
                                 max_functions: int = MAX_FUNCTIONS) -> dict:
    """Replay local source admission and return explicit eligible decoder input.

    ``supported_samples`` retains every grammar-supported function. ``samples``
    excludes all members of every cross-split body/shape collision. No function
    is reassigned to another split, and exclusions remain in the report.
    Source payloads are local-only; this function provides no publication grant.
    """
    if type(max_functions) is not int or not 1 <= max_functions <= MAX_FUNCTIONS:
        raise ValueError("bounded explicit function selection required")
    root = context_api.corpus_api._root(context)
    loaded = context_api.load_security_source_context(root, expected_manifest_sha256=expected_manifest_sha256)
    records = {record.cid: record for record in loaded["records"]}
    supported, functions, files, frontiers = [], [], [], []
    count, supported_nodes = 0, 0
    grammar_counts = Counter()
    for entry in loaded["entries"]:
        unit = records.get(entry["code_unit_cid"])
        if (type(unit) is not CodeUnit or unit.unit_kind != "file" or unit.path != entry["path"]
                or unit.payload["body_sha256"] != entry["body_sha256"]
                or unit.payload["source_context_cid"] != entry["source_context_cid"]):
            raise ValueError("complete native CodeUnit entry binding differs")
        raw = context_api.canonical.codebase_autoencoder._read(root / entry["body_path"],
            limit=loaded["manifest"]["config"]["budget"]["max_file_bytes"])
        if _sha(raw) != entry["body_sha256"] or len(raw) != entry["body_bytes"]:
            raise ValueError("complete source changed after admission")
        file_ref = {key: entry[key] for key in ("split", "repository_family", "path", "polarity", "revision",
            "body_sha256", "body_bytes", "body_path", "blob_sha", "source_record_cid", "source_context_cid", "code_unit_cid")}
        file_row = {**file_ref, "function_count": 0, "status": "observed", "reason": None}
        files.append(file_row)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(raw.decode("utf-8"), type_comments=True)
        except (SyntaxError, ValueError, UnicodeError, RecursionError):
            file_row.update(status="unsupported", reason="complete_file_ast_unsupported")
            frontiers.append({"kind": "file", **file_ref, "reason": file_row["reason"]})
            continue
        found = _qualified_functions(tree)
        file_row["function_count"] = len(found)
        for node, qualified, enclosing in found:
            count += 1
            identity = {"code_unit_cid": unit.cid, "qualified_name": qualified,
                        "line": node.lineno, "column": node.col_offset, "split": entry["split"]}
            identifier = "cve-formula:" + _sha(_wire(identity))
            row = {"id": identifier, **file_ref, "qualified_name": qualified, "symbol": node.name,
                "enclosing_scope": enclosing, "line": node.lineno, "end_line": node.end_lineno,
                "source_binding": None, "source_sha256": None, "program_shape_sha256": None,
                "grammar_status": "unsupported", "unsupported_reason": None,
                "node_count": 0, "eligible": False, "exclusion_reasons": [],
                "security_label_is_function_truth": False}
            functions.append(row)
            if count > max_functions:
                reason = "function_selection_bound_exceeded"
            elif any(control in raw for control in (b"\r", b"\v", b"\f", b"\x00")):
                reason = "source_line_controls_not_mapped"
            else:
                body, binding = _function_span(raw, node)
                _verify_span(raw, body, binding)
                row.update(source_binding=binding, source_sha256=_sha(body))
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", SyntaxWarning)
                        parsed = grammar.parse_formula_source(body)
                except grammar.UnsupportedFormulaSource as error:
                    reason = str(error)
                else:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", SyntaxWarning)
                        shape = grammar.source_shape(body)
                    row.update(grammar_status="supported", program_shape_sha256=shape,
                               node_count=len(parsed["nodes"]), eligible=True)
                    supported.append({"id": identifier, "split": entry["split"],
                        "source": body.decode("utf-8"), "source_sha256": _sha(body)})
                    supported_nodes += len(parsed["nodes"])
                    grammar_counts.update(node["teacher_production"] for node in parsed["nodes"])
                    continue
            row["unsupported_reason"] = reason
            frontiers.append({"kind": "function", "id": identifier, "code_unit_cid": unit.cid,
                              "qualified_name": qualified, "line": node.lineno, "reason": reason})
    if len({row["id"] for row in functions}) != len(functions):
        raise ValueError("ambiguous duplicate function provenance identity")
    supported_rows = {row["id"]: row for row in functions if row["grammar_status"] == "supported"}
    collisions, same_split_duplicates = [], []
    for kind, field in (("body", "source_sha256"), ("alpha_literal_shape", "program_shape_sha256")):
        groups = defaultdict(list)
        for row in supported_rows.values():
            groups[row[field]].append(row)
        for digest, rows in sorted(groups.items()):
            splits = sorted({row["split"] for row in rows})
            group = {"kind": kind, "sha256": digest, "splits": splits, "sample_ids": sorted(row["id"] for row in rows)}
            if len(splits) > 1:
                collisions.append(group)
                for row in rows:
                    row["eligible"] = False
                    row["exclusion_reasons"].append("cross_split_" + kind + "_collision")
                frontiers.append({**group, "kind": "cross_split_collision", "collision_kind": kind,
                    "reason": "all members quarantined; original repository splits preserved"})
            elif len(rows) > 1:
                same_split_duplicates.append(group)
    samples = [sample for sample in supported if supported_rows[sample["id"]]["eligible"]]
    eligible_counts = {split: sum(row["split"] == split for row in samples) for split in SPLITS}
    for split, number in eligible_counts.items():
        if not number:
            frontiers.append({"kind": "training_readiness", "split": split, "reason": "no_eligible_decoder_samples"})
    eligible_nodes = sum(supported_rows[sample["id"]]["node_count"] for sample in samples)
    within_trainer_bounds = 3 <= len(samples) <= 384 and eligible_nodes <= 8192
    if not within_trainer_bounds:
        frontiers.append({"kind": "training_readiness", "reason": "decoder_sample_or_node_bounds_not_satisfied",
                          "samples": len(samples), "nodes": eligible_nodes})
    # Source is re-admitted after extraction. Neither mutable files nor caller
    # metadata may silently replace the snapshot used to construct samples.
    reloaded = context_api.load_security_source_context(root, expected_manifest_sha256=expected_manifest_sha256)
    if reloaded["manifest"] != loaded["manifest"]:
        raise ValueError("source context changed while building decoder corpus")
    result = {"schema": SCHEMA, "source_context": {"output": str(root), "manifest_sha256": expected_manifest_sha256},
        "grammar_schema": grammar.SCHEMA, "max_functions": max_functions,
        "implementation_sha256": {"corpus_adapter": _sha(Path(__file__).read_bytes()),
            "grammar": _sha(Path(grammar.__file__).read_bytes()),
            "source_context": _sha(Path(context_api.__file__).read_bytes()),
            "span_adapter": _sha(Path(_function_span.__code__.co_filename).read_bytes())},
        "counts": {"file_entries": len(files), "functions_observed": count,
            "grammar_supported": len(supported), "unsupported_functions": count - len(supported),
            "cross_split_collision_functions": len(supported) - len(samples),
            "eligible_samples": len(samples), "eligible_by_split": eligible_counts,
            "supported_by_split": {split: sum(row["split"] == split for row in supported) for split in SPLITS},
            "supported_nodes": supported_nodes, "eligible_nodes": eligible_nodes},
        "files": files, "functions": functions, "supported_samples": supported, "samples": samples,
        "cross_split_collisions": collisions, "same_split_duplicates": same_split_duplicates,
        "frontiers": frontiers, "source_recovery_frontiers": reloaded["frontiers"],
        "production_counts": dict(sorted(grammar_counts.items())),
        "training_input_contract_satisfied": within_trainer_bounds and all(eligible_counts.values()),
        "sample_payload_scope": "local source only; no license or redistribution grant",
        "teacher_target_origin": "admitted source AST productions; no CWE or corpus security labels",
        "polarity_scope": "fixing-commit versus parent provenance; not per-function vulnerability truth",
        "heldout_semantic_claims": False, "heldout_evaluated": False, "source_semantics_verified": False,
        "proof_authority": False, "execution_authority": False, "training_steps": 0,
        "mutation_authority": False, "completion_authority": False,
        "network_calls": 0, "provider_calls": 0, "learned_formula_generation": False}
    result["corpus_cid"] = _cid(result)
    return result


def validate_security_formula_corpus(expected_report: dict, *, context: Path,
        expected_manifest_sha256: str, max_functions: int = MAX_FUNCTIONS) -> dict:
    actual = build_security_formula_corpus(context=context, expected_manifest_sha256=expected_manifest_sha256,
                                          max_functions=max_functions)
    if type(expected_report) is not dict or _wire(actual) != _wire(expected_report):
        raise ValueError("formula corpus differs from current source and native grammar replay")
    return actual
