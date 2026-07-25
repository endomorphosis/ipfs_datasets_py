# Security IR Migration

Status: reviewed migration and deprecation policy  
Interface: `SecurityIRMigration@1`  
Strategy: strangler migration with a reversible compatibility facade

This policy migrates
`ipfs_datasets_py.logic.security_models.crypto_exchange` to the shared
`ipfs_datasets_py.logic.security_ir` contracts without changing the meaning of
legacy imports or treating an artifact's storage location as authority. The
frozen surface is documented in
`docs/security_verification/security_ir_v1_compatibility.md`.

## Non-negotiable invariants

- Legacy imports, input decoding, report/receipt reading, CLI exit behavior,
  and registry discovery remain available throughout the deprecation window.
- A declaration identity does not change when verification runs, results are
  attached, or optional CID/solver libraries are present.
- Migration copies and classifies; it does not delete source artifacts,
  rewrite a legacy ID, select release evidence, or grant theorem authority.
- `ProofResult`, `MonitorResult`, `EvidenceGateResult`, and `PolicyDecision`
  remain distinct. An Xaman evidence-readiness result cannot be migrated or
  relabeled as theorem proof.
- Missing, malformed, stale, unsupported, unavailable, or unreviewed evidence
  fails closed.

## Migration phases

| Phase | Write path | Read path | Exit condition |
| --- | --- | --- | --- |
| `inventory` | None; inspect legacy tree read-only | Legacy only | Frozen API/golden corpus and complete classified inventory |
| `dual-read` | Legacy producers continue; new manifests may be generated in a run directory | Strict v1 first where selected, then reviewed legacy adapter | Golden legacy-to-v1-to-legacy round trips and identity bindings pass |
| `v1-write` | New producers write immutable v1 declarations/results and manifests | v1 plus legacy facade/reader | Shadow parity, typed authority, lineage, and rollback pass |
| `v1-default` | v1 is canonical for approved scopes | v1 plus deprecated legacy facade/reader | Deprecation window and measured downstream migration complete |
| `legacy-removal` | v1 only for removed scope | Versioned archived legacy reader only where policy requires | Separate breaking-release approval and all removal gates pass |

Moving between phases requires a reviewed manifest. There is no
traffic-derived or time-derived automatic transition.

## Declaration and result conversion

For every migrated declaration:

1. read legacy bytes without mutation and record path, size, SHA-256, legacy
   canonical bytes, and both legacy identifier representations when present;
2. validate with the frozen legacy decoder;
3. adapt declarations into immutable typed `SecurityIR`; move solver output,
   runtime traces, disproof vectors, evidence gates, release decisions, and
   receipts to their separate result records;
4. record `legacy_id -> v1 declaration digest` in a content-addressed migration
   entry without replacing the legacy ID;
5. validate v1-to-legacy compatibility for the golden corpus;
6. prove that executing verification does not change the v1 declaration
   digest;
7. write a migration integrity receipt and parent-bound artifact manifest.

Unknown extension vocabulary, source gaps, invalid legacy input, or a lossy
conversion is quarantined for human review. It must not be silently normalized
or promoted.

## Artifact layout and authority

Classify existing files without initially moving or deleting them:

```text
security_ir_artifacts/
  inputs/
  golden/
  runs/<run-id>/
  promoted/
  migrations/
  archive/
```

`SecurityArtifactMigration@1` records source, target classification, legacy
identity, exact digest/size, and migration status. Its invariant is
`authority_selected == false` for every record and
`authority_decisions_made == 0` for the inventory manifest. The word
`promoted` in a legacy path or migration classification is not a review
decision.

A release-grade v1 promotion requires a separate
`ir-artifact-manifest/v1` that binds:

- exact input, parent, and output digests/CIDs and sizes;
- legacy ID mapping and migration integrity receipt;
- declaration, schema, ontology, repository, producer, configuration, and
  tool/backend versions;
- typed proof/evidence/policy result identities and assumptions;
- license, trust, review, proof-authority, expiry, and release decisions;
- independent reviewer and rollback owner.

Write new output to `runs/<run-id>/`, validate it, and promote by immutable
copy to a content-addressed destination. Reject mutable `latest` aliases,
ambiguous `-new` names, temporary compiler/solver output, digest drift, stale
receipts, and unmanifested evidence. Never overwrite an existing promoted
artifact.

## Shadow and cutover gates

Before selecting v1 as the default for any scope:

- frozen public import/CLI/registry contracts and the legacy golden corpus
  pass;
