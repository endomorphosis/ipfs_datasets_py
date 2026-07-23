"""No-LLM contract tests for deterministic legal parsing."""

import sys
import types

from ipfs_datasets_py.logic.deontic import DeonticConverter
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_proof_ready_clause_does_not_call_llm_router(monkeypatch) -> None:
    """Clean deterministic clauses must parse and formalize without model calls."""

    router = types.ModuleType("ipfs_datasets_py.llm_router")

    def _fail(*args, **kwargs):
        raise AssertionError("llm_router must not be called by deterministic parser")

    router.generate_text = _fail
    router.get_default_router = _fail
    monkeypatch.setitem(sys.modules, "ipfs_datasets_py.llm_router", router)

    elements = extract_normative_elements("The tenant must pay rent.")
    converter = DeonticConverter(use_ml=False, enable_monitoring=False)
    result = converter.convert("The tenant must pay rent.")

    assert len(elements) == 1
    assert elements[0]["promotable_to_theorem"] is True
    assert elements[0]["llm_repair"]["required"] is False
    assert result.success
    assert result.metadata["deterministic_parser"]["proof_ready"] is True
    assert result.output is not None
    assert result.output.proposition == "∀x (Tenant(x) → PayRent(x))"

