"""Canonical content identity for Crypto IR records.

This module reuses :mod:`ipfs_datasets_py.logic.ir_core.identity` rather than
cloning its multiformat profile.  Crypto IR identities bind:

* the shared ``ir-canonical-identity-v1`` profile;
* a Crypto IR domain and schema version;
* explicit collection semantics; and
* chain/genesis discriminators when the payload is chain-qualified.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from ..ir_core.canonical import (
    CANONICAL_JSON_PROFILE,
    CollectionRule,
    CollectionSchema,
    CollectionSemantics,
    coerce_collection_schema,
)
from ..ir_core.identity import (
    CID_VERSION,
    DIGEST_SIZE,
    IDENTITY_PROFILE,
    IDENTITY_PROFILE_NAME,
    MULTIBASE_NAME,
    MULTICODEC_CODE,
    MULTICODEC_NAME,
    MULTIHASH_CODE,
    MULTIHASH_NAME,
    CanonicalIdentity,
    IdentityProfile,
    canonical_identity,
    cid_v1,
    cid_v1_from_digest,
    identity_preimage,
    sha256_digest,
)
from .schema_versions import (
    CRYPTO_IR_IDENTITY_SCHEMA_VERSION,
    CRYPTO_IR_KERNEL_SCHEMA_VERSION,
)


CRYPTO_IR_IDENTITY_DOMAIN: Final[str] = "crypto-ir"
CRYPTO_IR_CHAIN_QUALIFIED_DOMAIN: Final[str] = "crypto-ir.chain-qualified"
CRYPTO_IR_IDENTITY_SCHEMA_ID: Final[str] = CRYPTO_IR_IDENTITY_SCHEMA_VERSION.identifier


class CryptoIRIdentityError(ValueError):
    """Raised when a Crypto IR identity cannot be computed."""


@dataclass(frozen=True, slots=True)
class CryptoIRIdentityProfile:
    """Crypto IR binding of the shared IR identity profile.

    Chain/genesis and schema profile fields are part of the *payload* envelope,
    not a separate multiformat profile.  The wire profile remains the shared
    ``ir-canonical-identity-v1`` settings.
    """

    identity_profile: IdentityProfile = IDENTITY_PROFILE
    domain: str = CRYPTO_IR_IDENTITY_DOMAIN
    schema_version: str = CRYPTO_IR_KERNEL_SCHEMA_VERSION
    schema_id: str = CRYPTO_IR_IDENTITY_SCHEMA_ID
    canonicalization: str = CANONICAL_JSON_PROFILE

    def to_dict(self) -> dict[str, Any]:
        profile = self.identity_profile.to_dict()
        return {
            "canonicalization": self.canonicalization,
            "domain": self.domain,
            "identity_profile": profile,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
        }


CRYPTO_IR_IDENTITY_PROFILE: Final[CryptoIRIdentityProfile] = CryptoIRIdentityProfile()


def crypto_ir_identity(
    payload: Any,
    *,
    schema_version: str = CRYPTO_IR_KERNEL_SCHEMA_VERSION,
    domain: str = CRYPTO_IR_IDENTITY_DOMAIN,
    collection_schema: (
        CollectionSchema
        | Mapping[str, CollectionSemantics | str]
        | Sequence[CollectionRule]
        | None
    ) = None,
) -> CanonicalIdentity:
    """Compute the shared fixed-profile identity for a Crypto IR payload."""

    if not isinstance(schema_version, str) or not schema_version.strip():
        raise CryptoIRIdentityError("schema_version must be a non-empty string")
    if not isinstance(domain, str) or not domain.strip():
        raise CryptoIRIdentityError("domain must be a non-empty string")
    try:
        return canonical_identity(
            payload,
            domain=domain,
            schema_version=schema_version,
            collection_schema=collection_schema,
        )
    except (TypeError, ValueError) as exc:
        raise CryptoIRIdentityError(str(exc)) from exc


def chain_qualified_identity(
    payload: Any,
    *,
    chain_namespace: str,
    network: str,
    genesis_digest: str,
    schema_version: str = CRYPTO_IR_KERNEL_SCHEMA_VERSION,
    collection_schema: (
        CollectionSchema
        | Mapping[str, CollectionSemantics | str]
        | Sequence[CollectionRule]
        | None
    ) = None,
) -> CanonicalIdentity:
    """Identity for a payload whose chain/genesis binding is authoritative.

    The chain discriminators are sealed into the identity envelope payload so
    that two equal semantic bodies on different networks cannot collide.
    """

    for name, value in (
        ("chain_namespace", chain_namespace),
        ("network", network),
        ("genesis_digest", genesis_digest),
    ):
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise CryptoIRIdentityError(
                f"{name} must be a non-empty exact string"
            )

    envelope = {
        "chain_namespace": chain_namespace,
        "genesis_digest": genesis_digest,
        "network": network,
        "payload": payload,
    }
    schema = coerce_collection_schema(collection_schema)
    # Nested payload collections keep caller declarations; top-level keys are
    # not sequences.
    return crypto_ir_identity(
        envelope,
        schema_version=schema_version,
        domain=CRYPTO_IR_CHAIN_QUALIFIED_DOMAIN,
        collection_schema=schema,
    )


def identity_profile_descriptor() -> dict[str, Any]:
    """Return the machine-readable Crypto IR identity profile descriptor."""

    return CRYPTO_IR_IDENTITY_PROFILE.to_dict()


__all__ = [
    "CANONICAL_JSON_PROFILE",
    "CID_VERSION",
    "CRYPTO_IR_CHAIN_QUALIFIED_DOMAIN",
    "CRYPTO_IR_IDENTITY_DOMAIN",
    "CRYPTO_IR_IDENTITY_PROFILE",
    "CRYPTO_IR_IDENTITY_SCHEMA_ID",
    "DIGEST_SIZE",
    "IDENTITY_PROFILE",
    "IDENTITY_PROFILE_NAME",
    "MULTIBASE_NAME",
    "MULTICODEC_CODE",
    "MULTICODEC_NAME",
    "MULTIHASH_CODE",
    "MULTIHASH_NAME",
    "CanonicalIdentity",
    "CollectionRule",
    "CollectionSchema",
    "CollectionSemantics",
    "CryptoIRIdentityError",
    "CryptoIRIdentityProfile",
    "IdentityProfile",
    "canonical_identity",
    "chain_qualified_identity",
    "cid_v1",
    "cid_v1_from_digest",
    "crypto_ir_identity",
    "identity_preimage",
    "identity_profile_descriptor",
    "sha256_digest",
]
