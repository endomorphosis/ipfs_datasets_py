# Proposed legal graph aggregation

These APIs preserve explicitly supplied legal IR as ordered, source-scoped graph
proposals. This implements preparatory subsets of LAC-040, LAC-044 and LAC-045; legal interpretation, admission and whole-corpus completeness remain unverified.

## Official extraction and exact occurrences

Retain local official GovInfo HTML and an independently trusted `custody.json`
with `source_url`, integer `edition`, `legal_id`, `document_revision`, and
`html_sha256`. Extraction checks the supported URL/heading/paragraph shape;
the retained hash establishes byte custody. It does not authenticate a download.
V2 character and UTF-8 byte selectors address the immutable **normalized
`document_text` view**, never raw HTML bytes. Repeated identical text at different
positions has distinct occurrence IDs. `exact_view_occurrences` returns all
exact matches, including overlap, without choosing an interpretation.

Run the snippets in the repository with normal dependencies installed. Inputs
are retained local files; these examples perform no network or model inference.
`selected-range.json` has `char_start` and `char_end`. `declared-scope.json` has
`jurisdiction`, `instrument`, integer `edition`, `applicability`, `definition_scope`.

```python
import hashlib
import json
from pathlib import Path
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as graphs

custody = json.loads(Path("custody.json").read_text())
raw = Path("source.html").read_bytes()
assert hashlib.sha256(raw).hexdigest() == custody["html_sha256"]
document = context.extract_document(raw, url=custody["source_url"],
    edition=custody["edition"], legal_id=custody["legal_id"])
selector = context.source_selector(document, raw,
    **json.loads(Path("selected-range.json").read_text()))
source = graphs.bind_source_occurrence(document, raw, selector=selector,
    document_revision=custody["document_revision"])
scope = graphs.bind_scope(**json.loads(Path("declared-scope.json").read_text()))
```

The selector must lie inside one exact extracted paragraph occurrence, and source/scope editions must agree. Scope strings remain caller declarations.
## Explicit AST, entity and assertion proposals

`canonical_rules_v1` validates the existing `CanonicalRoundTripIR` contract while
preserving supplied rule/qualifier order and repetitions. `normative_scope_v1`
validates the existing normative scope contract and requires a separately
supplied exact `scope_request`. Neither profile infers verified source meaning.
```python
proposal = json.loads(Path("ast-proposal.json").read_text())  # ast, profile
arguments = {key: proposal[key] for key in (
    "semantic_declarations", "dependency_refs", "evidence_refs", "scope_request"
) if key in proposal}
graph = graphs.build_graph(proposal["ast"], profile=proposal["profile"],
    source=source, scope=scope, **arguments)
assert graphs.graph_to_ast(graph) == proposal["ast"]
graphs.validate_graph(graph, ast=proposal["ast"], profile=proposal["profile"],
    source=source, scope=scope, **arguments)
```

Optional `semantic_declarations` has `entities` and `assertions` lists. Entities
require `entity_key`, `kind`, `label`, `source_selector`, `definition_kind`,
`ast_path`, `ambiguity`, `evidence_refs`. Kind is `mention`, `concept` or
`definition`; concepts use null selectors/definition kinds, mentions exact
subselectors/null kinds, and definitions exact subselectors plus a distinct
`means`, `includes` or `deems` tag. These tags remain **unreviewed declarations**,
not encoded equivalence, inclusion or deeming semantics. `ast_path` is a JSON
pointer or null. Assertions require `assertion_key`, `subject_key`, `predicate`,
ordered `object_keys`, `ambiguity`, `evidence_refs`, `dependency_refs`.

References have exactly `artifact_id`, `artifact_sha256`, `role`; relevance
remains unverified. Mention IDs bind occurrence/revision/scope; concept IDs bind
explicit key/revision/scope. Labels never merge entities. `graph_to_ast` checks
closed schemas and regenerates ordered/typed envelopes. `validate_graph` also
compares independent expected inputs: retain those outside the received graph.
## An already prepared EntityCache

Use an input-bound local cache with completed containment preparation and an
unclaimed `prepared` section. Freeze the complete ordered occurrence inventory
independently; never derive it from proposed rows or legacy `contained_span_ids`.

