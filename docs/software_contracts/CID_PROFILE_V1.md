# Software-Contract CID Profile v1

Status: normative for symbolic contract analysis content identity
(DSCON-G040 / goal packet `goal_packet/content_identity/ipfs_datasets_py/43083d90d46a`).

Machine authority lives in:

- Implementation: `ipfs_datasets_py/logic/software_contracts/content.py`
- Golden vectors: `tests/fixtures/software_contracts/cid_vectors.json`
  (payload produced by `cid_vectors_document()`; Python tests enforce parity
  even when the fixture file has not yet been materialized)

Profile id: `software-contract-cid-profile-v1`  
Profile version: `1.0.0`

## Goal

Select one strict, versioned CIDv1 profile for:

1. **Source bytes** (tracked blobs, file contents, raw receipt payloads)
2. **Structured analysis artifacts** (IR records, receipts, findings, cache
   keys, policy documents encoded as JSON/IPLD data-model values)

and reconcile incompatible canonicalization paths across `ipfs_datasets_py`
and accelerator code by **adapting** the fail-closed DAG-JSON path from
`utils.cid_utils`, **not** copying permissive helpers (`default=repr`, finite
floats as first-class structured values, or `raw` codec over JSON text for
structured objects).

## Multiformats profile (frozen)

| Field | Source bytes | Structured artifacts |
| --- | --- | --- |
| CID version | 1 | 1 |
| Multibase | lowercase `base32` (`b…`) | lowercase `base32` (`b…`) |
| Multicodec | `raw` (`0x55`) | `dag-json` (`0x0129`) |
| Multihash | `sha2-256` (`0x12`, 32-byte digest) | `sha2-256` (`0x12`, 32-byte digest) |

No other version, base, codec, or hash function is admitted for software-contract
content identity unless a reviewed ADR supersedes this document and bumps the
profile version.

## Domain separation

| Domain | Python API | Codec | Input |
| --- | --- | --- | --- |
| Source | `cid_for_bytes(data: bytes)` | `raw` | Exact bytes; never re-encoded |
| Structured | `cid_for_obj(obj)` / `cid_for_structured(obj)` | `dag-json` | Reviewed structured value |

Calling `cid_for_obj` on host objects, paths, or binary payloads is a hard error.
Binary content must use the source domain.

## Structured identity type rules

Accepted types (recursive):

- `null`
- `bool` (`true` / `false`)
- `int` (arbitrary magnitude; JSON number without fractional part)
- `str` (Unicode; encoded as UTF-8 in the canonical byte stream)
- `list` of accepted values
- `map` / object with **only** `str` keys and accepted values

Rejected types (non-exhaustive but required):

- `float` (including finite floats) — encode ratios or fixed-point as reviewed
  strings or integers if needed
- non-finite numbers (`NaN`, `±Infinity`)
- `bytes` / `bytearray` / `memoryview` — use source identity
- `set` / `frozenset` / `tuple`
- filesystem `Path` and other host objects
- any type that would require `default=repr` or similar fallback

Key ordering: object keys are sorted lexicographically by Unicode code point
before serialization. Insertion order must not affect the CID.

## Canonical DAG-JSON byte contract

For a reviewed structured value `v`:

1. Validate types (fail closed).
2. Serialize with:
   - sorted keys
   - compact separators `(",", ":")`
   - `ensure_ascii=False` (non-ASCII remains UTF-8 in the byte stream)
   - `allow_nan=False`
3. Encode the JSON text as UTF-8.
4. Multihash with `sha2-256`.
5. Wrap as CIDv1 / `dag-json` / lowercase base32.

This matches a careful JavaScript implementation that:

1. Recursively sorts object keys
2. Uses `JSON.stringify` without whitespace
3. Hashes the UTF-8 bytes of that string
4. Builds CIDv1 `dag-json` `sha2-256` base32

Python and JavaScript **must** produce identical `expected_cid` values for every
entry in the golden vector set.

## Decode-and-recompute (every read)

Stored CIDs are untrusted labels until recomputed:

| Read path | API |
| --- | --- |
| Source | `decode_and_recompute_source(claimed_cid, data)` / `verify_source_read` |
| Structured | `decode_and_recompute_structured(claimed_cid, obj)` / `verify_structured_read` |

Algorithm:

1. `validate_cid` under the expected codec set for the domain.
2. Recompute the CID from the payload with the domain encoder.
3. Require exact string equality with the claimed CID.
4. On mismatch or profile violation, fail closed (do not use the payload).

Aggregate snapshot receipts may commit to a global repository-tree CID; reusable
blob, symbol, and slice cache keys must **not** embed that global tree CID (see
DSCON-G100 cache goals). This profile only defines how each payload is named.

## Relationship to existing helpers

