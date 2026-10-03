# Bounded checkpoint and model replay

The canonical autoencoder registry now reads an immutable artifact through one
bounded, non-following file descriptor. Descriptor and consumer limits precede
file reads. Root/prefix/file symlinks, nonregular files, growth, truncation and
wrong hashes refuse. Path replacement cannot substitute unverified return bytes.

Source384 generations, prior-centered generations and their feature microbatches,
model-generation corpus attachments, prior projections and resident inference
records use this reader. Projection replay now has an explicit 32 MiB limit.
Existing source, model, producer, completed-run and operation checks remain in
place. This does not migrate old producer generations or grant proof authority.

Final qualification has 148 passing tests: 127 storage/lifecycle controls,
9 resident inference controls and 12 selected source-generation controls. Actual
CPU inference, cold process replay, source-generation training and independent
Lake checks execute in their declared fixtures. The earlier source-generation
attempt skipped 12 cases because its explicit Lake variable was missing; those
skips remain alongside the successful pinned-Lake run. Earlier test generations
and their source snapshots are retained separately and not added to the count.

The bound concerns input bytes; chunk buffers, joined bytes and JSON decoding
consume additional memory. It is not a peak-RSS guarantee, CUDA qualification or
new benchmark result. No weights were uploaded or promoted.
