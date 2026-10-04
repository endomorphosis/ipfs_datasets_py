"""End-to-end capability evaluation of frozen security advice and code models.

Classification scores and reconstruction vectors are not a formula decoder.
This evaluator executes the actual checkpoint, joins every observed function to
exact source bytes, and independently runs the guarded native ProgramIR path.
Its learned-formula acceptance gate stays failed for the current advisory head.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from . import security_autoencoder_checkpoint as checkpoint_api
from ..source_screening import SourceSecretError, _contains_secret, _credential_path_reason
from ....ir_core.identity import canonical_identity
from ....security_ir import code_program_derivation as derivation_api
from ....security_ir.cvefixes.schemas import CodeUnit

SCHEMA = "security-autoencoder-formalization-evaluation@1"
_MISSING = "learned_source_to_formula_decoder"


class MissingFormalDecoderError(ValueError):
    """The current checkpoint has no learned source-to-formula decoding head."""


def _cid(value, domain):
    return canonical_identity(value, domain=domain, schema_version=SCHEMA).cid


@dataclass(frozen=True, slots=True)
class _FunctionLineIndex:
    source_bytes: bytes
    lines: tuple[bytes, ...]
    offsets: tuple[int, ...]


def _function_line_index(raw):
    """Build one immutable line table for an exact in-memory source object."""
    lines = tuple(raw.splitlines(keepends=True))
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    return _FunctionLineIndex(raw, lines, tuple(offsets))


def _function_span(raw, node, *, _line_index=None):
    """Keep decorators and record exact per-line indentation removal.

    The normalized body is a function-level structural modeling input. Its
    distinct digest is never substituted for the original file's identity.
    """
    if _line_index is None:
        _line_index = _function_line_index(raw)
    if type(_line_index) is not _FunctionLineIndex or _line_index.source_bytes is not raw:
        raise ValueError("exact source-local line index required")
    lines, offsets = _line_index.lines, _line_index.offsets
    start_line = min([node.lineno, *(item.lineno for item in node.decorator_list)])
    start, stop = offsets[start_line - 1], offsets[node.end_lineno - 1] + node.end_col_offset
    span = raw[start:stop]
    first = lines[start_line - 1]
    prefix = first[:len(first) - len(first.lstrip(b" \t"))]
    inconsistent = any(prefix and not line.startswith(prefix) and line.strip()
                       for line in span.splitlines(keepends=True))
    # Continuations and multiline literals may legitimately cross the outer
    # indentation margin. Preserve those exact bytes as an unsupported input;
    # one such function must not discard every other observed function.
    if inconsistent:
        prefix = b""
    normalized, mappings, source_offset, normalized_offset = [], [], start, 0
    for line in span.splitlines(keepends=True):
        trim = len(prefix) if line.startswith(prefix) else 0
        kept = line[trim:]
        normalized.append(kept)
        mappings.append({"source_start_byte": source_offset + trim,
            "source_end_byte": source_offset + len(line),
            "normalized_start_byte": normalized_offset,
            "normalized_end_byte": normalized_offset + len(kept)})
        source_offset += len(line)
        normalized_offset += len(kept)
    body = b"".join(normalized)
    return body, {"start_byte": start, "end_byte": stop,
        "span_sha256": checkpoint_api._sha(span), "normalized_body_sha256": checkpoint_api._sha(body),
        "normalization": ("identity; inconsistent indentation remains unsupported" if inconsistent
                          else "remove exact common indentation; retain decorators and byte map"),
        "normalization_frontier": "inconsistent_function_indentation" if inconsistent else None,
        "line_byte_map": mappings, "whole_file_semantics_verified": False}


def derive_security_source_programs(*, repository: Path, paths, source_hashes: dict,
        polarity="vulnerable", max_functions=1024) -> dict:
    """Deterministic model-off control; visits all functions without ranking."""
    repository = Path(repository).absolute()
    ledger = checkpoint_api._ledger(source_hashes)
    if (type(paths) not in (list, tuple) or not paths or len(set(paths)) != len(paths)
            or not set(paths) <= set(ledger) or polarity not in {"vulnerable", "fixed"}
            or type(max_functions) is not int or not 1 <= max_functions <= 1024):
        raise ValueError("exact admitted paths, source-version polarity and function bound required")
    sources = checkpoint_api._sources(repository, ledger)
    profile = derivation_api.describe_code_program_derivation_profile()
    config_cid = _cid({"profile": profile, "normalization": "exact-indentation-removal@1"},
                      "security-evaluation/source-modeling")
    results, unsupported = [], []
    for path in sorted(paths):
        raw = sources[path]
        if _credential_path_reason(path) or _contains_secret(raw):
            raise SourceSecretError("formalization input refused by shared source screen")
        if not path.endswith(".py"):
            unsupported.append({"path": path, "reason": "non_python_source"})
            continue
        # Python AST uses LF line boundaries, while splitlines also recognizes
        # other separators. Keep such files out of this exact mapping profile.
        if any(byte in raw for byte in (b"\r", b"\v", b"\f")):
            unsupported.append({"path": path, "reason": "source_line_mapping_unsupported"})
            continue
        try:
            tree = ast.parse(raw.decode("utf-8"))
        except (SyntaxError, UnicodeError, ValueError, RecursionError):
            unsupported.append({"path": path, "reason": "python_ast_unavailable"})
            continue
        source_cid = _cid({"path": path, "sha256": ledger[path]}, "security-evaluation/source-file")

        def visit(node, prefix=""):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if len(results) >= max_functions:
                    raise ValueError("formalization function bound exceeded; source is not truncated")
                identity = {"path": path, "symbol": prefix + node.name, "line": node.lineno,
                    "ast_sha256": checkpoint_api._sha(ast.dump(node, include_attributes=False).encode())}
                row_id = checkpoint_api._sha(checkpoint_api._json(identity))
                body, binding = _function_span(raw, node)
                binding.update(source_sha256=ledger[path], source_cid=source_cid,
                               enclosing_scope=prefix, modeling_scope="isolated_function_under_explicit_assumptions")
                body_cid = canonical_identity({"body": body.decode("utf-8")},
                    domain="cvefixes-security-ir/code-body", schema_version="cvefixes-code-body/v1").cid
                unit = CodeUnit(source_cids=(source_cid,), parent_cids=(source_cid,), config_cid=config_cid,
                    unit_kind="symbol", language="python", path=path, polarity=polarity,
                    payload={"body_sha256": checkpoint_api._sha(body), "body_cid": body_cid,
                        "source_binding": binding, "symbol": identity["symbol"],
                        "polarity_source": "caller_declared_source_version_not_a_function_vulnerability_prediction"})
                result = derivation_api.derive_code_program(code_unit=unit, source_bytes=body)
                results.append({**identity, "row_id": row_id, "source_binding": binding,
                    "code_unit": unit.to_dict(), "derivation": result})
                prefix += node.name + "."
            elif isinstance(node, ast.ClassDef):
                prefix += node.name + "."
            for child in ast.iter_child_nodes(node):
                visit(child, prefix)
        visit(tree)
    checkpoint_api._sources(repository, ledger)
    return {"source_hashes": ledger, "paths": sorted(paths), "function_results": results,
        "unsupported_files": unsupported, "provider_calls": 0, "solver_calls": 0,
        "executes_source": False, "source_semantics_verified": False, "proof_authority": False}


def _assemble(*, repository, paths, source_hashes, checkpoint, output, polarity, max_functions, inference):
    expected_selection = {"repository": str(repository), "checkpoint": checkpoint,
        "paths": sorted(paths), "source_hashes": checkpoint_api._ledger(source_hashes),
        "max_functions": max_functions, "output": str(output / "inference")}
    if any(inference.get(key) != value for key, value in expected_selection.items()):
        raise ValueError("evaluation and inference source/model selection differ")
    loaded = checkpoint_api._load_descriptor(checkpoint)
    deterministic = derive_security_source_programs(repository=repository, paths=paths,
        source_hashes=source_hashes, polarity=polarity, max_functions=max_functions)
    rows = {row["row_id"]: row for row in deterministic["function_results"]}
    ranked = [row["row_id"] for row in inference["ranks"]]
    # Files outside the source-map profile stay explicit coverage gaps.
    missing = sorted(set(ranked) - set(rows))
    if set(rows) - set(ranked):
        raise ValueError("deterministic function identity differs from checkpoint observations")
    results = [rows[row_id] for row_id in ranked if row_id in rows]
    programs = sum(row["derivation"]["status"] == "derived" for row in results)
    summary = {"sample_count": inference["sample_count"], "visited_function_count": len(results),
        "program_ir_count": programs, "unsupported_function_count": len(results) - programs,
        "unmapped_observation_count": len(missing), "learned_formula_count": 0,
        "smt_formula_count": 0, "learned_formula_generation_passed": False,
        "missing_capabilities": [_MISSING], "formal_artifact_producer": "deterministic_guarded_source_adapter",
        "autoencoder_role": "candidate_order_and_security_classification_only",
        "all_functions_retained": len(results) + len(missing) == inference["sample_count"],
        "held_out_evaluation": False, "security_specification_inferred": False}
    model = {"learned_formula_head": loaded["config"]["learned_formula_head"],
        "head": loaded["config"]["head"], "target_vocabulary": loaded["vocabularies"]["targets"],
        "decoder_output": "44 AST feature reconstruction values; not serialized formulas",
        "formal_decoder_implementation": None, "checkpoint_model_scope": loaded["manifest"]["model_scope"]}
    if model["learned_formula_head"] is not False:
        raise ValueError("this evaluator admits only the installed advisory checkpoint contract")
    implementation = {"evaluator_sha256": checkpoint_api._sha(Path(__file__).read_bytes()),
        "derivation_sha256": checkpoint_api._sha(Path(derivation_api.__file__).read_bytes()),
        "derivation_profile_cid": derivation_api.describe_code_program_derivation_profile()["profile_cid"]}
    value = {"schema": SCHEMA, "repository": str(repository), "output": str(output),
        "checkpoint": checkpoint, "paths": sorted(paths), "source_hashes": deterministic["source_hashes"],
        "polarity": polarity, "max_functions": max_functions, "inference": inference,
        "model_capabilities": model, "summary": summary, "missing_capabilities": [_MISSING],
        "function_results": results, "unmapped_observation_row_ids": missing,
        "unsupported_files": deterministic["unsupported_files"], "implementation": implementation,
        "training_steps": 0, "provider_calls": 0, "download_calls": 0, "solver_calls": 0,
        "executes_source": False, "source_semantics_verified": False,
        "proof_authority": False, "completion_authority": False}
    return {**value, "evaluation_cid": _cid(value, "security-evaluation/report")}


def run_security_formalization_evaluation(*, repository: Path, paths, source_hashes: dict,
        checkpoint: dict, output: Path, polarity="vulnerable", max_functions=1024) -> dict:
    repository = Path(repository).absolute()
    output = checkpoint_api._namespace(Path(output), fresh=True, excluded=(repository, Path(checkpoint["output"])))
    # Validate the modeling input contract before creating inference artifacts.
    derive_security_source_programs(repository=repository, paths=paths, source_hashes=source_hashes,
                                    polarity=polarity, max_functions=max_functions)
    output.mkdir(parents=True, mode=0o700)
    inference = checkpoint_api.infer_security_checkpoint(repository=repository, paths=paths,
        source_hashes=source_hashes, checkpoint=checkpoint, output=output / "inference", max_functions=max_functions)
    report = _assemble(repository=repository, paths=paths, source_hashes=source_hashes,
        checkpoint=checkpoint, output=output, polarity=polarity, max_functions=max_functions, inference=inference)
    raw = checkpoint_api._json(report)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("formalization evaluation artifact exceeds bound")
    checkpoint_api._write(output / "evaluation.json", raw)
    validate_security_formalization_evaluation(repository=repository, expected_report=report)
    return report


def validate_security_formalization_evaluation(*, repository: Path, expected_report: dict) -> dict:
    """Replay current source, actual frozen inference and deterministic models."""
    repository = Path(repository).absolute()
    output = checkpoint_api._namespace(Path(expected_report["output"]), excluded=(repository,))
    if {p.name for p in output.iterdir()} - {"evaluation.json", "inference", "cli-receipt.json"}:
        raise ValueError("closed evaluation artifact inventory required")
    raw = checkpoint_api._read(output / "evaluation.json", 32 * 1024 * 1024)
    if checkpoint_api._json(expected_report) != raw:
        raise ValueError("evaluation artifact differs from its expected report")
    checkpoint_api.validate_security_inference(repository=repository, expected_receipt=expected_report["inference"])
    rebuilt = _assemble(repository=repository, paths=expected_report["paths"],
        source_hashes=expected_report["source_hashes"], checkpoint=expected_report["checkpoint"],
        output=output, polarity=expected_report["polarity"], max_functions=expected_report["max_functions"],
        inference=expected_report["inference"])
    if checkpoint_api._json(rebuilt) != raw:
        raise ValueError("evaluation source, model attribution, coverage or authority changed")
    return rebuilt


def require_learned_formula_generation(report: dict) -> None:
    """Strict capability gate; deterministic artifacts cannot satisfy it."""
    if report.get("schema") != SCHEMA:
        raise ValueError("security formalization evaluation required")
    # There is intentionally no success path for this checkpoint architecture.
    # Adding a real decoder requires a new implementation and its own evidence.
    raise MissingFormalDecoderError("learned source-to-formula decoder is absent; classification and deterministic ProgramIR do not satisfy the capability")
