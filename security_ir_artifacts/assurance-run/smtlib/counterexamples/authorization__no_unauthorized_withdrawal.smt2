; crypto-exchange SMT-LIB2 artifact
; cxtp.schema_version: crypto-exchange-smtlib/v1
; cxtp.model_id: minimal-btc-exchange
; cxtp.model_cid: bafkreibg2qtsfuh7ptgjetiiqf5ycgrvasfyfya6sreb3o44ivtij7swvi
; cxtp.claim_id: no_unauthorized_withdrawal
; cxtp.claim_version: 1.0
; cxtp.modeled: true
; cxtp.metadata: {"assertion_count":8,"claim_description":"No withdrawal broadcast occurs without authorization.","claim_id":"no_unauthorized_withdrawal","claim_version":"1.0","compiler_artifact":{"kind":"withdrawal_policy","violating_event_ids":["event:withdrawal_broadcast:1"],"violating_withdrawals":["withdrawal:1"],"violations":[{"conditions":{"approval_before_broadcast":false,"approval_wallet_matches":false,"has_approval":false,"has_request":true,"nonce_ok":true,"not_frozen":true,"request_wallet_matches":true,"reservation_ok":true},"event_id":"event:withdrawal_broadcast:1","wallet_id":"wallet:user_alice","withdrawal_id":"withdrawal:1"}],"wallet_ids":["wallet:user_alice"],"withdrawal_ids":["withdrawal:1"]},"compiler_artifact_cid":"bafkreigyfxgzju6e3fzl5te55j2kog24igod2dtqjddlv7ai452sqag4xa","evidence_refs":[{"kind":"test_fixture","line_end":65,"line_start":55,"notes":"Fixture authorization policy.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":65,"line_start":55,"notes":"Fixture nonce freshness policy.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":65,"line_start":55,"notes":"Fixture balance policy.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":65,"line_start":55,"notes":"Fixture wallet freeze policy.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":77,"line_start":66,"notes":"Fixture withdrawal request trace.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":77,"line_start":66,"notes":"Fixture withdrawal broadcast trace.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"}],"logic":"QF_LIA","model_cid":"bafkreibg2qtsfuh7ptgjetiiqf5ycgrvasfyfya6sreb3o44ivtij7swvi","model_id":"minimal-btc-exchange","model_schema_version":"security-model-ir/v1","modeled":true,"not_modeled_reason":null,"query_kind":"violation_satisfiability","required_assumptions":["A3","A4","A5","A8"],"schema_version":"crypto-exchange-smtlib/v1","severity":"blocking","soundness_notes":[],"violation_scope_explanation":"Each broadcast must be justified by prior request/approval and unfrozen wallet state."}
(set-info :smt-lib-version 2.6)
(set-info :source "ipfs_datasets_py crypto_exchange SMT-LIB2 compiler")
(set-logic QF_LIA)
(declare-fun withdrawal_0_has_request () Bool)
(declare-fun withdrawal_0_has_approval () Bool)
(declare-fun withdrawal_0_approval_before_broadcast () Bool)
(declare-fun withdrawal_0_request_wallet_matches () Bool)
(declare-fun withdrawal_0_approval_wallet_matches () Bool)
(declare-fun withdrawal_0_not_frozen () Bool)
(declare-fun withdrawal_0_nonce_ok () Bool)
(declare-fun withdrawal_0_reservation_ok () Bool)
(assert
 (= withdrawal_0_has_request true))
(assert
 (= withdrawal_0_has_approval false))
(assert
 (= withdrawal_0_approval_before_broadcast false))
(assert
 (= withdrawal_0_request_wallet_matches true))
(assert
 (= withdrawal_0_approval_wallet_matches false))
(assert
 (= withdrawal_0_not_frozen true))
(assert
 (= withdrawal_0_nonce_ok true))
(assert
 (= withdrawal_0_reservation_ok true))
(assert
 (let (($x21 (and withdrawal_0_has_request withdrawal_0_has_approval withdrawal_0_approval_before_broadcast withdrawal_0_request_wallet_matches withdrawal_0_approval_wallet_matches withdrawal_0_not_frozen withdrawal_0_nonce_ok withdrawal_0_reservation_ok)))
(let (($x22 (and true $x21)))
(not $x22))))
(check-sat)
