# Optimization Loop Architecture

This note documents the canonical optimizer loop used across GraphRAG, logic,
and agentic optimizers.

## Flow (ASCII)

```text
input_data
   |
   v
+-------------------+
| generate(...)     |
| - create artifact |
+-------------------+
   |
   v
+-------------------+
| critique(...)     |
| - score           |
| - feedback        |
+-------------------+
   |
   v
+---------------------------+
| optimize(...)             |
| - refine artifact         |
| - repeat until stop rule  |
+---------------------------+
   |
   v
+-------------------+
| validate(...)     |
| - correctness     |
| - constraints     |
+-------------------+
   |
   v
result
  - artifact
  - score
  - iterations
  - validity
  - timing / metrics
```

## Stop Conditions

- target score reached
- max iterations reached
- early stopping (improvement below threshold)

## Shared Contract

`BaseOptimizer.run_session()` executes this loop and returns `OptimizerResult`.
Concrete optimizers implement:

- `generate(input_data, context)`
- `critique(artifact, context)`
- `optimize(artifact, score, feedback, context)`
- `validate(artifact, context)` (optional override)
