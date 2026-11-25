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


def _fictional_kernel_receipt(request, *, toolchain=None):
    from ipfs_datasets_py.logic.backends.kernel import lean
    from ipfs_datasets_py.logic.backends.kernel.wasm import CapabilityPlane,KernelSourceTreeBinding,KernelToolchainBinding
    payload=request.payload.to_dict()
    # Deliberately retain legacy selection while constructing fictional receipt
    # headers. Cache replay must independently enforce the current backend policy.
    source=payload.get("lean")or payload.get("source")or payload.get("checked_source")
    name=payload["expected_declaration"];proposition=payload["expected_proposition"]
    guard=lean.lean_expected_obligation_declaration(source,name,proposition)
    compiled=lean.instrument_lean_source_for_axioms(source,name,expected_proposition=proposition)
    proof=lean.extract_generated_proof(source,name);policy=lean.lean_axiom_policy_digest(())
    identity=_fictional_native_identity(version="fictional")
    return lean.LeanKernelReceipt(request_digest=request.digest,source_binding=lean.LeanSourceBinding.bind(request,source),
        theorem_name=name,theorem_digest=lean.content_digest(source),imports=lean.extract_lean_imports(source),
        generated_proof=proof,generated_proof_digest=lean.content_digest(proof),
        toolchain=toolchain if toolchain is not None else KernelToolchainBinding(toolchain_id="fictional:lean-v3",kernel_id="lean",plane=CapabilityPlane.NATIVE,
            executable=identity.resolved_executable,version=identity.actual_version,metadata=lean.FrozenMap({
                "approved_axioms":[],"approved_imports":list(lean.LEAN_DEFAULT_APPROVED_IMPORTS),"axiom_policy_digest":policy,
                "native_identity_digest":identity.identity_digest,"native_library_scope":identity.library_scope,
                "verification_profile":lean.LEAN_KERNEL_VERIFICATION_PROFILE})),
        source_tree=KernelSourceTreeBinding.from_files({"Main.lean":source},primary_path="Main.lean"),translation=None,
        axiom_report=lean.LeanAxiomReport(declaration=guard,report_text="'"+guard+"' does not depend on any axioms",axioms=(),
            contains_sorry_ax=False,source_path="Main.lean",source_line=compiled[:compiled.rfind("#print axioms")].count("\n")+1,source_column=0),
        plane=CapabilityPlane.NATIVE,accepted=True,authority_disposition=lean.LeanAuthorityDisposition.REJECT,
        submitted_source=source,expected_obligation_declaration=guard,native_identity=identity,native_identity_checked_after_compile=True,
        expected_proposition=proposition,expected_proposition_digest=lean.content_digest(proposition),expected_proposition_checked=True,
        compiled_source_digest=lean.content_digest(compiled),approved_axioms=(),approved_imports=lean.LEAN_DEFAULT_APPROVED_IMPORTS,axiom_policy_digest=policy)


def _bound_fixture(*, extra_obligation: bool = False,
                   native_resource_profile: dict[str, Any] | None = None,
                   request_native_resource_profile: dict[str, Any] | None = None,
                   kernel_native_resource_profile: dict[str, Any] | None = None,
                   source_aliases: dict[str, Any] | None = None):
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
            "native_library_scope": identity.library_scope,
            "verification_profile": lean.LEAN_KERNEL_VERIFICATION_PROFILE}))
    if native_resource_profile is not None:
        toolchain = replace(toolchain, metadata={**toolchain.metadata.to_dict(),
            "native_resource_profile": deepcopy(native_resource_profile)})
    context = dict(schema_version=LEGAL_PROOF_CONTEXT_SCHEMA_VERSION, jurisdiction="fictional",
        interpretation_digest=stable_digest({"fictional_interpretation": 1}),
        dependency_versions={"fictional-definition": stable_digest({"definition": 1})},
        backend_id="lean", backend_version="fictional", toolchain=toolchain.to_dict(),
        expected_declaration="cache_fixture", expected_proposition="True", axiom_policy_digest=policy)
    claim = IRClaim(claim_id="claim:fictional-cache", declaration_id=artifact.declaration_id, statement="True",
        assumptions=artifact.assumptions, obligations=(obligation,), domain="legal", source_refs=(source_ref,),
        metadata={"artifact_digest": artifact.digest, "source_digest": artifact.declaration_digest,
                  "proof_context_digest": stable_digest(context)})
    request_context = deepcopy(context)
    if request_native_resource_profile is not None:
        request_context["toolchain"]["metadata"]["native_resource_profile"] = deepcopy(request_native_resource_profile)
    request = BackendRequest.for_claim(claim, obligation.obligation_id, request_id="request:fictional-cache",
        requested_backend_id="lean", bounds=ExecutionBounds(timeout_ms=1000, max_steps=1000,
            max_memory_bytes=1000000, max_output_bytes=4096),
        payload={**({"lean": "theorem cache_fixture : True := by trivial\n"}
                    if source_aliases is None else deepcopy(source_aliases)),
                 "expected_declaration": "cache_fixture",
                 "expected_proposition": "True", "legal_proof_context": request_context})
    kernel_toolchain = toolchain
    if kernel_native_resource_profile is not None:
        kernel_toolchain = replace(toolchain, metadata={**toolchain.metadata.to_dict(),
            "native_resource_profile": deepcopy(kernel_native_resource_profile)})
    kernel = _fictional_kernel_receipt(request, toolchain=kernel_toolchain)
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



@pytest.mark.parametrize("alias", ["lean", "source", "checked_source"])
@pytest.mark.parametrize("value", [
    pytest.param(False, id="false"),
    pytest.param(0, id="zero-int"),
    pytest.param(0.0, id="zero-float"),
    pytest.param([], id="empty-list"),
    pytest.param({}, id="empty-mapping"),
])
def test_bound_proof_rejects_legacy_falsey_nontext_source_alias(alias: str, value: Any) -> None:
    # The complete fictional chain selects valid Lean bytes under the old
    # truthiness rule; replay must not reinterpret the malformed alias as absent.
    source = "theorem cache_fixture : True := by trivial\n"
    aliases = {"source" if alias == "lean" else "lean": source, alias: value}
    with pytest.raises(LegalProofIntegrityError, match="current backend"):
        _bound_fixture(source_aliases=aliases)


@pytest.mark.parametrize("aliases", [
    pytest.param({"lean": "theorem cache_fixture : True := by trivial\n"}, id="lean-only"),
    pytest.param({"source": "theorem cache_fixture : True := by trivial\n"}, id="source-only"),
    pytest.param({"checked_source": "theorem cache_fixture : True := by trivial\n"}, id="checked-source-only"),
    pytest.param(dict.fromkeys(("lean", "source", "checked_source"),
                              "theorem cache_fixture : True := by trivial\n"), id="identical-aliases"),
    pytest.param({"lean": None, "source": "theorem cache_fixture : True := by trivial\n",
                  "checked_source": ""}, id="empty-optional-aliases"),
])
def test_bound_proof_preserves_canonical_source_alias_reuse(aliases: dict[str, Any]) -> None:
    artifact, receipt, binding, context = _bound_fixture(source_aliases=aliases)
    record = LegalProofRecord.build(artifact, profile="fictional-bound", jurisdiction="fictional",
        theorem_receipts=(receipt,), proof_bindings=(binding,))
    assert record.theorem_receipt_results(expected_context=context,
        obligation_id=receipt.obligation_id) == (receipt,)


