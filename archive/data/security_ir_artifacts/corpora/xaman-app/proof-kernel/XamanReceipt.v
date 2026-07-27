(*
   PORTAL-CXTP-093: independent Coq kernel for Xaman proof-consumer invariants.
*)

Require Import Coq.Strings.String.

Inductive ProofStatus :=
| proved
| disproved
| unknown
| notModeled.

Record ProofReport := {
  proofClaimId : string;
  proofModelCid : string;
  proofStatus : ProofStatus;
  proofAssumptionsCleared : bool;
  proofEvidenceReviewed : bool;
  proofSolverAgreement : bool;
  proofNoCounterexample : bool
}.

Record ProofReceipt := {
  receiptClaimId : string;
  receiptModelCid : string;
  receiptReportCidMatches : bool;
  receiptTrustedSignatureOrCanonicalCid : bool;
  receiptAcceptedAssumptionsCurrent : bool;
  receiptSupportedProver : bool
}.

Definition bindingMatches (report : ProofReport) (receipt : ProofReceipt) : bool :=
  String.eqb report.(proofClaimId) receipt.(receiptClaimId)
    && String.eqb report.(proofModelCid) receipt.(receiptModelCid).

Definition canAccept (report : ProofReport) (receipt : ProofReceipt) : bool :=
  match report.(proofStatus) with
  | proved =>
      if report.(proofAssumptionsCleared) then
        if report.(proofEvidenceReviewed) then
          if report.(proofSolverAgreement) then
            if report.(proofNoCounterexample) then
              if bindingMatches report receipt then
                if receipt.(receiptReportCidMatches) then
                  if receipt.(receiptTrustedSignatureOrCanonicalCid) then
                    if receipt.(receiptAcceptedAssumptionsCurrent) then
                      receipt.(receiptSupportedProver)
                    else false
                  else false
                else false
              else false
            else false
          else false
        else false
      else false
  | _ => false
  end.

Definition withStatus (report : ProofReport) (status : ProofStatus) : ProofReport :=
  {| proofClaimId := report.(proofClaimId);
     proofModelCid := report.(proofModelCid);
     proofStatus := status;
     proofAssumptionsCleared := report.(proofAssumptionsCleared);
     proofEvidenceReviewed := report.(proofEvidenceReviewed);
     proofSolverAgreement := report.(proofSolverAgreement);
     proofNoCounterexample := report.(proofNoCounterexample) |}.

Definition withAssumptionsCleared (report : ProofReport) (value : bool) : ProofReport :=
  {| proofClaimId := report.(proofClaimId);
     proofModelCid := report.(proofModelCid);
     proofStatus := report.(proofStatus);
     proofAssumptionsCleared := value;
     proofEvidenceReviewed := report.(proofEvidenceReviewed);
     proofSolverAgreement := report.(proofSolverAgreement);
     proofNoCounterexample := report.(proofNoCounterexample) |}.

Definition withEvidenceReviewed (report : ProofReport) (value : bool) : ProofReport :=
  {| proofClaimId := report.(proofClaimId);
     proofModelCid := report.(proofModelCid);
     proofStatus := report.(proofStatus);
     proofAssumptionsCleared := report.(proofAssumptionsCleared);
     proofEvidenceReviewed := value;
     proofSolverAgreement := report.(proofSolverAgreement);
     proofNoCounterexample := report.(proofNoCounterexample) |}.

Definition withSolverAgreement (report : ProofReport) (value : bool) : ProofReport :=
  {| proofClaimId := report.(proofClaimId);
     proofModelCid := report.(proofModelCid);
     proofStatus := report.(proofStatus);
     proofAssumptionsCleared := report.(proofAssumptionsCleared);
     proofEvidenceReviewed := report.(proofEvidenceReviewed);
     proofSolverAgreement := value;
     proofNoCounterexample := report.(proofNoCounterexample) |}.

