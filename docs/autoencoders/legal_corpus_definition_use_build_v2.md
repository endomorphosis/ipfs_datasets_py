# Bounded V2 definition-use engineering builds

`logic/autoformal/legal_corpus_definition_use_build_v2.py` adds an explicit
build API for the [V2 conditional preparation](legal_corpus_definition_use_lake_v2.md).
It reuses the installed-toolchain checker, bounded process runner and closed
project transport. Import executes no compiler, version probe, model or network
operation. Existing preparation, shared-definition and incremental profiles are
unchanged.

The build profile is `bounded-v2-definition-use-conditional-build/v1`; receipts
use `legal-corpus-v2-definition-use-native-build/v1`. This is an engineering
execution profile for a caller-declared interpretation. A successful build
does not decide legal meaning, authenticate a reviewer, qualify a governing
definition use, admit a corpus/cache record or create training gold.

## Explicit intake and execution

```python
receipt = build_definition_use_corpus_v2(
    preparation,
    assessment_raw,
    expected_assessment_file_sha256=assessment_file_sha256,
    review_inputs=review_inputs,
    toolchain="leanprover/lean4:v4.34.1",
    lake_executable="/explicit/installed/bin/lake",
    expected_binary_sha256={
        "/explicit/installed/bin/lake": independently_expected_lake_sha256,
        "/explicit/installed/bin/lean": independently_expected_lean_sha256,
    },
    output_directory="/fresh/owned/build",
    timeout_seconds=60,
)
```

The toolchain above is an illustrative declared version, not an observation of
installed software. The binary expectations must come from trusted intake
outside the untrusted build payload. Computing and accepting new hashes from
an unknown installation establishes internal identity only. Callers acquire
the same shared validation lease used by the existing native build workflow.
The adapter does not schedule resources, obtain a lease, install software or
download a toolchain.

The typed preparation and all original assessment/review inputs are mandatory.
The closed 17-field `review_inputs` contract and separate original-file hashes
are exactly those of the preparation API. Complete regeneration retains the
source bytes, both original definitions, explicit alias, full joint AST,
native symbols, contexts, observation time/maps and dependency evidence. The
preparation manifest and its original 101-artifact/183-edge example review
manifest are not rewritten for execution.

Timeout must be finite, greater than zero and at most 60 seconds. The output
directory must be new and use ordinary directories without symlinks or parent
traversal. The independent binary map must contain exactly one absolute path
named `lake` and its sibling `lean`, with lowercase SHA256 values. After full
preparation replay, both executables must be regular executable ELF files no
larger than 64 MiB each and match those expectations before any version probe.
Stable descriptor/path identities are checked while reading.

The existing installed-toolchain owner runs two version probes, each bounded
to five seconds and 16,384 captured bytes. Both commands, matching declared
version observations and the two binary pins are rechecked. Preparation and
build-owner identities are checked again before Lake starts. An already
cancelled signal refuses before probes; cancellation is also checked before
the build and forwarded to the shared runner. A signal arriving during the
existing probe helper is observed after its bounded probes complete.

The exact command is:

```text
<independently-pinned-native-lake> --offline --no-cache build legal
```

It receives the preparation's exact nine generated files, its six ordered
`.olean` output paths, `ELAN_TOOLCHAIN` and `LEAN_NUM_THREADS=1`. The shared
runner supplies a private workspace and these limits:

| Resource | Bound |
| --- | --- |
| Wall time / CPU time | Caller timeout, at most 60 seconds each |
| Sampled process-tree resident memory | 2 GiB |
| Generated input bytes | 8 MiB |
| Workspace bytes | 128 MiB |
| Expected captured artifact files | Six |
| Each captured stream and each `.olean` | 262,144 bytes |
| Complete sealed build receipt | Common one-MiB record bound |

The runner's resident-memory guard is sampled, not a cgroup hard limit.
Its capture ceiling also applies to each artifact; larger complete `.olean`
outputs cannot qualify under this profile. A clipped UTF8 tail may re-encode
to at most two extra bytes in a truncated text observation; it is retained
verbatim and always fails qualification. The complete receipt must also fit
the common JSON depth/node/byte limits. Malformed or over-bound observations
are refused rather than filtered to fit.

