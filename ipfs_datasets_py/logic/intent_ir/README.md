# Intent IR scaffold

Intent IR is the source-grounded semantic boundary between skill corpora,
GraphRAG, and formal-logic training. It represents goals, modalities,
conditions, actions, effects, verification steps, and control flow. It never
authorizes or executes commands found in a source skill.

The v0.1 scaffold contains:

- an immutable canonical schema and cross-reference validator;
- deterministic JSON and SHA-256 content identity;
- backend-neutral normalizer, GraphRAG, formalizer, and artifact-store ports;
- a bounded read-only adapter for pinned SkillCenter SQLite bundles.

It deliberately does not yet contain an LLM normalizer, GraphRAG ontology,
autoencoder head, theorem compiler, or production downloader. Those stages must
be implemented behind the protocols after licensing, untrusted-input, split
leakage, and evaluation policies are approved.

## Intended artifact chain

```text
pinned HF bundle
  -> raw bundle CID + manifest
  -> bounded SkillCenter record/content CID
  -> validated IntentIRDocument CID
  -> GraphRAG projection CID
  -> formal-logic projection CID
  -> proof/evaluation receipt CID
```

Each arrow must retain the parent identity, producer version, configuration
digest, diagnostics, and review state. Training and proof artifacts must refer
to bodies by CID rather than recursively embedding the corpus.
