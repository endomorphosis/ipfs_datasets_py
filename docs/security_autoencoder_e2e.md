# End-to-end security autoencoder formalization checks

These checks distinguish learned feature/classification advice, deterministic
structural models, and verification of explicitly supplied contracts. A
successful classifier run does not pass the learned-formula gate.

The datasets-owned
[`evaluator`](../ipfs_datasets_py/logic/formalization/autoencoder/security/security_formalization_evaluation.py)
runs actual frozen inference on explicitly hashed permitted source files. Every
function observation joins its original file, exact function span, normalized
body digest and indentation byte map. Decorators, defaults and unsupported
syntax remain visible. Unsupported functions stay in coverage totals; inference
rank changes only visit order.

The native-only guarded adapter produces ProgramIR for its arithmetic fragment.
It does not import the supervisor, execute source, infer security specifications
or confer proof authority. Model-off ablations must reproduce its exact artifacts.
Native VC/SMT controls use separately authored postconditions and explicit
integer-model assumptions.

## Run the regression controls

From the datasets checkout with its dependencies available:

```bash
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest \
  -o addopts='' --noconftest -q \
  tests/unit/logic/formalization/autoencoder/test_security_formalization_evaluation.py \
  tests/unit/logic/formalization/autoencoder/test_security_formalization_control.py \
  tests/unit/logic/formalization/autoencoder/test_security_formalization_cli.py \
  tests/unit/logic/security_ir/test_code_program_derivation.py
```

Positive controls train/export an authored fixture checkpoint, then evaluate
through frozen inference. Evaluation forbids training and downloads. With Z3
installed, the solver controls prove `result == x + 1` and disprove
`result == x + 2` for the modeled increment function. These are deterministic
model/specification checks, not learned formula output.

## Evaluate permitted benchmark software

Supply a JSON source ledger mapping permitted relative filenames to independently
established SHA256 hashes, and a previously validated checkpoint descriptor. Do
not include benchmark tests, solutions or verifier files.

```bash
CUDA_VISIBLE_DEVICES='' PYTHONPATH=. python3 \
  scripts/evaluation/security_autoencoder_formalization.py \
  --repository /absolute/permitted-inputs \
  --source-ledger /absolute/source-ledger.json \
  --checkpoint-descriptor /absolute/checkpoint-descriptor.json \
  --output /absolute/fresh-evaluation
```

Output contains `evaluation.json`, the real `inference/` artifacts, and
`cli-receipt.json` binding the descriptor bytes. Replay it with
`validate_security_formalization_evaluation(repository=..., expected_report=...)`.
Source/model substitutions, changed source maps, missing functions and fabricated
learned/proof claims invalidate replay even after consistent report rehashing.

The default CLI **exits 2 when learned formula generation is unavailable**.
`--allow-diagnostic-only` permits a successful diagnostic process exit while
retaining the failed capability result. Neither mode trains a decoder or falls
back to an LLM.

## Original checkpoint capability

The separate [production decoder and formalization pipeline](security_formula_decoder.md)
adds a learned path. Use its new descriptor and CLI for that path; the evaluator
described above continues to test the original advisory checkpoint faithfully.

The development checkpoint's decoder reconstructs 44 AST feature values. Its
classification head emits audit/CWE/polarity scores. `learned_formula_head` is
false; that checkpoint contains no source-to-formula decoder. Its benchmark-informed training
also prevents a held-out accuracy claim on the same task source.

The pinned `fix-code-vulnerability` input is the 175,565-byte `bottle.py` with
SHA256 `761756ce31753e526c48d28ccbca13a5d2493b16fe37aff3e1e4d2efaf3a2bba`.
It has 358 function observations. Its calls, branches, mutation, string operations
and object state exceed the original arithmetic fragment. This original
checkpoint's capability gate remains failed. The separate production decoder's
coverage is measured by its own pipeline; classifier scores and authored
specifications alone cannot count as learned formal artifacts.
