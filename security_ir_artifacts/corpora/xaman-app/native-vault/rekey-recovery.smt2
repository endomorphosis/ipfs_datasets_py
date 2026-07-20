(set-logic QF_UF)
; PORTAL-CXTP-162.  Abstract public-source rekey ordering only.
; A recovery snapshot is written under the old key before the primary vault is
; deleted.  A replacement write may fail after that deletion.
(declare-const recovery_snapshot_written Bool)
(declare-const replacement_write_succeeds Bool)
(declare-const primary_present_after Bool)
(declare-const recovery_present_after Bool)
(declare-const recovery_requires_old_key Bool)

(assert (= primary_present_after replacement_write_succeeds))
(assert (= recovery_present_after
  (and recovery_snapshot_written (not replacement_write_succeeds))))
(assert (= recovery_requires_old_key recovery_snapshot_written))

; Property 1: a successful replacement leaves the primary vault and removes
; the recovery vault in this abstraction.
(push)
(assert (not (=> replacement_write_succeeds
  (and primary_present_after (not recovery_present_after)))))
(check-sat)
(pop)

; Property 2: after a replacement-write failure, a written recovery snapshot
; remains and the primary vault is absent.  Recovery therefore needs old-key
; material; the model makes no claim that an application retains it.
(push)
(assert (not (=> (and recovery_snapshot_written (not replacement_write_succeeds))
  (and (not primary_present_after) recovery_present_after recovery_requires_old_key))))
(check-sat)
(pop)

; Expected partial-state witness.  It is a test obligation, not a vulnerability
; finding: a failed replacement can leave only the old-key recovery vault.
(push)
(assert recovery_snapshot_written)
(assert (not replacement_write_succeeds))
(assert (not primary_present_after))
(assert recovery_present_after)
(assert recovery_requires_old_key)
(check-sat)
(pop)
