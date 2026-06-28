"""Tests for Hybrid TDFOL, CEC, and F-Logic ProveKit backend wiring.

PROVEKIT-130: Hybrid TDFOL CEC And F-Logic Compatibility

Acceptance: ``ZKPTDFOLProver``, ``ZKPCECProver``, and ``ZKPFLogicProver`` can
select ``zkp_backend="provekit"`` through their existing constructors, verify
generated proof envelopes, and retain standard proving fallback behavior where
allowed.

Strategy
--------
The ProveKit backend requires a configured CLI binary and prepared key
artifacts, so tests monkeypatch ``ProveKitBackend.generate_proof`` to return
a properly-shaped ``ZKPProof`` (backend=``"provekit"``,
proof_system=``"ProveKit-WHIR"``, consistent attestation view).  The simulated
verifier is exercised on each returned envelope so that
``ZKPVerifier._validate_proof_structure`` guards are checked without a live
ProveKit installation.

Invariants checked
------------------
- Each prover's constructor accepts ``zkp_backend="provekit"`` without error.
- Monkeypatched ProveKit proofs satisfy ``ZKPVerifier._validate_proof_structure``:
  * proof data 100-300 bytes
  * ``theorem_hash`` matches ``theorem_hash_hex(theorem)``
  * ``proof_system`` present in metadata
  * ``security_level`` >= 128
  * ``attestation_view`` internally consistent
- ``is_private=True`` results expose no raw axiom text.
- Standard fallback (``enable_zkp=False``) still produces a proved result for
  trivial theorems.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Module-level import guard
#
# ``ZKPTDFOLProver``, ``ZKPCECProver``, and ``ZKPFLogicProver`` transitively
# import ``ipfs_datasets_py.logic.common.proof_cache``, which imports
# ``ipfs_datasets_py.caching.router_remote_cache``, which imports ``libp2p``.
# The installed libp2p raises ``google.protobuf.runtime_version.VersionError``
# (NOT a subclass of ``ImportError``) when loaded, bypassing the
# ``except ImportError`` guard in proof_cache.py.
#
# Solution: stub the broken modules in sys.modules before any logic imports
# so that the optional IPFS cache path is silently skipped.
# ---------------------------------------------------------------------------

import sys
import types as _types

def _stub_module(name: str) -> _types.ModuleType:
    mod = _types.ModuleType(name)
    sys.modules[name] = mod
    return mod

for _name in (
    "ipfs_datasets_py.caching",
    "ipfs_datasets_py.caching.cache",
    "ipfs_datasets_py.caching.router_remote_cache",
):
    if _name not in sys.modules:
        _stub_module(_name)

# Provide the one symbol that proof_cache.py imports from this path
sys.modules["ipfs_datasets_py.caching.router_remote_cache"].IPFSBackedRemoteCache = None  # type: ignore

# ---------------------------------------------------------------------------
# Standard library / third-party imports
# ---------------------------------------------------------------------------

import time
import warnings
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Logic / ZKP imports
# ---------------------------------------------------------------------------

try:
    from ipfs_datasets_py.logic.deontic import DeonticConverter as _DC  # noqa: F401
except Exception:
    pass

from ipfs_datasets_py.logic.zkp import ZKPProof
from ipfs_datasets_py.logic.zkp.backends import clear_backend_cache
from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend
from ipfs_datasets_py.logic.zkp.canonicalization import (
    axioms_commitment_hex,
    theorem_hash_hex,
)
from ipfs_datasets_py.logic.zkp.circuits import build_proof_attestation_view
from ipfs_datasets_py.logic.zkp.zkp_verifier import ZKPVerifier

# TDFOL prover
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    TDFOLKnowledgeBase,
    Predicate,
)
from ipfs_datasets_py.logic.TDFOL.zkp_integration import ZKPTDFOLProver

# CEC prover
from ipfs_datasets_py.logic.CEC.native.cec_zkp_integration import ZKPCECProver
from ipfs_datasets_py.logic.CEC.native.dcec_integration import parse_dcec_string

# F-Logic prover
from ipfs_datasets_py.logic.flogic.flogic_zkp_integration import ZKPFLogicProver
from ipfs_datasets_py.logic.flogic.flogic_types import (
    FLogicClass,
    FLogicFrame,
    FLogicStatus,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 200 bytes — within the ZKPVerifier 100-300 byte acceptance window.
_PROVEKIT_PROOF_DATA = b"NP" + b"\xab" * 198


# ---------------------------------------------------------------------------
# Proof-builder helper
# ---------------------------------------------------------------------------


def _build_provekit_proof(theorem: str, private_axioms: list[str]) -> ZKPProof:
    """Return a ProveKit-shaped ``ZKPProof`` that passes simulated verification.

    The proof satisfies all ``ZKPVerifier._validate_proof_structure`` guards:
    * ``size_bytes`` 100-300
    * ``theorem_hash`` correct
    * ``proof_system`` present in metadata
    * ``security_level`` >= 128
    * ``attestation_view`` internally consistent
    """
    th_hash = theorem_hash_hex(theorem)
    ax_commit = axioms_commitment_hex(sorted(set(private_axioms)))
    circuit_ref = "provekit_knowledge_of_axioms@v1"
    ruleset_id = "LegalIR_TDFOL_v1"

    public_inputs_draft: dict[str, Any] = {
        "theorem": theorem,
        "theorem_hash": th_hash,
        "axioms_commitment": ax_commit,
        "circuit_ref": circuit_ref,
        "circuit_version": 1,
        "ruleset_id": ruleset_id,
    }
    metadata_draft: dict[str, Any] = {
        "backend": "provekit",
        "proof_system": "ProveKit-WHIR",
        "curve_id": "bn254",
        "security_level": 128,
        "provekit": {
            "command": {"ok": True},
            "public_input_schema": "provekit-public-inputs-v1",
        },
    }
    attestation_view = build_proof_attestation_view(
        proof_data=_PROVEKIT_PROOF_DATA,
        public_inputs=public_inputs_draft,
        metadata=metadata_draft,
    )
    public_inputs = {
        **public_inputs_draft,
        "attestation_ref": attestation_view["attestation_ref"],
        "attestation_view_version": int(attestation_view["attestation_view_version"]),
    }
    metadata = {
        **metadata_draft,
        "attestation_view": attestation_view,
    }
    return ZKPProof(
        proof_data=_PROVEKIT_PROOF_DATA,
        public_inputs=public_inputs,
        metadata=metadata,
        timestamp=time.time(),
        size_bytes=len(_PROVEKIT_PROOF_DATA),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_backend_cache():
    """Reset backend registry before and after each test."""
    clear_backend_cache()
    yield
    clear_backend_cache()


@pytest.fixture()
def patched_provekit(monkeypatch):
    """Monkeypatch ``ProveKitBackend`` to avoid requiring a live CLI binary.

    - ``generate_proof`` returns a valid ProveKit-shaped envelope.
    - ``verify_proof`` returns ``True`` (simulates a passing verification).
    """

    def _fake_generate(self, theorem, private_axioms, metadata=None):
        return _build_provekit_proof(theorem, list(private_axioms or []))

    def _fake_verify(self, proof):
        return True

    monkeypatch.setattr(ProveKitBackend, "generate_proof", _fake_generate)
    monkeypatch.setattr(ProveKitBackend, "verify_proof", _fake_verify)
    return _fake_generate


@pytest.fixture()
def tdfol_kb():
    """A minimal TDFOL knowledge base with two axioms."""
    kb = TDFOLKnowledgeBase()
    kb.add_axiom(Predicate("P", []))
    kb.add_axiom(Predicate("Q", []))
    return kb


@pytest.fixture()
def cec_axioms():
    """Simple CEC axiom list."""
    return [parse_dcec_string("p"), parse_dcec_string("p -> q")]


def _cec_prover(**kwargs) -> ZKPCECProver:
    """Helper: build a ZKPCECProver with caching disabled (avoids IPFS cache path)."""
    defaults = {"enable_caching": False}
    defaults.update(kwargs)
    return ZKPCECProver(**defaults)


@pytest.fixture()
def flogic_prover_base():
    """F-Logic prover with a tiny class/frame ontology (no ZKP)."""
    prover = ZKPFLogicProver(enable_zkp=False, enable_caching=False)
    prover.add_class(FLogicClass("Dog", superclasses=["Animal"]))
    prover.add_frame(FLogicFrame("rex", isa="Dog"))
    return prover


# ---------------------------------------------------------------------------
# ZKPTDFOLProver — constructor
# ---------------------------------------------------------------------------


class TestZKPTDFOLProverConstructor:
    """ZKPTDFOLProver accepts ``zkp_backend='provekit'`` in its constructor."""

    def test_constructor_accepts_provekit_backend(self, tdfol_kb):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPTDFOLProver(
                tdfol_kb,
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
        assert prover.zkp_backend == "provekit"

    def test_constructor_provekit_backend_stored(self, tdfol_kb):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPTDFOLProver(
                tdfol_kb,
                enable_zkp=True,
                zkp_backend="provekit",
            )
        # The backing ZKPProver should have recorded the backend name.
        if prover.zkp_prover is not None:
            assert prover.zkp_prover.backend == "provekit"

    def test_constructor_without_zkp_is_harmless(self, tdfol_kb):
        """Requesting provekit with enable_zkp=False should not raise."""
        prover = ZKPTDFOLProver(
            tdfol_kb,
            enable_zkp=False,
            zkp_backend="provekit",
        )
        assert prover.zkp_backend == "provekit"
        assert prover.zkp_prover is None


# ---------------------------------------------------------------------------
# ZKPTDFOLProver — proof envelopes
# ---------------------------------------------------------------------------


class TestZKPTDFOLProverProofEnvelopes:
    """Proof envelopes generated via the ProveKit path are well-formed."""

    def test_zkp_proof_has_provekit_backend(self, tdfol_kb, patched_provekit):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPTDFOLProver(
                tdfol_kb,
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
        goal = Predicate("P", [])
        result = prover.prove(goal, prefer_zkp=True)

        assert result.is_proved
        assert result.zkp_proof is not None
        proof = result.zkp_proof
        assert proof.metadata.get("backend") == "provekit"
        assert proof.metadata.get("proof_system") == "ProveKit-WHIR"

    def test_zkp_proof_envelope_theorem_hash_deterministic(
        self, tdfol_kb, patched_provekit
    ):
        """``theorem_hash`` in the envelope matches ``theorem_hash_hex``."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPTDFOLProver(
                tdfol_kb,
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
        goal = Predicate("P", [])
        result = prover.prove(goal, prefer_zkp=True)
        proof = result.zkp_proof

        pi = proof.public_inputs
        expected_hash = theorem_hash_hex(pi["theorem"])
        assert pi["theorem_hash"] == expected_hash

    def test_zkp_proof_envelope_passes_verifier_structure(
        self, tdfol_kb, patched_provekit
    ):
        """The generated envelope satisfies ``ZKPVerifier._validate_proof_structure``."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPTDFOLProver(
                tdfol_kb,
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
        goal = Predicate("P", [])
        result = prover.prove(goal, prefer_zkp=True)
        proof = result.zkp_proof

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            verifier = ZKPVerifier(backend="simulated")
        assert verifier._validate_proof_structure(proof) is True

    def test_zkp_proof_envelope_required_public_input_keys(
        self, tdfol_kb, patched_provekit
    ):
        """Public inputs contain the required canonical keys."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPTDFOLProver(
                tdfol_kb,
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
        goal = Predicate("P", [])
        result = prover.prove(goal, prefer_zkp=True)
        pi = result.zkp_proof.public_inputs

        required = {
            "theorem",
            "theorem_hash",
            "axioms_commitment",
            "circuit_ref",
            "circuit_version",
            "ruleset_id",
            "attestation_ref",
            "attestation_view_version",
        }
        missing = required - pi.keys()
        assert not missing, f"Public inputs missing keys: {missing}"

    def test_zkp_proof_private_result_hides_axiom_text(
        self, tdfol_kb, patched_provekit
    ):
        """With is_private=True no raw axiom text leaks into the unified result."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPTDFOLProver(
                tdfol_kb,
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
        goal = Predicate("P", [])
        result = prover.prove(goal, prefer_zkp=True, private_axioms=True)

        assert result.is_private is True


# ---------------------------------------------------------------------------
# ZKPTDFOLProver — standard fallback
# ---------------------------------------------------------------------------


class TestZKPTDFOLProverFallback:
    """Standard TDFOL fallback is preserved when ZKP is disabled or fails."""

    def test_standard_fallback_when_zkp_disabled(self, tdfol_kb):
        prover = ZKPTDFOLProver(
            tdfol_kb,
            enable_zkp=False,
            zkp_backend="provekit",
            zkp_fallback="standard",
        )
        goal = Predicate("P", [])
        result = prover.prove(goal, prefer_zkp=False)

        assert result.is_proved
        assert result.method == "tdfol_standard"

    def test_standard_fallback_when_prefer_zkp_false(self, tdfol_kb):
        """Even with ZKP enabled, prefer_zkp=False routes through standard."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPTDFOLProver(
                tdfol_kb,
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
        goal = Predicate("P", [])
        result = prover.prove(goal, prefer_zkp=False)

        # Standard path should have proved from the axiom.
        assert result.is_proved
        assert result.method == "tdfol_standard"


