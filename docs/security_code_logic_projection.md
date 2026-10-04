# Source-bound code logic projections

`ipfs_datasets_py.logic.security_ir.code_logic_projection` connects a native
CVEfixes `CodeUnit` to explicitly supplied software-verification IRs. It checks
the complete UTF-8 body against the unit's `body_sha256` and `body_cid`, then
uses `SoftwareVerificationSyntaxBridge` for exact typed round trips.

| Input owner | Existing family | Existing profile | Additional boundary |
| --- | --- | --- | --- |
| `ProgramIR` | `program` | `program_ir` | Native source maps must match the code unit. |
| `ProgramContract` | `program` | `dynamic_hoare` | Requires `ProgramIR`; native `validate_against` resolves references, effects, and frames. |
| `StateTransitionIR` | `transition_system` | `action_system` | Native bounded `TLACompiler` output includes all losses and bounds. |
| `TemporalFormula` | `temporal` | `ltl` | Other temporal profiles remain explicit unsupported cases. |
| `HeapModel` | `separation_logic` | `heap_model` | Requires a native bridge identity. |
| `SeparationLogicIR` | `separation_logic` | `separation` | Retains the native heap, ownership, and resource constraints. |
| `HyperpropertyIR` | `hyperproperty` | `hyperltl` | Requires explicit information-flow policy and self-composition bounds. |

TLA+ is an encoding. Noninterference is a property. Neither becomes a new
semantic family. This service does not modify the family or LegalIR registry.

The supervisor's canonical corpus selection is
[Publicus/cvefixes-security-ir-graphrag](https://huggingface.co/datasets/Publicus/cvefixes-security-ir-graphrag).
Its separately owned initializer source is
[justicedao/legal-ir-autoencoder-checkpoints](https://huggingface.co/datasets/justicedao/legal-ir-autoencoder-checkpoints).
These repository locations are discovery links. A training declaration must
bind full immutable revisions, manifest digests, the corpus release root, and
the selected parent state digest through the native source validators. A
mutable branch or repository name alone is insufficient.

Corpus retrieval or classification rows supply neither a program model nor
proved logic targets. Complete source bodies must be recovered through the
native source-CID path; missing material remains quarantined. The LegalIR
parent contributes only explicitly compatible shared lexical weight rows.
Legal heads are not code heads, and the parent checkpoint remains unchanged.

## API

```python
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.logic.security_ir.code_logic_projection import (
    CodeLogicEvidence,
    describe_code_logic_projection_profile,
    project_code_logic,
    validate_code_logic_projection,
)

# code_unit comes from the native CVEfixes projector. source_bytes must be
# the complete matching body, not its possibly truncated public excerpt.
source = SourceRef(
    ref_id=code_unit.cid,
    source_uri="code-unit:" + code_unit.cid,
    source_id=code_unit.path,
    source_revision=reviewed_revision,
    content_sha256=code_unit.payload["body_sha256"],
    content_cid=code_unit.payload["body_cid"],
)

# program_ir and program_contract are separately authored native typed IRs.
# Their intrinsic source maps must use this source reference.
projection = project_code_logic(
    code_unit=code_unit,
    source_bytes=source_bytes,
    typed_inputs=[CodeLogicEvidence(program_ir, source),
                  CodeLogicEvidence(program_contract, source)],
    requested_kinds=["program", "contract"],
)
validate_code_logic_projection(
    projection, code_unit=code_unit, source_bytes=current_source_bytes,
)
```

The profile and projection are JSON-serializable and content-addressed.
Validation reconstructs native owners and regenerates the full result,
including generated TLA+ text. It rejects altered targets, source bytes,
bindings, authority flags, or serialized declarations.

Missing body identities or absent complete bytes produce a quarantined result
with no targets. Missing typed evidence produces an explicit unsupported
entry. CWE labels and classifier scores never manufacture formal declarations.

Source linkage and structural preservation do not establish that an authored
model accurately describes code. Every result therefore retains
`source_semantics_verified=false` and false proof, execution, and completion
authority. Compilation executes no model checker, prover, provider, or source
program. Native proof and admission systems remain responsible for those
decisions. No training occurs in this service, and its capability profile does
not imply that any trained checkpoint has these output heads.

## Guarded derivation without an LLM

`logic.security_ir.code_program_derivation` adds
`describe_code_program_derivation_profile()`,
`derive_code_program(code_unit=..., source_bytes=...)`, and
`validate_code_program_derivation(payload, code_unit=..., source_bytes=...)`.
It admits one ASCII Python function with simple positional parameters, fresh
local assignments, and one terminal return. Expressions are bounded integer
literals, already-bound names, addition/subtraction/multiplication, and unary
plus/minus. Source size, AST size/depth, and literal size have explicit limits.

Calls, default arguments, annotations, decorators, branches, loops, imports,
global reads, reassignment, non-ASCII text, and control characters other than
LF/tab remain unsupported. The native source adapter must return complete
success. Its resulting commands, expression trees, evaluation order, exact
symbol bindings, unchanged native types, and source spans are independently
checked against the admitted AST. Source-reference rebinding has an explicit
receipt with the original and new program identities and per-span hashes.

This yields only a candidate structural `ProgramIR` target. Exact built-in
integer arguments are an explicit, unverified modeling assumption; native
parameter/result types remain `any`. Runtime operator overloading, resource
exhaustion, and concurrency are outside that model. The adapter neither creates
a security contract nor claims whole-program semantic equivalence. It invokes
the existing source adapter with `include_supervisor_evidence=False`, so the
standalone path never attempts to import the accelerator consumer.

## End-to-end capability controls

`tests/unit/logic/formalization/autoencoder/test_security_formalization_control.py`
executes a real fixture checkpoint on an authored arithmetic function and
compares its deterministic target with the same source path while checkpoint
inference is disabled. Identical targets establish that the model did not
generate them. The current checkpoint reconstructs numerical AST features and
classifies audit/CWE/polarity candidates; the strict learned-formula capability
gate fails because it has no formula decoder.

Separate controls supply an explicitly authored postcondition to the native
`ContractSpec` → verification-condition → SMT pipeline. When Z3 is available,
the correct postcondition is proved and an incorrect one is disproved. Those
solver results concern the explicit integer model and authored specification;
they do not confer proof authority on the autoencoder or certify arbitrary
Python runtime behavior.
