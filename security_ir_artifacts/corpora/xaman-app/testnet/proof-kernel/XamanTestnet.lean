namespace XamanTestnet

inductive ClaimStatus where
  | modeledWithTestnetScope
  | modeledWithBlockingNotModeledBoundary
  | notModeled
  deriving DecidableEq, Repr

inductive KernelResult where
  | proved
  | counterexample
  | incomplete
  deriving DecidableEq, Repr

structure TestnetClaim where
  claimId : String
  modelCid : String
  status : ClaimStatus
  modelCidMatches : Bool
  claimIdInFrozenModel : Bool
  evidenceReviewed : Bool
  deriving Repr

structure TestnetEvidence where
  networkKeyIsTestnet : Bool
  networkIdIsOne : Bool
  endpointAllowListed : Bool
  freshTestnetAccount : Bool
  importedProductionAccountAbsent : Bool
  accountMaterialRedacted : Bool
  payloadIntakeObserved : Bool
  reviewObserved : Bool
  authObserved : Bool
  signingDecisionObserved : Bool
  submitAttemptObserved : Bool
  submitResultObserved : Bool
  observedOrderMatches : Bool
  rawPayloadExcluded : Bool
  rawSignatureBlobExcluded : Bool
  auditRedactionPreserved : Bool
  blockingAssumptionsCleared : Bool
  runtimeEquivalenceProved : Bool
  independentKernelChecked : Bool
  deriving Repr

def testnetNetworkBoundary (evidence : TestnetEvidence) : Bool :=
  evidence.networkKeyIsTestnet
    && evidence.networkIdIsOne
    && evidence.endpointAllowListed

def freshAccountBoundary (evidence : TestnetEvidence) : Bool :=
  evidence.freshTestnetAccount
    && evidence.importedProductionAccountAbsent
    && evidence.accountMaterialRedacted

def observedLifecycleOrder (evidence : TestnetEvidence) : Bool :=
  evidence.payloadIntakeObserved
    && evidence.reviewObserved
    && evidence.authObserved
    && evidence.signingDecisionObserved
    && evidence.submitAttemptObserved
    && evidence.submitResultObserved
    && evidence.observedOrderMatches

def auditRedactionBoundary (evidence : TestnetEvidence) : Bool :=
  evidence.rawPayloadExcluded
    && evidence.rawSignatureBlobExcluded
    && evidence.auditRedactionPreserved

def formalizedInvariantHolds (evidence : TestnetEvidence) : Bool :=
  testnetNetworkBoundary evidence
    && freshAccountBoundary evidence
    && observedLifecycleOrder evidence
    && auditRedactionBoundary evidence

def canUseLeanEvidenceForClaim
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) : Bool :=
  result == KernelResult.proved
    && claim.status == ClaimStatus.modeledWithTestnetScope
    && claim.modelCidMatches
    && claim.claimIdInFrozenModel
    && claim.evidenceReviewed
    && formalizedInvariantHolds evidence

def canCloseTestnetAssurance
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) : Bool :=
  canUseLeanEvidenceForClaim claim result evidence
    && evidence.blockingAssumptionsCleared
    && evidence.runtimeEquivalenceProved
    && evidence.independentKernelChecked

theorem reject_counterexample_result
    (claim : TestnetClaim)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim KernelResult.counterexample evidence = false := by
  simp [canUseLeanEvidenceForClaim]

theorem reject_incomplete_result
    (claim : TestnetClaim)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim KernelResult.incomplete evidence = false := by
  simp [canUseLeanEvidenceForClaim]

theorem reject_not_modeled_claim
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim { claim with status := ClaimStatus.notModeled } result evidence = false := by
  simp [canUseLeanEvidenceForClaim]

theorem reject_blocking_not_modeled_boundary
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim
      { claim with status := ClaimStatus.modeledWithBlockingNotModeledBoundary }
      result
      evidence = false := by
  simp [canUseLeanEvidenceForClaim]

theorem reject_model_cid_mismatch
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim { claim with modelCidMatches := false } result evidence = false := by
  simp [canUseLeanEvidenceForClaim]