def _bound_record(*, extra_obligation: bool = False, native_resource_profile: dict[str, Any] | None = None):
    artifact, receipt, binding, context = _bound_fixture(extra_obligation=extra_obligation,
                                                       native_resource_profile=native_resource_profile)
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


# Python treats these values as equal; their canonical JSON identities differ.
_NUMERIC_CONTEXT_ALIASES = [
    pytest.param(1, True, id="int-to-bool"),
    pytest.param(True, 1, id="bool-to-int"),
    pytest.param(1, 1.0, id="int-to-float"),
    pytest.param(1.0, 1, id="float-to-int"),
    pytest.param(True, 1.0, id="bool-to-float"),
    pytest.param(1.0, True, id="float-to-bool"),
]


@pytest.mark.parametrize(("stored", "alias"), _NUMERIC_CONTEXT_ALIASES)
def test_proof_reuse_requires_exact_json_numeric_context(stored: Any, alias: Any) -> None:
    record, _, receipt, _, context = _bound_record(native_resource_profile={"cpu_slots": stored})
    assert record.theorem_receipt_results(expected_context=context) == (receipt,)
    changed = deepcopy(context)
    changed["toolchain"]["metadata"]["native_resource_profile"]["cpu_slots"] = alias
    assert changed == context and stable_digest(changed) != stable_digest(context)
    with pytest.raises(LegalProofIntegrityError, match="expected reuse context"):
        record.theorem_receipt_results(expected_context=changed)


@pytest.mark.parametrize(("stored", "alias"), _NUMERIC_CONTEXT_ALIASES)
def test_bound_request_requires_exact_json_numeric_context(stored: Any, alias: Any) -> None:
    # The claim, request, attempt, kernel receipt and proof header are genuinely
    # reissued by the fixture owners. Only the two declared contexts disagree.
    with pytest.raises(LegalProofIntegrityError, match="backend request.*exact reuse context"):
        _bound_fixture(native_resource_profile={"cpu_slots": stored},
                       request_native_resource_profile={"cpu_slots": alias})


@pytest.mark.parametrize(("stored", "alias"), _NUMERIC_CONTEXT_ALIASES)
def test_checked_kernel_toolchain_requires_exact_json_numeric_context(stored: Any, alias: Any) -> None:
    with pytest.raises(LegalProofIntegrityError, match="checked kernel receipt.*proof context"):
        _bound_fixture(native_resource_profile={"cpu_slots": stored},
                       kernel_native_resource_profile={"cpu_slots": alias})


@pytest.mark.parametrize("numeric", [pytest.param(1, id="int"), pytest.param(True, id="bool"),
                                   pytest.param(1.0, id="float")])
def test_exact_typed_numeric_context_reuse_is_key_order_independent(numeric: Any) -> None:
    record, _, receipt, _, context = _bound_record(native_resource_profile={"cpu_slots": numeric,
                                                                         "child_process_slots": 4})
    reordered = dict(reversed(list(deepcopy(context).items())))
    reordered["toolchain"] = dict(reversed(list(reordered["toolchain"].items())))
    reordered["toolchain"]["metadata"] = dict(reversed(list(reordered["toolchain"]["metadata"].items())))
    profile = reordered["toolchain"]["metadata"]["native_resource_profile"]
    reordered["toolchain"]["metadata"]["native_resource_profile"] = dict(reversed(list(profile.items())))
    assert type(profile["cpu_slots"]) is type(numeric)
    assert stable_digest(reordered) == stable_digest(context)
    assert record.theorem_receipt_results(expected_context=reordered) == (receipt,)


@pytest.mark.parametrize("different", [pytest.param(2, id="different-int"), pytest.param(False, id="different-bool"),
                                     pytest.param(1.5, id="different-float")])
def test_proof_reuse_rejects_changed_numeric_context(different: Any) -> None:
    record, _, _, _, context = _bound_record(native_resource_profile={"cpu_slots": 1})
    changed = deepcopy(context)
    changed["toolchain"]["metadata"]["native_resource_profile"]["cpu_slots"] = different
    assert changed != context
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


# Reissue every protocol link with independently supplied artifact/claim content.
# Updating the artifact digest correctly avoids an unrelated early refusal. The
# extra-obligation mode explicitly enrolls the unselected target in the claim;
# its presence never establishes proof of that second target.
def _reissued_formal_content_binding(artifact_metadata: dict[str, Any],
                                    claim_metadata: dict[str, Any], *,
                                    facet: str = "assumption", reverse_content_order: bool = False):
    assert facet in {"assumption", "unselected-obligation"}
    artifact, _, previous_binding, context = _bound_fixture(extra_obligation=facet == "unselected-obligation")
    claim_assumptions = artifact.assumptions
    claim_obligations = artifact.proof_obligations[:1]
    if facet == "assumption":
        declared = replace(artifact.assumptions[0], metadata=deepcopy(artifact_metadata))
        artifact_assumptions = (declared,)
        claim_assumptions = (replace(declared, metadata=deepcopy(claim_metadata)),)
        if reverse_content_order:
            second = replace(declared, assumption_id="assumption:fictional-second-premise",
                statement="A second explicitly fictional premise.", metadata={"fixture_only": True})
            artifact_assumptions += (second,)
            claim_assumptions = (second,) + claim_assumptions
        artifact = replace(artifact, assumptions=artifact_assumptions)
    else:
        declared = replace(artifact.proof_obligations[1], metadata=deepcopy(artifact_metadata))
        artifact = replace(artifact, proof_obligations=(artifact.proof_obligations[0], declared))
        claim_obligations = (artifact.proof_obligations[0], replace(declared, metadata=deepcopy(claim_metadata)))
        if reverse_content_order:
            claim_obligations = tuple(reversed(claim_obligations))
    previous_claim = IRClaim.from_dict(previous_binding["claim"])
    claim = replace(previous_claim, assumptions=claim_assumptions, obligations=claim_obligations,
        metadata={**previous_claim.metadata.to_dict(), "artifact_digest": artifact.digest})
    previous_request = BackendRequest.from_dict(previous_binding["request"])
    request = BackendRequest.for_claim(claim, previous_request.obligation_id,
        request_id="request:fictional-formal-content", requested_backend_id="lean",
        bounds=previous_request.bounds, payload=previous_request.payload.to_dict())
    assert request.obligation_digest == artifact.proof_obligations[0].digest
    kernel = _fictional_kernel_receipt(request)
    previous_attempt = BackendAttempt.from_dict(previous_binding["attempt"])
    attempt = replace(previous_attempt, request_digest=request.digest,
        output_digest=stable_digest({"authored_kernel_fixture": kernel.to_dict()}))
    previous_result = ProofResult.from_dict(previous_binding["result"])
    result = ProofResult.for_attempt(request, attempt, result_id="result:fictional-formal-content",
        authority=replace(previous_result.authority, scope_digest=request.digest),
        status=ResultStatus.PROVED, payload={"kernel_receipt": kernel.to_dict(), "fixture_only": True})
    receipt = ProofReceipt.issue(claim, request, attempt, result,
        receipt_id="receipt:fictional-formal-content", verifier="fictional-test")
    assert receipt.obligation_digest == artifact.proof_obligations[0].digest
    binding = build_legal_proof_binding(artifact, receipt, claim=claim, request=request,
        attempt=attempt, result=result, context=context)
    return artifact, receipt, binding, context


