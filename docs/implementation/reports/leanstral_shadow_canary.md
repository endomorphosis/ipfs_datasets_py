# Leanstral Shadow Canary

- Schema: `legal-ir-leanstral-shadow-canary-v1`
- Mode: `dry-run`
- Selected clusters: 17 of 50 source records
- Runtime seconds: 0.013056
- Promotion allowed: `false`
- Promotion blockers: `dry_run_no_promotion`, `verifier_guardrail_not_satisfied`

## Cache Use
- `cache_hits`: 0
- `cache_misses`: 17
- `llm_calls`: 0
- `requests`: 17

## Audit Validity
- `invalid`: 17
- `valid`: 0
- `verified`: 0

## Theorem Outcomes
- `local_checks`: 0
- `proof_route_attempted`: 214
- `proof_route_failures`: 21
- `proof_route_valid`: 193

## Disagreement Categories
- `compiler_component_gap`: 8
- `deadline_order`: 1
- `decompiler`: 3
- `deontic`: 2
- `deontic.ir`: 2
- `deontic_ir_obligation_scope`: 1
- `edge_role`: 1
- `event_calculus`: 2
- `event_calculus.core`: 2
- `event_calculus_core_fluent_interval`: 1
- `exception_reconstruction`: 1
- `external_provers.router`: 3
- `external_provers_router_proof_route_failure_ratio`: 1
- `fluent_interval`: 1
- `formal_prover_gap`: 1
- `frame_logic`: 2
- `knowledge_graph`: 1
- `knowledge_graphs.neo4j_compat`: 1
- `knowledge_graphs_neo4j_compat_edge_role`: 1
- `modal.frame_logic`: 2
- `modal.ir_decompiler`: 3
- `modal.source_provenance`: 2
- `modal.temporal`: 2
- `modal_frame_logic_slot_alignment`: 1
- `modal_ir_decompiler_exception_reconstruction`: 1
- `modal_source_provenance_source_span_hash`: 1
- `modal_temporal_deadline_order`: 1
- `obligation_scope`: 1
- `proof_route_failure_ratio`: 2
- `provenance`: 2
- `prover`: 3
- `slot_alignment`: 1
- `source_span_hash`: 1
- `synthesis_focus_gap`: 8
- `temporal`: 2

## Projected TODO Specificity
- `complete_count`: 17.0
- `mean`: 1.0
- `min`: 1.0

## Estimated Compiler Impact
- `mean_promotion_value`: 0.7006279179813166
- `top_promotion_value`: 0.8369398606333294
- `total_projected_impact`: 11.910674605682383

## No-Mutation Contract
- `mode`: "shadow"
- `queue_seeded_count`: 0
- `report_only`: true
- `source_mutation_count`: 0
- `source_mutation_detected`: false
- `todo_queue_seeded`: false

## Cluster Audits

### 1. `lir-cluster-b7b8d4c828f548d2`
- Surface: `external_provers.router`
- Family: `prover`
- Signature: `prover:formal_prover_gap:prover->temporal:route_failure_ratio`
- Score: 0.909571; recurrence: 7; held-out impact: 0.875000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `repair_multiview_legal_ir_prover_gate` on `external_provers.router`; specificity 1.000

### 2. `lir-cluster-fda24c331480bfd5`
- Surface: `deontic.ir`
- Family: `deontic`
- Signature: `deontic:compiler_component_gap:deontic->temporal:obligation_scope`
- Score: 0.906186; recurrence: 7; held-out impact: 0.920000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `repair_deontic_bridge_quality_gate` on `deontic.ir`; specificity 1.000

### 3. `lir-cluster-e77b0212bdc71365`
- Surface: `external_provers.router`
- Family: `prover`
- Signature: `prover:compiler_component_gap:prover->temporal:failure_ratio`
- Score: 0.897571; recurrence: 7; held-out impact: 0.875000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `repair_multiview_legal_ir_prover_gate` on `external_provers.router`; specificity 1.000

### 4. `lir-cluster-93f402990b1ef2ae`
- Surface: `external_provers.router`
- Family: `prover`
- Signature: `prover:synthesis_focus_gap:prover->temporal:failure_ratio`
- Score: 0.887071; recurrence: 7; held-out impact: 0.875000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `repair_multiview_legal_ir_prover_gate` on `external_provers.router`; specificity 1.000

### 5. `lir-cluster-a3d46a0b4e660b31`
- Surface: `deontic.ir`
- Family: `deontic`
- Signature: `deontic:synthesis_focus_gap:deontic->temporal:obligation_scope`
- Score: 0.879786; recurrence: 7; held-out impact: 0.920000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `repair_deontic_bridge_quality_gate` on `deontic.ir`; specificity 1.000

