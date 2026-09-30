# Native formal-expression readout

`native_formal_decoder.py` reconstructs candidate native expressions from the
autoencoder's **reconstructed projection scores**. It supports the existing
Security, Intent and UI/UX structural feature representations. It does not
require changing the hashed v1 numerical backend or its stored weights.

The path is:

```text
typed domain input → native compiler targets → numeric autoencoder
  → reconstructed path/value scores → fixed-shape readout
  → native validation → decoded candidate or explicit abstention
```

This path remains conditioned on compiler-prepared structural inputs. It is not
an independent natural-language-to-logic model. The readout fits zero additional
neural parameters: it records training tree shapes, including empty containers
which the original scalar feature vocabulary omitted. All leaf values must be
selected from the existing vocabulary by the numerical decoder's actual output.
It never copies the inference target expression as a fallback.

## API

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import native_formal_decoder as formulas
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features

head = formulas.train_formal_decoder(feature_space, training_targets)
head_sha256 = formulas.validate_decoder(feature_space, head)

inference = features.infer_projection_features(contract, feature_space, state, evaluation_targets)
candidates = formulas.decode_formal_features(feature_space, head, inference)
```

Fit the head using exactly the training targets and order that established the
feature basis. Validation/evaluation rows cannot be substituted. The head binds
the exact feature-space digest, training target digest, decoder implementation,
and the listed native validator source files. This is an explicit source list,
not an attestation of every transitive dependency.

The result contains per-source, per-projection `expression`, `typed_expression`
where supported, `readable_notation` where supported, status and abstention
reason. It retains the original projection family, profile, properties, role,
representation and producer declaration, plus model/basis/head identities and
the input coverage report. Batch `status` is `decoded`, `partial`, or
`abstained`; `decoded_formulas_generated` is true only when at least one native
expression candidate was generated.

The formula decoder supports fixed tree shapes only. Different training shapes
within a projection produce an unsupported head entry for that projection;
numeric feature training can continue. A future presence/length decoder is
needed to predict different tree shapes instead of imposing one.

Every leaf requires a score greater than `1e-8`. Where a path has several known
values, the best score must exceed the runner-up by more than `1e-8`. These are
deterministic ambiguity gates, **not calibrated semantic confidence**. Missing,
negative, zero or tied evidence abstains. Nonfinite or dimensionally malformed
scores are rejected. Native validation failures abstain without silently fixing
predicted identifiers or replacing values from the input target.

## What is validated

| Domain | Candidate representation | Validation scope |
| --- | --- | --- |
| Security | Native typed document and its `TypedExpression@1` syntax extension | Existing `SoftwareVerificationSyntaxBridge` reconstructs the typed owner and requires exact local replay, including content identifiers and source-reference consistency |
| Intent | Native structured records, including facts, modalities, action contracts and temporal workflow records | Closed native fields, operators and route/family bindings; existing typed Intent action/statement/edge decoders where applicable |
| UI/UX | Native frame facts, event records, deontic records and cognitive records | Closed fields/operators and exact native projection route declarations |

Intent and UI readable notation is labeled as native record notation. For
example, `ui_component("delete", "button").` is a readable structural fact.
Opaque UI proposition strings remain explicitly quoted; they are not silently
parsed into executable temporal formulas. Security returns the actual typed
extension AST and does not disguise JSON as a new calculus text renderer.

`family_syntax_checked` stays false: native record validation and syntax-extension
replay do not certify every downstream logic-family parser/backend. Predicted
`source_ref_ids`, source hashes, confidence and review-status fields inside a
candidate remain model outputs. They do not establish source grounding,
semantic fidelity, proof or execution authority. All outputs retain false
qualification/admission/formalization flags. Lake admission still requires the
separate, existing source-bound `lake build <Lib>` path.

## Streamed v2

`train_formal_decoder` also accepts an explicit v2 feature space and processes
its training targets one at a time, up to the backend's 32,768-source bound. Its
digest follows v2's canonical-target-lines convention. A v1 head cannot be
substituted for a v2 head.

```python
candidates = formulas.infer_and_decode_native_v2(
    v2_feature_space, v2_state, v2_head, evaluation_targets,
)
```

The helper calls the existing validated v2 inference once. That backend exposes
float64 latents but omits reconstructed coordinates; the helper applies the
saved decoder matrix and bias to those same latents. It does not modify the v2
backend or add training, registry, fleet or Hub integration. The original
inference receipt is retained as `model_inference` for comparison.

## Evidence and limits

Tests separately cover perfect-coordinate structural inversion and actual
numeric training. Small authored Security, Intent and UI fixtures each train an
existing v1 autoencoder for 16 epochs and produce a native candidate; zeroing
the model's output matrix and bias causes abstention. Other checks cover score
changes, ties, negative scores, mixed layouts, head/source tampering, unknown
vocabulary coverage and incoherent predicted Security identities. V2 tests
check latent parity and streaming head preparation beyond 1,024 sources.

These are plumbing and structural validation tests. They establish neither
held-out semantic accuracy nor successful open-vocabulary generation. The
decoder can choose only values already represented in its training vocabulary.
Coverage gaps are reported; a syntactically valid candidate may still fail to
express the source's meaning.
