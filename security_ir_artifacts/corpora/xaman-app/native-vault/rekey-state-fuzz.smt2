(set-logic QF_UF)
; PORTAL-CXTP-167. Public-source single-vault rekey order under injected exceptions.
(declare-const recovery_write_ok Bool)
(declare-const primary_purge_ok Bool)
(declare-const replacement_write_ok Bool)
(declare-const recovery_cleanup_ok Bool)
(declare-const primary_old_after Bool)
(declare-const primary_new_after Bool)
(declare-const recovery_old_after Bool)
(declare-const operation_success Bool)

; A phase failure stops the source method through its exception boundary.
(assert (= primary_old_after (or (not recovery_write_ok) (and recovery_write_ok (not primary_purge_ok)))))
(assert (= primary_new_after (and recovery_write_ok primary_purge_ok replacement_write_ok)))
(assert (= recovery_old_after
  (and recovery_write_ok
       (or (not primary_purge_ok)
           (not replacement_write_ok)
           (not recovery_cleanup_ok)))))
(assert (= operation_success
  (and recovery_write_ok primary_purge_ok replacement_write_ok recovery_cleanup_ok)))

; A reported success leaves exactly the new primary and no old-key recovery.
(push)
(assert (not (=> operation_success
  (and primary_new_after (not primary_old_after) (not recovery_old_after)))))
(check-sat)
(pop)

; Replacement failure after a successful snapshot and purge leaves old-key recovery.
(push)
(assert (not (=> (and recovery_write_ok primary_purge_ok (not replacement_write_ok))
  (and (not primary_old_after) (not primary_new_after) recovery_old_after (not operation_success)))))
(check-sat)
(pop)

; Cleanup failure after replacement leaves both new-primary and old-key recovery,
; and cannot be reported as successful.
(push)
(assert (not (=> (and recovery_write_ok primary_purge_ok replacement_write_ok (not recovery_cleanup_ok))
  (and primary_new_after recovery_old_after (not operation_success)))))
(check-sat)
(pop)

; Expected cleanup-failure witness. This is a runtime test obligation, not a defect claim.
(push)
(assert recovery_write_ok)
(assert primary_purge_ok)
(assert replacement_write_ok)
(assert (not recovery_cleanup_ok))
(assert primary_new_after)
(assert recovery_old_after)
(assert (not operation_success))
(check-sat)
(pop)
