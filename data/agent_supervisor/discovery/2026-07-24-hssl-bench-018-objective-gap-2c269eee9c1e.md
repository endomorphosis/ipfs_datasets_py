# HSSL-BENCH-018 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-018
Goal: HSSL-G040 — Freeze and measure the current baseline
Missing evidence: HSSLEV0404E6E
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-018-objective-gap-2c269eee9c1e.md`
Source fingerprint: `2c269eee9c1e80ae6d4910849ae31e7e85605f90`

## Evidence

- `benchmarks.logic_pipeline.runner.HSSLEV0404E6E` is the stable AST evidence symbol for the A0 freeze-and-measure boundary.
- The canonical frozen manifest is stored at `workspace/benchmarks/hammer-symai-spacy-leanstral/a0-baseline-v1/state/baseline-manifest.json` and is code-pinned by SHA-256 `6b37a6493d6328102b558258843218128ad0bf6f8cc7be13f8d0c2e0bb61e156`.
- The manifest binds the pre-run repository commit, all recorded submodule gitlinks, byte digests for the current production codec and spaCy encoder, frozen protocol and corpus identities, the exact ordered ten-case pilot membership, and the complete requested `ModalLogicCodecConfig`.
- Requested and effective identities remain separate. A0 requested `en_core_web_sm`; this snapshot observed spaCy 3.8.14 using `spacy.blank:en` with the `sentencizer`, and records `spacy_used_fallback_model=true` as degraded capability evidence rather than silently relabeling the arm.
- Cold and warm modes have separate validated `RunContract` cache namespaces. The measurement contract requires one content-addressed `CaseResultRecord` for each eligible case in each mode, for twenty total records, with the complete telemetry schema on every executed stage.
- A0 invokes only the existing composite `DeterministicModalLogicCodec.encode` entry point. SyMAI, Hammer, and Leanstral are explicitly outside the frozen route. Results never claim verification without a native kernel receipt.
- Validate-only is read-only and dependency-free. Normal execution imports the production codec lazily, retains every failure as a case result, writes only under an isolated selected output root, and fails closed rather than overwriting an existing measurement.

## Validation

```text
python benchmarks/logic_pipeline/runner.py --variant A0 --split pilot --validate-only
python -m pytest tests/integration/benchmarks/logic_pipeline/test_baseline_runner.py -q
```

The focused integration suite covers canonical and content digest validation, source/corpus/configuration tampering, immutable pilot order, cold/warm isolation, explicit spaCy fallback identity, read-only CLI behavior, out-of-route exclusion, twenty-result cardinality, complete telemetry, strict result round trips, retained infrastructure failures, and overwrite refusal.

Results:

- Required validate-only command: passed and reported the pinned manifest digest, ten pilot cases, and both cache modes.
- Complete logic-pipeline benchmark suite: 249 tests passed.
- Real A0 replay against the frozen production entry point in a disposable output root: twenty results emitted (ten cold and ten warm), twenty `not_verified`, `spacy_fallback_observations=[true]`, and no out-of-route component invoked.
- Python bytecode compilation: passed. The optional `ruff` executable was not installed in this environment.

## Backlog alignment

HSSL-G040 is a cohesive baseline snapshot and does not need a smaller child goal. The existing HSSL-G050 child owns the broader ablation scheduler and resume/randomization behavior. Generated todo-vector, objective bundle, and task status remain supervisor-owned and were not edited manually; this receipt and the objective-heap evidence allow the supervisor to reconcile HSSLEV0404E6E from code and validation.
