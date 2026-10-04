#!/usr/bin/env python3

import logging
import os

from ipfs_datasets_py.logic.integration.deontic_logic_core import (
    DeonticFormula,
    DeonticOperator,
    LegalAgent,
)
from ipfs_datasets_py.logic.integration.proof_execution_engine import ProofExecutionEngine


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    timeout = int(os.environ.get("IPFS_DATASETS_PY_PROOF_TIMEOUT", "60"))
    require_coq = _truthy(os.environ.get("IPFS_DATASETS_PY_REQUIRE_COQ"))

    engine = ProofExecutionEngine(timeout=timeout, default_prover="coq")

    if not engine.available_provers.get("coq", False):
        msg = (
            "SKIP: Coq is not installed (coqc not found on PATH). "
            "Install Coq to enable symbolic proof execution via Coq."
        )
        print(msg)
        return 1 if require_coq else 0

    formula = DeonticFormula(
        operator=DeonticOperator.OBLIGATION,
        proposition="provide written notice before termination",
        agent=LegalAgent("party", "Contract Party", "person"),
        confidence=0.9,
        source_text="Party must provide written notice before termination.",
    )

    print("Running Coq proof execution for one deontic formula...")
    result = engine.prove_deontic_formula(formula)
    print(f"Prover: {result.prover}")
    print(f"Status: {result.status.value}")
    if result.errors:
        print("Errors:")
        for err in result.errors:
            print(f"- {err}")
    if result.warnings:
        print("Warnings:")
        for w in result.warnings:
            print(f"- {w}")
    if result.proof_output:
        print("Proof output (truncated):")
        print(result.proof_output[:2000])

    if result.status.value in {"error", "timeout"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