@pytest.mark.parametrize(("artifact_value", "claim_value"), _NUMERIC_CONTEXT_ALIASES)
def test_bound_proof_rejects_numeric_assumption_alias(artifact_value: Any, claim_value: Any) -> None:
    artifact_metadata = {"fictional_threshold": artifact_value}
    claim_metadata = {"fictional_threshold": claim_value}
    assert artifact_metadata == claim_metadata
    assert stable_digest(artifact_metadata) != stable_digest(claim_metadata)
    with pytest.raises(LegalProofIntegrityError, match="formal assumption content"):
        _reissued_formal_content_binding(artifact_metadata, claim_metadata)


@pytest.mark.parametrize("numeric", [pytest.param(1, id="int"), pytest.param(True, id="bool"),
                                   pytest.param(1.0, id="float")])
def test_bound_proof_preserves_typed_assumption_content_and_order(numeric: Any) -> None:
    artifact_metadata = {"fictional_threshold": numeric,
                         "nested": {"fixture_only": True, "labels": ["fictional", "premise"]}}
    claim_metadata = {"nested": {"labels": ["fictional", "premise"], "fixture_only": True},
                      "fictional_threshold": numeric}
    artifact, receipt, binding, context = _reissued_formal_content_binding(
        artifact_metadata, claim_metadata, reverse_content_order=True)
    claim = IRClaim.from_dict(binding["claim"])
    assert [item.assumption_id for item in claim.assumptions] == list(reversed(
        [item.assumption_id for item in artifact.assumptions]))
    by_id = {item.assumption_id: item for item in claim.assumptions}
    assert all(item.digest == by_id[item.assumption_id].digest for item in artifact.assumptions)
    record = LegalProofRecord.build(artifact, profile="fictional-assumption-content", jurisdiction="fictional",
        theorem_receipts=(receipt,), proof_bindings=(binding,))
    assert record.theorem_receipt_results(expected_context=context) == (receipt,)


@pytest.mark.parametrize("different", [pytest.param(2, id="different-int"), pytest.param(False, id="different-bool"),
                                     pytest.param(1.5, id="different-float")])
def test_bound_proof_rejects_changed_numeric_assumption_content(different: Any) -> None:
    with pytest.raises(LegalProofIntegrityError, match="formal assumption content"):
        _reissued_formal_content_binding({"fictional_threshold": 1}, {"fictional_threshold": different})


@pytest.mark.parametrize(("artifact_value", "claim_value"), _NUMERIC_CONTEXT_ALIASES)
def test_bound_proof_rejects_numeric_unselected_obligation_alias(artifact_value: Any, claim_value: Any) -> None:
    artifact_metadata = {"fictional_threshold": artifact_value}
    claim_metadata = {"fictional_threshold": claim_value}
    assert artifact_metadata == claim_metadata
    assert stable_digest(artifact_metadata) != stable_digest(claim_metadata)
    with pytest.raises(LegalProofIntegrityError, match="claim obligation differs"):
        _reissued_formal_content_binding(artifact_metadata, claim_metadata, facet="unselected-obligation")


@pytest.mark.parametrize("numeric", [pytest.param(1, id="int"), pytest.param(True, id="bool"),
                                   pytest.param(1.0, id="float")])
def test_bound_proof_preserves_typed_unselected_obligation_content_and_order(numeric: Any) -> None:
    artifact_metadata = {"fictional_threshold": numeric,
                         "nested": {"fixture_only": True, "labels": ["fictional", "unproved"]}}
    claim_metadata = {"nested": {"labels": ["fictional", "unproved"], "fixture_only": True},
                      "fictional_threshold": numeric}
    artifact, receipt, binding, context = _reissued_formal_content_binding(
        artifact_metadata, claim_metadata, facet="unselected-obligation", reverse_content_order=True)
    claim = IRClaim.from_dict(binding["claim"])
    assert [item.obligation_id for item in claim.obligations] == list(reversed(
        [item.obligation_id for item in artifact.proof_obligations]))
    by_id = {item.obligation_id: item for item in claim.obligations}
    assert all(item.digest == by_id[item.obligation_id].digest for item in artifact.proof_obligations)
    record = LegalProofRecord.build(artifact, profile="fictional-extra-obligation", jurisdiction="fictional",
        theorem_receipts=(receipt,), proof_bindings=(binding,))
    assert record.theorem_receipt_results(expected_context=context, obligation_id=receipt.obligation_id) == (receipt,)
    spy = _ShadowObservation()
    cache = LegalProofCache()
    cache.bind_shadow_repository(spy)
    cache.put(record)
    assert spy.writes[-1]["status"] == "unknown" and spy.writes[-1]["kernel_accepted"] is False


@pytest.mark.parametrize("different", [pytest.param(2, id="different-int"), pytest.param(False, id="different-bool"),
                                     pytest.param(1.5, id="different-float")])
def test_bound_proof_rejects_changed_numeric_unselected_obligation_content(different: Any) -> None:
    with pytest.raises(LegalProofIntegrityError, match="claim obligation differs"):
        _reissued_formal_content_binding({"fictional_threshold": 1}, {"fictional_threshold": different},
                                         facet="unselected-obligation")


def test_current_lean_verification_profile_survives_bound_cache_wire_replay(tmp_path: Path) -> None:
    """Authored receipt integrity only: no compiler or native identity probe."""
    from ipfs_datasets_py.logic.backends.kernel import lean
    record, _, receipt, binding, context = _bound_record()
    assert context["toolchain"]["metadata"]["verification_profile"] == lean.LEAN_KERNEL_VERIFICATION_PROFILE
    kernel = binding["result"]["payload"]["kernel_receipt"]
    assert kernel["schema_version"] == "lean-kernel-receipt/v3"
    assert kernel["toolchain"]["metadata"]["verification_profile"] == lean.LEAN_KERNEL_VERIFICATION_PROFILE
    before = record.to_dict()
    cache = LegalProofCache(root=tmp_path / "current-profile-cache")
    cache.put(record)
    restored = LegalProofCache(root=tmp_path / "current-profile-cache").get(record.content_cid)
    reopened = LegalProofRecord.from_dict(restored.to_dict())
    assert reopened.to_dict() == before
    assert reopened.theorem_receipt_results(expected_context=context) == (receipt,)


