# Private autoencoder release metadata verification

A new read-only verifier compares an already sealed private resume package with
file metadata at an explicitly supplied Hugging Face commit. It supports the
publication boundary without downloading weights. This is one prerequisite for
the future outbox consumer; it is not an upload or uncertain-outcome recovery
implementation. Native training validation remains deferred by the user.

## Implemented boundary

[`verify_private_resume_release_metadata`](../../../ipfs_datasets_py/huggingface/autoencoder_remote_metadata.py)
requires the package root, owner-selected version and variant records, outer
manifest SHA-256, expected repository, known full lowercase 40-character commit
SHA, and an injected metadata client. It strongly reopens the existing package
before contacting that client. It never chooses a mutable head or regenerates
a package, plan, model, approval or evaluation.

The client uses the installed `huggingface_hub` 0.36.2 record contract:
`ModelInfo`, `RepoFile`, `RepoFolder` and `BlobLfsInfo`. Repository metadata must
name the expected model repository and exact commit and report `private is True`.
The repository query requests only SHA and privacy expansion, avoiding the
default complete sibling inventory. Both observations, before and after the
tree inspection, use the supplied commit. Privacy is observed at query time;
Git does not attest historical repository visibility.
[Versioned SDK source](https://github.com/huggingface/huggingface_hub/blob/v0.36.2/src/huggingface_hub/hf_api.py)

Recursive tree inspection is restricted to the sealed release prefix. Every
file and internal ancestor directory must match the exact planned namespace.
Extra, missing, duplicate, conflicting or malformed records fail. The local
outer package manifest, publication plan and root model card are control files,
not additional upload operations. Their local closure is still verified.

| Remote representation | Comparison | Evidence retained |
| --- | --- | --- |
| Ordinary Git file | Remote blob SHA-1 against local `SHA1("blob " + decimal_size + NUL + bytes)` and matching size | Git blob SHA-1, explicitly not a remote file SHA-256 |
| LFS file | Remote LFS SHA-256 and both reported payload sizes against sealed local bytes | LFS payload SHA-256; pointer blob identity is separate |
| Missing digest | No identity substitution or download fallback | `verification_pending`, with an explicit missing-digest reason |

The local streaming pass also recomputes SHA-256 and compares it with the sealed
operation. This prevents an intervening local change from becoming the expected
remote identity. Git hashes include the blob header; a raw content SHA-1 is not
the expected value. LFS metadata never falls back to Git when its digest is
missing or malformed. Conflicting hashes raise rather than returning pending.
[Git object format](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects)

Local file opens reject aliases and special files. The streamed comparison
uses a nonblocking descriptor so a substituted FIFO cannot hang that read.
Final bounded namespace and exact manifest verification detects later changes
to the package, including local control files. This rechecks bytes without a
second compact-state hydration. Iterator cleanup preserves the original
verification error if cleanup also fails.

## Cost and authority

Weight reads during training remain local. This verifier runs at release
boundaries and adds local package reads, SHA-256/SHA-1 computation and remote
metadata queries. It avoids artifact downloads and a second native checkpoint
hydration, but does not claim a measured latency or memory improvement.

The existing package bounds apply: 128 files, 256 MiB per checkpoint and
512 MiB package closure. Remote iteration is limited to the expected number of
files and directories, at most 256 entries, with path-length and depth bounds.
The consumer can request at most one extra iterator item to detect overflow.
These bounds do not cap the SDK's internal HTTP response/page allocation or
provide a transport deadline; the caller must configure transport limits.

Successful receipts say `metadata_verified`. They distinguish Git SHA-1 from
LFS SHA-256, retain both private-visibility observations, and bind the commit,
release, package manifest and exact publication plan. They explicitly retain:

- `bytes_verified: false`, `remote_bytes_downloaded: 0`;
- `publication_outcome_established: false`, `publication_acknowledged: false`;
- `pointer_promoted: false`, `admitted: false`.

Metadata correspondence does not prove downloaded bytes, remote file modes,
parent ancestry, which operation created a commit, approval or model quality.
An injected fixture client is not live Hub qualification. The existing stronger
publisher verification remains unchanged; its non-LFS fallback can download
files, so it is not called here. A later consumer must enforce its declared
verification level. Requiring remote SHA-256 or byte readback cannot be satisfied
by relabeling Git SHA-1 metadata.

## Remaining publication work

The owner still needs a durable delivery adapter with repository-wide exclusion,
event lease renewal, exact approval and send-intent binding, guarded commit
submission, uncertain-response reconciliation and idempotent acknowledgement.
This verifier accepts a known commit; it does not discover or infer one after a
lost upload response. An unknown outcome must remain unresolved until separate
evidence establishes it. Pointer promotion remains a separate operation.

No native training/evaluation comparison, model upload, download, live Quack
qualification or production DuckLake activation ran for this change. The
Constitution remains unformalized and no span is marked `roundtrip_ok`. Only
`lake build <Lib>` supplies a Lean admit.

## Verification

The [combined capture](../../../workspace/test-logs/federal-corpus-audits/autoencoder-remote-metadata-20260925/combined-r1-receipt.json)
passes **235 tests in 58.59 seconds pytest / 60.815200 seconds wrapper**, with
zero failures, errors or skips. All 7,744 canonical package Python sources,
the six selected test files and the protected historical checkpoints/receipts
remained unchanged during execution. Linux seccomp denied socket and outbound
network syscalls before package imports. No live Hub client was contacted.

The [new 87 cases](../../../tests/unit/huggingface/test_autoencoder_remote_metadata.py)
cover legacy and compact packages, nested evaluation files, unordered mixed
Git/LFS observations, a local `git hash-object` oracle, all-LFS metadata,
missing digests, exact destination/privacy checks at both boundaries,
unsupported record types, wrong sizes/hashes, complete namespace matching,
bounded iteration, later-page failures, cleanup failures and local mutations.
Same-size content changes and a substituted FIFO after reopening fail before
tree inspection. Successful checks preserve package bytes, inodes, timestamps
and existing plan authority flags. Fixture metadata is explicitly simulated.

The other 148 tests cover existing package construction, strong reopening,
durable owner publication preparation, generic publisher guards and publication
profiles. This storage regression does not replace the previously deferred
native training qualification or validate a real repository. These test times
are not legal-span or bridge-on evaluation timings, and no speed claim follows.
