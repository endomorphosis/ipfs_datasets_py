"""Property-based and explicit determinism/failure tests for ProveKit ZKP logic.

Covers:
- Determinism: identical inputs always produce identical outputs.
- Failure cases: invalid or absent inputs are rejected with the right errors.
- Invariants: canonicalization, public-input building, and Prover.toml
  rendering satisfy algebraic properties independent of any fixed value.

Uses both hypothesis-based strategies and hand-crafted edge cases so that the
suite passes even when hypothesis is not installed (the parametrize fallback
covers the critical cases).
"""

from __future__ import annotations

import hashlib
import json
import string
from typing import List

import pytest

from ipfs_datasets_py.logic.zkp.canonicalization import (
    axioms_commitment_hex,
    canonicalize_axioms,
    normalize_text,
    theorem_hash_hex,
)
from ipfs_datasets_py.logic.zkp.provekit.public_inputs import (
    DEFAULT_PROVEKIT_CIRCUIT_ID,
    DEFAULT_PROVEKIT_CIRCUIT_VERSION,
    DEFAULT_PROVEKIT_HASH_BACKEND,
    DEFAULT_PROVEKIT_RULESET_ID,
    ProveKitPublicInputRecord,
    build_provekit_public_input_record,
    field_element_from_hex_digest,
    field_element_from_text,
)
from ipfs_datasets_py.logic.zkp.provekit.witness import (
    KNOWLEDGE_OF_AXIOMS_FIELD_ORDER,
    render_knowledge_of_axioms_prover_toml,
)

try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    _HYPOTHESIS_AVAILABLE = True
except ImportError:
    _HYPOTHESIS_AVAILABLE = False

    class HealthCheck:  # type: ignore[no-redef]
        too_slow = object()

    class _UnavailableStrategy:
        def filter(self, *_args, **_kwargs):
            return self

        def map(self, *_args, **_kwargs):
            return self

    class _UnavailableStrategies:
        def text(self, **_kwargs):
            return _UnavailableStrategy()

        def lists(self, *_args, **_kwargs):
            return _UnavailableStrategy()

    def given(**_kwargs):  # type: ignore[no-redef]
        def decorator(func):
            return func

        return decorator

    def settings(**_kwargs):  # type: ignore[no-redef]
        def decorator(func):
            return func

        return decorator

    st = _UnavailableStrategies()  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ASCII_TEXT = string.ascii_letters + string.digits + " _->()."
_SAMPLE_THEOREMS = ["Q", "R", "P and Q", "Socrates is mortal", "alpha -> beta"]
_SAMPLE_AXIOM_SETS = [
    ["P"],
    ["P", "P -> Q"],
    ["P -> Q", "P"],
    ["P", "P", "P"],
    ["P", "P -> Q", "Q -> R"],
    ["All humans are mortal", "Socrates is human"],
]


def _make_record(theorem: str, axioms: List[str]) -> ProveKitPublicInputRecord:
    return build_provekit_public_input_record(
        theorem=theorem,
        private_axioms=axioms,
    )


# ---------------------------------------------------------------------------
# Determinism: canonicalization
# ---------------------------------------------------------------------------


class TestCanonicalizationDeterminism:
    @pytest.mark.parametrize("theorem", _SAMPLE_THEOREMS)
    def test_theorem_hash_deterministic(self, theorem: str) -> None:
        assert theorem_hash_hex(theorem) == theorem_hash_hex(theorem)

    @pytest.mark.parametrize("axioms", _SAMPLE_AXIOM_SETS)
    def test_axioms_commitment_deterministic(self, axioms: List[str]) -> None:
        assert axioms_commitment_hex(axioms) == axioms_commitment_hex(axioms)

    def test_normalize_text_idempotent(self) -> None:
        for raw in ["  Q  ", "P  ->   Q", "All  humans  are  mortal", "x"]:
            once = normalize_text(raw)
            twice = normalize_text(once)
            assert once == twice

    def test_canonicalize_axioms_idempotent(self) -> None:
        for axioms in _SAMPLE_AXIOM_SETS:
            once = canonicalize_axioms(axioms)
            twice = canonicalize_axioms(once)
            assert once == twice

    def test_theorem_hash_length_always_64(self) -> None:
        for t in _SAMPLE_THEOREMS:
            assert len(theorem_hash_hex(t)) == 64

    def test_axioms_commitment_length_always_64(self) -> None:
        for axioms in _SAMPLE_AXIOM_SETS:
            assert len(axioms_commitment_hex(axioms)) == 64