- legacy/v1 declaration round trips pass or an explicit reviewed diagnostic
  documents an intentionally unsupported case;
- canonical v1 identity is independent of results and optional dependencies;
- required Security claims have supported and available
  `BackendCapabilities`, bounded attempts, typed results, and valid receipts;
- every blocking/high claim follows the production release decision policy;
- evidence-readiness and runtime-monitor results have no theorem authority;
- migration manifests have zero authority decisions;
- promoted artifacts have complete immutable lineage and independent review;
- Legal/Intent conformance and the IR rollout contract remain green;
- rollback to the legacy facade has been rehearsed.

## Deprecation window

The legacy Python facade, legacy input decoder, legacy report/receipt reader,
CLI compatibility, and registry entry remain supported for at least **two
consecutive minor releases and 180 days after the first published deprecation
warning, whichever ends later**.

The warning must name the replacement import, the first release containing the
warning, the earliest calendar removal date, the earliest eligible breaking
release, this migration guide, and a stable telemetry/issue channel. Warnings
must be deterministic, bounded, and must not change serialization or exit
codes.

During the window, maintainers monitor legacy import/CLI/reader use by release
and known internal downstream consumer. Telemetry must not include source
bodies, secrets, PII, model content, or proof payloads. Absence of telemetry is
not evidence of zero use.

## Removal gates

Removing any shim is a separately reviewed breaking-release change. It
requires all of:

- the full two-minor-release/180-day window has elapsed;
- at least 30 consecutive days of zero observed use by known internal
  consumers, with telemetry health demonstrated;
- owners of registered downstream consumers acknowledge migration;
- current legacy golden-reader/export and v1 compatibility suites pass;
- all tracked promoted legacy artifacts have reviewed v1 manifests or an
  explicit retained/archive decision;
- documentation, import warnings, and registry guidance name the final
  replacement;
- rollback rehearsal demonstrates that the previous release and archived
  legacy reader can consume required artifacts;
- security reviewer and release owner explicitly approve the exact removal
  release.

Time elapsed, an empty issue queue, or a drained task board cannot satisfy
these gates. Serialized legacy v1 artifacts are not deleted when code shims are
removed; retention and the archived reader follow the approved evidence policy.

## Monitoring

Migration telemetry records bounded counts and digests for:

- legacy and v1 reads/writes by interface and version;
- conversion success, explicit unsupported cases, quarantine, and round-trip
  mismatch;
- declaration digest changes before/after verification;
- optional-dependency identity variance;
- typed result/authority mismatches and invalid proof receipts;
- backend unsupported/unavailable/timeout/unknown results;
- unmanifested, stale, `latest`, `-new`, temporary, overwritten, or
  digest-drifting artifacts;
- compatibility, golden-corpus, registry, CLI, and release-gate failures.

Any identity mutation, authority mismatch, release-evidence integrity failure,
or unexplained golden/compatibility regression blocks cutover and triggers
rollback. Missing monitoring blocks shim removal.

## Rollback

Rollback is non-destructive:

1. stop new v1-default admission for the affected scope;
2. set the IR family advisor stage to `off` when the incident touches shared
   formalization, backend, or promotion evidence;
3. route reads/writes through the frozen legacy facade or last approved v1
   manifest as declared by the incident plan;
4. revoke the active cutover/promotion manifest without deleting it;
5. quarantine incomplete outputs and preserve both legacy and v1 bytes,
   mappings, receipts, logs, counterexamples, and parent digests;
6. run the legacy public API/golden corpus, IR compatibility, cross-domain
   conformance, offline pipeline, and rollout-contract tests;
7. notify Security consumers and owners of every affected promoted digest;
8. require reviewed root cause, repaired migration receipt, rollback rehearsal,
   and new human approvals before resuming `dual-read` or `v1-write`.

Never roll back by deleting the migration map, renaming an unreviewed artifact
to `promoted`, silently changing a snapshot/backend, or disabling validation.

## Human approvals

The following decisions cannot be delegated to migration code or inferred from
artifact classification:

- the authoritative CID/multicodec profile and any legacy-ID exception;
- vocabulary/schema conversions that are not lossless;
- solver/model provisioning or updates, the solver/backend/version
  proof-authority allowlist, and required assumptions;
- reviewed evidence, release decisions, artifact promotion/revocation, and
  retention/archive disposition;
- cutover into `v1-write` or `v1-default`;
- compatibility-window start and downstream consumer inventory;
- incident disposition and post-rollback resumption;
- exact breaking release that removes each legacy shim or reader surface.
