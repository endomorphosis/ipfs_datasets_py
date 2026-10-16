# Authored counted-frame profile v1

This profile represents **at most three distinct objects in each explicitly declared event/time frame**. It is a small, unreviewed formal declaration. It does not determine the intended meaning of a statute.

For arbitrary sorts `Object`, `EventFrame` and `TimeFrame`, and a caller-declared relation `Member : Object × EventFrame × TimeFrame → Bool`, the formula is:

```text
forall event, time, x0, x1, x2, x3.
  (Member(x0,event,time) and Member(x1,event,time)
   and Member(x2,event,time) and Member(x3,event,time))
  -> (x0=x1 or x0=x2 or x0=x3 or x1=x2 or x1=x3 or x2=x3)
```

Each quantifier has an explicit sort. Equality is the existing typed AST's built-in object identity, not an uninterpreted predicate. All four membership atoms share the same event and time variables. Connectives have a fixed binary left-associated representation. The complete expansion has 49 physical nodes, six quantifiers, four membership occurrences and six equality occurrences.

The formula allows zero, one, two or three distinct members. Duplicate occurrence rows do not increase the count. Separate event frames and time frames have separate limits. `TimeFrame` is an arbitrary index: this profile introduces no ordering, calendar, duration, simultaneity or native temporal semantics. It does not assert a global, lifetime or cumulative cap, select the legal unit of counting, or supply a domain-specific meaning of `Member`.

## Public use

Import `ipfs_datasets_py.logic.autoformal.legal_counted_frame_v1`. The module's ordinary import uses the standard library; syntax owners load after bounded, duplicate-free request validation.

```python
import hashlib
import json
from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted

request = counted.authored_counted_frame_request()
raw = (json.dumps(request, ensure_ascii=False, indent=2) + "\n").encode()
request_sha256 = hashlib.sha256(raw).hexdigest()
report = counted.prepare_counted_frame(raw, expected_request_sha256=request_sha256)
counted.validate_counted_frame(
    report, raw,
    expected_request_sha256=request_sha256,
    expected_report_sha256=counted.counted_frame_report_sha256(report),
)
```

The constructor supplies an authored example, never a source-derived target. Requests must explicitly declare the fixed maximum, distinctness rule, frame, argument roles, variable names, complete typed expression and null source binding. Missing declarations, additional fields, other bounds, altered binder/argument order, unsupported syntax and noncanonical expression serialization fail closed. Report validation replays the exact original request and regenerates the complete report, including generated text and trusted producer identities. Offered producer paths do not select files to read.

## Qualification boundary

The profile reuses the shared typed AST, elaboration, canonical FOL printer/parser and alpha-equivalence check. A narrow local printer subclass explicitly parenthesizes binary conjunctions and disjunctions: the shared default printer otherwise flattens their textual grouping, and reparsing creates n-ary nodes. Every other printing case delegates to the shared printer. The original 49-node tree is alpha-compared with both parses, and grouped printing must remain stable. Parsing produces fresh node IDs and ranges, so its structural comparison uses alpha-equivalence rather than byte identity. Original request and typed-expression identities are retained separately.

The existing native TDFOL route has no equality formula constructor/rendering branch. This profile consequently uses canonical FOL syntax and a specialized Lean text template for this one recognized formula. Lean text uses actual `=` and a parameterized membership relation. It needs no `Finset`, `DecidableEq`, Mathlib or finite-domain assumption. No Lean build, kernel check, proof, native TDFOL parse, theorem validity or legal fidelity is implied by text generation or finite controls.

Retained finite controls independently interpret the typed formula. Three versus four distinct members, duplicate rows, different events, different times, unrelated objects, zero/two members and each of the six equality-pair witnesses detect specific representation mistakes. They are illustrative authored controls, not a general proof or independent statutory evaluation set.

## Relationship to the corpus plan

The earlier source-to-typed join and relational owners remain unchanged. This many-sorted equality profile is not automatically an accepted relational candidate or join target. A future versioned correspondence route must preserve its frame, equality, sorts, source dependencies and unresolved assumptions before any source-linked lowering can be qualified.

The sampled §7214 paragraph remains source-only pending. Its counting unit/frame, permission scope, assignment restriction, purpose, pronoun and entity/definition correspondence still need supported decisions and independent review. §7213's two partial alternatives remain unreviewed. No accepted meaning, governing-definition edge, review signature, graph/cache/corpus/Lean admission or training/evaluation gold is created here. Training and evaluation masks remain zero.

The fixed training review remains the basis for learned work: F18 is scientific failure/no promotion; F19 is the saved-score diagnostic; the separately reported auxiliary embedding epoch is not formula-decoder training. This mechanical profile adds no training, rescoring, inventory refresh or new formalization control.
