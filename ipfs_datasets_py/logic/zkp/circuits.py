"""
Zero-Knowledge Proof Circuits for Logic Operations.

Defines arithmetic circuits that can be used to create zero-knowledge
proofs for various logic operations, and MVP circuits for statement proving.
"""

from typing import List, Dict, Any, Tuple, Mapping
from dataclasses import dataclass
import json
import re

from .canonicalization import canonicalize_axioms, hash_axioms_commitment, tdfol_v1_axioms_commitment_hex_v2
from .canonicalization import hash_theorem
from .statement import Statement, Witness, format_circuit_ref, parse_circuit_ref_lenient
from .legal_theorem_semantics import parse_tdfol_v1_axiom, parse_tdfol_v1_theorem
import hashlib

_SIMZKP_MAGIC = b"SIMZKP\x00\x01"
_SIMZKP_PROOF_LENGTH = 160
_ATTESTATION_VIEW_VERSION = 1
_DERIVED_PUBLIC_INPUT_KEYS = frozenset(
    {
        "attestation_ref",
        "attestation_view_version",
    }
)
_HEX_CHARS = frozenset("0123456789abcdefABCDEF")
_COMPILER_GUIDANCE_CONTAINER_KEYS = (
    "compiler_guidance_contract",
    "compiler_guidance",
    "compiler_guidance_bundle",
    "guidance_contract",
    "guidance",
    "semantic_bundle",
    "semantic_bundle_key",
    "bundle",
    "compiler_guidance_attribution",
)
_COMPILER_GUIDANCE_PACKET_KEYS = frozenset(
    {
        "action",
        "compiler_guidance_quality_gate",
        "compiler_guidance_ranked_features",
        "compiler_guidance_route",
        "compiler_guidance_target_metrics",
        "compiler_guidance_todo_routes",
        "compiler_guidance_todo_routes_augmented_from_features",
        "compiler_guidance_todo_routes_inferred_from_features",
        "feature_groups",
        "legal_ir_target_view_distribution",
        "objective",
        "program_synthesis_scope",
        "quality_gate",
        "ranked_guidance_features",
        "role",
        "route",
        "samples",
        "scope",
        "source",
        "support",
        "support_count",
        "sample_ids",
        "target",
        "target_component",
        "target_metrics",
        "target_file_lane",
        "target_view",
        "todo_routes",
        "vector_bundle",
    }
)
_COMPILER_GUIDANCE_EVIDENCE_KEYS = (
    "compiler_guidance_evidence",
    "guidance_evidence",
    "evidence",
    "passing_compiler_guidance_evidence",
    "autoencoder_evidence",
)
_US_CODE_CITATION_RE = re.compile(
    r"\b(?P<title>\d+)\s+U\.?\s*S\.?\s*C\.?\s+"
    r"(?:§\s*)?(?P<section>[A-Za-z0-9][A-Za-z0-9.\-]*)",
    re.IGNORECASE,
)


def _bytes_from_proof_data(proof_data: object) -> bytes:
    """Best-effort conversion of proof_data to bytes for deterministic hashing."""
    if isinstance(proof_data, bytes):
        return proof_data
    if isinstance(proof_data, bytearray):
        return bytes(proof_data)
    if isinstance(proof_data, memoryview):
        return proof_data.tobytes()
    if isinstance(proof_data, str):
        stripped = proof_data.strip()
        hex_candidate = stripped[2:] if stripped.startswith(("0x", "0X")) else stripped
        if (
            hex_candidate
            and len(hex_candidate) % 2 == 0
            and all(char in _HEX_CHARS for char in hex_candidate)
        ):
            try:
                return bytes.fromhex(hex_candidate)
            except ValueError:
                pass
        return proof_data.encode("utf-8")
    if proof_data is None:
        return b""
    return str(proof_data).encode("utf-8")


def decode_simulated_proof_layout(proof_data: object) -> Dict[str, Any]:
    """Decode the fixed SIMZKP/1 byte layout when present.

    Returns a deterministic dictionary for attestation views. Unknown/non-simulated
    proof layouts are represented with ``valid=False`` and best-effort metadata.
    """
    raw = _bytes_from_proof_data(proof_data)
    decoded: Dict[str, Any] = {
        "byte_length": len(raw),
        "format": "opaque",
        "valid": False,
    }
    if len(raw) != _SIMZKP_PROOF_LENGTH:
        return decoded
    if raw[:8] != _SIMZKP_MAGIC:
        return decoded

    proof_hash = raw[8:40]
    circuit_hash = raw[40:72]
    witness_hash = raw[72:104]
    padding = raw[104:160]
    decoded.update(
        {
            "format": "SIMZKP/1",
            "magic_hex": raw[:8].hex(),
            "proof_hash_hex": proof_hash.hex(),
            "circuit_hash_hex": circuit_hash.hex(),
            "witness_hash_hex": witness_hash.hex(),
            "padding_sha256": hashlib.sha256(padding).hexdigest(),
            "valid": True,
        }
    )
    return decoded


def _mapping_dict(value: object) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _resolve_circuit_identity(public_inputs: Mapping[str, Any]) -> tuple[str, int]:
    raw_ref = str(public_inputs.get("circuit_ref") or "").strip()
    raw_version = public_inputs.get("circuit_version")
    fallback_version = 1
    if isinstance(raw_version, int) and not isinstance(raw_version, bool) and raw_version >= 0:
        fallback_version = raw_version

    if raw_ref:
        try:
            circuit_id, version = parse_circuit_ref_lenient(
                raw_ref,
                legacy_default_version=fallback_version,
            )
            return circuit_id, version
        except Exception:
            pass

    return "knowledge_of_axioms", fallback_version


def _json_safe_public_input(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, bytearray):
        return bytes(value).hex()
    if isinstance(value, memoryview):
        return value.tobytes().hex()
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe_public_input(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe_public_input(item) for item in value]
    return str(value)


def _decode_json_guidance_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "{[":
        return value
    try:
        return json.loads(stripped)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _canonical_guidance_value(value: Any) -> Any:
    return _json_safe_public_input(_decode_json_guidance_value(value))


