; crypto-exchange SMT-LIB2 artifact
; cxtp.schema_version: crypto-exchange-smtlib/v1
; cxtp.model_id: minimal-btc-exchange
; cxtp.model_cid: bafkreics22k4sezd6maidggz5ohuxu4kkyvazwl62wetygtpe5jeiswbz4
; cxtp.claim_id: global_asset_conservation
; cxtp.claim_version: 1.0
; cxtp.modeled: true
; cxtp.metadata: {"assertion_count":4,"claim_description":"Global asset liabilities are covered by custody assets.","claim_id":"global_asset_conservation","claim_version":"1.0","compiler_artifact":{"asset_ids":["asset:btc"],"kind":"global_asset_conservation","violations":[]},"compiler_artifact_cid":"bafkreifrkxyregy4ycgj5cthivxgzib2zky2eeqqlht6cvwpd7jil7yxc4","evidence_refs":[{"kind":"test_fixture","line_end":129,"line_start":8,"notes":"Fixture account balance and reservations.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":150,"line_start":132,"notes":"Fixture ledger totals for global conservation.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"}],"logic":"QF_LIA","model_cid":"bafkreics22k4sezd6maidggz5ohuxu4kkyvazwl62wetygtpe5jeiswbz4","model_id":"minimal-btc-exchange","model_schema_version":"security-model-ir/v1","modeled":true,"not_modeled_reason":null,"query_kind":"violation_satisfiability","required_assumptions":["A4","A10"],"schema_version":"crypto-exchange-smtlib/v1","severity":"blocking","soundness_notes":[],"violation_scope_explanation":"Each modeled asset bucket is constrained independently."}
(set-info :smt-lib-version 2.6)
(set-info :source "ipfs_datasets_py crypto_exchange SMT-LIB2 compiler")
(set-logic QF_LIA)
(declare-fun liability_0 () Int)
(declare-fun available_0 () Int)
(assert
 (= liability_0 5))
(assert
 (= available_0 5))
(assert
 (>= liability_0 0))
(assert
 (>= available_0 0))
(assert
 (let (($x64 (and (<= liability_0 available_0))))
(not $x64)))
(check-sat)
