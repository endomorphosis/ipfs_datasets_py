; crypto-exchange SMT-LIB2 artifact
; cxtp.schema_version: crypto-exchange-smtlib/v1
; cxtp.model_id: minimal-btc-exchange
; cxtp.model_cid: bafkreics22k4sezd6maidggz5ohuxu4kkyvazwl62wetygtpe5jeiswbz4
; cxtp.claim_id: revoked_capability_no_future_authorization
; cxtp.claim_version: 1.0
; cxtp.modeled: true
; cxtp.metadata: {"assertion_count":1,"claim_description":"Revoked capability cannot authorize future action.","claim_id":"revoked_capability_no_future_authorization","claim_version":"1.0","compiler_artifact":{"capability_ids":[],"kind":"capability_revocation","violating_event_ids":[],"violations":[]},"compiler_artifact_cid":"bafkreiejak3xmoazuivo5ar5szfonxaxxut56owzbwm3cu6loireynlx3i","evidence_refs":[{"kind":"test_fixture","line_end":65,"line_start":55,"notes":"Fixture capability revocation policy.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":77,"line_start":66,"notes":"Fixture privileged action trace.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":77,"line_start":66,"notes":"Fixture capability revocation trace.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":54,"line_start":45,"notes":"Fixture capability chain.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"}],"logic":"QF_LIA","model_cid":"bafkreics22k4sezd6maidggz5ohuxu4kkyvazwl62wetygtpe5jeiswbz4","model_id":"minimal-btc-exchange","model_schema_version":"security-model-ir/v1","modeled":true,"not_modeled_reason":null,"query_kind":"violation_satisfiability","required_assumptions":["A10"],"schema_version":"crypto-exchange-smtlib/v1","severity":"high","soundness_notes":[],"violation_scope_explanation":"Each privileged action must occur before revocation or after explicit reinstatement."}
(set-info :smt-lib-version 2.6)
(set-info :source "ipfs_datasets_py crypto_exchange SMT-LIB2 compiler")
(set-logic QF_LIA)
(declare-fun revocation_0_not_revoked () Bool)
(assert
 (= revocation_0_not_revoked true))
(assert
 (let (($x70 (and true revocation_0_not_revoked)))
(not $x70)))
(check-sat)
