; crypto-exchange SMT-LIB2 artifact
; cxtp.schema_version: crypto-exchange-smtlib/v1
; cxtp.model_id: minimal-btc-exchange
; cxtp.model_cid: bafkreifrd5ui2m2bmtyckteyyrkqez6od5plcgr447t46mfbmbqwclavia
; cxtp.claim_id: capability_delegation_no_authority_increase
; cxtp.claim_version: 1.0
; cxtp.modeled: true
; cxtp.metadata: {"assertion_count":7,"claim_description":"Capability delegation cannot increase authority.","claim_id":"capability_delegation_no_authority_increase","claim_version":"1.0","compiler_artifact":{"capability_ids":["cap:withdraw:user_alice"],"kind":"capability_delegation","violations":[{"capability_id":"cap:withdraw:user_alice","conditions":{"actions_ok":true,"authority_ok":false,"caveats_ok":true,"expiry_ok":true,"parent_active":true,"parent_exists":true,"resources_ok":true}}]},"compiler_artifact_cid":"bafkreicud4j6ootdax2ijsuay6mawh33bx56lcagpr27aw3zupajoggggm","evidence_refs":[{"kind":"test_fixture","line_end":65,"line_start":55,"notes":"Fixture delegation monotonicity policy.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":54,"line_start":45,"notes":"Fixture capability chain.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"}],"logic":"QF_LIA","model_cid":"bafkreifrd5ui2m2bmtyckteyyrkqez6od5plcgr447t46mfbmbqwclavia","model_id":"minimal-btc-exchange","model_schema_version":"security-model-ir/v1","modeled":true,"not_modeled_reason":null,"query_kind":"violation_satisfiability","required_assumptions":["A1","A7"],"schema_version":"crypto-exchange-smtlib/v1","severity":"high","soundness_notes":[],"violation_scope_explanation":"Each delegated capability is constrained by the modeled parent scope."}
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
 (= capability_0_authority_ok false))
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
 (let (($x49 (and capability_0_authority_ok capability_0_parent_exists capability_0_actions_ok capability_0_resources_ok capability_0_caveats_ok capability_0_expiry_ok capability_0_parent_active)))
(let (($x60 (and $x49)))
(not $x60))))
(check-sat)
