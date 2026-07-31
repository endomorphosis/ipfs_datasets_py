"""Unit tests for SecurityConstraintCache@1 put/get/reload integrity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.ir_core.claims import stable_digest
from ipfs_datasets_py.logic.ir_core.protocols import (
    AttemptStatus,
    AuthorityKind,
    BackendAttempt,
    BackendRequest,
    ExecutionBounds,
    PolicyDecision,
    QueryKind,
    ResourceUsage,
    ResultAuthority,
    ResultStatus,
)
from ipfs_datasets_py.logic.security_ir.constraint_cache import (
    KNOWN_SECURITY_EXTENSION_VOCABULARIES,
    SECURITY_CONSTRAINT_CACHE_INTERFACE,
    SECURITY_CONSTRAINT_CACHE_SCHEMA_VERSION,
    SECURITY_CONSTRAINT_RECORD_SCHEMA_VERSION,
    SecurityConstraintCache,
    SecurityConstraintCacheError,
    SecurityConstraintIntegrityError,
    SecurityConstraintRecord,
    UnknownSecurityExtensionError,
    get_security_constraints,
    put_security_constraints,
    validate_extensions_known,
)
from ipfs_datasets_py.logic.security_ir.exchange.adapter import adapt_exchange_security_ir
from ipfs_datasets_py.logic.security_ir.exchange.vocabulary import EXCHANGE_VOCABULARY
from ipfs_datasets_py.logic.security_ir.formalization_adapter import adapt_security_ir
from ipfs_datasets_py.logic.security_ir.model import SecurityIR
from ipfs_datasets_py.logic.security_ir.xaman.adapter import adapt_xaman_security_ir
from ipfs_datasets_py.logic.security_ir.xaman.config import (
    XAMAN_VOCABULARY,
    XamanAdapterConfig,
    XamanSourceConfig,
)


FIXTURES = (
    Path(__file__).resolve().parents[3] / "fixtures" / "security_ir" / "constraint_cache"
)
V1_FIXTURES = (
    Path(__file__).resolve().parents[3] / "fixtures" / "security_ir" / "v1"
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest() -> dict[str, Any]:
    return _load_json(FIXTURES / "manifest.json")


def _exchange_declaration() -> SecurityIR:
    payload = _load_json(V1_FIXTURES / "exchange_model.json")
    return adapt_exchange_security_ir(payload).declaration


def _xaman_declaration() -> SecurityIR:
    payload = _load_json(V1_FIXTURES / "xaman_model.json")
    corpus = payload["metadata"]["corpus"]
    config = XamanAdapterConfig(
        config_id="config:xaman-golden",
        source=XamanSourceConfig(
            source_id="source:xaman-app",
            uri=corpus["source_url"],
            revision=corpus["pinned_commit"],
            review_status="trusted_fixture",
        ),
    )
    return adapt_xaman_security_ir(payload, config=config).declaration


def _unknown_declaration() -> SecurityIR:
    return SecurityIR.from_dict(
        _load_json(FIXTURES / "unknown_extension_declaration.json")
    )


def _policy_decision_for(declaration: SecurityIR) -> PolicyDecision:
    bounds = ExecutionBounds(
        timeout_ms=1_000,
        max_steps=1_000,
        max_memory_bytes=1_000_000,
        max_output_bytes=4_096,
    )
    request = BackendRequest(
        request_id="request:constraint-cache-policy",
        query_kind=QueryKind.POLICY_APPROVAL,
        claim_id="claim:constraint-cache-policy",
        claim_digest=stable_digest(
            {
                "claim_id": "claim:constraint-cache-policy",
                "declaration_id": declaration.declaration_id,
            }
        ),
        declaration_id=declaration.declaration_id,
        obligation_id="obligation:constraint-cache-policy",
        obligation_digest=stable_digest(
            {"obligation_id": "obligation:constraint-cache-policy"}
        ),
        assumption_ids=(),
        logic_family="security_policy",
        bounds=bounds,
        requested_backend_id="policy-backend",
    )
    attempt = BackendAttempt(
        attempt_id="attempt:constraint-cache-policy",
        request_digest=request.digest,
        backend_id="policy-backend",
        backend_version="1.0.0",
        status=AttemptStatus.SUCCEEDED,
        bounds=request.bounds,
        usage=ResourceUsage(
            elapsed_ms=1,
            steps=1,
            peak_memory_bytes=1_024,
            output_bytes=40,
        ),
        output_digest=stable_digest({"decision": "allow"}),
    )
    authority = ResultAuthority(
        kind=AuthorityKind.POLICY_APPROVAL,
        issuer="constraint-cache-test",
        method="policy-approval/v1",
        scope_digest=request.digest,
        configuration_digest=stable_digest({"profile": "test"}),
    )
    return PolicyDecision.for_attempt(
        request,
        attempt,
        result_id="result:constraint-cache-policy",
        authority=authority,
        status=ResultStatus.APPROVED,
        payload={"decision": "allow", "profile": "test"},
    )


def test_interface_constants_are_stable() -> None:
    assert SECURITY_CONSTRAINT_CACHE_INTERFACE == "SecurityConstraintCache@1"
    assert SECURITY_CONSTRAINT_CACHE_SCHEMA_VERSION == "security-constraint-cache/v1"
    assert (
        SECURITY_CONSTRAINT_RECORD_SCHEMA_VERSION == "security-constraint-record/v1"
    )
    assert EXCHANGE_VOCABULARY in KNOWN_SECURITY_EXTENSION_VOCABULARIES
    assert XAMAN_VOCABULARY in KNOWN_SECURITY_EXTENSION_VOCABULARIES


def test_fixture_manifest_describes_exchange_and_xaman_samples() -> None:
    manifest = _manifest()
    assert manifest["interface"] == SECURITY_CONSTRAINT_CACHE_INTERFACE
    assert set(manifest["samples"]) == {"exchange", "xaman"}
    for name in ("exchange", "xaman"):
        sample = manifest["samples"][name]
        record = SecurityConstraintRecord.from_dict(
            _load_json(FIXTURES / sample["record_path"])
        )
        assert record.profile == sample["profile"]
        assert record.declaration_id == sample["declaration_id"]
        assert record.declaration_digest == sample["declaration_digest"]
        assert record.declaration_cid == sample["declaration_cid"]
        assert record.content_cid == sample["content_cid"]
        assert record.content_digest == sample["content_digest"]
        assert list(record.extension_vocabularies) == sample["extension_vocabularies"]
        record.verify_integrity()


@pytest.mark.parametrize(
    ("builder", "profile", "sample_key"),
    (
        (_exchange_declaration, "exchange-golden", "exchange"),
        (_xaman_declaration, "xaman-golden", "xaman"),
    ),
)
def test_exchange_and_xaman_constraints_cache_and_reload(
    tmp_path: Path,
    builder,
    profile: str,
    sample_key: str,
) -> None:
    declaration = builder()
    sample = _manifest()["samples"][sample_key]
    cache = SecurityConstraintCache(root=tmp_path / "cache")

    record = cache.put(declaration, profile=profile)

    assert record.declaration_id == declaration.declaration_id
    assert record.declaration_digest == declaration.digest
    assert record.declaration_cid == declaration.cid
    assert record.declaration_digest == sample["declaration_digest"]
    assert record.declaration_cid == sample["declaration_cid"]
    assert record.profile == profile
    assert record.content_cid == sample["content_cid"]
    assert record.content_digest == sample["content_digest"]
    assert set(record.extension_vocabularies) <= set(
        KNOWN_SECURITY_EXTENSION_VOCABULARIES
    )

    loaded = cache.get(record.content_cid)
    assert loaded.content_cid == record.content_cid
    assert loaded.security_ir().digest == declaration.digest
    assert isinstance(loaded.formalization_artifact(), FormalizationArtifact)
    assert loaded.formalization_artifact().declaration_digest == declaration.digest

    # Fresh process view: reload from disk only.
    reloaded = SecurityConstraintCache(root=tmp_path / "cache")
    assert len(reloaded) >= 1
    again = reloaded.get(record.content_cid)
    assert again.content_digest == record.content_digest
    assert again.security_ir().to_dict() == declaration.to_dict()
    assert again.security_ir().digest == declaration.digest
    by_profile = reloaded.get_by_profile(profile)
    assert by_profile.content_cid == record.content_cid
    by_decl = reloaded.get_by_declaration(declaration.cid, profile=profile)
    assert by_decl.content_cid == record.content_cid


def test_put_get_functional_wrappers_and_policy_decision_authority(
    tmp_path: Path,
) -> None:
    declaration = _exchange_declaration()
    decision = _policy_decision_for(declaration)
    cache = SecurityConstraintCache(root=tmp_path / "policy-cache")

    record = put_security_constraints(
        cache,
        declaration,
        profile="exchange-with-policy",
        policy_decisions=(decision,),
    )
    loaded = get_security_constraints(cache, record.content_cid)
    decisions = loaded.policy_decision_results()
    assert len(decisions) == 1
    assert decisions[0].authority.kind is AuthorityKind.POLICY_APPROVAL
    assert decisions[0].status is ResultStatus.APPROVED
    assert decisions[0].declaration_id == declaration.declaration_id


def test_fixture_records_round_trip_through_disk_cache(tmp_path: Path) -> None:
    cache = SecurityConstraintCache(root=tmp_path / "fixture-cache")
    for name in ("exchange", "xaman"):
        sample = _manifest()["samples"][name]
        record = SecurityConstraintRecord.from_dict(
            _load_json(FIXTURES / sample["record_path"])
        )
        stored = cache.put(record)
        assert stored.content_cid == sample["content_cid"]

    reloaded = SecurityConstraintCache(root=tmp_path / "fixture-cache")
    assert set(reloaded.profiles()) == {"exchange-golden", "xaman-golden"}
    assert reloaded.reload() == 2


def test_unknown_extension_fails_closed_on_put(tmp_path: Path) -> None:
    declaration = _unknown_declaration()
    cache = SecurityConstraintCache(root=tmp_path / "unknown")

    with pytest.raises(UnknownSecurityExtensionError, match="fail closed"):
        cache.put(declaration, profile="unknown-vendor")

    with pytest.raises(UnknownSecurityExtensionError, match="security.unknown-vendor"):
        validate_extensions_known(declaration)

    # Building a record without the cache also fails closed.
    with pytest.raises(UnknownSecurityExtensionError):
        SecurityConstraintRecord.build(declaration, profile="unknown-vendor")


def test_unknown_extension_fails_closed_on_reload(tmp_path: Path) -> None:
    """Records written under an expanded allowlist fail closed for default caches."""

    declaration = _unknown_declaration()
    cache_dir = tmp_path / "unknown-reload"
    writer = SecurityConstraintCache(
        root=cache_dir,
        known_vocabularies=KNOWN_SECURITY_EXTENSION_VOCABULARIES
        | frozenset({"security.unknown-vendor"}),
    )
    record = writer.put(declaration, profile="unknown-vendor-allowed")
    assert (cache_dir / "records" / f"{record.content_cid}.json").is_file()

    with pytest.raises(
        (UnknownSecurityExtensionError, SecurityConstraintIntegrityError),
        match="fail closed|unknown security extension",
    ):
        SecurityConstraintCache(root=cache_dir)


def test_corruption_of_content_digest_fails_closed(tmp_path: Path) -> None:
    declaration = _exchange_declaration()
    cache_dir = tmp_path / "corrupt"
    cache = SecurityConstraintCache(root=cache_dir)
    record = cache.put(declaration, profile="exchange-golden")

    path = cache_dir / "records" / f"{record.content_cid}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["content_digest"] = "sha256:" + ("ab" * 32)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(SecurityConstraintIntegrityError):
        SecurityConstraintCache(root=cache_dir)


def test_declaration_identity_immutable_under_cache(tmp_path: Path) -> None:
    declaration = _exchange_declaration()
    before = (declaration.digest, declaration.cid, declaration.to_dict())
    cache = SecurityConstraintCache(root=tmp_path / "identity")
    record = cache.put(declaration, profile="exchange-golden")
    after = declaration.digest, declaration.cid, declaration.to_dict()
    assert before == after
    assert record.declaration_digest == before[0]
    assert record.declaration_cid == before[1]
    # Mutating the caller-held mapping returned by to_dict must not affect cache.
    mutable = record.to_dict()
    mutable["declaration"]["declaration_id"] = "security:mutated"
    assert cache.get(record.content_cid).declaration_id == declaration.declaration_id


def test_profile_filter_and_duplicate_declaration_requires_profile(
    tmp_path: Path,
) -> None:
    declaration = _exchange_declaration()
    cache = SecurityConstraintCache(root=tmp_path / "profiles")
    first = cache.put(declaration, profile="exchange-default")
    second = cache.put(declaration, profile="exchange-strict")
    assert first.content_cid != second.content_cid
    assert cache.get_by_profile("exchange-default").content_cid == first.content_cid
    assert cache.get_by_profile("exchange-strict").content_cid == second.content_cid
    with pytest.raises(SecurityConstraintCacheError, match="specify profile"):
        cache.get_by_declaration(declaration.cid)


def test_optional_artifact_must_bind_same_declaration(tmp_path: Path) -> None:
    exchange = _exchange_declaration()
    xaman = _xaman_declaration()
    artifact = adapt_security_ir(xaman)
    cache = SecurityConstraintCache(root=tmp_path / "mismatch")
    with pytest.raises(SecurityConstraintCacheError, match="declaration_id"):
        cache.put(exchange, profile="exchange-golden", artifact=artifact)


def test_memory_only_cache_put_get_and_reload() -> None:
    declaration = _exchange_declaration()
    cache = SecurityConstraintCache()
    record = cache.put(declaration, profile="exchange-memory")
    assert cache.contains(record.content_cid)
    assert cache.get(record.content_cid).content_digest == record.content_digest
    assert cache.reload() == 1


def test_registering_extra_vocabulary_allows_put(tmp_path: Path) -> None:
    declaration = _unknown_declaration()
    cache = SecurityConstraintCache(
        root=tmp_path / "extra",
        known_vocabularies=KNOWN_SECURITY_EXTENSION_VOCABULARIES
        | frozenset({"security.unknown-vendor"}),
    )
    # Extension id/version still fail closed against the built-in id allowlist
    # unless the vocabulary has no fixed id set.  Unknown vendor has no fixed
    # id allowlist entry, so vocabulary allowlisting is sufficient.
    record = cache.put(declaration, profile="unknown-vendor-allowed")
    assert "security.unknown-vendor" in record.extension_vocabularies


def test_put_finished_record_rejects_conflicting_profile(tmp_path: Path) -> None:
    record = SecurityConstraintRecord.from_dict(
        _load_json(FIXTURES / "exchange_record.json")
    )
    cache = SecurityConstraintCache(root=tmp_path / "conflict")
    with pytest.raises(SecurityConstraintCacheError, match="profile argument"):
        cache.put(record, profile="other-profile")


def test_missing_profile_and_missing_cid_errors(tmp_path: Path) -> None:
    cache = SecurityConstraintCache(root=tmp_path / "missing")
    declaration = _exchange_declaration()
    with pytest.raises(SecurityConstraintCacheError, match="profile is required"):
        cache.put(declaration)
    with pytest.raises(SecurityConstraintCacheError, match="not found"):
        cache.get("bafybeigmissingconstraintcid000000000000000000000000000000")
    with pytest.raises(SecurityConstraintCacheError, match="no constraint record"):
        cache.get_by_profile("does-not-exist")


def test_invalid_profile_rejected() -> None:
    declaration = _exchange_declaration()
    with pytest.raises(SecurityConstraintCacheError, match="profile"):
        SecurityConstraintRecord.build(declaration, profile="Not Valid")
