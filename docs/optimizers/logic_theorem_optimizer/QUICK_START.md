# Logic Theorem Optimizer: Quick Start Guide

This guide shows how to use the LogicTheoremOptimizer to extract, optimize, and validate logical theorems from text.

## Installation

```bash
# Assumes ipfs_datasets_py is installed
pip install ipfs_datasets_py[logic]
```

## Basic Usage

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicTheoremOptimizer
from ipfs_datasets_py.optimizers.common import OptimizerConfig

# Create configuration
config = OptimizerConfig(
    max_iterations=3,
    target_score=0.85,
    validation_enabled=True,
    metrics_enabled=True,
)

# Create optimizer
optimizer = LogicTheoremOptimizer(config=config, llm_backend=None)

# Context for extraction (describes what to prove)
context = {
    "domain": "propositional_logic",
    "rules": ["Modus Ponens", "Modus Tollens"],
    "target": "Prove Q from P and P→Q",
}

# Data to optimize (axioms and theorem)
data = {
    "axioms": ["P", "P → Q"],
    "theorem": "Q",
}

# Run optimization session
result = optimizer.run_session(data, context)

print(f"Optimization score: {result['score']:.2f}")
print(f"Valid: {result['valid']}")
print(f"Extracted statements: {result['artifact']['statements'][:3]}")
```

## Validate Statements

```python
# Verify theorems using integrated prover
statements = [
    {"formula": "P", "type": "axiom"},
    {"formula": "P → Q", "type": "axiom"},
    {"formula": "Q", "type": "theorem"},
]

is_valid, errors = optimizer.validate_statements(statements)

if is_valid:
    print("All statements logically consistent!")
else:
    print(f"Validation errors: {errors}")
```

## Deterministic Modal Legal Parser

Use the deterministic parser path for legal modal extraction when you want
reproducible IR, BM25 frame candidates, and loss metrics without default LLM
calls.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    BM25FrameSelector,
    DEFAULT_LEGAL_FRAME_FIXTURE,
    LegalModalParser,
    ModalAutoencoderBaseline,
    ModalProverRouter,
    ModalSystem,
    build_modal_parser_report,
    build_us_code_sample,
)

text = "The agency must provide notice and a hearing before a final order."

parser = LegalModalParser()
modal_ir = parser.parse(text, document_id="sample-5-552", source="us_code", citation="5 U.S.C. 552")

selector = BM25FrameSelector(DEFAULT_LEGAL_FRAME_FIXTURE)
frames = selector.rank(text, top_k=3)

sample = build_us_code_sample(title="5", section="552", citation="5 U.S.C. 552", text=text)
losses = ModalAutoencoderBaseline().evaluate([sample])
prover_route = ModalProverRouter().route(formula=None, system=ModalSystem.S5)

report = build_modal_parser_report(
    samples=[sample],
    autoencoder=losses,
    prover_results=[prover_route],
    expected_frames={sample.sample_id: sample.selected_frame or ""},
)

print(modal_ir.canonical_hash())
print(frames[0].to_dict())
print(report.to_markdown())
```

## CLI Usage

```bash
# Theorem proving from command line
python -m ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper prove \
  --axiom "P" \
  --axiom "P -> Q" \
  --theorem "Q" \
  --ruleset TDFOL_v1
```

## Optimization Loop

```python
for iteration in range(5):
    # Run optimization session
    result = optimizer.run_session(data, context)
    
    score = result['score']
    valid = result['valid']
    
    print(f"Iteration {iteration+1}: score={score:.2f}, valid={valid}")
    
    # Check convergence
    if score >= config.target_score:
        print(f"Converged at iteration {iteration+1}!")
        break
    
    # Apply feedback from critic to refine approach
    feedback = optimizer.critique(result['artifact'])
    context['feedback'] = feedback.feedback
```

## Generate → Critique → Optimize Cycle

```python
import json

# PHASE 1: Generate initial extraction
extraction = optimizer.generate(data, context)
print(f"Generated {len(extraction['statements'])} statements")

# PHASE 2: Critique the result  
critique = optimizer.critique(extraction)
print(f"Critic score: {critique.overall:.2f}")
print(f"Issues: {critique.issues[:2]}")

# PHASE 3:  Optimize based on feedback
optimized = optimizer.optimize(extraction, critique)
print(f"Optimized score: optimized['score']:.2f}")
print(f"Improved: {optimized['score'] > critique.overall}")
```

## Common TDFOL Theorems

