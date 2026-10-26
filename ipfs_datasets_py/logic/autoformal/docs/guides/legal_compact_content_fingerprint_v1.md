# Compact-content framed fingerprint v1

`logic/formalization/autoencoder/legal_compact_content_fingerprint_v1.py` is an
additive, standard-library-only fingerprint utility. It aims to preserve the
existing head's exact framed byte stream while avoiding creation of a bounded
copy and JSON encoder for every scalar leaf. It does not change a training
consumer, checkpoint, custody guard or historical report.

## API and reference contract

```python
fingerprint(value, *, maximum=24 * 1024 * 1024, allow_bytes=True) -> str
```

The result is a lowercase SHA256 hex digest. Refusals raise
`FingerprintError(ValueError)`. The input must remain stable while traversed.
The `maximum` argument is a plain integer from zero through 64 MiB, and
`allow_bytes` is a plain boolean. Zero permits an empty byte leaf when bytes are
allowed; it does not permit an empty JSON container or string.

The compatibility reference for these stable inputs is:

```python
captured = legal_compact_content_trained_runtime_v2._copy(
    value, maximum, allow_bytes=allow_bytes,
)
expected = legal_compact_content_head_v1._fingerprint(captured)
```

The head's standalone `_fingerprint` does not impose aggregate item/depth/byte
bounds. Conversely, the trained runtime's own `_fingerprint` has different `j`
framing and is not this utility's compatibility target. Acceptance parity applies
inside the new API's explicit argument bounds; it does not broaden those bounds
to every call that a private legacy function might accept.

## Exact stream and accepted values

| Value | Framed bytes |
| --- | --- |
| Plain dict | `d` + decimal entry count + `:`, then sorted string keys and their values |
| Plain list | `l` + decimal item count + `:`, then values in their original order |
| Plain bytes, when allowed | `b` + decimal raw length + `:` + original bytes |
| Other supported plain scalar | `j` + decimal canonical JSON byte length + `:` + canonical scalar JSON |

Dictionary insertion order does not change the stream. Repeated references to
one container are traversed separately; ancestor cycles refuse. Keys must be
plain strings. Tuples, subclasses, custom objects and non-string keys refuse.

Integers must satisfy `-(2**63) < value < 2**63`. Floats must be finite; plain
float `repr` preserves the JSON spelling of signed zero, exponent notation and
the distinction between integer and floating-point values. `None`, booleans,
integers and floats are encoded without per-scalar legacy `_wire` or `_copy`
calls. Strings use the standard-library `encode_basestring` implementation,
including its Python fallback, with `ensure_ascii=False` behavior and UTF8.
NUL and surrogate code points refuse; JSON control-character and quote/backslash
escapes retain their exact spelling. Bytes remain distinct from strings.

The utility streams chunks into SHA256. It materializes neither the complete
framed stream nor a detached input tree. A single escaped string and sorted
dictionary-key list may be allocated within the accepted input bounds.

## Bounds and failure behavior

Each visit consumes an item, including dictionary keys. The fixed limits are
12,000,000 visits and depth 96, matching the named runtime copy. Containers,
commas/colons, keys and scalar values charge the same JSON byte accounting as
that copy; byte leaves charge their raw length. This byte budget is not the
framed stream length. String charges are checked before escaped-byte allocation.

Keys are validated before sorting so custom comparisons cannot execute. Sorting
changes traversal order relative to the legacy copy, but all charges are
nonnegative and the complete accepted footprint is identical for stable inputs.
The first detected error and its message need not match the legacy implementation.
No partial digest is returned on failure.

The private `_stream(value, sink, *, maximum=..., allow_bytes=...)` helper is a
test seam. It emits byte chunks to `sink` and returns `None`. A failing input may
have emitted a prefix, which its caller must discard. Tests may collect small
successful streams for exact comparison; production `fingerprint` supplies only
the SHA256 update method. The sink is not an untrusted public callback interface.

## Qualification and consumer adoption

Byte compatibility must be qualified against the complete original source
leaves and retained checkpoint inputs. Include exact stream/digest parity,
boundary acceptance/refusal, insertion orders, aliases/cycles, float/int/bool
distinctions, Unicode/control escapes and the standard-library string fallback.
Compare matched copy-plus-fingerprint scopes and report wall time, CPU time and
memory with their boundaries. Faster leaf encoding, if observed, is not measured
training throughput or reconstruction improvement.

This utility does not authenticate source modules, acquire source/resource
leases, snapshot mutable inputs, cache object identities or preserve a training
session by itself. Any consumer adoption requires an explicitly reviewed owner
or consumer version. Preserve the bounded original-input copy, both original
and captured traversals, all four existing update guards, loaded-source checks,
numerical state checks, failure poisoning and close behavior. Do not monkeypatch
the old head, weaken checks, rewrite source pins or relabel old checkpoints.

No models, training, optimizer, solver, Lean build, network or filesystem action
is performed by this utility. It asserts no legal meaning, source fidelity,
holdout reconstruction or 384D/768D/4096D qualification. It has no effect on
unchanged consumers until a separately qualified adoption calls it.