@pytest.mark.parametrize("profile", [None, "lean-kernel-verification/older", False, 1, ["lean-kernel-verification/v1"], "lean-kernel-verification/v1"])
def test_reissued_kernel_profile_cannot_launder_old_or_wrong_verifier_into_current_cache(profile: Any) -> None:
    """Reissue the outer protocol; the canonical Lean parser must still refuse.

    Removing the marker constructs an explicitly fictional old-v3-shaped wire.
    It does not alter or upgrade any archived source, receipt or native result.
    """
    record, artifact, _, binding, _ = _bound_record()
    original = record.to_dict()
    claim = IRClaim.from_dict(binding["claim"])
    request = BackendRequest.from_dict(binding["request"])
    attempt = BackendAttempt.from_dict(binding["attempt"])
    result = ProofResult.from_dict(binding["result"])
    payload = result.payload.to_dict()
    metadata = payload["kernel_receipt"]["toolchain"]["metadata"]
    if profile is None:
        metadata.pop("verification_profile")
    else:
        metadata["verification_profile"] = deepcopy(profile)
    kernel = payload["kernel_receipt"]
    kernel["receipt_id"] = "lean-kernel-receipt:" + stable_digest(
        {key: value for key, value in kernel.items() if key != "receipt_id"})
    result = replace(result, payload=payload)
    receipt = ProofReceipt.issue(claim, request, attempt, result,
        receipt_id="receipt:fictional-reissued-wrong-verifier-profile", verifier="fictional-test")
    changed = deepcopy(binding)
    changed.update(receipt_digest=receipt.digest, result=result.to_dict())
    with pytest.raises(LegalProofIntegrityError, match="canonical checked Lean v3 receipt") as caught:
        LegalProofRecord.build(artifact, profile="fictional-wrong-verifier-profile", jurisdiction="fictional",
            theorem_receipts=(receipt,), proof_bindings=(changed,))
    assert "verification profile" in str(caught.value.__cause__).lower()
    assert record.to_dict() == original


@pytest.mark.parametrize("profile", [None, "lean-kernel-verification/older", False, 1, "lean-kernel-verification/v1"])
def test_current_cache_reuse_refuses_missing_or_mutated_expected_verification_profile(profile: Any) -> None:
    record, _, receipt, _, context = _bound_record()
    original = record.to_dict()
    assert record.theorem_receipt_results(expected_context=context) == (receipt,)
    changed = deepcopy(context)
    if profile is None:
        changed["toolchain"]["metadata"].pop("verification_profile")
    else:
        changed["toolchain"]["metadata"]["verification_profile"] = profile
    with pytest.raises(LegalProofIntegrityError, match="expected reuse context"):
        record.theorem_receipt_results(expected_context=changed)
    assert record.to_dict() == original


@pytest.mark.parametrize("profile", [None, "lean-kernel-verification/older", False, 1,
                                    ["lean-kernel-verification/v1"], {"profile": "lean-kernel-verification/v1"}, "lean-kernel-verification/v1"])
def test_current_cache_refuses_an_unsupported_loaded_lean_verifier_profile_before_parser(monkeypatch, profile: Any) -> None:
    """An old cached v3 Python module is not upgraded by its wire version."""
    from ipfs_datasets_py.logic.backends.kernel import lean
    artifact, receipt, binding, _ = _bound_fixture()
    calls = []
    class OlderParser:
        @staticmethod
        def from_dict(value):
            calls.append(value)
            raise AssertionError("unsupported loaded verifier must not parse a proof")
    if profile is None:
        monkeypatch.delattr(lean, "LEAN_KERNEL_VERIFICATION_PROFILE")
    else:
        monkeypatch.setattr(lean, "LEAN_KERNEL_VERIFICATION_PROFILE", deepcopy(profile))
    monkeypatch.setattr(lean, "LeanKernelReceipt", OlderParser)
    with pytest.raises(LegalProofIntegrityError, match="canonical checked Lean v3 receipt"):
        LegalProofRecord.build(artifact, profile="fictional-older-loaded-verifier", jurisdiction="fictional",
            theorem_receipts=(receipt,), proof_bindings=(binding,))
    assert calls == []


# Exact outer protocol coherence over an explicitly fictional kernel receipt.
# These controls execute no Lean process and attest no native proof or statute.
def _reissued_backend_version_cache_fixture(advertised_version: str):
    artifact, _, original_binding, original_context = _bound_fixture()
    original_snapshot = deepcopy(original_binding)
    context = deepcopy(original_context)
    context["backend_version"] = advertised_version
    previous_claim = IRClaim.from_dict(original_binding["claim"])
    claim = replace(previous_claim, metadata={**previous_claim.metadata.to_dict(),
        "proof_context_digest": stable_digest(context)})
    previous_request = BackendRequest.from_dict(original_binding["request"])
    payload = previous_request.payload.to_dict()
    payload["legal_proof_context"] = deepcopy(context)
    request = BackendRequest.for_claim(claim, previous_request.obligation_id,
        request_id="request:fictional-reissued-backend-version", requested_backend_id="lean",
        bounds=previous_request.bounds, payload=payload)
    # Rebuild the inner request/source binding using the existing fictional
    # factory, preserving its actual native/toolchain version unchanged.
    kernel = _fictional_kernel_receipt(request)
    original_kernel = ProofResult.from_dict(original_binding["result"]).to_dict()["payload"]["kernel_receipt"]
    assert kernel.accepted is True
    assert kernel.native_identity.observation_kind == "trusted_fictional_identity_fixture"
    assert kernel.native_identity.to_dict() == original_kernel["native_identity"]
    assert kernel.toolchain.to_dict() == context["toolchain"]
    assert kernel.native_identity.actual_version == kernel.toolchain.version == "fictional"
    assert kernel.request_digest == request.digest
    previous_attempt = BackendAttempt.from_dict(original_binding["attempt"])
    attempt = replace(previous_attempt, attempt_id="attempt:fictional-reissued-backend-version",
        request_digest=request.digest, backend_version=advertised_version,
        output_digest=stable_digest({"authored_kernel_fixture": kernel.to_dict()}))
    previous_result = ProofResult.from_dict(original_binding["result"])
    result = ProofResult.for_attempt(request, attempt,
        result_id="result:fictional-reissued-backend-version",
        authority=replace(previous_result.authority, scope_digest=request.digest,
            configuration_digest=stable_digest(context)), status=ResultStatus.PROVED,
        payload={"kernel_receipt": kernel.to_dict(), "fixture_only": True})
    receipt = ProofReceipt.issue(claim, request, attempt, result,
        receipt_id="receipt:fictional-reissued-backend-version", verifier="fictional-test")
    assert receipt.backend_version == result.backend_version == attempt.backend_version == context["backend_version"]
    assert claim.metadata["proof_context_digest"] == stable_digest(context)
    assert request.payload.to_dict()["legal_proof_context"] == context
    assert receipt.request_digest == kernel.request_digest == request.digest
    assert original_binding == original_snapshot and original_context["backend_version"] == "fictional"
    return artifact, receipt, claim, request, attempt, result, context, kernel


def test_bound_cache_reissued_coherent_native_backend_version_preserves_reuse():
    """Binding-consistency fixture only; this is not a native Lean result."""
    artifact, receipt, claim, request, attempt, result, context, kernel = (
        _reissued_backend_version_cache_fixture("fictional"))
    assert receipt.backend_version == kernel.native_identity.actual_version == kernel.toolchain.version
    binding = build_legal_proof_binding(artifact, receipt, claim=claim, request=request,
        attempt=attempt, result=result, context=context)
    record = LegalProofRecord.build(artifact, profile="fictional-coherent-native-version",
        jurisdiction="fictional", theorem_receipts=(receipt,), proof_bindings=(binding,))
    assert record.verify_integrity() is record
    assert record.theorem_receipt_results(expected_context=context) == (receipt,)


@pytest.mark.parametrize("advertised_version", [
    "fictional-advertised-other", "lean4",
])
def test_bound_cache_rejects_reissued_outer_version_differing_from_native_toolchain(advertised_version):
    """Reissue every outer link; the native version remains the same fixture."""
    artifact, receipt, claim, request, attempt, result, context, kernel = (
        _reissued_backend_version_cache_fixture(advertised_version))
    assert receipt.backend_version != kernel.native_identity.actual_version
    assert kernel.native_identity.actual_version == kernel.toolchain.version == "fictional"
    # ProofReceipt.issue above used the actual canonical factories and checked
    # all outer digests. Only the cross-owner backend/native version is wrong.
    with pytest.raises(LegalProofIntegrityError, match="backend version"):
        build_legal_proof_binding(artifact, receipt, claim=claim, request=request,
            attempt=attempt, result=result, context=context)


