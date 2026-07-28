"""Family-agnostic content-addressed proof corpus store (ProofCorpusStore@1).

Unifies Intent, Legal, and Security formalization envelopes under one integrity
bound put/get surface.  Query/index (LIG-012) and attestation verify (LIG-013)
extend this package without changing the envelope authority model.

Import leaf modules for the full surface; this package root re-exports the
stable store and schema contracts used by the admissibility gate.
"""

from __future__ import annotations

from .schemas import (
    PROOF_CORPUS_ENVELOPE_SCHEMA_VERSION,
    PROOF_CORPUS_FAMILY_VALUES,
    PROOF_CORPUS_INDEX_SCHEMA_VERSION,
    PROOF_CORPUS_STORE_INTERFACE,
    PROOF_CORPUS_STORE_SCHEMA_VERSION,
    ArtifactEnvelope,
    ProofCorpusFamily,
    ProofCorpusIntegrityError,
    ProofCorpusSchemaError,
    envelope_identity_digest,
    family_for_domain,
    normalize_artifact,
    normalize_attachments,
    parse_family,
)
from .store import (
    ProofCorpusStore,
    ProofCorpusStoreError,
    ProofCorpusStoreIntegrityError,
    get_envelope,
    put_envelope,
    put_family_fixtures,
)

__all__ = [
    "PROOF_CORPUS_ENVELOPE_SCHEMA_VERSION",
    "PROOF_CORPUS_FAMILY_VALUES",
    "PROOF_CORPUS_INDEX_SCHEMA_VERSION",
    "PROOF_CORPUS_STORE_INTERFACE",
    "PROOF_CORPUS_STORE_SCHEMA_VERSION",
    "ArtifactEnvelope",
    "ProofCorpusFamily",
    "ProofCorpusIntegrityError",
    "ProofCorpusSchemaError",
    "ProofCorpusStore",
    "ProofCorpusStoreError",
    "ProofCorpusStoreIntegrityError",
    "envelope_identity_digest",
    "family_for_domain",
    "get_envelope",
    "normalize_artifact",
    "normalize_attachments",
    "parse_family",
    "put_envelope",
    "put_family_fixtures",
]