# ---------------------------------------------------------------------------
# Determinism: public-input building
# ---------------------------------------------------------------------------


class TestPublicInputDeterminism:
    @pytest.mark.parametrize("theorem,axioms", [
        ("Q", ["P", "P -> Q"]),
        ("R", ["P", "P -> Q", "Q -> R"]),
        ("Socrates is mortal", ["All humans are mortal", "Socrates is human"]),
    ])
    def test_build_record_deterministic(self, theorem: str, axioms: List[str]) -> None:
        r1 = _make_record(theorem, axioms)
        r2 = _make_record(theorem, axioms)
        assert r1 == r2
        assert r1.canonical_hash() == r2.canonical_hash()

    def test_canonical_json_is_stable(self) -> None:
        r = _make_record("Q", ["P", "P -> Q"])
        assert r.canonical_json() == r.canonical_json()

    def test_canonical_hash_is_stable(self) -> None:
        r = _make_record("Q", ["P", "P -> Q"])
        assert r.canonical_hash() == r.canonical_hash()

    def test_noir_field_inputs_deterministic(self) -> None:
        r = _make_record("Q", ["P", "P -> Q"])
        assert r.to_noir_field_inputs() == r.to_noir_field_inputs()

    def test_different_theorems_produce_different_hashes(self) -> None:
        hashes = {theorem_hash_hex(t) for t in _SAMPLE_THEOREMS}
        assert len(hashes) == len(_SAMPLE_THEOREMS)

    def test_different_axiom_sets_produce_different_commitments(self) -> None:
        distinct_sets = [
            ["P"],
            ["P", "P -> Q"],
            ["P", "P -> Q", "Q -> R"],
            ["All humans are mortal", "Socrates is human"],
        ]
        commitments = {axioms_commitment_hex(a) for a in distinct_sets}
        assert len(commitments) == len(distinct_sets)

    def test_axiom_order_does_not_change_commitment(self) -> None:
        axioms = ["P", "P -> Q", "Q -> R"]
        c1 = axioms_commitment_hex(axioms)
        c2 = axioms_commitment_hex(list(reversed(axioms)))
        assert c1 == c2

    def test_duplicate_axioms_do_not_change_commitment(self) -> None:
        c1 = axioms_commitment_hex(["P", "P -> Q"])
        c2 = axioms_commitment_hex(["P", "P -> Q", "P", "P -> Q"])
        assert c1 == c2


# ---------------------------------------------------------------------------
# Determinism: Prover.toml rendering
# ---------------------------------------------------------------------------


class TestProverTomlDeterminism:
    @pytest.mark.parametrize("theorem,axioms", [
        ("Q", ["P", "P -> Q"]),
        ("R", ["P", "P -> Q", "Q -> R"]),
    ])
    def test_prover_toml_deterministic(self, theorem: str, axioms: List[str]) -> None:
        record = _make_record(theorem, axioms)
        assert render_knowledge_of_axioms_prover_toml(record) == render_knowledge_of_axioms_prover_toml(record)

    def test_prover_toml_ends_with_newline(self) -> None:
        record = _make_record("Q", ["P", "P -> Q"])
        assert render_knowledge_of_axioms_prover_toml(record).endswith("\n")

    def test_prover_toml_has_all_field_order_keys(self) -> None:
        record = _make_record("Q", ["P", "P -> Q"])
        rendered = render_knowledge_of_axioms_prover_toml(record)
        for key in KNOWLEDGE_OF_AXIOMS_FIELD_ORDER:
            assert f'{key} = ' in rendered, f"Missing: {key}"
            assert f'witness_{key} = ' in rendered, f"Missing witness: witness_{key}"

    def test_prover_toml_values_are_non_negative_integers(self) -> None:
        record = _make_record("Q", ["P", "P -> Q"])
        rendered = render_knowledge_of_axioms_prover_toml(record)
        for line in rendered.strip().split("\n"):
            key, _, raw_val = line.partition(" = ")
            val = raw_val.strip().strip('"')
            assert val.isdigit(), f"Non-integer value for {key}: {val}"

    def test_prover_toml_does_not_contain_axiom_text(self) -> None:
        axioms = ["private_rule_alpha", "private_rule_alpha -> Conclusion"]
        record = _make_record("Conclusion", axioms)
        rendered = render_knowledge_of_axioms_prover_toml(record)
        for axiom in axioms:
            assert axiom not in rendered


