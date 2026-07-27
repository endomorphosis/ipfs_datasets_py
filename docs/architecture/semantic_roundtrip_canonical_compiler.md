# Canonical structured-text round trip

## Status and scope

This document is the SRT-015 design contract for turning structured legal text
into a canonical intermediate representation (IR) and realizing that IR back
into source-withheld natural language. It specifies interfaces and evidence
lineage; it does not promote the implementation to production.

The design is authorized by `CanonicalDesignGate@1`
`baguqeerab4top4ljgojms7f7p6y4ksdlivfwhyzxzhynnii4zbrfvw4mqtfq`.
That gate was independently recomputed from a complete replacement run. It
records an **exact tie**, not a unique semantic winner:

1. `typed_deontic__no_guidance__no_repair__not_applicable__deterministic`
2. `typed_deontic__no_guidance__selective__not_applicable__deterministic`

The first arm is the implementation representative only because it occurs
first in the frozen preregistered order. The selection basis is
`replacement_bounded_tie_policy`. The representative is not asserted to be
semantically superior.

## Evidence lineage

The original SRT-014 run is retained as negative evidence. Its report CID is
`baguqeerakqgerwv6npdlqpgrc3bjzuxqog3hiouey3c4giw5vkdgk2jhfbpq`, its
selection-gate CID is
`baguqeeraa7vbts26rxvqujbvgvgplq4xrprcebufol5qqmstc6cbrac2rthq`, and its
selection outcome was `no_eligible_composition`. The corresponding immutable
remediation manifest is
`baguqeerarr7ebjrzd3argtdekd7er3bqrnvhuzy2ogqzfi7h5nv37dbea52a`.
The original result is not rewritten as a success.

The complete replacement report CID is
`baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga`; its
selection-gate CID is
`baguqeerawhggoyrnacv74kbuq3rhpmz4jikhr3tnv5uahpxcnpghfrwfj6jq`.
The selected representative's measured arm identity is
`baguqeeraylvbngffosmvcvwowelspcdbbk5wom5itjvfanbzty4eioxsauhq`.
Its constructor was `TypedDeonticCanonicalConstructor@1` and its realizer was
`SourceWithheldCanonicalParaphraser@1`. The exact adapter raw CIDs were,
respectively,
`bafkreig2yeibug44tbffleyvju4zvo62thdqkpht3n2qn6guefkvbv7z2a` and
`bafkreifrmafgdy5wajq7sepxxatwc2mnnubqt2c7kwped456vukyptfi6y`.
The realizer's exact frozen configuration CID is
`baguqeeratlk326nodsva4rxwm65xgnpenhcovspm7crtyd4enaqhgjciqayq`,
and its source-withheld rendering-spec CID is
`baguqeera72pqowlkovfqvydbtk5lxc7g42o75xtfgmx7cm4vqdvnaimjpjvq`.

Both tied arms achieved macro end-to-end loss `0.0883333334` after per-case
aggregation, with a 95% seeded case-cluster bootstrap interval
`[0.0383333334, 0.1366666668]`. Both passed source-copy, polarity, and full
coverage gates on every scheduled coordinate. The representative used five
coordinates, 15 component calls, and zero model calls. The selective arm used
25 coordinates and 75 component calls but also zero model calls: its repair
route was never activated. Consequently, the evidence does not show that
Leanstral, SyMAI, spaCy, autoencoder guidance, or learned repair improves this
canonical path.

Raw artifact CIDs are useful for byte-level auditing but are not substitutes
for the semantic report identities above:

- SRT-014 report:
  `bafkreih2qqfopijqrvxq6fda63laz5iloh227dw34s6zn7tbyk6dhcbk4e`
- replacement report:
  `bafkreifruyd4f64rtmewj4suirpde3425c5gccvkm65ehn4yjo4byuv27e`
- remediation manifest:
  `bafkreiariailns3nlwjvye7ukslov6be52el3khedit3ki2wrt6hhmrjre`
