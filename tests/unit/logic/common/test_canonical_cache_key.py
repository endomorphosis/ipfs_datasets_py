"""LPC-080: Canonical semantic cache-key contract.

Acceptance:

* Keys bind the required identity fields (source, expression, formalization,
  slice, obligation, assumptions, bounds, translation, provider, environment,
  policy, schema, checker, network policy, evidence kind, authority ceiling).
* Invalid CIDs, empty digests, and candidate-as-kernel entries are rejected.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.common.canonical_cache_key import (
    CANONICAL_PROOF_CACHE_KEY_GENERATION,
    CANONICAL_PROOF_CACHE_KEY_INTERFACE,
    CANONICAL_PROOF_CACHE_KEY_MODULE_VERSION,
    CANONICAL_PROOF_CACHE_KEY_SCHEMA,
    CANONICAL_PROOF_CACHE_KEY_SCHEMA_VERSION,
    REQUIRED_IDENTITY_FIELDS,
    CanonicalCacheKeyError,
    CanonicalProofCacheKey,
    CandidateAsKernelError,
    CrossEnvironmentHitError,
    EmptyDigestError,
    InvalidCidError,
    admit_cache_hit,
    admit_canonical_cache_key,
    content_digest,
    environments_compatible,
    is_candidate_evidence_kind,
    is_kernel_grade_authority,
    is_structurally_valid_cid_v1,
    key_carries_required_identity_fields,
    looks_like_cid,
    make_identity_cid,
    make_identity_digest,
    reject_candidate_as_kernel,
    require_digest,
    require_valid_cid,
)
from ipfs_datasets_py.logic.ir_core.axes import (
    LogicEvidenceAuthority,
    LogicEvidenceKind,
)
from ipfs_datasets_py.logic.ir_core.identity import cid_v1


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _valid_cid(label: str) -> str:
    return cid_v1(label.encode("utf-8"))


def _full_key(**changes: object) -> CanonicalProofCacheKey:
    fields: dict[str, object] = {
        "source": _digest("source"),
        "expression": _digest("expression"),
        "formalization": _digest("formalization"),
        "slice": _digest("slice"),
        "obligation": _digest("obligation"),
        "assumptions": _digest("assumptions"),
        "bounds": _digest("bounds"),
        "translation": _digest("translation"),
        "provider": "provider.z3",
        "environment": _digest("env:linux-x86_64-lean-4.0"),
        "policy": _digest("policy:kernel-required"),
        "schema": _digest("schema:logic-axis/v1"),
        "checker": "checker.lean-kernel",
        "network_policy": _digest("net:offline"),
        "evidence_kind": LogicEvidenceKind.KERNEL_CHECKED_PROOF,
        "authority_ceiling": LogicEvidenceAuthority.AUTHORITATIVE,
        "source_cid": _valid_cid("source-bytes"),
    }
    fields.update(changes)
    return CanonicalProofCacheKey(**fields)  # type: ignore[arg-type]


def _note_path() -> Path:
    note_relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "cache_key_contract.md"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / note_relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[5] / note_relative


# ---------------------------------------------------------------------------
# Identities and inventory
# ---------------------------------------------------------------------------


def test_interface_and_schema_identities() -> None:
    assert CANONICAL_PROOF_CACHE_KEY_INTERFACE == "CanonicalProofCacheKey@1"
    assert CANONICAL_PROOF_CACHE_KEY_GENERATION == "CanonicalProofCacheKey@1"
    assert CANONICAL_PROOF_CACHE_KEY_SCHEMA == (
        "ipfs_datasets_py/canonical-proof-cache-key@1"
    )
    assert CANONICAL_PROOF_CACHE_KEY_SCHEMA_VERSION == (
        "canonical-proof-cache-key/v1"
    )
    assert CANONICAL_PROOF_CACHE_KEY_MODULE_VERSION == "1.0.0"


def test_required_identity_field_inventory_matches_acceptance() -> None:
    expected = {
        "source",
        "expression",
        "formalization",
        "slice",
        "obligation",
        "assumptions",
        "bounds",
        "translation",
        "provider",
        "environment",
        "policy",
        "schema",
        "checker",
        "network_policy",
        "evidence_kind",
        "authority_ceiling",
    }
    assert set(REQUIRED_IDENTITY_FIELDS) == expected
    assert len(REQUIRED_IDENTITY_FIELDS) == 16


def test_key_binds_every_required_identity_field() -> None:
    key = _full_key()
    payload = key.to_dict()
    for field_name in REQUIRED_IDENTITY_FIELDS:
        assert field_name in payload, f"missing required field {field_name}"
        assert payload[field_name] not in (None, "")
    assert key.binds_required_identity_fields()
    assert key_carries_required_identity_fields(key)
    assert key_carries_required_identity_fields(payload)
    assert payload["interface"] == CANONICAL_PROOF_CACHE_KEY_INTERFACE
    assert key.key_id.startswith("canonical-proof-cache-key:sha256:")


def test_build_digests_raw_values_and_preserves_stable_ids() -> None:
    key = CanonicalProofCacheKey.build(
        source={"path": "src/main.py"},
        expression={"kind": "goal", "text": "∀x. P(x)"},
        formalization={"artifact": "formalization@3"},
        slice={"domain": "software", "profile": "g"},
        obligation={"id": "obl-1"},
        assumptions=[{"name": "classical"}],
        bounds={"timeout_ms": 5000},
        translation={"receipt": "tr-1"},
        provider="provider.cvc5",
        environment={"os": "linux", "arch": "x86_64"},
        policy={"ceiling": "kernel"},
        schema={"name": "logic-axis", "version": "v1"},
        checker="checker.cvc5",
        network_policy={"mode": "offline"},
        evidence_kind=LogicEvidenceKind.CHECKED_PROOF,
        authority_ceiling=LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    )
    assert key.provider == "provider.cvc5"
    assert key.checker == "checker.cvc5"
    assert key.source.startswith("sha256:")
    assert key.environment.startswith("sha256:")
    assert key.evidence_kind is LogicEvidenceKind.CHECKED_PROOF
    assert (
        key.authority_ceiling
        is LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE
    )
    assert key_carries_required_identity_fields(key)


def test_dict_round_trip_preserves_identity() -> None:
    original = _full_key()
    rebuilt = CanonicalProofCacheKey.from_dict(original.to_dict())
    assert rebuilt == original
    assert rebuilt.key_id == original.key_id
    admitted = admit_canonical_cache_key(original.to_dict())
    assert admitted.key_id == original.key_id


def test_missing_semantic_field_fails_closed() -> None:
    payload = _full_key().to_dict()
    del payload["obligation"]
    with pytest.raises(CanonicalCacheKeyError, match="missing required"):
        CanonicalProofCacheKey.from_dict(payload)


# ---------------------------------------------------------------------------
# Empty digests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "sha256:",
        "sha256: ",
        "sha256:deadbeef",  # too short
        "md5:" + ("ab" * 16),
    ],
)
def test_empty_and_malformed_digests_rejected(bad: str) -> None:
    with pytest.raises((EmptyDigestError, CanonicalCacheKeyError)):
        require_digest(bad, "obligation")
    with pytest.raises((EmptyDigestError, CanonicalCacheKeyError)):
        _full_key(obligation=bad)


def test_bare_hex_digest_is_normalized() -> None:
    bare = "ab" * 32
    assert require_digest(bare, "source") == f"sha256:{bare}"
    key = _full_key(source=bare)
    assert key.source == f"sha256:{bare}"


def test_whitespace_padded_digest_rejected() -> None:
    good = _digest("padded")
    with pytest.raises(EmptyDigestError):
        require_digest(f" {good}", "source")
    with pytest.raises(EmptyDigestError):
        require_digest(f"{good} ", "source")


# ---------------------------------------------------------------------------
# Invalid CIDs / CID-looking non-CIDs
# ---------------------------------------------------------------------------


def test_valid_profile_cid_is_accepted() -> None:
    cid = _valid_cid("canonical-cache-key-fixture")
    assert looks_like_cid(cid)
    assert is_structurally_valid_cid_v1(cid)
    assert require_valid_cid(cid) == cid
    key = _full_key(source_cid=cid)
    assert key.source_cid == cid


@pytest.mark.parametrize(
    "impostor",
    [
        # Synthetic HF-style cache key (bafy + truncated hex) — not multiformats.
        "bafy" + ("0a" * 28),
        "bafy" + hashlib.sha256(b"hf").hexdigest()[:56],
        # Truncated / broken CIDv1-looking strings (base32 alphabet only).
        "bafkreigaknpexyvxt76zgkitavbwx6ejgfheup5oybpm77f3pxzrvwpf",
        "bafkrei" + ("a" * 50),
        # Non-base32 characters (0,1,8,9) in a CID-shaped string.
        "bafy0000111122223333444455556666777788889999aaaabbbbcccc",
        # CIDv0-looking garbage.
        "QmInvalidCidThatIsNotReallyValid000000000000000",
        # Empty / whitespace.
        "",
        "   ",
    ],
)
def test_cid_looking_non_cids_rejected(impostor: str) -> None:
    stripped = impostor.strip()
    if stripped:
        assert looks_like_cid(stripped)
        assert not is_structurally_valid_cid_v1(stripped)
    with pytest.raises((InvalidCidError, CanonicalCacheKeyError)):
        require_valid_cid(impostor, "source_cid")
    if stripped:
        with pytest.raises((InvalidCidError, CanonicalCacheKeyError)):
            _full_key(source_cid=stripped)


def test_digest_slot_rejects_cid_looking_impostor() -> None:
    impostor = "bafy" + hashlib.sha256(b"not-a-cid").hexdigest()[:56]
    assert looks_like_cid(impostor)
    assert not is_structurally_valid_cid_v1(impostor)
    with pytest.raises(InvalidCidError):
        require_digest(impostor, "source")


def test_make_identity_helpers_match_profile() -> None:
    payload = {"k": "v"}
    digest = make_identity_digest(payload)
    assert digest == content_digest(payload)
    assert digest.startswith("sha256:")
    cid = make_identity_cid(b"raw-bytes")
    assert is_structurally_valid_cid_v1(cid)


# ---------------------------------------------------------------------------
# Candidate-as-kernel rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        LogicEvidenceKind.CANDIDATE,
        LogicEvidenceKind.ATP_CANDIDATE,
        LogicEvidenceKind.SMT_CANDIDATE,
        LogicEvidenceKind.LLM_OUTPUT,
        LogicEvidenceKind.MODEL_OUTPUT,
        LogicEvidenceKind.DECLARATION,
        LogicEvidenceKind.REVIEW,
    ],
)
@pytest.mark.parametrize(
    "authority",
    [
        LogicEvidenceAuthority.AUTHORITATIVE,
        LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    ],
)
def test_candidate_as_kernel_rejected(
    kind: LogicEvidenceKind,
    authority: LogicEvidenceAuthority,
) -> None:
    assert is_candidate_evidence_kind(kind)
    assert is_kernel_grade_authority(authority)
    with pytest.raises(CandidateAsKernelError, match="candidate-as-kernel"):
        reject_candidate_as_kernel(kind, authority)
    with pytest.raises(CandidateAsKernelError):
        _full_key(evidence_kind=kind, authority_ceiling=authority)


@pytest.mark.parametrize(
    ("kind", "authority"),
    [
        (LogicEvidenceKind.CANDIDATE, LogicEvidenceAuthority.ADVISORY),
        (LogicEvidenceKind.CANDIDATE, LogicEvidenceAuthority.BOUNDED),
        (LogicEvidenceKind.CANDIDATE, LogicEvidenceAuthority.UNKNOWN),
        (
            LogicEvidenceKind.KERNEL_CHECKED_PROOF,
            LogicEvidenceAuthority.AUTHORITATIVE,
        ),
        (
            LogicEvidenceKind.CHECKED_PROOF,
            LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        ),
        (
            LogicEvidenceKind.PROOF_CERTIFICATE,
            LogicEvidenceAuthority.AUTHORITATIVE,
        ),
    ],
)
def test_non_kernel_candidate_and_kernel_proof_allowed(
    kind: LogicEvidenceKind,
    authority: LogicEvidenceAuthority,
) -> None:
    reject_candidate_as_kernel(kind, authority)  # must not raise
    key = _full_key(evidence_kind=kind, authority_ceiling=authority)
    assert key.evidence_kind is kind
    assert key.authority_ceiling is authority


# ---------------------------------------------------------------------------
# Default-string unknown objects
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "placeholder",
    [
        "unknown",
        "<unknown>",
        "null",
        "None",
        "unspecified",
        "default",
        "n/a",
        "todo",
    ],
)
def test_default_string_unknown_stable_ids_rejected(placeholder: str) -> None:
    with pytest.raises(CanonicalCacheKeyError, match="placeholder"):
        _full_key(provider=placeholder)
    with pytest.raises(CanonicalCacheKeyError, match="placeholder"):
        _full_key(checker=placeholder)


# ---------------------------------------------------------------------------
# Cross-environment hits
# ---------------------------------------------------------------------------


def test_cross_environment_hit_rejected() -> None:
    stored = _full_key(environment=_digest("env:linux"))
    request = _full_key(environment=_digest("env:darwin"))
    # Same obligation-family fields otherwise — only environment differs.
    assert stored.obligation == request.obligation
    assert stored.environment != request.environment
    assert not environments_compatible(stored, request)
    with pytest.raises(CrossEnvironmentHitError, match="cross-environment"):
        admit_cache_hit(stored, request)


def test_same_environment_exact_hit_admitted() -> None:
    stored = _full_key()
    request = CanonicalProofCacheKey.from_dict(stored.to_dict())
    assert environments_compatible(stored, request)
    admitted = admit_cache_hit(stored, request)
    assert admitted.key_id == stored.key_id


def test_identity_mismatch_rejected_even_with_same_environment() -> None:
    stored = _full_key(obligation=_digest("obl-a"))
    request = _full_key(obligation=_digest("obl-b"))
    assert stored.environment == request.environment
    with pytest.raises(CanonicalCacheKeyError, match="identity mismatch"):
        admit_cache_hit(stored, request)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_key_id_is_deterministic() -> None:
    a = _full_key()
    b = _full_key()
    assert a.key_id == b.key_id
    assert a.digest == b.digest
    different = _full_key(policy=_digest("other-policy"))
    assert different.key_id != a.key_id


# ---------------------------------------------------------------------------
# Contract note
# ---------------------------------------------------------------------------


def test_contract_note_documents_inventory_and_rejections() -> None:
    note = _note_path()
    assert note.is_file(), f"missing contract note at {note}"
    text = note.read_text(encoding="utf-8")
    assert "CanonicalProofCacheKey@1" in text
    assert "REQUIRED_IDENTITY_FIELDS" in text
    for field_name in REQUIRED_IDENTITY_FIELDS:
        assert field_name in text, f"note missing field {field_name}"
    assert "candidate-as-kernel" in text.lower() or "Candidate-as-kernel" in text
    assert "empty digest" in text.lower() or "Empty digests" in text
    assert "CID" in text
    assert "cross-environment" in text.lower() or "Cross-environment" in text
    assert "canonical_cache_key.py" in text