theorem reject_claim_outside_frozen_model
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim { claim with claimIdInFrozenModel := false } result evidence = false := by
  simp [canUseLeanEvidenceForClaim]

theorem reject_unreviewed_evidence
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim { claim with evidenceReviewed := false } result evidence = false := by
  simp [canUseLeanEvidenceForClaim]

theorem reject_wrong_network_key
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim result { evidence with networkKeyIsTestnet := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, testnetNetworkBoundary]

theorem reject_wrong_network_id
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim result { evidence with networkIdIsOne := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, testnetNetworkBoundary]

theorem reject_non_allowlisted_endpoint
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim result { evidence with endpointAllowListed := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, testnetNetworkBoundary]

theorem reject_imported_or_production_account
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim
      claim
      result
      { evidence with importedProductionAccountAbsent := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, freshAccountBoundary]

theorem reject_account_material_retained
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim result { evidence with accountMaterialRedacted := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, freshAccountBoundary]

theorem reject_missing_payload_intake
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim result { evidence with payloadIntakeObserved := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, observedLifecycleOrder]

theorem reject_missing_review
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim result { evidence with reviewObserved := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, observedLifecycleOrder]

theorem reject_missing_auth
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim result { evidence with authObserved := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, observedLifecycleOrder]

theorem reject_missing_signing_decision
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim result { evidence with signingDecisionObserved := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, observedLifecycleOrder]

theorem reject_missing_submit_result
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim result { evidence with submitResultObserved := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, observedLifecycleOrder]

theorem reject_misordered_lifecycle
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim result { evidence with observedOrderMatches := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, observedLifecycleOrder]

theorem reject_raw_payload_retained
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim result { evidence with rawPayloadExcluded := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, auditRedactionBoundary]

theorem reject_raw_signature_blob_retained
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim result { evidence with rawSignatureBlobExcluded := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, auditRedactionBoundary]

theorem reject_redaction_failure
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canUseLeanEvidenceForClaim claim result { evidence with auditRedactionPreserved := false } = false := by
  simp [canUseLeanEvidenceForClaim, formalizedInvariantHolds, auditRedactionBoundary]

theorem missing_assumptions_prevent_assurance
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canCloseTestnetAssurance
      claim
      result
      { evidence with blockingAssumptionsCleared := false } = false := by
  simp [canCloseTestnetAssurance]

theorem missing_runtime_equivalence_prevents_assurance
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canCloseTestnetAssurance
      claim
      result
      { evidence with runtimeEquivalenceProved := false } = false := by
  simp [canCloseTestnetAssurance]

theorem missing_independent_kernel_prevents_assurance
    (claim : TestnetClaim)
    (result : KernelResult)
    (evidence : TestnetEvidence) :
    canCloseTestnetAssurance
      claim
      result
      { evidence with independentKernelChecked := false } = false := by
  simp [canCloseTestnetAssurance]

def acceptedFormalClaim : TestnetClaim := {
  claimId := "xaman-testnet-claim:review-auth-sequence-observed"
  modelCid := "sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43"
  status := ClaimStatus.modeledWithTestnetScope
  modelCidMatches := true
  claimIdInFrozenModel := true
  evidenceReviewed := true
}

def acceptedFormalEvidence : TestnetEvidence := {
  networkKeyIsTestnet := true
  networkIdIsOne := true
  endpointAllowListed := true
  freshTestnetAccount := true
  importedProductionAccountAbsent := true
  accountMaterialRedacted := true
  payloadIntakeObserved := true
  reviewObserved := true
  authObserved := true
  signingDecisionObserved := true
  submitAttemptObserved := true
  submitResultObserved := true
  observedOrderMatches := true
  rawPayloadExcluded := true
  rawSignatureBlobExcluded := true
  auditRedactionPreserved := true
  blockingAssumptionsCleared := false
  runtimeEquivalenceProved := false
  independentKernelChecked := false
}

example :
    canUseLeanEvidenceForClaim acceptedFormalClaim KernelResult.proved acceptedFormalEvidence = true := by
  native_decide

example :
    canCloseTestnetAssurance acceptedFormalClaim KernelResult.proved acceptedFormalEvidence = false := by
  native_decide

end XamanTestnet
