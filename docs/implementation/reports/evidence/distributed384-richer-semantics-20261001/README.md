# Explicit native interpretations — 2026-10-01

These runs add explicit typed interpretations to unchanged native models and
replay one prediction from each existing distributed 384d checkpoint. The new
context closes previously unsupported declaration dependencies. It is authored
development evidence: no model training, new weights, holdout evaluation, source
correctness result, or benchmark performance improvement is claimed.

The [exact summary](summary.json) records every authority, admission,
qualification and source-fidelity flag as false. The tested implementation is
[`39df567b`](https://github.com/endomorphosis/ipfs_datasets_py/commit/39df567b00569b90a064e2a40f0c015c71172a10).
[Producer verification](producer-commit-verification.json) matches all 414
producer/tool hashes collected across six native receipts to that commit's Git
objects and the installed tool binaries. The run results and 862-test total
below describe this tested source.

Concurrent upstream commit
[`df732e8a`](https://github.com/endomorphosis/ipfs_datasets_py/commit/df732e8aaf5b4eec7373f1581e7193d7c0a91134)
was subsequently merged at
[`337e659e`](https://github.com/endomorphosis/ipfs_datasets_py/commit/337e659e3b309ee8ca0bf6ea88fe9d33053371ef).
An affected-integration suite passed **269 tests in 241.26 seconds** on this
merge; see [post-merge validation](postmerge-tests.log). Those tests overlap the
original suites and are not added to the 862-test total. They do not retroactively
change the source identity of the archived runs.

## Identical models with additional interpretation evidence

Both authored SecurityIR runs use the same source, candidate, native model
declarations and native projection report. The second context adds explicit
interpretation bindings; it does not replace the original models with easier
fixtures. Their context digests therefore differ. Both reports retain native-report
SHA-256 `5ab298db446f6f29e129fa491a935c5bcdf6b93b842d27c9d807b6fe596d8844`.

| Original native declarations | Supported families | Complete native checks | SANY |
| --- | ---: | ---: | ---: |
| Without interpretation bindings | 13/16 | 16/19 | 1/1 |
| With explicit interpretation bindings | 16/16 | 19/19 | 1/1 |

The three newly supported inputs are concurrency, protocol and refinement:

- Concurrency receives explicitly typed integer expressions, source guard and
  effect syntax bindings, store updates, frames, rely/guarantee relations, FIFO
  channel semantics and session action definitions.
- Protocol receives explicit static frames for its observational-equivalence
  claim. Public recipes and their observations have executable semantics.
- Refinement receives mathematical integer types, exact arithmetic state
  predicates, authored before/after edge relations and finite-depth symbolic
  simulation formulas. The original counter declaration, metadata and prose are
  retained; no increment or reset is inferred from an edge label.

The protocol claim is **refuted under the supplied frames**. A public handle
compares equal to the literal `left-observation` in one frame and unequal in the
other. Lean checks the generated refutation. Thus a successful native check here
includes a kernel-checked counterexample; it does not mean the equivalence claim
was proved. General process equivalence remains unverified. Witness search is
bounded, and failure to find a witness would be inconclusive.

## Existing checkpoint inference

Each unchanged checkpoint was actually loaded and used to infer one existing
tuning row from its ID, source text and precomputed embedding. The resulting
candidate received explicit caller-authored context. That context was not
predicted by the autoencoder. All four saved inference outputs are byte-identical
to the preceding checkpoint replay; see the [identity checks](identity-verification.json).

| Domain | Supported selected families | Complete native checks | SANY | Declared dependencies supported |
| --- | ---: | ---: | ---: | --- |
| IntentIR | 9/9 | 19/19 | 1/1 | Yes |
| SecurityIR | 16/16 | 19/19 | 1/1 | Yes |
| UI/UX IR | 9/9 | 10/10 | — | Yes |
| LegalIR | 9/9 | 10/10 | — | Yes |

IntentIR now receives an explicitly authored atomic dispatcher world model for
the exact tuning instruction. This resolves the earlier auxiliary control-flow
dependency without claiming that the checkpoint inferred the world model.
SecurityIR uses the original richer native declarations and explicit
interpretations; protocol provenance is rebound to that row's exact CodeUnit.
The other two domains reuse their previous contexts.

All four runs set `all_requested_dependencies_supported=true` and
`all_requested_native_checks_passed=true` within those declared contexts. They
retain `source_semantics_verified=false`, `context_inferred_by_model=false`,
`proof_authority=false`, `admitted=false` and `qualified=false`. One tuning row
per domain is a replay check, not a reconstruction-accuracy or throughput study.

The checkpoints are unchanged from the
[previous distributed training round](../distributed-384-local-hub-20261001/README.md):

| Domain | Checkpoint SHA-256 |
| --- | --- |
| IntentIR | `a3d8550144bbd10d7a2aebe8da034dbcb0114d3f698c7cdb1ea496a99d7a2308` |
| SecurityIR | `2ca38dfcc05536315fc3e2c0647b710b930ef4066b474061a7b4e5bfb9a258c5` |
| UI/UX IR | `94d535f43fde2c95be0ad794faad85f3f7d4625a05066e244b61cd9ff66d304a` |
| LegalIR | `dc02475b033e1e849e880e3c3cb30e2f2a432e5e54022296e571731d16139543` |

Each checkpoint tree retains its immutable Hugging Face publication reference,
exact inference input/output, context, requested families, report, generated Lean
and execution receipt. No checkpoint files are duplicated or modified here.

## Validation and review scope

The completed suites record **862 distinct passing tests and three skips**.
The [focused log](focused-tests.log) records **117 tests passing in 52.61 seconds**. It covers typed interpretations, exact context binding,
source/candidate replay and real Lake semantic checks. A separate independent
[refinement direction audit](refinement-direction-audit.log) passed **six tests
in 2.44 seconds**: asymmetric forward/backward behavior, rejected false edge
assertions and explicit leading-stutter rejection in both directions. These six
cases are additional to the 117 focused cases. The completed
[broad regression log](regressions.log) records **774 passes and three skips in
390.85 seconds**. Its 35 context/world-model/integration cases also occur in the
focused run; counting them once gives `774 + (117 - 35) + 6 = 862` distinct
passes. The three broader-suite skips are not promoted to passing checks.

Positive checks exercise arithmetic guards and updates, variable frames,
ownership, channel capacity and FIFO order, session actions, dynamic fairness,
integer predicates, resets and stutters. Negative checks reject altered context,
unsupported syntax, false updates and unsatisfiable initial witnesses. A
separate mutation proves that disabling concrete resets invalidates the declared
refinement obligation; another proves that a state-changing silent step consumes
matching budget.

Independent reads of the refinement and concurrency implementations found no
blocking semantic-loss issue within their supported fragments. Their scope is
deliberately explicit:

- Concurrency's `declaredSpecification` combines execution, fairness,
  interference and rely/guarantee. Linearization obligations, finite schedules,
  channel operations and session graphs remain separate definitions. Channel
  state is not coupled to component stores, session execution is not linked to
  component steps, and global history-based linearizability is not proved.
- Session action-graph duality is emitted; the native parser also validates
  opposite roles and matching entry actions before lowering.
- Refinement supports explicit trailing stutters and bounded directional
  simulation over symbolic integer stores. Leading stutters, opaque relational
  couple constraints and unbounded refinement remain unsupported. Its general
  simulation propositions are generated without asserting their truth.

Lake compilation checks declaration syntax and typing. The explicit theorem
tests establish only their stated consequences within supplied models. SANY
performs syntax, semantic and level checks; no TLA+ model checker was executed.
None of these checks establishes that authored context faithfully models the
source software.

## Immutable archive and reproduction

[evidence.tar.gz](evidence.tar.gz) contains 67 regular files: the full completed
`run-01/` tree, exact `reproduce.py`, completed run log, and all 11 historical
inputs that the reproducer reads through `--prior-evidence`. Its SHA-256 is
`88318499031660a7ccb2a69cb3a999ea0cdd6b82df69a71487f05730f863fd5a`.

[artifact-manifest.json](artifact-manifest.json) records every member hash and
size, plus the copied summary, script and completed test log. The archive is
deterministic: sorted USTAR regular-file members, mode `0644`, zero timestamps
and owner IDs, empty owner names, and a gzip header with zero time and no
filename. Two independent serializations were byte-identical, and every archived
member was checked against its original bytes.

Extract it and run the [exact reproducer](reproduce.py) from the matching full
datasets checkout, including its test fixture modules:

```bash
PYTHONPATH=. python /path/to/extracted/reproduce.py \
  --prior-evidence /path/to/extracted/prior-evidence \
  --training-round /path/to/previous/distributed384/run-01 \
  --output /tmp/richer-semantics-fresh-replay \
  --lake /path/to/lean4-4.34.1/bin/lake \
  --java /path/to/java17/bin/java \
  --sany-jar /path/to/tla2tools-1.8.0.jar
```

The output directory must be fresh. The prior context/baseline inputs are
self-contained in this archive; the previously published training round's
coordinator data and merged checkpoints remain required external inputs. That
round's `merged-result.json` must resolve its checkpoint path on the replay
machine. Existing reports contain historical paths and are not live replay
handles. Installed tools and the matching code are required; tool hashes and
producer hashes are retained in the receipts.

## Hugging Face publication

The evidence was uploaded beside the existing checkpoints in all four model
repositories. Each content-addressed manifest identifies the tested
implementation and immutable parent checkpoint. Uploaded manifests, evidence
archives and their members were downloaded at the new immutable revisions and
verified; the parent checkpoint references were also verified. Checkpoint
weights and defaults were unchanged.

These per-domain publication archives contain the corresponding checkpoint
replay evidence; SecurityIR also includes the authored comparison. They are
separate from the complete 67-file local archive above.

- [Publicus/intent-ir-autoencoder](https://huggingface.co/Publicus/intent-ir-autoencoder/blob/672a84cf34f30748e7fde7ef2d6a9378728c9e20/training/structured384/fd9d9b655650583be0d76972ac3b9c67905628294ba2df38ef59fb6d1c8b1fc5/projection-checks/fe0565ce508a6b637343bb0f34629aca164bfb47e05ee06d5b3583f303ae89e2/manifest.json) — revision `672a84cf34f30748e7fde7ef2d6a9378728c9e20`.
- [Publicus/security-ir-autoencoder](https://huggingface.co/Publicus/security-ir-autoencoder/blob/22ce0b82bab60d1c330b590051a5c6b4de8d2f9b/training/structured384/fcab87ade962350c30a3e80d2f7bd3385d60bcfc666e0ba74955ca8e4008074c/projection-checks/432ed85d74e0985b34ad0d9c73188eab42532862be0b08a511875bd0ab97e66d/manifest.json) — revision `22ce0b82bab60d1c330b590051a5c6b4de8d2f9b`.
- [Publicus/ui-ux-ir-autoencoder](https://huggingface.co/Publicus/ui-ux-ir-autoencoder/blob/5f2b0841ddec180767293c763326493e13416e8d/training/structured384/20c621da5b717eb7fb8174df991efb593bcd846e0d68a3edd62f3151ae041157/projection-checks/618dbcccbb2d5b6279d78e40e7d511b361a79dab65f03c1804ce59dcdb66c142/manifest.json) — revision `5f2b0841ddec180767293c763326493e13416e8d`.
- [Publicus/legal-ir-autoencoder](https://huggingface.co/Publicus/legal-ir-autoencoder/blob/51c21af74109d375560d715363019c4c853dc831/training/structured384/0a70e2ca59bb14791ae52ba8cd5253dc66bf7b2ae20fa23908a3bd1f9410d1e5/projection-checks/ff8f5624ac8a11923dd418c39e976368fb6ca6e0584047316fe253aadf84c104/manifest.json) — revision `51c21af74109d375560d715363019c4c853dc831`.

[Publication receipts](publication/receipts.json), the per-domain manifests and
receipts under `publication/`, and the [append-only publisher](publish_evidence.py)
are retained here. Publication records preserve the experimental, non-authoritative
scope and do not promote these checks into training qualification or source
correctness claims.
