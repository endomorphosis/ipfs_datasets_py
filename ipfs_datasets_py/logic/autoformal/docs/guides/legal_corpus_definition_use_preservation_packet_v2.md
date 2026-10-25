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
[qualification receipt](../../../../../docs/autoformalization/evidence/legal-ir-preservation-publication-20261023.json)
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

The earlier next-step paragraph records the historical packet-reader boundary. The bounded observational projection already exists in the [preservation index owner](legal_corpus_definition_use_preservation_index_v2.md); reuse its UNKNOWN result, CANDIDATE/NONE authority boundary, visible failures and complete key dimensions rather than implementing another adapter.

The retained reader accepts only the official V2 twelve-module, fifteen-theorem, 49-file preservation profile. Parent, shared/aggregate and direct-incremental native receipts have different packet and preparation contracts and remain unsupported here; schema relabeling or a matching hash cannot substitute for a compatible reader.

## Current primary reconciliation — 153 cases / 459 phases passed

The [closed current-source qualification](../../../../../docs/autoformalization/evidence/legal-ir-preservation-publication-20261023.json)
passed 153 authored-fixture cases / 459 setup, call and teardown phases: 47
real-SQL persistence cases, 47 packet-index cases and 59 store regressions. Unit
packet execution claims remain authored fixture data. Real SQL writes and cold
close/reopen exercise fixture entries; this cohort does not replay the two
historical compiled packets or invoke Lean. One unchanged exact stdlib cold-index
child retains its 20-second timeout. The declared path-only reasoning namespace
executes genuine required leaf modules; the public reasoning package initializer
was not executed and its import surface remains unqualified. Original native,
storage and source READ custody closed for this generation.

The historical 68-case packet qualification, 153-case index qualification and
separate DuckDB 1.5.5 two-packet replay/readback above retain their original pins
and scopes. This current fixture qualification reuses the existing official-V2
reader and index; it adds no parent/shared/direct-incremental packet support,
proof usability, statutory meaning, training/gold, model quality or Lean
admission. All authority ceilings and zero masks remain unchanged.

At this publication-preparation cutoff, no new test cohort, historical packet/database replay, native or Lean run, or model execution has been performed. The linked portable evidence records the retained 153-case/459-phase primary composition and its declared reasoning namespace profile separately from the original 68-case packet qualification, original 153-case SQL/index qualification and historical two-packet replays. Those qualifications keep their original source/toolchain scopes. Preserved public companion differences do not establish whole-runtime byte identity with the 126 raw-compile observations/119 module origins or qualify the public reasoning initializer/reexports. Original receipts, packet/database exports and raw execution evidence remain unbundled and unavailable in a clean clone; the portable record supplies their immutable descriptors and scope, rather than substituting fresh runtime evidence.


## Opt-in direct parent-norm packet reader

`validate_parent_norm_native_packet_v1` is a separate opt-in sibling in this same
owner. `parent_norm_packet_sha256` commits its exact sorted 23-file inventory;
`packet_sha256` and `validate_definition_use_preservation_packet_v2` keep their
original official-V2 49-file contracts. Earlier unsupported-profile statements
above retain their original profile and publication cutoffs.

The direct reader accepts the original seven-file `DefinitionUseCorpusPreparation`,
complete parent correspondence and all original correspondence replay inputs.
It requires independent SHA256 pins for the full preparation and correspondence,
the exact receipt file and complete bundle, plus the selected versioned toolchain
and externally pinned sibling `lake`/`lean` binary identities. Computing a digest
from incoming evidence supplies no independent provenance.

```python
validate_parent_norm_native_packet_v1(
    packet_files, preparation, correspondence,
    expected_preparation_sha256=preparation_pin,
    expected_correspondence_sha256=correspondence_pin,
    correspondence_inputs=original_correspondence_inputs,
    toolchain=versioned_toolchain,
    expected_receipt_file_sha256=receipt_file_pin,
    expected_bundle_sha256=bundle_pin,
    expected_binary_sha256=historical_binary_pins,
)
```

The immutable sorted tuple contains eight `project/` files including the full
manifest, seven matching `executed-inputs/`, four nonempty `compiled/` artifacts,
and the root receipt plus three complete logs. Genuine
`validate_parent_norm_native_v1` opening and closing replay binds the complete
authored norm, original source/context/unresolved commitments and physical
parent inputs. Full logs must retain the single `original_norm_preserved`
empty-axiom observation. This theorem has only definitional alias-identity scope;
the supplied norm remains unreviewed and relational source binding remains null.

The resulting `RetainedDefinitionUsePreservationPacket` uses schema
`legal-corpus-parent-norm-native-packet-observation/v1` and profile
`replayed-retained-parent-literal-complete-authored-norm-native-byte-packet/v1`.
Its observation explicitly records:

- `receipt_consistency_only=true`; `accepted_execution`,
  `accepted_outer_operation` and `accepted_operation_result_bound` are false.
- `outer_operation_outcome="unprovided"`. A persisted `build_passed=true` receipt
  can precede an outer closing-custody refusal. The packet supplies no accepted
  outer result or closeout; consistency cannot establish accepted execution.
- The unchanged historical receipt, full inventory and current/historical
  producer commitments, with all authority flags false and training/gold masks zero.

Historical producer paths and hashes must exactly equal the current genuine
producer closure. There is no path normalization, resealing, relocation fallback
or automatic acceptance of the original frozen 23-case native generation.
Externally trusted raw pins remain provenance premises. Filesystem acquisition
and link/race custody belong to the external acquirer. The reader checks retained
lifecycle consistency without inspecting live PIDs or installed compiler bytes,
running Lean, rechecking oleans or writing a database.

The existing preservation index still accepts its official-V2 packet profile;
this direct parent-norm profile has no index adapter yet. Parent-shared and
incremental packet profiles remain separate. No norm-truth, concrete denotation,
statutory source/edition/meaning, model-accuracy, proof-cache, graph/corpus,
training/gold or unified Lean-corpus admission follows from this readback.

### Qualification of the direct parent-norm reader

The [accepted qualification](../../../../../docs/autoformalization/evidence/legal-ir-parent-norm-packet-consistency-20261025.json) passed 123 authored-fixture cases / 369 phases: 54 new reader controls and 69 selected packet/native pure regressions, under 199 frozen source files. Compiler, artifact and historical process claims in these fixtures are synthetic; genuine current parent preparation and physical-source replay remain separate from actual native execution. Original 185/68/23 campaigns keep their own generations and are not pooled or rerun. Receipt consistency grants no accepted execution, legal meaning, model accuracy, proof-cache, graph/corpus or training/gold authority; masks stay zero.