Definition withNoCounterexample (report : ProofReport) (value : bool) : ProofReport :=
  {| proofClaimId := report.(proofClaimId);
     proofModelCid := report.(proofModelCid);
     proofStatus := report.(proofStatus);
     proofAssumptionsCleared := report.(proofAssumptionsCleared);
     proofEvidenceReviewed := report.(proofEvidenceReviewed);
     proofSolverAgreement := report.(proofSolverAgreement);
     proofNoCounterexample := value |}.

Example can_accept_rejects_disproved :
  forall (r : ProofReport) (p : ProofReceipt), canAccept (withStatus r disproved) p = false.
Proof.
  intros.
  unfold canAccept, withStatus.
  simpl.
  reflexivity.
Qed.

Example can_accept_rejects_unknown :
  forall (r : ProofReport) (p : ProofReceipt), canAccept (withStatus r unknown) p = false.
Proof.
  intros.
  unfold canAccept, withStatus.
  simpl.
  reflexivity.
Qed.

Example can_accept_rejects_notModeled :
  forall (r : ProofReport) (p : ProofReceipt), canAccept (withStatus r notModeled) p = false.
Proof.
  intros.
  unfold canAccept, withStatus.
  simpl.
  reflexivity.
Qed.

Example can_accept_rejects_uncleared :
  forall (r : ProofReport) (p : ProofReceipt),
    canAccept (withAssumptionsCleared r false) p = false.
Proof.
  intros.
  unfold canAccept, withAssumptionsCleared.
  destruct (proofStatus r); simpl; reflexivity.
Qed.

Example can_accept_rejects_unreviewed :
  forall (r : ProofReport) (p : ProofReceipt),
    canAccept (withEvidenceReviewed r false) p = false.
Proof.
  intros.
  unfold canAccept, withEvidenceReviewed.
  destruct (proofStatus r) as [| | |].
  - simpl.
    destruct (proofAssumptionsCleared r); simpl; reflexivity.
  - reflexivity.
  - reflexivity.
  - reflexivity.
Qed.

Example can_accept_rejects_solver_disagree :
  forall (r : ProofReport) (p : ProofReceipt),
    canAccept (withSolverAgreement r false) p = false.
Proof.
  intros.
  unfold canAccept, withSolverAgreement.
  destruct (proofStatus r) as [| | |].
  - simpl.
    destruct (proofAssumptionsCleared r); simpl.
    + destruct (proofEvidenceReviewed r); simpl; reflexivity.
    + reflexivity.
  - reflexivity.
  - reflexivity.
  - reflexivity.
Qed.

Example can_accept_rejects_counterexample :
  forall (r : ProofReport) (p : ProofReceipt),
    canAccept (withNoCounterexample r false) p = false.
Proof.
  intros.
  unfold canAccept, withNoCounterexample.
  destruct (proofStatus r) as [| | |].
  - simpl.
    destruct (proofAssumptionsCleared r); simpl.
    + destruct (proofEvidenceReviewed r); simpl.
      * destruct (proofSolverAgreement r); simpl; reflexivity.
      * reflexivity.
    + reflexivity.
  - reflexivity.
  - reflexivity.
  - reflexivity.
Qed.

Definition acceptedExampleReport : ProofReport :=
  {| proofClaimId := "xaman-claim:proof-consumer-must-reject-non-proved-results";
     proofModelCid := "sha256:316ead1268fb192641ece96ef255e92922b93623d6f4b1057dc56a2cec711c8d";
     proofStatus := proved;
     proofAssumptionsCleared := true;
     proofEvidenceReviewed := true;
     proofSolverAgreement := true;
     proofNoCounterexample := true |}.

Definition acceptedExampleReceipt : ProofReceipt :=
  {| receiptClaimId := "xaman-claim:proof-consumer-must-reject-non-proved-results";
     receiptModelCid := "sha256:316ead1268fb192641ece96ef255e92922b93623d6f4b1057dc56a2cec711c8d";
     receiptReportCidMatches := true;
     receiptTrustedSignatureOrCanonicalCid := true;
     receiptAcceptedAssumptionsCurrent := true;
     receiptSupportedProver := true |}.

Example accepted_example : canAccept acceptedExampleReport acceptedExampleReceipt = true.
Proof.
  vm_compute.
  reflexivity.
Qed.
