"""Source-bound learned candidates and independent code-model checks.

This is an offline inference pipeline, not a training or repair executor. The
learned production decoder, deterministic source models and solver results keep
separate attribution. Unsupported functions remain in the coverage denominator.
"""
from __future__ import annotations

import ast
from pathlib import Path

from . import security_autoencoder_checkpoint as portable
from .security_formalization_evaluation import derive_security_source_programs, _function_span
from ....ir_core.identity import canonical_identity

SCHEMA = "security-formalization-pipeline@1"


def _cid(value):
    return canonical_identity(value, domain="security-ir/formalization-pipeline", schema_version=SCHEMA).cid


def _bodies(raw):
    tree = ast.parse(raw.decode("utf-8"))
    return {(node.lineno, node.name): _function_span(raw, node)[0]
            for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _assemble(*, repository, source_hashes, decoder, protocol, max_functions, model_enabled, check_headers):
    from .security_formula_decoder import load_security_formula_decoder, decode_security_formula
    if type(model_enabled) is not bool or type(check_headers) is not bool:
        raise ValueError("exact boolean model and solver selections required")
    sources = portable._sources(repository, portable._ledger(source_hashes))
    loaded = load_security_formula_decoder(decoder)
    deterministic = derive_security_source_programs(repository=repository, paths=sorted(source_hashes),
        source_hashes=source_hashes, max_functions=max_functions)
    bodies = {name: _bodies(raw) for name, raw in sources.items()
              if name not in {row["path"] for row in deterministic["unsupported_files"]}}
    rows = []
    for row in deterministic["function_results"]:
        body = bodies[row["path"]][row["line"], row["symbol"].rsplit(".", 1)[-1]]
        decoded = decode_security_formula(source_bytes=body, source_path=row["path"],
            checkpoint=decoder, loaded=loaded, model_enabled=model_enabled)
        rows.append({**row, "learned": decoded})
    headers, checks = [], []
    if protocol is not None:
        from ....security_ir.code_header_derivation import (
            derive_header_semantics, check_header_semantics, validate_header_candidate_function,
        )
        from ....security_ir.doctor_header_contracts import WsgiHeaderProtocolContract
        if type(protocol) is not dict or set(protocol) != {"review_ref", "callback_parameter"}:
            raise ValueError("explicit closed reviewed header protocol required")
        reviewed = WsgiHeaderProtocolContract(**protocol)
        for path, raw in sorted(sources.items()):
            if path.endswith(".py"):
                header = derive_header_semantics(source_bytes=raw, source_path=path, protocol=reviewed)
                headers.append(header)
                if model_enabled:
                    for modeled in header["modeled_symbols"]:
                        for row in rows:
                            decoded = row["learned"]
                            if (row["path"] != path or row["symbol"] != modeled["symbol"]
                                    or row["line"] != modeled["line"]
                                    or decoded["validation"]["source_AST_equivalent"] is not True
                                    or not decoded["predicted_productions"]):
                                continue
                            binding = validate_header_candidate_function(source_bytes=raw,
                                source_path=path, protocol=reviewed, symbol=modeled["symbol"],
                                candidate_function_source=decoded["candidate_source"])
                            targets = [target for target in header["smt_targets"]
                                       if target["symbol"] == modeled["symbol"]]
                            # The model supplies productions; exact AST equality
                            # admits their deterministic native lowering. Model
                            # scores never invent the caller's specification.
                            row["learned_header"] = {"binding_cid": binding["validation_cid"],
                                "derivation_cid": header["derivation_cid"], "targets": targets,
                                "learned_formula_count": len(targets),
                                "producer": "learned_productions_with_independent_source_validation",
                                "compiler": "deterministic_native_string_SMT_lowering",
                                "specification": "caller_reviewed_header_protocol",
                                "proof_authority": False}
                if check_headers:
                    checks.append(check_header_semantics(header, source_bytes=raw, source_path=path, protocol=reviewed))
    learned_count = sum(row["learned"].get("learned_formula_count", 0)
                        + row.get("learned_header", {}).get("learned_formula_count", 0) for row in rows)
    accepted = sum(row["learned"].get("status") == "accepted" or bool(row.get("learned_header")) for row in rows)
    summary = {"function_count": len(rows), "learned_accepted_functions": accepted,
        "learned_formula_count": learned_count,
        "learned_abstained_functions": len(rows) - accepted,
        "deterministic_program_count": sum(row["derivation"]["status"] == "derived" for row in rows),
        "header_source_count": len(headers), "unsupported_file_count": len(deterministic["unsupported_files"]),
        "all_functions_retained": not deterministic["unsupported_files"],
        "deterministic_header_function_count": sum(len(header["modeled_symbols"]) for header in headers),
        "deterministic_header_formula_count": sum(header["formula_count"] for header in headers),
        "header_smt_obligation_count": sum(header["smt_obligation_count"] for header in headers),
        "learned_formula_generation_passed": learned_count > 0,
        "all_functions_have_learned_candidates": accepted == len(rows) and bool(rows)
            and not deterministic["unsupported_files"],
        "whole_program_semantics_verified": False,
        "security_specification_inferred": False, "held_out_benchmark_evaluation": False}
    if not model_enabled and learned_count:
        raise ValueError("model-off control cannot contain learned formulas")
    if portable._sources(repository, portable._ledger(source_hashes)) != sources:
        raise ValueError("formalization source changed during inference")
    value = {"schema": SCHEMA, "repository": str(repository), "source_hashes": source_hashes,
        "decoder": decoder, "protocol": protocol, "max_functions": max_functions,
        "model_enabled": model_enabled, "summary": summary, "function_results": rows,
        "header_models": headers, "header_checks": checks, "check_headers": check_headers,
        "unsupported_files": deterministic["unsupported_files"],
        "implementation_sha256": portable._sha(Path(__file__).read_bytes()),
        "training_steps": 0, "provider_calls": 0, "download_calls": 0,
        "solver_calls": sum(check["solver_calls"] for check in checks),
        "executes_source": False, "proof_authority": False, "completion_authority": False}
    return {**value, "report_cid": _cid(value)}


def run_security_formalization_pipeline(*, repository: Path, source_hashes: dict,
        decoder: dict, output: Path, protocol: dict | None = None,
        max_functions: int = 1024, model_enabled: bool = True, check_headers: bool = False) -> dict:
    """Run a frozen decoder and retain exact independent deterministic models."""
    repository = Path(repository).absolute()
    source_hashes = portable._ledger(source_hashes)
    if type(model_enabled) is not bool or type(check_headers) is not bool:
        raise ValueError("explicit boolean model ablation required")
    output = portable._namespace(Path(output), fresh=True,
                                 excluded=(repository, Path(decoder["output"])))
    report = _assemble(repository=repository, source_hashes=source_hashes, decoder=decoder,
        protocol=protocol, max_functions=max_functions, model_enabled=model_enabled, check_headers=check_headers)
    raw = portable._json(report)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("formalization report exceeds 32 MiB")
    output.mkdir(parents=True, mode=0o700)
    portable._write(output / "formalization.json", raw)
    return {"schema": SCHEMA, "output": str(output), "report_sha256": portable._sha(raw),
            "report_cid": report["report_cid"], "summary": report["summary"]}


def validate_security_formalization_pipeline(*, repository: Path, receipt: dict) -> dict:
    """Replay source, weights and every candidate; no trust in reported counts."""
    repository = Path(repository).absolute()
    output = portable._namespace(Path(receipt["output"]), excluded=(repository,))
    if {item.name for item in output.iterdir()} != {"formalization.json"}:
        raise ValueError("closed formalization inventory required")
    raw = portable._read(output / "formalization.json", 32 * 1024 * 1024)
    report = portable._decode(raw)
    expected = {"schema": SCHEMA, "output": str(output), "report_sha256": portable._sha(raw),
                "report_cid": report["report_cid"], "summary": report["summary"]}
    if portable._json(receipt) != portable._json(expected) or report["repository"] != str(repository):
        raise ValueError("formalization receipt or repository differs")
    rebuilt = _assemble(repository=repository, source_hashes=report["source_hashes"],
        decoder=report["decoder"], protocol=report["protocol"], max_functions=report["max_functions"],
        model_enabled=report["model_enabled"], check_headers=report["check_headers"])
    if portable._json(rebuilt) != raw:
        raise ValueError("formalization source, weights, model attribution or candidates changed")
    return report