| Module | Role relative to this profile |
| --- | --- |
| `utils.cid_utils.canonical_dag_json_bytes` | Related fail-closed JSON path; still allows finite floats. Software-contract structured identity is **stricter** (no floats). |
| `utils.cid_utils.canonical_json_bytes` | **Not** used: applies `default=repr`. |
| `utils.cid_utils.cid_for_obj` | Defaults to `raw` over permissive JSON. Software-contract `cid_for_obj` uses `dag-json` over strict structured values. |
| `logic.ipld_cid` | Profile D helper with `ensure_ascii=True`. Not authoritative for software contracts. |
| `benchmarks.logic_pipeline.content_addressing` | Benchmark bridge; must stay byte-compatible for shared cases but is not the contract owner. |

Sole owner of the software-contract CID profile: this document plus
`logic/software_contracts/content.py`.

## Golden vectors

Normative cases are defined by `cid_vectors_document()` and, when present, the
fixture file:

`ipfs_datasets_py/tests/fixtures/software_contracts/cid_vectors.json`

Schema: `ipfs-datasets.software-contract-cid-vectors.v1`

Each vector records domain, codec, multihash, base, version, payload
(`bytes_hex` or `value` + `canonical_utf8` / `canonical_hex`), and
`expected_cid`. Python unit tests recompute every CID. JavaScript consumers
must match the same `expected_cid` field for cross-runtime parity.

Representative fixed points (recomputed by the implementation; do not edit by
hand without regenerating the full document):

| id | domain | notes |
| --- | --- | --- |
| `source.empty` | source | empty blob |
| `source.hello` | source | ASCII `hello` |
| `source.unicode_utf8` | source | UTF-8 `café` |
| `structured.null` | structured | `null` |
| `structured.simple_map` | structured | `{"a":2,"b":1}` regardless of insertion order |
| `structured.nested_unicode` | structured | nested map/list with non-ASCII string |

Regenerate the on-disk fixture (when the path is writable):

```python
from pathlib import Path
from ipfs_datasets_py.logic.software_contracts.content import (
    materialize_cid_vectors_fixture,
)

materialize_cid_vectors_fixture(Path("ipfs_datasets_py"))
```

## Acceptance mapping (DSCON-G040)

| Acceptance criterion | Enforcement |
| --- | --- |
| Structured identity accepts only reviewed types | `validate_structured_value` / `canonical_dag_json_bytes` |
| Rejects floats, bytes, sets, paths, NaN, host objects, repr fallback | same; no `default=` on `json.dumps` |
| Source uses raw / sha2-256 | `cid_for_bytes` |
| Structured uses dag-json / sha2-256 / base32 | `cid_for_obj` |
| Decode-and-recompute verifies every read | `decode_and_recompute_*` / `verify_*_read` |
| Python and JavaScript golden vectors match | `cid_vectors_document` + fixture path + unit tests |

## Cache binding (DSCON-G100)

`logic/software_contracts/cache.py` is the authoritative consumer of this CID
profile for reusable analysis caching. Its `AnalysisCacheKey` binds the source
CID, complete transitive dependency closure, analyzer, configuration,
semantics, policy, solver, toolchain, and result schema. It deliberately omits
the global repository-tree CID so an unrelated tree change cannot invalidate
every reusable shard.

`ImmutableCAS` publishes canonical objects with write/fsync/link-no-replace and
performs decode-and-recompute plus schema checks on every read. Mutable exact-key
indexes carry no trust and may be rebuilt or discarded. `CacheReceipt` binds a
key to its result CID; `UNKNOWN`, negative, unsupported, incomplete, stale, and
error results require bounded leases and never satisfy completion.
`AggregateSnapshotReceipt` separately binds verified shard-receipt CIDs to the
global repository-tree CID and rejects wrong tree or shard membership.

| DSCON-G100 acceptance criterion | Enforcement |
| --- | --- |
| Atomic immutable writes | `ImmutableCAS._publish` uses fsynced staging plus atomic no-replace link |
| Recompute identity and schema on reads | `ImmutableCAS.get` / `get_bytes` |
| Poisoning and truncation reject | canonical byte and recomputed CID checks |
| Toolchain, policy, dependency changes miss | all are bound by `AnalysisCacheKey` |
| Tree CID absent from reusable key | closed key schema has no tree field |
| Tree CID present in aggregate receipt | `AggregateSnapshotReceipt.repository_tree_cid` |
| Unknown/negative results are bounded | `CacheReceipt` lease validation |
| Selective reverse-closure invalidation | `AnalysisCache.invalidate_source_closure` |

## Non-goals

- CIDv0, base58btc presentation, or `dag-cbor` as the default structured codec
- Silent coercion of floats, paths, or sets into JSON
- Using the global repository-tree CID inside per-blob cache keys
- Reinterpreting historical task IDs; DSCON-007 remains the compatibility
  identity for this objective

## Versioning

Breaking changes to accepted types, codecs, multibase, multihash, or the
canonical byte contract require a new profile version (`v2`) and a new document.
Existing task IDs remain versioned compatibility identities and are not silently
reinterpreted.
