# Logic API v1 compatibility

This document defines `LogicAPICompatibility@1`, the reviewed compatibility
boundary that predates the general software-verification API. The executable
source of truth is
`tests/fixtures/logic/api_v1/manifest.json`; the corresponding unit test checks
that the current imports and deterministic payloads still match it.

## Compatibility promise

Version 1 keeps the reviewed FOL, deontic, modal, CEC/DCEC, TDFOL, and FLogic
entry points available while newer logic families are added. It covers Python
imports, CLI parsing, MCP tool discovery, bridge descriptions, caches, simulated
ZKP attestations, lazy imports, and the meanings of proof outcomes.

The promise is behavioral, not merely syntactic:

- exported names remain in their reviewed order;
- representative formulas and result envelopes serialize exactly as recorded;
- a missing optional tool is reported as unavailable and never as success;
- imports do not install packages, access the network, start processes, mutate
  the environment, or write files; and
- adapters, caches, learned candidates, monitors, and attestations never gain
  theorem-proof authority by being routed through a public API.

## Frozen Python imports

The canonical external import is `ipfs_datasets_py.logic.api`. Its exact
`__all__` list is recorded in the manifest. Existing family paths remain
supported:

| Family | Reviewed path | Representative surface |
| --- | --- | --- |
| FOL | `ipfs_datasets_py.logic.fol` | `FOLConverter`, `convert_text_to_fol` |
| deontic | `ipfs_datasets_py.logic.deontic` | converter, norm IR, graph, knowledge base |
| modal | `ipfs_datasets_py.logic.modal.compiler` | deterministic compiler and result/config records |
| CEC/DCEC | `ipfs_datasets_py.logic.CEC` | framework and lazy legacy prover/converter wrappers |
| TDFOL | `ipfs_datasets_py.logic.TDFOL` | formulas, parsers, knowledge base, prover and proof records |
| FLogic | `ipfs_datasets_py.logic.flogic` | frame types, ErgoAI wrapper, cache and ZKP result wrapper |
| bridges | `ipfs_datasets_py.logic.bridge` | registry, reports and `ProofGateResult` |
| caches | `ipfs_datasets_py.logic.common` | bounded and proof caches |
| ZKP | `ipfs_datasets_py.logic.zkp` | simulated proof/attestation compatibility API |

`Formula`, `Predicate`, `Variable`, `Constant`, `ProofStatus`, `ProofStep`, and
`ProofResult` on `logic.api` are the TDFOL core objects, not parallel types.
CEC/DCEC, TDFOL optional helpers, FLogic, and ZKP implementations continue to
load lazily. The deprecated `logic.tools` alias is outside the canonical import
path but remains a package-level compatibility shim until v2.

The manifest also freezes exact enum values and canonical examples for TDFOL
formula rendering, FLogic frame/class rendering, proof results, cache metadata,
bridge availability, and simulated ZKP records. Those examples are wire
fixtures; changing punctuation, status spelling, field names, or nullability is
a compatibility change.

## CLI contract

`ipfs_datasets_py.logic.cli.create_parser()` uses the program name
`ipfs-datasets logic`, accepts the global `--json` flag, and exposes these
commands:

- `convert-fol TEXT`
- `convert-deontic TEXT`
- `analyze-normative SENTENCE [--document-type legal]`
- `add-theorem` with required `--operator` and `--proposition`
- `query-theorems QUERY` with operator, jurisdiction, domain, limit, and
  relevance filters
- `check-document DOCUMENT_TEXT` with document and legal-context options

The manifest records every argument, option spelling, default, type, required
flag, and operator choice. A handler exception returns exit code `2`; JSON mode
returns exactly an `{"error": ..., "success": false}` envelope. Parser errors
remain argparse errors and are not converted into successful results.

## MCP contract

`ipfs_datasets_py.mcp_server.tools.logic_tools` exposes the exact ordered tool
list in the manifest. It includes temporal-deontic, TDFOL, CEC/DCEC, capability
and health, graph/RAG, and FLogic operations.

MCP transport success is not proof success. Tool payloads retain their domain
status (`proved`, `is_theorem`, `status`, `consistent`, or similar). Four
reviewed optional-absence envelopes are executable fixtures:

- `cec_parse: LogicProcessor not available.`
- `tdfol_prove: LogicProcessor not available.`
- `logic_health: LogicProcessor not available.`
- `flogic_query: F-logic module not available.`

Each envelope has `success: false`. Optional-tool absence must stay distinct
from a valid negative result, an unknown proof result, malformed input, a
timeout, and a successful call.

## Result and proof-authority meanings

The v1 statuses are intentionally non-interchangeable:

| Observation | Meaning | Theorem-proof authority |
| --- | --- | --- |
| `ProofStatus.PROVED` | the selected proof path reports a derivation | only as strong as that path and its checked assumptions |
| `ProofStatus.DISPROVED` | the selected path reports a countermodel/disproof | conclusive for the represented claim and bounds |
| `UNKNOWN`, `TIMEOUT`, `ERROR`, `UNPROVABLE` | no conclusive proof was obtained | none |
| optional tool unavailable/unsupported | the operation could not be attempted on that path | none |
| FLogic `SUCCESS` | an FLogic operation completed | not automatically a theorem proof; inspect status and `simulation_mode` |
| cache hit | an exact prior result was replayed | exactly the cached authority, never more |
| bridge `compiles` | every attempted proof-gate item was valid | compilation/gate evidence only |
| modal/learned/shadow output | candidate or advisor output | none until independently checked |
| ZKP attestation | a proof record/public-input binding was produced or checked | does not prove source translation or raise the bound receipt’s authority |

`ProofGateResult` records `unavailable_count`, `error_count`, and
`failed_count` independently. In particular, an unavailable optional prover has
`compiles: false` and failure ratio `1.0`; callers must not translate it into a
soft theorem-proof success.

The v1 `ipfs_datasets_py.logic.zkp` package explicitly describes itself as a
simulation. Its `ZKPProof`/`SimulatedZKPProof` compatibility record is useful
for demonstrations and attestations, but is not a production cryptographic
proof. Even a production ZKP can only attest the statement and receipt it
binds; it does not establish the correctness of an earlier source-to-logic
translation.

## Optional dependencies and lazy imports

Importing `ipfs_datasets_py.logic` or `ipfs_datasets_py.logic.api` must be quiet.
It must not eagerly load the heavy integration namespace, external prover
router, modal implementation, or ZKP implementation. Import and declaration
discovery are observational: no installation, network, subprocess, environment
mutation, or filesystem write is allowed.

Optional capability is probed when the related operation or lazy symbol is
used. Absence is then returned or raised through the documented unavailable
path. It is never represented by a fabricated empty proof, a `success: true`
envelope, or a cache entry with higher authority.

## Changing the v1 contract

A deliberate compatibility change requires all of the following in one review:

1. update the implementation or add a versioned adapter;
2. update `tests/fixtures/logic/api_v1/manifest.json`;
3. update this document and the executable compatibility test;
4. explain status, optional-dependency, and proof-authority consequences; and
5. provide a migration path when an existing name or payload cannot remain.

Additive implementation work should normally leave this fixture unchanged.
Never refresh the manifest mechanically just to make a failing test green:
review the observed difference, especially any change that could collapse
unavailable, unknown, cached, proposed, attested, and proved outcomes.