- canonical-design gate artifact:
  `bafkreifbirqwxmsgicuui5z7ingx3pylgt3wp6h4eybbizdvdvv4zj5ooq`

## Architectural boundary

The canonical path has two independently testable halves:

```text
structured text
    |
    | CanonicalStructuredTextCompiler@1
    v
canonical {"rules": [...]} IR + source-map receipt + diagnostics
    |
    | source map and originating text are withheld
    v
canonical {"rules": [...]} IR
    |
    | CanonicalStructuredTextDecompiler@1
    v
reconstructed text + attribution receipt
```

`canonical_contracts.py` is dependency-free except for CID utilities. It owns
the immutable request, result, error, source-map, attribution, and policy
contracts. SRT-016 and SRT-017 import these definitions; neither may redefine
or mutate them.

The default pipeline is deliberately deterministic:

- Compiler: the measured typed-deontic path, with no guidance, no repair, and
  no model call.
- Decompiler: the measured source-withheld canonical paraphraser.
- Structural validation: Hammer/CVC5 and Lean may verify artifacts after they
  are produced. They do not alter candidates or scores.
- Optional learned stages: none in the canonical default. A future version
  may add one only after a separately frozen experiment demonstrates benefit
  and defines bounded failure behavior.

## Canonical IR

The packaged JSON Schema is
`ipfs_datasets_py/logic/legal_ir/schemas/canonical_roundtrip_ir.schema.json`.
The semantic payload remains exactly:

```json
{
  "rules": [
    {
      "modality": "O",
      "actor": "permit_holder",
      "action": "file",
      "object": "notice",
      "conditions": ["work_begins"],
      "exceptions": [],
      "temporal": ["within_10_days"]
    }
  ]
}
```

This exact shape preserves direct CID and L1 compatibility with the measured
benchmark. `CanonicalRoundTripIR.ir_cid` is
`cid_for_dag_json({"rules": [...]})`. A rule CID is likewise the DAG-JSON CID
of its exact seven-field object. Text bodies use raw CIDs over UTF-8 bytes.
Every CID is CIDv1/base32/sha2-256.

The seven fields are stable in v1. Actor, action, object, and qualifier values
are open vocabulary. Modality is the measured deontic operator set `O`, `P`,
or `F`, because the selected realizer has no reviewed grammar for another
operator. Holdings, assertions, and other non-deontic operators are explicit
unsupported/new-version semantics rather than arbitrary modality strings. The
production API does not expose the benchmark fixture's allowed-atom lists and
does not impose its 16-rule, eight-qualifier, or 512-character experimental
caps. The larger schema bounds are operational denial-of-service limits, not
a legal ontology. A semantic facet that cannot be represented in these seven
fields must be surfaced as `UnsupportedSemantic`; it must not be silently
dropped. Adding a new semantic field requires a new schema/interface version
and a migration.

Rules and qualifier arrays are canonically ordered by the shared Python
contract. Duplicate qualifier strings collapse. This makes semantically
equivalent construction order produce one DAG-JSON identity while retaining
duplicate rules when multiplicity is meaningful.

## Compiler contract

`CompilerRequest` binds:

- the source text through a raw CID,
- an operator-supplied request ID,
- the exact parity-policy CID,
- a caller-supplied open atom vocabulary,
- whether explicit partial output is allowed, and
- bounded JSON configuration.

The vocabulary is explicit request data, never an implicit benchmark fixture.
It has the same four general categories needed by the measured projection
(actors, actions, objects, and qualifiers), but accepts arbitrary caller
values. SRT-016 conformance passes each frozen case's public vocabulary
explicitly to reproduce its L1. Normal production calls must supply a reviewed
domain vocabulary and must not import those five-case lists or treat them as a
legal ontology. Deriving a vocabulary automatically would be a new,
unmeasured constructor stage; it is outside v1 and requires a separately
frozen benchmark before adoption.
The five frozen fixture vocabularies are test-only conformance inputs;
replacement parity does not establish performance for a new domain vocabulary.

