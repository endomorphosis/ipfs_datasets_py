"""Unit tests for LegalProofCache@1 put/get integrity, hit/miss, and indexes."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
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
    LEGAL_BOUND_PROOF_RECORD_SCHEMA_VERSION,
    LEGAL_PROOF_CONTEXT_SCHEMA_VERSION,
    build_legal_proof_binding,
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


FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "legal_ir" / "proof_cache"


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
        record = LegalProofRecord.from_dict(_load_json(FIXTURES / sample["record_path"]))
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
    assert not cache.contains("bafybeigmissinglegalproofcid000000000000000000000000000000")

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
    by_source_profile = reloaded.get_by_source_digest(record.source_digest, profile="legal-strict")
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
        cache.get_by_source_digest(first.source_digest, profile="legal-default").content_cid
        == first.content_cid
    )
    assert (
        cache.get_by_source_digest(first.source_digest, profile="legal-strict").content_cid
        == second.content_cid
    )
    assert cache.get_by_profile("legal-default").content_cid == first.content_cid
    assert cache.get_by_profile("legal-strict").content_cid == second.content_cid


def test_fixture_records_round_trip_through_disk_cache(tmp_path: Path) -> None:
    cache = LegalProofCache(root=tmp_path / "fixture-cache")
    for name in ("us_code_552", "us_code_553"):
        sample = _manifest()["samples"][name]
        record = LegalProofRecord.from_dict(_load_json(FIXTURES / sample["record_path"]))
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
    cache = rebuild_offline_from_fixture_dir(FIXTURES, root=tmp_path / "offline-rebuild")
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
    # The old fixture attached an unrelated obligation to an artifact declaring
    # no obligations. That historical association is no longer a positive proof.
    artifact, receipt, binding, context = _bound_fixture()
    cache = LegalProofCache(root=tmp_path / "receipt-cache")

    record = put_legal_proof(
        cache,
        artifact,
        profile="legal-with-receipt",
        jurisdiction="fictional",
        theorem_receipts=(receipt,),
        proof_bindings=(binding,),
    )
    loaded = get_legal_proof(cache, record.content_cid)
    receipts = loaded.theorem_receipt_results(expected_context=context)
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
    record = LegalProofRecord.from_dict(_load_json(FIXTURES / "us_code_552_record.json"))
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



# These v2 fixtures model binding consistency only. No compiler process or
# actual statutory review is executed or represented by any helper below.
def _fictional_native_identity(*, executable="/fictional/lean", version="test"):
    from ipfs_datasets_py.logic.backends.kernel import lean
    stats=lean.FrozenMap(dict(device=1,inode=1,size=1,mtime_ns=1,ctime_ns=1))
    return lean.LeanNativeIdentity(resolved_executable=executable,executable_sha256="d"*64,executable_bytes=1,
        executable_stat_before=stats,executable_stat_after=stats,actual_version=version,
        version_stdout="Lean (version "+version+")",version_stderr="",version_command=(executable,"--version"),
        version_returncode=0,observation_kind="trusted_fictional_identity_fixture")


def _fictional_kernel_receipt(request):
    from ipfs_datasets_py.logic.backends.kernel import lean
    from ipfs_datasets_py.logic.backends.kernel.wasm import CapabilityPlane,KernelSourceTreeBinding,KernelToolchainBinding
    payload=request.payload.to_dict()
    source=payload.get("lean")or payload.get("source")or payload.get("checked_source")
    name=payload["expected_declaration"];proposition=payload["expected_proposition"]
    guard=lean.lean_expected_obligation_declaration(source,name,proposition)
    compiled=lean.instrument_lean_source_for_axioms(source,name,expected_proposition=proposition)
    proof=lean.extract_generated_proof(source,name);policy=lean.lean_axiom_policy_digest(())
    identity=_fictional_native_identity(version="fictional")
    return lean.LeanKernelReceipt(request_digest=request.digest,source_binding=lean.LeanSourceBinding.bind(request,source),
        theorem_name=name,theorem_digest=lean.content_digest(source),imports=lean.extract_lean_imports(source),
        generated_proof=proof,generated_proof_digest=lean.content_digest(proof),
        toolchain=KernelToolchainBinding(toolchain_id="fictional:lean-v3",kernel_id="lean",plane=CapabilityPlane.NATIVE,
            executable=identity.resolved_executable,version=identity.actual_version,metadata=lean.FrozenMap({
                "approved_axioms":[],"approved_imports":list(lean.LEAN_DEFAULT_APPROVED_IMPORTS),"axiom_policy_digest":policy,
                "native_identity_digest":identity.identity_digest,"native_library_scope":identity.library_scope})),
        source_tree=KernelSourceTreeBinding.from_files({"Main.lean":source},primary_path="Main.lean"),translation=None,
        axiom_report=lean.LeanAxiomReport(declaration=guard,report_text="'"+guard+"' does not depend on any axioms",axioms=(),
            contains_sorry_ax=False,source_path="Main.lean",source_line=compiled[:compiled.rfind("#print axioms")].count("\n")+1,source_column=0),
        plane=CapabilityPlane.NATIVE,accepted=True,authority_disposition=lean.LeanAuthorityDisposition.REJECT,
        submitted_source=source,expected_obligation_declaration=guard,native_identity=identity,native_identity_checked_after_compile=True,
        expected_proposition=proposition,expected_proposition_digest=lean.content_digest(proposition),expected_proposition_checked=True,
        compiled_source_digest=lean.content_digest(compiled),approved_axioms=(),approved_imports=lean.LEAN_DEFAULT_APPROVED_IMPORTS,axiom_policy_digest=policy)


def _bound_fixture(*, extra_obligation: bool = False):
    from ipfs_datasets_py.logic.backends.kernel import lean
    from ipfs_datasets_py.logic.backends.kernel.wasm import CapabilityPlane, KernelToolchainBinding
    from ipfs_datasets_py.logic.ir_core.claims import FrozenMap

    sample = _reviewed_fixture(sample_id="fictional-cache-provision", citation="FICTIONAL Test Act 1", section="1")
    artifact = _legal_artifact(sample)
    source_ref = artifact.source_map.sources[0].ref_id
    assumption = Assumption("assumption:fictional-premise", "An explicitly fictional premise.", source_refs=(source_ref,))
    obligation = ProofObligation("obligation:fictional-cache", "True", assumption_ids=(assumption.assumption_id,),
                                 logic_family="lean4", source_refs=(source_ref,), metadata={"fixture_only": True})
    obligations = (obligation,)
    if extra_obligation:
        obligations += (replace(obligation, obligation_id="obligation:unproved-second"),)
    artifact = replace(artifact, assumptions=(assumption,), proof_obligations=obligations)
    policy = lean.lean_axiom_policy_digest(())
    identity = _fictional_native_identity(version="fictional")
    toolchain = KernelToolchainBinding(toolchain_id="fictional:lean-v3", kernel_id="lean", plane=CapabilityPlane.NATIVE,
        executable=identity.resolved_executable, version=identity.actual_version,
        metadata=FrozenMap({"approved_axioms": [], "approved_imports": list(lean.LEAN_DEFAULT_APPROVED_IMPORTS),
            "axiom_policy_digest": policy, "native_identity_digest": identity.identity_digest,
            "native_library_scope": identity.library_scope}))
    context = dict(schema_version=LEGAL_PROOF_CONTEXT_SCHEMA_VERSION, jurisdiction="fictional",
        interpretation_digest=stable_digest({"fictional_interpretation": 1}),
        dependency_versions={"fictional-definition": stable_digest({"definition": 1})},
        backend_id="lean", backend_version="fictional", toolchain=toolchain.to_dict(),
        expected_declaration="cache_fixture", expected_proposition="True", axiom_policy_digest=policy)
    claim = IRClaim(claim_id="claim:fictional-cache", declaration_id=artifact.declaration_id, statement="True",
        assumptions=artifact.assumptions, obligations=(obligation,), domain="legal", source_refs=(source_ref,),
        metadata={"artifact_digest": artifact.digest, "source_digest": artifact.declaration_digest,
                  "proof_context_digest": stable_digest(context)})
    request = BackendRequest.for_claim(claim, obligation.obligation_id, request_id="request:fictional-cache",
        requested_backend_id="lean", bounds=ExecutionBounds(timeout_ms=1000, max_steps=1000,
            max_memory_bytes=1000000, max_output_bytes=4096),
        payload={"lean": "theorem cache_fixture : True := by trivial\n", "expected_declaration": "cache_fixture",
                 "expected_proposition": "True", "legal_proof_context": context})
    kernel = _fictional_kernel_receipt(request)
    attempt = BackendAttempt(attempt_id="attempt:fictional-cache", request_digest=request.digest, backend_id="lean",
        backend_version="fictional", status=AttemptStatus.SUCCEEDED, bounds=request.bounds,
        usage=ResourceUsage(elapsed_ms=1, steps=1, peak_memory_bytes=1024, output_bytes=40),
        output_digest=stable_digest({"authored_kernel_fixture": kernel.to_dict()}))
    result = ProofResult.for_attempt(request, attempt, result_id="result:fictional-cache",
        authority=ResultAuthority(kind=AuthorityKind.THEOREM_PROOF, issuer="fictional-test",
            method="authored-fixture-only", scope_digest=request.digest,
            configuration_digest=stable_digest(context)), status=ResultStatus.PROVED,
        payload={"kernel_receipt": kernel.to_dict(), "fixture_only": True})
    receipt = ProofReceipt.issue(claim, request, attempt, result, receipt_id="receipt:fictional-cache", verifier="fictional-test")
    binding = build_legal_proof_binding(artifact, receipt, claim=claim, request=request, attempt=attempt,
                                      result=result, context=context)
    return artifact, receipt, binding, context


def _bound_record(*, extra_obligation: bool = False):
    artifact, receipt, binding, context = _bound_fixture(extra_obligation=extra_obligation)
    record = LegalProofRecord.build(artifact, profile="fictional-bound", jurisdiction="fictional",
                                    theorem_receipts=(receipt,), proof_bindings=(binding,))
    return record, artifact, receipt, binding, context


class _ShadowObservation:
    def __init__(self):
        self.writes = []
    def register_backend(self, backend):
        pass
    def project_key(self, *args, **kwargs):
        return kwargs
    def write(self, *args, **kwargs):
        self.writes.append(kwargs)


def test_new_unbound_receipt_association_is_rejected() -> None:
    artifact = _legal_artifact()
    assert artifact.proof_obligations == ()
    with pytest.raises(LegalProofCacheError, match="proof_bindings"):
        LegalProofRecord.build(artifact, profile="unbound", theorem_receipts=(_theorem_receipt_for(artifact),))


def test_legacy_receipts_remain_archival_without_shadow_authority() -> None:
    artifact = _legal_artifact()
    header = _theorem_receipt_for(artifact)
    record = LegalProofRecord(source_id=artifact.declaration_id, source_digest=artifact.declaration_digest,
        profile="historical-unbound", artifact=artifact.to_dict(), theorem_receipts=(header.to_dict(),))
    restored = LegalProofRecord.from_dict(record.to_dict())
    assert restored.content_cid == record.content_cid
    assert restored.schema_version == LEGAL_PROOF_RECORD_SCHEMA_VERSION
    assert restored.theorem_receipts[0]["obligation_id"] == header.obligation_id
    with pytest.raises(LegalProofIntegrityError, match="archival"):
        restored.theorem_receipt_results()
    spy = _ShadowObservation()
    cache = LegalProofCache()
    cache.bind_shadow_repository(spy)
    cache.put(restored)
    assert spy.writes[-1]["status"] == "unknown"
    assert spy.writes[-1]["kernel_accepted"] is False


def test_archival_envelope_mutation_cannot_keep_old_content_identity() -> None:
    artifact = _legal_artifact()
    record = LegalProofRecord(source_id=artifact.declaration_id, source_digest=artifact.declaration_digest,
        profile="historical-mutation", artifact=artifact.to_dict(),
        theorem_receipts=(_theorem_receipt_for(artifact).to_dict(),))
    record.theorem_receipts[0]["assumption_ids"].append("assumption:tampered")
    with pytest.raises(LegalProofIntegrityError, match="envelope mutated"):
        record.verify_integrity()


def test_bound_record_v2_disk_round_trip_and_explicit_context(tmp_path: Path) -> None:
    record, artifact, receipt, _, context = _bound_record()
    assert record.schema_version == LEGAL_BOUND_PROOF_RECORD_SCHEMA_VERSION
    cache = LegalProofCache(root=tmp_path / "bound")
    cache.put(record)
    restored = LegalProofCache(root=tmp_path / "bound").get(record.content_cid)
    assert restored.theorem_receipt_results(expected_context=context, obligation_id=receipt.obligation_id) == (receipt,)
    assert restored.artifact_digest == artifact.digest
    with pytest.raises(LegalProofCacheError, match="expected_context"):
        restored.theorem_receipt_results()


@pytest.mark.parametrize("facet", ["toolchain", "backend", "interpretation", "dependencies", "declaration", "proposition", "axiom-policy", "jurisdiction"])
def test_proof_reuse_rejects_changed_expected_context(facet: str) -> None:
    record, _, _, _, context = _bound_record()
    changed = deepcopy(context)
    if facet == "toolchain":
        changed["toolchain"]["version"] = "other"
    elif facet == "backend":
        changed["backend_version"] = "other"
    elif facet == "interpretation":
        changed["interpretation_digest"] = stable_digest({"fictional_interpretation": 2})
    elif facet == "dependencies":
        changed["dependency_versions"]["fictional-definition"] = stable_digest({"definition": 2})
    elif facet == "declaration":
        changed["expected_declaration"] = "another_theorem"
    elif facet == "proposition":
        changed["expected_proposition"] = "False"
    elif facet == "axiom-policy":
        changed["axiom_policy_digest"] = stable_digest({"approved_axioms": ["foreign"]})
    else:
        changed["jurisdiction"] = "different"
    with pytest.raises(LegalProofIntegrityError, match="expected reuse context"):
        record.theorem_receipt_results(expected_context=changed)


@pytest.mark.parametrize(("field", "value"), [
    ("claim_digest", "ab" * 32), ("obligation_digest", "cd" * 32),
    ("assumption_ids", ("assumption:unprovided",)), ("backend_id", "other-kernel"),
    ("backend_version", "other-version"), ("declaration_id", "another-declaration"),
])
def test_bound_receipt_header_changes_fail_chain_replay(field: str, value: Any) -> None:
    _, artifact, receipt, binding, _ = _bound_record()
    changed = replace(receipt, **{field: value})
    binding = deepcopy(binding)
    binding["receipt_digest"] = changed.digest
    with pytest.raises(LegalProofCacheError):
        LegalProofRecord.build(artifact, profile="changed-header", jurisdiction="fictional",
                              theorem_receipts=(changed,), proof_bindings=(binding,))


@pytest.mark.parametrize("facet", ["source", "obligation", "assumptions"])
def test_bound_proof_cannot_follow_changed_formal_artifact(facet: str) -> None:
    _, artifact, receipt, binding, _ = _bound_record()
    if facet == "source":
        changed = replace(artifact, declaration_digest="sha256:" + "fa" * 32)
    elif facet == "obligation":
        changed = replace(artifact, proof_obligations=(replace(artifact.proof_obligations[0], statement="False"),))
    else:
        changed = replace(artifact, assumptions=(replace(artifact.assumptions[0], statement="Different fictional premise."),))
    assert changed.digest != artifact.digest
    with pytest.raises(LegalProofIntegrityError):
        LegalProofRecord.build(changed, profile="changed-artifact", jurisdiction="fictional",
                              theorem_receipts=(receipt,), proof_bindings=(binding,))


def test_current_bound_context_is_recursively_immutable() -> None:
    record, _, _, _, _ = _bound_record()
    with pytest.raises(TypeError):
        record.proof_bindings[0]["context"]["toolchain"]["version"] = "tampered"


def test_partial_obligation_coverage_does_not_grant_whole_artifact_shadow_proof() -> None:
    record, _, _, _, _ = _bound_record(extra_obligation=True)
    spy = _ShadowObservation()
    cache = LegalProofCache()
    cache.bind_shadow_repository(spy)
    cache.put(record)
    assert spy.writes[-1]["status"] == "unknown"
    assert spy.writes[-1]["kernel_accepted"] is False


@pytest.mark.parametrize("facet", ["legacy-schema", "legacy-native-v2", "unchecked-proposition", "wrong-compiled-source", "missing-native-identity", "wrong-guard-declaration"])
def test_reissued_header_cannot_launder_invalid_kernel_evidence(facet: str) -> None:
    _, artifact, _, binding, context = _bound_record()
    claim = IRClaim.from_dict(binding["claim"])
    request = BackendRequest.from_dict(binding["request"])
    attempt = BackendAttempt.from_dict(binding["attempt"])
    result = ProofResult.from_dict(binding["result"])
    payload = result.payload.to_dict()
    if facet == "legacy-schema":
        payload["kernel_receipt"]["schema_version"] = "lean-kernel-receipt/v1"
    elif facet == "legacy-native-v2":
        payload["kernel_receipt"]["schema_version"] = "lean-kernel-receipt/v2"
    elif facet == "missing-native-identity":
        payload["kernel_receipt"]["native_identity"] = None
    elif facet == "wrong-guard-declaration":
        payload["kernel_receipt"]["expected_obligation_declaration"] = "unrelated_guard"
    elif facet == "unchecked-proposition":
        payload["kernel_receipt"]["expected_proposition_checked"] = False
    else:
        payload["kernel_receipt"]["compiled_source_digest"] = "ab" * 32
    result = replace(result, payload=payload)
    receipt = ProofReceipt.issue(claim, request, attempt, result, receipt_id="receipt:altered-kernel", verifier="fictional-test")
    changed = deepcopy(binding)
    changed.update(receipt_digest=receipt.digest, result=result.to_dict())
    with pytest.raises(LegalProofIntegrityError):
        LegalProofRecord.build(artifact, profile="invalid-kernel", jurisdiction="fictional",
                              theorem_receipts=(receipt,), proof_bindings=(changed,))


def test_v1_positional_constructor_arguments_keep_their_original_meaning() -> None:
    artifact = _legal_artifact()
    record = LegalProofRecord(artifact.declaration_id, artifact.declaration_digest,
                              "positional-v1", artifact.to_dict(), "", "", (), "us-federal")
    assert record.jurisdiction == "us-federal"
    assert record.proof_bindings == ()
    assert record.schema_version == LEGAL_PROOF_RECORD_SCHEMA_VERSION


def test_bound_shadow_proof_scope_is_formal_obligations_only() -> None:
    record, _, _, _, _ = _bound_record()
    spy = _ShadowObservation()
    cache = LegalProofCache()
    cache.bind_shadow_repository(spy)
    cache.put(record)
    row = spy.writes[-1]
    assert row["status"] == "proved" and row["kernel_accepted"] is True
    assert row["result_payload"]["property"] == "declared_formal_obligation_coverage"
    assert row["result_payload"]["required_obligation_ids"] == ["obligation:fictional-cache"]
    assert all(row["result_payload"][name] is False for name in ("source_admission", "legal_admission", "corpus_admission"))
    assert row["key"]["property_value"]["property"] == "declared_formal_obligation_coverage"


def test_v1_artifact_shadow_key_keeps_its_existing_dimensions() -> None:
    artifact = _legal_artifact()
    spy = _ShadowObservation()
    cache = LegalProofCache()
    cache.bind_shadow_repository(spy)
    record = cache.put(artifact, profile="artifact-v1", jurisdiction="us-federal")
    key = spy.writes[-1]["key"]
    assert key["toolchain"] == {"legal_ir": True}
    assert key["ir"] == {"source_id": record.source_id, "source_digest": record.source_digest,
                         "artifact_cid": record.artifact_cid}
    assert key["policy"] == {"profile": "artifact-v1", "jurisdiction": "us-federal"}
    assert "property_value" not in key


@pytest.mark.parametrize("facet", ["artifact", "receipt"])
def test_shadow_writer_rechecks_a_detached_snapshot_after_nested_mutation(facet: str) -> None:
    record, _, _, _, _ = _bound_record()
    record.verify_integrity()
    if facet == "artifact":
        record.artifact["metadata"]["post_verify_mutation"] = True
    else:
        record.theorem_receipts[0]["assumption_ids"].append("assumption:post-verify")
    spy = _ShadowObservation()
    cache = LegalProofCache()
    cache.bind_shadow_repository(spy)
    cache._shadow_write(record)
    assert spy.writes == []


def test_bound_proof_binding_normalizes_protocol_frozen_kernel_payload_to_canonical_wire():
    """FrozenMap tuples are internal protocol storage, not serialized Lean wire."""
    from ipfs_datasets_py.logic.backends.kernel import lean

    artifact, receipt, binding, context = _bound_fixture()
    result = ProofResult.from_dict(binding["result"])
    frozen = result.payload["kernel_receipt"]
    assert type(frozen["approved_axioms"]) is tuple
    assert type(result.to_dict()["payload"]["kernel_receipt"]["approved_axioms"]) is list
    with pytest.raises((lean.LeanKernelError, ValueError)):
        lean.LeanKernelReceipt.from_dict(frozen)
    rebuilt = build_legal_proof_binding(artifact, receipt,
        claim=IRClaim.from_dict(binding["claim"]), request=BackendRequest.from_dict(binding["request"]),
        attempt=BackendAttempt.from_dict(binding["attempt"]), result=result, context=context)
    assert rebuilt == binding


def test_genuine_archived_native_v2_false_acceptance_is_not_upgraded_or_reused():
    """The preserved native run is a reproduced failure, never a v3 proof."""
    from ipfs_datasets_py.logic.backends.kernel import lean
    data = json.loads((FIXTURES / "native_v2" / "implicit_instance_false_acceptance.json").read_text())
    archived = data["receipt"]
    before = deepcopy(archived)
    request = BackendRequest.from_dict(data["request"])
    assert data["original_observation"]["sha256"] == "a80c792a2dc9ae899a783a71c62b925bb6a941205b90cf2040a80d16e96cded2"
    assert archived["schema_version"] == "lean-kernel-receipt/v2" and archived["accepted"] is True
    assert archived["request_digest"] == request.digest
    source = request.payload.get("lean") or request.payload.get("source") or request.payload.get("checked_source")
    assert archived["source_binding"]["source_digest"] == lean.content_digest(source)
    assert archived["receipt_id"] == data["original_receipt_id"]
    with pytest.raises((lean.LeanKernelError, ValueError)):
        lean.LeanKernelReceipt.from_dict(archived)
    assert archived == before


def test_bound_proof_reuse_refuses_an_installed_older_kernel_profile(monkeypatch):
    from ipfs_datasets_py.logic.backends.kernel import lean
    artifact, receipt, binding, _ = _bound_fixture()
    calls = []
    class OlderParser:
        @staticmethod
        def from_dict(value):
            calls.append(value)
            raise AssertionError("known-bad older verification profile must not run")
    monkeypatch.setattr(lean, "LEAN_KERNEL_RECEIPT_VERSION", "lean-kernel-receipt/v2")
    monkeypatch.setattr(lean, "LeanKernelReceipt", OlderParser)
    with pytest.raises(LegalProofIntegrityError, match="v3"):
        LegalProofRecord.build(artifact, profile="older-owner", jurisdiction="fictional",
            theorem_receipts=(receipt,), proof_bindings=(binding,))
    assert calls == []