def _second_obligation_binding(artifact, first_binding, variant):
    from ipfs_datasets_py.logic.backends.kernel.wasm import KernelToolchainBinding

    context = deepcopy(first_binding["context"])
    context["expected_declaration"] = "second_cache_fixture"
    if variant == "interpretation":
        context["interpretation_digest"] = stable_digest({"fictional_interpretation": 2})
    if variant == "dependency":
        context["dependency_versions"]["fictional-definition"] = stable_digest({"definition": 2})
    if variant in {"toolchain", "numeric-toolchain-alias"}:
        context["toolchain"]["metadata"]["native_resource_profile"]["cpu_slots"] = (
            True if variant == "numeric-toolchain-alias" else 2
        )
    obligation = artifact.proof_obligations[1]
    old_claim = IRClaim.from_dict(first_binding["claim"])
    claim = replace(old_claim, claim_id="claim:second-fictional-cache",
                    statement=obligation.statement, obligations=(obligation,),
                    metadata={**old_claim.metadata.to_dict(),
                              "proof_context_digest": stable_digest(context)})
    old_request = BackendRequest.from_dict(first_binding["request"])
    request = BackendRequest.for_claim(
        claim, obligation.obligation_id, request_id="request:second-fictional-cache",
        requested_backend_id="lean", bounds=old_request.bounds,
        payload={"lean": "theorem second_cache_fixture : True := by trivial\n",
                 "expected_declaration": context["expected_declaration"],
                 "expected_proposition": context["expected_proposition"],
                 "legal_proof_context": context},
    )
    kernel = _fictional_kernel_receipt(
        request, toolchain=KernelToolchainBinding(**context["toolchain"]),
    )
    old_attempt = BackendAttempt.from_dict(first_binding["attempt"])
    attempt = replace(old_attempt, attempt_id="attempt:second-fictional-cache",
                      request_digest=request.digest,
                      output_digest=stable_digest({"authored_kernel_fixture": kernel.to_dict()}))
    old_result = ProofResult.from_dict(first_binding["result"])
    result = ProofResult.for_attempt(
        request, attempt, result_id="result:second-fictional-cache", status=ResultStatus.PROVED,
        authority=replace(old_result.authority, scope_digest=request.digest,
                          configuration_digest=stable_digest(context)),
        payload={"kernel_receipt": kernel.to_dict(), "fixture_only": True},
    )
    receipt = ProofReceipt.issue(claim, request, attempt, result,
                                 receipt_id="receipt:second-fictional-cache", verifier="fictional-test")
    binding = build_legal_proof_binding(artifact, receipt, claim=claim, request=request,
                                       attempt=attempt, result=result, context=context)
    return receipt, binding, context


@pytest.mark.parametrize("variant", [
    "same", "interpretation", "dependency", "toolchain", "numeric-toolchain-alias",
])
@pytest.mark.parametrize("projection", ["shadow", "migration"])
def test_artifact_coverage_requires_one_proof_context(variant, projection):
    """Fictional receipt chains only, with no prover or database execution."""
    artifact, first, first_binding, context = _bound_fixture(
        extra_obligation=True, native_resource_profile={"cpu_slots": 1},
    )
    second, second_binding, second_context = _second_obligation_binding(artifact, first_binding, variant)
    record = LegalProofRecord.build(
        artifact, profile="fictional-two-proof-contexts", jurisdiction="fictional",
        theorem_receipts=(first, second), proof_bindings=(second_binding, first_binding),
    )
    assert first.obligation_id != second.obligation_id
    assert context["expected_declaration"] != second_context["expected_declaration"]
    assert record.theorem_receipt_results(expected_context=context, obligation_id=first.obligation_id) == (first,)
    assert record.theorem_receipt_results(expected_context=second_context, obligation_id=second.obligation_id) == (second,)
    before = record.to_dict()
    complete = variant == "same"
    if projection == "shadow":
        spy = _ShadowObservation()
        cache = LegalProofCache()
        cache.bind_shadow_repository(spy)
        assert cache.put(record) is record
        assert len(spy.writes) == 1
        row = spy.writes[0]
        assert row["status"] == ("proved" if complete else "unknown")
        assert row["kernel_accepted"] is complete
        assert row["trust_level"] == ("independently_checkable" if complete else "none")
        assert row["legacy_payload"] == before
    else:
        from ipfs_datasets_py.logic.common.duckdb_proof_migration import (
            ProofCacheFamily, RawLegacyRecord, normalize_legacy_record,
        )
        entry = normalize_legacy_record(
            RawLegacyRecord(record_index=1, line_number=1, payload=before),
            family=ProofCacheFamily.LEGAL_IR,
        )
        assert entry.status.value == ("proved" if complete else "candidate")
        assert entry.trust_level.value == ("independently_checkable" if complete else "none")
        assert entry.result_payload["theorem_receipts"] == before["theorem_receipts"]
        assert entry.result_payload["proof_bindings"] == before["proof_bindings"]
    assert record.to_dict() == before


@pytest.mark.parametrize("legacy_version", ["legacy", "bound-v2"])
def test_old_aggregate_cache_authority_is_unusable_but_retained(legacy_version):
    from ipfs_datasets_py.logic.common.duckdb_proof_migration import (
        ProofCacheFamily, RawLegacyRecord, normalize_legacy_record,
    )
    from ipfs_datasets_py.logic.common.duckdb_proof_store import (
        DuckDBProofStore, DuckDBProofStoreAuthorityError,
    )

    record, _, _, _, _ = _bound_record()
    projection = normalize_legacy_record(
        RawLegacyRecord(record_index=1, line_number=1, payload=record.to_dict()),
        family=ProofCacheFamily.LEGAL_IR,
    )
    current = projection.to_unified_entry(created_at=1.0)
    store = DuckDBProofStore()
    assert store.put(current, now=1.0).usable is True
    assert store.get(current.key, now=2.0) == current
    legacy_payload = current.result_payload.to_dict()
    legacy_payload.pop("complete_proof_contexts", None)
    old = replace(current, key=replace(current.key, backend_version=legacy_version),
                  result_payload=legacy_payload, entry_digest="")
    # Seed the exact historical row without going through new write admission.
    archive = DuckDBProofStore()
    archive._entries[old.key.digest] = old
    result = archive.lookup(old.key, now=2.0)
    assert result.usable is False
    assert result.entry is None
    assert result.reason.value == "authority_mismatch"
    assert archive.get(old.key, now=2.0) is None
    assert archive._entries[old.key.digest].to_dict() == old.to_dict()
    with pytest.raises(DuckDBProofStoreAuthorityError):
        archive.put(old, now=2.0)
    partial, _, _, _, _ = _bound_record(extra_obligation=True)
    advisory = normalize_legacy_record(
        RawLegacyRecord(record_index=2, line_number=2, payload=partial.to_dict()),
        family=ProofCacheFamily.LEGAL_IR,
    ).to_unified_entry(created_at=2.0)
    advisory = replace(advisory, key=old.key, entry_digest="")
    computed = []

    def compute_advisory():
        computed.append(True)
        return advisory

    retry = archive.get_or_compute(old.key, compute_advisory, now=2.0)
    assert computed == [], "obsolete proof lookup invoked an advisory producer"
    assert retry.usable is False and retry.reason.value == "authority_mismatch"
    assert archive._entries[old.key.digest].to_dict() == old.to_dict()