```python
# Modus Ponens: From P and P→Q, infer Q
theorems = [
    {
        "axioms": ["P", "P → Q"],
        "theorem": "Q",
        "rule": "Modus Ponens"
    },
    {
        "axioms": ["¬Q", "P → Q"],
        "theorem": "¬P",
        "rule": "Modus Tollens"
    },
    {
        "axioms": ["P ∧ Q"],
        "theorem": "P",
        "rule": "Conjunction Elimination"
    },
]

for t in theorems:
    context = {"domain": "propositional_logic", "rule": t["rule"]}
    data = {"axioms": t["axioms"], "theorem": t["theorem"]}
    
    result = optimizer.run_session(data, context)
    valid = result['valid']
    
    print(f"{t['rule']}: {'✓' if valid else '✗'}")
```

## Daemon-Driven Modal Optimization

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    AdaptiveModalAutoencoder,
    ModalTodoSupervisor,
    SpaCyLegalEncoder,
    SpaCyModalCodec,
    build_us_code_sample,
)

samples = [
    build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice and a hearing before a final order.",
    )
]

autoencoder = AdaptiveModalAutoencoder(
    feature_codec=SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="en_core_web_sm")
    )
)
supervisor = ModalTodoSupervisor()

before = autoencoder.evaluate(samples)
run = supervisor.optimize(
    samples,
    autoencoder=autoencoder,
    max_iterations=3,
    max_items=4,
    learning_rate=0.5,
)
after = run.final_evaluation

print(before.cross_entropy_loss, after.cross_entropy_loss)
print(before.embedding_cosine_similarity, after.embedding_cosine_similarity)
print(supervisor.queue.status_counts())
```

The supervisor generates loss-targeted TODOs, claims a batch, applies deterministic encoder/decoder updates, re-evaluates, and marks TODOs complete only when validation shows the loss moved in the right direction.

The spaCy codec keeps this path local: it compiles text into token features,
modal cue spans, IR formulas, family logits, and deterministic feature vectors
without LLM inference. If `en_core_web_sm` is not installed, it falls back to
`spacy.blank("en")` plus a sentencizer.

You can also request the spaCy path through the normal extractor API:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    ExtractionMode,
    LogicExtractionContext,
    LogicExtractor,
)

result = LogicExtractor(use_ipfs_accelerate=False).extract(
    LogicExtractionContext(
        data="The agency must make records promptly available.",
        domain="legal",
        config={"extraction_mode": ExtractionMode.MODAL.value, "modal_profile": "spacy"},
    )
)
print(result.metrics["llm_call_count"])
```

## U.S. Code Parquet Dataset

The daemon can optimize over schema-compatible parquet rows from
`justicedao/ipfs_uscode`, including `uscode_parquet/laws.parquet` and optional
embeddings from `uscode_parquet/laws_embeddings.parquet`.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    AdaptiveModalAutoencoder,
    ModalTodoSupervisor,
    SpaCyLegalEncoder,
    SpaCyModalCodec,
    load_uscode_samples_from_parquet,
)

samples = load_uscode_samples_from_parquet(
    "uscode_parquet/laws.parquet",
    embeddings_parquet="uscode_parquet/laws_embeddings.parquet",
    limit=25,
)

run = ModalTodoSupervisor().optimize(
    samples,
    autoencoder=AdaptiveModalAutoencoder(
        feature_codec=SpaCyModalCodec(
            encoder=SpaCyLegalEncoder(model_name="en_core_web_sm")
        )
    ),
    max_iterations=3,
    max_items=8,
)
print(run.final_evaluation.to_dict())
```

Default tests use a tiny local parquet fixture with the same columns. The live
Hub smoke test is opt-in:

```bash
IPFS_DATASETS_PY_RUN_HF_USCODE_LIVE=1 \
  pytest tests/unit/optimizers/logic_theorem_optimizer/test_uscode_dataset.py::test_hf_uscode_live_dataset_smoke -q
```

## Configuration

```python
from ipfs_datasets_py.optimizers.common import OptimizerConfig

config = OptimizerConfig(
    max_iterations=5,           # Max optimization rounds
    target_score=0.90,          # Target quality score
    early_stopping=True,        # Stop if target reached
    validation_enabled=True,    # Validate proofs
    metrics_enabled=True,       # Track metrics
)

optimizer = LogicTheoremOptimizer(config=config, llm_backend=None)
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **Validation always fails** | Check axioms follow standard propositional logic syntax (use `∧`, `∨`, `→`, `¬`, parentheses). |
| **Unknown formula elements** | ProverIntegrationAdapter only handles propositional logic. Use simpler formulas. |
| **Slow convergence** | Reduce `max_iterations` or lower `target_score`. Try simpler theorems first. |

## Next Steps

- **API Reference:** See [README.md](README.md) for full API docs
- **Theorem Database:** See [examples/](../examples/) for more complex theorems
- **Prover Details:** See [prover_integration_adapter.py](prover_integration_adapter.py)

---

**Last updated:** 2026-02-20  
**Test coverage:** 50+ deterministic tests in `tests/unit/optimizers/logic_theorem_optimizer/`
