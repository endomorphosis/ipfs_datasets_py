# Explicit Intent/code effect contracts — 2026-10-02

This development check connects selected native Intent preconditions and effects
to bounded code-state observations through an explicit caller declaration. The
instruction and code remain separate sources, with unchanged candidates and
independent hashes. It exercises the supervisor's optional advice path, not a
full supervisor-daemon or Terminal Bench lifecycle.

The positive contract fixtures use authored native Intent documents paired with
an actual SecurityIR checkpoint prediction. The separate learned-Intent path
must abstain when its predicted action lacks effects; no effect is inserted to
make the contract pass. Security uses the existing published **384-dimensional**
checkpoint. Intent uses an existing local **paired-text round-trip** checkpoint;
this is not a test of a published 384-dimensional Intent checkpoint.

The completed [run-03 summary](summary.json) records the following populations.
Security embeddings were recomputed on CPU from the cached GTE-small assets.
The three authored interpretations reuse the same unchanged predicted addition
function and the same nine input combinations; their 27 condition evaluations
are not 27 independent learned examples.

| Population | Cases retained | Enabled cases | Lake result | Contract result |
| --- | ---: | ---: | --- | --- |
| Authored matching Intent effect | 9 | 9 | Passed | Satisfied within explicit bounds |
| Authored conflicting Intent effect | 9 | 9 | Passed | Counterexample checked; refuted |
| Authored impossible precondition | 9 | 0 | Passed | No enabled instances; not satisfied |
| Actual learned Intent plus actual Security prediction | One selected contract | Not evaluated | Not invoked | Fail open: learned action has no declared effects |

The learned instruction is `the agent may delete the report.` Its actual
prediction has one action and zero effects. The [consumer advice](learned-contract-advice.json)
preserves that candidate and returns `fail_open_no_supported_contracts` with the
specific missing-effects reason, while allowing existing planning to continue.
It does not infer a relationship between this instruction and the addition
function. The explicit attempted association does not make the missing effect
exist. The tested learned action supplies no effect contract; this run does not
establish coverage for other prompts or checkpoints.

## What the checks establish

The owner requires an exact association between the selected native action's
complete precondition/effect sets and typed expressions over four code-state
variables: two inputs, a result observation, and a returned flag. Expressions
can refer explicitly to old and current state. The carrier uses the code's exact
native source references; the Intent document and its source references stay
separate. This association is an authored interpretation, not an inferred
translation of natural-language meaning.

Every input combination in the caller's bounded integer domains is retained,
including disabled preconditions and false effects. Lean checks the existing
ProgramIR/state-transition correspondence, each declared condition value, and
one of three distinct outcomes:

| Outcome | Kernel obligation | Positive contract satisfaction |
| --- | --- | --- |
| Satisfied | Every enabled transition satisfies the effects, with an actual enabled initial-state witness | Yes, within the declared finite interpretation |
| Refuted | An initial-state transition, its ProgramIR outcome, and an enabled false effect form a counterexample | No |
| No enabled cases | Every transition has a false precondition; no enabled instance exists | No |

A compiled counterexample remains a refutation. Zero enabled inputs cannot
produce a positive contract result. Unsupported contracts remain in the batch
denominator. The live gate replays original inputs and emitted declarations,
checks imported producer identities and Lake/Lean binaries, and accepts only a
process-local issued execution handle. Saved receipts are historical evidence.

These checks cover the supported two-integer scalar source fragment and the
selected action's declared conditions. They do not establish Python runtime
equivalence, whole-instruction meaning, complete workflow correctness, security
policy compliance, LegalIR/UIUXIR constraints, or task completion. Other native
Intent declarations are retained without being claimed as verified. No source
Python is executed and no proof or execution authority is granted.

## Validation

There are **263 distinct passing tests**: 124 datasets tests and 139 supervisor
tests, with the corrected rerun accounted for below.

| Saved log | Result | Counting rule |
| --- | --- | --- |
| [Datasets tests](datasets-tests.log) | 124 passed in 97.58 seconds | 95 new owner/emitter/gate cases and 29 existing world/state-gate regressions |
| [Initial supervisor tests](consumer-initial-tests.log) | 135 passed, 4 failed | The four failures were a test-fixture package-import collision |
| [Corrected native supervisor tests](consumer-corrected-native-tests.log) | 4 passed in 10.95 seconds | Count these four once; test-only import correction, no production change |

The tests cover all nine supported arithmetic/comparison operators with direct
and temporary returns, one-case and 64-case boundaries, disabled false effects,
`old(...)` semantics, exact source/candidate/association identities, and missing
effects. Actual Lake mutations reject changed arithmetic, state mappings,
preconditions, reported case verdicts, source operations, and old/current
observations. Consumer tests retain fail-open behavior and detect source or
native task changes around optional advice.

