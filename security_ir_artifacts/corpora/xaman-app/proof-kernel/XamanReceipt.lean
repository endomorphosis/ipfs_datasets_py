namespace XamanReceipt

inductive ProofStatus where
  | proved
  | disproved
  | unknown
  | notModeled
  deriving DecidableEq, Repr

structure ProofReport where
  claimId : String
  modelCid : String
  status : ProofStatus
  assumptionsCleared : Bool
  evidenceReviewed : Bool
  solverAgreement : Bool
  noCounterexample : Bool
  deriving Repr

structure ProofReceipt where
  claimId : String
  modelCid : String
  reportCidMatches : Bool
  trustedSignatureOrCanonicalCid : Bool
  acceptedAssumptionsCurrent : Bool
  supportedProver : Bool
  deriving Repr

def bindingMatches (report : ProofReport) (receipt : ProofReceipt) : Bool :=
  report.claimId == receipt.claimId && report.modelCid == receipt.modelCid

def canAccept (report : ProofReport) (receipt : ProofReceipt) : Bool :=
  report.status == ProofStatus.proved
    && bindingMatches report receipt
    && report.assumptionsCleared
    && report.evidenceReviewed
    && report.solverAgreement
    && report.noCounterexample
    && receipt.reportCidMatches
    && receipt.trustedSignatureOrCanonicalCid
    && receipt.acceptedAssumptionsCurrent
    && receipt.supportedProver

theorem reject_disproved_status (report : ProofReport) (receipt : ProofReceipt) :
    canAccept { report with status := ProofStatus.disproved } receipt = false := by
  simp [canAccept]

theorem reject_unknown_status (report : ProofReport) (receipt : ProofReceipt) :
    canAccept { report with status := ProofStatus.unknown } receipt = false := by
  simp [canAccept]

theorem reject_not_modeled_status (report : ProofReport) (receipt : ProofReceipt) :
    canAccept { report with status := ProofStatus.notModeled } receipt = false := by
  simp [canAccept]

theorem reject_uncleared_assumptions (report : ProofReport) (receipt : ProofReceipt) :
    canAccept { report with assumptionsCleared := false } receipt = false := by
  simp [canAccept]

theorem reject_unreviewed_evidence (report : ProofReport) (receipt : ProofReceipt) :
    canAccept { report with evidenceReviewed := false } receipt = false := by
  simp [canAccept]

theorem reject_solver_disagreement (report : ProofReport) (receipt : ProofReceipt) :
    canAccept { report with solverAgreement := false } receipt = false := by
  simp [canAccept]

theorem reject_counterexample (report : ProofReport) (receipt : ProofReceipt) :
    canAccept { report with noCounterexample := false } receipt = false := by
  simp [canAccept]

theorem reject_report_cid_mismatch (report : ProofReport) (receipt : ProofReceipt) :
    canAccept report { receipt with reportCidMatches := false } = false := by
  simp [canAccept]

theorem reject_missing_trust_anchor (report : ProofReport) (receipt : ProofReceipt) :
    canAccept report { receipt with trustedSignatureOrCanonicalCid := false } = false := by
  simp [canAccept]

theorem reject_stale_assumptions (report : ProofReport) (receipt : ProofReceipt) :
    canAccept report { receipt with acceptedAssumptionsCurrent := false } = false := by
  simp [canAccept]

theorem reject_unsupported_prover (report : ProofReport) (receipt : ProofReceipt) :
    canAccept report { receipt with supportedProver := false } = false := by
  simp [canAccept]

def acceptedExampleReport : ProofReport := {
  claimId := "xaman-claim:proof-consumer-must-reject-non-proved-results"
  modelCid := "sha256:316ead1268fb192641ece96ef255e92922b93623d6f4b1057dc56a2cec711c8d"
  status := ProofStatus.proved
  assumptionsCleared := true
  evidenceReviewed := true
  solverAgreement := true
  noCounterexample := true
}

def acceptedExampleReceipt : ProofReceipt := {
  claimId := "xaman-claim:proof-consumer-must-reject-non-proved-results"
  modelCid := "sha256:316ead1268fb192641ece96ef255e92922b93623d6f4b1057dc56a2cec711c8d"
  reportCidMatches := true
  trustedSignatureOrCanonicalCid := true
  acceptedAssumptionsCurrent := true
  supportedProver := true
}

example : canAccept acceptedExampleReport acceptedExampleReceipt = true := by
  native_decide

example : canAccept { acceptedExampleReport with status := ProofStatus.unknown } acceptedExampleReceipt = false := by
  native_decide

end XamanReceipt