```python
from ipfs_datasets_py.logic.autoformal.entity_cache import EntityCache
trusted_inputs = dict(document=document, raw_html=raw,
    document_revision=custody["document_revision"], scope=scope,
    occurrences=json.loads(Path("graph-requests.json").read_text()),
    expected_population=json.loads(Path("expected-occurrences.json").read_text()))
entity_id = Path("prepared-section-id.txt").read_text().strip()
cache = EntityCache("prepared-entities.duckdb")
try:
    report = cache.build_proposed_graphs(entity_id, **trusted_inputs)
    payload = cache.export_proposed_graphs(report, entity_id, **trusted_inputs)
    assert cache.import_proposed_graphs(payload, entity_id, **trusted_inputs) == report
finally:
    cache.close()
```

Each occurrence requires `source_span_id`, `source_sha256`, exact v2 `selector`,
`ast`, `profile`; optional `source_text` and graph arguments are checked. Expected
rows have exactly `source_span_id`, `occurrence_id`, `source_sha256`. Membership,
order, multiplicity and text hashes must match. Both AST/profile null retains an
unresolved row; it cannot silently discard substantive graph arguments.
The detached `entity-cache-source-graph-proposals/v1` report does not persist
graphs or change queue/claim/resume state. `population_complete` covers only the
supplied inventory; `complete_section_coverage_verified` stays false. The local
EntityCache queue and HF materialized graph index are distinct schemas. SpanCache
`rule_json`/Hub rows require explicit validated adapters. Legacy sealed/admitted/formalized flags confer no authority.

## Independently pinned dependencies and reverse invalidation

Persist graph bytes using `graphs.wire(graph)` and hash those exact bytes for
`artifact_sha256`; `graph_id` hashes a different payload. Keep unresolved rows in
the aggregation report. `dependency-inputs.json` contains `artifacts`, `edges`,
`expected_artifact_ids`. Each artifact has `artifact_id`, `artifact_sha256`,
`dependency_pins`; each edge has `dependent_id`, `dependency_id` pointing toward
the dependency. The independently expected ordered artifact list prevents
omissions within that declared population, without proving legal exhaustiveness.
```python
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as deps
manifest = deps.build_dependency_manifest(
    **json.loads(Path("dependency-inputs.json").read_text()))
Path("dependency-manifest.json").write_text(json.dumps(manifest))
# Later replay: expected_pin comes from a separately retained trusted job receipt.
expected_pin = Path("trusted-manifest-pin.txt").read_text().strip()
deps.validate_dependency_manifest(manifest, expected_manifest_sha256=expected_pin)
observations = dict(
    observed_artifact_sha256s=json.loads(Path("current-artifact-hashes.json").read_text()),
    observed_pins=json.loads(Path("current-pin-hashes.json").read_text()))
invalidation = deps.invalidate_dependencies(manifest,
    expected_manifest_sha256=expected_pin, **observations)
deps.validate_invalidation(invalidation, manifest,
    expected_manifest_sha256=expected_pin, **observations)
```

Pins explicitly list all seven categories: `root`, `source`, `revision`,
`context`, `definition`, `model`, `policy`, each containing `{key, sha256}` rows.
Null hashes mean missing evidence; empty lists mean no declared pins. Observations
must freshly rehash/check every artifact (null if unavailable), with all seven
pin categories mapping declared keys to hashes/null. Never copy old pins as
current observations or trust the incoming manifest's own hash as its expected
pin. Changed/unbound/missing inputs seed reverse invalidation through all
reachable dependents, including cycles; reuse remains a custody claim only.

## Remaining work

These bounded paragraph-contained profiles do not resolve cross-paragraph
qualifications, governing context, definitions, ambiguity or doctrine consistency.
Locators alone never attach governing context. Exceeded bounds fail without
truncation. Full-section coverage, direct bulk backfill, Hub-index interchange,
independent semantic review, cross-instrument reconciliation and Lean 4 export/
checking remain downstream work. There is no accepted graph view or complete corpus claim; all authority flags stay false and task acceptance preparatory.
