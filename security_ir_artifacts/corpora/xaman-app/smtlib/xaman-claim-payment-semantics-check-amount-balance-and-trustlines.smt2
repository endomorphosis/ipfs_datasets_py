; task_id: PORTAL-CXTP-069
; schema_version: xaman-smtlib-differential/v1
; claim_id: xaman-claim:payment-semantics-check-amount-balance-and-trustlines
; model_cid: sha256:316ead1268fb192641ece96ef255e92922b93623d6f4b1057dc56a2cec711c8d
; severity: high
; source_status: SUPPORTED_FOR_PAYMENT_WITH_ASSUMPTIONS
; query_semantics: satisfiable means unresolved assumptions block release
(set-logic QF_LIA)
(declare-const blocking_assumption_count Int)
(declare-const reviewed_counterexample_count Int)
(assert (= blocking_assumption_count 2))
(assert (>= reviewed_counterexample_count 0))
(assert (>= blocking_assumption_count 1))
(check-sat)