# ---------------------------------------------------------------------------
# Determinism: field element projection
# ---------------------------------------------------------------------------


class TestFieldElementDeterminism:
    def test_field_element_from_text_deterministic(self) -> None:
        for text in ["sha256", "TDFOL_v1", "provekit_knowledge_of_axioms@v1"]:
            v1 = field_element_from_text(text)
            v2 = field_element_from_text(text)
            assert v1 == v2

    def test_field_element_from_hex_deterministic(self) -> None:
        digest = "a" * 64
        assert field_element_from_hex_digest(digest) == field_element_from_hex_digest(digest)

    def test_field_elements_are_within_bn254_range(self) -> None:
        P_BN254 = 21888242871839275222246405745257275088548364400416034343698204186575808495617
        for text in ["sha256", "TDFOL_v1", "hello"]:
            v = field_element_from_text(text)
            assert 0 <= v < P_BN254

    def test_field_element_from_hex_within_bn254_range(self) -> None:
        P_BN254 = 21888242871839275222246405745257275088548364400416034343698204186575808495617
        full_hex = "f" * 64
        v = field_element_from_hex_digest(full_hex)
        assert 0 <= v < P_BN254


# ---------------------------------------------------------------------------
# Failure cases: canonicalization
# ---------------------------------------------------------------------------


class TestCanonicalizationFailureCases:
    def test_empty_axiom_set_is_accepted(self) -> None:
        commitment = axioms_commitment_hex([])
        assert isinstance(commitment, str)
        assert len(commitment) == 64

    def test_empty_theorem_hash_accepted(self) -> None:
        h = theorem_hash_hex("")
        assert len(h) == 64


# ---------------------------------------------------------------------------
# Failure cases: public-input building
# ---------------------------------------------------------------------------


