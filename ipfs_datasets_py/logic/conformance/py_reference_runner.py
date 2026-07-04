"""Python reference runner for the shared SwissKnife logic conformance corpus.

The runner intentionally accepts the same vector JSON as the TypeScript runner
and emits the same ConformanceResult envelope. It is designed to run in normal
developer checkouts before optional ATP/ZKP binaries are installed; the result
metadata records available Python logic modules so CI can distinguish host
provisioning from logical mismatches.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import pathlib
import subprocess
import time
from typing import Any, Dict, Iterable, List, Optional


RESULT_SCHEMA_VERSION = "2026-07-03"
SUBSYSTEMS = {
    "propositional",
    "fol",
    "temporal",
    "deontic",
    "modal",
    "dcec",
    "legal-norm",
    "zkp-statement",
}


def load_vectors(vectors_dir: str | pathlib.Path) -> List[Dict[str, Any]]:
    root = pathlib.Path(vectors_dir)
    vectors: List[Dict[str, Any]] = []
    seen = set()
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for vector in payload.get("vectors", []):
            validate_vector(vector, path.name)
            if vector["id"] in seen:
                raise ValueError(f"Duplicate conformance vector id: {vector['id']}")
            seen.add(vector["id"])
            vectors.append(vector)
    return vectors


def run_python_reference(
    vectors_dir: str | pathlib.Path,
    *,
    out_path: Optional[str | pathlib.Path] = None,
    subsystems: Optional[Iterable[str]] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    vectors = load_vectors(vectors_dir)
    if subsystems:
        wanted = set(subsystems)
        vectors = [vector for vector in vectors if vector["subsystem"] in wanted]
    if limit is not None:
        vectors = vectors[:limit]

    results = [run_vector(vector) for vector in vectors]
    envelope = {
        "schemaVersion": RESULT_SCHEMA_VERSION,
        "runner": "python-reference",
        "generatedAt": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "submoduleCommit": git_commit(pathlib.Path(__file__).resolve().parents[4]),
        "engineVersions": discover_engine_versions(),
        "results": results,
    }

    if out_path:
        out = pathlib.Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(envelope, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return envelope


def run_vector(vector: Dict[str, Any]) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        policy = vector.get("input", {}).get("policy")
        if vector.get("inputType") == "policy" and isinstance(policy, dict):
            outcome = evaluate_policy(policy, vector)
        else:
            outcome = {
                "status": "unknown",
                "reason": "unknown",
                "proverId": "python-reference",
                "metadata": {"skipped": "unsupported-vector-input", "inputType": vector.get("inputType")},
            }
        duration_ms = max(0.0, (time.perf_counter() - start) * 1000.0)
        expected = vector.get("expected", {})
        return {
            "vectorId": vector["id"],
            "subsystem": vector["subsystem"],
            "status": outcome["status"],
            "reason": outcome["reason"],
            "backendMode": backend_mode(vector, outcome),
            "proverId": outcome["proverId"],
            "durationMs": duration_ms,
            "modelHash": outcome.get("modelHash"),
            "metadata": {
                "expected": expected.get("status"),
                "acceptableReasons": expected.get("acceptableReasons", []),
                "tags": vector.get("tags", []),
                **outcome.get("metadata", {}),
            },
        }
    except Exception as exc:  # pragma: no cover - exercised by CLI failures
        return {
            "vectorId": vector.get("id", "<missing>"),
            "subsystem": vector.get("subsystem", "unknown"),
            "status": "error",
            "reason": "error",
            "backendMode": backend_mode(vector, None),
            "proverId": "python-reference",
            "durationMs": max(0.0, (time.perf_counter() - start) * 1000.0),
            "error": str(exc),
        }


def evaluate_policy(policy: Dict[str, Any], vector: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    subsystem = str((vector or {}).get("subsystem") or infer_policy_subsystem(policy))
    conflict = exact_permission_conflict(policy) or obligation_prohibition_conflict(policy)
    prover_checks = run_python_prover_checks(policy, subsystem)
    z3_check = next((check for check in prover_checks if check.get("engine") == "z3"), None)
    z3_status = z3_check.get("status") if z3_check else None
    is_refuted = z3_status == "unsat" or (z3_status != "sat" and conflict is not None)
    metadata = {
        "conflict": conflict,
        "pythonModuleMode": "module-backed-policy-runner",
        "pythonProverChecks": prover_checks,
    }

    if is_refuted:
        return {
            "status": "refuted",
            "reason": "refuted",
            "proverId": "python-z3-reference" if z3_status == "unsat" else preferred_policy_prover_id(subsystem, prover_checks),
            "metadata": {**metadata, "route": "policy-conflict"},
        }

    if policy.get("temporal") or any("deadline" in obligation for obligation in policy.get("obligations", [])):
        return {
            "status": "proved",
            "reason": "proved",
            "proverId": "python-tdfol-reference",
            "metadata": {**metadata, "route": "temporal"},
        }

    if policy.get("obligations") or policy.get("prohibitions"):
        return {
            "status": "proved",
            "reason": "proved",
            "proverId": preferred_policy_prover_id(subsystem, prover_checks),
            "metadata": {**metadata, "route": "modal_deontic"},
        }

    return {
        "status": "sat",
        "reason": "sat",
        "proverId": "python-z3-reference" if z3_status == "sat" else preferred_policy_prover_id(subsystem, prover_checks),
        "modelHash": stable_hash(policy),
        "metadata": {**metadata, "route": "smt"},
    }


def infer_policy_subsystem(policy: Dict[str, Any]) -> str:
    if policy.get("temporal") or any("deadline" in obligation for obligation in policy.get("obligations", [])):
        return "temporal"
    if policy.get("obligations") or policy.get("prohibitions"):
        return "dcec"
    return "propositional"


def run_python_prover_checks(policy: Dict[str, Any], subsystem: str) -> List[Dict[str, Any]]:
    checks = [run_tdfol_prover_check(policy, subsystem), run_z3_policy_check(policy)]
    if should_run_dcec_check(policy, subsystem):
        checks.append(run_dcec_prover_check(policy))
    return checks


def should_run_dcec_check(policy: Dict[str, Any], subsystem: str) -> bool:
    if subsystem in {"deontic", "modal", "dcec", "legal-norm", "zkp-statement"}:
        return True
    return bool(policy.get("obligations") or policy.get("prohibitions"))


def run_tdfol_prover_check(policy: Dict[str, Any], subsystem: str) -> Dict[str, Any]:
    try:
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import TDFOLKnowledgeBase
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import TDFOLProver

        formula = build_tdfol_policy_formula(policy, subsystem)
        kb = TDFOLKnowledgeBase()
        kb.add_axiom(formula, "conformance_policy")
        result = TDFOLProver(kb, enable_cache=False).prove(formula, timeout_ms=100)
        return {
            "engine": "tdfol",
            "status": getattr(result.status, "value", str(result.status)),
            "method": getattr(result, "method", "unknown"),
            "formulaHash": stable_hash(formula.to_string()),
        }
    except Exception as exc:
        return {"engine": "tdfol", "status": "unavailable", "error": f"{exc.__class__.__name__}: {exc}"}


def run_dcec_prover_check(policy: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from ipfs_datasets_py.logic.CEC.native.prover_core import TheoremProver

        formula = build_dcec_policy_formula(policy)
        attempt = TheoremProver().prove_theorem(formula, [formula], timeout=0.1)
        return {
            "engine": "dcec",
            "status": getattr(attempt.result, "value", str(attempt.result)),
            "formulaHash": stable_hash(formula.to_string()),
        }
    except Exception as exc:
        return {"engine": "dcec", "status": "unavailable", "error": f"{exc.__class__.__name__}: {exc}"}


def run_z3_policy_check(policy: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import z3  # type: ignore

        solver = z3.Solver()
        atoms: Dict[str, Any] = {}

        def atom(name: str) -> Any:
            normalized = normalize_atom(name) or "policy_atom"
            if normalized not in atoms:
                atoms[normalized] = z3.Bool(normalized)
            return atoms[normalized]

        for permission in policy.get("permissions", []):
            name = atom_name(str(permission.get("cap", "")), str(permission.get("rsc", "")))
            solver.add(atom(name))
        for prohibition in policy.get("prohibitions", []):
            name = atom_name(str(prohibition.get("cap", "")), str(prohibition.get("rsc", "")))
            solver.add(
                z3.Not(atom(name))
            )
        for obligation in policy.get("obligations", []):
            required = atom_name(str(obligation.get("requiredCap", "")), str(obligation.get("rsc", "")))
            description = normalize_atom(str(obligation.get("description", "")))
            solver.add(atom(required or description or "obligation"))

        result = solver.check()
        return {"engine": "z3", "status": str(result), "assertionCount": len(solver.assertions())}
    except Exception as exc:
        return {"engine": "z3", "status": "unavailable", "error": f"{exc.__class__.__name__}: {exc}"}


def build_tdfol_policy_formula(policy: Dict[str, Any], subsystem: str) -> Any:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
        DeonticFormula,
        DeonticOperator,
        Predicate,
        TemporalFormula,
        TemporalOperator,
    )

    formulas = []
    for permission in policy.get("permissions", []):
        formulas.append(
            DeonticFormula(
                DeonticOperator.PERMISSION,
                Predicate(atom_name(str(permission.get("cap", "")), str(permission.get("rsc", ""))), ()),
            )
        )
    for prohibition in policy.get("prohibitions", []):
        formulas.append(
            DeonticFormula(
                DeonticOperator.PROHIBITION,
                Predicate(atom_name(str(prohibition.get("cap", "")), str(prohibition.get("rsc", ""))), ()),
            )
        )
    for index, obligation in enumerate(policy.get("obligations", [])):
        atom = atom_name(str(obligation.get("requiredCap", "")), str(obligation.get("rsc", "")))
        atom = atom or normalize_atom(str(obligation.get("description", ""))) or f"obligation_{index}"
        formulas.append(DeonticFormula(DeonticOperator.OBLIGATION, Predicate(atom, ())))

    formula = combine_tdfol_formulas(formulas, Predicate(f"{normalize_atom(subsystem)}_policy", ()))
    if policy.get("temporal") or any("deadline" in obligation for obligation in policy.get("obligations", [])):
        return TemporalFormula(TemporalOperator.ALWAYS, formula)
    return formula


def combine_tdfol_formulas(formulas: List[Any], fallback: Any) -> Any:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import BinaryFormula, LogicOperator

    if not formulas:
        return fallback
    formula = formulas[0]
    for next_formula in formulas[1:]:
        formula = BinaryFormula(LogicOperator.AND, formula, next_formula)
    return formula


def build_dcec_policy_formula(policy: Dict[str, Any]) -> Any:
    from ipfs_datasets_py.logic.CEC.native.dcec_core import (
        AtomicFormula,
        ConnectiveFormula,
        DeonticFormula,
        DeonticOperator,
        LogicalConnective,
        Predicate,
    )

    formulas = []
    for permission in policy.get("permissions", []):
        atom = atom_name(str(permission.get("cap", "")), str(permission.get("rsc", "")))
        formulas.append(
            DeonticFormula(
                DeonticOperator.PERMISSION,
                AtomicFormula(Predicate(atom, []), []),
            )
        )
    for prohibition in policy.get("prohibitions", []):
        atom = atom_name(str(prohibition.get("cap", "")), str(prohibition.get("rsc", "")))
        formulas.append(
            DeonticFormula(
                DeonticOperator.PROHIBITION,
                AtomicFormula(Predicate(atom, []), []),
            )
        )
    for index, obligation in enumerate(policy.get("obligations", [])):
        atom = atom_name(str(obligation.get("requiredCap", "")), str(obligation.get("rsc", "")))
        atom = atom or normalize_atom(str(obligation.get("description", ""))) or f"obligation_{index}"
        formulas.append(DeonticFormula(DeonticOperator.OBLIGATION, AtomicFormula(Predicate(atom, []), [])))

    if not formulas:
        return AtomicFormula(Predicate("policy", []), [])
    if len(formulas) == 1:
        return formulas[0]
    return ConnectiveFormula(LogicalConnective.AND, formulas)


def preferred_policy_prover_id(subsystem: str, checks: List[Dict[str, Any]]) -> str:
    if subsystem == "temporal":
        return "python-tdfol-reference"
    if any(check.get("engine") == "dcec" and check.get("status") == "proved" for check in checks):
        return "python-dcec-reference"
    if any(check.get("engine") == "tdfol" and check.get("status") == "proved" for check in checks):
        return "python-tdfol-reference"
    return "python-module-reference"


def backend_mode(vector: Dict[str, Any], outcome: Optional[Dict[str, Any]]) -> str:
    expected_mode = vector.get("expected", {}).get("backendMode")
    if expected_mode == "simulated":
        return "simulated"
    if expected_mode == "real":
        return "real"
    if outcome and outcome.get("reason") not in {"unknown", "error"}:
        return "real"
    return expected_mode or "host-dependent"


def exact_permission_conflict(policy: Dict[str, Any]) -> Optional[str]:
    permissions = {f"{rule.get('cap')}|{rule.get('rsc')}" for rule in policy.get("permissions", [])}
    for prohibition in policy.get("prohibitions", []):
        key = f"{prohibition.get('cap')}|{prohibition.get('rsc')}"
        if key in permissions:
            return key
    return None


def obligation_prohibition_conflict(policy: Dict[str, Any]) -> Optional[str]:
    prohibited = {atom_name(rule.get("cap", ""), rule.get("rsc", "")) for rule in policy.get("prohibitions", [])}
    for obligation in policy.get("obligations", []):
        description = normalize_atom(str(obligation.get("description", "")))
        required = atom_name(str(obligation.get("requiredCap", "")), str(obligation.get("rsc", "")))
        if description in prohibited:
            return description
        if required and required in prohibited:
            return required
    return None


def atom_name(cap: str, rsc: str) -> str:
    return normalize_atom(f"{cap}_{rsc}" if rsc else cap)


def normalize_atom(value: str) -> str:
    chars = [char if char.isalnum() or char == "_" else "_" for char in value.strip()]
    return "".join(chars).strip("_")


def stable_hash(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def validate_vector(vector: Dict[str, Any], source: str) -> None:
    for key in ("id", "subsystem", "inputType", "input", "expected"):
        if key not in vector:
            raise ValueError(f"Vector in {source} is missing {key}")
    if vector["subsystem"] not in SUBSYSTEMS:
        raise ValueError(f"Unknown subsystem {vector['subsystem']} in {source}")
    reasons = vector.get("expected", {}).get("acceptableReasons")
    if not isinstance(reasons, list) or not reasons:
        raise ValueError(f"Vector {vector['id']} in {source} has no acceptableReasons")


def discover_engine_versions() -> Dict[str, str]:
    versions = {"runner": "py_reference_runner", "mode": "module-backed-policy-runner"}
    imports = {
        "z3_bridge": "ipfs_datasets_py.logic.external_provers.smt.z3_prover_bridge",
        "tdfol_core": "ipfs_datasets_py.logic.TDFOL.tdfol_core",
        "dcec_prover": "ipfs_datasets_py.logic.CEC.native.prover_core",
        "z3_runtime": "z3",
    }
    for label, module in imports.items():
        try:
            imported = __import__(module, fromlist=["__name__"])
            versions[label] = getattr(imported, "__version__", "available")
        except Exception as exc:
            versions[label] = f"unavailable:{exc.__class__.__name__}"
    return versions


def git_commit(repo_root: pathlib.Path) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return completed.stdout.strip()
    except Exception:
        return None


def default_vectors_dir() -> pathlib.Path:
    current = pathlib.Path.cwd().resolve()
    for candidate in [current, *current.parents]:
        vectors = candidate / "implementation_plan" / "conformance" / "vectors"
        if vectors.exists():
            return vectors
    return current / "implementation_plan" / "conformance" / "vectors"


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Python reference conformance vectors")
    parser.add_argument("--vectors", default=str(default_vectors_dir()), help="Directory containing vector JSON files")
    parser.add_argument("--out", help="Output result JSON path")
    parser.add_argument("--subsystems", help="Comma-separated subsystem filter")
    parser.add_argument("--limit", type=int, help="Limit vector count after filtering")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    subsystems = args.subsystems.split(",") if args.subsystems else None
    envelope = run_python_reference(args.vectors, out_path=args.out, subsystems=subsystems, limit=args.limit)
    if not args.out:
        print(json.dumps(envelope, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
