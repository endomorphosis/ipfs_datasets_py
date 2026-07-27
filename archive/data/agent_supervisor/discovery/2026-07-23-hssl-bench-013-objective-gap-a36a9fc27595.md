# HSSL-BENCH-013 Objective Split-integrity Receipt

Date: 2026-07-24
Task id: HSSL-BENCH-013
Goal id: HSSL-G023
Goal title: Freeze split integrity and leakage checks
Objective heap: `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-013-objective-gap-a36a9fc27595.md`
Source fingerprint: `a36a9fc275956213e37fe46012b84f31447332d6`
Objective marker: `HSSLEV0232D57`
Todo vector key: `25b5eb5f0aa1208a`
Merge key: `0efc390a63c042e1`
Merge family: `objective/HSSL-G023`
Work scope: `goal_subgoal_multi_evidence_batch`

## Finding Reconciliation

The source scan found no implementation evidence for HSSL-G023. The objective
required exact and normalized duplicate checks, frozen split identities, and
auditable holdout access, while its goal text also named near-copy, cache,
prompt, and tuning leakage.

`benchmarks.logic_pipeline.cases.HSSLEV0232D57` is now a literal Python
function symbol bound to the executable split-integrity contract. The
implementation preserves the reviewed corpus-v1 wire records and their
existing digests while adding an independently content-addressed manifest for
each split and a no-tuning access receipt for the holdout.

## Implementation Evidence

- `normalize_source_text` applies the frozen, locale-independent Unicode NFKC,
  case-fold, alphanumeric, punctuation, and whitespace policy. Integrity
  validation rejects exact source digests, normalized source digests, reused
  provenance, and token-trigram near copies across different splits. The
  near-copy Jaccard threshold is fixed at `0.8`.
- The holdout is sealed against prompt exposure in case provenance.
  `validate_holdout_prompt_isolation` also compares real prompt/example IDs
  and normalized text against every holdout case, including near copies, and
  returns deterministic fingerprints for the access receipt.
- `SplitManifest` binds one split's ordered IDs, case digests, exact source
  digests, normalized source digests, and reviewed corpus-manifest identity.
  `SplitIntegrityManifest` requires all three non-overlapping splits in frozen
  order and binds their complete canonical records.
- The frozen identities are pilot
  `a050371dae1248deecfb17f2d9e610124c6e493a1a227ec3c161008891ce1881`,
  development
  `530860019b164c9750083ec5affd6ae71202b695c8c8042400d0f02488436b74`,
  holdout
  `c7b969ed19a1248143740068e2853ca6132ba3d65dfeec4133e37fad55dbab4a`,
  and aggregate split integrity
  `dd68177636a3db87752de54399ed8f066d5fdefe568649d9551bb29a0fb529d0`.
  Loading a self-consistent but reassigned, reordered, copied, or otherwise
  changed split fails against these preregistered identities.
- `HoldoutAccessAudit.from_run_contract` composes with the existing strict
  `RunContract`, which already binds run, protocol, requested/effective
  variant, split, cache mode, and exact split-scoped cache namespace. The
  access receipt additionally binds the reviewed corpus, frozen holdout,
  accessed cases in manifest order, configuration, prompts, policy, model
  identities, thresholds, prompt-example fingerprints, audit ID and sequence,
  explicit frozen-state booleans, and the no-tuning boundary.
- Split and audit records are frozen and slotted, convert to strict
  JSON-native dictionaries, reject missing and unknown fields, validate their
  own canonical SHA-256, and contain no volatile timestamps or random values.
- `tests/unit/benchmarks/logic_pipeline/test_holdout_integrity.py` pins every
  split digest and exercises Unicode normalization; exact, normalized,
  near-copy, provenance, and prompt leakage; immutable/strict serialization;
  content tampering; run/cache composition; case membership and order; and
  frozen/no-tuning access invariants.
- The inherited reviewed fixture `corpus.jsonl` had been omitted from the
  preceding corpus commit because of the repository-wide `*.jsonl` ignore
  pattern. Its already validated canonical bytes were recovered from the
  HSSL-BENCH-012 implementation log, verified against the committed manifest,
  and made durable through a fixture-specific `.gitignore` exception. This
  restores clean-checkout reproducibility without changing any corpus digest.

## Backlog Alignment

No child goal is needed. HSSL-G023 is one cohesive leakage-boundary layer over
the reviewed HSSL-G020 corpus and the frozen HSSL-G010 run contract. The
existing code/test outputs and validation command cover its exact scope.
HSSL-G023 remains active so the supervisor can reconcile completion from this
validated receipt. The generated external todo, bundle, vector index, and task
status were not edited manually.

## Validation

Commands:

```text
python -m pytest tests/unit/benchmarks/logic_pipeline/test_holdout_integrity.py -q
python -m pytest tests/unit/benchmarks/logic_pipeline -q
python -m pytest tests/integration/benchmarks/logic_pipeline -q
```

Results on 2026-07-24: focused split/holdout validation passed (`23 passed`);
the complete logic-pipeline unit regression passed (`109 passed`), and the
logic-pipeline integration regression passed (`16 passed`).