def test_genuine_sql_legal_shadow_requires_coherent_context_and_preserves_prior_rows(tmp_path: Path) -> None:
    """Real SQL/adapter paths with fictional receipt chains; no Native claim."""
    import duckdb

    from ipfs_datasets_py.logic.backends.cache_protocol import CacheLookupReason
    from ipfs_datasets_py.logic.backends.results import (
        ResultAuthority as StoredAuthority,
        ResultStatus as StoredStatus,
    )
    from ipfs_datasets_py.logic.common.duckdb_proof_migration import (
        ProofCacheFamily, RawLegacyRecord, normalize_legacy_record,
    )
    from ipfs_datasets_py.logic.common.duckdb_proof_store import (
        DuckDBProofStore, LEGAL_FORMAL_COVERAGE_VERSION,
        ProofOutcomeKind, ProofTrustLevel, UnifiedProofEntry,
    )
    from ipfs_datasets_py.logic.common.proof_cache import UnifiedProofShadowRepository
    from ipfs_datasets_py.logic.families.models import EvidenceAuthority

    path = tmp_path / "live-coherent-proof-coverage.duckdb"
    config = {
        "threads": 1,
        "memory_limit": "128MB",
        "enable_external_access": False,
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
    }
    artifact, first, first_binding, first_context = _bound_fixture(
        extra_obligation=True, native_resource_profile={"cpu_slots": 1},
    )

    def bound_record(variant):
        second, binding, context = _second_obligation_binding(artifact, first_binding, variant)
        record = LegalProofRecord.build(
            artifact, profile="fictional-genuine-sql-contexts", jurisdiction="fictional",
            theorem_receipts=(first, second), proof_bindings=(binding, first_binding),
        )
        # Both receipts remain valid for their own exact requests. The adverse
        # cases change shared context, not the integrity of either receipt.
        assert record.theorem_receipt_results(
            expected_context=first_context, obligation_id=first.obligation_id,
        ) == (first,)
        assert record.theorem_receipt_results(
            expected_context=context, obligation_id=second.obligation_id,
        ) == (second,)
        return record

    def selected_rows(connection, digest):
        queries = (
            "SELECT * FROM proof_keys WHERE key_digest=?",
            "SELECT * FROM proof_key_dimensions WHERE key_digest=? ORDER BY dimension_name",
            "SELECT * FROM premises WHERE key_digest=? ORDER BY premise_ordinal",
            "SELECT * FROM proof_entries WHERE key_digest=?",
            "SELECT * FROM proof_evidence WHERE entry_digest IN "
            "(SELECT entry_digest FROM proof_entries WHERE key_digest=?) ORDER BY evidence_id",
        )
        # Access statistics may change; normalized proof evidence must not.
        return tuple(connection.execute(query, [digest]).fetchall() for query in queries)

    def stored_shadow(connection, record):
        # _shadow_write intentionally catches errors. Reading actual SQL is
        # required here; a LegalProofCache memory hit cannot satisfy the test.
        rows = connection.execute(
            "SELECT payload_json FROM proof_entries WHERE result_id=?", [record.content_cid],
        ).fetchall()
        assert len(rows) == 1, "live shadow did not persist exactly one physical SQL row"
        return UnifiedProofEntry.from_dict(json.loads(rows[0][0])).verify_integrity()

    def migrated(record, index):
        return normalize_legacy_record(
            RawLegacyRecord(record_index=index, line_number=index, payload=record.to_dict()),
            family=ProofCacheFamily.LEGAL_IR,
        ).to_unified_entry(created_at=100.0)

    def assert_advisory(entry):
        assert entry.key.backend_version == LEGAL_FORMAL_COVERAGE_VERSION
        assert entry.status in (StoredStatus.UNKNOWN, StoredStatus.CANDIDATE)
        assert entry.outcome is not ProofOutcomeKind.PROOF
        assert entry.result_authority is StoredAuthority.CANDIDATE
        assert entry.trust_level is ProofTrustLevel.NONE
        assert entry.evidence_authority is EvidenceAuthority.NONE
        assert not entry.result_payload["complete_proof_contexts"]
        for name in ("source_admission", "legal_admission", "corpus_admission"):
            assert entry.result_payload[name] is False

    coherent = bound_record("same")
    coherent_wire = coherent.to_dict()
    retained = []
    advisory_entries = []
    coherent_rows = {}
    with duckdb.connect(str(path), config=config) as connection:
        store = DuckDBProofStore(connection=connection, max_entries=32)
        shadow = UnifiedProofShadowRepository(store=store, clock=lambda: 100.0)
        assert shadow.store is store
        cache = LegalProofCache()
        cache.bind_shadow_repository(shadow)
        assert cache.put(coherent) is coherent
        live_positive = stored_shadow(connection, coherent)
        positive_migration = migrated(coherent, 1)
        assert positive_migration.key.digest != live_positive.key.digest
        assert store.put(positive_migration, now=100.0).reason is CacheLookupReason.STORED
        for positive in (live_positive, positive_migration):
            assert positive.key.backend_version == LEGAL_FORMAL_COVERAGE_VERSION
            assert positive.status is StoredStatus.PROVED
            assert positive.trust_level is ProofTrustLevel.INDEPENDENTLY_CHECKABLE
            assert len(positive.result_payload["complete_proof_contexts"]) == 1
            for name in ("source_admission", "legal_admission", "corpus_admission"):
                assert positive.result_payload[name] is False
            assert store.get(positive.key, require_result_authority=StoredAuthority.THEOREM,
                             now=101.0).to_dict() == positive.to_dict()
            coherent_rows[positive.key.digest] = selected_rows(connection, positive.key.digest)
            assert len(coherent_rows[positive.key.digest][0]) == 1
            assert len(coherent_rows[positive.key.digest][3]) == 1
            retained.append(positive)

        for index, variant in enumerate(
            ("interpretation", "dependency", "toolchain", "numeric-toolchain-alias"), start=2,
        ):
            mixed = bound_record(variant)
            before = mixed.to_dict()
            assert cache.put(mixed) is mixed
            live_advisory = stored_shadow(connection, mixed)
            assert live_advisory.status is StoredStatus.UNKNOWN
            migration_advisory = migrated(mixed, index)
            assert migration_advisory.status is StoredStatus.CANDIDATE
            assert migration_advisory.key.digest != live_advisory.key.digest
            assert store.put(migration_advisory, now=100.0).reason is CacheLookupReason.STORED
            for entry in (live_advisory, migration_advisory):
                assert_advisory(entry)
                assert entry.key.digest not in coherent_rows
                # Ordinary advisory reuse is valid; it confers no theorem authority.
                assert store.get(entry.key, now=101.0).to_dict() == entry.to_dict()
                advisory_entries.append(entry)
                retained.append(entry)
            assert mixed.to_dict() == before
            for digest, rows in coherent_rows.items():
                assert selected_rows(connection, digest) == rows
        assert coherent.to_dict() == coherent_wire
        assert connection.execute("SELECT count(*) FROM proof_entries").fetchone()[0] == 10

    # A genuinely closed/reopened file prevents warm _entries from hiding a
    # different persisted projection, or a failed live shadow write.
    with duckdb.connect(str(path), config=config) as connection:
        cold = DuckDBProofStore(connection=connection, max_entries=32)
        for positive in retained[:2]:
            calls = []

            def must_not_compute():
                calls.append(positive.key.digest)
                raise AssertionError("coherent cached theorem was recomputed")

            for key in (positive.key, positive.key.to_verification_cache_key()):
                hit = cold.get_or_compute(key, must_not_compute,
                    require_result_authority=StoredAuthority.THEOREM, now=101.0)
                assert hit.hit and hit.usable
                assert hit.entry.to_dict() == positive.to_verification_cache_entry().to_dict()
            assert calls == []

        for advisory in advisory_entries:
            for key in (advisory.key, advisory.key.to_verification_cache_key()):
                refused = cold.lookup(key, require_result_authority=StoredAuthority.THEOREM, now=101.0)
                assert refused.hit and not refused.usable
                assert refused.reason is CacheLookupReason.AUTHORITY_MISMATCH
                assert cold.get(key, require_result_authority=StoredAuthority.THEOREM, now=101.0) is None
                retry_calls = []

                def retain_advisory():
                    retry_calls.append(advisory.key.digest)
                    return advisory

                retry = cold.get_or_compute(key, retain_advisory,
                    require_result_authority=StoredAuthority.THEOREM, now=101.0)
                assert retry_calls == [advisory.key.digest]
                # The current retry API returns a storage acknowledgement after
                # computing; its usable flag is not a theorem-proof assertion.
                assert retry.entry is not None
                assert retry.entry.to_dict() == advisory.to_verification_cache_entry().to_dict()
                assert cold.get(key, require_result_authority=StoredAuthority.THEOREM, now=101.0) is None
                persisted = cold.get(key, now=101.0)
                assert_advisory(persisted)
                assert persisted.to_dict() == advisory.to_dict()
                for digest, rows in coherent_rows.items():
                    assert selected_rows(connection, digest) == rows

    with duckdb.connect(str(path), config=config) as connection:
        final_store = DuckDBProofStore(connection=connection, max_entries=32)
        for entry in retained:
            assert final_store.get(entry.key, now=101.0).to_dict() == entry.to_dict()
        for digest, rows in coherent_rows.items():
            assert selected_rows(connection, digest) == rows


