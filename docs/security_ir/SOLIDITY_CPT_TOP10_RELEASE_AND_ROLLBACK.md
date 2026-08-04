# Solidity CPT release and rollback

This runbook governs local, source-free staging of the Solidity CPT Top-10
Security IR artifacts. It does not authorize publication, upload, proof,
contract enforcement, wallet signing, or broadcast.

## Authority boundary

The Solidity CPT bridge is advisory. A reviewer may use corpus records,
GraphRAG retrieval, model output, quality scores, or candidate formulas to
choose a property worth checking. The bridge emits only reviewed Crypto IR
`SecurityRule` and `ProofObligation` declarations with exact semantic
prerequisites and fact bindings.

An obligation says “check this property”; it does not say the property holds.
The bridge always records candidate authority, `proof_authority=false`, and
`transaction_authority=false`. It does not emit `ContractSafetyDecision`.

Contract enforcement remains with the existing contract-safety gate. That gate
requires independently validated, executed receipts for every required
obligation, bound to the exact transaction candidate, intent effects, deployed
code/proxy/upgrade/state epochs, assumptions, authority class, and freshness
window. The wallet policy and compliance gates remain separate and are still
required. In particular:

- retrieval rank, corpus quality, model confidence, and calibration are not
  proof;
- a candidate formula or unexecuted lowering is not proof;
- SAT, simulation, monitoring, and static analysis do not elevate to theorem
  proof where proof authority is required;
- unknown, unsupported, unavailable, corrupt, mismatched, stale, and
  unexecuted results block automation;
- an upgrade or code-epoch change invalidates an earlier decision.

## Deterministic local release gate

Run from the `ipfs_datasets_py` repository:

```bash
python scripts/ops/security_ir/build_solidity_cpt_top10_release.py \
  --output-dir /existing-parent/solidity-cpt-release
```

The output directory must be absent or empty. When `--evaluation` is omitted,
the command uses the deterministic offline evaluation fixture. Production
staging supplies a previously generated local evaluation receipt:

```bash
python scripts/ops/security_ir/build_solidity_cpt_top10_release.py \
  --output-dir /existing-parent/solidity-cpt-release \
  --evaluation /local/evaluation-receipt.json \
  --candidate-metadata /local/reviewed-candidates.json \
  --config-cid b...
```

The gate fails closed unless the receipt rehashes and its promotion gate passes
with zero leakage, zero false-proof claims, zero authority violations, complete
metric slices, and all required held-out/adversarial controls.

The release manifest binds these identities independently:

- immutable source CID;
- graph and retrieval-index CIDs;
- partition CID;
- model or checkpoint CID;
- evaluation CID and promotion-gate CID;
- license CID;
- release configuration CID;
- pinned source-profile and release-policy SHA-256 values; and
- every staged artifact SHA-256, CID, byte length, media type, and relative
  path.

Two builds with the same inputs in separate empty directories are
byte-identical. Verification rehashes the manifest and every artifact:

```bash
python scripts/ops/security_ir/build_solidity_cpt_top10_release.py \
  --verify-only /existing-parent/solidity-cpt-release
```

There are deliberately no credential, network, download, publish, upload,
sign, prove, or broadcast flags.

## License and content filter

The builder evaluates the pinned release policy for a source-free derivative.
Candidate metadata has a closed schema and excludes Solidity text, contract
bodies, bytecode, raw rows, solver outcomes, safety decisions, and transaction
verdicts. Rejected or unreviewed raw-source bodies are therefore never staged.
Raw-source redistribution and learned-weight publication require separate
license review and operator authority outside this command.

The release includes:

- `release-manifest.json`;
- `candidates.json`, containing only reviewed identifiers, CIDs, rule and
  obligation ids, review ids, and semantic prerequisites;
- `DATA_CARD.md`; and
- `MODEL_CARD.md`.

The cards state the data/model limitations and the candidate-only authority
boundary. Operators must preserve them with the manifest.

## Integration mode and limitations

The only supported integration mode is `observation_shadow_only`.

- Observation may record which reviewed obligations would be selected.
- Shadow mode may compare advisory selection with existing policy results.
- Neither mode may modify a signing decision, required-obligation policy,
  proof receipt, code epoch, or wallet verdict.
- Direct enforcement, automatic policy mutation, publication, and upload are
  disabled.

This release does not establish completeness, absence of vulnerabilities,
applicability to unsupported Solidity/compiler/deployment semantics, legal
permission to redistribute raw source, or safety of any deployed contract.

## Rollback

Rollback is a manifest-pointer operation, never an in-place edit:

1. Disable ingestion of the suspect manifest CID in observation/shadow
   consumers.
2. Restore the previously verified manifest CID and its complete directory.
3. Re-run `--verify-only` before resuming observation.
4. Invalidate cached advisory selections derived from the suspect graph,
   index, model/checkpoint, evaluation, license, configuration, or bridge CID.
5. Record the trigger, old/new manifest CIDs, affected observation window, and
   operator.
6. If a false allow is suspected, stop automated transaction processing and
   follow the wallet/contract incident runbook. A release rollback cannot
   retroactively authorize or repair a transaction decision.

Triggers include CID or digest mismatch, corrupt/missing artifact, source or
license drift, leakage discovery, evaluation regression, unsupported-semantics
misclassification, authority-confusion finding, or any evidence that raw source
or a forbidden verdict field entered a staged artifact.
