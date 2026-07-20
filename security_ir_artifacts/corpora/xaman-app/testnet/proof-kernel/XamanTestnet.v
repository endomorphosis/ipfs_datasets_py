(*
   PORTAL-CXTP-136: independent Rocq kernel for the bounded Xaman Testnet
   evidence model. This validates acceptance and refusal rules only. It does
   not model native vault cryptography, raw payload semantics, backend
   single-use, XRPL finality, deployed runtime equivalence, or production.
*)

Inductive ClaimStatus : Type :=
| modeledWithTestnetScope
| modeledWithBlockingNotModeledBoundary
| notModeled.

Inductive KernelResult : Type :=
| proved
| counterexample
| incomplete.

Record TestnetClaim : Type := {
  claimStatus : ClaimStatus;
  modelCidMatches : bool;
  claimIdInFrozenModel : bool;
  evidenceReviewed : bool
}.

Record TestnetEvidence : Type := {
  networkKeyIsTestnet : bool;
  networkIdIsOne : bool;
  endpointAllowListed : bool;
  freshTestnetAccount : bool;
  importedProductionAccountAbsent : bool;
  accountMaterialRedacted : bool;
  payloadIntakeObserved : bool;
  reviewObserved : bool;
  authObserved : bool;
  signingDecisionObserved : bool;
  submitAttemptObserved : bool;
  submitResultObserved : bool;
  observedOrderMatches : bool;
  rawPayloadExcluded : bool;
  rawSignatureBlobExcluded : bool;
  auditRedactionPreserved : bool
}.

Definition testnetNetworkBoundary (evidence : TestnetEvidence) : bool :=
  andb (networkKeyIsTestnet evidence)
    (andb (networkIdIsOne evidence) (endpointAllowListed evidence)).

Definition freshAccountBoundary (evidence : TestnetEvidence) : bool :=
  andb (freshTestnetAccount evidence)
    (andb (importedProductionAccountAbsent evidence)
      (accountMaterialRedacted evidence)).

Definition observedLifecycleOrder (evidence : TestnetEvidence) : bool :=
  andb (payloadIntakeObserved evidence)
    (andb (reviewObserved evidence)
      (andb (authObserved evidence)
        (andb (signingDecisionObserved evidence)
          (andb (submitAttemptObserved evidence)
            (andb (submitResultObserved evidence) (observedOrderMatches evidence)))))).

Definition auditRedactionBoundary (evidence : TestnetEvidence) : bool :=
  andb (rawPayloadExcluded evidence)
    (andb (rawSignatureBlobExcluded evidence) (auditRedactionPreserved evidence)).

Definition formalizedInvariantHolds (evidence : TestnetEvidence) : bool :=
  andb (testnetNetworkBoundary evidence)
    (andb (freshAccountBoundary evidence)
      (andb (observedLifecycleOrder evidence) (auditRedactionBoundary evidence))).

Definition canUseRocqEvidenceForClaim
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) : bool :=
  match result, claimStatus claim with
  | proved, modeledWithTestnetScope =>
      andb (modelCidMatches claim)
        (andb (claimIdInFrozenModel claim)
          (andb (evidenceReviewed claim) (formalizedInvariantHolds evidence)))
  | _, _ => false
  end.

Definition canCloseTestnetAssurance
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence)
    (blockingAssumptionsCleared runtimeEquivalenceProved independentKernelChecked : bool) : bool :=
  andb (canUseRocqEvidenceForClaim claim result evidence)
    (andb blockingAssumptionsCleared
      (andb runtimeEquivalenceProved independentKernelChecked)).

Theorem reject_counterexample_result : forall claim evidence,
  canUseRocqEvidenceForClaim claim counterexample evidence = false.
Proof. intros. reflexivity. Qed.

Theorem reject_incomplete_result : forall claim evidence,
  canUseRocqEvidenceForClaim claim incomplete evidence = false.
Proof. intros. reflexivity. Qed.

Theorem reject_not_modeled_claim : forall result evidence model_cid frozen reviewed,
  canUseRocqEvidenceForClaim
    {| claimStatus := notModeled;
       modelCidMatches := model_cid;
       claimIdInFrozenModel := frozen;
       evidenceReviewed := reviewed |}
    result evidence = false.
Proof. intros. destruct result; reflexivity. Qed.

Theorem reject_blocking_not_modeled_boundary : forall result evidence model_cid frozen reviewed,
  canUseRocqEvidenceForClaim
    {| claimStatus := modeledWithBlockingNotModeledBoundary;
       modelCidMatches := model_cid;
       claimIdInFrozenModel := frozen;
       evidenceReviewed := reviewed |}
    result evidence = false.
Proof. intros. destruct result; reflexivity. Qed.

Theorem reject_model_cid_mismatch : forall status result evidence frozen reviewed,
  canUseRocqEvidenceForClaim
    {| claimStatus := status;
       modelCidMatches := false;
       claimIdInFrozenModel := frozen;
       evidenceReviewed := reviewed |}
    result evidence = false.
Proof. intros. destruct result, status, frozen, reviewed; reflexivity. Qed.

Theorem reject_claim_outside_frozen_model : forall status result evidence model_cid reviewed,
  canUseRocqEvidenceForClaim
    {| claimStatus := status;
       modelCidMatches := model_cid;
       claimIdInFrozenModel := false;
       evidenceReviewed := reviewed |}
    result evidence = false.
Proof. intros. destruct result, status, model_cid, reviewed; reflexivity. Qed.

Theorem reject_unreviewed_evidence : forall status result evidence model_cid frozen,
  canUseRocqEvidenceForClaim
    {| claimStatus := status;
       modelCidMatches := model_cid;
       claimIdInFrozenModel := frozen;
       evidenceReviewed := false |}
    result evidence = false.
Proof. intros. destruct result, status, model_cid, frozen; reflexivity. Qed.

Theorem missing_assumptions_prevent_assurance : forall claim result evidence runtime independent,
  canCloseTestnetAssurance claim result evidence false runtime independent = false.
Proof.
  intros. unfold canCloseTestnetAssurance.
  destruct (canUseRocqEvidenceForClaim claim result evidence); reflexivity.
Qed.

Theorem missing_runtime_equivalence_prevents_assurance : forall claim result evidence assumptions independent,
  canCloseTestnetAssurance claim result evidence assumptions false independent = false.
Proof.
  intros. unfold canCloseTestnetAssurance.
  destruct (canUseRocqEvidenceForClaim claim result evidence); destruct assumptions; reflexivity.
Qed.

Theorem missing_independent_kernel_prevents_assurance : forall claim result evidence assumptions runtime,
  canCloseTestnetAssurance claim result evidence assumptions runtime false = false.
Proof.
  intros. unfold canCloseTestnetAssurance.
  destruct (canUseRocqEvidenceForClaim claim result evidence); destruct assumptions, runtime; reflexivity.
Qed.