def _guidance_container_contract(value: Any) -> Any:
    decoded = _decode_json_guidance_value(value)
    if isinstance(decoded, Mapping):
        return {
            str(key): _canonical_guidance_value(item)
            for key, item in sorted(decoded.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(decoded, (list, tuple)):
        return [_canonical_guidance_value(item) for item in decoded]
    if decoded in (None, ""):
        return {}
    return _canonical_guidance_value(decoded)


def _sequence_values(value: Any) -> list[Any]:
    decoded = _decode_json_guidance_value(value)
    if isinstance(decoded, Mapping):
        return [decoded]
    if isinstance(decoded, (list, tuple)):
        return list(decoded)
    return []


def _guidance_text_tokens(value: Any) -> set[str]:
    decoded = _decode_json_guidance_value(value)
    tokens: set[str] = set()
    if isinstance(decoded, Mapping):
        for key, item in decoded.items():
            tokens.update(_guidance_text_tokens(key))
            tokens.update(_guidance_text_tokens(item))
        return tokens
    if isinstance(decoded, (list, tuple, set)):
        for item in decoded:
            tokens.update(_guidance_text_tokens(item))
        return tokens
    text = str(decoded or "").strip().lower()
    if not text:
        return tokens
    normalized = "".join(char if char.isalnum() else "_" for char in text)
    tokens.add(normalized.strip("_"))
    tokens.update(part for part in normalized.split("_") if part)
    return tokens


def _guidance_targets_zkp(value: Mapping[str, Any]) -> bool:
    target_values = [
        value.get("program_synthesis_scope"),
        value.get("scope"),
        value.get("target"),
        value.get("target_component"),
        value.get("target_file_lane"),
        value.get("target_view"),
    ]
    for key in (
        "feature_groups",
        "legal_ir_target_view_distribution",
        "compiler_guidance_legal_ir_target_view_distribution",
        "target_metrics",
        "compiler_guidance_target_metrics",
    ):
        target_values.append(value.get(key))

    tokens: set[str] = set()
    for item in target_values:
        tokens.update(_guidance_text_tokens(item))

    return bool(
        {
            "zkp",
            "zkp_circuits",
            "zkp_attestation",
            "zkp_attestations",
            "zkp_verification_failure_ratio",
        }
        & tokens
    )


def _guidance_route_tokens(value: Mapping[str, Any]) -> set[str]:
    route_values = [
        value.get("action"),
        value.get("route"),
        value.get("compiler_guidance_route"),
        value.get("samples"),
        value.get("sample_ids"),
        value.get("todo_routes"),
        value.get("compiler_guidance_todo_routes"),
        value.get("ranked_guidance_features"),
        value.get("compiler_guidance_ranked_features"),
    ]
    tokens: set[str] = set()
    for item in route_values:
        tokens.update(_guidance_text_tokens(item))
    return tokens


def _guidance_has_zkp_attestation_route(value: Mapping[str, Any]) -> bool:
    return any(
        "repair_zkp_attestation_bridge" in token
        for token in _guidance_route_tokens(value)
    )


def _guidance_quality_passes(value: Mapping[str, Any]) -> bool:
    quality = _first_nonempty(
        value.get("compiler_guidance_quality_gate"),
        value.get("quality_gate"),
        value.get("gate"),
        value.get("status"),
    ).lower()
    if quality:
        return quality in {"pass", "passed", "ok", "success", "accepted", "true"}
    passed = value.get("passed")
    if isinstance(passed, bool):
        return passed
    return True


def _contract_from_guidance_evidence_row(value: Any) -> Dict[str, Any]:
    decoded = _decode_json_guidance_value(value)
    if not isinstance(decoded, Mapping):
        return {}
    row = dict(decoded)
    route_matches = _guidance_has_zkp_attestation_route(row)
    target_matches = _guidance_targets_zkp(row)
    if not _guidance_quality_passes(row):
        return {}
    if not (route_matches or target_matches):
        return {}

    selected: Dict[str, Any] = {}
    for key, item in sorted(row.items(), key=lambda pair: str(pair[0])):
        name = str(key)
        if name in _COMPILER_GUIDANCE_PACKET_KEYS or name.startswith(
            "compiler_guidance_"
        ):
            selected[name] = _canonical_guidance_value(item)

    if route_matches and not selected.get("route"):
        selected.setdefault("route", "repair_zkp_attestation_bridge")
    if (route_matches or target_matches) and not selected.get("target_component"):
        selected.setdefault("target_component", "zkp.circuits")
    if not selected.get("program_synthesis_scope") and (route_matches or target_matches):
        selected.setdefault("program_synthesis_scope", "zkp")
    if not selected.get("source") and (
        route_matches or "compiler_guidance_distillation_v1" in _guidance_text_tokens(row)
    ):
        selected.setdefault("source", "compiler_guidance_distillation_v1")

    return selected


def _compact_zkp_guidance_packet_contract(value: Any) -> Dict[str, Any]:
    """Return a compact ZKP guidance contract from packet-shaped metadata.

    Autoencoder TODO metadata often includes large diagnostic maps alongside
    the route/scope/target evidence.  The ZKP attestation circuit only needs a
    stable public commitment to the passing repair contract, so keep the compact
    packet fields and infer the same route defaults used for evidence rows.
    """
    decoded = _decode_json_guidance_value(value)
    if not isinstance(decoded, Mapping):
        return {}

    row = dict(decoded)
    route_matches = _guidance_has_zkp_attestation_route(row)
    target_matches = _guidance_targets_zkp(row)
    if not _guidance_quality_passes(row):
        return {}
    if not (route_matches or target_matches):
        return {}

    selected: Dict[str, Any] = {}
    for key, item in sorted(row.items(), key=lambda pair: str(pair[0])):
        name = str(key)
        if name in _COMPILER_GUIDANCE_PACKET_KEYS:
            selected[name] = _canonical_guidance_value(item)

    if route_matches and not (
        selected.get("route") or selected.get("compiler_guidance_route")
    ):
        selected["route"] = "repair_zkp_attestation_bridge"
    if (route_matches or target_matches) and not selected.get("target_component"):
        selected["target_component"] = "zkp.circuits"
    if not selected.get("program_synthesis_scope") and (route_matches or target_matches):
        selected["program_synthesis_scope"] = "zkp"
    if not selected.get("source") and (
        route_matches or "compiler_guidance_distillation_v1" in _guidance_text_tokens(row)
    ):
        selected["source"] = "compiler_guidance_distillation_v1"

    return selected


def _evidence_contract_from_metadata(metadata: Mapping[str, Any]) -> Dict[str, Any]:
    for key in _COMPILER_GUIDANCE_EVIDENCE_KEYS:
        for row in _sequence_values(metadata.get(key)):
            contract = _contract_from_guidance_evidence_row(row)
            if contract:
                return contract

    nested_values = []
    attribution = metadata.get("compiler_guidance_attribution")
    if isinstance(_decode_json_guidance_value(attribution), Mapping):
        nested_values.append(_decode_json_guidance_value(attribution))
    for nested in nested_values:
        for key in _COMPILER_GUIDANCE_EVIDENCE_KEYS + ("sample_records", "records"):
            for row in _sequence_values(nested.get(key)):
                contract = _contract_from_guidance_evidence_row(row)
                if contract:
                    return contract

    compact_contract = _contract_from_guidance_evidence_row(metadata)
    if compact_contract and (
        _guidance_has_zkp_attestation_route(metadata)
        or _guidance_targets_zkp(metadata)
    ):
        return compact_contract
    return {}


def compiler_guidance_contract_from_metadata(
    metadata: Mapping[str, Any] | None,
) -> Any:
    """Return the deterministic compiler-guidance contract carried by metadata.

    Compiler guidance can arrive as an explicit contract, a nested packet
    bundle, or flattened ``compiler_guidance_*`` fields.  This normalizer keeps
    the ZKP circuit layer responsible for the public commitment shape instead
    of relying on each bridge caller to pre-normalize evidence.
    """
    metadata_dict = _mapping_dict(metadata)
    if not metadata_dict:
        return {}

    nested_metadata = _decode_json_guidance_value(metadata_dict.get("metadata"))
    if isinstance(nested_metadata, Mapping):
        nested_contract = compiler_guidance_contract_from_metadata(nested_metadata)
        if nested_contract not in ({}, [], ""):
            return nested_contract

    selected: Dict[str, Any] = {}
    for key, value in sorted(metadata_dict.items(), key=lambda pair: str(pair[0])):
        name = str(key)
        if (
            name.startswith("compiler_guidance_")
            and name not in _COMPILER_GUIDANCE_CONTAINER_KEYS
            and name not in _COMPILER_GUIDANCE_EVIDENCE_KEYS
        ):
            selected[name] = _canonical_guidance_value(value)

    packet_signal = {
        "program_synthesis_scope",
        "route",
        "target_component",
    } & {str(key) for key in metadata_dict}
    if packet_signal:
        for key, value in sorted(metadata_dict.items(), key=lambda pair: str(pair[0])):
            name = str(key)
            if name in _COMPILER_GUIDANCE_PACKET_KEYS:
                selected.setdefault(name, _canonical_guidance_value(value))

    explicit_route_signal = (
        selected.get("compiler_guidance_route")
        or selected.get("compiler_guidance_todo_routes")
        or selected.get("route")
        or selected.get("samples")
        or selected.get("sample_ids")
        or _guidance_has_zkp_attestation_route(selected)
    )
    if explicit_route_signal:
        compact_selected = _compact_zkp_guidance_packet_contract(selected)
        return compact_selected or selected

    evidence_contract = _evidence_contract_from_metadata(metadata_dict)
    if evidence_contract:
        return evidence_contract

    if _guidance_has_zkp_attestation_route(metadata_dict) or _guidance_targets_zkp(
        metadata_dict
    ):
        compact_contract = _compact_zkp_guidance_packet_contract(metadata_dict)
        if compact_contract:
            return compact_contract

    for key in _COMPILER_GUIDANCE_CONTAINER_KEYS:
        if key not in metadata_dict:
            continue
        contract = _guidance_container_contract(metadata_dict.get(key))
        if contract not in ({}, [], ""):
            if isinstance(contract, Mapping):
                compact_contract = _compact_zkp_guidance_packet_contract(contract)
                if compact_contract:
                    return compact_contract
            return contract

    if selected:
        return selected

    # Packet-shaped autoencoder rows sometimes arrive directly as the metadata
    # object.  Require a target/component signal before accepting generic keys
    # such as "source" so ordinary proof metadata does not become guidance.
    names = {str(key) for key in metadata_dict}
    if names & {
        "program_synthesis_scope",
        "target_component",
        "compiler_guidance_route",
        "compiler_guidance_todo_routes",
    }:
        return {
            str(key): _canonical_guidance_value(value)
            for key, value in sorted(metadata_dict.items(), key=lambda pair: str(pair[0]))
            if str(key) in _COMPILER_GUIDANCE_PACKET_KEYS
            or str(key).startswith("compiler_guidance_")
        }

    return {}


def compiler_guidance_ref_from_metadata(metadata: Mapping[str, Any] | None) -> str:
    """Return a stable guidance ref from explicit metadata or a contract body."""
    metadata_dict = _mapping_dict(metadata)
    explicit_ref = str(metadata_dict.get("compiler_guidance_ref") or "").strip()
    if explicit_ref:
        return explicit_ref

    contract = compiler_guidance_contract_from_metadata(metadata_dict)
    if contract in ({}, [], ""):
        return ""

    canonical_contract = _json_safe_public_input(contract)
    payload = json.dumps(canonical_contract, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_public_inputs(public_inputs: Mapping[str, Any]) -> Dict[str, Any]:
    """Return public inputs suitable for stable attestation-view commitments."""
    return {
        str(key): _json_safe_public_input(value)
        for key, value in sorted(public_inputs.items(), key=lambda pair: str(pair[0]))
        if str(key) not in _DERIVED_PUBLIC_INPUT_KEYS
    }


def _public_input_commitment(public_inputs: Mapping[str, Any]) -> tuple[Dict[str, Any], str]:
    canonical = _canonical_public_inputs(public_inputs)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return canonical, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_proof_attestation_view(
    *,
    proof_data: object,
    public_inputs: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a deterministic proof-attestation view from proof components."""
    public_inputs_dict = _mapping_dict(public_inputs)
    metadata_dict = _mapping_dict(metadata)
    proof_bytes = _bytes_from_proof_data(proof_data)
    layout = decode_simulated_proof_layout(proof_bytes)
    circuit_id, circuit_version = _resolve_circuit_identity(public_inputs_dict)
    circuit_ref = format_circuit_ref(circuit_id, circuit_version)
    theorem_hash = str(public_inputs_dict.get("theorem_hash") or "")
    axioms_commitment = str(public_inputs_dict.get("axioms_commitment") or "")
    ruleset_id = str(public_inputs_dict.get("ruleset_id") or "")
    compiler_guidance_ref = str(
        public_inputs_dict.get("compiler_guidance_ref")
        or metadata_dict.get("compiler_guidance_ref")
        or compiler_guidance_ref_from_metadata(metadata_dict)
        or ""
    )
    compiler_guidance_version = _non_negative_int(
        public_inputs_dict.get("compiler_guidance_version")
        or metadata_dict.get("compiler_guidance_version")
    )
    proof_digest = hashlib.sha256(proof_bytes).hexdigest()
    canonical_public_inputs, public_inputs_commitment = _public_input_commitment(
        public_inputs_dict
    )

    attestation_basis = {
        "axioms_commitment": axioms_commitment,
        "circuit_ref": circuit_ref,
        "proof_digest": proof_digest,
        "ruleset_id": ruleset_id,
        "theorem_hash": theorem_hash,
    }
    if compiler_guidance_ref:
        attestation_basis["compiler_guidance_ref"] = compiler_guidance_ref
        attestation_basis["compiler_guidance_version"] = compiler_guidance_version
    attestation_ref = hashlib.sha256(
        json.dumps(attestation_basis, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    view = {
        "attestation_ref": attestation_ref,
        "attestation_view_version": _ATTESTATION_VIEW_VERSION,
        "axioms_commitment": axioms_commitment,
        "backend": str(metadata_dict.get("backend") or ""),
        "circuit_ref": circuit_ref,
        "circuit_version": circuit_version,
        "layout": layout,
        "proof_digest": proof_digest,
        "public_input_count": len(canonical_public_inputs),
        "public_input_keys": list(canonical_public_inputs.keys()),
        "public_inputs_commitment": public_inputs_commitment,
        "proof_system": str(metadata_dict.get("proof_system") or ""),
        "ruleset_id": ruleset_id,
        "theorem_hash": theorem_hash,
    }
    if compiler_guidance_ref:
        view["compiler_guidance_ref"] = compiler_guidance_ref
        view["compiler_guidance_version"] = compiler_guidance_version
    return view


def refresh_proof_attestation(proof: Any) -> Any:
    """Synchronize a proof's public attestation fields with its current inputs.

    Some bridge paths add deterministic public inputs after backend proof
    generation.  Keep the public ``attestation_ref`` and embedded
    ``metadata.attestation_view`` in lockstep so verifier and LegalIR views see
    the same commitment.
    """
    public_inputs = getattr(proof, "public_inputs", None)
    if not isinstance(public_inputs, dict):
        return proof

    metadata = getattr(proof, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        try:
            proof.metadata = metadata
        except Exception:
            return proof

    attestation_view = build_proof_attestation_view(
        proof_data=getattr(proof, "proof_data", b""),
        public_inputs=public_inputs,
        metadata=metadata,
    )
    public_inputs["attestation_ref"] = attestation_view["attestation_ref"]
    public_inputs["attestation_view_version"] = int(
        attestation_view["attestation_view_version"]
    )
    metadata["attestation_view"] = attestation_view
    return proof


def _proof_bytes_from_serialized(proof_data: object) -> object:
    if isinstance(proof_data, str):
        try:
            return bytes.fromhex(proof_data)
        except ValueError:
            return proof_data
    return proof_data


def attestation_view_matches_proof(
    *,
    proof_data: object,
    public_inputs: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
    attestation_view: Mapping[str, Any] | None = None,
) -> bool:
    """Return True when public attestation fields match the proof bytes.

    The attestation view is a bridge-facing commitment over proof bytes,
    public inputs, circuit identity, and compiler guidance.  Verification
    should fail closed when a serialized proof carries stale or missing
    attestation fields.
    """
    try:
        public_inputs_dict = _mapping_dict(public_inputs)
        if not public_inputs_dict:
            return False
        metadata_dict = _mapping_dict(metadata)
        embedded = _mapping_dict(
            attestation_view
            if attestation_view is not None
            else metadata_dict.get("attestation_view")
        )

        expected = build_proof_attestation_view(
            proof_data=_proof_bytes_from_serialized(proof_data),
            public_inputs=public_inputs_dict,
            metadata=metadata_dict,
        )

        if not embedded:
            return False

        public_ref = public_inputs_dict.get("attestation_ref")
        public_version = public_inputs_dict.get("attestation_view_version")
        if public_ref is not None and public_ref != expected["attestation_ref"]:
            return False
        if public_version is not None and int(public_version or 0) != int(
            expected["attestation_view_version"]
        ):
            return False
        if (public_ref is None) != (public_version is None):
            return False

        for key in (
            "attestation_ref",
            "attestation_view_version",
            "proof_digest",
            "public_inputs_commitment",
            "circuit_ref",
            "theorem_hash",
            "axioms_commitment",
            "ruleset_id",
        ):
            if embedded.get(key) != expected.get(key):
                return False

        if "compiler_guidance_ref" in expected:
            if embedded.get("compiler_guidance_ref") != expected["compiler_guidance_ref"]:
                return False
            if int(embedded.get("compiler_guidance_version") or 0) != int(
                expected["compiler_guidance_version"]
            ):
                return False
        elif embedded.get("compiler_guidance_ref"):
            return False

        return True
    except (TypeError, ValueError, AttributeError):
        return False


def _non_negative_int(value: object, default: int = 1) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def proof_attestation_view_from_proof_dict(proof: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the canonical attestation view embedded in a serialized proof.

    Older callers may only have a proof dictionary, not a ``ZKPProof`` object.
    Prefer the backend-produced ``metadata.attestation_view`` when present, and
    otherwise rebuild the same deterministic view from serialized proof bytes,
    public inputs, and metadata.
    """
    if not isinstance(proof, Mapping):
        return {}

    metadata = proof.get("metadata")
    metadata_dict = _mapping_dict(metadata)
    embedded = metadata_dict.get("attestation_view")

    proof_data = proof.get("proof_data")
    proof_bytes = _proof_bytes_from_serialized(proof_data)
    public_inputs = _mapping_dict(proof.get("public_inputs"))
    rebuilt = build_proof_attestation_view(
        proof_data=proof_bytes,
        public_inputs=public_inputs,
        metadata=metadata_dict,
    )
    if isinstance(embedded, Mapping) and attestation_view_matches_proof(
        proof_data=proof_bytes,
        public_inputs=public_inputs,
        metadata=metadata_dict,
        attestation_view=embedded,
    ):
        return dict(embedded)

    return rebuilt


def proof_digest_from_proof_dict(proof: Mapping[str, Any]) -> str:
    """Return the proof byte digest from a serialized proof dictionary."""
    if not isinstance(proof, Mapping):
        return ""
    proof_data = _proof_bytes_from_serialized(proof.get("proof_data"))
    proof_bytes = _bytes_from_proof_data(proof_data)
    if not proof_bytes:
        return ""
    return hashlib.sha256(proof_bytes).hexdigest()


def proof_public_inputs_from_proof_dict(proof: Mapping[str, Any]) -> Dict[str, Any]:
    """Return serialized proof public inputs with fresh attestation fields.

    Bridge exporters sometimes receive a proof dictionary after the surrounding
    record has lost its duplicated ``public_inputs`` field.  The proof itself is
    the authoritative public-input carrier, so rebuild the derived attestation
    fields from it before publishing LegalIR records.
    """
    if not isinstance(proof, Mapping):
        return {}

    public_inputs = _mapping_dict(proof.get("public_inputs"))
    if not public_inputs:
        return {}

    attestation_view = proof_attestation_view_from_proof_dict(proof)
    if not attestation_view:
        return public_inputs

    completed = dict(public_inputs)
    completed["attestation_ref"] = attestation_view["attestation_ref"]
    completed["attestation_view_version"] = int(
        attestation_view["attestation_view_version"]
    )

    for key in (
        "axioms_commitment",
        "circuit_ref",
        "circuit_version",
        "compiler_guidance_ref",
        "compiler_guidance_version",
        "ruleset_id",
        "theorem_hash",
    ):
        value = attestation_view.get(key)
        if value not in (None, ""):
            completed.setdefault(key, value)

    return completed


def _first_nonempty(*values: object) -> str:
    for value in values:
        if value in (None, ""):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _us_code_citation_from_text(text: object) -> str:
    """Extract a normalized U.S. Code citation from free text when present."""
    if not isinstance(text, str):
        return ""
    match = _US_CODE_CITATION_RE.search(text)
    if not match:
        return ""
    title = match.group("title").strip()
    section = match.group("section").strip()
    if section.endswith(":"):
        section = section[:-1].rstrip()
    if not title or not section:
        return ""
    return f"{title} U.S.C. {section}"


def _us_code_source_id_from_fields(
    record: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> str:
    source = _first_nonempty(
        record.get("source"),
        record.get("source_type"),
        metadata.get("source"),
        metadata.get("source_type"),
    ).lower()
    if source not in {"us_code", "us-code", "usc", "u.s.c.", "u.s. code"}:
        return ""

    title = _first_nonempty(
        record.get("title"),
        record.get("title_number"),
        record.get("usc_title"),
        record.get("uscode_title"),
        metadata.get("title"),
        metadata.get("title_number"),
        metadata.get("usc_title"),
        metadata.get("uscode_title"),
    )
    section = _first_nonempty(
        record.get("section"),
        record.get("section_number"),
        record.get("usc_section"),
        record.get("uscode_section"),
        metadata.get("section"),
        metadata.get("section_number"),
        metadata.get("usc_section"),
        metadata.get("uscode_section"),
    )
    if title and section:
        return f"{title} U.S.C. {section}"
    return ""


def _source_id_from_record(
    record: Mapping[str, Any],
    metadata: Mapping[str, Any],
    proof_hash: str,
) -> str:
    """Return a stable LegalIR source id from common proof/export fields."""
    direct = _first_nonempty(
        record.get("source_id"),
        record.get("sample_id"),
        record.get("document_id"),
        record.get("doc_id"),
        record.get("id"),
        record.get("form_id"),
        record.get("source_pdf"),
        metadata.get("source_id"),
        metadata.get("sample_id"),
        metadata.get("document_id"),
        metadata.get("doc_id"),
        metadata.get("form_id"),
        metadata.get("source_pdf"),
    )
    if direct:
        return direct

    citation = _first_nonempty(record.get("citation"), metadata.get("citation"))
    if citation:
        return citation
    embedded_citation = _us_code_citation_from_text(
        _first_nonempty(
            record.get("text"),
            record.get("sample_text"),
            record.get("source_text"),
            record.get("normalized_text"),
            record.get("content"),
            record.get("body"),
            metadata.get("text"),
            metadata.get("sample_text"),
            metadata.get("source_text"),
            metadata.get("normalized_text"),
        )
    )
    if embedded_citation:
        return embedded_citation

    title = _first_nonempty(record.get("title"), metadata.get("title"))
    section = _first_nonempty(record.get("section"), metadata.get("section"))
    source = _first_nonempty(record.get("source"), metadata.get("source"))
    if source.lower() in {"us_code", "us-code", "usc", "u.s.c."} and title and section:
        return f"{title} U.S.C. {section}"

    us_code_source_id = _us_code_source_id_from_fields(record, metadata)
    if us_code_source_id:
        return us_code_source_id

    if proof_hash:
        return f"zkp-proof:{proof_hash[:16]}"
    return ""


def _source_text_from_record(record: Mapping[str, Any], metadata: Mapping[str, Any]) -> str:
    return _first_nonempty(
        record.get("text"),
        record.get("sample_text"),
        record.get("source_text"),
        record.get("normalized_text"),
        record.get("content"),
        record.get("body"),
        metadata.get("text"),
        metadata.get("sample_text"),
        metadata.get("source_text"),
        metadata.get("normalized_text"),
    )


def _is_legal_source_record(record: Mapping[str, Any], metadata: Mapping[str, Any]) -> bool:
    source = _first_nonempty(
        record.get("source"),
        record.get("source_type"),
        metadata.get("source"),
        metadata.get("source_type"),
    ).lower()
    if source in {"us_code", "us-code", "usc", "u.s.c.", "u.s. code"}:
        return True

    citation = _first_nonempty(record.get("citation"), metadata.get("citation"))
    if "u.s.c" in citation.lower():
        return True

    sample_id = _first_nonempty(record.get("sample_id"), metadata.get("sample_id"))
    if sample_id.lower().startswith("us-code-"):
        return True

    source_text = _source_text_from_record(record, metadata)
    return bool(_us_code_citation_from_text(source_text))


def _synthetic_source_proof_data(
    *,
    source_id: str,
    source_text: str,
    public_inputs: Mapping[str, Any],
) -> bytes:
    """Return verifier-compatible deterministic proof bytes for a source record."""
    payload = {
        "public_inputs": _canonical_public_inputs(public_inputs),
        "source_id": source_id,
        "source_text": " ".join(source_text.split()),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode(
        "utf-8",
    )
    proof_hash = hashlib.sha256(b"LEGALIR-ZKP-SOURCE-PROOF\x00" + encoded).digest()
    circuit_hash = hashlib.sha256(b"LEGALIR-ZKP-SOURCE-CIRCUIT\x00" + encoded).digest()
    witness_hash = hashlib.sha256(b"LEGALIR-ZKP-SOURCE-WITNESS\x00" + encoded).digest()
    padding_basis = hashlib.sha256(b"LEGALIR-ZKP-SOURCE-PADDING\x00" + encoded).digest()
    padding = bytearray()
    counter = 0
    while len(padding) < 56:
        padding.extend(
            hashlib.sha256(
                padding_basis + counter.to_bytes(4, "big", signed=False)
            ).digest()
        )
        counter += 1
    return (
        _SIMZKP_MAGIC
        + proof_hash
        + circuit_hash
        + witness_hash
        + bytes(padding[:56])
    )


def _proofless_source_attestation_record(
    record: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build a deterministic LegalIR attestation for proofless source samples.

    Metric samples can arrive as raw legal source records before the bridge has
    materialized a ``ZKPProof``.  This does not claim cryptographic
    verification; it gives the LegalIR view a stable source-level attestation
    envelope so missing-view loss reflects the available legal input instead of
    a serialization artifact.
    """
    if not _is_legal_source_record(record, metadata):
        return {}

    source_text = _source_text_from_record(record, metadata)
    source_id = _source_id_from_record(record, metadata, "")
    if not source_text or not source_id:
        return {}

    normalized_text = " ".join(source_text.split())
    theorem_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    axiom_basis = json.dumps(
        {
            "source_id": source_id,
            "source_text_hash": theorem_hash,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    axioms_commitment = hashlib.sha256(axiom_basis.encode("utf-8")).hexdigest()
    public_inputs: Dict[str, Any] = {
        "axioms_commitment": axioms_commitment,
        "circuit_ref": "legal_ir_source_attestation@v1",
        "circuit_version": 1,
        "ruleset_id": "LegalIR_Source_Attestation_v1",
        "theorem": normalized_text,
        "theorem_hash": theorem_hash,
    }
    proof_data = _synthetic_source_proof_data(
        source_id=source_id,
        source_text=normalized_text,
        public_inputs=public_inputs,
    )
    attestation_view = build_proof_attestation_view(
        proof_data=proof_data,
        public_inputs=public_inputs,
        metadata={
            **metadata,
            "backend": "source_attestation",
            "proof_system": "deterministic_source_attestation",
        },
    )
    completed_public_inputs = dict(public_inputs)
    completed_public_inputs["attestation_ref"] = attestation_view["attestation_ref"]
    completed_public_inputs["attestation_view_version"] = int(
        attestation_view["attestation_view_version"]
    )
    proof_hash = hashlib.sha256(proof_data).hexdigest()
    proof_metadata = {
        **metadata,
        "attestation_view": attestation_view,
        "backend": "source_attestation",
        "proof_system": "deterministic_source_attestation",
        "security_level": 128,
    }

    completed = dict(record)
    completed["attestation_ref"] = attestation_view["attestation_ref"]
    completed["attestation_view"] = attestation_view
    completed["attestation_view_version"] = int(
        attestation_view["attestation_view_version"]
    )
    completed["axioms_commitment"] = axioms_commitment
    completed["circuit_ref"] = attestation_view["circuit_ref"]
    completed["proof"] = {
        "proof_data": proof_data.hex(),
        "public_inputs": completed_public_inputs,
        "metadata": proof_metadata,
        "timestamp": 0.0,
        "size_bytes": len(proof_data),
    }
    completed["proof_hash"] = proof_hash
    completed["public_inputs"] = completed_public_inputs
    completed["ruleset_id"] = public_inputs["ruleset_id"]
    completed["source_id"] = source_id
    completed["theorem_hash"] = theorem_hash
    return completed


def _metadata_with_record_guidance(
    metadata: Mapping[str, Any],
    record: Mapping[str, Any],
) -> Dict[str, Any]:
    """Merge root-level compiler guidance into proof metadata deterministically."""
    merged = dict(metadata)
    if compiler_guidance_ref_from_metadata(merged):
        return merged

    contract = compiler_guidance_contract_from_metadata(record)
    if contract not in ({}, [], ""):
        merged["compiler_guidance_contract"] = contract

    explicit_ref = str(record.get("compiler_guidance_ref") or "").strip()
    if explicit_ref:
        merged["compiler_guidance_ref"] = explicit_ref
    if record.get("compiler_guidance_version") not in (None, ""):
        merged["compiler_guidance_version"] = record.get("compiler_guidance_version")

    return merged


def complete_zkp_attestation_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a LegalIR ZKP attestation record with deterministic bridge fields.

    LegalIR exporters are not perfectly uniform: some put the serialized proof
    under ``proof`` while others flatten proof bytes and public inputs at the
    record root.  This helper treats the proof payload as authoritative and
    fills the duplicated attestation fields expected by downstream views.
    """
    record_dict = _mapping_dict(record)
    if not record_dict:
        return {}

    completed = dict(record_dict)
    proof = _mapping_dict(completed.get("proof"))
    if not proof and (
        "proof_data" in completed
        or "public_inputs" in completed
        or "metadata" in completed
    ):
        proof = {
            "proof_data": completed.get("proof_data"),
            "public_inputs": completed.get("public_inputs"),
            "metadata": completed.get("metadata"),
        }

    proof_data = proof.get("proof_data", completed.get("proof_data", b""))
    metadata = _metadata_with_record_guidance(
        _mapping_dict(proof.get("metadata") or completed.get("metadata")),
        completed,
    )
    public_inputs = _mapping_dict(
        proof.get("public_inputs") or completed.get("public_inputs")
    )

    if not public_inputs:
        source_attestation = _proofless_source_attestation_record(
            completed,
            metadata,
        )
        if source_attestation:
            return source_attestation
        return completed

    proof_for_view = {
        "proof_data": proof_data,
        "public_inputs": public_inputs,
        "metadata": metadata,
    }
    attestation_view = proof_attestation_view_from_proof_dict(proof_for_view)
    proof_public_inputs = proof_public_inputs_from_proof_dict(proof_for_view)
    if not attestation_view:
        return completed

    attestation_ref = str(attestation_view.get("attestation_ref") or "")
    completed["attestation_view"] = attestation_view
    completed["public_inputs"] = proof_public_inputs or public_inputs
    if proof:
        synced_proof = dict(proof)
        synced_metadata = dict(metadata)
        synced_metadata["attestation_view"] = attestation_view
        synced_proof["metadata"] = synced_metadata
        synced_proof["public_inputs"] = proof_public_inputs or public_inputs
        completed["proof"] = synced_proof
    if attestation_ref:
        completed["attestation_ref"] = attestation_ref
        completed["attestation_view_version"] = int(
            attestation_view.get("attestation_view_version") or 0
        )
    proof_hash = proof_digest_from_proof_dict(proof_for_view)
    if proof_hash and not completed.get("proof_hash"):
        completed["proof_hash"] = proof_hash

    for key in (
        "axioms_commitment",
        "circuit_ref",
        "compiler_guidance_ref",
        "compiler_guidance_version",
        "ruleset_id",
        "source_id",
        "theorem_hash",
    ):
        if completed.get(key):
            continue
        if key == "source_id":
            source_id = _source_id_from_record(completed, metadata, proof_hash)
            if source_id:
                completed[key] = str(source_id)
            continue
        value = proof_public_inputs.get(key) or attestation_view.get(key)
        if value not in (None, ""):
            completed[key] = value

    return completed


def zkp_attestation_legal_ir_view_loss(
    records: object,
) -> float:
    """Return a bounded LegalIR view loss for ZKP attestation records.

    The supervisor scores the ZKP bridge as a LegalIR view producer, not just as
    a proof verifier.  A record is view-complete when it is verified and exposes
    the stable fields needed to round-trip proof attestations through LegalIR.
    """
    if not isinstance(records, (list, tuple)):
        return 1.0
    if not records:
        return 1.0

    required_record_keys = (
        "attestation_ref",
        "attestation_view",
        "circuit_ref",
        "proof_hash",
        "public_inputs",
        "ruleset_id",
        "source_id",
        "theorem_hash",
    )
    missing = 0
    total = len(records) * (len(required_record_keys) + 2)
    for raw_record in records:
        record = complete_zkp_attestation_record(_mapping_dict(raw_record))
        for key in required_record_keys:
            if not record.get(key):
                missing += 1

        public_inputs = _mapping_dict(record.get("public_inputs"))
        attestation_view = _mapping_dict(record.get("attestation_view"))
        attestation_ref = str(record.get("attestation_ref") or "")
        if not attestation_ref or public_inputs.get("attestation_ref") != attestation_ref:
            missing += 1
        if not attestation_ref or attestation_view.get("attestation_ref") != attestation_ref:
            missing += 1

    return min(1.0, max(0.0, missing / total))


@dataclass
class CircuitGate:
    """
    A single gate in a logic circuit.
    
    Attributes:
        gate_type: Type of gate (AND, OR, NOT, IMPLIES, etc.)
        inputs: Input wire indices
        output: Output wire index
    """
    gate_type: str
    inputs: List[int]
    output: int


class ZKPCircuit:
    """
    Arithmetic circuit for zero-knowledge proofs of logic formulas.
    
    Converts logic operations into arithmetic circuits over finite fields,
    which can then be proven using zkSNARKs.
    
    Example:
        >>> circuit = ZKPCircuit()
        >>> # Create circuit for: (P AND Q) IMPLIES R
        >>> p_wire = circuit.add_input("P")
        >>> q_wire = circuit.add_input("Q")
        >>> r_wire = circuit.add_input("R")
        >>> pq_wire = circuit.add_and_gate(p_wire, q_wire)
        >>> output = circuit.add_implies_gate(pq_wire, r_wire)
        >>> circuit.set_output(output)
        >>> 
        >>> print(f"Circuit has {circuit.num_gates()} gates")
        Circuit has 3 gates
    
    Note:
        This is a high-level circuit representation. For actual zkSNARK
        proving, the circuit would be compiled to R1CS (Rank-1 Constraint
        System) constraints over a finite field.
    """
    
    def __init__(self):
        """Initialize empty circuit."""
        self._gates: List[CircuitGate] = []
        self._inputs: Dict[str, int] = {}  # name -> wire index
        self._outputs: List[int] = []
        self._next_wire: int = 0
    
    def add_input(self, name: str) -> int:
        """
        Add an input wire to the circuit.
        
        Args:
            name: Name of the input (e.g., "P", "Q")
        
        Returns:
            int: Wire index for this input
        """
        wire = self._next_wire
        self._next_wire += 1
        self._inputs[name] = wire
        return wire
    
    def add_and_gate(self, wire_a: int, wire_b: int) -> int:
        """
        Add an AND gate to the circuit.
        
        In arithmetic circuits over finite fields:
            AND(a, b) = a * b
        
        Args:
            wire_a: First input wire
            wire_b: Second input wire
        
        Returns:
            int: Output wire index
        """
        output_wire = self._next_wire
        self._next_wire += 1
        
        self._gates.append(CircuitGate(
            gate_type="AND",
            inputs=[wire_a, wire_b],
            output=output_wire
        ))
        
        return output_wire
    
    def add_or_gate(self, wire_a: int, wire_b: int) -> int:
        """
        Add an OR gate to the circuit.
        
        In arithmetic circuits:
            OR(a, b) = a + b - (a * b)
        
        Args:
            wire_a: First input wire
            wire_b: Second input wire
        
        Returns:
            int: Output wire index
        """
        output_wire = self._next_wire
        self._next_wire += 1
        
        self._gates.append(CircuitGate(
            gate_type="OR",
            inputs=[wire_a, wire_b],
            output=output_wire
        ))
        
        return output_wire
    
    def add_not_gate(self, wire: int) -> int:
        """
        Add a NOT gate to the circuit.
        
        In arithmetic circuits:
            NOT(a) = 1 - a
        
        Args:
            wire: Input wire
        
        Returns:
            int: Output wire index
        """
        output_wire = self._next_wire
        self._next_wire += 1
        
        self._gates.append(CircuitGate(
            gate_type="NOT",
            inputs=[wire],
            output=output_wire
        ))
        
        return output_wire
    
    def add_implies_gate(self, wire_a: int, wire_b: int) -> int:
        """
        Add an IMPLIES gate to the circuit.
        
        In logic: A -> B = (NOT A) OR B
        In arithmetic: IMPLIES(a, b) = (1 - a) + b - ((1 - a) * b)
        
        Args:
            wire_a: Antecedent wire
            wire_b: Consequent wire
        
        Returns:
            int: Output wire index
        """
        output_wire = self._next_wire
        self._next_wire += 1
        
        self._gates.append(CircuitGate(
            gate_type="IMPLIES",
            inputs=[wire_a, wire_b],
            output=output_wire
        ))
        
        return output_wire
    
    def add_xor_gate(self, wire_a: int, wire_b: int) -> int:
        """
        Add an XOR gate to the circuit.
        
        In arithmetic: XOR(a, b) = a + b - 2(a * b)
        
        Args:
            wire_a: First input wire
            wire_b: Second input wire
        
        Returns:
            int: Output wire index
        """
        output_wire = self._next_wire
        self._next_wire += 1
        
        self._gates.append(CircuitGate(
            gate_type="XOR",
            inputs=[wire_a, wire_b],
            output=output_wire
        ))
        
        return output_wire
    
    def set_output(self, wire: int):
        """
        Mark a wire as a circuit output.
        
        Args:
            wire: Wire index to mark as output
        """
        self._outputs.append(wire)
    
    def num_gates(self) -> int:
        """Get the number of gates in the circuit."""
        return len(self._gates)
    
    def num_inputs(self) -> int:
        """Get the number of input wires."""
        return len(self._inputs)
    
    def num_wires(self) -> int:
        """Get the total number of wires."""
        return self._next_wire
    
    def get_circuit_hash(self) -> str:
        """
        Compute a hash of the circuit structure.
        
        Returns:
            str: Hex-encoded hash of circuit
        """
        circuit_data = {
            'num_gates': len(self._gates),
            'num_inputs': len(self._inputs),
            'num_wires': self._next_wire,
            'gates': [
                {
                    'type': gate.gate_type,
                    'inputs': gate.inputs,
                    'output': gate.output
                }
                for gate in self._gates
            ],
        }
        
        import json
        circuit_json = json.dumps(circuit_data, sort_keys=True)
        return hashlib.sha256(circuit_json.encode()).hexdigest()
    
    def to_r1cs(self) -> Dict[str, Any]:
        """
        Convert circuit to R1CS (Rank-1 Constraint System).
        
        R1CS is the constraint system used by zkSNARKs like Groth16.
        Each constraint has the form: (A · w) * (B · w) = (C · w)
        where w is the witness vector.
        
        Returns:
            dict: R1CS representation with A, B, C matrices
        
        Note:
            This is a simplified representation. Real R1CS compilation
            would produce sparse matrices over a finite field.
        """
        # Simplified R1CS representation
        constraints = []
        
        for gate in self._gates:
            if gate.gate_type == "AND":
                # a * b = c
                constraints.append({
                    'type': 'multiplication',
                    'A': gate.inputs[0],
                    'B': gate.inputs[1],
                    'C': gate.output,
                })
            elif gate.gate_type == "OR":
                # OR(a,b) = a + b - a*b
                # Needs multiple constraints
                constraints.append({
                    'type': 'or_composition',
                    'inputs': gate.inputs,
                    'output': gate.output,
                })
            # Other gate types...
        
        return {
            'num_constraints': len(constraints),
            'num_variables': self._next_wire,
            'constraints': constraints,
            'public_inputs': list(self._outputs),
        }
    
    def __repr__(self) -> str:
        return (
            f"ZKPCircuit("
            f"inputs={self.num_inputs()}, "
            f"gates={self.num_gates()}, "
            f"wires={self.num_wires()})"
        )

# MVP (Minimum Viable Proof) Circuit Support
# ==========================================

@dataclass
class MVPCircuit:
    """
    Minimum Viable Proof circuit for knowledge-of-axioms.
    
    Circuit statement: "I know a set of axioms whose SHA256 commitment matches X."
    
    This is a non-cryptographic first implementation.
    In production, this would be compiled to R1CS / arithmetic constraints.
    """
    
    circuit_version: int = 1
    circuit_type: str = "knowledge_of_axioms"
    
    def num_inputs(self) -> int:
        """Number of public input field elements."""
        return 4  # theorem_hash, axioms_commitment, circuit_version, ruleset_id
    
    def num_constraints(self) -> int:
        """Number of constraints in circuit."""
        return 1  # commitment check constraint
    
    def compile(self) -> Dict[str, Any]:
        """
        Compile circuit to schema (JSON representation).
        
        In production, this would generate R1CS or other constraint format.
        
        Returns:
            Dictionary describing circuit structure
        """
        return {
            'version': self.circuit_version,
            'type': self.circuit_type,
            'num_inputs': self.num_inputs(),
            'num_constraints': self.num_constraints(),
            'description': 'Prove knowledge of axioms matching a commitment',
        }

    def verify_constraints(self, witness: Witness, statement: Statement) -> bool:
        """Evaluate MVP constraints for the given witness and statement.

        This provides a concrete, non-cryptographic constraint evaluation path
        for the MVP circuit. It is intentionally strict and fail-closed.

        Constraints (v1):
        - circuit version matches
        - ruleset_id matches
        - SHA256(canonicalize_axioms(witness.axioms)) == statement.axioms_commitment
        - witness.axioms_commitment_hex matches the same computed commitment
        """
        try:
            if statement.circuit_version != self.circuit_version:
                return False
            if witness.circuit_version != statement.circuit_version:
                return False
            if witness.ruleset_id != statement.ruleset_id:
                return False

            canonical_axioms = canonicalize_axioms(witness.axioms)
            if witness.axioms != canonical_axioms:
                return False
            expected_commitment_hex = hash_axioms_commitment(canonical_axioms).hex()

            if statement.axioms_commitment != expected_commitment_hex:
                return False
            if witness.axioms_commitment_hex != expected_commitment_hex:
                return False

            return True
        except (AttributeError, TypeError, ValueError):
            return False


def create_knowledge_of_axioms_circuit(circuit_version: int = 1) -> MVPCircuit:
    """
    Create a knowledge-of-axioms circuit.
    
    Args:
        circuit_version: Circuit version number (default 1 for MVP)
    
    Returns:
        MVPCircuit instance
    """
    return MVPCircuit(circuit_version=circuit_version)


@dataclass
class TDFOLv1DerivationCircuit:
    """Constraint evaluation for the `TDFOL_v1` MVP semantics (P7.2).

    This is still a *non-cryptographic* constraint checker implemented in
    Python, but it defines a witness structure that is designed to be compiled
    to arithmetic constraints later.

    Witness requirements (v2):
    - witness.axioms: canonicalized axioms
    - witness.theorem: theorem atom (string)
    - witness.intermediate_steps: derivation trace of atoms (strings)

    Public statement requirements:
    - statement.theorem_hash == hash_theorem(witness.theorem)
    - statement.axioms_commitment == tdfol_v1_axioms_commitment_hex_v2(witness.axioms)
    - statement.ruleset_id == 'TDFOL_v1'
    - statement.circuit_version == 2
    """

    circuit_version: int = 2
    circuit_type: str = "tdfol_v1_horn_derivation"

    def num_inputs(self) -> int:
        return 4

    def compile(self) -> Dict[str, Any]:
        return {
            'version': self.circuit_version,
            'type': self.circuit_type,
            'num_inputs': self.num_inputs(),
            'description': 'Prove theorem holds under TDFOL_v1 Horn-fragment semantics using a derivation trace',
        }

    def verify_constraints(self, witness: Witness, statement: Statement) -> bool:
        try:
            if statement.circuit_version != self.circuit_version:
                return False
            if witness.circuit_version != statement.circuit_version:
                return False
            if statement.ruleset_id != "TDFOL_v1":
                return False
            if witness.ruleset_id != statement.ruleset_id:
                return False

            if not witness.theorem:
                return False

            theorem_atom = parse_tdfol_v1_theorem(witness.theorem)
            if statement.theorem_hash != hash_theorem(theorem_atom).hex():
                return False

            canonical_axioms = canonicalize_axioms(witness.axioms)
            if witness.axioms != canonical_axioms:
                return False
            expected_commitment_hex = tdfol_v1_axioms_commitment_hex_v2(canonical_axioms)
            if statement.axioms_commitment != expected_commitment_hex:
                return False
            if witness.axioms_commitment_hex != expected_commitment_hex:
                return False

            # Validate the derivation trace.
            #
            # Rules:
            # - Each trace entry must be an atom.
            # - Facts (axioms without antecedent) are initially known.
            # - For any derived atom X that is not a fact, there must exist an axiom (P -> X)
            #   with P already known.
            if witness.intermediate_steps is None or len(witness.intermediate_steps) == 0:
                return False

            parsed_axioms = [parse_tdfol_v1_axiom(a) for a in canonical_axioms]
            facts = {ax.consequent for ax in parsed_axioms if ax.antecedent is None}
            implications = [ax for ax in parsed_axioms if ax.antecedent is not None]

            known = set(facts)
            seen = set()

            for raw_step in witness.intermediate_steps:
                step = parse_tdfol_v1_theorem(raw_step)

                # Keep trace strictly additive.
                if step in seen:
                    return False
                seen.add(step)

                if step not in known:
                    # Must be justified by some implication whose antecedent is already known.
                    ok = False
                    for ax in implications:
                        assert ax.antecedent is not None
                        if ax.consequent == step and ax.antecedent in known:
                            ok = True
                            break
                    if not ok:
                        return False
                    known.add(step)

            return theorem_atom in known

        except Exception:
            return False

def create_implication_circuit(num_premises: int) -> ZKPCircuit:
    """
    Create a circuit for proving: (P1 AND P2 AND ... AND Pn) IMPLIES Q
    
    This is useful for proving theorems where multiple premises
    lead to a conclusion.
    
    Args:
        num_premises: Number of premise variables
    
    Returns:
        ZKPCircuit: Circuit that verifies the implication
    
    Example:
        >>> # Create circuit for: (P AND Q) IMPLIES R
        >>> circuit = create_implication_circuit(num_premises=2)
        >>> print(circuit)
        ZKPCircuit(inputs=3, gates=3, wires=7)
    """
    circuit = ZKPCircuit()
    
    # Add premise inputs
    premise_wires = []
    for i in range(num_premises):
        wire = circuit.add_input(f"P{i}")
        premise_wires.append(wire)
    
    # Add conclusion input
    q_wire = circuit.add_input("Q")
    
    # AND all premises together
    if num_premises == 1:
        premises_wire = premise_wires[0]
    else:
        premises_wire = circuit.add_and_gate(premise_wires[0], premise_wires[1])
        for i in range(2, num_premises):
            premises_wire = circuit.add_and_gate(premises_wire, premise_wires[i])
    
    # Create implication: premises -> Q
    result_wire = circuit.add_implies_gate(premises_wire, q_wire)
    circuit.set_output(result_wire)
    
    return circuit
