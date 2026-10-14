# Lossless checkpoint component storage

The optional `legal_checkpoint_components` codec stores repeated rectangular
numeric arrays once in a flat SHA256-keyed table. A typed metadata skeleton
preserves the rest of the checkpoint, including its ancestral checkpoints.
Unpacking restores the exact original canonical JSON bytes so existing model
validators can check the original state, policy, source identities and lineage.

This is a storage prototype. Nine synthetic controls pass; trained-checkpoint
round trips and actual storage savings have not yet been qualified. Existing
loaders and the class-balanced training experiment do not use this codec.

`pack_checkpoint` requires canonical checkpoint bytes and trusted checkpoint,
model-state and implementation SHA256 identities. `unpack_checkpoint` requires
those same identities plus the trusted archive SHA256. Callers must obtain these
identities from reviewed provenance rather than trusting a manifest supplied
alongside an unknown archive.

The codec preserves JSON integer/float distinctions and signed zero. It does
not cast arrays to float32 or discard repeated provenance: deduplication changes
the physical representation, while all original lineage data returns on unpack.
Arrays with at least eight numeric scalars become components; smaller arrays
remain in the typed skeleton. No external donor lookup is performed.

The format rejects missing or extra components, changed shapes or bytes,
duplicate keys, unknown token kinds, nonfinite numbers, cyclic structures and
untrusted identities. It bounds input/archive bytes, structure depth and nodes,
component count, and expanded byte size before serializing the restored result.
The codec performs no model execution, filesystem access or logic validation.

Before adopting it for trained artifacts, run a reviewed, resource-guarded
conversion of pinned checkpoints, verify restored bytes against the originals,
then use the existing model validators. Measure the total archive size and
retain the immutable legacy checkpoints and their published references.
Serialization equality supplies no evidence of legal or logical correctness.
