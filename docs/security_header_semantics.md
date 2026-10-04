# Source-bound header semantics

`ipfs_datasets_py.logic.security_ir.code_header_derivation` models a small,
recognized pair of Python HTTP header normalizers. It reuses the canonical
`doctor_header_contracts` recognizer, which observes a setter, stored header
pairs, a property projection, and an explicitly reviewed WSGI callback role.
The accelerator import is a compatibility alias to this datasets module.

```python
from ipfs_datasets_py.logic.security_ir.code_header_derivation import (
    WsgiHeaderProtocolContract, derive_header_semantics,
    validate_header_semantics, check_header_semantics,
)

protocol = WsgiHeaderProtocolContract("my recorded WSGI source review")
report = derive_header_semantics(
    source_bytes=source_bytes, source_path="app.py", protocol=protocol,
)
validate_header_semantics(
    report, source_bytes=source_bytes, source_path="app.py", protocol=protocol,
)
check = check_header_semantics(
    report, source_bytes=source_bytes, source_path="app.py", protocol=protocol,
    z3_executable="z3",
)
```

The review reference records a caller-supplied premise. Neither a label nor a
model score establishes the callback or receiver identity. Missing or ambiguous
source structure returns an unsupported report with no formal targets. Target
code is never imported or executed.

Supported normalizers convert one argument using an unshadowed `str` or the
recognized bytes/None/string helper, then return the converted value. Field
names can additionally use `title`, `lower`, `upper`, or `casefold`, optionally
followed by `.replace('_', '-')`. The optional guard must reject CR, LF, and NUL
with the exact recognized `ValueError` branch. Defaults, keyword conversion
arguments, decorators, unknown normalization operations, and altered guards
are unsupported.

Each modeled symbol records its role, source lines, exact UTF-8 byte span and
hash, AST hash, conversion symbol, normalization operations, and observed guard
presence. The report includes native `SecurityIR`, `FormalizationSample`, and
`FormalizationArtifact` payloads and identities. Observed unguarded transitions
remain unguarded in those declarations; desired behavior is a separate claim.

Three native `SmtObligation`/`SmtCompilation` targets are emitted per normalizer:

| Obligation | Unguarded source model | Guarded source model |
| --- | --- | --- |
| A forbidden converted string is accepted | SAT | UNSAT |
| Negation of preservation on safe converted strings | UNSAT | UNSAT |
| An accepted result contains a forbidden control | SAT | UNSAT |

The SMT model begins after successful conversion. It uses fixed String terms
and `str.contains` literals for NUL, LF, and CR through the native compiler's
explicit term interface. The string operator extension is recorded rather than
advertised as a new native compiler feature. Named equations bind acceptance
and return behavior to the recognized shape. Identity normalization is exact
inside this model; other normalization operations are abstracted and require
the explicit premise that they terminate and preserve forbidden-control
membership. SMT String has a narrower codepoint domain than arbitrary Python
strings, which is recorded as a frontier.

The optional real Z3 backend supplies SAT models or UNSAT cores, solver version,
and exact script/compilation hashes. Missing Z3 returns `solver_unavailable`.
Checking first regenerates the entire report from current source bytes and
recompiles each native obligation. Stale source, forged formulas, or added
authority cannot pass replay. Solver results concern this local model; they do
not close conversion, aliasing, runtime mutation, Unicode implementation,
additional header sources, or whole-program security frontiers.

`validate_header_candidate_function` can join an independently produced
function to the native pipeline. It takes the full original module, explicit
protocol, selected symbol, and candidate function text; it independently parses
and requires exact AST equality. A mismatch raises instead of substituting a
source template. The returned receipt identifies the native compiler as
deterministic and leaves the candidate producer unverified. This is suitable as
an independent check after learned AST production, but this adapter itself
generates no learned formulas.

The authored tests exercise both behavior models, stale and forged receipts,
unsupported syntax, optional solver behavior, and datasets-only imports. A
separate local qualification uses only the permitted original public Bottle
input: its `_hkey` and `_hval` functions are recognized, while the remaining
functions receive no coverage claim. The recognizer was developed using public
benchmark source, so this is benchmark-informed capability evidence rather
than a held-out generalization result.