### 6. `lir-cluster-b0027d88d32c370c`
- Surface: `knowledge_graphs.neo4j_compat`
- Family: `knowledge_graph`
- Signature: `knowledge_graph:compiler_component_gap:knowledge_graph->temporal:edge_role`
- Score: 0.835090; recurrence: 6; held-out impact: 0.830000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `repair_multiview_legal_ir_graph_projection` on `knowledge_graphs.neo4j_compat`; specificity 1.000

### 7. `lir-cluster-88aa05896b838237`
- Surface: `modal.ir_decompiler`
- Family: `decompiler`
- Signature: `decompiler:compiler_component_gap:decompiler->temporal:exception_reconstruction`
- Score: 0.817857; recurrence: 6; held-out impact: 0.785000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `refine_semantic_decompiler_reconstruction` on `modal.ir_decompiler`; specificity 1.000

### 8. `lir-cluster-69178b0535c6715b`
- Surface: `modal.temporal`
- Family: `temporal`
- Signature: `temporal:compiler_component_gap:temporal->deontic:deadline_order`
- Score: 0.800624; recurrence: 6; held-out impact: 0.740000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `review_temporal_legal_ir_gap` on `modal.temporal`; specificity 1.000

### 9. `lir-cluster-cf80aaaa4a36e04c`
- Surface: `modal.source_provenance`
- Family: `provenance`
- Signature: `provenance:compiler_component_gap:provenance->temporal:span_hash`
- Score: 0.783390; recurrence: 6; held-out impact: 0.695000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `review_provenance_legal_ir_gap` on `modal.source_provenance`; specificity 1.000

### 10. `lir-cluster-a0a56d8aa4be53ad`
- Surface: `modal.frame_logic`
- Family: `frame_logic`
- Signature: `frame_logic:compiler_component_gap:frame_logic->temporal:slot_alignment`
- Score: 0.766157; recurrence: 6; held-out impact: 0.650000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `repair_flogic_ontology_constraints` on `modal.frame_logic`; specificity 1.000

### 11. `lir-cluster-e3376de9831c9b6a`
- Surface: `modal.source_provenance`
- Family: `provenance`
- Signature: `provenance:synthesis_focus_gap:provenance->temporal:span_hash`
- Score: 0.756690; recurrence: 6; held-out impact: 0.695000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `review_provenance_legal_ir_gap` on `modal.source_provenance`; specificity 1.000

### 12. `lir-cluster-9a43ab36085df1d5`
- Surface: `modal.temporal`
- Family: `temporal`
- Signature: `temporal:synthesis_focus_gap:temporal->deontic:deadline_order`
- Score: 0.756224; recurrence: 6; held-out impact: 0.740000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `review_temporal_legal_ir_gap` on `modal.temporal`; specificity 1.000

### 13. `lir-cluster-2d56b69fde9d6c95`
- Surface: `event_calculus.core`
- Family: `event_calculus`
- Signature: `event_calculus:compiler_component_gap:event_calculus->temporal:fluent_interval`
- Score: 0.748924; recurrence: 6; held-out impact: 0.605000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `review_event_calculus_legal_ir_gap` on `event_calculus.core`; specificity 1.000

### 14. `lir-cluster-21f7acdf151dae44`
- Surface: `modal.ir_decompiler`
- Family: `decompiler`
- Signature: `decompiler:synthesis_focus_gap:decompiler->temporal:exception_reconstruction`
- Score: 0.748557; recurrence: 6; held-out impact: 0.785000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `refine_semantic_decompiler_reconstruction` on `modal.ir_decompiler`; specificity 1.000

### 15. `lir-cluster-c9a27eef5b51ab45`
- Surface: `modal.frame_logic`
- Family: `frame_logic`
- Signature: `frame_logic:synthesis_focus_gap:frame_logic->temporal:slot_alignment`
- Score: 0.713957; recurrence: 6; held-out impact: 0.650000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `repair_flogic_ontology_constraints` on `modal.frame_logic`; specificity 1.000

### 16. `lir-cluster-da997b075ca29f68`
- Surface: `event_calculus.core`
- Family: `event_calculus`
- Signature: `event_calculus:synthesis_focus_gap:event_calculus->temporal:fluent_interval`
- Score: 0.707224; recurrence: 6; held-out impact: 0.605000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `review_event_calculus_legal_ir_gap` on `event_calculus.core`; specificity 1.000

### 17. `lir-cluster-ab8b1a66a330f3c3`
- Surface: `modal.ir_decompiler`
- Family: `decompiler`
- Signature: `decompiler:synthesis_focus_gap:knowledge_graph->temporal:edge_role`
- Score: 0.467290; recurrence: 6; held-out impact: 0.000000
- Cache hit: `false`; LLM called: `false`
- Audit valid: `false`; verified: `false`
- Guardrails: `failed:verifier`
- Projected TODO: `refine_semantic_decompiler_reconstruction` on `modal.ir_decompiler`; specificity 1.000

## Machine Readable Summary

