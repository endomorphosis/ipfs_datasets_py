"""Canonical source regression gates and five-case pilot; no Lean execution."""
from pathlib import Path
import hashlib, importlib.util, json, os, sys, time

PREPARED = Path('/home/barberb/lift_coding/external/ipfs_datasets')
BASE = Path(__file__).resolve().parent
TREE = "current-canonical-workspace"
sys.path.insert(0, str(PREPARED))
os.environ.update(IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0", IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE="0", HF_HUB_OFFLINE="1", CUDA_VISIBLE_DEVICES="")
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span, vocabulary_from_clause
from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalAtomVocabulary, CompilerRequest, OperationStatus
from benchmarks import bench_semantic_logic_roundtrip as benchmark

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
    paths = require_workspace_logic_tree()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_native_pool import _package_manifest
    producer_before = _package_manifest()
    lock_path = Path("/home/barberb/lift_coding/JevOps/jevops/statement_lock.py")
    spec = importlib.util.spec_from_file_location("isolated_statement_lock", lock_path)
    lock = importlib.util.module_from_spec(spec); sys.modules[spec.name] = lock; spec.loader.exec_module(lock)
    cases = [
        ("deadline_exception", "Company A shall submit backup report within 10 days unless emergency.", "O", "within_duration", 10),
        ("prohibition", "The agency shall not disclose records.", "F", None, None),
        ("minimum_duration", "The officer shall retain the file for at least 20 days.", "O", "minimum_duration", 20),
    ]
    gates = []
    compiler = TypedDeonticCanonicalCompiler()
    for name, text, modality, kind, quantity in cases:
        started = time.perf_counter(); vocab = vocabulary_from_clause(text); vocabulary_seconds = time.perf_counter() - started
        atoms = vocab is not None and all(isinstance(atom, str) for values in vocab.values() for atom in values)
        started = time.perf_counter()
        direct = compiler.compile(CompilerRequest(text, "canonical-search:" + name, CanonicalAtomVocabulary.from_dict(vocab)))
        compile_seconds = time.perf_counter() - started
        session = AutoformalSession(); span = compile_span(session, text, name, allow_partial=False)
        row = session.rows[0] if session.rows else None
        rule = dict(row.rule) if row is not None and row.rule else {}
        decompiled = str(span.get("decompiled") or (row.decompiled if row is not None else ""))
        temporal = rule.get("temporal_records", [])
        checks = {"parser_string_atoms": atoms, "direct_compile_success": direct.status.value == "success", "span_compile_success": span.get("compiler_status") == "compiled", "roundtrip_ok": row is not None and row.status == "roundtrip_ok", "modality": rule.get("modality") == modality}
        if kind:
            checks["typed_temporal"] = any(item.get("temporal_kind") == kind and item.get("quantity") == quantity for item in temporal)
        pattern = lock.pattern_from_rule(rule)
        if name == "deadline_exception":
            checks.update(deadline_text="10 days" in decompiled, exception_text="emergency" in decompiled, deadline_not_renderable=pattern is None)
        if name == "minimum_duration":
            checks.update(minimum_text="at least 20 days" in decompiled, no_malformed_minimum="at least days" not in decompiled, threshold_pattern=pattern == {"kind": "threshold", "fail": 19, "meet": 20})
        empty = compiler.compile(CompilerRequest(text, "canonical-search:empty:" + name, CanonicalAtomVocabulary()))
        checks["empty_vocabulary_abstains"] = empty.status is OperationStatus.ABSTAINED
        gates.append({"name": name, "source": text, "passed": all(checks.values()), "checks": checks, "vocabulary": vocab, "rule": rule, "decompiled": decompiled, "pattern": pattern, "empty_vocabulary": {"status": empty.status.value, "error_code": None if empty.error is None else empty.error.code.value}, "wall_seconds": {"vocabulary": vocabulary_seconds, "compile": compile_seconds}})
    reference_path = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/autoencoder-hardware-optimizer-20260928/semantic-pilot.json'); reference = json.loads(reference_path.read_bytes())
    previous = {row["case_id"]: row["result"] for row in reference["cases"]}
    results, pilot_rows = [], []
    for case in benchmark._load_cases(benchmark.DEFAULT_FIXTURE):
        result = benchmark.run_deontic_codec(case); results.append(result)
        scores = {name: result[name]["semantic_score"] for name in ("forward_vs_gold", "cycle_l1_vs_l2", "end_to_end_vs_gold")}
        baseline = {name: previous[case["id"]][name]["semantic_score"] for name in scores}
        passed = result["status"] == "success" and result["source_withheld_from_realizer"] and result["cycle_l1_vs_l2"]["exact_ir_nonvacuous"] and all(scores[name] >= baseline[name] for name in scores)
        pilot_rows.append({"case_id": case["id"], "passed": bool(passed), "scores": scores, "previous_canonical_scores": baseline, "l1_cid": result["l1_cid"], "l2_cid": result["l2_cid"], "rule_count": len(result["l1"]["rules"]), "realization": result["realization"]})
    aggregate = benchmark._aggregate_standard_arm(results)
    escaped = {name: str(Path(module.__file__).resolve()) for name, module in list(sys.modules.items()) if name.startswith("ipfs_datasets_py") and getattr(module, "__file__", None) and PREPARED not in Path(module.__file__).resolve().parents}
    producer_after = _package_manifest()
    checks = {"producer_unchanged": producer_before == producer_after, "all_fixed_gates": all(row["passed"] for row in gates), "five_case_nonregression": len(pilot_rows) == 5 and all(row["passed"] for row in pilot_rows), "historical_forward_threshold": aggregate["mean_forward_semantic_score"] >= .915, "cycle_threshold": aggregate["mean_cycle_semantic_score"] == 1.0, "all_ipfs_imports_canonical": not escaped}
    output = {"schema": "canonical-search-semantic-gates/v1", "passed": all(checks.values()), "producer_before": producer_before, "producer_after": producer_after, "checks": checks, "prepared_tree": TREE, "prepared_directory": str(PREPARED), "source_files": {name: {"path": path, "sha256": sha(path)} for name, path in paths.items()}, "escaped_ipfs_imports": escaped, "statement_lock": {"path": str(lock_path), "sha256": sha(lock_path)}, "harness": {"path": benchmark.__file__, "sha256": sha(benchmark.__file__), "fixture_path": str(benchmark.DEFAULT_FIXTURE), "fixture_sha256": sha(benchmark.DEFAULT_FIXTURE)}, "comparison_receipt": {"path": str(reference_path), "sha256": sha(reference_path)}, "gates": gates, "pilot": {"aggregate": aggregate, "cases": pilot_rows}, "scope": "Canonical source tests using current benchmark resources and unchanged JevOps rendering helper. No model calls, external prover, or Lake execution; not an admission.", "admitted": False, "formalized": False, "constitution_formalized": False}
    path = BASE / "semantic-gates.json"
    with path.open("x") as stream: json.dump(output, stream, sort_keys=True, indent=2); stream.write("\n")
    print(json.dumps({"path": str(path), "passed": output["passed"], "checks": checks, "pilot": aggregate}, sort_keys=True))

    return 0 if output["passed"] else 1

if __name__ == "__main__": raise SystemExit(main())
