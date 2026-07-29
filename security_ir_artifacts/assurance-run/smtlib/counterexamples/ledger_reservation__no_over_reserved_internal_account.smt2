; crypto-exchange SMT-LIB2 artifact
; cxtp.schema_version: crypto-exchange-smtlib/v1
; cxtp.model_id: minimal-btc-exchange
; cxtp.model_cid: bafkreig4ruudcce4dp522n7b6dcneqiliwwbxkdpjpptyx74dfm67ihhki
; cxtp.claim_id: no_over_reserved_internal_account
; cxtp.claim_version: 1.0
; cxtp.modeled: true
; cxtp.metadata: {"assertion_count":3,"claim_description":"No internal account is over-reserved.","claim_id":"no_over_reserved_internal_account","claim_version":"1.0","compiler_artifact":{"account_ids":["account:alice_btc"],"kind":"internal_account_reservations","overdrawn_accounts":["account:alice_btc"],"violations":[{"account_id":"account:alice_btc","reason":"over-reserved"}]},"compiler_artifact_cid":"bafkreidtcz3vndlbk65hpdcwplukkbdl4k5cy4yam7w7fxqifvre7fa4gu","evidence_refs":[{"kind":"test_fixture","line_end":65,"line_start":55,"notes":"Fixture atomic reservation policy.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":129,"line_start":8,"notes":"Fixture account balance and reservations.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"}],"logic":"QF_LIA","model_cid":"bafkreig4ruudcce4dp522n7b6dcneqiliwwbxkdpjpptyx74dfm67ihhki","model_id":"minimal-btc-exchange","model_schema_version":"security-model-ir/v1","modeled":true,"not_modeled_reason":null,"query_kind":"violation_satisfiability","required_assumptions":["A4","A5"],"schema_version":"crypto-exchange-smtlib/v1","severity":"blocking","soundness_notes":[],"violation_scope_explanation":"Each account balance/reservation tuple is checked independently."}
(set-info :smt-lib-version 2.6)
(set-info :source "ipfs_datasets_py crypto_exchange SMT-LIB2 compiler")
(set-logic QF_LIA)
(declare-fun account_balance_0 () Int)
(declare-fun account_0_reservation_0 () Int)
(declare-fun account_0_reservation_1 () Int)
(assert
 (= account_balance_0 5))
(assert
 (= account_0_reservation_0 4))
(assert
 (= account_0_reservation_1 4))
(assert
 (let (($x67 (<= (+ account_0_reservation_0 account_0_reservation_1) account_balance_0)))
(let (($x43 (>= account_0_reservation_1 0)))
(let (($x69 (>= account_0_reservation_0 0)))
(let (($x47 (>= account_balance_0 0)))
(let (($x44 (and true (and $x47 $x69 $x43 $x67))))
(not $x44)))))))
(check-sat)
