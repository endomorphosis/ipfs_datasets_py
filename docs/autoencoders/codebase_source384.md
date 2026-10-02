# Source-conditioned CodebaseIR: experimental scalar profile

`codebase_ir/source_conditioned_384_v1` connects the durable repository source
owner, the shared 384D structured decoder, and the native model registry. Its
implementation is in
[codebase_source_384.py](../../ipfs_datasets_py/logic/software_contracts/codebase_source_384.py).
Accelerate can consume its explicit preparation and inference APIs; neither
admission replay nor a catalog read starts training.

The **384 dimensions describe GTE-small input embeddings**. The envelope is a
CodebaseIR generation, while the numerical payload keeps the existing
`security_ir` checkpoint schema. No LegalIR, IntentIR, UIUXIR or SecurityIR
checkpoint is overwritten. The implementation retains exact original parent
bytes and the existing, narrowly reviewed checkpoint compatibility receipt.
It does not add an untrained fifth domain to the four-domain decoder registry.

## Supported input and training

The initial source profile admits one Python function per selected file, two
explicitly annotated integer parameters, and one supported arithmetic or
comparison expression, optionally assigned to a temporary. The shared source
binding independently checks the complete candidate and native effects.
Annotations are declared assumptions; they do not establish runtime input types
or whole-program equivalence. Unsupported files remain in the structural
inventory and cannot silently become training examples.

`prepare_corpus` reads exact captured CAS bytes. A caller enumerates path, role
(`train`, `validation`, `holdout`) and indivisible group IDs. Labels come from
the reviewed source AST/ProgramIR adapter, never desired intent or unchecked
model output. The split audit adds source hashes, AST clones ignoring locations
and function names, and numerical embedding duplicates. It does not claim to
discover all semantic clones or parameter alpha-equivalence.

`register_shared_parent` preserves the shared checkpoint in an immutable native
registry version. `train_current_source384` creates a leased private child and
performs actual GTE embedding and numerical fitting in a bounded CPU process.
The existing distributed-384 sufficient-statistics implementation refits the
head over the complete declared training round. It retains the projection and
target vocabulary exactly. This is not gradient continuation, FedAvg, recovery
of historical training samples from weights, or a remote training deployment.

Validation selects regularization. Holdout measurements happen afterward and
never select the candidate. Descendants must keep ancestral path/split/group
roles and fixed validation/holdout bytes. Changing that cohort requires a new
lineage. A run has an overall deadline, sampled process-tree RSS limit,
cancellation, bounded messages and a native registry lease. Sampled RSS can
overshoot; this is not kernel memory isolation. Source and model ownership are
separate: source is checked before completion, and consumers must check again.

No child is automatically promoted. A separate qualified owner promotion policy
is still required. Exact head-refit compatibility alone says nothing about
retention or useful generalization.

## Inference and evidence

`infer_current_source384` requires the exact source generation and model lineage,
loads the real weights, embeds target-free source rows, and independently checks
the unchanged predictions. A wrong prediction stays wrong. It cannot be replaced
with the training label or AST-derived answer. Embedding assets, producer bytes,
parent/child numerical relationships and current source are checked during replay.

The resulting candidate can be passed to the existing
`build_decoded_source_program_lake` API. Actual `lake build` success establishes
the emitted program's syntax and typing. It does not establish a security
property, instruction satisfaction, or permission for a supervisor edit.
Those require separately grounded obligations and live checker evidence.

## Local qualification, 2026-10-02

The integration tests use an authored 27-file scalar fixture: nine training,
nine validation and nine holdout functions. The shared parent correctly
reconstructs **9/9 holdouts**. A head refit on the small selected corpus
reconstructs **0/9 holdouts**. The missing parameter-name coverage is a retention
failure; it is recorded and the child is not promoted. This is not a production
benchmark or evidence of an accuracy improvement. These are repository-round
holdouts; independence from all of the parent's pretraining data is not asserted.

Actual child inference reconstructs the three selected arithmetic training
examples. Their source-bound IR compiles with Lean; a zero-head control yields
three source mismatches. Tests also cover exact source/split/clone contracts,
dirty-source refusal, operation replay without refitting, fixed holdout lineage,
original-parent tampering, forged child request bindings and independent-process
historical model replay. Test reports retain the initial failed protocol run,
whose imported diagnostics polluted stdout before being routed to stderr.

To run the actual numerical/prover test, set `CODEBASE384_CHECKPOINT` to an exact
shared structured SecurityIR checkpoint, `CODEBASE384_EMBEDDING_SNAPSHOT` to the
pinned local GTE snapshot, and `CODEBASE384_LAKE` to the native Lake executable:

```sh
python -m pytest tests/integration/logic/software_contracts/test_codebase_source_384.py
```

Without the explicit checkpoint, the numerical test is skipped, and the ordinary
source-contract tests still run. Use `CODEBASE384_REPORT` to retain the JSON
evaluation. The comprehensive RPI backlog still needs a richer source grammar,
independent canary/promotion policy, shared parent replay data, source-successor
learning/reproof, model-dependent proof-index publication, mixed-family semantic
obligations, remote CodebaseIR dispatch and fair full-supervisor benchmarks.
