"""Unit tests for LegalProofCache@1 put/get integrity, hit/miss, and indexes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.ir_core.claims import (
    Assumption,
    IRClaim,
    ProofObligation,
    stable_digest,
)
from ipfs_datasets_py.logic.ir_core.provenance import SourceReviewStatus
from ipfs_datasets_py.logic.ir_core.protocols import (
    AttemptStatus,
    AuthorityKind,
    BackendAttempt,
    BackendRequest,
    ExecutionBounds,
    ProofReceipt,
    ProofResult,
    QueryKind,
    ResourceUsage,
    ResultAuthority,
    ResultStatus,
)
from ipfs_datasets_py.logic.legal_ir.adapter import LegalIRFormalizationAdapter
from ipfs_datasets_py.logic.legal_ir.proof_cache import (
    LEGAL_PROOF_CACHE_INTERFACE,
    LEGAL_PROOF_CACHE_SCHEMA_VERSION,
    LEGAL_PROOF_INDEX_SCHEMA_VERSION,
    LEGAL_PROOF_RECORD_SCHEMA_VERSION,
    LegalProofCache,
    LegalProofCacheError,
    LegalProofIntegrityError,
    LegalProofRecord,
    get_legal_proof,
    put_legal_proof,
    rebuild_offline_from_fixture_dir,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIRFrameLogic,
    ModalIRFrameLogicTriple,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


FIXTURES = (
    Path(__file__).resolve().parents[3] / "fixtures" / "legal_ir" / "proof_cache"
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest() -> dict[str, Any]:
    return _load_json(FIXTURES / "manifest.json")


def _reviewed_fixture(
    *,
    sample_id: str = "us-code-5-552-fixture",
    text: str | None = None,
    citation: str = "5 U.S.C. 552",
    section: str = "552",
) -> LegalSample:
    source_text = text or "Agency shall publish notice unless an emergency applies."
    first = source_text.split()[0]
    start = source_text.index(first)
    modal = ModalIRDocument(
        document_id=sample_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id=f"{sample_id}:f0001",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="publish_notice",
                    arguments=["agency", "notice"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id=sample_id,
                    start_char=start,
                    end_char=len(source_text),
                    citation=citation,
                ),
                conditions=["request_received"],
                exceptions=["emergency"],
                metadata={"legal_scope": "agency_records"},
            )
        ],
        frame_logic=ModalIRFrameLogic(
            selected_frame="administrative_notice",
            graph_id=f"legal-graph-{section}",
            triples=[
                ModalIRFrameLogicTriple(
                    subject="agency",
                    predicate="must_publish",
                    object="notice",
                )
            ],
            metadata={"legal_relation_scope": f"section_{section}"},
        ),
        metadata={
            "citation": citation,
            "deterministic_parser": "reviewed_fixture_v1",
        },
    )
    sample = LegalSample(
        sample_id=sample_id,
        source="us_code",
        title="5",
        section=section,
        citation=citation,
        text=source_text,
        normalized_text=source_text,
        embedding_model="fixture:embedding-v1",
        embedding_vector=[0.25, -0.5],
        modal_ir=modal,
        frame_candidates=[
            {
                "domain": "administrative",
                "frame_id": "administrative_notice",
                "label": "Administrative notice",
                "score": 1.0,
            }
        ],
        selected_frame="administrative_notice",
        parser_trace={"parser": "reviewed_fixture_v1"},
        losses={"reconstruction_loss": 0.125},
    )
    sample.validate()
    return sample


def _legal_artifact(
    sample: LegalSample | None = None,
) -> FormalizationArtifact:
    legal = sample or _reviewed_fixture()
    return LegalIRFormalizationAdapter(
        source_review_status=SourceReviewStatus.TRUSTED_FIXTURE
    ).adapt_artifact(legal)


def _theorem_receipt_for(artifact: FormalizationArtifact) -> ProofReceipt:
    claim = IRClaim(
        claim_id="claim:legal-proof-cache",
        declaration_id=artifact.declaration_id,
        statement="Cached legal formal artifact satisfies the pinned obligation.",
        assumptions=(
            Assumption(
                assumption_id="assumption:source-reviewed",
                statement="The legal source is a trusted reviewed fixture.",
                source_refs=(f"source:{artifact.sample_id}",),
            ),
        ),
        obligations=(
            ProofObligation(
                obligation_id="obligation:legal-proof-cache",
                statement="The formal artifact declaration is theorem-entailed.",
                assumption_ids=("assumption:source-reviewed",),
                logic_family="typed_deontic",
                source_refs=(f"source:{artifact.sample_id}",),
            ),
        ),
        domain="legal",
    )
    bounds = ExecutionBounds(
        timeout_ms=1_000,
        max_steps=1_000,
        max_memory_bytes=1_000_000,
        max_output_bytes=4_096,
    )
    request = BackendRequest.for_claim(
        claim,
        "obligation:legal-proof-cache",
        request_id="request:legal-proof-cache",
        query_kind=QueryKind.THEOREM_PROOF,
        bounds=bounds,
        requested_backend_id="native-kernel",
    )
    attempt = BackendAttempt(
        attempt_id="attempt:legal-proof-cache",
        request_digest=request.digest,
        backend_id="native-kernel",
        backend_version="1.0.0",
        status=AttemptStatus.SUCCEEDED,
        bounds=request.bounds,
        usage=ResourceUsage(
            elapsed_ms=1,
            steps=1,
            peak_memory_bytes=1_024,
            output_bytes=40,
        ),
        output_digest=stable_digest({"proved": True}),
    )
    authority = ResultAuthority(
        kind=AuthorityKind.THEOREM_PROOF,
        issuer="legal-proof-cache-test",
        method="native-kernel/v1",
        scope_digest=request.digest,
        configuration_digest=stable_digest({"profile": "test"}),
    )
    result = ProofResult.for_attempt(
        request,
        attempt,
        result_id="result:legal-proof-cache",
        authority=authority,
        status=ResultStatus.PROVED,
        payload={"decision": "proved", "profile": "test"},
    )
    return ProofReceipt.issue(
        claim,
        request,
        attempt,
        result,
        receipt_id="receipt:legal-proof-cache",
        verifier="legal-proof-cache-test",
    )


def test_interface_constants_are_stable() -> None:
    assert LEGAL_PROOF_CACHE_INTERFACE == "LegalProofCache@1"
    assert LEGAL_PROOF_CACHE_SCHEMA_VERSION == "legal-proof-cache/v1"
    assert LEGAL_PROOF_RECORD_SCHEMA_VERSION == "legal-proof-record/v1"
    assert LEGAL_PROOF_INDEX_SCHEMA_VERSION == "legal-proof-index/v1"


def test_fixture_manifest_describes_golden_samples() -> None:
    manifest = _manifest()
    assert manifest["interface"] == LEGAL_PROOF_CACHE_INTERFACE
    assert set(manifest["samples"]) == {"us_code_552", "us_code_553"}
    for name, sample in manifest["samples"].items():
        record = LegalProofRecord.from_dict(
            _load_json(FIXTURES / sample["record_path"])
        )
        assert record.profile == sample["profile"]
        assert record.source_id == sample["source_id"]
        assert record.source_digest == sample["source_digest"]
        assert record.content_cid == sample["content_cid"]
        assert record.content_digest == sample["content_digest"]
        assert record.artifact_cid == sample["artifact_cid"]
        assert record.artifact_digest == sample["artifact_digest"]
        assert record.jurisdiction == sample["jurisdiction"]
        record.verify_integrity()
        assert name  # keep name used


def test_put_get_hit_and_miss(tmp_path: Path) -> None:
    artifact = _legal_artifact()
    cache = LegalProofCache(root=tmp_path / "cache")

    # Miss before put.
    with pytest.raises(LegalProofCacheError, match="not found"):
        cache.get("bafybeigmissinglegalproofcid000000000000000000000000000000")
    assert cache.misses == 1
    assert cache.hits == 0
    assert not cache.contains(
        "bafybeigmissinglegalproofcid000000000000000000000000000000"
    )

    record = cache.put(artifact, profile="legal-strict", jurisdiction="us-federal")
    assert cache.contains(record.content_cid)

    loaded = cache.get(record.content_cid)
    assert loaded.content_cid == record.content_cid
    assert loaded.source_digest == artifact.declaration_digest
    assert isinstance(loaded.formalization_artifact(), FormalizationArtifact)
    assert loaded.formalization_artifact().digest == artifact.digest
    assert cache.hits == 1

    # Second get is another hit.
    again = cache.get(record.content_cid)
    assert again.content_digest == record.content_digest
    assert cache.hits == 2
    assert cache.stats()["size"] == 1


def test_cache_and_reload_from_disk_with_indexes(tmp_path: Path) -> None:
    artifact = _legal_artifact()
    cache_dir = tmp_path / "disk-cache"
    cache = LegalProofCache(root=cache_dir)
    record = cache.put(artifact, profile="legal-strict", jurisdiction="us-federal")

    reloaded = LegalProofCache(root=cache_dir)
    assert len(reloaded) >= 1
    by_cid = reloaded.get(record.content_cid)
    assert by_cid.content_digest == record.content_digest
    by_profile = reloaded.get_by_profile("legal-strict")
    assert by_profile.content_cid == record.content_cid
    by_source = reloaded.get_by_source_digest(record.source_digest)
    assert by_source.content_cid == record.content_cid
    by_source_profile = reloaded.get_by_source_digest(
        record.source_digest, profile="legal-strict"
    )
    assert by_source_profile.content_cid == record.content_cid
    assert record.source_digest in reloaded.source_digests()
    assert "legal-strict" in reloaded.profiles()


def test_index_by_source_digest_requires_profile_when_ambiguous(
    tmp_path: Path,
) -> None:
    artifact = _legal_artifact()
    cache = LegalProofCache(root=tmp_path / "profiles")
    first = cache.put(artifact, profile="legal-default")
    second = cache.put(artifact, profile="legal-strict")
    assert first.content_cid != second.content_cid
    assert first.source_digest == second.source_digest

    with pytest.raises(LegalProofCacheError, match="specify profile"):
        cache.get_by_source_digest(first.source_digest)

    assert (
        cache.get_by_source_digest(
            first.source_digest, profile="legal-default"
        ).content_cid
        == first.content_cid
    )
    assert (
        cache.get_by_source_digest(
            first.source_digest, profile="legal-strict"
        ).content_cid
        == second.content_cid
    )
    assert cache.get_by_profile("legal-default").content_cid == first.content_cid
    assert cache.get_by_profile("legal-strict").content_cid == second.content_cid


def test_fixture_records_round_trip_through_disk_cache(tmp_path: Path) -> None:
    cache = LegalProofCache(root=tmp_path / "fixture-cache")
    for name in ("us_code_552", "us_code_553"):
        sample = _manifest()["samples"][name]
        record = LegalProofRecord.from_dict(
            _load_json(FIXTURES / sample["record_path"])
        )
        stored = cache.put(record)
        assert stored.content_cid == sample["content_cid"]
        assert stored.source_digest == sample["source_digest"]

    reloaded = LegalProofCache(root=tmp_path / "fixture-cache")
    assert set(reloaded.profiles()) == {"legal-strict", "legal-dev-offline"}
    assert reloaded.reload() == 2
    for name, sample in _manifest()["samples"].items():
        by_source = reloaded.get_by_source_digest(
            sample["source_digest"], profile=sample["profile"]
        )
        assert by_source.content_cid == sample["content_cid"]
        assert name


def test_offline_rebuild_from_fixture_dir(tmp_path: Path) -> None:
    cache = rebuild_offline_from_fixture_dir(
        FIXTURES, root=tmp_path / "offline-rebuild"
    )
    assert len(cache) == 2
    for sample in _manifest()["samples"].values():
        loaded = cache.get(sample["content_cid"])
        assert loaded.source_digest == sample["source_digest"]
        assert loaded.profile == sample["profile"]


def test_corruption_of_content_digest_fails_closed(tmp_path: Path) -> None:
    artifact = _legal_artifact()
    cache_dir = tmp_path / "corrupt"
    cache = LegalProofCache(root=cache_dir)
    record = cache.put(artifact, profile="legal-strict")

    path = cache_dir / "records" / f"{record.content_cid}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["content_digest"] = "sha256:" + ("ab" * 32)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(LegalProofIntegrityError):
        LegalProofCache(root=cache_dir)


def test_corruption_of_artifact_payload_fails_closed(tmp_path: Path) -> None:
    artifact = _legal_artifact()
    cache_dir = tmp_path / "corrupt-artifact"
    cache = LegalProofCache(root=cache_dir)
    record = cache.put(artifact, profile="legal-strict")

    path = cache_dir / "records" / f"{record.content_cid}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Tamper with a nested field while leaving digests as written.
    payload["artifact"]["declaration_id"] = "legal:mutated-declaration"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(LegalProofIntegrityError):
        LegalProofCache(root=cache_dir)


def test_put_get_functional_wrappers_and_theorem_receipt(
    tmp_path: Path,
) -> None:
    artifact = _legal_artifact()
    receipt = _theorem_receipt_for(artifact)
    cache = LegalProofCache(root=tmp_path / "receipt-cache")

    record = put_legal_proof(
        cache,
        artifact,
        profile="legal-with-receipt",
        jurisdiction="us-federal",
        theorem_receipts=(receipt,),
    )
    loaded = get_legal_proof(cache, record.content_cid)
    receipts = loaded.theorem_receipt_results()
    assert len(receipts) == 1
    assert receipts[0].proof_authority is AuthorityKind.THEOREM_PROOF
    assert receipts[0].status is ResultStatus.PROVED
    assert receipts[0].declaration_id == artifact.declaration_id


def test_no_cache_hit_without_integrity(tmp_path: Path) -> None:
    """A digest mismatch is never treated as a successful hit."""

    artifact = _legal_artifact()
    cache_dir = tmp_path / "no-false-hit"
    cache = LegalProofCache(root=cache_dir)
    record = cache.put(artifact, profile="legal-strict")

    path = cache_dir / "records" / f"{record.content_cid}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_digest"] = "sha256:" + ("cd" * 32)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(LegalProofIntegrityError):
        LegalProofCache(root=cache_dir).get(record.content_cid)


def test_source_identity_immutable_under_cache(tmp_path: Path) -> None:
    artifact = _legal_artifact()
    before = (artifact.digest, artifact.declaration_digest, artifact.to_dict())
    cache = LegalProofCache(root=tmp_path / "identity")
    record = cache.put(artifact, profile="legal-strict")
    after = (artifact.digest, artifact.declaration_digest, artifact.to_dict())
    assert before == after
    assert record.artifact_digest == before[0]
    assert record.source_digest == before[1]
    mutable = record.to_dict()
    mutable["source_id"] = "legal:mutated"
    assert cache.get(record.content_cid).source_id == artifact.declaration_id


def test_memory_only_cache_put_get_and_reload() -> None:
    artifact = _legal_artifact()
    cache = LegalProofCache()
    record = cache.put(artifact, profile="legal-memory")
    assert cache.contains(record.content_cid)
    assert cache.get(record.content_cid).content_digest == record.content_digest
    assert cache.reload() == 1


def test_put_finished_record_rejects_conflicting_profile(tmp_path: Path) -> None:
    record = LegalProofRecord.from_dict(
        _load_json(FIXTURES / "us_code_552_record.json")
    )
    cache = LegalProofCache(root=tmp_path / "conflict")
    with pytest.raises(LegalProofCacheError, match="profile argument"):
        cache.put(record, profile="other-profile")


def test_missing_profile_and_missing_indexes(tmp_path: Path) -> None:
    cache = LegalProofCache(root=tmp_path / "missing")
    artifact = _legal_artifact()
    with pytest.raises(LegalProofCacheError, match="profile is required"):
        cache.put(artifact)
    with pytest.raises(LegalProofCacheError, match="not found"):
        cache.get("bafybeigmissinglegalproofcid000000000000000000000000000000")
    with pytest.raises(LegalProofCacheError, match="no proof record"):
        cache.get_by_profile("does-not-exist")
    with pytest.raises(LegalProofCacheError, match="no proof record"):
        cache.get_by_source_digest("sha256:" + ("11" * 32))


def test_invalid_profile_rejected() -> None:
    artifact = _legal_artifact()
    with pytest.raises(LegalProofCacheError, match="profile"):
        LegalProofRecord.build(artifact, profile="Not Valid")


def test_source_digest_mismatch_rejected() -> None:
    artifact = _legal_artifact()
    with pytest.raises(LegalProofCacheError, match="source_digest"):
        LegalProofRecord.build(
            artifact,
            profile="legal-strict",
            source_digest="sha256:" + ("ee" * 32),
        )


def test_non_legal_domain_artifact_rejected(tmp_path: Path) -> None:
    artifact = _legal_artifact()
    payload = artifact.to_dict()
    payload["domain"] = "security"
    cache = LegalProofCache(root=tmp_path / "domain")
    with pytest.raises(LegalProofCacheError, match="legal-domain"):
        cache.put(payload, profile="legal-strict")
