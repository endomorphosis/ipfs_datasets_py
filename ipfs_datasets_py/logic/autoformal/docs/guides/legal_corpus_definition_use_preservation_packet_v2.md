# Retained V2 corpus preservation packets

The [packet reader](../../legal_corpus_definition_use_preservation_packet_v2.py)
validates an immutable collection of retained file bytes against the current
public source, review and preparation owners. It supports the exact twelve-module,
fifteen-theorem profile produced by the [V2 corpus preservation executor](legal_corpus_definition_use_preservation_v2.md).
It performs no Lean execution or installed compiler inspection.

**Qualified on October 15, 2026:** all 68 focused tests passed without failures,
errors or skips. Separate replay consumed both previously compiled authored
FOL/TDFOL packets, retaining all 98 packet files and 30 historical theorem
observations. Independent readback checked all 110 exports and reconstructed
the four AST roles in each family. Three altered-evidence controls refused.
There were zero new Lean invocations, compiler probes or cache writes. The
[qualification receipt](../../../../../../../artifacts/legal-ir-corpus-packet-20261015-01/qualification-receipt.json)
binds the exact inputs, sources, requests and readback evidence. Unit packet
fixtures contain explicitly synthetic historical claims and remain separate
from the replay of actual earlier native evidence.

This is an engineering readback boundary for later retrieval and index integration.
The result preserves the whole historical native receipt and records the current
readback separately. A historical success does not become a fresh compilation,
kernel proof, legal interpretation, source review or cache admission.

## Inputs and commitments

`validate_definition_use_preservation_packet_v2` accepts:

- An immutable, path-sorted tuple of exactly 49 `(relative_path, bytes)` pairs.
- The original typed nine-file `DefinitionUseCorpusPreparation` and original assessment bytes.
- Complete original review inputs, including source, policy, dependency observations and evidence bytes.
- Independent SHA256 commitments for the complete preservation preparation, complete original corpus preparation, assessment file, raw native receipt file and whole packet inventory.
- The exact versioned toolchain and a two-entry map of historical sibling `lake`/`lean` paths to externally pinned binary hashes.

The caller must obtain expected commitments from independently trusted provenance.
An invented self-sealed receipt with matching invented expected pins does not
authenticate execution. `packet_sha256(files)` computes the whole packet
commitment; computing it from incoming files supplies no independent provenance.

The packet commitment hashes compact canonical UTF8 JSON of sorted inventory
rows, each with `path`, integer `bytes` and `sha256`. The receipt commitment hashes
its exact original file bytes, including whitespace. It is separate from the
receipt payload's record CID. Keep these identities distinct.

| Packet group | Required population |
| --- | --- |
| `project/` | Sixteen exact project inputs and `corpus-manifest.json` |
| `executed-inputs/` | Sixteen executed inputs, each equal to the current regenerated input |
| `compiled/` | Twelve nonempty retained `.olean` files with exact recorded lengths and hashes |
| Root logs | Complete `stdout.txt`, `stderr.txt` and `runner-error.txt` |
| Root receipt | Exact original `build-receipt.json` |

Before loading operation owners, the reader checks input types and bounds,
closed relative paths, sorted unique membership, packet and raw receipt pins,
strict JSON, historical runtime consistency and full log commitments. Limits
include 64 MiB per complete packet, 48 MiB for original input material, 8 MiB per
source/executed/artifact group, 1 MiB per record and 12 MiB per log.

Filesystem acquisition belongs to the caller's existing transport: directory
inventory, regular-file identities, links, races and immutable byte acquisition.
This bytes-only API does not certify a filesystem directory. It neither reads
the named historical compiler binaries nor probes their current versions.

## Current replay and historical observations

The reader regenerates the preservation project through the current public
preparation and native-validation owners twice. The full expected preparation
commitment, original source/review/dependency state, all project text, original
interpretation, theorem identities and original assumptions must match.
Historical producer pins must equal current producer pins. Producer drift
refuses this profile; it requires separate migration or requalification work.

A detached snapshot binds every original review-input value, including exact
bytes and ordinary value types. The final check also catches mutation immediately
after the second successful public replay. The operation leaves original
preparation objects and packet bytes unchanged.

All fifteen theorem names and their empty axiom observations must appear in the
complete retained logs, partitioned into twelve concrete preservation checks and
three original conditional theorems. The recorded process lifecycle must be
internally consistent, with joined workers, completed tracking and observed
cleanup. Historical PIDs and birth times are not compared with the new reader's
process or inspected for current liveness.

The returned frozen `RetainedDefinitionUsePreservationPacket` contains the exact
input file tuple and sealed `observation_json`. Its `.to_dict()` exposes:

- `readback_verified`, `current_preparation_replayed` and `historical_kernel_observations_retained` as true.
- The unchanged `historical_native_receipt`, exact packet inventory, external commitments and current/historical producer pins.
- Fresh compilation, native execution, kernel checking, installed compiler validation, proof-cache compatibility and admission as false.
- All source/legal/review/model/training authority as false, with zero training and evaluation masks.

The existing native `receipt_reference` remains an unreviewed address-only
`EvidenceRef`. This reader does not modify it or convert engineering observations
into a legal-domain `FormalizationArtifact` or typed theorem `ProofReceipt`.

## Integration sequence

Run project tests and actual packet replay through the existing frozen-request
owned validation launcher. Use the existing transport to acquire the complete
packet and expected original inputs; call this reader before interpreting
retrieved historical observations.

The qualification driver initializes the existing reasoning dependency during
owned startup before guarding every preparation and packet replay call. In this
environment, that package initialization can invoke NumPy's CPU capability
probe. The zero native/compiler counts describe the guarded operations; they do
not assert that the entire launcher and dependency startup created no OS child
processes. The initial guard refusal is retained as failed evidence and has no
successful readback claim.

The next step is a bounded observational projection through existing index
owners. It must record an unknown result, no kernel-acceptance credit and visible
write failures, while retaining exact immutable payload references and key
dimensions. The existing graph dependency owner remains responsible for declared
reverse invalidation.

Theorem-specific typed receipt lineage, compiler artifact reuse, actual DuckLake
activation and clean-build equivalence each require separate qualification.
Reviewed statutory source correspondence, broader logic constructors and model
convergence also remain separate acceptance gates. No token savings or model
quality improvement is measured by retained packet readback.