The compiler returns `CompilerResult`. Success contains a non-empty canonical
IR, source-map receipt, provenance, diagnostics, and a component trace.
Source-map entries bind one IR rule and field path to a half-open character
span in the source's raw CID. The source-map receipt is a DAG-JSON CID over
the request CID, canonical IR CID, and every entry.

Unsupported meaning follows two explicit dispositions:

- `abstain`: no IR is returned; the result carries a structured
  `unsupported_semantics` error.
- `explicit_partial`: permitted only when the request opted in. The partial
  regions remain enumerated in the result and are never presented as complete.

Invalid input, missing components, component exceptions, empty output,
unsupported semantics, and policy mismatch are terminal typed errors. There
is no silent fallback to another constructor, model, vocabulary, or policy.

## Decompiler contract and source withholding

`DecompilerRequest` contains only:

- canonical semantic IR (and therefore its reproducible IR CID),
- request ID,
- parity-policy CID, and
- bounded public configuration.

It contains no source text, source map, source path, source cache, native
constructor record, gold IR, or prior reconstruction. Nested configuration is
checked for those channels. The implementation must not resolve the source
CID, query an external content store, or inspect compiler-private state.

`DecompilerResult` succeeds only with nonblank UTF-8 text, its matching raw
CID, deterministic component attribution, and no error. Model use, if a future
version authorizes it, must be visible as a non-deterministic component trace
with a model receipt CID. The selected v1 trace is deterministic and cannot
carry a model receipt.

## Source maps and unsupported semantics

Source maps are compiler evidence, not decompiler input. This separation
allows reviewers to trace an IR field to source while making source leakage
through the realization path structurally harder. Offsets are Unicode
character offsets in a half-open interval `[start, end)`, tied to the raw
source CID. They are evidence pointers, not permission to fetch content.

For caselaw, likely unsupported v1 features include competing holdings,
procedural posture, authority weight, quoted versus adopted reasoning,
multi-document citation relations, and fact-to-rule analogies. The compiler
must either map those concepts into an explicitly reviewed new schema version
or report them. It may not force them into a benchmark atom vocabulary.

## Versioning

The stable v1 identifiers are:

- `CanonicalStructuredTextCompiler@1`
- `CanonicalStructuredTextDecompiler@1`
- `CanonicalRoundTripContracts@1`
- `CanonicalRoundTripIR@1`
- `ipfs-datasets.canonical-roundtrip-ir.v1`
- `CanonicalRoundTripParityPolicy@1`

Changing field meaning, CID scope, canonical ordering, source-withholding
rules, terminal-status invariants, or policy comparison semantics is a
breaking change. Additive implementation telemetry may evolve only outside
the CID-addressed contract or under a separately versioned receipt.

## Frozen parity policy

The policy at
`docs/benchmarks/semantic_roundtrip_canonical_parity_policy.json` has CID
`baguqeera5g5z4yvncxbn3uk4ftqmnxxmmclwpnwjpdshiy52la2o5bzdk27a`.
Its CID is `cid_for_dag_json(document_without_policy_cid)`.

SRT-018 compares canonical minus selected end-to-end loss, where lower is
better. It first aggregates repeats within each case, then performs an
unweighted macro average across cases. Uncertainty uses a seeded percentile
case-cluster bootstrap with seed `17291`, 10,000 samples, and 95% confidence,
resampling cases only after within-case aggregation. Noninferiority passes
only when the paired difference's upper confidence bound is at most `0.03`.
The three selection gates must also pass, and a failed or missing coordinate
has loss one.

The margin is frozen before SRT-018 and is not inferred from its outcomes. A
three-percentage-point maximum regression is materially below the selected
baseline's observed macro loss while allowing small implementation-boundary
differences. This policy tests parity; it does not establish correctness on
caselaw outside the frozen cases, nor does it authorize production promotion.