```json
{
  "analysis_error": "",
  "audit_validity": {
    "invalid": 17,
    "valid": 0,
    "verified": 0
  },
  "audits": [
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-b7b8d4c828f548d2",
      "compiler_surface": "external_provers.router",
      "confidence": 0.622857,
      "disagreement_categories": [
        "external_provers.router",
        "formal_prover_gap",
        "proof_route_failure_ratio",
        "prover"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.875,
        "promotion_value": 0.817875,
        "rank_score": 0.909571,
        "recurrence_norm": 0.528874
      },
      "formal_severity": 1.0,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.875,
      "llm_called": false,
      "projected_todo": {
        "action": "repair_multiview_legal_ir_prover_gate",
        "allowed_paths": [
          "ipfs_datasets_py/optimizers/logic_theorem_optimizer/prover_integration.py",
          "ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py"
        ],
        "dedup_key": "leanstral-shadow-4bd261e4d8679d16",
        "missing_axes": [],
        "mutation_cases": [
          "unsupported_modal_system"
        ],
        "specificity_score": 1.0,
        "target_component": "external_provers.router",
        "target_metrics": [
          "legal_ir_multiview_proof_failure_ratio"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "proof_route_is_distinct_from_proof"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 1,
      "rank_score": 0.909571,
      "recurrence": 7,
      "request_id": "leanstral-audit-13ceeb6f34699cc9",
      "response_hash": "",
      "semantic_family": "prover",
      "semantic_signature": "prover:formal_prover_gap:prover->temporal:route_failure_ratio",
      "theorem_outcomes": {
        "cluster_formal_severity": 1.0,
        "local_check_count": 0,
        "proof_route_attempted_count": 14,
        "proof_route_failed_records": 7,
        "proof_route_valid_count": 7,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-fda24c331480bfd5",
      "compiler_surface": "deontic.ir",
      "confidence": 0.631429,
      "disagreement_categories": [
        "compiler_component_gap",
        "deontic",
        "deontic.ir",
        "deontic_ir_obligation_scope"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.92,
        "promotion_value": 0.83694,
        "rank_score": 0.906186,
        "recurrence_norm": 0.528874
      },
      "formal_severity": 0.95,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.92,
      "llm_called": false,
      "projected_todo": {
        "action": "repair_deontic_bridge_quality_gate",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/codec.py",
          "ipfs_datasets_py/logic/modal/decompiler.py"
        ],
        "dedup_key": "leanstral-shadow-74fb040347f3c52e",
        "missing_axes": [],
        "mutation_cases": [
          "invert_modality",
          "remove_exception"
        ],
        "specificity_score": 1.0,
        "target_component": "deontic.ir",
        "target_metrics": [
          "deontic_decoder_slot_loss",
          "legal_ir_view_cross_entropy_loss"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "exception_scope_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 2,
      "rank_score": 0.906186,
      "recurrence": 7,
      "request_id": "leanstral-audit-500be289957cd333",
      "response_hash": "",
      "semantic_family": "deontic",
      "semantic_signature": "deontic:compiler_component_gap:deontic->temporal:obligation_scope",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.95,
        "local_check_count": 0,
        "proof_route_attempted_count": 14,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 14,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-e77b0212bdc71365",
      "compiler_surface": "external_provers.router",
      "confidence": 0.622857,
      "disagreement_categories": [
        "compiler_component_gap",
        "external_provers.router",
        "external_provers_router_proof_route_failure_ratio",
        "prover"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.875,
        "promotion_value": 0.813675,
        "rank_score": 0.897571,
        "recurrence_norm": 0.528874
      },
      "formal_severity": 1.0,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.875,
      "llm_called": false,
      "projected_todo": {
        "action": "repair_multiview_legal_ir_prover_gate",
        "allowed_paths": [
          "ipfs_datasets_py/optimizers/logic_theorem_optimizer/prover_integration.py",
          "ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py"
        ],
        "dedup_key": "leanstral-shadow-ce9d53ab33c557a7",
        "missing_axes": [],
        "mutation_cases": [
          "unsupported_modal_system"
        ],
        "specificity_score": 1.0,
        "target_component": "external_provers.router",
        "target_metrics": [
          "legal_ir_multiview_proof_failure_ratio"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "proof_route_is_distinct_from_proof"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 3,
      "rank_score": 0.897571,
      "recurrence": 7,
      "request_id": "leanstral-audit-91de8fe44eac467b",
      "response_hash": "",
      "semantic_family": "prover",
      "semantic_signature": "prover:compiler_component_gap:prover->temporal:failure_ratio",
      "theorem_outcomes": {
        "cluster_formal_severity": 1.0,
        "local_check_count": 0,
        "proof_route_attempted_count": 14,
        "proof_route_failed_records": 7,
        "proof_route_valid_count": 7,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-93f402990b1ef2ae",
      "compiler_surface": "external_provers.router",
      "confidence": 0.622857,
      "disagreement_categories": [
        "external_provers.router",
        "proof_route_failure_ratio",
        "prover",
        "synthesis_focus_gap"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.875,
        "promotion_value": 0.81,
        "rank_score": 0.887071,
        "recurrence_norm": 0.528874
      },
      "formal_severity": 1.0,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.875,
      "llm_called": false,
      "projected_todo": {
        "action": "repair_multiview_legal_ir_prover_gate",
        "allowed_paths": [
          "ipfs_datasets_py/optimizers/logic_theorem_optimizer/prover_integration.py",
          "ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py"
        ],
        "dedup_key": "leanstral-shadow-61039e7425f6da22",
        "missing_axes": [],
        "mutation_cases": [
          "unsupported_modal_system"
        ],
        "specificity_score": 1.0,
        "target_component": "external_provers.router",
        "target_metrics": [
          "legal_ir_multiview_proof_failure_ratio"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "proof_route_is_distinct_from_proof"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 4,
      "rank_score": 0.887071,
      "recurrence": 7,
      "request_id": "leanstral-audit-ed77b5cc6b4b64fc",
      "response_hash": "",
      "semantic_family": "prover",
      "semantic_signature": "prover:synthesis_focus_gap:prover->temporal:failure_ratio",
      "theorem_outcomes": {
        "cluster_formal_severity": 1.0,
        "local_check_count": 0,
        "proof_route_attempted_count": 14,
        "proof_route_failed_records": 7,
        "proof_route_valid_count": 7,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-a3d46a0b4e660b31",
      "compiler_surface": "deontic.ir",
      "confidence": 0.631429,
      "disagreement_categories": [
        "deontic",
        "deontic.ir",
        "obligation_scope",
        "synthesis_focus_gap"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.92,
        "promotion_value": 0.8277,
        "rank_score": 0.879786,
        "recurrence_norm": 0.528874
      },
      "formal_severity": 0.86,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.92,
      "llm_called": false,
      "projected_todo": {
        "action": "repair_deontic_bridge_quality_gate",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/codec.py",
          "ipfs_datasets_py/logic/modal/decompiler.py"
        ],
        "dedup_key": "leanstral-shadow-c7b5d47236779a3a",
        "missing_axes": [],
        "mutation_cases": [
          "invert_modality",
          "remove_exception"
        ],
        "specificity_score": 1.0,
        "target_component": "deontic.ir",
        "target_metrics": [
          "deontic_decoder_slot_loss",
          "legal_ir_view_cross_entropy_loss"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "exception_scope_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 5,
      "rank_score": 0.879786,
      "recurrence": 7,
      "request_id": "leanstral-audit-41b990bbf8fac9c3",
      "response_hash": "",
      "semantic_family": "deontic",
      "semantic_signature": "deontic:synthesis_focus_gap:deontic->temporal:obligation_scope",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.86,
        "local_check_count": 0,
        "proof_route_attempted_count": 14,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 14,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-b0027d88d32c370c",
      "compiler_surface": "knowledge_graphs.neo4j_compat",
      "confidence": 0.626667,
      "disagreement_categories": [
        "compiler_component_gap",
        "knowledge_graph",
        "knowledge_graphs.neo4j_compat",
        "knowledge_graphs_neo4j_compat_edge_role"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.83,
        "promotion_value": 0.764764,
        "rank_score": 0.83509,
        "recurrence_norm": 0.494913
      },
      "formal_severity": 0.95,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.83,
      "llm_called": false,
      "projected_todo": {
        "action": "repair_multiview_legal_ir_graph_projection",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/kg_bridge.py"
        ],
        "dedup_key": "leanstral-shadow-63e71928de616bb7",
        "missing_axes": [],
        "mutation_cases": [
          "remove_relation_endpoint"
        ],
        "specificity_score": 1.0,
        "target_component": "knowledge_graphs.neo4j_compat",
        "target_metrics": [
          "legal_ir_multiview_graph_failure_penalty"
        ],
        "theorem_templates": [
          "graph_has_no_dangling_edges",
          "source_provenance_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 6,
      "rank_score": 0.83509,
      "recurrence": 6,
      "request_id": "leanstral-audit-eaf6119a8d5abbe7",
      "response_hash": "",
      "semantic_family": "knowledge_graph",
      "semantic_signature": "knowledge_graph:compiler_component_gap:knowledge_graph->temporal:edge_role",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.95,
        "local_check_count": 0,
        "proof_route_attempted_count": 12,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 12,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-88aa05896b838237",
      "compiler_surface": "modal.ir_decompiler",
      "confidence": 0.62,
      "disagreement_categories": [
        "compiler_component_gap",
        "decompiler",
        "modal.ir_decompiler",
        "modal_ir_decompiler_exception_reconstruction"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.785,
        "promotion_value": 0.738483,
        "rank_score": 0.817857,
        "recurrence_norm": 0.494913
      },
      "formal_severity": 0.95,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.785,
      "llm_called": false,
      "projected_todo": {
        "action": "refine_semantic_decompiler_reconstruction",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/codec.py",
          "ipfs_datasets_py/logic/modal/decompiler.py"
        ],
        "dedup_key": "leanstral-shadow-d5a29cb2e25c366e",
        "missing_axes": [],
        "mutation_cases": [
          "invert_modality",
          "remove_exception",
          "alter_deadline"
        ],
        "specificity_score": 1.0,
        "target_component": "modal.ir_decompiler",
        "target_metrics": [
          "reconstruction_loss",
          "source_decompiled_text_embedding_cosine_loss",
          "source_decompiled_text_token_loss"
        ],
        "theorem_templates": [
          "decompiler_round_trip",
          "exception_scope_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 7,
      "rank_score": 0.817857,
      "recurrence": 6,
      "request_id": "leanstral-audit-82d0c132a9445c32",
      "response_hash": "",
      "semantic_family": "decompiler",
      "semantic_signature": "decompiler:compiler_component_gap:decompiler->temporal:exception_reconstruction",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.95,
        "local_check_count": 0,
        "proof_route_attempted_count": 12,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 12,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-69178b0535c6715b",
      "compiler_surface": "modal.temporal",
      "confidence": 0.613333,
      "disagreement_categories": [
        "compiler_component_gap",
        "modal.temporal",
        "modal_temporal_deadline_order",
        "temporal"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.74,
        "promotion_value": 0.712201,
        "rank_score": 0.800624,
        "recurrence_norm": 0.494913
      },
      "formal_severity": 0.95,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.74,
      "llm_called": false,
      "projected_todo": {
        "action": "review_temporal_legal_ir_gap",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/codec.py",
          "ipfs_datasets_py/logic/CEC/native/temporal.py",
          "ipfs_datasets_py/logic/TDFOL/inference_rules/temporal.py"
        ],
        "dedup_key": "leanstral-shadow-2f8ea96980ab8bf4",
        "missing_axes": [],
        "mutation_cases": [
          "temporal_semantic_regression"
        ],
        "specificity_score": 1.0,
        "target_component": "modal.temporal",
        "target_metrics": [
          "temporal_heldout_impact"
        ],
        "theorem_templates": [
          "source_provenance_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 8,
      "rank_score": 0.800624,
      "recurrence": 6,
      "request_id": "leanstral-audit-1751f26a79d5243e",
      "response_hash": "",
      "semantic_family": "temporal",
      "semantic_signature": "temporal:compiler_component_gap:temporal->deontic:deadline_order",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.95,
        "local_check_count": 0,
        "proof_route_attempted_count": 12,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 12,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-cf80aaaa4a36e04c",
      "compiler_surface": "modal.source_provenance",
      "confidence": 0.606667,
      "disagreement_categories": [
        "compiler_component_gap",
        "modal.source_provenance",
        "modal_source_provenance_source_span_hash",
        "provenance"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.695,
        "promotion_value": 0.685919,
        "rank_score": 0.78339,
        "recurrence_norm": 0.494913
      },
      "formal_severity": 0.95,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.695,
      "llm_called": false,
      "projected_todo": {
        "action": "review_provenance_legal_ir_gap",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/compiler.py",
          "ipfs_datasets_py/logic/modal/leanstral.py"
        ],
        "dedup_key": "leanstral-shadow-f8fbd85c72add2a5",
        "missing_axes": [],
        "mutation_cases": [
          "provenance_semantic_regression"
        ],
        "specificity_score": 1.0,
        "target_component": "modal.source_provenance",
        "target_metrics": [
          "provenance_heldout_impact"
        ],
        "theorem_templates": [
          "source_provenance_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 9,
      "rank_score": 0.78339,
      "recurrence": 6,
      "request_id": "leanstral-audit-e761d59b49688b1a",
      "response_hash": "",
      "semantic_family": "provenance",
      "semantic_signature": "provenance:compiler_component_gap:provenance->temporal:span_hash",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.95,
        "local_check_count": 0,
        "proof_route_attempted_count": 12,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 12,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-a0a56d8aa4be53ad",
      "compiler_surface": "modal.frame_logic",
      "confidence": 0.6,
      "disagreement_categories": [
        "compiler_component_gap",
        "frame_logic",
        "modal.frame_logic",
        "modal_frame_logic_slot_alignment"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.65,
        "promotion_value": 0.659638,
        "rank_score": 0.766157,
        "recurrence_norm": 0.494913
      },
      "formal_severity": 0.95,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.65,
      "llm_called": false,
      "projected_todo": {
        "action": "repair_flogic_ontology_constraints",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/kg_bridge.py"
        ],
        "dedup_key": "leanstral-shadow-4c347374e2bf63d0",
        "missing_axes": [],
        "mutation_cases": [
          "remove_frame_relation",
          "alter_scope"
        ],
        "specificity_score": 1.0,
        "target_component": "modal.frame_logic",
        "target_metrics": [
          "flogic_similarity_loss",
          "legal_ir_view_cross_entropy_loss"
        ],
        "theorem_templates": [
          "source_provenance_preserved",
          "frame_terms_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 10,
      "rank_score": 0.766157,
      "recurrence": 6,
      "request_id": "leanstral-audit-ed7cb28f5ca09f6c",
      "response_hash": "",
      "semantic_family": "frame_logic",
      "semantic_signature": "frame_logic:compiler_component_gap:frame_logic->temporal:slot_alignment",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.95,
        "local_check_count": 0,
        "proof_route_attempted_count": 12,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 12,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-e3376de9831c9b6a",
      "compiler_surface": "modal.source_provenance",
      "confidence": 0.606667,
      "disagreement_categories": [
        "modal.source_provenance",
        "provenance",
        "source_span_hash",
        "synthesis_focus_gap"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.695,
        "promotion_value": 0.676574,
        "rank_score": 0.75669,
        "recurrence_norm": 0.494913
      },
      "formal_severity": 0.86,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.695,
      "llm_called": false,
      "projected_todo": {
        "action": "review_provenance_legal_ir_gap",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/compiler.py",
          "ipfs_datasets_py/logic/modal/leanstral.py"
        ],
        "dedup_key": "leanstral-shadow-8f00cd41770639b3",
        "missing_axes": [],
        "mutation_cases": [
          "provenance_semantic_regression"
        ],
        "specificity_score": 1.0,
        "target_component": "modal.source_provenance",
        "target_metrics": [
          "provenance_heldout_impact"
        ],
        "theorem_templates": [
          "source_provenance_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 11,
      "rank_score": 0.75669,
      "recurrence": 6,
      "request_id": "leanstral-audit-8259aca973e70314",
      "response_hash": "",
      "semantic_family": "provenance",
      "semantic_signature": "provenance:synthesis_focus_gap:provenance->temporal:span_hash",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.86,
        "local_check_count": 0,
        "proof_route_attempted_count": 12,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 12,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-9a43ab36085df1d5",
      "compiler_surface": "modal.temporal",
      "confidence": 0.613333,
      "disagreement_categories": [
        "deadline_order",
        "modal.temporal",
        "synthesis_focus_gap",
        "temporal"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.74,
        "promotion_value": 0.696661,
        "rank_score": 0.756224,
        "recurrence_norm": 0.494913
      },
      "formal_severity": 0.76,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.74,
      "llm_called": false,
      "projected_todo": {
        "action": "review_temporal_legal_ir_gap",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/codec.py",
          "ipfs_datasets_py/logic/CEC/native/temporal.py",
          "ipfs_datasets_py/logic/TDFOL/inference_rules/temporal.py"
        ],
        "dedup_key": "leanstral-shadow-b293ce454c50ba00",
        "missing_axes": [],
        "mutation_cases": [
          "temporal_semantic_regression"
        ],
        "specificity_score": 1.0,
        "target_component": "modal.temporal",
        "target_metrics": [
          "temporal_heldout_impact"
        ],
        "theorem_templates": [
          "source_provenance_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 12,
      "rank_score": 0.756224,
      "recurrence": 6,
      "request_id": "leanstral-audit-1d359b9c617c1f1d",
      "response_hash": "",
      "semantic_family": "temporal",
      "semantic_signature": "temporal:synthesis_focus_gap:temporal->deontic:deadline_order",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.76,
        "local_check_count": 0,
        "proof_route_attempted_count": 12,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 12,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-2d56b69fde9d6c95",
      "compiler_surface": "event_calculus.core",
      "confidence": 0.593333,
      "disagreement_categories": [
        "compiler_component_gap",
        "event_calculus",
        "event_calculus.core",
        "event_calculus_core_fluent_interval"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.605,
        "promotion_value": 0.633356,
        "rank_score": 0.748924,
        "recurrence_norm": 0.494913
      },
      "formal_severity": 0.95,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.605,
      "llm_called": false,
      "projected_todo": {
        "action": "review_event_calculus_legal_ir_gap",
        "allowed_paths": [
          "ipfs_datasets_py/logic/CEC/native/event_calculus.py",
          "ipfs_datasets_py/logic/CEC/native/fluents.py",
          "ipfs_datasets_py/logic/bridge/cec_dcec.py"
        ],
        "dedup_key": "leanstral-shadow-0407f2f4b6b4f993",
        "missing_axes": [],
        "mutation_cases": [
          "event_calculus_semantic_regression"
        ],
        "specificity_score": 1.0,
        "target_component": "event_calculus.core",
        "target_metrics": [
          "event_calculus_heldout_impact"
        ],
        "theorem_templates": [
          "source_provenance_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 13,
      "rank_score": 0.748924,
      "recurrence": 6,
      "request_id": "leanstral-audit-1bc54cf5c741b718",
      "response_hash": "",
      "semantic_family": "event_calculus",
      "semantic_signature": "event_calculus:compiler_component_gap:event_calculus->temporal:fluent_interval",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.95,
        "local_check_count": 0,
        "proof_route_attempted_count": 12,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 12,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-21f7acdf151dae44",
      "compiler_surface": "modal.ir_decompiler",
      "confidence": 0.62,
      "disagreement_categories": [
        "decompiler",
        "exception_reconstruction",
        "modal.ir_decompiler",
        "synthesis_focus_gap"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.785,
        "promotion_value": 0.714228,
        "rank_score": 0.748557,
        "recurrence_norm": 0.494913
      },
      "formal_severity": 0.62,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.785,
      "llm_called": false,
      "projected_todo": {
        "action": "refine_semantic_decompiler_reconstruction",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/codec.py",
          "ipfs_datasets_py/logic/modal/decompiler.py"
        ],
        "dedup_key": "leanstral-shadow-4c435d0b92cd9be1",
        "missing_axes": [],
        "mutation_cases": [
          "invert_modality",
          "remove_exception",
          "alter_deadline"
        ],
        "specificity_score": 1.0,
        "target_component": "modal.ir_decompiler",
        "target_metrics": [
          "reconstruction_loss",
          "source_decompiled_text_embedding_cosine_loss",
          "source_decompiled_text_token_loss"
        ],
        "theorem_templates": [
          "decompiler_round_trip",
          "exception_scope_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 14,
      "rank_score": 0.748557,
      "recurrence": 6,
      "request_id": "leanstral-audit-2ddf72992436057e",
      "response_hash": "",
      "semantic_family": "decompiler",
      "semantic_signature": "decompiler:synthesis_focus_gap:decompiler->temporal:exception_reconstruction",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.62,
        "local_check_count": 0,
        "proof_route_attempted_count": 12,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 12,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-c9a27eef5b51ab45",
      "compiler_surface": "modal.frame_logic",
      "confidence": 0.6,
      "disagreement_categories": [
        "frame_logic",
        "modal.frame_logic",
        "slot_alignment",
        "synthesis_focus_gap"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.65,
        "promotion_value": 0.641368,
        "rank_score": 0.713957,
        "recurrence_norm": 0.494913
      },
      "formal_severity": 0.72,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.65,
      "llm_called": false,
      "projected_todo": {
        "action": "repair_flogic_ontology_constraints",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/kg_bridge.py"
        ],
        "dedup_key": "leanstral-shadow-a673b92a68361a59",
        "missing_axes": [],
        "mutation_cases": [
          "remove_frame_relation",
          "alter_scope"
        ],
        "specificity_score": 1.0,
        "target_component": "modal.frame_logic",
        "target_metrics": [
          "flogic_similarity_loss",
          "legal_ir_view_cross_entropy_loss"
        ],
        "theorem_templates": [
          "source_provenance_preserved",
          "frame_terms_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 15,
      "rank_score": 0.713957,
      "recurrence": 6,
      "request_id": "leanstral-audit-2b782aafda5f3951",
      "response_hash": "",
      "semantic_family": "frame_logic",
      "semantic_signature": "frame_logic:synthesis_focus_gap:frame_logic->temporal:slot_alignment",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.72,
        "local_check_count": 0,
        "proof_route_attempted_count": 12,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 12,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-da997b075ca29f68",
      "compiler_surface": "event_calculus.core",
      "confidence": 0.593333,
      "disagreement_categories": [
        "event_calculus",
        "event_calculus.core",
        "fluent_interval",
        "synthesis_focus_gap"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.605,
        "promotion_value": 0.618761,
        "rank_score": 0.707224,
        "recurrence_norm": 0.494913
      },
      "formal_severity": 0.78,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.605,
      "llm_called": false,
      "projected_todo": {
        "action": "review_event_calculus_legal_ir_gap",
        "allowed_paths": [
          "ipfs_datasets_py/logic/CEC/native/event_calculus.py",
          "ipfs_datasets_py/logic/CEC/native/fluents.py",
          "ipfs_datasets_py/logic/bridge/cec_dcec.py"
        ],
        "dedup_key": "leanstral-shadow-e768d8c488b189c7",
        "missing_axes": [],
        "mutation_cases": [
          "event_calculus_semantic_regression"
        ],
        "specificity_score": 1.0,
        "target_component": "event_calculus.core",
        "target_metrics": [
          "event_calculus_heldout_impact"
        ],
        "theorem_templates": [
          "source_provenance_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 16,
      "rank_score": 0.707224,
      "recurrence": 6,
      "request_id": "leanstral-audit-481d2d510df7df03",
      "response_hash": "",
      "semantic_family": "event_calculus",
      "semantic_signature": "event_calculus:synthesis_focus_gap:event_calculus->temporal:fluent_interval",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.78,
        "local_check_count": 0,
        "proof_route_attempted_count": 12,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 12,
        "verifier_outcome": "not-run"
      }
    },
    {
      "audit_reasons": [
        "dry_run_no_provider_audit"
      ],
      "audit_valid": false,
      "audit_verified": false,
      "cache_hit": false,
      "cluster_id": "lir-cluster-ab8b1a66a330f3c3",
      "compiler_surface": "modal.ir_decompiler",
      "confidence": 0.626667,
      "disagreement_categories": [
        "decompiler",
        "edge_role",
        "modal.ir_decompiler",
        "synthesis_focus_gap"
      ],
      "estimated_compiler_impact": {
        "heldout_impact": 0.0,
        "promotion_value": 0.262534,
        "rank_score": 0.46729,
        "recurrence_norm": 0.494913
      },
      "formal_severity": 0.62,
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "heldout_impact": 0.0,
      "llm_called": false,
      "projected_todo": {
        "action": "refine_semantic_decompiler_reconstruction",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/codec.py",
          "ipfs_datasets_py/logic/modal/decompiler.py"
        ],
        "dedup_key": "leanstral-shadow-3ed88353976758eb",
        "missing_axes": [],
        "mutation_cases": [
          "invert_modality",
          "remove_exception",
          "alter_deadline"
        ],
        "specificity_score": 1.0,
        "target_component": "modal.ir_decompiler",
        "target_metrics": [
          "reconstruction_loss",
          "source_decompiled_text_embedding_cosine_loss",
          "source_decompiled_text_token_loss"
        ],
        "theorem_templates": [
          "decompiler_round_trip",
          "exception_scope_preserved"
        ],
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "rank": 17,
      "rank_score": 0.46729,
      "recurrence": 6,
      "request_id": "leanstral-audit-00d9c8eeca7b5522",
      "response_hash": "",
      "semantic_family": "decompiler",
      "semantic_signature": "decompiler:synthesis_focus_gap:knowledge_graph->temporal:edge_role",
      "theorem_outcomes": {
        "cluster_formal_severity": 0.62,
        "local_check_count": 0,
        "proof_route_attempted_count": 12,
        "proof_route_failed_records": 0,
        "proof_route_valid_count": 12,
        "verifier_outcome": "not-run"
      }
    }
  ],
  "cache_summary": {
    "cache_hits": 0,
    "cache_misses": 17,
    "llm_calls": 0,
    "requests": 17
  },
  "config": {
    "cache_dir": "",
    "dry_run": true,
    "max_clusters": 50,
    "max_source_span_copy_ratio": 0.25,
    "model": "Leanstral",
    "provider": "mistral_vibe",
    "report_path": "docs/implementation/reports/leanstral_shadow_canary.md",
    "require_local_verifier": true,
    "timeout_seconds": 300.0,
    "vibe_agent": "lean"
  },
  "disagreement_categories": {
    "compiler_component_gap": 8,
    "deadline_order": 1,
    "decompiler": 3,
    "deontic": 2,
    "deontic.ir": 2,
    "deontic_ir_obligation_scope": 1,
    "edge_role": 1,
    "event_calculus": 2,
    "event_calculus.core": 2,
    "event_calculus_core_fluent_interval": 1,
    "exception_reconstruction": 1,
    "external_provers.router": 3,
    "external_provers_router_proof_route_failure_ratio": 1,
    "fluent_interval": 1,
    "formal_prover_gap": 1,
    "frame_logic": 2,
    "knowledge_graph": 1,
    "knowledge_graphs.neo4j_compat": 1,
    "knowledge_graphs_neo4j_compat_edge_role": 1,
    "modal.frame_logic": 2,
    "modal.ir_decompiler": 3,
    "modal.source_provenance": 2,
    "modal.temporal": 2,
    "modal_frame_logic_slot_alignment": 1,
    "modal_ir_decompiler_exception_reconstruction": 1,
    "modal_source_provenance_source_span_hash": 1,
    "modal_temporal_deadline_order": 1,
    "obligation_scope": 1,
    "proof_route_failure_ratio": 2,
    "provenance": 2,
    "prover": 3,
    "slot_alignment": 1,
    "source_span_hash": 1,
    "synthesis_focus_gap": 8,
    "temporal": 2
  },
  "estimated_compiler_impact": {
    "mean_promotion_value": 0.700628,
    "top_promotion_value": 0.83694,
    "total_projected_impact": 11.910675
  },
  "no_mutation": {
    "mode": "shadow",
    "queue_seeded_count": 0,
    "report_only": true,
    "source_mutation_count": 0,
    "source_mutation_detected": false,
    "todo_queue_seeded": false
  },
  "projected_todo_specificity": {
    "complete_count": 17.0,
    "mean": 1.0,
    "min": 1.0
  },
  "promotion_allowed": false,
  "promotion_blockers": [
    "dry_run_no_promotion",
    "verifier_guardrail_not_satisfied"
  ],
  "runtime_seconds": 0.013056,
  "schema_version": "legal-ir-leanstral-shadow-canary-v1",
  "selected_cluster_count": 17,
  "source_record_count": 50,
  "theorem_outcomes": {
    "local_checks": 0,
    "proof_route_attempted": 214,
    "proof_route_failures": 21,
    "proof_route_valid": 193
  }
}
```
