# Leanstral Real Shadow Canary

- Schema: `legal-ir-leanstral-real-shadow-canary-v1`
- Mode: `real-shadow`
- Status: `blocked`
- Source records: 0
- Valid real packets: 0
- Invalid packets: 0
- Runtime seconds: 0.000000
- Promotion allowed: `false`
- Synthetic promotion evidence generated: `false`
- Blocked reasons: `no_canonical_packet_input`, `insufficient_real_canonical_packets`, `leanstral_labs_access_unavailable_or_not_configured`, `no_provider_or_verified_cache_evidence`, `no_local_verifier_acceptance`, `no_verified_audit_responses`

## Real Packet Validity
- `valid_real_packet_count`: 0
- `invalid_packet_count`: 0
- `min_required_real_packets`: 25
- `meets_minimum_real_packet_count`: false
- `invalid_reasons`: {}

## Canonical State And Compiler Commit
- `packet_count`: 0
- `state_hash`: ""
- `state_hash_count`: 0
- `state_hashes`: []
- `compiler_commit`: ""
- `compiler_commit_count`: 0
- `compiler_commits`: []

## Family And Surface Coverage
- `family_count`: 0
- `family_counts`: {}
- `surface_count`: 0
- `surface_counts`: {}
- `audit_item_count`: 0
- `audit_item_family_counts`: {}
- `audit_item_surface_counts`: {}
- `evaluation_role_counts`: {}
- `sample_role_counts`: {}

## Cache Behavior
- `requests`: 0
- `cache_hits`: 0
- `cache_misses`: 0
- `llm_calls`: 0
- `provider_disabled_or_missed`: 0
- `checkpoint_skips`: 0
- `unavailable`: 0

## Audit Validity
- `valid`: 0
- `verified`: 0
- `invalid`: 0

## Verifier Outcomes
- `accepted`: 0
- `rejected_or_unsupported`: 0
- `local_check_count`: 0
- `outcomes`: {}
- `reasons`: {}

## State-To-Verified-Audit Lag
- `count`: 0
- `min`: null
- `mean`: null
- `max`: null
- `missing_count`: 0

## No-Mutation Contract
- `mode`: "real_shadow"
- `report_only`: true
- `queue_seeded_count`: 0
- `source_mutation_count`: 0
- `source_mutation_detected`: false
- `todo_queue_seeded`: false
- `provider_cache_writes_allowed`: false
- `promotion_evidence_generated`: false

## Audit Work Items

No audit work items produced verified promotion evidence.

## Operator Note

This implementation environment did not provide a canonical-state packet file, a verified hash-matching Leanstral audit cache, or Leanstral Labs access credentials. The canary is therefore explicitly blocked and does not generate synthetic promotion evidence.