## Qualification and failure evidence

Successful engineering qualification requires all of the following:

- The selected bounded-runner interface, native/kernel runtime, exact command,
  positive PID, zero exit code and `completed` termination reason.
- No timeout, cancellation, unavailability, resource exhaustion, output
  truncation, workspace limit failure or execution error, and successful
  workspace cleanup. Normal exit does not require forced process termination.
- All six expected nonempty artifact files, with no unexpected output path.
- Exactly one empty-axiom report for each of the three expected conditional
  theorems. Bare Lean messages and bounded `info: file:line:column:` framing
  are supported. Missing, duplicate, unknown, nonempty or contradictory axiom
  diagnostics refuse qualification. `sorry`, `sorryAx` and `admit` diagnostics
  also refuse qualification.
- Complete preparation/review/source replay and unchanged build owners after
  execution, plus a final exact check of both independent binary hashes.

Known bounded execution failures produce a failed receipt. Missing or empty
expected outputs remain failed observations. Unexpected paths, invalid result
types or capture-bound violations are malformed results and raise before
persisting a completed bundle. Post-run source/review or binary drift produces
a failed receipt retaining the exact project that was submitted, rather than
silently substituting regenerated inputs.

The receipt binds the preparation CID and exact manifest SHA, original review
intake commitments/status/blockers, declared toolchain, independent binary pins,
version observations, observed build-owner file pins, command/environment/
limits, complete bounded diagnostics and lifecycle state, ordered module and
theorem population, output lengths/hashes, and the derived qualification.
`lean_compilation_verified`, `conditional_proofs_verified` and
`kernel_proofs_checked` describe this conditional engineering build only.
They require actual trusted runner observations in production; authored fake
runner tests are not compiler or kernel evidence.

Pending or rejected human review can accompany this candidate engineering
build. The original preparation remains immutable with `build_eligible=false`;
its old handoff describes the earlier preparation-only stage. The new receipt
has `engineering_build_only=true` and `admission_build_eligible=false`. All
human-review, source/meaning, governing-use, semantic binding, accepted-view,
training/gold, formalized/admitted and proof-authority flags remain false even
when conditional compilation succeeds. The alias remains an assumption and
the representative lookup does not become per-occurrence lookup verification.

Only the two native binaries and their version observations are verified by
this profile. `toolchain_library_closure_verified=false`: it does not inventory
the entire installed library/distribution or attest continuously loaded code.
It supplies no cache reuse or incremental validity claim. Broader toolchain
closure and cache reuse require their separately versioned integration.

## Retained bundle and historical readback

The new output directory contains exactly:

```text
build-receipt.json
project/             # exact nine generated files + original corpus manifest
compiled/            # complete or partial known .olean outputs
```

Existing projects are never overwritten. Project files use the existing
exclusive, no-follow, descriptor-based transport. Artifact writes are likewise
exclusive and read back exactly. The receipt is written last and read back
with stable identities and closed directory population checks. An interrupted
write can leave an incomplete owned directory; existence is not completion.

`load_definition_use_build_v2(directory, preparation, assessment_raw, *,
expected_receipt_sha256, expected_assessment_file_sha256, review_inputs,
toolchain, expected_binary_sha256)` requires the separately trusted original
receipt-file SHA and the same independent preparation/binary expectations.
It performs complete preparation regeneration, closed ordinary-file readback,
exact frozen-project comparison, artifact byte/hash checks and complete receipt
reconstruction, including qualification and authority flags. It refuses altered,
extra, missing, symlinked or resealed inconsistent contents.

Historical loading does not read installed binaries, probe their versions or
execute a compiler. Binaries can be absent at readback. The receipt's external
trusted pin establishes custody of a historical observation; accepting a
self-resealed replacement from the same producer cannot establish that a
process actually ran. Changed current source/preparation producers or original
review/dependency inputs refuse replay. Failed post-run qualification bundles
retain their original bytes even when changed current inputs prevent a later
successful replay.

Actual statutory source and meaning decisions, independent legal/formal
reviews, governing use, reviewed graph/cache release and corpus/training/Lean
admission remain separate work. A real authored native integration build is
also separate evidence from this adapter's simulated-runner unit tests.