All four required supervisor documentation checks passed locally with Python
3.12.3: primary-doc vocabulary, maintained relative links, packaging version
alignment, and closeout navigation markers. The [exact log](documentation-gates.log)
records command outcomes and unchanged working-tree file hashes. No remote CI
success is inferred from these local checks. The
[remote documentation job](https://github.com/endomorphosis/ipfs_accelerate_py/actions/runs/36951226013/job/110664403264)
for supervisor commit `6feb1173` ran no steps: GitHub reports that the account is
locked due to a billing issue. This is an infrastructure-blocked CI result, not
a code-test failure or a passing remote check.

Independent read-only review found no blocking semantic or integrity defect in
the gate, emitter, supervisor consumer, or task-context hook. The standalone
consumer validates supplied Security inference identity; it does not independently
repeat numerical Security inference. The task-context hook supplies freshly
prepared Security advice and rechecks its existing source/Intent owners. Code
pins exclude Python, external libraries, generated methods and full toolchain
libraries; they are not a complete environment capsule.

## Preserved initial failures

[Run 01](run-01-failure.log) failed before successful Security inference because
CUDA could not allocate memory. Its [advice](run-01-security-advice.json) records
`fail_open_unavailable` at `embedding_and_inference`. A subsequent correctness
replay selected CPU; it is not a throughput comparison.

[Run 02](run-02-failure.log) reached contract preparation but retained a stale
canonical ID after changing the authored expression carrier's code source
references. The [receipt](run-02-blocked-receipt.json) rejects all three contracts
with `program_id does not match canonical program semantics`. This is a
reproducer-fixture error, not a change to the learned Security prediction.

## Implementation identity and reproduction

The tested datasets implementation is
[`4e70da8ef06331b5368cf574dce4d16a4b6fa8dd`](https://github.com/endomorphosis/ipfs_datasets_py/commit/4e70da8ef06331b5368cf574dce4d16a4b6fa8dd),
preserving concurrent upstream `6589f7887` in its ancestry. The tested supervisor
implementation is
[`6feb1173584714eadf9cb9cafc7671aa0f4f9a10`](https://github.com/endomorphosis/ipfs_accelerate_py/commit/6feb1173584714eadf9cb9cafc7671aa0f4f9a10).

Security consumes the unchanged published checkpoint with SHA-256
`2ca38dfcc05536315fc3e2c0647b710b930ef4066b474061a7b4e5bfb9a258c5`.
The [Intent checkpoint reference](intent-checkpoint-reference.json) separately
identifies the local `intent-roundtrip-package/v1` manifest
`e3a534ee7f2f0967bbba0ddf760d95ec347dff78358d750ed44cc0be020fa2f8`
and its `shared-paired-text-autoencoder/v1` backend weights
`699bf438f5340b23eb86fb78d77991a42fa91d8b84cbc8a0ae3e42799382d86d`.
The reproducer checks descriptor, manifest, backend and Security checkpoint
bytes before and after inference. No weights change.

[producer-sources.json](producer-sources.json) captures 245 imported module file
hashes: 240 datasets modules, four supervisor modules and the authored fixture
test module. The native receipt separately pins 99 producer files and the Lake
and Lean binaries. These inventories have the limited pin scope described
above; they do not claim full environment reproducibility.

[reproduce.py](reproduce.py) is copied exactly from the completed CPU run. It
requires both matching checkouts, the prior source-state run inputs/configuration,
the original Security checkpoint and cached pinned GTE-small assets, the local
Intent descriptor with its manifest/backend, and native Lake. The descriptor and
prior configuration contain local paths which must resolve to the exact original
artifacts. The run uses a fresh output directory and performs no downloads:

```bash
CUDA_VISIBLE_DEVICES='' python reproduce.py \
  --prior-run /path/to/source-derived-states/run-02 \
  --intent-descriptor /path/to/intent-roundtrip/descriptor.json \
  --lake /path/to/native/lake \
  --output /path/to/fresh-output
```

[run-03-artifacts.json](run-03-artifacts.json) binds all 16 files in the completed
run by path, byte size and SHA-256. The [run log](run-03.log) and
[execution environment](execution-environment.json) record CPU selection for
correctness replay. [source-provenance.json](source-provenance.json) records the
existing authored tuning source and checkpoint lineage; these are development
fixtures, not a new corpus or holdout evaluation.

## Published evidence

The exact reviewed [archive](publication/evidence.tar.gz),
[manifest](publication/manifest.json), and [receipt](publication/receipt.json)
are copied without rebuilding. The archive has 25 members, 287,434 bytes, and
SHA-256 `dc19360caf291c4def2fee82038f073774a91aeac9c1a086fe4456cbd799a6b4`.
The manifest SHA-256 is
`31e86fa58b432d99a80a60396d0d7b6a3976b822c379fba68dbf16e135876caf`.
The publisher matched all 241 datasets and four supervisor source-file hashes
to the declared Git objects. Its [validation log](publisher-validation.log)
also records nine rejected corruption controls; these are not added to the
263-test total. All 25 archived member hashes were independently checked when
copying this evidence directory.

The evidence is published in `Publicus/security-ir-autoencoder` at immutable
revision `9ec76c511c120886e4eff843d8ba4de736acfb38`:
[published manifest](https://huggingface.co/Publicus/security-ir-autoencoder/blob/9ec76c511c120886e4eff843d8ba4de736acfb38/training/structured384/fcab87ade962350c30a3e80d2f7bd3385d60bcfc666e0ba74955ca8e4008074c/intent-code-effect-checks/31e86fa58b432d99a80a60396d0d7b6a3976b822c379fba68dbf16e135876caf/manifest.json),
[published archive](https://huggingface.co/Publicus/security-ir-autoencoder/resolve/9ec76c511c120886e4eff843d8ba4de736acfb38/training/structured384/fcab87ade962350c30a3e80d2f7bd3385d60bcfc666e0ba74955ca8e4008074c/intent-code-effect-checks/31e86fa58b432d99a80a60396d0d7b6a3976b822c379fba68dbf16e135876caf/evidence.tar.gz).
The receipt records successful download verification of the manifest, archive,
all archive members, and the immutable original Security checkpoint reference.
Publication adds evidence only. It does not replace or promote a checkpoint,
and includes no new model weights. The local Intent backend is referenced by
hash and is not included in this upload.

[artifact-manifest.json](artifact-manifest.json) binds every copied evidence
file except itself by relative path, byte size and SHA-256.

No training, new weights, new holdout evaluation, Terminal Bench score, full
daemon run, token-saving result or throughput improvement is claimed. The native
Lean build does not invoke SANY or TLC in this run.
