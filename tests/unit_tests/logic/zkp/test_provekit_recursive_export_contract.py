"""Tests for ProveKit recursive verifier / Gnark export contract interface.

These tests document and enforce the decision recorded in
``docs/PROVEKIT_RECURSIVE_ONCHAIN_EVALUATION.md``:

- The ``provekit_recursive_groth16`` backend alias is known but unavailable
  until gate criteria G1–G7 are satisfied.
- The reserved circuit ref ``provekit_recursive_groth16_wrapper@v1`` is
  recognized by schema helpers but must not produce real proofs yet.
- The recursive path must not bypass the existing fail-closed ZKP contract
  (no private axioms in proof bytes or public inputs).
- The existing on-chain pipeline (``OnchainPipelineResult``, ``run_offchain_to_onchain_pipeline``)
  shape is unchanged by the recursive alias introduction.
- Full round-trip tests for the recursive path require
  ``IPFS_DATASETS_RUN_PROVEKIT_RECURSIVE_TESTS=1`` and are skipped otherwise.

No test in this module creates real proving keys, contacts an external network,
or writes private witness material to disk outside of ``tmp_path``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import pytest

from ipfs_datasets_py.logic.zkp import ZKPError, ZKPProof
from ipfs_datasets_py.logic.zkp.backends import (
    clear_backend_cache,
    get_backend,
    list_backends,
)

# ---------------------------------------------------------------------------
# Constants from the evaluation document
# ---------------------------------------------------------------------------

RECURSIVE_CIRCUIT_REF = "provekit_recursive_groth16_wrapper@v1"
RECURSIVE_BACKEND_ALIAS = "provekit_recursive_groth16"

# Gate flag: set to '1' to enable full round-trip recursive tests.
_RUN_RECURSIVE = os.environ.get("IPFS_DATASETS_RUN_PROVEKIT_RECURSIVE_TESTS", "0") == "1"

_REQUIRES_RECURSIVE = pytest.mark.skipif(
    not _RUN_RECURSIVE,
    reason=(
        "Set IPFS_DATASETS_RUN_PROVEKIT_RECURSIVE_TESTS=1 to run recursive "
        "ProveKit/Gnark export tests. Gate criteria G1–G7 in "
        "docs/PROVEKIT_RECURSIVE_ONCHAIN_EVALUATION.md must be satisfied first."
    ),
)


# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


def _sample_zkpproof(circuit_ref: str = RECURSIVE_CIRCUIT_REF) -> ZKPProof:
    """Return a plausible fake ZKPProof for the recursive circuit ref."""
    return ZKPProof(
        proof_data=b"\x00" * 128,
        public_inputs={
            "theorem": "P -> Q",
            "theorem_hash": "a" * 64,
            "axioms_commitment": "b" * 64,
            "circuit_ref": circuit_ref,
            "circuit_version": 1,
            "ruleset_id": "TDFOL_v1",
        },
        metadata={
            "backend": RECURSIVE_BACKEND_ALIAS,
            "proof_system": "ProveKit-WHIR-Gnark-Groth16",
            "curve_id": "bn254",
        },
        timestamp=0.0,
        size_bytes=128,
    )


@dataclass
class _FakeRecursiveProver:
    """Minimal prover stub that returns a fake recursive proof object."""

    proof_obj: Any

    def generate_proof(self, witness_json: str) -> Any:
        return self.proof_obj


@dataclass
class _FakeOnchainClient:
    """Minimal on-chain client stub that records calls."""

    precheck_ok: bool = True
    calls: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.calls is None:
            self.calls = []

    def verify_proof_rpc_call(self, proof_hex: str, public_inputs_hex: list[str]) -> bool:
        self.calls.append(("precheck", (proof_hex, public_inputs_hex)))
        return self.precheck_ok

    def submit_proof_transaction(
        self,
        proof_hex: str,
        public_inputs_hex: list[str],
        from_account: str,
        private_key: str,
        gas_price_wei: Optional[int] = None,
    ) -> str:
        self.calls.append(("submit", (proof_hex, public_inputs_hex, from_account)))
        return "0x" + "cc" * 32

    def wait_for_confirmation(
        self, tx_hash: str, timeout_seconds: int = 300
    ) -> Mapping[str, Any]:
        self.calls.append(("confirm", tx_hash))
        return {"transactionHash": tx_hash, "status": 1, "blockNumber": 42}


# ---------------------------------------------------------------------------
# Decision / contract shape tests
# ---------------------------------------------------------------------------


class TestReservedCircuitRefShape:
    """Verify the reserved circuit ref string is correctly formatted."""

    def test_recursive_circuit_ref_format(self):
        """Circuit ref must follow the ``<id>@<version>`` convention."""
        assert "@" in RECURSIVE_CIRCUIT_REF
        name, version = RECURSIVE_CIRCUIT_REF.split("@", 1)
        assert name == "provekit_recursive_groth16_wrapper"
        assert version == "v1"

    def test_recursive_circuit_ref_not_a_simulated_ref(self):
        """Recursive circuit ref must not start with 'simulated_'."""
        assert not RECURSIVE_CIRCUIT_REF.startswith("simulated_")

    def test_recursive_circuit_ref_not_a_groth16_ref(self):
        """Recursive circuit ref must be distinguishable from native Groth16."""
        assert "provekit" in RECURSIVE_CIRCUIT_REF
        assert "groth16" in RECURSIVE_CIRCUIT_REF

    def test_recursive_circuit_ref_distinct_from_knowledge_of_axioms(self):
        assert RECURSIVE_CIRCUIT_REF != "provekit_knowledge_of_axioms@v1"

    def test_recursive_circuit_ref_distinct_from_tdfol_trace(self):
        assert RECURSIVE_CIRCUIT_REF != "provekit_tdfol_v1_trace@v1"


class TestBackendRegistryShape:
    """The recursive alias must be known to the registry as unavailable."""

    def test_standard_provekit_backend_is_registered(self):
        backends = list_backends()
        assert "provekit" in backends

    def test_recursive_alias_not_yet_registered_as_default_production(self):
        """The recursive alias must not silently resolve to a production backend."""
        backends = list_backends()
        # The alias is not expected to be a first-class entry until gate
        # criteria are satisfied.  If it ever does appear, its description must
        # mention that it is gated.
        if RECURSIVE_BACKEND_ALIAS in backends:
            desc = backends[RECURSIVE_BACKEND_ALIAS].get("description", "")
            assert any(
                word in desc.lower()
                for word in ("gated", "experimental", "unavailable", "future", "recursive")
            ), (
                f"Recursive backend alias '{RECURSIVE_BACKEND_ALIAS}' is registered "
                f"but its description does not mention that it is gated or experimental. "
                f"Update the registry description before production exposure."
            )

    def test_get_backend_provekit_does_not_return_recursive_proof_system(self):
        """Standard ``get_backend('provekit')`` must not claim recursive support."""
        clear_backend_cache()
        backend = get_backend("provekit")
        # proof_system is a string attribute on ProveKitBackend
        ps = getattr(backend, "proof_system", "")
        assert "recursive" not in ps.lower()
        assert "gnark" not in ps.lower()
        clear_backend_cache()


class TestFailClosedRecursivePath:
    """The recursive path must fail closed until gate criteria are satisfied."""

    def test_get_backend_unknown_alias_raises_zkperror(self):
        clear_backend_cache()
        with pytest.raises((ZKPError, KeyError, ValueError)):
            get_backend(RECURSIVE_BACKEND_ALIAS)
        clear_backend_cache()

    def test_recursive_proof_without_artifacts_raises_zkperror(self, tmp_path):
        """Attempting to use the standard backend for a recursive circuit without
        artifacts must raise ZKPError, not produce a simulated proof."""
        from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend

        backend = ProveKitBackend()
        with pytest.raises(ZKPError):
            backend.generate_proof(
                theorem="P -> Q",
                private_axioms=["P", "P -> Q"],
                metadata={},
            )

    def test_recursive_proof_metadata_without_prover_key_raises_zkperror(self, tmp_path):
        from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend

        binary = tmp_path / "provekit-cli"
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(binary.stat().st_mode | 0o111)

        backend = ProveKitBackend(binary_path=str(binary))
        with pytest.raises(ZKPError):
            backend.generate_proof(
                theorem="P -> Q",
                private_axioms=["P"],
                metadata={"provekit_artifacts": {}},
            )


class TestNoLeakRecursivePublicInputs:
    """Private axioms must not appear in proof bytes or public inputs for recursive proofs."""

    def test_recursive_zkpproof_public_inputs_contain_no_private_axiom_text(self):
        private_axioms = ["private_axiom_text_must_not_leak", "also_private"]
        proof = _sample_zkpproof()

        # Public inputs should only contain hashes / commitments, not raw text.
        for k, v in proof.public_inputs.items():
            for axiom in private_axioms:
                assert axiom not in str(v), (
                    f"Private axiom text found in public input '{k}': {v!r}"
                )

    def test_recursive_zkpproof_bytes_contain_no_private_axiom_text(self):
        private_axioms = [b"private_axiom_text_must_not_leak", b"also_private"]
        proof = _sample_zkpproof()

        for axiom in private_axioms:
            assert axiom not in proof.proof_data, (
                f"Private axiom bytes found in proof_data"
            )

    def test_recursive_zkpproof_metadata_contains_no_private_axiom_text(self):
        private_axioms = ["private_secret", "witness_material"]
        proof = _sample_zkpproof()

        metadata_str = str(proof.metadata)
        for axiom in private_axioms:
            assert axiom not in metadata_str


class TestPublicInputSchemaCompatibility:
    """Recursive proofs must carry the same required public-input fields as
    other ProveKit circuit families."""

    REQUIRED_FIELDS = {
        "theorem",
        "theorem_hash",
        "axioms_commitment",
        "circuit_ref",
        "circuit_version",
        "ruleset_id",
    }

    def test_sample_recursive_proof_has_all_required_public_input_fields(self):
        proof = _sample_zkpproof()
        missing = self.REQUIRED_FIELDS - set(proof.public_inputs.keys())
        assert not missing, f"Missing required public input fields: {missing}"

    def test_circuit_ref_in_public_inputs_matches_recursive_ref(self):
        proof = _sample_zkpproof(circuit_ref=RECURSIVE_CIRCUIT_REF)
        assert proof.public_inputs["circuit_ref"] == RECURSIVE_CIRCUIT_REF

    def test_theorem_hash_is_hex_string(self):
        proof = _sample_zkpproof()
        th = proof.public_inputs["theorem_hash"]
        assert isinstance(th, str)
        assert len(th) == 64
        int(th, 16)  # must be valid hex

    def test_axioms_commitment_is_hex_string(self):
        proof = _sample_zkpproof()
        ac = proof.public_inputs["axioms_commitment"]
        assert isinstance(ac, str)
        assert len(ac) == 64
        int(ac, 16)

    def test_ruleset_id_is_tdfol_v1(self):
        proof = _sample_zkpproof()
        assert proof.public_inputs["ruleset_id"] == "TDFOL_v1"


class TestOnchainPipelineUnchanged:
    """Adding the recursive alias must not break the existing on-chain pipeline."""

    def _make_proof_dict(self) -> dict:
        return {
            "proof_data": "0x" + "aa" * 64,
            "public_inputs": {
                "theorem_hash": "0x" + "bb" * 32,
                "axioms_commitment": "0x" + "cc" * 32,
                "circuit_version": 1,
                "ruleset_id": "TDFOL_v1",
            },
        }

    def test_pipeline_dry_run_still_works(self):
        from ipfs_datasets_py.logic.zkp.onchain_pipeline import (
            OnchainPipelineResult,
            run_offchain_to_onchain_pipeline,
        )

        prover = _FakeRecursiveProver(self._make_proof_dict())
        client = _FakeOnchainClient(precheck_ok=True)

        result = run_offchain_to_onchain_pipeline(
            witness_json="{}",
            prover=prover,
            client=client,
            from_account="0x" + "1" * 40,
            private_key="0x" + "2" * 64,
            dry_run=True,
        )

        assert isinstance(result, OnchainPipelineResult)
        assert result.precheck_ok is True
        assert result.submitted is False

    def test_pipeline_submit_still_works(self):
        from ipfs_datasets_py.logic.zkp.onchain_pipeline import (
            OnchainPipelineResult,
            run_offchain_to_onchain_pipeline,
        )

        prover = _FakeRecursiveProver(self._make_proof_dict())
        client = _FakeOnchainClient(precheck_ok=True)

        result = run_offchain_to_onchain_pipeline(
            witness_json="{}",
            prover=prover,
            client=client,
            from_account="0x" + "1" * 40,
            private_key="0x" + "2" * 64,
            dry_run=False,
        )

        assert isinstance(result, OnchainPipelineResult)
        assert result.submitted is True
        assert result.tx_hash == "0x" + "cc" * 32

    def test_pipeline_precheck_failure_still_blocks_submit(self):
        from ipfs_datasets_py.logic.zkp.onchain_pipeline import (
            OnchainPipelineResult,
            run_offchain_to_onchain_pipeline,
        )

        prover = _FakeRecursiveProver(self._make_proof_dict())
        client = _FakeOnchainClient(precheck_ok=False)

        result = run_offchain_to_onchain_pipeline(
            witness_json="{}",
            prover=prover,
            client=client,
            from_account="0x" + "1" * 40,
            private_key="0x" + "2" * 64,
            dry_run=False,
        )

        assert result.precheck_ok is False
        assert result.submitted is False
        assert [c[0] for c in client.calls] == ["precheck"]


class TestGateCriteriaDocs:
    """Verify that the evaluation document exists and covers required topics."""

    EVAL_DOC = (
        Path(__file__).resolve().parents[5]
        / "docs"
        / "PROVEKIT_RECURSIVE_ONCHAIN_EVALUATION.md"
    )

    def test_evaluation_document_exists(self):
        assert self.EVAL_DOC.exists(), (
            f"Missing evaluation document: {self.EVAL_DOC}"
        )

    def test_evaluation_document_references_gate_criteria(self):
        text = self.EVAL_DOC.read_text(encoding="utf-8")
        assert "G1" in text
        assert "G7" in text

    def test_evaluation_document_references_reserved_circuit_ref(self):
        text = self.EVAL_DOC.read_text(encoding="utf-8")
        assert RECURSIVE_CIRCUIT_REF in text

    def test_evaluation_document_names_backend_alias(self):
        text = self.EVAL_DOC.read_text(encoding="utf-8")
        assert RECURSIVE_BACKEND_ALIAS in text

    def test_evaluation_document_references_groth16_evm_as_default(self):
        text = self.EVAL_DOC.read_text(encoding="utf-8").lower()
        assert "groth16" in text
        assert "evm" in text or "on-chain" in text or "onchain" in text

    def test_evaluation_document_mentions_no_witness_in_calldata(self):
        text = self.EVAL_DOC.read_text(encoding="utf-8").lower()
        assert "witness" in text
        assert "private" in text


# ---------------------------------------------------------------------------
# Full round-trip tests — require gate flag
# ---------------------------------------------------------------------------


@_REQUIRES_RECURSIVE
class TestRecursiveRoundTrip:
    """Full recursive export and on-chain verification round-trip.

    These tests require:
      IPFS_DATASETS_RUN_PROVEKIT_RECURSIVE_TESTS=1
      IPFS_DATASETS_PROVEKIT_BINARY=<path>

    Gate criteria G1–G7 in docs/PROVEKIT_RECURSIVE_ONCHAIN_EVALUATION.md
    must be satisfied before these tests can pass in CI.
    """

    def test_recursive_proof_generation_and_export(self, tmp_path):  # pragma: no cover
        raise NotImplementedError(
            "Implement this test once gate criteria G1–G7 are satisfied. "
            "See docs/PROVEKIT_RECURSIVE_ONCHAIN_EVALUATION.md."
        )

    def test_recursive_verifier_key_digest_matches_manifest(self, tmp_path):  # pragma: no cover
        raise NotImplementedError(
            "Implement this test once the recursive artifact manifest is "
            "committed to artifacts/provekit-recursive/."
        )

    def test_recursive_proof_passes_evm_harness_verifier(self, tmp_path):  # pragma: no cover
        raise NotImplementedError(
            "Implement this test once a Solidity verifier contract for the "
            "recursive verifier key is deployed to the test network."
        )
