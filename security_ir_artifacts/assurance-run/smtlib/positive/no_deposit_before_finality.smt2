; crypto-exchange SMT-LIB2 artifact
; cxtp.schema_version: crypto-exchange-smtlib/v1
; cxtp.model_id: minimal-btc-exchange
; cxtp.model_cid: bafkreics22k4sezd6maidggz5ohuxu4kkyvazwl62wetygtpe5jeiswbz4
; cxtp.claim_id: no_deposit_before_finality
; cxtp.claim_version: 1.0
; cxtp.modeled: true
; cxtp.metadata: {"assertion_count":6,"claim_description":"Deposits are credited only after finality is reached.","claim_id":"no_deposit_before_finality","claim_version":"1.0","compiler_artifact":{"deposit_ids":[],"kind":"deposit_policy","offending_ids":[],"txids":[],"violating_event_ids":[],"violations":[]},"compiler_artifact_cid":"bafkreib676kpvtfbnt5675ihws7tecq7oa2ou3wgrr5k2a63pos4rox62a","evidence_refs":[{"kind":"test_fixture","line_end":65,"line_start":55,"notes":"Fixture deposit finality policy.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":77,"line_start":66,"notes":"Fixture deposit credited trace.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":77,"line_start":66,"notes":"Fixture deposit observed trace.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":77,"line_start":66,"notes":"Fixture deposit finalized trace.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"}],"logic":"QF_LIA","model_cid":"bafkreics22k4sezd6maidggz5ohuxu4kkyvazwl62wetygtpe5jeiswbz4","model_id":"minimal-btc-exchange","model_schema_version":"security-model-ir/v1","modeled":true,"not_modeled_reason":null,"query_kind":"violation_satisfiability","required_assumptions":["A6","A9"],"schema_version":"crypto-exchange-smtlib/v1","severity":"high","soundness_notes":[],"violation_scope_explanation":"Each credited deposit must have matching observed/finalized events and survive modeled reorg checks."}
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
 (= deposit_0_finalized_ok true))
(assert
 (= deposit_0_confirmation_ok true))
(assert
 (= deposit_0_finalized_before_credit true))
(assert
 (= deposit_0_domain_fields_ok true))
(assert
 (= deposit_0_reorg_ok true))
(assert
 (let (($x44 (and deposit_0_observed_ok deposit_0_finalized_ok deposit_0_confirmation_ok deposit_0_finalized_before_credit deposit_0_domain_fields_ok deposit_0_reorg_ok)))
(let (($x45 (and $x44)))
(not $x45))))
(check-sat)
