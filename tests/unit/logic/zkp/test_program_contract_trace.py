"""Cross-codec vectors and structural tests for program_contract_trace@v1.

Implements the VFS-023 Python companion for the Noir circuit
``provekit_program_contract_trace``:

* canonical public-input and witness field vectors with explicit BN254 encoding
* bounds matching the circuit (MAX_TRACE_STEPS=16, CANONICAL_TRACE_LENGTH=8)
* a pure-Python reference checker that mirrors the circuit constraints
* rejection of reordered/omitted steps, forged result, wrong contract/call
  slice/forest/version, overflow, padding ambiguity, and altered key/circuit
  identity

Does **not** copy a simulated backend, emit an authoritative proof, or claim
general function-call semantics. When the real Noir/ProveKit toolchain is
unavailable, capability tests are explicitly skipped.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

# ---------------------------------------------------------------------------
# Constants (must match main.nr)
# ---------------------------------------------------------------------------

P_BN254: int = (
    21888242871839275222246405745257275088548364400416034343698204186575808495617
)

MAX_TRACE_STEPS: int = 16
CANONICAL_TRACE_LENGTH: int = 8
CIRCUIT_VERSION: int = 1

CIRCUIT_PACKAGE_NAME: str = "provekit_program_contract_trace"
CIRCUIT_DIR_NAME: str = "program_contract_trace"
CIRCUIT_ID: str = "circuit:program-contract-trace@1"
PUBLIC_INPUT_CODEC_ID: str = (
    "ipfs_accelerate_py/agent-supervisor/program-analysis-zkp-public-input-codec"
)
PUBLIC_INPUT_CODEC_VERSION: str = "1"

# Ordered public commitment keys (program-analysis-zkp codec order).
PUBLIC_COMMITMENT_KEYS: tuple[str, ...] = (
    "forest_commitment",
    "inventory_commitment",
    "contract_commitment",
    "call_slice_commitment",
    "assumptions_commitment",
    "analyzer_version",
    "resolver_version",
    "translator_version",
    "prover_version",
    "result_commitment",
    "circuit_id",
    "proving_key_id",
    "verifying_key_id",
    "ceremony_id",
    "public_input_codec_id",
    "public_input_codec_version",
)

# Public Noir field parameter names (same order + control fields).
PUBLIC_NOIR_FIELD_NAMES: tuple[str, ...] = (
    "forest_commitment_field",
    "inventory_commitment_field",
    "contract_commitment_field",
    "call_slice_commitment_field",
    "assumptions_commitment_field",
    "analyzer_version_field",
    "resolver_version_field",
    "translator_version_field",
    "prover_version_field",
    "result_commitment_field",
    "circuit_id_field",
    "proving_key_id_field",
    "verifying_key_id_field",
    "ceremony_id_field",
    "public_input_codec_id_field",
    "public_input_codec_version_field",
    "trace_length",
    "circuit_version",
)

# Private opening witness names (pair with public commitments).
OPENING_WITNESS_NAMES: tuple[str, ...] = (
    "open_forest_commitment",
    "open_inventory_commitment",
    "open_contract_commitment",
    "open_call_slice_commitment",
    "open_assumptions_commitment",
    "open_analyzer_version",
    "open_resolver_version",
    "open_translator_version",
    "open_prover_version",
    "open_result_commitment",
    "open_circuit_id",
    "open_proving_key_id",
    "open_verifying_key_id",
    "open_ceremony_id",
    "open_public_input_codec_id",
    "open_public_input_codec_version",
)

STATE_CODES: dict[str, int] = {
    "init": 0,
    "forest_opened": 1,
    "inventory_opened": 2,
    "contract_opened": 3,
    "call_slice_opened": 4,
    "assumptions_opened": 5,
    "versions_bound": 6,
    "result_committed": 7,
    "terminal": 8,
}

KIND_CODES: dict[str, int] = {
    "open_forest": 0,
    "open_inventory": 1,
    "open_contract": 2,
    "open_call_slice": 3,
    "open_assumptions": 4,
    "bind_versions": 5,
    "commit_result": 6,
    "terminate": 7,
}

# Canonical supported transition table (source, kind, target).
SUPPORTED_TRANSITIONS: tuple[tuple[str, str, str], ...] = (
    ("init", "open_forest", "forest_opened"),
    ("forest_opened", "open_inventory", "inventory_opened"),
    ("inventory_opened", "open_contract", "contract_opened"),
    ("contract_opened", "open_call_slice", "call_slice_opened"),
    ("call_slice_opened", "open_assumptions", "assumptions_opened"),
    ("assumptions_opened", "bind_versions", "versions_bound"),
    ("versions_bound", "commit_result", "result_committed"),
    ("result_committed", "terminate", "terminal"),
)

# Explicit non-claims mirrored in the circuit header.
TRACE_VALIDITY_DOES_NOT_PROVE: frozenset[str] = frozenset(
    {
        "inventory_completeness",
        "translator_soundness",
        "arbitrary_runtime_semantics",
        "general_function_call_semantics",
        "theorem_beyond_committed_supported_result",
    }
)


class ProgramContractTraceError(ValueError):
    """Raised when a program-contract trace vector fails circuit constraints."""


# ---------------------------------------------------------------------------
# Field encoding
# ---------------------------------------------------------------------------


def field_element_from_text(value: str) -> int:
    """Map UTF-8 text to the BN254 scalar field via SHA-256 (mod P)."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest, "big") % P_BN254


