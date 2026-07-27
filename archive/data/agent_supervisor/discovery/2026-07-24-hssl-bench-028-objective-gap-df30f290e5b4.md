# HSSL-BENCH-028 Objective Gap Resolution

Date: 2026-07-24
Fingerprint: df30f290e5b405260a5ae16db6704d278f04b0bb
Task: HSSL-BENCH-028
Goal: HSSL-G032 — Integrate SyMAI through the existing router
Missing evidence: HSSLEV0328B3A
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-028-objective-gap-df30f290e5b4.md`
Source fingerprint: `df30f290e5b405260a5ae16db6704d278f04b0bb`
Objective heap: `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`
Todo vector: `74278fd4cb6f973f`
Merge key: `9fac3116ccefd1ba`
Merge family: `objective/HSSL-G032`
Work scope: `goal_subgoal_multi_evidence_batch`

## Evidence

- `benchmarks.logic_pipeline.adapters.HSSLEV0328B3A` is the stable AST
  evidence symbol for strict SyMAI semantic interpretation through the existing
  IPFS `llm_router`.
- `SymaiAdapterConfig` freezes provider/model identity, raw/input byte limits,
  cache behavior, dry-run state, and a retry count capped by
  `SYMAI_MAX_RETRIES`. The default configured path lazily loads
  `IPFSSyMAINeurosymbolicEngine`, pins the existing router provider, and disables
  local-model fallback. It does not configure production defaults, launch a
  model manager, or start a second Leanstral service.
- The shared SyMAI engine now accepts request-scoped provider, dependency,
  fallback, dry-run, model, and cache-namespace settings while retaining its
  backward-compatible defaults. Generation still passes through
  `ipfs_datasets_py.llm_router.generate_text`; requested and effective
  provider/model identities are retained from the router trace.
- Every cache namespace comes from the frozen `CacheScope`, binding protocol
  digest, run, variant, split, and cold/warm mode. The SyMAI key additionally
  binds the case input, upstream stage digests, provider, model, and dry-run
  state. Cold executions cannot consume warm entries, and no entry crosses
  run, variant, or split boundaries.
- The adapter rejects SyMAI re-entry both from the incoming route stack and
  from the router's effective provider trace. Import or preflight configuration
  missingness is explicit, router/configuration failures use
  `symai_import_or_configuration_error`, and malformed JSON/contracts use
  `symai_contract_or_json_failure`.
- A successful response must be exactly one strict JSON object containing
  candidate IR, normalized predicates, quantifiers, entities, ambiguity flags,
  confidence, and validation errors. Duplicate keys, non-finite numbers,
  unknown/missing fields, oversized values, and proof-authority claims fail
  closed. Raw output is retained separately and is explicitly non-canonical;
  only the validated candidate receives a digest.
- Model-lane telemetry records calls, bounded retries, cache hits/misses, bytes,
  and timing. SyMAI evidence always remains an untrusted semantic hypothesis:
  it cannot assert verification, kernel acceptance, authority, or a proof
  receipt.

## Validation

The required focused command completed successfully:

```text
python -m pytest tests/unit/benchmarks/logic_pipeline/test_symai_adapter.py -q
22 passed
```

The shared stage boundary and strict Leanstral integration regression command
also completed successfully:

```text
python -m pytest tests/unit/benchmarks/logic_pipeline/test_adapters.py tests/integration/benchmarks/logic_pipeline/test_leanstral_adapter.py tests/unit/benchmarks/logic_pipeline/test_symai_adapter.py -q
38 passed
```

The complete benchmark unit package completed successfully:

```text
python -m pytest tests/unit/benchmarks/logic_pipeline -q
163 passed
```

Coverage includes the existing-engine dispatch, stable records/digests,
deterministic dry-run, full cache-scope separation, malformed and repaired
contracts, retry exhaustion, output bounds, unavailable package/configuration
including `SystemExit`, pre/post-dispatch recursion, effective identity, proof
authority denial, and confirmation that no service-start boundary is called.

## Backlog alignment

HSSL-G032 is already one cohesive bounded child of HSSL-G030, with one adapter
implementation and one focused test suite. The executable evidence, objective
heap contract, and this supervisor discovery receipt cover HSSLEV0328B3A
without a smaller child goal. Generated todo-vector, bundle, and task status
remain supervisor-owned and were not edited manually.
