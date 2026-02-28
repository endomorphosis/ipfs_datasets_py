# F-logic (Frame Logic) Module

F-logic is an object-oriented logic programming language that extends classical
first-order logic with *frames*: structured objects with typed attributes,
inheritance hierarchies, and defeasible reasoning.  It was designed specifically
for knowledge representation and is the foundation of many Semantic Web and
ontology-based AI systems.

> **Reference:** Kifer, Lausen & Wu (1995) — [Logical Foundations of Object-Oriented and Frame-Based Languages](https://dl.acm.org/doi/10.1145/212331.212335)  
> **Wikipedia:** <https://en.wikipedia.org/wiki/F-logic>

---

## ErgoAI / ErgoEngine Submodule

This module integrates the **ErgoAI/ErgoEngine** theorem prover as a git
submodule.  ErgoAI is a production-quality F-logic engine built on top of XSB
Prolog, maintained by Coherent Knowledge Systems.

| Resource | URL |
|---|---|
| Source repository | <https://github.com/ErgoAI/ErgoEngine> |
| Official tutorial | <https://sites.google.com/coherentknowledge.com/ergoai-tutorial/ergoai-tutorial> |
| Submodule path | `ipfs_datasets_py/logic/ErgoAI/` |

### Initialising the submodule

```bash
# From the repository root
git submodule update --init ipfs_datasets_py/logic/ErgoAI
```

### Installing ErgoAI

Follow the official instructions in the submodule's `README` or visit the
tutorial linked above.  After installation, point the wrapper to the binary:

```bash
export ERGOAI_BINARY=/path/to/ErgoAI/runErgo.sh
```

If `ERGOAI_BINARY` is not set, the wrapper searches common locations inside the
submodule and then the system `PATH`.

---

## Python API

### Core types (`flogic_types`)

| Class | Description |
|---|---|
| `FLogicFrame` | A single object with scalar/set-valued methods |
| `FLogicClass` | A class with optional superclasses and method signatures |
| `FLogicOntology` | A collection of frames, classes, and raw rules |
| `FLogicQuery` | A query goal together with its result bindings |
| `FLogicStatus` | Enum: `SUCCESS`, `FAILURE`, `UNKNOWN`, `ERROR` |

### ErgoAI wrapper (`ergoai_wrapper`)

| Symbol | Description |
|---|---|
| `ErgoAIWrapper` | High-level wrapper; degrades to simulation mode when binary absent |
| `ERGOAI_AVAILABLE` | `bool` — `True` if an ErgoAI binary was found at import time |
| `ERGOAI_SUBMODULE_PATH` | `Path` pointing to the submodule directory |

---

## Quick start

```python
from ipfs_datasets_py.logic.flogic import (
    ErgoAIWrapper,
    FLogicClass,
    FLogicFrame,
    FLogicOntology,
)

# ── Build an ontology ──────────────────────────────────────────────
onto = FLogicOntology(name="animals")

onto.classes.append(FLogicClass("Animal"))
onto.classes.append(FLogicClass("Dog", superclasses=["Animal"]))
onto.classes.append(FLogicClass("Cat", superclasses=["Animal"]))

onto.frames.append(
    FLogicFrame("rex",  scalar_methods={"name": '"Rex"'},  isa="Dog")
)
onto.frames.append(
    FLogicFrame("whiskers", scalar_methods={"name": '"Whiskers"'}, isa="Cat")
)

# ── Query ─────────────────────────────────────────────────────────
ergo = ErgoAIWrapper()
ergo.load_ontology(onto)

result = ergo.query("?X : Dog")
print(result.status)    # FLogicStatus.SUCCESS  (or UNKNOWN in simulation mode)
print(result.bindings)  # [{'?X': 'rex'}]
```

### Building frames programmatically

```python
from ipfs_datasets_py.logic.flogic import FLogicFrame

# Single-valued (scalar) method
person = FLogicFrame(
    "alice",
    scalar_methods={"age": "30", "employer": "acme"},
    isa="Person",
)
print(person.to_ergo_string())
# alice[age -> 30, employer -> acme] : Person

# Set-valued (multi-valued) method
project = FLogicFrame(
    "proj1",
    set_methods={"member": ["alice", "bob"]},
    isa="Project",
)
print(project.to_ergo_string())
# proj1[member ->> {alice,bob}] : Project
```

### Adding rules

```python
ergo.add_rule(
    "?X[mammal -> true] :- ?X : Animal[warm_blooded -> true]."
)
```

---

## Integration with the knowledge-graph ontology

The F-logic module is designed to complement the existing knowledge-graph layer
(`ipfs_datasets_py.knowledge_graphs`).  A typical workflow:

1. **Extract triples** from the knowledge graph.
2. **Convert** them to `FLogicFrame` / `FLogicClass` objects.
3. **Assert** the frames into `ErgoAIWrapper`.
4. **Prove** statements about the ontology (e.g. class membership, inheritance).
5. **Feed** the proven facts back into the graph or into the NL→KG→NL pipeline
   (see `ipfs_datasets_py/optimizers/logic/flogic_optimizer.py`).

---

## Integration with the optimizers

The companion module
`ipfs_datasets_py.optimizers.logic.flogic_optimizer` (`FLogicSemanticOptimizer`)
uses F-logic consistency checking to preserve semantic meaning across the
encoder/decoder round-trip:

```
Natural Language
      │
      ▼
  Encoder  (knowledge graph + formal F-logic ontology)
      │
      ▼
  Decoder  (natural language)
      │
      ▼
  FLogicSemanticOptimizer ── cosine similarity score
```

The optimizer scores the semantic preservation as a cosine similarity and
optionally re-runs the pipeline when the score falls below a threshold.

---

## Graceful degradation

The wrapper **never raises** when ErgoAI is absent.  Every query returns a
`FLogicQuery` with `status = FLogicStatus.UNKNOWN` and an explanatory
`error_message`.  This allows the rest of the system to function without a full
ErgoAI installation.

```python
from ipfs_datasets_py.logic.flogic import ERGOAI_AVAILABLE, ErgoAIWrapper

ergo = ErgoAIWrapper()
if ergo.simulation_mode:
    print("Running in simulation mode — install ErgoAI for full reasoning")

stats = ergo.get_statistics()
print(stats)
```

---

## Further reading

* ErgoAI tutorial: <https://sites.google.com/coherentknowledge.com/ergoai-tutorial/ergoai-tutorial>
* F-logic Wikipedia: <https://en.wikipedia.org/wiki/F-logic>
* ErgoEngine source: <https://github.com/ErgoAI/ErgoEngine>
