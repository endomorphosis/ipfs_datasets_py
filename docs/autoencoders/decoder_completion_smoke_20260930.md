# Decoder training and schema Lake smoke — 2026-09-30

This run exercises the installed public interface and CLI, with the canonical
workspace tree pinned. Full model outputs, losses, family formulas, failed
comparisons, checkpoint identities and individual Lake receipts are in
[native-formula-and-schema-smoke.json](../implementation/reports/evidence/legal-lineages-20260930/native-formula-and-schema-smoke.json).

## Native training → DuckDB → inference → Lake

Each domain trained `native_formula_v1` for 35 epochs / 70 Adam updates on two
authored examples, with a two-row tuning panel. The tuning source identifiers
are disjoint but the structures repeat the training structures deliberately;
this is a plumbing/reconstruction diagnostic, not generalization evidence.
CPU float64, one Torch thread, latent width 8, batch size 1, learning rate .04,
seed 1729, and temperature zero were fixed. No model weights were downloaded.

| Domain | Categorical CE before → after | Training wall seconds | Complete CLI wall seconds | Exact tuned projections | Actual Lake builds passed |
| --- | --- | ---: | ---: | ---: | ---: |
| Intent | .699371 → .000788 | .266 | 5.096 | 2/2 | 2/2 |
| Security | .693329 → .000508 | .419 | 6.147 | 2/2 | 2/2 |
| UI/UX | .696538 → .009445 | .268 | 4.807 | 2/2 | 2/2 |

The CLI creates an immutable candidate and checkpoint, then invokes the actual
selected-weight decoder and runs installed Lean4.26.0 `lake build DecoderSchema`
on every emitted native record. The Intent candidate was reloaded from its
registered version and trained for one more epoch; the second registry version
points to its exact numerical parent. All qualification and admission flags
remain false.

## Legal held-out outputs: schema success is insufficient

The previously trained source-only legal checkpoint was loaded unchanged and
received the same 12 held-out source strings. This check did not train or select
weights using them. Decoding plus structural Lake checks took 13.687 seconds.
All 12 outputs passed their structural schema builds; only **11/12** exactly
matched their expected canonical rules.

For “The officer shall retain the file for at least 20 days unless emergency.”,
the decoder retained the minimum duration but dropped the emergency exception.
Both expected and actual rules are retained in the report. That is a semantic
failure despite a successful schema build and the previously low training loss.
The new gate does not mark this output qualified or formalized.

## Eight legal syntax checks

The three existing gate sentences compiled and passed all eight restricted
family syntax checks. Individual compiler wall observations were .169, .047 and
.049 seconds. These are small local observations, **not** a speed comparison or
bridge-on legal-IR measurement. The five metric bridges were not invoked,
provers were off, metric disk caching was not invoked, one worker was used, and
`legal_ir_target_count` was zero. No claim of faster legal-IR evaluation follows.

Full family semantics and schema-capability coverage remain false. In
particular, the CEC/propositional projections disclose omitted deontic meaning;
ordinary predicates do not establish temporal/event/cognitive operator coverage.
The default qualification, retry, distributed-selection and publication paths
now require the separate coverage gate. Historical receipts missing it fail.
Constitution status remains unformalized.

The build projects, logs, CLI commands and checkpoint files remain under
`workspace/decoder-completion-staging/installed-smoke/`. The committed evidence
contains full output observations and source hashes; serialized receipts remain
historical audit data and must be re-executed to establish fresh local evidence.
The run used the shared working tree, which includes pre-existing edits outside
this change. Those files are not swept into this commit.

See [training commands, bounds and remaining implementation gaps](native_formula_training.md).

The [installed validation receipt](../implementation/reports/evidence/legal-lineages-20260930/decoder-completion-validation.json) records **580 passing tests in 84.03 seconds**, including the existing semantic gates, compiler/decompiler pilot, historical lineages, actual Lake builds, source-drift rejection and exact resume.
