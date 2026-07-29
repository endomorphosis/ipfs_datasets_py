; crypto-exchange SMT-LIB2 artifact
; cxtp.schema_version: crypto-exchange-smtlib/v1
; cxtp.model_id: minimal-btc-exchange
; cxtp.model_cid: bafkreics22k4sezd6maidggz5ohuxu4kkyvazwl62wetygtpe5jeiswbz4
; cxtp.claim_id: capability_delegation_no_authority_increase
; cxtp.claim_version: 1.0
; cxtp.modeled: true
; cxtp.metadata: {"assertion_count":7,"claim_description":"Capability delegation cannot increase authority.","claim_id":"capability_delegation_no_authority_increase","claim_version":"1.0","compiler_artifact":{"capability_ids":[],"kind":"capability_delegation","violations":[]},"compiler_artifact_cid":"bafkreiazyraphzvs76kvto7tmli22yxorz2fo7lgghkxtptu4n3bb57bsi","evidence_refs":[{"kind":"test_fixture","line_end":65,"line_start":55,"notes":"Fixture delegation monotonicity policy.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":54,"line_start":45,"notes":"Fixture capability chain.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"}],"logic":"QF_LIA","model_cid":"bafkreics22k4sezd6maidggz5ohuxu4kkyvazwl62wetygtpe5jeiswbz4","model_id":"minimal-btc-exchange","model_schema_version":"security-model-ir/v1","modeled":true,"not_modeled_reason":null,"query_kind":"violation_satisfiability","required_assumptions":["A1","A7"],"schema_version":"crypto-exchange-smtlib/v1","severity":"high","soundness_notes":[],"violation_scope_explanation":"Each delegated capability is constrained by the modeled parent scope."}
(set-info :smt-lib-version 2.6)
(set-info :source "ipfs_datasets_py crypto_exchange SMT-LIB2 compiler")
(set-logic QF_LIA)
(declare-fun capability_0_authority_ok () Bool)
(declare-fun capability_0_parent_exists () Bool)
(declare-fun capability_0_actions_ok () Bool)
(declare-fun capability_0_resources_ok () Bool)
(declare-fun capability_0_caveats_ok () Bool)
(declare-fun capability_0_expiry_ok () Bool)
(declare-fun capability_0_parent_active () Bool)
(assert
 (= capability_0_authority_ok true))
(assert
 (= capability_0_parent_exists true))
(assert
 (= capability_0_actions_ok true))
(assert
 (= capability_0_resources_ok true))
(assert
 (= capability_0_caveats_ok true))
(assert
 (= capability_0_expiry_ok true))
(assert
 (= capability_0_parent_active true))
(assert
 (let (($x65 (and capability_0_authority_ok capability_0_parent_exists capability_0_actions_ok capability_0_resources_ok capability_0_caveats_ok capability_0_expiry_ok capability_0_parent_active)))
(let (($x66 (and $x65)))
(not $x66))))
(check-sat)