class TestPublicInputBuildingFailureCases:
    def test_empty_theorem_rejected(self) -> None:
        with pytest.raises((ValueError, Exception)):
            ProveKitPublicInputRecord(
                theorem="",
                theorem_hash=theorem_hash_hex("Q"),
                axioms_commitment=axioms_commitment_hex(["P"]),
                circuit_ref="provekit_knowledge_of_axioms@v1",
                circuit_version=1,
                ruleset_id="TDFOL_v1",
            )

    def test_invalid_theorem_hash_length_rejected(self) -> None:
        with pytest.raises((ValueError, Exception)):
            ProveKitPublicInputRecord(
                theorem="Q",
                theorem_hash="tooshort",
                axioms_commitment=axioms_commitment_hex(["P"]),
                circuit_ref="provekit_knowledge_of_axioms@v1",
                circuit_version=1,
                ruleset_id="TDFOL_v1",
            )

    def test_uppercase_hex_theorem_hash_rejected(self) -> None:
        upper_hash = theorem_hash_hex("Q").upper()
        with pytest.raises((ValueError, Exception)):
            ProveKitPublicInputRecord(
                theorem="Q",
                theorem_hash=upper_hash,
                axioms_commitment=axioms_commitment_hex(["P"]),
                circuit_ref="provekit_knowledge_of_axioms@v1",
                circuit_version=1,
                ruleset_id="TDFOL_v1",
            )

    def test_negative_circuit_version_rejected(self) -> None:
        with pytest.raises((ValueError, TypeError, Exception)):
            ProveKitPublicInputRecord(
                theorem="Q",
                theorem_hash=theorem_hash_hex("Q"),
                axioms_commitment=axioms_commitment_hex(["P"]),
                circuit_ref="provekit_knowledge_of_axioms@v-1",
                circuit_version=-1,
                ruleset_id="TDFOL_v1",
            )

    def test_empty_ruleset_id_rejected(self) -> None:
        with pytest.raises((ValueError, Exception)):
            ProveKitPublicInputRecord(
                theorem="Q",
                theorem_hash=theorem_hash_hex("Q"),
                axioms_commitment=axioms_commitment_hex(["P"]),
                circuit_ref="provekit_knowledge_of_axioms@v1",
                circuit_version=1,
                ruleset_id="",
            )

    def test_compiler_guidance_version_without_ref_rejected(self) -> None:
        with pytest.raises((ValueError, Exception)):
            ProveKitPublicInputRecord(
                theorem="Q",
                theorem_hash=theorem_hash_hex("Q"),
                axioms_commitment=axioms_commitment_hex(["P"]),
                circuit_ref="provekit_knowledge_of_axioms@v1",
                circuit_version=1,
                ruleset_id="TDFOL_v1",
                compiler_guidance_ref="",
                compiler_guidance_version=1,
            )

    def test_attestation_version_without_ref_rejected(self) -> None:
        with pytest.raises((ValueError, Exception)):
            ProveKitPublicInputRecord(
                theorem="Q",
                theorem_hash=theorem_hash_hex("Q"),
                axioms_commitment=axioms_commitment_hex(["P"]),
                circuit_ref="provekit_knowledge_of_axioms@v1",
                circuit_version=1,
                ruleset_id="TDFOL_v1",
                attestation_ref="",
                attestation_view_version=1,
            )

    def test_field_element_from_text_rejects_non_string(self) -> None:
        with pytest.raises((TypeError, Exception)):
            field_element_from_text(12345)  # type: ignore[arg-type]

    def test_field_element_from_hex_rejects_wrong_length(self) -> None:
        with pytest.raises((ValueError, Exception)):
            field_element_from_hex_digest("aabbcc")

    def test_field_element_from_hex_rejects_non_hex(self) -> None:
        with pytest.raises((ValueError, Exception)):
            field_element_from_hex_digest("z" * 64)


# ---------------------------------------------------------------------------
# Failure cases: Prover.toml rendering
# ---------------------------------------------------------------------------


class TestProverTomlFailureCases:
    def test_prover_toml_different_inputs_produce_different_output(self) -> None:
        r1 = _make_record("Q", ["P", "P -> Q"])
        r2 = _make_record("R", ["P", "P -> Q", "Q -> R"])
        assert render_knowledge_of_axioms_prover_toml(r1) != render_knowledge_of_axioms_prover_toml(r2)

    def test_prover_toml_axiom_change_changes_output(self) -> None:
        r1 = _make_record("Q", ["P", "P -> Q"])
        r2 = _make_record("Q", ["X", "X -> Q"])
        t1 = render_knowledge_of_axioms_prover_toml(r1)
        t2 = render_knowledge_of_axioms_prover_toml(r2)
        assert t1 != t2


# ---------------------------------------------------------------------------
# Hypothesis-based property tests (skipped when hypothesis not installed)
# ---------------------------------------------------------------------------


def _hypothesis_tests_are_available() -> bool:
    return _HYPOTHESIS_AVAILABLE


