# HSSL-BENCH-032 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-032
Goal: HSSL-G111 — Restore and pin SyMAI and llm_router provider/model identities
Missing evidence: HSSLEV1118B52
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-24-hssl-bench-032-objective-gap-c60b68baa207.md`
Source fingerprint: `c60b68baa207dbd5061188693dec76beb8e1ff13`
Todo vector: `7d80248e231716e7`
Merge key: `9925664a1431fe09`
Merge family: `objective/HSSL-G111`
Work scope: `goal_subgoal_multi_evidence_batch`

## Evidence

- `scripts.benchmarks.provision_hssl_symai_router.HSSLEV1118B52` is the stable
  AST evidence symbol for the pinned, existing-router SyMAI runtime boundary.
- `benchmarks/logic_pipeline/runtime_env/symai-router.lock` is a strict JSON
  lock despite its `.lock` suffix. It pins the `symbolicai` distribution and
  `symai` import to 1.14.0, verifies the installed distribution metadata
  digest, names the repository's `ipfs_datasets_py.llm_router` and
  `IPFSSyMAINeurosymbolicEngine`, and selects exactly provider
  `ipfs_accelerate_py` plus model `Leanstral-119B`. The SyMAI config spelling is
  independently fixed as `ipfs:Leanstral-119B`.
- The lock rejects missing or unknown fields and fixes all safety switches:
  local, provider, and model fallbacks are false; recursive routing is false;
  setup is noninteractive; the existing model service is reused; and neither
  a model server nor model manager is started.
- `scripts/benchmarks/provision_hssl_symai_router.py` separates a default
  read-only runtime check from explicit installation, configuration, and live
  smoke actions. The install command uses the active Python interpreter,
  `pip --no-input`, an exact version, argv rather than a shell, and a bounded
  subprocess. SyMAI configuration is created under an explicit isolated
  prefix before import, preventing the package's first-import wizard and
  user-global configuration drift.
- The provisioner aligns `HSSL_SYMAI_*`, `HSSL_LLM_ROUTER_*`, top-level router,
  and SyMAI config identities from the one lock. It disables Codex
  auto-selection and response caches for identity smoke evidence. Credentials
  are never copied into configuration or serialized: receipts contain only
  presence plus a contextual SHA-256 digest for present allowlisted variables.
  Exceptions, subprocess output, endpoints, model output, and raw credentials
  are absent from failure and success receipts.
- The opt-in live smoke uses an authored non-corpus sentence, one call, zero
  adapter retries, JSON-object response format, bounded input/output, and a
  maximum 30-second deadline. It requires explicit effective trace values
  equal to the requested provider and model, retains only input/output and
  candidate digests, and records existing-service reuse. The focused
  integration test executes this complete smoke contract with an injected
  existing-router engine; it does not claim that an external 119B service was
  contacted during CI.
- The SyMAI adapter now fails closed when router trace identity is absent or
  differs from the request. The existing SyMAI engine also passes
  `disable_model_retry=True` when fallback is disabled, preventing the
  top-level router from retrying the provider with an unrequested default
  model.

## Validation

Required command:

```text
python -m pytest tests/integration/benchmarks/logic_pipeline/test_symai_router_runtime.py tests/unit/benchmarks/logic_pipeline/test_symai_adapter.py -q
```

Result: passed, 39 tests at the completed implementation checkpoint.
The suite covers the evidence symbol; strict lock schema; exact
distribution/artifact, router, engine, provider, and model pins; noninteractive
installation and isolated configuration; aligned capability environment;
secret-safe receipts; fail-closed package, module, identity, recursion, and
fallback drift; the bounded structured smoke contract; canonical create-only
receipt output; and compatibility with the pre-existing SyMAI adapter suite.

The default read-only provisioner check also passed in the implementation
environment. It found SymbolicAI 1.14.0 with the pinned metadata digest,
the `symai` import, and the repository router module/source. No live model call,
package installation, model server, or model manager was started.

Additional nearby adapter, capability-probe, engine backend-selection, and
top-level engine-router regression suites passed: 32 tests. Python bytecode
compilation and repository whitespace validation also passed.

## Backlog alignment

HSSL-G111 remains one cohesive runtime identity goal. Package discovery,
noninteractive config, router selection, provider/model equality, secret-safe
receipts, fallback exclusion, and the bounded smoke call are all validated at
one trust boundary, so splitting them into child goals would weaken rather than
clarify the acceptance contract. Generated todo-vector, objective-bundle, and
task-status metadata remain supervisor-owned and were not edited manually. The
supervisor can reconcile HSSLEV1118B52 from the AST symbol, strict runtime
lock, provisioner, focused tests, objective heap, and this discovery receipt.
