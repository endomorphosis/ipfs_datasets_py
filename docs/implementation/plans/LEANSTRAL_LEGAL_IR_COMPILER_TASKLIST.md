# Leanstral Legal IR Compiler Task List

## Goal

Use Leanstral as a proof-backed, shadow-first synthesis worker that converts
auditable autoencoder projection evidence into bounded Python compiler and
decompiler improvements. The deterministic legal IR remains authoritative;
no model proposal may mutate it without passing source-grounding, Lean, Python,
mutation, and held-out metric gates.

## Implementation Checklist

- [x] Port the reusable Mistral Vibe transport from `ipfs_accelerate_py` into
  `ipfs_datasets_py` with explicit Lean-agent selection.
- [x] Add a shadow-only Leanstral task/proposal/proof-artifact contract and
  distinguish prover-route health from actual theorem validity.
- [x] Define `ProjectionEvidence` and `CompilerChangeSpec` contracts that map
  learned residuals to an owned compiler/decompiler change surface.
- [ ] Extend the Lean task contract with fixed semantic theorem templates for
  modality, exception scope, temporal constraints, provenance, and round trips.
- [ ] Add a constrained Python patch proposal contract and reuse isolated
  worktree validation for syntax, focused tests, and allowed-file enforcement.
- [ ] Add mutation fixtures and held-out Pareto gates across CE, cosine,
  LegalIR view families, graph validity, route health, and proved theorems.
- [ ] Emit accepted/rejected evidence into the existing program-synthesis TODO
  pipeline without automatically applying Leanstral patches.
- [ ] Run a no-mutation canary, document activation settings, and only then
  consider an opt-in proposal application lane.

## Non-Negotiable Gates

1. The model receives compact projection evidence and source-span hashes, not
   a free-form request to reinterpret a statute.
2. Leanstral supplies a proof body for a verifier-generated theorem. It cannot
   change the theorem, add axioms, imports, `sorry`, or executable tactics.
3. Python changes are reviewed in an isolated worktree and restricted to the
   files named by the deterministic `CompilerChangeSpec`.
4. A proposal must preserve IR schema, source provenance, graph integrity, and
   compiler/decompiler semantic behavior before metric improvements matter.
5. Hold-out acceptance is Pareto based: lower CE or higher cosine cannot mask a
   regression in formal, mutation, or provenance gates.

## Delivery Order

1. Projection evidence to compiler-change specification.
2. Fixed Lean theorem templates and proof validation.
3. Shadow-only Python patch proposal and worktree validator.
4. TODO evidence handoff and held-out acceptance report.
5. No-mutation canary and measured production activation.