@pytest.mark.parametrize("store_name", ["exact", "unified"])
@pytest.mark.parametrize("extra_obligation", [True, False], ids=["advisory-refused", "theorem-usable"])
def test_cache_compute_leader_respects_requested_theorem_authority(store_name, extra_obligation):
    from ipfs_datasets_py.logic.backends.cache_protocol import CacheLookupReason, ExactVerificationCache
    from ipfs_datasets_py.logic.backends.results import ResultAuthority
    from ipfs_datasets_py.logic.common.duckdb_proof_migration import (
        ProofCacheFamily, RawLegacyRecord, normalize_legacy_record,
    )
    from ipfs_datasets_py.logic.common.duckdb_proof_store import DuckDBProofStore

    record, *_ = _bound_record(extra_obligation=extra_obligation)
    unified = normalize_legacy_record(
        RawLegacyRecord(record_index=1, line_number=1, payload=record.to_dict()),
        family=ProofCacheFamily.LEGAL_IR,
    ).to_unified_entry(created_at=100.0)
    if store_name == "exact":
        store = ExactVerificationCache()
        entry = unified.to_verification_cache_entry()
    else:
        store = DuckDBProofStore()
        entry = unified

    required = ResultAuthority.THEOREM
    assert entry.result_authority is (
        ResultAuthority.CANDIDATE if extra_obligation else required
    )
    calls = []

    def produce():
        calls.append(entry.key.digest)
        return entry

    if extra_obligation:
        assert store.put(entry, now=100.0).reason is CacheLookupReason.STORED
        observed = store.lookup(entry.key, require_result_authority=required, now=101.0)
        assert observed.hit and not observed.usable
        assert observed.reason is CacheLookupReason.AUTHORITY_MISMATCH
        assert observed.entry is not None

    result = store.get_or_compute(
        entry.key, produce, require_result_authority=required, now=101.0,
    )
    assert calls == [entry.key.digest]
    assert store.get(entry.key, now=102.0).to_dict() == entry.to_dict()
    if extra_obligation:
        assert store.get(entry.key, require_result_authority=required, now=102.0) is None
        assert not result.usable
        assert result.reason is CacheLookupReason.AUTHORITY_MISMATCH
    else:
        assert store.get(entry.key, require_result_authority=required, now=102.0).to_dict() == entry.to_dict()
        assert result.usable and result.reason is CacheLookupReason.STORED