@pytest.mark.skipif(not _hypothesis_tests_are_available(), reason="hypothesis not installed")
class TestHypothesisProperties:
    @given(
        theorem=st.text(
            alphabet=string.ascii_letters + string.digits + " _->().",
            min_size=1,
            max_size=200,
        ),
        axioms=st.lists(
            st.text(
                alphabet=string.ascii_letters + string.digits + " _->().",
                min_size=1,
                max_size=100,
            ),
            min_size=0,
            max_size=8,
        ),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_theorem_hash_always_64_hex_chars(self, theorem: str, axioms: list) -> None:
        h = theorem_hash_hex(theorem)
        assert len(h) == 64
        assert all(c in string.hexdigits for c in h)
        assert h == h.lower()

    @given(
        axioms=st.lists(
            st.text(
                alphabet=string.ascii_letters + string.digits + " _->().",
                min_size=1,
                max_size=100,
            ),
            min_size=0,
            max_size=8,
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_axioms_commitment_always_64_hex_chars(self, axioms: list) -> None:
        c = axioms_commitment_hex(axioms)
        assert len(c) == 64
        assert all(c_char in string.hexdigits for c_char in c)
        assert c == c.lower()

    @given(
        axioms=st.lists(
            st.text(
                alphabet=string.ascii_letters + string.digits + " _->().",
                min_size=1,
                max_size=100,
            ),
            min_size=1,
            max_size=6,
        )
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_axiom_order_independence(self, axioms: list) -> None:
        import random as _random
        shuffled = list(axioms)
        _random.shuffle(shuffled)
        assert axioms_commitment_hex(axioms) == axioms_commitment_hex(shuffled)

    @given(
        axioms=st.lists(
            st.text(
                alphabet=string.ascii_letters + string.digits + " _->().",
                min_size=1,
                max_size=100,
            ),
            min_size=1,
            max_size=6,
        )
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_axiom_duplication_does_not_change_commitment(self, axioms: list) -> None:
        c1 = axioms_commitment_hex(axioms)
        doubled = axioms + axioms
        c2 = axioms_commitment_hex(doubled)
        assert c1 == c2

    @given(
        theorem=st.text(
            alphabet=string.ascii_letters + string.digits + " _->().",
            min_size=1,
            max_size=200,
        ),
        axioms=st.lists(
            st.text(
                alphabet=string.ascii_letters + string.digits + " _->().",
                min_size=1,
                max_size=100,
            ),
            min_size=1,
            max_size=6,
        ),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_public_input_record_is_deterministic(self, theorem: str, axioms: list) -> None:
        r1 = build_provekit_public_input_record(theorem=theorem, private_axioms=axioms)
        r2 = build_provekit_public_input_record(theorem=theorem, private_axioms=axioms)
        assert r1 == r2
        assert r1.canonical_hash() == r2.canonical_hash()

    @given(
        theorem=st.text(
            alphabet=string.ascii_letters + string.digits + " _->().",
            min_size=1,
            max_size=200,
        ),
        axioms=st.lists(
            st.text(
                alphabet=string.ascii_letters + string.digits + " _->().",
                min_size=1,
                max_size=100,
            ),
            min_size=1,
            max_size=6,
        ),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_prover_toml_rendering_deterministic(self, theorem: str, axioms: list) -> None:
        record = build_provekit_public_input_record(theorem=theorem, private_axioms=axioms)
        t1 = render_knowledge_of_axioms_prover_toml(record)
        t2 = render_knowledge_of_axioms_prover_toml(record)
        assert t1 == t2

    @given(
        theorem=st.text(
            alphabet=string.ascii_letters + "_->().",
            min_size=4,
            max_size=200,
        ).filter(lambda t: any(c.isalpha() for c in t) and not t.isdigit()),
        axioms=st.lists(
            st.text(
                alphabet=string.ascii_letters + "_->().",
                min_size=4,
                max_size=100,
            ).filter(lambda a: any(c.isalpha() for c in a) and not a.isdigit()),
            min_size=1,
            max_size=6,
        ),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_private_axiom_text_absent_from_prover_toml(self, theorem: str, axioms: list) -> None:
        """Axiom text must not appear in Prover.toml field values.

        Prover.toml values are quoted integers.  Any alphabetic axiom text
        cannot be present in those numeric values.  We check the value portion
        of each line (right side of ` = `) to confirm the axiom string is
        absent there.  Key names are fixed constants and are not checked.
        """
        record = build_provekit_public_input_record(theorem=theorem, private_axioms=axioms)
        rendered = render_knowledge_of_axioms_prover_toml(record)
        values_text = "\n".join(
            line.partition(" = ")[2]
            for line in rendered.strip().split("\n")
        )
        for axiom in axioms:
            assert axiom not in values_text, f"Private axiom leaked into Prover.toml value: {axiom!r}"
