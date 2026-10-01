# Preserved linguistic training validation — 2026-10-01

The old 8D linguistic feature path trains and resumes independently of the
experimental latent-to-formula implementation. Its historical semantic errors
remain visible; this is operational validation, not legal qualification.

Implementation commit: `09105a738f652844a4dd6ae3a9003bc46c695c18`.
The [training guide](legacy_linguistic_training.md) documents the public API,
checkpoint contract and repeatable smoke command.

## Verification

**125 tests passed in 16.49 seconds** against an isolated Git export of that
exact commit. Coverage includes the new linguistic profile and audit,
both legal lineages, historical streamed norm accounting, and existing joint
formula-head tests. Real original-versus-wrapped projection training produced
identical accepted sparse states. The historical numerical snapshot is unchanged;
the supplemental codec has exactly four dependency-import relocations.

The release smoke took **8.966 seconds** for both backend profiles. Each used
five authored spans for observation, one training span and one disjoint tuning
span. Each accepted the initial epoch, a second uninterrupted epoch and its
resumed counterpart. Complete states and predictions matched on reload and
resume. A separate fresh process reproduced all ten first-epoch predictions.
No experimental formula-training module loaded during the smoke.

The actual retained 398,209,746-byte teacher also loaded under the explicit
blank-English profile and produced finite 8D outputs plus linguistic IR for two
authored spans. SHA-256 remained
`7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be`;
file identity and timestamps were unchanged. Load time was 15.087 seconds and
peak RSS 2.03 GiB. That was read-only compatibility testing, without teacher
training. The selected linguistic configuration is an explicit assumption;
the checkpoint does not verify its original producer configuration.

## Measurements and scope

| Release measurement | Historical blank English | Local `en_core_web_sm` |
| --- | ---: | ---: |
| Preparation, seconds per span | 0.21484 | 0.22011 |
| Inference, seconds per span | 0.07902 | 0.08778 |
| Bridge-off evaluate, one tuning span | 0.01126 s | 0.00846 s |
| First accepted epoch | 0.29117 s | 0.24421 s |
| Tuning family cross-entropy, before → after two epochs | 0.316035 → 0.315307 | 0.316035 → 0.315308 |

Configuration: CPU, `python_sparse_batch`, four update families, one line-search
attempt, 30-second cap per training call; bridge names `[]`, external provers
false, one bridge worker, metric disk cache disabled, sample memory false,
temperature zero. `legal_ir_target_count` is zero. **No bridge-on timing was
measured**; these numbers are not a faster legal-IR result or a production
throughput benchmark. The process began cold, but sample preparation preceded
inference and the second backend reused imported dependencies. The concurrent
release test suite also ran on the same host.

Sparse family heads changed: `feature_family_logits`,
`legal_ir_view_family_logits` and `semantic_slot_family_logits`. Reconstruction
MSE was already zero because the deterministic linguistic base equaled the
target; cosine was approximately one before training. Moreover, the original
target-aware safety projection remains enabled. These scores do not establish
learned vector or formula fidelity. This small tuning panel is not a held-out
generalization canary.

## Actual formula findings

The frozen linguistic compiler emits inspectable structured formulas. For
“The agency shall submit reports.” the blank-English profile emits a deontic
operator `{family: deontic, system: D, symbol: O}` and predicate
`submit_reports(actor:agency, scope:submit_reports)`. This is deterministic
linguistic IR, not neural formula generation.

Both preserved backends have these observed limitations:

| Source case | Frozen linguistic result | Separate canonical result |
| --- | --- | --- |
| “shall not disclose records” | Deontic `O`, a prohibition conflict | Correct deontic `F` |
| “within 10 days unless emergency” | Exception retained; quantity `10` absent from explicit formula fields | Deadline and exception retained; `within_duration` stays non-renderable by the Lean threshold renderer |
| “for at least 20 days” | Quantity `20` absent from explicit formula fields | `minimum_duration`, integer quantity 20 and correct rendered text |

The deterministic decompiler reproduces all three source sentences from
provenance despite those formula limitations. The smoke therefore reports one
operator conflict and two quantity coverage gaps per backend, separately from
operational success. Its audit only checks these explicit properties; it is not
a complete equivalence test. The frozen codec was not rewritten to hide its
historical behavior.

All three required canonical gates passed with parser-supplied string atoms;
empty vocabulary still abstained. The same checks passed in the live pinned
workspace and the isolated committed export. No Lake build was run by this
feature smoke, no legal admission was granted, and the Constitution remains
unformalized. The new latent-to-formula head still lacks real legal fidelity
qualification.

## Retained evidence

- [Release summary and sampled full formula ASTs](../implementation/reports/evidence/legacy-linguistic-20261001/release-summary.json)
- [Pinned-workspace comparison](../implementation/reports/evidence/legacy-linguistic-20261001/workspace-summary.json)
- [Fresh-process reload](../implementation/reports/evidence/legacy-linguistic-20261001/fresh-process-reload.json)
- [Retained teacher read-only receipt](../implementation/reports/evidence/legacy-linguistic-20261001/teacher-readonly.json)
- [125-test JUnit receipt](../implementation/reports/evidence/legacy-linguistic-20261001/release-tests.xml)

Summaries retain source hashes, sampled outputs, losses, semantic conflicts and
full-artifact hashes. Detailed receipts remain under
`workspace/test-logs/legacy-linguistic-20261001/`; their large deterministic
decompiler phrase inventories are not duplicated in Git. Nothing was uploaded
to Hugging Face, and the running census service was not restarted.
