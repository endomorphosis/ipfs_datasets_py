# Source-derived finite states — 2026-10-02

The supervisor's source-program advice path consumes the existing SecurityIR
checkpoint, checks its unchanged prediction against the source, derives a
bounded return-state model, and checks that model against native ProgramIR
execution in Lean. This evidence exercises that advice path, rather than a full
supervisor-daemon or Terminal Bench lifecycle. It contains one existing tuning
example and separate authored arithmetic controls, with no new holdout accuracy
or Terminal Bench performance measurement.

The [exact summary](summary.json) records no training, new weights, source Python
execution, provider calls, admission, qualification or proof authority.

| Population | Candidate origin | Candidates checked | Finite input cases | Lake | SANY |
| --- | --- | ---: | ---: | ---: | ---: |
| Existing tuning example through supervisor advice | Loaded published checkpoint | 1/1 | 9 | 1/1 | 1/1 |
| Direct-return arithmetic controls | Authored | 9/9 | 81 | 9/9 | 9/9 |
| Temporary-then-return arithmetic controls | Authored | 9/9 | 81 | 9/9 | 9/9 |

The supervisor's v2 configuration requests Lake only. The reproducer then passes
the unchanged supervisor prediction to a separate datasets gate, which performs
the listed SANY check and another Lake build over the same derived model.

The 18 authored controls cover `+`, `-`, `*`, `<`, `<=`, `>`, `>=`, `==` and
`!=`, with two integer parameters ranging independently from −1 through 1.
Their 162 cases are not learned predictions. The checkpoint's nine cases come
from one existing tuning row, `v3:security_ir:0:3:0:0`, whose source is retained in
[checkpoint-source-inputs.json](checkpoint-source-inputs.json). Its embeddings
were recomputed using the locally cached, pinned 384-dimensional GTE-small
assets. The source state is derived deterministically from the source-qualified
candidate; the model does not predict the input domains or state table.

## Initial failure and corrected replay

[Run 01](run-01-supervisor-advice.json) failed open during checkpoint loading,
before inference. The strict loader rejected implementation pin drift. Diagnosis
identified exactly one changed dependency: the unrelated UI/UX decoder changed
from `d7be6bff3a1f1464d4783567b90942258ef718bc1c2b7e02938698ed4e619e57`
to `21e8315b0054f7755512212d610d4e3f5f4ac86387f3b27edb9632fa8ca68bc3`.

Run 02 uses the explicit Security-only compatibility loader. Every other
implementation field must match. It changes only that pin in a detached runtime
view and passes the view through the original complete runtime validation.
Original artifact bytes, numerical weights, target schema and split manifests
remain unchanged. Unknown revisions, Security or numerical drift, malformed
checkpoints and leakage still fail. The old strict loader remains unchanged.

The [compatibility receipt](checkpoint-compatibility.json) distinguishes the
immutable artifact from its runtime view. The supervisor independently reloads
the original bytes to verify the receipt and requires matching description and
inference receipts. Regression tests also replay an archived precomputed vector
and reproduce its exact candidate, predicted classes and projected embedding.

The existing checkpoint SHA-256 is
`2ca38dfcc05536315fc3e2c0647b710b930ef4066b474061a7b4e5bfb9a258c5`.
Its [original publication reference](published-checkpoint-reference.json)
identifies `Publicus/security-ir-autoencoder` at immutable revision
`84ea9a8877989d9bde21e0cee5868c936fc184a9`. No checkpoint was retrained or
replaced in this work.

## What the checks establish

Each supported function has two explicitly annotated integer parameters, one
supported binary operation, and either a direct return or one fresh temporary.
Explicit caller intervals enumerate all permitted inputs, up to 64 cases;
unsupported source, predictions and domains remain visible. One action represents
a complete scalar function return. It preserves inputs and updates only the
output observation and returned flag. The pending output sentinel never
initializes a source local or result slot.

The generated Lean theorems check every concrete ProgramIR return, actual local
assignments, complete input-domain coverage, initial-state witnesses, and
correspondence of every native or bounded transition with ProgramIR execution.
Additional theorems establish that returned states have no outgoing native or
bounded transitions. Unused source-store fields remain universally quantified.
Mutation tests make real Lake builds fail for incorrect arithmetic, output
relations, initial states and return guards.

These are bounded model-correspondence proofs under the source adapter's stated
mathematical-integer assumptions. They do not establish Python runtime
equivalence, an inferred security policy, Intent-goal compliance or liveness.
SANY parses and performs semantic/level checks on the same TLA+ model; TLC did
not run. TLA+ specification stuttering remains distinct from the nonstuttering
native action relation. No throughput, token-saving or benchmark-score
improvement is claimed.

## Validation and implementation identity

There are **333 distinct passing tests** across the datasets and supervisor
suites:

