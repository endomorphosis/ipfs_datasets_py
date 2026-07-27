# Canonical Compiler Decision (SRT-019)

## Status

**Selected** under `CanonicalCompilerDecision@1`.

| Field | Value |
|-------|--------|
| Decision CID | `baguqeerapxofx7azmhz3qzzplcl46fw3osraruubohvbfwrhezd66thk6u3a` |
| Selected arm | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` |
| Selection basis | `srt015_bounded_tie_policy` (exact replacement co-winner) |
| Parity | passed (UCB high `0.0` ≤ margin `0.03`) |
| Evidence complete | true |

Machine-readable receipt:

`docs/performance_snapshots/semantic_roundtrip_canonical_compiler_decision.json`

## What was selected

The production composition is fully deterministic:

1. **L1 compile** — typed deontic constructor (`CanonicalStructuredTextCompiler@1`)
2. **T1 decompile** — source-withheld deterministic realizer
3. **L2 compile** — same typed deontic constructor on realized text

No optional learned stages are promoted. SRT-014 remains no-eligible
negative evidence; replacement measurement supplies the bounded exact-tie
authorization; SRT-018 proves noninferiority under the frozen SRT-015 policy.

## Reconstruction loss (unchanged replacement uncertainty)

From the replacement composition report arm summary:

- metric: end-to-end loss (lower is better)
- aggregation: per-case-first macro mean
- mean: `0.0883333334`
- 95% case-cluster bootstrap interval: `[0.0383333334, 0.1366666668]`

SRT-018 parity deltas vs this arm are exactly `0.0` on every pilot case.

## Tool accounting

| Class | Tools |
|-------|--------|
| Scored / selected | `typed_deontic`, `deterministic_realizer` |
| Unscored | `modal`, `spacy`, `autoencoder`, `symai`, `leanstral`, `selective_repair`, `hammer`, `cvc5`, `lean`, `multiformats` |
| Unavailable | _(none)_ |

## Bound artifacts

Paths and raw CIDs are sealed in the decision receipt `artifacts` map,
including:

- replacement composition report (selectable exact-tie evidence)
- SRT-015 parity policy
- SRT-016/017 compiler and decompiler modules
- SRT-018 round-trip module and parity report
- IR schema and architecture specification

## Reproduce

```bash
# Validate replacement composition report
PYTHONPATH=. python benchmarks/bench_semantic_roundtrip_compositions.py \
  --validate-report docs/performance_snapshots/2026-07-27_semantic_roundtrip_composition_replacement.json

# Schema / contract tests
PYTHONPATH=. python -m pytest tests/unit/logic/legal_ir/test_canonical_roundtrip_schema.py -q

# SRT-018 parity integration
PYTHONPATH=. python -m pytest tests/integration/logic/test_canonical_semantic_roundtrip.py -q

# Validate this decision (fail-closed)
PYTHONPATH=. python benchmarks/bench_semantic_roundtrip_compositions.py \
  --validate-canonical-decision \
  docs/performance_snapshots/semantic_roundtrip_canonical_compiler_decision.json
```

Supervisor handoff (plan / launch only; no silent deployment):

```bash
PYTHONPATH=. python benchmarks/semantic_roundtrip_scheduler.py plan
PYTHONPATH=. python benchmarks/semantic_roundtrip_scheduler.py launch
```

## Limitations

- Production default compiler mode remains `allow_explicit_partial=False`
  (stricter than the measured arm). Measured parity runs must use
  `measured_parity_compiler_request`.
- Orchestrator `SUCCESS` means sealed stage completion only; semantic admission
  is the parity report / decision receipt.
- Structural Hammer/cvc5/Lean checks are not applicable for this deterministic
  arm and are recorded as such on the SRT-018 parity report.
- The selected arm is a bounded co-winner, not a unique semantic superior.
