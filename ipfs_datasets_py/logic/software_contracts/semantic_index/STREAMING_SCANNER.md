# Explicit streaming ordinary-source scanning

`scan_chunked_repository_streaming` is an explicit committed chunk consumer.
It admits the complete canonical manifest DAG against fresh Git metadata, then
hashes every unique immutable blob. Only one ordinary blob is captured at a
time; oversized, binary, malformed and nonregular inputs retain the same exact
snapshot identity and explicit limitation as the existing projection. Ordinary
files are never made opaque to avoid a cumulative retention limit.

Each ordinary Python/config file is analyzed in a fresh owned child. The child
runs the existing Python and pytest static analyzers, without importing or
executing target code. Python ASTs remain inside that child. Canonical per-file
facts are accumulated under a 32 MiB aggregate ceiling. A second child combines
pytest facts, applies the existing identity unification/configuration rules, and
resolves the symbol graph. Complete committed snapshot metadata has no captured
bytes and binds the existing paged evidence representation.

The fixed limits are 4 MiB captured per source file, 100,000 AST nodes per file,
1 MiB per semantic record, 8 MiB per file's facts, 32 MiB aggregate/final state
facts, and 100,000 semantic records per assembled phase. Typed limits may tighten
these ceilings. Every analyzer/assembly process has a 256 MiB `RLIMIT_AS`,
15-second CPU limit, at most 20 seconds elapsed time and bounded stdin/stdout/
stderr. Timeout, output excess or any failed worker kills and reaps the owned
child. Memory/AST/record/aggregate failures are structured refusals; no partial
state or invented analyzed input escapes.

The parent retains canonical fact bytes rather than a growing source/AST cache.
The final returned state contains bounded normalized semantic facts. These
canonical byte/count ceilings are not a hard bound on total parent RSS: Python
object overhead, imported dependencies and native allocations are separate.
Observations distinguish the largest captured blob, accumulated fact bytes,
Linux worker `ru_maxrss`, and the worker address-space limit. A real test consumes
138,410,910 unique committed bytes in 66 ordinary Python files, verifies every
source CID, and measures parent Python allocations with `tracemalloc` separately
from child RSS. Git decoding uses its existing independent 128 MiB address cap.

A small mixed fixture proves exact snapshot-CID equality and exact state equality
with the existing scanner after both use the same paged evidence artifact. The
legacy scanner's original evidence envelope is unchanged. Python/pytest symbol,
artifact and edge identities are preserved, including cross-file fixture scope,
config/lock edges, opaque inputs and parse failures. This API changes no default
scanner or snapshot behavior and offers no incremental reuse.

Worker source hashes are checked before and after each analysis and assembly.
The complete scan also fences its initial process profile and committed Git
state. The profile records interpreter version, dependency import root, fixed
process bounds and worker source hash. Native qualification must still bind all
producer/dependency bytes and immutable request inputs; this local protocol is
not an independent execution certificate or a full dependency attestation.

Streamed byte work is separately qualified by the existing chunk admission
limits; allowing more cumulative work never raises the retained-byte, AST or
fact ceilings. The ordinary retained projection continues refusing populations
above its existing 128 MiB limit. Large semantic state indices/artifact envelopes
or complex ASTs can still exceed fixed bounds and refuse. This change does not
page those other indices, analyze oversized opaque code, acquire nested Git
forests, grant semantic/completion authority, or modify live services or boards.
