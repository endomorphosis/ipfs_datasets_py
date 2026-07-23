"""Tests for persisting replayable hammer receipts through IPFS-aware
storage (HAMMER-012).

These tests cover:

- :class:`HammerReceipt` construction, cross-record coherence validation
  (out-of-band evidence must reference the same ``request_id``/
  ``attempt_id``/``candidate_id``/``reconstruction_id`` as the bundled
  :class:`~ipfs_datasets_py.logic.hammers.models.HammerResult`), and
  ``to_dict``/``from_dict`` round-trips.
- Deterministic, content-addressed ``receipt_id`` computation
  (:func:`~ipfs_datasets_py.logic.hammers.receipts.compute_receipt_digest`):
  identical content always produces the same id, and any change to the
  bundled trust-contract content changes it.
- :func:`build_publishable_view`/:meth:`HammerReceipt.to_publishable_dict`:
  redaction of the private goal statement, translated formula text,
  candidate certificate, reconstruction checked source/kernel output,
  solver raw output, normalized proof-step formula text, and decomposition
  subgoal statements — while leaving public corpus premise statements and
  structural metadata untouched — plus defense-in-depth credential
  scrubbing (:func:`scrub_credential_text`) applied everywhere, including
  caller metadata and diagnostic notes.
- :class:`ReceiptStore`'s local-disk fallback (the default, zero-dependency
  behavior), an injected fake IPFS backend (CID-addressed storage plus
  index-based recovery after the local cache file is deleted), and
  ``ReceiptNotFoundError``/``exists``/``list_ids`` behavior.
- :func:`persist_hammer_receipt`'s convenience wrapper.
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.hammers.fallbacks import (
    DecompositionPlan,
    DecompositionSource,
    FallbackTrigger,
    ReviewStatus,
    SubgoalStatus,
    redact_llm_text,
)
from ipfs_datasets_py.logic.hammers.fallbacks import DecompositionSubgoal
from ipfs_datasets_py.logic.hammers.corpus import compute_content_digest
from ipfs_datasets_py.logic.hammers.models import (
    EnvironmentLockRecord,
    HammerPolicy,
    HammerRequest,
    HammerResult,
    HammerResultStatus,
    ITPKind,
    PremiseRecord,
    ProofCandidateRecord,
    ReconstructionRecord,
    SolverAttemptRecord,
    SolverVerdict,
    TranslationRecord,
    TranslationStatus,
    TranslationTarget,
)
from ipfs_datasets_py.logic.hammers.portfolio import SolverAttemptEvidence
from ipfs_datasets_py.logic.hammers.provenance import (
    EvidenceKind,
    NormalizedEvidence,
    ProofStep,
)
from ipfs_datasets_py.logic.hammers.reconstruction import ReconstructionEvidence
from ipfs_datasets_py.logic.hammers import receipts as rc

FAKE_API_KEY = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
FAKE_GOAL = "private_lemma_42 : forall n, n = n"
FAKE_TRANSLATED = "fof(private_lemma_42, conjecture, ! [N] : N = N)."
FAKE_CHECKED_SOURCE = (
    "theorem private_lemma_42 (n : Nat) : n = n := by\n  rfl -- private full proof source"
)
FAKE_CERTIFICATE = "fof(private_lemma_42, plain, ! [N] : N = N, inference(rfl,[],[])) ."


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def make_request(**overrides) -> HammerRequest:
    defaults = dict(
        request_id="req-1",
        itp=ITPKind.LEAN,
        theorem_id="private_lemma_42",
        goal_statement=FAKE_GOAL,
        corpus_revision="corpus-rev-1",
        policy=HammerPolicy(timeout_seconds=20.0, allowed_solvers=["z3"]),
        metadata={"caller": "unit-test", "api_key": FAKE_API_KEY},
    )
    defaults.update(overrides)
    return HammerRequest(**defaults)


def make_verified_result(**overrides) -> HammerResult:
    request = overrides.pop("request", None) or make_request()
    premise = PremiseRecord(
        premise_id="p1",
        statement="public_corpus_lemma : forall n, n = n",
        source_itp=ITPKind.LEAN,
        corpus_revision="corpus-rev-1",
        rank=0,
        score=1.0,
        selection_method="deterministic-baseline",
    )
    translation = TranslationRecord(
        translation_id="t1",
        request_id=request.request_id,
        target=TranslationTarget.TPTP,
        status=TranslationStatus.SUPPORTED,
        source_construct="goal",
        translated_text=FAKE_TRANSLATED,
    )
    attempt = SolverAttemptRecord(
        attempt_id="a1",
        request_id=request.request_id,
        translation_id="t1",
        solver_name="z3",
        target=TranslationTarget.TPTP,
        timeout_seconds=20.0,
        verdict=SolverVerdict.PROVED,
        exit_code=0,
        wall_time_seconds=0.01,
    )
    candidate = ProofCandidateRecord(
        candidate_id="c1",
        request_id=request.request_id,
        solver_attempt_id="a1",
        premise_ids=["p1"],
        certificate=FAKE_CERTIFICATE,
        certificate_format="tstp",
    )
    env_lock = EnvironmentLockRecord(
        lock_id="lock-1",
        itp=ITPKind.LEAN,
        itp_version="4.9.0",
        kernel_command_template="lean {file}",
        solver_versions={"z3": "4.13.0"},
        executable_paths={"lean": "/usr/bin/lean"},
        os_info="linux-x86_64",
    )
    reconstruction = ReconstructionRecord(
        reconstruction_id="r1",
        request_id=request.request_id,
        candidate_id="c1",
        target_itp=ITPKind.LEAN,
        environment_lock_id="lock-1",
        kernel_command="lean check.lean",
        kernel_accepted=True,
    )
    defaults = dict(
        result_id="res-1",
        request=request,
        status=HammerResultStatus.VERIFIED,
        corpus_revision="corpus-rev-1",
        environment_lock=env_lock,
        premises=[premise],
        translations=[translation],
        solver_attempts=[attempt],
        proof_candidate=candidate,
        reconstruction=reconstruction,
    )
    defaults.update(overrides)
    return HammerResult(**defaults)


def make_reconstruction_evidence(**overrides) -> ReconstructionEvidence:
    defaults = dict(
        reconstruction_id="r1",
        request_id="req-1",
        candidate_id="c1",
        itp=ITPKind.LEAN,
        command=["lean", "check.lean"],
        checked_source=FAKE_CHECKED_SOURCE,
        reconstructed_proof_text="rfl",
        stdout=f"kernel accepted; debug password={FAKE_API_KEY}",
        stderr="",
        returncode=0,
        timed_out=False,
        wall_time_seconds=0.2,
    )
    defaults.update(overrides)
    return ReconstructionEvidence(**defaults)


def make_solver_evidence(**overrides) -> SolverAttemptEvidence:
    defaults = dict(
        attempt_id="a1",
        command=["z3", "-in", "input.smt2"],
        input_digest=compute_content_digest({"input": FAKE_TRANSLATED}),
        raw_stdout=f"unsat -- token={FAKE_API_KEY}",
        raw_stderr="",
        solver_trace="unsat",
    )
    defaults.update(overrides)
    return SolverAttemptEvidence(**defaults)


def make_normalized_evidence(**overrides) -> NormalizedEvidence:
    defaults = dict(
        request_id="req-1",
        attempt_id="a1",
        candidate_id="c1",
        kind=EvidenceKind.PROOF,
        format="tstp",
        verdict=SolverVerdict.PROVED,
        premise_ids=["p1"],
        translation_ids=["t1"],
        proof_steps=[ProofStep(step_id="f1", role="axiom", formula=FAKE_TRANSLATED)],
        recommended_status=HammerResultStatus.CANDIDATE,
    )
    defaults.update(overrides)
    return NormalizedEvidence(**defaults)


def make_decomposition_plan(**overrides) -> DecompositionPlan:
    native_text = "n = n"
    llm_text = "n + 0 = n"
    native_subgoal = DecompositionSubgoal(
        subgoal_id="sg-native",
        request_id="req-1",
        rank=0,
        source=DecompositionSource.NATIVE_STRUCTURAL,
        statement=native_text,
        redacted_suggestion=None,
        review_status=ReviewStatus.NOT_REQUIRED,
        status=SubgoalStatus.PENDING,
        content_digest=compute_content_digest({"statement": native_text}),
    )
    llm_subgoal = DecompositionSubgoal(
        subgoal_id="sg-llm",
        request_id="req-1",
        rank=1,
        source=DecompositionSource.LLM_SUGGESTED,
        statement=llm_text,
        redacted_suggestion=redact_llm_text(llm_text),
        review_status=ReviewStatus.PENDING_REVIEW,
        status=SubgoalStatus.PENDING,
        content_digest=compute_content_digest({"statement": llm_text}),
    )
    defaults = dict(
        plan_id="plan-1",
        request_id="req-1",
        trigger=FallbackTrigger.RECONSTRUCTION_FAILURE,
        max_subgoals=4,
        subgoals=[native_subgoal, llm_subgoal],
        notes=["no native automation attempted in this fixture"],
    )
    defaults.update(overrides)
    return DecompositionPlan(**defaults)


def make_receipt_components() -> dict:
    """Build one shared set of trust-contract/evidence objects.

    Note: several nested records default their timestamp fields to
    ``utcnow()`` at construction time (``HammerRequest.created_at``,
    ``HammerResult.created_at``, ``SolverAttemptRecord.started_at``,
    ``ReconstructionRecord.started_at``, ``EnvironmentLockRecord.
    pinned_at``, ``DecompositionPlan.created_at``). Reusing the exact same
    object instances (rather than rebuilding fresh ones) across multiple
    :class:`~ipfs_datasets_py.logic.hammers.receipts.HammerReceipt`
    constructions is what makes ``receipt_id`` determinism tests
    meaningful without needing to freeze the clock.
    """

    return dict(
        result=make_verified_result(),
        reconstruction_evidence=make_reconstruction_evidence(),
        solver_evidence=[make_solver_evidence()],
        normalized_evidence=[make_normalized_evidence()],
        decomposition_plan=make_decomposition_plan(),
    )


def make_full_receipt(**overrides) -> rc.HammerReceipt:
    defaults = make_receipt_components()
    defaults.update(
        metadata={"pipeline_run": "ci-1", "secret_token": FAKE_API_KEY},
        notes=[f"contact api_key={FAKE_API_KEY} for support"],
    )
    defaults.update(overrides)
    return rc.HammerReceipt(**defaults)


# ---------------------------------------------------------------------------
# HammerReceipt construction / validation
# ---------------------------------------------------------------------------


class TestHammerReceiptConstruction:
    def test_minimal_receipt_from_result_only(self):
        result = make_verified_result()
        receipt = rc.HammerReceipt(result=result)
        assert receipt.receipt_id
        assert receipt.is_verified()
        assert receipt.reconstruction_evidence is None
        assert receipt.solver_evidence == []

    def test_full_receipt_construction_succeeds(self):
        receipt = make_full_receipt()
        assert receipt.receipt_id
        assert receipt.is_verified()
        assert receipt.reconstruction_evidence is not None
        assert len(receipt.solver_evidence) == 1
        assert len(receipt.normalized_evidence) == 1
        assert receipt.decomposition_plan is not None

    def test_missing_result_raises(self):
        with pytest.raises(rc.ReceiptValidationError):
            rc.HammerReceipt(result=None)

    def test_result_of_wrong_type_raises(self):
        with pytest.raises(rc.ReceiptValidationError):
            rc.HammerReceipt(result="not-a-result")  # type: ignore[arg-type]

    def test_reconstruction_evidence_request_mismatch_raises(self):
        result = make_verified_result()
        bad_evidence = make_reconstruction_evidence(request_id="other-req")
        with pytest.raises(rc.ReceiptValidationError, match="request_id"):
            rc.HammerReceipt(result=result, reconstruction_evidence=bad_evidence)

    def test_reconstruction_evidence_candidate_mismatch_raises(self):
        result = make_verified_result()
        bad_evidence = make_reconstruction_evidence(candidate_id="other-candidate")
        with pytest.raises(rc.ReceiptValidationError, match="candidate_id"):
            rc.HammerReceipt(result=result, reconstruction_evidence=bad_evidence)

    def test_reconstruction_evidence_reconstruction_id_mismatch_raises(self):
        result = make_verified_result()
        bad_evidence = make_reconstruction_evidence(reconstruction_id="other-recon")
        with pytest.raises(rc.ReceiptValidationError, match="reconstruction_id"):
            rc.HammerReceipt(result=result, reconstruction_evidence=bad_evidence)

    def test_solver_evidence_unknown_attempt_id_raises(self):
        result = make_verified_result()
        bad_evidence = make_solver_evidence(attempt_id="unknown-attempt")
        with pytest.raises(rc.ReceiptValidationError, match="attempt_id"):
            rc.HammerReceipt(result=result, solver_evidence=[bad_evidence])

    def test_normalized_evidence_request_mismatch_raises(self):
        result = make_verified_result()
        bad_evidence = make_normalized_evidence(request_id="other-req")
        with pytest.raises(rc.ReceiptValidationError, match="request_id"):
            rc.HammerReceipt(result=result, normalized_evidence=[bad_evidence])

    def test_normalized_evidence_unknown_attempt_id_raises(self):
        result = make_verified_result()
        bad_evidence = make_normalized_evidence(attempt_id="unknown-attempt")
        with pytest.raises(rc.ReceiptValidationError, match="attempt_id"):
            rc.HammerReceipt(result=result, normalized_evidence=[bad_evidence])

    def test_decomposition_plan_request_mismatch_raises(self):
        result = make_verified_result()
        # Internally consistent (subgoals share the plan's own request_id)
        # so DecompositionPlan.validate() itself passes; only the
        # receipt-level cross-check against result.request.request_id
        # should fail.
        other_subgoal = DecompositionSubgoal(
            subgoal_id="sg-other",
            request_id="other-req",
            rank=0,
            source=DecompositionSource.NATIVE_STRUCTURAL,
            statement="m = m",
            review_status=ReviewStatus.NOT_REQUIRED,
            status=SubgoalStatus.PENDING,
            content_digest=compute_content_digest({"statement": "m = m"}),
        )
        bad_plan = make_decomposition_plan(
            request_id="other-req", subgoals=[other_subgoal]
        )
        with pytest.raises(rc.ReceiptValidationError, match="request_id"):
            rc.HammerReceipt(result=result, decomposition_plan=bad_plan)


# ---------------------------------------------------------------------------
# Content addressing
# ---------------------------------------------------------------------------


class TestReceiptDigest:
    def test_receipt_id_is_deterministic(self):
        components = make_receipt_components()
        receipt_a = rc.HammerReceipt(**components)
        receipt_b = rc.HammerReceipt(**components)
        assert receipt_a.receipt_id == receipt_b.receipt_id

    def test_receipt_id_changes_with_content(self):
        components = make_receipt_components()
        receipt_a = rc.HammerReceipt(**components)
        other = dict(components)
        other["result"] = make_verified_result(result_id="res-2")
        receipt_b = rc.HammerReceipt(**other)
        assert receipt_a.receipt_id != receipt_b.receipt_id

    def test_receipt_id_stable_across_notes_and_metadata(self):
        components = make_receipt_components()
        receipt_a = rc.HammerReceipt(**components, notes=["note A"], metadata={"x": 1})
        receipt_b = rc.HammerReceipt(
            **components, notes=["note B", "note C"], metadata={"y": 2}
        )
        assert receipt_a.receipt_id == receipt_b.receipt_id

    def test_compute_receipt_digest_matches_receipt_id(self):
        receipt = make_full_receipt()
        assert rc.compute_receipt_digest(receipt) == receipt.receipt_id

    def test_explicit_receipt_id_is_preserved_not_recomputed(self):
        receipt = rc.HammerReceipt(result=make_verified_result(), receipt_id="custom-id-1")
        assert receipt.receipt_id == "custom-id-1"


# ---------------------------------------------------------------------------
# to_dict / from_dict round-trip
# ---------------------------------------------------------------------------


class TestReceiptRoundTrip:
    def test_round_trip_preserves_receipt_id_and_content(self):
        receipt = make_full_receipt()
        data = receipt.to_dict()
        restored = rc.HammerReceipt.from_dict(data)
        assert restored.receipt_id == receipt.receipt_id
        assert restored.to_dict() == data

    def test_round_trip_is_json_serializable(self):
        receipt = make_full_receipt()
        data = receipt.to_dict()
        blob = json.dumps(data)
        restored = rc.HammerReceipt.from_dict(json.loads(blob))
        assert restored.receipt_id == receipt.receipt_id


# ---------------------------------------------------------------------------
# Publishable (redacted) view
# ---------------------------------------------------------------------------


class TestPublishableView:
    def test_visibility_and_digest_present(self):
        receipt = make_full_receipt()
        published = receipt.to_publishable_dict()
        assert published["visibility"] == "publishable"
        assert published["publishable_digest"]
        assert isinstance(published["redaction_notes"], list)
        assert published["redaction_notes"] == sorted(published["redaction_notes"])

    def test_goal_statement_is_redacted(self):
        receipt = make_full_receipt()
        published = receipt.to_publishable_dict()
        goal = published["result"]["request"]["goal_statement"]
        assert FAKE_GOAL not in goal
        assert "redacted:private-theorem-goal" in goal
        assert "private-theorem-goal" in published["redaction_notes"]

    def test_translation_text_is_redacted(self):
        receipt = make_full_receipt()
        published = receipt.to_publishable_dict()
        translated = published["result"]["translations"][0]["translated_text"]
        assert FAKE_TRANSLATED not in translated
        assert "redacted:private-theorem-translation" in translated

    def test_candidate_certificate_is_redacted(self):
        receipt = make_full_receipt()
        published = receipt.to_publishable_dict()
        certificate = published["result"]["proof_candidate"]["certificate"]
        assert FAKE_CERTIFICATE not in certificate
        assert "redacted:private-theorem-candidate-certificate" in certificate

    def test_reconstruction_evidence_is_redacted(self):
        receipt = make_full_receipt()
        published = receipt.to_publishable_dict()
        evidence = published["reconstruction_evidence"]
        assert FAKE_CHECKED_SOURCE not in evidence["checked_source"]
        assert "redacted:private-theorem-checked-source" in evidence["checked_source"]
        assert "rfl" != evidence["reconstructed_proof_text"]
        assert "redacted:private-theorem-proof-text" in evidence["reconstructed_proof_text"]
        # the credential embedded in stdout must not survive in any form.
        assert FAKE_API_KEY not in json.dumps(published)

    def test_solver_evidence_raw_output_is_redacted(self):
        receipt = make_full_receipt()
        published = receipt.to_publishable_dict()
        evidence = published["solver_evidence"][0]
        assert "redacted:solver-stdout" in evidence["raw_stdout"]
        assert FAKE_API_KEY not in evidence["raw_stdout"]

    def test_normalized_proof_step_formula_is_redacted(self):
        receipt = make_full_receipt()
        published = receipt.to_publishable_dict()
        step = published["normalized_evidence"][0]["proof_steps"][0]
        assert FAKE_TRANSLATED not in step["formula"]
        assert "redacted:proof-step-formula" in step["formula"]

    def test_decomposition_subgoal_statements_are_redacted(self):
        receipt = make_full_receipt()
        published = receipt.to_publishable_dict()
        subgoals = published["decomposition_plan"]["subgoals"]
        native = next(s for s in subgoals if s["source"] == "native_structural")
        llm = next(s for s in subgoals if s["source"] == "llm_suggested")
        assert "redacted:private-theorem-subgoal" in native["statement"]
        assert "redacted:llm-suggested-subgoal" in llm["statement"]
        # HAMMER-011's own redacted_suggestion placeholder is untouched and
        # never itself leaks the raw suggestion text.
        assert llm["redacted_suggestion"].startswith("<llm-suggested subgoal redacted")

    def test_public_premise_statement_is_not_redacted(self):
        receipt = make_full_receipt()
        published = receipt.to_publishable_dict()
        premise = published["result"]["premises"][0]
        assert premise["statement"] == "public_corpus_lemma : forall n, n = n"

    def test_credentials_are_scrubbed_everywhere(self):
        receipt = make_full_receipt()
        published = receipt.to_publishable_dict()
        blob = json.dumps(published)
        assert FAKE_API_KEY not in blob
        # the request metadata credential key is fully replaced.
        assert published["result"]["request"]["metadata"]["api_key"] == (
            rc._CREDENTIAL_PLACEHOLDER
        )
        assert published["metadata"]["secret_token"] == rc._CREDENTIAL_PLACEHOLDER
        assert rc._CREDENTIAL_PLACEHOLDER in published["notes"][0]

    def test_original_receipt_is_not_mutated(self):
        receipt = make_full_receipt()
        before = receipt.to_dict()
        receipt.to_publishable_dict()
        after = receipt.to_dict()
        assert before == after

    def test_publishable_dict_is_json_serializable(self):
        receipt = make_full_receipt()
        published = receipt.to_publishable_dict()
        json.dumps(published)  # must not raise

    def test_build_publishable_view_matches_method(self):
        receipt = make_full_receipt()
        assert rc.build_publishable_view(receipt) == receipt.to_publishable_dict()


class TestScrubCredentialText:
    def test_scrubs_openai_style_key(self):
        text = f"key is {FAKE_API_KEY} end"
        scrubbed = rc.scrub_credential_text(text)
        assert FAKE_API_KEY not in scrubbed
        assert rc._CREDENTIAL_PLACEHOLDER in scrubbed

    def test_scrubs_bearer_token(self):
        text = "Authorization: Bearer abcdef1234567890ABCDEF"
        scrubbed = rc.scrub_credential_text(text)
        assert "abcdef1234567890ABCDEF" not in scrubbed

    def test_scrubs_aws_key(self):
        text = "aws_access_key_id=AKIAABCDEFGHIJKLMNOP"
        scrubbed = rc.scrub_credential_text(text)
        assert "AKIAABCDEFGHIJKLMNOP" not in scrubbed

    def test_leaves_ordinary_text_untouched(self):
        text = "the theorem n = n holds by reflexivity"
        assert rc.scrub_credential_text(text) == text

    def test_handles_non_string_input(self):
        assert rc.scrub_credential_text(None) is None  # type: ignore[arg-type]
        assert rc.scrub_credential_text("") == ""


# ---------------------------------------------------------------------------
# ReceiptStore: local-disk fallback (default behavior)
# ---------------------------------------------------------------------------


class TestReceiptStoreLocalDisk:
    def test_put_and_get_round_trip(self, tmp_path):
        store = rc.ReceiptStore(root_dir=tmp_path)
        receipt = make_full_receipt()
        result = store.put(receipt)
        assert result.full.backend == "local-disk"
        assert result.full.cid is None
        assert result.publishable is None

        restored = store.get(receipt.receipt_id)
        assert restored.receipt_id == receipt.receipt_id
        assert restored.to_dict() == receipt.to_dict()

    def test_put_with_publish_writes_redacted_copy(self, tmp_path):
        store = rc.ReceiptStore(root_dir=tmp_path)
        receipt = make_full_receipt()
        result = store.put(receipt, publish=True)
        assert result.publishable is not None
        assert result.publishable.backend == "local-disk"

        published = store.get_publishable(receipt.receipt_id)
        assert published["visibility"] == "publishable"
        assert FAKE_GOAL not in json.dumps(published)
        assert FAKE_API_KEY not in json.dumps(published)

    def test_get_unknown_id_raises_not_found(self, tmp_path):
        store = rc.ReceiptStore(root_dir=tmp_path)
        with pytest.raises(rc.ReceiptNotFoundError):
            store.get("does-not-exist")

    def test_get_publishable_unknown_id_raises_not_found(self, tmp_path):
        store = rc.ReceiptStore(root_dir=tmp_path)
        receipt = make_full_receipt()
        store.put(receipt, publish=False)
        with pytest.raises(rc.ReceiptNotFoundError):
            store.get_publishable(receipt.receipt_id)

    def test_exists_and_list_ids(self, tmp_path):
        store = rc.ReceiptStore(root_dir=tmp_path)
        receipt = make_full_receipt()
        assert not store.exists(receipt.receipt_id)
        store.put(receipt)
        assert store.exists(receipt.receipt_id)
        assert receipt.receipt_id in store.list_ids()
        assert store.list_ids(publishable=True) == []

    def test_default_store_never_touches_ipfs_backend(self, tmp_path, monkeypatch):
        # Sanity: a store constructed with defaults (use_ipfs unset, no
        # backend injected, no env override) never even attempts to
        # resolve an IPFS backend, so persistence works with zero external
        # dependencies and no network/daemon requirement.
        monkeypatch.delenv("IPFS_DATASETS_PY_HAMMER_RECEIPTS_USE_IPFS", raising=False)
        store = rc.ReceiptStore(root_dir=tmp_path)
        assert store._resolve_ipfs_backend() is None
        receipt = make_full_receipt()
        location = store.put(receipt).full
        assert location.backend == "local-disk"


# ---------------------------------------------------------------------------
# ReceiptStore: injected fake IPFS backend
# ---------------------------------------------------------------------------


class _FakeIPFSBackend:
    """Duck-typed in-memory stand-in for
    :class:`ipfs_datasets_py.ipfs_backend_router.IPFSBackend` used to test
    the IPFS-aware path without any real daemon/network dependency."""

    def __init__(self, *, fail: bool = False):
        self._store: dict[str, bytes] = {}
        self._counter = 0
        self.fail = fail
        self.pinned: set[str] = set()

    def add_bytes(self, data: bytes, *, pin: bool = True) -> str:
        if self.fail:
            raise RuntimeError("simulated IPFS daemon unavailable")
        self._counter += 1
        cid = f"bafyfake{self._counter:04d}"
        self._store[cid] = data
        if pin:
            self.pinned.add(cid)
        return cid

    def cat(self, cid: str) -> bytes:
        if cid not in self._store:
            raise KeyError(cid)
        return self._store[cid]


class TestReceiptStoreIPFS:
    def test_put_uses_injected_backend(self, tmp_path):
        backend = _FakeIPFSBackend()
        store = rc.ReceiptStore(root_dir=tmp_path, ipfs_backend=backend)
        receipt = make_full_receipt()
        result = store.put(receipt)
        assert result.full.backend == "ipfs"
        assert result.full.cid in backend._store
        assert result.full.pinned is True

    def test_get_survives_local_cache_deletion_via_index(self, tmp_path):
        backend = _FakeIPFSBackend()
        store = rc.ReceiptStore(root_dir=tmp_path, ipfs_backend=backend)
        receipt = make_full_receipt()
        store.put(receipt)

        local_path = store._local_path(receipt.receipt_id, publishable=False)
        assert local_path.exists()
        local_path.unlink()
        assert not local_path.exists()

        restored = store.get(receipt.receipt_id)
        assert restored.receipt_id == receipt.receipt_id
        # Reading through IPFS repopulates the local cache.
        assert local_path.exists()

    def test_ipfs_failure_falls_back_to_local_disk(self, tmp_path):
        backend = _FakeIPFSBackend(fail=True)
        store = rc.ReceiptStore(root_dir=tmp_path, ipfs_backend=backend)
        receipt = make_full_receipt()
        result = store.put(receipt)
        assert result.full.backend == "local-disk"
        assert result.full.cid is None

        restored = store.get(receipt.receipt_id)
        assert restored.receipt_id == receipt.receipt_id

    def test_publishable_copy_uses_distinct_cid_from_full_copy(self, tmp_path):
        backend = _FakeIPFSBackend()
        store = rc.ReceiptStore(root_dir=tmp_path, ipfs_backend=backend)
        receipt = make_full_receipt()
        result = store.put(receipt, publish=True)
        assert result.full.cid != result.publishable.cid
        assert result.publishable.backend == "ipfs"


# ---------------------------------------------------------------------------
# persist_hammer_receipt convenience wrapper
# ---------------------------------------------------------------------------


class TestPersistHammerReceipt:
    def test_persist_with_explicit_store(self, tmp_path):
        store = rc.ReceiptStore(root_dir=tmp_path)
        receipt = make_full_receipt()
        result = rc.persist_hammer_receipt(receipt, store=store)
        assert result.full.backend == "local-disk"
        assert store.get(receipt.receipt_id).receipt_id == receipt.receipt_id

    def test_persist_with_default_store_uses_default_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IPFS_DATASETS_PY_HAMMER_RECEIPTS_DIR", str(tmp_path))
        receipt = make_full_receipt()
        result = rc.persist_hammer_receipt(receipt)
        assert result.full.path is not None
        assert str(tmp_path) in result.full.path


# ---------------------------------------------------------------------------
# StorageLocation / PersistResult serialization
# ---------------------------------------------------------------------------


class TestStorageLocationSerialization:
    def test_storage_location_round_trip(self):
        location = rc.StorageLocation(
            backend="ipfs", digest="sha256:abc", cid="bafyfake0001", path="/tmp/x.json", pinned=True
        )
        data = location.to_dict()
        restored = rc.StorageLocation.from_dict(data)
        assert restored == location

    def test_persist_result_to_dict(self, tmp_path):
        store = rc.ReceiptStore(root_dir=tmp_path)
        receipt = make_full_receipt()
        result = store.put(receipt, publish=True)
        data = result.to_dict()
        assert data["full"]["digest"] == receipt.receipt_id
        assert data["publishable"]["digest"] == receipt.receipt_id