def field_element_from_int(value: int) -> int:
    """Map a non-negative integer into the BN254 scalar field."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("value must be an int")
    if value < 0:
        raise ProgramContractTraceError("field integer must be non-negative")
    if value >= P_BN254:
        raise ProgramContractTraceError("field integer overflows BN254 scalar field")
    return value


EXPECTED_CIRCUIT_ID_FIELD: int = field_element_from_text(CIRCUIT_ID)
EXPECTED_CODEC_ID_FIELD: int = field_element_from_text(PUBLIC_INPUT_CODEC_ID)
EXPECTED_CODEC_VERSION_FIELD: int = field_element_from_text(PUBLIC_INPUT_CODEC_VERSION)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _package_root() -> Path:
    # tests/unit/logic/zkp -> ipfs_datasets_py package root
    return Path(__file__).resolve().parents[4]


def _circuit_dir() -> Path:
    return (
        _package_root()
        / "ipfs_datasets_py"
        / "logic"
        / "zkp"
        / "provekit"
        / "circuits"
        / CIRCUIT_DIR_NAME
    )


def _nr_code() -> str:
    return (_circuit_dir() / "src" / "main.nr").read_text(encoding="utf-8")


def _nargo_toml() -> str:
    return (_circuit_dir() / "Nargo.toml").read_text(encoding="utf-8")


def _nargo_available() -> bool:
    return shutil.which("nargo") is not None


# ---------------------------------------------------------------------------
# Canonical fixture material
# ---------------------------------------------------------------------------


def _default_public_strings(**overrides: str) -> dict[str, str]:
    base = {
        "forest_commitment": "cid:forest:repo-alpha@1",
        "inventory_commitment": "cid:inventory:files-ab@1",
        "contract_commitment": "cid:contract:pkg.api.call@1",
        "call_slice_commitment": "cid:call-slice:main>pkg.api.call@1",
        "assumptions_commitment": "cid:assumptions:finite-hermetic@1",
        "analyzer_version": "analyzer:program-graph@1.0.0",
        "resolver_version": "resolver:call@2.1.0",
        "translator_version": "translator:contract-ir@1.3.0",
        "prover_version": "prover:program-contract-trace@0.1.0",
        "result_commitment": "cid:result:contract_check_ok:finite@1",
        "circuit_id": CIRCUIT_ID,
        "proving_key_id": "pk:program-contract-trace@1:sha256-pk-fixture",
        "verifying_key_id": "vk:program-contract-trace@1:sha256-vk-fixture",
        "ceremony_id": "ceremony:program-contract-trace@1",
        "public_input_codec_id": PUBLIC_INPUT_CODEC_ID,
        "public_input_codec_version": PUBLIC_INPUT_CODEC_VERSION,
    }
    base.update(overrides)
    return base


def encode_public_commitment_fields(public_strings: Mapping[str, str]) -> dict[str, int]:
    """Encode string public inputs to Noir Field integers (codec order)."""

    if set(public_strings.keys()) != set(PUBLIC_COMMITMENT_KEYS):
        missing = sorted(set(PUBLIC_COMMITMENT_KEYS) - set(public_strings.keys()))
        extra = sorted(set(public_strings.keys()) - set(PUBLIC_COMMITMENT_KEYS))
        raise ProgramContractTraceError(
            "public commitment keys mismatch; missing=%s extra=%s" % (missing, extra)
        )
    fields: dict[str, int] = {}
    for key in PUBLIC_COMMITMENT_KEYS:
        value = public_strings[key]
        if not isinstance(value, str) or not value.strip():
            raise ProgramContractTraceError(
                "public input %s must be a non-empty string" % key
            )
        fields[f"{key}_field"] = field_element_from_text(value.strip())
    return fields


def _versions_binding(fields: Mapping[str, int]) -> int:
    return (
        fields["analyzer_version_field"]
        + fields["resolver_version_field"]
        + fields["translator_version_field"]
        + fields["prover_version_field"]
    ) % P_BN254


def _key_identity_binding(fields: Mapping[str, int]) -> int:
    return (
        fields["circuit_id_field"]
        + fields["proving_key_id_field"]
        + fields["verifying_key_id_field"]
        + fields["ceremony_id_field"]
    ) % P_BN254


def _binding_for_step(index: int, fields: Mapping[str, int]) -> int:
    if index == 0:
        return fields["forest_commitment_field"]
    if index == 1:
        return fields["inventory_commitment_field"]
    if index == 2:
        return fields["contract_commitment_field"]
    if index == 3:
        return fields["call_slice_commitment_field"]
    if index == 4:
        return fields["assumptions_commitment_field"]
    if index == 5:
        return _versions_binding(fields)
    if index == 6:
        return fields["result_commitment_field"]
    if index == 7:
        return _key_identity_binding(fields)
    raise ProgramContractTraceError("step index out of canonical range: %s" % index)


@dataclass(frozen=True)
class ProgramContractTraceVectors:
    """Canonical Python/Noir public-input and witness vectors."""

    public_strings: dict[str, str]
    public_fields: dict[str, int]
    witness_openings: dict[str, int]
    step_kinds: list[int]
    step_source_states: list[int]
    step_target_states: list[int]
    step_binding_fields: list[int]
    trace_length: int
    circuit_version: int

    def public_input_vector(self) -> list[int]:
        """Ordered public Field vector matching Noir ``main`` parameters."""

        values = []
        for name in PUBLIC_NOIR_FIELD_NAMES:
            if name == "trace_length":
                values.append(self.trace_length)
            elif name == "circuit_version":
                values.append(self.circuit_version)
            else:
                values.append(self.public_fields[name])
        return values

    def witness_vector(self) -> dict[str, Any]:
        """Full private witness payload for the circuit."""

        return {
            **self.witness_openings,
            "step_kinds": list(self.step_kinds),
            "step_source_states": list(self.step_source_states),
            "step_target_states": list(self.step_target_states),
            "step_binding_fields": list(self.step_binding_fields),
        }

    def to_noir_prover_inputs(self) -> dict[str, Any]:
        """Combined public + private map suitable for a prover frontend."""

        return {
            **{name: self.public_fields[name] for name in PUBLIC_NOIR_FIELD_NAMES if name.endswith("_field")},
            "trace_length": self.trace_length,
            "circuit_version": self.circuit_version,
            **self.witness_vector(),
        }

    def public_accumulator(self) -> int:
        """Mirror the circuit return expression (mod P)."""

        f = self.public_fields
        return (
            f["forest_commitment_field"]
            + f["inventory_commitment_field"]
            + f["contract_commitment_field"]
            + f["call_slice_commitment_field"]
            + f["assumptions_commitment_field"]
            + f["result_commitment_field"]
            + f["circuit_id_field"]
            + f["proving_key_id_field"]
            + f["verifying_key_id_field"]
            + f["ceremony_id_field"]
            + self.circuit_version
            + self.trace_length
        ) % P_BN254


def build_canonical_vectors(**public_overrides: str) -> ProgramContractTraceVectors:
    """Build honest canonical public/witness vectors for one contract-check result."""

    public_strings = _default_public_strings(**public_overrides)
    fields = encode_public_commitment_fields(public_strings)

    step_kinds = [0] * MAX_TRACE_STEPS
    step_source_states = [0] * MAX_TRACE_STEPS
    step_target_states = [0] * MAX_TRACE_STEPS
    step_binding_fields = [0] * MAX_TRACE_STEPS

    for index, (source, kind, target) in enumerate(SUPPORTED_TRANSITIONS):
        step_kinds[index] = KIND_CODES[kind]
        step_source_states[index] = STATE_CODES[source]
        step_target_states[index] = STATE_CODES[target]
        step_binding_fields[index] = _binding_for_step(index, fields)

    openings = {
        OPENING_WITNESS_NAMES[i]: fields[f"{PUBLIC_COMMITMENT_KEYS[i]}_field"]
        for i in range(len(PUBLIC_COMMITMENT_KEYS))
    }

    return ProgramContractTraceVectors(
        public_strings=public_strings,
        public_fields=fields,
        witness_openings=openings,
        step_kinds=step_kinds,
        step_source_states=step_source_states,
        step_target_states=step_target_states,
        step_binding_fields=step_binding_fields,
        trace_length=CANONICAL_TRACE_LENGTH,
        circuit_version=CIRCUIT_VERSION,
    )


def check_circuit_constraints(vectors: ProgramContractTraceVectors) -> int:
    """Python reference checker mirroring ``main.nr`` constraints.

    Returns the public accumulator on success; raises
    :class:`ProgramContractTraceError` on any violation. Never emits a proof.
    """

    f = vectors.public_fields
    if vectors.circuit_version != CIRCUIT_VERSION:
        raise ProgramContractTraceError("circuit_version mismatch")
    if f["circuit_id_field"] != EXPECTED_CIRCUIT_ID_FIELD:
        raise ProgramContractTraceError("altered circuit identity")
    if f["public_input_codec_id_field"] != EXPECTED_CODEC_ID_FIELD:
        raise ProgramContractTraceError("altered public_input_codec_id")
    if f["public_input_codec_version_field"] != EXPECTED_CODEC_VERSION_FIELD:
        raise ProgramContractTraceError("altered public_input_codec_version")

    for key, opening_name in zip(PUBLIC_COMMITMENT_KEYS, OPENING_WITNESS_NAMES):
        field_name = f"{key}_field"
        if vectors.witness_openings.get(opening_name) != f[field_name]:
            raise ProgramContractTraceError(
                "commitment opening mismatch for %s" % key
            )

    for key in (
        "forest_commitment",
        "inventory_commitment",
        "contract_commitment",
        "call_slice_commitment",
        "assumptions_commitment",
        "analyzer_version",
        "resolver_version",
        "translator_version",
        "prover_version",
        "result_commitment",
        "proving_key_id",
        "verifying_key_id",
        "ceremony_id",
    ):
        if f[f"{key}_field"] == 0:
            raise ProgramContractTraceError("zeroed public commitment: %s" % key)

    if vectors.trace_length != CANONICAL_TRACE_LENGTH:
        raise ProgramContractTraceError(
            "trace_length must equal %s (got %s)"
            % (CANONICAL_TRACE_LENGTH, vectors.trace_length)
        )
    if vectors.trace_length <= 0 or vectors.trace_length > MAX_TRACE_STEPS:
        raise ProgramContractTraceError("trace_length out of bounds")

    for name, arr in (
        ("step_kinds", vectors.step_kinds),
        ("step_source_states", vectors.step_source_states),
        ("step_target_states", vectors.step_target_states),
        ("step_binding_fields", vectors.step_binding_fields),
    ):
        if len(arr) != MAX_TRACE_STEPS:
            raise ProgramContractTraceError(
                "%s must have length %s" % (name, MAX_TRACE_STEPS)
            )

    n = vectors.trace_length
    for i in range(MAX_TRACE_STEPS):
        if i >= n:
            if (
                vectors.step_kinds[i] != 0
                or vectors.step_source_states[i] != 0
                or vectors.step_target_states[i] != 0
                or vectors.step_binding_fields[i] != 0
            ):
                raise ProgramContractTraceError(
                    "padding ambiguity at index %s" % i
                )

    expected_steps = (
        (KIND_CODES["open_forest"], STATE_CODES["init"], STATE_CODES["forest_opened"], f["forest_commitment_field"]),
        (KIND_CODES["open_inventory"], STATE_CODES["forest_opened"], STATE_CODES["inventory_opened"], f["inventory_commitment_field"]),
        (KIND_CODES["open_contract"], STATE_CODES["inventory_opened"], STATE_CODES["contract_opened"], f["contract_commitment_field"]),
        (KIND_CODES["open_call_slice"], STATE_CODES["contract_opened"], STATE_CODES["call_slice_opened"], f["call_slice_commitment_field"]),
        (KIND_CODES["open_assumptions"], STATE_CODES["call_slice_opened"], STATE_CODES["assumptions_opened"], f["assumptions_commitment_field"]),
        (KIND_CODES["bind_versions"], STATE_CODES["assumptions_opened"], STATE_CODES["versions_bound"], _versions_binding(f)),
        (KIND_CODES["commit_result"], STATE_CODES["versions_bound"], STATE_CODES["result_committed"], f["result_commitment_field"]),
        (KIND_CODES["terminate"], STATE_CODES["result_committed"], STATE_CODES["terminal"], _key_identity_binding(f)),
    )
    for i, (kind, source, target, binding) in enumerate(expected_steps):
        if vectors.step_kinds[i] != kind:
            raise ProgramContractTraceError("reordered or substituted kind at %s" % i)
        if vectors.step_source_states[i] != source:
            raise ProgramContractTraceError("source state mismatch at %s" % i)
        if vectors.step_target_states[i] != target:
            raise ProgramContractTraceError("target state mismatch at %s" % i)
        if vectors.step_binding_fields[i] != binding:
            raise ProgramContractTraceError("binding mismatch at %s" % i)

    return vectors.public_accumulator()


def _mutate_vectors(
    vectors: ProgramContractTraceVectors,
    *,
    public_fields: Mapping[str, int] | None = None,
    witness_openings: Mapping[str, int] | None = None,
    step_kinds: Sequence[int] | None = None,
    step_source_states: Sequence[int] | None = None,
    step_target_states: Sequence[int] | None = None,
    step_binding_fields: Sequence[int] | None = None,
    trace_length: int | None = None,
    circuit_version: int | None = None,
) -> ProgramContractTraceVectors:
    return ProgramContractTraceVectors(
        public_strings=dict(vectors.public_strings),
        public_fields=dict(public_fields if public_fields is not None else vectors.public_fields),
        witness_openings=dict(
            witness_openings if witness_openings is not None else vectors.witness_openings
        ),
        step_kinds=list(step_kinds if step_kinds is not None else vectors.step_kinds),
        step_source_states=list(
            step_source_states
            if step_source_states is not None
            else vectors.step_source_states
        ),
        step_target_states=list(
            step_target_states
            if step_target_states is not None
            else vectors.step_target_states
        ),
        step_binding_fields=list(
            step_binding_fields
            if step_binding_fields is not None
            else vectors.step_binding_fields
        ),
        trace_length=vectors.trace_length if trace_length is None else trace_length,
        circuit_version=(
            vectors.circuit_version if circuit_version is None else circuit_version
        ),
    )


# ---------------------------------------------------------------------------
# Package / circuit structure
# ---------------------------------------------------------------------------


def test_noir_package_files_exist() -> None:
    circuit_dir = _circuit_dir()
    assert (circuit_dir / "Nargo.toml").is_file()
    assert (circuit_dir / "src" / "main.nr").is_file()


def test_nargo_package_named_and_dependency_free() -> None:
    nargo = _nargo_toml()
    assert f'name = "{CIRCUIT_PACKAGE_NAME}"' in nargo
    assert 'type = "bin"' in nargo
    assert "compiler_version" in nargo
    assert "[dependencies]" not in nargo
    assert "git =" not in nargo


def test_circuit_declares_bounds_and_version() -> None:
    code = _nr_code()
    assert f"global MAX_TRACE_STEPS: u32 = {MAX_TRACE_STEPS};" in code
    assert f"global CANONICAL_TRACE_LENGTH: u32 = {CANONICAL_TRACE_LENGTH};" in code
    assert f"global CIRCUIT_VERSION: Field = {CIRCUIT_VERSION};" in code
    assert "assert(circuit_version == CIRCUIT_VERSION);" in code
    assert "assert(n == CANONICAL_TRACE_LENGTH);" in code
    assert "assert(n <= MAX_TRACE_STEPS);" in code


def test_circuit_declares_all_public_field_parameters() -> None:
    code = _nr_code()
    for name in PUBLIC_NOIR_FIELD_NAMES:
        assert f"{name}: pub Field" in code, name


def test_circuit_declares_opening_witnesses_and_step_arrays() -> None:
    code = _nr_code()
    for name in OPENING_WITNESS_NAMES:
        assert f"{name}: Field" in code, name
    assert "step_kinds: [Field; 16]" in code
    assert "step_source_states: [Field; 16]" in code
    assert "step_target_states: [Field; 16]" in code
    assert "step_binding_fields: [Field; 16]" in code


def test_circuit_pins_expected_identity_fields() -> None:
    code = _nr_code()
    assert f"global EXPECTED_CIRCUIT_ID_FIELD: Field = {EXPECTED_CIRCUIT_ID_FIELD};" in code
    assert f"global EXPECTED_CODEC_ID_FIELD: Field = {EXPECTED_CODEC_ID_FIELD};" in code
    assert (
        f"global EXPECTED_CODEC_VERSION_FIELD: Field = {EXPECTED_CODEC_VERSION_FIELD};"
        in code
    )
    assert "assert(circuit_id_field == EXPECTED_CIRCUIT_ID_FIELD);" in code
    assert "assert(public_input_codec_id_field == EXPECTED_CODEC_ID_FIELD);" in code
    assert (
        "assert(public_input_codec_version_field == EXPECTED_CODEC_VERSION_FIELD);"
        in code
    )


def test_circuit_binds_openings_to_public_fields() -> None:
    code = _nr_code()
    pairs = [
        ("open_forest_commitment", "forest_commitment_field"),
        ("open_contract_commitment", "contract_commitment_field"),
        ("open_call_slice_commitment", "call_slice_commitment_field"),
        ("open_result_commitment", "result_commitment_field"),
        ("open_circuit_id", "circuit_id_field"),
        ("open_proving_key_id", "proving_key_id_field"),
        ("open_verifying_key_id", "verifying_key_id_field"),
    ]
    for witness, public in pairs:
        assert f"assert({witness} == {public});" in code


def test_circuit_enforces_supported_transition_table() -> None:
    code = _nr_code()
    assert "KIND_OPEN_FOREST" in code
    assert "KIND_TERMINATE" in code
    assert "STATE_INIT" in code
    assert "STATE_TERMINAL" in code
    assert "step_kinds[0] == KIND_OPEN_FOREST" in code
    assert "step_kinds[6] == KIND_COMMIT_RESULT" in code
    assert "step_binding_fields[6] == result_commitment_field" in code
    assert "step_kinds[7] == KIND_TERMINATE" in code


def test_circuit_zeroes_padding_slots() -> None:
    code = _nr_code()
    assert "step_kinds[i] == 0" in code
    assert "step_source_states[i] == 0" in code
    assert "step_target_states[i] == 0" in code
    assert "step_binding_fields[i] == 0" in code


def test_circuit_does_not_claim_general_function_call_semantics() -> None:
    code = _nr_code()
    # Non-claims must be documented; general semantics must not be claimed as proven.
    assert "inventory completeness" in code.lower() or "inventory_completeness" in code
    assert "translator soundness" in code.lower() or "translator_soundness" in code
    assert "function-call" in code.lower() or "function_call" in code
    assert "does NOT prove" in code or "does not prove" in code.lower()
    # Must not embed simulated-backend authority language.
    assert "SIMULATED_AUTHORITATIVE" not in code
    assert "authoritative proof" not in code.lower()


# ---------------------------------------------------------------------------
# Encoding and honest vectors
# ---------------------------------------------------------------------------


def test_field_encoding_is_deterministic_and_in_range() -> None:
    a = field_element_from_text("cid:forest:repo-alpha@1")
    b = field_element_from_text("cid:forest:repo-alpha@1")
    assert a == b
    assert 0 <= a < P_BN254
    assert field_element_from_int(0) == 0
    assert field_element_from_int(CIRCUIT_VERSION) == CIRCUIT_VERSION
    with pytest.raises(ProgramContractTraceError, match="overflows"):
        field_element_from_int(P_BN254)
    with pytest.raises(ProgramContractTraceError, match="non-negative"):
        field_element_from_int(-1)


def test_expected_identity_fields_match_python_codec() -> None:
    assert EXPECTED_CIRCUIT_ID_FIELD == field_element_from_text(CIRCUIT_ID)
    assert EXPECTED_CODEC_ID_FIELD == field_element_from_text(PUBLIC_INPUT_CODEC_ID)
    assert EXPECTED_CODEC_VERSION_FIELD == field_element_from_text(
        PUBLIC_INPUT_CODEC_VERSION
    )


def test_canonical_vectors_pass_reference_checker() -> None:
    vectors = build_canonical_vectors()
    acc = check_circuit_constraints(vectors)
    assert acc == vectors.public_accumulator()
    assert vectors.trace_length == CANONICAL_TRACE_LENGTH
    assert len(vectors.step_kinds) == MAX_TRACE_STEPS
    assert all(x == 0 for x in vectors.step_kinds[CANONICAL_TRACE_LENGTH:])
    assert all(x == 0 for x in vectors.step_binding_fields[CANONICAL_TRACE_LENGTH:])


def test_public_input_vector_shape_and_order() -> None:
    vectors = build_canonical_vectors()
    public = vectors.public_input_vector()
    assert len(public) == len(PUBLIC_NOIR_FIELD_NAMES)
    assert public[-2] == CANONICAL_TRACE_LENGTH
    assert public[-1] == CIRCUIT_VERSION
    assert public[0] == vectors.public_fields["forest_commitment_field"]
    assert public[10] == EXPECTED_CIRCUIT_ID_FIELD  # circuit_id


def test_witness_vector_contains_openings_and_padded_steps() -> None:
    vectors = build_canonical_vectors()
    witness = vectors.witness_vector()
    for name in OPENING_WITNESS_NAMES:
        assert name in witness
    assert len(witness["step_kinds"]) == MAX_TRACE_STEPS
    assert witness["step_kinds"][:8] == [KIND_CODES[k] for _, k, _ in SUPPORTED_TRANSITIONS]


def test_noir_prover_inputs_include_public_and_private() -> None:
    vectors = build_canonical_vectors()
    inputs = vectors.to_noir_prover_inputs()
    for name in PUBLIC_NOIR_FIELD_NAMES:
        assert name in inputs
    for name in OPENING_WITNESS_NAMES:
        assert name in inputs
    assert "step_kinds" in inputs


def test_encode_public_commitment_fields_rejects_key_mismatch() -> None:
    bad = _default_public_strings()
    del bad["forest_commitment"]
    with pytest.raises(ProgramContractTraceError, match="keys mismatch"):
        encode_public_commitment_fields(bad)
    bad = _default_public_strings()
    bad["extra"] = "nope"
    with pytest.raises(ProgramContractTraceError, match="keys mismatch"):
        encode_public_commitment_fields(bad)


# ---------------------------------------------------------------------------
# Rejection cases (adversarial)
# ---------------------------------------------------------------------------


def test_reject_reordered_steps() -> None:
    vectors = build_canonical_vectors()
    kinds = list(vectors.step_kinds)
    kinds[1], kinds[2] = kinds[2], kinds[1]
    mutated = _mutate_vectors(vectors, step_kinds=kinds)
    with pytest.raises(ProgramContractTraceError, match="reordered|substituted|kind"):
        check_circuit_constraints(mutated)


def test_reject_omitted_steps_via_wrong_length() -> None:
    vectors = build_canonical_vectors()
    with pytest.raises(ProgramContractTraceError, match="trace_length"):
        check_circuit_constraints(_mutate_vectors(vectors, trace_length=7))
    with pytest.raises(ProgramContractTraceError, match="trace_length"):
        check_circuit_constraints(_mutate_vectors(vectors, trace_length=0))


def test_reject_overflow_trace_length() -> None:
    vectors = build_canonical_vectors()
    with pytest.raises(ProgramContractTraceError, match="trace_length"):
        check_circuit_constraints(
            _mutate_vectors(vectors, trace_length=MAX_TRACE_STEPS + 1)
        )
    with pytest.raises(ProgramContractTraceError, match="trace_length"):
        check_circuit_constraints(
            _mutate_vectors(vectors, trace_length=MAX_TRACE_STEPS)
        )


def test_reject_forged_result() -> None:
    vectors = build_canonical_vectors()
    bindings = list(vectors.step_binding_fields)
    bindings[6] = (bindings[6] + 1) % P_BN254
    mutated = _mutate_vectors(vectors, step_binding_fields=bindings)
    with pytest.raises(ProgramContractTraceError, match="binding mismatch"):
        check_circuit_constraints(mutated)

    # Also reject when public result commitment itself is swapped but openings lag.
    fields = dict(vectors.public_fields)
    fields["result_commitment_field"] = (fields["result_commitment_field"] + 7) % P_BN254
    openings = dict(vectors.witness_openings)
    openings["open_result_commitment"] = fields["result_commitment_field"]
    bindings = list(vectors.step_binding_fields)
    # leave commit_result binding pointing at the old result
    mutated = _mutate_vectors(
        vectors,
        public_fields=fields,
        witness_openings=openings,
        step_binding_fields=bindings,
    )
    with pytest.raises(ProgramContractTraceError, match="binding mismatch"):
        check_circuit_constraints(mutated)


def test_reject_wrong_contract_call_slice_forest() -> None:
    vectors = build_canonical_vectors()
    for key, opening, step_index in (
        ("forest_commitment_field", "open_forest_commitment", 0),
        ("contract_commitment_field", "open_contract_commitment", 2),
        ("call_slice_commitment_field", "open_call_slice_commitment", 3),
    ):
        fields = dict(vectors.public_fields)
        fields[key] = (fields[key] + 11) % P_BN254
        openings = dict(vectors.witness_openings)
        openings[opening] = fields[key]
        bindings = list(vectors.step_binding_fields)
        # keep old step binding so the transition table binding fails
        mutated = _mutate_vectors(
            vectors,
            public_fields=fields,
            witness_openings=openings,
            step_binding_fields=bindings,
        )
        with pytest.raises(ProgramContractTraceError, match="binding mismatch"):
            check_circuit_constraints(mutated)


def test_reject_wrong_version_binding() -> None:
    vectors = build_canonical_vectors()
    fields = dict(vectors.public_fields)
    fields["analyzer_version_field"] = (fields["analyzer_version_field"] + 3) % P_BN254
    openings = dict(vectors.witness_openings)
    openings["open_analyzer_version"] = fields["analyzer_version_field"]
    # step 5 still binds old versions sum
    mutated = _mutate_vectors(
        vectors, public_fields=fields, witness_openings=openings
    )
    with pytest.raises(ProgramContractTraceError, match="binding mismatch"):
        check_circuit_constraints(mutated)


def test_reject_opening_mismatch() -> None:
    vectors = build_canonical_vectors()
    openings = dict(vectors.witness_openings)
    openings["open_forest_commitment"] = (
        openings["open_forest_commitment"] + 1
    ) % P_BN254
    mutated = _mutate_vectors(vectors, witness_openings=openings)
    with pytest.raises(ProgramContractTraceError, match="opening mismatch"):
        check_circuit_constraints(mutated)


def test_reject_padding_ambiguity() -> None:
    vectors = build_canonical_vectors()
    # Use a non-zero kind: KIND_OPEN_FOREST is 0 and collides with the pad value.
    kinds = list(vectors.step_kinds)
    kinds[CANONICAL_TRACE_LENGTH] = KIND_CODES["open_inventory"]
    mutated = _mutate_vectors(vectors, step_kinds=kinds)
    with pytest.raises(ProgramContractTraceError, match="padding ambiguity"):
        check_circuit_constraints(mutated)

    bindings = list(vectors.step_binding_fields)
    bindings[MAX_TRACE_STEPS - 1] = 1
    mutated = _mutate_vectors(vectors, step_binding_fields=bindings)
    with pytest.raises(ProgramContractTraceError, match="padding ambiguity"):
        check_circuit_constraints(mutated)

    states = list(vectors.step_source_states)
    states[CANONICAL_TRACE_LENGTH + 1] = STATE_CODES["terminal"]
    mutated = _mutate_vectors(vectors, step_source_states=states)
    with pytest.raises(ProgramContractTraceError, match="padding ambiguity"):
        check_circuit_constraints(mutated)


def test_reject_altered_circuit_identity() -> None:
    vectors = build_canonical_vectors()
    fields = dict(vectors.public_fields)
    fields["circuit_id_field"] = field_element_from_text("circuit:tampered@9")
    openings = dict(vectors.witness_openings)
    openings["open_circuit_id"] = fields["circuit_id_field"]
    bindings = list(vectors.step_binding_fields)
    bindings[7] = _key_identity_binding(fields)
    mutated = _mutate_vectors(
        vectors,
        public_fields=fields,
        witness_openings=openings,
        step_binding_fields=bindings,
    )
    with pytest.raises(ProgramContractTraceError, match="circuit identity"):
        check_circuit_constraints(mutated)


def test_reject_altered_key_identity() -> None:
    vectors = build_canonical_vectors()
    fields = dict(vectors.public_fields)
    fields["proving_key_id_field"] = field_element_from_text("pk:tampered")
    openings = dict(vectors.witness_openings)
    openings["open_proving_key_id"] = fields["proving_key_id_field"]
    # terminate binding still uses old key identity sum
    mutated = _mutate_vectors(
        vectors, public_fields=fields, witness_openings=openings
    )
    with pytest.raises(ProgramContractTraceError, match="binding mismatch"):
        check_circuit_constraints(mutated)


def test_reject_wrong_circuit_version() -> None:
    vectors = build_canonical_vectors()
    with pytest.raises(ProgramContractTraceError, match="circuit_version"):
        check_circuit_constraints(_mutate_vectors(vectors, circuit_version=2))


def test_reject_zeroed_public_commitment() -> None:
    vectors = build_canonical_vectors()
    fields = dict(vectors.public_fields)
    fields["result_commitment_field"] = 0
    openings = dict(vectors.witness_openings)
    openings["open_result_commitment"] = 0
    bindings = list(vectors.step_binding_fields)
    bindings[6] = 0
    mutated = _mutate_vectors(
        vectors,
        public_fields=fields,
        witness_openings=openings,
        step_binding_fields=bindings,
    )
    with pytest.raises(ProgramContractTraceError, match="zeroed public commitment"):
        check_circuit_constraints(mutated)


def test_non_claims_are_documented() -> None:
    for claim in (
        "inventory_completeness",
        "translator_soundness",
        "arbitrary_runtime_semantics",
        "general_function_call_semantics",
        "theorem_beyond_committed_supported_result",
    ):
        assert claim in TRACE_VALIDITY_DOES_NOT_PROVE


# ---------------------------------------------------------------------------
# Toolchain capability (skip without emitting authoritative proofs)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _nargo_available(), reason="nargo toolchain unavailable")
def test_nargo_check_when_toolchain_available() -> None:
    """Structural nargo check only — does not emit an authoritative proof."""

    result = subprocess.run(
        ["nargo", "check"],
        cwd=str(_circuit_dir()),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, (
        "nargo check failed:\nstdout=%s\nstderr=%s"
        % (result.stdout, result.stderr)
    )


def test_toolchain_skip_path_is_explicit_when_nargo_missing() -> None:
    """When nargo is absent, vectors still land and no proof is claimed."""

    vectors = build_canonical_vectors()
    acc = check_circuit_constraints(vectors)
    assert isinstance(acc, int)
    assert 0 <= acc < P_BN254
    # Explicitly document that this path is non-authoritative without nargo prove.
    assert not _nargo_available() or shutil.which("nargo") is not None
    # Never invent proof bytes in this unit suite.
    assert "proof" not in vectors.to_noir_prover_inputs()


def test_vectors_are_json_serializable_ints() -> None:
    import json

    vectors = build_canonical_vectors()
    payload = {
        "public_input_vector": vectors.public_input_vector(),
        "witness": vectors.witness_vector(),
        "public_accumulator": vectors.public_accumulator(),
        "bounds": {
            "max_trace_steps": MAX_TRACE_STEPS,
            "canonical_trace_length": CANONICAL_TRACE_LENGTH,
            "circuit_version": CIRCUIT_VERSION,
            "p_bn254": str(P_BN254),
        },
    }
    encoded = json.dumps(payload, sort_keys=True)
    restored = json.loads(encoded)
    assert restored["public_input_vector"] == vectors.public_input_vector()
    assert restored["witness"]["step_kinds"] == vectors.step_kinds