| Saved log | Passing tests | Counting rule |
| --- | ---: | --- |
| [Source-state and integration suite](source-state-tests.log) | 205 | Count all |
| [Compatibility and existing runtime suites](compatibility-tests.log) | 121 | Count 52 new compatibility tests; 69 overlap the first suite |
| [Supervisor consumer suite](consumer-tests.log) | 76 | Count all; includes actual checkpoint, cached GTE and Lake checks |

The tested datasets implementation is
[`e8cc16612328f7c76d066cf003ffc25d62aa63e8`](https://github.com/endomorphosis/ipfs_datasets_py/commit/e8cc16612328f7c76d066cf003ffc25d62aa63e8).
Upstream commit `06c45edbd7a4d82c2217bb9bf28d42fa1cf20b28` was merged at
[`04044260129055fa19824bc8f91c1673fdb44145`](https://github.com/endomorphosis/ipfs_datasets_py/commit/04044260129055fa19824bc8f91c1673fdb44145).
That upstream change adds 13 files and preserves the captured producer bytes.
[Post-merge validation](postmerge-tests.log) passed **69 tests in 9.27 seconds**.
These repeat 52 compatibility and 17 gate tests and are not added to the
333-test total. The tested supervisor implementation is
[`037b71444ca2434bcc4b95323c2e9f56bee536e6`](https://github.com/endomorphosis/ipfs_accelerate_py/commit/037b71444ca2434bcc4b95323c2e9f56bee536e6),
whose datasets gitlink selects the `04044260` merge.

All four required supervisor documentation-workflow checks passed locally on
that supervisor commit with Python 3.12.3: primary-document vocabulary,
maintained-surface relative links, packaging version alignment, and closeout
navigation markers. See [the exact log](documentation-gates.log).
The [remote GitHub job](https://github.com/endomorphosis/ipfs_accelerate_py/actions/runs/36947751715/job/110653589745)
did not execute any steps because the account was locked for a billing issue.
Remote CI is therefore infrastructure-blocked, not a passing CI result.

[producer-sources.json](producer-sources.json) records 47 loaded advisor and
inference module hashes: 45 datasets modules and two supervisor modules. Each
of the three standalone native receipts separately pins 44 native producer
files and four selected tool binaries. Those pins are not a complete operating
system, Python-package or toolchain-library capsule. Generated dataclass methods
and external libraries remain outside the limited loaded-code checks.

## Files and reproduction

[source-provenance.json](source-provenance.json) records the authored public
fixture, original training and tuning file identities, checkpoint lineage and
embedding asset hashes. This is not training on the full CVEfixes, SkillCenter
or US Code corpora.

[reproduce.py](reproduce.py) is copied exactly from the completed run. It requires
the matching datasets and supervisor checkouts, the original Security training
round metadata and checkpoint, cached pinned GTE-small assets, native Lake, and
Java 17 or newer with the local `tla2tools` JAR. It performs no downloads and
requires a fresh output directory:

```bash
python reproduce.py \
  --training-round /path/to/security_ir/training-round \
  --output /path/to/fresh-output \
  --lake /path/to/native/lake \
  --java /path/to/java17 \
  --sany-jar /path/to/tla2tools.jar
```

[run-02-artifacts.json](run-02-artifacts.json) binds the complete source artifact
tree by relative path, byte size and SHA-256. [artifact-manifest.json](artifact-manifest.json)
binds the copied files in this documentation directory. The reviewed full-run
archive has 39 members, 673,012 bytes and SHA-256
`198a1a65d4cf2e8e8c9e319b8a6b1105b2bc08b0e0eb846f7f834736d53fea77`.
The [exact archive](publication/evidence.tar.gz),
[manifest](publication/manifest.json) and [receipt](publication/receipt.json)
are copied from the reviewed publication without rebuilding the archive.
The publisher verified all 78 tested source-file hashes against the declared
Git objects: 76 datasets files and two supervisor files.

The evidence is published at immutable Hugging Face revision
`e4534069a154ae302ec176535931264a1e12d540`:
[published manifest](https://huggingface.co/Publicus/security-ir-autoencoder/blob/e4534069a154ae302ec176535931264a1e12d540/training/structured384/fcab87ade962350c30a3e80d2f7bd3385d60bcfc666e0ba74955ca8e4008074c/source-state-checks/9a0ada627e73014ed3f7fdc58bc94586d45895e5bb549992a52edc332ed13b01/manifest.json),
[published archive](https://huggingface.co/Publicus/security-ir-autoencoder/resolve/e4534069a154ae302ec176535931264a1e12d540/training/structured384/fcab87ade962350c30a3e80d2f7bd3385d60bcfc666e0ba74955ca8e4008074c/source-state-checks/9a0ada627e73014ed3f7fdc58bc94586d45895e5bb549992a52edc332ed13b01/evidence.tar.gz).
The upload receipt records successful download verification of both the evidence
and the immutable original-checkpoint reference. Publication adds evidence;
it does not upload new model weights or promote a checkpoint.
Saved receipts are historical evidence and cannot impersonate live issued
verification handles.