@pytest.mark.parametrize("extra_obligation", [True, False], ids=["advisory-refused", "theorem-usable"])
def test_unified_cache_waiter_respects_requested_theorem_authority(monkeypatch, extra_obligation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from ipfs_datasets_py.logic.backends.cache_protocol import CacheLookupReason
    from ipfs_datasets_py.logic.backends.results import ResultAuthority
    from ipfs_datasets_py.logic.common.duckdb_proof_migration import (
        ProofCacheFamily, RawLegacyRecord, normalize_legacy_record,
    )
    from ipfs_datasets_py.logic.common.duckdb_proof_store import DuckDBProofStore

    record, *_ = _bound_record(extra_obligation=extra_obligation)
    entry = normalize_legacy_record(
        RawLegacyRecord(record_index=1, line_number=1, payload=record.to_dict()),
        family=ProofCacheFamily.LEGAL_IR,
    ).to_unified_entry(created_at=100.0)
    required = ResultAuthority.THEOREM
    assert entry.result_authority is (ResultAuthority.CANDIDATE if extra_obligation else required)
    store = DuckDBProofStore()
    entered = Event()
    release = Event()
    flights_waited = []

    def produce():
        entered.set()
        assert release.wait(timeout=5), "waiter never reached the producer's flight"
        return entry

    def must_share():
        pytest.fail("a waiter independently invoked its producer")

    with ThreadPoolExecutor(max_workers=1) as executor:
        producing = executor.submit(store.get_or_compute, entry.key, produce, now=101.0)
        try:
            assert entered.wait(timeout=5), "producer never entered its flight"
            with store._lock:
                event = store._flights[entry.key.digest].event
            wait = event.wait

            def wait_then_release():
                flights_waited.append(entry.key.digest)
                release.set()
                assert wait(timeout=5), "producer did not release the flight"

            monkeypatch.setattr(event, "wait", wait_then_release)
            result = store.get_or_compute(
                entry.key, must_share, require_result_authority=required, now=101.0,
            )
        finally:
            release.set()
        leader = producing.result(timeout=5)

    assert leader.usable and leader.reason is CacheLookupReason.STORED
    assert flights_waited == [entry.key.digest]
    assert result.single_flight_shared
    assert result.entry.to_dict() == entry.to_verification_cache_entry().to_dict()
    assert store.get(entry.key, now=101.0).to_dict() == entry.to_dict()
    if extra_obligation:
        assert not result.usable
        assert result.reason is CacheLookupReason.AUTHORITY_MISMATCH
    else:
        assert result.usable
        assert result.reason is CacheLookupReason.SINGLE_FLIGHT_SHARED


def _cache_ceiling_fixture(store_name, ceiling_name):
    from ipfs_datasets_py.logic.backends.cache_protocol import CacheLookupReason, ExactVerificationCache
    from ipfs_datasets_py.logic.common.duckdb_proof_migration import (
        ProofCacheFamily, RawLegacyRecord, normalize_legacy_record,
    )
    from ipfs_datasets_py.logic.common.duckdb_proof_store import DuckDBProofStore
    from ipfs_datasets_py.logic.families.models import EvidenceAuthority

    record, *_ = _bound_record()
    unified = normalize_legacy_record(
        RawLegacyRecord(record_index=1, line_number=1, payload=record.to_dict()),
        family=ProofCacheFamily.LEGAL_IR,
    ).to_unified_entry(created_at=100.0)
    entry = unified.to_verification_cache_entry() if store_name == "exact" else unified
    store_type = ExactVerificationCache if store_name == "exact" else DuckDBProofStore
    assert entry.evidence_authority is EvidenceAuthority.INDEPENDENTLY_CHECKABLE
    return store_type(), entry, CacheLookupReason, {ceiling_name: "advisory"}


@pytest.mark.parametrize("store_name,ceiling_name", [
    pytest.param("exact", "max_evidence_authority", id="exact-evidence"),
    pytest.param("unified", "max_evidence_authority", id="unified-evidence"),
    pytest.param("unified", "max_trust_level", id="unified-trust"),
])
def test_diagnostic_cache_producer_retains_caller_ceiling(store_name, ceiling_name):
    store, entry, reasons, filters = _cache_ceiling_fixture(store_name, ceiling_name)
    calls = []

    def produce():
        calls.append(entry.key.digest)
        return entry

    computed = store.get_or_compute(entry.key, produce, now=101.0, **filters)
    later = store.lookup(entry.key, now=101.0, **filters)
    assert calls == [entry.key.digest]
    assert later.reason is reasons.INSUFFICIENT_AUTHORITY and not later.usable
    assert store.get(entry.key, now=101.0).to_dict() == entry.to_dict()
    assert computed.usable == later.usable
    assert computed.reason is later.reason


@pytest.mark.parametrize("store_name,ceiling_name", [
    pytest.param("exact", "max_evidence_authority", id="exact-evidence"),
    pytest.param("unified", "max_evidence_authority", id="unified-evidence"),
    pytest.param("unified", "max_trust_level", id="unified-trust"),
])
def test_diagnostic_cache_waiter_retains_caller_ceiling(monkeypatch, store_name, ceiling_name):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    store, entry, reasons, filters = _cache_ceiling_fixture(store_name, ceiling_name)
    started, release = Event(), Event()
    waits = []

    def produce():
        started.set()
        assert release.wait(timeout=5)
        return entry

    def unexpected():
        pytest.fail("the waiting caller became a second producer")

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(store.get_or_compute, entry.key, produce, now=101.0)
        try:
            assert started.wait(timeout=5)
            with store._lock:
                event = store._flights[entry.key.digest].event
            wait = event.wait

            def observed_wait():
                waits.append(entry.key.digest)
                release.set()
                assert wait(timeout=5)

            monkeypatch.setattr(event, "wait", observed_wait)
            computed = store.get_or_compute(entry.key, unexpected, now=101.0, **filters)
        finally:
            release.set()
        assert first.result(timeout=5).usable
    assert waits == [entry.key.digest]
    assert computed.single_flight_shared
    later = store.lookup(entry.key, now=101.0, **filters)
    assert later.reason is reasons.INSUFFICIENT_AUTHORITY and not later.usable
    assert computed.usable == later.usable
    assert computed.reason is later.reason


# Deterministic test-only interleaving: lookup result is real and returned unchanged.
_GET_SNAPSHOT_TRACE = []

@pytest.mark.parametrize("change", ["none", "equivalent-put", "invalidate", "result-authority", "trust-ceiling"])
def test_unified_get_eligibility_snapshot_after_actual_lookup(change, monkeypatch):
    from ipfs_datasets_py.logic.common.duckdb_proof_store import trust_rank
    store, original, reasons, _ = _cache_ceiling_fixture("unified", "max_trust_level")
    assert store._connection is None
    initial = original
    policy = {"require_result_authority": original.result_authority}
    replacement = None
    if change == "trust-ceiling":
        initial = replace(original, trust_level=type(original.trust_level).ADVISORY, entry_digest="")
        policy = {"max_trust_level": type(initial.trust_level).ADVISORY}
        replacement = original
    elif change == "result-authority":
        different = next(value for value in type(original.result_authority) if value is not original.result_authority)
        replacement = replace(original, result_authority=different, entry_digest="")
    elif change == "equivalent-put":
        replacement = original
    store.put(initial, now=100.0)
    actual_lookup = store.lookup
    before = actual_lookup(initial.key, **policy, now=100.0)
    assert before.usable is True and before.entry is not None
    calls = []
    def after_actual_lookup(*args, **kwargs):
        observed = actual_lookup(*args, **kwargs)
        assert observed.usable is True and observed.entry is not None
        assert args[0].digest == initial.key.digest
        assert kwargs == {"require_result_authority": None, "max_evidence_authority": None, "max_trust_level": None, **policy, "now": 100.0}
        calls.append(observed)
        # A synchronous scheduling hook models a different caller mutating
        # after the real lookup lock was released, before get reacquires it.
        if replacement is not None:
            stored = store.put(replacement, now=100.0)
            assert stored.usable is True
        elif change == "invalidate":
            assert store.invalidate(initial.key) is True
        return observed  # Never fabricate or change an approved lookup.
    monkeypatch.setattr(store, "lookup", after_actual_lookup)
    returned = store.get(initial.key, **policy, now=100.0)
    assert len(calls) == 1 and calls[0].usable is True
    after = actual_lookup(initial.key, **policy, now=100.0)
    row = {
        "change": change,
        "policy": {k: v.value for k, v in policy.items()},
        "initial_result_authority": initial.result_authority.value,
        "initial_trust": initial.trust_level.value,
        "real_lookup_usable": calls[0].usable,
        "post_lookup_usable": after.usable,
        "post_lookup_reason": after.reason.value,
        "returned_none": returned is None,
        "returned_result_authority": None if returned is None else returned.result_authority.value,
        "returned_trust": None if returned is None else returned.trust_level.value,
        "returned_key_digest": None if returned is None else returned.key.digest,
        "requested_key_digest": initial.key.digest,
    }
    _GET_SNAPSHOT_TRACE.append(row)
    if change == "result-authority":
        assert after.usable is False and after.reason is reasons.AUTHORITY_MISMATCH
    elif change == "trust-ceiling":
        assert after.usable is False and after.reason is reasons.INSUFFICIENT_AUTHORITY
    elif change == "invalidate":
        assert after.usable is False and after.reason is reasons.MISS
    else:
        assert returned is not None and after.usable is True
    if returned is not None:
        returned.verify_integrity()
        assert returned.key.digest == initial.key.digest
        if "require_result_authority" in policy:
            assert returned.result_authority is policy["require_result_authority"], row
        if "max_trust_level" in policy:
            assert trust_rank(returned.trust_level) <= trust_rank(policy["max_trust_level"]), row
