"""Reusable Worldcoin / World ID pure protocol package (WALPROC-G100/G120).

Importing this package performs no network I/O, secret resolution, or file
reads.  Optional crypto dependencies are only required when signing or hashing
functions are invoked.
"""

from __future__ import annotations

from .config import (
    DEFAULT_WORLD_ID_ACTION,
    DEFAULT_WORLD_ID_CREDENTIAL_POLICY,
    DEFAULT_WORLD_ID_HTTP_TIMEOUT_SECONDS,
    DEFAULT_WORLD_ID_SIGNATURE_TTL_SECONDS,
    DEFAULT_WORLD_ID_VERIFY_BASE_URL,
    SUPPORTED_WORLD_ID_ENVIRONMENTS,
    WorldIdConfig,
    WorldIdConfigError,
    WorldIdSecretConfig,
    load_world_id_config,
)
from .developer_portal import (
    WorldIdRequestJson,
    WorldIdVerificationError,
    WorldIdVerificationResult,
    normalize_world_id_verification_response,
    verify_world_id_proof,
    verify_world_id_proof_from_config,
)
from .idkit import (
    WorldIdCredentialResponse,
    WorldIdIdkitResult,
    WorldIdPayloadError,
    assert_idkit_allowed_by_config,
    normalize_idkit_response,
    normalize_world_id_idkit_response,
    redact_world_id_payload,
)
from .signing import (
    WorldIdRpSignature,
    WorldIdSignatureError,
    compute_rp_signature_message,
    eip191_digest,
    hash_to_field,
    hash_to_field_hex,
    sign_world_id_request,
    sign_world_id_request_from_config,
    world_id_keccak256,
)
from .world_chain import (
    WORLD_CHAIN_MAINNET,
    WORLD_CHAIN_MAINNET_CHAIN_ID,
    WORLD_CHAIN_SEPOLIA,
    WORLD_CHAIN_SEPOLIA_CHAIN_ID,
    EthereumWalletProcessor,
    WorldChainConfigError,
    WorldChainFinalityLabel,
    WorldChainNetwork,
    WorldChainProcessor,
    classify_world_chain_finality,
    get_world_chain_network,
    validate_world_chain_identity,
    world_chain_processor_for_chain_id,
)

__all__ = [
    "DEFAULT_WORLD_ID_ACTION",
    "DEFAULT_WORLD_ID_CREDENTIAL_POLICY",
    "DEFAULT_WORLD_ID_HTTP_TIMEOUT_SECONDS",
    "DEFAULT_WORLD_ID_SIGNATURE_TTL_SECONDS",
    "DEFAULT_WORLD_ID_VERIFY_BASE_URL",
    "SUPPORTED_WORLD_ID_ENVIRONMENTS",
    "WORLD_CHAIN_MAINNET",
    "WORLD_CHAIN_MAINNET_CHAIN_ID",
    "WORLD_CHAIN_SEPOLIA",
    "WORLD_CHAIN_SEPOLIA_CHAIN_ID",
    "EthereumWalletProcessor",
    "WorldChainConfigError",
    "WorldChainFinalityLabel",
    "WorldChainNetwork",
    "WorldChainProcessor",
    "WorldIdConfig",
    "WorldIdConfigError",
    "WorldIdCredentialResponse",
    "WorldIdIdkitResult",
    "WorldIdPayloadError",
    "WorldIdRequestJson",
    "WorldIdRpSignature",
    "WorldIdSecretConfig",
    "WorldIdSignatureError",
    "WorldIdVerificationError",
    "WorldIdVerificationResult",
    "assert_idkit_allowed_by_config",
    "classify_world_chain_finality",
    "compute_rp_signature_message",
    "eip191_digest",
    "get_world_chain_network",
    "hash_to_field",
    "hash_to_field_hex",
    "load_world_id_config",
    "normalize_idkit_response",
    "normalize_world_id_idkit_response",
    "normalize_world_id_verification_response",
    "redact_world_id_payload",
    "sign_world_id_request",
    "sign_world_id_request_from_config",
    "validate_world_chain_identity",
    "verify_world_id_proof",
    "verify_world_id_proof_from_config",
    "world_chain_processor_for_chain_id",
    "world_id_keccak256",
]