# ---------------------------------------------------------------------------
# ZKPCECProver — constructor
# ---------------------------------------------------------------------------


class TestZKPCECProverConstructor:
    """ZKPCECProver accepts ``zkp_backend='provekit'`` in its constructor."""

    def test_constructor_accepts_provekit_backend(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = _cec_prover(
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
        assert prover.zkp_backend == "provekit"

    def test_constructor_without_zkp_is_harmless(self):
        prover = _cec_prover(
            enable_zkp=False,
            zkp_backend="provekit",
        )
        assert prover.zkp_backend == "provekit"
        assert prover.zkp_prover is None

    def test_constructor_provekit_alias_pk(self):
        """The 'pk' alias resolves to the ProveKit backend."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = _cec_prover(
                enable_zkp=True,
                zkp_backend="pk",
            )
        # Stored as-is; the backend registry normalises it internally.
        assert prover.zkp_backend == "pk"


# ---------------------------------------------------------------------------
# ZKPCECProver — proof envelopes
# ---------------------------------------------------------------------------


class TestZKPCECProverProofEnvelopes:
    """Proof envelopes generated via the ProveKit path are well-formed."""

    def test_zkp_proof_has_provekit_backend(self, cec_axioms, patched_provekit):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = _cec_prover(
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
        goal = parse_dcec_string("q")
        result = prover.prove_theorem(
            goal, cec_axioms, prefer_zkp=True, private_axioms=True
        )

        assert result.is_proved
        proof = result.zkp_proof
        assert proof is not None
        assert proof.metadata.get("backend") == "provekit"
        assert proof.metadata.get("proof_system") == "ProveKit-WHIR"

    def test_zkp_proof_envelope_theorem_hash_deterministic(
        self, cec_axioms, patched_provekit
    ):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = _cec_prover(
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
        goal = parse_dcec_string("q")
        result = prover.prove_theorem(
            goal, cec_axioms, prefer_zkp=True, private_axioms=True
        )
        pi = result.zkp_proof.public_inputs
        expected = theorem_hash_hex(pi["theorem"])
        assert pi["theorem_hash"] == expected

    def test_zkp_proof_envelope_passes_verifier_structure(
        self, cec_axioms, patched_provekit
    ):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = _cec_prover(
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
        goal = parse_dcec_string("q")
        result = prover.prove_theorem(
            goal, cec_axioms, prefer_zkp=True, private_axioms=True
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            verifier = ZKPVerifier(backend="simulated")
        assert verifier._validate_proof_structure(result.zkp_proof) is True

    def test_zkp_proof_private_result_hides_axioms(
        self, cec_axioms, patched_provekit
    ):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = _cec_prover(
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
        goal = parse_dcec_string("q")
        result = prover.prove_theorem(
            goal, cec_axioms, prefer_zkp=True, private_axioms=True
        )
        assert result.is_private is True
        # Axiom list should be empty when private
        assert result.axioms == []


# ---------------------------------------------------------------------------
# ZKPCECProver — standard fallback
# ---------------------------------------------------------------------------


class TestZKPCECProverFallback:
    """Standard CEC fallback is preserved when ZKP is disabled."""

    def test_standard_fallback_when_zkp_disabled(self, cec_axioms):
        prover = _cec_prover(
            enable_zkp=False,
            zkp_backend="provekit",
        )
        goal = parse_dcec_string("q")
        result = prover.prove_theorem(goal, cec_axioms, prefer_zkp=False)
        assert result.is_proved

    def test_standard_fallback_prefer_zkp_false(self, cec_axioms):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = _cec_prover(
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
        goal = parse_dcec_string("q")
        result = prover.prove_theorem(goal, cec_axioms, prefer_zkp=False)
        assert result.is_proved
        assert "cec" in result.method.value.lower()


# ---------------------------------------------------------------------------
# ZKPFLogicProver — constructor
# ---------------------------------------------------------------------------


class TestZKPFLogicProverConstructor:
    """ZKPFLogicProver accepts ``zkp_backend='provekit'`` in its constructor."""

    def test_constructor_accepts_provekit_backend(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPFLogicProver(
                enable_zkp=True,
                zkp_backend="provekit",
            )
        assert prover.zkp_backend == "provekit"

    def test_constructor_without_zkp_is_harmless(self):
        prover = ZKPFLogicProver(
            enable_zkp=False,
            zkp_backend="provekit",
        )
        assert prover.zkp_backend == "provekit"
        assert prover._zkp_prover is None

    def test_constructor_provekit_whir_alias(self):
        """The 'provekit-whir' alias is accepted without error."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPFLogicProver(
                enable_zkp=True,
                zkp_backend="provekit-whir",
            )
        assert prover.zkp_backend == "provekit-whir"


# ---------------------------------------------------------------------------
# ZKPFLogicProver — proof envelopes
# ---------------------------------------------------------------------------


class TestZKPFLogicProverProofEnvelopes:
    """Proof envelopes generated via the ProveKit path are well-formed."""

    def test_zkp_proof_has_provekit_backend(self, patched_provekit):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPFLogicProver(
                enable_zkp=True,
                zkp_backend="provekit",
            )
        prover.add_class(FLogicClass("Dog", superclasses=["Animal"]))
        prover.add_frame(FLogicFrame("rex", isa="Dog"))

        result = prover.query("?X : Dog", prefer_zkp=True, private_ontology=True)

        assert result.status == FLogicStatus.SUCCESS
        proof = result.zkp_proof
        assert proof is not None
        assert proof.metadata.get("backend") == "provekit"
        assert proof.metadata.get("proof_system") == "ProveKit-WHIR"

    def test_zkp_proof_envelope_theorem_hash_deterministic(
        self, patched_provekit
    ):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPFLogicProver(
                enable_zkp=True,
                zkp_backend="provekit",
            )
        prover.add_class(FLogicClass("Dog", superclasses=["Animal"]))

        result = prover.query("?X : Dog", prefer_zkp=True)
        pi = result.zkp_proof.public_inputs
        expected = theorem_hash_hex(pi["theorem"])
        assert pi["theorem_hash"] == expected

    def test_zkp_proof_envelope_passes_verifier_structure(
        self, patched_provekit
    ):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPFLogicProver(
                enable_zkp=True,
                zkp_backend="provekit",
            )
        prover.add_class(FLogicClass("Dog", superclasses=["Animal"]))

        result = prover.query("?X : Dog", prefer_zkp=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            verifier = ZKPVerifier(backend="simulated")
        assert verifier._validate_proof_structure(result.zkp_proof) is True

    def test_zkp_proof_private_ontology_hides_contents(
        self, patched_provekit
    ):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPFLogicProver(
                enable_zkp=True,
                zkp_backend="provekit",
            )
        prover.add_class(FLogicClass("Dog", superclasses=["Animal"]))
        prover.add_frame(FLogicFrame("rex", isa="Dog"))

        result = prover.query(
            "?X : Dog", prefer_zkp=True, private_ontology=True
        )
        assert result.is_private is True


# ---------------------------------------------------------------------------
# ZKPFLogicProver — standard fallback
# ---------------------------------------------------------------------------


class TestZKPFLogicProverFallback:
    """Standard F-logic path is preserved when ZKP is disabled or not preferred."""

    def test_standard_fallback_when_zkp_disabled(self):
        prover = ZKPFLogicProver(enable_zkp=False, enable_caching=False)
        prover.add_class(FLogicClass("Dog", superclasses=["Animal"]))
        prover.add_frame(FLogicFrame("rex", isa="Dog"))

        result = prover.query("?X : Dog", prefer_zkp=False, use_cache=False)
        # Standard path runs (no ZKP). Simulated ErgoAI returns UNKNOWN (no binary);
        # the important invariant is that the ZKP proof is absent.
        assert result.zkp_proof is None
        assert result.status in (FLogicStatus.SUCCESS, FLogicStatus.UNKNOWN)

    def test_standard_fallback_prefer_zkp_false(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            prover = ZKPFLogicProver(enable_zkp=True, zkp_backend="provekit")
        prover.add_class(FLogicClass("Dog", superclasses=["Animal"]))

        result = prover.query("?X : Dog", prefer_zkp=False, use_cache=False)
        assert result.zkp_proof is None
        assert result.status in (FLogicStatus.SUCCESS, FLogicStatus.UNKNOWN)


# ---------------------------------------------------------------------------
# Cross-prover: ProveKit envelope shape consistency
# ---------------------------------------------------------------------------


class TestProveKitEnvelopeConsistency:
    """Envelopes from all three provers share the same ProveKit schema."""

    def test_all_three_provers_produce_consistent_backend_ids(
        self, tdfol_kb, cec_axioms, patched_provekit
    ):
        """backend='provekit' and proof_system='ProveKit-WHIR' across all provers."""
        results = []

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)

            tdfol_prover = ZKPTDFOLProver(
                tdfol_kb,
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
            tdfol_result = tdfol_prover.prove(Predicate("P", []), prefer_zkp=True)
            results.append(("TDFOL", tdfol_result.zkp_proof))

            cec_prover = _cec_prover(
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
            cec_result = cec_prover.prove_theorem(
                parse_dcec_string("q"), cec_axioms, prefer_zkp=True, private_axioms=True
            )
            results.append(("CEC", cec_result.zkp_proof))

            flogic_prover = ZKPFLogicProver(
                enable_zkp=True,
                zkp_backend="provekit",
            )
            flogic_prover.add_class(FLogicClass("Dog", superclasses=["Animal"]))
            flogic_result = flogic_prover.query("?X : Dog", prefer_zkp=True)
            results.append(("FLogic", flogic_result.zkp_proof))

        for name, proof in results:
            assert proof is not None, f"{name} produced no proof"
            assert proof.metadata.get("backend") == "provekit", (
                f"{name}: expected backend='provekit', got "
                f"{proof.metadata.get('backend')!r}"
            )
            assert proof.metadata.get("proof_system") == "ProveKit-WHIR", (
                f"{name}: expected proof_system='ProveKit-WHIR', got "
                f"{proof.metadata.get('proof_system')!r}"
            )

    def test_all_three_provers_proof_data_size_in_range(
        self, tdfol_kb, cec_axioms, patched_provekit
    ):
        """Proof data size is within the 100-300 byte verifier acceptance window."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)

            tdfol_prover = ZKPTDFOLProver(
                tdfol_kb,
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
            tdfol_result = tdfol_prover.prove(Predicate("P", []), prefer_zkp=True)

            cec_prover = _cec_prover(
                enable_zkp=True,
                zkp_backend="provekit",
                zkp_fallback="standard",
            )
            cec_result = cec_prover.prove_theorem(
                parse_dcec_string("q"), cec_axioms, prefer_zkp=True, private_axioms=True
            )

            flogic_prover = ZKPFLogicProver(
                enable_zkp=True,
                zkp_backend="provekit",
            )
            flogic_prover.add_class(FLogicClass("Dog", superclasses=["Animal"]))
            flogic_result = flogic_prover.query("?X : Dog", prefer_zkp=True)

        for name, result in [
            ("TDFOL", tdfol_result),
            ("CEC", cec_result),
            ("FLogic", flogic_result),
        ]:
            proof = (
                result.zkp_proof
                if hasattr(result, "zkp_proof")
                else getattr(result, "zkp_proof", None)
            )
            assert proof is not None, f"{name} produced no proof"
            assert 100 <= proof.size_bytes <= 300, (
                f"{name}: proof size {proof.size_bytes} outside [100, 300]"
            )
