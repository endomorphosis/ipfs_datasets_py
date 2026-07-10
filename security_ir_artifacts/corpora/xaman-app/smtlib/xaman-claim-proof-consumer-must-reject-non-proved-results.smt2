; task_id: PORTAL-CXTP-069
; schema_version: xaman-smtlib-differential/v1
; claim_id: xaman-claim:proof-consumer-must-reject-non-proved-results
; model_cid: sha256:316ead1268fb192641ece96ef255e92922b93623d6f4b1057dc56a2cec711c8d
; severity: blocking
; source_status: POLICY_DEFINED_NOT_YET_KERNEL_PROVED
; query_semantics: satisfiable means unresolved assumptions block release
(set-logic QF_LIA)
(declare-const blocking_assumption_count Int)
(declare-const reviewed_counterexample_count Int)
(assert (= blocking_assumption_count 1))
(assert (>= reviewed_counterexample_count 0))
(assert (>= blocking_assumption_count 1))
(check-sat)
