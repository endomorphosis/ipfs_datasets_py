; crypto-exchange SMT-LIB2 artifact
; cxtp.schema_version: crypto-exchange-smtlib/v1
; cxtp.model_id: minimal-btc-exchange
; cxtp.model_cid: bafkreigcfb6zychlb3bg6ofwcco6otshdrxl2htbrqwr76suszz7juozxi
; cxtp.claim_id: no_signing_request_after_wallet_freeze
; cxtp.claim_version: 1.0
; cxtp.modeled: true
; cxtp.metadata: {"assertion_count":6,"claim_description":"No signing request after wallet freeze.","claim_id":"no_signing_request_after_wallet_freeze","claim_version":"1.0","compiler_artifact":{"kind":"hsm_freeze_policy","violating_event_ids":["event:signing_request:after_freeze"],"violations":[{"conditions":{"not_frozen":false,"transaction_reference":true,"wallet_exists":true},"event_id":"event:signing_request:after_freeze","wallet_id":"wallet:user_alice"}],"wallet_ids":["wallet:user_alice"]},"compiler_artifact_cid":"bafkreia7xq6elh7jjc3kgow4mo654ma75f57bfcxlgrazbg6ymghu6tsy4","evidence_refs":[{"kind":"test_fixture","line_end":65,"line_start":55,"notes":"Fixture wallet freeze policy.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":77,"line_start":66,"notes":"Fixture wallet freeze trace.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"},{"kind":"test_fixture","line_end":77,"line_start":66,"notes":"Fixture signing request trace.","path":"ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py","review_status":"trusted_fixture"}],"logic":"QF_LIA","model_cid":"bafkreigcfb6zychlb3bg6ofwcco6otshdrxl2htbrqwr76suszz7juozxi","model_id":"minimal-btc-exchange","model_schema_version":"security-model-ir/v1","modeled":true,"not_modeled_reason":null,"query_kind":"violation_satisfiability","required_assumptions":["A3","A8"],"schema_version":"crypto-exchange-smtlib/v1","severity":"high","soundness_notes":["Signing request evidence is incomplete; attach HSM or key-manager evidence before production proof use."],"violation_scope_explanation":"Each signing request is checked against modeled freeze/unfreeze history."}
(set-info :smt-lib-version 2.6)
(set-info :source "ipfs_datasets_py crypto_exchange SMT-LIB2 compiler")
(set-logic QF_LIA)
(declare-fun signing_0_wallet_exists () Bool)
(declare-fun signing_0_not_frozen () Bool)
(declare-fun signing_0_transaction_reference () Bool)
(declare-fun signing_1_wallet_exists () Bool)
(declare-fun signing_1_not_frozen () Bool)
(declare-fun signing_1_transaction_reference () Bool)
(assert
 (= signing_0_wallet_exists true))
(assert
 (= signing_0_not_frozen true))
(assert
 (= signing_0_transaction_reference true))
(assert
 (= signing_1_wallet_exists true))
(assert
 (= signing_1_not_frozen false))
(assert
 (= signing_1_transaction_reference true))
(assert
 (let (($x45 (and signing_1_wallet_exists signing_1_not_frozen signing_1_transaction_reference)))
(let (($x30 (and signing_0_wallet_exists signing_0_not_frozen signing_0_transaction_reference)))
(let (($x57 (and $x30 $x45)))
(not $x57)))))
(check-sat)
