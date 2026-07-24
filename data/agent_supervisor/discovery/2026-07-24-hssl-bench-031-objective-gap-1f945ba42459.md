# HSSL-BENCH-031 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-031
Goal: HSSL-G110 — Restore and pin the requested full spaCy pipeline
Missing evidence: HSSLEV1103A41
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-24-hssl-bench-031-objective-gap-1f945ba42459.md`
Source fingerprint: `1f945ba42459fd9b4706eff52bdc1061cb0ee1a7`
Todo vector: `ee9dac0be0acd40b`
Merge key: `fd7953cefd505d6d`
Merge family: `objective/HSSL-G110`
Work scope: `goal_subgoal_multi_evidence_batch`

## Evidence

- `scripts.benchmarks.provision_hssl_spacy.HSSLEV1103A41` is the stable AST
  symbol for the artifact-pinned, no-fallback, detached full-spaCy runtime
  boundary. The implementation separates pre-run provisioning from benchmark
  evaluation and does not import a fixture, corpus, manifest, variant, policy,
  prompt, threshold, or result module.
- `benchmarks/logic_pipeline/runtime_env/spacy.lock` is closed-schema strict
  JSON with semantic digest
  `f45945e4e8a24305b3ade669ed52da2df2b0af63267b9ef28823b9bac442d68d`.
  It pins spaCy `3.8.14` for CPython 3.12 on Linux aarch64 and x86-64 to
  platform wheel SHA-256 values
  `daeb64b048f12c059997281aed53eb8776d26416dd313cf17ad6f63124b2b564`
  and
  `6d45715a24446f23b98ec3f09409a1d4111983d1d64613250ee38c3270e21853`.
  It pins `en_core_web_sm==3.8.0` to wheel SHA-256
  `1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85`,
  size 12,806,118 bytes, and raw model-metadata SHA-256
  `7456349002fa8cf31111051bd37fdbea67a1b7f7a0a60ce235466f98a6758125`.
  The clean-environment `click==8.3.2` import prerequisite is likewise
  artifact-pinned with its URL, size, and SHA-256.
- Lock loading rejects duplicate keys, non-finite JSON, unknown or missing
  fields, loose versions, credential-bearing or non-HTTPS URLs, unbounded
  artifacts or smoke input, incompatible interpreter/platform selectors,
  mismatched smoke digests, incomplete full-pipeline components, and any
  safety policy that permits fallback, corpus access, frozen-input mutation,
  or in-run installation.
- `scripts/benchmarks/provision_hssl_spacy.py` creates or verifies only an
  explicit detached virtual environment. It refuses current-environment
  mutation, active-run markers, frozen result namespaces, and repository
  evidence/data destinations. It downloads atomically into an explicit cache,
  checks size and SHA-256 before installation, installs the selected spaCy
  wheel and model wheel without a mutable `spacy download` lookup, runs
  `pip check`, then launches the probe with isolated Python.
- The probe requires exact spaCy/model distribution versions, model package,
  effective name, language, raw metadata digest, enabled component order,
  disabled `senter`, and DEP/ENT_IOB/LEMMA/POS/SENT_START/TAG annotations.
  `requested_identity` and `effective_identity` must be identical and name
  `en_core_web_sm`; `spacy.blank:en`, the regex/legal parser, fallback flags,
  missing annotations, and metadata/component/version drift all fail closed.
- The fixed smoke is a 47-byte non-corpus sentence. Its canonical receipt
  contains the input digest rather than text, bounded annotation/count
  evidence, locked artifact identities, requested/effective identity, explicit
  no-corpus/no-fallback/no-routing-mutation safety flags, and a recomputable
  receipt digest. A live Linux/aarch64 CPython 3.12 detached provision and
  probe passed with all six annotations, one sentence, nine tokens, two
  entities, requested equal to effective, and no fallback. The canonical
  receipt digest was
  `1879cbe401d89530458534394a502b8832a3ff769ec9d927ed5059474ce7ae4a`.
- `tests/integration/benchmarks/logic_pipeline/test_spacy_runtime.py` freezes
  the selected lock digest and artifacts, validates both platform selectors,
  exercises strict/tamper/offline checks, proves the isolated subprocess
  boundary, rejects identity/fallback/component/annotation drift, recomputes
  receipt identity, verifies orchestration and active-run refusal, and checks
  destination isolation. The existing unit adapter suite independently proves
  that full-model mode cannot silently become its blank fallback.
- The original v1 baseline, capability inventory, front-end report, pilot,
  holdout, final decision, protocol, reviewed corpus, variants, prompts,
  policies, thresholds, and selection inputs were not modified. This repair
  authorizes only a later fresh capability probe under HSSL-G120; it supplies
  no retrospective efficacy measurement and no production promotion.

## Validation

Required command:

```text
python -m pytest tests/integration/benchmarks/logic_pipeline/test_spacy_runtime.py tests/unit/benchmarks/logic_pipeline/test_spacy_adapter.py -q
```

Result: passed, 26 tests. The suite covers the exact lock and artifact
identities; full pipeline and fallback policy; strict JSON/schema validation;
platform selection; offline/tamper failure; detached isolated probing;
version, identity, fallback, component, and annotation drift; canonical
receipt validation; pre-run orchestration; active-run refusal; and the
existing spaCy linguistic adapter contract.

Additional live validation provisioned the locked wheels into a new detached
CPython 3.12 virtual environment, loaded `en_core_web_sm`, and produced the
passing receipt summarized above. Python bytecode compilation of the
provisioner and lock-digest validation also passed.

The broader logic-pipeline unit/integration run passed 432 tests and reported
seven existing baseline-runner failures because the frozen v1 manifest
correctly detects that recorded submodule gitlinks differ from this worktree.
That source-reconciliation condition predates and is outside this runtime
repair; HSSL-BENCH-034/HSSL-G113 owns reconciling it in a new run namespace.
This task did not weaken the manifest check or rewrite the immutable v1 source
snapshot to make those tests pass.

## Backlog alignment

HSSL-G110 remains one cohesive bounded runtime identity/provisioning goal.
Artifact selection, detached installation, full-pipeline identity, smoke
evidence, fallback refusal, and immutable evaluation boundaries form one
indivisible pre-run trust boundary, so no smaller child goal or output/parent
refinement is needed. HSSL-G120 separately owns the new-run capability reprobe
after all requested runtimes are repaired. Generated todo-vector,
objective-bundle, and task-status metadata remain supervisor-owned and were
not edited manually. The supervisor can reconcile HSSLEV1103A41 from the AST
symbol, pinned lock and digest, provisioner, integration suite, objective heap,
this discovery receipt, and required validation receipt.
