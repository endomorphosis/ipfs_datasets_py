; crypto-exchange SMT-LIB2 artifact
; cxtp.schema_version: crypto-exchange-smtlib/v1
; cxtp.model_id: minimal-btc-exchange
; cxtp.model_cid: bafkreigddzjxlp6ovzkx4gtmu2gip6lkb5eglhdtifj4xwkxnyetzgqiyi
; cxtp.claim_id: no_deposit_before_finality
; cxtp.claim_version: 1.0
; cxtp.modeled: true
; cxtp.metadata: {"assertion_count":6,"claim_description":"Deposits are credited only after finality is reached.","claim_id":"no_deposit_before_finality","claim_version":"1.0","compiler_artifact":{"deposit_ids":["deposit:1"],"kind":"deposit_policy","offending_ids":["deposit:1"],"txids":["tx:1"],"violating_event_ids":["event:deposit_credited:1"],"violations":[{"conditions":{"confirmation_ok":false,"domain_fields_ok":true,"finalized_before_credit":false,"finalized_ok":false,"observed_ok":true,"reorg_ok":true},"deposit_id":"deposit:1","event_id":"event:deposit_credited:1","txid":"tx:1"}]},"compiler_artifact_cid":"bafkreihfujnsk7sgap46jqebkoglib6vbhve67momgaxx7gtmvhkbmgztm","evidence_refs":[{"kind":"test_fixture","line_end":65,"line_start":55,"notes":"Fixture deposit finality policy.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":77,"line_start":66,"notes":"Fixture deposit credited trace.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":77,"line_start":66,"notes":"Fixture deposit observed trace.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"}],"logic":"QF_LIA","model_cid":"bafkreigddzjxlp6ovzkx4gtmu2gip6lkb5eglhdtifj4xwkxnyetzgqiyi","model_id":"minimal-btc-exchange","model_schema_version":"security-model-ir/v1","modeled":true,"not_modeled_reason":null,"query_kind":"violation_satisfiability","required_assumptions":["A6","A9"],"schema_version":"crypto-exchange-smtlib/v1","severity":"high","soundness_notes":[],"violation_scope_explanation":"Each credited deposit must have matching observed/finalized events and survive modeled reorg checks."}
(set-info :smt-lib-version 2.6)
(set-info :source "ipfs_datasets_py crypto_exchange SMT-LIB2 compiler")
(set-logic QF_LIA)
(declare-fun deposit_0_observed_ok () Bool)
(declare-fun deposit_0_finalized_ok () Bool)
(declare-fun deposit_0_confirmation_ok () Bool)
(declare-fun deposit_0_finalized_before_credit () Bool)
(declare-fun deposit_0_domain_fields_ok () Bool)
(declare-fun deposit_0_reorg_ok () Bool)
(assert
 (= deposit_0_observed_ok true))
(assert
 (= deposit_0_finalized_ok false))
(assert
 (= deposit_0_confirmation_ok false))
(assert
 (= deposit_0_finalized_before_credit false))
(assert
 (= deposit_0_domain_fields_ok true))
(assert
 (= deposit_0_reorg_ok true))
(assert
 (let (($x60 (and deposit_0_observed_ok deposit_0_finalized_ok deposit_0_confirmation_ok deposit_0_finalized_before_credit deposit_0_domain_fields_ok deposit_0_reorg_ok)))
(let (($x46 (and $x60)))
(not $x46))))
(check-sat)
