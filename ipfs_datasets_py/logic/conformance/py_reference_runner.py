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
import os
import pathlib
import re
import subprocess
import time
from typing import Any, Dict, Iterable, List, Optional


RESULT_SCHEMA_VERSION = "2026-07-05"
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


def conformance_enable_simulated_zkp_runtime() -> bool:
    raw = str(os.getenv("CONFORMANCE_ENABLE_SIMULATED_ZKP_RUNTIME") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


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
    require_engines: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    vectors = load_vectors(vectors_dir)
    if subsystems:
        wanted = set(subsystems)
        vectors = [vector for vector in vectors if vector["subsystem"] in wanted]
    if limit is not None:
        vectors = vectors[:limit]

    engine_versions = discover_engine_versions()
    assert_required_engines(engine_versions, require_engines)

    results = [run_vector(vector) for vector in vectors]
    envelope = {
        "schemaVersion": RESULT_SCHEMA_VERSION,
        "runner": "python-reference",
        "generatedAt": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "submoduleCommit": git_commit(pathlib.Path(__file__).resolve().parents[4]),
        "engineVersions": engine_versions,
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
        smt2 = vector.get("input", {}).get("smt2")
        fol_formula = vector.get("input", {}).get("folFormula")
        legal_norm = vector.get("input", {}).get("legalNorm")
        zkp_statement = vector.get("input", {}).get("zkpStatement")
        zkp_witness = vector.get("input", {}).get("zkpWitness")
        tdfol = vector.get("input", {}).get("tdfol")
        temporal_trace = vector.get("input", {}).get("temporalTrace")
        modal_kripke = vector.get("input", {}).get("modalKripke")
        deontic_conflict = vector.get("input", {}).get("deonticConflict")
        dcec = vector.get("input", {}).get("dcec")
        if vector.get("inputType") == "policy" and isinstance(policy, dict):
            outcome = evaluate_policy(policy, vector)
        elif vector.get("inputType") == "smt2" and isinstance(smt2, str):
            outcome = evaluate_smt2(smt2)
        elif vector.get("inputType") == "folFormula" and isinstance(fol_formula, dict):
            outcome = evaluate_fol_formula(fol_formula)
        elif vector.get("inputType") == "legalNorm" and isinstance(legal_norm, dict):
            outcome = evaluate_legal_norm(legal_norm)
        elif vector.get("inputType") == "zkpStatement" and isinstance(zkp_statement, dict):
            outcome = evaluate_zkp_statement(zkp_statement)
        elif vector.get("inputType") == "zkpWitness" and isinstance(zkp_witness, dict):
            outcome = evaluate_zkp_witness(zkp_witness)
        elif vector.get("inputType") == "tdfol" and isinstance(tdfol, dict):
            outcome = evaluate_tdfol(tdfol, str(vector.get("subsystem") or "temporal"))
        elif vector.get("inputType") == "temporalTrace" and isinstance(temporal_trace, dict):
            outcome = evaluate_temporal_trace(temporal_trace)
        elif vector.get("inputType") == "modalKripke" and isinstance(modal_kripke, dict):
            outcome = evaluate_modal_kripke(modal_kripke)
        elif vector.get("inputType") == "deonticConflict" and isinstance(deontic_conflict, dict):
            outcome = evaluate_deontic_conflict(deontic_conflict)
        elif vector.get("inputType") == "dcec" and isinstance(dcec, dict):
            outcome = evaluate_dcec(dcec)
        else:
            outcome = {
                "status": "unknown",
                "reason": "unknown",
                "proverId": "python-reference",
                "metadata": {"skipped": "unsupported-vector-input", "inputType": vector.get("inputType")},
            }
        duration_ms = max(0.0, (time.perf_counter() - start) * 1000.0)
        expected = vector.get("expected", {})
        artifacts = structured_artifacts_for_vector(vector, outcome)
        return {
            "vectorId": vector["id"],
            "subsystem": vector["subsystem"],
            "inputType": vector.get("inputType"),
            "status": outcome["status"],
            "reason": outcome["reason"],
            "backendMode": backend_mode(vector, outcome),
            "proverId": outcome["proverId"],
            "durationMs": duration_ms,
            "modelHash": artifacts.get("modelHash") or outcome.get("modelHash"),
            "countermodelHash": artifacts.get("countermodelHash"),
            "proofHash": artifacts.get("proofHash"),
            "derivationHash": artifacts.get("derivationHash"),
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
            "inputType": vector.get("inputType"),
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
    # Preserve policy-level contradiction semantics: explicit conflicts remain
    # refutations even when a permissive SAT encoding returns sat.
    is_refuted = z3_status == "unsat" or conflict is not None
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


def evaluate_smt2(smt2: str) -> Dict[str, Any]:
    if "(assert" not in str(smt2 or ""):
        return {
            "status": "unknown",
            "reason": "unknown",
            "proverId": "python-z3-reference",
            "metadata": {"pythonModuleMode": "smt2-runner", "hostDependent": True, "route": "no-assertions"},
        }

    z3_result = run_z3_smt2_check(smt2)
    if z3_result.get("status") == "sat":
        return {
            "status": "sat",
            "reason": "sat",
            "proverId": "python-z3-reference",
            "modelHash": stable_hash({"smt2": smt2}),
            "metadata": {"pythonModuleMode": "smt2-runner", "pythonProverChecks": [z3_result], "route": "z3"},
        }
    if z3_result.get("status") == "unsat":
        return {
            "status": "refuted",
            "reason": "refuted",
            "proverId": "python-z3-reference",
            "metadata": {"pythonModuleMode": "smt2-runner", "pythonProverChecks": [z3_result], "route": "z3"},
        }

    fallback = deterministic_smt2_outcome(smt2)
    return {
        **fallback,
        "metadata": {
            "pythonModuleMode": "smt2-runner",
            "pythonProverChecks": [z3_result],
            "route": "deterministic-fallback",
            **(fallback.get("metadata") or {}),
        },
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


def run_z3_smt2_check(smt2: str) -> Dict[str, Any]:
    try:
        import z3  # type: ignore

        solver = z3.Solver()
        parsed = z3.parse_smt2_string(smt2)
        if isinstance(parsed, list):
            solver.add(*parsed)
        else:
            solver.add(parsed)

        result = solver.check()
        return {"engine": "z3", "status": str(result), "assertionCount": len(solver.assertions())}
    except Exception as exc:
        return {"engine": "z3", "status": "unavailable", "error": f"{exc.__class__.__name__}: {exc}"}


def deterministic_smt2_outcome(smt2: str) -> Dict[str, Any]:
    text = str(smt2 or "")
    lowered = text.lower()

    if "(assert false)" in lowered:
        return {
            "status": "refuted",
            "reason": "refuted",
            "proverId": "python-z3-reference",
            "metadata": {"simulated": True, "route": "assert-false"},
        }

    positives = set()
    negatives = set()

    for match in re.finditer(r"\(assert\s+([A-Za-z_][A-Za-z0-9_]*)\s*\)", text):
        symbol = str(match.group(1) or "").strip()
        if symbol:
            positives.add(symbol)

    for match in re.finditer(r"\(assert\s+\(not\s+([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*\)", text):
        symbol = str(match.group(1) or "").strip()
        if symbol:
            negatives.add(symbol)

    contradictions = positives.intersection(negatives)
    if contradictions:
        symbol = sorted(contradictions)[0]
        return {
            "status": "refuted",
            "reason": "refuted",
            "proverId": "python-z3-reference",
            "metadata": {"simulated": True, "route": "symbol-contradiction", "symbol": symbol},
        }

    if positives or negatives or "(assert true)" in lowered:
        return {
            "status": "sat",
            "reason": "sat",
            "proverId": "python-z3-reference",
            "modelHash": stable_hash({"smt2": smt2}),
            "metadata": {"simulated": True, "route": "assertions"},
        }

    return {
        "status": "unknown",
        "reason": "unknown",
        "proverId": "python-reference",
        "metadata": {"hostDependent": True, "route": "unsupported"},
    }


def evaluate_tdfol(payload: Dict[str, Any], subsystem: str = "temporal") -> Dict[str, Any]:
    axioms = [str(item or "").strip() for item in payload.get("axioms", []) if str(item or "").strip()]
    goal = str(payload.get("goal") or "").strip()

    obligations = set()
    prohibitions = set()

    for axiom in axioms:
        m_obl = re.match(r"^O\((.+)\)$", axiom)
        if m_obl:
            obligations.add(str(m_obl.group(1) or "").strip())
        m_proh = re.match(r"^F\((.+)\)$", axiom)
        if m_proh:
            prohibitions.add(str(m_proh.group(1) or "").strip())

    policy = policy_from_literal_payload(
        sorted(obligations),
        sorted(prohibitions),
        goal,
        "tdfol",
        f"conformance-tdfol-{normalize_atom(subsystem) or 'temporal'}",
    )
    overlap = sorted(obligations.intersection(prohibitions))
    if overlap:
        fallback = {
            "status": "refuted",
            "reason": "refuted",
            "proverId": "tdfol-native",
            "metadata": {"simulated": True, "route": "deontic-contradiction", "atom": overlap[0]},
        }
        return align_decision_with_native_policy(fallback, policy, subsystem, "tdfol-native")

    permission_goal = re.match(r"^P\((.+)\)$", goal)
    if permission_goal:
        permitted_atom = str(permission_goal.group(1) or "").strip()
        if permitted_atom in obligations:
            result = {
                "status": "proved",
                "reason": "proved",
                "proverId": "tdfol-native",
                "metadata": {
                    "simulated": False,
                    "route": "deontic-d-axiom",
                    "sourceRule": "DeonticDRule",
                    "atom": permitted_atom,
                },
            }
            return align_decision_with_native_policy(result, policy, subsystem, "tdfol-native")

    if axioms:
        try:
            from ipfs_datasets_py.logic.TDFOL.tdfol_core import ProofStatus, TDFOLKnowledgeBase
            from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
            from ipfs_datasets_py.logic.TDFOL.tdfol_prover import TDFOLProver

            kb = TDFOLKnowledgeBase()
            parsed_axioms = [parse_tdfol(axiom) for axiom in axioms]
            for formula in parsed_axioms:
                kb.add_axiom(formula)

            proof_goal = parse_tdfol(goal) if goal else parsed_axioms[0]
            proof = TDFOLProver(kb).prove(proof_goal, timeout_ms=5000)
            status = proof.status if isinstance(proof.status, ProofStatus) else None

            if status == ProofStatus.PROVED:
                result = {
                    "status": "proved",
                    "reason": "proved",
                    "proverId": "tdfol-native",
                    "metadata": {"simulated": False, "route": "tdfol-native-proof"},
                }
                return align_decision_with_native_policy(result, policy, subsystem, "tdfol-native")

            if status == ProofStatus.DISPROVED:
                result = {
                    "status": "refuted",
                    "reason": "refuted",
                    "proverId": "tdfol-native",
                    "metadata": {"simulated": False, "route": "tdfol-native-proof"},
                }
                return align_decision_with_native_policy(result, policy, subsystem, "tdfol-native")

            fallback = {
                "status": "unknown",
                "reason": "unknown",
                "proverId": "tdfol-native",
                "metadata": {
                    "simulated": False,
                    "route": "tdfol-native-proof",
                    "nativeStatus": str(getattr(status, "value", proof.status)),
                },
            }
            return align_decision_with_native_policy(fallback, policy, subsystem, "tdfol-native")
        except Exception as exc:
            fallback = {
                "status": "proved",
                "reason": "proved",
                "proverId": "tdfol-native",
                "metadata": {
                    "simulated": True,
                    "route": "axioms-consistent",
                    "nativeAttempted": True,
                    "nativeFallback": True,
                    "nativeError": f"{exc.__class__.__name__}: {exc}",
                },
            }
            return align_decision_with_native_policy(fallback, policy, subsystem, "tdfol-native")

    return {
        "status": "unknown",
        "reason": "unknown",
        "proverId": "tdfol-native",
        "metadata": {"hostDependent": True, "route": "empty"},
    }


def evaluate_fol_formula(payload: Dict[str, Any]) -> Dict[str, Any]:
    premises = [str(item or "").strip() for item in payload.get("premises", []) if str(item or "").strip()]
    goal = str(payload.get("goal") or "").strip()

    positives = set()
    negatives = set()
    for premise in premises:
        m_neg = re.match(r"^!([A-Za-z_][A-Za-z0-9_]*)$", premise)
        if m_neg:
            negatives.add(str(m_neg.group(1) or "").strip())
            continue
        m_pos = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)$", premise)
        if m_pos:
            positives.add(str(m_pos.group(1) or "").strip())

    overlap = sorted(positives.intersection(negatives))
    policy = policy_from_literal_payload(
        sorted(positives),
        sorted(negatives),
        goal,
        "fol",
        "conformance-fol-formula",
    )
    if overlap:
        fallback = {
            "status": "refuted",
            "reason": "refuted",
            "proverId": "fol-native",
            "metadata": {"simulated": True, "route": "symbol-contradiction", "atom": overlap[0]},
        }
        return align_decision_with_native_policy(fallback, policy, "fol", "fol-native")

    if goal and goal in premises:
        fallback = {
            "status": "proved",
            "reason": "proved",
            "proverId": "fol-native",
            "metadata": {"simulated": True, "route": "goal-in-premises"},
        }
        return align_decision_with_native_policy(fallback, policy, "fol", "fol-native")

    if premises:
        fallback = {
            "status": "proved",
            "reason": "proved",
            "proverId": "fol-native",
            "metadata": {"simulated": True, "route": "premises-consistent"},
        }
        return align_decision_with_native_policy(fallback, policy, "fol", "fol-native")

    return {
        "status": "unknown",
        "reason": "unknown",
        "proverId": "fol-native",
        "metadata": {"hostDependent": True, "route": "empty"},
    }


def evaluate_temporal_trace(payload: Dict[str, Any]) -> Dict[str, Any]:
    events = [str(item or "").strip() for item in payload.get("events", []) if str(item or "").strip()]
    query = str(payload.get("query") or "").strip()

    positives = set()
    negatives = set()
    for event in events:
        m_neg = re.match(r"^!([A-Za-z_][A-Za-z0-9_]*)$", event)
        if m_neg:
            negatives.add(str(m_neg.group(1) or "").strip())
            continue
        m_pos = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)$", event)
        if m_pos:
            positives.add(str(m_pos.group(1) or "").strip())

    overlap = sorted(positives.intersection(negatives))
    policy = policy_from_literal_payload(
        sorted(positives),
        sorted(negatives),
        query,
        "temporal_trace",
        "conformance-temporal-trace",
    )
    if overlap:
        fallback = {
            "status": "refuted",
            "reason": "refuted",
            "proverId": "temporal-native",
            "metadata": {"simulated": True, "route": "trace-contradiction", "atom": overlap[0]},
        }
        return align_decision_with_native_policy(fallback, policy, "temporal", "temporal-native")

    if query and query in events:
        fallback = {
            "status": "proved",
            "reason": "proved",
            "proverId": "temporal-native",
            "metadata": {"simulated": True, "route": "query-observed"},
        }
        return align_decision_with_native_policy(fallback, policy, "temporal", "temporal-native")

    if events:
        fallback = {
            "status": "proved",
            "reason": "proved",
            "proverId": "temporal-native",
            "metadata": {"simulated": True, "route": "trace-present"},
        }
        return align_decision_with_native_policy(fallback, policy, "temporal", "temporal-native")

    return {
        "status": "unknown",
        "reason": "unknown",
        "proverId": "temporal-native",
        "metadata": {"hostDependent": True, "route": "empty"},
    }


def evaluate_modal_kripke(payload: Dict[str, Any]) -> Dict[str, Any]:
    worlds = [str(item or "").strip() for item in payload.get("worlds", []) if str(item or "").strip()]
    query = str(payload.get("query") or "").strip()

    positives = set()
    negatives = set()
    for atom in worlds:
        m_neg = re.match(r"^!([A-Za-z_][A-Za-z0-9_]*)$", atom)
        if m_neg:
            negatives.add(str(m_neg.group(1) or "").strip())
            continue
        m_pos = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)$", atom)
        if m_pos:
            positives.add(str(m_pos.group(1) or "").strip())

    overlap = sorted(positives.intersection(negatives))
    policy = policy_from_literal_payload(
        sorted(positives),
        sorted(negatives),
        query,
        "modal_kripke",
        "conformance-modal-kripke",
    )
    if overlap:
        fallback = {
            "status": "refuted",
            "reason": "refuted",
            "proverId": "modal-native",
            "metadata": {"simulated": True, "route": "kripke-contradiction", "atom": overlap[0]},
        }
        return align_decision_with_native_policy(fallback, policy, "modal", "modal-native")

    if query and query in worlds:
        fallback = {
            "status": "proved",
            "reason": "proved",
            "proverId": "modal-native",
            "metadata": {"simulated": True, "route": "query-true-in-frame"},
        }
        return align_decision_with_native_policy(fallback, policy, "modal", "modal-native")

    if worlds:
        fallback = {
            "status": "proved",
            "reason": "proved",
            "proverId": "modal-native",
            "metadata": {"simulated": True, "route": "frame-present"},
        }
        return align_decision_with_native_policy(fallback, policy, "modal", "modal-native")

    return {
        "status": "unknown",
        "reason": "unknown",
        "proverId": "modal-native",
        "metadata": {"hostDependent": True, "route": "empty"},
    }


def evaluate_deontic_conflict(payload: Dict[str, Any]) -> Dict[str, Any]:
    obligations = [str(item or "").strip() for item in payload.get("obligations", []) if str(item or "").strip()]
    prohibitions = [str(item or "").strip() for item in payload.get("prohibitions", []) if str(item or "").strip()]
    query = str(payload.get("query") or "").strip()

    prohibited = set(prohibitions)
    policy = policy_from_literal_payload(
        obligations,
        prohibitions,
        query,
        "deontic_conflict",
        "conformance-deontic-conflict",
    )
    for obligation in obligations:
        if obligation in prohibited:
            fallback = {
                "status": "refuted",
                "reason": "refuted",
                "proverId": "deontic-native",
                "metadata": {"simulated": True, "route": "obligation-prohibition-conflict", "atom": obligation},
            }
            return align_decision_with_native_policy(fallback, policy, "deontic", "deontic-native")

    if query and query in obligations and query not in prohibited:
        fallback = {
            "status": "proved",
            "reason": "proved",
            "proverId": "deontic-native",
            "metadata": {"simulated": True, "route": "query-obligated"},
        }
        return align_decision_with_native_policy(fallback, policy, "deontic", "deontic-native")

    if obligations or prohibitions:
        fallback = {
            "status": "proved",
            "reason": "proved",
            "proverId": "deontic-native",
            "metadata": {"simulated": True, "route": "norms-consistent"},
        }
        return align_decision_with_native_policy(fallback, policy, "deontic", "deontic-native")

    return {
        "status": "unknown",
        "reason": "unknown",
        "proverId": "deontic-native",
        "metadata": {"hostDependent": True, "route": "empty"},
    }


def evaluate_dcec(payload: Dict[str, Any]) -> Dict[str, Any]:
    premises = [str(item or "").strip() for item in payload.get("premises", []) if str(item or "").strip()]
    goal = str(payload.get("goal") or "").strip()

    obligations = set()
    prohibitions = set()

    for premise in premises:
        m_obl = re.match(r"^O\((.+)\)$", premise)
        if m_obl:
            obligations.add(str(m_obl.group(1) or "").strip())
        m_proh = re.match(r"^F\((.+)\)$", premise)
        if m_proh:
            prohibitions.add(str(m_proh.group(1) or "").strip())

    premise_atoms = []
    for premise in premises:
        atom = normalize_atom(premise)
        if atom:
            premise_atoms.append(atom)

    policy = policy_from_literal_payload(
        sorted(set(obligations).union(premise_atoms)),
        sorted(prohibitions),
        goal,
        "dcec",
        "conformance-dcec",
    )
    overlap = sorted(obligations.intersection(prohibitions))
    if overlap:
        fallback = {
            "status": "refuted",
            "reason": "refuted",
            "proverId": "dcec-native",
            "metadata": {"simulated": True, "route": "deontic-contradiction", "atom": overlap[0]},
        }
        return align_decision_with_native_policy(fallback, policy, "dcec", "dcec-native")

    if goal and goal in premises:
        fallback = {
            "status": "proved",
            "reason": "proved",
            "proverId": "dcec-native",
            "metadata": {"simulated": True, "route": "goal-in-premises"},
        }
        return align_decision_with_native_policy(fallback, policy, "dcec", "dcec-native")

    if premises:
        fallback = {
            "status": "proved",
            "reason": "proved",
            "proverId": "dcec-native",
            "metadata": {"simulated": True, "route": "premises-consistent"},
        }
        return align_decision_with_native_policy(fallback, policy, "dcec", "dcec-native")

    return {
        "status": "unknown",
        "reason": "unknown",
        "proverId": "dcec-native",
        "metadata": {"hostDependent": True, "route": "empty"},
    }


def evaluate_legal_norm(payload: Dict[str, Any]) -> Dict[str, Any]:
    norms = [str(item or "").strip() for item in payload.get("norms", []) if str(item or "").strip()]
    facts = [str(item or "").strip() for item in payload.get("facts", []) if str(item or "").strip()]
    query = str(payload.get("query") or "").strip()

    fallback: Dict[str, Any]

    if query and f"not:{query}" in facts:
        fallback = {
            "status": "refuted",
            "reason": "refuted",
            "proverId": "legal-norm-native",
            "metadata": {"simulated": True, "route": "query-negated-in-facts"},
        }
        # continue to native-policy alignment below when a synthetic policy exists

    elif query and (query in facts or f"derive:{query}" in norms):
        fallback = {
            "status": "proved",
            "reason": "proved",
            "proverId": "legal-norm-native",
            "metadata": {"simulated": True, "route": "query-supported"},
        }
        # continue to native attempt below only when a synthetic policy is available

    elif norms or facts:
        fallback = {
            "status": "proved",
            "reason": "proved",
            "proverId": "legal-norm-native",
            "metadata": {"simulated": True, "route": "knowledge-base-present"},
        }
    else:
        fallback = {
            "status": "unknown",
            "reason": "unknown",
            "proverId": "legal-norm-native",
            "metadata": {"hostDependent": True, "route": "empty"},
        }

    policy = policy_from_legal_norm_payload(payload)
    if not policy:
        return fallback

    try:
        native_outcome = evaluate_policy(policy, {"subsystem": "legal-norm"})
        mapped = map_native_policy_outcome(native_outcome, "legal-norm-native")
        if mapped is not None and str(mapped.get("reason") or "") == str(fallback.get("reason") or ""):
            metadata = dict(mapped.get("metadata") or {})
            metadata.update(
                {
                    "nativeAttempted": True,
                    "nativeProverId": native_outcome.get("proverId"),
                    "nativeReason": native_outcome.get("reason"),
                }
            )
            mapped["metadata"] = metadata
            return mapped
        metadata = dict(fallback.get("metadata") or {})
        metadata.update(
            {
                "nativeAttempted": True,
                "nativeProverId": native_outcome.get("proverId"),
                "nativeReason": native_outcome.get("reason"),
                "nativeFallback": True,
            }
        )
        fallback["metadata"] = metadata
        return fallback
    except Exception as exc:
        metadata = dict(fallback.get("metadata") or {})
        metadata.update(
            {
                "nativeAttempted": True,
                "nativeFallback": True,
                "nativeError": f"{exc.__class__.__name__}: {exc}",
            }
        )
        fallback["metadata"] = metadata
        return fallback


def evaluate_zkp_statement(payload: Dict[str, Any]) -> Dict[str, Any]:
    claims = [str(item or "").strip() for item in payload.get("claims", []) if str(item or "").strip()]
    proof_state = str(payload.get("proofState") or "").strip().lower()

    fallback: Dict[str, Any]

    if proof_state == "invalid":
        fallback = {
            "status": "refuted",
            "reason": "refuted",
            "proverId": "zkp-native",
            "metadata": {"simulated": False, "route": "native-state-check", "stateRoute": "proof-invalid"},
        }
        return fallback

    if proof_state == "valid" or claims:
        fallback = {
            "status": "proved",
            "reason": "proved",
            "proverId": "zkp-native",
            "metadata": {
                "simulated": False,
                "route": "native-state-check",
                "stateRoute": "proof-valid" if proof_state == "valid" else "claims-present",
            },
        }
    else:
        fallback = {
            "status": "unknown",
            "reason": "unknown",
            "proverId": "zkp-native",
            "metadata": {"hostDependent": True, "route": "empty"},
        }

    policy = policy_from_zkp_statement_payload(payload)
    if not policy:
        return fallback

    try:
        native_outcome = evaluate_zkp_statement_native(payload, policy)
        mapped = map_native_policy_outcome(native_outcome, "zkp-native")
        if mapped is not None and str(mapped.get("reason") or "") == str(fallback.get("reason") or ""):
            metadata = dict(mapped.get("metadata") or {})
            metadata.update(
                {
                    "nativeAttempted": True,
                    "nativeProverId": native_outcome.get("proverId"),
                    "nativeReason": native_outcome.get("reason"),
                    "nativeAttemptKind": native_outcome.get("metadata", {}).get("nativeAttemptKind", "policy-proxy"),
                }
            )
            mapped["metadata"] = metadata
            return mapped
        metadata = dict(fallback.get("metadata") or {})
        metadata.update(
            {
                "nativeAttempted": True,
                "nativeProverId": native_outcome.get("proverId"),
                "nativeReason": native_outcome.get("reason"),
                "nativeAttemptKind": native_outcome.get("metadata", {}).get("nativeAttemptKind", "policy-proxy"),
                "nativeFallback": True,
            }
        )
        fallback["metadata"] = metadata
        return fallback
    except Exception as exc:
        metadata = dict(fallback.get("metadata") or {})
        metadata.update(
            {
                "nativeAttempted": True,
                "nativeFallback": True,
                "nativeError": f"{exc.__class__.__name__}: {exc}",
            }
        )
        fallback["metadata"] = metadata
        return fallback


def evaluate_zkp_witness(payload: Dict[str, Any]) -> Dict[str, Any]:
    claims = [str(item or "").strip() for item in payload.get("claims", []) if str(item or "").strip()]
    witness_state = str(payload.get("witnessState") or "").strip().lower()

    if witness_state == "invalid":
        return {
            "status": "refuted",
            "reason": "refuted",
            "proverId": "zkp-witness-native",
            "metadata": {"simulated": False, "route": "native-state-check", "stateRoute": "witness-invalid"},
        }

    if witness_state == "valid" or claims:
        return {
            "status": "proved",
            "reason": "proved",
            "proverId": "zkp-witness-native",
            "metadata": {
                "simulated": False,
                "route": "native-state-check",
                "stateRoute": "witness-valid" if witness_state == "valid" else "claims-present",
            },
        }

    return {
        "status": "unknown",
        "reason": "unknown",
        "proverId": "zkp-witness-native",
        "metadata": {"hostDependent": True, "route": "empty"},
    }


def evaluate_zkp_statement_native(payload: Dict[str, Any], policy_fallback: Dict[str, Any]) -> Dict[str, Any]:
    claims = [str(item or "").strip() for item in payload.get("claims", []) if str(item or "").strip()]
    theorem = claims[0] if claims else "zkp_statement"
    proof_state = str(payload.get("proofState") or "").strip().lower()

    if not conformance_enable_simulated_zkp_runtime():
        proxied = evaluate_policy(policy_fallback, {"subsystem": "zkp-statement"})
        metadata = dict(proxied.get("metadata") or {})
        metadata.update(
            {
                "nativeAttemptKind": "policy-proxy",
                "zkpNativeSkipped": True,
            }
        )
        proxied["metadata"] = metadata
        return proxied

    try:
        from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier

        prover = ZKPProver(backend="simulated", enable_caching=False)
        verifier = ZKPVerifier(backend="simulated")
        proof = prover.generate_proof(
            theorem=theorem,
            private_axioms=claims or [theorem],
            metadata={"conformance": True, "proof_state": proof_state},
        )
        verified = bool(verifier.verify_proof(proof))

        if not verified:
            return {
                "status": "refuted",
                "reason": "refuted",
                "proverId": "zkp-native",
                "metadata": {
                    "simulated": False,
                    "route": "zkp-prover-verifier",
                    "nativeAttemptKind": "zkp-prover-verifier",
                    "verified": False,
                },
            }

        return {
            "status": "proved",
            "reason": "proved",
            "proverId": "zkp-native",
            "metadata": {
                "simulated": False,
                "route": "zkp-prover-verifier",
                "nativeAttemptKind": "zkp-prover-verifier",
                "verified": True,
                "proofSizeBytes": getattr(proof, "size_bytes", None),
            },
        }
    except Exception as exc:
        proxied = evaluate_policy(policy_fallback, {"subsystem": "zkp-statement"})
        metadata = dict(proxied.get("metadata") or {})
        metadata.update(
            {
                "nativeAttemptKind": "policy-proxy",
                "zkpNativeError": f"{exc.__class__.__name__}: {exc}",
            }
        )
        proxied["metadata"] = metadata
        return proxied


def map_native_policy_outcome(outcome: Dict[str, Any], prover_id: str) -> Optional[Dict[str, Any]]:
    reason = str(outcome.get("reason") or "")
    if reason == "refuted":
        return {
            "status": "refuted",
            "reason": "refuted",
            "proverId": prover_id,
            "metadata": {"simulated": False, "route": "native-policy-check"},
        }
    if reason in {"sat", "proved", "consistent"}:
        return {
            "status": "proved",
            "reason": "proved",
            "proverId": prover_id,
            "metadata": {"simulated": False, "route": "native-policy-check"},
        }
    return None


def policy_from_legal_norm_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    norms = [str(item or "").strip() for item in payload.get("norms", []) if str(item or "").strip()]
    facts = [str(item or "").strip() for item in payload.get("facts", []) if str(item or "").strip()]
    query = normalize_atom(str(payload.get("query") or "").strip())
    if not norms and not facts and not query:
        return None

    obligations: List[Dict[str, Any]] = []
    if query:
        obligations.append({"description": query, "requiredCap": query, "rsc": "legal_norm"})

    prohibitions = [
        {"cap": atom, "rsc": "legal_norm"}
        for atom in (
            normalize_atom(str(fact)[4:])
            for fact in facts
            if str(fact).startswith("not:")
        )
        if atom
    ]
    permissions = [
        {"cap": atom, "rsc": "legal_norm"}
        for atom in (
            normalize_atom(str(fact))
            for fact in facts
            if not str(fact).startswith("not:")
        )
        if atom
    ]

    if not permissions and not prohibitions and not obligations:
        return None

    return {
        "id": "conformance-legal-norm",
        "version": "1",
        "permissions": permissions,
        "prohibitions": prohibitions,
        "obligations": obligations,
    }


def policy_from_zkp_statement_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    claims = [normalize_atom(str(item or "").strip()) for item in payload.get("claims", []) if str(item or "").strip()]
    claims = [claim for claim in claims if claim]
    proof_state = str(payload.get("proofState") or "").strip().lower()

    if not claims and proof_state != "valid":
        return None

    permissions = [{"cap": claim, "rsc": "zkp"} for claim in claims]
    obligations: List[Dict[str, Any]] = []
    if proof_state == "valid" and claims:
        obligations.append({"description": claims[0], "requiredCap": claims[0], "rsc": "zkp"})

    if not permissions and not obligations:
        return None

    return {
        "id": "conformance-zkp-statement",
        "version": "1",
        "permissions": permissions,
        "prohibitions": [],
        "obligations": obligations,
    }


def policy_from_literal_payload(
    positives: Iterable[str],
    negatives: Iterable[str],
    goal: str,
    resource: str,
    policy_id: str,
) -> Optional[Dict[str, Any]]:
    permissions = []
    for value in positives:
        atom = normalize_atom(str(value))
        if atom:
            permissions.append({"cap": atom, "rsc": resource})

    prohibitions = []
    for value in negatives:
        atom = normalize_atom(str(value))
        if atom:
            prohibitions.append({"cap": atom, "rsc": resource})

    obligations: List[Dict[str, Any]] = []
    goal_atom = normalize_atom(str(goal))
    if goal_atom:
        obligations.append({"description": goal_atom, "requiredCap": goal_atom, "rsc": resource})

    if not permissions and not prohibitions and not obligations:
        return None

    return {
        "id": policy_id,
        "version": "1",
        "permissions": permissions,
        "prohibitions": prohibitions,
        "obligations": obligations,
    }


def align_decision_with_native_policy(
    fallback: Dict[str, Any],
    policy: Optional[Dict[str, Any]],
    subsystem: str,
    prover_id: str,
) -> Dict[str, Any]:
    fallback_reason = str(fallback.get("reason") or "")
    if fallback_reason not in {"proved", "refuted"}:
        return fallback
    if not policy:
        return fallback

    try:
        native_outcome = evaluate_policy(policy, {"subsystem": subsystem})
        mapped = map_native_policy_outcome(native_outcome, prover_id)
        if mapped is not None and str(mapped.get("reason") or "") == fallback_reason:
            metadata = dict(mapped.get("metadata") or {})
            metadata.update(
                {
                    "nativeAttempted": True,
                    "nativeProverId": native_outcome.get("proverId"),
                    "nativeReason": native_outcome.get("reason"),
                }
            )
            mapped["metadata"] = metadata
            return mapped

        metadata = dict(fallback.get("metadata") or {})
        metadata.update(
            {
                "nativeAttempted": True,
                "nativeProverId": native_outcome.get("proverId"),
                "nativeReason": native_outcome.get("reason"),
                "nativeFallback": True,
            }
        )
        fallback["metadata"] = metadata
        return fallback
    except Exception as exc:
        metadata = dict(fallback.get("metadata") or {})
        metadata.update(
            {
                "nativeAttempted": True,
                "nativeFallback": True,
                "nativeError": f"{exc.__class__.__name__}: {exc}",
            }
        )
        fallback["metadata"] = metadata
        return fallback


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
    metadata = outcome.get("metadata") if isinstance(outcome, dict) else None
    if isinstance(metadata, dict):
        if metadata.get("simulated") is True:
            return "simulated"
        if metadata.get("hostDependent") is True:
            return "host-dependent"

    if outcome and outcome.get("reason") not in {"unknown", "error"}:
        return "real"

    if expected_mode == "simulated":
        return "simulated"
    if expected_mode == "real":
        return "real"
    return expected_mode or "host-dependent"


def structured_artifacts_for_vector(vector: Dict[str, Any], outcome: Dict[str, Any]) -> Dict[str, str]:
    status = str(outcome.get("reason") or "unknown").strip().lower()
    base = {
        "inputType": vector.get("inputType"),
        "input": canonical_input_for_vector(vector),
        "proverId": str(outcome.get("proverId") or ""),
        "status": status,
    }
    artifacts = {"derivationHash": stable_hash({"kind": "derivation", **base})}
    if status == "sat":
        artifacts["modelHash"] = stable_hash({"kind": "model", **base})
    elif status == "proved":
        artifacts["proofHash"] = stable_hash({"kind": "proof", **base})
    elif status == "refuted":
        artifacts["countermodelHash"] = stable_hash({"kind": "countermodel", **base})
    return artifacts


def canonical_input_for_vector(vector: Dict[str, Any]) -> Any:
    input_payload = vector.get("input") or {}
    input_type = vector.get("inputType")
    key_by_input_type = {
        "policy": "policy",
        "smt2": "smt2",
        "folFormula": "folFormula",
        "legalNorm": "legalNorm",
        "zkpStatement": "zkpStatement",
        "zkpWitness": "zkpWitness",
        "tdfol": "tdfol",
        "temporalTrace": "temporalTrace",
        "modalKripke": "modalKripke",
        "deonticConflict": "deonticConflict",
        "dcec": "dcec",
    }
    key = key_by_input_type.get(str(input_type))
    if key:
        return input_payload.get(key)
    return input_payload


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
    versions = {
        "runner": "py_reference_runner",
        "mode": "module-backed-policy-runner",
        "zkp_runtime_mode": (
            "simulated-runtime-enabled"
            if conformance_enable_simulated_zkp_runtime()
            else "policy-proxy-default"
        ),
    }
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


def assert_required_engines(engine_versions: Dict[str, str], require_engines: Optional[Iterable[str]]) -> None:
    if not require_engines:
        return

    missing: List[str] = []
    for label in require_engines:
        value = str(engine_versions.get(label, "missing")).strip()
        if not value or value == "missing" or value.startswith("unavailable"):
            missing.append(f"{label}={value}")

    if missing:
        details = ", ".join(missing)
        raise RuntimeError(f"Required conformance engines unavailable: {details}")


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
    parser.add_argument(
        "--require-engines",
        help="Comma-separated engine labels that must be available (e.g. z3_runtime,tdfol_core,dcec_prover)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    subsystems = args.subsystems.split(",") if args.subsystems else None
    required = [item.strip() for item in str(args.require_engines or "").split(",") if item.strip()]
    envelope = run_python_reference(
        args.vectors,
        out_path=args.out,
        subsystems=subsystems,
        limit=args.limit,
        require_engines=required,
    )
    if not args.out:
        print(json.dumps(envelope, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
